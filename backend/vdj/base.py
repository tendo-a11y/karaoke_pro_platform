from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


class VirtualDJError(Exception):
    """Поднимается, когда VirtualDJ недоступен или отклонил операцию (ТЗ п.18)."""


@dataclass
class VDJQueueItem:
    vdj_item_id: str
    song_title: str
    artist: Optional[str]
    table_no: Optional[int]


class VirtualDJClient(ABC):
    """
    Логический интерфейс интеграции с VirtualDJ (ТЗ п.16).

    ВАЖНО: реальный протокол подключения (HTTP REST у стороннего плагина,
    VDJScript через локальный сокет, экспорт/чтение плейлист-файла и т.п.)
    должен быть определён по фактически установленной версии и конфигурации
    VirtualDJ в клубе — в ТЗ прямо запрещено фиксировать непроверенный URL.
    Этот интерфейс — та точка расширения, за которой прячется конкретный
    механизм: остальной backend (routes, sockets, тесты) работает только
    через него и не изменится, когда появится реальный адаптер.
    """

    @abstractmethod
    def add_to_queue(self, song_title: str, artist: Optional[str], table_no: Optional[int]) -> str:
        """Добавляет трек в очередь VirtualDJ. Возвращает vdj_item_id.
        Бросает VirtualDJError при недоступности/отказе VDJ."""

    @abstractmethod
    def remove_from_queue(self, vdj_item_id: str) -> None:
        """Удаляет ранее добавленный элемент очереди (ТЗ п.20)."""

    @abstractmethod
    def get_queue(self) -> list[VDJQueueItem]:
        """Текущая очередь VirtualDJ (ТЗ п.21)."""

    @abstractmethod
    def get_current_song(self) -> Optional[VDJQueueItem]:
        """Трек, который сейчас играет, если есть."""
