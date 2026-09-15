"""
Живой статус гостя (models.py::GuestStatus) — блокировка и текущий стол,
управляемые KJ из карточки гостя в KJ Panel (запрос пользователя 2026-09:
список гостей VIP/Простой/Без стола с картой гостя, блокировкой и снятием
со стола). См. подробный докстринг GuestStatus и auth.py::require_guest —
это единственный источник истины, который перебивает JWT гостя.
"""
from datetime import datetime, timezone

from extensions import db
from models import GuestStatus


def _utcnow():
    return datetime.now(timezone.utc)


def get_status(club_id: int, guest_id: int) -> GuestStatus | None:
    return GuestStatus.query.filter_by(club_id=club_id, telegram_user_id=guest_id).first()


def _get_or_create(club_id: int, guest_id: int) -> GuestStatus:
    status = get_status(club_id, guest_id)
    if status is None:
        status = GuestStatus(club_id=club_id, telegram_user_id=guest_id)
        db.session.add(status)
    return status


def set_table(club_id: int, guest_id: int, table_no: int | None) -> GuestStatus:
    """
    Запоминает текущий стол гостя как живой факт в БД (не только в его
    JWT) — вызывается и когда гость сам выбирает/меняет стол (routes/
    guest.py::link_google), и когда KJ принудительно снимает его со стола
    (table_no=None) из карточки гостя. Блокировку не трогает.
    """
    status = _get_or_create(club_id, guest_id)
    status.table_no = table_no
    db.session.commit()
    return status


def block(club_id: int, guest_id: int, kj) -> GuestStatus:
    status = _get_or_create(club_id, guest_id)
    status.is_blocked = True
    status.blocked_at = _utcnow()
    status.blocked_by = kj.id
    db.session.commit()
    return status


def unblock(club_id: int, guest_id: int) -> GuestStatus | None:
    status = get_status(club_id, guest_id)
    if status is None:
        return None
    status.is_blocked = False
    status.blocked_at = None
    status.blocked_by = None
    db.session.commit()
    return status
