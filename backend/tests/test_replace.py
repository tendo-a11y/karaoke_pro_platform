"""
Тесты замены песни (Role 3/4/5) — согласованная и утверждённая пользователем
спецификация (матрица правил замены, см. vdj_service.can_replace_order).

ОБНОВЛЕНО 2026-09-20 (жалоба пользователя "нет возможности удалить /
заменить / сменить категорию" — у гостя на уже принятом (queued) заказе
кнопки "Заменить" не было вообще): старая матрица опиралась на позицию
заказа в ЖИВОЙ очереди VirtualDJ, но с 2026-09-18 confirm_order() перестала
сама передавать туда принятые заказы (см. её докстринг) — vdj_item_id у
STATUS_QUEUED-заказа теперь НИКОГДА не проставляется, из-за чего старая
проверка ранга превратилась в "нельзя всегда". Актуальная матрица (кто
может ПОДАТЬ ЗАЯВКУ на замену — см. следующий абзац):

    STATUS_PENDING                          -> можно
    STATUS_PROCESSING                        -> нельзя
    STATUS_QUEUED                            -> можно (весь срок, пока
        заказ ждёт исполнения, вплоть до "Готово")
    STATUS_PLAYING/COMPLETED/REJECTED/ERROR   -> нельзя

ОБНОВЛЕНО ЕЩЁ РАЗ 2026-09-20, тем же днём (решение пользователя "Нужно
одобрение KJ (запрос → Одобрить/Отклонить)", по итогам его же следующего
сообщения: "Гость Удалить или заменить может только с согласия роли 2"):
POST /api/guest/order/<id>/replace больше не меняет песню в заказе сразу —
он только создаёт заявку (OrderChangeRequest, kind="replace"), которую
должен одобрить KJ (см. test_order_change_requests.py — там тесты самого
одобрения/отклонения и реального применения замены). Тесты в этом файле
проверяют именно ПОДАЧУ заявки: правильно ли эндпоинт решает, можно ли её
вообще создать (матрица выше, владелец заказа, service_id), и что она
создаётся с правильными полями — а не то, что песня меняется немедленно
(она больше не меняется).

Плюс обязательные условия: только владелец заказа; лимита на число заявок
на замену нет (кроме одной неразобранной заявки на заказ одновременно);
старая уязвимость с чужим заказом не переносится.
"""
import uuid

from extensions import db as _db
from models import (
    STATUS_COMPLETED,
    STATUS_ERROR,
    STATUS_ORDER_CHANGE_PENDING,
    STATUS_PLAYING,
    STATUS_PROCESSING,
    STATUS_QUEUED,
    STATUS_REJECTED,
    Order,
    OrderChangeRequest,
    Service,
)


def _headers(token):
    return {"Authorization": f"Bearer {token}"}


def _guest_session(client, club_id, table_no=5):
    """ТЗ п.45 (финальная единая модель входа): QR никогда не приносит
    номер стола — сессия создаётся без стола, а стол выбирается вместе с
    обязательным входом через Google, одним действием. Этот файл целиком
    про заказы/замену песни, поэтому здесь удобнее сразу выполнять оба
    шага одним местом, а не в каждом тесте отдельно. guest_id не меняется
    (аккаунта с этим mock-sub ещё не было), так что остальной код файла
    ничего не замечает."""
    resp = client.post("/api/guest/session", json={"club_id": club_id})
    session = resp.get_json()["data"]
    sub = f"mock-sub-{uuid.uuid4().hex[:12]}"
    linked = client.post(
        "/api/guest/profile/link-google",
        json={"table_no": table_no, "google_credential": {"sub": sub}},
        headers=_headers(session["token"]),
    )
    return linked.get_json()["data"]


def _create_order(client, token, song_title="Билет на самолет", artist="Дима Билан", service_id=None):
    resp = client.post(
        "/api/guest/order",
        json={"song_title": song_title, "artist": artist, "service_id": service_id},
        headers=_headers(token),
    )
    return resp.get_json()["data"]


def _replace(client, token, order_id, song_title="Новая песня", artist="Новый исполнитель", service_id=None):
    return client.post(
        f"/api/guest/order/{order_id}/replace",
        json={"song_title": song_title, "artist": artist, "service_id": service_id},
        headers=_headers(token),
    )


def _set_status(app, order_id, status):
    with app.app_context():
        o = _db.session.get(Order, order_id)
        o.status = status
        _db.session.commit()


def test_replace_requires_auth(client, db, club):
    order = _create_order(client, _guest_session(client, club.club_id)["token"])
    resp = client.post(f"/api/guest/order/{order['id']}/replace", json={"song_title": "X"})
    assert resp.status_code == 401


def test_replace_validates_song_title(client, db, club):
    session = _guest_session(client, club.club_id)
    order = _create_order(client, session["token"])
    resp = client.post(
        f"/api/guest/order/{order['id']}/replace", json={}, headers=_headers(session["token"]),
    )
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "VALIDATION_ERROR"


def test_replace_nonexistent_order_returns_404(client, db, club):
    session = _guest_session(client, club.club_id)
    resp = _replace(client, session["token"], 999999)
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "ORDER_NOT_FOUND"


# --- STATUS_PENDING -> можно подать заявку ---
def test_replace_request_created_for_pending_order(client, db, club):
    """ИЗМЕНЕНО 2026-09-20 (одобрение KJ): раньше здесь заказ менялся
    сразу — теперь эндпоинт только заводит заявку, сам заказ пока не
    трогается вообще."""
    session = _guest_session(client, club.club_id)
    order = _create_order(client, session["token"], song_title="Старая песня", artist="Старый исполнитель")

    resp = _replace(client, session["token"], order["id"], song_title="Новая песня", artist="Новый исполнитель")
    assert resp.status_code == 201
    data = resp.get_json()["data"]
    assert data["kind"] == "replace"
    assert data["order_id"] == order["id"]
    assert data["new_song_title"] == "Новая песня"
    assert data["new_artist"] == "Новый исполнитель"
    assert data["status"] == STATUS_ORDER_CHANGE_PENDING

    # Сам заказ не изменился — изменение произойдёт только при одобрении KJ.
    with client.application.app_context():
        unchanged = _db.session.get(Order, order["id"])
        assert unchanged.song_title == "Старая песня"
        assert unchanged.artist == "Старый исполнитель"


def test_replace_request_persisted_in_db(client, db, club):
    session = _guest_session(client, club.club_id)
    order = _create_order(client, session["token"])

    _replace(client, session["token"], order["id"], song_title="Новая песня")
    assert OrderChangeRequest.query.filter_by(order_id=order["id"]).count() == 1


# --- Одна активная заявка на заказ одновременно ---
def test_replace_rejects_second_request_while_one_pending(client, db, club):
    """Явное требование пользователя реализовано через одну неразобранную
    заявку на заказ (see vdj_service.get_pending_change_request) — до
    решения KJ по первой заявке вторую подать нельзя, иначе неясно, какую
    из двух одобрять."""
    session = _guest_session(client, club.club_id)
    order = _create_order(client, session["token"])

    resp1 = _replace(client, session["token"], order["id"], song_title="Раз")
    resp2 = _replace(client, session["token"], order["id"], song_title="Два")
    assert resp1.status_code == 201
    assert resp2.status_code == 409
    assert resp2.get_json()["error"] == "REQUEST_ALREADY_PENDING"
    assert OrderChangeRequest.query.filter_by(order_id=order["id"]).count() == 1


def test_replace_changes_service_id_in_request(client, db, club):
    service = Service(club_id=club.club_id, name="VIP", price=100, is_free=False)
    db.session.add(service)
    db.session.commit()

    session = _guest_session(client, club.club_id)
    order = _create_order(client, session["token"])

    resp = _replace(client, session["token"], order["id"], service_id=service.id)
    assert resp.status_code == 201
    assert resp.get_json()["data"]["new_service_id"] == service.id


def test_replace_rejects_unknown_service(client, db, club):
    session = _guest_session(client, club.club_id)
    order = _create_order(client, session["token"])

    resp = _replace(client, session["token"], order["id"], service_id=999999)
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "SERVICE_NOT_FOUND"
    assert OrderChangeRequest.query.count() == 0


def test_replace_rejects_service_id_wrong_type(client, db, club):
    session = _guest_session(client, club.club_id)
    order = _create_order(client, session["token"])

    resp = client.post(
        f"/api/guest/order/{order['id']}/replace",
        json={"song_title": "X", "service_id": "not-a-number"},
        headers=_headers(session["token"]),
    )
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "VALIDATION_ERROR"


# --- Владелец заказа ---
def test_replace_forbidden_for_other_guest(client, db, club):
    """Старая уязвимость (аудит замены песни): владелец заказа не
    проверялся вообще. Здесь — сознательно НЕ переносим её."""
    owner_session = _guest_session(client, club.club_id)
    order = _create_order(client, owner_session["token"])

    stranger_session = _guest_session(client, club.club_id, table_no=7)
    resp = _replace(client, stranger_session["token"], order["id"])
    assert resp.status_code == 403
    assert resp.get_json()["error"] == "FORBIDDEN"

    # заказ не должен был измениться, и заявка не должна была создаться
    with client.application.app_context():
        unchanged = _db.session.get(Order, order["id"])
        assert unchanged.song_title == order["song_title"]
    assert OrderChangeRequest.query.count() == 0


def test_replace_forbidden_across_clubs(client, db, club, other_club):
    session_a = _guest_session(client, club.club_id)
    order_a = _create_order(client, session_a["token"])

    session_b = _guest_session(client, other_club.club_id)
    resp = _replace(client, session_b["token"], order_a["id"])
    assert resp.status_code == 403


# --- STATUS_PROCESSING -> нельзя ---
def test_replace_blocked_while_processing(client, db, club, app):
    session = _guest_session(client, club.club_id)
    order = _create_order(client, session["token"])
    _set_status(app, order["id"], STATUS_PROCESSING)

    resp = _replace(client, session["token"], order["id"])
    assert resp.status_code == 409
    assert resp.get_json()["error"] == "REPLACE_NOT_ALLOWED"
    assert OrderChangeRequest.query.count() == 0


# --- STATUS_QUEUED -> можно подать заявку (см. докстринг файла) ---
def test_replace_request_allowed_when_queued(client, db, club, app):
    """confirm_order() больше не заводит принятый заказ в живую очередь
    VirtualDJ — vdj_item_id у него никогда не проставляется, поэтому
    прежняя проверка ранга здесь больше не применяется вообще: подать
    заявку на замену можно весь срок, пока заказ ждёт исполнения (до
    "Готово")."""
    session = _guest_session(client, club.club_id)
    order = _create_order(client, session["token"])
    _set_status(app, order["id"], STATUS_QUEUED)

    resp = _replace(client, session["token"], order["id"], song_title="Другая песня")
    assert resp.status_code == 201
    assert resp.get_json()["data"]["new_song_title"] == "Другая песня"

    # Заказ пока не изменился и остался queued — заявка ещё не одобрена.
    with client.application.app_context():
        unchanged = _db.session.get(Order, order["id"])
        assert unchanged.song_title != "Другая песня"
        assert unchanged.status == STATUS_QUEUED


def test_replace_blocked_when_playing(client, db, club, app):
    session = _guest_session(client, club.club_id)
    order = _create_order(client, session["token"])
    _set_status(app, order["id"], STATUS_PLAYING)

    resp = _replace(client, session["token"], order["id"])
    assert resp.status_code == 409


def test_replace_blocked_when_completed(client, db, club, app):
    session = _guest_session(client, club.club_id)
    order = _create_order(client, session["token"])
    _set_status(app, order["id"], STATUS_COMPLETED)

    resp = _replace(client, session["token"], order["id"])
    assert resp.status_code == 409


def test_replace_blocked_when_rejected(client, db, club, app):
    session = _guest_session(client, club.club_id)
    order = _create_order(client, session["token"])
    _set_status(app, order["id"], STATUS_REJECTED)

    resp = _replace(client, session["token"], order["id"])
    assert resp.status_code == 409


def test_replace_blocked_when_error(client, db, club, app):
    session = _guest_session(client, club.club_id)
    order = _create_order(client, session["token"])
    _set_status(app, order["id"], STATUS_ERROR)

    resp = _replace(client, session["token"], order["id"])
    assert resp.status_code == 409


# --- can_replace / pending_change_request в GET /api/guest/orders ---
def test_list_orders_exposes_can_replace_flag(client, db, club, app):
    """queued тоже даёт can_replace=True (см. докстринг файла) — это флаг
    "можно ли ПОДАТЬ заявку", не "заказ уже изменён"."""
    session = _guest_session(client, club.club_id)
    pending_order = _create_order(client, session["token"], song_title="Ожидает")
    queued_order = _create_order(client, session["token"], song_title="В очереди")
    _set_status(app, queued_order["id"], STATUS_QUEUED)

    resp = client.get("/api/guest/orders", headers=_headers(session["token"]))
    assert resp.status_code == 200
    by_id = {o["id"]: o for o in resp.get_json()["data"]}
    assert by_id[pending_order["id"]]["can_replace"] is True
    assert by_id[queued_order["id"]]["can_replace"] is True


def test_list_orders_exposes_pending_change_request(client, db, club):
    """ДОБАВЛЕНО 2026-09-20 (одобрение KJ): пока заявка на замену не
    разобрана KJ, GET /api/guest/orders должен показать её (kind="replace"),
    чтобы фронтенд мог скрыть кнопки и показать "ждите решения ведущего"
    вместо них (см. guest-app/src/App.jsx::OrderRow)."""
    session = _guest_session(client, club.club_id)
    order = _create_order(client, session["token"])

    before = client.get("/api/guest/orders", headers=_headers(session["token"]))
    assert before.get_json()["data"][0]["pending_change_request"] is None

    _replace(client, session["token"], order["id"], song_title="Другая")

    resp = client.get("/api/guest/orders", headers=_headers(session["token"]))
    by_id = {o["id"]: o for o in resp.get_json()["data"]}
    pending = by_id[order["id"]]["pending_change_request"]
    assert pending is not None
    assert pending["kind"] == "replace"
