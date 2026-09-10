import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from app import create_app
from auth import issue_admin_token, issue_kj_token
from config import TestingConfig
from extensions import db as _db
from models import AdminUser, Club, KJOperator


@pytest.fixture()
def app():
    application = create_app(TestingConfig)
    with application.app_context():
        _db.drop_all()
        _db.create_all()

    # Синглтон mock-VirtualDJ общий на процесс — сбрасываем очередь между
    # тестами, чтобы они не зависели от порядка выполнения друг друга.
    import vdj as vdj_module
    vdj_module._mock_singleton._queue.clear()
    vdj_module._mock_singleton.force_failure(False)

    yield application
    with application.app_context():
        _db.session.remove()
        _db.drop_all()


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def db(app):
    with app.app_context():
        yield _db


@pytest.fixture()
def club(db):
    c = Club(club_id=1, name="Club One", is_active=True)
    db.session.add(c)
    db.session.commit()
    return c


@pytest.fixture()
def other_club(db):
    c = Club(club_id=2, name="Club Two", is_active=True)
    db.session.add(c)
    db.session.commit()
    return c


@pytest.fixture()
def kj(db, club, app):
    operator = KJOperator(telegram_user_id=111, club_id=club.club_id, display_name="DJ One", is_active=True)
    db.session.add(operator)
    db.session.commit()
    token = issue_kj_token(operator.telegram_user_id, app.config["KJ_JWT_SECRET"], 3600)
    return {"operator": operator, "token": token, "headers": {"Authorization": f"Bearer {token}"}}


@pytest.fixture()
def other_kj(db, other_club, app):
    operator = KJOperator(telegram_user_id=222, club_id=other_club.club_id, display_name="DJ Two", is_active=True)
    db.session.add(operator)
    db.session.commit()
    token = issue_kj_token(operator.telegram_user_id, app.config["KJ_JWT_SECRET"], 3600)
    return {"operator": operator, "token": token, "headers": {"Authorization": f"Bearer {token}"}}


@pytest.fixture()
def super_admin(db, club, app):
    """
    Супер-админ (аналог единственного config.ADMIN_ID старого бота) — не
    ограничен club_id, но по схеме AdminUser.club_id всё равно NOT NULL
    (см. models.py), поэтому у него тоже есть "домашний" клуб.
    """
    admin = AdminUser(
        telegram_user_id=901, club_id=club.club_id, display_name="Super Admin",
        is_super_admin=True, is_active=True,
    )
    db.session.add(admin)
    db.session.commit()
    token = issue_admin_token(admin.telegram_user_id, app.config["ADMIN_JWT_SECRET"], 3600)
    return {"admin": admin, "token": token, "headers": {"Authorization": f"Bearer {token}"}}


@pytest.fixture()
def admin(db, club, app):
    """Обычный админ, привязан только к своему клубу (club fixture, club_id=1)."""
    admin_user = AdminUser(
        telegram_user_id=902, club_id=club.club_id, display_name="Club Admin",
        is_super_admin=False, is_active=True,
    )
    db.session.add(admin_user)
    db.session.commit()
    token = issue_admin_token(admin_user.telegram_user_id, app.config["ADMIN_JWT_SECRET"], 3600)
    return {"admin": admin_user, "token": token, "headers": {"Authorization": f"Bearer {token}"}}


@pytest.fixture()
def other_admin(db, other_club, app):
    """Обычный админ другого клуба (other_club fixture, club_id=2) — для проверки изоляции."""
    admin_user = AdminUser(
        telegram_user_id=903, club_id=other_club.club_id, display_name="Other Club Admin",
        is_super_admin=False, is_active=True,
    )
    db.session.add(admin_user)
    db.session.commit()
    token = issue_admin_token(admin_user.telegram_user_id, app.config["ADMIN_JWT_SECRET"], 3600)
    return {"admin": admin_user, "token": token, "headers": {"Authorization": f"Bearer {token}"}}


@pytest.fixture()
def bot_headers(app):
    return {"X-Internal-Token": app.config["BOT_INTERNAL_TOKEN"]}


def create_order(client, bot_headers, club_id=1, table_no=5, telegram_user_id=123456789,
                  song_title="Билет на самолет", artist="Дима Билан"):
    resp = client.post(
        "/api/client/order",
        json={
            "telegram_user_id": telegram_user_id,
            "club_id": club_id,
            "table_no": table_no,
            "song_title": song_title,
            "artist": artist,
        },
        headers=bot_headers,
    )
    return resp
