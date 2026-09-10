"""
Юнит-тесты NetworkControlVDJDriver (этап 6 — см. PHASE6_VDJ_NETWORK_CONTROL.md).

HTTP к настоящему VirtualDJ здесь не делается — requests.get подменяется,
чтобы проверить: правильно ли строится запрос (script как query-параметр),
правильную ли цепочку команд вызывает add_to_queue, и что driver честно
падает (RuntimeError/NotImplementedError), а не выдумывает результат, когда
VirtualDJ отвечает ошибкой или когда операция вообще не подтверждена.
"""
from unittest.mock import Mock, patch

import pytest

from driver import MockVDJDriver, NetworkControlVDJDriver


def _resp(text):
    m = Mock()
    m.text = text
    m.raise_for_status = Mock()
    return m


@pytest.fixture
def driver():
    return NetworkControlVDJDriver(base_url="http://127.0.0.1:80")


def test_query_sends_script_as_query_param(driver):
    with patch("requests.get", return_value=_resp("21:00:41")) as mock_get:
        result = driver._query("get_clock")

    assert result == "21:00:41"
    mock_get.assert_called_once_with(
        "http://127.0.0.1:80/query", params={"script": "get_clock"}, timeout=driver.timeout
    )


def test_query_strips_whitespace(driver):
    with patch("requests.get", return_value=_resp("  Afro House Mix 2026  \n")):
        assert driver._query("get_artist") == "Afro House Mix 2026"


def test_add_to_queue_happy_path_runs_count_then_search_then_filepath_then_add_then_count(driver):
    """
    Подтверждено живым тестом с пользователем (эксперименты №3-6,
    PHASE6_VDJ_NETWORK_CONTROL.md раздел 3.3-3.6): во вкладке Karaoke
    search -> get_browsed_filepath -> karaoke_add реально добавляет файл в
    очередь. Успех проверяется ростом file_count karaoke, а не текстом
    ответа karaoke_add (см. следующий тест — тот текст ненадёжен).
    """
    responses = iter([
        _resp("17"),  # file_count karaoke — before
        _resp("no"),  # search <query> — живой ответ VirtualDJ на успешный поиск
        _resp(r"C:\Music\Karaoke\Artist - Song.mp3"),  # get_browsed_filepath
        _resp("no"),  # karaoke_add <filepath>
        _resp("18"),  # file_count karaoke — after
    ])
    with patch("requests.get", side_effect=lambda *a, **kw: next(responses)) as mock_get:
        item_id = driver.add_to_queue("Song", "Artist", table_no=5)

    assert item_id == r"C:\Music\Karaoke\Artist - Song.mp3"
    scripts = [call.kwargs["params"]["script"] for call in mock_get.call_args_list]
    assert scripts[0] == "file_count karaoke"
    assert scripts[1] == "search Artist Song"
    assert scripts[2] == "get_browsed_filepath"
    assert scripts[3] == r"karaoke_add C:\Music\Karaoke\Artist - Song.mp3"
    assert scripts[4] == "file_count karaoke"


def test_add_to_queue_succeeds_even_when_karaoke_add_response_text_says_error(driver):
    """
    Живой тест с пользователем показал именно этот случай: VirtualDJ
    ответил на karaoke_add текстом "error:-2147467263", но песня реально
    добавилась (счётчик очереди вырос с 17 до 18). Драйвер должен доверять
    факту роста file_count karaoke, а не тексту ответа karaoke_add.
    """
    responses = iter([
        _resp("17"),
        _resp("no"),
        _resp(r"D:\Karaoke\Prima dragoste.mp4"),
        _resp("error:-2147467263"),  # обманчивый ответ — реально сработало
        _resp("18"),
    ])
    with patch("requests.get", side_effect=lambda *a, **kw: next(responses)):
        item_id = driver.add_to_queue("Prima dragoste", "Alexandru Cebotaru", table_no=5)

    assert item_id == r"D:\Karaoke\Prima dragoste.mp4"


def test_add_to_queue_without_artist_searches_by_title_only(driver):
    responses = iter([_resp("17"), _resp("no"), _resp(r"C:\Music\Song.mp3"), _resp("no"), _resp("17")])
    with patch("requests.get", side_effect=lambda *a, **kw: next(responses)) as mock_get:
        with pytest.raises(RuntimeError, match="не добавилась"):
            driver.add_to_queue("Song", None, table_no=None)

    second_script = mock_get.call_args_list[1].kwargs["params"]["script"]
    assert second_script == "search Song"


def test_add_to_queue_raises_when_filepath_not_found(driver):
    responses = iter([_resp("17"), _resp("no"), _resp("error:-2147024809")])
    with patch("requests.get", side_effect=lambda *a, **kw: next(responses)):
        with pytest.raises(RuntimeError, match="не нашёл файл"):
            driver.add_to_queue("Nonexistent Song", "Nobody", table_no=1)


def test_add_to_queue_raises_when_queue_count_does_not_grow(driver):
    """Если file_count karaoke не увеличился — считаем, что добавление не
    удалось, вне зависимости от того, что написал сам karaoke_add в ответе."""
    responses = iter([_resp("17"), _resp("no"), _resp(r"C:\Music\Song.mp3"), _resp("no"), _resp("17")])
    with patch("requests.get", side_effect=lambda *a, **kw: next(responses)):
        with pytest.raises(RuntimeError, match="не добавилась"):
            driver.add_to_queue("Song", "Artist", table_no=1)


def test_remove_from_queue_not_implemented(driver):
    with pytest.raises(NotImplementedError):
        driver.remove_from_queue("some-id")


def test_get_queue_returns_title_artist_and_filepath_for_each_position_in_order(driver):
    """
    Подтверждено живым тестом (PHASE6_VDJ_NETWORK_CONTROL.md, раздел 3.7-3.8):
    file_count karaoke -> количество, затем get_next_karaoke_song "title"/
    "artist"/"filepath"/"filename" для каждой позиции от 0 до количество-1.
    vdj_item_id = "filepath"+"filename" — подтверждено, что это совпадает
    (кроме буквы диска) с тем, что add_to_queue() сохраняет как vdj_item_id.
    """
    responses = iter([
        _resp("2"),  # file_count karaoke
        _resp("Song A"), _resp("Artist A"), _resp("\\Folder\\"), _resp("SongA.mp4"),  # позиция 0
        _resp("Song B"), _resp("Artist B"), _resp("\\Folder\\"), _resp("SongB.mp4"),  # позиция 1
    ])
    with patch("requests.get", side_effect=lambda *a, **kw: next(responses)) as mock_get:
        queue = driver.get_queue()

    assert queue == [
        {
            "vdj_item_id": "\\Folder\\SongA.mp4",
            "song_title": "Song A",
            "artist": "Artist A",
            "table_no": None,
        },
        {
            "vdj_item_id": "\\Folder\\SongB.mp4",
            "song_title": "Song B",
            "artist": "Artist B",
            "table_no": None,
        },
    ]
    scripts = [call.kwargs["params"]["script"] for call in mock_get.call_args_list]
    assert scripts[0] == "file_count karaoke"
    assert scripts[1] == 'get_next_karaoke_song "title" 0'
    assert scripts[2] == 'get_next_karaoke_song "artist" 0'
    assert scripts[3] == 'get_next_karaoke_song "filepath" 0'
    assert scripts[4] == 'get_next_karaoke_song "filename" 0'


def test_get_queue_returns_empty_list_when_queue_is_empty(driver):
    with patch("requests.get", return_value=_resp("0")) as mock_get:
        assert driver.get_queue() == []
    # раз песен нет, не нужно делать ни одного запроса про title/artist/filepath
    mock_get.assert_called_once()


def test_get_queue_handles_song_with_no_artist_set(driver):
    """Живой тест показал реальный случай: у некоторых файлов в очереди
    исполнитель не заполнен, и VirtualDJ отвечает пустой строкой — это не
    ошибка, artist в таком случае должен быть None, а не пустая строка."""
    responses = iter([_resp("1"), _resp("Коло Плота"), _resp(""), _resp("\\Folder\\"), _resp("Kolo.mp4")])
    with patch("requests.get", side_effect=lambda *a, **kw: next(responses)):
        queue = driver.get_queue()

    assert queue == [
        {
            "vdj_item_id": "\\Folder\\Kolo.mp4",
            "song_title": "Коло Плота",
            "artist": None,
            "table_no": None,
        }
    ]


def test_get_queue_sets_vdj_item_id_to_none_when_filename_missing(driver):
    """Если VirtualDJ почему-то не смогла отдать имя файла — не выдумываем
    идентификатор из пустой строки, оставляем None (Backend это уже умеет
    обрабатывать — см. _queue_rank в vdj_service.py: None не совпадёт ни с
    одним сохранённым vdj_item_id, ранг просто не определится)."""
    responses = iter([_resp("1"), _resp("Song"), _resp("Artist"), _resp("\\Folder\\"), _resp("")])
    with patch("requests.get", side_effect=lambda *a, **kw: next(responses)):
        queue = driver.get_queue()

    assert queue[0]["vdj_item_id"] is None


def test_get_current_song_returns_dict_when_something_loaded(driver):
    responses = iter([_resp("Afro House Mix 2026"), _resp("Cool Track")])
    with patch("requests.get", side_effect=lambda *a, **kw: next(responses)):
        song = driver.get_current_song()

    assert song == {
        "vdj_item_id": None,
        "song_title": "Cool Track",
        "artist": "Afro House Mix 2026",
        "table_no": None,
    }


def test_get_current_song_returns_none_when_nothing_loaded(driver):
    responses = iter([_resp(""), _resp("")])
    with patch("requests.get", side_effect=lambda *a, **kw: next(responses)):
        assert driver.get_current_song() is None


def test_query_raises_runtime_error_when_virtualdj_unreachable(driver):
    import requests

    with patch("requests.get", side_effect=requests.ConnectionError("refused")):
        with pytest.raises(RuntimeError, match="недоступен"):
            driver._query("get_clock")


def test_mock_driver_unaffected_baseline():
    """Контрольная проверка, что MockVDJDriver (уже существующий, используемый
    по умолчанию) не сломан этими изменениями — он не должен требовать сеть."""
    mock = MockVDJDriver()
    item_id = mock.add_to_queue("Song", "Artist", 3)
    assert mock.get_queue() == [
        {"vdj_item_id": item_id, "song_title": "Song", "artist": "Artist", "table_no": 3}
    ]
