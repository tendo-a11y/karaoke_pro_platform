"""
Частота воспроизведений для "Новинок" (2026-10): считается за те же
POPULAR_DAYS дней, что и "Популярные"; песни без игр получают count = 0.
"""
from datetime import datetime, timedelta, timezone

from models import Order
from services import song_lists_service as sls


def _play(db, club_id, title, artist, days_ago):
    order = Order(
        telegram_user_id=1, club_id=club_id, table_no=1, guest_type="vip",
        song_title=title, artist=artist, source="guest",
        playing_at=datetime.now(timezone.utc) - timedelta(days=days_ago),
    )
    db.session.add(order)
    db.session.commit()


def test_new_songs_count_plays_in_popular_period(db, club):
    cid = club.club_id
    sls.set_new(cid, "Где ты", "Ирина Круг", True)
    sls.set_new(cid, "Oriunde ai fi", "Dan Balan", True)
    _play(db, cid, "Где ты", "Ирина Круг", 1)
    _play(db, cid, "Где ты", "Ирина Круг", 5)
    _play(db, cid, "Где ты", "Ирина Круг", sls.POPULAR_DAYS + 10)  # вне периода
    counts = {r["song_title"]: r["count"] for r in sls.new_songs(cid)}
    assert counts == {"Где ты": 2, "Oriunde ai fi": 0}
