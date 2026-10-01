"""
Запрос VIP-гостя к KJ "хочу пополнить баланс" (запрос пользователя
2026-09-30, см. докстринг models.VipTopupRequest) — сама заявка деньги не
переводит: KJ, увидев её в своей панели, подходит к гостю и зачисляет
сумму вручную через уже существующую кнопку пополнения VIP-баланса
(routes/kj.py::topup_vip_balance, services/vip_service.py::topup_balance).
Это только уведомление, чтобы гостю не приходилось искать KJ по залу
самому.

Поток: VIP-гость -> POST /api/guest/vip/topup-request (request_topup) ->
заявка видна KJ Panel (list_pending, плюс сокет-событие
vip_topup_request_created, по образцу table_close_request_created) -> KJ
зачисляет деньги как обычно и жмёт "обработано" (resolve_request).

Тот же паттерн, что и table_close_service.request_close: одна незакрытая
заявка на гостя в клубе, повторное нажатие кнопки, пока прошлая заявка ещё
не обработана, возвращает ту же самую заявку, а не плодит дубликаты.
"""

from datetime import datetime, timezone

from extensions import db
from models import (
    STATUS_VIP_TOPUP_PENDING,
    STATUS_VIP_TOPUP_RESOLVED,
    VipTopupRequest,
)
from sockets import emit_vip_topup_request_created, emit_vip_topup_request_decided


def _utcnow():
    return datetime.now(timezone.utc)


class RequestResult:
    """outcome: "already_pending" | "ok"."""

    def __init__(self, outcome, request=None):
        self.outcome = outcome
        self.request = request


class ResolveResult:
    """outcome: "not_found" | "forbidden" | "already_decided" | "ok"."""

    def __init__(self, outcome, request=None):
        self.outcome = outcome
        self.request = request


def get_pending_for_guest(club_id: int, guest_id: int) -> VipTopupRequest | None:
    return (
        VipTopupRequest.query
        .filter_by(club_id=club_id, telegram_user_id=guest_id, status=STATUS_VIP_TOPUP_PENDING)
        .first()
    )


def request_topup(club_id: int, guest_id: int) -> RequestResult:
    """
    Вызывается самим гостем (кнопка "Запросить пополнение" в Guest App,
    видна только когда баланс уже в минусе — см.
    billing_service.is_vip_balance_blocked). Повторный вызов, пока прошлая
    заявка не обработана, возвращает её же, а не создаёт дубликат.
    """
    existing = get_pending_for_guest(club_id, guest_id)
    if existing is not None:
        return RequestResult(outcome="already_pending", request=existing)

    req = VipTopupRequest(club_id=club_id, telegram_user_id=guest_id)
    db.session.add(req)
    db.session.commit()
    emit_vip_topup_request_created(req)
    return RequestResult(outcome="ok", request=req)


def list_pending(club_id: int) -> list[VipTopupRequest]:
    return (
        VipTopupRequest.query
        .filter_by(club_id=club_id, status=STATUS_VIP_TOPUP_PENDING)
        .order_by(VipTopupRequest.created_at.asc())
        .all()
    )


def resolve_request(club_id: int, request_id: int, kj) -> ResolveResult:
    """
    KJ отмечает заявку обработанной, после того как сам пополнил баланс
    гостю наличными/картой через обычную кнопку VIP-клиента — эта функция
    саму сумму никак не трогает, только убирает уведомление из списка
    ожидающих во всех открытых панелях клуба.
    """
    req = db.session.get(VipTopupRequest, request_id)
    if req is None:
        return ResolveResult(outcome="not_found")
    if req.club_id != club_id:
        return ResolveResult(outcome="forbidden")
    if req.status != STATUS_VIP_TOPUP_PENDING:
        return ResolveResult(outcome="already_decided", request=req)

    req.status = STATUS_VIP_TOPUP_RESOLVED
    req.decided_at = _utcnow()
    req.decided_by = kj.id
    db.session.commit()
    emit_vip_topup_request_decided(req)
    return ResolveResult(outcome="ok", request=req)
