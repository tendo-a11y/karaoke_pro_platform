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


def clear_all_tables(club_id: int) -> None:
    """
    "Закрыть все столы" (запрос пользователя 2026-09-29: закрытие стола —
    это конец вечера, а не просто освобождение мест; у каждого гостя должен
    заново спроситься стол в следующий раз, точно как в самый первый визит)
    — сбрасывает table_no сразу у ВСЕХ гостей клуба, та же самая живая
    правда, что и set_table(..., None) поштучно у одного гостя (см. выше,
    "KJ снял со стола"), только массово.

    Гость при этом не выходит из Google и не теряет имя/VIP/историю/
    избранное — это всё живёт в GuestAccount, отдельно от GuestStatus, и
    никак здесь не трогается. При следующем действии гостю просто заново
    покажут экран "выберите стол и войдите через Google" (services/
    table_close_service.py::close_all_tables) — тот же самый Google-аккаунт
    сам вернёт всё старое (guest_account_service.link_google).

    Тех, у кого ещё вообще нет строки GuestStatus (ни разу не проходили
    через link_google), тут нечего сбрасывать — у них и так ещё нет
    постоянного профиля, значит экран выбора стола показывается им и без
    этого (см. App.jsx::activated).
    """
    GuestStatus.query.filter_by(club_id=club_id).update({"table_no": None})
    db.session.commit()


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
    "Закрыть стол" (запрос пользователя 2026-09-19; ИЗМЕНЕНО 2026-09-29 —
    прямая жалоба пользователя: нажал "Закрыть стол" на карточке гостя,
    ожидая только освободить стол, а гостя заодно молча заблокировало —
    "вместо этого сработала блокировка", "Заблокировать и Закрыть Стол.
    Это две отдельные кнопки") — раньше это действие одним кликом убирало
    гостя со стола (set_table(None)) И блокировало его (block()) сразу.
    Явное решение пользователя: разделить обратно — это действие ТОЛЬКО
    освобождает стол и отклоняет непроигранное, блокировка сюда больше не
    входит. Блокировка (см. block()/unblock() выше) — полностью отдельное,
    самостоятельное действие со своей кнопкой "🚫 Заблокировать", как и
    было до 2026-09-19, KJ должен нажать её отдельно, если гостя
    действительно нужно заблокировать, а не просто отвести от стола.

    Плюс — сохраняется с 2026-09-19, это не менялось: отклоняет все ещё
    активные (непроигранные) заказы этого стола (close_table_orders), чтобы
    места на табло реально освободились, а не остались висеть "принят"
    навсегда (см. table_board_service.py — раньше единственным способом
    освободить место было "Готово" по каждой песне отдельно, а для сценария
    "гости просто ушли" это неудобно и не подходит).

    Стол определяется тем же способом, что и в самой карточке гостя (см.
    guest_directory_service.get_guest_detail -> table_no) — текущий живой
    стол гостя (GuestStatus.table_no), а если строки статуса ещё нет —
    стол его последнего заказа. Если стола нет вообще (guest.table_no is
    None) — отклонять нечего, просто ничего не делаем со столом.

    kj-параметр оставлен в сигнатуре (используется в вызывающем коде,
    routes/kj.py::close_guest_table) хотя внутри уже не используется — эта
    функция больше не пишет blocked_by, писать здесь больше некуда.

    Возвращает {"status": GuestStatus, "closed_orders": [Order, ...]}.
    """
    detail = guest_directory_service.get_guest_detail(club_id, guest_id)
    table_no = detail.get("table_no")

    closed_orders = close_table_orders(club_id, table_no) if table_no is not None else []

    status = set_table(club_id, guest_id, None)

    return {"status": status, "closed_orders": closed_orders}
