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
    assert resp.status_code ==
