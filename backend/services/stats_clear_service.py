"""
Очистка статистики (запрос пользователя 2026-10-09): в каждой панели своя
кнопка — за день, неделю, месяц или год. Ничего не удаляется: панель
просто перестаёт показывать данные за очищенный отрезок времени. Другие
панели (и чеки, и балансы) видят всё как прежде.
"""
from datetime import datetime, timedelta, timezone

from extensions import db
from models import StatsClear

PERIOD_DAYS = {"day": 1, "week": 7, "month": 30, "year": 365}
SCOPES = {"kj", "guest_history", "guest_finance", "admin"}


def clear(scope: str, owner, period: str) -> StatsClear:
    if scope not in SCOPES:
        raise ValueError("scope")
    days = PERIOD_DAYS.get(period)
    if days is None:
        raise ValueError("period")
    now = datetime.now(timezone.utc)
    item = StatsClear(scope=scope, owner=str(owner), start_at=now - timedelta(days=days), end_at=now)
    db.session.add(item)
    db.session.commit()
    return item


def ranges(scope: str, owner) -> list[tuple]:
    rows = StatsClear.query.filter_by(scope=scope, owner=str(owner)).all()
    return [(r.start_at, r.end_at) for r in rows]


def exclude(column, scope: str, owner):
    """Условие "column не попадает ни в один очищенный отрезок"."""
    parts = [db.not_(column.between(start, end)) for start, end in ranges(scope, owner)]
    return db.and_(*parts) if parts else db.true()


def is_cleared(moment, cleared: list[tuple]) -> bool:
    if moment is None:
        return False
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    for start, end in cleared:
        s = start if start.tzinfo else start.replace(tzinfo=timezone.utc)
        e = end if end.tzinfo else end.replace(tzinfo=timezone.utc)
        if s <= moment <= e:
            return True
    return False
