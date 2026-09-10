"""
Тесты гостевой истории финансов (единая хронологическая лента) — старое:
handlers/vip.py::vip_finances (4 отдельные секции по типу с
промежуточными итогами). Здесь по решению — один эндпоинт,
GET /api/guest/vip/transactions, отдающий все типы вперемешку по времени,
включая ручные корректировки KJ (topup/manual_debit), которых в старом
боте гость вообще не видел (аудит по VIP-пополнению, баг №7).
"""
from decimal import Decimal

from models import Transaction, TX_TYPE_CASHBACK, TX_TYPE_ORDER_PAYMENT, TX_TYPE_TOPUP, VipClient


def _headers(token):
    return {"Authorization": f"Bearer {token}"}


def _make_vip(db, club_id, telegram_user_id=555000111, balance="0.00"):
    vip = VipClient(club_id=club_id, telegram_user_id=telegram_user_id, balance=Decimal(balance), cashback_percent=0)
    db.session.add(vip)
    db.session.commit()
    return vip


def test_empty_history_for_fresh_vip(client, db, club, kj):
    vip = _make_vip(db, club.club_id)
    resp = client.post(
        f"/api/kj/vip-clients/{vip.id}/topup", json={"amount": 1}, headers=_headers(kj["token"]),
    )
    assert resp.status_code == 200
    # Токен для гостя нужен для чтения его же истории — session с этим же guest_id.
    from auth import issue_guest_token
    from flask import current_app
    with client.application.app_context():
        token = issue_guest_token(
            vip.telegram_user_id, club.club_id, None,
            current_app.config["GUEST_JWT_SECRET"], current_app.config["GUEST_JWT_TTL_SECONDS"],
        )
    resp = client.get("/api/guest/vip/transactions", headers=_headers(token))
    assert resp.status_code == 200
    data = resp.get_json()["data"]
    assert len(data) == 1
    assert data[0]["type"] == TX_TYPE_TOPUP
    assert data[0]["amount"] == 1.0


def test_history_includes_all_transaction_types_newest_first(client, db, club, kj):
    vip = _make_vip(db, club.club_id, balance="50.00")

    from auth import issue_guest_token
    from flask import current_app
    with client.application.app_context():
        token = issue_guest_token(
            vip.telegram_user_id, club.club_id, None,
            current_app.config["GUEST_JWT_SECRET"], current_app.config["GUEST_JWT_TTL_SECONDS"],
        )

    # Ручное начисление KJ (topup) и списание (manual_debit).
    client.post(f"/api/kj/vip-clients/{vip.id}/topup", json={"amount": 10}, headers=_headers(kj["token"]))
    client.post(f"/api/kj/vip-clients/{vip.id}/debit", json={"amount": 5}, headers=_headers(kj["token"]))

    # Оплата заказа + кэшбэк через обычный путь завершения (billing_service).
    from models import Order, Service
    service = Service(club_id=club.club_id, name="VIP-стол", price=Decimal("20.00"))
    db.session.add(service)
    db.session.commit()
    vip.cashback_percent = Decimal("10.00")
    db.session.commit()
    order = Order(
        telegram_user_id=vip.telegram_user_id, club_id=club.club_id, table_no=None,
        guest_type="vip", song_title="Тест", service_id=service.id, source="guest",
        status="completed",
    )
    db.session.add(order)
    db.session.commit()
    from services.billing_service import charge_at_completion
    charge_at_completion(order)

    resp = client.get("/api/guest/vip/transactions", headers=_headers(token))
    assert resp.status_code == 200
    data = resp.get_json()["data"]

    types_seen = {row["type"] for row in data}
    assert types_seen == {TX_TYPE_TOPUP, "manual_debit", TX_TYPE_ORDER_PAYMENT, TX_TYPE_CASHBACK}
    assert len(data) == 4

    # Новейшие первыми.
    timestamps = [row["created_at"] for row in data]
    assert timestamps == sorted(timestamps, reverse=True)

    # Оплата заказа несёт order_id, ручные корректировки — нет.
    payment_row = next(r for r in data if r["type"] == TX_TYPE_ORDER_PAYMENT)
    assert payment_row["order_id"] == order.id
    topup_row = next(r for r in data if r["type"] == TX_TYPE_TOPUP)
    assert topup_row["order_id"] is None


def test_days_filter_excludes_old_transactions(client, db, club, kj):
    from datetime import datetime, timedelta, timezone

    vip = _make_vip(db, club.club_id)
    old_tx = Transaction(
        club_id=club.club_id, telegram_user_id=vip.telegram_user_id, amount=Decimal("5.00"),
        type=TX_TYPE_TOPUP, description="старое", idempotency_key="old-1",
        created_at=datetime.now(timezone.utc) - timedelta(days=30),
    )
    db.session.add(old_tx)
    db.session.commit()

    client.post(f"/api/kj/vip-clients/{vip.id}/topup", json={"amount": 7}, headers=_headers(kj["token"]))

    from auth import issue_guest_token
    from flask import current_app
    with client.application.app_context():
        token = issue_guest_token(
            vip.telegram_user_id, club.club_id, None,
            current_app.config["GUEST_JWT_SECRET"], current_app.config["GUEST_JWT_TTL_SECONDS"],
        )

    resp = client.get("/api/guest/vip/transactions", headers=_headers(token))
    assert len(resp.get_json()["data"]) == 2

    resp = client.get("/api/guest/vip/transactions?days=7", headers=_headers(token))
    data = resp.get_json()["data"]
    assert len(data) == 1
    assert data[0]["amount"] == 7.0


def test_history_scoped_to_own_guest_only(client, db, club, kj):
    vip1 = _make_vip(db, club.club_id, telegram_user_id=1001)
    vip2 = _make_vip(db, club.club_id, telegram_user_id=1002)

    client.post(f"/api/kj/vip-clients/{vip1.id}/topup", json={"amount": 10}, headers=_headers(kj["token"]))
    client.post(f"/api/kj/vip-clients/{vip2.id}/topup", json={"amount": 20}, headers=_headers(kj["token"]))

    from auth import issue_guest_token
    from flask import current_app
    with client.application.app_context():
        token1 = issue_guest_token(
            vip1.telegram_user_id, club.club_id, None,
            current_app.config["GUEST_JWT_SECRET"], current_app.config["GUEST_JWT_TTL_SECONDS"],
        )

    resp = client.get("/api/guest/vip/transactions", headers=_headers(token1))
    data = resp.get_json()["data"]
    assert len(data) == 1
    assert data[0]["amount"] == 10.0


def test_no_history_for_regular_non_vip_guest(client, db, club):
    resp = client.post("/api/guest/session", json={"club_id": club.club_id, "table_no": 9})
    session = resp.get_json()["data"]
    resp = client.get("/api/guest/vip/transactions", headers=_headers(session["token"]))
    assert resp.status_code == 200
    assert resp.get_json()["data"] == []


def test_transactions_requires_auth(client, db, club):
    resp = client.get("/api/guest/vip/transactions")
    assert resp.status_code == 401
