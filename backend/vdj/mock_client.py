import itertools
import threading
from typing import Optional

from vdj.base import VDJQueueItem, VirtualDJClient, VirtualDJError


class MockVirtualDJClient(VirtualDJClient):
    """
    Рабочая имитация VirtualDJ для разработки и тестов (ТЗ п.16: пока реальный
    протокол не согласован, нельзя ни блокировать остальную разработку, ни
    выдумывать несуществующий API). Хранит очередь в памяти процесса.

    Поддерживает принудительный сбой через force_failure(True) — используется
    в тесте "Ошибка VirtualDJ" (ТЗ п.42, тест 4).
    """

    _id_counter = itertools.count(1)

    def __init__(self):
        self._queue: dict[str, VDJQueueItem] = {}
        self._lock = threading.Lock()
        self._force_failure = False

    def force_failure(self, value: bool = True):
        self._force_failure = value

    def add_to_queue(self, song_title: str, artist: Optional[str], table_no: Optional[int]) -> str:
        if self._force_failure:
            raise VirtualDJError("VirtualDJ недоступен (симуляция сбоя)")
        with self._lock:
            item_id = f"mock-{next(self._id_counter)}"
            self._queue[item_id] = VDJQueueItem(
                vdj_item_id=item_id, song_title=song_title, artist=artist, table_no=table_no
            )
            return item_id

    def remove_from_queue(self, vdj_item_id: str) -> None:
        with self._lock:
            self._queue.pop(vdj_item_id, None)

    def get_queue(self) -> list[VDJQueueItem]:
        with self._lock:
            return list(self._queue.values())

    def get_current_song(self) -> Optional[VDJQueueItem]:
        with self._lock:
            items = list(self._queue.values())
            return items[0] if items else None
