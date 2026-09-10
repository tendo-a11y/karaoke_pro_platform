from decimal import Decimal

from extensions import db as _db
from models import Order, Service, VipClient, Transaction, TX_TYPE_ORDER_PAYMENT, TX_TYPE_CASHBACK
from services.billing_service import charge_at_completion


def _make_service(db, club_id=1, price="10.00", is_free=False):
    s = Service(club_id=club_id, name="Обычная песня", price=Decimal(price), is_free=is_free)
    db.session.add(s)
    db.session.commit()
    return s


def _make_vip(db, club_id=1, telegram_user_id=123456789, balance="50.00", cashback_percent="0"):
    v = VipClient(
        club_id=club_id,
        telegram_user_id=telegram_user_id,
        balance=Decimal(balance),
        cashback_percent=Decimal(cashback_percent),
    )
    db.session.add(v)
    db.session.commit()
    return v


def _make_order(db, club_id=1, telegram_user_id=123456789, service_id=None, guest_type="vip"):
    o = Order(
        telegram_user_id=telegram_user_id,
        club_id=club_id,
        table_no=5,
        guest_type=guest_type,
        song_title="Test Song",
        artist="Test Artist",
        service_id=service_id,
        status="completed",
    )
    db.session.add(o)
    db.session.commit()
    return o


def test_charge_and_cashback(app, db, club):
    service = _make_service(db, price="10.00")
    vip = _make_vip(db, balance="50.00", cashback_percent="10")
    order = _make_order(db, service_id=service.id)

    result = charge_at_completion(order)

    assert result.charged is True
    assert result.charge_amount == Decimal("10.00")
    assert result.cashback_amount == Decimal("1.00")

    _db.session.refresh(vip)
    assert vip.balance == Decimal("41.00")  # 50 - 10 + 1

    txs = Transaction.query.filter_by(order_id=order.id).all()
    assert len(txs) == 2
    types = {t.type for t in txs}
    assert types == {TX_TYPE_ORDER_PAYMENT, TX_TYPE_CASHBACK}


def test_charge_without_cashback(app, db, club):
    service = _make_service(db, price="15.00")
    vip = _make_vip(db, balance="30.00", cashback_percent="0")
    order = _make_order(db, service_id=service.id)

    result = charge_at_completion(order)

    assert result.charged is True
    assert result.charge_amount == Decimal("15.00")
    assert result.cashback_amount is None

    _db.session.refresh(vip)
    assert vip.balance == Decimal("15.00")

    txs = Transaction.query.filter_by(order_id=order.id).all()
    assert len(txs) == 1
    assert txs[0].type == TX_TYPE_ORDER_PAYMENT


def test_free_service_is_noop(app, db, club):
    service = _make_service(db, price="10.00", is_free=True)
    vip = _make_vip(db, balance="30.00")
    order = _make_order(db, service_id=service.id)

    result = charge_at_completion(order)

    assert result.charged is False
    assert result.skipped_reason == "free_or_missing_service"

    _db.session.refresh(vip)
    assert vip.balance == Decimal("30.00")
    assert Transaction.query.filter_by(order_id=order.id).count() == 0


def test_non_vip_guest_is_noop(app, db, club):
    service = _make_service(db, price="10.00")
    order = _make_order(db, service_id=service.id, guest_type="client")

    result = charge_at_completion(order)

    assert result.charged is False
    assert result.skipped_reason == "not_vip"
    assert Transaction.query.filter_by(order_id=order.id).count() == 0


def test_vip_guest_without_account_is_noop(app, db, club):
    service = _make_service(db, price="10.00")
    order = _make_order(db, service_id=service.id, guest_type="vip")
    # Намеренно не создаём VipClient — гость помечен как vip на момент
    # заказа, но счёта в этом клубе нет (пограничный случай).

    result = charge_at_completion(order)

    assert result.charged is False
    assert result.skipped_reason == "no_vip_account"


def test_no_service_id_is_noop(app, db, club):
    order = _make_order(db, service_id=None)

    result = charge_at_completion(order)

    assert result.charged is False
    assert result.skipped_reason == "no_service_id"


def test_idempotent_double_call(app, db, club):
    service = _make_service(db, price="10.00")
    vip = _make_vip(db, balance="50.00", cashback_percent="10")
    order = _make_order(db, service_id=service.id)

    first = charge_at_completion(order)
    second = charge_at_completion(order)

    assert first.charged is True
    assert second.charged is False
    assert second.already_processed is True
    assert second.charge_amount == Decimal("10.00")

    _db.session.refresh(vip)
    # Баланс изменился только один раз, а не дважды.
    assert vip.balance == Decimal("41.00")

    assert Transaction.query.filter_by(order_id=order.id).count() == 2
