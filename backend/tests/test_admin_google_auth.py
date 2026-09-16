"""
Тесты входа в Admin App через Google-аккаунт (запрос пользователя 2026-09:
"нормальный вход через Google в админку" — основной способ входа наряду
со ссылкой manage.py admin-link, которая остаётся запасной). Точная копия
test_kj_google_auth.py для admin_users/routes/admin.py::admin_google_login.

GOOGLE_AUTH_MODE=mock (см. config.py::TestingConfig) — credential это не
настоящий Google id_token, а {"sub": ..., "email": ...}.

В отличие от KJ, привязать google_email к администратору из самого Admin
App пока нельзя (нет такого эндпоинта — см. manage.py::
cmd_set_admin_google_email) — поэтому в тестах google_email проставляется
напрямую через фикстуру db, как это в реальности делает CLI-команда.
"""
from models import AdminUser


def _google_login(client, sub, email=None):
    credential = {"sub": sub}
    if email is not None:
        credential["email"] = email
    return client.post("/api/admin/auth/google", json={"credential": credential})


def _set_google_email(db, admin, email):
    admin.google_email = email.lower()
    db.session.commit()


def test_google_login_succeeds_for_registered_email_and_binds_sub(client, db, super_admin):
    _set_google_email(db, super_admin["admin"], "owner@gmail.com")

    resp = _google_login(client, sub="google-sub-1", email="Owner@Gmail.com")
    assert resp.status_code == 200
    token = resp.get_json()["data"]["token"]

    me = client.get("/api/admin/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.get_json()["data"]["is_super_admin"] is True

    admin = AdminUser.query.filter_by(google_email="owner@gmail.com").first()
    assert admin.google_sub == "google-sub-1"


def test_google_login_second_time_uses_bound_sub_not_email(client, db, super_admin):
    _set_google_email(db, super_admin["admin"], "owner@gmail.com")
    _google_login(client, sub="google-sub-1", email="owner@gmail.com")

    # Второй вход — email можно даже не передавать, sub уже привязан.
    resp = _google_login(client, sub="google-sub-1")
    assert resp.status_code == 200


def test_google_login_rejects_unregistered_account(client):
    resp = _google_login(client, sub="stranger-sub", email="stranger@gmail.com")
    assert resp.status_code == 403
    assert resp.get_json()["error"] == "GOOGLE_NOT_REGISTERED"


def test_google_login_rejects_inactive_admin(client, db, super_admin):
    _set_google_email(db, super_admin["admin"], "owner@gmail.com")
    super_admin["admin"].is_active = False
    db.session.commit()

    resp = _google_login(client, sub="google-sub-1", email="owner@gmail.com")
    assert resp.status_code == 403
    assert resp.get_json()["error"] == "FORBIDDEN"


def test_google_login_rejects_missing_credential(client):
    resp = client.post("/api/admin/auth/google", json={})
    assert resp.status_code == 400


def test_google_login_still_lets_admin_link_token_work_afterwards(client, db, super_admin, app):
    """Ссылка admin-link (telegram-токен) и Google-токен — два равноценных
    способа входа для одной и той же записи, оба должны продолжать
    работать независимо друг от друга (обратная совместимость, как и у
    KJ — см. test_kj_google_auth.py)."""
    _set_google_email(db, super_admin["admin"], "owner@gmail.com")
    _google_login(client, sub="google-sub-1", email="owner@gmail.com")

    # Старый telegram-токен (super_admin["token"]) по-прежнему работает.
    me = client.get("/api/admin/me", headers=super_admin["headers"])
    assert me.status_code == 200
