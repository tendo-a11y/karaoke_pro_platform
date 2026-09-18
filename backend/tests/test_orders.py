"""
Тесты соответствуют сценариям из ТЗ, раздел 42 "ТЕСТИРОВАНИЕ":
  1. Обычный заказ            -> test_guest_order_is_visible_to_kj
  2. Подтверждение             -> test_confirm_does_not_touch_virtualdj
  3. Двойное нажатие           -> test_double_confirm_returns_409 /
                                   test_concurrent_double_confirm_queues_once
  4. Завершение (KJ отыграл)   -> test_complete_order_frees_status /
                                   test_complete_requires_queued_status /
                                   test_kj_cannot_complete_other_club_order
  5. Несколько заказов         -> test_multiple_orders_per_table_all_visible
  6. Несколько клубов          -> test_kj_cannot_see_other_club_orders /
                                   test_kj_cannot_confirm_other_club_order
  7. Отклонение                -> test_reject_order
  8. Перезапуск (устойчивость) -> test_orders_persist_in_postgres_across_sessions

Плюс базовая защита эндпоинтов (401/400) и защита от неавторизованного
подтверждения токеном не-KJ.

2026-09-18, запрос пользователя: подтверждение заказа больше не передаёт
песню в VirtualDJ само (мост часто недоступен, а KJ и так предпочитает
ставить песню в плеер вручную) — сценарий 4 "Ошибка VirtualDJ" при
подтверждении (test_vdj_failure_sets_error_status) для confirm_order()
больше не применим и удалён; вместо него здесь тесты на новую кнопку
"Готово" (complete_order()), которая явно освобождает место на карточке
стола вместо прежней реконсиляции с живой очередью VirtualDJ. См. подробный
докстринг confirm_order()/complete_order() в services/vdj_service.py.
"""
import threading

from app import create_app
from config import TestingConfig
from extensions import db as _db
from models import STATUS_COMPLETED, STATUS_PENDING, STATUS_QUEUED, STATUS_REJECTED, Order
from tests.conftest import create_order


def test_create_order_requires_bot_token(client, club):
    resp = client.post("/api/client/order", json={
        "telegram_user_id": 1, "club_id": club.club_id, "table_no": 1, "song_title": "X",
    })
    assert resp.status_code == 401
    assert resp.get_json()["error"] == "UNAUTHORIZED"


def test_create_order_validates_payload(client, club, bot_headers):
    resp = client.post("/api/client/order", json={"club_id": club.club_id}, headers=bot_headers)
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "VALIDATION_ERROR"


def test_create_order_rejects_unknown_club(client, bot_headers):
    resp = create_order(client, bot_headers, club_id=999)
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "CLUB_NOT_FOUND"


# --- Тест 1: обычный заказ ---
def test_guest_order_is_visible_to_kj(client, club, kj, bot_headers):
    resp = create_order(client, bot_headers, club_id=club.club_id, table_no=5)
    assert resp.status_code == 201
    body = resp.get_json()["data"]
    assert body["status"] == STATUS_PENDING
    assert body["table_no"] == 5

    listing = client.get(f"/api/kj/orders/{club.club_id}", headers=kj["headers"])
    assert listing.status_code == 200
    orders = listing.get_json()["data"]
    assert len(orders) == 1
    assert orders[0]["id"] == body["id"]


# --- Тест 2: подтверждение ---
def test_confirm_does_not_touch_virtualdj(client, club, kj, bot_headers, monkeypatch):
    """
    2026-09-18: подтверждение заказа сразу переводит его в STATUS_QUEUED
    БЕЗ обращения к VirtualDJ — vdj_item_id остаётся пустым, а заказ не
    появляется в живой очереди VirtualDJ (GET /api/kj/queue/<club_id>).
    KJ сам решает, когда поставить песню в плеер, и сам же освобождает
    место на карточке кнопкой "Готово" (см. test_complete_order_frees_status
    ниже) — это больше не делает VirtualDJ автоматически.
    """
    notified = []
    monkeypatch.setattr("services.vdj_service.notify_guest", lambda guest_id, text: notified.append((guest_id, text)))

    order_id = create_order(client, bot_headers, club_id=club.club_id).get_json()["data"]["id"]

    resp = client.put(f"/api/kj/order/{order_id}/confirm", headers=kj["headers"])
    assert resp.status_code == 200
    data = resp.get_json()["data"]
    assert data["status"] == STATUS_QUEUED
    assert not data["vdj_item_id"]

    queue_resp = client.get(f"/api/kj/queue/{club.club_id}", headers=kj["headers"])
    queue = queue_resp.get_json()["data"]
    assert queue == []

    # Гость получает сообщение о том, что заказ принят (запрос пользователя:
    # "при принятие заказа идет только сообщение тому кто заказал").
    assert len(notified) == 1
    assert "принят" in notified[0][1].lower()


# --- Тест 3a: последовательное двойное нажатие ---
def test_double_confirm_returns_409(client, club, kj, bot_headers):
    order_id = create_order(client, bot_headers, club_id=club.club_id).get_json()["data"]["id"]

    first = client.put(f"/api/kj/order/{order_id}/confirm", headers=kj["headers"])
    second = client.put(f"/api/kj/order/{order_id}/confirm", headers=kj["headers"])

    assert first.status_code == 200
    assert second.status_code == 409
    assert second.get_json()["error"] == "ORDER_ALREADY_PROCESSED"


# --- Тест 3b: настоящая гонка (два потока подтверждают один и тот же заказ одновременно) ---
def test_concurrent_double_confirm_queues_once(app, club, kj, bot_headers, client):
    """
    2026-09-18: раньше эта гонка нарочно расширялась искусственной задержкой
    внутри замоканного vdj.add_to_queue(), чтобы точно поймать оба потока в
    окне между CAS-переходом pending->processing и вызовом VirtualDJ.
    Теперь confirm_order() вообще не обращается к VirtualDJ — сама атомарная
    защита (UPDATE ... WHERE status='pending', см. confirm_order()) не
    зависит от VDJ и её достаточно проверить без искусственной задержки.
    """
    order_id = create_order(client, bot_headers, club_id=club.club_id).get_json()["data"]["id"]

    results = []

    def hit_confirm():
        c = app.test_client()
        r = c.put(f"/api/kj/order/{order_id}/confirm", headers=kj["headers"])
        results.append(r.status_code)

    threads = [threading.Thread(target=hit_confirm) for _ in range(5)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()

    assert results.count(200) == 1, f"ожидался ровно один успех, получили {results}"
    assert results.count(409) == 4

    with app.app_context():
        order = _db.session.get(Order, order_id)
        assert order.status == STATUS_QUEUED


# --- Тест 4: завершение заказа (KJ сам отыграл песню) ---
def test_complete_order_frees_status(client, club, kj, bot_headers):
    """
    2026-09-18: подтверждение больше не ставит песню в VirtualDJ само (см.
    test_confirm_does_not_touch_virtualdj выше) — единственный способ
    убрать принятый заказ с карточки стола теперь явная кнопка "Готово"
    (PUT /api/kj/order/<id>/complete), а не сверка с живой очередью
    VirtualDJ.
    """
    order_id = create_order(client, bot_headers, club_id=club.club_id).get_json()["data"]["id"]
    client.put(f"/api/kj/order/{order_id}/confirm", headers=kj["headers"])

    resp = client.put(f"/api/kj/order/{order_id}/complete", headers=kj["headers"])
    assert resp.status_code == 200
    data = resp.get_json()["data"]
    assert data["status"] == STATUS_COMPLETED
    assert data["completion_source"] == "manual"


def test_complete_requires_queued_status(client, club, kj, bot_headers):
    order_id = create_order(client, bot_headers, club_id=club.club_id).get_json()["data"]["id"]

    # Заказ ещё STATUS_PENDING (не подтверждён) — "Готово" ничего не меняет.
    resp = client.put(f"/api/kj/order/{order_id}/complete", headers=kj["headers"])
    assert resp.status_code == 409
    assert resp.get_json()["error"] == "ORDER_ALREADY_PROCESSED"


def test_kj_cannot_complete_other_club_order(client, club, other_club, kj, other_kj, bot_headers):
    order_id = create_order(client, bot_headers, club_id=other_club.club_id).get_json()["data"]["id"]
    client.put(f"/api/kj/order/{order_id}/confirm", headers=other_kj["headers"])

    resp = client.put(f"/api/kj/order/{order_id}/complete", headers=kj["headers"])
    assert resp.status_code == 403
    assert resp.get_json()["error"] == "FORBIDDEN"


# --- Тест 5: несколько заказов по разным столам ---
def test_multiple_orders_per_table_all_visible(client, club, kj, bot_headers):
    for table_no, count in ((1, 3), (2, 2), (5, 5)):
        for i in range(count):
            create_order(client, bot_headers, club_id=club.club_id, table_no=table_no,
                         song_title=f"Song {table_no}-{i}")

    listing = client.get(f"/api/kj/orders/{club.club_id}", headers=kj["headers"])
    orders = listing.get_json()["data"]
    assert len(orders) == 10
    by_table = {}
    for o in orders:
        by_table.setdefault(o["table_no"], 0)
        by_table[o["table_no"]] += 1
    assert by_table == {1: 3, 2: 2, 5: 5}


# --- Тест 6: несколько клубов, изоляция ---
def test_kj_cannot_see_other_club_orders(client, club, other_club, kj, other_kj, bot_headers):
    create_order(client, bot_headers, club_id=club.club_id, telegram_user_id=1)
    create_order(client, bot_headers, club_id=other_club.club_id, telegram_user_id=2)

    club1_orders = client.get(f"/api/kj/orders/{club.club_id}", headers=kj["headers"]).get_json()["data"]
    club2_orders = client.get(f"/api/kj/orders/{other_club.club_id}", headers=other_kj["headers"]).get_json()["data"]

    assert len(club1_orders) == 1
    assert len(club2_orders) == 1

    # KJ клуба 1 не может прочитать заказы клуба 2, даже подставив его id в URL
    denied = client.get(f"/api/kj/orders/{other_club.club_id}", headers=kj["headers"])
    assert denied.status_code == 403
    assert denied.get_json()["error"] == "FORBIDDEN"


def test_kj_cannot_confirm_other_club_order(client, club, other_club, kj, other_kj, bot_headers):
    order_id = create_order(client, bot_headers, club_id=other_club.club_id).get_json()["data"]["id"]
    resp = client.put(f"/api/kj/order/{order_id}/confirm", headers=kj["headers"])
    assert resp.status_code == 403
    assert resp.get_json()["error"] == "FORBIDDEN"


# --- Тест 7: отклонение ---
def test_reject_order(client, club, kj, bot_headers):
    order_id = create_order(client, bot_headers, club_id=club.club_id).get_json()["data"]["id"]
    resp = client.put(f"/api/kj/order/{order_id}/reject", headers=kj["headers"])
    assert resp.status_code == 200
    assert resp.get_json()["data"]["status"] == STATUS_REJECTED

    # отклонённый заказ нельзя задним числом подтвердить
    confirm_after_reject = client.put(f"/api/kj/order/{order_id}/confirm", headers=kj["headers"])
    assert confirm_after_reject.status_code == 409


# --- Тест 8: устойчивость к перезапуску backend-процесса ---
# Заказы лежат в Postgres, а не в памяти процесса — открываем данные в новой
# сессии/приложении, эмулируя то, что видел бы только что перезапущенный backend.
def test_orders_persist_in_postgres_across_sessions(client, club, kj, bot_headers):
    order_id = create_order(client, bot_headers, club_id=club.club_id).get_json()["data"]["id"]
    client.put(f"/api/kj/order/{order_id}/confirm", headers=kj["headers"])

    fresh_app = create_app(TestingConfig)
    with fresh_app.app_context():
        reloaded = _db.session.get(Order, order_id)
        assert reloaded is not None
        assert reloaded.status == STATUS_QUEUED


def test_inactive_kj_is_forbidden(client, club, kj, db):
    kj["operator"].is_active = False
    db.session.commit()
    resp = client.get(f"/api/kj/orders/{club.club_id}", headers=kj["headers"])
    assert resp.status_code == 403


def test_missing_token_is_unauthorized(client, club):
    resp = client.get(f"/api/kj/orders/{club.club_id}")
    assert resp.status_code == 401


def test_kj_me_returns_own_club(client, club, kj):
    resp = client.get("/api/kj/me", headers=kj["headers"])
    assert resp.status_code == 200
    data = resp.get_json()["data"]
    assert data["club_id"] == club.club_id
    assert data["club_name"] == club.name
