"""
Тесты Admin App, шаг 1 (Phase 3) — аутентификация и /api/admin/me, по
образцу test_kj_me_returns_own_club / test_inactive_kj_is_forbidden /
test_missing_token_is_unauthorized из test_orders.py.
"""
from auth import issue_admin_token
from extensions import db as _db
from models import AdminUser


def _make_admin(db, club, telegram_user_id=999, is_super_admin=False, is_active=True,
                 display_name="Owner"):
    admin = AdminUser(
        telegram_user_id=telegram_user_id,
        club_id=club.club_id,
        display_name=display_name,
        is_super_admin=is_super_admin,
        is_active=is_active,
    )
    db.session.add(admin)
    db.session.commit()
    return admin


def _headers_for(app, telegram_user_id):
    token = issue_admin_token(telegram_user_id, app.config["ADMIN_JWT_SECRET"], 3600)
    return {"Authorization": f"Bearer {token}"}


def test_missing_token_is_unauthorized(client, club):
    resp = client.get("/api/admin/me")
    assert resp.status_code == 401
    assert resp.get_json()["error"] == "UNAUTHORIZED"


def test_admin_me_returns_own_club(client, app, db, club):
    _make_admin(db, club, telegram_user_id=111)
    resp = client.get("/api/admin/me", headers=_headers_for(app, 111))
    assert resp.status_code == 200
    data = resp.get_json()["data"]
    assert data["club_id"] == club.club_id
    assert data["club_name"] == club.name
    assert data["is_super_admin"] is False


def test_unregistered_admin_is_forbidden(client, app, db, club):
    resp = client.get("/api/admin/me", headers=_headers_for(app, 424242))
    assert resp.status_code == 403
    assert resp.get_json()["error"] == "FORBIDDEN"


def test_inactive_admin_is_forbidden(client, app, db, club):
    _make_admin(db, club, telegram_user_id=222, is_active=False)
    resp = client.get("/api/admin/me", headers=_headers_for(app, 222))
    assert resp.status_code == 403


def test_admin_of_inactive_club_is_forbidden(client, app, db, club):
    _make_admin(db, club, telegram_user_id=333)
    club.is_active = False
    db.session.commit()
    resp = client.get("/api/admin/me", headers=_headers_for(app, 333))
    assert resp.status_code == 403


def test_super_admin_not_blocked_by_inactive_club(client, app, db, club):
    _make_admin(db, club, telegram_user_id=444, is_super_admin=True)
    club.is_active = False
    db.session.commit()
    resp = client.get("/api/admin/me", headers=_headers_for(app, 444))
    assert resp.status_code == 200
    assert resp.get_json()["data"]["is_super_admin"] is True


def test_kj_token_cannot_access_admin_endpoint(client, app, db, club, kj):
    # ТЗ п.24: токены ролей не взаимозаменяемы — KJ-токен подписан другим
    # секретом (ADMIN_JWT_SECRET != KJ_JWT_SECRET), поэтому даже structурно
    # верный JWT от одной роли не пройдёт проверку подписи для другой.
    resp = client.get("/api/admin/me", headers=kj["headers"])
    assert resp.status_code == 401
