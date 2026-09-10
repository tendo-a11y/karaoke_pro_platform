import asyncio
import html
import logging
from aiogram import Bot, Dispatcher, F, BaseMiddleware
from aiogram.filters import CommandStart
from aiogram.types import Message, InlineQuery, InlineQueryResultArticle, InputTextMessageContent, ChosenInlineResult, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.storage.base import StorageKey

import config
from database import Database
from handlers import admin, kj, vip, client, no_table_client
from keyboards import kj_kb
import utils
import backend_client
from ai_search_handlers import router as ai_search_router
from kj_panel_link import router as kj_panel_router
from lang import get_lang, t

MENU_BTN_RU = "🎵 Меню"
MENU_BTN_RO = "🎵 Meniu"
LANG_BTN_RU = "🌐 Язык"
LANG_BTN_RO = "🌐 Limbă"

ALL_MENU_BTNS = {MENU_BTN_RU, MENU_BTN_RO}
ALL_LANG_BTNS = {LANG_BTN_RU, LANG_BTN_RO}

MENU_BTN = MENU_BTN_RU

def make_main_keyboard(lang: str) -> ReplyKeyboardMarkup:
    menu_text = t(lang, 'menu_btn')
    lang_text = t(lang, 'lang_btn')
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=menu_text), KeyboardButton(text=lang_text)]],
        resize_keyboard=True,
        is_persistent=True
    )

MENU_KEYBOARD = make_main_keyboard('ru')

class FSMCleanupMiddleware(BaseMiddleware):

    async def __call__(self, handler, event: Message, data):
        state: FSMContext = data.get("state")
        should_cleanup = False
        old_prompt_id = None
        old_prompt_chat_id = None

        if state and isinstance(event, Message) and event.text and not event.text.startswith('/') and event.text not in (ALL_MENU_BTNS | ALL_LANG_BTNS):
            current_state = await state.get_state()
            if current_state:
                should_cleanup = True
                try:
                    state_data = await state.get_data()
                    old_prompt_id = state_data.get("_prompt_msg_id")
                    old_prompt_chat_id = state_data.get("_prompt_chat_id", event.chat.id)
                except Exception:
                    pass

        result = await handler(event, data)

        if should_cleanup:
            if old_prompt_id:
                try:
                    await event.bot.delete_message(old_prompt_chat_id, old_prompt_id)
                except Exception:
                    pass

            try:
                await event.delete()
            except Exception:
                pass

        return result

class BlockedUserMiddleware(BaseMiddleware):

    async def __call__(self, handler, event, data):
        user_id = None
        if isinstance(event, Message):
            user_id = event.from_user.id if event.from_user else None
        elif isinstance(event, CallbackQuery):
            user_id = event.from_user.id if event.from_user else None

        if user_id:
            db_user = await db.get_user(user_id)
            if db_user and db_user.is_blocked and db_user.role >= config.ROLE_VIP:
                user_lang = await db.get_user_language(user_id)
                blocked_text = t(user_lang, 'blocked_user')
                try:
                    if isinstance(event, Message):
                        await event.answer(blocked_text)
                    elif isinstance(event, CallbackQuery):
                        await event.answer(blocked_text, show_alert=True)
                except Exception:
                    pass
                return
        return await handler(event, data)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

bot = Bot(token=config.BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

db = Database()

async def _all_tables_full(venue_id: int, table_count: int) -> bool:
    for table_num in range(1, table_count + 1):
        count = await db.get_table_users_count(venue_id, table_num)
        if count < config.MAX_GROUP_SIZE:
            return False
    return True

async def _return_to_user_main_menu(callback: CallbackQuery, user) -> None:
    lang = await get_lang(user.user_id)
    if user.role == config.ROLE_NONE:
        await callback.message.edit_text(t(lang, 'session_ended'))
        return

    if user.role == config.ROLE_VIP:
        from handlers import vip as vip_handler
        await vip_handler.vip_main_menu(callback)
        return

    from handlers import client as client_handler
    await client_handler.client_main_menu(callback)

async def _send_user_main_menu(bot_instance: Bot, user) -> None:
    """Send main menu as a new message (for cases where the original message was deleted)."""
    lang = await get_lang(user.user_id)
    if user.role == config.ROLE_NONE:
        await bot_instance.send_message(user.user_id, t(lang, 'session_ended'))
        return

    venue = await db.get_venue(user.venue_id)
    if not venue:
        return
    is_no_table = user.role == config.ROLE_NO_TABLE
    admin_user_id = await db.get_table_admin_user_id(user.venue_id, user.table_number) if not is_no_table else None
    show_table_admin = (not is_no_table) and (admin_user_id == user.user_id)

    if user.role == config.ROLE_VIP:
        from keyboards import vip_kb
        vip = await db.get_vip_client(user.user_id, user.venue_id)
        await bot_instance.send_message(
            user.user_id,
            t(lang, 'choose_action'),
            reply_markup=vip_kb.get_vip_main_menu(show_table_admin, venue.chat_enabled, venue.chat_link, lang),
            parse_mode="HTML"
        )
    else:
        from keyboards import client_kb
        await bot_instance.send_message(
            user.user_id,
            t(lang, 'choose_action'),
            reply_markup=client_kb.get_client_main_menu(show_table_admin, venue.chat_enabled, venue.chat_link, lang),
            parse_mode="HTML"
        )

@dp.message(CommandStart())
async def cmd_start(message: Message):
    user = await db.get_user(message.from_user.id)
    lang = await get_lang(message.from_user.id)
    
    args = message.text.split(maxsplit=1)
    deeplink_param = args[1] if len(args) > 1 else None
    
    if deeplink_param and deeplink_param.startswith("venue"):
        try:
            parts = deeplink_param.replace("venue", "").split("_table")
            venue_id = int(parts[0])
            table_number = int(parts[1]) if len(parts) > 1 else None
            
            venue = await db.get_venue(venue_id)
            if venue:
                if not user:
                    await db.create_user(
                        user_id=message.from_user.id,
                        username=message.from_user.username,
                        first_name=message.from_user.first_name,
                        role=config.ROLE_USER
                    )
                    user = await db.get_user(message.from_user.id)
                
                await db.update_user_venue(user.user_id, venue_id)
                
                if user.role == config.ROLE_NONE:
                    vip = await db.get_vip_client(user.user_id, venue_id)
                    if vip:
                        await db.update_user_role(user.user_id, config.ROLE_VIP, venue_id)
                    else:
                        await db.update_user_role(user.user_id, config.ROLE_USER, venue_id)
                    user = await db.get_user(user.user_id)
                
                if table_number and table_number <= venue.table_count:
                    if user.table_number == table_number:
                        await message.answer(
                            t(lang, 'venue_attached', venue=venue.name, table=table_number)
                        )

                        if user.role == config.ROLE_VIP:
                            from handlers import vip as vip_handler
                            await vip_handler.cmd_vip(message)
                        else:
                            from handlers import client as client_handler
                            state = FSMContext(
                                storage=storage,
                                key=StorageKey(bot_id=bot.id, chat_id=message.chat.id, user_id=message.from_user.id)
                            )
                            await client_handler.cmd_client(message, state)
                        return

                    admin_user_id = await db.get_table_admin_user_id(venue_id, table_number)

                    if not admin_user_id:
                        await db.update_table_number(user.user_id, table_number)
                        await db.set_table_admin(venue_id, table_number, user.user_id)

                        await message.answer(
                            t(lang, 'venue_attached_admin', venue=venue.name, table=table_number)
                        )

                        if user.role == config.ROLE_VIP:
                            from handlers import vip as vip_handler
                            await vip_handler.cmd_vip(message)
                        else:
                            from handlers import client as client_handler
                            state = FSMContext(
                                storage=storage,
                                key=StorageKey(bot_id=bot.id, chat_id=message.chat.id, user_id=message.from_user.id)
                            )
                            await client_handler.cmd_client(message, state)
                        return

                    users_count = await db.get_table_users_count(venue_id, table_number)
                    if users_count >= config.MAX_GROUP_SIZE:
                        if await _all_tables_full(venue_id, venue.table_count):
                            no_tbl_builder = InlineKeyboardBuilder()
                            no_tbl_builder.row(
                                InlineKeyboardButton(text=t(lang, 'btn_no_table_confirm'), callback_data=f"no_table_confirm_{venue_id}"),
                                InlineKeyboardButton(text=t(lang, 'btn_no_table_cancel'), callback_data="no_table_cancel")
                            )
                            await message.answer(
                                t(lang, 'all_tables_full', venue=html.escape(venue.name)),
                                reply_markup=no_tbl_builder.as_markup(),
                                parse_mode="HTML"
                            )
                        else:
                            tbl_builder = InlineKeyboardBuilder()
                            tbl_buttons = [
                                InlineKeyboardButton(text=str(i), callback_data=f"join_table_{venue_id}_{i}")
                                for i in range(1, venue.table_count + 1)
                            ]
                            for i in range(0, len(tbl_buttons), 5):
                                tbl_builder.row(*tbl_buttons[i:i+5])
                            await message.answer(
                                t(lang, 'table_full_choose', venue=html.escape(venue.name), table=table_number),
                                reply_markup=tbl_builder.as_markup(),
                                parse_mode="HTML"
                            )
                        return

                    has_pending = await db.has_pending_table_join_request(venue_id, table_number, user.user_id)
                    if not has_pending:
                        request_id = await db.create_table_join_request(venue_id, table_number, user.user_id)
                    else:
                        request_id = await db.get_pending_table_join_request_id(venue_id, table_number, user.user_id)

                    if request_id:
                        try:
                            admin_user = await db.get_user(admin_user_id)
                            if admin_user:
                                admin_lang = await get_lang(admin_user.user_id)
                                builder = InlineKeyboardBuilder()
                                builder.row(
                                    InlineKeyboardButton(
                                        text=t(admin_lang, 'btn_confirm'),
                                        callback_data=f"table_join_approve_{request_id}"
                                    ),
                                    InlineKeyboardButton(
                                        text=t(admin_lang, 'btn_reject'),
                                        callback_data=f"table_join_reject_{request_id}"
                                    )
                                )
                                user_name = message.from_user.first_name or "?"
                                user_username = message.from_user.username or "нет"
                                await bot.send_message(
                                    admin_user.user_id,
                                    t(admin_lang, 'table_join_request_msg', table=table_number, name=user_name, username=user_username),
                                    reply_markup=builder.as_markup()
                                )
                                await utils.send_user_menu(bot, admin_user.user_id)
                        except Exception as e:
                            logger.error("Не удалось отправить уведомление админу стола: %s", e)

                    await message.answer(t(lang, 'join_request_sent'))
                    return
                else:
                    builder = InlineKeyboardBuilder()
                    buttons = [
                        InlineKeyboardButton(text=str(i), callback_data=f"join_table_{venue_id}_{i}")
                        for i in range(1, venue.table_count + 1)
                    ]
                    for i in range(0, len(buttons), 5):
                        builder.row(*buttons[i:i+5])
                    await message.answer(
                        t(lang, 'select_table', venue=html.escape(venue.name)),
                        reply_markup=builder.as_markup(),
                        parse_mode="HTML"
                    )
                    return
        except Exception as e:
            logger.exception("Ошибка обработки deep link '%s': %s", deeplink_param, e)
    
    if not user:
        await db.create_user(
            user_id=message.from_user.id,
            username=message.from_user.username,
            first_name=message.from_user.first_name,
            role=config.ROLE_USER
        )
        lang = await get_lang(message.from_user.id)
        
        if message.from_user.id == config.ADMIN_ID:
            await db.update_user_role(message.from_user.id, config.ROLE_ADMIN)
            await message.answer(
                t(lang, 'welcome_new', name=message.from_user.first_name),
                reply_markup=make_main_keyboard(lang)
            )
            from handlers import admin as admin_handler
            await admin_handler.cmd_admin(message)
            return
        else:
            await message.answer(
                t(lang, 'welcome_new', name=message.from_user.first_name),
                reply_markup=make_main_keyboard(lang)
            )
            from handlers import client as client_handler
            state = FSMContext(
                storage=storage,
                key=StorageKey(bot_id=bot.id, chat_id=message.chat.id, user_id=message.from_user.id)
            )
            await client_handler.cmd_client(message, state)
            return
    
    if user.role == config.ROLE_NONE:
        if user.venue_id:
            vip = await db.get_vip_client(user.user_id, user.venue_id)
            if vip:
                await db.update_user_role(user.user_id, config.ROLE_VIP, user.venue_id)
            else:
                await db.update_user_role(user.user_id, config.ROLE_USER, user.venue_id)
        else:
            await db.update_user_role(user.user_id, config.ROLE_USER, None)
        user = await db.get_user(user.user_id)
    
    kbd = make_main_keyboard(lang)
    if user.role == config.ROLE_ADMIN:
        from handlers import admin as admin_handler
        await message.answer(t(lang, 'menu_btn'), reply_markup=kbd)
        await admin_handler.cmd_admin(message)
    elif user.role == config.ROLE_KJ:
        from handlers import kj as kj_handler
        await message.answer(t(lang, 'menu_btn'), reply_markup=kbd)
        await kj_handler.cmd_kj(message)
    elif user.role == config.ROLE_VIP:
        from handlers import vip as vip_handler
        await message.answer(t(lang, 'menu_btn'), reply_markup=kbd)
        await vip_handler.cmd_vip(message)
    elif user.role == config.ROLE_NO_TABLE:
        from handlers import client as client_handler
        await message.answer(t(lang, 'menu_btn'), reply_markup=kbd)
        state = FSMContext(
            storage=storage,
            key=StorageKey(bot_id=bot.id, chat_id=message.chat.id, user_id=message.from_user.id)
        )
        await client_handler.cmd_client(message, state)
    else:
        from handlers import client as client_handler
        await message.answer(t(lang, 'menu_btn'), reply_markup=kbd)
        state = FSMContext(
            storage=storage,
            key=StorageKey(bot_id=bot.id, chat_id=message.chat.id, user_id=message.from_user.id)
        )
        await client_handler.cmd_client(message, state)

@dp.message(F.text.in_(ALL_MENU_BTNS))
async def menu_button_handler(message: Message, state: FSMContext):
    await state.clear()
    await cmd_start(message)

@dp.message(F.text.in_(ALL_LANG_BTNS))
async def lang_button_handler(message: Message):
    lang = await get_lang(message.from_user.id)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t(lang, 'lang_ru'), callback_data='lang_set_ru'),
         InlineKeyboardButton(text=t(lang, 'lang_ro'), callback_data='lang_set_ro')]
    ])
    await message.answer(t(lang, 'lang_title'), reply_markup=kb, parse_mode='Markdown')

@dp.callback_query(F.data == 'lang_set_ru')
async def lang_set_ru(callback: CallbackQuery):
    await db.set_user_language(callback.from_user.id, 'ru')
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.answer(t('ru', 'lang_changed_ru'), show_alert=False)
    await callback.message.answer(t('ru', 'lang_changed_ru'), reply_markup=make_main_keyboard('ru'))

@dp.callback_query(F.data == 'lang_set_ro')
async def lang_set_ro(callback: CallbackQuery):
    await db.set_user_language(callback.from_user.id, 'ro')
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.answer(t('ro', 'lang_changed_ro'), show_alert=False)
    await callback.message.answer(t('ro', 'lang_changed_ro'), reply_markup=make_main_keyboard('ro'))

@dp.callback_query(F.data.startswith("no_table_confirm_"))
async def no_table_confirm(callback: CallbackQuery):
    venue_id = int(callback.data.split("_")[3])
    user = await db.get_user(callback.from_user.id)
    venue = await db.get_venue(venue_id)
    lang = await get_lang(callback.from_user.id)

    if not user or not venue:
        await callback.answer(t(lang, 'error_data'), show_alert=True)
        return

    await db.update_user_role(user.user_id, config.ROLE_NO_TABLE, venue_id)
    from handlers.no_table_client import assign_no_table_number
    table_num = await assign_no_table_number(user.user_id, venue_id)

    await callback.message.edit_text(
        t(lang, 'no_table_joined', venue=html.escape(venue.name), num=table_num),
        parse_mode="HTML"
    )
    await callback.answer()

@dp.callback_query(F.data == "no_table_cancel")
async def no_table_cancel(callback: CallbackQuery):
    lang = await get_lang(callback.from_user.id)
    await callback.message.edit_text(t(lang, 'no_table_cancelled'))
    await callback.answer()

@dp.callback_query(F.data.startswith("join_table_"))
async def join_table_callback(callback: CallbackQuery):
    parts = callback.data.split("_")
    venue_id = int(parts[2])
    table_number = int(parts[3])

    user = await db.get_user(callback.from_user.id)
    venue = await db.get_venue(venue_id)
    lang = await get_lang(callback.from_user.id)

    if not user or not venue:
        await callback.answer(t(lang, 'error_data'), show_alert=True)
        return

    if user.table_number == table_number:
        await callback.answer(t(lang, 'already_at_table', table=table_number), show_alert=True)
        if user.role == config.ROLE_VIP:
            from handlers import vip as vip_handler
            await vip_handler.vip_main_menu(callback)
        else:
            from handlers import client as client_handler
            await client_handler.client_main_menu(callback)
        return

    admin_user_id = await db.get_table_admin_user_id(venue_id, table_number)

    if not admin_user_id:
        await db.update_table_number(user.user_id, table_number)
        await db.set_table_admin(venue_id, table_number, user.user_id)
        await callback.answer(t(lang, 'table_selected', table=table_number), show_alert=True)
        if user.role == config.ROLE_VIP:
            from handlers import vip as vip_handler
            await vip_handler.vip_main_menu(callback)
        else:
            from handlers import client as client_handler
            await client_handler.client_main_menu(callback)
        return

    users_count = await db.get_table_users_count(venue_id, table_number)
    if users_count >= config.MAX_GROUP_SIZE:
        if await _all_tables_full(venue_id, venue.table_count):
            no_tbl_builder = InlineKeyboardBuilder()
            no_tbl_builder.row(
                InlineKeyboardButton(text=t(lang, 'btn_no_table_confirm'), callback_data=f"no_table_confirm_{venue_id}"),
                InlineKeyboardButton(text=t(lang, 'btn_no_table_cancel'), callback_data="no_table_cancel")
            )
            await callback.message.edit_text(
                t(lang, 'all_tables_full', venue=html.escape(venue.name)),
                reply_markup=no_tbl_builder.as_markup(),
                parse_mode="HTML"
            )
        else:
            await callback.answer(t(lang, 'table_full_choose', venue='', table=table_number).split('❌')[0] + '❌ ' + str(table_number), show_alert=True)
        return

    has_pending = await db.has_pending_table_join_request(venue_id, table_number, user.user_id)
    if not has_pending:
        request_id = await db.create_table_join_request(venue_id, table_number, user.user_id)
    else:
        request_id = await db.get_pending_table_join_request_id(venue_id, table_number, user.user_id)

    if request_id:
        try:
            admin_user = await db.get_user(admin_user_id)
            if admin_user:
                admin_lang = await get_lang(admin_user.user_id)
                req_builder = InlineKeyboardBuilder()
                req_builder.row(
                    InlineKeyboardButton(text=t(admin_lang, 'btn_confirm'), callback_data=f"table_join_approve_{request_id}"),
                    InlineKeyboardButton(text=t(admin_lang, 'btn_reject'), callback_data=f"table_join_reject_{request_id}")
                )
                await callback.bot.send_message(
                    admin_user.user_id,
                    t(admin_lang, 'table_join_request_msg',
                      table=table_number,
                      name=html.escape(callback.from_user.first_name or '?'),
                      username=callback.from_user.username or 'n/a'),
                    reply_markup=req_builder.as_markup()
                )
                await utils.send_user_menu(callback.bot, admin_user.user_id)
        except Exception as e:
            logger.error("join_table: не удалось уведомить админа стола: %s", e)

    await callback.answer(t(lang, 'join_request_sent'), show_alert=True)

@dp.inline_query()
async def inline_search(inline_query: InlineQuery):
    logger.info("INLINE_QUERY from=%s query=%r", inline_query.from_user.id, inline_query.query)
    query = inline_query.query.strip()
    
    if not query or len(query) < 1:
        await inline_query.answer([])
        return
    
    user = await db.get_user(inline_query.from_user.id)
    if not user or not user.venue_id:
        await inline_query.answer([])
        return

    kj_table_number = None
    kj_query = None
    replace_order_id = None
    replace_query = None
    
    if query.lower().startswith("kj:"):
        parts = query[3:].strip().split(maxsplit=1)
        if parts and parts[0].isdigit() and user.role <= config.ROLE_KJ:
            kj_table_number = int(parts[0])
            kj_query = parts[1] if len(parts) > 1 else ""
    elif query.lower().startswith("replace:"):
        parts = query[8:].strip().split(maxsplit=1)
        if parts and parts[0].isdigit():
            replace_order_id = int(parts[0])
            replace_query = parts[1] if len(parts) > 1 else ""

    if kj_table_number is not None:
        query = kj_query.strip()
        if not query:
            await inline_query.answer([])
            return
    elif replace_order_id is not None:
        query = replace_query.strip()
        if not query:
            await inline_query.answer([])
            return

    songs = await db.search_songs(user.venue_id, query, limit=50)
    logger.info("INLINE_QUERY results=%s venue_id=%s", len(songs), user.venue_id)
    
    results = []
    for song in songs[:50]:
        if hasattr(song, "keys"):
            artist = song["artist"] if "artist" in song.keys() and song["artist"] else ""
            title = song["title"] if "title" in song.keys() and song["title"] else "Без названия"
            song_id = song["song_id"]
        else:
            artist = getattr(song, "artist", "") or getattr(song, "artist_name", "") or ""
            title = getattr(song, "title", None) or "Без названия"
            song_id = getattr(song, "song_id")
        
        display_name = f"{artist} - {title}" if artist else title
        if not display_name.strip():
            continue
        
        if kj_table_number is not None:
            callback_data = f"inline_pick_kj_{kj_table_number}_{song_id}"
        elif replace_order_id is not None:
            callback_data = f"inline_pick_replace_{replace_order_id}_{song_id}"
        else:
            callback_data = f"inline_pick_{song_id}"

        results.append(
            InlineQueryResultArticle(
                id=str(song_id),
                title=display_name[:100],
                description=artist or "Песня",
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=[
                        [
                            InlineKeyboardButton(text="❌ Отмена", callback_data="inline_cancel"),
                            InlineKeyboardButton(text="✅ Выбрать", callback_data=callback_data)
                        ]
                    ]
                ),
                input_message_content=InputTextMessageContent(
                    message_text=f"🎵 {display_name}"
                )
            )
        )
    
    await inline_query.answer(results, cache_time=10)

async def _song_display_name(song) -> str:
    if hasattr(song, "keys"):
        artist = song["artist"] if "artist" in song.keys() and song["artist"] else ""
        title = song["title"] if "title" in song.keys() and song["title"] else "Без названия"
    else:
        artist = getattr(song, "artist", "") or getattr(song, "artist_name", "") or ""
        title = getattr(song, "title", None) or "Без названия"
    return f"{artist} - {title}" if artist else title

async def _send_service_menu(user, song_id: int, bot: Bot) -> None:
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    from aiogram.types import InlineKeyboardButton

    lang = await get_lang(user.user_id)
    song = await db.get_song(song_id)
    logger.info("SONG_PICK song_found=%s song_id=%s", bool(song), song_id)
    if not song:
        await bot.send_message(user.user_id, t(lang, 'song_not_found'))
        await utils.send_user_menu(bot, user.user_id)
        return

    services = await db.get_venue_services(user.venue_id)
    logger.info("SONG_PICK services_count=%s venue_id=%s", len(services), user.venue_id)
    if not services:
        await bot.send_message(user.user_id, t(lang, 'no_services'))
        await utils.send_user_menu(bot, user.user_id)
        return

    venue = await db.get_venue(user.venue_id)
    import aiosqlite
    async with db.get_db() as db_conn:
        async with db_conn.execute(
            "SELECT COUNT(*) FROM orders WHERE venue_id = ? AND table_number = ? AND user_id = ? AND status IN ('pending', 'waiting')",
            (user.venue_id, user.table_number, user.user_id)
        ) as cursor:
            orders_count = (await cursor.fetchone())[0]

    if orders_count >= config.MAX_ACTIVE_SONGS_PER_USER:
        await bot.send_message(
            user.user_id,
            t(lang, 'order_limit_reached', limit=config.MAX_ACTIVE_SONGS_PER_USER)
        )
        await utils.send_user_menu(bot, user.user_id)
        return

    vip = await db.get_vip_client(user.user_id, user.venue_id)

    builder = InlineKeyboardBuilder()
    service_desc_lines = []
    for service in services:
        price_text = t(lang, 'btn_free') if service.is_free else f"{service.price} MDL"
        desc = f" — {html.escape(service.description)}" if service.description else ""
        service_desc_lines.append(f"• <b>{html.escape(service.name)}</b> ({price_text}){desc}")
        builder.row(
            InlineKeyboardButton(
                text=f"{service.name} - {price_text}",
                callback_data=f"select_service_{service.service_id}_{song_id}"
            )
        )

    song_display_name = await _song_display_name(song)
    services_text = "\n".join(service_desc_lines)
    balance_line = t(lang, 'balance_line', balance=int(vip.balance)) if (vip and user.role == config.ROLE_VIP) else ""
    try:
        await bot.send_message(
            user.user_id,
            t(lang, 'choose_service_title', balance_line=balance_line) + t(lang, 'choose_service_body', services=services_text),
            reply_markup=builder.as_markup(),
            parse_mode="HTML"
        )
        logger.info("SONG_PICK sent service menu to user_id=%s", user.user_id)
    except Exception as exc:
        logger.exception("SONG_PICK failed to send service menu: %s", exc)

async def _send_kj_service_menu(user, table_number: int, song_id: int, bot: Bot) -> None:
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    from aiogram.types import InlineKeyboardButton

    lang = await get_lang(user.user_id)
    song = await db.get_song(song_id)
    logger.info("KJ_SONG_PICK song_found=%s song_id=%s", bool(song), song_id)
    if not song:
        await bot.send_message(user.user_id, t(lang, 'song_not_found'))
        return

    services = await db.get_venue_services(user.venue_id)
    if not services:
        await bot.send_message(user.user_id, "❌ В клубе нет доступных услуг")
        return

    venue = await db.get_venue(user.venue_id)
    import aiosqlite
    async with db.get_db() as db_conn:
        async with db_conn.execute(
            "SELECT COUNT(*) FROM orders WHERE venue_id = ? AND table_number = ? AND status IN ('pending', 'waiting')",
            (user.venue_id, table_number)
        ) as cursor:
            orders_count = (await cursor.fetchone())[0]

    builder = InlineKeyboardBuilder()
    for service in services:
        price_text = t(lang, 'btn_free') if service.is_free else f"{service.price} MDL"
        builder.row(
            InlineKeyboardButton(
                text=f"{service.name} - {price_text}",
                callback_data=f"kj_add_service_{table_number}_{song_id}_{service.service_id}"
            )
        )

    builder.row(
        InlineKeyboardButton(text=t(lang, 'btn_back'), callback_data=f"queue_table_{table_number}")
    )

    song_display_name = await _song_display_name(song)
    try:
        await bot.send_message(
            user.user_id,
            t(lang, 'choose_service_title', balance_line='') + t(lang, 'choose_service_body', services=html.escape(song_display_name)),
            reply_markup=builder.as_markup(),
            parse_mode="HTML"
        )
        logger.info("KJ_SONG_PICK sent service menu to user_id=%s", user.user_id)
    except Exception as exc:
        logger.exception("KJ_SONG_PICK failed to send service menu: %s", exc)

@dp.chosen_inline_result()
async def chosen_inline_result(chosen: ChosenInlineResult):
    logger.info("CHOSEN_INLINE from=%s result_id=%s (ignored, using inline_pick)", chosen.from_user.id, chosen.result_id)
    return

@dp.callback_query(F.data.startswith("inline_pick_") & ~F.data.startswith("inline_pick_kj_") & ~F.data.startswith("inline_pick_replace_"))
async def inline_pick_song(callback: CallbackQuery):
    logger.info("INLINE_PICK callback=%s from=%s", callback.data, callback.from_user.id)
    song_id = int(callback.data.split("_")[2])
    user = await db.get_user(callback.from_user.id)
    lang = await get_lang(callback.from_user.id)
    if not user or not user.venue_id or not user.table_number:
        await callback.answer(t(lang, 'error_not_found'), show_alert=True)
        return

    try:
        if callback.inline_message_id:
            await callback.bot.edit_message_reply_markup(
                inline_message_id=callback.inline_message_id,
                reply_markup=None
            )
        elif callback.message:
            await callback.message.edit_reply_markup(reply_markup=None)
    except Exception as exc:
        logger.exception("INLINE_PICK failed to remove markup: %s", exc)

    await _send_service_menu(user, song_id, callback.bot)
    await callback.answer()

@dp.callback_query(F.data.startswith("inline_pick_kj_"))
async def inline_pick_song_kj(callback: CallbackQuery):
    logger.info("INLINE_PICK_KJ callback=%s from=%s", callback.data, callback.from_user.id)
    parts = callback.data.split("_")
    table_number = int(parts[3])
    song_id = int(parts[4])

    user = await db.get_user(callback.from_user.id)
    if not user or user.role > config.ROLE_KJ or not user.venue_id:
        await callback.answer("❌ Нет прав для добавления заказа", show_alert=True)
        return

    try:
        if callback.inline_message_id:
            await callback.bot.edit_message_reply_markup(
                inline_message_id=callback.inline_message_id,
                reply_markup=None
            )
        elif callback.message:
            await callback.message.edit_reply_markup(reply_markup=None)
    except Exception as exc:
        logger.exception("INLINE_PICK_KJ failed to remove markup: %s", exc)

    await _send_kj_service_menu(user, table_number, song_id, callback.bot)
    await callback.answer()

@dp.callback_query(F.data.startswith("inline_pick_replace_"))
async def inline_pick_song_replace(callback: CallbackQuery, state: FSMContext):
    logger.info("INLINE_PICK_REPLACE callback=%s from=%s", callback.data, callback.from_user.id)
    parts = callback.data.split("_")
    order_id = int(parts[3])
    song_id = int(parts[4])

    user = await db.get_user(callback.from_user.id)
    if not user or not user.venue_id:
        lang = await get_lang(callback.from_user.id)
        await callback.answer(t(lang, 'error_no_rights'), show_alert=True)
        return

    try:
        if callback.inline_message_id:
            await callback.bot.edit_message_reply_markup(
                inline_message_id=callback.inline_message_id,
                reply_markup=None
            )
        elif callback.message:
            await callback.message.edit_reply_markup(reply_markup=None)
    except Exception as exc:
        logger.exception("INLINE_PICK_REPLACE failed to remove markup: %s", exc)

    song = await db.get_song(song_id)
    lang = await get_lang(callback.from_user.id)
    if not song:
        await callback.answer(t(lang, 'song_not_found'), show_alert=True)
        return

    song_name = await _song_display_name(song)

    services = await db.get_venue_services(user.venue_id)
    svc_builder = InlineKeyboardBuilder()
    for svc in services:
        price_text = t(lang, 'btn_free') if svc.is_free else f"{svc.price} MDL"
        svc_builder.row(InlineKeyboardButton(
            text=f"{svc.name} - {price_text}",
            callback_data=f"replace_svc_{order_id}_{song_id}_{svc.service_id}"
        ))
    svc_builder.row(InlineKeyboardButton(text=t(lang, 'btn_cancel'), callback_data="replace_cancel"))

    target_chat = user.user_id
    try:
        data = await state.get_data()
        prompt_message_id = data.get("replace_prompt_message_id")
        prompt_chat_id = data.get("replace_prompt_chat_id")
        if prompt_chat_id:
            target_chat = prompt_chat_id
    except Exception:
        pass

    await callback.bot.send_message(
        target_chat,
        t(lang, 'replace_title'),
        reply_markup=svc_builder.as_markup(),
        parse_mode="HTML"
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("replace_svc_"))
async def replace_svc_execute(callback: CallbackQuery, state: FSMContext):
    parts = callback.data.split("_")
    order_id = int(parts[2])
    song_id = int(parts[3])
    service_id = int(parts[4])

    lang = await get_lang(callback.from_user.id)
    user = await db.get_user(callback.from_user.id)
    if not user or not user.venue_id:
        await callback.answer("❌ Нет прав", show_alert=True)
        return

    import aiosqlite as _sl
    async with db.get_db() as db_conn:
        db_conn.row_factory = _sl.Row
        async with db_conn.execute("SELECT * FROM orders WHERE order_id = ?", (order_id,)) as cur:
            order = await cur.fetchone()

    if not order:
        await callback.answer("❌ Заказ не найден", show_alert=True)
        return

    song = await db.get_song(song_id)
    if not song:
        await callback.answer("❌ Песня не найдена", show_alert=True)
        return

    song_name = await _song_display_name(song)
    old_song_name = order["song_name"]

    service = await db.get_service(service_id)
    if service and not service.is_free:
        vip = await db.get_vip_client(user.user_id, user.venue_id)
        if vip and vip.balance < service.price:
            await callback.answer(
                f"❌ Недостаточно средств\nБаланс: {int(vip.balance)} MDL\nТребуется: {int(service.price)} MDL",
                show_alert=True
            )
            return

    async with db.get_db() as db_conn:
        await db_conn.execute(
            "UPDATE orders SET song_name = ?, service_id = ? WHERE order_id = ?",
            (song_name, service_id, order_id)
        )
        await db_conn.commit()

    logger.info("replace_svc: order_id=%s song=%r service=%s", order_id, song_name, service_id)

    try:
        kj_user = await db.get_kj_by_venue(user.venue_id)
        if kj_user:
            client_user = await db.get_user(order["user_id"])
            client_name = html.escape(client_user.first_name if client_user else "Клиент")
            svc_name = service.name if service else ""
            await callback.bot.send_message(
                kj_user.user_id,
                f"🔄 <b>Замена песни</b>\n\n"
                f"🪑 Стол: {order['table_number']}\n"
                f"👤 {client_name}\n"
                f"🎵 Было: {html.escape(old_song_name)}\n"
                f"🎵 Стало: {html.escape(song_name)}\n"
                f"💼 Услуга: {html.escape(svc_name)}",
                parse_mode="HTML"
            )
    except Exception as exc:
        logger.exception("replace_svc KJ notify failed: %s", exc)

    try:
        await callback.message.delete()
    except Exception:
        pass

    try:
        data = await state.get_data()
        prompt_message_id = data.get("replace_prompt_message_id")
        prompt_chat_id = data.get("replace_prompt_chat_id")
        if prompt_message_id and prompt_chat_id:
            await callback.bot.delete_message(prompt_chat_id, prompt_message_id)
            await state.update_data(replace_prompt_message_id=None, replace_prompt_chat_id=None)
    except Exception:
        pass

    await callback.answer(t(lang, 'order_created'), show_alert=True)

    try:
        order_user_id = order["user_id"]
        if order_user_id != user.user_id:
            order_user_lang = await get_lang(order_user_id)
            await callback.bot.send_message(
                order_user_id,
                f"🔄 <b>{html.escape(song_name)}</b>",
                parse_mode="HTML"
            )
            await utils.send_user_menu(callback.bot, order_user_id)
    except Exception:
        pass

    # After replacement, stay in "My orders" section
    if user.role == config.ROLE_VIP:
        from handlers.vip import vip_my_orders
        await vip_my_orders(callback)
    else:
        from handlers.client import client_my_orders
        await client_my_orders(callback)

@dp.callback_query(F.data == "replace_cancel")
async def replace_cancel_handler(callback: CallbackQuery):
    lang = await get_lang(callback.from_user.id)
    try:
        await callback.message.delete()
    except Exception:
        pass
    await callback.answer(t(lang, 'action_cancelled'))

@dp.callback_query(F.data == "inline_cancel")
async def inline_cancel(callback: CallbackQuery):

    try:
        if callback.inline_message_id:
            await callback.bot.edit_message_reply_markup(
                inline_message_id=callback.inline_message_id,
                reply_markup=None
            )
        elif callback.message:
            await callback.message.edit_reply_markup(reply_markup=None)
    except Exception as exc:
        logger.exception("INLINE_CANCEL failed to remove markup: %s", exc)
    await callback.answer("Отменено")

@dp.callback_query(F.data.startswith("table_join_approve_"))
async def table_join_approve(callback: CallbackQuery):
    request_id = int(callback.data.split("_")[3])
    request = await db.get_table_join_request(request_id)
    if not request or request["status"] != "pending":
        await callback.answer("❌ Запрос не найден", show_alert=True)
        return

    admin_user_id = await db.get_table_admin_user_id(request["venue_id"], request["table_number"])
    if admin_user_id != callback.from_user.id:
        await callback.answer("❌ Нет прав", show_alert=True)
        return

    users_count = await db.get_table_users_count(request["venue_id"], request["table_number"])
    if users_count >= config.MAX_GROUP_SIZE:
        await db.update_table_join_request_status(request_id, "rejected")
        await callback.answer("❌ Стол заполнен", show_alert=True)
        return

    await db.update_user_venue(request["user_id"], request["venue_id"])
    await db.update_user_table(request["user_id"], request["table_number"])
    await db.update_table_join_request_status(request_id, "approved")

    joined_user_lang = await get_lang(request["user_id"])
    try:
        await callback.bot.send_message(
            request["user_id"],
            t(joined_user_lang, 'table_join_approved_client', table=request['table_number'])
        )
        await utils.send_user_menu(callback.bot, request["user_id"])
    except Exception:
        pass

    await callback.answer("✅ Пользователь добавлен", show_alert=True)
    try:
        await callback.message.delete()
    except Exception:
        pass
    await _send_user_main_menu(callback.bot, await db.get_user(callback.from_user.id))

@dp.callback_query(F.data.startswith("table_join_reject_"))
async def table_join_reject(callback: CallbackQuery):
    request_id = int(callback.data.split("_")[3])
    request = await db.get_table_join_request(request_id)
    if not request or request["status"] != "pending":
        await callback.answer("❌ Запрос не найден", show_alert=True)
        return

    admin_user_id = await db.get_table_admin_user_id(request["venue_id"], request["table_number"])
    if admin_user_id != callback.from_user.id:
        await callback.answer("❌ Нет прав", show_alert=True)
        return

    await db.update_table_join_request_status(request_id, "rejected")

    joined_user_lang = await get_lang(request["user_id"])
    try:
        await callback.bot.send_message(
            request["user_id"],
            t(joined_user_lang, 'table_join_rejected_client', table=request['table_number'])
        )
        await utils.send_user_menu(callback.bot, request["user_id"])
    except Exception:
        pass

    await callback.answer("✅ Запрос отклонен", show_alert=True)
    try:
        await callback.message.delete()
    except Exception:
        pass
    await _send_user_main_menu(callback.bot, await db.get_user(callback.from_user.id))

@dp.callback_query(F.data == "table_group_manage")
async def table_group_manage(callback: CallbackQuery):
    user = await db.get_user(callback.from_user.id)
    lang = await get_lang(callback.from_user.id)
    if not user or not user.venue_id or not user.table_number:
        await callback.answer(t(lang, 'error_not_found'), show_alert=True)
        return

    admin_user_id = await db.get_table_admin_user_id(user.venue_id, user.table_number)
    if admin_user_id != user.user_id:
        await callback.answer(t(lang, 'error_no_rights'), show_alert=True)
        return

    members = await db.get_table_users(user.venue_id, user.table_number)
    builder = InlineKeyboardBuilder()
    text = t(lang, 'table_group_title', table=user.table_number, count=len(members), max=config.MAX_GROUP_SIZE) + "\n\n"

    for member in members:
        name = html.escape(member.first_name or "")
        username = f" (@{html.escape(member.username)})" if member.username else ""
        is_admin = member.user_id == admin_user_id
        admin_tag = " (admin)" if is_admin else ""
        text += f"• {name}{username}{admin_tag}\n"
        if not is_admin:
            builder.row(
                InlineKeyboardButton(
                    text=f"{t(lang, 'table_group_kick')}: {member.first_name or '?'}",
                    callback_data=f"table_group_transfer_{member.user_id}"
                )
            )

    builder.row(InlineKeyboardButton(text=t(lang, 'btn_back'), callback_data="table_group_back"))

    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")
    await callback.answer()

@dp.callback_query(F.data == "table_group_back")
async def table_group_back(callback: CallbackQuery):
    user = await db.get_user(callback.from_user.id)
    if not user:
        await callback.answer()
        return
    await _return_to_user_main_menu(callback, user)

@dp.callback_query(F.data.startswith("table_group_transfer_"))
async def table_group_transfer(callback: CallbackQuery):
    target_user_id = int(callback.data.split("_")[3])
    user = await db.get_user(callback.from_user.id)
    lang = await get_lang(callback.from_user.id)
    if not user or not user.venue_id or not user.table_number:
        await callback.answer(t(lang, 'error_no_rights'), show_alert=True)
        return

    admin_user_id = await db.get_table_admin_user_id(user.venue_id, user.table_number)
    if admin_user_id != user.user_id:
        await callback.answer(t(lang, 'error_no_rights'), show_alert=True)
        return

    members = await db.get_table_users(user.venue_id, user.table_number)
    member_ids = {member.user_id for member in members}
    if target_user_id not in member_ids:
        await callback.answer(t(lang, 'error_not_found'), show_alert=True)
        return

    await db.set_table_admin(user.venue_id, user.table_number, target_user_id)

    new_admin_lang = await get_lang(target_user_id)
    try:
        await callback.bot.send_message(
            target_user_id,
            f"👑 {t(new_admin_lang, 'venue_attached_admin', venue='', table=user.table_number)}"
        )
        await utils.send_user_menu(callback.bot, target_user_id)
    except Exception:
        pass

    await callback.answer(t(lang, 'order_created'), show_alert=True)
    await _return_to_user_main_menu(callback, user)

@dp.callback_query(F.data.startswith("kj_add_service_"))
async def kj_add_service(callback: CallbackQuery):
    parts = callback.data.split("_")
    table_number = int(parts[3])
    song_id = int(parts[4])
    service_id = int(parts[5])

    user = await db.get_user(callback.from_user.id)
    lang = await get_lang(callback.from_user.id)
    if not user or user.role > config.ROLE_KJ or not user.venue_id:
        await callback.answer(t(lang, 'error_no_rights'), show_alert=True)
        return

    song = await db.get_song(song_id)
    service = await db.get_service(service_id)
    if not song or not service:
        await callback.answer(t(lang, 'error_data'), show_alert=True)
        return

    users_at_table = await db.get_table_users(user.venue_id, table_number)
    table_admin_id = await db.get_table_admin_user_id(user.venue_id, table_number)
    order_user_id = table_admin_id or (users_at_table[0].user_id if users_at_table else user.user_id)

    import aiosqlite
    async with db.get_db() as db_conn:
        async with db_conn.execute(
            """SELECT COUNT(*) FROM orders
               WHERE venue_id = ? AND table_number = ? AND user_id = ? AND status IN ('pending', 'waiting')""",
            (user.venue_id, table_number, order_user_id)
        ) as cursor:
            orders_count = (await cursor.fetchone())[0]

    if orders_count >= config.MAX_ACTIVE_SONGS_PER_USER:
        await callback.answer(
            t(lang, 'order_limit_reached', limit=config.MAX_ACTIVE_SONGS_PER_USER),
            show_alert=True
        )
        return

    song_display_name = await _song_display_name(song)
    order_id = await db.create_order(
        user.venue_id,
        table_number,
        order_user_id,
        service.service_id,
        song_display_name,
        status="pending"
    )

    async with db.get_db() as db_conn:
        async with db_conn.execute(
            "SELECT position FROM orders WHERE order_id = ?",
            (order_id,)
        ) as cursor:
            row = await cursor.fetchone()
            position = row[0] if row else 0

    await callback.message.edit_text(
        t(lang, 'order_sent', order_id=order_id, song=html.escape(song_display_name), service=html.escape(service.name), pos=position),
        parse_mode="HTML",
        reply_markup=kj_kb.get_back_button(f"queue_table_{table_number}")
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("select_service_"))
async def handle_service_selection(callback: CallbackQuery):
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    from aiogram.types import InlineKeyboardButton
    
    logger.info("SELECT_SERVICE callback=%s from=%s", callback.data, callback.from_user.id)
    parts = callback.data.split("_")
    service_id = int(parts[2])
    song_id = int(parts[3])
    
    user = await db.get_user(callback.from_user.id)
    lang = await get_lang(callback.from_user.id)
    song = await db.get_song(song_id)
    service = await db.get_service(service_id)
    venue = await db.get_venue(user.venue_id)
    
    if not song or not service:
        logger.warning("SELECT_SERVICE invalid song/service song_id=%s service_id=%s", song_id, service_id)
        await callback.answer(t(lang, 'error_data'), show_alert=True)
        return
    
    vip = await db.get_vip_client(user.user_id, user.venue_id)
    if vip and not service.is_free:
        if vip.balance < service.price:
            await callback.answer(
                t(lang, 'insufficient_balance_detail', balance=vip.balance, price=service.price),
                show_alert=True
            )
            return
    
    artist = song["artist"] if "artist" in song.keys() and song["artist"] else ""
    title = song["title"] if "title" in song.keys() and song["title"] else "Без названия"
    song_display_name = f"{artist} - {title}" if artist else title
    
    order_id = await db.create_order(
        venue_id=user.venue_id,
        table_number=user.table_number,
        user_id=user.user_id,
        service_id=service.service_id,
        song_name=song_display_name,
        status="waiting"
    )
    logger.info("SELECT_SERVICE order_created order_id=%s table=%s", order_id, user.table_number)

    if vip and not service.is_free:
        await db.charge_vip_for_order(user.user_id, user.venue_id, service.price, order_id, song_display_name)
        logger.info("SELECT_SERVICE charged VIP user_id=%s amount=%s", user.user_id, service.price)
    
    await db.log_event('order_created', user.venue_id, user.user_id,
                       f'Заказ #{order_id}: {song_display_name}, услуга: {service.name}')
    
    import aiosqlite
    async with db.get_db() as db_conn:
        async with db_conn.execute(
            "SELECT position FROM orders WHERE order_id = ?",
            (order_id,)
        ) as cursor:
            position = (await cursor.fetchone())[0]

        async with db_conn.execute(
            """SELECT COUNT(*) FROM orders
               WHERE venue_id = ? AND table_number = ? AND user_id = ? AND status IN ('pending', 'waiting')""",
            (user.venue_id, user.table_number, user.user_id)
        ) as cursor:
            active_user_orders = (await cursor.fetchone())[0]
    
    is_no_table = user.role == config.ROLE_NO_TABLE or (venue and utils.is_virtual_table(user.table_number, venue.table_count))
    table_label = utils.get_table_label(user.table_number, venue.table_count) if venue else f"Стол {user.table_number}"

    # Доп. отправка заказа в новый Backend API (ТЗ п.7) — параллельный,
    # централизованный процесс для React KJ Panel и VirtualDJ. Существующая
    # логика заказа выше (SQLite, очередь, статистика, начисление VIP) уже
    # выполнена и не зависит от результата этого вызова; сбой здесь не должен
    # влиять на UX гостя, поэтому запускаем фоновой таской, а не await.
    asyncio.create_task(
        backend_client.post_order_to_backend(
            telegram_user_id=user.user_id,
            club_id=user.venue_id,
            table_no=None if is_no_table else user.table_number,
            song_title=title,
            artist=artist or None,
        )
    )

    kj = await db.get_kj_by_venue(user.venue_id)
    if kj:
        kj_lang = await get_lang(kj.user_id)
        builder = InlineKeyboardBuilder()
        builder.row(
            InlineKeyboardButton(text=t(kj_lang, 'btn_order_cancel'), callback_data=f"order_reject_{order_id}"),
            InlineKeyboardButton(text=t(kj_lang, 'btn_order_approve'), callback_data=f"order_approve_{order_id}")
        )
        builder.row(
            InlineKeyboardButton(text=t(kj_lang, 'btn_chat_reply'), callback_data=f"chat_reply_{user.user_id}")
        )
        
        vip_badge = "⭐ VIP" if vip else ""
        table_label_str = f"🪑 Стол: <b>{table_label}</b>" if not is_no_table else t(kj_lang, 'kj_no_table_label', num=user.table_number)
        no_table_warning = t(kj_lang, 'kj_new_order_no_table_warn') if is_no_table else ""
        
        try:
            await callback.bot.send_message(
                kj.user_id,
                t(kj_lang, 'kj_new_order',
                  order_id=order_id,
                  table=table_label_str,
                  name=html.escape(user.first_name or ''),
                  vip_badge=vip_badge,
                  song=html.escape(song_display_name),
                  service=html.escape(service.name),
                  pos=position,
                  active=active_user_orders,
                  max=config.MAX_ACTIVE_SONGS_PER_USER) + no_table_warning,
                reply_markup=builder.as_markup(),
                parse_mode="HTML"
            )
            logger.info("SELECT_SERVICE notified KJ user_id=%s", kj.user_id)
        except Exception:
            logger.exception("SELECT_SERVICE failed to notify KJ")
            pass
    
    no_table_suffix = t(lang, 'order_sent_no_table_suffix') if is_no_table else ""
    message_text = t(lang, 'order_sent',
                     order_id=order_id,
                     song=html.escape(song_display_name),
                     service=html.escape(service.name),
                     pos=position) + no_table_suffix

    sent_msg = None
    sent_via_edit = False
    if callback.message:
        try:
            await callback.message.edit_text(
                message_text,
                parse_mode="HTML"
            )
            sent_via_edit = True
            sent_msg = callback.message
            logger.info("SELECT_SERVICE edited service message for user_id=%s", user.user_id)
        except Exception as exc:
            logger.exception("SELECT_SERVICE failed to edit service message: %s", exc)

    if not sent_via_edit:
        sent_msg = await callback.bot.send_message(
            user.user_id,
            message_text,
            parse_mode="HTML"
        )
        logger.info("SELECT_SERVICE sent user notification user_id=%s", user.user_id)
    await callback.answer()

    import asyncio
    await asyncio.sleep(3)
    if sent_msg:
        try:
            await sent_msg.delete()
        except Exception:
            pass
    await utils.send_user_menu(callback.bot, user.user_id)

async def main():
    logger.info("Инициализация базы данных...")
    await db.init_db()
    
    dp.message.middleware(FSMCleanupMiddleware())
    dp.message.middleware(BlockedUserMiddleware())
    dp.callback_query.middleware(BlockedUserMiddleware())

    dp.include_router(admin.router)
    dp.include_router(kj.router)
    dp.include_router(vip.router)
    dp.include_router(client.router)
    dp.include_router(no_table_client.router)
    dp.include_router(ai_search_router)
    dp.include_router(kj_panel_router)
    
    logger.info("Бот запущен!")
    
    try:
        allowed_updates = dp.resolve_used_update_types()
        if "chosen_inline_result" not in allowed_updates:
            allowed_updates.append("chosen_inline_result")
        await dp.start_polling(bot, allowed_updates=allowed_updates)
    finally:
        await db.close()
        await bot.session.close()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Бот остановлен")
