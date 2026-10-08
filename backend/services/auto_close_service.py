"""
Автозакрытие столов (запрос пользователя 2026-10: "сделать автозакрытие,
чтобы можно было поставить время, каждый KJ ставил своё; даже если KJ не
закрыл — происходит автозакрытие").

В заданное время клуба система сама делает то же, что кнопка "Закрыть все
столы" (table_close_service.close_all_tables). Время — по часам компьютера
KJ: панель при сохранении присылает смещение своего часового пояса.

Защита (решение пользователя): если за последние ACTIVITY_GUARD_MINUTES
минут в клубе что-то происходило с заказами (заказали, приняли, спели),
закрытие откладывается и повторяется позже, когда станет тихо.

Отдельного планировщика нет: проверка выполняется попутно с обычными
запросами к серверу, не чаще раза в CHECK_INTERVAL_SECONDS. Если ночью к
серверу никто не обращался, закрытие произойдёт при первом же обращении —
раньше, чем кто-либо что-то увидит.
"""
import logging
import time
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from sqlalchemy import or_

from extensions import db
from models import Club, Order

log = logging.getLogger(__name__)

CHECK_INTERVAL_SECONDS = 60
ACTIVITY_GUARD_MINUTES = 30

_last_check = 0.0


def parse_time(value):
    """ "07:30" -> (7, 30); None, если строка не похожа на время."""
    if not isinstance(value, str):
        return None
    parts = value.strip().split(":")
    if len(parts) != 2 or not all(p.isdigit() for p in parts):
        return None
    hour, minute = int(parts[0]), int(parts[1])
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    return hour, minute


def last_occurrence_date(club, now=None):
    """Дата (по часам клуба) последнего уже наступившего времени закрытия."""
    parsed = parse_time(club.auto_close_time)
    if parsed is None:
        return None
    now = now or datetime.now(timezone.utc)
    local = now + timedelta(minutes=club.auto_close_tz_offset or 0)
    hour, minute = parsed
    if (local.hour, local.minute) >= (hour, minute):
        return local.date()
    return local.date() - timedelta(days=1)


def has_recent_activity(club_id: int, now=None) -> bool:
    now = now or datetime.now(timezone.utc)
    border = now - timedelta(minutes=ACTIVITY_GUARD_MINUTES)
    return db.session.query(
        Order.query.filter(
            Order.club_id == club_id,
            or_(
                Order.created_at >= border,
                Order.confirmed_at >= border,
                Order.queued_at >= border,
                Order.playing_at >= border,
                Order.completed_at >= border,
            ),
        ).exists()
    ).scalar()


def run_due(now=None) -> list[int]:
    """Закрывает столы во всех клубах, где подошло время. Возвращает их id."""
    from services import table_close_service

    now = now or datetime.now(timezone.utc)
    closed = []
    clubs = Club.query.filter(Club.auto_close_enabled.is_(True)).all()
    for club in clubs:
        due = last_occurrence_date(club, now)
        if due is None or club.auto_close_last_date == due:
            continue
        club_id = club.club_id
        if has_recent_activity(club_id, now):
            continue
        # Отметка ставится одним запросом с условием — если сервер работает
        # в несколько процессов, закрытие выполнит только один из них.
        updated = (
            Club.query
            .filter(
                Club.club_id == club_id,
                or_(Club.auto_close_last_date.is_(None), Club.auto_close_last_date != due),
            )
            .update({"auto_close_last_date": due}, synchronize_session=False)
        )
        db.session.commit()
        if not updated:
            continue
        try:
            table_close_service.close_all_tables(club_id, SimpleNamespace(id=None, club_id=club_id))
            closed.append(club_id)
            log.info("auto-close: club %s closed for %s", club_id, due)
        except Exception:
            db.session.rollback()
            log.exception("auto-close failed for club %s", club_id)
            Club.query.filter(Club.club_id == club_id).update(
                {"auto_close_last_date": None}, synchronize_session=False
            )
            db.session.commit()
    return closed


def maybe_run() -> None:
    """Попутная проверка из обычных запросов — не чаще раза в минуту."""
    global _last_check
    current = time.monotonic()
    if current - _last_check < CHECK_INTERVAL_SECONDS:
        return
    _last_check = current
    try:
        run_due()
    except Exception:
        db.session.rollback()
        log.exception("auto-close check failed")
