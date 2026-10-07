"""
Закрытие группового стола по инициативе гостя-админа (запрос пользователя
2026-09-27) — см. подробный докстринг models.TableCloseRequest про то, чем
это отличается от guest_status_service.close_table и почему подтверждение
здесь обязательно чинит корневую причину "зависшего" группового стола
(TableGroup без этого не имеет вообще никакого способа освободиться, если
прежняя компания просто ушла, не нажав ни одной кнопки).

Поток: гость-админ -> POST /api/guest/table-group/request-close
(request_close) -> заявка видна KJ Panel (list_pending, плюс сокет-событие
table_close_request_created, по образцу order_change_request_created) ->
KJ подтверждает/отклоняет (approve_request/reject_request). При approve:
  1. считаем чек по ещё живым данным (_build_receipt) — только за ЭТУ
     сессию стола (с TableGroup.created_at), только реально сыгранные
     песни (решения пользователя 2026-09-27);
  2. автоматически снимаем ещё непроигранные заказы стола (решение
     пользователя — используем ту же логику, что и в существующем
     guest_status_service.close_table, services/vdj_service.py::
     close_table_orders);
  3. удаляем TableGroup/TableGroupMember/TableJoinRequest — это и есть
     собственно "освобождение стола" для следующей компании.

ОБНОВЛЕНО (запрос пользователя 2026-09-30, полная отмена кнопки "Готово"):
шаг 2 раньше означал "автоматически снимаем ещё непроигранные заказы
стола" (close_table_orders -> STATUS_REJECTED) — то есть в чек попадали
ТОЛЬКО заказы, которые кто-то явно пометил сыгранными. Теперь наоборот:
ЛЮБОЙ заказ этой сессии стола, который не был отклонён кнопкой "Удалить"
(STATUS_REJECTED), при закрытии стола засчитывается как сыгранный — см.
complete_table_orders ниже и правило дословно от пользователя в её
докстринге. Кнопки "Готово" в KJ Panel больше нет вообще — деньги с VIP
списываются этим же шагом одной суммой при закрытии стола, а не по
каждой песне отдельно (services/billing_service.py::charge_at_completion
— та же самая функция, просто вызывается теперь отсюда для всех заказов
стола сразу в момент закрытия, а не по одному за раз по кнопке "Готово").
"""
from datetime import datetime, timedelta, timezone

from extensions import db
from models import (
    Club,
    GuestAccount,
    Order,
    Service,
    STATUS_COMPLETED,
    STATUS_REJECTED,
    STATUS_TABLE_CLOSE_APPROVED,
    STATUS_TABLE_CLOSE_PENDING,
    STATUS_TABLE_CLOSE_REJECTED,
    TableCloseRequest,
    TableGroup,
    TableGroupMember,
    TableJoinRequest,
    Transaction,
    TX_TYPE_ORDER_PAYMENT,
)
from services import billing_service, guest_status_service, table_group_service
from services.table_board_service import ACTIVE_TABLE_STATUSES, get_table_capacity, partition_table_orders
from sockets import emit_table_close_request_created, emit_table_close_request_decided


def _utcnow():
    return datetime.now(timezone.utc)


class RequestCloseResult:
    """outcome: "forbidden" (не админ стола) | "already_pending" | "ok"."""

    def __init__(self, outcome, request=None):
        self.outcome = outcome
        self.request = request


def get_pending_for_table(club_id: int, table_no: int) -> TableCloseRequest | None:
    return (
        TableCloseRequest.query
        .filter_by(club_id=club_id, table_no=table_no, status=STATUS_TABLE_CLOSE_PENDING)
        .first()
    )


def request_close(club_id: int, table_no: int, guest_id: int) -> RequestCloseResult:
    """
    Вызывается только текущим админом группового стола — проверка та же,
    что и у остальных admin-only действий в table_group_service (kick/
    transfer): сверяем guest_id с TableGroup.admin_guest_id, а не доверяем
    значению из токена. Повторный вызов, пока предыдущая заявка ещё не
    решена, возвращает ту же самую заявку, а не создаёт дубликат — гость
    может один раз случайно/повторно нажать кнопку, не насоздавав KJ
    десяток одинаковых уведомлений.
    """
    group = table_group_service.get_group(club_id, table_no)
    if group is None or group.admin_guest_id != guest_id:
        return RequestCloseResult(outcome="forbidden")

    existing = get_pending_for_table(club_id, table_no)
    if existing is not None:
        return RequestCloseResult(outcome="already_pending", request=existing)

    req = TableCloseRequest(club_id=club_id, table_no=table_no, requested_by_guest_id=guest_id)
    db.session.add(req)
    db.session.commit()
    emit_table_close_request_created(req)
    return RequestCloseResult(outcome="ok", request=req)


def list_pending(club_id: int) -> list[TableCloseRequest]:
    return (
        TableCloseRequest.query
        .filter_by(club_id=club_id, status=STATUS_TABLE_CLOSE_PENDING)
        .order_by(TableCloseRequest.created_at.asc())
        .all()
    )


def _build_receipt(club_id: int, table_no: int, since) -> dict:
    """
    Чек только за эту сессию стола (created_at этого TableGroup, решение
    пользователя 2026-09-27 — не за весь вечер, стол мог до этого занимать
    кто-то другой и уже закрыться штатно) и только реально сыгранные песни
    (STATUS_COMPLETED) — единственное уже существующее в проекте
    определение "что считается оплатой", см. services/billing_service.py::
    charge_at_completion ("деньги начисляются только за реально сыгранную и
    отмеченную 'Готово' песню, а не за отменённые из-за ухода гостей").

    Заказы без выбранной услуги (service_id is None — Guest App с выбором
    тарифа пока не везде подключён, см. докстринг Order.service_id)
    попадают в отдельную категорию "Без категории" с ценой 0, а не
    отбрасываются — иначе "количество песен" в чеке разошлось бы с тем, что
    гость видел в "Моих заказах".

    ДОБАВЛЕНО (запрос пользователя 2026-09-28, "VIP и обычный гость за одним
    столом"): VIP платит за свою песню СРАЗУ при "Готово" — списание с его
    баланса происходит в момент завершения (billing_service.
    charge_at_completion), задолго до закрытия стола. Раньше чек на закрытии
    просто складывал стоимость ВСЕХ сыгранных песен стола в один "total" —
    для стола с одними обычными гостями это верно (никто ещё не платил), но
    для стола, где сидели и VIP, и обычные гости, получалось, что VIP как бы
    просили оплатить его песни ЕЩЁ РАЗ прямо на столе, поверх уже списанного
    с баланса. Теперь чек разбит по каждому гостю ("guests": сколько песен,
    на какую сумму, оплачено ли уже) и считает ДВЕ суммы:
      - "total" — честная сумма чека за весь стол, всех гостей, для отчёта;
      - "payable_total" — сколько реально нужно собрать на месте (наличными/
        картой) — то, что ещё не списано автоматически.
    "Оплачено" определяется не по guest_type/VIP-статусу самому по себе (VIP
    мог не иметь VIP-счёта в клубе, услуга могла быть бесплатной — см. все
    ветки skipped_reason в charge_at_completion, тогда фактического списания
    не было бы, хотя гость и VIP), а по реальному наличию строки Transaction
    с TX_TYPE_ORDER_PAYMENT для этого заказа — она появляется ТОЛЬКО когда
    charge_at_completion реально списал деньги, это и есть источник истины.
    """
    orders = (
        Order.query
        .filter(
            Order.club_id == club_id,
            Order.table_no == table_no,
            Order.status == STATUS_COMPLETED,
            Order.created_at >= since,
        )
        .all()
    )

    service_ids = {o.service_id for o in orders if o.service_id is not None}
    services_by_id = {}
    if service_ids:
        services_by_id = {s.id: s for s in Service.query.filter(Service.id.in_(service_ids)).all()}

    order_ids = [o.id for o in orders]
    paid_order_ids = set()
    if order_ids:
        paid_order_ids = {
            row[0] for row in
            db.session.query(Transaction.order_id)
            .filter(Transaction.order_id.in_(order_ids), Transaction.type == TX_TYPE_ORDER_PAYMENT)
            .all()
        }

    guest_ids = {o.telegram_user_id for o in orders}
    accounts_by_guest = {}
    if guest_ids:
        accounts_by_guest = {
            a.telegram_user_id: a
            for a in GuestAccount.query.filter(
                GuestAccount.club_id == club_id, GuestAccount.telegram_user_id.in_(guest_ids),
            ).all()
        }

    categories = {}
    guests = {}
    total = 0.0
    payable_total = 0.0
    for order in orders:
        service = services_by_id.get(order.service_id) if order.service_id else None
        name = service.name if service is not None else "Без категории"
        price = float(service.price) if service is not None and service.price is not None else 0.0
        bucket = categories.setdefault(name, {"category": name, "count": 0, "price": price, "sum": 0.0})
        bucket["count"] += 1
        bucket["sum"] += price
        total += price

        paid = order.id in paid_order_ids
        if not paid:
            payable_total += price

        account = accounts_by_guest.get(order.telegram_user_id)
        guest_bucket = guests.setdefault(order.telegram_user_id, {
            "guest_id": str(order.telegram_user_id),
            "display_name": account.display_name if account else None,
            "guest_type": order.guest_type,
            "count": 0,
            "sum": 0.0,
            "paid": True,
        })
        guest_bucket["count"] += 1
        guest_bucket["sum"] += price
        if not paid:
            guest_bucket["paid"] = False

    return {
        "table_no": table_no,
        "song_count": len(orders),
        "categories": list(categories.values()),
        "guests": list(guests.values()),
        "total": total,
        "payable_total": payable_total,
    }


def _session_since(club_id: int, table_no: int, group_created_at):
    """
    ДОБАВЛЕНО (2026-10, запрос пользователя "стол закрыт — значит песен не
    должно быть никаких вообще"): если за столом остались активные песни,
    заказанные ещё до того, как нынешняя компания села (гость вставал и
    садился снова), они тоже закрываются и попадают в чек — после закрытия
    стола на нём не остаётся ни одной активной песни.
    """
    earliest = (
        db.session.query(db.func.min(Order.created_at))
        .filter(
            Order.club_id == club_id,
            Order.table_no == table_no,
            Order.status.in_(ACTIVE_TABLE_STATUSES),
        )
        .scalar()
    )
    if earliest is not None and (group_created_at is None or earliest < group_created_at):
        return earliest
    return group_created_at


def complete_table_orders(club_id: int, table_no: int, since) -> list[Order]:
    """
    ЗАМЕНЯЕТ старый close_table_orders (массовое STATUS_REJECTED) в потоке
    закрытия стола С ЧЕКОМ (запрос пользователя 2026-09-30, полная отмена
    кнопки "Готово" — см. models.py и billing_service.py). close_table_orders
    сам по себе остаётся и продолжает использоваться там, где чек не нужен
    (guest_status_service.close_table — закрытие карточки гостя без чека).

    Правило дословно от пользователя: "если кнопка Удалить на песне не
    была нажата и при этом идёт закрытие стола, то считаются в чек все не
    удалённые песни". То есть ЛЮБОЙ заказ этой сессии стола (created_at >=
    since, тот же смысл since, что и в _build_receipt выше — только эта
    сессия, а не весь предыдущий оборот стола), который не в STATUS_REJECTED
    (кнопка "Удалить" не нажималась), при закрытии стола становится
    STATUS_COMPLETED — независимо от того, был ли он вообще принят KJ,
    стоял в очереди или уже играл. Уже STATUS_COMPLETED заказы (не должно
    быть новых после отмены "Готово", но на всякий случай — старые данные)
    пропускаем, чтобы не пытаться списать деньги повторно.

    Сперва переводим статусы и коммитим, и только ПОСЛЕ ЭТОГО вызываем
    billing_service.charge_at_completion по каждому заказу — списание VIP
    ищет заказ по актуальному статусу/данным в БД и создаёт свою отдельную
    транзакцию с защитой от двойной обработки (idempotency_key), так что
    порядок "сначала все статусы, потом все списания" не даёт разным
    заказам одного гостя мешать друг другу, а сбой на одном заказе не
    оставляет остальные непомеченными сыгранными.
    """
    # ДОБАВЛЕНО (2026-10, вместе с подъёмом лимита заказов гостя до 12 —
    # см. config.py::MAX_ACTIVE_SONGS_PER_GUEST): заказы, которые к моменту
    # закрытия стола всё ещё ждали места сверх вместимости стола (KJ их
    # вообще не видел на карточке и не мог ни спеть, ни удалить), в чек не
    # попадают — они отклоняются, а не засчитываются сыгранными. Иначе
    # гость заплатил бы за песни, до которых очередь так и не дошла.
    waiting_ids = set()
    club = db.session.get(Club, club_id)
    if club is not None:
        _visible, waiting = partition_table_orders(club_id, table_no, get_table_capacity(club))
        rejected_at = datetime.now(timezone.utc)
        for waiting_order in waiting:
            waiting_order.status = STATUS_REJECTED
            waiting_order.rejected_at = rejected_at
            waiting_ids.add(waiting_order.id)

    orders = (
        Order.query
        .filter(
            Order.club_id == club_id,
            Order.table_no == table_no,
            Order.status != STATUS_REJECTED,
            Order.status != STATUS_COMPLETED,
            Order.created_at >= since,
        )
        .all()
    )
    orders = [order for order in orders if order.id not in waiting_ids]
    for order in orders:
        order.status = STATUS_COMPLETED
    db.session.commit()

    for order in orders:
        billing_service.charge_at_completion(order)

    return orders


class DecisionResult:
    """outcome: "not_found" | "forbidden" | "already_decided" | "ok"."""

    def __init__(self, outcome, request=None, closed_orders=None):
        self.outcome = outcome
        self.request = request
        self.closed_orders = closed_orders or []


def approve_request(request_id: int, kj, hide_receipt: bool) -> DecisionResult:
    """
    Подтверждение KJ. Порядок действий важен: сперва считаем чек (нужны ещё
    живые Order + TableGroup.created_at), затем автоматически снимаем
    непроигранные заказы стола (решение пользователя), и только в конце
    удаляем сам групповой стол — именно последний шаг освобождает table_no
    для следующей компании.
    """
    req = db.session.get(TableCloseRequest, request_id)
    if req is None:
        return DecisionResult(outcome="not_found")
    if req.club_id != kj.club_id:
        return DecisionResult(outcome="forbidden")
    if req.status != STATUS_TABLE_CLOSE_PENDING:
        return DecisionResult(outcome="already_decided", request=req)

    group = table_group_service.get_group(req.club_id, req.table_no)
    if group is None:
        # Гонка/повторное подтверждение — стол уже освобождён другим путём
        # (например, эту же заявку одобрили с другой вкладки KJ Panel чуть
        # раньше). Заявку всё равно помечаем решённой, просто без чека и
        # без закрытия заказов — закрывать уже нечего.
        req.status = STATUS_TABLE_CLOSE_APPROVED
        req.hide_receipt = hide_receipt
        req.member_guest_ids = []
        req.receipt_json = None
        req.decided_at = _utcnow()
        req.decided_by = kj.id
        db.session.commit()
        emit_table_close_request_decided(req)
        return DecisionResult(outcome="ok", request=req)

    member_guest_id_ints = [
        m.guest_id
        for m in TableGroupMember.query.filter_by(club_id=req.club_id, table_no=req.table_no).all()
    ]
    member_guest_ids = [str(gid) for gid in member_guest_id_ints]
    since = _session_since(req.club_id, req.table_no, group.created_at)
    closed_orders = complete_table_orders(req.club_id, req.table_no, since)
    receipt = _build_receipt(req.club_id, req.table_no, since)

    TableJoinRequest.query.filter_by(club_id=req.club_id, table_no=req.table_no).delete()
    TableGroupMember.query.filter_by(club_id=req.club_id, table_no=req.table_no).delete()
    TableGroup.query.filter_by(club_id=req.club_id, table_no=req.table_no).delete()

    req.status = STATUS_TABLE_CLOSE_APPROVED
    req.hide_receipt = hide_receipt
    req.member_guest_ids = member_guest_ids
    req.receipt_json = receipt
    req.decided_at = _utcnow()
    req.decided_by = kj.id
    db.session.commit()
    emit_table_close_request_decided(req)

    # ДОБАВЛЕНО (2026-09-29, жалоба пользователя: карточка стола "ни в одной
    # из карточек ничего нет" — при починке (см. миграцию 92cb15093592)
    # всплыл отдельный, самостоятельный баг рядом: эта функция удаляет
    # TableGroup/TableGroupMember (живую "компанию" за столом), но раньше
    # никогда не трогала GuestStatus.table_no — а это отдельный, свой
    # "текущий живой стол" гостя, который показывает его собственная
    # карточка гостя (guest_directory_service.get_guest_detail) и общий
    # список гостей. Из-за этого после закрытия стола гость мог продолжать
    # числиться "за столом N" в своей карточке, пока не зайдёт заново через
    # Google (routes/guest.py::link_google — единственное место, которое
    # само перезаписывает GuestStatus.table_no при обычном входе). Обнуляем
    # его здесь явно, тем же способом, что и guest_status_service.close_table
    # для одного гостя — каждому, кто реально сидел за этим столом
    # (member_guest_id_ints собран ДО удаления TableGroupMember выше, пока
    # список ещё доступен).
    for guest_id in member_guest_id_ints:
        guest_status_service.set_table(req.club_id, guest_id, None)

    return DecisionResult(outcome="ok", request=req, closed_orders=closed_orders)


def close_table_directly(club_id: int, table_no: int, kj, hide_receipt: bool) -> DecisionResult:
    """
    Закрытие стола сразу действием KJ из карточки стола в KJ Panel (запрос
    пользователя 2026-09-28) — без предварительной заявки гостя. Та же
    самая механика, что и approve_request выше (чек по ещё живым данным,
    автоотклонение непроигранного, удаление TableGroup/участников/заявок):
    KJ просто подтверждает закрытие от своего имени сразу, минуя шаг
    "гость сначала попросил".

    TableCloseRequest здесь всё равно создаётся — сразу в статусе approved,
    а не пропускается вовсе — чтобы уже существующий поллинг чека у гостя
    (pending_receipt_for_guest, см. routes/guest.py::me) сработал одинаково
    для обоих путей закрытия, не зная о разнице между ними.

    Если у этого стола на момент прямого закрытия уже висела НЕ решённая
    заявка гостя (guest успел попросить закрыть, а KJ в это же время закрыл
    с карточки стола) — она устарела, помечаем её отклонённой, чтобы не
    зависала в списке "Заявки на закрытие стола" как будто ничего не
    произошло.

    ОБНОВЛЕНО (запрос пользователя 2026-10, жалоба "один стол не
    закрылся" — "Все столы должны быть закрыты при нажатии на кнопку
    закрыть стол, даже если марсиане заказ прислали"): раньше отсутствие
    TableGroup означало "за столом никого нет" и давало TABLE_EMPTY — но
    песню на стол можно поставить и без TableGroup (диджей сам вписал её
    вручную, см. docstring list_occupied_table_nos в table_group_service.py
    за полным обоснованием). Теперь при отсутствии группы ищем просто
    активные заказы этого стола (ACTIVE_TABLE_STATUSES) — если они есть,
    закрываем стол тем же способом (чек, списание), просто без шагов, что
    касаются только настоящей компании гостей (удалять/сбрасывать нечего —
    группы никогда не было). requested_by_guest_id = -1 — то же "не гость"
    значение, что и в add_manual_song() (vdj_service.py).
    """
    group = table_group_service.get_group(club_id, table_no)

    if group is not None:
        # Читаем admin_guest_id/created_at ДО удаления группы ниже — bulk
        # TableGroup.query.delete() истекает (expire) уже загруженный
        # объект group в сессии, и обращение к его атрибутам после
        # удаления попыталось бы перечитать уже не существующую строку
        # (ObjectDeletedError).
        admin_guest_id = group.admin_guest_id
        member_guest_id_ints = [
            m.guest_id
            for m in TableGroupMember.query.filter_by(club_id=club_id, table_no=table_no).all()
        ]
        since = _session_since(club_id, table_no, group.created_at)
    else:
        active_orders = Order.query.filter(
            Order.club_id == club_id,
            Order.table_no == table_no,
            Order.status.in_(ACTIVE_TABLE_STATUSES),
        ).all()
        if not active_orders:
            return DecisionResult(outcome="not_found")
        admin_guest_id = -1
        member_guest_id_ints = []
        since = min(o.created_at for o in active_orders)

    member_guest_ids = [str(gid) for gid in member_guest_id_ints]
    closed_orders = complete_table_orders(club_id, table_no, since)
    receipt = _build_receipt(club_id, table_no, since)

    if group is not None:
        TableJoinRequest.query.filter_by(club_id=club_id, table_no=table_no).delete()
        TableGroupMember.query.filter_by(club_id=club_id, table_no=table_no).delete()
        TableGroup.query.filter_by(club_id=club_id, table_no=table_no).delete()

    req = TableCloseRequest(
        club_id=club_id,
        table_no=table_no,
        requested_by_guest_id=admin_guest_id,
        status=STATUS_TABLE_CLOSE_APPROVED,
        hide_receipt=hide_receipt,
        member_guest_ids=member_guest_ids,
        receipt_json=receipt,
        decided_at=_utcnow(),
        decided_by=kj.id,
    )
    db.session.add(req)

    stale = get_pending_for_table(club_id, table_no)
    if stale is not None:
        stale.status = STATUS_TABLE_CLOSE_REJECTED
        stale.decided_at = _utcnow()
        stale.decided_by = kj.id

    db.session.commit()
    emit_table_close_request_decided(req)
    if stale is not None:
        emit_table_close_request_decided(stale)

    # ДОБАВЛЕНО (2026-09-29) — см. подробный комментарий в approve_request
    # выше про тот же самый пробел: без этого GuestStatus.table_no (живой
    # стол гостя, который видит его собственная карточка) оставался бы
    # указывать на уже закрытый стол до следующего входа гостя через Google.
    for guest_id in member_guest_id_ints:
        guest_status_service.set_table(club_id, guest_id, None)

    return DecisionResult(outcome="ok", request=req, closed_orders=closed_orders)


class CloseAllResult:
    """Итог "Закрыть все столы" — одно outcome="ok" всегда (пустой список
    столов — тоже нормальный, не ошибочный исход, см. докстринг ниже)."""

    def __init__(self, closed_table_nos, decisions):
        self.closed_table_nos = closed_table_nos
        self.decisions = decisions  # список DecisionResult, по одному на стол


def close_all_tables(club_id: int, kj) -> CloseAllResult:
    """
    "Закрыть все столы" (запрос пользователя 2026-09-29: "кнопка. Закрыть
    все столы. просто закрывает вечер когда все ушли с караоке.") — конец
    вечера одним нажатием, чтобы не закрывать каждый занятый стол по
    отдельности через карточку стола.

    БЕЗ ЧЕКА, всегда (уточнение пользователя 2026-09-29: "столы, на которые
    требуются чеки, я закрываю отдельно [обычной кнопкой закрытия одного
    стола]. Потом отдельной кнопкой я закрываю столы. Всё." — то есть к
    моменту нажатия этой кнопки чеки уже выданы кому нужно вручную,
    остаётся просто зачистить оставшиеся столы) — hide_receipt здесь не
    параметр снаружи, а всегда True, в отличие от close_table_directly
    (карточка одного стола), где KJ сам решает, показывать чек или нет.

    Помимо самого закрытия (автоотклонение непроигранного, удаление
    TableGroup/участников/заявок — та же механика, что и close_table_directly
    выше), это ещё и конец вечера для КАЖДОГО гостя клуба: guest_status_
    service.clear_all_tables сбрасывает у всех "закреплённый стол", чтобы в
    следующий раз каждый заново увидел экран "выберите стол и войдите через
    Google" — но с тем же Google-аккаунтом, так что имя/VIP/история/
    избранное возвращаются сами (решение пользователя 2026-09-29, вариант
    "1"). Это касается ВСЕХ гостей клуба, а не только тех, кто сидел за
    только что закрытыми столами — "закрыть все столы" здесь означает
    "клуб закрывается на сегодня", а не только "эти конкретные столы опустели".

    Список "кто сейчас занят" (какие столы вообще нужно закрыть) берём из
    table_group_service.list_occupied_table_nos — тот же самый источник
    истины, что уже использует KJ Panel в списке столов при переносе (см.
    routes/kj.py::list_table_groups), а не отдельная догадка о занятости.

    Идёт по столам по одному (а не одним bulk-запросом к БД) — каждый стол
    может успеть сыграть разное число песен, а close_table_directly уже
    содержит всю эту логику проверенной и протестированной; здесь её
    незачем дублировать.
    """
    table_nos = sorted(table_group_service.list_occupied_table_nos(club_id))
    decisions = []
    closed_table_nos = []
    for table_no in table_nos:
        result = close_table_directly(club_id, table_no, kj, hide_receipt=True)
        decisions.append(result)
        if result.outcome == "ok":
            closed_table_nos.append(table_no)
    guest_status_service.clear_all_tables(club_id)

    # ДОБАВЛЕНО (2026-10, запрос пользователя): "Закрыть все столы" — это
    # очистка всего вечера, поэтому и чеки ранее закрытых столов у гостей
    # больше не показываются.
    TableCloseRequest.query.filter(
        TableCloseRequest.club_id == club_id,
        TableCloseRequest.status == STATUS_TABLE_CLOSE_APPROVED,
        TableCloseRequest.hide_receipt.is_(False),
    ).update({"hide_receipt": True}, synchronize_session=False)
    db.session.commit()

    # ДОБАВЛЕНО (запрос пользователя: "Начало очереди" должно каждый раз
    # запрашиваться заново, а не оставаться от прошлого вечера) — "Закрыть
    # все столы" и есть тот самый конец вечера, поэтому именно здесь стол
    # начала очереди сбрасывается обратно в "не задано" (см. models.py::
    # Club.queue_start_table, backend/routes/kj.py::confirm — принять заказ
    # нельзя, пока это поле не выбрано заново).
    club = db.session.get(Club, club_id)
    if club is not None:
        club.queue_start_table = None
        db.session.commit()

    return CloseAllResult(closed_table_nos=closed_table_nos, decisions=decisions)


def reject_request(request_id: int, kj) -> DecisionResult:
    req = db.session.get(TableCloseRequest, request_id)
    if req is None:
        return DecisionResult(outcome="not_found")
    if req.club_id != kj.club_id:
        return DecisionResult(outcome="forbidden")
    if req.status != STATUS_TABLE_CLOSE_PENDING:
        return DecisionResult(outcome="already_decided", request=req)

    req.status = STATUS_TABLE_CLOSE_REJECTED
    req.decided_at = _utcnow()
    req.decided_by = kj.id
    db.session.commit()
    emit_table_close_request_decided(req)
    return DecisionResult(outcome="ok", request=req)


# Окно, в течение которого чек ещё отдаётся поллингом (routes/guest.py::me)
# после approve. Guest App не имеет WebSocket-подключения (см. докстринг
# sockets.py::emit_chat_message), поэтому единственный способ доставки —
# опрос; окно — просто подстраховка, чтобы очень старое закрытие того же
# номера стола (тот же guest_id мог сидеть за ним много вечеров назад) не
# вылезло чеком на новый, никак не связанный визит. Дедупликация "показать
# один раз" — на стороне фронтенда, по id заявки.
RECEIPT_POLL_WINDOW_SECONDS = 900


def pending_receipt_for_guest(club_id: int, guest_id: int) -> dict | None:
    if guest_id is None:
        return None
    cutoff = _utcnow() - timedelta(seconds=RECEIPT_POLL_WINDOW_SECONDS)
    guest_id_str = str(guest_id)
    candidates = (
        TableCloseRequest.query
        .filter(
            TableCloseRequest.club_id == club_id,
            TableCloseRequest.status == STATUS_TABLE_CLOSE_APPROVED,
            TableCloseRequest.hide_receipt.is_(False),
            TableCloseRequest.decided_at >= cutoff,
        )
        .order_by(TableCloseRequest.decided_at.desc())
        .all()
    )
    for req in candidates:
        if req.member_guest_ids and guest_id_str in req.member_guest_ids:
            # Пустой чек (ни одной песни) гостю не показываем.
            receipt = req.receipt_json if isinstance(req.receipt_json, dict) else None
            if receipt is not None and not receipt.get("song_count"):
                continue
            return req.to_dict()
    return None
