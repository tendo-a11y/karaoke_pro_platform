"""
Мост к VirtualDJ, который физически стоит на компьютере KJ.

Контекст (обсуждали с заказчиком отдельно от буквы ТЗ): Backend — единая
централизованная система (ТЗ п.4, п.31, п.25 — мультиклубность), обычно
развёрнутая не в клубе, а в облаке/на своём сервере. VirtualDJ — локальная
программа на компьютере KJ, без доступа из интернета и без статического IP.
Поэтому Backend не может сам "достучаться" до VirtualDJ напрямую — вместо
этого маленькая программа-мост (vdj_bridge/agent.py) запускается на том же
компьютере, что и VirtualDJ, и САМА открывает соединение НАРУЖУ, к Backend
(WebSocket, namespace "/bridge"). Это стандартный обход NAT/файрвола клуба:
исходящие соединения почти всегда разрешены, входящие — нет.

Что этот файл НЕ решает: какой именно локальный протокол использовать, чтобы
сам мост уже на месте говорил с VirtualDJ (VDJScript, локальный сокет,
чтение файла плейлиста и т.п.) — это по-прежнему открытый вопрос ТЗ п.16,
требующий доступа к реально установленному VirtualDJ. Здесь решается только
СЕТЕВАЯ ДОСТИЖИМОСТЬ моста из централизованного Backend, а не протокол моста
с VirtualDJ.
"""
from typing import Optional

from extensions import socketio
from vdj.base import VDJQueueItem, VirtualDJClient, VirtualDJError
from vdj.bridge_registry import registry

DEFAULT_TIMEOUT = 15.0  # компьютер KJ может на секунду затупить — даём запас


class BridgeVirtualDJClient(VirtualDJClient):
    def __init__(self, club_id: int, timeout: float = DEFAULT_TIMEOUT):
        self.club_id = club_id
        self.timeout = timeout

    def _room(self) -> str:
        return f"bridge_club_{self.club_id}"

    def _call(self, command: str, payload: dict) -> dict:
        request_id = registry.new_request_id()
        pending = registry.register(request_id)
        socketio.emit(
            "vdj_command",
            {"request_id": request_id, "command": command, **payload},
            room=self._room(),
            namespace="/bridge",
        )
        result = registry.wait(request_id, pending, self.timeout)
        if result is None:
            raise VirtualDJError(
                f"Компьютер KJ не ответил за {self.timeout:.0f}с — "
                f"мост offline или VirtualDJ не отвечает"
            )
        if result.get("error"):
            raise VirtualDJError(result["error"])
        return result

    def add_to_queue(self, song_title: str, artist: Optional[str], table_no: Optional[int]) -> str:
        result = self._call("add_to_queue", {
            "song_title": song_title, "artist": artist, "table_no": table_no,
        })
        item_id = result.get("vdj_item_id")
        if not item_id:
            raise VirtualDJError("Мост не вернул vdj_item_id при добавлении в очередь")
        return item_id

    def remove_from_queue(self, vdj_item_id: str) -> None:
        self._call("remove_from_queue", {"vdj_item_id": vdj_item_id})

    def get_queue(self) -> list[VDJQueueItem]:
        try:
            result = self._call("get_queue", {})
        except VirtualDJError:
            # Живая очередь — не критичная операция: если мост временно не
            # ответил, лучше показать пустую/старую очередь, чем уронить
            # запрос, из-за которого её спрашивают (например, после confirm).
            return []
        return [
            VDJQueueItem(
                vdj_item_id=i["vdj_item_id"], song_title=i.get("song_title", ""),
                artist=i.get("artist"), table_no=i.get("table_no"),
            )
            for i in result.get("items", [])
        ]

    def get_current_song(self) -> Optional[VDJQueueItem]:
        try:
            result = self._call("get_current_song", {})
        except VirtualDJError:
            return None
        item = result.get("item")
        if not item:
            return None
        return VDJQueueItem(
            vdj_item_id=item["vdj_item_id"], song_title=item.get("song_title", ""),
            artist=item.get("artist"), table_no=item.get("table_no"),
        )
