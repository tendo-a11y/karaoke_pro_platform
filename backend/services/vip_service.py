"""
Бизнес-логика Role 3 (VIP) для Guest App — 1:1 перенос из старого бота
(handlers/vip.py, handlers/client.py, database.py), см. отчёт по аудиту
"Role 3/4/5" перед этим шагом. Отклонения от старого поведения — только
там, где они уже были приняты решением по мастер-ТЗ раньше в этом проекте
(списание при завершении, а не при создании — services/billing_service.py).

ТЗ п.45 (постоянная идентификация гостя): VIP-идентичность БОЛЬШЕ НЕ
создаётся с нуля — ни через одобрение заявки, ни вручную KJ (старая
функция grant_vip_manually и весь механизм access_code удалены). VIP —
это всегда надстройка над уже существующим постоянным профилем гостя
(см. models.py::GuestAccount, services/guest_account_service.py):
telegram_user_id нового VipClient всегда берётся из GuestAccount гостя,
который подаёт заявку, а не генерируется заново — см. approve_vip_request.

Функции здесь намеренно НЕ трогают HTTP/JWT — это забота routes/guest.py и
routes/kj.py, чтобы логику можно было одинаково тестировать и переиспользовать.
"""
import uuid
from decimal import Decimal

from extensions import db
from models import (
    Favorite,
    Order,
    Service,
    STATUS_PENDING,
    STATUS_QUEUED,
    STATUS_VIP_REQUEST_APPROVED,
    STATUS_VIP_REQUEST_PENDING,
    STATUS_VIP_REQUEST_REJECTED,
    Transaction,
    TX_TYPE_MANUAL_DEBIT,
    TX_TYPE_TOPUP,
    VipClient,
    VipRequest,
)
from services import guest_account_service

# Активные = ещё не сыгранные и не отклонённые — соответствует старому
# `status IN ('pending','waiting')` (там 'waiting' = ожидает подтверждения
# KJ, 'pending' = подтверждён и в очереди). Здесь два эквивалентных статуса
# — STATUS_PENDING (ждёт KJ) и STATUS_QUEUED (уже в очереди VirtualDJ).
_ACTIVE_ORDER_STATUSES = (STATUS_PENDING, STATUS_QUEUED)


def get_vip_client(club_id: int, guest_id: int) -> VipClient | None:
    return VipClient.query.filter_by(club_id=club_id, telegram_user_id=guest_id).first()


def list_vip_clients(club_id: int) -> list[VipClient]:
    """
    Block D KJ Pro — старый бот находил VIP-клиента только по точному
    Telegram ID/username через client_search (kj.py:596-665), т.к. у
    каждого был "настоящий" аккаунт. У Guest App VIP-идентичность — тот
    же постоянный номер, что у GuestAccount (см. models.py), искать по
    нему пока негде на фронтенде — поэтому здесь простой список всех VIP
    клуба (в реальном клубе их немного), а не поиск по идентификатору.
    """
    return (
        VipClient.query
        .filter_by(club_id=club_id)
        .order_by(VipClient.added_at.desc())
        .all()
    )


def count_active_orders(club_id: int, guest_id: int) -> int:
    """ТЗ Role 3/4/5 аудит, п.6 — лимит MAX_ACTIVE_SONGS_PER_GUEST считается
    per-гость per-клуб (в старом коде — per-гость per-стол; здесь без
    per-стола, т.к. Guest App не хранит групповые столы — см. отчёт, п.13-15,
    NOT DONE в этом шаге)."""
    return (
        Order.query
        .filter(
            Order.club_id == club_id,
            Order.telegram_user_id == guest_id,
            Order.status.in_(_ACTIVE_ORDER_STATUSES),
        )
        .count()
    )


# --- Заявка на VIP (старое: handlers/client.py::request_vip_status, п.8А) ---

class VipRequestCreateResult:
    def __init__(self, request=None, outcome=None):
        self.request = request
        self.outcome = outcome  # requires_google_link | ok


def create_vip_request(club_id: int, guest_id: int, table_no) -> VipRequestCreateResult:
    """
    ТЗ п.45: заявку может подать только гость с уже существующим постоянным
    профилем (Role 4) — иначе при одобрении опять пришлось бы создавать
    VIP-идентичность "из ничего", чего решено больше не делать (см. модуль
    docstring и approve_vip_request ниже).
    """
    if guest_account_service.get_by_guest_id(club_id, guest_id) is None:
        return VipRequestCreateResult(outcome="requires_google_link")

    request = VipRequest(club_id=club_id, telegram_user_id=guest_id, table_no=table_no)
    db.session.add(request)
    db.session.commit()
    return VipRequestCreateResult(request=request, outcome="ok")


def get_pending_vip_request(club_id: int, guest_id: int) -> VipRequest | None:
    return (
        VipRequest.query
        .filter_by(club_id=club_id, telegram_user_id=guest_id, status=STATUS_VIP_REQUEST_PENDING)
        .order_by(VipRequest.created_at.desc())
        .first()
    )


class VipRequestResult:
    def __init__(self, request=None, vip_client=None, outcome=None):
        self.request = request
        self.vip_client = vip_client
        self.outcome = outcome  # not_found | forbidden | already_decided | approved | rejected


def approve_vip_request(request_id: int, kj) -> VipRequestResult:
    """
    Старое: handlers/kj.py::vip_request_approve — одобряет KJ своего клуба,
    создаёт vip_clients с cashback_percent=0 (в старом коде тоже 0 через
    этот путь — изменить кэшбэк отдельно, как и в старом боте через
    client_commission_manage/PUT .../cashback ниже).

    ТЗ п.45: telegram_user_id нового VipClient — это telegram_user_id
    GuestAccount заявителя, а НЕ новый случайный номер. Это гарантированно
    существует, потому что create_vip_request (routes/guest.py::request_vip)
    не даёт подать заявку без уже привязанного постоянного профиля — см.
    docstring VipRequestCreateResult выше. Отличие от старого бота
    минимально теперь: там VIP тоже был равен уже существующему постоянному
    (Telegram) идентификатору, а не создавался с нуля — здесь то же самое,
    только постоянство обеспечивает GuestAccount, а не сам факт быть
    Telegram-пользователем.
    """
    request = db.session.get(VipRequest, request_id)
    if request is None:
        return VipRequestResult(outcome="not_found")
    if request.club_id != kj.club_id:
        return VipRequestResult(outcome="forbidden")
    if request.status != STATUS_VIP_REQUEST_PENDING:
        return VipRequestResult(request=request, outcome="already_decided")

    account = guest_account_service.get_by_guest_id(request.club_id, request.telegram_user_id)
    if account is None:
        # Не должно происходить при нормальном потоке (заявку нельзя было
        # подать без профиля) — но если профиль исчез между подачей заявки
        # и одобрением, честно отказываем, а не создаём личность из ничего.
        return VipRequestResult(request=request, outcome="guest_account_missing")

    request.status = STATUS_VIP_REQUEST_APPROVED
    request.decided_by = kj.id
    from datetime import datetime, timezone
    request.decided_at = datetime.now(timezone.utc)

    vip_client = VipClient(
        club_id=request.club_id,
        telegram_user_id=account.telegram_user_id,
        cashback_percent=0,
    )
    db.session.add(vip_client)
    db.session.commit()

    return VipRequestResult(request=request, vip_client=vip_client, outcome="approved")


def reject_vip_request(request_id: int, kj) -> VipRequestResult:
    request = db.session.get(VipRequest, request_id)
    if request is None:
        return VipRequestResult(outcome="not_found")
    if request.club_id != kj.club_id:
        return VipRequestResult(outcome="forbidden")
    if request.status != STATUS_VIP_REQUEST_PENDING:
        return VipRequestResult(request=request, outcome="already_decided")

    request.status = STATUS_VIP_REQUEST_REJECTED
    request.decided_by = kj.id
    from datetime import datetime, timezone
    request.decided_at = datetime.now(timezone.utc)
    db.session.commit()
    return VipRequestResult(request=request, outcome="rejected")


# --- Финансы/история транзакций (старое: handlers/vip.py::vip_finances,
# database.py::get_user_transactions, аудит-отчёт по Finance/cashback
# history) — старый бот показывал 4 отдельные секции по типу (пополнения/
# оплата заказов/возвраты/кэшбэк) с промежуточными итогами по каждой,
# каждая — отдельным запросом в БД. Здесь по решению — единая
# хронологическая лента одним запросом (мобильный React-список, не
# Telegram-сообщение с посекционным форматированием). Ручные корректировки
# KJ (topup/manual_debit, прошлый шаг) гостю тоже видны — в старом боте их
# не было видно вообще вообще (баг №7 прошлого аудита, там же исправлено на
# уровне записи, здесь — на уровне показа). ---

def list_transactions(club_id: int, guest_id: int, days: int | None = None, limit: int = 200) -> list[Transaction]:
    """
    Старое: get_user_transactions делал отдельный запрос на каждый из 4
    типов без общего лимита — при активном госте за "месяц" сообщение в
    Telegram могло превысить ~4096 символов и не отправиться (баг №8
    прошлого аудита). Здесь один запрос по всем типам сразу, с лимитом —
    последние `limit` операций, а не "всё за период" без границ.
    """
    query = Transaction.query.filter_by(club_id=club_id, telegram_user_id=guest_id)
    if days is not None:
        from datetime import datetime, timedelta, timezone
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        query = query.filter(Transaction.created_at >= cutoff)
    return query.order_by(Transaction.created_at.desc()).limit(limit).all()


# --- Ручная корректировка баланса VIP (Role 2/KJ, старое: handlers/kj.py
# ::balance_add/balance_sub/balance_set, database.py::update_vip_balance/
# set_vip_balance) — гость просит пополнение УСТНО, в баре, поэтому здесь
# нет цифровой заявки гость→KJ (в отличие от VIP-заявки на членство выше) —
# только прямое действие KJ над уже существующим VIP-счётом. ---

class BalanceAdjustResult:
    def __init__(self, vip_client=None, transaction=None, outcome=None):
        self.vip_client = vip_client
        self.transaction = transaction
        self.outcome = outcome  # not_found | forbidden | validation_error | ok


def _apply_balance_delta(vip_client: VipClient, delta, tx_type: str, description: str) -> Transaction:
    """
    Общий примитив для начисления/списания/установки — атомарный
    SQL UPDATE (Query.update()), тот же паттерн, что и в
    billing_service.py::charge_at_completion, чтобы не терять обновление
    при двух почти одновременных ручных корректировках одного счёта (гонка,
    аналогичная старому багу с двойным одобрением, но применённая здесь на
    новый, ранее не защищённый путь).

    idempotency_key у Transaction обязателен и уникален по схеме, но здесь
    это НЕ повторно доставляемое внешнее событие (как завершение песни из
    VirtualDJ History) — это разовое ручное действие живого человека,
    поэтому ключ просто гарантирует уникальность строки, а не служит
    дедупликацией конкретного бизнес-события (защита от двойного клика —
    забота фронтенда/кнопки, не бэкенда).
    """
    db.session.query(VipClient).filter(VipClient.id == vip_client.id).update(
        {VipClient.balance: VipClient.balance + delta},
        synchronize_session=False,
    )
    transaction = Transaction(
        club_id=vip_client.club_id,
        telegram_user_id=vip_client.telegram_user_id,
        order_id=None,
        amount=abs(delta),
        type=tx_type,
        description=description,
        idempotency_key=f"manual_adjust:{uuid.uuid4()}",
    )
    db.session.add(transaction)
    db.session.commit()
    db.session.refresh(vip_client)
    return transaction


def topup_balance(club_id: int, vip_client_id: int, amount: Decimal) -> BalanceAdjustResult:
    """➕ Начислить (старое: handlers/kj.py::balance_add). amount должен
    быть строго положительным — проверка на уровне вызывающего кода
    (routes/kj.py), сюда попадает уже провалидированное значение."""
    vip_client = db.session.get(VipClient, vip_client_id)
    if vip_client is None:
        return BalanceAdjustResult(outcome="not_found")
    if vip_client.club_id != club_id:
        return BalanceAdjustResult(outcome="forbidden")

    tx = _apply_balance_delta(
        vip_client, amount, TX_TYPE_TOPUP,
        f"Начисление KJ: +{amount}",
    )
    return BalanceAdjustResult(vip_client=vip_client, transaction=tx, outcome="ok")


def debit_balance(club_id: int, vip_client_id: int, amount: Decimal) -> BalanceAdjustResult:
    """➖ Списать (старое: handlers/kj.py::balance_sub). Сознательно БЕЗ
    защиты от ухода в минус — в старом коде такой защиты тоже не было
    (аудит-отчёт по VIP-пополнению, найденный баг №2: "нет floor на нулевой
    баланс нигде в примитивах изменения баланса"), а не добавлена она
    сейчас, чтобы не переносить будто-бы-старое поведение с добавленной
    новой бизнес-логикой без отдельного решения."""
    vip_client = db.session.get(VipClient, vip_client_id)
    if vip_client is None:
        return BalanceAdjustResult(outcome="not_found")
    if vip_client.club_id != club_id:
        return BalanceAdjustResult(outcome="forbidden")

    tx = _apply_balance_delta(
        vip_client, -amount, TX_TYPE_MANUAL_DEBIT,
        f"Списание KJ: -{amount}",
    )
    return BalanceAdjustResult(vip_client=vip_client, transaction=tx, outcome="ok")


def set_balance(club_id: int, vip_client_id: int, new_balance: Decimal) -> BalanceAdjustResult:
    """🔄 Установить (старое: handlers/kj.py::balance_set) — прямое
    назначение значения, а не относительное изменение. Реализовано через
    тот же атомарный примитив: дельта считается от текущего значения на
    момент вызова (небольшое окно гонки между чтением old_balance и записью
    делты неизбежно при "установить абсолютное значение" — это то же самое
    ограничение, что и в старом коде, где set_vip_balance тоже был плоским
    UPDATE без версионирования)."""
    vip_client = db.session.get(VipClient, vip_client_id)
    if vip_client is None:
        return BalanceAdjustResult(outcome="not_found")
    if vip_client.club_id != club_id:
        return BalanceAdjustResult(outcome="forbidden")

    delta = new_balance - vip_client.balance
    tx_type = TX_TYPE_TOPUP if delta >= 0 else TX_TYPE_MANUAL_DEBIT
    tx = _apply_balance_delta(
        vip_client, delta, tx_type,
        f"Установка баланса KJ: {vip_client.balance} → {new_balance}",
    )
    return BalanceAdjustResult(vip_client=vip_client, transaction=tx, outcome="ok")


# --- Избранное (старое: database.py::add/remove/get_favorites, handlers/*::order_favorite, п.3) ---

def add_favorite(club_id: int, guest_id: int, song_title: str, artist, service_id) -> Favorite:
    """Старый код не проверяет дубликаты (см. отчёт, п.3) — сохраняем то же
    самое поведение: можно добавить одну и ту же песню в избранное дважды."""
    favorite = Favorite(
        club_id=club_id, telegram_user_id=guest_id,
        song_title=song_title, artist=artist, service_id=service_id,
    )
    db.session.add(favorite)
    db.session.commit()
    return favorite


def list_favorites(club_id: int, guest_id: int) -> list[Favorite]:
    return (
        Favorite.query
        .filter_by(club_id=club_id, telegram_user_id=guest_id)
        .order_by(Favorite.added_at.desc())
        .all()
    )


class FavoriteActionResult:
    def __init__(self, favorite=None, order=None, outcome=None):
        self.favorite = favorite
        self.order = order
        self.outcome = outcome  # not_found | forbidden | limit_reached | ok


def remove_favorite(club_id: int, guest_id: int, favorite_id: int) -> FavoriteActionResult:
    favorite = db.session.get(Favorite, favorite_id)
    if favorite is None:
        return FavoriteActionResult(outcome="not_found")
    if favorite.club_id != club_id or favorite.telegram_user_id != guest_id:
        # Старый код вообще не проверял владельца (см. отчёт, п.3) — здесь
        # проверяем, т.к. Guest App-эндпоинт получает club_id/guest_id из
        # проверенного токена, а не доверяет чужому favorite_id "потому что
        # так пришло с фронтенда" — это не новая бизнес-логика, а обычная
        # серверная авторизация запроса (как и везде в этом backend).
        return FavoriteActionResult(outcome="forbidden")
    db.session.delete(favorite)
    db.session.commit()
    return FavoriteActionResult(outcome="ok")


def reorder_favorite(club_id: int, guest_id: int, table_no, guest_type: str, favorite_id: int,
                      max_active: int) -> FavoriteActionResult:
    """
    Старое: handlers/client.py::fav_reorder / handlers/vip.py::fav_reorder
    (п.3-4). Лимит активных песен проверяется как и в старом коде — ДО
    создания заказа. Проверка баланса ПЕРЕД созданием заказа сюда
    сознательно НЕ перенесена: в новой архитектуре списание происходит при
    завершении песни (services/billing_service.py::charge_at_completion,
    решение мастер-ТЗ, принятое раньше в этом проекте), а не при создании,
    поэтому "хватит ли баланса сейчас" больше не тот вопрос, который нужно
    задавать в момент заказа — баланс проверяется/списывается позже, в
    момент реального завершения песни.
    """
    favorite = db.session.get(Favorite, favorite_id)
    if favorite is None:
        return FavoriteActionResult(outcome="not_found")
    if favorite.club_id != club_id or favorite.telegram_user_id != guest_id:
        return FavoriteActionResult(outcome="forbidden")

    if count_active_orders(club_id, guest_id) >= max_active:
        return FavoriteActionResult(favorite=favorite, outcome="limit_reached")

    order = Order(
        telegram_user_id=guest_id,
        club_id=club_id,
        table_no=table_no,
        guest_type=guest_type,
        song_title=favorite.song_title,
        artist=favorite.artist,
        service_id=favorite.service_id,
        source="guest",
        channel="webapp",
    )
    db.session.add(order)
    db.session.commit()
    return FavoriteActionResult(favorite=favorite, order=order, outcome="ok")
