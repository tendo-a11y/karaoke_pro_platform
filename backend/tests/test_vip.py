"""
Тесты Role 3 (VIP) для Guest App: постоянный профиль через Google (ТЗ
п.45) -> заявка на VIP -> одобрение KJ -> баланс/кэшбэк, плюс избранное и
лимит активных песен. См. отчёт по аудиту Role 3/4/5 и последующий отчёт
по п.45 (постоянная идентификация гостя), переданные в чате, не файлы в
репозитории.
"""
import uuid
from decimal import Decimal

from models import Favorite, Order, Service, STATUS_QUEUED, VipClient, VipRequest
from services.billing_service import charge_at_completion


def _headers(token):
    return {"Authorization": f"Bearer {token}"}


def _guest_session(client, club_id, table_no=None):
    """ТЗ п.45 (финальная единая модель входа): table_no здесь больше ни на
    что не влияет — QR никогда не приносит номер стола, сессия всегда
    создаётся без стола. Параметр оставлен только чтобы не переписывать
    все вызовы ниже; стол появляется только вместе со входом через Google,
    см. _link_google."""
    resp = client.post("/api/guest/session", json={"club_id": club_id})
    return resp.get_json()["data"]


def _link_google(client, token, table_no=1, sub=None):
    """GOOGLE_AUTH_MODE=mock (см. config.py::TestingConfig) — credential
    здесь не настоящий Google id_token, а простой {"sub", "email"}, как и
    задокументировано в services/google_auth_service.py. table_no теперь
    обязателен на каждый вызов (стол выбирается всегда вместе со входом),
    поэтому у него есть значение по умолчанию, а не None."""
    sub = sub or f"mock-sub-{uuid.uuid4().hex[:12]}"
    payload = {"table_no": table_no, "google_credential": {"sub": sub, "email": f"{sub}@example.com"}}
    return client.post("/api/guest/profile/link-google", json=payload, headers=_headers(token))


def test_me_reports_not_vip_by_default(client, club):
    session = _guest_session(client, club.club_id)
    resp = client.get("/api/guest/me", headers=_headers(session["token"]))
    data = resp.get_json()["data"]
    assert data["is_vip"] is False
    assert data["vip"] is None
    assert data["vip_request_pending"] is False
    assert data["has_permanent_profile"] is False


def test_request_vip_requires_google_link(client, db, club):
    session = _guest_session(client, club.club_id)
    resp = client.post("/api/guest/vip/request", headers=_headers(session["token"]))
    assert resp.status_code == 409
    assert resp.get_json()["error"] == "GOOGLE_LINK_REQUIRED"


def test_link_google_without_sub_rejected(client, db, club):
    session = _guest_session(client, club.club_id)
    resp = client.post(
        "/api/guest/profile/link-google",
        json={"table_no": 1, "google_credential": {}},
        headers=_headers(session["token"]),
    )
    assert resp.status_code == 401
    assert resp.get_json()["error"] == "GOOGLE_AUTH_FAILED"


def test_vip_request_then_approve_upgrades_existing_profile(client, db, club, kj):
    """
    ТЗ п.45: одобрение VIP больше не создаёт новую личность и не выдаёт
    код — оно ставит VIP-статус на тот же самый постоянный номер, которым
    гость уже пользовался (тот же токен продолжает работать без замены).
    """
    session = _guest_session(client, club.club_id)
    linked = _link_google(client, session["token"]).get_json()["data"]
    token = linked["token"]
    assert linked["guest_id"] == session["guest_id"]  # номер не меняется — аккаунта ещё не было

    resp = client.post("/api/guest/vip/request", headers=_headers(token))
    assert resp.status_code == 201
    request_id = resp.get_json()["data"]["id"]

    # Повторная заявка, пока первая не решена — отклоняется.
    resp = client.post("/api/guest/vip/request", headers=_headers(token))
    assert resp.status_code == 409
    assert resp.get_json()["error"] == "VIP_REQUEST_PENDING"

    me = client.get("/api/guest/me", headers=_headers(token)).get_json()["data"]
    assert me["vip_request_pending"] is True

    resp = client.put(f"/api/kj/vip-requests/{request_id}/approve", headers=kj["headers"])
    assert resp.status_code == 200
    approved = resp.get_json()["data"]
    assert approved["request"]["status"] == "approved"
    assert approved["vip_client"]["telegram_user_id"] == int(linked["guest_id"])
    assert "access_code" not in approved["vip_client"]

    # Тот же самый токен — без повторного "входа" — уже показывает VIP.
    me = client.get("/api/guest/me", headers=_headers(token)).get_json()["data"]
    assert me["vip_request_pending"] is False
    assert me["is_vip"] is True
    assert me["vip"]["balance"] == 0.0


def test_reject_vip_request(client, db, club, kj):
    session = _guest_session(client, club.club_id)
    token = _link_google(client, session["token"]).get_json()["data"]["token"]
    request_id = client.post(
        "/api/guest/vip/request", headers=_headers(token)
    ).get_json()["data"]["id"]

    resp = client.put(f"/api/kj/vip-requests/{request_id}/reject", headers=kj["headers"])
    assert resp.status_code == 200
    assert resp.get_json()["data"]["status"] == "rejected"

    # После отклонения гость может подать заявку заново.
    resp = client.post("/api/guest/vip/request", headers=_headers(token))
    assert resp.status_code == 201


def test_cannot_request_vip_twice_when_already_vip(client, db, club, kj):
    session = _guest_session(client, club.club_id)
    token = _link_google(client, session["token"]).get_json()["data"]["token"]
    request_id = client.post(
        "/api/guest/vip/request", headers=_headers(token)
    ).get_json()["data"]["id"]
    client.put(f"/api/kj/vip-requests/{request_id}/approve", headers=kj["headers"])

    resp = client.post("/api/guest/vip/request", headers=_headers(token))
    assert resp.status_code == 409
    assert resp.get_json()["error"] == "ALREADY_VIP"


def test_kj_cannot_approve_other_club_vip_request(client, db, club, other_club, kj):
    session = _guest_session(client, other_club.club_id)
    token = _link_google(client, session["token"]).get_json()["data"]["token"]
    request_id = client.post(
        "/api/guest/vip/request", headers=_headers(token)
    ).get_json()["data"]["id"]

    resp = client.put(f"/api/kj/vip-requests/{request_id}/approve", headers=kj["headers"])
    assert resp.status_code == 403


def test_order_gets_vip_guest_type_after_approval(client, db, club, kj):
    session = _guest_session(client, club.club_id, table_no=7)
    token = _link_google(client, session["token"]).get_json()["data"]["token"]
    request_id = client.post(
        "/api/guest/vip/request", headers=_headers(token)
    ).get_json()["data"]["id"]
    client.put(f"/api/kj/vip-requests/{request_id}/approve", headers=kj["headers"])

    resp = client.post(
        "/api/guest/order", json={"song_title": "Believer"}, headers=_headers(token)
    )
    assert resp.status_code == 201
    assert resp.get_json()["data"]["guest_type"] == "vip"


def test_order_requires_table(client, db, club):
    """ТЗ п.45 — без стола очередь смотреть можно, заказывать нет."""
    session = _guest_session(client, club.club_id, table_no=None)
    resp = client.post(
        "/api/guest/order", json={"song_title": "Believer"}, headers=_headers(session["token"]),
    )
    assert resp.status_code == 409
    assert resp.get_json()["error"] == "TABLE_REQUIRED"


def test_active_songs_limit_enforced(client, db, club):
    session = _guest_session(client, club.club_id)
    token = _link_google(client, session["token"]).get_json()["data"]["token"]
    for i in range(2):
        resp = client.post(
            "/api/guest/order", json={"song_title": f"Song {i}"}, headers=_headers(token)
        )
        assert resp.status_code == 201

    resp = client.post(
        "/api/guest/order", json={"song_title": "Song 3"}, headers=_headers(token)
    )
    assert resp.status_code == 409
    assert resp.get_json()["error"] == "ACTIVE_SONGS_LIMIT"


def test_services_listed_for_club(client, db, club):
    service = Service(club_id=club.club_id, name="Приоритет", price=Decimal("10.00"), is_free=False)
    db.session.add(service)
    db.session.commit()

    session = _guest_session(client, club.club_id)
    resp = client.get("/api/guest/services", headers=_headers(session["token"]))
    names = [s["name"] for s in resp.get_json()["data"]]
    assert "Приоритет" in names


def test_order_with_service_id_and_cashback_at_completion(client, db, club, kj):
    service = Service(club_id=club.club_id, name="Приоритет", price=Decimal("10.00"), is_free=False)
    db.session.add(service)
    db.session.commit()

    session = _guest_session(client, club.club_id)
    token = _link_google(client, session["token"]).get_json()["data"]["token"]
    request_id = client.post(
        "/api/guest/vip/request", headers=_headers(token)
    ).get_json()["data"]["id"]
    approved = client.put(
        f"/api/kj/vip-requests/{request_id}/approve", headers=kj["headers"]
    ).get_json()["data"]
    vip_client_id = approved["vip_client"]["id"]

    client.put(
        f"/api/kj/vip-clients/{vip_client_id}/cashback",
        json={"cashback_percent": 10}, headers=kj["headers"],
    )

    # VIP нужен баланс, чтобы списание не увело его в минус для этого теста —
    # пополняем напрямую в БД (топ-ап через API покрыт test_vip_balance_adjust.py).
    vip = db.session.get(VipClient, vip_client_id)
    vip.balance = Decimal("50.00")
    db.session.commit()

    resp = client.post(
        "/api/guest/order",
        json={"song_title": "Believer", "service_id": service.id},
        headers=_headers(token),
    )
    order_id = resp.get_json()["data"]["id"]
    order = db.session.get(Order, order_id)
    order.status = STATUS_QUEUED
    db.session.commit()

    result = charge_at_completion(order)
    assert result.charged is True
    assert result.charge_amount == Decimal("10.00")
    assert result.cashback_amount == Decimal("1.00")

    db.session.refresh(vip)
    assert vip.balance == Decimal("41.00")  # 50 - 10 + 1

    me = client.get("/api/guest/me", headers=_headers(token)).get_json()["data"]
    assert me["vip"]["balance"] == 41.0


def test_favorite_add_list_delete(client, db, club):
    session = _guest_session(client, club.club_id)
    resp = client.post(
        "/api/guest/favorites",
        json={"song_title": "Believer", "artist": "Imagine Dragons"},
        headers=_headers(session["token"]),
    )
    assert resp.status_code == 201
    favorite_id = resp.get_json()["data"]["id"]

    resp = client.get("/api/guest/favorites", headers=_headers(session["token"]))
    assert len(resp.get_json()["data"]) == 1

    resp = client.delete(f"/api/guest/favorites/{favorite_id}", headers=_headers(session["token"]))
    assert resp.status_code == 200

    resp = client.get("/api/guest/favorites", headers=_headers(session["token"]))
    assert resp.get_json()["data"] == []


def test_favorite_belongs_to_one_guest(client, db, club):
    session_a = _guest_session(client, club.club_id)
    session_b = _guest_session(client, club.club_id)

    favorite_id = client.post(
        "/api/guest/favorites", json={"song_title": "Believer"}, headers=_headers(session_a["token"])
    ).get_json()["data"]["id"]

    resp = client.delete(f"/api/guest/favorites/{favorite_id}", headers=_headers(session_b["token"]))
    assert resp.status_code == 403

    resp = client.get("/api/guest/favorites", headers=_headers(session_b["token"]))
    assert resp.get_json()["data"] == []


def test_reorder_favorite_creates_order(client, db, club):
    session = _guest_session(client, club.club_id)
    token = _link_google(client, session["token"]).get_json()["data"]["token"]
    favorite_id = client.post(
        "/api/guest/favorites",
        json={"song_title": "Believer", "artist": "Imagine Dragons"},
        headers=_headers(token),
    ).get_json()["data"]["id"]

    resp = client.post(f"/api/guest/favorites/{favorite_id}/reorder", headers=_headers(token))
    assert resp.status_code == 201
    order = resp.get_json()["data"]
    assert order["song_title"] == "Believer"
    assert order["artist"] == "Imagine Dragons"

    orders = client.get("/api/guest/orders", headers=_headers(token)).get_json()["data"]
    assert len(orders) == 1


def test_reorder_favorite_respects_active_limit(client, db, club):
    session = _guest_session(client, club.club_id)
    token = _link_google(client, session["token"]).get_json()["data"]["token"]
    favorite_id = client.post(
        "/api/guest/favorites", json={"song_title": "Believer"}, headers=_headers(token)
    ).get_json()["data"]["id"]

    for i in range(2):
        client.post(
            "/api/guest/order", json={"song_title": f"Filler {i}"}, headers=_headers(token)
        )

    resp = client.post(f"/api/guest/favorites/{favorite_id}/reorder", headers=_headers(token))
    assert resp.status_code == 409
    assert resp.get_json()["error"] == "ACTIVE_SONGS_LIMIT"
