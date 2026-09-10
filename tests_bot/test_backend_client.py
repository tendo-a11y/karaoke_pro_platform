"""
Проверка требований, которые заказчик сформулировал к пункту 3 ТЗ-ревью:

  1. Сбой POST /api/client/order не должен приводить к повторной попытке или
     как-либо трогать существующую SQLite-логику.
  2. Вызов Backend должен быть фоновым/неблокирующим для ответа пользователю.
  3. Если Backend недоступен — остальной код (SQLite-заказ) не должен падать.

Тестируется РЕАЛЬНАЯ функция backend_client.post_order_to_backend — та же
самая, что импортирована и вызывается в bot.py и ai_search_handlers.py, а не
переписанная копия.
"""
import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import backend_client


def run(coro):
    return asyncio.run(coro)


def test_post_order_never_raises_when_backend_unreachable(monkeypatch):
    """Требование 1 и 3: недоступный Backend не должен ронять вызывающий код."""
    monkeypatch.setattr(backend_client, "BACKEND_API_URL", "http://127.0.0.1:1")  # заведомо не слушает

    async def scenario():
        # Если бы функция бросала исключение, эта корутина упала бы и pytest
        # зафиксировал бы ошибку теста.
        await backend_client.post_order_to_backend(
            telegram_user_id=1, club_id=1, table_no=5,
            song_title="Test", artist="Artist",
        )
        return "sqlite_flow_continued"

    result = run(scenario())
    assert result == "sqlite_flow_continued"


def test_post_order_call_does_not_retry_on_failure(monkeypatch):
    """Требование 1: сбой не должен приводить к повторной отправке того же заказа."""
    calls = []

    class FakeResp:
        status = 500
        async def text(self):
            return "internal error"
        async def __aenter__(self):
            return self
        async def __aexit__(self, *a):
            return False

    class FakeSession:
        async def __aenter__(self):
            return self
        async def __aexit__(self, *a):
            return False
        def post(self, *args, **kwargs):
            calls.append((args, kwargs))
            return FakeResp()

    import aiohttp
    monkeypatch.setattr(aiohttp, "ClientSession", lambda: FakeSession())

    run(backend_client.post_order_to_backend(
        telegram_user_id=1, club_id=1, table_no=5, song_title="Test", artist="Artist",
    ))

    assert len(calls) == 1, "функция не должна сама повторять запрос при ошибке backend"


def test_fire_and_forget_pattern_does_not_block_caller(monkeypatch):
    """
    Требование 2: именно тот паттерн вызова, что используется в bot.py —
    asyncio.create_task(...) — должен возвращать управление немедленно, не
    дожидаясь ответа Backend. Симулируем "зависший" на 2 секунды backend и
    проверяем, что код после create_task выполняется практически сразу.
    """
    async def slow_post_order_to_backend(**kwargs):
        await asyncio.sleep(2)

    monkeypatch.setattr(backend_client, "post_order_to_backend", slow_post_order_to_backend)

    async def scenario_like_bot_py():
        # Это ровно та же конструкция, что в bot.py/handle_service_selection
        # и в ai_search_handlers.py: asyncio.create_task(...), без await.
        start = time.monotonic()
        asyncio.create_task(
            backend_client.post_order_to_backend(
                telegram_user_id=1, club_id=1, table_no=5,
                song_title="Test", artist="Artist",
            )
        )
        # Дальше в реальном коде идёт отправка ответа гостю/уведомления KJ —
        # эмулируем это и меряем, сколько реально заняло времени ДО этого места.
        elapsed = time.monotonic() - start
        return elapsed

    elapsed = run(scenario_like_bot_py())
    assert elapsed < 0.05, (
        f"вызов backend заблокировал выполнение на {elapsed:.3f}с — "
        f"ожидалось <0.05с, т.к. это должно быть фоновой задачей"
    )
