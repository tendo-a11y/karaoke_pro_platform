"""
Тесты для трёх доработок экрана "Живая очередь VirtualDJ" (доп. ТЗ "KJ Pro",
запрос пользователя после того, как стало непонятно, куда перетаскивать
карточки заказов): смена стола, смена категории и удаление уже поставленной
в очередь песни. Перестановка порядка внутри самой очереди VirtualDJ сюда
намеренно не входит — отложена отдельно (в реальном VirtualDJ-мосте для неё
пока не найдена рабочая команда, см. vdj_bridge/driver.py).

Смена стола/категории — чисто наши поля Order.table_no/service_id,
VirtualDJ о них не знает и не участвует. Удаление, в отличие от старого
бота (handlers/kj.py::order_delete_confirmed + db.refund_vip_for_order()),
не требует отдельного возврата денег: в новой архитектуре списание
происходит только при ЗАВЕРШЕНИИ песни (services/billing_service.py), а
удалённая из очереди песня никогда не завершится — значит, с неё и так
ничего не спишется.
"""
from datetime import datetime, timezone

from extensions import db as _db
from models import STATUS_PENDING, STATUS_QUEUED, STATUS_REJECTED, Order, Service
from vdj import get_vdj_client


def _headers(token):
    return {"Authorization": f"Bearer {token}"}


def _make_queued_order(club_id, table_no=5, vdj_item_id="fixed-id", service_id=None,
                        song_title="Песня", artist="Артист", channel="webapp", telegram_user_id=1):
    order = Order(
        telegram_user_id=telegram_user_id,
        club_id=club_id,
        table_no=table_no,
        song_title=song_title,
        artist=artist,
        status=STATUS_QUEUED,
        vdj_item_id=vdj_item_id,
        service_id=service_id,
        channel=channel,
        queued_at=datetime.now(timezone.utc),
    )
    _db.session.add(order)
    _db.session.commit()
    return order


# --- Смена стола ---

def test_update_table_requires_auth(client, db, club):
    order = _make_queued_order(club.club_id)
    resp = client.put(f"/api/kj/order/{order.id}/table", json={"table_no": 3})
    assert resp.status_code == 401


def test_update_table_success(client, db, club, kj):
    order = _make_queued_order(club.club_id, table_no=1)
    resp = client.put(f"/api/kj/order/{order.id}/table", json={"table_no": 9}, headers=_headers(kj["token"]))
    assert resp.status_code == 200
    assert resp.get_json()["data"]["table_no"] == 9
    assert _db.session.get(Order, order.id).table_no == 9


def test_update_table_can_clear_to_null(client, db, club, kj):
    order = _make_queued_order(club.club_id, table_no=4)
    resp = client.put(f"/api/kj/order/{order.id}/table", json={"table_no": None}, headers=_headers(kj["token"]))
    assert resp.status_code == 200
    assert resp.get_json()["data"]["table_no"] is None


def test_update_table_rejects_non_positive(client, db, club, kj):
    order = _make_queued_order(club.club_id)
    resp = client.put(f"/api/kj/order/{order.id}/table", json={"table_no": 0}, headers=_headers(kj["token"]))
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "VALIDATION_ERROR"


def test_update_table_bounded_by_club_table_count(client, db, club, kj):
    club.table_count = 5
    db.session.commit()
    order = _make_queued_order(club.club_id)

    resp = client.put(f"/api/kj/order/{order.id}/table", json={"table_no": 6}, headers=_headers(kj["token"]))
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "TABLE_OUT_OF_RANGE"

    resp2 = client.put(f"/api/kj/order/{order.id}/table", json={"table_no": 5}, headers=_headers(kj["token"]))
    assert resp2.status_code == 200


def test_update_table_forbidden_for_other_clubs_order(client, db, club, other_club, kj, other_kj):
    order = _make_queued_order(other_club.club_id)
    resp = client.put(f"/api/kj/order/{order.id}/table", json={"table_no": 2}, headers=_headers(kj["token"]))
    assert resp.status_code == 403


def test_update_table_rejects_when_order_not_queued(client, db, club, kj):
    order = _make_queued_order(club.club_id)
    order.status = STATUS_PENDING
    db.session.commit()

    resp = client.put(f"/api/kj/order/{order.id}/table", json={"table_no": 2}, headers=_headers(kj["token"]))
    assert resp.status_code == 409
    assert resp.get_json()["error"] == "ORDER_NOT_QUEUED"


def test_update_table_not_found(client, db, club, kj):
    resp = client.put("/api/kj/order/999999/table", json={"table_no": 2}, headers=_headers(kj["token"]))
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "ORDER_NOT_FOUND"


# --- Смена категории ---

def test_update_category_success(client, db, club, kj):
    service = Service(club_id=club.club_id, name="VIP", price=100)
    db.session.add(service)
    db.session.commit()
    order = _make_queued_order(club.club_id)

    resp = client.put(
        f"/api/kj/order/{order.id}/category", json={"service_id": service.id}, headers=_headers(kj["token"]),
    )
    assert resp.status_code == 200
    assert resp.get_json()["data"]["service_id"] == service.id
    assert _db.session.get(Order, order.id).service_id == service.id


def test_update_category_can_clear_to_null(client, db, club, kj):
    service = Service(club_id=club.club_id, name="VIP", price=100)
    db.session.add(service)
    db.session.commit()
    order = _make_queued_order(club.club_id, service_id=service.id)

    resp = client.put(
        f"/api/kj/order/{order.id}/category", json={"service_id": None}, headers=_headers(kj["token"]),
    )
    assert resp.status_code == 200
    assert resp.get_json()["data"]["service_id"] is None


def test_update_category_rejects_unknown_service(client, db, club, kj):
    order = _make_queued_order(club.club_id)
    resp = client.put(
        f"/api/kj/order/{order.id}/category", json={"service_id": 999999}, headers=_headers(kj["token"]),
    )
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "SERVICE_NOT_FOUND"


def test_update_category_rejects_service_from_other_club(client, db, club, other_club, kj):
    other_service = Service(club_id=other_club.club_id, name="Чужая категория", price=50)
    db.session.add(other_service)
    db.session.commit()
    order = _make_queued_order(club.club_id)

    resp = client.put(
        f"/api/kj/order/{order.id}/category", json={"service_id": other_service.id}, headers=_headers(kj["token"]),
    )
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "SERVICE_NOT_FOUND"


def test_update_category_forbidden_for_other_clubs_order(client, db, club, other_club, kj, other_kj):
    order = _make_queued_order(other_club.club_id)
    resp = client.put(
        f"/api/kj/order/{order.id}/category", json={"service_id": None}, headers=_headers(kj["token"]),
    )
    assert resp.status_code == 403


def test_update_category_rejects_when_order_not_queued(client, db, club, kj):
    order = _make_queued_order(club.club_id)
    order.status = STATUS_PENDING
    db.session.commit()

    resp = client.put(
        f"/api/kj/order/{order.id}/category", json={"service_id": None}, headers=_headers(kj["token"]),
    )
    assert resp.status_code == 409
    assert resp.get_json()["error"] == "ORDER_NOT_QUEUED"


# --- Удаление песни из очереди ---

def test_remove_from_queue_requires_auth(client, db, club, app):
    with app.app_context():
        vdj = get_vdj_client(club.club_id)
        vdj_item_id = vdj.add_to_queue("Песня", "Артист", table_no=1)
    resp = client.delete(f"/api/vdj/queue/{vdj_item_id}")
    assert resp.status_code == 401


def test_remove_from_queue_actually_removes_from_vdj_and_rejects_order(client, db, club, kj, app):
    with app.app_context():
        vdj = get_vdj_client(club.club_id)
        vdj_item_id = vdj.add_to_queue("Удаляемая песня", "Артист", table_no=6)
    order = _make_queued_order(club.club_id, table_no=6, vdj_item_id=vdj_item_id, song_title="Удаляемая песня")

    resp = client.delete(f"/api/vdj/queue/{vdj_item_id}", headers=_headers(kj["token"]))
    assert resp.status_code == 200
    data = resp.get_json()["data"]
    assert data["removed"] is True
    assert data["order"]["id"] == order.id
    assert data["order"]["status"] == STATUS_REJECTED

    with app.app_context():
        vdj = get_vdj_client(club.club_id)
        assert not any(i.vdj_item_id == vdj_item_id for i in vdj.get_queue())

    stored = _db.session.get(Order, order.id)
    assert stored.status == STATUS_REJECTED
    assert stored.rejected_at is not None


def test_remove_from_queue_without_matching_order_still_works(client, db, club, kj, app):
    """Песня, добавленная прямо в VirtualDJ в обход Backend (см.
    get_kj_queue_view) — order=None в ответе, но саму песню из VirtualDJ
    всё равно нужно убрать."""
    with app.app_context():
        vdj = get_vdj_client(club.club_id)
        vdj_item_id = vdj.add_to_queue("Ручная песня", None, table_no=None)

    resp = client.delete(f"/api/vdj/queue/{vdj_item_id}", headers=_headers(kj["token"]))
    assert resp.status_code == 200
    data = resp.get_json()["data"]
    assert data["removed"] is True
    assert data["order"] is None

    with app.app_context():
        vdj = get_vdj_client(club.club_id)
        assert not any(i.vdj_item_id == vdj_item_id for i in vdj.get_queue())


def test_remove_from_queue_only_touches_own_clubs_order(client, db, club, other_club, kj, other_kj, app):
    """Тот же vdj_item_id "случайно" совпал у заказа другого клуба — удаление
    из СВОЕЙ очереди не должно менять статус чужого заказа (та же изоляция
    по club_id, что и everywhere в проекте, ТЗ п.24-25)."""
    with app.app_context():
        vdj = get_vdj_client(club.club_id)
        vdj_item_id = vdj.add_to_queue("Песня клуба", None, table_no=None)
    foreign_order = _make_queued_order(other_club.club_id, table_no=1, vdj_item_id=vdj_item_id)

    resp = client.delete(f"/api/vdj/queue/{vdj_item_id}", headers=_headers(kj["token"]))
    assert resp.status_code == 200
    assert resp.get_json()["data"]["order"] is None

    assert _db.session.get(Order, foreign_order.id).status == STATUS_QUEUED
