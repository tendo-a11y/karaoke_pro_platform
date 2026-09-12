"""
Тесты постоянной идентификации гостя через Google (ТЗ п.45,
POST /api/guest/profile/link-google) — заменяет удалённый механизм
access_code/redeem (см. test_vip.py, test_kj_vip_clients.py,
test_table_group.py про перенос членства группового стола).

Финальная единая модель входа (по итогам обсуждения — заменяет прежнее
деление на "способ 1"/"способ 2", полностью убранное): QR-код никогда не
содержит номер стола, сессия всегда создаётся без стола. Пока стола нет,
гость (Role 5) может смотреть очередь и выбрать песню в форму, но не
может заказать. Стол выбирается и Google подтверждается ОДНИМ действием
— единственным вызовом этого эндпоинта; после него гость становится
Role 4 (или 3, если уже был одобрен как VIP).

GOOGLE_AUTH_MODE=mock (см. config.py::TestingConfig, services/
google_auth_service.py) — credential здесь простой {"sub", "email"}, а не
настоящий Google id_token.
"""
from models import GuestAccount


def _headers(token):
    return {"Authorization": f"Bearer {token}"}


def _session(client, club_id):
    resp = client.post("/api/guest/session", json={"club_id": club_id})
    return resp.get_json()["data"]


def test_link_google_reuses_current_guest_id_no_data_lost(client, db, club):
    """Гость добавляет избранное анонимно (до стола и до Google — это
    можно), пробует заказать без стола (блок TABLE_REQUIRED), затем одним
    действием выбирает стол и входит через Google — постоянный номер
    остаётся ТЕМ ЖЕ самым, и избранное остаётся доступным без единой
    миграции строк (см. отчёт по п.45), после чего заказ уже проходит."""
    session = _session(client, club.club_id)
    token = session["token"]

    fav_resp = client.post(
        "/api/guest/favorites", json={"song_title": "My favorite"}, headers=_headers(token),
    )
    assert fav_resp.status_code == 201

    blocked = client.post(
        "/api/guest/order", json={"song_title": "Song 0"}, headers=_headers(token),
    )
    assert blocked.status_code == 409
    assert blocked.get_json()["error"] == "TABLE_REQUIRED"

    resp = client.post(
        "/api/guest/profile/link-google",
        json={"table_no": 5, "google_credential": {"sub": "mock-sub-reuse", "email": "guest@example.com"}},
        headers=_headers(token),
    )
    assert resp.status_code == 200
    data = resp.get_json()["data"]
    assert data["guest_id"] == session["guest_id"]  # тот же номер — ничего не создавалось заново
    assert data["table_no"] == 5
    new_token = data["token"]

    order_resp = client.post(
        "/api/guest/order", json={"song_title": "Song 1"}, headers=_headers(new_token),
    )
    assert order_resp.status_code == 201

    favorites = client.get("/api/guest/favorites", headers=_headers(new_token)).get_json()["data"]
    assert len(favorites) == 1
    assert favorites[0]["song_title"] == "My favorite"

    account = GuestAccount.query.filter_by(club_id=club.club_id, google_sub="mock-sub-reuse").first()
    assert account is not None
    assert account.telegram_user_id == int(session["guest_id"])


def test_order_blocked_until_table_and_google_done(client, db, club):
    """До единственного действия "стол + Google" доступны только просмотр
    очереди и выбор песни в форму — заказ заблокирован сразу на первом
    недостающем условии (стол)."""
    session = _session(client, club.club_id)

    # Очередь смотреть можно сразу.
    resp = client.get("/api/guest/queue", headers=_headers(session["token"]))
    assert resp.status_code == 200

    resp = client.post(
        "/api/guest/order", json={"song_title": "Believer"}, headers=_headers(session["token"]),
    )
    assert resp.status_code == 409
    assert resp.get_json()["error"] == "TABLE_REQUIRED"

    me = client.get("/api/guest/me", headers=_headers(session["token"])).get_json()["data"]
    assert me["has_permanent_profile"] is False


def test_link_google_without_table_no_rejected(client, db, club):
    session = _session(client, club.club_id)
    resp = client.post(
        "/api/guest/profile/link-google",
        json={"google_credential": {"sub": "mock-sub-missing-table"}},
        headers=_headers(session["token"]),
    )
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "VALIDATION_ERROR"


def test_choose_table_and_link_unlocks_order(client, db, club):
    session = _session(client, club.club_id)
    resp = client.post(
        "/api/guest/profile/link-google",
        json={"table_no": 9, "google_credential": {"sub": "mock-sub-ok"}},
        headers=_headers(session["token"]),
    )
    assert resp.status_code == 200
    data = resp.get_json()["data"]
    assert data["table_no"] == 9
    token = data["token"]

    me = client.get("/api/guest/me", headers=_headers(token)).get_json()["data"]
    assert me["table_no"] == 9
    assert me["has_permanent_profile"] is True

    order_resp = client.post(
        "/api/guest/order", json={"song_title": "Believer"}, headers=_headers(token),
    )
    assert order_resp.status_code == 201


def test_link_with_existing_google_account_switches_to_it(client, db, club, app):
    """Редкий случай (см. отчёт по п.45): Google-аккаунт уже был привязан
    раньше (другое устройство/визит) — новый вход подключает СТАРЫЙ
    постоянный профиль, а не то немногое, что накопилось в этой сессии."""
    with app.app_context():
        existing = GuestAccount(club_id=club.club_id, telegram_user_id=42424242, google_sub="already-linked-sub")
        db.session.add(existing)
        db.session.commit()

    session = _session(client, club.club_id)
    resp = client.post(
        "/api/guest/profile/link-google",
        json={"table_no": 10, "google_credential": {"sub": "already-linked-sub"}},
        headers=_headers(session["token"]),
    )
    assert resp.status_code == 200
    data = resp.get_json()["data"]
    assert data["guest_id"] == "42424242"
    assert data["guest_id"] != session["guest_id"]
    assert data["table_no"] == 10


def test_link_google_missing_credential_rejected(client, db, club):
    session = _session(client, club.club_id)
    resp = client.post(
        "/api/guest/profile/link-google",
        json={"table_no": 5, "google_credential": {}},
        headers=_headers(session["token"]),
    )
    assert resp.status_code == 401
    assert resp.get_json()["error"] == "GOOGLE_AUTH_FAILED"


def test_link_google_table_out_of_range_rejected(client, db, club):
    """KJ-04 доп. ТЗ "KJ Pro": если у клуба задано количество столов
    (Club.table_count, настраивается KJ через PUT /api/kj/table-settings),
    гость не может выбрать номер больше этого — как в старом боте
    (venue.table_count, handlers/client.py: table_count_exceeded)."""
    club.table_count = 5
    db.session.commit()

    session = _session(client, club.club_id)
    resp = client.post(
        "/api/guest/profile/link-google",
        json={"table_no": 6, "google_credential": {"sub": "mock-sub-oob"}},
        headers=_headers(session["token"]),
    )
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "TABLE_OUT_OF_RANGE"

    ok = client.post(
        "/api/guest/profile/link-google",
        json={"table_no": 5, "google_credential": {"sub": "mock-sub-in-range"}},
        headers=_headers(session["token"]),
    )
    assert ok.status_code == 200


def test_link_google_table_no_unbounded_when_not_configured(client, db, club):
    """Пока KJ не задал table_count (None по умолчанию) — старое поведение,
    ограничения нет."""
    session = _session(client, club.club_id)
    resp = client.post(
        "/api/guest/profile/link-google",
        json={"table_no": 999, "google_credential": {"sub": "mock-sub-unbounded"}},
        headers=_headers(session["token"]),
    )
    assert resp.status_code == 200
