"""
Тесты блока "Системные функции" Admin App (Block #4) — аудит
show_system_menu/system_logs/system_backup из handlers/admin.py.
Согласовано перед реализацией: только super_admin, "Заказов всего" вместо
"Всего пользователей" (без придуманной интерпретации telegram_user_id как
гостя), размер БД через pg_database_size, backup — реальный pg_dump
(Plain SQL, --no-owner --no-privileges), потоковая отдача без временного
файла на диске.
"""
from datetime import datetime, timezone
from decimal import Decimal

from models import KJOperator, Order, STATUS_COMPLETED, Transaction, TX_TYPE_ORDER_PAYMENT


def _make_order(db, club_id, guest_id=555):
    order = Order(
        telegram_user_id=guest_id, club_id=club_id, table_no=1,
        guest_type="vip", song_title="Song", source="guest",
        status=STATUS_COMPLETED, completed_at=datetime.now(timezone.utc),
    )
    db.session.add(order)
    db.session.commit()
    return order


def _make_transaction(db, club_id, order_id, amount, guest_id=555, idem_suffix="x"):
    tx = Transaction(
        club_id=club_id, telegram_user_id=guest_id, order_id=order_id,
        amount=Decimal(amount), type=TX_TYPE_ORDER_PAYMENT, description="test tx",
        idempotency_key=f"test-system-{order_id}-{idem_suffix}",
    )
    db.session.add(tx)
    db.session.commit()
    return tx


# --- overview ---

def test_overview_requires_auth(client):
    resp = client.get("/api/admin/system/overview")
    assert resp.status_code == 401


def test_overview_regular_admin_forbidden(client, admin):
    resp = client.get("/api/admin/system/overview", headers=admin["headers"])
    assert resp.status_code == 403
    assert resp.get_json()["error"] == "FORBIDDEN"


def test_overview_counts(client, db, super_admin, club, other_club):
    order1 = _make_order(db, club.club_id)
    _make_order(db, other_club.club_id)

    active_kj = KJOperator(telegram_user_id=301, club_id=club.club_id, display_name="Active KJ", is_active=True)
    inactive_kj = KJOperator(telegram_user_id=302, club_id=club.club_id, display_name="Inactive KJ", is_active=False)
    db.session.add_all([active_kj, inactive_kj])
    db.session.commit()

    resp = client.get("/api/admin/system/overview", headers=super_admin["headers"])
    assert resp.status_code == 200
    data = resp.get_json()["data"]

    assert data["clubs_count"] == 2  # club + other_club
    assert data["kj_count"] == 2
    assert data["kj_active_count"] == 1
    assert data["orders_count"] == 2
    assert data["db_size_mb"] > 0
    assert "server_time" in data
    # Не должно быть придуманного "users_count"/"unique_guests" —
    # согласовано использовать ровно orders_count.
    assert "users_count" not in data
    assert "unique_guests_count" not in data
    del order1


# --- logs ---

def test_logs_requires_auth(client):
    resp = client.get("/api/admin/system/logs")
    assert resp.status_code == 401


def test_logs_regular_admin_forbidden(client, admin):
    resp = client.get("/api/admin/system/logs", headers=admin["headers"])
    assert resp.status_code == 403


def test_logs_returns_recent_transactions_with_exact_fields(client, db, super_admin, club):
    order = _make_order(db, club.club_id)
    _make_transaction(db, club.club_id, order.id, "77.50", idem_suffix="a")

    resp = client.get("/api/admin/system/logs", headers=super_admin["headers"])
    assert resp.status_code == 200
    rows = resp.get_json()["data"]
    assert len(rows) >= 1
    row = rows[0]
    # Поля 1:1 из старого system_logs — без добавленного club_name.
    assert set(row.keys()) == {"type", "amount", "description", "created_at"}
    assert row["type"] == TX_TYPE_ORDER_PAYMENT


def test_logs_limited_to_20_most_recent(client, db, super_admin, club):
    order = _make_order(db, club.club_id)
    for i in range(25):
        _make_transaction(db, club.club_id, order.id, "1.00", idem_suffix=str(i))

    resp = client.get("/api/admin/system/logs", headers=super_admin["headers"])
    rows = resp.get_json()["data"]
    assert len(rows) == 20


# --- backup ---

def test_backup_requires_auth(client):
    resp = client.get("/api/admin/system/backup")
    assert resp.status_code == 401


def test_backup_regular_admin_forbidden(client, admin):
    resp = client.get("/api/admin/system/backup", headers=admin["headers"])
    assert resp.status_code == 403


def test_backup_returns_valid_sql_dump(client, super_admin):
    resp = client.get("/api/admin/system/backup", headers=super_admin["headers"])
    assert resp.status_code == 200
    assert resp.headers["Content-Type"].startswith("application/sql")
    assert "attachment; filename=backup_" in resp.headers["Content-Disposition"]

    body = resp.get_data(as_text=True)
    # Plain SQL дамп реального pg_dump на тестовой БД — проверяем, что это
    # не заглушка, а настоящий дамп схемы проекта.
    assert "PostgreSQL database dump" in body
    assert "CREATE TABLE" in body
    assert "clubs" in body
    assert "transactions" in body
    # --no-owner --no-privileges — в дампе не должно быть OWNER TO/GRANT.
    assert "OWNER TO" not in body
