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
from services import guest_directory_service
from services.vdj_service import close_table_orders


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


def close_table(club_id: int, guest_id: int, kj) -> dict:
    """
    "Закрыть стол" (запрос пользователя 2026-09-19) — одно действие из
    карточки гостя в KJ Panel на случай, когда компания встала и ушла:
    убрать гостя со стола (set_table(None)) + заблокировать его
    (block()) — ровно то же самое, что KJ раньше делал вручную двумя
    отдельными кнопками "Снять со стола" и "Заблокировать" (обе кнопки
    остаются на месте как есть, это просто их объединение в один клик) —
    ПЛЮС, чего раньше не делала ни одна из них: отклоняет все ещё активные
    (непроигранные) заказы этого стола (close_table_orders), чтобы места
    на табло реально освободились, а не остались висеть "принят" навсегда
    (см. table_board_service.py — раньше единственным способом освободить
    место было "Готово" по каждой песне отдельно, а для этого сценария
    "гости просто ушли" это неудобно и не подходит).

    Стол определяется тем же способом, что и в самой карточке гостя (см.
    guest_directory_service.get_guest_detail -> table_no) — текущий живой
    стол гостя (GuestStatus.table_no), а если строки статуса ещё нет —
    стол его последнего заказа. Если стола нет вообще (guest.table_no is
    None) — отклонять нечего, просто блокируем.

    Возвращает {"status": GuestStatus, "closed_orders": [Order, ...]}.
    """
    detail = guest_directory_service.get_guest_detail(club_id, guest_id)
    table_no = detail.get("table_no")

    closed_orders = close_table_orders(club_id, table_no) if table_no is not None else []

    set_table(club_id, guest_id, None)
    status = block(club_id, guest_id, kj)

    return {"status": status, "closed_orders": closed_orders}
