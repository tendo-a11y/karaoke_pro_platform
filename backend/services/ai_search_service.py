"""
AI-поиск песни по свободному описанию гостя (Role 3/4/5, аудит-отчёт п.2).

Текст гостя -> Claude (анализ, извлекает 1-3 варианта "исполнитель -
название") -> iTunes Search API (реальный поиск треков) -> подходящие песни.

Изначально вместо iTunes здесь был Genius (1:1 перенос старого
ai_search.py). Заменено по итогам живой проверки: Genius — это сайт про
тексты песен, ориентированный на западную музыку, и заметно хуже находит
русский шансон и молдавский/румынский репертуар (конкретный пример,
из-за которого искали замену: гость не смог найти "Рюмку водки" —
Genius её просто не знал). iTunes Search API — каталог реальных
музыкальных треков Apple Music, ключ/регистрация не нужны вообще, и
на живых проверках (в т.ч. молдавский исполнитель Valentin Boghean)
показал заметно лучшее покрытие нужного репертуара.

У iTunes Search API нет единого "глобального" поиска — только по
одному магазину (country) за раз, и набор треков в разных магазинах
отличается (права правообладателя). Поэтому _search_itunes проверяет
сразу несколько магазинов и объединяет результаты (см. её докстринг) —
это и есть тот эффект "искать по всему Apple Music", который отдельно
попросили при живой проверке (случай с румынской колядкой "Galbenă
Gutuie" — была в магазинах Британии/США, но не в молдавском).

Первая версия сразу же останавливалась на первом магазине, где хоть
что-то нашлось, — но это оказалось ошибкой: живой случай "oriunde ai
fi" показал, что один магазин может вернуть случайное, слабое
совпадение (совсем другого исполнителя) раньше, чем другой магазин
дошёл бы до настоящей песни. Поэтому теперь проверяются все магазины
из списка, а результат сортируется по тому, сколько слов запроса
реально совпало с названием/исполнителем — точное совпадение не
теряется за случайным.

Правила, которые важны и здесь сохранены как есть:
  - Claude используется ТОЛЬКО для анализа текста, не как источник
    музыкальной базы — реальные треки достаёт исключительно iTunes.
  - Если Claude не смог ничего предложить (нет ключа/ошибка/пустой JSON) —
    честный fallback: исходный текст гостя уходит в iTunes как есть.
  - Максимум 5 результатов суммарно по всем запросам, дедупликация по
    (title.lower(), artist.lower()). Меньше — показывается фактически
    найденное, никогда не дополняется выдумкой (старое: MIN_RESULTS_TARGET=3
    объявлена, но не использовалась в реальной логике — сюда тоже не
    переносится, см. аудит, находка №12).
  - ANTHROPIC_API_KEY опционален — без него шаг анализа текста Клодом
    просто возвращается [] и не роняет запрос (честный fallback на
    исходный текст гостя, см. выше). iTunes Search API ключа не требует
    вообще — этот шаг работает всегда.

Синхронный перенос (requests вместо aiohttp) — Flask-эндпоинты в этом
backend синхронные, как и остальные внешние вызовы (services/notify.py,
vdj/http_client.py).
"""
import json
import logging
import re

import requests
from flask import current_app

logger = logging.getLogger(__name__)

MAX_RESULTS = 5

CLAUDE_PROMPT = """Гость караоке-бара описал песню свободным текстом (возможно, с ошибками,
на русском или румынском, без знаков препинания). Определи, какую песню он имеет
в виду. Верни СТРОГО JSON без пояснений в формате:

{{"queries": ["исполнитель - название", "исполнитель2 - название2"]}}

Дай от 1 до 3 наиболее вероятных вариантов "исполнитель - название" для поиска
в базе Apple Music/iTunes. Если исполнитель неизвестен — верни только
название. Если совсем не удаётся ничего определить — верни {{"queries": []}}.

Текст гостя: {text}"""


def _ask_claude(text: str) -> list[str]:
    api_key = current_app.config.get("ANTHROPIC_API_KEY")
    if not api_key:
        logger.warning("ANTHROPIC_API_KEY не задан — AI-анализ текста пропущен")
        return []

    try:
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": current_app.config.get("ANTHROPIC_MODEL"),
                "max_tokens": 300,
                "messages": [{"role": "user", "content": CLAUDE_PROMPT.format(text=text)}],
            },
            timeout=10,
        )
    except requests.RequestException:
        logger.exception("Ошибка сети при обращении к Claude API")
        return []

    if resp.status_code != 200:
        logger.error("Claude API вернул %s: %s", resp.status_code, resp.text)
        return []

    try:
        data = resp.json()
        raw_text = data["content"][0]["text"]
        match = re.search(r"\{.*\}", raw_text, re.DOTALL)
        parsed = json.loads(match.group(0) if match else raw_text)
        queries = parsed.get("queries", [])
        return [q for q in queries if isinstance(q, str) and q.strip()][:3]
    except (KeyError, IndexError, ValueError, AttributeError, TypeError):
        logger.exception("Не удалось разобрать ответ Claude")
        return []


def _relevance_score(query: str, title: str, artist: str | None) -> int:
    """Сколько слов запроса реально встречается в названии+исполнителе
    (без учёта регистра). Простая эвристика без всякого AI/выдумывания —
    нужна, чтобы точное совпадение из магазина, проверенного позже, не
    терялось за случайным однословным совпадением из магазина,
    проверенного раньше (живой случай — см. докстринг файла)."""
    query_words = [w for w in query.lower().split() if w]
    haystack = f"{artist or ''} {title}".lower()
    return sum(1 for w in query_words if w in haystack)


def _search_itunes(query: str, limit: int) -> list[dict]:
    # iTunes Search API — открытый каталог реальных треков Apple Music,
    # ключ/регистрация не нужны (подтверждено официальной документацией
    # Apple). У каждого магазина (country) свой набор треков — один и тот
    # же трек может быть в каталоге одной страны и отсутствовать в другой
    # (права правообладателя). Живой проверкой найдено: молдавский
    # исполнитель нашёлся только в магазине Молдовы (MD), а румынская
    # колядка "Galbenă Gutuie" — только в магазинах Британии/США, но не
    # в молдавском. Поэтому проверяем все магазины из списка (не
    # останавливаясь на первом, где хоть что-то нашлось, — так терялись
    # правильные совпадения из более поздних магазинов, живой случай
    # "oriunde ai fi") и объединяем результаты, отсортировав по
    # реальному совпадению слов запроса (_relevance_score). Список
    # магазинов переопределяется переменной окружения ITUNES_COUNTRIES
    # (через запятую).
    countries = current_app.config.get("ITUNES_COUNTRIES", ["MD", "RO", "RU", "US"])

    seen = set()
    candidates: list[dict] = []
    for country in countries:
        try:
            resp = requests.get(
                "https://itunes.apple.com/search",
                params={
                    "term": query,
                    "media": "music",
                    "entity": "song",
                    "limit": limit,
                    "country": country,
                },
                timeout=8,
            )
        except requests.RequestException:
            logger.exception("Ошибка сети при обращении к iTunes Search API (магазин %s)", country)
            continue

        if resp.status_code != 200:
            logger.error("iTunes Search API вернул %s (магазин %s): %s", resp.status_code, country, resp.text)
            continue

        data = resp.json()
        for item in data.get("results", [])[:limit]:
            title = item.get("trackName")
            artist = item.get("artistName")
            if not title:
                continue
            key = (title.strip().lower(), (artist or "").strip().lower())
            if key in seen:
                continue
            seen.add(key)
            candidates.append({"title": title, "artist": artist, "itunes_url": item.get("trackViewUrl")})

    # sort() в Python устойчив — при равном счёте порядок между магазинами
    # (MD, потом RO, RU, US) сохраняется как есть.
    candidates.sort(key=lambda c: _relevance_score(query, c["title"], c["artist"]), reverse=True)
    return candidates[:limit]


def ai_powered_search(text: str) -> list[dict]:
    """
    Возвращает от 0 до 5 словарей {title, artist, itunes_url}. Никогда не
    дополняет список выдуманными записями — если найдено меньше, возвращается
    фактическое количество (в т.ч. 0, если ничего не нашлось).
    """
    queries = _ask_claude(text)
    if not queries:
        # Честный fallback, как в старом коде (там — на Genius, теперь —
        # на iTunes): ищем по исходному тексту гостя напрямую, iTunes сам
        # решает, что нашлось.
        queries = [text]

    seen = set()
    results: list[dict] = []
    for query in queries:
        for item in _search_itunes(query, limit=MAX_RESULTS):
            key = (item["title"].strip().lower(), (item["artist"] or "").strip().lower())
            if key in seen:
                continue
            seen.add(key)
            results.append(item)
            if len(results) >= MAX_RESULTS:
                return results
    return results
