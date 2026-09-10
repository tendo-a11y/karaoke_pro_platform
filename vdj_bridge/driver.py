"""
Точка расширения для реального протокола VirtualDJ (ТЗ п.16 — до сих пор
открытый вопрос: нет доступа к реально установленному VirtualDJ на месте,
чтобы понять, как именно им управлять снаружи — VDJScript, локальный
сокет/HTTP, чтение/запись файла плейлиста и т.п.).

Мост (agent.py) НЕ знает, как устроен VirtualDJ — он знает только, как
получать команды с Backend и отвечать на них. Вся VDJ-специфика
инкапсулирована здесь, за одним и тем же интерфейсом. Чтобы подключить
настоящий VirtualDJ, нужно реализовать методы VDJDriver в новом классе —
остальной код моста (agent.py, реестр запросов, Backend) трогать не
придётся вообще.
"""
from abc import ABC, abstractmethod
from typing import Optional


class VDJDriver(ABC):
    @abstractmethod
    def add_to_queue(self, song_title: str, artist: Optional[str], table_no: Optional[int]) -> str:
        """Должен вернуть идентификатор добавленного элемента очереди VirtualDJ."""

    @abstractmethod
    def remove_from_queue(self, vdj_item_id: str) -> None:
        ...

    @abstractmethod
    def get_queue(self) -> list:
        """Список словарей {vdj_item_id, song_title, artist, table_no}."""

    @abstractmethod
    def get_current_song(self) -> Optional[dict]:
        """Словарь {vdj_item_id, song_title, artist, table_no} или None."""


class MockVDJDriver(VDJDriver):
    """
    Реализация по умолчанию — держит очередь в памяти самого моста (на
    компьютере KJ) и НЕ трогает реальный VirtualDJ. Нужна, чтобы можно было
    проверить весь путь Telegram -> Backend -> мост -> Backend -> KJ Panel
    end-to-end уже сейчас, не дожидаясь ответа на п.16.

    Как только протокол VirtualDJ будет определён — этот класс заменяется
    на реальный драйвер (например RealVirtualDJDriver в этом же файле), а
    agent.py меняется одной строкой импорта/инициализации.
    """

    def __init__(self):
        self._queue: list[dict] = []
        self._next_id = 1

    def add_to_queue(self, song_title, artist, table_no):
        item_id = f"local-{self._next_id}"
        self._next_id += 1
        self._queue.append(
            {
                "vdj_item_id": item_id,
                "song_title": song_title,
                "artist": artist,
                "table_no": table_no,
            }
        )
        return item_id

    def remove_from_queue(self, vdj_item_id):
        self._queue = [i for i in self._queue if i["vdj_item_id"] != vdj_item_id]

    def get_queue(self):
        return list(self._queue)

    def get_current_song(self):
        return self._queue[0] if self._queue else None


class NetworkControlVDJDriver(VDJDriver):
    """
    Реальный драйвер VirtualDJ через встроенный Network Control Plugin.

    Протокол подтверждён живой проверкой этапа 6 — подробности, что именно
    и кем проверено, см. PHASE6_VDJ_NETWORK_CONTROL.md в корне репозитория.
    Коротко: плагин слушает HTTP на самой машине, где стоит VirtualDJ (по
    умолчанию 127.0.0.1:80), и выполняет VDJScript-команды через
    `GET /query?script=<команда>`, возвращая результат обычным текстом.

    Статус подтверждения (см. PHASE6_VDJ_NETWORK_CONTROL.md, раздел 3.3-3.6
    — эксперименты №3-6, проведены вживую вместе с пользователем 2026-09):
      * get_clock/get_artist/get_title/get_loaded_song/file_count karaoke —
        проверены напрямую.
      * Цепочка search -> get_browsed_filepath -> karaoke_add ТЕПЕРЬ
        ПОДТВЕРЖДЕНА полностью, живым тестом от начала до конца: во вкладке
        Karaoke (это оказалось обязательным условием — в Automix цепочка не
        воспроизводилась), `search <запрос>` реально меняет то, что вернёт
        `get_browsed_filepath`, а `karaoke_add <путь>` реально добавляет
        файл в очередь караоке (посчитано вручную пользователем: было 17
        песен, стало 18). Более ранний отрицательный результат (раздел 3.1)
        объясняется тем, что тогда не было учтено, что нужна именно вкладка
        Karaoke.
      * ВАЖНАЯ ОГОВОРКА: сама VirtualDJ в ответ на успешный `karaoke_add`
        может вернуть текст вида `error:-2147467263` — при этом песня
        реально добавляется в очередь. То есть текст ответа Network Control
        Plugin НЕЛЬЗЯ использовать как признак успеха/неудачи `karaoke_add`
        — единственный надёжный способ проверить результат — сравнить
        `file_count karaoke` до и после вызова. Реализовано ниже именно так.
      * get_queue() ТЕПЕРЬ РЕАЛИЗОВАН и подтверждён отдельным живым тестом
        (см. PHASE6_VDJ_NETWORK_CONTROL.md, раздел 3.7 и раздел с проверкой
        динамики очереди после него): команда `get_next_karaoke_song`
        принимает номер позиции в очереди как обычное целое число НАЧИНАЯ
        С НУЛЯ (0 — первая песня в списке; знак "+" из официальной
        документации VirtualDJ не обязателен) и слово в кавычках — `"title"`
        или `"artist"` — и возвращает соответствующее значение для песни на
        этой позиции. Проверено на всех позициях реальной очереди (0..17 при
        18 песнях), включая случай, когда одна и та же песня стоит в очереди
        дважды одновременно (это подтверждено пользователем как нормальная
        реальная ситуация, не баг). Отдельно, уже после этого, проверено и
        подтверждено, что список, получаемый этим способом, ТОЧНО отражает
        живое состояние очереди после ручных действий KJ прямо в VirtualDJ:
        перемещение песни вверх, перемещение вниз, удаление из середины
        очереди, добавление новой песни вручную и несколько таких изменений
        подряд — во всех случаях `file_count karaoke` и содержимое по
        позициям совпадали с тем, что пользователь видел на экране.
      * remove_from_queue() по-прежнему НЕ реализован — рабочая команда
        удаления/переупорядочивания одного конкретного элемента по индексу
        не найдена и не проверялась (пользователь отдельно подтвердил, что
        это и не требуется — авто-удаление через нашу систему не нужно,
        это остаётся ручным действием KJ в самой VirtualDJ, как и было в
        старой системе). Единственная найденная в документации команда
        рядом с этой темой — `karaoke_clear`, которая очищает СРАЗУ ВЕСЬ
        список, а не один элемент, — специально не проверялась вживую, чтобы
        не рисковать реальной боевой очередью пользователя.
    """

    def __init__(self, base_url: str = "http://127.0.0.1:80", timeout: float = 5.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _query(self, script: str) -> str:
        import requests

        try:
            resp = requests.get(
                f"{self.base_url}/query",
                params={"script": script},
                timeout=self.timeout,
            )
            resp.raise_for_status()
        except requests.RequestException as exc:
            raise RuntimeError(
                f"VirtualDJ Network Control Plugin недоступен ({self.base_url}): {exc}"
            ) from exc
        return resp.text.strip()

    def _karaoke_count(self) -> Optional[int]:
        """file_count karaoke — подтверждено напрямую (раздел 2
        PHASE6_VDJ_NETWORK_CONTROL.md). Используется как единственный
        надёжный способ проверить, реально ли произошло добавление в
        очередь (текст ответа karaoke_add для этого не годится — см.
        docstring класса выше). Возвращает None, если ответ не число
        (не должно происходить в норме, но лучше не падать с ValueError на
        неожиданном ответе плагина)."""
        raw = self._query("file_count karaoke")
        try:
            return int(raw)
        except ValueError:
            return None

    def add_to_queue(self, song_title: str, artist: Optional[str], table_no: Optional[int]) -> str:
        """
        Подтверждено живым тестом (эксперименты №3-6, PHASE6_VDJ_NETWORK_
        CONTROL.md раздел 3.3-3.6) — работает именно в этой последовательности,
        при условии что в VirtualDJ открыта вкладка Karaoke (не Automix).
        table_no сюда не передаётся в саму VirtualDJ — у неё нет понятия
        "стол", это остаётся только в Backend/Order для сопоставления заказа
        с гостем (согласовано с пользователем отдельно).
        """
        query = f"{artist} {song_title}".strip() if artist else song_title

        before = self._karaoke_count()

        self._query(f"search {query}")
        # НЕ ПОДТВЕРЖДЕНО: если поиск вернул несколько результатов, здесь
        # предполагается, что get_browsed_filepath берёт первый/выделенный
        # по умолчанию элемент. Явного шага "выбрать результат №N" не
        # реализовано — на реальном VirtualDJ его команда пока не известна.
        filepath = self._query("get_browsed_filepath")
        if not filepath or filepath.startswith("error:"):
            raise RuntimeError(
                f"VirtualDJ не нашёл файл по запросу '{query}' "
                f"(get_browsed_filepath вернул: {filepath!r})"
            )

        # Намеренно НЕ проверяем текст ответа karaoke_add на "error:" —
        # живой тест показал, что VirtualDJ может вернуть именно такой
        # текст даже при успешном добавлении (см. docstring класса).
        self._query(f"karaoke_add {filepath}")

        after = self._karaoke_count()
        if before is not None and after is not None and after <= before:
            raise RuntimeError(
                f"karaoke_add не увеличил очередь караоке (было {before}, "
                f"стало {after}) — песня '{query}' похоже не добавилась"
            )

        # У нас нет подтверждённого способа получить стабильный числовой/
        # строковый ID добавленного элемента очереди от Network Control —
        # используем сам filepath как временный идентификатор. Это НЕ
        # позволяет надёжно удалить/переместить именно этот элемент позже
        # (см. remove_from_queue ниже) — только явно подтверждает, что
        # операция прошла успешно (по факту роста file_count karaoke).
        return filepath

    def remove_from_queue(self, vdj_item_id: str) -> None:
        raise NotImplementedError(
            "Удаление/перемещение элемента karaoke-очереди VirtualDJ по ID "
            "пока не подтверждено экспериментально — см. раздел 4 "
            "PHASE6_VDJ_NETWORK_CONTROL.md. Нужно сначала найти и проверить "
            "рабочую VDJScript-команду для индексированного доступа к "
            "элементам очереди."
        )

    def _next_karaoke_property(self, prop: str, index: int) -> str:
        """
        Один вызов get_next_karaoke_song для конкретного свойства ("title"
        или "artist") и позиции в очереди (нумерация с нуля — подтверждено
        живым тестом, см. docstring класса и PHASE6_VDJ_NETWORK_CONTROL.md
        раздел 3.7). requests сам корректно закодирует кавычки и пробелы в
        параметре script — писать их вручную (%22, %20 и т.п.) не нужно.
        """
        return self._query(f'get_next_karaoke_song "{prop}" {index}')

    def get_queue(self) -> list:
        """
        Подтверждено живым тестом (PHASE6_VDJ_NETWORK_CONTROL.md, раздел 3.7
        и раздел с проверкой динамики очереди сразу после него) — включая
        проверку, что список верно обновляется после ручного перемещения,
        удаления из середины и добавления песен в самой VirtualDJ.

        Спрашивает у VirtualDJ количество песен в очереди караоке, затем по
        очереди — название и исполнителя каждой позиции от первой до
        последней, и возвращает их в том же порядке.

        VirtualDJ не знает и не возвращает номер стола или то, кто заказал
        песню — это сопоставляется отдельно, на стороне Backend, по
        совпадению названия/исполнителя с уже существующими заказами. Так
        как одна и та же песня может стоять в очереди VirtualDJ дважды
        одновременно (подтверждено вживую, это нормальная реальная
        ситуация), такое сопоставление должно расходовать каждую позицию
        очереди только один раз (та же дисциплина "next unmatched", что
        описана в разделе 5 для сопоставления с History) — это забота
        Backend, не этого драйвера.

        vdj_item_id здесь — это путь к файлу, собранный из двух свойств этой
        же команды ("filepath" — папка без буквы диска, и "filename" — имя
        файла). Подтверждено живым тестом (PHASE6_VDJ_NETWORK_CONTROL.md,
        раздел 3.8): "папка"+"имя файла" совпадает с полным путём, который
        `add_to_queue()` получает от `get_browsed_filepath` и сохраняет как
        vdj_item_id при добавлении песни — РОВНО ЗА ИСКЛЮЧЕНИЕМ буквы диска
        (`get_browsed_filepath` возвращает её, например "D:\\...", а
        "filepath" — нет, только "\\..."). Поэтому сравнивать эти два вида
        vdj_item_id между собой нужно не через точное равенство, а через
        "заканчивается на" (см. `backend/services/vdj_service.py::
        _queue_rank`) — это уже сделано на стороне Backend.

        ВАЖНАЯ ОГОВОРКА про дубликаты: если одна и та же песня стоит в
        очереди VirtualDJ дважды одновременно (подтверждено вживую, это
        нормальная реальная ситуация), путь к файлу у обеих записей будет
        одинаковым — по одному только пути их не различить, только по
        текущей позиции в очереди на момент запроса. Backend должен
        учитывать это при сопоставлении с заказами (см. раздел 3.7/3.8).
        """
        count = self._karaoke_count()
        if not count:
            return []

        queue = []
        for i in range(count):
            title = self._next_karaoke_property("title", i)
            artist = self._next_karaoke_property("artist", i)
            folder = self._next_karaoke_property("filepath", i)
            filename = self._next_karaoke_property("filename", i)
            vdj_item_id = f"{folder}{filename}" if filename else None
            queue.append(
                {
                    "vdj_item_id": vdj_item_id,
                    "song_title": title or None,
                    "artist": artist or None,
                    "table_no": None,
                }
            )
        return queue

    def get_current_song(self) -> Optional[dict]:
        artist = self._query("get_artist")
        title = self._query("get_title")
        if not title:
            return None
        return {
            "vdj_item_id": None,
            "song_title": title,
            "artist": artist or None,
            "table_no": None,
        }
