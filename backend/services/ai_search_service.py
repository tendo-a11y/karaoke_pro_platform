"""
AI-поиск песни по свободному описанию гостя (Role 3/4/5, аудит-отчёт п.2).

История этого файла (важно для понимания, почему он выглядит именно так):
сначала здесь был Genius (1:1 перенос старого ai_search.py), потом —
iTunes Search API как внешняя проверка "такая песня реально существует".
Обе версии по очереди отказали на одном и том же классе репертуара
(русский шансон, молдавский/румынский фольклор — конкретные живые случаи:
"Рюмка водки" не нашлась у Genius, "Focul din vatră" Иона
Алдя-Теодоровича не нашлась у iTunes ни в одном из проверяемых
магазинов), и каждый раз для гостя это выглядело как "ИИ-поиск сломан",
хотя на самом деле спотыкался не сам ИИ, а внешний каталог, который его
результат подтверждал.

2026-09-17, явное и окончательное решение пользователя: "НЕ СТОИТ НИКОГДА
ИСПОЛЬЗОВАТЬ iTunes И Apple Music". Раньше (до появления Genius/iTunes)
поиск работал по-другому и правильно: Claude сам находил и подтверждал
песню, без сверки по внешней базе. Эта версия возвращает именно такое
поведение.

Текст гостя -> Claude (анализ, определяет 1-3 варианта "исполнитель -
название") -> это и есть окончательный ответ. Никакого стороннего
музыкального каталога здесь больше нет и не должно появляться — ни
Genius, ни iTunes/Apple Music, ни что-либо ему подобное.

Осознанный компромисс от такого решения (проговорено с пользователем):
Claude — теперь единственный источник, и его ответ ничем не
перепроверяется. Значит, он может для редкой/малоизвестной песни назвать
исполнителя или написание не совсем точно, и это не будет отловлено
автоматически, как раньше отлавливалось (если бы каталог песню не
подтвердил). Взамен находится репертуар, которого в принципе нет ни в
одном музыкальном каталоге с лицензионными ограничениями по регионам —
ровно то, ради чего это и попросили вернуть.

Из этого решения прямо следует: ANTHROPIC_API_KEY для этой функции
теперь строго обязателен, а не опционален, как было при iTunes
(раньше без ключа искали хотя бы по исходному тексту гостя напрямую в
iTunes — таким запасным вариантом сейчас разумно пользоваться нельзя,
он и есть тот самый Apple Music, от которого прямо отказались). Без
ключа или при сбое обращения к Claude ИИ-поиск теперь честно возвращает
пустой список — так и должно быть, никакой самодеятельности вместо
настоящего ответа Клода.

Правила, которые важны и здесь сохранены как есть:
  - Максимум 3 варианта от Claude за раз, максимум 5 результатов после
    дедупликации по (title.lower(), artist.lower()). Меньше — показывается
    фактически найденное, никогда не дополняется выдумкой (старое:
    MIN_RESULTS_TARGET=3 объявлена, но не использовалась в реальной логике —
    сюда тоже не переносится, см. аудит, находка №12).
  - Если Claude не смог ничего предложить (нет ключа/ошибка/пустой JSON) —
    честно возвращается [], без фальшивого совпадения на основе сырого
    текста гостя (см. выше, почему raw-fallback здесь больше не годится).

2026-09-17, второе решение пользователя следом за первым (запрос: "а можем
несколько источников поиска сделать и чтоб Клод принимал решение после
результатов всех источников"): версия выше, где Claude вообще ни с чем не
сверяется, полностью честная, но тоже рискует — единственный источник без
подсказки может напутать даже там, где реальный каталог помог бы. Поэтому
добавлены Deezer и MusicBrainz (оба — открытые бесплатные API без ключей,
это НЕ Apple Music/iTunes и явный запрет их не касается) как источники-
ПОДСКАЗКА, а не проверки. Уточняющий вопрос пользователю и его ответы:
источники — "Deezer + MusicBrainz (рекомендую)"; кто решает — "Клод решает
всегда, источники — подсказка (рекомендую)". Это значит: результаты Deezer
и MusicBrainz по вариантам Claude собираются (_gather_catalog_hits) и
передаются самому Claude вторым запросом (_ask_claude_to_decide) вместе с
его же первоначальными вариантами — а решает всё равно Claude, и он прямо
уполномочен ответить из собственного знания, даже если оба каталога
ничего не нашли (ровно так и должно происходить для регионального
репертуара, которого в этих каталогах в принципе нет — то, ради чего всё
это и делалось). Если Claude на первом шаге вообще ничего не предложил —
ни каталоги, ни второй запрос к Claude не вызываются, результат честно [].

Дополнение: гость может вставить в то же самое поле не описание, а прямую
ссылку на Ютуб/Spotify — тогда гадать вообще не нужно, он уже точно
знает песню. В этом случае Claude пропускается полностью, название
читается прямо из самой ссылки (_resolve_link) через официальные
бесплатные способы каждого сервиса, без ключей — открытый oEmbed
(просто отдаёт title/author_name по ссылке на видео/трек). Ссылки на
Apple Music/iTunes сюда сознательно не входят по той же самой причине,
что и выше — сервис нельзя использовать вообще, даже как способ узнать
название по ссылке, которую сам гость вставил. Если ссылка распознана,
но вытащить название не удалось — честно возвращается [], как и везде в
этом файле.

Синхронный перенос (requests вместо aiohttp) — Flask-эндпоинты в этом
backend синхронные, как и остальные внешние вызовы (services/notify.py,
vdj/http_client.py).
"""
import json
import logging
import re
from urllib.parse import urlparse

import requests
from flask import current_app

logger = logging.getLogger(__name__)

MAX_RESULTS = 5

# Apple Music/iTunes сюда сознательно не входят — см. докстринг файла
# (явное решение пользователя 2026-09-17 вообще не использовать этот
# сервис, даже как способ прочитать название по ссылке).
LINK_DOMAINS = ("youtube.com", "youtu.be", "open.spotify.com")

# Типы картинок, которые принимает Claude API (и которых достаточно для
# скриншота из телефона — HEIC на бэкенд не доходит, конвертируется в JPEG
# ещё на фронтенде при сжатии через canvas, см. guest-app/src/App.jsx).
ALLOWED_SCREENSHOT_TYPES = {"image/jpeg", "image/png", "image/webp"}

# 2026-09-17: раньше здесь было "для поиска в базе Apple Music/iTunes" —
# формулировка предполагала, что ответ пойдёт дальше на проверку в каталог.
# Каталога больше нет (см. докстринг файла), этот ответ теперь окончательный
# и его увидит гость напрямую, формулировка обновлена соответственно.
CLAUDE_PROMPT = """Гость караоке-бара описал песню свободным текстом (возможно, с ошибками,
на русском или румынском, без знаков препинания, иногда с посторонним мусором —
например, декоративными символами, скопированными вместе с названием из Ютуба).
Определи, какую песню он имеет в виду. Верни СТРОГО JSON без пояснений в формате:

{{"queries": ["исполнитель - название", "исполнитель2 - название2"]}}

Дай от 1 до 3 наиболее вероятных вариантов "исполнитель - название" — это и есть
окончательный ответ, который увидит гость, дальше он никем и ничем не
перепроверяется, поэтому называй только то, в чём действительно уверен. Если
исполнитель неизвестен — верни только название. Если совсем не удаётся ничего
определить — верни {{"queries": []}}.

Текст гостя: {text}"""

CLAUDE_VISION_PROMPT = """Гость караоке-бара прислал скриншот (например, из Shazam, Spotify,
YouTube Music, ВКонтакте или похожего приложения), где виден плеер или
карточка песни. Найди на картинке название песни и, если видно, исполнителя.
Текст на скриншоте может быть частично обрезан или на разных языках (русский,
румынский, английский). Верни СТРОГО JSON без пояснений в формате:

{"queries": ["исполнитель - название"]}

Дай ровно один наиболее вероятный вариант "исполнитель - название" — это и есть
окончательный ответ, который увидит гость, дальше он никем и ничем не
перепроверяется (или только название, если исполнитель не виден). Если на
картинке вообще не видно ничего похожего на название песни — верни
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
        result = [q for q in queries if isinstance(q, str) and q.strip()][:3]
        # 2026-09-17, запрос пользователя ("проверить саму цепочку поиска —
        # что Клод понял из текста, что вернул каталог, где теряется
        # результат"): без этой записи было невозможно увидеть, чем
        # конкретно закончился разбор текста гостя — сервер отвечал 200 с
        # пустым списком, и не было ни одной зацепки, на каком именно шаге
        # результат терялся.
        logger.info("AI-поиск: текст гостя %r -> Claude предложил варианты %r", text, result)
        return result
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


# Deezer и MusicBrainz — открытые бесплатные API без ключей. Это НЕ
# Apple Music/iTunes: явный запрет пользователя ("НЕ СТОИТ НИКОГДА
# ИСПОЛЬЗОВАТЬ iTunes И Apple Music") их не касается — они используются
# как источник-подсказка для следующего решения Claude, а не как каталог,
# который что-то "подтверждает" или отфильтровывает (см. докстринг файла).
MUSICBRAINZ_USER_AGENT = "KaraokeProPlatform/1.0 (+https://github.com/tendo-a11y/karaoke_pro_platform)"


def _search_deezer(query: str, limit: int = 5) -> list[dict]:
    """Deezer Search API. Публичный, без ключа. Сбой сети/формата — честно
    [], как и остальной файл (это подсказка, а не обязательный источник)."""
    try:
        resp = requests.get(
            "https://api.deezer.com/search",
            params={"q": query, "limit": limit},
            timeout=8,
        )
    except requests.RequestException:
        logger.exception("Ошибка сети при обращении к Deezer: %r", query)
        return []

    if resp.status_code != 200:
        logger.error("Deezer вернул %s для %r", resp.status_code, query)
        return []

    try:
        data = resp.json()
        hits = []
        for item in data.get("data", [])[:limit]:
            title = item.get("title")
            artist = (item.get("artist") or {}).get("name")
            if title:
                hits.append({"title": title, "artist": artist})
        return hits
    except (ValueError, AttributeError, TypeError):
        logger.exception("Не удалось разобрать ответ Deezer для %r", query)
        return []


def _search_musicbrainz(query: str, limit: int = 5) -> list[dict]:
    """MusicBrainz recording search. Публичный, без ключа, но их политика
    использования требует описательный User-Agent (см. MUSICBRAINZ_USER_AGENT
    выше) — без него сервис вправе резать запросы."""
    try:
        resp = requests.get(
            "https://musicbrainz.org/ws/2/recording/",
            params={"query": query, "fmt": "json", "limit": limit},
            headers={"User-Agent": MUSICBRAINZ_USER_AGENT},
            timeout=8,
        )
    except requests.RequestException:
        logger.exception("Ошибка сети при обращении к MusicBrainz: %r", query)
        return []

    if resp.status_code != 200:
        logger.error("MusicBrainz вернул %s для %r", resp.status_code, query)
        return []

    try:
        data = resp.json()
        hits = []
        for item in data.get("recordings", [])[:limit]:
            title = item.get("title")
            artist_credit = item.get("artist-credit") or []
            artist = artist_credit[0].get("name") if artist_credit else None
            if title:
                hits.append({"title": title, "artist": artist})
        return hits
    except (ValueError, AttributeError, TypeError, IndexError, KeyError):
        logger.exception("Не удалось разобрать ответ MusicBrainz для %r", query)
        return []


def _gather_catalog_hits(queries: list[str], limit_per_source: int = 5) -> list[dict]:
    """Опрашивает Deezer и MusicBrainz по всем вариантам Claude и
    дедуплицирует по (title.lower(), artist.lower()). Результат — только
    подсказка для _ask_claude_to_decide, окончательное решение всё равно
    за Claude (см. докстринг файла)."""
    seen = set()
    hits: list[dict] = []
    for query in queries:
        for source_fn in (_search_deezer, _search_musicbrainz):
            for hit in source_fn(query, limit_per_source):
                key = (hit["title"].strip().lower(), (hit.get("artist") or "").strip().lower())
                if key in seen:
                    continue
                seen.add(key)
                hits.append(hit)
    return hits


DECISION_PROMPT = """Гость караоке-бара пытается найти песню. Ты уже проанализировал(а) его
запрос и предложил(а) свои варианты. Дополнительно по этим вариантам
опрошены два открытых музыкальных каталога (Deezer и MusicBrainz) — их
результаты ниже даны как ПОДСКАЗКА, а не как источник истины: если
каталоги ничего не нашли или нашли что-то явно не то, а ты сам(а)
уверен(а) в песне из собственного знания — отвечай из своего знания, это
разрешено и даже ожидается (именно ради редкого регионального
репертуара, которого в этих каталогах в принципе нет, всё так и
устроено). Решение всегда принимаешь ты сам(а).

Исходный запрос гостя: {context}

Твои первоначальные варианты: {guesses}

Результаты каталогов (могут быть пустыми): {catalog_hits}

Верни СТРОГО JSON без пояснений в формате:

{{"results": [{{"title": "название", "artist": "исполнитель или null"}}]}}

От 0 до 3 наиболее вероятных вариантов, отсортированных по убыванию
уверенности. Если ты вообще не уверен(а) ни в одном варианте — верни
{{"results": []}}, не отвечай наугад."""


def _ask_claude_to_decide(context: str, guesses: list[str], catalog_hits: list[dict]) -> list[dict]:
    """Второй, финальный запрос к Claude — уже с его собственными
    первоначальными вариантами и подсказками от Deezer/MusicBrainz.
    Решение остаётся полностью за Claude (см. DECISION_PROMPT и докстринг
    файла — 2026-09-17, явный ответ пользователя "Клод решает всегда,
    источники — подсказка")."""
    api_key = current_app.config.get("ANTHROPIC_API_KEY")
    if not api_key:
        logger.warning("ANTHROPIC_API_KEY не задан — финальное решение пропущено")
        return []

    prompt = DECISION_PROMPT.format(
        context=context,
        guesses=json.dumps(guesses, ensure_ascii=False),
        catalog_hits=json.dumps(catalog_hits, ensure_ascii=False),
    )

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
                "max_tokens": 400,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=10,
        )
    except requests.RequestException:
        logger.exception("Ошибка сети при обращении к Claude API (решение)")
        return []

    if resp.status_code != 200:
        logger.error("Claude API (решение) вернул %s: %s", resp.status_code, resp.text)
        return []

    try:
        data = resp.json()
        raw_text = data["content"][0]["text"]
        match = re.search(r"\{.*\}", raw_text, re.DOTALL)
        parsed = json.loads(match.group(0) if match else raw_text)
        raw_results = parsed.get("results", [])
        results = []
        for item in raw_results:
            if not isinstance(item, dict):
                continue
            title = item.get("title")
            if not isinstance(title, str) or not title.strip():
                continue
            artist = item.get("artist")
            artist = artist.strip() if isinstance(artist, str) and artist.strip() else None
            results.append({"title": title.strip(), "artist": artist})
        logger.info("AI-поиск: финальное решение Claude по вариантам %r и подсказкам каталогов -> %r", guesses, results)
        return results[:3]
    except (KeyError, IndexError, ValueError, AttributeError, TypeError):
        logger.exception("Не удалось разобрать решение Claude")
        return []


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
    except requests.RequestException:
        logger.exception("Ошибка сети при чтении ссылки гостя: %s", url)
        return []

    return []


def screenshot_powered_search(image_base64: str, media_type: str) -> list[dict]:
    """
    Гость прислал скриншот вместо текста (например, из Shazam/Spotify/ВК).
    Пайплайн (см. докстринг файла — второе решение пользователя,
    Deezer+MusicBrainz как подсказка, Claude решает всегда):
      1. Claude по картинке определяет 1-3 варианта "исполнитель - название"
         (_ask_claude_vision). Ничего не разглядел — честно [], дальше
         каталоги и второй запрос к Claude не вызываются (сверять не с чем).
      2. Deezer + MusicBrainz опрашиваются по этим вариантам как подсказка
         (_gather_catalog_hits).
      3. Claude ещё раз, уже видя и свои варианты, и подсказки каталогов,
         принимает окончательное решение (_ask_claude_to_decide) — вправе
         ответить из собственного знания, даже если каталоги ничего не
         нашли.
    """
    guesses = _ask_claude_vision(image_base64, media_type)
    if not guesses:
        return []

    catalog_hits = _gather_catalog_hits(guesses)
    decided = _ask_claude_to_decide("(скриншот, исходного текста нет)", guesses, catalog_hits)

    seen = set()
    results: list[dict] = []
    for item in decided:
        key = (item["title"].strip().lower(), (item.get("artist") or "").strip().lower())
        if key in seen:
            continue
        seen.add(key)
        results.append(item)
        if len(results) >= MAX_RESULTS:
            break
    return results


def ai_powered_search(text: str) -> list[dict]:
    """
    Возвращает от 0 до 5 словарей {title, artist}. Никогда не дополняет
    список выдуманными записями сверх того, что в итоге решил Claude — если
    вариантов меньше, возвращается фактическое количество (в т.ч. 0).

    Если text — это прямая ссылка (Ютуб/Spotify), весь пайплайн ниже
    пропускается — название читается прямо из ссылки (_resolve_link), см.
    докстринг файла.

    Пайплайн (2026-09-17, второе решение пользователя — добавить источники-
    подсказки, но решение оставить полностью за Claude):
      1. Claude по тексту гостя предлагает 1-3 варианта "исполнитель -
         название" (_ask_claude). Ничего не предложил — честно [], дальше
         каталоги и второй запрос к Claude не вызываются.
      2. Deezer + MusicBrainz опрашиваются по этим вариантам как подсказка
         (_gather_catalog_hits) — не как проверка/фильтр.
      3. Claude ещё раз, уже видя и свои первоначальные варианты, и то, что
         нашли каталоги, принимает окончательное решение
         (_ask_claude_to_decide). Вправе ответить из собственного знания,
         даже если оба каталога ничего не нашли — так и должно быть для
         репертуара, которого в этих каталогах в принципе нет.
    """
    text = text.strip()
    if _looks_like_link(text):
        return _resolve_link(text)

    guesses = _ask_claude(text)
    if not guesses:
        logger.info("AI-поиск: текст гостя %r -> Claude не предложил вариантов, итог 0 результатов", text)
        return []

    catalog_hits = _gather_catalog_hits(guesses)
    decided = _ask_claude_to_decide(text, guesses, catalog_hits)

    seen = set()
    results: list[dict] = []
    for item in decided:
        key = (item["title"].strip().lower(), (item.get("artist") or "").strip().lower())
        if key in seen:
            continue
        seen.add(key)
        results.append(item)
        if len(results) >= MAX_RESULTS:
            break

    logger.info(
        "AI-поиск: текст гостя %r -> варианты от Claude %r -> каталоги нашли %d подсказок -> итог %d результат(ов)",
        text, guesses, len(catalog_hits), len(results),
    )
    return results
