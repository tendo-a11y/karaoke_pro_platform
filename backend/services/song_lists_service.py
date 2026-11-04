"""
Списки песен для гостя над живой очередью (запрос пользователя 2026-10):
"История за час", "Популярные" (что чаще всего поют в клубе за 30 дней,
до 50 песен) и "Новинки" (песни, которые KJ отметил галочкой в живой
очереди; одна песня в списке только один раз).

Спетой считается песня, у которой есть время выхода на сцену (playing_at —
"Готово" вручную или автоматически по истории VirtualDJ). Заказы, которые
только засчитаны при закрытии стола, сюда не попадают.
"""
import difflib
import re
from collections import Counter
from datetime import datetime, timedelta, timezone

from extensions import db
from models import NewSong, Order, SongListHidden

POPULAR_DAYS = 30
POPULAR_LIMIT = 50
RECENT_MINUTES = 60
NEW_SONGS_LIMIT = 30


def _norm_text(value) -> str:
    # Знаки препинания, регистр и ё/е не учитываются, чтобы одна и та же песня
    # не делилась на несколько строк (счётчик "Популярных" считался бы неверно).
    text = str(value or "").lower().replace("ё", "е")
    text = re.sub(r"[^\w\s]", "", text)
    return " ".join(text.split())


def norm_key(song_title, artist) -> str:
    return f"{_norm_text(artist)}|{_norm_text(song_title)}"


def _renorm_stored_key(stored: str) -> str:
    # Ключи, сохранённые до смены правила (с знаками препинания), приводим к новому виду на лету.
    artist, _, title = (stored or "").partition("|")
    return f"{_norm_text(artist)}|{_norm_text(title)}"


# Одна и та же песня может быть записана по-разному: порядок слов и место исполнителя не важны
# («Рюмка водки - Лепс», «Рюмка водки на столе - Лепс», «Лепс Рюмка водки»).
def _same_song_tokens(a: set, b: set) -> bool:
    if not a or not b:
        return False
    if a == b:
        return True
    shorter, longer = (a, b) if len(a) <= len(b) else (b, a)
    # Короткое название (минимум два слова) целиком входит в длинное.
    if len(shorter) >= 2 and shorter <= longer:
        return True
    # Небольшие опечатки: слова почти совпадают.
    return difflib.SequenceMatcher(None, " ".join(sorted(a)), " ".join(sorted(b))).ratio() >= 0.9


class _SongGroups:
    """Группирует записи одной песни: исполнитель не должен отличаться, а слова названия и исполнителя сравниваются без учёта порядка."""

    def __init__(self):
        self.groups = []

    def key_for(self, song_title, artist):
        title_n = _norm_text(song_title)
        if not title_n:
            return None
        artist_n = _norm_text(artist)
        title_words = set(title_n.split())
        # Исполнителя, написанного в названии, не сравниваем: остаются только слова песни.
        core = (title_words - set(artist_n.split())) or title_words
        for g in self.groups:
            if artist_n and g["artist"] and artist_n != g["artist"]:
                continue
            if _same_song_tokens(core, g["core"]):
                return g["key"]
        self.groups.append({"artist": artist_n, "core": core, "key": norm_key(song_title, artist)})
        return self.groups[-1]["key"]


def _hidden_history_ids(club_id: int) -> set:
    return {
        r.order_id
        for r in SongListHidden.query.filter_by(club_id=club_id, kind="history").all()
        if r.order_id is not None
    }


def _hidden_popular_keys(club_id: int) -> set:
    return {_renorm_stored_key(r.norm_key) for r in SongListHidden.query.filter(SongListHidden.club_id == club_id, SongListHidden.kind.in_(["popular", "popular_archived"])).all()}


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
    hidden = _hidden_popular_keys(club_id)
    groups = _SongGroups()
    counter = Counter()
    variants = {}
    for song_title, artist in rows:
        key = groups.key_for(song_title, artist)
        if key is None or norm_key(song_title, artist) in hidden:
            continue
        counter[key] += 1
        variants.setdefault(key, Counter())[(song_title, artist)] += 1
    result = []
    for key, count in counter.most_common(POPULAR_LIMIT):
        title, artist = variants[key].most_common(1)[0][0]
        result.append({"song_title": title, "artist": artist, "count": count})
    return result


def new_songs(club_id: int, now=None, kind: str = "new") -> list[dict]:
    # У каждой новинки — число воспроизведений за тот же период, что и у "Популярных".
    # Одна и та же песня в разных написаниях считается одной (см. _SongGroups).
    now = now or datetime.now(timezone.utc)
    played = (
        Order.query.with_entities(Order.song_title, Order.artist)
        .filter(
            Order.club_id == club_id,
            Order.playing_at.isnot(None),
            Order.playing_at >= now - timedelta(days=POPULAR_DAYS),
        )
        .all()
    )
    groups = _SongGroups()
    counter = Counter(groups.key_for(song_title, artist) for song_title, artist in played)
    rows = NewSong.query.filter_by(club_id=club_id, kind=kind).order_by(NewSong.created_at.desc(), NewSong.id.desc()).all()
    result = []
    for r in rows:
        item = r.to_dict()
        item["count"] = counter.get(groups.key_for(r.song_title, r.artist), 0)
        result.append(item)
    return result


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


def clear_hidden_popular(club_id: int) -> int:
    """Полностью удалить все скрытые из "Популярных" записи клуба (без восстановления).
    "История за час" не трогаем. Возвращает, сколько записей удалено."""
    removed = SongListHidden.query.filter_by(club_id=club_id, kind="popular").update({"kind": "popular_archived"}, synchronize_session=False)
    db.session.commit()
    return removed


def hidden_popular(club_id: int) -> list[dict]:
    rows = (
        SongListHidden.query.filter_by(club_id=club_id, kind="popular")
        .order_by(SongListHidden.created_at.desc())
        .all()
    )
    return [r.to_dict() for r in rows]


def set_new(club_id: int, song_title: str, artist, is_new: bool, kind: str = "new") -> bool:
    """Отметить / снять песню в списке "new" (Новинки) или "duet" (Дуэты).
    Одна песня в клубе — только в одном списке."""
    key = norm_key(song_title, artist)
    existing = NewSong.query.filter_by(club_id=club_id, norm_key=key).first()
    if is_new:
        if existing is not None and existing.kind == kind:
            return True
        if existing is not None:
            db.session.delete(existing)
            db.session.commit()
        db.session.add(NewSong(club_id=club_id, song_title=song_title.strip(), artist=(artist or "").strip() or None, norm_key=key, kind=kind))
        db.session.commit()
        # Лимит только у "Новинок" (до NEW_SONGS_LIMIT, новая вытесняет самую старую).
        # "Дуэты" без лимита — постоянный список, песню убирает ведущий.
        if kind == "new":
            extra = (
                NewSong.query.filter_by(club_id=club_id, kind="new")
                .order_by(NewSong.created_at.desc(), NewSong.id.desc())
                .offset(NEW_SONGS_LIMIT)
                .all()
            )
            if extra:
                for row in extra:
                    db.session.delete(row)
                db.session.commit()
    elif existing is not None and existing.kind == kind:
        db.session.delete(existing)
        db.session.commit()
    return is_new


def _split_title_artist(text: str):
    """Строка "Название — Исполнитель" (тире с пробелами; также - и –). Без тире — только название."""
    parts = re.split(r"\s+[—–-]\s+", text.strip(), maxsplit=1)
    title = parts[0].strip()
    artist = parts[1].strip() if len(parts) > 1 and parts[1].strip() else None
    return title, artist


def bulk_add(club_id: int, lines: list, kind: str = "new"):
    """Массовое добавление в "Новинки" или "Дуэты". Песня, которая уже есть в каком-либо списке
    или повторяется в самом списке строк, пропускается. Возвращает (добавлено, пропущено)."""
    added, skipped, seen = [], [], set()
    for raw in lines:
        if not isinstance(raw, str) or not raw.strip():
            continue
        title, artist = _split_title_artist(raw)
        if not title:
            continue
        label = f"{title} — {artist}" if artist else title
        key = norm_key(title, artist)
        if key in seen or NewSong.query.filter_by(club_id=club_id, norm_key=key).first() is not None:
            skipped.append(label)
            continue
        seen.add(key)
        set_new(club_id, title, artist, True, kind=kind)
        added.append(label)
    return added, skipped
