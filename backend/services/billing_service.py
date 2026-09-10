"""
Списание VIP-баланса и начисление кэшбэка в момент завершения песни
(новое мастер-ТЗ §12) — заменяет старую модель "оплата при создании заказа".

Старое поведение (для сравнения, см. корневой database.py и
handlers/kj.py::order_complete_confirmed в исходном боте):
  - при СОЗДАНИИ заказа: charge_vip_for_order() списывает service.price
    с баланса VIP-клиента (если клиент VIP и услуга не бесплатная).
  - при ЗАВЕРШЕНИИ заказа: apply_cashback() начисляет кэшбэк
    (service.price * cashback_percent / 100), если у VIP есть
    cashback_percent > 0.
  Защита от повторной обработки была ad hoc: перед вставкой строки в
  transactions делался SELECT COUNT(*) ... WHERE order_id=? AND type=?
  (read-then-write — теоретическая гонка при параллельных вызовах).

Новое поведение: оба шага (списание + кэшбэк) происходят ОДНОВРЕМЕННО в
момент завершения песни — потому что момент создания заказа и момент
завершения теперь может разделять произвольное время, а событие
завершения приходит в первую очередь из VirtualDJ History (ТЗ §37-38),
источника, который может прислать одно и то же событие повторно
(переподключение моста, повторный опрос истории), плюс есть ручной
fallback от KJ (§14). Поэтому:
  - защита от двойной обработки — не read-then-write, а уникальный индекс
    на Transaction.idempotency_key: вторая попытка обработать то же
    завершение падает на констрейнте в БД, а не проскакивает из-за гонки;
  - изменение баланса VIP делается атомарным SQL UPDATE (balance = balance
    +/- X прямо в SQL, через Query.update()), а не через
    read-modify-write объекта в Python — по той же причине, по которой в
    этом проекте статусы заказов меняются через CAS
    (services/vdj_service.py::confirm_order), а не read-then-save.
"""
from decimal import Decimal

from sqlalchemy.exc import IntegrityError

from extensions import db
from models import (
    Order,
    Service,
    VipClient,
    Transaction,
    TX_TYPE_ORDER_PAYMENT,
    TX_TYPE_CASHBACK,
)


class ChargeResult:
    """
    Итог обработки charge_at_completion — для логирования, тестов и
    будущего API-ответа. Не бросает исключений на "нормальные" причины
    ничего-не-делать (гость не VIP, услуга бесплатная и т.п.) — это не
    ошибки, а штатные исходы; skipped_reason различает их для вызывающего
    кода/логов.
    """

    def __init__(self, charged=False, charge_amount=None, cashback_amount=None,
                 skipped_reason=None, already_processed=False):
        self.charged = charged
        self.charge_amount = charge_amount
        self.cashback_amount = cashback_amount
        self.skipped_reason = skipped_reason
        self.already_processed = already_processed

    def __repr__(self):
        return (
            f"ChargeResult(charged={self.charged}, charge_amount={self.charge_amount}, "
            f"cashback_amount={self.cashback_amount}, skipped_reason={self.skipped_reason!r}, "
            f"already_processed={self.already_processed})"
        )


def charge_at_completion(order: Order) -> ChargeResult:
    """
    Идемпотентно списывает стоимость услуги и начисляет кэшбэк VIP-гостю
    при завершении песни (ТЗ §12). Вызывается из логики обработки
    завершения (VirtualDJ History-детект §37-38 или ручное завершение KJ
    §14 — сама эта интеграция ещё не сделана, это отдельный шаг). Функция
    сама по себе НЕ меняет order.status — только деньги.

    Правила (сохранены из старой бизнес-логики один в один, см. docstring
    модуля):
      - если у заказа не выбрана услуга (order.service_id is None) —
        списывать нечего, no-op. На этом шаге НИ ОДИН эндпоинт создания
        заказа ещё не проставляет service_id (Guest App с выбором тарифа
        не реализован) — это ожидаемый штатный случай, а не ошибка;
      - если услуга бесплатная (service.is_free) — списание и кэшбэк не
        производятся;
      - если гость не VIP (order.guest_type != "vip") или у него нет
        VIP-счёта в этом клубе — списание и кэшбэк не производятся
        (обычные гости не имеют баланса в приложении);
      - кэшбэк начисляется только если vip.cashback_percent > 0.

    НЕ проверяется достаточность баланса перед списанием (баланс может
    уйти в минус) — это поведение один в один унаследовано от старой
    системы (database.py::update_vip_balance просто вычитает без
    проверки). Если для новой системы это нежелательно — отдельное
    решение, молча не меняю в рамках этого шага.
    """
    if order.service_id is None:
        return ChargeResult(skipped_reason="no_service_id")

    service = db.session.get(Service, order.service_id)
    if service is None or service.is_free:
        return ChargeResult(skipped_reason="free_or_missing_service")

    if order.guest_type != "vip":
        return ChargeResult(skipped_reason="not_vip")

    vip = (
        VipClient.query
        .filter_by(club_id=order.club_id, telegram_user_id=order.telegram_user_id)
        .first()
    )
    if vip is None:
        return ChargeResult(skipped_reason="no_vip_account")

    charge_amount = service.price
    charge_key = f"completion:{order.id}"

    # Быстрая проверка "уже обработано" — не единственная защита (см. ниже
    # try/except при commit), а просто способ не гонять лишний SQL/лог на
    # подавляющем большинстве повторных вызовов, которые не гонка, а просто
    # повторная доставка одного и того же события завершения.
    existing_charge = Transaction.query.filter_by(idempotency_key=charge_key).first()
    if existing_charge is not None:
        return ChargeResult(already_processed=True, charge_amount=existing_charge.amount)

    cashback_amount = None
    if vip.cashback_percent and vip.cashback_percent > 0:
        cashback_amount = (charge_amount * vip.cashback_percent / Decimal(100)).quantize(Decimal("0.01"))

    net_balance_change = -charge_amount + (cashback_amount or Decimal("0"))

    # Атомарный UPDATE ... SET balance = balance + :delta — исключает
    # потерянное обновление при двух завершениях одного и того же VIP-гостя
    # почти одновременно (в отличие от чтения vip.balance в Python и записи
    # изменённого значения обратно).
    db.session.query(VipClient).filter(VipClient.id == vip.id).update(
        {VipClient.balance: VipClient.balance + net_balance_change},
        synchronize_session=False,
    )

    db.session.add(Transaction(
        club_id=order.club_id,
        telegram_user_id=order.telegram_user_id,
        order_id=order.id,
        amount=charge_amount,
        type=TX_TYPE_ORDER_PAYMENT,
        description=f"Оплата заказа #{order.id}: {order.song_title}",
        idempotency_key=charge_key,
    ))

    if cashback_amount is not None:
        db.session.add(Transaction(
            club_id=order.club_id,
            telegram_user_id=order.telegram_user_id,
            order_id=order.id,
            amount=cashback_amount,
            type=TX_TYPE_CASHBACK,
            description=f"Кэшбэк за заказ #{order.id}: {order.song_title}",
            idempotency_key=f"cashback:{order.id}",
        ))

    try:
        db.session.commit()
    except IntegrityError:
        # Настоящая защита от гонки: параллельный вызов уже вставил строку
        # с этим idempotency_key между нашей проверкой и коммитом —
        # уникальный индекс в БД не дал вставить вторую. Откатываем всё
        # (включая UPDATE баланса) и считаем операцию уже обработанной.
        db.session.rollback()
        existing_charge = Transaction.query.filter_by(idempotency_key=charge_key).first()
        return ChargeResult(
            already_processed=True,
            charge_amount=existing_charge.amount if existing_charge else None,
        )

    return ChargeResult(charged=True, charge_amount=charge_amount, cashback_amount=cashback_amount)
