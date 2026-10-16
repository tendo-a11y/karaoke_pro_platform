"""
Приоритет песни за столом (2026-10): KJ ставит место 1 или 2, гость просит
приоритет и ждёт подтверждения KJ.
"""
import pytest

from services.table_board_service import table_queue_orders


@pytest.fixture()
def kj_headers(kj):
    return {"Authorization": f"Bearer {kj['token']}"}


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


def _kj_priority(client, kj_headers, order_id, flag):
    return client.put(f"/api/kj/order/{order_id}/priority", json={"priority": flag}, headers=kj_headers)


def test_kj_priority_takes_slot_one_then_two_then_full(client, db, club, kj_headers):
    token = _seated_guest(client, club.club_id, 6)
    a, b, c = (_order(client, token, t) for t in ("A", "B", "C"))

    assert _kj_priority(client, kj_headers, a, True).get_json()["data"]["priority_slot"] == 1
    assert _kj_priority(client, kj_headers, b, True).get_json()["data"]["priority_slot"] == 2
    full = _kj_priority(client, kj_headers, c, True)
    assert full.status_code == 409
    assert full.get_json()["error"] == "PRIORITY_SLOTS_FULL"


def test_priority_songs_come_first_in_table_queue(client, db, club, kj_headers):
    token = _seated_guest(client, club.club_id, 8)
    a, b, c = (_order(client, token, t) for t in ("A", "B", "C"))
    _kj_priority(client, kj_headers, c, True)   # место 1
    _kj_priority(client, kj_headers, b, True)   # место 2
    assert [o.id for o in table_queue_orders(club.club_id, 8)] == [c, b, a]

    _kj_priority(client, kj_headers, c, False)  # снять — место 1 свободно
    assert [o.id for o in table_queue_orders(club.club_id, 8)] == [b, a, c]


def test_guest_priority_request_needs_kj_confirmation(client, db, club, kj_headers):
    token = _seated_guest(client, club.club_id, 9)
    a, b, c = (_order(client, token, t) for t in ("A", "B", "C"))

    # A уже первая — просить нельзя
    first = client.post(f"/api/guest/order/{a}/priority-request", headers=_headers(token))
    assert first.status_code == 409
    assert first.get_json()["error"] == "PRIORITY_NOT_NEEDED"

    # C — третья, заявка уходит KJ
    req = client.post(f"/api/guest/order/{c}/priority-request", headers=_headers(token))
    assert req.status_code == 200
    assert req.get_json()["data"]["priority_requested"] is True
    assert req.get_json()["data"]["priority_slot"] is None
    again = client.post(f"/api/guest/order/{c}/priority-request", headers=_headers(token))
    assert again.get_json()["error"] == "REQUEST_ALREADY_PENDING"

    # KJ подтверждает — песня встаёт первой, заявка закрыта
    ok = _kj_priority(client, kj_headers, c, True).get_json()["data"]
    assert ok["priority_slot"] == 1
    assert ok["priority_requested"] is False
    assert [o.id for o in table_queue_orders(club.club_id, 9)][0] == c
