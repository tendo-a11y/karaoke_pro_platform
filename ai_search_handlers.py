"""
Команда /ai — умный поиск песни по свободному описанию (ТЗ п.5-6, 28-30):

    /ai -> гость описывает песню своими словами -> Claude + Genius (ai_search.py)
        -> 3-5 кнопок с вариантами -> выбор услуги -> обычное создание заказа

Сделано отдельным роутером с собственным FSM-состоянием, чтобы НЕ трогать
существующий inline-поиск (@bot query) в bot.py — он остаётся основным
способом поиска до тех пор, пока новый не протестирован (ТЗ п.30). После
выбора песни используется тот же db.create_order(...) и тот же путь
уведомления KJ, что и в основном сценарии — новый заказ ведёт себя для
остальной системы (KJ, очередь, статистика) неотличимо от найденного через
обычный поиск.
"""
import html
import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

import backend_client
import config
import utils
from ai_search import ai_powered_search
from database import Database
from lang import get_lang, t

router = Router()
db = Database()
logger = logging.getLogger(__name__)


class AiSearchState(StatesGroup):
    waiting_text = State()


@router.message(Command("ai"))
async def cmd_ai_search(message: Message, state: FSMContext):
    lang = await get_lang(message.from_user.id)
    user = await db.get_user(message.from_user.id)

    if not user or not user.venue_id:
        await message.answer(t(lang, 'error_no_rights'))
        return

    await state.set_state(AiSearchState.waiting_text)
    await message.answer(
        "🤖 Опишите песню своими словами — исполнителя, кусок текста, о чём песня.\n\n"
        "Например: «Дима Билан идёт по улице, машины, хочешь куплю»"
    )


@router.message(AiSearchState.waiting_text)
async def handle_ai_search_text(message: Message, state: FSMContext):
    lang = await get_lang(message.from_user.id)
    text = (message.text or "").strip()

    if not text:
        await message.answer(t(lang, 'error_data'))
        return

    searching_msg = await message.answer("🔎 Ищу...")
    results = await ai_powered_search(text)

    if not results:
        await state.clear()
        await searching_msg.edit_text(
            "😔 Ничего не нашлось по описанию. Попробуйте переформулировать "
            "или воспользуйтесь обычным поиском через @-упоминание бота."
        )
        return

    await state.update_data(ai_results=results)

    builder = InlineKeyboardBuilder()
    lines = []
    for idx, item in enumerate(results):
        label = f"{item['title']} — {item['artist']}" if item.get('artist') else item['title']
        lines.append(f"{idx + 1}. {html.escape(label)}")
        builder.row(InlineKeyboardButton(text=f"{idx + 1}. {label}"[:64], callback_data=f"ai_pick_{idx}"))

    await searching_msg.edit_text(
        "🎵 Вот что удалось найти:\n\n" + "\n".join(lines) + "\n\nВыберите вариант:",
        reply_markup=builder.as_markup(),
    )


@router.callback_query(F.data.startswith("ai_pick_"))
async def handle_ai_pick(callback: CallbackQuery, state: FSMContext):
    lang = await get_lang(callback.from_user.id)
    idx = int(callback.data.split("_")[2])

    data = await state.get_data()
    results = data.get("ai_results") or []
    if idx >= len(results):
        await callback.answer(t(lang, 'error_data'), show_alert=True)
        return

    user = await db.get_user(callback.from_user.id)
    services = await db.get_venue_services(user.venue_id)
    if not services:
        await callback.answer(t(lang, 'no_services'), show_alert=True)
        return

    builder = InlineKeyboardBuilder()
    for service in services:
        price_text = t(lang, 'btn_free') if service.is_free else f"{service.price} MDL"
        builder.row(
            InlineKeyboardButton(
                text=f"{service.name} - {price_text}",
                callback_data=f"ai_svc_{idx}_{service.service_id}",
            )
        )

    item = results[idx]
    label = f"{item['title']} — {item['artist']}" if item.get('artist') else item['title']
    await callback.message.edit_text(f"🎵 {html.escape(label)}\n\nВыберите услугу:", reply_markup=builder.as_markup())
    await callback.answer()


@router.callback_query(F.data.startswith("ai_svc_"))
async def handle_ai_service_selection(callback: CallbackQuery, state: FSMContext):
    lang = await get_lang(callback.from_user.id)
    parts = callback.data.split("_")
    idx = int(parts[2])
    service_id = int(parts[3])

    data = await state.get_data()
    results = data.get("ai_results") or []
    if idx >= len(results):
        await callback.answer(t(lang, 'error_data'), show_alert=True)
        return
    item = results[idx]

    user = await db.get_user(callback.from_user.id)
    service = await db.get_service(service_id)
    venue = await db.get_venue(user.venue_id)
    if not service:
        await callback.answer(t(lang, 'error_data'), show_alert=True)
        return

    vip = await db.get_vip_client(user.user_id, user.venue_id)
    if vip and not service.is_free and vip.balance < service.price:
        await callback.answer(
            t(lang, 'insufficient_balance_detail', balance=vip.balance, price=service.price),
            show_alert=True,
        )
        return

    async with db.get_db() as db_conn:
        async with db_conn.execute(
            """SELECT COUNT(*) FROM orders
               WHERE venue_id = ? AND table_number = ? AND user_id = ? AND status IN ('pending', 'waiting')""",
            (user.venue_id, user.table_number, user.user_id),
        ) as cursor:
            orders_count = (await cursor.fetchone())[0]

    if orders_count >= config.MAX_ACTIVE_SONGS_PER_USER:
        await callback.answer(
            t(lang, 'order_limit_reached', limit=config.MAX_ACTIVE_SONGS_PER_USER), show_alert=True
        )
        return

    artist = item.get("artist") or ""
    title = item["title"]
    song_display_name = f"{artist} - {title}" if artist else title

    order_id = await db.create_order(
        venue_id=user.venue_id,
        table_number=user.table_number,
        user_id=user.user_id,
        service_id=service.service_id,
        song_name=song_display_name,
        status="waiting",
    )
    logger.info("AI_SEARCH order_created order_id=%s table=%s query=%s", order_id, user.table_number, title)

    if vip and not service.is_free:
        await db.charge_vip_for_order(user.user_id, user.venue_id, service.price, order_id, song_display_name)

    await db.log_event(
        'order_created', user.venue_id, user.user_id,
        f'Заказ #{order_id} (AI-поиск): {song_display_name}, услуга: {service.name}',
    )

    is_no_table = user.role == config.ROLE_NO_TABLE or (
        venue and utils.is_virtual_table(user.table_number, venue.table_count)
    )

    import asyncio
    asyncio.create_task(
        backend_client.post_order_to_backend(
            telegram_user_id=user.user_id,
            club_id=user.venue_id,
            table_no=None if is_no_table else user.table_number,
            song_title=title,
            artist=artist or None,
        )
    )

    async with db.get_db() as db_conn:
        async with db_conn.execute("SELECT position FROM orders WHERE order_id = ?", (order_id,)) as cursor:
            row = await cursor.fetchone()
            position = row[0] if row else 0
        async with db_conn.execute(
            """SELECT COUNT(*) FROM orders
               WHERE venue_id = ? AND table_number = ? AND user_id = ? AND status IN ('pending', 'waiting')""",
            (user.venue_id, user.table_number, user.user_id),
        ) as cursor:
            active_user_orders = (await cursor.fetchone())[0]

    table_label = utils.get_table_label(user.table_number, venue.table_count) if venue else f"Стол {user.table_number}"

    kj = await db.get_kj_by_venue(user.venue_id)
    if kj:
        kj_lang = await get_lang(kj.user_id)
        kj_builder = InlineKeyboardBuilder()
        kj_builder.row(
            InlineKeyboardButton(text=t(kj_lang, 'btn_order_cancel'), callback_data=f"order_reject_{order_id}"),
            InlineKeyboardButton(text=t(kj_lang, 'btn_order_approve'), callback_data=f"order_approve_{order_id}"),
        )
        vip_badge = "⭐ VIP" if vip else ""
        table_label_str = (
            f"🪑 Стол: <b>{table_label}</b>" if not is_no_table
            else t(kj_lang, 'kj_no_table_label', num=user.table_number)
        )
        no_table_warning = t(kj_lang, 'kj_new_order_no_table_warn') if is_no_table else ""
        try:
            await callback.bot.send_message(
                kj.user_id,
                t(kj_lang, 'kj_new_order',
                  order_id=order_id, table=table_label_str,
                  name=html.escape(user.first_name or ''), vip_badge=vip_badge,
                  song=html.escape(song_display_name), service=html.escape(service.name),
                  pos=position, active=active_user_orders, max=config.MAX_ACTIVE_SONGS_PER_USER) + no_table_warning,
                reply_markup=kj_builder.as_markup(),
                parse_mode="HTML",
            )
        except Exception:
            logger.exception("AI_SEARCH failed to notify KJ")

    await state.clear()
    await callback.message.edit_text(
        t(lang, 'order_sent', order_id=order_id, song=html.escape(song_display_name),
          service=html.escape(service.name), pos=position)
    )
    await callback.answer()
    await utils.send_user_menu(callback.bot, user.user_id)
