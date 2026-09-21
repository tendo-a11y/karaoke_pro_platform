"""
Тесты решения KJ по заявкам гостей на отмену/замену заказа — ДОБАВЛЕНО
2026-09-20 вместе с самой моделью OrderChangeRequest (см. models.py и
docstring services/vdj_service.py::approve_order_change_request).

Решение пользователя, реализуемое здесь: "Гость Удалить или заменить
может только с согласия роли 2 — об этом роли 2 должно прийти уведомление
о замене или удалении" (Нужно одобрение KJ: запрос → Одобрить/Отклонить).

Подача самих заявок гостем покрыта test_cancel_order.py (kind="cancel") и
test_replace.py (kind="replace") — этот файл проверяет только вторую
половину потока: список неразобранных заявок у KJ и решение по ним
(одобрить -> реально применить cancel/replace к заказу; отклонить ->
заказ остаётся как был), включая изоляцию по клубам и обработку
"устаревшей" заявки (заказ успел измениться, пока заявка ждала решения).
"""
import uuid

from extensions import db as _db
from models import (
    STATUS_ORDER_CHANGE_APPROVED,
    STATUS_ORDER_CHANGE_REJECTED,
    STATUS_PLAYING,
    STATUS_QUEUED,
    STATUS_REJECTED,
    Order,
)


def _headers(token):
    return {"Authorization": f"Bearer {token}"}


def _guest_session(client, club_id, table_no=5):
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


def _request_cancel(client, token, order_id):
    resp = client.post(f"/api/guest/order/{order_id}/cancel", headers=_headers(token))
    return resp.get_json()["data"]["id"]


def _request_replace(client, token, order_id, song_title="Другая песня", artist=None, service_id=None):
    resp = client.post(
        f"/api/guest/order/{order_id}/replace",
        json={"song_title": song_title, "artist": artist, "service_id": service_id},
        headers=_headers(token),
    )
    return resp.get_json()["data"]["id"]


def _set_status(app, order_id, status):
    with app.app_context():
        o = _db.session.get(Order, order_id)
        o.status = status
        _db.session.commit()


# --- Список неразобранных заявок у KJ ---
def test_list_order_change_requests_empty_by_default(client, db, club, kj):
    resp = client.get(f"/api/kj/order-change-requests/{club.club_id}", headers=kj["headers"])
    assert resp.status_code == 200
    assert resp.get_json()["data"] == []


def test_list_order_change_requests_shows_order_context(client, db, club, kj):
    """table_no/order_song_title/order_artist подтягиваются из связанного
    Order (см. routes/kj.py::list_order_change_requests) — KJ должен
    видеть, о каком именно заказе речь, не открывая его отдельно."""
    session = _guest_session(client, club.club_id, table_no=9)
    order = _create_order(client, session["token"], song_title="Кукла колдуна", artist="Технология")
    _request_cancel(client, session["token"], order["id"])

    resp = client.get(f"/api/kj/order-change-requests/{club.club_id}", headers=kj["headers"])
    data = resp.get_json()["data"]
    assert len(data) == 1
    assert data[0]["kind"] == "cancel"
    assert data[0]["table_no"] == 9
    assert data[0]["order_song_title"] == "Кукла колдуна"
    assert data[0]["order_artist"] == "Технология"


def test_list_order_change_requests_isolated_by_club(client, db, club, other_club, kj):
    session = _guest_session(client, club.club_id)
    order = _create_order(client, session["token"])
    _request_cancel(client, session["token"], order["id"])

    resp = client.get(f"/api/kj/order-change-requests/{other_club.club_id}", headers=kj["headers"])
    # kj принадлежит club, не other_club — доступ вообще запрещён.
    assert resp.status_code == 403


# --- Одобрение отмены ---
def test_approve_cancel_request_rejects_the_order(client, db, club, kj):
    session = _guest_session(client, club.club_id)
    order = _create_order(client, session["token"])
    request_id = _request_cancel(client, session["token"], order["id"])

    resp = client.put(f"/api/kj/order-change-requests/{request_id}/approve", headers=kj["headers"])
    assert resp.status_code == 200
    data = resp.get_json()["data"]
    assert data["request"]["status"] == STATUS_ORDER_CHANGE_APPROVED
    assert data["order"]["status"] == STATUS_REJECTED

    with client.application.app_context():
        updated = _db.session.get(Order, order["id"])
        assert updated.status == STATUS_REJECTED


def test_approved_cancel_request_disappears_from_pending_list(client, db, club, kj):
    session = _guest_session(client, club.club_id)
    order = _create_order(client, session["token"])
    request_id = _request_cancel(client, session["token"], order["id"])

    client.put(f"/api/kj/order-change-requests/{request_id}/approve", headers=kj["headers"])

    resp = client.get(f"/api/kj/order-change-requests/{club.club_id}", headers=kj["headers"])
    assert resp.get_json()["data"] == []


# --- Одобрение замены ---
def test_approve_replace_request_updates_the_order(client, db, club, kj):
    session = _guest_session(client, club.club_id)
    order = _create_order(client, session["token"], song_title="Старая", artist="Кто-то")
    request_id = _request_replace(client, session["token"], order["id"], song_title="Новая", artist="Кто-то другой")

    resp = client.put(f"/api/kj/order-change-requests/{request_id}/approve", headers=kj["headers"])
    assert resp.status_code == 200
    data = resp.get_json()["data"]
    assert data["order"]["song_title"] == "Новая"
    assert data["order"]["artist"] == "Кто-то другой"
    # Замена не меняет статус заказа — только песню/исполнителя/категорию.
    assert data["order"]["status"] == "pending"

    with client.application.app_context():
        updated = _db.session.get(Order, order["id"])
        assert updated.song_title == "Новая"
        assert updated.artist == "Кто-то другой"


# --- Отклонение ---
def test_reject_change_request_leaves_order_untouched(client, db, club, kj):
    session = _guest_session(client, club.club_id)
    order = _create_order(client, session["token"], song_title="Старая")
    request_id = _request_replace(client, session["token"], order["id"], song_title="Новая")

    resp = client.put(f"/api/kj/order-change-requests/{request_id}/reject", headers=kj["headers"])
    assert resp.status_code == 200
    assert resp.get_json()["data"]["status"] == STATUS_ORDER_CHANGE_REJECTED

    with client.application.app_context():
        unchanged = _db.session.get(Order, order["id"])
        assert unchanged.song_title == "Старая"


def test_reject_cancel_request_leaves_order_untouched(client, db, club, kj):
    session = _guest_session(client, club.club_id)
    order = _create_order(client, session["token"])
    request_id = _request_cancel(client, session["token"], order["id"])

    client.put(f"/api/kj/order-change-requests/{request_id}/reject", headers=kj["headers"])

    with client.application.app_context():
        unchanged = _db.session.get(Order, order["id"])
        assert unchanged.status == "pending"


# --- После отклонения гость может подать заявку заново ---
def test_new_request_allowed_after_previous_one_rejected(client, db, club, kj):
    session = _guest_session(client, club.club_id)
    order = _create_order(client, session["token"])
    first_request_id = _request_cancel(client, session["token"], order["id"])
    client.put(f"/api/kj/order-change-requests/{first_request_id}/reject", headers=kj["headers"])

    resp = client.post(f"/api/guest/order/{order['id']}/cancel", headers=_headers(session["token"]))
    assert resp.status_code == 201


# --- Изоляция по клубам ---
def test_approve_forbidden_for_other_club_kj(client, db, club, other_club, other_kj):
    session = _guest_session(client, club.club_id)
    order = _create_order(client, session["token"])
    request_id = _request_cancel(client, session["token"], order["id"])

    resp = client.put(f"/api/kj/order-change-requests/{request_id}/approve", headers=other_kj["headers"])
    assert resp.status_code == 403


def test_reject_forbidden_for_other_club_kj(client, db, club, other_club, other_kj):
    session = _guest_session(client, club.club_id)
    order = _create_order(client, session["token"])
    request_id = _request_cancel(client, session["token"], order["id"])

    resp = client.put(f"/api/kj/order-change-requests/{request_id}/reject", headers=other_kj["headers"])
    assert resp.status_code == 403


# --- Повторное решение по уже решённой заявке ---
def test_approve_already_decided_request_returns_409(client, db, club, kj):
    session = _guest_session(client, club.club_id)
    order = _create_order(client, session["token"])
    request_id = _request_cancel(client, session["token"], order["id"])
    client.put(f"/api/kj/order-change-requests/{request_id}/approve", headers=kj["headers"])

    resp = client.put(f"/api/kj/order-change-requests/{request_id}/approve", headers=kj["headers"])
    assert resp.status_code == 409
    assert resp.get_json()["error"] == "ALREADY_DECIDED"


def test_approve_nonexistent_request_returns_404(client, db, club, kj):
    resp = client.put("/api/kj/order-change-requests/999999/approve", headers=kj["headers"])
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "REQUEST_NOT_FOUND"


# --- Заказ устарел, пока заявка ждала решения KJ ---
def test_approve_cancel_request_stale_when_order_already_playing(client, db, club, kj, app):
    """Между подачей заявки и решением KJ заказ мог перейти в состояние,
    для которого отмена уже не имеет смысла (например, уже играет) — такая
    заявка автоматически отклоняется вместо того, чтобы тихо примениться к
    неподходящему заказу (см. docstring approve_order_change_request)."""
    session = _guest_session(client, club.club_id)
    order = _create_order(client, session["token"])
    request_id = _request_cancel(client, session["token"], order["id"])

    _set_status(app, order["id"], STATUS_PLAYING)

    resp = client.put(f"/api/kj/order-change-requests/{request_id}/approve", headers=kj["headers"])
    assert resp.status_code == 409
    assert resp.get_json()["error"] == "ORDER_CHANGED"

    with client.application.app_context():
        unchanged = _db.session.get(Order, order["id"])
        assert unchanged.status == STATUS_PLAYING  # не тронут одобрением

    resp = client.get(f"/api/kj/order-change-requests/{club.club_id}", headers=kj["headers"])
    assert resp.get_json()["data"] == []  # заявка исчезла из списка (сама отклонилась)


def test_approve_replace_request_still_works_when_order_queued(client, db, club, kj, app):
    """queued остаётся допустимым для замены весь срок до "Готово" — заявка
    НЕ должна стать stale только из-за перехода pending -> queued между
    подачей и решением (см. can_replace_order)."""
    session = _guest_session(client, club.club_id)
    order = _create_order(client, session["token"], song_title="Старая")
    request_id = _request_replace(client, session["token"], order["id"], song_title="Новая")

    _set_status(app, order["id"], STATUS_QUEUED)

    resp = client.put(f"/api/kj/order-change-requests/{request_id}/approve", headers=kj["headers"])
    assert resp.status_code == 200
    assert resp.get_json()["data"]["order"]["song_title"] == "Новая"
