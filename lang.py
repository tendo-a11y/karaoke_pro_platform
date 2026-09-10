from __future__ import annotations
from locales import t, pluralize_tables

__all__ = ['t', 'pluralize_tables', 'get_lang']

_db = None

def _get_db():
    global _db
    if _db is None:
        from database import Database
        _db = Database()
    return _db

async def get_lang(user_id: int) -> str:
    try:
        db = _get_db()
        lang = await db.get_user_language(user_id)
        return lang if lang in ('ru', 'ro') else 'ru'
    except Exception:
        return 'ru'
