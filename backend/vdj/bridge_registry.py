"""
Реестр ожидающих ответа команд для моста VirtualDJ (см. bridge_client.py).

Backend отправляет команду мостику через WebSocket и должен СИНХРОННО (в
рамках одного HTTP-запроса KJ на подтверждение заказа) дождаться результата
или таймаута — чтобы весь остальной код (services/vdj_service.py, тесты,
формат ответа API) не менялся и не знал, что VirtualDJ теперь не рядом, а на
другом конце сети. Соответствие команда->ответ — по request_id (uuid),
не по order_id, чтобы несколько одновременных команд одному клубу не путались.
"""
import threading
import uuid
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class _PendingRequest:
    event: threading.Event = field(default_factory=threading.Event)
    result: Optional[dict] = None


class BridgeRequestRegistry:
    def __init__(self):
        self._lock = threading.Lock()
        self._pending: dict[str, _PendingRequest] = {}

    def new_request_id(self) -> str:
        return uuid.uuid4().hex

    def register(self, request_id: str) -> _PendingRequest:
        pending = _PendingRequest()
        with self._lock:
            self._pending[request_id] = pending
        return pending

    def resolve(self, request_id: str, result: dict) -> bool:
        """Вызывается обработчиком, когда мост прислал ответ. Возвращает
        False, если такого request_id уже нет (например, истёк таймаут)."""
        with self._lock:
            pending = self._pending.get(request_id)
        if pending is None:
            return False
        pending.result = result
        pending.event.set()
        return True

    def wait(self, request_id: str, pending: _PendingRequest, timeout: float) -> Optional[dict]:
        try:
            got_result = pending.event.wait(timeout)
            return pending.result if got_result else None
        finally:
            with self._lock:
                self._pending.pop(request_id, None)


registry = BridgeRequestRegistry()
