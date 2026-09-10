import html
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from datetime import datetime, timedelta
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import InlineKeyboardButton
import aiosqlite

from database import Database
from keyboards import vip_kb
import utils
import config
from lang import get_lang, t, pluralize_tables

router = Router()
db = Database()

class ChatForm(StatesGroup):
    message = State()

class TopupForm(StatesGroup):
    amount = State()

@router.message(Command("vip"))
async def cmd_vip(message: Message):
    user = await db.get_user(message.from_user.id)
    lang = await get_lang(message.from_user.id)
    
    if not user or user.role == config.ROLE_NONE or user.role > config.ROLE_VIP:
        await message.answer(t(lang, 'vip_access_denied'))
        return
    
    if not user.venue_id or not user.table_number:
        await message.answer(t(lang, 'vip_select_venue_first'))
        return
    
    vip = await db.get_vip_client(user.user_id, user.venue_id)
    venue = await db.get_venue(user.venue_id)
    
    admin_user_id = await db.get_table_admin_user_id(user.venue_id, user.table_number)

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

    text = t(lang, 'vip_menu_title') + "\n\n" + t(lang, 'vip_menu_body',
        venue=venue.name,
        uid=user.user_id,
        balance=vip.balance if vip else 0,
        table=user.table_number,
        tables_before=tables_before,
        tables_word=pluralize_tables(tables_before, lang),
        playing_info=playing_info
    )

    await message.answer(
        text,
        reply_markup=vip_kb.get_vip_main_menu(admin_user_id == user.user_id, venue.chat_enabled, venue.chat_link, lang),
        parse_mode="Markdown"
    )

@router.callback_query(F.data == "vip_main")
async def vip_main_menu(callback: CallbackQuery):
    user = await db.get_user(callback.from_user.id)
    lang = await get_lang(callback.from_user.id)
    
    if user.role == config.ROLE_NONE:
        await callback.message.edit_text(t(lang, 'session_ended'))
        await callback.answer()
        return
    
    vip = await db.get_vip_client(user.user_id, user.venue_id)
    venue = await db.get_venue(user.venue_id)
    
    admin_user_id = await db.get_table_admin_user_id(user.venue_id, user.table_number)

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

    text = t(lang, 'vip_menu_title') + "\n\n" + t(lang, 'vip_menu_body',
        venue=venue.name,
        uid=user.user_id,
        balance=vip.balance if vip else 0,
        table=user.table_number,
        tables_before=tables_before,
        tables_word=pluralize_tables(tables_before, lang),
        playing_info=playing_info
    )

    await callback.message.edit_text(
        text,
        reply_markup=vip_kb.get_vip_main_menu(admin_user_id == user.user_id, venue.chat_enabled, venue.chat_link, lang),
        parse_mode="Markdown"
    )
    await callback.answer()

@router.callback_query(F.data == "vip_profile")
async def vip_profile(callback: CallbackQuery):
    user = await db.get_user(callback.from_user.id)
    lang = await get_lang(callback.from_user.id)
    vip = await db.get_vip_client(user.user_id, user.venue_id)
    venue = await db.get_venue(user.venue_id)
    
    text = t(lang, 'vip_profile_text',
        name=user.first_name,
        username=user.username or t(lang, 'not_specified'),
        venue=venue.name,
        table=user.table_number,
        balance=vip.balance if vip else 0,
        cashback=vip.cashback_percent if vip else 0
    )
    
    await callback.message.edit_text(text, reply_markup=vip_kb.get_back_to_main(lang), parse_mode="Markdown")
    await callback.answer()

@router.callback_query(F.data == "vip_balance")
async def vip_balance(callback: CallbackQuery):
    user = await db.get_user(callback.from_user.id)
    lang = await get_lang(callback.from_user.id)
    vip = await db.get_vip_client(user.user_id, user.venue_id)
    
    text = t(lang, 'balance_title', balance=vip.balance if vip else 0)
    
    await callback.message.edit_text(text, reply_markup=vip_kb.get_balance_menu(lang), parse_mode="Markdown")
    await callback.answer()

@router.callback_query(F.data == "vip_topup_request")
async def vip_topup_request(callback: CallbackQuery, state: FSMContext):
    lang = await get_lang(callback.from_user.id)
    await state.set_state(TopupForm.amount)
    
    await callback.message.edit_text(
        t(lang, 'topup_title'),
        parse_mode="Markdown",
        reply_markup=InlineKeyboardBuilder().row(
            InlineKeyboardButton(text=t(lang, 'btn_cancel'), callback_data="vip_balance")
        ).as_markup()
    )
    await state.update_data(_prompt_msg_id=callback.message.message_id, _prompt_chat_id=callback.message.chat.id)
    await callback.answer()

@router.message(TopupForm.amount)
async def vip_topup_amount(message: Message, state: FSMContext):
    lang = await get_lang(message.from_user.id)
    try:
        amount = float(message.text.replace(',', '.'))
        if amount <= 0:
            raise ValueError()
    except ValueError:
        await message.answer(t(lang, 'topup_invalid'))
        await utils.send_user_menu(message.bot, message.from_user.id, message.chat.id)
        return
    
    user = await db.get_user(message.from_user.id)
    venue = await db.get_venue(user.venue_id)
    
    request_id = await db.create_request(
        venue_id=user.venue_id,
        user_id=user.user_id,
        table_number=user.table_number,
        request_type='topup',
        amount=amount
    )
    
    kj = await db.get_kj_by_venue(user.venue_id)
    if kj:
        kj_lang = await get_lang(kj.user_id)
        builder = InlineKeyboardBuilder()
        builder.row(
            InlineKeyboardButton(
                text=t(kj_lang, 'btn_topup_approve'),
                callback_data=f"topup_request_approve_{request_id}"
            ),
            InlineKeyboardButton(
                text=t(kj_lang, 'btn_topup_reject'),
                callback_data=f"topup_request_reject_{request_id}"
            )
        )
        
        await message.bot.send_message(
            kj.user_id,
            t(kj_lang, 'kj_topup_request',
              table=user.table_number,
              name=user.first_name,
              username=user.username or 'n/a',
              amount=amount),
            parse_mode="Markdown",
            reply_markup=builder.as_markup()
        )
    
    admin_user_id = await db.get_table_admin_user_id(user.venue_id, user.table_number)
    await message.answer(
        t(lang, 'topup_sent', amount=amount),
        reply_markup=vip_kb.get_vip_main_menu(admin_user_id == user.user_id, venue.chat_enabled, venue.chat_link, lang)
    )
    await state.clear()

@router.callback_query(F.data == "vip_order_history")
async def vip_order_history_menu(callback: CallbackQuery):
    lang = await get_lang(callback.from_user.id)
    await callback.message.edit_text(
        t(lang, 'order_history_title'),
        reply_markup=vip_kb.get_history_period_menu(lang),
        parse_mode="Markdown"
    )
    await callback.answer()

@router.callback_query(F.data.startswith("history_"))
async def vip_order_history(callback: CallbackQuery):
    period = callback.data.split("_")[1]
    user = await db.get_user(callback.from_user.id)
    lang = await get_lang(callback.from_user.id)
    
    days_map = {"today": 1, "week": 7, "month": 30}
    days = days_map.get(period, 30)
    
    orders = await db.get_user_orders_history(user.user_id, user.venue_id, days)
    
    period_key_map = {"today": "period_today_low", "week": "period_week_low", "month": "period_month_low"}
    period_str = t(lang, period_key_map.get(period, 'period_month_low'))
    text = t(lang, 'order_history_period', period=period_str)
    
    if orders:
        for order in orders:
            created_at = datetime.fromisoformat(order['created_at'])
            text += f"🎵 {created_at.strftime('%d.%m %H:%M')} - {order['artist']} - {order['title']}\n"
    else:
        text += t(lang, 'order_history_empty')
    
    await callback.message.edit_text(text, reply_markup=vip_kb.get_history_period_menu(lang), parse_mode="Markdown")
    await callback.answer()

@router.callback_query(F.data == "vip_finances")
async def vip_finances_menu(callback: CallbackQuery):
    lang = await get_lang(callback.from_user.id)
    await callback.message.edit_text(
        t(lang, 'finances_title'),
        reply_markup=vip_kb.get_finances_period_menu(lang),
        parse_mode="Markdown"
    )
    await callback.answer()

@router.callback_query(F.data.startswith("finances_"))
async def vip_finances(callback: CallbackQuery):
    period = callback.data.split("_")[1]
    user = await db.get_user(callback.from_user.id)
    lang = await get_lang(callback.from_user.id)
    
    days_map = {"today": 1, "week": 7, "month": 30}
    days = days_map.get(period, 30)
    
    topups = await db.get_user_transactions(user.user_id, user.venue_id, 'topup', days)
    cashbacks = await db.get_user_transactions(user.user_id, user.venue_id, 'cashback', days)
    payments = await db.get_user_transactions(user.user_id, user.venue_id, 'order_payment', days)
    refunds = await db.get_user_transactions(user.user_id, user.venue_id, 'order_refund', days)
    
    period_key_map = {"today": "period_today_low", "week": "period_week_low", "month": "period_month_low"}
    period_str = t(lang, period_key_map.get(period, 'period_month_low'))
    text = t(lang, 'finances_period', period=period_str)
    
    text += t(lang, 'finances_topups')
    if topups:
        total_topup = 0
        for tx in topups:
            created_at = datetime.fromisoformat(tx['created_at'])
            text += f"  {created_at.strftime('%d.%m %H:%M')} +{tx['amount']} MDL\n"
            total_topup += tx['amount']
        text += t(lang, 'finances_total_plus', total=total_topup)
    else:
        text += t(lang, 'finances_no_topups')
    
    text += t(lang, 'finances_payments')
    if payments:
        total_pay = 0
        for p in payments:
            created_at = datetime.fromisoformat(p['created_at'])
            text += f"  {created_at.strftime('%d.%m %H:%M')} -{p['amount']} MDL\n"
            total_pay += p['amount']
        text += t(lang, 'finances_total_minus', total=total_pay)
    else:
        text += t(lang, 'finances_no_payments')
    
    text += t(lang, 'finances_refunds')
    if refunds:
        total_refund = 0
        for r in refunds:
            created_at = datetime.fromisoformat(r['created_at'])
            text += f"  {created_at.strftime('%d.%m %H:%M')} +{r['amount']} MDL\n"
            total_refund += r['amount']
        text += t(lang, 'finances_total_plus', total=total_refund)
    else:
        text += t(lang, 'finances_no_refunds')
    
    text += t(lang, 'finances_cashbacks')
    if cashbacks:
        total_cb = 0
        for c in cashbacks:
            created_at = datetime.fromisoformat(c['created_at'])
            text += f"  {created_at.strftime('%d.%m %H:%M')} +{c['amount']} MDL\n"
            total_cb += c['amount']
        text += t(lang, 'finances_total_plus', total=total_cb)
    else:
        text += t(lang, 'finances_no_cashbacks')
    
    vip = await db.get_vip_client(user.user_id, user.venue_id)
    text += t(lang, 'finances_balance', balance=vip.balance if vip else 0)
    
    await callback.message.edit_text(text, reply_markup=vip_kb.get_finances_period_menu(lang), parse_mode="Markdown")
    await callback.answer()

@router.callback_query(F.data == "vip_make_order")
async def vip_make_order(callback: CallbackQuery):
    user = await db.get_user(callback.from_user.id)
    if not user or user.role != config.ROLE_VIP:
        from handlers import client as client_handler
        return await client_handler.client_make_order(callback)
    lang = await get_lang(callback.from_user.id)
    await callback.message.edit_text(
        t(lang, 'vip_order_title'),
        reply_markup=vip_kb.get_order_type_menu(lang),
        parse_mode="Markdown"
    )
    await callback.answer()

@router.callback_query(F.data == "order_new_song")
async def order_new_song(callback: CallbackQuery):
    lang = await get_lang(callback.from_user.id)
    await callback.answer(
        t(lang, 'btn_find_song'),
        show_alert=True
    )

@router.callback_query(F.data.startswith("select_song_"))
async def select_song(callback: CallbackQuery, state: FSMContext):
    song_id = int(callback.data.split("_")[-1])
    user = await db.get_user(callback.from_user.id)
    
    await state.update_data(song_id=song_id)
    
    services = await db.get_venue_services(user.venue_id)
    lang = await get_lang(callback.from_user.id)
    
    if not services:
        await callback.answer(t(lang, 'no_services'), show_alert=True)
        return
    
    vip = await db.get_vip_client(user.user_id, user.venue_id)
    
    builder = InlineKeyboardBuilder()
    service_desc_lines = []
    for service in services:
        price_text = t(lang, 'service_free') if service.is_free else f"{service.price} MDL"
        desc = f" — {html.escape(service.description)}" if service.description else ""
        service_desc_lines.append(f"• <b>{html.escape(service.name)}</b> ({price_text}){desc}")
        builder.row(
            InlineKeyboardButton(
                text=f"{service.name} - {price_text}",
                callback_data=f"vip_select_service_{service.service_id}"
            )
        )
    builder.row(InlineKeyboardButton(text=t(lang, 'btn_back'), callback_data="order_new_song"))
    
    services_text = "\n".join(service_desc_lines)
    balance_line = t(lang, 'balance_line', balance=int(vip.balance)) if (vip and user.role == config.ROLE_VIP) else ""
    
    await callback.message.edit_text(
        t(lang, 'choose_service_title', balance_line=balance_line) + t(lang, 'choose_service_body', services=services_text),
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )
    await callback.answer()

@router.callback_query(F.data.startswith("vip_select_service_"))
async def select_service(callback: CallbackQuery, state: FSMContext):
    service_id = int(callback.data.split("_")[-1])
    user = await db.get_user(callback.from_user.id)
    data = await state.get_data()
    song_id = data.get('song_id')
    
    service = await db.get_service(service_id)
    song = await db.get_song(song_id)
    vip = await db.get_vip_client(user.user_id, user.venue_id)
    
    if not service.is_free:
        if not vip or vip.balance < service.price:
            lang = await get_lang(callback.from_user.id)
            await callback.answer(
                t(lang, 'insufficient_balance'),
                show_alert=True
            )
            await state.clear()
            return
    
    order_id = await db.create_order(
        venue_id=user.venue_id,
        table_number=user.table_number,
        user_id=user.user_id,
        service_id=service_id,
        song_name=f"{song['artist']} - {song['title']}"
    )
    
    if not service.is_free:
        await db.charge_vip_for_order(
            user.user_id, user.venue_id, service.price,
            order_id, f"{song['artist']} - {song['title']}"
        )
    
    await db.log_event('order_created', user.venue_id, user.user_id,
                       f'Заказ #{order_id}: {song["artist"]} - {song["title"]}, услуга: {service.name}')
    
    kj = await db.get_user_by_venue(user.venue_id)
    lang = await get_lang(callback.from_user.id)
    if kj:
        kj_lang = await get_lang(kj.user_id)
        try:
            await callback.bot.send_message(
                kj.user_id,
                t(kj_lang, 'kj_new_order',
                  order_id=order_id,
                  table=t(kj_lang, 'kj_table_label', table=user.table_number),
                  name=html.escape(user.first_name or ''),
                  vip_badge='⭐ VIP',
                  song=html.escape(f"{song['artist']} - {song['title']}"),
                  service=html.escape(service.name),
                  pos=0,
                  active=1,
                  max=config.MAX_ACTIVE_SONGS_PER_USER),
                parse_mode="HTML"
            )
        except Exception:
            pass
    
    await callback.answer(t(lang, 'order_created'), show_alert=True)
    await state.clear()

    await callback.message.edit_text(
        t(lang, 'order_created'),
        parse_mode="HTML"
    )
    import asyncio
    await asyncio.sleep(3)
    try:
        await callback.message.delete()
    except Exception:
        pass
    await utils.send_user_menu(callback.bot, callback.from_user.id, callback.message.chat.id)

@router.callback_query(F.data == "order_favorites")
async def order_favorites(callback: CallbackQuery):
    user = await db.get_user(callback.from_user.id)
    if not user or user.role != config.ROLE_VIP:
        from handlers import client as client_handler
        return await client_handler.order_favorites(callback)

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
        builder.row(InlineKeyboardButton(text=t(lang, 'btn_back'), callback_data="vip_make_order"))
        
        await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="Markdown")
    else:
        builder = InlineKeyboardBuilder()
        builder.row(InlineKeyboardButton(text=t(lang, 'btn_back'), callback_data="vip_make_order"))
        await callback.message.edit_text(
            t(lang, 'favorites_empty'),
            reply_markup=builder.as_markup(),
            parse_mode="Markdown"
        )
    await callback.answer()

@router.callback_query(F.data.startswith("fav_action_"))
async def fav_action(callback: CallbackQuery):
    user = await db.get_user(callback.from_user.id)
    if not user or user.role != config.ROLE_VIP:
        from handlers import client as client_handler
        return await client_handler.fav_action(callback)

    favorite_id = int(callback.data.split("_")[-1])
    lang = await get_lang(callback.from_user.id)
    
    await callback.message.edit_text(
        t(lang, 'choose_action'),
        reply_markup=vip_kb.get_favorite_actions(favorite_id, lang=lang)
    )
    await callback.answer()

@router.callback_query(F.data.startswith("fav_reorder_"))
async def fav_reorder(callback: CallbackQuery):
    user = await db.get_user(callback.from_user.id)
    if not user or user.role != config.ROLE_VIP:
        from handlers import client as client_handler
        return await client_handler.fav_reorder(callback)

    favorite_id = int(callback.data.split("_")[-1])

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
        await vip_main_menu(callback)
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
        lang2 = await get_lang(callback.from_user.id)
        await callback.answer(t(lang2, 'song_not_found'), show_alert=True)
        return

    vip = await db.get_vip_client(user.user_id, user.venue_id)

    if not fav['is_free']:
        if not vip or vip.balance < fav['price']:
            lang2 = await get_lang(callback.from_user.id)
            await callback.answer(t(lang2, 'insufficient_balance'), show_alert=True)
            return

    order_id = await db.create_order(
        venue_id=user.venue_id,
        table_number=user.table_number,
        user_id=user.user_id,
        service_id=fav['service_id'],
        song_name=f"{fav['artist']} - {fav['title']}",
        status="waiting"
    )

    if not fav['is_free']:
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
    if kj:
        kj_lang = await get_lang(kj.user_id)
        vip_badge = "⭐ VIP" if vip else ""
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
                t(kj_lang, 'kj_new_order',
                  order_id=order_id,
                  table=t(kj_lang, 'kj_table_label', table=user.table_number),
                  name=html.escape(user.first_name or ''),
                  vip_badge=vip_badge,
                  song=html.escape(f"{fav['artist']} - {fav['title']}"),
                  service=html.escape(str(fav['service_name'])),
                  pos=position,
                  active=active_user_orders,
                  max=config.MAX_ACTIVE_SONGS_PER_USER),
                reply_markup=builder.as_markup(),
                parse_mode="HTML"
            )
        except Exception:
            pass

    admin_user_id = await db.get_table_admin_user_id(user.venue_id, user.table_number)
    venue = await db.get_venue(user.venue_id)
    await callback.message.edit_text(
        t(lang, 'order_sent',
          order_id=order_id,
          song=html.escape(f"{fav['artist']} - {fav['title']}"),
          service=html.escape(str(fav['service_name'])),
          pos=position),
        parse_mode="HTML"
    )
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
    user = await db.get_user(callback.from_user.id)
    if not user or user.role != config.ROLE_VIP:
        from handlers import client as client_handler
        return await client_handler.fav_delete(callback)

    favorite_id = int(callback.data.split("_")[-1])
    lang = await get_lang(callback.from_user.id)
    await db.remove_from_favorites(favorite_id)
    await callback.answer(t(lang, 'favorite_removed'), show_alert=True)
    await order_favorites(callback)

@router.callback_query(F.data == "vip_my_orders")
async def vip_my_orders(callback: CallbackQuery):
    user = await db.get_user(callback.from_user.id)
    lang = await get_lang(callback.from_user.id)
    orders = await db.get_orders_by_table(user.venue_id, user.table_number)
    
    text = t(lang, 'my_orders_title')
    
    number_emojis = ['1️⃣', '2️⃣', '3️⃣', '4️⃣', '5️⃣', '6️⃣', '7️⃣', '8️⃣', '9️⃣', '🔟']
    
    if orders:
        builder = InlineKeyboardBuilder()
        order_idx = 1
        for order in orders:
            if order.status == 'pending':
                emoji = number_emojis[order_idx - 1] if order_idx <= len(number_emojis) else f"{order_idx}."
                button_text = f"{emoji} {order.song_name}"
                builder.row(
                    InlineKeyboardButton(
                        text=button_text,
                        callback_data=f"order_action_{order.order_id}"
                    )
                )
                order_idx += 1
        builder.row(InlineKeyboardButton(text=t(lang, 'btn_back'), callback_data="vip_main"))
        
        await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="Markdown")
    else:
        await callback.message.edit_text(
            t(lang, 'my_orders_empty'),
            reply_markup=vip_kb.get_back_to_main(lang),
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
        reply_markup=vip_kb.get_order_actions(order_id, can_replace, lang)
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

@router.callback_query(F.data.startswith("order_replace_"))
async def order_replace(callback: CallbackQuery, state: FSMContext):
    order_id = int(callback.data.split("_")[-1])
    user = await db.get_user(callback.from_user.id)
    lang = await get_lang(callback.from_user.id)

    order = await db.get_order(order_id)

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
        InlineKeyboardButton(text=t(lang, 'btn_cancel'), callback_data="vip_my_orders")
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
    
    await vip_my_orders(callback)

@router.callback_query(F.data == "vip_queue")
async def vip_queue(callback: CallbackQuery):
    user = await db.get_user(callback.from_user.id)
    venue = await db.get_venue(user.venue_id)
    
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
    
    lang = await get_lang(callback.from_user.id)
    text = t(lang, 'queue_title')
    
    if playing_song:
        text += t(lang, 'queue_now_playing',
                  table=playing_song['table_number'],
                  song=playing_song['song_name'])
    
    if venue.table_mode == "sequential":
        all_orders = []
        for table_num in range(1, venue.table_count + 1):
            orders = await db.get_orders_by_table(user.venue_id, table_num)
            pending_orders = [o for o in orders if o.status == 'pending']
            for order in pending_orders[:config.MAX_ACTIVE_SONGS_PER_USER]:
                all_orders.append({
                    'table': table_num,
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
                            next_songs.append((table_num, order))
                        else:
                            regular_songs.append((table_num, order))
            
            if next_songs:
                text += t(lang, 'queue_next_header')
                for table_num, order in next_songs:
                    text += t(lang, 'queue_table_str', num=table_num) + f" — {order['song']}\n"
                text += "\n—————————\n\n"
            
            if regular_songs:
                text += t(lang, 'queue_regular_header')
                current_table = None
                for table_num, order in regular_songs:
                    if current_table != table_num:
                        if current_table is not None:
                            text += "\n"
                        text += t(lang, 'queue_table_str', num=table_num) + "\n"
                        current_table = table_num
                    text += f"    └  {order['song']}\n"
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
                    text += t(lang, 'queue_table_str', num=row['table_number']) + f" — {row['song_name']}\n"
                text += "\n—————————\n\n"
            
            if regular_songs:
                text += t(lang, 'queue_regular_header')
                current_table = None
                for row in regular_songs:
                    if current_table != row['table_number']:
                        if current_table is not None:
                            text += "\n"
                        text += t(lang, 'queue_table_str', num=row['table_number']) + "\n"
                        current_table = row['table_number']
                    text += f"    └  {row['song_name']}\n"
        else:
            text += t(lang, 'queue_empty')
    
    await callback.message.edit_text(text, reply_markup=vip_kb.get_back_to_main(lang), parse_mode="HTML")
    await callback.answer()

@router.callback_query(F.data == "vip_chat_kj")
async def vip_chat_kj(callback: CallbackQuery, state: FSMContext):
    import logging
    logger = logging.getLogger(__name__)
    lang = await get_lang(callback.from_user.id)
    sent = await callback.message.answer(
        t(lang, 'chat_title'),
        reply_markup=vip_kb.get_cancel_keyboard(lang),
        parse_mode="HTML"
    )
    logger.info("VIP_CHAT prompt sent message_id=%s chat_id=%s", sent.message_id, sent.chat.id)
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
    logger.info("VIP_CHAT delete attempt prompt_id=%s prompt_chat_id=%s", prompt_id, prompt_chat_id)
    if prompt_id:
        try:
            await message.bot.delete_message(prompt_chat_id, prompt_id)
            logger.info("VIP_CHAT prompt deleted")
        except Exception as exc:
            logger.exception("VIP_CHAT prompt delete failed: %s", exc)
            try:
                await message.bot.edit_message_reply_markup(
                    chat_id=prompt_chat_id,
                    message_id=prompt_id,
                    reply_markup=None
                )
                logger.info("VIP_CHAT prompt markup removed")
            except Exception as exc2:
                logger.exception("VIP_CHAT prompt markup remove failed: %s", exc2)
                pass
    
    user = await db.get_user(message.from_user.id)
    venue = await db.get_venue(user.venue_id)
    
    kj = await db.get_kj_by_venue(user.venue_id)
    
    lang = await get_lang(message.from_user.id)

    if not kj:
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
    
    kj_lang = await get_lang(kj.user_id)
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text=t(kj_lang, 'btn_chat_reply'), callback_data=f"chat_reply_{user.user_id}")
    )
    
    admin_user_id = await db.get_table_admin_user_id(user.venue_id, user.table_number)
    try:
        await message.bot.send_message(
            kj.user_id,
            t(kj_lang, 'chat_msg_to_kj',
              table=user.table_number,
              name=html.escape(user.first_name or ''),
              vip_badge='⭐ VIP',
              text=html.escape(message.text or '')),
            reply_markup=builder.as_markup(),
            parse_mode="HTML"
        )
        await message.answer(
            t(lang, 'chat_sent'),
            reply_markup=vip_kb.get_vip_main_menu(admin_user_id == user.user_id, venue.chat_enabled, venue.chat_link, lang)
        )
    except Exception:
        await message.answer(
            t(lang, 'chat_failed'),
            reply_markup=vip_kb.get_vip_main_menu(admin_user_id == user.user_id, venue.chat_enabled, venue.chat_link, lang)
        )
    
    await state.clear()

@router.callback_query(F.data.startswith("client_chat_reply_"))
async def vip_chat_reply(callback: CallbackQuery, state: FSMContext):
    kj_id = int(callback.data.split("_")[3])

    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    
    await state.update_data(kj_id=kj_id)
    await state.set_state(ChatForm.message)
    
    lang = await get_lang(callback.from_user.id)
    sent = await callback.message.answer(
        t(lang, 'chat_title'),
        parse_mode="HTML"
    )
    await state.update_data(_prompt_msg_id=sent.message_id, _prompt_chat_id=sent.chat.id)
    await callback.answer()

@router.callback_query(F.data.startswith("cancel_"))
async def cancel_action(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    lang = await get_lang(callback.from_user.id)
    await callback.answer(t(lang, 'btn_cancel'))
    await vip_main_menu(callback)
