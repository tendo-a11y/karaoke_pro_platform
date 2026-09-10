from typing import Optional

import requests

from vdj.base import VDJQueueItem, VirtualDJClient, VirtualDJError


class HttpVirtualDJClient(VirtualDJClient):
    """
    HTTP-адаптер к VirtualDJ. НЕ ПРОВЕРЕН на реальном VirtualDJ — ТЗ п.16 прямо
    запрещает фиксировать в ТЗ несуществующий/непроверенный URL, поэтому здесь
    задана лишь разумная по умолчанию форма запросов (VDJ_API_URL + REST-like
    маршруты), которую нужно свести с фактическим способом подключения на
    установленной у клуба версии VirtualDJ (родной REST-плагин, VDJScript
    через локальный сокет/командную строку, чтение M3U-плейлиста и т.д.)
    ПЕРЕД включением VDJ_ADAPTER=http в продакшене. Как только протокол
    известен — правится только этот файл, остальной backend не меняется.
    """

    def __init__(self, base_url: str, api_token: Optional[str], timeout: float = 5.0):
        if not base_url:
            raise ValueError("VDJ_API_URL не задан")
        self.base_url = base_url.rstrip("/")
        self.api_token = api_token
        self.timeout = timeout

    def _headers(self):
        headers = {"Content-Type": "application/json"}
        if self.api_token:
            headers["Authorization"] = f"Bearer {self.api_token}"
        return headers

    def add_to_queue(self, song_title: str, artist: Optional[str], table_no: Optional[int]) -> str:
        try:
            resp = requests.post(
                f"{self.base_url}/queue/add",
                json={"title": song_title, "artist": artist, "table_no": table_no},
                headers=self._headers(),
                timeout=self.timeout,
            )
            resp.raise_for_status()
            data = resp.json()
        except (requests.RequestException, ValueError) as exc:
            raise VirtualDJError(f"VirtualDJ недоступен или вернул ошибку: {exc}") from exc

        item_id = data.get("vdj_item_id") or data.get("id")
        if not item_id:
            raise VirtualDJError("VirtualDJ не вернул идентификатор элемента очереди")
        return str(item_id)

    def remove_from_queue(self, vdj_item_id: str) -> None:
        try:
            resp = requests.delete(
                f"{self.base_url}/queue/{vdj_item_id}",
                headers=self._headers(),
                timeout=self.timeout,
            )
            resp.raise_for_status()
        except requests.RequestException as exc:
            raise VirtualDJError(f"Не удалось удалить трек из VirtualDJ: {exc}") from exc

    def get_queue(self) -> list[VDJQueueItem]:
        try:
            resp = requests.get(f"{self.base_url}/queue", headers=self._headers(), timeout=self.timeout)
            resp.raise_for_status()
            items = resp.json().get("items", [])
        except (requests.RequestException, ValueError) as exc:
            raise VirtualDJError(f"Не удалось получить очередь VirtualDJ: {exc}") from exc

        return [
            VDJQueueItem(
                vdj_item_id=str(i.get("id")),
                song_title=i.get("title", ""),
                artist=i.get("artist"),
                table_no=i.get("table_no"),
            )
            for i in items
        ]

    def get_current_song(self) -> Optional[VDJQueueItem]:
        try:
            resp = requests.get(f"{self.base_url}/queue/current", headers=self._headers(), timeout=self.timeout)
            if resp.status_code == 204:
                return None
            resp.raise_for_status()
            i = resp.json()
        except (requests.RequestException, ValueError) as exc:
            raise VirtualDJError(f"Не удалось получить текущий трек VirtualDJ: {exc}") from exc

        if not i:
            return None
        return VDJQueueItem(
            vdj_item_id=str(i.get("id")),
            song_title=i.get("title", ""),
            artist=i.get("artist"),
            table_no=i.get("table_no"),
        )
