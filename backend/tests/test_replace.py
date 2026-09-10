"""
Тесты замены песни (Role 3/4/5) — согласованная и утверждённая пользователем
спецификация (полная матрица правил замены, см. vdj_service.can_replace_order):

    STATUS_PENDING                          -> можно
    STATUS_PROCESSING                        -> нельзя
    STATUS_QUEUED, rank 1 или 2               -> нельзя
    STATUS_QUEUED, rank >= 3                  -> можно
    STATUS_QUEUED, vdj_item_id не в очереди   -> нельзя
    STATUS_PLAYING/COMPLETED/REJECTED/ERROR   -> нельзя

Плюс обязательные условия: только владелец заказа; меняются только
song_title/artist/service_id без отдельной денежной операции; лимита на
число замен нет; старая уязвимость с чужим заказом не переносится.
"""
import uuid

from extensions import db as _db
from models import (
    STATUS_COMPLETED,
    STATUS_ERROR,
    STATUS_PLAYING,
    STATUS_PROCESSING,
    STATUS_QUEUED,
    STATUS_REJECTED,
    Order,
    Service,
    Transaction,
)
from vdj import get_vdj_client


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


# --- STATUS_PENDING -> можно ---
def test_replace_pending_order_allowed(client, db, club):
    session = _guest_session(client, club.club_id)
    order = _create_order(client, session["token"], song_title="Старая песня", artist="Старый исполнитель")

    resp = _replace(client, session["token"], order["id"], song_title="Новая песня", artist="Новый исполнитель")
    assert resp.status_code == 200
    data = resp.get_json()["data"]
    assert data["song_title"] == "Новая песня"
    assert data["artist"] == "Новый исполнитель"
    assert data["status"] == "pending"  # статус не меняется самой заменой


def test_replace_no_limit_on_number_of_replacements(client, db, club):
    """Явное требование пользователя: лимита на количество замен нет."""
    session = _guest_session(client, club.club_id)
    order = _create_order(client, session["token"])

    resp1 = _replace(client, session["token"], order["id"], song_title="Раз")
    resp2 = _replace(client, session["token"], order["id"], song_title="Два")
    resp3 = _replace(client, session["token"], order["id"], song_title="Три")
    assert resp1.status_code == 200
    assert resp2.status_code == 200
    assert resp3.status_code == 200
    assert resp3.get_json()["data"]["song_title"] == "Три"


def test_replace_does_not_create_money_transaction(client, db, club):
    """Утверждённое требование: замена не выполняет отдельную денежную
    операцию — только меняет song_title/artist/service_id на самом заказе."""
    session = _guest_session(client, club.club_id)
    order = _create_order(client, session["token"])

    resp = _replace(client, session["token"], order["id"])
    assert resp.status_code == 200
    assert Transaction.query.count() == 0


def test_replace_changes_service_id(client, db, club):
    service = Service(club_id=club.club_id, name="VIP", price=100, is_free=False)
    db.session.add(service)
    db.session.commit()

    session = _guest_session(client, club.club_id)
    order = _create_order(client, session["token"])

    resp = _replace(client, session["token"], order["id"], service_id=service.id)
    assert resp.status_code == 200
    assert resp.get_json()["data"]["service_id"] == service.id


def test_replace_rejects_unknown_service(client, db, club):
    session = _guest_session(client, club.club_id)
    order = _create_order(client, session["token"])

    resp = _replace(client, session["token"], order["id"], service_id=999999)
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "SERVICE_NOT_FOUND"


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

    # заказ не должен был измениться
    with client.application.app_context():
        unchanged = _db.session.get(Order, order["id"])
        assert unchanged.song_title == order["song_title"]


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

    with app.app_context():
        o = _db.session.get(Order, order["id"])
        o.status = STATUS_PROCESSING
        _db.session.commit()

    resp = _replace(client, session["token"], order["id"])
    assert resp.status_code == 409
    assert resp.get_json()["error"] == "REPLACE_NOT_ALLOWED"


# --- STATUS_QUEUED + rank ---
def _queue_order(app, order_id, club_id, ahead=0):
    """Переводит заказ в STATUS_QUEUED, кладёт `ahead` посторонних песен
    впереди него в mock-очередь VirtualDJ, затем сам заказ — так что его
    итоговый rank == ahead + 1."""
    with app.app_context():
        vdj = get_vdj_client(club_id)
        for i in range(ahead):
            vdj.add_to_queue(f"Чужая песня {i}", None, None)
        vdj_item_id = vdj.add_to_queue("Заказанная песня", None, None)

        o = _db.session.get(Order, order_id)
        o.status = STATUS_QUEUED
        o.vdj_item_id = vdj_item_id
        _db.session.commit()
        return vdj_item_id


def test_replace_blocked_when_queued_rank_1(client, db, club, app):
    session = _guest_session(client, club.club_id)
    order = _create_order(client, session["token"])
    _queue_order(app, order["id"], club.club_id, ahead=0)

    resp = _replace(client, session["token"], order["id"])
    assert resp.status_code == 409
    assert resp.get_json()["error"] == "REPLACE_NOT_ALLOWED"


def test_replace_blocked_when_queued_rank_2(client, db, club, app):
    session = _guest_session(client, club.club_id)
    order = _create_order(client, session["token"])
    _queue_order(app, order["id"], club.club_id, ahead=1)

    resp = _replace(client, session["token"], order["id"])
    assert resp.status_code == 409
    assert resp.get_json()["error"] == "REPLACE_NOT_ALLOWED"


def test_replace_allowed_when_queued_rank_3_or_more(client, db, club, app):
    session = _guest_session(client, club.club_id)
    order = _create_order(client, session["token"])
    _queue_order(app, order["id"], club.club_id, ahead=2)

    resp = _replace(client, session["token"], order["id"], song_title="Другая песня")
    assert resp.status_code == 200
    assert resp.get_json()["data"]["song_title"] == "Другая песня"
    assert resp.get_json()["data"]["status"] == "queued"  # статус не меняется


def test_replace_blocked_when_queued_but_vdj_item_id_not_in_live_queue(client, db, club, app):
    """vdj_item_id заказа не найден в актуальной очереди VirtualDJ (например,
    KJ вручную убрал/переставил трек в самом VDJ) — система не может
    достоверно определить позицию, поэтому замена запрещена."""
    session = _guest_session(client, club.club_id)
    order = _create_order(client, session["token"])

    with app.app_context():
        o = _db.session.get(Order, order["id"])
        o.status = STATUS_QUEUED
        o.vdj_item_id = "mock-does-not-exist"
        _db.session.commit()

    resp = _replace(client, session["token"], order["id"])
    assert resp.status_code == 409
    assert resp.get_json()["error"] == "REPLACE_NOT_ALLOWED"


# --- Финальные/прочие статусы -> нельзя ---
def _set_status(app, order_id, status):
    with app.app_context():
        o = _db.session.get(Order, order_id)
        o.status = status
        _db.session.commit()


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


# --- can_replace в GET /api/guest/orders ---
def test_list_orders_exposes_can_replace_flag(client, db, club, app):
    session = _guest_session(client, club.club_id)
    pending_order = _create_order(client, session["token"], song_title="Ожидает")
    queued_order = _create_order(client, session["token"], song_title="В очереди")
    _queue_order(app, queued_order["id"], club.club_id, ahead=0)  # rank 1 -> нельзя

    resp = client.get("/api/guest/orders", headers=_headers(session["token"]))
    assert resp.status_code == 200
    by_id = {o["id"]: o for o in resp.get_json()["data"]}
    assert by_id[pending_order["id"]]["can_replace"] is True
    assert by_id[queued_order["id"]]["can_replace"] is False
