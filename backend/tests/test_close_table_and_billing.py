"""
Тесты на два запроса пользователя от 2026-09-19:

  1. "Готово" означает, что можно списывать оплату по тарифу — но списание
     (services/billing_service.py::charge_at_completion) существовало
     отдельно и никогда не вызывалось из самой кнопки "Готово"
     (services/vdj_service.py::complete_order). См. её обновлённый
     докстринг.
  2. "Закрыть стол" — из карточки гостя в KJ Panel: снять со стола +
     заблокировать + отклонить всё ещё непроигранное с этого стола одним
     действием (services/guest_status_service.py::close_table).
"""
from decimal import Decimal

from extensions import db as _db
from models import (
    STATUS_ERROR,
    STATUS_PENDING,
    STATUS_QUEUED,
    STATUS_REJECTED,
    Order,
    Service,
    VipClient,
    Transaction,
)
from services import guest_status_service
from services.vdj_service import close_table_orders


def _make_service(db, club_id, price="10.00"):
    s = Service(club_id=club_id, name="Обычная песня", price=Decimal(price), is_free=False)
    db.session.add(s)
    db.session.commit()
    return s


def _make_vip(db, club_id, telegram_user_id, balance="50.00"):
    v = VipClient(club_id=club_id, telegram_user_id=telegram_user_id, balance=Decimal(balance))
    db.session.add(v)
    db.session.commit()
    return v


def _make_queued_order(db, club_id, telegram_user_id=555, table_no=5, guest_type="vip", service_id=None):
    o = Order(
        telegram_user_id=telegram_user_id,
        club_id=club_id,
        table_no=table_no,
        guest_type=guest_type,
        song_title="Test Song",
        artist="Test Artist",
        service_id=service_id,
        status=STATUS_QUEUED,
    )
    db.session.add(o)
    db.session.commit()
    return o


# --- "Готово" теперь реально списывает оплату у VIP ---

def test_complete_order_charges_vip_guest(app, db, club, kj):
    with app.app_context():
        service = _make_service(db, club.club_id, price="20.00")
        vip = _make_vip(db, club.club_id, telegram_user_id=555, balance="50.00")
        order = _make_queued_order(db, club.club_id, telegram_user_id=555, service_id=service.id)
        order_id = order.id
        vip_id = vip.id

    resp = app.test_client().put(f"/api/kj/order/{order_id}/complete", headers=kj["headers"])
    assert resp.status_code == 200
    data = resp.get_json()["data"]
    assert data["status"] == "completed"
    assert data["charge"]["charged"] is True
    assert data["charge"]["charge_amount"] == 20.0

    with app.app_context():
        vip = _db.session.get(VipClient, vip_id)
        assert vip.balance == Decimal("30.00")
        assert Transaction.query.filter_by(order_id=order_id).count() == 1


def test_complete_order_does_not_charge_non_vip_guest(app, db, club, kj):
    with app.app_context():
        service = _make_service(db, club.club_id, price="20.00")
        order = _make_queued_order(db, club.club_id, telegram_user_id=556, guest_type="client", service_id=service.id)
        order_id = order.id

    resp = app.test_client().put(f"/api/kj/order/{order_id}/complete", headers=kj["headers"])
    assert resp.status_code == 200
    data = resp.get_json()["data"]
    assert data["status"] == "completed"
    assert data["charge"]["charged"] is False
    assert data["charge"]["skipped_reason"] == "not_vip"

    with app.app_context():
        assert Transaction.query.filter_by(order_id=order_id).count() == 0


# --- Доска: заказ несёт guest_type, чтобы фронтенд мог скрыть "Готово" ---

def test_orders_board_slot_exposes_guest_type(app, db, club, kj):
    with app.app_context():
        club.table_count = 2
        db.session.commit()
        _make_queued_order(db, club.club_id, telegram_user_id=555, table_no=1, guest_type="vip")
        _make_queued_order(db, club.club_id, telegram_user_id=556, table_no=2, guest_type="client")

    resp = app.test_client().get(f"/api/kj/orders-board/{club.club_id}", headers=kj["headers"])
    assert resp.status_code == 200
    board = resp.get_json()["data"]
    guest_types = {
        slot["guest_type"]
        for table in board
        for slot in table["slots"]
        if slot is not None
    }
    assert guest_types == {"vip", "client"}


# --- close_table_orders: массовое отклонение заказов стола ---

def test_close_table_orders_rejects_active_orders_of_that_table_only(app, db, club):
    with app.app_context():
        o1 = _make_queued_order(db, club.club_id, telegram_user_id=555, table_no=1)
        o2 = Order(
            telegram_user_id=555, club_id=club.club_id, table_no=1, guest_type="vip",
            song_title="Второй трек", status=STATUS_PENDING,
        )
        db.session.add(o2)
        other_table = _make_queued_order(db, club.club_id, telegram_user_id=557, table_no=2)
        already_done = Order(
            telegram_user_id=555, club_id=club.club_id, table_no=1, guest_type="vip",
            song_title="Уже сыграно", status="completed",
        )
        db.session.add(already_done)
        db.session.commit()

        closed = close_table_orders(club.club_id, 1)
        closed_ids = {o.id for o in closed}
        assert closed_ids == {o1.id, o2.id}

        _db.session.refresh(o1)
        _db.session.refresh(o2)
        _db.session.refresh(other_table)
        assert o1.status == STATUS_REJECTED
        assert o2.status == STATUS_REJECTED
        assert other_table.status == STATUS_QUEUED  # другой стол не тронут


def test_close_table_orders_noop_when_nothing_active(app, db, club):
    with app.app_context():
        assert close_table_orders(club.club_id, 99) == []


# --- guest_status_service.close_table: снять со стола + заблокировать + отклонить ---

def test_guest_status_close_table_full_flow(app, db, club, kj):
    with app.app_context():
        order = _make_queued_order(db, club.club_id, telegram_user_id=555, table_no=4)
        order_id = order.id

        result = guest_status_service.close_table(club.club_id, 555, kj["operator"])

        assert result["status"].is_blocked is True
        assert result["status"].table_no is None
        assert {o.id for o in result["closed_orders"]} == {order_id}

        _db.session.refresh(order)
        assert order.status == STATUS_REJECTED


def test_close_table_route(app, db, club, kj):
    with app.app_context():
        order = _make_queued_order(db, club.club_id, telegram_user_id=555, table_no=4)
        order_id = order.id

    resp = app.test_client().post("/api/kj/guests/555/close-table", headers=kj["headers"])
    assert resp.status_code == 200
    data = resp.get_json()["data"]
    assert data["status"]["is_blocked"] is True
    assert data["closed_order_ids"] == [order_id]

    with app.app_context():
        refreshed = _db.session.get(Order, order_id)
        assert refreshed.status == STATUS_REJECTED
