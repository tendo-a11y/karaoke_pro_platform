"""
Тесты AI-поиска (Role 3/4/5, аудит-отчёт п.2). Сетевые вызовы к Claude и
Genius подменяются — как и в старом проекте (tests_bot/test_ai_search.py),
это платные внешние API, оркестрация проверяется отдельно от реальной сети
(живой прогон с настоящими ключами — в отдельном E2E-скрипте).
"""
from services import ai_search_service


def _headers(token):
    return {"Authorization": f"Bearer {token}"}


def _guest_session(client, club_id, table_no=5):
    resp = client.post("/api/guest/session", json={"club_id": club_id, "table_no": table_no})
    return resp.get_json()["data"]


def test_no_api_keys_returns_empty_without_crashing(client, db, club, app):
    app.config["ANTHROPIC_API_KEY"] = None
    app.config["GENIUS_API_KEY"] = None
    session = _guest_session(client, club.club_id)
    resp = client.post(
        "/api/guest/songs/ai-search", json={"text": "дима билан машины"}, headers=_headers(session["token"]),
    )
    assert resp.status_code == 200
    assert resp.get_json()["data"] == []


def test_dedupes_results_across_queries(client, db, club, monkeypatch):
    def fake_ask_claude(text):
        return ["Дима Билан - Билет на самолет", "Билан Билет на самолет"]

    def fake_search_genius(query, limit):
        return [
            {"title": "Билет на самолет", "artist": "Дима Билан", "genius_url": "u1"},
            {"title": "Пьяная ночь", "artist": "Дима Билан", "genius_url": "u2"},
        ]

    monkeypatch.setattr(ai_search_service, "_ask_claude", fake_ask_claude)
    monkeypatch.setattr(ai_search_service, "_search_genius", fake_search_genius)

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

    def fake_search_genius(query, limit):
        return [{"title": f"{query}-song-{i}", "artist": "X", "genius_url": "u"} for i in range(limit)]

    monkeypatch.setattr(ai_search_service, "_ask_claude", fake_ask_claude)
    monkeypatch.setattr(ai_search_service, "_search_genius", fake_search_genius)

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

    def fake_search_genius(query, limit):
        return [{"title": "Единственный трек", "artist": "Кто-то", "genius_url": "u"}]

    monkeypatch.setattr(ai_search_service, "_ask_claude", fake_ask_claude)
    monkeypatch.setattr(ai_search_service, "_search_genius", fake_search_genius)

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

    def fake_search_genius(query, limit):
        calls.append(query)
        return [{"title": "Что-то нашлось", "artist": None, "genius_url": "u"}]

    monkeypatch.setattr(ai_search_service, "_ask_claude", fake_ask_claude)
    monkeypatch.setattr(ai_search_service, "_search_genius", fake_search_genius)

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


def test_available_to_no_table_guest(client, db, club, monkeypatch):
    """Role 5 — старая команда /ai не проверяла роль, только наличие venue_id."""

    def fake_ask_claude(text):
        return []

    def fake_search_genius(query, limit):
        return [{"title": "Найдено", "artist": None, "genius_url": "u"}]

    monkeypatch.setattr(ai_search_service, "_ask_claude", fake_ask_claude)
    monkeypatch.setattr(ai_search_service, "_search_genius", fake_search_genius)

    session = _guest_session(client, club.club_id, table_no=None)
    resp = client.post(
        "/api/guest/songs/ai-search", json={"text": "что-то"}, headers=_headers(session["token"]),
    )
    assert resp.status_code == 200
    assert len(resp.get_json()["data"]) == 1
