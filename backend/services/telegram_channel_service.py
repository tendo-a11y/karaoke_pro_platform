"""Telegram-канал клуба: проверка бота и публикация описания и закреплённого сообщения.

Токен бота берётся из переменной окружения TELEGRAM_BOT_TOKEN (задаётся в Railway)
и нигде не показывается.
"""
import json
import os
import urllib.error
import urllib.parse
import urllib.request

CHANNEL_CHAT_ID = "@voicevocalclub"
DESCRIPTION_MAX = 255
PINNED_MAX = 4096
API_TIMEOUT_SECONDS = 15


class TelegramChannelError(Exception):
    pass


def _call(method, params=None):
    token = (os.environ.get("TELEGRAM_BOT_TOKEN") or "").strip()
    if not token:
        raise TelegramChannelError("Токен бота не задан на сервере")
    url = f"https://api.telegram.org/bot{token}/{method}"
    data = urllib.parse.urlencode(params or {}).encode("utf-8")
    try:
        with urllib.request.urlopen(url, data=data, timeout=API_TIMEOUT_SECONDS) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            body = json.loads(exc.read().decode("utf-8"))
        except Exception:
            raise TelegramChannelError("Telegram вернул ошибку")
    except Exception:
        raise TelegramChannelError("Не удалось связаться с Telegram. Попробуйте ещё раз.")
    if not body.get("ok"):
        raise TelegramChannelError(f"Telegram: {body.get('description') or 'ошибка'}")
    return body.get("result")


def check_bot():
    me = _call("getMe")
    channel = _call("getChat", {"chat_id": CHANNEL_CHAT_ID})
    member = _call("getChatMember", {"chat_id": CHANNEL_CHAT_ID, "user_id": me["id"]})
    return {
        "bot_username": me.get("username"),
        "channel_title": channel.get("title"),
        "bot_status": member.get("status"),
    }


def set_channel_description(text):
    text = (text or "").strip()
    if not text:
        raise TelegramChannelError("Текст описания пустой")
    if len(text) > DESCRIPTION_MAX:
        raise TelegramChannelError(f"Описание длиннее {DESCRIPTION_MAX} символов")
    _call("setChatDescription", {"chat_id": CHANNEL_CHAT_ID, "description": text})


def publish_pinned_message(text):
    text = (text or "").strip()
    if not text:
        raise TelegramChannelError("Текст сообщения пустой")
    if len(text) > PINNED_MAX:
        raise TelegramChannelError(f"Сообщение длиннее {PINNED_MAX} символов")
    sent = _call("sendMessage", {"chat_id": CHANNEL_CHAT_ID, "text": text, "disable_web_page_preview": "true"})
    try:
        _call("pinChatMessage", {"chat_id": CHANNEL_CHAT_ID, "message_id": sent["message_id"], "disable_notification": "true"})
    except TelegramChannelError as exc:
        raise TelegramChannelError(f"Сообщение опубликовано, но закрепить не удалось: {exc}")
    return sent["message_id"]
