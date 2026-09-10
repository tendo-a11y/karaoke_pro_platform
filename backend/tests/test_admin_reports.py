"""
Тесты блока "Отчёты" Admin App — аудит handlers/admin.py::report_today/
report_week/report_month/report_venues/report_cashback. Согласовано перед
реализацией: только super_admin, скользящие окна 24ч/7д/30д, процент от
полного итога (не от бага старого бота с частичной суммой внутри цикла),
CSV собирается на фронтенде (здесь не тестируется — backend отдаёт только JSON).
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from models import Order, STATUS_COMPLETED, Transaction, TX_TYPE_ORDER_PAYMENT


def _make_completed_order(db, club_id, amount, guest_id=555, completed_at=None):
    """
    completed_at управляет и Order.completed_at, и Transaction.created_at —
    _revenue_since (services/club_service.py) фильтрует именно по
    Transaction.created_at, а не по Order.completed_at, поэтому для тестов
    скользящих окон обе даты должны совпадать (иначе транзакция всегда
    попадает в окно "сегодня" по моменту создания в тесте, а не по
    смоделированной дате завершения заказа).
    """
    when = completed_at or datetime.now(timezone.utc)
    order = Order(
        telegram_user_id=guest_id, club_id=club_id, table_no=1,
        guest_type="vip", song_title="Song", source="guest",
        status=STATUS_COMPLETED, completed_at=when,
    )
    db.session.add(order)
    db.session.flush()
    tx = Transaction(
        club_id=club_id, telegram_user_id=guest_id, order_id=order.id,
        amount=Decimal(amount), type=TX_TYPE_ORDER_PAYMENT, description="test",
        idempotency_key=f"test-report:{order.id}", created_at=when,
    )
    db.session.add(tx)
    db.session.commit()
    return order


def test_requires_auth(client):
    resp = client.get("/api/admin/reports/overview")
    assert resp.status_code == 401


def test_regular_admin_forbidden(client, admin):
    resp = client.get("/api/admin/reports/overview", headers=admin["headers"])
    assert resp.status_code == 403
    assert resp.get_json()["error"] == "FORBIDDEN"


def test_overview_totals_and_commission(client, db, super_admin, club, other_club):
    _make_completed_order(db, club.club_id, "100.00")
    _make_completed_order(db, other_club.club_id, "50.00")

    resp = client.get("/api/admin/reports/overview", headers=super_admin["headers"])
    assert resp.status_code == 200
    data = resp.get_json()["data"]

    assert data["totals"]["revenue_today"] == 150.00
    assert data["totals"]["revenue_week"] == 150.00
    assert data["totals"]["revenue_month"] == 150.00
    assert data["totals"]["orders_completed_today"] == 2
    # ADMIN_COMMISSION по умолчанию 0.05
    assert data["totals"]["admin_commission_today"] == 7.50


def test_percent_of_total_correct_not_old_bug(client, db, super_admin, club, other_club):
    """
    Старый бот считал процент от частичной суммы внутри цикла (первый клуб
    в списке всегда получал 100%). Здесь процент — от полного итога по ВСЕМ
    клубам, посчитанного заранее.
    """
    _make_completed_order(db, club.club_id, "300.00")
    _make_completed_order(db, other_club.club_id, "100.00")

    resp = client.get("/api/admin/reports/overview", headers=super_admin["headers"])
    rows = {row["club_id"]: row for row in resp.get_json()["data"]["clubs"]}

    assert rows[club.club_id]["percent_of_total_today"] == 75.0
    assert rows[other_club.club_id]["percent_of_total_today"] == 25.0


def test_overview_zero_revenue_no_division_by_zero(client, super_admin, club):
    resp = client.get("/api/admin/reports/overview", headers=super_admin["headers"])
    assert resp.status_code == 200
    row = resp.get_json()["data"]["clubs"][0]
    assert row["percent_of_total_today"] == 0.0
    assert row["revenue_today"] == 0.0


def test_overview_sorted_by_revenue_month_desc(client, db, super_admin, club, other_club):
    _make_completed_order(db, club.club_id, "10.00")
    _make_completed_order(db, other_club.club_id, "500.00")

    resp = client.get("/api/admin/reports/overview", headers=super_admin["headers"])
    club_ids_in_order = [row["club_id"] for row in resp.get_json()["data"]["clubs"]]
    assert club_ids_in_order == [other_club.club_id, club.club_id]


def test_window_excludes_orders_older_than_30_days(client, db, super_admin, club):
    old_date = datetime.now(timezone.utc) - timedelta(days=40)
    _make_completed_order(db, club.club_id, "999.00", completed_at=old_date)

    resp = client.get("/api/admin/reports/overview", headers=super_admin["headers"])
    row = next(r for r in resp.get_json()["data"]["clubs"] if r["club_id"] == club.club_id)
    assert row["revenue_month"] == 0.0
    assert row["orders_completed_today"] == 0


def test_window_includes_order_within_7_days_but_not_1_day(client, db, super_admin, club):
    three_days_ago = datetime.now(timezone.utc) - timedelta(days=3)
    _make_completed_order(db, club.club_id, "40.00", completed_at=three_days_ago)

    resp = client.get("/api/admin/reports/overview", headers=super_admin["headers"])
    row = next(r for r in resp.get_json()["data"]["clubs"] if r["club_id"] == club.club_id)
    assert row["revenue_today"] == 0.0
    assert row["revenue_week"] == 40.0
    assert row["revenue_month"] == 40.0


def test_includes_inactive_and_contactless_clubs(client, super_admin, club, other_club, db):
    other_club.is_active = False
    db.session.commit()
    resp = client.get("/api/admin/reports/overview", headers=super_admin["headers"])
    rows = {row["club_id"]: row for row in resp.get_json()["data"]["clubs"]}
    assert rows[other_club.club_id]["is_active"] is False
