"""
Кешбек от клуба супер-админу (запрос пользователя 2026-10-09).

У каждого клуба свой процент (Club.cashback_percent), его вводит вручную
супер-админ, и переключатель "только с VIP / со всей выручки"
(Club.cashback_vip_only). В конце каждого вечера (автозакрытие или
"Закрыть все столы") записывается ClubCashback: выручка вечера (все спетые
песни по цене категории — как в статистике KJ), отдельно VIP и не VIP,
сколько было гостей VIP и не VIP, процент и сумма кешбека.

Деньги никуда не переводятся — это учёт "к выплате". Супер-админ ставит
отметку "Выплачено", когда клуб заплатил.
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from extensions import db
from models import STATUS_COMPLETED, STATUS_PLAYING, Club, ClubCashback, Order, Service
from services.category_service import not_bonus_filter

SUNG_STATUSES = (STATUS_PLAYING, STATUS_COMPLETED)
CENT = Decimal("0.01")


class CashbackError(Exception):
    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


def parse_percent(value):
    """None/"" — процент не задан; иначе число 0..100."""
    if value is None or value == "":
        return None
    try:
        percent = Decimal(str(value).replace(",", "."))
    except Exception:
        raise CashbackError("VALIDATION_ERROR", "Кешбек — число от 0 до 100")
    if percent < 0 or percent > 100:
        raise CashbackError("VALIDATION_ERROR", "Кешбек — число от 0 до 100")
    return percent.quantize(CENT)


def _price(order, services) -> Decimal:
    service = services.get(order.service_id)
    if service is None or service.is_free:
        return Decimal("0")
    return Decimal(str(service.price or 0))


def accrue_evening(club: Club, start_at, end_at):
    """Записывает кешбек за вечер [start_at, end_at). Пустой вечер не записывается."""
    services = {s.id: s for s in Service.query.filter_by(club_id=club.club_id).all()}
    sung = (
        Order.query
        .filter(
            Order.club_id == club.club_id,
            Order.created_at >= start_at,
            Order.created_at < end_at,
            Order.status.in_(SUNG_STATUSES),
            not_bonus_filter(),
        )
        .all()
    )
    if not sung:
        return None

    revenue_vip = sum((_price(o, services) for o in sung if o.guest_type == "vip"), Decimal("0"))
    revenue_total = sum((_price(o, services) for o in sung), Decimal("0"))
    revenue_regular = revenue_total - revenue_vip

    vip_guests = {o.telegram_user_id for o in sung if o.source == "guest" and o.guest_type == "vip"}
    all_guests = {o.telegram_user_id for o in sung if o.source == "guest"}

    percent = Decimal(str(club.cashback_percent or 0))
    vip_only = bool(club.cashback_vip_only)
    base = revenue_vip if vip_only else revenue_total
    amount = (base * percent / Decimal("100")).quantize(CENT)

    row = ClubCashback(
        club_id=club.club_id,
        start_at=start_at,
        end_at=end_at,
        revenue_total=revenue_total.quantize(CENT),
        revenue_vip=revenue_vip.quantize(CENT),
        revenue_regular=revenue_regular.quantize(CENT),
        guests_vip=len(vip_guests),
        guests_regular=len(all_guests - vip_guests),
        percent=percent,
        vip_only=vip_only,
        amount=amount,
    )
    db.session.add(row)
    db.session.commit()
    return row


def evening_start(club: Club, end_at):
    """Начало вечера — прошлое закрытие; если его не было — сутки назад."""
    prev = club.evening_closed_at
    if prev is not None and prev.tzinfo is None:
        prev = prev.replace(tzinfo=timezone.utc)
    if prev is None or prev >= end_at:
        return end_at - timedelta(days=1)
    return prev


def overview(evenings_limit: int = 60) -> list[dict]:
    """Для супер-админа: по каждому клубу процент, долг и последние вечера."""
    result = []
    for club in Club.query.order_by(Club.club_id.asc()).all():
        rows = (
            ClubCashback.query
            .filter_by(club_id=club.club_id)
            .order_by(ClubCashback.end_at.desc())
            .all()
        )
        owed = sum((Decimal(str(r.amount or 0)) for r in rows if r.paid_at is None), Decimal("0"))
        paid = sum((Decimal(str(r.amount or 0)) for r in rows if r.paid_at is not None), Decimal("0"))
        result.append({
            "club_id": club.club_id,
            "name": club.name,
            "cashback_percent": float(club.cashback_percent) if club.cashback_percent is not None else None,
            "cashback_vip_only": bool(club.cashback_vip_only),
            "owed": float(owed),
            "paid": float(paid),
            "evenings": [r.to_dict() for r in rows[:evenings_limit]],
        })
    return result


def set_paid(cashback_id: int, paid: bool) -> ClubCashback:
    row = db.session.get(ClubCashback, cashback_id)
    if row is None:
        raise CashbackError("NOT_FOUND", "Начисление не найдено", 404)
    row.paid_at = datetime.now(timezone.utc) if paid else None
    db.session.commit()
    return row
