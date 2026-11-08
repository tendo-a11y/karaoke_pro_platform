"""Агент клуба в Telegram-группе.

Бот читает сообщения гостей в группе и отвечает на них от имени бота клуба.
Бот никогда не выдаёт себя за гостя и не придумывает людей.
Ответы включаются переменной AGENT_ENABLED=1. Пока переменной нет, бот только
читает сообщения и записывает в журнал, что видел, ничего не отправляя.
"""
import hashlib
import json
import logging
import os
import urllib.request

from services.telegram_channel_service import CHANNEL_CHAT_ID, TelegramChannelError, _call

logger = logging.getLogger(__name__)

GROUP_USERNAME = CHANNEL_CHAT_ID.lstrip("@")
ESCALATE_MARK = "[ПЕРЕДАТЬ ВЕДУЩЕМУ]"
MAX_REPLY_CHARS = 600
MAX_INPUT_CHARS = 1000
MODEL_DEFAULT = "claude-haiku-5-5"
TRIGGER_WORDS = (
    "цена", "стоит", "сколько", "во сколько", "час", "график", "заказ", "песн",
    "дуэт", "спеть", "спою", "клуб", "скидк", "вип", "баланс", "очеред", "вход",
)

CLUB_KNOWLEDGE = """
Караоке-клуб работает с 20:00 до 05:00, по выходным иногда до 06:00.
Обычная песня караоке стоит 35 лей.
Про вариант с бэк-вокалом (лёгкой подпевкой) цену не называй, такой вопрос передай ведущему.
Заказ песни, которой нет в базе, из интернета — 100 лей.
Песня вне очереди — 1000 лей.
Скидки при заказе 2 или 3 песен есть, но их обсуждает ведущий лично. Цифр скидок не называй.
В базе песен почти все песни мира. Основной репертуар: русские, украинские, молдавские, румынские песни; английские — реже.
"""

SYSTEM_PROMPT = (
    "Ты бот караоке-клуба в Telegram-группе, где общаются гости клуба. "
    "Ты всегда представляешься как бот клуба и никогда не выдаёшь себя за гостя или живого человека. "
    "Отвечай коротко, дружелюбно, по-русски. Используй только сведения из блока ниже. "
    "Если спрашивают про скидки, возвраты, баланс VIP, личные жалобы, оплату или то, чего нет в сведениях, "
    "ответь, что передашь вопрос ведущему, и начни ответ со строки " + ESCALATE_MARK + ". "
    "Ничего не обещай от имени клуба сверх сведений. "
    "Можешь мягко подбодрить гостей спеть вместе или выбрать дуэт, но не навязывайся. "
    "Сведения о клубе: " + CLUB_KNOWLEDGE
)


def _token_value():
    return (os.environ.get("TELEGRAM_BOT_TOKEN") or "").strip()


def webhook_secret():
    token = _token_value()
    if not token:
        raise TelegramChannelError("Токен бота не задан на сервере")
    return hashlib.sha256(("club-agent:" + token).encode("utf-8")).hexdigest()[:48]


def _public_base(url_root):
    domain = (os.environ.get("RAILWAY_PUBLIC_DOMAIN") or "").strip()
    if domain:
        return "https://" + domain
    return url_root.rstrip("/").replace("http://", "https://", 1)


def connect_webhook(url_root):
    base = _public_base(url_root)
    _call("setWebhook", {
        "url": base + "/api/kj/telegram-webhook",
        "secret_token": webhook_secret(),
        "allowed_updates": json.dumps(["message"]),
    })
    info = _call("getWebhookInfo") or {}
    return {
        "url": info.get("url"),
        "pending_update_count": info.get("pending_update_count"),
        "last_error_message": info.get("last_error_message"),
    }


def _looks_worth_answering(text):
    low = text.lower()
    return "?" in text or any(word in low for word in TRIGGER_WORDS)


def _ask_model(question):
    api_key = (os.environ.get("ANTHROPIC_API_KEY") or "").strip()
    if not api_key:
        logger.warning("agent: ANTHROPIC_API_KEY is missing")
        return None
    payload = json.dumps({
        "model": os.environ.get("AGENT_MODEL") or MODEL_DEFAULT,
        "max_tokens": 300,
        "system": SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": question}],
    }).encode("utf-8")
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=payload,
        method="POST",
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except Exception:
        logger.exception("agent: model request failed")
        return None
    parts = body.get("content") or []
    text = "".join(p.get("text", "") for p in parts if p.get("type") == "text").strip()
    return text or None


def handle_update(update):
    message = update.get("message") or {}
    chat = message.get("chat") or {}
    sender = message.get("from") or {}
    text = (message.get("text") or "").strip()
    if not text or sender.get("is_bot"):
        return
    logger.warning("agent saw message chat_id=%s type=%s username=%s", chat.get("id"), chat.get("type"), chat.get("username"))
    if chat.get("username") != GROUP_USERNAME:
        return
    if not _looks_worth_answering(text):
        return
    if os.environ.get("AGENT_ENABLED") != "1":
        logger.warning("agent dry run: would answer this message in the group")
        return
    reply = _ask_model(text[:MAX_INPUT_CHARS])
    if not reply:
        return
    if reply.startswith(ESCALATE_MARK):
        reply = "Передам ваш вопрос ведущему, он ответит лично."
        logger.warning("agent passed a question to the KJ")
    _call("sendMessage", {
        "chat_id": chat["id"],
        "text": reply[:MAX_REPLY_CHARS],
        "disable_web_page_preview": "true",
    })
