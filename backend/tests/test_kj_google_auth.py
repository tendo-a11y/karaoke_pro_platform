"""
Тесты входа в KJ Panel через клубный Google-аккаунт (запрос пользователя
2026-09: "доступ KJ Pro определяется Google-аккаунтом клуба" — основной
способ входа наряду с /kjpanel через бота, который остаётся запасным).

GOOGLE_AUTH_MODE=mock (см. config.py::TestingConfig) — credential это не
настоящий Google id_token, а {"sub": ..., "email": ...}, как и в тестах
guest-аккаунта (test_guest_identity.py).
"""
from models import KJOperator


def _google_login(client, sub, email=None):
    credential = {"sub": sub}
    if email is not None:
        credential["email"] = email
    return client.post("/api/kj/auth/google", json={"credential": credential})


# --- POST /api/admin/kj с google_email ---

def test_super_admin_creates_kj_with_only_google_email(client, super_admin, club):
    resp = client.post(
        "/api/admin/kj",
        json={"google_email": "Voice.Chisinau@gmail.com", "display_name": "Voice KJ", "club_id": club.club_id},
        headers=super_admin["headers"],
    )
    assert resp.status_code == 201
    data = resp.get_json()["data"]
    assert data["telegram_user_id"] is None
    assert data["google_email"] == "voice.chisinau@gmail.com"  # нормализовано в нижний регистр
    assert data["google_linked"] is False


def test_assign_requires_at_least_one_identifier(client, super_admin, club):
    resp = client.post(
        "/api/admin/kj", json={"display_name": "X", "club_id": club.club_id}, headers=super_admin["headers"],
    )
    assert resp.status_code == 400


def test_assign_can_add_google_email_to_existing_telegram_kj(client, super_admin, club, kj):
    resp = client.post(
        "/api/admin/kj",
        json={
            "telegram_user_id": kj["operator"].telegram_user_id,
            "google_email": "club@gmail.com",
            "display_name": "DJ One",
            "club_id": club.club_id,
        },
        headers=super_admin["headers"],
    )
    assert resp.status_code == 201
    data = resp.get_json()["data"]
    assert data["id"] == kj["operator"].id
    assert data["telegram_user_id"] == kj["operator"].telegram_user_id
    assert data["google_email"] == "club@gmail.com"
    assert KJOperator.query.filter_by(club_id=club.club_id).count() == 1


def test_assign_with_only_google_email_reassigns_existing_kj_like_telegram_does(
    client, super_admin, club, other_club,
):
    """Совпадение по google_email — это тот же upsert, что и по telegram_user_id
    (см. test_admin_kj.py::test_super_admin_can_reassign_existing_kj_to_another_club):
    находим ту же запись и переносим её, а не создаём дубликат/ошибку."""
    client.post(
        "/api/admin/kj",
        json={"google_email": "shared@gmail.com", "display_name": "A", "club_id": club.club_id},
        headers=super_admin["headers"],
    )
    resp = client.post(
        "/api/admin/kj",
        json={"google_email": "shared@gmail.com", "display_name": "B", "club_id": other_club.club_id},
        headers=super_admin["headers"],
    )
    assert resp.status_code == 201
    assert resp.get_json()["data"]["club_id"] == other_club.club_id
    assert KJOperator.query.filter_by(google_email="shared@gmail.com").count() == 1


def test_assign_rejects_google_email_already_used_by_a_different_kj(client, super_admin, club, other_club):
    """В отличие от совпадения по самому google_email (реассайн выше), здесь
    telegram_user_id указывает на УЖЕ СУЩЕСТВУЮЩУЮ ДРУГУЮ запись (без своей
    google_email), а запрошенная google_email уже занята третьей — находим
    kj по telegram_user_id раньше, чем по email, и это настоящий конфликт."""
    client.post(
        "/api/admin/kj",
        json={"google_email": "taken@gmail.com", "display_name": "A", "club_id": club.club_id},
        headers=super_admin["headers"],
    )
    client.post(
        "/api/admin/kj",
        json={"telegram_user_id": 999888, "display_name": "B", "club_id": other_club.club_id},
        headers=super_admin["headers"],
    )

    resp = client.post(
        "/api/admin/kj",
        json={
            "telegram_user_id": 999888,
            "google_email": "taken@gmail.com",
            "display_name": "B",
            "club_id": other_club.club_id,
        },
        headers=super_admin["headers"],
    )
    assert resp.status_code == 400


# --- POST /api/kj/auth/google ---

def test_google_login_succeeds_for_registered_email_and_binds_sub(client, super_admin, club):
    client.post(
        "/api/admin/kj",
        json={"google_email": "club@gmail.com", "display_name": "Club KJ", "club_id": club.club_id},
        headers=super_admin["headers"],
    )

    resp = _google_login(client, sub="google-sub-1", email="Club@Gmail.com")
    assert resp.status_code == 200
    token = resp.get_json()["data"]["token"]

    me = client.get("/api/kj/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.get_json()["data"]["club_id"] == club.club_id

    kj = KJOperator.query.filter_by(google_email="club@gmail.com").first()
    assert kj.google_sub == "google-sub-1"


def test_google_login_second_time_uses_bound_sub_not_email(client, super_admin, club):
    client.post(
        "/api/admin/kj",
        json={"google_email": "club@gmail.com", "display_name": "Club KJ", "club_id": club.club_id},
        headers=super_admin["headers"],
    )
    _google_login(client, sub="google-sub-1", email="club@gmail.com")

    # Второй вход — email можно даже не передавать, sub уже привязан.
    resp = _google_login(client, sub="google-sub-1")
    assert resp.status_code == 200


def test_google_login_rejects_unregistered_account(client):
    resp = _google_login(client, sub="stranger-sub", email="stranger@gmail.com")
    assert resp.status_code == 403
    assert resp.get_json()["error"] == "GOOGLE_NOT_REGISTERED"


def test_google_login_rejects_inactive_kj(client, super_admin, club):
    client.post(
        "/api/admin/kj",
        json={"google_email": "club@gmail.com", "display_name": "Club KJ", "club_id": club.club_id},
        headers=super_admin["headers"],
    )
    _google_login(client, sub="google-sub-1", email="club@gmail.com")
    kj = KJOperator.query.filter_by(google_email="club@gmail.com").first()
    client.put(
        f"/api/admin/kj/{kj.id}/status", json={"is_active": False}, headers=super_admin["headers"],
    )

    resp = _google_login(client, sub="google-sub-1")
    assert resp.status_code == 403
    assert resp.get_json()["error"] == "FORBIDDEN"


def test_google_login_rejects_missing_credential(client):
    resp = client.post("/api/kj/auth/google", json={})
    assert resp.status_code == 400


# --- PUT /api/admin/kj/<id> — редактирование google_email ---

def test_update_kj_can_set_google_email(client, super_admin, kj):
    resp = client.put(
        f"/api/admin/kj/{kj['operator'].id}", json={"google_email": "New@Gmail.com"}, headers=super_admin["headers"],
    )
    assert resp.status_code == 200
    assert resp.get_json()["data"]["google_email"] == "new@gmail.com"


def test_update_kj_clears_google_email_and_sub(client, super_admin, club):
    create = client.post(
        "/api/admin/kj",
        json={"google_email": "club@gmail.com", "display_name": "Club KJ", "club_id": club.club_id},
        headers=super_admin["headers"],
    )
    kj_id = create.get_json()["data"]["id"]
    _google_login(client, sub="google-sub-1", email="club@gmail.com")

    resp = client.put(
        f"/api/admin/kj/{kj_id}", json={"google_email": None}, headers=super_admin["headers"],
    )
    assert resp.status_code == 200
    assert resp.get_json()["data"]["google_email"] is None
    assert resp.get_json()["data"]["google_linked"] is False

    # Прежний Google-вход больше не работает — почта отвязана.
    login_resp = _google_login(client, sub="google-sub-1")
    assert login_resp.status_code == 403


def test_update_kj_rejects_duplicate_google_email(client, super_admin, club, other_club):
    client.post(
        "/api/admin/kj",
        json={"google_email": "taken@gmail.com", "display_name": "A", "club_id": club.club_id},
        headers=super_admin["headers"],
    )
    create_b = client.post(
        "/api/admin/kj",
        json={"telegram_user_id": 777, "display_name": "B", "club_id": other_club.club_id},
        headers=super_admin["headers"],
    )
    kj_b_id = create_b.get_json()["data"]["id"]

    resp = client.put(
        f"/api/admin/kj/{kj_b_id}", json={"google_email": "taken@gmail.com"}, headers=super_admin["headers"],
    )
    assert resp.status_code == 400
