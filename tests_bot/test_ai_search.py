"""
Юнит-тесты оркестрации AI-поиска (ТЗ п.5, 28-30). Сетевые вызовы к Claude и
Genius подменяются — здесь проверяется только логика модуля: дедупликация,
ограничение 3-5 результатами, честный fallback без ключей API и без
выдумывания несуществующих треков.
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import ai_search


def run(coro):
    return asyncio.run(coro)


def test_no_api_keys_returns_empty_without_crashing(monkeypatch):
    monkeypatch.setattr(ai_search, "ANTHROPIC_API_KEY", None)
    monkeypatch.setattr(ai_search, "GENIUS_API_KEY", None)
    result = run(ai_search.ai_powered_search("дима билан машины"))
    assert result == []


def test_dedupes_results_across_queries(monkeypatch):
    async def fake_ask_claude(text):
        return ["Дима Билан - Билет на самолет", "Билан Билет на самолет"]

    async def fake_search_genius(query, limit):
        return [
            {"title": "Билет на самолет", "artist": "Дима Билан", "genius_url": "u1"},
            {"title": "Пьяная ночь", "artist": "Дима Билан", "genius_url": "u2"},
        ]

    monkeypatch.setattr(ai_search, "_ask_claude", fake_ask_claude)
    monkeypatch.setattr(ai_search, "_search_genius", fake_search_genius)

    result = run(ai_search.ai_powered_search("дима билан машины"))
    # Genius возвращает одни и те же 2 трека на оба запроса Claude — дубликаты убраны
    assert len(result) == 2
    titles = {r["title"] for r in result}
    assert titles == {"Билет на самолет", "Пьяная ночь"}


def test_never_returns_more_than_max_results(monkeypatch):
    async def fake_ask_claude(text):
        return ["q1", "q2", "q3"]

    async def fake_search_genius(query, limit):
        return [
            {"title": f"{query}-song-{i}", "artist": "X", "genius_url": "u"}
            for i in range(limit)
        ]

    monkeypatch.setattr(ai_search, "_ask_claude", fake_ask_claude)
    monkeypatch.setattr(ai_search, "_search_genius", fake_search_genius)

    result = run(ai_search.ai_powered_search("что угодно"))
    assert len(result) == ai_search.MAX_RESULTS


def test_fewer_than_three_results_are_returned_as_is_not_padded(monkeypatch):
    """ТЗ п.5: если найдено меньше трёх — показываем фактически найденное, а не выдумываем."""

    async def fake_ask_claude(text):
        return ["q1"]

    async def fake_search_genius(query, limit):
        return [{"title": "Единственный трек", "artist": "Кто-то", "genius_url": "u"}]

    monkeypatch.setattr(ai_search, "_ask_claude", fake_ask_claude)
    monkeypatch.setattr(ai_search, "_search_genius", fake_search_genius)

    result = run(ai_search.ai_powered_search("непонятное описание"))
    assert len(result) == 1
    assert result[0]["title"] == "Единственный трек"


def test_falls_back_to_raw_text_when_claude_finds_nothing(monkeypatch):
    calls = []

    async def fake_ask_claude(text):
        return []

    async def fake_search_genius(query, limit):
        calls.append(query)
        return [{"title": "Что-то нашлось", "artist": None, "genius_url": "u"}]

    monkeypatch.setattr(ai_search, "_ask_claude", fake_ask_claude)
    monkeypatch.setattr(ai_search, "_search_genius", fake_search_genius)

    result = run(ai_search.ai_powered_search("оригинальный текст гостя"))
    assert calls == ["оригинальный текст гостя"]
    assert len(result) == 1
