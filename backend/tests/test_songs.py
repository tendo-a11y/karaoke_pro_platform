"""
Тесты поиска песен (Role 3/4/5, аудит-отчёт п.1). Каталог наполняется
только через CSV-импорт KJ (services/song_service.py::parse_csv_songs,
bulk_add_songs) — VirtualDJ как источник не используется, как и в старом
коде.
"""
import io

from models import Song


def _headers(token):
    return {"Authorization": f"Bearer {token}"}


def _guest_session(client, club_id, table_no=5):
    resp = client.post("/api/guest/session", json={"club_id": club_id, "table_no": table_no})
    return resp.get_json()["data"]


def _upload_csv(client, kj_headers, content: bytes, filename="songs.csv"):
    return client.post(
        "/api/kj/songs/import",
        data={"file": (io.BytesIO(content), filename)},
        headers=kj_headers,
        content_type="multipart/form-data",
    )


def test_csv_import_adds_songs_and_dedupes_by_title(client, db, club, kj):
    csv_content = (
        "artist,title,code\n"
        "Imagine Dragons,Believer,101\n"
        "Coldplay,Yellow,102\n"
    ).encode("utf-8")

    resp = _upload_csv(client, kj["headers"], csv_content)
    assert resp.status_code == 201
    data = resp.get_json()["data"]
    assert data["added"] == 2
    assert data["skipped"] == 0

    songs = Song.query.filter_by(club_id=club.club_id).all()
    assert len(songs) == 2

    # Повторная загрузка с одним новым и одним дублирующимся по title (не
    # важно, что artist/code отличаются — старое поведение дедуплицирует
    # только по title.lower()).
    csv_content_2 = (
        "artist,title,code\n"
        "Other Artist,Believer,999\n"
        "Dua Lipa,Levitating,103\n"
    ).encode("utf-8")
    resp = _upload_csv(client, kj["headers"], csv_content_2)
    data = resp.get_json()["data"]
    assert data["added"] == 1
    assert data["skipped"] == 1

    songs = Song.query.filter_by(club_id=club.club_id).all()
    assert len(songs) == 3


def test_csv_import_semicolon_delimiter_and_artis_typo_column(client, db, club, kj):
    """Старое: utils.py::_parse_songs_from_content принимает опечатку
    'artis' вместо 'artist' и автоопределяет разделитель ';' против ','."""
    csv_content = "artis;title;code\nEminem;Lose Yourself;201\n".encode("utf-8")
    resp = _upload_csv(client, kj["headers"], csv_content)
    data = resp.get_json()["data"]
    assert data["added"] == 1

    song = Song.query.filter_by(club_id=club.club_id).first()
    assert song.artist == "Eminem"
    assert song.title == "Lose Yourself"


def test_csv_import_rejects_non_csv_extension(client, db, club, kj):
    resp = _upload_csv(client, kj["headers"], b"whatever", filename="songs.txt")
    assert resp.status_code == 400


def test_csv_import_empty_file_returns_error(client, db, club, kj):
    resp = _upload_csv(client, kj["headers"], b"just,a,header\n")
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "CSV_EMPTY_OR_INVALID"


def test_kj_cannot_import_songs_for_other_club(client, db, club, other_club, kj):
    """kj привязан к club, а не к other_club — g.club_id в токене решает
    club_id импорта, подменить club_id из запроса нельзя (в теле его и нет)."""
    resp = _upload_csv(client, kj["headers"], b"artist,title\nA,B\n")
    assert resp.status_code == 201
    songs = Song.query.filter_by(club_id=other_club.club_id).all()
    assert songs == []


def _seed_songs(db, club_id):
    db.session.add_all([
        Song(club_id=club_id, artist="Imagine Dragons", title="Believer", code="101"),
        Song(club_id=club_id, artist="Imagine Dragons", title="Radioactive", code="102"),
        Song(club_id=club_id, artist="Coldplay", title="Yellow", code="103"),
        Song(club_id=club_id, artist="", title="Despacito", code="104"),
    ])
    db.session.commit()


def test_search_by_artist_substring(client, db, club):
    _seed_songs(db, club.club_id)
    session = _guest_session(client, club.club_id)
    resp = client.get("/api/guest/songs/search?q=imagine", headers=_headers(session["token"]))
    titles = {s["title"] for s in resp.get_json()["data"]}
    assert titles == {"Believer", "Radioactive"}


def test_search_by_title_substring_case_insensitive(client, db, club):
    _seed_songs(db, club.club_id)
    session = _guest_session(client, club.club_id)
    resp = client.get("/api/guest/songs/search?q=YELLOW", headers=_headers(session["token"]))
    data = resp.get_json()["data"]
    assert len(data) == 1
    assert data[0]["title"] == "Yellow"


def test_search_song_without_artist(client, db, club):
    _seed_songs(db, club.club_id)
    session = _guest_session(client, club.club_id)
    resp = client.get("/api/guest/songs/search?q=despacito", headers=_headers(session["token"]))
    data = resp.get_json()["data"]
    assert len(data) == 1
    assert data[0]["artist"] == ""


def test_search_empty_query_returns_empty_list(client, db, club):
    _seed_songs(db, club.club_id)
    session = _guest_session(client, club.club_id)
    resp = client.get("/api/guest/songs/search?q=", headers=_headers(session["token"]))
    assert resp.get_json()["data"] == []

    resp = client.get("/api/guest/songs/search", headers=_headers(session["token"]))
    assert resp.get_json()["data"] == []


def test_search_no_matches_returns_empty_list(client, db, club):
    _seed_songs(db, club.club_id)
    session = _guest_session(client, club.club_id)
    resp = client.get("/api/guest/songs/search?q=zzz_nonexistent", headers=_headers(session["token"]))
    assert resp.get_json()["data"] == []


def test_search_respects_songs_from_own_club_only(client, db, club, other_club):
    _seed_songs(db, club.club_id)
    db.session.add(Song(club_id=other_club.club_id, artist="Imagine Dragons", title="Thunder"))
    db.session.commit()

    session = _guest_session(client, club.club_id)
    resp = client.get("/api/guest/songs/search?q=imagine", headers=_headers(session["token"]))
    titles = {s["title"] for s in resp.get_json()["data"]}
    assert "Thunder" not in titles


def test_search_results_alphabetically_sorted(client, db, club):
    db.session.add_all([
        Song(club_id=club.club_id, artist="Zebra Band", title="Song A"),
        Song(club_id=club.club_id, artist="Abba", title="Song B"),
    ])
    db.session.commit()
    session = _guest_session(client, club.club_id)
    resp = client.get("/api/guest/songs/search?q=song", headers=_headers(session["token"]))
    artists = [s["artist"] for s in resp.get_json()["data"]]
    assert artists == ["Abba", "Zebra Band"]


def test_search_respects_limit_50(client, db, club):
    for i in range(60):
        db.session.add(Song(club_id=club.club_id, artist="Bulk Artist", title=f"Song {i:02d}"))
    db.session.commit()

    session = _guest_session(client, club.club_id)
    resp = client.get("/api/guest/songs/search?q=song", headers=_headers(session["token"]))
    data = resp.get_json()["data"]
    assert len(data) == 50


def test_search_available_to_no_table_guest(client, db, club):
    """Role 5 (без стола) — поиск в старом коде не ограничивался ролью,
    только наличием venue_id/сессии клуба."""
    _seed_songs(db, club.club_id)
    session = _guest_session(client, club.club_id, table_no=None)
    resp = client.get("/api/guest/songs/search?q=coldplay", headers=_headers(session["token"]))
    assert resp.status_code == 200
    assert len(resp.get_json()["data"]) == 1
