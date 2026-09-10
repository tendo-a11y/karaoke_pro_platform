from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import InlineKeyboardButton

from database import Database
from keyboards import client_kb
import utils
import config
from lang import get_lang, t

router = Router()
db = Database()

async def assign_no_table_number(user_id: int, venue_id: int) -> int:
    venue = await db.get_venue(venue_id)
    
    async with db.get_db() as conn:
        start_number = venue.table_count + 1
        
        async with conn.execute(
            """SELECT MAX(table_number) as max_num FROM users 
               WHERE venue_id = ? AND table_number > ?""",
            (venue_id, venue.table_count)
        ) as cursor:
            row = await cursor.fetchone()
            max_num = row[0] if row[0] else start_number - 1
        
        new_number = max_num + 1
        await db.update_user_table(user_id, new_number)
        
        return new_number

@router.message(Command("notable"))
async def cmd_no_table(message: Message):
    user = await db.get_user(message.from_user.id)
    
    if not user:
        lang = await get_lang(message.from_user.id)
        await message.answer(t(lang, 'start_first'))
        return
    
    if user.role != config.ROLE_NO_TABLE:
        lang = await get_lang(message.from_user.id)
        await message.answer(t(lang, 'no_client_access'))
        return
    
    if not user.venue_id:
        venues = await db.get_all_venues()
        if not venues:
            lang = await get_lang(message.from_user.id)
            await message.answer(t(lang, 'no_venues'))
            return
        
        lang = await get_lang(message.from_user.id)
        builder = InlineKeyboardBuilder()
        for venue in venues:
            builder.row(
                InlineKeyboardButton(
                    text=venue.name,
                    callback_data=f"notable_select_venue_{venue.venue_id}"
                )
            )
        
        await message.answer(
            t(lang, 'select_club_notable'),
            reply_markup=builder.as_markup()
        )
        return
    
    if not user.table_number:
        await assign_no_table_number(user.user_id, user.venue_id)
    
    from handlers.client import cmd_client
    from aiogram.fsm.storage.memory import MemoryStorage
    from aiogram.fsm.storage.base import StorageKey
    
    try:
        from bot import storage as bot_storage
    except ImportError:
        bot_storage = MemoryStorage()
    
    state = FSMContext(
        storage=bot_storage,
        key=StorageKey(bot_id=message.bot.id, chat_id=message.chat.id, user_id=message.from_user.id)
    )
    await cmd_client(message, state)

@router.callback_query(F.data.startswith("notable_select_venue_"))
async def notable_select_venue(callback: CallbackQuery):
    venue_id = int(callback.data.split("_")[-1])
    user_id = callback.from_user.id
    
    await db.update_user_role(user_id, config.ROLE_NO_TABLE, venue_id)
    
    table_num = await assign_no_table_number(user_id, venue_id)
    
    venue = await db.get_venue(venue_id)
    lang = await get_lang(callback.from_user.id)
    
    await callback.message.edit_text(
        t(lang, 'notable_venue_selected', venue=venue.name, num=table_num)
    )
    await callback.answer()
