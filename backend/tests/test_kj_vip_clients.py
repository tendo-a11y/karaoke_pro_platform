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


def test_list_vip_clients_includes_is_blocked(client, db, club, kj):
    """Запрос пользователя 2026-09-23 "нужно иметь возможность блокировать
    VIP" — фронтенду вкладки VIP нужно текущее состояние блокировки, чтобы
    показать правильную кнопку (см. routes/kj.py::list_vip_clients)."""
    vip = _make_vip(db, club.club_id, telegram_user_id=333)

    resp = client.get(f"/api/kj/vip-clients/{club.club_id}", headers=_headers(kj["token"]))
    row = next(r for r in resp.get_json()["data"] if r["id"] == vip.id)
    assert row["is_blocked"] is False

    client.post(f"/api/kj/guests/{vip.telegram_user_id}/block", headers=_headers(kj["token"]))

    resp2 = client.get(f"/api/kj/vip-clients/{club.club_id}", headers=_headers(kj["token"]))
    row2 = next(r for r in resp2.get_json()["data"] if r["id"] == vip.id)
    assert row2["is_blocked"] is True


# --- DELETE /vip-clients/<id> ("Удалить" = перевести обратно в простые) ---

def test_remove_vip_client_requires_auth(client, club):
    resp = client.delete(f"/api/kj/vip-clients/1")
    assert resp.status_code == 401


def test_remove_vip_client_not_found(client, kj):
    resp = client.delete("/api/kj/vip-clients/999999", headers=_headers(kj["token"]))
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "VIP_CLIENT_NOT_FOUND"


def test_remove_vip_client_forbidden_for_other_club(client, db, other_club, kj):
    vip = _make_vip(db, other_club.club_id, telegram_user_id=444, balance="0")
    resp = client.delete(f"/api/kj/vip-clients/{vip.id}", headers=_headers(kj["token"]))
    assert resp.status_code == 403


def test_remove_vip_client_refuses_when_balance_not_zero(client, db, club, kj):
    vip = _make_vip(db, club.club_id, telegram_user_id=555, balance="12.50")
    resp = client.delete(f"/api/kj/vip-clients/{vip.id}", headers=_headers(kj["token"]))
    assert resp.status_code == 409
    assert resp.get_json()["error"] == "VIP_BALANCE_NOT_ZERO"

    still_listed = client.get(f"/api/kj/vip-clients/{club.club_id}", headers=_headers(kj["token"]))
    ids = {row["id"] for row in still_listed.get_json()["data"]}
    assert vip.id in ids


def test_remove_vip_client_ok_when_balance_zero(client, db, club, kj):
    vip = _make_vip(db, club.club_id, telegram_user_id=666, balance="0")
    resp = client.delete(f"/api/kj/vip-clients/{vip.id}", headers=_headers(kj["token"]))
    assert resp.status_code == 200
    assert resp.get_json()["data"]["removed"] is True

    still_listed = client.get(f"/api/kj/vip-clients/{club.club_id}", headers=_headers(kj["token"]))
    ids = {row["id"] for row in still_listed.get_json()["data"]}
    assert vip.id not in ids


def test_remove_vip_client_demotes_guest_type_in_directory(client, db, club, kj):
    """"это означает перевести его в простые" — guest_directory_service
    должна после удаления показывать этого гостя как client/no_table, а не
    vip (guest_type вычисляется по самому факту наличия VipClient, см.
    guest_directory_service._guest_type)."""
    token = _link_google_guest_id(client, club.club_id, table_no=7)
    guest_id = int(client.get("/api/guest/me", headers=_headers(token)).get_json()["data"]["guest_id"])
    vip = _make_vip(db, club.club_id, telegram_user_id=guest_id, balance="0")

    before = client.get(f"/api/kj/guests/{club.club_id}/{guest_id}", headers=_headers(kj["token"])).get_json()["data"]
    assert before["guest_type"] == "vip"

    client.delete(f"/api/kj/vip-clients/{vip.id}", headers=_headers(kj["token"]))

    after = client.get(f"/api/kj/guests/{club.club_id}/{guest_id}", headers=_headers(kj["token"])).get_json()["data"]
    assert after["guest_type"] == "client"
