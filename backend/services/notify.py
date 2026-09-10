import logging

import requests
from flask import current_app

logger = logging.getLogger(__name__)


def notify_guest(telegram_user_id: int, text: str) -> None:
    """
    Уведомляет гостя напрямую через Telegram Bot API. Backend вызывает Telegram
    API тем же токеном, что и сам бот, а не идёт через процесс бота — так
    очередь/подтверждение работают, даже если в моменте нет прямого канала к
    процессу aiogram-бота. Ошибка отправки не должна ронять обработку заказа —
    поэтому исключения только логируются.
    """
    token = current_app.config.get("TELEGRAM_BOT_TOKEN")
    if not token:
        logger.warning("TELEGRAM_BOT_TOKEN не задан — уведомление гостю не отправлено: %s", text)
        return

    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": telegram_user_id, "text": text},
            timeout=5,
        )
        if not resp.ok:
            logger.warning(
                "Не удалось отправить уведомление гостю %s: %s %s",
                telegram_user_id, resp.status_code, resp.text,
            )
    except requests.RequestException:
        logger.exception("Ошибка сети при отправке уведомления гостю %s", telegram_user_id)
