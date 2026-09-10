from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from datetime import datetime, timedelta
import aiosqlite

from database import Database
from keyboards import admin_kb
import config
import utils
from lang import get_lang, t

router = Router()
db = Database()

class VenueForm(StatesGroup):
    name = State()
    city = State()
    phone = State()
    email = State()

class VenueEditForm(StatesGroup):
    edit_name = State()

class AssignKJForm(StatesGroup):
    venue_id = State()
    username = State()

class AdminManagementForm(StatesGroup):
    user_identifier = State()

@router.message(Command("admin"))
async def cmd_admin(message: Message):
    user = await db.get_user(message.from_user.id)
    lang = await get_lang(message.from_user.id)

    if not user or user.role != config.ROLE_ADMIN:
        await message.answer(t(lang, 'admin_no_rights'))
        return

    venues = await db.get_all_venues()
    total_venues = len(venues)
    active_venues = len([v for v in venues if v.is_active])

    today = utils.get_stats_date()
    total_revenue = 0
    for venue in venues:
        revenue = await db.get_daily_revenue(venue.venue_id, today)
        total_revenue += revenue

    text = t(lang, 'admin_panel_main',
             clubs=total_venues,
             active=active_venues,
             revenue=utils.format_currency(total_revenue))

    await message.answer(text, reply_markup=admin_kb.get_admin_main_menu(lang), parse_mode="Markdown")

@router.message(Command("set_admin"))
async def cmd_set_admin(message: Message, state: FSMContext):
    lang = await get_lang(message.from_user.id)
    if message.from_user.id != config.ADMIN_ID:
        await message.answer(t(lang, 'admin_not_main_admin'))
        return

    await message.answer(t(lang, 'admin_set_admin_prompt'), parse_mode="Markdown")
    await state.set_state(AdminManagementForm.user_identifier)

@router.message(AdminManagementForm.user_identifier)
async def process_admin_management(message: Message, state: FSMContext):
    lang = await get_lang(message.from_user.id)
    data = await state.get_data()
    action = data.get('action', 'set')

    identifier = message.text.strip()

    if identifier.startswith("@"):
        username = identifier[1:]
        user = await db.get_user_by_username(username)
    elif identifier.isdigit():
        user_id = int(identifier)
        user = await db.get_user(user_id)
    else:
        await message.answer(t(lang, 'admin_invalid_identifier'))
        return

    if not user:
        await message.answer(t(lang, 'admin_user_not_found'))
        await state.clear()
        return

    if action == 'set':
        if user.role == config.ROLE_ADMIN:
            await message.answer(t(lang, 'admin_already_admin',
                                   name=user.first_name,
                                   username=user.username or 'нет'))
            await state.clear()
            return

        await db.update_user_role(user.user_id, config.ROLE_ADMIN, None)

        try:
            await message.bot.send_message(
                user.user_id,
                t('ru', 'admin_new_admin_notify'),
                parse_mode="Markdown"
            )
        except Exception:
            pass

        await message.answer(t(lang, 'admin_set_done',
                               name=user.first_name,
                               username=user.username or 'нет',
                               uid=user.user_id))

    else:
        if user.user_id == config.ADMIN_ID:
            await message.answer(t(lang, 'admin_cant_unset_main'))
            await state.clear()
            return

        if user.role != config.ROLE_ADMIN:
            await message.answer(t(lang, 'admin_not_admin_user',
                                   name=user.first_name,
                                   username=user.username or 'нет'))
            await state.clear()
            return

        await db.update_user_role(user.user_id, config.ROLE_USER, None)

        try:
            await message.bot.send_message(
                user.user_id,
                t('ru', 'admin_admin_revoked_notify')
            )
        except Exception:
            pass

        await message.answer(t(lang, 'admin_unset_done',
                               name=user.first_name,
                               username=user.username or 'нет',
                               uid=user.user_id))

    await state.clear()

@router.message(Command("unset_admin"))
async def cmd_unset_admin(message: Message, state: FSMContext):
    lang = await get_lang(message.from_user.id)
    if message.from_user.id != config.ADMIN_ID:
        await message.answer(t(lang, 'admin_not_main_admin'))
        return

    await message.answer(t(lang, 'admin_unset_admin_prompt'), parse_mode="Markdown")
    await state.update_data(action='unset')
    await state.set_state(AdminManagementForm.user_identifier)

@router.callback_query(F.data == "admin_main")
async def admin_main_callback(callback: CallbackQuery):
    lang = await get_lang(callback.from_user.id)
    venues = await db.get_all_venues()
    total_venues = len(venues)
    active_venues = len([v for v in venues if v.is_active])

    today = utils.get_stats_date()
    total_revenue = 0
    for venue in venues:
        revenue = await db.get_daily_revenue(venue.venue_id, today)
        total_revenue += revenue

    text = t(lang, 'admin_panel_main',
             clubs=total_venues,
             active=active_venues,
             revenue=utils.format_currency(total_revenue))

    await callback.message.edit_text(text, reply_markup=admin_kb.get_admin_main_menu(lang), parse_mode="Markdown")
    await callback.answer()

@router.callback_query(F.data == "admin_refresh")
async def admin_refresh(callback: CallbackQuery):
    await admin_main_callback(callback)
    await callback.answer("✅")

@router.callback_query(F.data == "admin_venues")
async def show_venues(callback: CallbackQuery):
    lang = await get_lang(callback.from_user.id)
    venues = await db.get_all_venues()

    if not venues:
        text = t(lang, 'admin_venues_empty')
    else:
        text = t(lang, 'admin_venues_title', total=len(venues))
        for venue in venues:
            status = t(lang, 'admin_venue_status_online') if venue.is_active else t(lang, 'admin_venue_status_blocked')
            today = utils.get_stats_date()
            revenue = await db.get_daily_revenue(venue.venue_id, today)
            text += f"{venue.venue_id}. *{venue.name}* (ID:{venue.venue_id}) {status} | {utils.format_currency(revenue)}\n"

    await callback.message.edit_text(text, reply_markup=admin_kb.get_venues_menu(lang), parse_mode="Markdown")
    await callback.answer()

@router.callback_query(F.data == "venue_add")
async def venue_add_start(callback: CallbackQuery, state: FSMContext):
    lang = await get_lang(callback.from_user.id)
    await callback.message.edit_text(t(lang, 'admin_add_venue_title'), parse_mode="Markdown")
    await state.set_state(VenueForm.name)
    await callback.answer()

@router.message(VenueForm.name)
async def venue_add_name(message: Message, state: FSMContext):
    lang = await get_lang(message.from_user.id)
    await state.update_data(name=message.text)
    await message.answer(t(lang, 'admin_enter_city'))
    await state.set_state(VenueForm.city)

@router.message(VenueForm.city)
async def venue_add_city(message: Message, state: FSMContext):
    lang = await get_lang(message.from_user.id)
    await state.update_data(city=message.text)
    await message.answer(t(lang, 'admin_enter_phone'))
    await state.set_state(VenueForm.phone)

@router.message(VenueForm.phone)
async def venue_add_phone(message: Message, state: FSMContext):
    lang = await get_lang(message.from_user.id)
    await state.update_data(phone=message.text)
    await message.answer(t(lang, 'admin_enter_email'))
    await state.set_state(VenueForm.email)

@router.message(VenueForm.email)
async def venue_add_email(message: Message, state: FSMContext):
    lang = await get_lang(message.from_user.id)
    data = await state.get_data()
    venue_id = await db.create_venue(
        name=data['name'],
        city=data['city'],
        owner_phone=data['phone'],
        owner_email=message.text
    )

    await message.answer(
        t(lang, 'admin_venue_created', name=data['name'], vid=venue_id),
        reply_markup=admin_kb.get_admin_main_menu(lang)
    )
    await state.clear()

@router.callback_query(F.data == "venue_details")
async def venue_details_list(callback: CallbackQuery):
    lang = await get_lang(callback.from_user.id)
    venues = await db.get_all_venues()

    if not venues:
        await callback.answer("❌", show_alert=True)
        return

    await callback.message.edit_text(
        t(lang, 'admin_choose_venue'),
        reply_markup=admin_kb.get_venue_list_keyboard(venues, "venue_show", lang)
    )
    await callback.answer()

@router.callback_query(F.data.startswith("venue_show_"))
async def venue_show_details(callback: CallbackQuery, venue_id: int = None):
    lang = await get_lang(callback.from_user.id)
    if venue_id is None:
        venue_id = int(callback.data.split("_")[2])
    venue = await db.get_venue(venue_id)

    if not venue:
        await callback.answer("❌", show_alert=True)
        return

    kj = await db.get_user_by_venue(venue_id)
    kj_info = f"@{kj.username}" if kj else "-"

    today = utils.get_stats_date()
    revenue_today = await db.get_daily_revenue(venue_id, today)

    songs = await db.get_songs(venue_id)
    songs_count = len(songs) if songs else 0

    status = t(lang, 'admin_venue_active_status') if venue.is_active else t(lang, 'admin_venue_status_blocked')

    text = t(lang, 'admin_venue_details',
             name=venue.name,
             vid=venue_id,
             status=status,
             kj=kj_info,
             created=venue.created_at,
             tables=venue.table_count,
             songs=songs_count,
             revenue=utils.format_currency(revenue_today),
             city=venue.city,
             phone=venue.owner_phone,
             email=venue.owner_email)

    await callback.message.edit_text(
        text,
        reply_markup=admin_kb.get_venue_details_menu(venue_id, lang),
        parse_mode="Markdown"
    )
    await callback.answer()

@router.callback_query(F.data.startswith("venue_finance_"))
async def venue_finance_details(callback: CallbackQuery):
    lang = await get_lang(callback.from_user.id)
    venue_id = int(callback.data.split("_")[2])
    venue = await db.get_venue(venue_id)

    if not venue:
        await callback.answer("❌", show_alert=True)
        return

    today = utils.get_stats_date()
    revenue_today = await db.get_daily_revenue(venue_id, today)

    week_start = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
    revenue_week = await db.get_period_revenue(venue_id, week_start, today)

    month_start = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
    revenue_month = await db.get_period_revenue(venue_id, month_start, today)

    admin_cashback = revenue_month * config.ADMIN_COMMISSION

    text = t(lang, 'admin_venue_finance',
             name=venue.name,
             today=utils.format_currency(revenue_today),
             week=utils.format_currency(revenue_week),
             month=utils.format_currency(revenue_month),
             admin_fee=utils.format_currency(admin_cashback))

    await callback.message.edit_text(
        text,
        reply_markup=admin_kb.get_back_button(f"venue_show_{venue_id}", lang),
        parse_mode="Markdown"
    )
    await callback.answer()

@router.callback_query(F.data.startswith("venue_songs_"))
async def venue_songs_management(callback: CallbackQuery):
    lang = await get_lang(callback.from_user.id)
    venue_id = int(callback.data.split("_")[2])
    venue = await db.get_venue(venue_id)

    if not venue:
        await callback.answer("❌", show_alert=True)
        return

    songs = await db.get_songs(venue_id)
    songs_count = len(songs) if songs else 0

    text = t(lang, 'admin_venue_songs', name=venue.name, count=songs_count)

    await callback.message.edit_text(
        text,
        reply_markup=admin_kb.get_back_button(f"venue_show_{venue_id}", lang),
        parse_mode="Markdown"
    )
    await callback.answer()

@router.callback_query(F.data.startswith("venue_qr_"))
async def venue_qr_code(callback: CallbackQuery):
    lang = await get_lang(callback.from_user.id)
    venue_id = int(callback.data.split("_")[2])
    venue = await db.get_venue(venue_id)

    if not venue:
        await callback.answer("❌", show_alert=True)
        return

    bot_username = (await callback.bot.get_me()).username

    import qrcode
    from io import BytesIO
    from aiogram.types import BufferedInputFile

    deeplink = f"https://t.me/{bot_username}?start=venue{venue_id}"

    qr = qrcode.QRCode(version=1, box_size=10, border=2)
    qr.add_data(deeplink)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")

    bio = BytesIO()
    img.save(bio, 'PNG')
    bio.seek(0)

    photo = BufferedInputFile(bio.read(), filename=f"venue_{venue_id}_qr.png")

    await callback.message.answer_photo(
        photo=photo,
        caption=(
            f"🎵 *{venue.name}*\n\n"
            + t(lang, 'admin_venue_qr_caption', tables=venue.table_count)
        ),
        parse_mode="Markdown"
    )

    await callback.answer("✅")

@router.callback_query(F.data.startswith("venue_edit_name_"))
async def venue_edit_name_start(callback: CallbackQuery, state: FSMContext):
    lang = await get_lang(callback.from_user.id)
    venue_id = int(callback.data.split("_")[3])
    venue = await db.get_venue(venue_id)

    if not venue:
        await callback.answer("❌", show_alert=True)
        return

    await state.set_state(VenueEditForm.edit_name)
    await state.update_data(venue_id=venue_id)

    await callback.message.answer(
        t(lang, 'admin_edit_name_prompt', name=venue.name),
        parse_mode="Markdown"
    )
    await callback.answer()

@router.message(VenueEditForm.edit_name)
async def venue_edit_name_process(message: Message, state: FSMContext):
    lang = await get_lang(message.from_user.id)
    data = await state.get_data()
    venue_id = data['venue_id']
    new_name = message.text.strip()

    await db.update_venue_name(venue_id, new_name)
    await state.clear()

    await message.answer(
        t(lang, 'admin_name_changed', name=new_name),
        parse_mode="Markdown"
    )

@router.callback_query(F.data.startswith("venue_refresh_"))
async def venue_refresh_data(callback: CallbackQuery):
    venue_id = int(callback.data.split("_")[2])
    
    await venue_show_details(callback, venue_id=venue_id)

@router.callback_query(F.data.startswith("venue_unbind_tables_"))
async def venue_unbind_all_tables(callback: CallbackQuery):
    lang = await get_lang(callback.from_user.id)
    venue_id = int(callback.data.split("_")[3])

    count = await db.get_table_orders_count(venue_id)
    venue = await db.get_venue(venue_id)

    text = t(lang, 'admin_unbind_tables_confirm', venue=venue.name, count=count)

    await callback.message.edit_text(
        text,
        reply_markup=admin_kb.get_confirmation_keyboard("venue_unbind_tables", str(venue_id), lang),
        parse_mode="Markdown"
    )
    await callback.answer()

@router.callback_query(F.data.startswith("confirm_venue_unbind_tables_"))
async def confirm_venue_unbind_tables(callback: CallbackQuery):
    lang = await get_lang(callback.from_user.id)
    venue_id = int(callback.data.split("_")[4])

    affected_ids = await db.reset_venue_roles(venue_id)

    count = await db.unbind_all_tables(venue_id)
    venue = await db.get_venue(venue_id)

    for uid in affected_ids:
        try:
            await callback.bot.send_message(uid, t('ru', 'session_ended'))
        except Exception:
            pass

    await callback.message.edit_text(
        t(lang, 'admin_unbind_tables_done', venue=venue.name, count=count),
        parse_mode="Markdown"
    )
    await callback.answer("✅")

@router.callback_query(F.data.startswith("venue_unbind_all_"))
async def venue_unbind_all_venue(callback: CallbackQuery):
    lang = await get_lang(callback.from_user.id)
    venue_id = int(callback.data.split("_")[3])

    import aiosqlite
    async with db.get_db() as db_conn:
        async with db_conn.execute(
            "SELECT COUNT(*) FROM users WHERE venue_id = ?",
            (venue_id,)
        ) as cursor:
            result = await cursor.fetchone()
            count = result[0] if result else 0

    venue = await db.get_venue(venue_id)

    text = t(lang, 'admin_unbind_venue_confirm', venue=venue.name, count=count)

    await callback.message.edit_text(
        text,
        reply_markup=admin_kb.get_confirmation_keyboard("venue_unbind_all", str(venue_id), lang),
        parse_mode="Markdown"
    )
    await callback.answer()

@router.callback_query(F.data.startswith("confirm_venue_unbind_all_"))
async def confirm_venue_unbind_all(callback: CallbackQuery):
    lang = await get_lang(callback.from_user.id)
    venue_id = int(callback.data.split("_")[4])

    affected_ids = await db.reset_venue_roles(venue_id)

    count = await db.unbind_all_venue_users(venue_id)
    venue = await db.get_venue(venue_id)

    for uid in affected_ids:
        try:
            await callback.bot.send_message(uid, t('ru', 'session_ended'))
        except Exception:
            pass

    await callback.message.edit_text(
        t(lang, 'admin_unbind_venue_done', venue=venue.name, count=count),
        parse_mode="Markdown"
    )
    await callback.answer("✅")

@router.callback_query(F.data.startswith("cancel_venue_unbind_"))
async def cancel_venue_unbind(callback: CallbackQuery):
    lang = await get_lang(callback.from_user.id)
    await callback.message.edit_text(t(lang, 'action_cancelled'))
    await callback.answer()

@router.callback_query(F.data == "venue_contacts")
async def venue_contacts_list(callback: CallbackQuery):
    lang = await get_lang(callback.from_user.id)
    venues = await db.get_all_venues()

    text = t(lang, 'admin_venue_contacts_header')

    if venues:
        for venue in venues:
            text += f"🏢 *{venue.name}* (ID:{venue.venue_id})\n"
            text += f"{venue.city} | {venue.owner_phone} | {venue.owner_email}\n\n"
    else:
        text += t(lang, 'admin_venue_contacts_empty')

    await callback.message.edit_text(
        text,
        reply_markup=admin_kb.get_back_button("admin_venues", lang),
        parse_mode="Markdown"
    )
    await callback.answer()

@router.callback_query(F.data.startswith("venue_assign_kj_"))
async def venue_assign_kj(callback: CallbackQuery, state: FSMContext):
    lang = await get_lang(callback.from_user.id)
    venue_id = int(callback.data.split("_")[-1])

    await state.update_data(venue_id=venue_id)
    await callback.message.edit_text(
        t(lang, 'admin_kj_enter_username'),
        parse_mode="Markdown"
    )
    await state.set_state(AssignKJForm.username)
    await callback.answer()

@router.message(AssignKJForm.username)
async def assign_kj_username(message: Message, state: FSMContext):
    lang = await get_lang(message.from_user.id)
    username = message.text.strip().lstrip("@")
    data = await state.get_data()
    venue_id = data['venue_id']

    user = await db.get_user_by_username(username)

    if not user:
        await message.answer(
            t(lang, 'admin_kj_not_found', username=username),
            reply_markup=admin_kb.get_admin_main_menu(lang)
        )
        await state.clear()
        return

    if user.user_id == config.ADMIN_ID:
        await message.answer(
            t(lang, 'admin_kj_cant_be_admin'),
            reply_markup=admin_kb.get_admin_main_menu(lang)
        )
        await state.clear()
        return

    await db.update_user_role(user.user_id, config.ROLE_KJ)
    await db.update_user_venue(user.user_id, venue_id)

    venue = await db.get_venue(venue_id)

    try:
        await message.bot.send_message(
            user.user_id,
            t('ru', 'admin_kj_welcome', venue=venue.name, city=venue.city),
            parse_mode="Markdown"
        )
        await message.answer(
            t(lang, 'admin_kj_assigned', username=username, venue=venue.name),
            reply_markup=admin_kb.get_admin_main_menu(lang)
        )
    except Exception:
        await message.answer(
            t(lang, 'admin_kj_assigned_no_notify', username=username, venue=venue.name),
            reply_markup=admin_kb.get_admin_main_menu(lang)
        )

    await state.clear()

@router.callback_query(F.data == "venue_toggle_block")
async def venue_toggle_block_list(callback: CallbackQuery):
    lang = await get_lang(callback.from_user.id)
    venues = await db.get_all_venues()

    if not venues:
        await callback.answer("❌", show_alert=True)
        return

    await callback.message.edit_text(
        t(lang, 'admin_venue_block_select'),
        reply_markup=admin_kb.get_venue_list_keyboard(venues, "venue_toggle", lang)
    )
    await callback.answer()

@router.callback_query(F.data.startswith("venue_toggle_"))
async def venue_toggle_confirm(callback: CallbackQuery):
    lang = await get_lang(callback.from_user.id)
    venue_id = int(callback.data.split("_")[2])
    venue = await db.get_venue(venue_id)

    key = 'admin_venue_toggle_unblock_confirm' if not venue.is_active else 'admin_venue_toggle_block_confirm'

    await callback.message.edit_text(
        t(lang, key, name=venue.name),
        reply_markup=admin_kb.get_confirm_keyboard("toggle_venue", str(venue_id), lang),
        parse_mode="Markdown"
    )
    await callback.answer()

@router.callback_query(F.data.startswith("confirm_toggle_venue_"))
async def venue_toggle_execute(callback: CallbackQuery):
    venue_id = int(callback.data.split("_")[3])
    venue = await db.get_venue(venue_id)

    new_status = not venue.is_active
    await db.update_venue_status(venue_id, new_status)

    await callback.answer("✅", show_alert=False)
    await show_venues(callback)

@router.callback_query(F.data == "venue_delete")
async def venue_delete_list(callback: CallbackQuery):
    lang = await get_lang(callback.from_user.id)
    venues = await db.get_all_venues()

    if not venues:
        await callback.answer("❌", show_alert=True)
        return

    await callback.message.edit_text(
        t(lang, 'admin_venue_delete_select'),
        reply_markup=admin_kb.get_venue_list_keyboard(venues, "venue_del", lang)
    )
    await callback.answer()

@router.callback_query(F.data.startswith("venue_del_"))
async def venue_delete_confirm(callback: CallbackQuery):
    lang = await get_lang(callback.from_user.id)
    venue_id = int(callback.data.split("_")[2])
    venue = await db.get_venue(venue_id)

    await callback.message.edit_text(
        f"⚠️ {t(lang, 'btn_venue_delete')} *{venue.name}*?",
        reply_markup=admin_kb.get_confirm_keyboard("delete_venue", str(venue_id), lang),
        parse_mode="Markdown"
    )
    await callback.answer()

@router.callback_query(F.data.startswith("confirm_delete_venue_"))
async def venue_delete_execute(callback: CallbackQuery):
    venue_id = int(callback.data.split("_")[3])
    await db.delete_venue(venue_id)

    await callback.answer("✅", show_alert=False)
    await show_venues(callback)

@router.callback_query(F.data == "admin_kj_list")
async def show_kj_list(callback: CallbackQuery):
    lang = await get_lang(callback.from_user.id)
    kj_list = await db.get_all_kj()

    text = t(lang, 'admin_kj_list_header', total=len(kj_list))

    if kj_list:
        for kj in kj_list:
            venue = await db.get_venue(kj.venue_id) if kj.venue_id else None
            venue_name = venue.name if venue else "-"
            venue_name_safe = venue_name.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            username_safe = (kj.username or "нет").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            status = f" {t(lang, 'admin_kj_blocked_status')}" if kj.is_blocked else ""
            text += f"• @{username_safe} → <b>{venue_name_safe}</b>{status}\n"
    else:
        text += t(lang, 'admin_kj_list_empty')

    await callback.message.edit_text(
        text,
        reply_markup=admin_kb.get_kj_menu(lang),
        parse_mode="HTML"
    )
    await callback.answer()

@router.callback_query(F.data == "kj_assign")
async def kj_assign_start(callback: CallbackQuery):
    lang = await get_lang(callback.from_user.id)
    venues = await db.get_all_venues()

    if not venues:
        await callback.answer("❌", show_alert=True)
        return

    from aiogram.utils.keyboard import InlineKeyboardBuilder
    from aiogram.types import InlineKeyboardButton

    builder = InlineKeyboardBuilder()
    for venue in venues:
        kj = await db.get_user_by_venue(venue.venue_id)
        status = f"(KJ: @{kj.username})" if kj else "(Free)"

        builder.row(
            InlineKeyboardButton(
                text=f"{venue.name} {status}",
                callback_data=f"venue_assign_kj_{venue.venue_id}"
            )
        )
    builder.row(InlineKeyboardButton(text=t(lang, 'btn_back'), callback_data="admin_kj_list"))

    await callback.message.edit_text(
        t(lang, 'admin_kj_assign_title'),
        reply_markup=builder.as_markup(),
        parse_mode="Markdown"
    )
    await callback.answer()

@router.callback_query(F.data == "kj_remove")
async def kj_remove_list(callback: CallbackQuery):
    lang = await get_lang(callback.from_user.id)
    kj_list = await db.get_all_kj()

    if not kj_list:
        await callback.answer("❌", show_alert=True)
        return

    from aiogram.utils.keyboard import InlineKeyboardBuilder
    from aiogram.types import InlineKeyboardButton

    builder = InlineKeyboardBuilder()
    for kj in kj_list:
        venue = await db.get_venue(kj.venue_id) if kj.venue_id else None
        venue_name = venue.name if venue else "-"
        builder.row(
            InlineKeyboardButton(
                text=f"@{kj.username} - {venue_name}",
                callback_data=f"kj_remove_confirm_{kj.user_id}"
            )
        )
    builder.row(InlineKeyboardButton(text=t(lang, 'btn_back'), callback_data="admin_kj_list"))

    await callback.message.edit_text(
        t(lang, 'admin_kj_remove_select'),
        reply_markup=builder.as_markup()
    )
    await callback.answer()

@router.callback_query(F.data.startswith("kj_remove_confirm_"))
async def kj_remove_confirm(callback: CallbackQuery):
    lang = await get_lang(callback.from_user.id)
    parts = callback.data.split("_")
    user_id = int(parts[-1])
    user = await db.get_user(user_id)

    await callback.message.edit_text(
        t(lang, 'admin_kj_remove_confirm', username=user.username or str(user_id)),
        reply_markup=admin_kb.get_confirm_keyboard("remove_kj", str(user_id), lang)
    )
    await callback.answer()

@router.callback_query(F.data.startswith("confirm_remove_kj_"))
async def kj_remove_execute(callback: CallbackQuery):
    parts = callback.data.split("_")
    user_id = int(parts[-1])
    await db.update_user_role(user_id, config.ROLE_USER, None)

    await callback.answer("✅", show_alert=False)
    await show_kj_list(callback)

@router.callback_query(F.data == "admin_kj_stats")
async def admin_kj_stats(callback: CallbackQuery):
    lang = await get_lang(callback.from_user.id)
    kj_list = await db.get_all_kj()

    text = t(lang, 'admin_kj_stats_header')
    today = utils.get_stats_date()

    for kj in kj_list:
        if kj.venue_id:
            venue = await db.get_venue(kj.venue_id)
            revenue = await db.get_daily_revenue(kj.venue_id, today)
            orders_count = await db.get_venue_orders_count(kj.venue_id, "completed", today)

            text += f"*@{kj.username}* ({venue.name})\n"
            text += f"  {utils.format_currency(revenue)} | {orders_count}\n\n"

    await callback.message.edit_text(
        text,
        reply_markup=admin_kb.get_back_button("admin_kj_list", lang),
        parse_mode="Markdown"
    )
    await callback.answer()

@router.callback_query(F.data == "kj_contacts")
async def kj_contacts(callback: CallbackQuery):
    lang = await get_lang(callback.from_user.id)
    kj_list = await db.get_all_kj()

    text = t(lang, 'admin_kj_contacts_header')

    if kj_list:
        for kj in kj_list:
            venue = await db.get_venue(kj.venue_id) if kj.venue_id else None
            venue_name = venue.name if venue else "-"
            text += f"• @{kj.username or 'нет'}\n"
            text += f"  ID: `{kj.user_id}` | {kj.first_name} | {venue_name}\n\n"
    else:
        text += t(lang, 'admin_kj_contacts_empty')

    await callback.message.edit_text(
        text,
        reply_markup=admin_kb.get_back_button("admin_kj_list", lang),
        parse_mode="Markdown"
    )
    await callback.answer()

@router.callback_query(F.data == "kj_toggle_block")
async def kj_toggle_block_list(callback: CallbackQuery):
    lang = await get_lang(callback.from_user.id)
    kj_list = await db.get_all_kj()

    if not kj_list:
        await callback.answer("❌", show_alert=True)
        return

    from aiogram.utils.keyboard import InlineKeyboardBuilder
    from aiogram.types import InlineKeyboardButton

    builder = InlineKeyboardBuilder()
    for kj in kj_list:
        status = "🔴" if kj.is_blocked else "🟢"
        builder.row(
            InlineKeyboardButton(
                text=f"{status} @{kj.username}",
                callback_data=f"kj_toggle_{kj.user_id}"
            )
        )
    builder.row(InlineKeyboardButton(text=t(lang, 'btn_back'), callback_data="admin_kj_list"))

    await callback.message.edit_text(
        t(lang, 'admin_kj_select_toggle'),
        reply_markup=builder.as_markup()
    )
    await callback.answer()

@router.callback_query(F.data.startswith("kj_toggle_"))
async def kj_toggle_execute(callback: CallbackQuery):
    user_id = int(callback.data.split("_")[2])
    user = await db.get_user(user_id)

    new_status = not user.is_blocked
    await db.block_user(user_id, new_status)

    await callback.answer("✅", show_alert=False)
    await kj_toggle_block_list(callback)

@router.callback_query(F.data == "admin_reports")
async def show_reports_menu(callback: CallbackQuery):
    lang = await get_lang(callback.from_user.id)
    today = utils.get_stats_date()
    venues = await db.get_all_venues()

    total_today = 0
    for venue in venues:
        revenue = await db.get_daily_revenue(venue.venue_id, today)
        total_today += revenue

    text = t(lang, 'admin_reports_header', today=utils.format_currency(total_today))

    await callback.message.edit_text(
        text,
        reply_markup=admin_kb.get_reports_menu(lang),
        parse_mode="Markdown"
    )
    await callback.answer()

@router.callback_query(F.data == "report_today")
async def report_today(callback: CallbackQuery):
    lang = await get_lang(callback.from_user.id)
    today = utils.get_stats_date()
    venues = await db.get_all_venues()

    text = t(lang, 'admin_report_today_title', date=today)
    text += "═" * 35 + "\n"

    total_revenue = 0
    total_orders = 0

    for venue in venues:
        revenue = await db.get_daily_revenue(venue.venue_id, today)
        orders_count = await db.get_venue_orders_count(venue.venue_id, "completed", today)
        total_revenue += revenue
        total_orders += orders_count
        percent = (revenue / total_revenue * 100) if total_revenue > 0 else 0
        text += f"├── *{venue.name}*: *{utils.format_currency(revenue)}* ({percent:.0f}%) | *{orders_count}*\n"

    text += "\n"
    text += t(lang, 'admin_report_revenue_total', revenue=utils.format_currency(total_revenue))
    text += t(lang, 'admin_report_orders_total', count=total_orders)

    admin_commission = utils.calculate_admin_commission(total_revenue)
    text += t(lang, 'admin_report_commission', amount=utils.format_currency(admin_commission))
    text += "═" * 35

    await callback.message.edit_text(
        text,
        reply_markup=admin_kb.get_back_button("admin_reports", lang),
        parse_mode="Markdown"
    )
    await callback.answer()

@router.callback_query(F.data == "report_week")
async def report_week(callback: CallbackQuery):
    lang = await get_lang(callback.from_user.id)
    venues = await db.get_all_venues()

    text = t(lang, 'admin_report_week_title')
    text += "═" * 35 + "\n"

    total_revenue = 0

    for venue in venues:
        revenue = await db.get_weekly_revenue(venue.venue_id)
        total_revenue += revenue
        text += f"├── *{venue.name}*: *{utils.format_currency(revenue)}*\n"

    text += "\n"
    text += t(lang, 'admin_report_week_revenue', revenue=utils.format_currency(total_revenue))

    admin_commission = utils.calculate_admin_commission(total_revenue)
    text += t(lang, 'admin_report_commission', amount=utils.format_currency(admin_commission))
    text += "═" * 35

    await callback.message.edit_text(
        text,
        reply_markup=admin_kb.get_back_button("admin_reports", lang),
        parse_mode="Markdown"
    )
    await callback.answer()

@router.callback_query(F.data == "report_month")
async def report_month(callback: CallbackQuery):
    lang = await get_lang(callback.from_user.id)
    venues = await db.get_all_venues()

    text = t(lang, 'admin_report_month_title')
    text += "═" * 35 + "\n"

    total_revenue = 0

    for venue in venues:
        revenue = await db.get_monthly_revenue(venue.venue_id)
        total_revenue += revenue
        text += f"├── *{venue.name}*: *{utils.format_currency(revenue)}*\n"

    text += "\n"
    text += t(lang, 'admin_report_month_revenue', revenue=utils.format_currency(total_revenue))

    admin_commission = utils.calculate_admin_commission(total_revenue)
    text += t(lang, 'admin_report_commission', amount=utils.format_currency(admin_commission))
    text += "═" * 35

    await callback.message.edit_text(
        text,
        reply_markup=admin_kb.get_back_button("admin_reports", lang),
        parse_mode="Markdown"
    )
    await callback.answer()

@router.callback_query(F.data == "report_venues")
async def report_venues(callback: CallbackQuery):
    lang = await get_lang(callback.from_user.id)
    venues = await db.get_all_venues()
    today = utils.get_stats_date()

    text = t(lang, 'admin_report_venues_title')

    venue_data = []
    for venue in venues:
        today_revenue = await db.get_daily_revenue(venue.venue_id, today)
        week_revenue = await db.get_weekly_revenue(venue.venue_id)
        month_revenue = await db.get_monthly_revenue(venue.venue_id)
        venue_data.append({
            'name': venue.name,
            'today': today_revenue,
            'week': week_revenue,
            'month': month_revenue
        })

    venue_data.sort(key=lambda x: x['month'], reverse=True)

    for data in venue_data:
        text += f"*{data['name']}*\n"
        text += f"  {utils.format_currency(data['today'])} / {utils.format_currency(data['week'])} / {utils.format_currency(data['month'])}\n\n"

    await callback.message.edit_text(
        text,
        reply_markup=admin_kb.get_back_button("admin_reports", lang),
        parse_mode="Markdown"
    )
    await callback.answer()

@router.callback_query(F.data == "report_cashback")
async def report_cashback(callback: CallbackQuery):
    lang = await get_lang(callback.from_user.id)
    today = utils.get_stats_date()
    venues = await db.get_all_venues()

    text = t(lang, 'admin_report_cashback_title')

    total_revenue = 0
    for venue in venues:
        revenue = await db.get_daily_revenue(venue.venue_id, today)
        total_revenue += revenue

    admin_commission_today = utils.calculate_admin_commission(total_revenue)

    week_revenue = await db.get_weekly_revenue()
    admin_commission_week = utils.calculate_admin_commission(week_revenue)

    month_revenue = await db.get_monthly_revenue()
    admin_commission_month = utils.calculate_admin_commission(month_revenue)

    text += f"*{utils.format_currency(admin_commission_today)}* ({utils.format_currency(total_revenue)})\n\n"
    text += f"📆 *{utils.format_currency(admin_commission_week)}* ({utils.format_currency(week_revenue)})\n\n"
    text += f"📈 *{utils.format_currency(admin_commission_month)}* ({utils.format_currency(month_revenue)})\n"

    await callback.message.edit_text(
        text,
        reply_markup=admin_kb.get_back_button("admin_reports", lang),
        parse_mode="Markdown"
    )
    await callback.answer()

@router.callback_query(F.data == "report_export")
async def report_export(callback: CallbackQuery):
    lang = await get_lang(callback.from_user.id)
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    from aiogram.types import InlineKeyboardButton

    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="📊 CSV", callback_data="export_csv"))
    builder.row(InlineKeyboardButton(text="📈 Excel", callback_data="export_excel"))
    builder.row(InlineKeyboardButton(text=t(lang, 'btn_back'), callback_data="admin_reports"))

    await callback.message.edit_text(
        t(lang, 'admin_report_export_title'),
        reply_markup=builder.as_markup(),
        parse_mode="Markdown"
    )
    await callback.answer()

@router.callback_query(F.data == "export_csv")
async def export_csv(callback: CallbackQuery):
    lang = await get_lang(callback.from_user.id)
    import csv
    import io
    from aiogram.types import BufferedInputFile

    venues = await db.get_all_venues()
    today = utils.get_stats_date()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        t(lang, 'admin_csv_col_club'),
        t(lang, 'admin_csv_col_city'),
        t(lang, 'admin_csv_col_revenue_today'),
        t(lang, 'admin_csv_col_revenue_week'),
        t(lang, 'admin_csv_col_revenue_month'),
        t(lang, 'admin_csv_col_status'),
    ])

    for venue in venues:
        today_revenue = await db.get_daily_revenue(venue.venue_id, today)
        week_revenue = await db.get_weekly_revenue(venue.venue_id)
        month_revenue = await db.get_monthly_revenue(venue.venue_id)
        status = t(lang, 'admin_csv_status_active') if venue.is_active else t(lang, 'admin_csv_status_blocked')

        writer.writerow([
            venue.name,
            venue.city,
            f"{today_revenue:.2f}",
            f"{week_revenue:.2f}",
            f"{month_revenue:.2f}",
            status
        ])

    file_content = output.getvalue().encode('utf-8')
    file = BufferedInputFile(file_content, filename=f"report_{today}.csv")

    await callback.message.answer_document(file, caption=t(lang, 'admin_csv_caption'))
    await callback.answer(t(lang, 'admin_csv_sent'))

@router.callback_query(F.data == "export_excel")
async def export_excel(callback: CallbackQuery):
    lang = await get_lang(callback.from_user.id)
    await callback.answer(t(lang, 'admin_excel_soon'), show_alert=True)

@router.callback_query(F.data == "admin_system")
async def show_system_menu(callback: CallbackQuery):
    lang = await get_lang(callback.from_user.id)
    venues = await db.get_all_venues()
    kj_count = len(await db.get_all_kj())
    users_count = await db.get_all_users_count()

    text = t(lang, 'admin_system_header',
             clubs=len(venues),
             kj=kj_count,
             users=users_count,
             time=datetime.now().strftime('%d.%m.%Y %H:%M'))

    await callback.message.edit_text(
        text,
        reply_markup=admin_kb.get_system_menu(lang),
        parse_mode="Markdown"
    )
    await callback.answer()

@router.callback_query(F.data == "system_support")
async def system_support(callback: CallbackQuery):
    lang = await get_lang(callback.from_user.id)
    import os
    import psutil

    process = psutil.Process(os.getpid())
    memory_info = process.memory_info()
    cpu_percent = process.cpu_percent(interval=1)

    text = t(lang, 'admin_support_header',
             memory=f"{memory_info.rss / 1024 / 1024:.2f}",
             cpu=cpu_percent,
             time=datetime.now().strftime('%d.%m.%Y %H:%M'),
             db_path=config.DATABASE_PATH)

    try:
        db_size = os.path.getsize(config.DATABASE_PATH) / 1024 / 1024
        text += t(lang, 'admin_support_db_size', size=f"{db_size:.2f}")
    except Exception:
        text += t(lang, 'admin_support_db_na')

    await callback.message.edit_text(
        text,
        reply_markup=admin_kb.get_back_button("admin_system", lang),
        parse_mode="Markdown"
    )
    await callback.answer()

@router.callback_query(F.data == "system_logs")
async def system_logs(callback: CallbackQuery):
    lang = await get_lang(callback.from_user.id)
    async with db.get_db() as db_conn:
        db_conn.row_factory = aiosqlite.Row
        async with db_conn.execute(
            """SELECT * FROM transactions
               ORDER BY created_at DESC LIMIT 20"""
        ) as cursor:
            rows = await cursor.fetchall()

    text = t(lang, 'admin_logs_header')

    if rows:
        for row in rows:
            text += f"• {row['type']}: {utils.format_currency(row['amount'])}\n"
            text += f"  {row['description']}\n"
            text += f"  {row['created_at']}\n\n"
    else:
        text += t(lang, 'admin_logs_empty')

    await callback.message.edit_text(
        text,
        reply_markup=admin_kb.get_back_button("admin_system", lang),
        parse_mode="Markdown"
    )
    await callback.answer()

@router.callback_query(F.data == "system_backup")
async def system_backup(callback: CallbackQuery):
    lang = await get_lang(callback.from_user.id)
    import shutil
    from aiogram.types import FSInputFile

    try:
        backup_name = f"backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
        shutil.copy2(config.DATABASE_PATH, backup_name)

        file = FSInputFile(backup_name)
        await callback.message.answer_document(
            file,
            caption=t(lang, 'admin_backup_caption', time=datetime.now().strftime('%d.%m.%Y %H:%M'))
        )

        import os
        os.remove(backup_name)

        await callback.answer(t(lang, 'admin_backup_done'), show_alert=True)
    except Exception as e:
        await callback.answer(t(lang, 'admin_backup_error', error=str(e)), show_alert=True)

@router.callback_query(F.data == "system_restart")
async def system_restart(callback: CallbackQuery):
    lang = await get_lang(callback.from_user.id)
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    from aiogram.types import InlineKeyboardButton

    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text=t(lang, 'btn_cancel'), callback_data="admin_system"),
        InlineKeyboardButton(text=t(lang, 'btn_confirm'), callback_data="confirm_restart")
    )

    await callback.message.edit_text(
        t(lang, 'admin_restart_confirm'),
        reply_markup=builder.as_markup(),
        parse_mode="Markdown"
    )
    await callback.answer()

@router.callback_query(F.data == "confirm_restart")
async def confirm_restart(callback: CallbackQuery):
    lang = await get_lang(callback.from_user.id)
    await callback.message.edit_text(t(lang, 'admin_restarting'))
    await callback.answer(t(lang, 'admin_restart_manual'), show_alert=True)

@router.callback_query(F.data.startswith("cancel_"))
async def cancel_action(callback: CallbackQuery, state: FSMContext):
    lang = await get_lang(callback.from_user.id)
    await state.clear()
    await callback.answer(t(lang, 'action_cancelled'))
    await admin_main_callback(callback)

async def admin_venues(callback: CallbackQuery):
    await show_venues(callback)
