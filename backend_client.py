"""
Клиент Telegram-бота для нового Backend API (ТЗ разделы 4, 7, 33).

Используется как ДОПОЛНЕНИЕ к существующей логике заказа, а не замена: заказ
по-прежнему создаётся как раньше в SQLite через database.py, и только
дополнительно, лучшим усилием (best-effort), отправляется в новый Backend
(Flask + PostgreSQL), откуда его увидит React KJ Panel и далее VirtualDJ.
Сбой этого вызова НЕ должен ломать существующий сценарий заказа — поэтому
все ошибки только логируются.
"""
import logging
import os
import time

import aiohttp
import jwt

logger = logging.getLogger(__name__)

BACKEND_API_URL = os.getenv("BACKEND_API_URL", "http://localhost:5000")
BACKEND_INTERNAL_TOKEN = os.getenv("BACKEND_INTERNAL_TOKEN", "change_me_shared_secret")
KJ_PANEL_JWT_SECRET = os.getenv("KJ_PANEL_JWT_SECRET", "change_me_jwt_secret")
KJ_PANEL_URL = os.getenv("KJ_PANEL_URL", "http://localhost:3000")
KJ_JWT_TTL_SECONDS = int(os.getenv("KJ_JWT_TTL_SECONDS", "43200"))


async def post_order_to_backend(telegram_user_id: int, club_id: int, table_no, song_title: str, artist: str) -> None:
    """POST /api/client/order — см. ТЗ п.7. Молча логирует ошибку и не бросает
    исключение наверх, чтобы не портить существующий UX бота."""
    payload = {
        "telegram_user_id": telegram_user_id,
        "club_id": club_id,
        "table_no": table_no,
        "song_title": song_title,
        "artist": artist,
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{BACKEND_API_URL}/api/client/order",
                json=payload,
                headers={"X-Internal-Token": BACKEND_INTERNAL_TOKEN},
                timeout=aiohttp.ClientTimeout(total=5),
            ) as resp:
                if resp.status not in (200, 201):
                    body = await resp.text()
                    logger.warning("backend_client: POST /api/client/order -> %s %s", resp.status, body)
    except (aiohttp.ClientError, TimeoutError):
        logger.exception("backend_client: не удалось связаться с Backend API (заказ остался только в SQLite)")


def build_kj_panel_link(telegram_user_id: int) -> str:
    """
    Выпускает JWT для KJ Panel напрямую в процессе бота — без сетевого
    запроса к Backend (тот же секрет KJ_PANEL_JWT_SECRET прописан у обеих
    сторон, см. .env.example). Используется командой /kjpanel (kj_panel_link.py).
    """
    now = int(time.time())
    payload = {
        "sub": str(telegram_user_id),
        "iat": now,
        "exp": now + KJ_JWT_TTL_SECONDS,
        "type": "kj_panel",
    }
    token = jwt.encode(payload, KJ_PANEL_JWT_SECRET, algorithm="HS256")
    return f"{KJ_PANEL_URL}?token={token}"
