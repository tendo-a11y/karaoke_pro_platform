"""
Массовое удаление своих не спетых заказов гостем (2026-10, без KJ).
Первые две песни очереди стола не удаляются.
"""
from models import STATUS_REJECTED, Order
from services.table_board_service import table_queue_orders


def _headers(token):
    return {"Authorization": f"Bearer {token}"}


def _seated_guest(client, club_id, table_no):
    session = client.post("/api/guest/session", json={"club_id": club_id}).get_json()["data"]
    data = client.post(
        "/api/guest/profile/table-no-login", json={"table_no": table_no}, headers=_headers(session["token"]),
    ).get_json()["data"]
    return data["token"]


def _order(client, token, title):
    resp = client.post("/api/guest/order", json={"song_title": title}, headers=_headers(token))
    assert resp.status_code == 201
    return resp.get_json()["data"]["id"]


def test_guest_removes_unplayed_except_first_two_in_table_queue(client, db, club):
    token = _seated_guest(client, club.club_id, 11)
    a, b, c, d = (_order(client, token, t) for t in ("A", "B", "C", "D"))

    resp = client.post("/api/guest/orders/cancel-unplayed", headers=_headers(token))
    assert resp.status_code == 200
    data = resp.get_json()["data"]
    assert data["cancelled"] == 2
    assert sorted(data["order_ids"]) == sorted([c, d])

    assert [o.id for o in table_queue_orders(club.club_id, 11)] == [a, b]
    assert db.session.get(Order, c).status == STATUS_REJECTED
    assert db.session.get(Order, d).status == STATUS_REJECTED


def test_guest_cannot_remove_other_guests_orders(client, db, club):
    owner = _seated_guest(client, club.club_id, 12)
    other = _seated_guest(client, club.club_id, 13)
    _order(client, owner, "A")
    _order(client, owner, "B")
    x = _order(client, other, "X")

    resp = client.post("/api/guest/orders/cancel-unplayed", headers=_headers(owner))
    assert resp.get_json()["data"]["cancelled"] == 0
    assert db.session.get(Order, x).status != STATUS_REJECTED
