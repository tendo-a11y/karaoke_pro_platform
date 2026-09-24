"""
Тесты фильтрации истории заказов по периоду (GET /api/guest/orders?days=N)
— старое: handlers/vip.py::vip_order_history, только для VIP, аудит по
"Фильтрация истории заказов". Здесь доступно всем ролям — /orders и так
уже единый эндпоинт для всех в новой архитектуре.

Фильтруем по created_at (не completed_at) — иначе из ленты пропадали бы
ещё не сыгранные заказы текущего периода (см. docstring routes/guest.py
::list_my_orders).
"""
from datetime import datetime, timedelta, timezone

from models import Order


def _headers(token):
    return {"Authorization": f"Bearer {token}"}


def _guest_session(client, club_id, table_no=5):
    resp = client.post("/api/guest/session", json={"club_id": club_id, "table_no": table_no})
    return resp.get_json()["data"]


def _make_order(db, club_id, guest_id, song_title, created_at):
    order = Order(
        telegram_user_id=guest_id, club_id=club_id, table_no=5,
        guest_type="client", song_title=song_title, source="guest",
        created_at=created_at,
    )
    db.session.add(order)
    db.session.commit()
    return order


def test_no_days_param_returns_everything_same_as_before(client, db, club):
    session = _guest_session(client, club.club_id)
    guest_id = int(session["guest_id"])
    _make_order(db, club.club_id, guest_id, "Старая песня", datetime.now(timezone.utc) - timedelta(days=60))
    _make_order(db, club.club_id, guest_id, "Новая песня", datetime.now(timezone.utc))

    resp = client.get("/api/guest/orders", headers=_headers(session["token"]))
    assert resp.status_code == 200
    titles = {o["song_title"] for o in resp.get_json()["data"]}
    assert titles == {"Старая песня", "Новая песня"}


def test_days_filter_excludes_older_orders(client, db, club):
    session = _guest_session(client, club.club_id)
    guest_id = int(session["guest_id"])
    _make_order(db, club.club_id, guest_id, "Месяц назад", datetime.now(timezone.utc) - timedelta(days=30))
    _make_order(db, club.club_id, guest_id, "Сегодня", datetime.now(timezone.utc))

    resp = client.get("/api/guest/orders?days=1", headers=_headers(session["token"]))
    assert resp.status_code == 200
    titles = [o["song_title"] for o in resp.get_json()["data"]]
    assert titles == ["Сегодня"]

    resp = client.get("/api/guest/orders?days=7", headers=_headers(session["token"]))
    titles = [o["song_title"] for o in resp.get_json()["data"]]
    assert titles == ["Сегодня"]

    resp = client.get("/api/guest/orders?days=31", headers=_headers(session["token"]))
    titles = {o["song_title"] for o in resp.get_json()["data"]}
    assert titles == {"Месяц назад", "Сегодня"}


def test_filter_does_not_hide_not_yet_played_orders_regardless_of_completed_at(client, db, club):
    """Ключевая проверка: фильтр по периоду не должен прятать ещё не
    сыгранные заказы (completed_at IS NULL) — иначе гость перестал бы
    видеть свой текущий заказ, переключив период (регрессия, которую
    решили не переносить из старого бота)."""
    session = _guest_session(client, club.club_id)
    guest_id = int(session["guest_id"])
    order = _make_order(db, club.club_id, guest_id, "Играет сейчас", datetime.now(timezone.utc))
    assert order.completed_at is None

    resp = client.get("/api/guest/orders?days=1", headers=_headers(session["token"]))
    titles = [o["song_title"] for o in resp.get_json()["data"]]
    assert titles == ["Играет сейчас"]


def test_filter_scoped_to_own_club_and_guest(client, db, club, other_club):
    session = _guest_session(client, club.club_id)
    guest_id = int(session["guest_id"])
    other_session = _guest_session(client, other_club.club_id)
    other_guest_id = int(other_session["guest_id"])

    _make_order(db, club.club_id, guest_id, "Моя песня", datetime.now(timezone.utc))
    _make_order(db, other_club.club_id, other_guest_id, "Чужая песня (другой клуб)", datetime.now(timezone.utc))

    resp = client.get("/api/guest/orders?days=1", headers=_headers(session["token"]))
    titles = [o["song_title"] for o in resp.get_json()["data"]]
    assert titles == ["Моя песня"]


def test_invalid_days_param_ignored_not_500(client, db, club):
    """type=int в request.args.get молча возвращает None на нечисловой
    ввод — а не 500; фиксируем это поведение явным тестом."""
    session = _guest_session(client, club.club_id)
    guest_id = int(session["guest_id"])
    _make_order(db, club.club_id, guest_id, "Песня", datetime.now(timezone.utc))

    resp = client.get("/api/guest/orders?days=abc", headers=_headers(session["token"]))
    assert resp.status_code == 200
    assert len(resp.get_json()["data"]) == 1


# ДОБАВЛЕНО (2026-09-24, жалоба пользователя "почему в панели гостя висят
# старые заказы, им уже 2 дня" + уточнение "правильно разделить на две
# вкладки история и мои заказы, мои заказы — это то что происходит в рамках
# одной сессии") — см. подробный докстринг routes/guest.py::list_my_orders
# про ?scope=session и почему календарного ?days=N для этого недостаточно
# (guest_id у вошедшего через Google гостя постоянный между визитами).
def test_scope_session_excludes_orders_from_before_this_session(client, db, club):
    session = _guest_session(client, club.club_id)
    guest_id = int(session["guest_id"])
    # "Прошлый визит" — заказ старше момента выпуска токена этой сессии.
    _make_order(db, club.club_id, guest_id, "Прошлый визит", datetime.now(timezone.utc) - timedelta(hours=2))
    _make_order(db, club.club_id, guest_id, "Этот визит", datetime.now(timezone.utc))

    resp = client.get("/api/guest/orders?scope=session", headers=_headers(session["token"]))
    assert resp.status_code == 200
    titles = [o["song_title"] for o in resp.get_json()["data"]]
    assert titles == ["Этот визит"]


def test_scope_session_matches_own_google_identity_even_across_days(client, db, club):
    """Ключевой сценарий из жалобы: тот же (постоянный) guest_id, но новый
    токен, выпущенный сильно позже — старые заказы под ?scope=session не
    всплывают, хотя под ?days=7 (и тем более без фильтра) всплыли бы."""
    guest_id = 424242
    _make_order(db, club.club_id, guest_id, "Позавчера", datetime.now(timezone.utc) - timedelta(days=2))

    from auth import issue_guest_token
    token = issue_guest_token(guest_id, club.club_id, 5, client.application.config["GUEST_JWT_SECRET"], 43200)
    _make_order(db, club.club_id, guest_id, "Сейчас", datetime.now(timezone.utc))

    resp = client.get("/api/guest/orders?scope=session", headers=_headers(token))
    assert resp.status_code == 200
    assert [o["song_title"] for o in resp.get_json()["data"]] == ["Сейчас"]

    resp = client.get("/api/guest/orders?days=7", headers=_headers(token))
    titles = {o["song_title"] for o in resp.get_json()["data"]}
    assert titles == {"Позавчера", "Сейчас"}


def test_scope_session_does_not_hide_not_yet_played_order_from_this_session(client, db, club):
    session = _guest_session(client, club.club_id)
    guest_id = int(session["guest_id"])
    order = _make_order(db, club.club_id, guest_id, "Играет сейчас", datetime.now(timezone.utc))
    assert order.completed_at is None

    resp = client.get("/api/guest/orders?scope=session", headers=_headers(session["token"]))
    assert [o["song_title"] for o in resp.get_json()["data"]] == ["Играет сейчас"]


def test_scope_other_than_session_falls_back_to_days_behaviour(client, db, club):
    """?scope=anything-else (или отсутствие ?scope вовсе) не должен молча
    включать фильтр по сессии — это оставленное для ?days=N поведение."""
    session = _guest_session(client, club.club_id)
    guest_id = int(session["guest_id"])
    _make_order(db, club.club_id, guest_id, "Месяц назад", datetime.now(timezone.utc) - timedelta(days=30))

    resp = client.get("/api/guest/orders?scope=history&days=60", headers=_headers(session["token"]))
    assert resp.status_code == 200
    assert [o["song_title"] for o in resp.get_json()["data"]] == ["Месяц назад"]
