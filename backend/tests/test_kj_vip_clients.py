"""
Тесты Block D KJ Pro — GET /api/kj/vip-clients/<club_id>, список VIP-
клиентов клуба (без него нечем было выбрать, кому начислять/списывать).

ТЗ п.45: ручное создание VIP "из ничего" (POST /vip-clients, было здесь
раньше) — удалено вместе с access_code, см. отчёт по п.45. VIP теперь
всегда появляется через заявку гостя + одобрение KJ (test_vip.py).

Остальные VIP-заявки/баланс-эндпоинты уже покрыты test_vip.py и
test_vip_balance_adjust.py — здесь не дублируется.
"""
import uuid
from decimal import Decimal

from models import VipClient


def _headers(token):
    return {"Authorization": f"Bearer {token}"}


def _make_vip(db, club_id, telegram_user_id=987654321, balance="10.00", cashback_percent=0):
    vip = VipClient(
        club_id=club_id, telegram_user_id=telegram_user_id,
        balance=Decimal(balance), cashback_percent=cashback_percent,
    )
    db.session.add(vip)
    db.session.commit()
    return vip


def _link_google_guest_id(client, club_id, table_no=5):
    """ТЗ п.45 (финальная единая модель входа): сессия создаётся без
    стола, стол выбирается вместе со входом через Google одним действием."""
    session = client.post("/api/guest/session", json={"club_id": club_id}).get_json()["data"]
    sub = f"mock-sub-{uuid.uuid4().hex[:12]}"
    linked = client.post(
        "/api/guest/profile/link-google",
        json={"table_no": table_no, "google_credential": {"sub": sub}},
        headers=_headers(session["token"]),
    ).get_json()["data"]
    return linked["token"]


# --- GET /vip-clients/<club_id> ---

def test_list_vip_clients_requires_auth(client, club):
    resp = client.get(f"/api/kj/vip-clients/{club.club_id}")
    assert resp.status_code == 401


def test_list_vip_clients_returns_club_clients(client, db, club, kj):
    vip1 = _make_vip(db, club.club_id, telegram_user_id=111, balance="5.00")
    vip2 = _make_vip(db, club.club_id, telegram_user_id=222, balance="15.00")

    resp = client.get(f"/api/kj/vip-clients/{club.club_id}", headers=_headers(kj["token"]))
    assert resp.status_code == 200
    ids = {row["id"] for row in resp.get_json()["data"]}
    assert ids == {vip1.id, vip2.id}


def test_list_vip_clients_excludes_other_clubs_data(client, db, club, other_club, kj):
    _make_vip(db, club.club_id, telegram_user_id=111)
    _make_vip(db, other_club.club_id, telegram_user_id=222)

    resp = client.get(f"/api/kj/vip-clients/{club.club_id}", headers=_headers(kj["token"]))
    rows = resp.get_json()["data"]
    assert len(rows) == 1
    assert rows[0]["telegram_user_id"] == 111


def test_list_vip_clients_forbidden_for_other_club_url(client, db, other_club, kj):
    """kj — оператор club (fixture), пытается запросить список other_club по URL."""
    resp = client.get(f"/api/kj/vip-clients/{other_club.club_id}", headers=_headers(kj["token"]))
    assert resp.status_code == 403


def test_manual_vip_creation_endpoint_removed(client, kj):
    """ТЗ п.45 — старый POST /api/kj/vip-clients удалён целиком."""
    resp = client.post(
        "/api/kj/vip-clients", headers=_headers(kj["token"]), json={"cashback_percent": 15},
    )
    assert resp.status_code == 404


def test_vip_from_approved_request_is_then_listed(client, db, club, kj):
    token = _link_google_guest_id(client, club.club_id)
    request_id = client.post(
        "/api/guest/vip/request", headers=_headers(token)
    ).get_json()["data"]["id"]
    approved = client.put(
        f"/api/kj/vip-requests/{request_id}/approve", headers=kj["headers"]
    ).get_json()["data"]
    new_id = approved["vip_client"]["id"]

    list_resp = client.get(f"/api/kj/vip-clients/{club.club_id}", headers=_headers(kj["token"]))
    ids = {row["id"] for row in list_resp.get_json()["data"]}
    assert new_id in ids
