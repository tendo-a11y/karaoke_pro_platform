"""
Тесты GET/PUT /api/kj/table-settings/<club_id> (доп. ТЗ "KJ Pro", KJ-04) —
у каждого клуба своё количество столов, роль 2 (KJ) сама может это менять.
В старом боте это тоже была настройка KJ, а не админа (handlers/kj.py:
tables_count_edit/tables_settings_save), здесь тот же смысл, отдельным
эндпоинтом на стороне KJ Panel (Club.table_count уже существует в модели и
уже используется Admin App — см. services/club_service.py). None означает
"не ограничено" — поведение по умолчанию, пока KJ явно не задал число.
"""
from models import Club


def _headers(token):
    return {"Authorization": f"Bearer {token}"}


def test_requires_auth(client, db, club):
    resp = client.get(f"/api/kj/table-settings/{club.club_id}")
    assert resp.status_code == 401


def test_get_default_is_unbounded(client, db, club, kj):
    resp = client.get(f"/api/kj/table-settings/{club.club_id}", headers=_headers(kj["token"]))
    assert resp.status_code == 200
    assert resp.get_json()["data"]["table_count"] is None


def test_scoped_to_own_club(client, db, club, other_club, kj, other_kj):
    resp = client.get(f"/api/kj/table-settings/{other_club.club_id}", headers=_headers(kj["token"]))
    assert resp.status_code == 403


def test_update_sets_table_count(client, db, club, kj):
    resp = client.put(
        f"/api/kj/table-settings/{club.club_id}", json={"table_count": 16}, headers=_headers(kj["token"]),
    )
    assert resp.status_code == 200
    assert resp.get_json()["data"]["table_count"] == 16

    stored = db.session.get(Club, club.club_id)
    assert stored.table_count == 16


def test_update_can_clear_back_to_unbounded(client, db, club, kj):
    client.put(f"/api/kj/table-settings/{club.club_id}", json={"table_count": 10}, headers=_headers(kj["token"]))

    resp = client.put(
        f"/api/kj/table-settings/{club.club_id}", json={"table_count": None}, headers=_headers(kj["token"]),
    )
    assert resp.status_code == 200
    assert resp.get_json()["data"]["table_count"] is None


def test_update_rejects_zero_or_negative(client, db, club, kj):
    resp = client.put(f"/api/kj/table-settings/{club.club_id}", json={"table_count": 0}, headers=_headers(kj["token"]))
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "VALIDATION_ERROR"

    resp2 = client.put(
        f"/api/kj/table-settings/{club.club_id}", json={"table_count": -1}, headers=_headers(kj["token"]),
    )
    assert resp2.status_code == 400


def test_update_rejects_non_integer(client, db, club, kj):
    resp = client.put(
        f"/api/kj/table-settings/{club.club_id}", json={"table_count": "16"}, headers=_headers(kj["token"]),
    )
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "VALIDATION_ERROR"


def test_update_scoped_to_own_club(client, db, club, other_club, kj, other_kj):
    resp = client.put(
        f"/api/kj/table-settings/{other_club.club_id}", json={"table_count": 5}, headers=_headers(kj["token"]),
    )
    assert resp.status_code == 403

    unaffected = db.session.get(Club, other_club.club_id)
    assert unaffected.table_count is None
