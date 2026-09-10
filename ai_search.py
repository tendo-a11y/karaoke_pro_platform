"""
AI-поиск песни по свободному описанию гостя (ТЗ п.5-6, п.28-30):

    Текст гостя -> Claude AI -> Genius API -> подходящие песни

Правила из ТЗ, которые здесь важны:
  - Claude используется ТОЛЬКО для анализа текста (извлечение вероятных
    названия/исполнителя/ключевых слов), а не как источник музыкальной базы
    (п.28) — реальные треки достаёт исключительно Genius (п.29).
  - Если найдено меньше 3 подходящих результатов, показываются фактически
    найденные варианты, а не выдуманные (п.5). Пустой список — тоже валидный
    результат.
  - Это ДОПОЛНЕНИЕ к существующему поиску, а не замена (п.30) — существующий
    inline-поиск в bot.py трогать не нужно.

Модуль не требует наличия ключей на этапе импорта: при отсутствии
ANTHROPIC_API_KEY/GENIUS_API_KEY функции возвращают пустой список и логируют
предупреждение, чтобы остальной бот продолжал работать.
"""
import json
import logging
import os
import re

import aiohttp

logger = logging.getLogger(__name__)

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-3-5-haiku-20241022")
GENIUS_API_KEY = os.getenv("GENIUS_API_KEY")

MAX_RESULTS = 5
MIN_RESULTS_TARGET = 3

CLAUDE_PROMPT = """Гость караоке-бара описал песню свободным текстом (возможно, с ошибками,
на русском или румынском, без знаков препинания). Определи, какую песню он имеет
в виду. Верни СТРОГО JSON без пояснений в формате:

{{"queries": ["исполнитель - название", "исполнитель2 - название2"]}}

Дай от 1 до 3 наиболее вероятных вариантов "исполнитель - название" для поиска в
Genius. Если исполнитель неизвестен — верни только название. Если совсем не
удаётся ничего определить — верни {{"queries": []}}.

Текст гостя: {text}"""


async def _ask_claude(text: str) -> list[str]:
    if not ANTHROPIC_API_KEY:
        logger.warning("ANTHROPIC_API_KEY не задан — AI-анализ текста пропущен")
        return []

    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": ANTHROPIC_API_KEY,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": ANTHROPIC_MODEL,
                    "max_tokens": 300,
                    "messages": [{"role": "user", "content": CLAUDE_PROMPT.format(text=text)}],
                },
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    logger.error("Claude API вернул %s: %s", resp.status, body)
                    return []
                data = await resp.json()
        except (aiohttp.ClientError, TimeoutError):
            logger.exception("Ошибка сети при обращении к Claude API")
            return []

    try:
        raw_text = data["content"][0]["text"]
        match = re.search(r"\{.*\}", raw_text, re.DOTALL)
        parsed = json.loads(match.group(0) if match else raw_text)
        queries = parsed.get("queries", [])
        return [q for q in queries if isinstance(q, str) and q.strip()][:3]
    except (KeyError, IndexError, ValueError, AttributeError):
        logger.exception("Не удалось разобрать ответ Claude: %s", data)
        return []


async def _search_genius(query: str, limit: int) -> list[dict]:
    if not GENIUS_API_KEY:
        logger.warning("GENIUS_API_KEY не задан — поиск по Genius пропущен")
        return []

    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(
                "https://api.genius.com/search",
                params={"q": query},
                headers={"Authorization": f"Bearer {GENIUS_API_KEY}"},
                timeout=aiohttp.ClientTimeout(total=8),
            ) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    logger.error("Genius API вернул %s: %s", resp.status, body)
                    return []
                data = await resp.json()
        except (aiohttp.ClientError, TimeoutError):
            logger.exception("Ошибка сети при обращении к Genius API")
            return []

    hits = data.get("response", {}).get("hits", [])[:limit]
    results = []
    for hit in hits:
        result = hit.get("result", {})
        title = result.get("title") or result.get("title_with_featured")
        artist = (result.get("primary_artist") or {}).get("name")
        if not title:
            continue
        results.append({"title": title, "artist": artist, "genius_url": result.get("url")})
    return results


async def ai_powered_search(text: str) -> list[dict]:
    """
    Возвращает от 0 до 5 словарей {title, artist, genius_url}. Никогда не
    дополняет список выдуманными записями (ТЗ п.5) — если найдено меньше,
    возвращается фактическое количество.
    """
    queries = await _ask_claude(text)
    if not queries:
        # Если Claude не смог ничего предложить (или не настроен), пробуем
        # искать по исходному тексту гостя напрямую — это не выдумывание
        # результата, а честный fallback: Genius сам решит, что найдено.
        queries = [text]

    seen = set()
    results: list[dict] = []
    for query in queries:
        for item in await _search_genius(query, limit=MAX_RESULTS):
            key = (item["title"].strip().lower(), (item["artist"] or "").strip().lower())
            if key in seen:
                continue
            seen.add(key)
            results.append(item)
            if len(results) >= MAX_RESULTS:
                return results
    return results
