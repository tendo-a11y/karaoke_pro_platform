"""
Тесты закрытия группового стола по инициативе гостя-админа (запрос
пользователя 2026-09-27) — см. докстринг models.TableCloseRequest и
services/table_close_service.py.

Ключевые решения пользователя, которые здесь проверяются:
  - подтверждение KJ обязательно освобождает TableGroup (чинит зависание
    "первый гость навсегда админ стола");
  - непроигранные (ещё активные) заказы стола автоматически снимаются;
  - в чек попадают только реально сыгранные (completed) заказы ЭТОЙ сессии
    стола (с момента создания текущего TableGroup), а не весь вечер;
  - чекбокс "Не показывать чек" (hide_receipt) скрывает чек от гостей, но
    не отменяет его подсчёт.
"""
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from extensions import db as _db
from models import (
    STATUS_COMPLETED,
    STATUS_QUEUED,
    STATUS_REJECTED,
    STATUS_TABLE_CLOSE_APPROVED,
    Order,
    Service,
    TableCloseRequest,
    TableGroup,
    TableGroupMember,
)


def _headers(token):
    return {"Authorization": f"Bearer {token}"}


def _session(client, club_id, table_no):
    """Тот же двухшаговый вход, что и в test_table_group.py::_session
    (ТЗ п.45: стол выбирается только вместе со входом через Google)."""
    resp = client.post("/api/guest/session", json={"club_id": club_id})
    session = resp.get_json()["data"]
    sub = f"mock-sub-{uuid.uuid4().hex[:12]}"
    linked = client.post(
        "/api/guest/profile/link-google",
        json={"table_no": table_no, "google_credential": {"sub": sub}},
        headers=_headers(session["token"]),
    )
    assert linked.status_code == 200
    return linked.get_json()["data"]


def _me(client, token):
    return client.get("/api/guest/me", headers=_headers(token)).get_json()["data"]


def _completed_order(db, club_id, table_no, guest_id, service_id=None, song_title="Песня"):
    o = Order(
        telegram_user_id=guest_id, club_id=club_id, table_no=table_no, guest_type="client",
        song_title=song_title, service_id=service_id, status=STATUS_COMPLETED,
    )
    db.session.add(o)
    db.session.commit()
    return o


# --- Заявку может подать только текущий админ стола ---

def test_only_admin_can_request_close(client, db, club):
    admin_session = _session(client, club.club_id, table_no=20)

    resp = client.post(
        "/api/guest/table-group/request-close", headers=_headers(admin_session["token"]),
    )
    assert resp.status_code == 201
    assert resp.get_json()["data"]["status"] == "pending"

    # Второй такой же запрос, пока первый ещё не решён — не плодит дубликат.
    resp2 = client.post(
        "/api/guest/table-group/request-close", headers=_headers(admin_session["token"]),
    )
    assert resp2.status_code == 200
    assert resp2.get_json()["data"]["id"] == resp.get_json()["data"]["id"]

    with client.application.app_context():
        assert TableCloseRequest.query.filter_by(club_id=club.club_id, table_no=20).count() == 1


def test_non_admin_cannot_request_close(client, db, club):
    admin_session = _session(client, club.club_id, table_no=21)

    # Второй гость присоединяется и админ его одобряет — так у стола
    # появляется участник, который НЕ админ.
    joiner = client.post("/api/guest/session", json={"club_id": club.club_id}).get_json()["data"]
    sub = f"mock-sub-{uuid.uuid4().hex[:12]}"
    joiner = client.post(
        "/api/guest/profile/link-google",
        json={"table_no": 21, "google_credential": {"sub": sub}},
        headers=_headers(joiner["token"]),
    ).get_json()["data"]
    assert joiner["table_group_status"] == "pending"

    pending = client.get(
        "/api/guest/table-group", headers=_headers(admin_session["token"]),
    ).get_json()["data"]["pending_requests"]
    req_id = pending[0]["id"]
    client.post(
        f"/api/guest/table-group/join-requests/{req_id}/approve",
        headers=_headers(admin_session["token"]),
    )

    resp = client.post(
        "/api/guest/table-group/request-close", headers=_headers(joiner["token"]),
    )
    assert resp.status_code == 403
    assert resp.get_json()["error"] == "FORBIDDEN"


# --- KJ другого клуба не может решать чужую заявку ---

def test_kj_cannot_decide_other_clubs_request(client, db, club, kj, other_kj):
    admin_session = _session(client, club.club_id, table_no=22)
    req = client.post(
        "/api/guest/table-group/request-close", headers=_headers(admin_session["token"]),
    ).get_json()["data"]

    resp = client.put(
        f"/api/kj/table-close-requests/{req['id']}/approve",
        json={}, headers=other_kj["headers"],
    )
    assert resp.status_code == 403
    assert resp.get_json()["error"] == "FORBIDDEN"


# --- Полный цикл: подтверждение освобождает стол, считает чек, снимает непроигранное ---

def test_approve_closes_table_builds_receipt_and_rejects_unplayed_orders(client, db, club, kj):
    admin_session = _session(client, club.club_id, table_no=23)
    admin_guest_id = int(admin_session["guest_id"])

    with client.application.app_context():
        service = Service(club_id=club.club_id, name="Обычная песня", price=Decimal("15.00"), is_free=False)
        db.session.add(service)
        db.session.commit()
        service_id = service.id

        # Сыгранная за ЭТУ сессию — должна попасть в чек.
        _completed_order(db, club.club_id, 23, admin_guest_id, service_id=service_id, song_title="Сыгранная")
        # Сыгранная, но без тарифа — тоже считается, отдельной категорией.
        _completed_order(db, club.club_id, 23, admin_guest_id, service_id=None, song_title="Без тарифа")

        # Сыгранная ДО того, как сформировался этот групповой стол — не
        # должна попасть в чек (решение пользователя: только эта сессия).
        old_order = _completed_order(db, club.club_id, 23, admin_guest_id, service_id=service_id, song_title="Старая")
        old_order.created_at = datetime.now(timezone.utc) - timedelta(hours=5)
        db.session.commit()

    # Ещё непроигранная песня — должна быть автоматически снята при закрытии.
    order_resp = client.post(
        "/api/guest/order", json={"song_title": "Ещё не сыграна"}, headers=_headers(admin_session["token"]),
    )
    assert order_resp.status_code == 201
    active_order_id = order_resp.get_json()["data"]["id"]

    req = client.post(
        "/api/guest/table-group/request-close", headers=_headers(admin_session["token"]),
    ).get_json()["data"]

    resp = client.put(
        f"/api/kj/table-close-requests/{req['id']}/approve",
        json={"hide_receipt": False}, headers=kj["headers"],
    )
    assert resp.status_code == 200
    data = resp.get_json()["data"]
    assert data["closed_order_ids"] == [active_order_id]

    receipt = data["request"]["receipt"]
    assert receipt["song_count"] == 2
    assert receipt["table_no"] == 23
    categories = {c["category"]: c for c in receipt["categories"]}
    assert categories["Обычная песня"]["count"] == 1
    assert categories["Обычная песня"]["sum"] == 15.0
    assert categories["Без категории"]["count"] == 1
    assert categories["Без категории"]["sum"] == 0.0
    assert receipt["total"] == 15.0

    with client.application.app_context():
        refreshed_active = _db.session.get(Order, active_order_id)
        assert refreshed_active.status == STATUS_REJECTED

        # Стол реально освобождён.
        assert TableGroup.query.filter_by(club_id=club.club_id, table_no=23).first() is None
        assert TableGroupMember.query.filter_by(club_id=club.club_id, table_no=23).count() == 0

    # Следующая компания может тут же занять тот же стол и снова стать
    # админом — именно это чинит корневой баг "зависшего" стола.
    new_session = _session(client, club.club_id, table_no=23)
    assert new_session["table_group_status"] == "admin"


def test_approve_second_time_is_already_decided(client, db, club, kj):
    admin_session = _session(client, club.club_id, table_no=24)
    req = client.post(
        "/api/guest/table-group/request-close", headers=_headers(admin_session["token"]),
    ).get_json()["data"]

    first = client.put(f"/api/kj/table-close-requests/{req['id']}/approve", json={}, headers=kj["headers"])
    assert first.status_code == 200

    second = client.put(f"/api/kj/table-close-requests/{req['id']}/approve", json={}, headers=kj["headers"])
    assert second.status_code == 409
    assert second.get_json()["error"] == "ALREADY_DECIDED"


# --- Отклонение KJ — стол остаётся как есть ---

def test_reject_leaves_table_group_untouched(client, db, club, kj):
    admin_session = _session(client, club.club_id, table_no=25)
    req = client.post(
        "/api/guest/table-group/request-close", headers=_headers(admin_session["token"]),
    ).get_json()["data"]

    resp = client.put(f"/api/kj/table-close-requests/{req['id']}/reject", headers=kj["headers"])
    assert resp.status_code == 200
    assert resp.get_json()["data"]["status"] == "rejected"

    with client.application.app_context():
        assert TableGroup.query.filter_by(club_id=club.club_id, table_no=25).first() is not None

    # Стол всё ещё рабочий — можно заказывать как ни в чём не бывало.
    order_resp = client.post(
        "/api/guest/order", json={"song_title": "После отказа"}, headers=_headers(admin_session["token"]),
    )
    assert order_resp.status_code == 201


# --- hide_receipt: чек считается всегда, но раздаётся гостям только если не скрыт ---

def test_hide_receipt_suppresses_delivery_to_guest(client, db, club, kj):
    admin_session = _session(client, club.club_id, table_no=26)
    req = client.post(
        "/api/guest/table-group/request-close", headers=_headers(admin_session["token"]),
    ).get_json()["data"]

    resp = client.put(
        f"/api/kj/table-close-requests/{req['id']}/approve",
        json={"hide_receipt": True}, headers=kj["headers"],
    )
    assert resp.status_code == 200
    # Чек всё равно посчитан и сохранён для истории.
    assert resp.get_json()["data"]["request"]["receipt"] is not None
    assert resp.get_json()["data"]["request"]["hide_receipt"] is True

    me = _me(client, admin_session["token"])
    assert me["table_close_receipt"] is None

    with client.application.app_context():
        stored = _db.session.get(TableCloseRequest, req["id"])
        assert stored.status == STATUS_TABLE_CLOSE_APPROVED
        assert stored.receipt_json is not None


def test_visible_receipt_delivered_to_guest_via_me(client, db, club, kj):
    admin_session = _session(client, club.club_id, table_no=27)
    req = client.post(
        "/api/guest/table-group/request-close", headers=_headers(admin_session["token"]),
    ).get_json()["data"]

    client.put(
        f"/api/kj/table-close-requests/{req['id']}/approve",
        json={"hide_receipt": False}, headers=kj["headers"],
    )

    me = _me(client, admin_session["token"])
    assert me["table_close_receipt"] is not None
    assert me["table_close_receipt"]["table_no"] == 27
    # Групповой стол при этом уже удалён — статус закономерно "not_joined".
    assert me["table_group_status"] == "not_joined"


# --- Список ожидающих заявок в KJ Panel — только своего клуба, только pending ---

def test_list_pending_requests_scoped_to_own_club(client, db, club, other_club, kj):
    admin_session = _session(client, club.club_id, table_no=28)
    client.post("/api/guest/table-group/request-close", headers=_headers(admin_session["token"]))

    resp = client.get(f"/api/kj/table-close-requests/{club.club_id}", headers=kj["headers"])
    assert resp.status_code == 200
    data = resp.get_json()["data"]
    assert len(data) == 1
    assert data[0]["table_no"] == 28

    denied = client.get(f"/api/kj/table-close-requests/{other_club.club_id}", headers=kj["headers"])
    assert denied.status_code == 403
    assert denied.get_json()["error"] == "FORBIDDEN"
