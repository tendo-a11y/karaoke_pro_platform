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
"""
from datetime import datetime, timedelta, timezone

from extensions import db
from models import (
    Order,
    Service,
    STATUS_COMPLETED,
    STATUS_TABLE_CLOSE_APPROVED,
    STATUS_TABLE_CLOSE_PENDING,
    STATUS_TABLE_CLOSE_REJECTED,
    TableCloseRequest,
    TableGroup,
    TableGroupMember,
    TableJoinRequest,
)
from services import table_group_service
from services.vdj_service import close_table_orders
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

    categories = {}
    total = 0.0
    for order in orders:
        service = services_by_id.get(order.service_id) if order.service_id else None
        name = service.name if service is not None else "Без категории"
        price = float(service.price) if service is not None and service.price is not None else 0.0
        bucket = categories.setdefault(name, {"category": name, "count": 0, "price": price, "sum": 0.0})
        bucket["count"] += 1
        bucket["sum"] += price
        total += price

    return {
        "table_no": table_no,
        "song_count": len(orders),
        "categories": list(categories.values()),
        "total": total,
    }


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

    member_guest_ids = [
        str(m.guest_id)
        for m in TableGroupMember.query.filter_by(club_id=req.club_id, table_no=req.table_no).all()
    ]
    receipt = _build_receipt(req.club_id, req.table_no, group.created_at)
    closed_orders = close_table_orders(req.club_id, req.table_no)

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

    return DecisionResult(outcome="ok", request=req, closed_orders=closed_orders)


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
            return req.to_dict()
    return None
