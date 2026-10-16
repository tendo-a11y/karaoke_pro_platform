"""
Вход без Google (2026-10): гость выбирает только стол. Пока за столом есть
заказы песен, стол закрыт для остальных (и без входа, и через Google).
Избранного и VIP у такого гостя нет.
"""
from models import GuestAccount


def _headers(token):
    return {"Authorization": f"Bearer {token}"}


def _session(client, club_id):
    return client.post("/api/guest/session", json={"club_id": club_id}).get_json()["data"]


def _choose_no_login(client, token, table_no):
    return client.post(
        "/api/guest/profile/table-no-login", json={"table_no": table_no}, headers=_headers(token),
    )


def test_no_login_guest_chooses_table_and_orders(client, db, club):
    session = _session(client, club.club_id)
    resp = _choose_no_login(client, session["token"], 7)
    assert resp.status_code == 200
    data = resp.get_json()["data"]
    assert data["table_no"] == 7
    assert data["account"] is None
    assert data["table_group_status"] == "admin"
    assert GuestAccount.query.filter_by(club_id=club.club_id).count() == 0

    order = client.post(
        "/api/guest/order", json={"song_title": "Believer"}, headers=_headers(data["token"]),
    )
    assert order.status_code == 201


def test_second_guest_locked_out_while_no_login_table_has_orders(client, db, club):
    first = _session(client, club.club_id)
    first_data = _choose_no_login(client, first["token"], 7).get_json()["data"]
    client.post("/api/guest/order", json={"song_title": "Believer"}, headers=_headers(first_data["token"]))

    second = _session(client, club.club_id)
    no_login = _choose_no_login(client, second["token"], 7)
    assert no_login.status_code == 409
    assert no_login.get_json()["error"] == "TABLE_LOCKED_BY_ORDERS"
    assert "заказы песен" in no_login.get_json()["message"]

    google = client.post(
        "/api/guest/profile/link-google",
        json={"table_no": 7, "google_credential": {"sub": "mock-sub-locked", "email": "x@example.com"}},
        headers=_headers(second["token"]),
    )
    assert google.status_code == 409
    assert google.get_json()["error"] == "TABLE_LOCKED_BY_ORDERS"


def test_second_guest_can_join_no_login_table_without_orders(client, db, club):
    first = _session(client, club.club_id)
    _choose_no_login(client, first["token"], 9)

    second = _session(client, club.club_id)
    resp = _choose_no_login(client, second["token"], 9)
    assert resp.status_code == 200
    assert resp.get_json()["data"]["table_group_status"] == "pending"


def test_no_login_guest_cannot_use_favorites(client, db, club):
    session = _session(client, club.club_id)
    data = _choose_no_login(client, session["token"], 3).get_json()["data"]
    resp = client.post(
        "/api/guest/favorites", json={"song_title": "My favorite"}, headers=_headers(data["token"]),
    )
    assert resp.status_code == 409
    assert resp.get_json()["error"] == "GOOGLE_LINK_REQUIRED"


def test_table_choice_is_one_time(client, db, club):
    session = _session(client, club.club_id)
    data = _choose_no_login(client, session["token"], 4).get_json()["data"]
    again = _choose_no_login(client, data["token"], 5)
    assert again.status_code == 409
    assert again.get_json()["error"] == "TABLE_ALREADY_SET"
