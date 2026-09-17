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

2026-09-17 (панель обзора для KJ — три индикатора: Гость↔KJ, KJ↔VirtualDJ,
Мост↔VirtualDJ): раньше здесь хранилось только "мост подключён к Backend
или нет" — это средняя часть цепочки (сервер видит мост), но ничего не
говорило о том, видит ли САМ мост живую VirtualDJ на компьютере KJ. Мост
может быть подключён к серверу (WebSocket открыт), но VirtualDJ на этом
компьютере выключена/не отвечает — раньше это никак не было видно в KJ
Panel, KJ узнавал об этом только когда песня не появлялась в очереди.
Теперь мост сам периодически проверяет VirtualDJ (см. vdj_bridge_app.py::
_queue_refresh_loop) и присылает результат событием "bridge_vdj_status" —
handle_bridge_vdj_status в sockets.py кладёт его сюда через
mark_vdj_reachable. vdj_reachable может быть: True/False (мост проверял и
получил ответ/не получил), None (мост подключён, но ещё ни разу не успел
проверить — например, первые секунды после connect).
"""
import threading
from datetime import datetime, timezone

_lock = threading.Lock()
# sid -> {"club_id": int, "connected_at": datetime, "vdj_reachable": bool | None}
_connected: dict[str, dict] = {}


def mark_connected(sid: str, club_id: int) -> None:
    with _lock:
        _connected[sid] = {
            "club_id": club_id,
            "connected_at": datetime.now(timezone.utc),
            # None — мост только что подключился, ещё ни разу не отчитался
            # о состоянии VirtualDJ (первый отчёт придёт из
            # _queue_refresh_loop в течение QUEUE_REFRESH_SECONDS).
            "vdj_reachable": None,
        }


def mark_disconnected(sid: str) -> int | None:
    """Убирает sid из реестра. Возвращает club_id, которому принадлежал этот
    sid, чтобы вызывающий код (sockets.py) знал, в чью комнату клуба
    разослать обновлённый статус — сам disconnect-обработчик Socket.IO этого
    не знает, у него есть только sid."""
    with _lock:
        entry = _connected.pop(sid, None)
    return entry["club_id"] if entry else None


def mark_vdj_reachable(sid: str, reachable: bool) -> int | None:
    """Мост (по этому sid) отчитался, видит ли он сейчас VirtualDJ.
    Возвращает club_id для рассылки в sockets.py — как и mark_disconnected,
    сам обработчик события знает только sid. None, если sid не значится
    подключённым мостом (например, отчёт пришёл после разрыва — просто
    игнорируем, рассылать нечего)."""
    with _lock:
        entry = _connected.get(sid)
        if entry is None:
            return None
        entry["vdj_reachable"] = reachable
        return entry["club_id"]


def is_connected(club_id: int) -> bool:
    """Хотя бы одно текущее подключение моста для этого клуба."""
    with _lock:
        return any(e["club_id"] == club_id for e in _connected.values())


def vdj_reachable(club_id: int) -> bool | None:
    """Последний известный результат проверки VirtualDJ этим клубом. None —
    моста сейчас нет вообще, либо он подключён, но ещё не успел ни разу
    проверить (см. mark_connected)."""
    with _lock:
        for e in _connected.values():
            if e["club_id"] == club_id:
                return e["vdj_reachable"]
    return None


def connected_since(club_id: int):
    """Момент самого раннего из текущих подключений моста этого клуба (если
    их несколько — например, идёт переподключение) — None, если моста
    сейчас нет вообще."""
    with _lock:
        timestamps = [e["connected_at"] for e in _connected.values() if e["club_id"] == club_id]
    return min(timestamps) if timestamps else None
