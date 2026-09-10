import html
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from datetime import datetime
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import InlineKeyboardButton
import aiosqlite

from database import Database
from keyboards import client_kb
import utils
import config
from lang import get_lang, t, pluralize_tables

router = Router()
db = Database()

class TableSelect(StatesGroup):
    venue_id = State()
    table_number = State()

class ChatForm(StatesGroup):
    message = State()

@router.message(Command("client"))
async def cmd_client(message: Message, state: FSMContext):
    user = await db.get_user(message.from_user.id)
    lang = await get_lang(message.from_user.id)
    
    if not user:
        await message.answer(t(lang, 'start_first'))
        return
    
    if user.role == config.ROLE_NONE:
        await message.answer(t(lang, 'session_ended'))
        return
    
    if not user.venue_id:
        venues = await db.get_all_venues()
        
        if not venues:
            await message.answer(t(lang, 'no_venues'))
            return
        
        builder = InlineKeyboardBuilder()
        for venue in venues:
            builder.button(
                text=f"🏢 {venue.name}",
                callback_data=f"select_venue_{venue.venue_id}"
            )
        builder.adjust(1)
        
        await message.answer(t(lang, 'select_club'), reply_markup=builder.as_markup())
        return
    
    if user.role == config.ROLE_NO_TABLE:
        if not user.table_number:
            from handlers.no_table_client import assign_no_table_number
            table_num = await assign_no_table_number(user.user_id, user.venue_id)
            user = await db.get_user(user.user_id)
    else:
        if not user.table_number:
            sent = await message.answer(t(lang, 'enter_table'))
            await state.update_data(_prompt_msg_id=sent.message_id, _prompt_chat_id=sent.chat.id)
            await state.set_state(TableSelect.table_number)
            return
    
    venue = await db.get_venue(user.venue_id)
    
    if not venue:
        await message.answer(t(lang, 'venue_not_found'))
        return
    
    import aiosqlite
    async with db.get_db() as db_conn:
        async with db_conn.execute(
            "SELECT COUNT(*) FROM orders WHERE user_id = ? AND venue_id = ? AND table_number = ? AND status IN ('pending', 'waiting')",
            (user.user_id, user.venue_id, user.table_number)
        ) as cursor:
            orders_count = (await cursor.fetchone())[0]
    
    is_no_table = user.role == config.ROLE_NO_TABLE
    admin_user_id = await db.get_table_admin_user_id(user.venue_id, user.table_number) if not is_no_table else None

    if is_no_table:
        table_display = t(lang, 'client_table_no_table', num=user.table_number)
        status_display = t(lang, 'client_status_no_table')
    else:
        table_display = str(user.table_number)
        status_display = t(lang, 'client_status_guest')

    text = (
        f"{t(lang, 'client_main_title')}\n\n"
        f"👤 <b>{html.escape(user.first_name or '')}</b>\n"
        f"Telegram: @{html.escape((user.username or t(lang, 'not_specified')))}\n"
        f"ID: <code>{user.user_id}</code>\n"
        f"🏢 Club: <b>{html.escape(venue.name or '')}</b>\n"
        f"🪑 {t(lang, 'queue_table_str', num=table_display)}\n"
        f"👤 {t(lang, 'client_status_guest')}: <b>{status_display}</b>\n"
        f"📋 {orders_count}/{config.MAX_ACTIVE_SONGS_PER_USER}\n\n"
        f"{t(lang, 'choose_action')}"
    )

    show_table_admin = (not is_no_table) and (admin_user_id == user.user_id)
    await message.answer(
        text,
        reply_markup=client_kb.get_client_main_menu(show_table_admin, venue.chat_enabled, venue.chat_link, lang),
        parse_mode="HTML"
    )

@router.callback_query(F.data.startswith("select_venue_"))
async def select_venue(callback: CallbackQuery):
    venue_id = int(callback.data.split("_")[2])
    user = await db.get_user(callback.from_user.id)
    lang = await get_lang(callback.from_user.id)
    
    await db.update_user_venue(user.user_id, venue_id)
    
    venue = await db.get_venue(venue_id)
    
    await callback.message.edit_text(
        t(lang, 'club_selected', venue=html.escape(venue.name or '')),
        parse_mode="HTML"
    )
    await callback.answer()

@router.message(TableSelect.table_number)
async def process_table_number(message: Message, state: FSMContext):
    lang = await get_lang(message.from_user.id)
    try:
        table_number = int(message.text)
        
        if table_number < 1:
            await message.answer(t(lang, 'table_must_be_positive'))
            await utils.send_user_menu(message.bot, message.from_user.id, message.chat.id)
            return
        
        user = await db.get_user(message.from_user.id)
        
        if not user.venue_id:
            await message.answer(t(lang, 'no_venue_selected'))
            await state.clear()
            await utils.send_user_menu(message.bot, message.from_user.id, message.chat.id)
            return
        
        venue = await db.get_venue(user.venue_id)
        
        if not venue:
            await message.answer(t(lang, 'venue_not_found'))
            await state.clear()
            await utils.send_user_menu(message.bot, message.from_user.id, message.chat.id)
            return
        
        if table_number > venue.table_count:
            await message.answer(t(lang, 'table_count_exceeded', count=venue.table_count))
            await utils.send_user_menu(message.bot, message.from_user.id, message.chat.id)
            return

        if user.table_number == table_number:
            await message.answer(t(lang, 'table_set', table=table_number))
            await state.clear()
            await utils.send_user_menu(message.bot, message.from_user.id, message.chat.id)
            return

        admin_user_id = await db.get_table_admin_user_id(user.venue_id, table_number)

        if not admin_user_id:
            await db.update_user_table(user.user_id, table_number)
            await db.set_table_admin(user.venue_id, table_number, user.user_id)

            await message.answer(
                t(lang, 'you_are_table_admin', table=table_number),
                reply_markup=client_kb.get_client_main_menu(True, venue.chat_enabled, venue.chat_link, lang)
            )
            await state.clear()
            return

        users_count = await db.get_table_users_count(user.venue_id, table_number)
        if users_count >= config.MAX_GROUP_SIZE:
            await state.clear()
            return

        has_pending = await db.has_pending_table_join_request(user.venue_id, table_number, user.user_id)
        if not has_pending:
            request_id = await db.create_table_join_request(user.venue_id, table_number, user.user_id)
        else:
            request_id = await db.get_pending_table_join_request_id(user.venue_id, table_number, user.user_id)

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
                    user_username = message.from_user.username or "n/a"
                    await message.bot.send_message(
                        admin_user.user_id,
                        t(admin_lang, 'table_join_request_msg', table=table_number, name=user_name, username=user_username),
                        reply_markup=builder.as_markup()
                    )
            except Exception as e:
                import logging
                logging.getLogger(__name__).error("Не удалось отправить уведомление админу стола: %s", e)

        await message.answer(t(lang, 'join_request_sent'))
        await state.clear()
        await utils.send_user_menu(message.bot, message.from_user.id, message.chat.id)
        
    except ValueError:
        await message.answer(t(lang, 'enter_table_number'))
        await utils.send_user_menu(message.bot, message.from_user.id, message.chat.id)

@router.callback_query(F.data.startswith("select_venue_"))
async def select_venue(callback: CallbackQuery):
    venue_id = int(callback.data.split("_")[2])
    user = await db.get_user(callback.from_user.id)
    
    await db.update_user_venue(user.user_id, venue_id)
    
    venue = await db.get_venue(venue_id)
    
    await callback.message.edit_text(
        f"✅ Клуб <b>{html.escape(venue.name or '')}</b> выбран!\n\n"
        f"Используйте /client чтобы продолжить.",
        parse_mode="HTML"
    )
    await callback.answer()

@router.callback_query(F.data == "client_main")
async def client_main_menu(callback: CallbackQuery):
    user = await db.get_user(callback.from_user.id)
    lang = await get_lang(callback.from_user.id)

    if user.role == config.ROLE_NONE:
        await callback.message.edit_text(t(lang, 'session_ended'))
        await callback.answer()
        return
    
    venue = await db.get_venue(user.venue_id)
    
    import aiosqlite
    
    is_no_table = user.role == config.ROLE_NO_TABLE
    admin_user_id = await db.get_table_admin_user_id(user.venue_id, user.table_number) if not is_no_table else None

    if is_no_table:
        table_display = t(lang, 'client_table_no_table', num=user.table_number)
        status_display = t(lang, 'client_status_no_table')
    else:
        table_display = str(user.table_number)
        status_display = t(lang, 'client_status_guest')

    async with db.get_db() as db_conn:
        db_conn.row_factory = aiosqlite.Row
        async with db_conn.execute(
            """SELECT COUNT(DISTINCT table_number) as tables_before
               FROM orders 
               WHERE venue_id = ? AND status = 'pending' AND table_number < ?""",
            (user.venue_id, user.table_number)
        ) as cursor:
            result = await cursor.fetchone()
            tables_before = result['tables_before'] if result else 0
        
        async with db_conn.execute(
            """SELECT table_number, position
               FROM orders 
               WHERE venue_id = ? AND status = 'playing'
               ORDER BY started_at DESC
               LIMIT 1""",
            (user.venue_id,)
        ) as cursor:
            playing = await cursor.fetchone()
            playing_info = t(lang, 'queue_now_playing_info', table=playing['table_number'], pos=playing['position']) if playing else ""

    text = (
        t(lang, 'client_main_title') + "\n\n" +
        t(lang, 'client_main_body',
          venue=html.escape(venue.name or ''),
          status=status_display,
          uid=user.user_id,
          table=table_display,
          tables_before=tables_before,
          tables_word=pluralize_tables(tables_before, lang),
          playing_info=playing_info)
    )

    show_table_admin = (not is_no_table) and (admin_user_id == user.user_id)
    await callback.message.edit_text(
        text,
        reply_markup=client_kb.get_client_main_menu(show_table_admin, venue.chat_enabled, venue.chat_link, lang),
        parse_mode="HTML"
    )
    await callback.answer()

@router.callback_query(F.data == "client_make_order")
async def client_make_order(callback: CallbackQuery):
    lang = await get_lang(callback.from_user.id)
    await callback.message.edit_text(
        t(lang, 'order_menu_title'),
        reply_markup=client_kb.get_order_type_menu(lang),
        parse_mode="Markdown"
    )
    await callback.answer()

@router.callback_query(F.data == "order_favorites")
async def order_favorites(callback: CallbackQuery):
    user = await db.get_user(callback.from_user.id)
    lang = await get_lang(callback.from_user.id)
    favorites = await db.get_user_favorites(user.user_id, user.venue_id)
    
    text = t(lang, 'favorites_title')
    
    number_emojis = ['1️⃣', '2️⃣', '3️⃣', '4️⃣', '5️⃣', '6️⃣', '7️⃣', '8️⃣', '9️⃣', '🔟']
    
    if favorites:
        builder = InlineKeyboardBuilder()
        for idx, fav in enumerate(favorites, 1):
            emoji = number_emojis[idx - 1] if idx <= len(number_emojis) else f"{idx}."
            button_text = f"{emoji} {fav['artist']} — {fav['title']}"
            builder.row(
                InlineKeyboardButton(
                    text=button_text,
                    callback_data=f"fav_action_{fav['favorite_id']}"
                )
            )
        builder.row(InlineKeyboardButton(text=t(lang, 'btn_back'), callback_data="client_make_order"))
        
        await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")
    else:
        builder = InlineKeyboardBuilder()
        builder.row(InlineKeyboardButton(text=t(lang, 'btn_back'), callback_data="client_make_order"))
        await callback.message.edit_text(
            t(lang, 'favorites_empty'),
            reply_markup=builder.as_markup(),
            parse_mode="HTML"
        )
    await callback.answer()

@router.callback_query(F.data.startswith("fav_action_"))
async def fav_action(callback: CallbackQuery):
    favorite_id = int(callback.data.split("_")[-1])
    lang = await get_lang(callback.from_user.id)
    await callback.message.edit_text(
        t(lang, 'choose_action'),
        reply_markup=client_kb.get_favorite_actions(favorite_id, lang=lang)
    )
    await callback.answer()

@router.callback_query(F.data.startswith("fav_reorder_"))
async def fav_reorder(callback: CallbackQuery):
    favorite_id = int(callback.data.split("_")[-1])
    user = await db.get_user(callback.from_user.id)
    
    import aiosqlite
    async with db.get_db() as db_conn:
        async with db_conn.execute(
            """SELECT COUNT(*) FROM orders 
               WHERE venue_id = ? AND table_number = ? AND user_id = ? AND status IN ('pending', 'waiting')""",
            (user.venue_id, user.table_number, user.user_id)
        ) as cursor:
            row = await cursor.fetchone()
            current_count = row[0]
    
    if current_count >= config.MAX_ACTIVE_SONGS_PER_USER:
        lang = await get_lang(callback.from_user.id)
        await callback.answer(
            t(lang, 'order_limit_reached', limit=config.MAX_ACTIVE_SONGS_PER_USER),
            show_alert=True
        )
        await client_main_menu(callback)
        return
    
    async with db.get_db() as conn:
        conn.row_factory = aiosqlite.Row
        async with conn.execute(
            """SELECT f.*, s.artist, s.title,
                  COALESCE(srv.name, '') as service_name,
                  COALESCE(srv.price, 0) as price,
                  COALESCE(srv.is_free, 1) as is_free
               FROM favorites f
               JOIN songs s ON f.song_id = s.song_id
               LEFT JOIN services srv ON f.service_id = srv.service_id
               WHERE f.favorite_id = ?""",
            (favorite_id,)
        ) as cursor:
            fav = await cursor.fetchone()
    
    if not fav:
        lang = await get_lang(callback.from_user.id)
        await callback.answer(t(lang, 'song_not_found'), show_alert=True)
        return
    
    order_id = await db.create_order(
        venue_id=user.venue_id,
        table_number=user.table_number,
        user_id=user.user_id,
        service_id=fav['service_id'],
        song_name=f"{fav['artist']} - {fav['title']}",
        status="waiting"
    )
    
    vip = await db.get_vip_client(user.user_id, user.venue_id)
    if vip and not fav['is_free']:
        await db.charge_vip_for_order(
            user.user_id, user.venue_id, fav['price'],
            order_id, f"{fav['artist']} - {fav['title']}"
        )
    
    await db.log_event('order_created', user.venue_id, user.user_id,
                       f'Заказ #{order_id} (избранное): {fav["artist"]} - {fav["title"]}')
    
    async with db.get_db() as db_conn:
        async with db_conn.execute(
            "SELECT position FROM orders WHERE order_id = ?",
            (order_id,)
        ) as cursor:
            row = await cursor.fetchone()
            position = row[0] if row else 0

        async with db_conn.execute(
            """SELECT COUNT(*) FROM orders
               WHERE venue_id = ? AND table_number = ? AND user_id = ? AND status IN ('pending', 'waiting')""",
            (user.venue_id, user.table_number, user.user_id)
        ) as cursor:
            active_user_orders = (await cursor.fetchone())[0]
    
    kj = await db.get_kj_by_venue(user.venue_id)
    lang = await get_lang(callback.from_user.id)
    is_no_table = user.role == config.ROLE_NO_TABLE
    
    if kj:
        kj_lang = await get_lang(kj.user_id)
        kj_msg = t(kj_lang, 'kj_new_order',
                   order_id=order_id,
                   table=user.table_number,
                   name=html.escape(user.first_name or ''),
                   song=html.escape(f"{fav['artist']} - {fav['title']}"),
                   service=html.escape(str(fav['service_name'])),
                   pos=position,
                   active=active_user_orders,
                   max_active=config.MAX_ACTIVE_SONGS_PER_USER,
                   is_no_table=is_no_table)
        builder = InlineKeyboardBuilder()
        builder.row(
            InlineKeyboardButton(text=t(kj_lang, 'btn_reject'), callback_data=f"order_reject_{order_id}"),
            InlineKeyboardButton(text=t(kj_lang, 'btn_approve'), callback_data=f"order_approve_{order_id}")
        )
        builder.row(
            InlineKeyboardButton(text=t(kj_lang, 'btn_chat_reply'), callback_data=f"chat_reply_{user.user_id}")
        )
        try:
            await callback.bot.send_message(
                kj.user_id,
                kj_msg,
                reply_markup=builder.as_markup(),
                parse_mode="HTML"
            )
        except Exception:
            pass
    
    no_table_suffix = t(lang, 'order_sent_no_table_suffix') if is_no_table else ""
    await callback.message.edit_text(
        t(lang, 'order_sent',
          order_id=order_id,
          song=html.escape(f"{fav['artist']} - {fav['title']}"),
          service=html.escape(str(fav['service_name'])),
          pos=position) + no_table_suffix,
        parse_mode="HTML"
    )
    
    if is_no_table:
        await callback.answer(t(lang, 'approach_kj'), show_alert=True)
    else:
        await callback.answer()

    import asyncio
    await asyncio.sleep(3)
    try:
        await callback.message.delete()
    except Exception:
        pass
    await utils.send_user_menu(callback.bot, callback.from_user.id, callback.message.chat.id)

@router.callback_query(F.data.startswith("fav_delete_"))
async def fav_delete(callback: CallbackQuery):
    favorite_id = int(callback.data.split("_")[-1])
    lang = await get_lang(callback.from_user.id)
    await db.remove_from_favorites(favorite_id)
    await callback.answer(t(lang, 'favorite_removed'), show_alert=True)
    await order_favorites(callback)

@router.callback_query(F.data == "client_my_orders")
async def client_my_orders(callback: CallbackQuery):
    user = await db.get_user(callback.from_user.id)
    lang = await get_lang(callback.from_user.id)
    
    import aiosqlite
    async with db.get_db() as db_conn:
        db_conn.row_factory = aiosqlite.Row
        async with db_conn.execute(
            """SELECT o.*, s.name as service_name 
               FROM orders o
               LEFT JOIN services s ON o.service_id = s.service_id
               WHERE o.venue_id = ? AND o.table_number = ? AND o.user_id = ? AND o.status IN ('pending', 'waiting')
               ORDER BY o.is_next DESC, o.marked_next_at ASC, o.position ASC""",
            (user.venue_id, user.table_number, user.user_id)
        ) as cursor:
            orders = await cursor.fetchall()
    
    text = t(lang, 'my_orders_title')
    
    number_emojis = ['1️⃣', '2️⃣', '3️⃣', '4️⃣', '5️⃣', '6️⃣', '7️⃣', '8️⃣', '9️⃣', '🔟']
    
    if orders:
        builder = InlineKeyboardBuilder()
        for idx, order in enumerate(orders, 1):
            is_next = order['is_next'] if 'is_next' in order.keys() else 0
            next_label = " ⏭" if is_next else ""
            emoji = number_emojis[idx - 1] if idx <= len(number_emojis) else f"{idx}."
            button_text = f"{emoji} {order['song_name']}{next_label}"
            builder.row(
                InlineKeyboardButton(
                    text=button_text,
                    callback_data=f"order_action_{order['order_id']}"
                )
            )

        builder.row(InlineKeyboardButton(text=t(lang, 'btn_back'), callback_data="client_main"))
        
        await callback.message.edit_text(
            text, 
            reply_markup=builder.as_markup(), 
            parse_mode="Markdown"
        )
    else:
        await callback.message.edit_text(
            t(lang, 'my_orders_empty'),
            reply_markup=client_kb.get_back_to_main(lang),
            parse_mode="Markdown"
        )
    await callback.answer()

@router.callback_query(F.data.startswith("order_action_"))
async def order_action(callback: CallbackQuery):
    order_id = int(callback.data.split("_")[-1])
    user = await db.get_user(callback.from_user.id)
    lang = await get_lang(callback.from_user.id)
    rank = await db.get_order_global_rank(user.venue_id, order_id)
    can_replace = (rank == 0 or rank >= 3)
    await callback.message.edit_text(
        t(lang, 'choose_action'),
        reply_markup=client_kb.get_order_actions(order_id, can_replace, lang)
    )
    await callback.answer()

@router.callback_query(F.data.startswith("replace_blocked_"))
async def replace_blocked(callback: CallbackQuery):
    order_id = int(callback.data.split("_")[-1])
    user = await db.get_user(callback.from_user.id)
    lang = await get_lang(callback.from_user.id)
    rank = await db.get_order_global_rank(user.venue_id, order_id)
    await callback.answer(
        t(lang, 'replace_blocked', rank=rank),
        show_alert=True
    )

async def order_replace(callback: CallbackQuery, state: FSMContext):
    order_id = int(callback.data.split("_")[-1])
    user = await db.get_user(callback.from_user.id)
    lang = await get_lang(callback.from_user.id)
    
    orders = await db.get_orders_by_table(user.venue_id, user.table_number)
    order = next((o for o in orders if o.order_id == order_id), None)
    
    if not order:
        await callback.answer(t(lang, 'order_not_found'), show_alert=True)
        return

    rank = await db.get_order_global_rank(user.venue_id, order_id)
    if rank > 0 and rank <= 2:
        await callback.answer(
            t(lang, 'replace_unavailable', rank=rank),
            show_alert=True
        )
        return
    
    await state.update_data(
        replace_order_id=order_id,
        replace_prompt_message_id=callback.message.message_id,
        replace_prompt_chat_id=callback.message.chat.id
    )
    
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text=t(lang, 'btn_find_song_replace'),
            switch_inline_query_current_chat=f"replace:{order_id} "
        )
    )
    builder.row(
        InlineKeyboardButton(text=t(lang, 'btn_cancel'), callback_data="client_my_orders")
    )
    
    await callback.message.edit_text(
        t(lang, 'replace_title'),
        parse_mode="HTML",
        reply_markup=builder.as_markup()
    )
    await callback.answer()

@router.callback_query(F.data.startswith("order_favorite_"))
async def order_favorite(callback: CallbackQuery):
    order_id = int(callback.data.split("_")[-1])
    user = await db.get_user(callback.from_user.id)
    lang = await get_lang(callback.from_user.id)
    
    order = await db.get_order(order_id)
    if not order:
        await callback.answer(t(lang, 'order_not_found'), show_alert=True)
        return
    
    async with db.get_db() as conn:
        conn.row_factory = aiosqlite.Row
        async with conn.execute(
            """SELECT song_id FROM songs
               WHERE venue_id = ? AND (artist || ' - ' || title) = ?""",
            (user.venue_id, order.song_name)
        ) as cursor:
            song_row = await cursor.fetchone()
    
    if song_row:
        await db.add_to_favorites(user.user_id, user.venue_id, song_row['song_id'], order.service_id)
        await callback.answer(t(lang, 'favorite_added'), show_alert=True)
    else:
        await callback.answer(t(lang, 'song_not_found'), show_alert=True)
    
    await client_my_orders(callback)

@router.callback_query(F.data == "client_queue")
async def client_queue(callback: CallbackQuery):
    user = await db.get_user(callback.from_user.id)
    venue = await db.get_venue(user.venue_id)
    lang = await get_lang(callback.from_user.id)
    
    import aiosqlite
    
    async with db.get_db() as conn:
        conn.row_factory = aiosqlite.Row
        async with conn.execute(
            """SELECT table_number, song_name, position
               FROM orders 
               WHERE venue_id = ? AND status = 'playing'
               ORDER BY started_at DESC
               LIMIT 1""",
            (user.venue_id,)
        ) as cursor:
            playing_song = await cursor.fetchone()
    
    text = t(lang, 'queue_title')
    
    def table_label(table_num):
        if table_num > venue.table_count:
            return t(lang, 'queue_no_table_str', num=table_num)
        return t(lang, 'queue_table_str', num=table_num)
    
    if playing_song:
        text += t(lang, 'queue_now_playing',
                  table=table_label(playing_song['table_number']),
                  song=html.escape(str(playing_song['song_name'])))
    
    if venue.table_mode == "sequential":
        all_orders = []
        
        for table_num in range(1, venue.table_count + 1):
            orders = await db.get_orders_by_table(user.venue_id, table_num)
            pending_orders = [o for o in orders if o.status == 'pending']
            for order in pending_orders[:config.MAX_ACTIVE_SONGS_PER_USER]:
                all_orders.append({
                    'table': table_num,
                    'table_label': table_label(table_num),
                    'song': order.song_name,
                    'position': order.position,
                    'is_next': getattr(order, 'is_next', 0) or 0,
                    'created_at': order.created_at
                })
        
        async with db.get_db() as conn:
            conn.row_factory = aiosqlite.Row
            async with conn.execute(
                """SELECT DISTINCT table_number FROM users 
                   WHERE venue_id = ? AND table_number > ?""",
                (user.venue_id, venue.table_count)
            ) as cursor:
                virtual_tables = await cursor.fetchall()
        
        for vt in virtual_tables:
            orders = await db.get_orders_by_table(user.venue_id, vt['table_number'])
            pending_orders = [o for o in orders if o.status == 'pending']
            for order in pending_orders[:config.MAX_ACTIVE_SONGS_PER_USER]:
                all_orders.append({
                    'table': vt['table_number'],
                    'table_label': table_label(vt['table_number']),
                    'song': order.song_name,
                    'position': order.position,
                    'is_next': getattr(order, 'is_next', 0) or 0,
                    'created_at': order.created_at
                })
        
        if all_orders:
            by_table = {}
            for order in all_orders:
                table = order['table']
                if table not in by_table:
                    by_table[table] = []
                by_table[table].append(order)
            
            for table in by_table:
                by_table[table].sort(key=lambda x: x['position'])
            
            next_songs = []
            regular_songs = []
            
            max_songs = max(len(orders) for orders in by_table.values()) if by_table else 0
            songs_per_round = config.MAX_ACTIVE_SONGS_PER_USER
            max_rounds = (max_songs + songs_per_round - 1) // songs_per_round if max_songs > 0 else 0
            
            for round_idx in range(max_rounds):
                for table_num in sorted(by_table.keys()):
                    start_idx = round_idx * songs_per_round
                    end_idx = start_idx + songs_per_round
                    for song_idx in range(start_idx, min(end_idx, len(by_table[table_num]))):
                        order = by_table[table_num][song_idx]
                        if order['is_next']:
                            next_songs.append((order['table_label'], order))
                        else:
                            regular_songs.append((order['table_label'], order))
            
            if next_songs:
                text += t(lang, 'queue_next_header')
                for tbl_label, order in next_songs:
                    text += f"      └ <b>{tbl_label}</b> — {html.escape(str(order['song']))}\n"
                text += "\n—————————\n\n"
            
            if regular_songs:
                text += t(lang, 'queue_regular_header')
                current_label = None
                for tbl_label, order in regular_songs:
                    if current_label != tbl_label:
                        if current_label is not None:
                            text += "\n"
                        text += f"📍 <b>{tbl_label}</b>\n"
                        current_label = tbl_label
                    text += f"    └  {html.escape(str(order['song']))}\n"
        else:
            text += t(lang, 'queue_empty')
    
    else:
        async with db.get_db() as conn:
            conn.row_factory = aiosqlite.Row
            async with conn.execute(
                """SELECT table_number, song_name, is_next, created_at 
                   FROM orders 
                   WHERE venue_id = ? AND status = 'pending'
                   ORDER BY is_next DESC, created_at ASC""",
                (user.venue_id,)
            ) as cursor:
                rows = await cursor.fetchall()
        
        if rows:
            next_songs = [r for r in rows if r['is_next']]
            regular_songs = [r for r in rows if not r['is_next']]

            _tbl_counter = {}
            filtered_regular = []
            for r in regular_songs:
                tbl = r['table_number']
                _tbl_counter[tbl] = _tbl_counter.get(tbl, 0) + 1
                if _tbl_counter[tbl] <= config.MAX_ACTIVE_SONGS_PER_USER:
                    filtered_regular.append(r)
            regular_songs = filtered_regular

            if next_songs:
                text += t(lang, 'queue_next_header')
                for row in next_songs:
                    text += f"      └ <b>{table_label(row['table_number'])}</b> — {html.escape(str(row['song_name']))}\n"
                text += "\n—————————\n\n"
            
            if regular_songs:
                text += t(lang, 'queue_regular_header')
                current_tbl = None
                for row in regular_songs:
                    tbl = table_label(row['table_number'])
                    if current_tbl != tbl:
                        if current_tbl is not None:
                            text += "\n"
                        text += f"📍 <b>{tbl}</b>\n"
                        current_tbl = tbl
                    text += f"    └  {html.escape(str(row['song_name']))}\n"
        else:
            text += t(lang, 'queue_empty')
    
    await callback.message.edit_text(text, reply_markup=client_kb.get_back_to_main(lang), parse_mode="HTML")
    await callback.answer()

@router.callback_query(F.data == "client_become_vip")
async def client_become_vip(callback: CallbackQuery):
    user = await db.get_user(callback.from_user.id)
    lang = await get_lang(callback.from_user.id)
    venue = await db.get_venue(user.venue_id)
    
    if lang == 'ro':
        vip_desc = venue.vip_description_ro or venue.vip_description or ""
    else:
        vip_desc = venue.vip_description or ""
    vip_text = t(lang, 'become_vip_text', desc=vip_desc)
    
    await callback.message.edit_text(
        vip_text,
        reply_markup=client_kb.get_become_vip_menu(lang),
        parse_mode="Markdown"
    )
    await callback.answer()

@router.callback_query(F.data == "request_vip_status")
async def request_vip_status(callback: CallbackQuery):
    user = await db.get_user(callback.from_user.id)
    lang = await get_lang(callback.from_user.id)

    if not user.table_number:
        await callback.answer(t(lang, 'vip_select_venue_first'), show_alert=True)
        await client_main_menu(callback)
        return
    
    request_id = await db.create_request(
        venue_id=user.venue_id,
        user_id=user.user_id,
        table_number=user.table_number,
        request_type='vip'
    )
    
    kj = await db.get_kj_by_venue(user.venue_id)
    if kj:
        try:
            kj_lang = await get_lang(kj.user_id)
            builder = InlineKeyboardBuilder()
            builder.row(
                InlineKeyboardButton(text=t(kj_lang, 'btn_confirm'), callback_data=f"vip_request_approve_{request_id}"),
                InlineKeyboardButton(text=t(kj_lang, 'btn_reject'), callback_data=f"vip_request_reject_{request_id}")
            )
            await callback.bot.send_message(
                kj.user_id,
                t(kj_lang, 'vip_request_to_kj',
                  table=user.table_number,
                  name=html.escape(user.first_name or ''),
                  username=html.escape(user.username or 'n/a')),
                parse_mode="Markdown",
                reply_markup=builder.as_markup()
            )
        except Exception:
            pass
    
    await callback.answer(t(lang, 'vip_request_sent'), show_alert=True)
    await client_become_vip(callback)

@router.callback_query(F.data == "client_chat_kj")
async def client_chat_kj(callback: CallbackQuery, state: FSMContext):
    import logging
    logger = logging.getLogger(__name__)
    lang = await get_lang(callback.from_user.id)
    sent = await callback.message.answer(
        t(lang, 'chat_title'),
        reply_markup=client_kb.get_cancel_keyboard(lang),
        parse_mode="Markdown"
    )
    logger.info("CHAT_KJ prompt sent message_id=%s chat_id=%s", sent.message_id, sent.chat.id)
    await state.update_data(
        chat_prompt_message_id=sent.message_id,
        chat_prompt_chat_id=sent.chat.id
    )
    await state.set_state(ChatForm.message)
    await callback.answer()

@router.message(ChatForm.message)
async def process_chat_message(message: Message, state: FSMContext):
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    from aiogram.types import InlineKeyboardButton
    import logging
    logger = logging.getLogger(__name__)

    data = await state.get_data()
    prompt_id = data.get("chat_prompt_message_id")
    prompt_chat_id = data.get("chat_prompt_chat_id", message.chat.id)
    logger.info("CHAT_KJ delete attempt prompt_id=%s prompt_chat_id=%s", prompt_id, prompt_chat_id)
    if prompt_id:
        try:
            await message.bot.delete_message(prompt_chat_id, prompt_id)
            logger.info("CHAT_KJ prompt deleted")
        except Exception as exc:
            logger.exception("CHAT_KJ prompt delete failed: %s", exc)
            try:
                await message.bot.edit_message_reply_markup(
                    chat_id=prompt_chat_id,
                    message_id=prompt_id,
                    reply_markup=None
                )
                logger.info("CHAT_KJ prompt markup removed")
            except Exception as exc2:
                logger.exception("CHAT_KJ prompt markup remove failed: %s", exc2)
                pass
    
    user = await db.get_user(message.from_user.id)
    venue = await db.get_venue(user.venue_id)
    
    kj = await db.get_kj_by_venue(user.venue_id)
    
    if not kj:
        lang = await get_lang(message.from_user.id)
        await message.answer(t(lang, 'chat_failed'))
        await state.clear()
        await utils.send_user_menu(message.bot, message.from_user.id, message.chat.id)
        return
    
    await db.save_chat_message(
        venue_id=user.venue_id,
        from_user_id=user.user_id,
        to_user_id=kj.user_id,
        message_text=message.text,
        table_number=user.table_number
    )
    
    lang = await get_lang(message.from_user.id)
    
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text=t(lang, 'btn_chat_reply'), callback_data=f"chat_reply_{user.user_id}")
    )
    
    is_no_table = user.role == config.ROLE_NO_TABLE
    if is_no_table:
        table_info = t(lang, 'client_table_no_table', num=user.table_number)
    else:
        table_info = f"🪑 {t(lang, 'queue_table_str', num=user.table_number)}"
    
    try:
        kj_lang = await get_lang(kj.user_id)
        await message.bot.send_message(
            kj.user_id,
            t(kj_lang, 'chat_msg_to_kj',
              table=user.table_number,
              name=html.escape(user.first_name or ''),
              text=html.escape(message.text or '')),
            reply_markup=builder.as_markup(),
            parse_mode="Markdown"
        )
        
        admin_user_id = await db.get_table_admin_user_id(user.venue_id, user.table_number) if not is_no_table else None
        show_table_admin = (not is_no_table) and (admin_user_id == user.user_id)
        await message.answer(
            t(lang, 'chat_sent'),
            reply_markup=client_kb.get_client_main_menu(show_table_admin, venue.chat_enabled, venue.chat_link, lang)
        )
    except Exception as e:
        admin_user_id = await db.get_table_admin_user_id(user.venue_id, user.table_number) if not is_no_table else None
        show_table_admin = (not is_no_table) and (admin_user_id == user.user_id)
        await message.answer(
            f"{t(lang, 'chat_failed')}: {str(e)}",
            reply_markup=client_kb.get_client_main_menu(show_table_admin, venue.chat_enabled, venue.chat_link, lang)
        )
    
    await state.clear()

@router.callback_query(F.data.startswith("client_chat_reply_"))
async def client_chat_reply(callback: CallbackQuery, state: FSMContext):
    kj_id = int(callback.data.split("_")[3])
    lang = await get_lang(callback.from_user.id)

    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    
    await state.update_data(kj_id=kj_id)
    await state.set_state(ChatForm.message)
    
    sent = await callback.message.answer(
        t(lang, 'chat_title'),
        parse_mode="Markdown"
    )
    await state.update_data(_prompt_msg_id=sent.message_id, _prompt_chat_id=sent.chat.id)
    await callback.answer()

@router.callback_query(F.data.startswith("cancel_"))
async def cancel_action(callback: CallbackQuery, state: FSMContext):
    lang = await get_lang(callback.from_user.id)
    await state.clear()
    await callback.answer(t(lang, 'btn_cancel'))
    await client_main_menu(callback)
