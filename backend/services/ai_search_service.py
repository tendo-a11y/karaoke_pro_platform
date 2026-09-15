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

Дополнение: гость может вставить в то же самое поле не описание, а прямую
ссылку на Ютуб/Apple Music/Spotify — тогда гадать вообще не нужно, он уже
точно знает песню. В этом случае Клод и iTunes-поиск пропускаются
полностью, название читается прямо из самой ссылки (_resolve_link) через
официальные бесплатные способы каждого сервиса, без ключей:
  - Ютуб и Spotify — открытый oEmbed (просто отдаёт title/author_name по
    ссылке на видео/трек).
  - Apple Music/iTunes — тот же lookup, что и у обычного поиска, но по
    точному id трека из самой ссылки.
Если ссылка распознана, но вытащить название не удалось — честно
возвращается [], как и везде в этом файле.

Синхронный перенос (requests вместо aiohttp) — Flask-эндпоинты в этом
backend синхронные, как и остальные внешние вызовы (services/notify.py,
vdj/http_client.py).
"""
import json
import logging
import re
from urllib.parse import parse_qs, urlparse

import requests
from flask import current_app

logger = logging.getLogger(__name__)

MAX_RESULTS = 5

LINK_DOMAINS = ("youtube.com", "youtu.be", "music.apple.com", "itunes.apple.com", "open.spotify.com")

# Типы картинок, которые принимает Claude API (и которых достаточно для
# скриншота из телефона — HEIC на бэкенд не доходит, конвертируется в JPEG
# ещё на фронтенде при сжатии через canvas, см. guest-app/src/App.jsx).
ALLOWED_SCREENSHOT_TYPES = {"image/jpeg", "image/png", "image/webp"}

CLAUDE_PROMPT = """Гость караоке-бара описал песню свободным текстом (возможно, с ошибками,
на русском или румынском, без знаков препинания). Определи, какую песню он имеет
в виду. Верни СТРОГО JSON без пояснений в формате:

{{"queries": ["исполнитель - название", "исполнитель2 - название2"]}}

Дай от 1 до 3 наиболее вероятных вариантов "исполнитель - название" для поиска
в базе Apple Music/iTunes. Если исполнитель неизвестен — верни только
название. Если совсем не удаётся ничего определить — верни {{"queries": []}}.

Текст гостя: {text}"""

CLAUDE_VISION_PROMPT = """Гость караоке-бара прислал скриншот (например, из Shazam, Spotify,
YouTube Music, ВКонтакте или похожего приложения), где виден плеер или
карточка песни. Найди на картинке название песни и, если видно, исполнителя.
Текст на скриншоте может быть частично обрезан или на разных языках (русский,
румынский, английский). Верни СТРОГО JSON без пояснений в формате:

{"queries": ["исполнитель - название"]}

Дай ровно один наиболее вероятный вариант "исполнитель - название" для поиска
в базе Apple Music/iTunes (или только название, если исполнитель не виден).
Если на картинке вообще не видно ничего похожего на название песни — верни
{"queries": []}."""


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


def _ask_claude_vision(image_base64: str, media_type: str) -> list[str]:
    api_key = current_app.config.get("ANTHROPIC_API_KEY")
    if not api_key:
        logger.warning("ANTHROPIC_API_KEY не задан — распознавание скриншота пропущено")
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
                "messages": [{
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {"type": "base64", "media_type": media_type, "data": image_base64},
                        },
                        {"type": "text", "text": CLAUDE_VISION_PROMPT},
                    ],
                }],
            },
            timeout=20,
        )
    except requests.RequestException:
        logger.exception("Ошибка сети при обращении к Claude API (скриншот)")
        return []

    if resp.status_code != 200:
        logger.error("Claude API (скриншот) вернул %s: %s", resp.status_code, resp.text)
        return []

    try:
        data = resp.json()
        raw_text = data["content"][0]["text"]
        match = re.search(r"\{.*\}", raw_text, re.DOTALL)
        parsed = json.loads(match.group(0) if match else raw_text)
        queries = parsed.get("queries", [])
        return [q for q in queries if isinstance(q, str) and q.strip()][:3]
    except (KeyError, IndexError, ValueError, AttributeError, TypeError):
        logger.exception("Не удалось разобрать ответ Claude (скриншот)")
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


def _looks_like_link(text: str) -> bool:
    """Гость вставил ссылку целиком (а не текст, где ссылка — часть фразы)."""
    text = text.strip()
    if not (text.startswith("http://") or text.startswith("https://")):
        return False
    host = urlparse(text).netloc.lower()
    return any(domain in host for domain in LINK_DOMAINS)


def _resolve_link(url: str) -> list[dict]:
    """
    Гость прислал прямую ссылку — значит, он уже точно знает песню, гадать
    не нужно. Название читаем прямо из ссылки официальными бесплатными
    способами (без ключей, см. докстринг файла). Ссылка узнана, но
    прочитать название не вышло (сервис недоступен/ссылка не на конкретный
    трек) — честно возвращаем [], как и остальной файл.
    """
    url = url.strip()
    host = urlparse(url).netloc.lower()

    try:
        if "youtube.com" in host or "youtu.be" in host:
            resp = requests.get(
                "https://www.youtube.com/oembed",
                params={"url": url, "format": "json"},
                timeout=8,
            )
            if resp.status_code != 200:
                logger.error("YouTube oEmbed вернул %s для %s", resp.status_code, url)
                return []
            data = resp.json()
            title = data.get("title")
            if not title:
                return []
            # author_name — это канал на Ютубе, не всегда точно исполнитель
            # песни, но для официальных каналов артистов обычно совпадает.
            return [{"title": title, "artist": data.get("author_name"), "source_url": url}]

        if "open.spotify.com" in host:
            resp = requests.get(
                "https://open.spotify.com/oembed",
                params={"url": url},
                timeout=8,
            )
            if resp.status_code != 200:
                logger.error("Spotify oEmbed вернул %s для %s", resp.status_code, url)
                return []
            data = resp.json()
            title = data.get("title")
            if not title:
                return []
            # Spotify oEmbed отдаёт только название трека, без исполнителя.
            return [{"title": title, "artist": None, "source_url": url}]

        if "music.apple.com" in host or "itunes.apple.com" in host:
            parsed = urlparse(url)
            qs = parse_qs(parsed.query)
            track_id = qs["i"][0] if "i" in qs else None
            if track_id is None:
                # Ссылка не на конкретную песню (?i=...), а на альбом целиком —
                # последний числовой кусок пути тогда id альбома, не песни.
                for part in reversed(parsed.path.split("/")):
                    if part.isdigit():
                        track_id = part
                        break
            if not track_id:
                return []

            resp = requests.get(
                "https://itunes.apple.com/lookup",
                params={"id": track_id},
                timeout=8,
            )
            if resp.status_code != 200:
                logger.error("iTunes lookup вернул %s для %s", resp.status_code, url)
                return []
            results = resp.json().get("results", [])
            if not results:
                return []
            item = results[0]
            title = item.get("trackName") or item.get("collectionName")
            if not title:
                return []
            return [{"title": title, "artist": item.get("artistName"), "source_url": url}]
    except requests.RequestException:
        logger.exception("Ошибка сети при чтении ссылки гостя: %s", url)
        return []

    return []


def screenshot_powered_search(image_base64: str, media_type: str) -> list[dict]:
    """
    Гость прислал скриншот вместо текста (например, из Shazam/Spotify/ВК) —
    Клод по картинке определяет название и исполнителя, дальше поиск идёт
    так же, как при обычном текстовом AI-поиске (ai_powered_search):
    полученный вариант ищется в iTunes. В отличие от текстового поиска
    здесь нет "запасного" текста гостя для честного fallback в iTunes —
    если Клод ничего не разглядел на картинке (нет ключа/ошибка/пустой
    JSON/на скриншоте не оказалось названия песни), результат тоже
    честно пустой [], без выдумывания.
    """
    queries = _ask_claude_vision(image_base64, media_type)
    if not queries:
        return []

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


def ai_powered_search(text: str) -> list[dict]:
    """
    Возвращает от 0 до 5 словарей {title, artist, itunes_url}. Никогда не
    дополняет список выдуманными записями — если найдено меньше, возвращается
    фактическое количество (в т.ч. 0, если ничего не нашлось).

    Если text — это прямая ссылка (Ютуб/Apple Music/Spotify), Клод и
    iTunes-поиск пропускаются — название читается прямо из ссылки
    (_resolve_link), см. докстринг файла.
    """
    text = text.strip()
    if _looks_like_link(text):
        return _resolve_link(text)

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
