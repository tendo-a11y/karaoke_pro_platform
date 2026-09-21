"""
Тесты самостоятельной отмены заказа гостем (Role 3/4/5).

ДОБАВЛЕНО 2026-09-20, жалоба пользователя "нет возможности удалить /
заменить / сменить категорию" в "Мои заказы" (у гостя на заказе в статусе
"🎶 В очереди" не было вообще никакого способа его убрать самостоятельно,
кроме как дождаться решения KJ).

ИЗМЕНЕНО ТЕМ ЖЕ ДНЁМ (решение пользователя "Нужно одобрение KJ (запрос →
Одобрить/Отклонить)", по итогам его следующего сообщения: "Гость Удалить
или заменить может только с согласия роли 2"): POST
/api/guest/order/<id>/cancel больше не отменяет заказ немедленно — он
только создаёт заявку (OrderChangeRequest, kind="cancel"), которую должен
одобрить KJ (см. test_order_change_requests.py — там тесты самого
одобрения/отклонения и реальной отмены). Тесты в этом файле проверяют
именно ПОДАЧУ заявки: можно ли её вообще создать (та же матрица, что и у
замены песни, см. vdj_service.CANCELABLE_BY_GUEST_STATUSES) и владельца
заказа — а не то, что заказ немедленно становится rejected (он больше не
становится, пока KJ не одобрит).

Разрешённые статусы намеренно совпадают с can_replace_order (см.
vdj_service.CANCELABLE_BY_GUEST_STATUSES) — то же самое "заказ ещё не
завершил жизненный цикл":

    STATUS_PENDING                          -> можно
    STATUS_PROCESSING                        -> нельзя (переходное состояние)
    STATUS_QUEUED                            -> можно
    STATUS_PLAYING/COMPLETED/REJECTED/ERROR   -> нельзя

Плюс обязательные условия (по аналогии с заменой песни, test_replace.py):
только владелец заказа; заявка не выполняет никакой денежной операции; одна
неразобранная заявка на заказ одновременно.
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
    Transaction,
)


def _headers(token):
    return {"Authorization": f"Bearer {token}"}


def _guest_session(client, club_id, table_no=5):
    """См. пояснение в test_replace.py::_guest_session — ТЗ п.45, стол и
    Google выбираются одним действием, QR никогда не приносит номер стола."""
    resp = client.post("/api/guest/session", json={"club_id": club_id})
    session = resp.get_json()["data"]
    sub = f"mock-sub-{uuid.uuid4().hex[:12]}"
    linked = client.post(
        "/api/guest/profile/link-google",
        json={"table_no": table_no, "google_credential": {"sub": sub}},
        headers=_headers(session["token"]),
    )
    return linked.get_json()["data"]


def _create_order(client, token, song_title="Билет на самолет", artist="Дима Билан"):
    resp = client.post(
        "/api/guest/order",
        json={"song_title": song_title, "artist": artist},
        headers=_headers(token),
    )
    return resp.get_json()["data"]


def _cancel(client, token, order_id):
    return client.post(f"/api/guest/order/{order_id}/cancel", headers=_headers(token))


def _set_status(app, order_id, status):
    with app.app_context():
        o = _db.session.get(Order, order_id)
        o.status = status
        _db.session.commit()


def test_cancel_requires_auth(client, db, club):
    order = _create_order(client, _guest_session(client, club.club_id)["token"])
    resp = client.post(f"/api/guest/order/{order['id']}/cancel")
    assert resp.status_code == 401


def test_cancel_nonexistent_order_returns_404(client, db, club):
    session = _guest_session(client, club.club_id)
    resp = _cancel(client, session["token"], 999999)
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "ORDER_NOT_FOUND"


# --- STATUS_PENDING -> можно подать заявку ---
def test_cancel_request_created_for_pending_order(client, db, club):
    """ИЗМЕНЕНО 2026-09-20 (одобрение KJ): раньше заказ становился rejected
    сразу — теперь эндпоинт только заводит заявку, сам заказ пока остаётся
    pending."""
    session = _guest_session(client, club.club_id)
    order = _create_order(client, session["token"])

    resp = _cancel(client, session["token"], order["id"])
    assert resp.status_code == 201
    data = resp.get_json()["data"]
    assert data["kind"] == "cancel"
    assert data["order_id"] == order["id"]
    assert data["status"] == STATUS_ORDER_CHANGE_PENDING

    with client.application.app_context():
        unchanged = _db.session.get(Order, order["id"])
        assert unchanged.status == "pending"


def test_cancel_request_does_not_create_money_transaction(client, db, club):
    session = _guest_session(client, club.club_id)
    order = _create_order(client, session["token"])

    resp = _cancel(client, session["token"], order["id"])
    assert resp.status_code == 201
    assert Transaction.query.count() == 0


def test_cancel_request_does_not_remove_order_from_my_orders(client, db, club):
    """Заявка сама по себе ничего не меняет в заказе — он остаётся
    видимым в "Мои заказы" (как обычный pending), просто с
    pending_change_request != null (см. test_replace.py про тот же флаг)."""
    session = _guest_session(client, club.club_id)
    order = _create_order(client, session["token"])
    _cancel(client, session["token"], order["id"])

    resp = client.get("/api/guest/orders", headers=_headers(session["token"]))
    data = resp.get_json()["data"]
    assert len(data) == 1
    assert data[0]["id"] == order["id"]
    assert data[0]["pending_change_request"]["kind"] == "cancel"


# --- Одна активная заявка на заказ одновременно ---
def test_cancel_rejects_second_request_while_one_pending(client, db, club):
    session = _guest_session(client, club.club_id)
    order = _create_order(client, session["token"])

    resp1 = _cancel(client, session["token"], order["id"])
    resp2 = _cancel(client, session["token"], order["id"])
    assert resp1.status_code == 201
    assert resp2.status_code == 409
    assert resp2.get_json()["error"] == "REQUEST_ALREADY_PENDING"
    assert OrderChangeRequest.query.filter_by(order_id=order["id"]).count() == 1


# --- Владелец заказа ---
def test_cancel_forbidden_for_other_guest(client, db, club):
    owner_session = _guest_session(client, club.club_id)
    order = _create_order(client, owner_session["token"])

    stranger_session = _guest_session(client, club.club_id, table_no=7)
    resp = _cancel(client, stranger_session["token"], order["id"])
    assert resp.status_code == 403
    assert resp.get_json()["error"] == "FORBIDDEN"

    with client.application.app_context():
        unchanged = _db.session.get(Order, order["id"])
        assert unchanged.status == "pending"
    assert OrderChangeRequest.query.count() == 0


def test_cancel_forbidden_across_clubs(client, db, club, other_club):
    session_a = _guest_session(client, club.club_id)
    order_a = _create_order(client, session_a["token"])

    session_b = _guest_session(client, other_club.club_id)
    resp = _cancel(client, session_b["token"], order_a["id"])
    assert resp.status_code == 403


# --- STATUS_PROCESSING -> нельзя ---
def test_cancel_blocked_while_processing(client, db, club, app):
    session = _guest_session(client, club.club_id)
    order = _create_order(client, session["token"])
    _set_status(app, order["id"], STATUS_PROCESSING)

    resp = _cancel(client, session["token"], order["id"])
    assert resp.status_code == 409
    assert resp.get_json()["error"] == "CANCEL_NOT_ALLOWED"
    assert OrderChangeRequest.query.count() == 0


# --- STATUS_QUEUED -> можно подать заявку ---
def test_cancel_request_allowed_when_queued(client, db, club, app):
    """confirm_order() больше не заводит принятый заказ в живую очередь
    VirtualDJ (см. её докстринг) — подать заявку на отмену можно весь срок,
    пока заказ ждёт исполнения, вплоть до "Готово"."""
    session = _guest_session(client, club.club_id)
    order = _create_order(client, session["token"])
    _set_status(app, order["id"], STATUS_QUEUED)

    resp = _cancel(client, session["token"], order["id"])
    assert resp.status_code == 201
    assert resp.get_json()["data"]["status"] == STATUS_ORDER_CHANGE_PENDING

    with client.application.app_context():
        unchanged = _db.session.get(Order, order["id"])
        assert unchanged.status == STATUS_QUEUED


# --- Финальные/прочие статусы -> нельзя ---
def test_cancel_blocked_when_playing(client, db, club, app):
    session = _guest_session(client, club.club_id)
    order = _create_order(client, session["token"])
    _set_status(app, order["id"], STATUS_PLAYING)

    resp = _cancel(client, session["token"], order["id"])
    assert resp.status_code == 409


def test_cancel_blocked_when_completed(client, db, club, app):
    session = _guest_session(client, club.club_id)
    order = _create_order(client, session["token"])
    _set_status(app, order["id"], STATUS_COMPLETED)

    resp = _cancel(client, session["token"], order["id"])
    assert resp.status_code == 409


def test_cancel_blocked_when_already_rejected(client, db, club, app):
    session = _guest_session(client, club.club_id)
    order = _create_order(client, session["token"])
    _set_status(app, order["id"], STATUS_REJECTED)

    resp = _cancel(client, session["token"], order["id"])
    assert resp.status_code == 409


def test_cancel_blocked_when_error(client, db, club, app):
    session = _guest_session(client, club.club_id)
    order = _create_order(client, session["token"])
    _set_status(app, order["id"], STATUS_ERROR)

    resp = _cancel(client, session["token"], order["id"])
    assert resp.status_code == 409
