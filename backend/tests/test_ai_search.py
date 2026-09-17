"""
Тесты AI-поиска (Role 3/4/5, аудит-отчёт п.2).

2026-09-17: файл переписан во второй раз вслед за ai_search_service.py.
Первый раз убрали внешний музыкальный каталог (Genius/iTunes/Apple Music)
совсем — Claude был единственным источником, без проверки. Второй раз, по
явному следующему решению пользователя ("а можем несколько источников
поиска сделать и чтоб Клод принимал решение после результатов всех
источников"), добавили Deezer и MusicBrainz как источники-ПОДСКАЗКА (оба —
открытые бесплатные API без ключей, это НЕ Apple Music/iTunes, явный запрет
их не касается), но решение по-прежнему всегда принимает сам Claude — это
и есть ответ пользователя на уточняющий вопрос ("Клод решает всегда,
источники — подсказка").

Пайплайн, который тестируется ниже:
  1. _ask_claude / _ask_claude_vision — первый запрос, Claude предлагает
     1-3 варианта "исполнитель - название". Пусто — дальше вообще ничего
     не вызывается, результат [].
  2. _gather_catalog_hits — Deezer + MusicBrainz опрашиваются по этим
     вариантам, результат — только подсказка.
  3. _ask_claude_to_decide — второй запрос к Claude, с его же вариантами и
     подсказками каталогов, возвращает уже готовые {title, artist} —
     окончательный результат. Разбора строки "исполнитель - название"
     здесь больше нет (в отличие от первой версии с _parse_query) — Claude
     сам возвращает структурированный JSON, поэтому проблема с дефисом в
     имени исполнителя (Ion Aldea-Teodorovici) на этом шаге в принципе не
     может повториться.

Тесты подменяют только сетевые вызовы (requests.get/post через моки
_ask_claude/_ask_claude_vision/_ask_claude_to_decide/_search_deezer/
_search_musicbrainz) — оркестрация проверяется отдельно от реальной сети
(живой прогон с настоящим ключом — в отдельном E2E-скрипте).
"""
from services import ai_search_service


def _headers(token):
    return {"Authorization": f"Bearer {token}"}


def _guest_session(client, club_id, table_no=5):
    resp = client.post("/api/guest/session", json={"club_id": club_id, "table_no": table_no})
    return resp.get_json()["data"]


# --- Основной пайплайн: текстовый AI-поиск ---

def test_no_anthropic_key_returns_empty_without_crashing(client, db, club, app):
    """Без ANTHROPIC_API_KEY даже первый запрос к Claude пропускается — и,
    раз внешние каталоги здесь только подсказка, а не обязательный
    источник, результат честно пустой, без выдумки на основе сырого текста
    гостя."""
    app.config["ANTHROPIC_API_KEY"] = None

    session = _guest_session(client, club.club_id)
    resp = client.post(
        "/api/guest/songs/ai-search", json={"text": "дима билан машины"}, headers=_headers(session["token"]),
    )
    assert resp.status_code == 200
    assert resp.get_json()["data"] == []


def test_claude_decision_used_directly_as_result(client, db, club, monkeypatch):
    """Основной сценарий: первый запрос предлагает вариант, второй
    (решающий) запрос его подтверждает — это и есть окончательный
    результат, уже готовым словарём, без разбора строки."""

    monkeypatch.setattr(ai_search_service, "_ask_claude", lambda text: ["Дима Билан - Билет на самолет"])
    monkeypatch.setattr(ai_search_service, "_gather_catalog_hits", lambda queries, limit_per_source=5: [])
    monkeypatch.setattr(
        ai_search_service, "_ask_claude_to_decide",
        lambda context, guesses, catalog_hits: [{"title": "Билет на самолет", "artist": "Дима Билан"}],
    )

    session = _guest_session(client, club.club_id)
    resp = client.post(
        "/api/guest/songs/ai-search", json={"text": "дима билан билет на самолет"}, headers=_headers(session["token"]),
    )
    data = resp.get_json()["data"]
    assert data == [{"title": "Билет на самолет", "artist": "Дима Билан"}]


def test_hyphenated_artist_name_reaches_decision_step_untouched(client, db, club, monkeypatch):
    """Живой случай, из-за которого раньше меняли способ разбора строки:
    у некоторых исполнителей дефис — часть самого имени (Ion
    Aldea-Teodorovici). Теперь Claude на решающем шаге сам возвращает
    структурированный JSON {title, artist}, разбора строки по дефису в
    коде больше нет вообще — такую ошибку в принципе стало невозможно
    допустить снова на этом уровне."""

    guesses_seen = []

    def fake_decide(context, guesses, catalog_hits):
        guesses_seen.extend(guesses)
        return [{"title": "Focul din vatră", "artist": "Ion Aldea-Teodorovici"}]

    monkeypatch.setattr(ai_search_service, "_ask_claude", lambda text: ["Ion Aldea-Teodorovici - Focul din vatră"])
    monkeypatch.setattr(ai_search_service, "_gather_catalog_hits", lambda queries, limit_per_source=5: [])
    monkeypatch.setattr(ai_search_service, "_ask_claude_to_decide", fake_decide)

    session = _guest_session(client, club.club_id)
    resp = client.post(
        "/api/guest/songs/ai-search",
        json={"text": "Ion Aldea-Teodorovici Focul din vatra"},
        headers=_headers(session["token"]),
    )
    data = resp.get_json()["data"]
    assert guesses_seen == ["Ion Aldea-Teodorovici - Focul din vatră"]
    assert data == [{"title": "Focul din vatră", "artist": "Ion Aldea-Teodorovici"}]


def test_query_without_artist_returns_title_only(client, db, club, monkeypatch):
    monkeypatch.setattr(ai_search_service, "_ask_claude", lambda text: ["Билет на самолет"])
    monkeypatch.setattr(ai_search_service, "_gather_catalog_hits", lambda queries, limit_per_source=5: [])
    monkeypatch.setattr(
        ai_search_service, "_ask_claude_to_decide",
        lambda context, guesses, catalog_hits: [{"title": "Билет на самолет", "artist": None}],
    )

    session = _guest_session(client, club.club_id)
    resp = client.post(
        "/api/guest/songs/ai-search", json={"text": "билет на самолет"}, headers=_headers(session["token"]),
    )
    data = resp.get_json()["data"]
    assert data == [{"title": "Билет на самолет", "artist": None}]


def test_dedupes_results_from_decision_step(client, db, club, monkeypatch):
    """Дедупликация теперь происходит над готовыми словарями от решающего
    запроса, а не над строками до разбора."""
    monkeypatch.setattr(ai_search_service, "_ask_claude", lambda text: ["Дима Билан - Билет на самолет"])
    monkeypatch.setattr(ai_search_service, "_gather_catalog_hits", lambda queries, limit_per_source=5: [])
    monkeypatch.setattr(
        ai_search_service, "_ask_claude_to_decide",
        lambda context, guesses, catalog_hits: [
            {"title": "Билет на самолет", "artist": "Дима Билан"},
            {"title": "Билет На Самолет", "artist": "дима билан"},
        ],
    )

    session = _guest_session(client, club.club_id)
    resp = client.post(
        "/api/guest/songs/ai-search", json={"text": "дима билан"}, headers=_headers(session["token"]),
    )
    data = resp.get_json()["data"]
    assert len(data) == 1


def test_never_returns_more_than_max_results(client, db, club, monkeypatch):
    monkeypatch.setattr(ai_search_service, "_ask_claude", lambda text: ["что-то - угодно"])
    monkeypatch.setattr(ai_search_service, "_gather_catalog_hits", lambda queries, limit_per_source=5: [])
    monkeypatch.setattr(
        ai_search_service, "_ask_claude_to_decide",
        lambda context, guesses, catalog_hits: [
            {"title": f"Песня{i}", "artist": f"Артист{i}"} for i in range(ai_search_service.MAX_RESULTS + 5)
        ],
    )

    session = _guest_session(client, club.club_id)
    resp = client.post(
        "/api/guest/songs/ai-search", json={"text": "что угодно"}, headers=_headers(session["token"]),
    )
    assert len(resp.get_json()["data"]) == ai_search_service.MAX_RESULTS


def test_claude_finds_nothing_skips_catalogs_and_decision_returns_empty(client, db, club, monkeypatch):
    """Аудит п.2 / старое ТЗ п.5, актуально и с каталогами-подсказками:
    если Claude на первом шаге вообще ничего не предложил, спрашивать
    каталоги и решающий запрос не о чем — они не должны даже вызываться, а
    результат честно пустой, а не выдуманный из сырого текста гостя."""
    catalogs_called = []
    decide_called = []

    monkeypatch.setattr(ai_search_service, "_ask_claude", lambda text: [])
    monkeypatch.setattr(
        ai_search_service, "_gather_catalog_hits",
        lambda queries, limit_per_source=5: catalogs_called.append(queries) or [],
    )
    monkeypatch.setattr(
        ai_search_service, "_ask_claude_to_decide",
        lambda context, guesses, catalog_hits: decide_called.append((guesses, catalog_hits)) or [],
    )

    session = _guest_session(client, club.club_id)
    resp = client.post(
        "/api/guest/songs/ai-search", json={"text": "оригинальный текст гостя"}, headers=_headers(session["token"]),
    )
    assert resp.get_json()["data"] == []
    assert catalogs_called == []
    assert decide_called == []


def test_decision_step_finds_nothing_returns_empty_not_fabricated(client, db, club, monkeypatch):
    """Первый запрос предложил вариант, каталоги что-то нашли, но
    решающий запрос Claude в итоге не уверен ни в одном — честно []."""
    monkeypatch.setattr(ai_search_service, "_ask_claude", lambda text: ["Кто-то - Что-то"])
    monkeypatch.setattr(
        ai_search_service, "_gather_catalog_hits",
        lambda queries, limit_per_source=5: [{"title": "Совсем не то", "artist": "Не тот исполнитель"}],
    )
    monkeypatch.setattr(ai_search_service, "_ask_claude_to_decide", lambda context, guesses, catalog_hits: [])

    session = _guest_session(client, club.club_id)
    resp = client.post(
        "/api/guest/songs/ai-search", json={"text": "оригинальный текст гостя"}, headers=_headers(session["token"]),
    )
    assert resp.get_json()["data"] == []


def test_decision_step_can_answer_from_own_knowledge_when_catalogs_empty(client, db, club, monkeypatch):
    """Ключевое правило, ради которого всё затевалось ("Клод решает
    всегда, источники — подсказка"): даже если оба каталога ничего не
    нашли (ровно случай регионального репертуара вроде "Focul din
    vatră"), Claude на решающем шаге вправе всё равно ответить из
    собственного знания — это не должно давать пустой результат просто
    потому, что подсказки оказались пустыми."""
    monkeypatch.setattr(ai_search_service, "_ask_claude", lambda text: ["Ion Aldea-Teodorovici - Focul din vatră"])
    monkeypatch.setattr(ai_search_service, "_gather_catalog_hits", lambda queries, limit_per_source=5: [])
    monkeypatch.setattr(
        ai_search_service, "_ask_claude_to_decide",
        lambda context, guesses, catalog_hits: [{"title": "Focul din vatră", "artist": "Ion Aldea-Teodorovici"}]
        if catalog_hits == [] else [],
    )

    session = _guest_session(client, club.club_id)
    resp = client.post(
        "/api/guest/songs/ai-search",
        json={"text": "Ion Aldea-Teodorovici Focul din vatra"},
        headers=_headers(session["token"]),
    )
    data = resp.get_json()["data"]
    assert data == [{"title": "Focul din vatră", "artist": "Ion Aldea-Teodorovici"}]


def test_empty_text_rejected(client, db, club):
    session = _guest_session(client, club.club_id)
    resp = client.post("/api/guest/songs/ai-search", json={"text": "  "}, headers=_headers(session["token"]))
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "VALIDATION_ERROR"

    resp = client.post("/api/guest/songs/ai-search", json={}, headers=_headers(session["token"]))
    assert resp.status_code == 400


def test_youtube_link_resolves_via_oembed_and_skips_claude_and_catalogs(client, db, club, monkeypatch):
    """Гость вставил прямую ссылку на Ютуб — ни Claude, ни каталоги вообще
    не должны вызываться, название берётся прямо из oEmbed."""
    claude_called = []
    catalogs_called = []

    monkeypatch.setattr(ai_search_service, "_ask_claude", lambda text: claude_called.append(text) or [])
    monkeypatch.setattr(
        ai_search_service, "_gather_catalog_hits",
        lambda queries, limit_per_source=5: catalogs_called.append(queries) or [],
    )

    class FakeResponse:
        status_code = 200

        def json(self):
            return {"title": "Ирина Круг - Тебе моя последняя любовь", "author_name": "Ирина Круг"}

    def fake_get(url, params, timeout):
        assert url == "https://www.youtube.com/oembed"
        assert params["url"] == "https://youtu.be/abc123"
        return FakeResponse()

    monkeypatch.setattr(ai_search_service.requests, "get", fake_get)

    session = _guest_session(client, club.club_id)
    resp = client.post(
        "/api/guest/songs/ai-search", json={"text": "https://youtu.be/abc123"}, headers=_headers(session["token"]),
    )
    data = resp.get_json()["data"]
    assert claude_called == []
    assert catalogs_called == []
    assert len(data) == 1
    assert data[0]["title"] == "Ирина Круг - Тебе моя последняя любовь"
    assert data[0]["artist"] == "Ирина Круг"


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


def test_apple_music_link_is_not_treated_as_a_link_at_all(client, db, club, monkeypatch):
    """2026-09-17, явное решение пользователя: Apple Music/iTunes нельзя
    использовать вообще, даже как способ прочитать название по ссылке,
    которую сам гость вставил. Такая ссылка должна уйти обычным текстом на
    разбор Claude (и дальше через тот же пайплайн с каталогами-подсказками
    и решающим запросом), а не в специальную обработку ссылок."""
    seen_texts = []

    monkeypatch.setattr(ai_search_service, "_ask_claude", lambda text: seen_texts.append(text) or ["Valentin Boghean - Boschetar"])
    monkeypatch.setattr(ai_search_service, "_gather_catalog_hits", lambda queries, limit_per_source=5: [])
    monkeypatch.setattr(
        ai_search_service, "_ask_claude_to_decide",
        lambda context, guesses, catalog_hits: [{"title": "Boschetar", "artist": "Valentin Boghean"}],
    )
    monkeypatch.setattr(
        ai_search_service.requests, "get",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("не должно быть сетевых вызовов к Apple/iTunes")),
    )

    session = _guest_session(client, club.club_id)
    link = "https://music.apple.com/ru/album/boschetar/1706558354?i=1706558355"
    resp = client.post(
        "/api/guest/songs/ai-search", json={"text": link}, headers=_headers(session["token"]),
    )
    data = resp.get_json()["data"]
    assert seen_texts == [link]
    assert data == [{"title": "Boschetar", "artist": "Valentin Boghean"}]


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
    monkeypatch.setattr(ai_search_service, "_ask_claude", lambda text: ["Кто-то - Найдено"])
    monkeypatch.setattr(ai_search_service, "_gather_catalog_hits", lambda queries, limit_per_source=5: [])
    monkeypatch.setattr(
        ai_search_service, "_ask_claude_to_decide",
        lambda context, guesses, catalog_hits: [{"title": "Найдено", "artist": "Кто-то"}],
    )

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
    monkeypatch.setattr(ai_search_service, "_ask_claude", lambda text: ["Кто-то - Найдено"])
    monkeypatch.setattr(ai_search_service, "_gather_catalog_hits", lambda queries, limit_per_source=5: [])
    monkeypatch.setattr(
        ai_search_service, "_ask_claude_to_decide",
        lambda context, guesses, catalog_hits: [{"title": "Найдено", "artist": "Кто-то"}],
    )

    session = _guest_session(client, club.club_id, table_no=None)
    resp = client.post(
        "/api/guest/songs/ai-search", json={"text": "что-то"}, headers=_headers(session["token"]),
    )
    assert resp.status_code == 200
    assert len(resp.get_json()["data"]) == 1


# --- Поиск по скриншоту (screenshot_powered_search) ---

def test_screenshot_search_happy_path(client, db, club, monkeypatch):
    """Claude разглядел на картинке "исполнитель - название", каталоги
    подтверждают, решающий запрос возвращает окончательный результат."""
    seen_images = []

    monkeypatch.setattr(
        ai_search_service, "_ask_claude_vision",
        lambda image_base64, media_type: seen_images.append((image_base64, media_type)) or ["Дима Билан - Не молчи"],
    )
    monkeypatch.setattr(ai_search_service, "_gather_catalog_hits", lambda queries, limit_per_source=5: [])
    monkeypatch.setattr(
        ai_search_service, "_ask_claude_to_decide",
        lambda context, guesses, catalog_hits: [{"title": "Не молчи", "artist": "Дима Билан"}],
    )

    session = _guest_session(client, club.club_id)
    resp = client.post(
        "/api/guest/songs/screenshot-search",
        json={"image_base64": "ZmFrZQ==", "media_type": "image/jpeg"},
        headers=_headers(session["token"]),
    )
    assert resp.status_code == 200
    data = resp.get_json()["data"]
    assert data == [{"title": "Не молчи", "artist": "Дима Билан"}]
    assert seen_images == [("ZmFrZQ==", "image/jpeg")]


def test_screenshot_search_no_claude_key_returns_empty(client, db, club, app):
    """Без ANTHROPIC_API_KEY распознавание картинки пропускается — честно
    пустой результат, без выдуманного текста для fallback (здесь у нас
    вообще нет исходного текста гостя, а каталоги — только подсказка)."""
    app.config["ANTHROPIC_API_KEY"] = None

    session = _guest_session(client, club.club_id)
    resp = client.post(
        "/api/guest/songs/screenshot-search",
        json={"image_base64": "ZmFrZQ==", "media_type": "image/jpeg"},
        headers=_headers(session["token"]),
    )
    assert resp.status_code == 200
    assert resp.get_json()["data"] == []


def test_screenshot_search_nothing_recognized_skips_catalogs_and_decision(client, db, club, monkeypatch):
    """Claude посмотрел на картинку, но не разглядел там ничего похожего на
    песню (queries: []) — каталоги и решающий запрос не должны вызываться."""
    catalogs_called = []
    decide_called = []

    monkeypatch.setattr(ai_search_service, "_ask_claude_vision", lambda image_base64, media_type: [])
    monkeypatch.setattr(
        ai_search_service, "_gather_catalog_hits",
        lambda queries, limit_per_source=5: catalogs_called.append(queries) or [],
    )
    monkeypatch.setattr(
        ai_search_service, "_ask_claude_to_decide",
        lambda context, guesses, catalog_hits: decide_called.append((guesses, catalog_hits)) or [],
    )

    session = _guest_session(client, club.club_id)
    resp = client.post(
        "/api/guest/songs/screenshot-search",
        json={"image_base64": "ZmFrZQ==", "media_type": "image/png"},
        headers=_headers(session["token"]),
    )
    assert resp.status_code == 200
    assert resp.get_json()["data"] == []
    assert catalogs_called == []
    assert decide_called == []


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


# --- Источники-подсказки: Deezer, MusicBrainz, сбор и дедупликация ---

def test_search_deezer_parses_hits(monkeypatch):
    class FakeResponse:
        status_code = 200

        def json(self):
            return {"data": [
                {"title": "Boschetar", "artist": {"name": "Valentin Boghean"}},
                {"title": "Без исполнителя", "artist": None},
            ]}

    def fake_get(url, params, timeout):
        assert url == "https://api.deezer.com/search"
        assert params["q"] == "Valentin Boghean - Boschetar"
        return FakeResponse()

    monkeypatch.setattr(ai_search_service.requests, "get", fake_get)

    hits = ai_search_service._search_deezer("Valentin Boghean - Boschetar", limit=5)
    assert hits == [
        {"title": "Boschetar", "artist": "Valentin Boghean"},
        {"title": "Без исполнителя", "artist": None},
    ]


def test_search_deezer_network_error_returns_empty(monkeypatch):
    def fake_get(url, params, timeout):
        raise ai_search_service.requests.RequestException("boom")

    monkeypatch.setattr(ai_search_service.requests, "get", fake_get)
    assert ai_search_service._search_deezer("что угодно") == []


def test_search_musicbrainz_parses_hits_and_sends_user_agent(monkeypatch):
    class FakeResponse:
        status_code = 200

        def json(self):
            return {"recordings": [
                {"title": "Focul din vatră", "artist-credit": [{"name": "Ion Aldea-Teodorovici"}]},
            ]}

    def fake_get(url, params, headers, timeout):
        assert url == "https://musicbrainz.org/ws/2/recording/"
        assert "User-Agent" in headers and headers["User-Agent"]
        return FakeResponse()

    monkeypatch.setattr(ai_search_service.requests, "get", fake_get)

    hits = ai_search_service._search_musicbrainz("Ion Aldea-Teodorovici - Focul din vatră", limit=5)
    assert hits == [{"title": "Focul din vatră", "artist": "Ion Aldea-Teodorovici"}]


def test_search_musicbrainz_http_error_returns_empty(monkeypatch):
    class FakeResponse:
        status_code = 503

        def json(self):
            return {}

    monkeypatch.setattr(ai_search_service.requests, "get", lambda *a, **k: FakeResponse())
    assert ai_search_service._search_musicbrainz("что угодно") == []


def test_gather_catalog_hits_queries_both_sources_and_dedupes(monkeypatch):
    monkeypatch.setattr(
        ai_search_service, "_search_deezer",
        lambda query, limit=5: [{"title": "Boschetar", "artist": "Valentin Boghean"}],
    )
    monkeypatch.setattr(
        ai_search_service, "_search_musicbrainz",
        lambda query, limit=5: [{"title": "boschetar", "artist": "valentin boghean"}],
    )

    hits = ai_search_service._gather_catalog_hits(["Valentin Boghean - Boschetar"])
    assert hits == [{"title": "Boschetar", "artist": "Valentin Boghean"}]


def test_gather_catalog_hits_returns_empty_when_both_sources_empty(monkeypatch):
    """Ключевой случай для регионального репертуара: оба каталога честно
    ничего не находят, но это не должно ломать пайплайн — решение всё
    равно за Claude (см. test_decision_step_can_answer_from_own_knowledge_when_catalogs_empty)."""
    monkeypatch.setattr(ai_search_service, "_search_deezer", lambda query, limit=5: [])
    monkeypatch.setattr(ai_search_service, "_search_musicbrainz", lambda query, limit=5: [])

    hits = ai_search_service._gather_catalog_hits(["Ion Aldea-Teodorovici - Focul din vatră"])
    assert hits == []


# --- Решающий запрос к Claude напрямую ---

def test_ask_claude_to_decide_no_key_returns_empty(app):
    app.config["ANTHROPIC_API_KEY"] = None
    with app.app_context():
        assert ai_search_service._ask_claude_to_decide("текст", ["Кто-то - Что-то"], []) == []


def test_ask_claude_to_decide_parses_response_and_caps_at_three(app, monkeypatch):
    app.config["ANTHROPIC_API_KEY"] = "test-key"

    class FakeResponse:
        status_code = 200

        def json(self):
            import json as _json
            return {"content": [{"text": _json.dumps({"results": [
                {"title": f"Песня{i}", "artist": f"Артист{i}"} for i in range(5)
            ]})}]}

    monkeypatch.setattr(ai_search_service.requests, "post", lambda *a, **k: FakeResponse())

    with app.app_context():
        results = ai_search_service._ask_claude_to_decide("текст", ["что-то"], [])
    assert len(results) == 3
    assert results[0] == {"title": "Песня0", "artist": "Артист0"}


def test_ask_claude_to_decide_malformed_response_returns_empty(app, monkeypatch):
    app.config["ANTHROPIC_API_KEY"] = "test-key"

    class FakeResponse:
        status_code = 200

        def json(self):
            return {"content": [{"text": "не json вообще"}]}

    monkeypatch.setattr(ai_search_service.requests, "post", lambda *a, **k: FakeResponse())

    with app.app_context():
        assert ai_search_service._ask_claude_to_decide("текст", ["что-то"], []) == []
