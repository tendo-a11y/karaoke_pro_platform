"""
Тесты блока "Управление KJ" Admin App — аудит handlers/admin.py::
show_kj_list/kj_assign_start/kj_remove_*/admin_kj_stats/kj_toggle_block_*.
План согласован перед реализацией: "уволить"+"заблокировать" объединены в
один is_active, персональная статистика через Order.confirmed_by, обычный
админ видит/управляет только своим клубом, перенос KJ между клубами —
только super_admin, POST /api/admin/kj — upsert по telegram_user_id.
"""
from datetime import datetime, timezone
from decimal import Decimal

from models import KJOperator, Order, STATUS_COMPLETED, Transaction, TX_TYPE_ORDER_PAYMENT


def _make_completed_order(db, club_id, kj_id, guest_id=555, amount="20.00"):
    order = Order(
        telegram_user_id=guest_id, club_id=club_id, table_no=1,
        guest_type="vip", song_title="Song", source="guest",
        status=STATUS_COMPLETED, confirmed_by=kj_id, completed_at=datetime.now(timezone.utc),
    )
    db.session.add(order)
    db.session.flush()
    tx = Transaction(
        club_id=club_id, telegram_user_id=guest_id, order_id=order.id,
        amount=Decimal(amount), type=TX_TYPE_ORDER_PAYMENT, description="test",
        idempotency_key=f"test-kj-stats:{order.id}",
    )
    db.session.add(tx)
    db.session.commit()
    return order


# --- GET /api/admin/kj ---

def test_super_admin_lists_all_kj(client, super_admin, kj, other_kj):
    resp = client.get("/api/admin/kj", headers=super_admin["headers"])
    assert resp.status_code == 200
    ids = {row["id"] for row in resp.get_json()["data"]}
    assert ids == {kj["operator"].id, other_kj["operator"].id}


def test_regular_admin_lists_only_own_club_kj(client, admin, kj, other_kj):
    resp = client.get("/api/admin/kj", headers=admin["headers"])
    assert resp.status_code == 200
    data = resp.get_json()["data"]
    assert len(data) == 1
    assert data[0]["id"] == kj["operator"].id


def test_list_kj_personal_stats_via_confirmed_by(client, db, super_admin, club, kj, other_kj):
    # Заказ подтверждён kj, но НЕ other_kj — несмотря на то что other_kj в другом клубе,
    # проверяем именно персональную привязку через confirmed_by, а не по клубу.
    _make_completed_order(db, club.club_id, kj["operator"].id, amount="30.00")

    resp = client.get("/api/admin/kj", headers=super_admin["headers"])
    data = {row["id"]: row for row in resp.get_json()["data"]}
    assert data[kj["operator"].id]["orders_completed_today"] == 1
    assert data[kj["operator"].id]["revenue_today"] == 30.00
    assert data[other_kj["operator"].id]["orders_completed_today"] == 0
    assert data[other_kj["operator"].id]["revenue_today"] == 0.0


def test_list_kj_requires_auth(client):
    resp = client.get("/api/admin/kj")
    assert resp.status_code == 401


# --- POST /api/admin/kj (assign / upsert) ---

def test_super_admin_creates_new_kj(client, super_admin, club):
    resp = client.post(
        "/api/admin/kj",
        json={"telegram_user_id": 555000, "display_name": "New KJ", "club_id": club.club_id},
        headers=super_admin["headers"],
    )
    assert resp.status_code == 201
    data = resp.get_json()["data"]
    assert data["telegram_user_id"] == 555000
    assert data["club_id"] == club.club_id
    assert data["is_active"] is True


def test_regular_admin_creates_kj_forced_to_own_club(client, admin, club):
    resp = client.post(
        "/api/admin/kj",
        json={"telegram_user_id": 555001, "display_name": "New KJ"},
        headers=admin["headers"],
    )
    assert resp.status_code == 201
    assert resp.get_json()["data"]["club_id"] == club.club_id


def test_regular_admin_cannot_assign_to_other_club(client, admin, other_club):
    resp = client.post(
        "/api/admin/kj",
        json={"telegram_user_id": 555002, "display_name": "X", "club_id": other_club.club_id},
        headers=admin["headers"],
    )
    assert resp.status_code == 403


def test_super_admin_can_reassign_existing_kj_to_another_club(client, db, super_admin, club, other_club, kj):
    resp = client.post(
        "/api/admin/kj",
        json={
            "telegram_user_id": kj["operator"].telegram_user_id,
            "display_name": "Moved KJ",
            "club_id": other_club.club_id,
        },
        headers=super_admin["headers"],
    )
    assert resp.status_code == 201
    data = resp.get_json()["data"]
    assert data["id"] == kj["operator"].id  # тот же KJ, не новая запись
    assert data["club_id"] == other_club.club_id
    assert data["display_name"] == "Moved KJ"

    # в базе реально одна запись, не дубликат
    assert KJOperator.query.filter_by(telegram_user_id=kj["operator"].telegram_user_id).count() == 1


def test_regular_admin_cannot_reassign_kj_from_other_club(client, admin, other_kj):
    """other_kj принадлежит other_club — обычный админ клуба club не может забрать его себе."""
    resp = client.post(
        "/api/admin/kj",
        json={"telegram_user_id": other_kj["operator"].telegram_user_id, "display_name": "Stolen"},
        headers=admin["headers"],
    )
    assert resp.status_code == 403


def test_assign_reactivates_deactivated_kj(client, db, super_admin, club, kj):
    kj["operator"].is_active = False
    db.session.commit()

    resp = client.post(
        "/api/admin/kj",
        json={"telegram_user_id": kj["operator"].telegram_user_id, "display_name": "Back", "club_id": club.club_id},
        headers=super_admin["headers"],
    )
    assert resp.status_code == 201
    assert resp.get_json()["data"]["is_active"] is True


def test_assign_requires_display_name(client, super_admin, club):
    resp = client.post(
        "/api/admin/kj", json={"telegram_user_id": 1, "club_id": club.club_id}, headers=super_admin["headers"],
    )
    assert resp.status_code == 400


def test_assign_rejects_non_positive_telegram_id(client, super_admin, club):
    resp = client.post(
        "/api/admin/kj",
        json={"telegram_user_id": -5, "display_name": "X", "club_id": club.club_id},
        headers=super_admin["headers"],
    )
    assert resp.status_code == 400


def test_super_admin_assign_requires_club_id(client, super_admin):
    resp = client.post(
        "/api/admin/kj", json={"telegram_user_id": 1, "display_name": "X"}, headers=super_admin["headers"],
    )
    assert resp.status_code == 400


# --- PUT /api/admin/kj/<id> ---

def test_regular_admin_edits_display_name(client, admin, kj):
    resp = client.put(
        f"/api/admin/kj/{kj['operator'].id}", json={"display_name": "Renamed"}, headers=admin["headers"],
    )
    assert resp.status_code == 200
    assert resp.get_json()["data"]["display_name"] == "Renamed"


def test_regular_admin_cannot_change_club_id(client, admin, kj, other_club):
    resp = client.put(
        f"/api/admin/kj/{kj['operator'].id}", json={"club_id": other_club.club_id}, headers=admin["headers"],
    )
    assert resp.status_code == 403


def test_super_admin_can_change_club_id(client, super_admin, kj, other_club):
    resp = client.put(
        f"/api/admin/kj/{kj['operator'].id}", json={"club_id": other_club.club_id}, headers=super_admin["headers"],
    )
    assert resp.status_code == 200
    assert resp.get_json()["data"]["club_id"] == other_club.club_id


def test_regular_admin_cannot_edit_other_club_kj(client, admin, other_kj):
    resp = client.put(
        f"/api/admin/kj/{other_kj['operator'].id}", json={"display_name": "X"}, headers=admin["headers"],
    )
    assert resp.status_code == 403


def test_update_kj_404(client, super_admin):
    resp = client.put("/api/admin/kj/999999", json={"display_name": "X"}, headers=super_admin["headers"])
    assert resp.status_code == 404


# --- PUT /api/admin/kj/<id>/status ---

def test_regular_admin_deactivates_own_kj(client, admin, kj):
    resp = client.put(
        f"/api/admin/kj/{kj['operator'].id}/status", json={"is_active": False}, headers=admin["headers"],
    )
    assert resp.status_code == 200
    assert resp.get_json()["data"]["is_active"] is False


def test_regular_admin_cannot_toggle_other_club_kj(client, admin, other_kj):
    resp = client.put(
        f"/api/admin/kj/{other_kj['operator'].id}/status", json={"is_active": False}, headers=admin["headers"],
    )
    assert resp.status_code == 403


def test_super_admin_toggles_any_kj(client, super_admin, other_kj):
    resp = client.put(
        f"/api/admin/kj/{other_kj['operator'].id}/status", json={"is_active": False}, headers=super_admin["headers"],
    )
    assert resp.status_code == 200
    assert resp.get_json()["data"]["is_active"] is False


def test_toggle_status_rejects_non_boolean(client, super_admin, kj):
    resp = client.put(
        f"/api/admin/kj/{kj['operator'].id}/status", json={"is_active": "yes"}, headers=super_admin["headers"],
    )
    assert resp.status_code == 400


def test_deactivated_kj_loses_kj_panel_access(client, db, admin, kj, app):
    """Живая проверка, что is_active реально работает как замена старого
    "уволен"/"заблокирован" — require_kj должен отказать после деактивации."""
    from auth import issue_kj_token

    token = issue_kj_token(kj["operator"].telegram_user_id, app.config["KJ_JWT_SECRET"], 3600)
    resp = client.get("/api/kj/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200

    client.put(
        f"/api/admin/kj/{kj['operator'].id}/status", json={"is_active": False}, headers=admin["headers"],
    )

    resp2 = client.get("/api/kj/me", headers={"Authorization": f"Bearer {token}"})
    assert resp2.status_code == 403
