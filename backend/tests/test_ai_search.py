"""
Тесты AI-поиска (Role 3/4/5, аудит-отчёт п.2). Сетевые вызовы к Claude и
iTunes Search API подменяются — как и в старом проекте (tests_bot/test_ai_search.py
для прежней версии на Genius), это внешние сервисы, оркестрация проверяется
отдельно от реальной сети (живой прогон с настоящими ключами — в отдельном
E2E-скрипте).
"""
from services import ai_search_service


def _headers(token):
    return {"Authorization": f"Bearer {token}"}


def _guest_session(client, club_id, table_no=5):
    resp = client.post("/api/guest/session", json={"club_id": club_id, "table_no": table_no})
    return resp.get_json()["data"]


def test_no_anthropic_key_returns_empty_without_crashing(client, db, club, app, monkeypatch):
    """Без ANTHROPIC_API_KEY шаг анализа текста Клодом пропускается, и
    поиск честно уходит в iTunes с исходным текстом гостя как есть (iTunes
    ключа не требует вообще). Здесь iTunes подменена на "ничего не нашла",
    чтобы не дёргать реальную сеть, — проверяем именно что не падает."""
    app.config["ANTHROPIC_API_KEY"] = None

    def fake_search_itunes(query, limit):
        return []

    monkeypatch.setattr(ai_search_service, "_search_itunes", fake_search_itunes)

    session = _guest_session(client, club.club_id)
    resp = client.post(
        "/api/guest/songs/ai-search", json={"text": "дима билан машины"}, headers=_headers(session["token"]),
    )
    assert resp.status_code == 200
    assert resp.get_json()["data"] == []


def test_dedupes_results_across_queries(client, db, club, monkeypatch):
    def fake_ask_claude(text):
        return ["Дима Билан - Билет на самолет", "Билан Билет на самолет"]

    def fake_search_itunes(query, limit):
        return [
            {"title": "Билет на самолет", "artist": "Дима Билан", "itunes_url": "u1"},
            {"title": "Пьяная ночь", "artist": "Дима Билан", "itunes_url": "u2"},
        ]

    monkeypatch.setattr(ai_search_service, "_ask_claude", fake_ask_claude)
    monkeypatch.setattr(ai_search_service, "_search_itunes", fake_search_itunes)

    session = _guest_session(client, club.club_id)
    resp = client.post(
        "/api/guest/songs/ai-search", json={"text": "дима билан машины"}, headers=_headers(session["token"]),
    )
    data = resp.get_json()["data"]
    assert len(data) == 2
    assert {r["title"] for r in data} == {"Билет на самолет", "Пьяная ночь"}


def test_never_returns_more_than_max_results(client, db, club, monkeypatch):
    def fake_ask_claude(text):
        return ["q1", "q2", "q3"]

    def fake_search_itunes(query, limit):
        return [{"title": f"{query}-song-{i}", "artist": "X", "itunes_url": "u"} for i in range(limit)]

    monkeypatch.setattr(ai_search_service, "_ask_claude", fake_ask_claude)
    monkeypatch.setattr(ai_search_service, "_search_itunes", fake_search_itunes)

    session = _guest_session(client, club.club_id)
    resp = client.post(
        "/api/guest/songs/ai-search", json={"text": "что угодно"}, headers=_headers(session["token"]),
    )
    assert len(resp.get_json()["data"]) == ai_search_service.MAX_RESULTS


def test_fewer_than_three_results_not_padded(client, db, club, monkeypatch):
    """Аудит п.2 / старое ТЗ п.5: меньше найдено — показываем фактическое
    количество, не выдумываем недостающее до 3."""

    def fake_ask_claude(text):
        return ["q1"]

    def fake_search_itunes(query, limit):
        return [{"title": "Единственный трек", "artist": "Кто-то", "itunes_url": "u"}]

    monkeypatch.setattr(ai_search_service, "_ask_claude", fake_ask_claude)
    monkeypatch.setattr(ai_search_service, "_search_itunes", fake_search_itunes)

    session = _guest_session(client, club.club_id)
    resp = client.post(
        "/api/guest/songs/ai-search", json={"text": "непонятное описание"}, headers=_headers(session["token"]),
    )
    data = resp.get_json()["data"]
    assert len(data) == 1
    assert data[0]["title"] == "Единственный трек"


def test_falls_back_to_raw_text_when_claude_finds_nothing(client, db, club, monkeypatch):
    calls = []

    def fake_ask_claude(text):
        return []

    def fake_search_itunes(query, limit):
        calls.append(query)
        return [{"title": "Что-то нашлось", "artist": None, "itunes_url": "u"}]

    monkeypatch.setattr(ai_search_service, "_ask_claude", fake_ask_claude)
    monkeypatch.setattr(ai_search_service, "_search_itunes", fake_search_itunes)

    session = _guest_session(client, club.club_id)
    resp = client.post(
        "/api/guest/songs/ai-search", json={"text": "оригинальный текст гостя"}, headers=_headers(session["token"]),
    )
    assert calls == ["оригинальный текст гостя"]
    assert len(resp.get_json()["data"]) == 1


def test_empty_text_rejected(client, db, club):
    session = _guest_session(client, club.club_id)
    resp = client.post("/api/guest/songs/ai-search", json={"text": "  "}, headers=_headers(session["token"]))
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "VALIDATION_ERROR"

    resp = client.post("/api/guest/songs/ai-search", json={}, headers=_headers(session["token"]))
    assert resp.status_code == 400


def test_itunes_checks_every_store_and_merges_results(app, monkeypatch):
    """Живой случай, из-за которого это появилось: румынская колядка
    "Galbenă Gutuie" не нашлась в молдавском магазине Apple Music, но
    нашлась в румынском. _search_itunes должна проверить все магазины
    из списка (не останавливаясь на первом непустом) и вернуть найденное."""
    calls = []

    class FakeResponse:
        def __init__(self, results):
            self.status_code = 200
            self._results = results

        def json(self):
            return {"results": self._results}

    def fake_get(url, params, timeout):
        calls.append(params["country"])
        if params["country"] == "RO":
            return FakeResponse([{"trackName": "Galbenă Gutuie", "artistName": "Maria Moldovan", "trackViewUrl": "u"}])
        return FakeResponse([])  # MD/RU/US — пусто

    monkeypatch.setattr(ai_search_service.requests, "get", fake_get)

    with app.app_context():
        app.config["ITUNES_COUNTRIES"] = ["MD", "RO", "RU", "US"]
        results = ai_search_service._search_itunes("galbena gutuie", limit=5)

    assert calls == ["MD", "RO", "RU", "US"]  # проверили все, не остановились на RO
    assert len(results) == 1
    assert results[0]["title"] == "Galbenă Gutuie"


def test_itunes_returns_empty_when_no_store_has_it(app, monkeypatch):
    def fake_get(url, params, timeout):
        return type("R", (), {"status_code": 200, "json": lambda self: {"results": []}})()

    monkeypatch.setattr(ai_search_service.requests, "get", fake_get)

    with app.app_context():
        app.config["ITUNES_COUNTRIES"] = ["MD", "RO"]
        results = ai_search_service._search_itunes("что-то совсем не найдётся", limit=5)

    assert results == []


def test_itunes_ranks_real_match_above_unrelated_early_store_hit(app, monkeypatch):
    """Живой случай "oriunde ai fi": молдавский магазин вернул случайные
    песни группы Voltaj (ни одного общего слова с запросом), а нужная
    песня Дана Балана нашлась только в американском магазине. Раньше
    поиск останавливался на первом непустом магазине и показывал только
    Voltaj; теперь должен объединить всё и поставить настоящее
    совпадение выше случайного."""

    class FakeResponse:
        def __init__(self, results):
            self.status_code = 200
            self._results = results

        def json(self):
            return {"results": self._results}

    def fake_get(url, params, timeout):
        if params["country"] == "MD":
            return FakeResponse([
                {"trackName": "MSD2", "artistName": "Voltaj", "trackViewUrl": "u1"},
                {"trackName": "Crede", "artistName": "Voltaj", "trackViewUrl": "u2"},
            ])
        if params["country"] == "US":
            return FakeResponse([
                {"trackName": "Oriunde ai fi", "artistName": "Dan Balan", "trackViewUrl": "u3"},
            ])
        return FakeResponse([])  # RO/RU — пусто

    monkeypatch.setattr(ai_search_service.requests, "get", fake_get)

    with app.app_context():
        app.config["ITUNES_COUNTRIES"] = ["MD", "RO", "RU", "US"]
        results = ai_search_service._search_itunes("oriunde ai fi", limit=5)

    assert len(results) == 3
    assert results[0]["title"] == "Oriunde ai fi"
    assert results[0]["artist"] == "Dan Balan"


def test_youtube_link_resolves_via_oembed_and_skips_claude(client, db, club, monkeypatch):
    """Гость вставил прямую ссылку на Ютуб — Клод и iTunes не должны
    вызываться вообще, название берётся прямо из oEmbed."""
    claude_called = []

    def fake_ask_claude(text):
        claude_called.append(text)
        return []

    class FakeResponse:
        status_code = 200

        def json(self):
            return {"title": "Ирина Круг - Тебе моя последняя любовь", "author_name": "Ирина Круг"}

    def fake_get(url, params, timeout):
        assert url == "https://www.youtube.com/oembed"
        assert params["url"] == "https://youtu.be/abc123"
        return FakeResponse()

    monkeypatch.setattr(ai_search_service, "_ask_claude", fake_ask_claude)
    monkeypatch.setattr(ai_search_service.requests, "get", fake_get)

    session = _guest_session(client, club.club_id)
    resp = client.post(
        "/api/guest/songs/ai-search", json={"text": "https://youtu.be/abc123"}, headers=_headers(session["token"]),
    )
    data = resp.get_json()["data"]
    assert claude_called == []
    assert len(data) == 1
    assert data[0]["title"] == "Ирина Круг - Тебе моя последняя любовь"
    assert data[0]["artist"] == "Ирина Круг"


def test_apple_music_link_uses_track_id_from_i_param(client, db, club, monkeypatch):
    class FakeResponse:
        status_code = 200

        def json(self):
            return {"results": [{"trackName": "Boschetar", "artistName": "Valentin Boghean"}]}

    def fake_get(url, params, timeout):
        assert url == "https://itunes.apple.com/lookup"
        assert params["id"] == "1706558355"
        return FakeResponse()

    monkeypatch.setattr(ai_search_service.requests, "get", fake_get)

    session = _guest_session(client, club.club_id)
    link = "https://music.apple.com/ru/album/boschetar/1706558354?i=1706558355"
    resp = client.post(
        "/api/guest/songs/ai-search", json={"text": link}, headers=_headers(session["token"]),
    )
    data = resp.get_json()["data"]
    assert len(data) == 1
    assert data[0]["title"] == "Boschetar"
    assert data[0]["artist"] == "Valentin Boghean"


def test_spotify_link_has_no_artist_field(client, db, club, monkeypatch):
    class FakeResponse:
        status_code = 200

        def json(self):
            return {"title": "Boschetar"}

    def fake_get(url, params, timeout):
        assert url == "https://open.spotify.com/oembed"
        return FakeResponse()

    monkeypatch.setattr(ai_search_service.requests, "get", fake_get)

    session = _guest_session(client, club.club_id)
    link = "https://open.spotify.com/track/0WDDFvbmLKx8tyiWYbObyx"
    resp = client.post(
        "/api/guest/songs/ai-search", json={"text": link}, headers=_headers(session["token"]),
    )
    data = resp.get_json()["data"]
    assert len(data) == 1
    assert data[0]["title"] == "Boschetar"
    assert data[0]["artist"] is None


def test_link_that_resolves_to_nothing_returns_empty_not_fabricated(client, db, club, monkeypatch):
    class FakeResponse:
        status_code = 404

        def json(self):
            return {}

    monkeypatch.setattr(ai_search_service.requests, "get", lambda *a, **k: FakeResponse())

    session = _guest_session(client, club.club_id)
    resp = client.post(
        "/api/guest/songs/ai-search",
        json={"text": "https://youtu.be/deleted-video"},
        headers=_headers(session["token"]),
    )
    assert resp.get_json()["data"] == []


def test_plain_text_with_url_word_is_not_treated_as_link(client, db, club, monkeypatch):
    """Ссылка должна занимать всё поле целиком — иначе это обычное текстовое
    описание (например, гость мог упомянуть youtube мимоходом)."""

    def fake_ask_claude(text):
        return []

    def fake_search_itunes(query, limit):
        return [{"title": "Найдено", "artist": None, "itunes_url": "u"}]

    monkeypatch.setattr(ai_search_service, "_ask_claude", fake_ask_claude)
    monkeypatch.setattr(ai_search_service, "_search_itunes", fake_search_itunes)

    session = _guest_session(client, club.club_id)
    resp = client.post(
        "/api/guest/songs/ai-search",
        json={"text": "видел в ютубе клип с песней про машины"},
        headers=_headers(session["token"]),
    )
    data = resp.get_json()["data"]
    assert len(data) == 1
    assert data[0]["title"] == "Найдено"


def test_available_to_no_table_guest(client, db, club, monkeypatch):
    """Role 5 — старая команда /ai не проверяла роль, только наличие venue_id."""

    def fake_ask_claude(text):
        return []

    def fake_search_itunes(query, limit):
        return [{"title": "Найдено", "artist": None, "itunes_url": "u"}]

    monkeypatch.setattr(ai_search_service, "_ask_claude", fake_ask_claude)
    monkeypatch.setattr(ai_search_service, "_search_itunes", fake_search_itunes)

    session = _guest_session(client, club.club_id, table_no=None)
    resp = client.post(
        "/api/guest/songs/ai-search", json={"text": "что-то"}, headers=_headers(session["token"]),
    )
    assert resp.status_code == 200
    assert len(resp.get_json()["data"]) == 1


# --- Поиск по скриншоту (третий режим, ai_search_service.screenshot_powered_search) ---

def test_screenshot_search_happy_path(client, db, club, monkeypatch):
    """Клод разглядел на картинке "исполнитель - название" -> iTunes нашёл трек."""
    seen_images = []

    def fake_ask_claude_vision(image_base64, media_type):
        seen_images.append((image_base64, media_type))
        return ["Дима Билан - Не молчи"]

    def fake_search_itunes(query, limit):
        return [{"title": "Не молчи", "artist": "Дима Билан", "itunes_url": "u"}]

    monkeypatch.setattr(ai_search_service, "_ask_claude_vision", fake_ask_claude_vision)
    monkeypatch.setattr(ai_search_service, "_search_itunes", fake_search_itunes)

    session = _guest_session(client, club.club_id)
    resp = client.post(
        "/api/guest/songs/screenshot-search",
        json={"image_base64": "ZmFrZQ==", "media_type": "image/jpeg"},
        headers=_headers(session["token"]),
    )
    assert resp.status_code == 200
    data = resp.get_json()["data"]
    assert len(data) == 1
    assert data[0]["title"] == "Не молчи"
    assert seen_images == [("ZmFrZQ==", "image/jpeg")]


def test_screenshot_search_no_claude_key_returns_empty(client, db, club, app):
    """Без ANTHROPIC_API_KEY распознавание картинки пропускается — честно
    пустой результат, без выдуманного текста для fallback (в отличие от
    текстового поиска, здесь у нас вообще нет исходного текста гостя)."""
    app.config["ANTHROPIC_API_KEY"] = None

    session = _guest_session(client, club.club_id)
    resp = client.post(
        "/api/guest/songs/screenshot-search",
        json={"image_base64": "ZmFrZQ==", "media_type": "image/jpeg"},
        headers=_headers(session["token"]),
    )
    assert resp.status_code == 200
    assert resp.get_json()["data"] == []


def test_screenshot_search_nothing_recognized_on_image(client, db, club, monkeypatch):
    """Клод посмотрел на картинку, но не разглядел там ничего похожего на
    песню (queries: [])."""
    def fake_ask_claude_vision(image_base64, media_type):
        return []

    monkeypatch.setattr(ai_search_service, "_ask_claude_vision", fake_ask_claude_vision)

    session = _guest_session(client, club.club_id)
    resp = client.post(
        "/api/guest/songs/screenshot-search",
        json={"image_base64": "ZmFrZQ==", "media_type": "image/png"},
        headers=_headers(session["token"]),
    )
    assert resp.status_code == 200
    assert resp.get_json()["data"] == []


def test_screenshot_search_validation(client, db, club):
    session = _guest_session(client, club.club_id)

    resp = client.post(
        "/api/guest/songs/screenshot-search", json={}, headers=_headers(session["token"]),
    )
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "VALIDATION_ERROR"

    resp = client.post(
        "/api/guest/songs/screenshot-search",
        json={"image_base64": "ZmFrZQ==", "media_type": "image/gif"},
        headers=_headers(session["token"]),
    )
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "VALIDATION_ERROR"

    resp = client.post(
        "/api/guest/songs/screenshot-search",
        json={"image_base64": "x" * 8_000_001, "media_type": "image/jpeg"},
        headers=_headers(session["token"]),
    )
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "IMAGE_TOO_LARGE"
