"""
Команда /kjpanel — выдаёт KJ ссылку на новую React KJ Panel (ТЗ разделы 11-13).

Отдельный роутер, а не правка существующего handlers/kj.py — минимизирует
риск задеть существующую (полностью рабочую, по ТЗ п.3) логику KJ в самом
Telegram-боте. Существующий способ работы KJ через сообщения бота никуда не
делся; /kjpanel — это просто ещё один вход, для нового процесса с VirtualDJ.
"""
import logging

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

import config
from database import Database
from lang import get_lang, t
import backend_client

router = Router()
db = Database()
logger = logging.getLogger(__name__)


@router.message(Command("kjpanel"))
async def cmd_kj_panel(message: Message):
    lang = await get_lang(message.from_user.id)
    user = await db.get_user(message.from_user.id)

    if not user or user.role > config.ROLE_KJ:
        await message.answer(t(lang, 'error_no_rights'))
        return

    link = backend_client.build_kj_panel_link(message.from_user.id)
    await message.answer(
        "🎛 Ссылка на панель подтверждения заказов (KJ Panel):\n"
        f"{link}\n\n"
        "Ссылка персональная и действует ограниченное время. Не пересылайте её."
    )
