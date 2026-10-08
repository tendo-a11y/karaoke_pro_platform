"""
Списки песен для гостя над живой очередью (запрос пользователя 2026-10):
"История за час", "Популярные" (что чаще всего поют в клубе за 30 дней,
до 50 песен) и "Новинки" (песни, которые KJ отметил галочкой в живой
очереди; одна песня в списке только один раз).

Спетой считается песня, у которой есть время выхода на сцену (playing_at —
"Готово" вручную или автоматически по истории VirtualDJ). Заказы, которые
только засчитаны при закрытии стола, сюда не попадают.
"""
from collections import Counter
from datetime import datetime, timedelta, timezone

from extensions import db
from models import NewSong, Order, SongListHidden

POPULAR_DAYS = 30
POPULAR_LIMIT = 50
RECENT_MINUTES = 60
NEW_SONGS_LIMIT = 30


def norm_key(song_title, artist) -> str:
    def norm(value):
        return " ".join(str(value or "").lower().split())
    return f"{norm(artist)}|{norm(song_title)}"


def _hidden_history_ids(club_id: int) -> set:
    return {
        r.order_id
        for r in SongListHidden.query.filter_by(club_id=club_id, kind="history").all()
        if r.order_id is not None
    }


def _hidden_popular_keys(club_id: int) -> set:
    return {r.norm_key for r in SongListHidden.query.filter_by(club_id=club_id, kind="popular").all()}


def recent_hour(club_id: int, now=None) -> list[dict]:
    now = now or datetime.now(timezone.utc)
    hidden = _hidden_history_ids(club_id)
    rows = (
        Order.query
        .filter(
            Order.club_id == club_id,
            Order.playing_at.isnot(None),
            Order.playing_at >= now - timedelta(minutes=RECENT_MINUTES),
        )
        .order_by(Order.playing_at.desc())
        .all()
    )
    return [
        {"order_id": o.id, "song_title": o.song_title, "artist": o.artist, "played_at": o.playing_at.isoformat()}
        for o in rows
        if o.id not in hidden
    ]


def popular(club_id: int, now=None) -> list[dict]:
    now = now or datetime.now(timezone.utc)
    rows = (
        Order.query.with_entities(Order.song_title, Order.artist)
        .filter(
            Order.club_id == club_id,
            Order.playing_at.isnot(None),
            Order.playing_at >= now - timedelta(days=POPULAR_DAYS),
        )
        .all()
    )
    counter = Counter()
    label = {}
    hidden = _hidden_popular_keys(club_id)
    for song_title, artist in rows:
        key = norm_key(song_title, artist)
        if key == "|" or key in hidden:
            continue
        counter[key] += 1
        label.setdefault(key, (song_title, artist))
    return [
        {"song_title": label[key][0], "artist": label[key][1], "count": count}
        for key, count in counter.most_common(POPULAR_LIMIT)
    ]


def new_songs(club_id: int) -> list[dict]:
    rows = NewSong.query.filter_by(club_id=club_id).order_by(NewSong.created_at.desc(), NewSong.id.desc()).all()
    return [r.to_dict() for r in rows]


def hide(club_id: int, kind: str, song_title=None, artist=None, order_id=None) -> None:
    """KJ: скрыть песню из "Популярных" (kind="popular") или одну спетую
    песню из "Истории за час" (kind="history")."""
    if kind == "popular":
        key = norm_key(song_title, artist)
        if SongListHidden.query.filter_by(club_id=club_id, kind="popular", norm_key=key).first() is None:
            db.session.add(SongListHidden(
                club_id=club_id, kind="popular", norm_key=key,
                song_title=(song_title or "").strip() or None, artist=(artist or "").strip() or None,
            ))
            db.session.commit()
    elif kind == "history" and order_id is not None:
        if SongListHidden.query.filter_by(club_id=club_id, kind="history", order_id=order_id).first() is None:
            order = db.session.get(Order, order_id)
            db.session.add(SongListHidden(
                club_id=club_id, kind="history", order_id=order_id,
                song_title=order.song_title if order is not None else None,
                artist=order.artist if order is not None else None,
            ))
            db.session.commit()


def unhide(club_id: int, hidden_id: int) -> None:
    row = SongListHidden.query.filter_by(club_id=club_id, id=hidden_id).first()
    if row is not None:
        db.session.delete(row)
        db.session.commit()


def hidden_popular(club_id: int) -> list[dict]:
    rows = (
        SongListHidden.query.filter_by(club_id=club_id, kind="popular")
        .order_by(SongListHidden.created_at.desc())
        .all()
    )
    return [r.to_dict() for r in rows]


def set_new(club_id: int, song_title: str, artist, is_new: bool) -> bool:
    """Отметить / снять "Новинку". Повторно одна и та же песня не добавляется."""
    key = norm_key(song_title, artist)
    existing = NewSong.query.filter_by(club_id=club_id, norm_key=key).first()
    if is_new and existing is None:
        db.session.add(NewSong(club_id=club_id, song_title=song_title.strip(), artist=(artist or "").strip() or None, norm_key=key))
        db.session.commit()
        # ДОБАВЛЕНО (2026-10, запрос пользователя): в "Новинках" не больше
        # NEW_SONGS_LIMIT песен — новая вытесняет самую старую.
        extra = (
            NewSong.query.filter_by(club_id=club_id)
            .order_by(NewSong.created_at.desc(), NewSong.id.desc())
            .offset(NEW_SONGS_LIMIT)
            .all()
        )
        if extra:
            for row in extra:
                db.session.delete(row)
            db.session.commit()
    elif not is_new and existing is not None:
        db.session.delete(existing)
        db.session.commit()
    return is_new
