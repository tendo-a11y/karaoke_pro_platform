"""
Тесты блока "Управление администраторами" Admin App (запрос пользователя
2026-09, сразу после "нормальный вход через Google в админку" — до этого
единственный способ вписать google_email администратору был manage.py по
SSH). Точная копия по структуре test_admin_kj.py, адаптированная под
admin_users — см. admin_admin_service.py docstring про то, почему здесь
доступ только super_admin (в отличие от KJ) и про защиты от блокировки
последнего супер-админа.
"""


# --- GET /api/admin/admins ---

def test_super_admin_lists_all_admins(client, super_admin, admin):
    resp = client.get("/api/admin/admins", headers=super_admin["headers"])
    assert resp.status_code == 200
    ids = {row["id"] for row in resp.get_json()["data"]}
    assert ids == {super_admin["admin"].id, admin["admin"].id}


def test_regular_admin_cannot_list_admins(client, admin):
    resp = client.get("/api/admin/admins", headers=admin["headers"])
    assert resp.status_code == 403


def test_list_admins_requires_auth(client):
    resp = client.get("/api/admin/admins")
    assert resp.status_code == 401


# --- POST /api/admin/admins (assign / upsert) ---

def test_super_admin_creates_new_admin(client, super_admin, club):
    resp = client.post(
        "/api/admin/admins",
        json={"telegram_user_id": 555100, "display_name": "New Admin", "club_id": club.club_id},
        headers=super_admin["headers"],
    )
    assert resp.status_code == 201
    data = resp.get_json()["data"]
    assert data["telegram_user_id"] == 555100
    assert data["club_id"] == club.club_id
    assert data["is_active"] is True
    assert data["is_super_admin"] is False


def test_super_admin_creates_admin_with_only_google_email(client, super_admin, club):
    resp = client.post(
        "/api/admin/admins",
        json={"google_email": "Owner2@Gmail.com", "display_name": "Owner Two", "club_id": club.club_id},
        headers=super_admin["headers"],
    )
    assert resp.status_code == 201
    data = resp.get_json()["data"]
    assert data["telegram_user_id"] is None
    assert data["google_email"] == "owner2@gmail.com"
    assert data["google_linked"] is False


def test_assign_can_create_another_super_admin(client, super_admin, club):
    resp = client.post(
        "/api/admin/admins",
        json={
            "telegram_user_id": 555101, "display_name": "Co-Owner", "club_id": club.club_id,
            "is_super_admin": True,
        },
        headers=super_admin["headers"],
    )
    assert resp.status_code == 201
    assert resp.get_json()["data"]["is_super_admin"] is True


def test_regular_admin_cannot_create_admins(client, admin, club):
    resp = client.post(
        "/api/admin/admins",
        json={"telegram_user_id": 555102, "display_name": "X", "club_id": club.club_id},
        headers=admin["headers"],
    )
    assert resp.status_code == 403


def test_assign_requires_at_least_one_identifier(client, super_admin, club):
    resp = client.post(
        "/api/admin/admins", json={"display_name": "X", "club_id": club.club_id}, headers=super_admin["headers"],
    )
    assert resp.status_code == 400


def test_assign_requires_display_name(client, super_admin, club):
    resp = client.post(
        "/api/admin/admins", json={"telegram_user_id": 1, "club_id": club.club_id}, headers=super_admin["headers"],
    )
    assert resp.status_code == 400


def test_assign_requires_club_id(client, super_admin):
    resp = client.post(
        "/api/admin/admins", json={"telegram_user_id": 1, "display_name": "X"}, headers=super_admin["headers"],
    )
    assert resp.status_code == 400


def test_assign_reactivates_deactivated_admin(client, db, super_admin, club, admin):
    admin["admin"].is_active = False
    db.session.commit()

    resp = client.post(
        "/api/admin/admins",
        json={"telegram_user_id": admin["admin"].telegram_user_id, "display_name": "Back", "club_id": club.club_id},
        headers=super_admin["headers"],
    )
    assert resp.status_code == 201
    assert resp.get_json()["data"]["is_active"] is True


def test_assign_with_only_google_email_reassigns_existing_admin_like_telegram_does(
    client, super_admin, club, other_club,
):
    """Совпадение по google_email — это тот же upsert, что и по
    telegram_user_id (см. kj_admin_service-эквивалентный тест) — находим ту
    же запись и дополняем/переносим её, а не создаём дубликат/ошибку."""
    client.post(
        "/api/admin/admins",
        json={"google_email": "shared@gmail.com", "display_name": "A", "club_id": club.club_id},
        headers=super_admin["headers"],
    )
    resp = client.post(
        "/api/admin/admins",
        json={
            "telegram_user_id": 999777, "google_email": "shared@gmail.com", "display_name": "B",
            "club_id": other_club.club_id,
        },
        headers=super_admin["headers"],
    )
    assert resp.status_code == 201
    assert resp.get_json()["data"]["club_id"] == other_club.club_id
    assert resp.get_json()["data"]["telegram_user_id"] == 999777
    from models import AdminUser
    assert AdminUser.query.filter_by(google_email="shared@gmail.com").count() == 1


def test_assign_rejects_google_email_already_used_by_a_different_admin(client, super_admin, club, other_club):
    """В отличие от совпадения по самому google_email (реассайн выше), здесь
    telegram_user_id указывает на УЖЕ СУЩЕСТВУЮЩУЮ ДРУГУЮ запись (без своей
    google_email), а запрошенная google_email уже занята третьей — находим
    админа по telegram_user_id раньше, чем по email, и это настоящий конфликт."""
    client.post(
        "/api/admin/admins",
        json={"google_email": "taken@gmail.com", "display_name": "A", "club_id": club.club_id},
        headers=super_admin["headers"],
    )
    client.post(
        "/api/admin/admins",
        json={"telegram_user_id": 999888, "display_name": "B", "club_id": other_club.club_id},
        headers=super_admin["headers"],
    )

    resp = client.post(
        "/api/admin/admins",
        json={
            "telegram_user_id": 999888,
            "google_email": "taken@gmail.com",
            "display_name": "B",
            "club_id": other_club.club_id,
        },
        headers=super_admin["headers"],
    )
    assert resp.status_code == 400


def test_assign_demoting_last_super_admin_is_rejected(client, super_admin, club):
    """super_admin — единственный супер-админ (фикстура его создаёт одного) —
    upsert по его же telegram_user_id с is_super_admin=False должен быть
    отклонён, иначе в системе не останется ни одного супер-админа."""
    resp = client.post(
        "/api/admin/admins",
        json={
            "telegram_user_id": super_admin["admin"].telegram_user_id,
            "display_name": "Demoted", "club_id": club.club_id, "is_super_admin": False,
        },
        headers=super_admin["headers"],
    )
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "LAST_SUPER_ADMIN"


# --- PUT /api/admin/admins/<id> ---

def test_super_admin_edits_display_name(client, super_admin, admin):
    resp = client.put(
        f"/api/admin/admins/{admin['admin'].id}", json={"display_name": "Renamed"}, headers=super_admin["headers"],
    )
    assert resp.status_code == 200
    assert resp.get_json()["data"]["display_name"] == "Renamed"


def test_super_admin_can_grant_super_admin(client, super_admin, admin):
    resp = client.put(
        f"/api/admin/admins/{admin['admin'].id}", json={"is_super_admin": True}, headers=super_admin["headers"],
    )
    assert resp.status_code == 200
    assert resp.get_json()["data"]["is_super_admin"] is True


def test_cannot_demote_the_last_super_admin(client, super_admin):
    resp = client.put(
        f"/api/admin/admins/{super_admin['admin'].id}",
        json={"is_super_admin": False},
        headers=super_admin["headers"],
    )
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "LAST_SUPER_ADMIN"


def test_can_demote_super_admin_when_another_one_remains(client, db, super_admin, admin):
    admin["admin"].is_super_admin = True
    db.session.commit()

    resp = client.put(
        f"/api/admin/admins/{admin['admin'].id}", json={"is_super_admin": False}, headers=super_admin["headers"],
    )
    assert resp.status_code == 200
    assert resp.get_json()["data"]["is_super_admin"] is False


def test_update_admin_can_set_and_clear_google_email(client, super_admin, admin):
    resp = client.put(
        f"/api/admin/admins/{admin['admin'].id}", json={"google_email": "New@Gmail.com"}, headers=super_admin["headers"],
    )
    assert resp.status_code == 200
    assert resp.get_json()["data"]["google_email"] == "new@gmail.com"

    resp2 = client.put(
        f"/api/admin/admins/{admin['admin'].id}", json={"google_email": None}, headers=super_admin["headers"],
    )
    assert resp2.status_code == 200
    assert resp2.get_json()["data"]["google_email"] is None
    assert resp2.get_json()["data"]["google_linked"] is False


def test_regular_admin_cannot_update_admins(client, admin):
    resp = client.put(
        f"/api/admin/admins/{admin['admin'].id}", json={"display_name": "X"}, headers=admin["headers"],
    )
    assert resp.status_code == 403


def test_update_admin_404(client, super_admin):
    resp = client.put("/api/admin/admins/999999", json={"display_name": "X"}, headers=super_admin["headers"])
    assert resp.status_code == 404


# --- PUT /api/admin/admins/<id>/status ---

def test_super_admin_deactivates_another_admin(client, super_admin, admin):
    resp = client.put(
        f"/api/admin/admins/{admin['admin'].id}/status", json={"is_active": False}, headers=super_admin["headers"],
    )
    assert resp.status_code == 200
    assert resp.get_json()["data"]["is_active"] is False


def test_cannot_deactivate_self(client, super_admin):
    resp = client.put(
        f"/api/admin/admins/{super_admin['admin'].id}/status",
        json={"is_active": False},
        headers=super_admin["headers"],
    )
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "FORBIDDEN"


def test_can_deactivate_a_super_admin_when_another_active_one_remains(client, db, super_admin, admin):
    """Раз этот эндпоинт вообще доступен только супер-админу (см.
    _require_super_admin), деактивирующий сам всегда активный супер-админ —
    значит "последним" супер-админ может остаться только при попытке
    деактивировать САМОГО СЕБЯ (см. test_cannot_deactivate_self). Здесь же
    супер-админов двое — деактивация другого должна пройти нормально."""
    admin["admin"].is_super_admin = True
    db.session.commit()

    resp = client.put(
        f"/api/admin/admins/{super_admin['admin'].id}/status",
        json={"is_active": False},
        headers=admin["headers"],
    )
    assert resp.status_code == 200
    assert resp.get_json()["data"]["is_active"] is False


def test_regular_admin_cannot_toggle_status(client, admin):
    resp = client.put(
        f"/api/admin/admins/{admin['admin'].id}/status", json={"is_active": False}, headers=admin["headers"],
    )
    assert resp.status_code == 403


def test_toggle_status_rejects_non_boolean(client, super_admin, admin):
    resp = client.put(
        f"/api/admin/admins/{admin['admin'].id}/status", json={"is_active": "yes"}, headers=super_admin["headers"],
    )
    assert resp.status_code == 400


def test_deactivated_admin_loses_admin_app_access(client, db, admin):
    """Живая проверка, что is_active реально работает — require_admin
    должен отказать после деактивации (по образцу
    test_admin_kj.py::test_deactivated_kj_loses_kj_panel_access)."""
    resp = client.get("/api/admin/me", headers=admin["headers"])
    assert resp.status_code == 200

    admin["admin"].is_active = False
    db.session.commit()

    resp2 = client.get("/api/admin/me", headers=admin["headers"])
    assert resp2.status_code == 403
