"""
Тесты чата гость↔KJ (ТЗ §20, §49) — Club.chat_enabled, ChatMessage,
/api/guest/chat и /api/kj/chat/<club_id>.
"""
import uuid


def _headers(token):
    return {"Authorization": f"Bearer {token}"}


def _guest_session(client, club_id, table_no=5):
    """table_no здесь больше ни на что не влияет при создании сессии (ТЗ
    п.45, финальная единая модель входа — QR никогда не приносит номер
    стола); параметр оставлен только чтобы не переписывать все вызовы
    ниже — чат ни от стола, ни от Google не зависит."""
    resp = client.post("/api/guest/session", json={"club_id": club_id})
    return resp.get_json()["data"]


def _with_table(client, token, table_no):
    """Единственный способ дать гостю стол — вместе со входом через
    Google, одним действием (см. routes/guest.py::link_google)."""
    sub = f"mock-sub-{uuid.uuid4().hex[:12]}"
    resp = client.post(
        "/api/guest/profile/link-google",
        json={"table_no": table_no, "google_credential": {"sub": sub}},
        headers=_headers(token),
    )
    assert resp.status_code == 200
    return resp.get_json()["data"]


def test_guest_chat_disabled_by_default(client, db, club):
    session = _guest_session(client, club.club_id)
    resp = client.post(
        "/api/guest/chat", json={"message_text": "Привет"}, headers=_headers(session["token"])
    )
    assert resp.status_code == 403
    assert resp.get_json()["error"] == "CHAT_DISABLED"


def test_guest_can_send_and_read_own_chat(client, db, club):
    club.chat_enabled = True
    db.session.commit()

    session = _guest_session(client, club.club_id)
    linked = _with_table(client, session["token"], table_no=4)
    resp = client.post(
        "/api/guest/chat", json={"message_text": "Можно погромче музыку?"},
        headers=_headers(linked["token"]),
    )
    assert resp.status_code == 201
    sent = resp.get_json()["data"]
    assert sent["from_guest"] is True
    assert sent["table_no"] == 4
    assert sent["telegram_user_id"] == int(session["guest_id"])

    resp = client.get("/api/guest/chat", headers=_headers(linked["token"]))
    assert resp.status_code == 200
    messages = resp.get_json()["data"]
    assert len(messages) == 1
    assert messages[0]["message_text"] == "Можно погромче музыку?"


def test_guest_chat_requires_message_text(client, db, club):
    club.chat_enabled = True
    db.session.commit()
    session = _guest_session(client, club.club_id)
    resp = client.post("/api/guest/chat", json={}, headers=_headers(session["token"]))
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "VALIDATION_ERROR"


def test_guests_do_not_see_each_others_chat(client, db, club):
    club.chat_enabled = True
    db.session.commit()

    session_a = _guest_session(client, club.club_id)
    session_b = _guest_session(client, club.club_id)

    client.post("/api/guest/chat", json={"message_text": "От A"}, headers=_headers(session_a["token"]))
    client.post("/api/guest/chat", json={"message_text": "От B"}, headers=_headers(session_b["token"]))

    resp = client.get("/api/guest/chat", headers=_headers(session_a["token"]))
    texts = [m["message_text"] for m in resp.get_json()["data"]]
    assert texts == ["От A"]


def test_kj_sees_all_club_chat_and_can_filter_by_guest(client, db, club, kj):
    club.chat_enabled = True
    db.session.commit()

    session_a = _guest_session(client, club.club_id)
    session_b = _guest_session(client, club.club_id)
    client.post("/api/guest/chat", json={"message_text": "От A"}, headers=_headers(session_a["token"]))
    client.post("/api/guest/chat", json={"message_text": "От B"}, headers=_headers(session_b["token"]))

    resp = client.get(f"/api/kj/chat/{club.club_id}", headers=kj["headers"])
    assert resp.status_code == 200
    assert len(resp.get_json()["data"]) == 2

    resp = client.get(
        f"/api/kj/chat/{club.club_id}?telegram_user_id={session_a['guest_id']}",
        headers=kj["headers"],
    )
    data = resp.get_json()["data"]
    assert len(data) == 1
    assert data[0]["message_text"] == "От A"


def test_kj_reply_reaches_guest(client, db, club, kj):
    club.chat_enabled = True
    db.session.commit()
    session = _guest_session(client, club.club_id)

    resp = client.post(
        f"/api/kj/chat/{club.club_id}",
        json={"telegram_user_id": int(session["guest_id"]), "message_text": "Уже включаю громче"},
        headers=kj["headers"],
    )
    assert resp.status_code == 201
    assert resp.get_json()["data"]["from_guest"] is False

    resp = client.get("/api/guest/chat", headers=_headers(session["token"]))
    messages = resp.get_json()["data"]
    assert len(messages) == 1
    assert messages[0]["from_guest"] is False
    assert messages[0]["message_text"] == "Уже включаю громче"


def test_kj_reply_requires_valid_payload(client, db, club, kj):
    club.chat_enabled = True
    db.session.commit()
    resp = client.post(
        f"/api/kj/chat/{club.club_id}",
        json={"message_text": "Без адресата"},
        headers=kj["headers"],
    )
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "VALIDATION_ERROR"


def test_kj_cannot_read_other_club_chat(client, db, club, other_club, kj):
    club.chat_enabled = True
    other_club.chat_enabled = True
    db.session.commit()
    resp = client.get(f"/api/kj/chat/{other_club.club_id}", headers=kj["headers"])
    assert resp.status_code == 403
