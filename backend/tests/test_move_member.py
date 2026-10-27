"""
Перенос одного гостя за другой стол (запрос 2026-10-28): гость ошибся столом,
его неигранные песни переезжают вместе с ним на стол с уже существующим админом.
"""
import uuid

from extensions import db as _db
from models import GuestStatus, Order, TableGroup, TableGroupMember
from services import table_group_service


def _headers(token):
    return {"Authorization": f"Bearer {token}"}


def _session(client, club_id, table_no):
    resp = client.post("/api/guest/session", json={"club_id": club_id})
    session = resp.get_json()["data"]
    sub = f"mock-sub-{uuid.uuid4().hex[:12]}"
    linked = client.post(
        "/api/guest/profile/link-google",
        json={"table_no": table_no, "google_credential": {"sub": sub}},
        headers=_headers(session["token"]),
    )
    assert linked.status_code == 200
    return linked.get_json()["data"]


def test_move_member_with_queued_songs_joins_destination(client, db, club):
    club_id = club.club_id
    # Гость C первым садится за стол 2 и становится его админом (он же ошибся столом).
    guest_c = _session(client, club_id, table_no=2)
    c_id = int(guest_c["guest_id"])
    resp = client.post("/api/guest/order", json={"song_title": "Песня C"}, headers=_headers(guest_c["token"]))
    assert resp.status_code == 201

    # Админ стола 5 — отдельный гость.
    _session(client, club_id, table_no=5)
    assert TableGroup.query.filter_by(club_id=club_id, table_no=5).first() is not None

    moved_orders_before = Order.query.filter_by(club_id=club_id, table_no=2, telegram_user_id=c_id).count()
    assert moved_orders_before == 1

    result = table_group_service.move_member(club_id, 2, 5, c_id, max_group_size=4)
    assert result.outcome == "ok"
    assert len(result.moved_order_ids) == 1

    assert TableGroupMember.query.filter_by(club_id=club_id, table_no=5, guest_id=c_id).first() is not None
    assert TableGroupMember.query.filter_by(club_id=club_id, table_no=2, guest_id=c_id).first() is None
    assert TableGroup.query.filter_by(club_id=club_id, table_no=2).first() is None
    assert Order.query.filter_by(club_id=club_id, table_no=5, telegram_user_id=c_id).count() == 1
    status = GuestStatus.query.filter_by(club_id=club_id, telegram_user_id=c_id).first()
    assert status is not None and status.table_no == 5


def test_move_member_refuses_missing_destination(client, db, club):
    club_id = club.club_id
    guest = _session(client, club_id, table_no=2)
    result = table_group_service.move_member(club_id, 2, 9, int(guest["guest_id"]), max_group_size=4)
    assert result.outcome == "destination_not_found"
    assert TableGroupMember.query.filter_by(club_id=club_id, table_no=2, guest_id=int(guest["guest_id"])).first() is not None
