"""
Тесты панели заказов по столам (доп. ТЗ "KJ Pro", запрос пользователя
2026-09-18) — GET /api/kj/orders-board/<club_id> и связанное с ним поле
waiting_position в GET /api/guest/orders.

См. подробный докстринг services/table_board_service.py про саму механику:
карточка на N мест (Club.songs_per_table), первые N заказов стола по
времени создания видны KJ на карточке, остальные — только самому гостю как
"ожидание" с номером места.
"""
from datetime import datetime, timedelta, timezone

from models import STATUS_PENDING, STATUS_QUEUED, STATUS_REJECTED, Order


def _headers(token):
    return {"Authorization": f"Bearer {token}"}


def _guest_session(client, club_id, table_no=None):
    resp = client.post("/api/guest/session", json={"club_id": club_id, "table_no": table_no})
    return resp.get_json()["data"]


_BASE_TIME = datetime(2026, 9, 18, 20, 0, 0, tzinfo=timezone.utc)


def _make_order(db, club_id, guest_id, table_no, offset_seconds=0, status=STATUS_PENDING,
                 song_title="Песня", artist="Артист", service_id=None):
    order = Order(
        telegram_user_id=guest_id, club_id=club_id, table_no=table_no,
        guest_type="client", song_title=song_title, artist=artist, service_id=service_id,
        source="guest", status=status,
        created_at=_BASE_TIME + timedelta(seconds=offset_seconds),
    )
    db.session.add(order)
    db.session.commit()
    return order


def test_requires_auth(client, db, club):
    resp = client.get(f"/api/kj/orders-board/{club.club_id}")
    assert resp.status_code == 401


def test_scoped_to_own_club(client, db, club, other_club, kj, other_kj):
    resp = client.get(f"/api/kj/orders-board/{other_club.club_id}", headers=_headers(kj["token"]))
    assert resp.status_code == 403


def test_empty_when_table_count_not_set(client, db, club, kj):
    resp = client.get(f"/api/kj/orders-board/{club.club_id}", headers=_headers(kj["token"]))
    assert resp.status_code == 200
    assert resp.get_json()["data"] == []


def test_board_shape_matches_table_count_and_capacity(client, db, club, kj):
    club.table_count = 3
    club.songs_per_table = 2
    db.session.commit()

    resp = client.get(f"/api/kj/orders-board/{club.club_id}", headers=_headers(kj["token"]))
    assert resp.status_code == 200
    board = resp.get_json()["data"]
    assert [t["table_no"] for t in board] == [1, 2, 3]
    for table in board:
        assert table["capacity"] == 2
        assert table["slots"] == [None, None]


def test_default_capacity_when_songs_per_table_not_set(client, db, club, kj):
    club.table_count = 1
    club.songs_per_table = None
    db.session.commit()

    resp = client.get(f"/api/kj/orders-board/{club.club_id}", headers=_headers(kj["token"]))
    board = resp.get_json()["data"]
    assert board[0]["capacity"] == 2


def test_orders_fill_slots_up_to_capacity_in_creation_order(client, db, club, kj):
    club.table_count = 1
    club.songs_per_table = 2
    db.session.commit()

    o1 = _make_order(db, club.club_id, 111, table_no=1, offset_seconds=0, song_title="Первая")
    o2 = _make_order(db, club.club_id, 222, table_no=1, offset_seconds=1, song_title="Вторая")

    resp = client.get(f"/api/kj/orders-board/{club.club_id}", headers=_headers(kj["token"]))
    slots = resp.get_json()["data"][0]["slots"]
    assert [s["order_id"] for s in slots] == [o1.id, o2.id]
    assert slots[0]["song_title"] == "Первая"
    assert slots[0]["status"] == "pending"
    assert slots[0]["guest_id"] == 111


def test_orders_beyond_capacity_are_invisible_on_board(client, db, club, kj):
    club.table_count = 1
    club.songs_per_table = 2
    db.session.commit()

    o1 = _make_order(db, club.club_id, 111, table_no=1, offset_seconds=0)
    o2 = _make_order(db, club.club_id, 222, table_no=1, offset_seconds=1)
    o3 = _make_order(db, club.club_id, 333, table_no=1, offset_seconds=2, song_title="Третья лишняя")

    resp = client.get(f"/api/kj/orders-board/{club.club_id}", headers=_headers(kj["token"]))
    slots = resp.get_json()["data"][0]["slots"]
    order_ids = [s["order_id"] for s in slots]
    assert order_ids == [o1.id, o2.id]
    assert o3.id not in order_ids


def test_rejecting_active_order_promotes_next_waiting_order(client, db, club, kj):
    club.table_count = 1
    club.songs_per_table = 2
    db.session.commit()

    o1 = _make_order(db, club.club_id, 111, table_no=1, offset_seconds=0)
    o2 = _make_order(db, club.club_id, 222, table_no=1, offset_seconds=1)
    o3 = _make_order(db, club.club_id, 333, table_no=1, offset_seconds=2, song_title="Ждёт своей очереди")

    resp = client.put(f"/api/kj/order/{o1.id}/reject", headers=_headers(kj["token"]))
    assert resp.status_code == 200

    resp = client.get(f"/api/kj/orders-board/{club.club_id}", headers=_headers(kj["token"]))
    slots = resp.get_json()["data"][0]["slots"]
    assert [s["order_id"] for s in slots] == [o2.id, o3.id]


def test_queued_order_shows_status_and_service_id(client, db, club, kj):
    club.table_count = 1
    club.songs_per_table = 1
    db.session.commit()

    order = _make_order(db, club.club_id, 111, table_no=1, service_id=None)
    resp = client.put(f"/api/kj/order/{order.id}/confirm", headers=_headers(kj["token"]))
    assert resp.status_code == 200
    assert resp.get_json()["data"]["status"] == "queued"

    resp = client.get(f"/api/kj/orders-board/{club.club_id}", headers=_headers(kj["token"]))
    slot = resp.get_json()["data"][0]["slots"][0]
    assert slot["order_id"] == order.id
    assert slot["status"] == "queued"


def test_guest_sees_waiting_position_for_orders_beyond_capacity(client, db, club, kj):
    club.table_count = 1
    club.songs_per_table = 2
    db.session.commit()

    session = _guest_session(client, club.club_id, table_no=1)
    guest_id = int(session["guest_id"])

    o1 = _make_order(db, club.club_id, guest_id, table_no=1, offset_seconds=0, song_title="Активная 1")
    o2 = _make_order(db, club.club_id, guest_id, table_no=1, offset_seconds=1, song_title="Активная 2")
    o3 = _make_order(db, club.club_id, guest_id, table_no=1, offset_seconds=2, song_title="В ожидании")

    resp = client.get("/api/guest/orders", headers=_headers(session["token"]))
    assert resp.status_code == 200
    by_id = {o["id"]: o for o in resp.get_json()["data"]}
    assert by_id[o1.id]["waiting_position"] is None
    assert by_id[o2.id]["waiting_position"] is None
    assert by_id[o3.id]["waiting_position"] == 1


def test_guest_without_table_has_no_waiting_position(client, db, club, kj):
    session = _guest_session(client, club.club_id, table_no=None)
    guest_id = int(session["guest_id"])
    order = _make_order(db, club.club_id, guest_id, table_no=None)

    resp = client.get("/api/guest/orders", headers=_headers(session["token"]))
    by_id = {o["id"]: o for o in resp.get_json()["data"]}
    assert by_id[order.id]["waiting_position"] is None
