"""
Тесты "самопереименования гостя" (запрос пользователя 2026-09): гость сам
задаёт/меняет своё отображаемое имя (models.py::GuestAccount.display_name,
routes/guest.py::set_display_name) — имя должно быть доступно только после
входа через Google (у гостя должен быть постоянный профиль) и должно быть
видно KJ в списке гостей и в карточке гостя (services/guest_directory_service.py).
"""
import uuid

from models import GuestAccount


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


def test_set_name_requires_auth(client, club):
    resp = client.put("/api/guest/profile/name", json={"display_name": "Аня"})
    assert resp.status_code == 401


def test_set_name_requires_google_link_first(client, db, club):
    """Без постоянного профиля привязать имя не к чему — GOOGLE_LINK_REQUIRED,
    тот же принцип, что и у request_vip/add_favorite для действий, требующих
    постоянной личности."""
    session = client.post("/api/guest/session", json={"club_id": club.club_id}).get_json()["data"]
    resp = client.put(
        "/api/guest/profile/name",
        json={"display_name": "Аня"},
        headers=_headers(session["token"]),
    )
    assert resp.status_code == 409
    assert resp.get_json()["error"] == "GOOGLE_LINK_REQUIRED"


def test_set_name_happy_path_visible_in_me(client, db, club):
    token, guest_id, _ = _link_google(client, club.club_id)

    resp = client.put(
        "/api/guest/profile/name",
        json={"display_name": "Анна"},
        headers=_headers(token),
    )
    assert resp.status_code == 200
    assert resp.get_json()["data"]["display_name"] == "Анна"

    me = client.get("/api/guest/me", headers=_headers(token)).get_json()["data"]
    assert me["display_name"] == "Анна"

    account = GuestAccount.query.filter_by(club_id=club.club_id, telegram_user_id=guest_id).first()
    assert account.display_name == "Анна"


def test_set_name_trims_whitespace(client, db, club):
    token, _, _ = _link_google(client, club.club_id)
    resp = client.put(
        "/api/guest/profile/name",
        json={"display_name": "   Марина   "},
        headers=_headers(token),
    )
    assert resp.status_code == 200
    assert resp.get_json()["data"]["display_name"] == "Марина"


def test_set_name_rejects_empty(client, db, club):
    token, _, _ = _link_google(client, club.club_id)
    resp = client.put(
        "/api/guest/profile/name",
        json={"display_name": "   "},
        headers=_headers(token),
    )
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "VALIDATION_ERROR"


def test_set_name_rejects_missing_field(client, db, club):
    token, _, _ = _link_google(client, club.club_id)
    resp = client.put("/api/guest/profile/name", json={}, headers=_headers(token))
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "VALIDATION_ERROR"


def test_set_name_rejects_too_long(client, db, club):
    token, _, _ = _link_google(client, club.club_id)
    resp = client.put(
        "/api/guest/profile/name",
        json={"display_name": "Ы" * 41},
        headers=_headers(token),
    )
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "VALIDATION_ERROR"


def test_set_name_can_be_changed_again(client, db, club):
    """Это переименование, а не одноразовая настройка — можно менять сколько
    угодно раз."""
    token, _, _ = _link_google(client, club.club_id)
    client.put("/api/guest/profile/name", json={"display_name": "Первое"}, headers=_headers(token))
    resp = client.put("/api/guest/profile/name", json={"display_name": "Второе"}, headers=_headers(token))
    assert resp.status_code == 200
    assert resp.get_json()["data"]["display_name"] == "Второе"


def test_name_visible_to_kj_in_guest_list_and_card(client, db, club, kj):
    token, guest_id, _ = _link_google(client, club.club_id, table_no=6)
    client.put("/api/guest/profile/name", json={"display_name": "Дмитрий"}, headers=_headers(token))

    guests = client.get(f"/api/kj/guests/{club.club_id}", headers=_kj_headers(kj)).get_json()["data"]
    by_id = {row["guest_id"]: row for row in guests}
    assert by_id[str(guest_id)]["display_name"] == "Дмитрий"

    detail = client.get(f"/api/kj/guests/{club.club_id}/{guest_id}", headers=_kj_headers(kj)).get_json()["data"]
    assert detail["display_name"] == "Дмитрий"


def test_name_null_when_never_set(client, db, club, kj):
    _, guest_id, _ = _link_google(client, club.club_id, table_no=6)

    detail = client.get(f"/api/kj/guests/{club.club_id}/{guest_id}", headers=_kj_headers(kj)).get_json()["data"]
    assert detail["display_name"] is None
