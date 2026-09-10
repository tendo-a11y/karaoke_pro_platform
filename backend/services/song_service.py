"""
Каталог песен и поиск по нему (Role 3/4/5, аудит-отчёт п.1: "Поиск песен").

1:1 перенос РАБОТАЮЩЕЙ бизнес-логики старого бота:
  - utils.py::_detect_delimiter / _parse_songs_from_content / parse_csv_songs
  - database.py::bulk_add_songs
  - database.py::search_songs (строка 1688 — ТРЕТЬЕ, фактически исполняемое
    определение метода с этим именем в старом классе Database; первые два
    определения на строках 1242 и 1473 являются мёртвым кодом, недостижимым
    в Python из-за переопределения метода в одном классе, и сознательно НЕ
    переносятся — см. отчёт аудита, находка №4).

Сознательно НЕ перенесено:
  - Каталог никогда не читается из VirtualDJ (в старом коде тоже не читался
    — только ручной CSV), поэтому здесь нет никакой интеграции с vdj_bridge.
  - Спецпрефиксы "kj:" и "replace:" старого инлайн-поиска (bot.py) — это
    отдельные функции (ручное добавление KJ и замена песни, аудит пп. NOT
    DONE), а не часть самого поиска; "replace:" вдобавок в старом коде не
    проверял владельца заказа (аудит, находка №3) — эта уязвимость новой
    архитектуре не наследуется, потому что сама функция замены здесь не
    реализуется.
"""
import csv
import io

from extensions import db
from models import Song

MAX_SEARCH_RESULTS = 50  # старое: database.py:1688 limit: int = 50


def _detect_delimiter(content: str) -> str:
    """1:1 перенос utils.py::_detect_delimiter."""
    first_line = content.split("\n")[0]
    return ";" if first_line.count(";") > first_line.count(",") else ","


def _parse_songs_from_content(content: str) -> list[dict]:
    """1:1 перенос utils.py::_parse_songs_from_content."""
    delimiter = _detect_delimiter(content)
    reader = csv.DictReader(io.StringIO(content), delimiter=delimiter)
    songs = []
    for row in reader:
        row_lower = {k.strip().lower(): v for k, v in row.items() if k}
        artist_val = row_lower.get("artist") or row_lower.get("artis", "")
        title_val = row_lower.get("title", "")
        if artist_val or title_val:
            songs.append({
                "artist": (artist_val or "").strip(),
                "title": (title_val or "").strip(),
                "code": (row_lower.get("code") or "").strip() or None,
            })
    return songs


def parse_csv_songs(file_content: bytes) -> tuple[list[dict], str]:
    """1:1 перенос utils.py::parse_csv_songs (та же цепочка кодировок)."""
    for encoding in ("utf-8", "utf-8-sig", "windows-1251"):
        try:
            content = file_content.decode(encoding)
            songs = _parse_songs_from_content(content)
            if songs:
                return songs, f"Успешно загружено {len(songs)} песен"
            return [], "Файл пуст или неверный формат (нет колонок artist/artis и title)"
        except UnicodeDecodeError:
            continue
        except Exception as e:  # noqa: BLE001 — старое поведение: любая ошибка парсинга -> сообщение, не 500
            return [], f"Ошибка парсинга: {e}"
    return [], "Ошибка декодирования файла"


def bulk_add_songs(club_id: int, songs: list[dict]) -> int:
    """
    1:1 перенос database.py::bulk_add_songs — дедупликация ТОЛЬКО по
    title.lower() (не по паре artist+title — так было и в старом коде,
    сознательно не улучшается, чтобы не изменить наблюдаемое поведение
    импорта, на которое клубы уже полагаются).
    """
    existing_titles = {
        (title or "").lower()
        for (title,) in db.session.query(Song.title).filter_by(club_id=club_id).all()
    }
    new_songs = [s for s in songs if (s.get("title") or "").lower() not in existing_titles]

    for s in new_songs:
        db.session.add(Song(club_id=club_id, artist=s.get("artist") or "", title=s["title"], code=s.get("code")))
    if new_songs:
        db.session.commit()

    return len(new_songs)


def search_songs(club_id: int, query: str, limit: int = MAX_SEARCH_RESULTS) -> list[Song]:
    """
    1:1 перенос РАБОЧЕЙ версии database.py::search_songs (строка 1688):
    подстрока (casefold, без учёта регистра) по объединению
    "artist title code artist - title", алфавитная сортировка по
    (artist, title) до фильтрации, обрезка по limit. Никакого
    релевантность-скоринга в старом коде не было — сюда он тоже не
    добавляется.
    """
    if not query:
        return []

    query_norm = " ".join(query.split()).casefold()
    if not query_norm:
        return []

    rows = Song.query.filter_by(club_id=club_id).order_by(Song.artist, Song.title).all()

    matches = []
    for row in rows:
        artist = (row.artist or "").strip()
        title = (row.title or "").strip()
        code = (row.code or "").strip()
        combined = f"{artist} - {title}".strip(" -")

        haystack = " ".join(filter(None, [artist, title, code, combined])).casefold()
        if query_norm in haystack:
            matches.append(row)
            if len(matches) >= limit:
                break

    return matches
