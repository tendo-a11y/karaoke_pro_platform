"""
Тесты живого статуса гостя (models.py::GuestStatus, services/
guest_status_service.py) — блокировка и снятие со стола из карточки гостя
в KJ Panel (запрос пользователя 2026-09), и то, что это ДЕЙСТВИТЕЛЬНО
перекрывает уже выданный гостю JWT (auth.py::require_guest), а не только
влияет на новые токены.
"""
import uuid

from models import GuestStatus


def _headers(token):
    return {"Authorization": f"Bearer {token}"}


def _kj_headers(kj):
    return {"Authorization": f"Bearer {kj['token']}"}


def _link_google(client, club_id, table_no=5, sub=None):
    session = client.post("/api/guest/session", json={"club_id": club_id}).get_json()["data"]
    sub = sub or f"mock-sub-{uuid.uuid4().hex[:12]}"
    linked = client.post(
        "/api/guest/profile/link-google",
        json={"table_no": table_no, "google_credential": {"sub": sub}},
        headers=_headers(session["token"]),
    ).get_json()["data"]
    return linked["token"], int(linked["guest_id"]), sub


def test_link_google_records_live_table_status(client, db, club):
    """Выбор стола через link-google сразу же появляется как живая строка
    в БД (не только в токене) — иначе KJ Panel не увидит текущий стол
    гостя, который ещё ничего не заказывал."""
    _, guest_id, _ = _link_google(client, club.club_id, table_no=7)
    status = GuestStatus.query.filter_by(club_id=club.club_id, telegram_user_id=guest_id).first()
    assert status is not None
    assert status.table_no == 7
    assert status.is_blocked is False


def test_block_denies_further_guest_requests(client, db, club, kj):
    token, guest_id, _ = _link_google(client, club.club_id, table_no=3)

    block_resp = client.post(f"/api/kj/guests/{guest_id}/block", headers=_kj_headers(kj))
    assert block_resp.status_code == 200
    assert block_resp.get_json()["data"]["is_blocked"] is True

    me_resp = client.get("/api/guest/me", headers=_headers(token))
    assert me_resp.status_code == 403
    assert me_resp.get_json()["error"] == "GUEST_BLOCKED"

    order_resp = client.post(
        "/api/guest/order", json={"song_title": "Песня"}, headers=_headers(token),
    )
    assert order_resp.status_code == 403
    assert order_resp.get_json()["error"] == "GUEST_BLOCKED"


def test_unblock_restores_access(client, db, club, kj):
    token, guest_id, _ = _link_google(client, club.club_id, table_no=3)
    client.post(f"/api/kj/guests/{guest_id}/block", headers=_kj_headers(kj))
    assert client.get("/api/guest/me", headers=_headers(token)).status_code == 403

    unblock_resp = client.post(f"/api/kj/guests/{guest_id}/unblock", headers=_kj_headers(kj))
    assert unblock_resp.status_code == 200
    assert unblock_resp.get_json()["data"]["is_blocked"] is False

    me_resp = client.get("/api/guest/me", headers=_headers(token))
    assert me_resp.status_code == 200


def test_remove_from_table_takes_effect_immediately_with_old_token(client, db, club, kj):
    """Ключевая проверка: КЖ снимает гостя со стола, а у гостя на руках
    старый токен, где ЕЩЁ записан старый стол — auth.py::require_guest
    должен подменить table_no живьём из БД, а не поверить токену."""
    token, guest_id, _ = _link_google(client, club.club_id, table_no=9)

    me_before = client.get("/api/guest/me", headers=_headers(token)).get_json()["data"]
    assert me_before["table_no"] == 9

    remove_resp = client.post(f"/api/kj/guests/{guest_id}/remove-table", headers=_kj_headers(kj))
    assert remove_resp.status_code == 200
    assert remove_resp.get_json()["data"]["table_no"] is None

    # Тот же самый (старый) токен — не перевыпускался.
    me_after = client.get("/api/guest/me", headers=_headers(token)).get_json()["data"]
    assert me_after["table_no"] is None

    order_resp = client.post(
        "/api/guest/order", json={"song_title": "Песня"}, headers=_headers(token),
    )
    assert order_resp.status_code == 409
    assert order_resp.get_json()["error"] == "TABLE_REQUIRED"


def test_guest_can_reselect_table_after_removal(client, db, club, kj):
    """Снятие со стола — не бан, гость может снова выбрать стол."""
    token, guest_id, sub = _link_google(client, club.club_id, table_no=9)
    client.post(f"/api/kj/guests/{guest_id}/remove-table", headers=_kj_headers(kj))

    relinked = client.post(
        "/api/guest/profile/link-google",
        json={"table_no": 4, "google_credential": {"sub": sub}},
        headers=_headers(token),
    )
    assert relinked.status_code == 200
    assert relinked.get_json()["data"]["table_no"] == 4

    status = GuestStatus.query.filter_by(club_id=club.club_id, telegram_user_id=guest_id).first()
    assert status.table_no == 4


def test_guest_without_status_row_unaffected(client, db, club):
    """Гость, над которым KJ никогда ничего не делал — обычное поведение,
    как до появления GuestStatus (доверяем токену)."""
    session = client.post("/api/guest/session", json={"club_id": club.club_id}).get_json()["data"]
    resp = client.get("/api/guest/me", headers=_headers(session["token"]))
    assert resp.status_code == 200
    assert resp.get_json()["data"]["table_no"] is None


def test_kj_cannot_block_guest_of_other_club(client, db, club, other_club, other_kj):
    """club_id всегда берётся из токена KJ (g.club_id), а не из URL — блок
    пишется под club_id вызывающего KJ, поэтому не может задеть гостя
    чужого клуба даже случайно теми же числовым guest_id."""
    _, guest_id, _ = _link_google(client, club.club_id, table_no=1)

    client.post(f"/api/kj/guests/{guest_id}/block", headers=_kj_headers(other_kj))

    status_own_club = GuestStatus.query.filter_by(club_id=club.club_id, telegram_user_id=guest_id).first()
    assert status_own_club is not None and status_own_club.is_blocked is False

    status_other_club = GuestStatus.query.filter_by(club_id=other_club.club_id, telegram_user_id=guest_id).first()
    assert status_other_club is not None and status_other_club.is_blocked is True


def test_block_requires_kj_auth(client, db, club):
    resp = client.post("/api/kj/guests/12345/block")
    assert resp.status_code == 401
