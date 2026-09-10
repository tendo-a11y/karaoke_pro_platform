"""
Тесты блока "Управление клубами" Admin App (GET/POST/PUT/DELETE
/api/admin/clubs*) — аудит handlers/admin.py::show_venues/venue_add_*/
venue_show_details/venue_finance_details/venue_edit_name_*/venue_toggle_*/
venue_delete_*/venue_qr_code, план блока согласован с пользователем перед
реализацией (см. отчёт по плану): super_admin видит/управляет всеми
клубами, обычный админ — только своим; DELETE — guard-delete; QR — один
код на стол, а не один на клуб.
"""
from decimal import Decimal

from models import Order, Transaction, TX_TYPE_ORDER_PAYMENT


def _make_order_payment(db, club_id, amount="10.00", guest_id=555, order_id=None):
    if order_id is None:
        order = Order(
            telegram_user_id=guest_id, club_id=club_id, table_no=1,
            guest_type="vip", song_title="Song", source="guest",
        )
        db.session.add(order)
        db.session.flush()
        order_id = order.id
    tx = Transaction(
        club_id=club_id, telegram_user_id=guest_id, order_id=order_id,
        amount=Decimal(amount), type=TX_TYPE_ORDER_PAYMENT, description="test",
        idempotency_key=f"test:{club_id}:{order_id}:{amount}",
    )
    db.session.add(tx)
    db.session.commit()
    return tx


# --- GET /api/admin/clubs ---

def test_super_admin_lists_all_clubs(client, super_admin, club, other_club):
    resp = client.get("/api/admin/clubs", headers=super_admin["headers"])
    assert resp.status_code == 200
    club_ids = {c["club_id"] for c in resp.get_json()["data"]}
    assert club_ids == {club.club_id, other_club.club_id}


def test_regular_admin_lists_only_own_club(client, admin, club, other_club):
    resp = client.get("/api/admin/clubs", headers=admin["headers"])
    assert resp.status_code == 200
    data = resp.get_json()["data"]
    assert len(data) == 1
    assert data[0]["club_id"] == club.club_id


def test_list_clubs_includes_revenue_today(client, db, super_admin, club):
    _make_order_payment(db, club.club_id, amount="15.50")
    resp = client.get("/api/admin/clubs", headers=super_admin["headers"])
    data = resp.get_json()["data"]
    entry = next(c for c in data if c["club_id"] == club.club_id)
    assert entry["revenue_today"] == 15.50


def test_list_clubs_requires_auth(client):
    resp = client.get("/api/admin/clubs")
    assert resp.status_code == 401


# --- GET /api/admin/clubs/<id> ---

def test_get_club_detail_includes_finance_and_kj(client, db, super_admin, club, kj):
    _make_order_payment(db, club.club_id, amount="100.00")
    resp = client.get(f"/api/admin/clubs/{club.club_id}", headers=super_admin["headers"])
    assert resp.status_code == 200
    data = resp.get_json()["data"]
    assert data["revenue_today"] == 100.00
    assert data["revenue_week"] == 100.00
    assert data["revenue_month"] == 100.00
    # ADMIN_COMMISSION по умолчанию 0.05 (см. config.py)
    assert data["admin_cashback"] == 5.00
    assert data["songs_count"] == 0
    assert [k["id"] for k in data["kj_operators"]] == [kj["operator"].id]


def test_regular_admin_cannot_see_other_club_detail(client, admin, other_club):
    resp = client.get(f"/api/admin/clubs/{other_club.club_id}", headers=admin["headers"])
    assert resp.status_code == 403


def test_regular_admin_sees_own_club_detail(client, admin, club):
    resp = client.get(f"/api/admin/clubs/{club.club_id}", headers=admin["headers"])
    assert resp.status_code == 200
    assert resp.get_json()["data"]["club_id"] == club.club_id


def test_get_club_detail_404(client, super_admin):
    resp = client.get("/api/admin/clubs/999999", headers=super_admin["headers"])
    assert resp.status_code == 404


# --- POST /api/admin/clubs ---

def test_super_admin_creates_club(client, super_admin, club, other_club):
    resp = client.post(
        "/api/admin/clubs",
        json={"name": "New Club", "city": "Chisinau", "phone": "+373...", "email": "a@b.c", "table_count": 12},
        headers=super_admin["headers"],
    )
    assert resp.status_code == 201
    data = resp.get_json()["data"]
    # club/other_club фикстуры уже заняли id 1 и 2 — новый должен получить 3
    assert data["club_id"] == 3
    assert data["name"] == "New Club"
    assert data["table_count"] == 12


def test_regular_admin_cannot_create_club(client, admin):
    resp = client.post("/api/admin/clubs", json={"name": "Nope"}, headers=admin["headers"])
    assert resp.status_code == 403


def test_create_club_requires_name(client, super_admin):
    resp = client.post("/api/admin/clubs", json={"city": "X"}, headers=super_admin["headers"])
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "VALIDATION_ERROR"


def test_create_club_rejects_negative_table_count(client, super_admin):
    resp = client.post(
        "/api/admin/clubs", json={"name": "X", "table_count": -1}, headers=super_admin["headers"],
    )
    assert resp.status_code == 400


# --- PUT /api/admin/clubs/<id> ---

def test_regular_admin_edits_own_club(client, admin, club):
    resp = client.put(
        f"/api/admin/clubs/{club.club_id}",
        json={"city": "Balti", "table_count": 8},
        headers=admin["headers"],
    )
    assert resp.status_code == 200
    data = resp.get_json()["data"]
    assert data["city"] == "Balti"
    assert data["table_count"] == 8
    assert data["name"] == club.name  # не тронуто


def test_regular_admin_cannot_edit_other_club(client, admin, other_club):
    resp = client.put(
        f"/api/admin/clubs/{other_club.club_id}", json={"city": "X"}, headers=admin["headers"],
    )
    assert resp.status_code == 403


def test_update_club_rejects_empty_name(client, super_admin, club):
    resp = client.put(
        f"/api/admin/clubs/{club.club_id}", json={"name": "   "}, headers=super_admin["headers"],
    )
    assert resp.status_code == 400


# --- PUT /api/admin/clubs/<id>/status ---

def test_super_admin_blocks_club(client, super_admin, club):
    resp = client.put(
        f"/api/admin/clubs/{club.club_id}/status", json={"is_active": False}, headers=super_admin["headers"],
    )
    assert resp.status_code == 200
    assert resp.get_json()["data"]["is_active"] is False


def test_regular_admin_cannot_toggle_own_club_status(client, admin, club):
    resp = client.put(
        f"/api/admin/clubs/{club.club_id}/status", json={"is_active": False}, headers=admin["headers"],
    )
    assert resp.status_code == 403


def test_toggle_status_rejects_non_boolean(client, super_admin, club):
    resp = client.put(
        f"/api/admin/clubs/{club.club_id}/status", json={"is_active": "yes"}, headers=super_admin["headers"],
    )
    assert resp.status_code == 400


# --- DELETE /api/admin/clubs/<id> (guard-delete) ---

def test_super_admin_deletes_empty_club(client, super_admin, other_club):
    resp = client.delete(f"/api/admin/clubs/{other_club.club_id}", headers=super_admin["headers"])
    assert resp.status_code == 200
    assert resp.get_json()["data"]["deleted"] is True

    resp2 = client.get(f"/api/admin/clubs/{other_club.club_id}", headers=super_admin["headers"])
    assert resp2.status_code == 404


def test_delete_guarded_when_club_has_orders(client, db, super_admin, club):
    _make_order_payment(db, club.club_id)
    resp = client.delete(f"/api/admin/clubs/{club.club_id}", headers=super_admin["headers"])
    assert resp.status_code == 409
    assert resp.get_json()["error"] == "CLUB_HAS_DATA"

    # клуб реально не удалён
    resp2 = client.get(f"/api/admin/clubs/{club.club_id}", headers=super_admin["headers"])
    assert resp2.status_code == 200


def test_regular_admin_cannot_delete_club(client, admin, club):
    resp = client.delete(f"/api/admin/clubs/{club.club_id}", headers=admin["headers"])
    assert resp.status_code == 403


# --- GET /api/admin/clubs/<id>/qr ---

def test_qr_links_one_per_table(client, super_admin, club, db):
    club.table_count = 3
    db.session.commit()
    resp = client.get(f"/api/admin/clubs/{club.club_id}/qr", headers=super_admin["headers"])
    assert resp.status_code == 200
    data = resp.get_json()["data"]
    assert data["table_count"] == 3
    assert [link["table_no"] for link in data["links"]] == [1, 2, 3]
    for link in data["links"]:
        assert f"club_id={club.club_id}" in link["url"]
        assert f"table_no={link['table_no']}" in link["url"]


def test_qr_links_empty_when_table_count_not_set(client, super_admin, club):
    resp = client.get(f"/api/admin/clubs/{club.club_id}/qr", headers=super_admin["headers"])
    assert resp.status_code == 200
    assert resp.get_json()["data"]["links"] == []


def test_regular_admin_cannot_get_other_club_qr(client, admin, other_club):
    resp = client.get(f"/api/admin/clubs/{other_club.club_id}/qr", headers=admin["headers"])
    assert resp.status_code == 403
