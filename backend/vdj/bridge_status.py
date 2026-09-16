"""
Живой статус подключения моста VirtualDJ к Backend (запрос пользователя
2026-09: "переключатель" для контроля из KJ Panel — светофор "мост
подключён/не подключён"). НЕ хранится в БД: это состояние самого текущего
процесса ("прямо сейчас есть открытый WebSocket от моста этого клуба или
нет"), а не что-то, что должно пережить перезапуск Backend — при рестарте
Backend все мосты и так переподключатся заново и снова зарегистрируются
здесь.

Хранится в памяти простым словарём sid -> club_id (по образцу
vdj/bridge_registry.py — тот же принцип "простое общее состояние одного
процесса", а не через БД/Redis). Это осознанно безопасно ровно потому, что
Backend этого проекта запускается как один-единственный процесс с одним
воркером (см. Procfile/Railway: `gunicorn --workers 1`, `async_mode=
"threading"` в extensions.py) — несколько экземпляров этого словаря в
разных процессах не появится и не разъедется в разное состояние.

sid, а не club_id, — ключ намеренно: у одного клуба физически может быть
несколько сессий подключения подряд (переподключение) до того, как старая
получит event "disconnect" от Socket.IO, а at Socket.IO disconnect-обработчик
(handle_bridge_disconnect в sockets.py) получает только request.sid, не
club_id, который был передан при connect — вот почему club_id нужно
"вспомнить" по sid именно отсюда.
"""
import threading
from datetime import datetime, timezone

_lock = threading.Lock()
_connected: dict[str, dict] = {}  # sid -> {"club_id": int, "connected_at": datetime}


def mark_connected(sid: str, club_id: int) -> None:
    with _lock:
        _connected[sid] = {"club_id": club_id, "connected_at": datetime.now(timezone.utc)}


def mark_disconnected(sid: str) -> int | None:
    """Убирает sid из реестра. Возвращает club_id, которому принадлежал этот
    sid, чтобы вызывающий код (sockets.py) знал, в чью комнату клуба
    разослать обновлённый статус — сам disconnect-обработчик Socket.IO этого
    не знает, у него есть только sid."""
    with _lock:
        entry = _connected.pop(sid, None)
    return entry["club_id"] if entry else None


def is_connected(club_id: int) -> bool:
    """Хотя бы одно текущее подключение моста для этого клуба."""
    with _lock:
        return any(e["club_id"] == club_id for e in _connected.values())


def connected_since(club_id: int):
    """Момент самого раннего из текущих подключений моста этого клуба (если
    их несколько — например, идёт переподключение) — None, если моста
    сейчас нет вообще."""
    with _lock:
        timestamps = [e["connected_at"] for e in _connected.values() if e["club_id"] == club_id]
    return min(timestamps) if timestamps else None
