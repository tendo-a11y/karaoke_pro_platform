"""
Тесты Guest App, Phase 4 шаг 1 — анонимная гостевая сессия, создание
заказа, своя история заказов, общая очередь. По образцу test_orders.py /
test_admin_auth.py.
"""
import uuid

from auth import issue_guest_token
from models import Order


def _create_session(client, club_id, table_no=5):
    """table_no здесь больше ни на что не влияет (ТЗ п.45, финальная
    единая модель входа — QR никогда не приносит номер стола, сессия
    всегда создаётся без стола); параметр оставлен только чтобы не
    переписывать все вызовы ниже. Стол появляется только вместе со входом
    через Google — см. _link_google."""
    resp = client.post("/api/guest/session", json={"club_id": club_id})
    assert resp.status_code == 200
    return resp.get_json()["data"]


def _headers(token):
    return {"Authorization": f"Bearer {token}"}


def _link_google(client, token, table_no=1):
    """ТЗ п.45 (финальная единая модель входа): стол и Google выбираются
    одним действием, и это единственный способ разблокировать заказ —
    заказ в тестах ниже теперь требует этого вызова заранее. guest_id не
    меняется (аккаунта ещё не было — см. guest_account_service.
    link_google), поэтому исходный токен теста продолжает быть валидным."""
    sub = f"mock-sub-{uuid.uuid4().hex[:12]}"
    resp = client.post(
        "/api/guest/profile/link-google",
        json={"table_no": table_no, "google_credential": {"sub": sub}},
        headers=_headers(token),
    )
    assert resp.status_code == 200
    return resp


def test_create_session_requires_club_id(client):
    resp = client.post("/api/guest/session", json={"table_no": 1})
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "VALIDATION_ERROR"


def test_create_session_unknown_club_is_404(client):
    resp = client.post("/api/guest/session", json={"club_id": 999, "table_no": 1})
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "CLUB_NOT_FOUND"


def test_create_session_inactive_club_is_404(client, db, club):
    club.is_active = False
    db.session.commit()
    resp = client.post("/api/guest/session", json={"club_id": club.club_id, "table_no": 1})
    assert resp.status_code == 404


def test_create_session_always_without_table(client, club):
    """ТЗ п.45 (финальная единая модель входа): QR никогда не приносит
    номер стола — сессия всегда создаётся без стола, независимо от того,
    что было передано в запросе (см. _create_session)."""
    session = _create_session(client, club.club_id)
    assert session["table_no"] is None
    # guest_id отдаётся строкой — потеря точности 62-битных значений в
    # JS Number/JSON.parse (см. models.py::TableGroup.to_dict()).
    assert isinstance(session["guest_id"], str)
    assert session["token"]


def test_two_sessions_get_different_guest_ids(client, club):
    s1 = _create_session(client, club.club_id)
    s2 = _create_session(client, club.club_id)
    assert s1["guest_id"] != s2["guest_id"]


def test_missing_token_is_unauthorized(client, club):
    resp = client.get("/api/guest/me")
    assert resp.status_code == 401


def test_guest_me_reflects_session(client, club):
    session = _create_session(client, club.club_id)
    resp = client.get("/api/guest/me", headers=_headers(session["token"]))
    assert resp.status_code == 200
    data = resp.get_json()["data"]
    assert data["guest_id"] == session["guest_id"]
    assert data["club_id"] == club.club_id
    assert data["table_no"] is None
    assert data["club_name"] == club.name
    assert data["chat_enabled"] is False


def test_guest_me_reflects_table_after_link_google(client, club):
    """После единственного шага "стол + Google" /me должен сразу
    показывать новый стол (ТЗ п.45, финальная единая модель входа)."""
    session = _create_session(client, club.club_id)
    linked = _link_google(client, session["token"], table_no=7).get_json()["data"]
    resp = client.get("/api/guest/me", headers=_headers(linked["token"]))
    assert resp.status_code == 200
    data = resp.get_json()["data"]
    assert data["table_no"] == 7
    assert data["has_permanent_profile"] is True


def test_guest_me_reflects_chat_enabled(client, db, club):
    club.chat_enabled = True
    db.session.commit()
    session = _create_session(client, club.club_id)
    resp = client.get("/api/guest/me", headers=_headers(session["token"]))
    assert resp.get_json()["data"]["chat_enabled"] is True


def test_guest_session_dead_after_club_deactivated(client, db, club):
    session = _create_session(client, club.club_id)
    club.is_active = False
    db.session.commit()
    resp = client.get("/api/guest/me", headers=_headers(session["token"]))
    assert resp.status_code == 403


def test_kj_token_cannot_be_used_as_guest_token(client, club, kj):
    resp = client.get("/api/guest/me", headers=kj["headers"])
    assert resp.status_code == 401


def test_guest_creates_order_with_table(client, db, club):
    session = _create_session(client, club.club_id)
    linked = _link_google(client, session["token"], table_no=3).get_json()["data"]
    resp = client.post(
        "/api/guest/order",
        json={"song_title": "Yesterday", "artist": "The Beatles"},
        headers=_headers(linked["token"]),
    )
    assert resp.status_code == 201
    data = resp.get_json()["data"]
    assert data["song_title"] == "Yesterday"
    assert data["table_no"] == 3
    assert data["guest_type"] == "client"
    assert data["source"] == "guest"
    assert data["telegram_user_id"] == int(session["guest_id"])

    order = db.session.get(Order, data["id"])
    assert order is not None
    assert order.club_id == club.club_id


def test_guest_without_table_cannot_order(client, club):
    """ТЗ п.45 (финальная единая модель входа): заказ недоступен, пока
    гость не выберет стол (см. tests/test_guest_identity.py) — раньше
    (до п.45) "гость без стола" мог заказывать сразу с guest_type
    "no_table", это поведение сознательно изменено."""
    session = _create_session(client, club.club_id, table_no=None)
    resp = client.post(
        "/api/guest/order",
        json={"song_title": "Song"},
        headers=_headers(session["token"]),
    )
    assert resp.status_code == 409
    assert resp.get_json()["error"] == "TABLE_REQUIRED"


def test_guest_order_requires_song_title(client, club):
    session = _create_session(client, club.club_id)
    resp = client.post("/api/guest/order", json={}, headers=_headers(session["token"]))
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "VALIDATION_ERROR"


def test_guest_sees_own_orders_only(client, club, other_club):
    session_a = _create_session(client, club.club_id)
    session_b = _create_session(client, club.club_id)
    # Разные столы — иначе второй гость окажется "pending" в групповом
    # столе первого (см. table_group_service) и его заказ будет отклонён
    # ещё до того, как этот тест успеет проверить то, что должен.
    token_a = _link_google(client, session_a["token"], table_no=1).get_json()["data"]["token"]
    token_b = _link_google(client, session_b["token"], table_no=2).get_json()["data"]["token"]

    resp_a = client.post("/api/guest/order", json={"song_title": "Song A"}, headers=_headers(token_a))
    resp_b = client.post("/api/guest/order", json={"song_title": "Song B"}, headers=_headers(token_b))
    assert resp_a.status_code == 201
    assert resp_b.status_code == 201

    resp = client.get("/api/guest/orders", headers=_headers(token_a))
    assert resp.status_code == 200
    titles = [o["song_title"] for o in resp.get_json()["data"]]
    assert titles == ["Song A"]


# ДОБАВЛЕНО (2026-09-19, запрос пользователя): второй гость за столом,
# отправив заказ, получал автосообщение "Ждите подтверждения KJ" — по
# факту ему нужен номер в общей очереди клуба (по всем столам вместе), а
# не формулировка про чьё-то отдельное подтверждение. См. docstring
# table_board_service.get_club_queue_positions.
def test_guest_order_response_includes_club_queue_position(client, club):
    session = _create_session(client, club.club_id)
    linked = _link_google(client, session["token"], table_no=1).get_json()["data"]
    resp = client.post(
        "/api/guest/order",
        json={"song_title": "First In Line"},
        headers=_headers(linked["token"]),
    )
    assert resp.status_code == 201
    assert resp.get_json()["data"]["queue_position"] == 1


def test_guest_order_queue_position_counts_across_all_tables(client, club):
    """Номер общий на весь клуб — второй гость за ДРУГИМ столом получает
    следующий номер очереди, а не отдельный счётчик по своему столу."""
    session_a = _create_session(client, club.club_id)
    session_b = _create_session(client, club.club_id)
    token_a = _link_google(client, session_a["token"], table_no=1).get_json()["data"]["token"]
    token_b = _link_google(client, session_b["token"], table_no=2).get_json()["data"]["token"]

    resp_a = client.post("/api/guest/order", json={"song_title": "Song A"}, headers=_headers(token_a))
    resp_b = client.post("/api/guest/order", json={"song_title": "Song B"}, headers=_headers(token_b))
    assert resp_a.get_json()["data"]["queue_position"] == 1
    assert resp_b.get_json()["data"]["queue_position"] == 2

    orders_a = client.get("/api/guest/orders", headers=_headers(token_a)).get_json()["data"]
    assert orders_a[0]["queue_position"] == 1


def test_guest_order_queue_position_shrinks_when_earlier_order_leaves_queue(client, db, club):
    """Номер пересчитывается заново на каждый запрос — когда более ранний
    заказ отклонён (или сыгран), следующий сдвигается вперёд."""
    session_a = _create_session(client, club.club_id)
    session_b = _create_session(client, club.club_id)
    token_a = _link_google(client, session_a["token"], table_no=1).get_json()["data"]["token"]
    token_b = _link_google(client, session_b["token"], table_no=2).get_json()["data"]["token"]

    order_a_id = client.post(
        "/api/guest/order", json={"song_title": "Song A"}, headers=_headers(token_a)
    ).get_json()["data"]["id"]
    client.post("/api/guest/order", json={"song_title": "Song B"}, headers=_headers(token_b))

    order_a = db.session.get(Order, order_a_id)
    order_a.status = "rejected"
    db.session.commit()

    orders_b = client.get("/api/guest/orders", headers=_headers(token_b)).get_json()["data"]
    assert orders_b[0]["queue_position"] == 1


def test_guest_queue_endpoint_reachable(client, club):
    session = _create_session(client, club.club_id)
    resp = client.get("/api/guest/queue", headers=_headers(session["token"]))
    assert resp.status_code == 200
    assert resp.get_json()["data"] == []


def test_guest_cannot_see_other_club_via_forged_club_id(client, app, club, other_club):
    # club_id в /api/guest/* берётся из подписанного токена, а не из URL —
    # здесь просто проверяем, что токен, выпущенный для club.club_id, и
    # даёт доступ именно к club.club_id, а не к произвольному другому.
    session = _create_session(client, club.club_id)
    resp = client.get("/api/guest/me", headers=_headers(session["token"]))
    assert resp.get_json()["data"]["club_id"] == club.club_id
    assert resp.get_json()["data"]["club_id"] != other_club.club_id
