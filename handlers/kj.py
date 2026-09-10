import html
import logging
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, Document, InlineKeyboardButton
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from datetime import datetime
import aiosqlite

from database import Database
from keyboards import kj_kb
import config
import utils
from lang import get_lang, t

router = Router()
db = Database()
logger = logging.getLogger(__name__)

async def is_kj_or_admin(callback: CallbackQuery) -> bool:
    user = await db.get_user(callback.from_user.id)
    return user and user.role <= config.ROLE_KJ

class ServiceForm(StatesGroup):
    name = State()
    description = State()
    price = State()
    edit_name = State()
    edit_description = State()
    edit_price = State()

class VIPForm(StatesGroup):
    user_id = State()
    cashback = State()
    cashback_setting = State()
    description = State()
    description_ro = State()

class ClientSearchForm(StatesGroup):
    user_id = State()

class BalanceForm(StatesGroup):
    amount = State()

class KJChatForm(StatesGroup):
    link = State()
    client_id = State()
    message = State()

class MoveOrderForm(StatesGroup):
    order_id = State()
    table_number = State()
    new_position = State()

class AddOrderForm(StatesGroup):
    table_number = State()
    song_search = State()
    song_name = State()
    service_id = State()

class ReplaceOrderForm(StatesGroup):
    order_id = State()
    table_number = State()
    song_search = State()
    table_number = State()
    song_name = State()
    service_id = State()

class TableSettingsForm(StatesGroup):
    setting_type = State()
    value = State()

@router.message(Command("kj"))
async def cmd_kj(message: Message):
    user = await db.get_user(message.from_user.id)
    lang = await get_lang(message.from_user.id)
    
    if not user or user.role > config.ROLE_KJ:
        await message.answer(t(lang, 'kj_no_rights'))
        return
    
    if not user.venue_id:
        await message.answer(t(lang, 'kj_no_venue'))
        return
    
    venue = await db.get_venue(user.venue_id)
    
    text = t(lang, 'kj_panel_title',
             venue=html.escape(venue.name or ''),
             city=html.escape(venue.city or ''))
    
    await message.answer(text, reply_markup=kj_kb.get_kj_main_menu(lang), parse_mode="HTML")

@router.callback_query(F.data == "kj_main")
async def kj_main_callback(callback: CallbackQuery):
    lang = await get_lang(callback.from_user.id)
    user = await db.get_user(callback.from_user.id)
    venue = await db.get_venue(user.venue_id)
    
    text = t(lang, 'kj_panel_title',
             venue=html.escape(venue.name or ''),
             city=html.escape(venue.city or ''))
    
    await callback.message.edit_text(text, reply_markup=kj_kb.get_kj_main_menu(lang), parse_mode="HTML")
    await callback.answer()

@router.callback_query(F.data == "kj_settings_warn")
async def kj_settings_warn_handler(callback: CallbackQuery):
    lang = await get_lang(callback.from_user.id)
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text=t(lang, 'btn_confirm'), callback_data="kj_settings"),
        InlineKeyboardButton(text=t(lang, 'btn_back'), callback_data="kj_main")
    )
    await callback.message.edit_text(
        t(lang, 'kj_settings_warn_text'),
        parse_mode="HTML",
        reply_markup=builder.as_markup()
    )
    await callback.answer()

@router.callback_query(F.data == "kj_settings")
async def kj_settings_menu(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    lang = await get_lang(callback.from_user.id)
    user = await db.get_user(callback.from_user.id)
    venue = await db.get_venue(user.venue_id)
    
    text = t(lang, 'kj_settings_title',
             venue=html.escape(venue.name or ''),
             table_count=venue.table_count,
             songs_limit=config.MAX_ACTIVE_SONGS_PER_USER)
    
    await callback.message.edit_text(text, reply_markup=kj_kb.get_kj_settings_menu(venue.chat_enabled, lang), parse_mode="HTML")
    await callback.answer()

@router.callback_query(F.data == "kj_import_csv")
async def kj_import_csv_request(callback: CallbackQuery):
    lang = await get_lang(callback.from_user.id)
    await callback.message.edit_text(
        t(lang, 'kj_import_csv_title'),
        parse_mode="Markdown",
        reply_markup=kj_kb.get_back_button("kj_settings", lang)
    )
    await callback.answer()

@router.message(F.document)
async def handle_csv_upload(message: Message):
    logger.info(f"[CSV] Получен документ от user_id={message.from_user.id}, file={message.document.file_name}")
    user = await db.get_user(message.from_user.id)
    lang = await get_lang(message.from_user.id)

    if not user:
        logger.warning(f"[CSV] Пользователь {message.from_user.id} не найден в БД")
        return
    if user.role not in (config.ROLE_KJ, config.ROLE_ADMIN):
        logger.warning(f"[CSV] Пользователь {message.from_user.id} имеет роль {user.role}, не KJ/Admin")
        return
    if not user.venue_id:
        await message.answer("❌ У вас не назначено заведение. Обратитесь к администратору.")
        return

    if not message.document.file_name.lower().endswith('.csv'):
        await message.answer(t(lang, 'kj_csv_format_error'))
        return

    try:
        file = await message.bot.download(message.document)
        file_content = file.read()

        songs, status_msg = await utils.parse_csv_songs(file_content)
        logger.info(f"[CSV] Спарсено {len(songs)} песен, статус: {status_msg}")

        if songs:
            added = await db.bulk_add_songs(user.venue_id, songs)
            skipped = len(songs) - added
            status_msg = f"✅ Добавлено {added} новых песен"
            if skipped:
                status_msg += f" ({skipped} уже были в базе)"
        else:
            status_msg = "❌ Файл пуст или неверный формат"

        await message.answer(status_msg, reply_markup=kj_kb.get_kj_main_menu(lang))
    except Exception as e:
        logger.exception(f"[CSV] Ошибка при обработке файла от {message.from_user.id}: {e}")
        await message.answer(f"❌ Ошибка при обработке файла: {e}")

@router.callback_query(F.data == "kj_services")
async def kj_services_menu(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    lang = await get_lang(callback.from_user.id)
    user = await db.get_user(callback.from_user.id)
    services = await db.get_venue_services(user.venue_id)
    
    text = t(lang, 'kj_services_title')
    if services:
        for service in services:
            price = t(lang, 'btn_free') if service.is_free else utils.format_currency(service.price)
            text += f"🔹 <b>{html.escape(service.name or '')}</b> — <b>{price}</b>\n"
    else:
        text += t(lang, 'kj_services_empty')
    
    await callback.message.edit_text(text, reply_markup=kj_kb.get_services_menu(lang), parse_mode="HTML")
    await callback.answer()

@router.callback_query(F.data == "service_add")
async def service_add_start(callback: CallbackQuery, state: FSMContext):
    lang = await get_lang(callback.from_user.id)
    await callback.message.edit_text(
        t(lang, 'kj_service_add_title'),
        parse_mode="Markdown",
        reply_markup=kj_kb.get_back_button("kj_services", lang)
    )
    await state.update_data(_prompt_msg_id=callback.message.message_id, _prompt_chat_id=callback.message.chat.id, _lang=lang)
    await state.set_state(ServiceForm.name)
    await callback.answer()

@router.message(ServiceForm.name)
async def service_add_name(message: Message, state: FSMContext):
    data = await state.get_data()
    lang = data.get('_lang', 'ru')
    await state.update_data(name=message.text)
    sent = await message.answer(t(lang, 'kj_service_add_desc_prompt'))
    await state.update_data(_prompt_msg_id=sent.message_id, _prompt_chat_id=sent.chat.id)
    await state.set_state(ServiceForm.description)

@router.message(ServiceForm.description)
async def service_add_description(message: Message, state: FSMContext):
    data = await state.get_data()
    lang = data.get('_lang', 'ru')
    await state.update_data(description=message.text)
    sent = await message.answer(t(lang, 'kj_service_add_price_prompt'))
    await state.update_data(_prompt_msg_id=sent.message_id, _prompt_chat_id=sent.chat.id)
    await state.set_state(ServiceForm.price)

@router.message(ServiceForm.price)
async def service_add_price(message: Message, state: FSMContext):
    data = await state.get_data()
    lang = data.get('_lang', 'ru')
    try:
        price = float(message.text.replace(',', '.'))
    except ValueError:
        await message.answer(t(lang, 'kj_service_price_invalid'))
        return
    
    user = await db.get_user(message.from_user.id)
    
    await db.create_service(
        user.venue_id,
        data['name'],
        data['description'],
        price
    )
    
    await message.answer(
        t(lang, 'kj_service_created', name=data['name']),
        reply_markup=kj_kb.get_kj_main_menu(lang)
    )
    await state.clear()

@router.callback_query(F.data == "service_edit")
async def service_edit_list(callback: CallbackQuery):
    lang = await get_lang(callback.from_user.id)
    user = await db.get_user(callback.from_user.id)
    services = await db.get_venue_services(user.venue_id)
    
    if not services:
        await callback.answer(t(lang, 'kj_service_none'), show_alert=True)
        return
    
    await callback.message.edit_text(
        t(lang, 'kj_service_edit_choose'),
        reply_markup=kj_kb.get_services_list_keyboard(services, "service_edit_item", lang)
    )
    await callback.answer()

@router.callback_query(F.data.startswith("service_edit_item_"))
async def service_edit_item(callback: CallbackQuery, state: FSMContext):
    lang = await get_lang(callback.from_user.id)
    service_id = int(callback.data.split("_")[3])
    service = await db.get_service(service_id)
    
    if not service:
        await callback.answer(t(lang, 'kj_service_not_found'), show_alert=True)
        return
    
    await state.update_data(service_id=service_id, _lang=lang)
    
    text = t(lang, 'kj_service_edit_title',
             name=html.escape(service.name or ''),
             desc=html.escape(service.description or ''),
             price=service.price)
    
    await callback.message.edit_text(text, parse_mode="HTML")
    await state.set_state(ServiceForm.edit_name)
    await callback.answer()

@router.message(ServiceForm.edit_name)
async def service_edit_name(message: Message, state: FSMContext):
    data = await state.get_data()
    lang = data.get('_lang', 'ru')
    if message.text == "/skip":
        await state.update_data(name=None)
    else:
        await state.update_data(name=message.text)
    
    await message.answer(t(lang, 'kj_service_edit_desc_prompt'))
    await state.set_state(ServiceForm.edit_description)

@router.message(ServiceForm.edit_description)
async def service_edit_description(message: Message, state: FSMContext):
    data = await state.get_data()
    lang = data.get('_lang', 'ru')
    if message.text == "/skip":
        await state.update_data(description=None)
    else:
        await state.update_data(description=message.text)
    
    await message.answer(t(lang, 'kj_service_edit_price_prompt'))
    await state.set_state(ServiceForm.edit_price)

@router.message(ServiceForm.edit_price)
async def service_edit_price(message: Message, state: FSMContext):
    data = await state.get_data()
    lang = data.get('_lang', 'ru')
    service_id = data['service_id']
    
    updates = {}
    if data.get('name'):
        updates['name'] = data['name']
    if data.get('description'):
        updates['description'] = data['description']
    
    if message.text != "/skip":
        try:
            price = float(message.text.replace(',', '.'))
            updates['price'] = price
        except ValueError:
            await message.answer(t(lang, 'kj_service_price_invalid'))
            return
    
    if updates:
        await db.update_service(service_id, **updates)
        await message.answer(
            t(lang, 'kj_service_updated'),
            reply_markup=kj_kb.get_kj_main_menu(lang)
        )
    else:
        await message.answer(
            t(lang, 'kj_service_no_changes'),
            reply_markup=kj_kb.get_kj_main_menu(lang)
        )
    
    await state.clear()

@router.callback_query(F.data == "service_delete")
async def service_delete_list(callback: CallbackQuery):
    lang = await get_lang(callback.from_user.id)
    user = await db.get_user(callback.from_user.id)
    services = await db.get_venue_services(user.venue_id)
    
    if not services:
        await callback.answer(t(lang, 'kj_service_none'), show_alert=True)
        return
    
    await callback.message.edit_text(
        t(lang, 'kj_service_delete_choose'),
        reply_markup=kj_kb.get_services_list_keyboard(services, "service_del", lang)
    )
    await callback.answer()

@router.callback_query(F.data.startswith("service_del_"))
async def service_delete_confirm(callback: CallbackQuery, state: FSMContext):
    lang = await get_lang(callback.from_user.id)
    service_id = int(callback.data.split("_")[2])
    await db.delete_service(service_id)
    
    await callback.answer(t(lang, 'kj_service_deleted'), show_alert=True)
    await kj_services_menu(callback, state)

@router.callback_query(F.data == "kj_tables")
async def kj_tables_menu(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    lang = await get_lang(callback.from_user.id)
    user = await db.get_user(callback.from_user.id)
    venue = await db.get_venue(user.venue_id)
    
    mode_text = t(lang, 'kj_table_mode_sequential') if venue.table_mode == "sequential" else t(lang, 'kj_table_mode_by_order')
    
    text = t(lang, 'kj_tables_title',
             count=venue.table_count,
             songs=config.MAX_ACTIVE_SONGS_PER_USER,
             mode=mode_text)
    
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text=t(lang, 'btn_kj_tables_count'), callback_data="tables_count"))
    builder.row(InlineKeyboardButton(text=t(lang, 'btn_kj_tables_songs'), callback_data="tables_songs"))
    builder.row(InlineKeyboardButton(text=t(lang, 'btn_kj_tables_mode'), callback_data="tables_mode"))
    builder.row(InlineKeyboardButton(text=t(lang, 'btn_back'), callback_data="kj_settings"))
    
    await callback.message.edit_text(
        text,
        parse_mode="Markdown",
        reply_markup=builder.as_markup()
    )
    await callback.answer()

@router.callback_query(F.data == "kj_vip_settings")
async def kj_vip_settings_menu(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    lang = await get_lang(callback.from_user.id)
    
    await callback.message.edit_text(
        t(lang, 'kj_vip_settings_title'),
        reply_markup=kj_kb.get_vip_settings_menu(lang),
        parse_mode="Markdown"
    )
    await callback.answer()

@router.callback_query(F.data == "vip_cashback")
async def vip_cashback_settings(callback: CallbackQuery, state: FSMContext):
    lang = await get_lang(callback.from_user.id)
    user = await db.get_user(callback.from_user.id)
    venue = await db.get_venue(user.venue_id)
    
    if not venue:
        await callback.answer(t(lang, 'btn_kj_venue_not_found'), show_alert=True)
        return
    
    current_cashback = venue.vip_cashback if venue.vip_cashback else 0
    
    await callback.message.edit_text(
        t(lang, 'kj_vip_cashback_title', current=current_cashback),
        parse_mode="Markdown",
        reply_markup=kj_kb.get_back_button("kj_vip_settings", lang)
    )
    await state.update_data(_prompt_msg_id=callback.message.message_id, _prompt_chat_id=callback.message.chat.id, _lang=lang)
    await state.set_state(VIPForm.cashback_setting)
    await callback.answer()

@router.message(VIPForm.cashback_setting)
async def vip_cashback_save(message: Message, state: FSMContext):
    data = await state.get_data()
    lang = data.get('_lang', 'ru')
    try:
        cashback = float(message.text.replace(',', '.'))
        if cashback < 0 or cashback > 100:
            await message.answer(t(lang, 'kj_vip_cashback_invalid'))
            return
    except ValueError:
        await message.answer(t(lang, 'kj_vip_cashback_format_error'))
        return
    
    user = await db.get_user(message.from_user.id)
    await db.update_venue_cashback(user.venue_id, cashback)
    
    await message.answer(
        t(lang, 'kj_vip_cashback_saved', value=cashback),
        reply_markup=kj_kb.get_kj_main_menu(lang),
        parse_mode="Markdown"
    )
    await state.clear()

@router.callback_query(F.data == "vip_description")
async def vip_description_edit(callback: CallbackQuery, state: FSMContext):
    lang = await get_lang(callback.from_user.id)
    user = await db.get_user(callback.from_user.id)
    venue = await db.get_venue(user.venue_id)
    
    if not venue:
        await callback.answer(t(lang, 'btn_kj_venue_not_found'), show_alert=True)
        return
    
    current_desc = venue.vip_description if venue.vip_description else t(lang, 'kj_client_none_label')
    
    await callback.message.edit_text(
        t(lang, 'kj_vip_desc_title', current=current_desc),
        parse_mode="Markdown",
        reply_markup=kj_kb.get_back_button("kj_vip_settings", lang)
    )
    await state.update_data(_prompt_msg_id=callback.message.message_id, _prompt_chat_id=callback.message.chat.id, _lang=lang)
    await state.set_state(VIPForm.description)
    await callback.answer()

@router.message(VIPForm.description)
async def vip_description_save(message: Message, state: FSMContext):
    data = await state.get_data()
    lang = data.get('_lang', 'ru')
    description = message.text

    user = await db.get_user(message.from_user.id)
    await db.update_venue_vip_description(user.venue_id, description)

    await message.answer(
        t(lang, 'kj_vip_desc_saved'),
        reply_markup=kj_kb.get_kj_main_menu(lang)
    )
    await state.clear()

@router.callback_query(F.data == "vip_description_ro")
async def vip_description_ro_edit(callback: CallbackQuery, state: FSMContext):
    lang = await get_lang(callback.from_user.id)
    user = await db.get_user(callback.from_user.id)
    venue = await db.get_venue(user.venue_id)

    if not venue:
        await callback.answer(t(lang, 'btn_kj_venue_not_found'), show_alert=True)
        return

    current_desc = venue.vip_description_ro if venue.vip_description_ro else t(lang, 'kj_client_none_label')

    await callback.message.edit_text(
        t(lang, 'kj_vip_desc_ro_title', current=current_desc),
        parse_mode="Markdown",
        reply_markup=kj_kb.get_back_button("kj_vip_settings", lang)
    )
    await state.update_data(_prompt_msg_id=callback.message.message_id, _prompt_chat_id=callback.message.chat.id, _lang=lang)
    await state.set_state(VIPForm.description_ro)
    await callback.answer()

@router.message(VIPForm.description_ro)
async def vip_description_ro_save(message: Message, state: FSMContext):
    data = await state.get_data()
    lang = data.get('_lang', 'ru')
    description = message.text

    user = await db.get_user(message.from_user.id)
    await db.update_venue_vip_description_ro(user.venue_id, description)

    await message.answer(
        t(lang, 'kj_vip_desc_ro_saved'),
        reply_markup=kj_kb.get_kj_main_menu(lang)
    )
    await state.clear()

@router.callback_query(F.data == "vip_add")
async def vip_add_start(callback: CallbackQuery, state: FSMContext):
    lang = await get_lang(callback.from_user.id)
    await callback.message.edit_text(
        t(lang, 'kj_vip_add_title'),
        parse_mode="Markdown",
        reply_markup=kj_kb.get_back_button("kj_vip_settings", lang)
    )
    await state.update_data(_prompt_msg_id=callback.message.message_id, _prompt_chat_id=callback.message.chat.id, _lang=lang)
    await state.set_state(VIPForm.user_id)
    await callback.answer()

@router.message(VIPForm.user_id)
async def vip_add_user_id(message: Message, state: FSMContext):
    data = await state.get_data()
    lang = data.get('_lang', 'ru')
    try:
        user_id = int(message.text)
    except ValueError:
        await message.answer(t(lang, 'kj_vip_id_invalid'))
        return
    
    await state.update_data(user_id=user_id)
    sent = await message.answer(t(lang, 'kj_vip_add_cashback_prompt'))
    await state.update_data(_prompt_msg_id=sent.message_id, _prompt_chat_id=sent.chat.id)
    await state.set_state(VIPForm.cashback)

@router.message(VIPForm.cashback)
async def vip_add_cashback(message: Message, state: FSMContext):
    data = await state.get_data()
    lang = data.get('_lang', 'ru')
    try:
        cashback = float(message.text.replace(',', '.'))
    except ValueError:
        await message.answer(t(lang, 'kj_vip_cashback_format'))
        return
    
    user = await db.get_user(message.from_user.id)
    
    target_user = await db.get_user(data['user_id'])
    if not target_user:
        await message.answer(t(lang, 'kj_vip_user_not_found'))
        await state.clear()
        return
    
    await db.add_vip_client(data['user_id'], user.venue_id, cashback)
    
    if target_user.role > config.ROLE_VIP:
        await db.update_user_role(data['user_id'], config.ROLE_VIP, user.venue_id)
    
    name = target_user.first_name or str(data['user_id'])
    await message.answer(
        t(lang, 'kj_vip_added', name=name),
        reply_markup=kj_kb.get_kj_main_menu(lang),
        parse_mode="Markdown"
    )
    await state.clear()

@router.callback_query(F.data == "kj_clients")
async def kj_clients_menu(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    lang = await get_lang(callback.from_user.id)
    
    await callback.message.edit_text(
        t(lang, 'kj_clients_title'),
        reply_markup=kj_kb.get_clients_menu(lang),
        parse_mode="Markdown"
    )
    await callback.answer()

@router.callback_query(F.data == "client_search")
async def client_search_start(callback: CallbackQuery, state: FSMContext):
    lang = await get_lang(callback.from_user.id)
    await callback.message.edit_text(
        t(lang, 'kj_client_search_prompt'),
        parse_mode="Markdown",
        reply_markup=kj_kb.get_back_button("kj_clients", lang)
    )
    await state.update_data(_prompt_msg_id=callback.message.message_id, _prompt_chat_id=callback.message.chat.id, _lang=lang)
    await state.set_state(ClientSearchForm.user_id)
    await callback.answer()

@router.message(ClientSearchForm.user_id)
async def client_search_result(message: Message, state: FSMContext):
    data = await state.get_data()
    lang = data.get('_lang', 'ru')
    try:
        user_id = int(message.text)
    except ValueError:
        await message.answer(t(lang, 'kj_client_id_invalid'))
        await state.clear()
        return
    
    user = await db.get_user(user_id)
    kj = await db.get_user(message.from_user.id)
    
    if not user:
        await message.answer(
            t(lang, 'kj_client_not_found'),
            reply_markup=kj_kb.get_kj_main_menu(lang)
        )
        await state.clear()
        return
    
    vip = await db.get_vip_client(user_id, kj.venue_id)
    
    status = t(lang, 'kj_client_status_vip') if vip else t(lang, 'kj_client_status_regular')
    table_label = str(user.table_number) if user.table_number else t(lang, 'kj_client_none_label')
    balance = utils.format_currency(vip.balance) if vip else '0'
    cashback = vip.cashback_percent if vip else 0
    
    text = t(lang, 'kj_client_info',
             uid=user.user_id,
             name=html.escape(user.first_name or ''),
             username=html.escape(user.username or t(lang, 'kj_client_none_label')),
             status=status,
             table=table_label,
             balance=balance,
             commission=cashback,
             blocked=t(lang, 'btn_yes') if user.is_blocked else t(lang, 'btn_no'))
    
    await message.answer(
        text,
        parse_mode="HTML",
        reply_markup=kj_kb.get_client_actions_keyboard(user_id, kj.venue_id, user.is_blocked, lang)
    )
    await state.clear()

@router.callback_query(F.data == "kj_chat_toggle")
async def kj_chat_toggle(callback: CallbackQuery, state: FSMContext):
    lang = await get_lang(callback.from_user.id)
    user = await db.get_user(callback.from_user.id)
    venue = await db.get_venue(user.venue_id)

    if venue.chat_enabled:
        await db.update_venue_settings(user.venue_id, chat_enabled=False)
        await callback.answer(t(lang, 'kj_chat_toggle_disabled'), show_alert=True)
        await kj_settings_menu(callback, state)
    else:
        if venue.chat_link:
            await db.update_venue_settings(user.venue_id, chat_enabled=True)
            await callback.answer(t(lang, 'kj_chat_toggle_enabled'), show_alert=True)
            await kj_settings_menu(callback, state)
        else:
            msg = await callback.message.edit_text(
                t(lang, 'kj_chat_link_prompt'),
                parse_mode="HTML",
                reply_markup=kj_kb.get_back_button("kj_settings", lang)
            )
            await state.update_data(_prompt_msg_id=msg.message_id, _prompt_chat_id=callback.message.chat.id, _lang=lang)
            await state.set_state(KJChatForm.link)
            await callback.answer()

@router.callback_query(F.data == "kj_set_chat_link")
async def kj_set_chat_link_request(callback: CallbackQuery, state: FSMContext):
    lang = await get_lang(callback.from_user.id)
    msg = await callback.message.edit_text(
        t(lang, 'kj_chat_change_link_prompt'),
        parse_mode="HTML",
        reply_markup=kj_kb.get_back_button("kj_settings", lang)
    )
    await state.update_data(_prompt_msg_id=msg.message_id, _prompt_chat_id=callback.message.chat.id, _lang=lang)
    await state.set_state(KJChatForm.link)
    await callback.answer()

@router.message(KJChatForm.link)
async def kj_process_chat_link(message: Message, state: FSMContext):
    data = await state.get_data()
    lang = data.get('_lang', 'ru')
    link = message.text.strip()
    if not (link.startswith("https://t.me/") or link.startswith("http://t.me/")):
        await message.answer(
            t(lang, 'kj_chat_link_invalid'),
            parse_mode="HTML"
        )
        return

    user = await db.get_user(message.from_user.id)
    await db.update_venue_settings(user.venue_id, chat_enabled=True, chat_link=link)
    await state.clear()

    await message.answer(t(lang, 'kj_chat_link_saved'))

@router.callback_query(F.data == "kj_free_options")
async def kj_free_options_callback(callback: CallbackQuery):
    await kj_free_options_menu(callback)

async def kj_free_options_menu(callback: CallbackQuery, _notification: str = ""):
    lang = await get_lang(callback.from_user.id)
    user = await db.get_user(callback.from_user.id)
    services = await db.get_venue_services(user.venue_id)

    if services:
        lines = [t(lang, 'kj_free_title')]
        for s in services:
            icon = "✅" if s.is_free else "💰"
            lines.append(f"{icon} {html.escape(s.name or '')}")
        text = "\n".join(lines)
    else:
        text = t(lang, 'kj_free_title') + t(lang, 'kj_free_empty')

    if _notification:
        text = f"{_notification}\n\n{text}"

    kb = InlineKeyboardBuilder()
    for s in services:
        price_text = t(lang, 'btn_free') if s.is_free else f"{s.price} MDL"
        kb.row(InlineKeyboardButton(
            text=f"{s.name} - {price_text}",
            callback_data=f"toggle_free_{s.service_id}"
        ))
    kb.row(InlineKeyboardButton(text=t(lang, 'btn_back'), callback_data="kj_settings"))

    await callback.message.edit_text(
        text,
        parse_mode="HTML",
        reply_markup=kb.as_markup() if services else kj_kb.get_back_button("kj_settings", lang)
    )

@router.callback_query(F.data.startswith("toggle_free_"))
async def toggle_free_service(callback: CallbackQuery):
    lang = await get_lang(callback.from_user.id)
    service_id = int(callback.data.split("_")[2])

    user = await db.get_user(callback.from_user.id)
    services = await db.get_venue_services(user.venue_id)
    service = next((s for s in services if s.service_id == service_id), None)

    notification = ""
    if service:
        new_status = not service.is_free
        await db.update_service(service_id, is_free=int(new_status))
        if new_status:
            notification = t(lang, 'kj_free_toggled_to_free', name=html.escape(service.name or ''))
        else:
            notification = t(lang, 'kj_free_toggled_to_paid',
                             name=html.escape(service.name or ''),
                             price=service.price)
    else:
        notification = t(lang, 'kj_free_service_not_found')

    await kj_free_options_menu(callback, _notification=notification)

@router.callback_query(F.data == "kj_work")
async def kj_work_menu(callback: CallbackQuery):
    lang = await get_lang(callback.from_user.id)
    
    await callback.message.edit_text(
        t(lang, 'kj_work_title'),
        reply_markup=kj_kb.get_kj_work_menu(lang),
        parse_mode="HTML"
    )
    await callback.answer()

@router.callback_query(F.data == "kj_queue")
async def kj_queue_show(callback: CallbackQuery):
    await show_table_queue(callback, 1)
    await callback.answer()

@router.callback_query(F.data == "kj_global_queue")
async def kj_global_queue_show(callback: CallbackQuery):
    lang = await get_lang(callback.from_user.id)
    user = await db.get_user(callback.from_user.id)
    venue = await db.get_venue(user.venue_id)

    import aiosqlite

    async with db.get_db() as conn:
        conn.row_factory = aiosqlite.Row
        async with conn.execute(
            """SELECT table_number, song_name
               FROM orders
               WHERE venue_id = ? AND status = 'playing'
               ORDER BY started_at DESC LIMIT 1""",
            (user.venue_id,)
        ) as cursor:
            playing_song = await cursor.fetchone()

    def table_label(table_num):
        if table_num > venue.table_count:
            return t(lang, 'kj_queue_no_table_label', num=table_num)
        return t(lang, 'kj_queue_table_label', num=table_num)

    text = t(lang, 'kj_global_queue_title') + "\n\n"
    if playing_song:
        text += t(lang, 'kj_queue_now_header') + f" <b>{table_label(playing_song['table_number'])}</b>\n"
        text += f"    \u2514 \U0001f3a4 {html.escape(str(playing_song['song_name']))}\n\n"
        text += "\u2014\u2014\u2014\u2014\u2014\u2014\u2014\u2014\u2014\n\n"

    async with db.get_db() as conn:
        conn.row_factory = aiosqlite.Row
        async with conn.execute(
            """SELECT table_number, song_name, is_next, created_at
               FROM orders
               WHERE venue_id = ? AND status = 'pending'
               ORDER BY is_next DESC, table_number ASC, created_at ASC""",
            (user.venue_id,)
        ) as cursor:
            rows = await cursor.fetchall()

    if rows:
        next_songs = [r for r in rows if r['is_next']]
        regular_songs = [r for r in rows if not r['is_next']]

        if next_songs:
            text += t(lang, 'kj_queue_vne_header') + "\n\n"
            for row in next_songs:
                text += f"      \u2514 <b>{table_label(row['table_number'])}</b> \u2014 {html.escape(str(row['song_name']))}\n"
            text += "\n\u2014\u2014\u2014\u2014\u2014\u2014\u2014\u2014\u2014\n\n"

        if regular_songs:
            text += t(lang, 'kj_queue_circle_header') + "\n\n"
            current_tbl = None
            for row in regular_songs:
                tbl = table_label(row['table_number'])
                if current_tbl != tbl:
                    if current_tbl is not None:
                        text += "\n"
                    text += f"\U0001f4cd <b>{tbl}</b>\n"
                    current_tbl = tbl
                text += f"    \u2514  {html.escape(str(row['song_name']))}\n"
    else:
        text += t(lang, 'kj_queue_empty')

    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text=t(lang, 'btn_kj_refresh_queue'), callback_data="kj_global_queue"),
        InlineKeyboardButton(text=t(lang, 'btn_back'), callback_data="kj_work")
    )
    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")
    await callback.answer()

@router.callback_query(F.data.startswith("queue_table_"))
async def queue_table_show(callback: CallbackQuery):
    table_number = int(callback.data.split("_")[2])
    await show_table_queue(callback, table_number)

async def show_table_queue(callback: CallbackQuery, table_number: int):
    lang = await get_lang(callback.from_user.id)
    user = await db.get_user(callback.from_user.id)
    
    import aiosqlite
    async with db.get_db() as db_conn:
        db_conn.row_factory = aiosqlite.Row
        async with db_conn.execute(
            """SELECT o.*, s.name as service_name 
               FROM orders o
               LEFT JOIN services s ON o.service_id = s.service_id
               WHERE o.venue_id = ? AND o.table_number = ? AND o.status IN ('pending', 'waiting')
               ORDER BY o.is_next DESC, o.marked_next_at ASC, o.position ASC""",
            (user.venue_id, table_number)
        ) as cursor:
            rows = await cursor.fetchall()
        
        async with db_conn.execute(
            """SELECT COUNT(*) FROM users 
               WHERE venue_id = ? AND table_number = ?""",
            (user.venue_id, table_number)
        ) as cursor:
            users_count = (await cursor.fetchone())[0]
    
    venue = await db.get_venue(user.venue_id)
    is_virtual = utils.is_virtual_table(table_number, venue.table_count)
    table_status = t(lang, 'kj_table_status_active') if users_count > 0 else t(lang, 'kj_table_status_free')
    if is_virtual:
        text = t(lang, 'kj_table_header_virtual', num=table_number, status=table_status) + "\n\n"
    else:
        text = t(lang, 'kj_table_header', num=table_number, status=table_status) + "\n\n"
    text += f"Заказов: <b>{len(rows)}</b>\n\n"
    
    builder = InlineKeyboardBuilder()
    
    if rows:
        for idx, row in enumerate(rows, 1):
            is_next = row['is_next'] if 'is_next' in row.keys() else 0
            status_emoji = "⏳" if row['status'] == 'waiting' else "✅"
            next_label = (" " + t(lang, 'kj_order_next_marker')) if is_next else ""
            text += f"<b>Песня {idx}</b>{next_label}\n"
            if 'artist_name' in row.keys() and row['artist_name']:
                text += f"Исполнитель: <b>{html.escape(str(row['artist_name']))}</b>\n"
            text += f"Название: <b>{html.escape(str(row['song_name']))}</b>\n"
            service_name = row['service_name'] if 'service_name' in row.keys() and row['service_name'] else ''
            text += f"Услуга: <b>{html.escape(str(service_name))}</b>\n"
            if row['status'] == 'waiting':
                text += f"Статус: {status_emoji} <i>{t(lang, 'kj_order_waiting_status')}</i>\n"
            text += "\n"
            
            if row['status'] == 'waiting':
                builder.row(
                    InlineKeyboardButton(
                        text=f"✅ Принять #{idx}",
                        callback_data=f"order_approve_{row['order_id']}"
                    ),
                    InlineKeyboardButton(
                        text=f"❌ Отклонить #{idx}",
                        callback_data=f"order_reject_{row['order_id']}"
                    )
                )
            else:
                next_btn_text = f"⏭✅ #{idx}" if is_next else f"⏭ #{idx}"
                builder.row(
                    InlineKeyboardButton(
                        text=f"❌ #{idx}",
                        callback_data=f"order_delete_{row['order_id']}"
                    ),
                    InlineKeyboardButton(
                        text=f"🔄 #{idx}",
                        callback_data=f"order_replace_{row['order_id']}_{table_number}"
                    ),
                    InlineKeyboardButton(
                        text=next_btn_text,
                        callback_data=f"order_next_toggle_{row['order_id']}"
                    ),
                    InlineKeyboardButton(
                        text=f"✅ #{idx}",
                        callback_data=f"order_complete_{row['order_id']}"
                    )
                )
    else:
        text += t(lang, 'kj_queue_empty')
    
    close_key = 'btn_kj_close_table_virtual' if is_virtual else 'btn_kj_close_table'
    builder.row(
        InlineKeyboardButton(text=t(lang, close_key), callback_data=f"table_close_{table_number}"),
        InlineKeyboardButton(text=t(lang, 'btn_kj_add_order'), callback_data=f"table_add_order_{table_number}")
    )
    
    import aiosqlite as _aios
    async with db.get_db() as _dbc:
        _dbc.row_factory = _aios.Row
        async with _dbc.execute(
            """SELECT DISTINCT table_number FROM orders
               WHERE venue_id = ? AND status IN ('pending', 'waiting')""",
            (user.venue_id,)
        ) as _cur:
            active_table_rows = await _cur.fetchall()
    active_tables = {r['table_number'] for r in active_table_rows}

    table_buttons = []
    for i in range(1, venue.table_count + 1):
        if i == table_number:
            label = f"🔸 {i}"
        elif i in active_tables:
            label = f"🔹 {i}"
        else:
            label = f"{i}"

        table_buttons.append(
            InlineKeyboardButton(text=label, callback_data=f"queue_table_{i}")
        )
    
    for i in range(0, len(table_buttons), 4):
        builder.row(*table_buttons[i:i+4])
    
    import aiosqlite as _aiosqlite
    async with db.get_db() as _db:
        _db.row_factory = _aiosqlite.Row
        async with _db.execute(
            """SELECT DISTINCT table_number FROM users 
               WHERE venue_id = ? AND table_number > ? 
               ORDER BY table_number""",
            (user.venue_id, venue.table_count)
        ) as _cur:
            virtual_rows = await _cur.fetchall()
    
    if virtual_rows:
        vt_buttons = []
        for vr in virtual_rows:
            vt = vr['table_number']
            if vt == table_number:
                label = f"🔸 👤{vt}"
            elif vt in active_tables:
                label = f"🔹 👤{vt}"
            else:
                label = f"👤{vt}"
            vt_buttons.append(
                InlineKeyboardButton(text=label, callback_data=f"queue_table_{vt}")
            )
        for i in range(0, len(vt_buttons), 4):
            builder.row(*vt_buttons[i:i+4])
    
    builder.row(
        InlineKeyboardButton(text=t(lang, 'btn_back'), callback_data="kj_work"),
        InlineKeyboardButton(text=t(lang, 'btn_kj_refresh_queue'), callback_data=f"queue_table_{table_number}")
    )

    await callback.message.edit_text(
        text,
        parse_mode="HTML",
        reply_markup=builder.as_markup()
    )
    await callback.answer()

@router.callback_query(F.data.startswith("order_next_toggle_"))
async def order_next_toggle(callback: CallbackQuery):
    order_id = int(callback.data.split("_")[3])
    lang = await get_lang(callback.from_user.id)

    user = await db.get_user(callback.from_user.id)
    if not user or user.role > config.ROLE_KJ:
        await callback.answer(t(lang, 'error_no_rights'), show_alert=True)
        return

    import aiosqlite
    async with db.get_db() as db_conn:
        db_conn.row_factory = aiosqlite.Row
        async with db_conn.execute(
            "SELECT * FROM orders WHERE order_id = ?", (order_id,)
        ) as cursor:
            order = await cursor.fetchone()

    if not order:
        await callback.answer(t(lang, 'kj_order_not_found'), show_alert=True)
        return

    new_state = await db.toggle_order_next(order_id)
    status_text = t(lang, 'kj_order_set_next') if new_state else t(lang, 'kj_order_cleared_next')
    await callback.answer(status_text, show_alert=False)

    if new_state:
        try:
            client_lang = await get_lang(order['user_id'])
            await callback.bot.send_message(
                order['user_id'],
                t(client_lang, 'kj_next_song_ready')
            )
            await utils.send_user_menu(callback.bot, order['user_id'])
        except Exception:
            pass

    await show_table_queue(callback, order['table_number'])

@router.callback_query(F.data.startswith("table_close_") & ~F.data.startswith("table_close_execute_"))
async def table_close_confirm(callback: CallbackQuery):
    table_number = int(callback.data.split("_")[2])
    lang = await get_lang(callback.from_user.id)
    user = await db.get_user(callback.from_user.id)
    
    import aiosqlite
    async with db.get_db() as db_conn:
        db_conn.row_factory = aiosqlite.Row
        async with db_conn.execute(
            """SELECT o.*, s.name as service_name, s.price as service_price
               FROM orders o
               LEFT JOIN services s ON o.service_id = s.service_id
               WHERE o.venue_id = ? AND o.table_number = ? AND o.status = 'completed'
               AND DATE(o.created_at) = DATE('now')
               ORDER BY o.created_at""",
            (user.venue_id, table_number)
        ) as cursor:
            rows = await cursor.fetchall()
    
    venue = await db.get_venue(user.venue_id)
    
    text = t(lang, 'kj_table_close_title', num=table_number) + "\n\n"
    
    service_counts = {}
    total_price = 0
    total_songs = 0
    
    for row in rows:
        service_name = row['service_name'] or 'Неизвестно'
        service_price = row['service_price'] or 0
        
        if service_name not in service_counts:
            service_counts[service_name] = {'count': 0, 'price': service_price}
        
        service_counts[service_name]['count'] += 1
        total_price += service_price
        total_songs += 1
    
    if service_counts:
        for service_name, data in service_counts.items():
            text += f"- <b>{data['count']}</b> {service_name}\n"
    else:
        text += t(lang, 'kj_queue_empty') + "\n"
    
    text += "\n" + t(lang, 'kj_table_close_songs', count=total_songs) + "\n"
    text += t(lang, 'kj_table_close_total', total=utils.format_currency(total_price)) + "\n"
    
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text=t(lang, 'btn_cancel'), callback_data=f"queue_table_{table_number}"),
        InlineKeyboardButton(text=t(lang, 'btn_confirm'), callback_data=f"table_close_execute_{table_number}")
    )
    
    await callback.message.edit_text(
        text,
        parse_mode="HTML",
        reply_markup=builder.as_markup()
    )
    await callback.answer()

@router.callback_query(F.data.startswith("table_close_execute_"))
async def table_close_execute(callback: CallbackQuery):
    table_number = int(callback.data.split("_")[3])
    lang = await get_lang(callback.from_user.id)
    user = await db.get_user(callback.from_user.id)
    venue = await db.get_venue(user.venue_id)
    
    import aiosqlite
    try:
        async with db.get_db() as db_conn:
            db_conn.row_factory = aiosqlite.Row
            async with db_conn.execute(
                """SELECT order_id FROM orders 
                   WHERE venue_id = ? AND table_number = ? AND status IN ('pending', 'waiting')""",
                (user.venue_id, table_number)
            ) as cursor:
                active_orders = await cursor.fetchall()
            
            for row in active_orders:
                await db.refund_vip_for_order(row['order_id'])
            
            await db_conn.execute(
                """UPDATE orders SET status = 'cancelled', 
                   cancelled_at = CURRENT_TIMESTAMP
                   WHERE venue_id = ? AND table_number = ? AND status IN ('pending', 'waiting')""",
                (user.venue_id, table_number)
            )
            await db_conn.commit()
    except Exception:
        pass
    
    await db.log_event('table_closed', user.venue_id, user.user_id,
                       f'Стол #{table_number} закрыт')
    
    await db.update_daily_stats(user.venue_id)

    import aiosqlite as _check_aios
    table_users = await db.get_table_users(user.venue_id, table_number)
    for tuser in table_users:
        try:
            async with db.get_db() as _cdb:
                _cdb.row_factory = _check_aios.Row
                async with _cdb.execute(
                    """SELECT o.song_name, s.name as service_name, s.price as service_price
                       FROM orders o
                       LEFT JOIN services s ON o.service_id = s.service_id
                       WHERE o.venue_id = ? AND o.table_number = ? AND o.user_id = ?
                         AND o.status = 'completed'
                         AND DATE(o.created_at) = DATE('now')
                       ORDER BY o.created_at""",
                    (user.venue_id, table_number, tuser.user_id)
                ) as _ccur:
                    user_rows = await _ccur.fetchall()

            client_lang = await get_lang(tuser.user_id)
            if user_rows:
                total_songs = len(user_rows)
                total_price = sum(r['service_price'] or 0 for r in user_rows)
                receipt_lines = ""
                for i, r in enumerate(user_rows, 1):
                    price_text = utils.format_currency(r['service_price'] or 0)
                    song_text = html.escape(r['song_name'] or '')
                    receipt_lines += t(client_lang, 'kj_receipt_item', n=i, song=song_text, price=price_text) + "\n"
                check_text = t(client_lang, 'kj_receipt_title') + f" — {table_number}\n\n"
                check_text += receipt_lines
                check_text += "\n" + t(client_lang, 'kj_table_close_total', total=utils.format_currency(total_price)) + "\n\n"
                check_text += t(client_lang, 'kj_session_ended_simple')
            else:
                check_text = t(client_lang, 'kj_session_ended_simple')
            await callback.bot.send_message(tuser.user_id, check_text, parse_mode="HTML")
        except Exception:
            pass

    if utils.is_virtual_table(table_number, venue.table_count):
        import aiosqlite as _aiosqlite2
        async with db.get_db() as _db2:
            async with _db2.execute(
                "SELECT user_id FROM users WHERE venue_id = ? AND table_number = ?",
                (user.venue_id, table_number)
            ) as _cur2:
                vt_users = await _cur2.fetchall()
            for row in vt_users:
                await _db2.execute(
                    "UPDATE users SET role = 0 WHERE user_id = ?",
                    (row[0],)
                )
            await _db2.commit()
    await db.unbind_table(user.venue_id, table_number)
    
    await callback.answer(t(lang, 'kj_table_closed_alert'), show_alert=True)
    
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    from aiogram.types import InlineKeyboardButton
    
    builder = InlineKeyboardBuilder()
    buttons = []
    for i in range(1, venue.table_count + 1):
        buttons.append(
            InlineKeyboardButton(text=f"{i}", callback_data=f"queue_table_{i}")
        )
    
    for i in range(0, len(buttons), 4):
        builder.row(*buttons[i:i+4])
    
    import aiosqlite as _aiosqlite3
    async with db.get_db() as _db3:
        _db3.row_factory = _aiosqlite3.Row
        async with _db3.execute(
            """SELECT DISTINCT table_number FROM users 
               WHERE venue_id = ? AND table_number > ? 
               ORDER BY table_number""",
            (user.venue_id, venue.table_count)
        ) as _cur3:
            virtual_rows3 = await _cur3.fetchall()
    
    if virtual_rows3:
        vt_buttons = []
        for vr in virtual_rows3:
            vt = vr['table_number']
            vt_buttons.append(
                InlineKeyboardButton(text=f"👤{vt}", callback_data=f"queue_table_{vt}")
            )
        for i in range(0, len(vt_buttons), 4):
            builder.row(*vt_buttons[i:i+4])
    
    builder.row(
        InlineKeyboardButton(text=t(lang, 'btn_back'), callback_data="kj_work")
    )
    
    text = t(lang, 'kj_queue_manage_title')
    
    await callback.message.edit_text(
        text,
        parse_mode="HTML",
        reply_markup=builder.as_markup()
    )

@router.callback_query(F.data == "kj_stats")
async def kj_stats_show(callback: CallbackQuery):
    lang = await get_lang(callback.from_user.id)
    user = await db.get_user(callback.from_user.id)
    today = utils.get_stats_date()
    
    stats = await db.get_venue_stats(user.venue_id, today)
    
    text = t(lang, 'kj_stats_title') + "\n\n"
    
    if stats:
        report = utils.format_venue_report(stats)
        text += report
    else:
        text += t(lang, 'kj_stats_no_data')
    
    await callback.message.edit_text(
        text,
        parse_mode="HTML",
        reply_markup=kj_kb.get_back_button("kj_work", lang)
    )
    await callback.answer()

@router.callback_query(F.data.startswith("vip_request_approve_"))
async def vip_request_approve(callback: CallbackQuery):
    request_id = int(callback.data.split("_")[3])

    user = await db.get_user(callback.from_user.id)
    if not user or user.role > config.ROLE_KJ:
        lang = await get_lang(callback.from_user.id)
        await callback.answer(t(lang, 'error_no_rights'), show_alert=True)
        return

    async with db.get_db() as conn:
        conn.row_factory = aiosqlite.Row
        async with conn.execute(
            "SELECT * FROM requests WHERE request_id = ?",
            (request_id,)
        ) as cursor:
            req = await cursor.fetchone()

    if not req:
        await callback.answer("❌ Запрос не найден", show_alert=True)
        return

    if req["status"] != "pending":
        await callback.answer("❌ Запрос уже обработан", show_alert=True)
        return

    if req["request_type"] != "vip":
        await callback.answer("❌ Неверный тип запроса", show_alert=True)
        return

    await db.update_request_status(request_id, "approved")
    await db.update_user_role(req["user_id"], config.ROLE_VIP, req["venue_id"])
    await db.add_vip_client(req["user_id"], req["venue_id"], cashback_percent=0)

    try:
        client_lang = await get_lang(req["user_id"])
        await callback.bot.send_message(
            req["user_id"],
            t(client_lang, 'vip_approved')
        )
        await utils.send_user_menu(callback.bot, req["user_id"])
    except Exception:
        pass

    try:
        await callback.message.edit_text(
            f"✅ *VIP подтвержден*\n\n"
            f"🪑 Стол *{req['table_number']}*\n"
            f"👤 Пользователь ID *{req['user_id']}*",
            parse_mode="Markdown"
        )
    except Exception:
        pass

    kj_lang = await get_lang(callback.from_user.id)
    await callback.answer(t(kj_lang, 'kj_vip_confirm_done'), show_alert=True)

@router.callback_query(F.data.startswith("vip_request_reject_"))
async def vip_request_reject(callback: CallbackQuery):
    request_id = int(callback.data.split("_")[3])

    user = await db.get_user(callback.from_user.id)
    if not user or user.role > config.ROLE_KJ:
        kj_lang2 = await get_lang(callback.from_user.id)
        await callback.answer(t(kj_lang2, 'error_no_rights'), show_alert=True)
        return

    async with db.get_db() as conn:
        conn.row_factory = aiosqlite.Row
        async with conn.execute(
            "SELECT * FROM requests WHERE request_id = ?",
            (request_id,)
        ) as cursor:
            req = await cursor.fetchone()

    if not req:
        await callback.answer("❌ Запрос не найден", show_alert=True)
        return

    if req["status"] != "pending":
        await callback.answer("❌ Запрос уже обработан", show_alert=True)
        return

    if req["request_type"] != "vip":
        await callback.answer("❌ Неверный тип запроса", show_alert=True)
        return

    await db.update_request_status(request_id, "rejected")

    try:
        client_lang = await get_lang(req["user_id"])
        await callback.bot.send_message(
            req["user_id"],
            t(client_lang, 'vip_rejected')
        )
        await utils.send_user_menu(callback.bot, req["user_id"])
    except Exception:
        pass

    try:
        await callback.message.edit_text(
            f"❌ *VIP отклонен*\n\n"
            f"🪑 Стол *{req['table_number']}*\n"
            f"👤 Пользователь ID *{req['user_id']}*",
            parse_mode="Markdown"
        )
    except Exception:
        pass

    kj_rlang = await get_lang(callback.from_user.id)
    await callback.answer(t(kj_rlang, 'kj_vip_reject_done'), show_alert=True)

@router.callback_query(F.data.startswith("topup_request_approve_"))
async def topup_request_approve(callback: CallbackQuery):
    request_id = int(callback.data.split("_")[3])

    user = await db.get_user(callback.from_user.id)
    if not user or user.role > config.ROLE_KJ:
        kj_lang3 = await get_lang(callback.from_user.id)
        await callback.answer(t(kj_lang3, 'error_no_rights'), show_alert=True)
        return

    async with db.get_db() as conn:
        conn.row_factory = aiosqlite.Row
        async with conn.execute(
            "SELECT * FROM requests WHERE request_id = ?",
            (request_id,)
        ) as cursor:
            req = await cursor.fetchone()

    if not req:
        await callback.answer("❌ Запрос не найден", show_alert=True)
        return

    if req["status"] != "pending":
        await callback.answer("❌ Запрос уже обработан", show_alert=True)
        return

    if req["request_type"] != "topup":
        await callback.answer("❌ Неверный тип запроса", show_alert=True)
        return

    try:
        amount = req["amount"] if req["amount"] else 0
    except (KeyError, IndexError):
        amount = 0
    
    await db.update_request_status(request_id, "approved")
    
    await db.update_vip_balance(req["user_id"], req["venue_id"], amount, add=True)
    
    await db.record_transaction(
        req["venue_id"], req["user_id"], amount, 'topup',
        f'Пополнение баланса ({amount} MDL)'
    )
    
    await db.log_event('topup_approved', req["venue_id"], req["user_id"],
                       f'Пополнение {amount} MDL одобрено')

    try:
        client_lang = await get_lang(req["user_id"])
        vip = await db.get_vip_client(req["user_id"], req["venue_id"])
        new_balance = vip.balance if vip else amount
        await callback.bot.send_message(
            req["user_id"],
            t(client_lang, 'topup_approved_client', amount=amount, balance=new_balance),
            parse_mode="Markdown"
        )
        await utils.send_user_menu(callback.bot, req["user_id"])
    except Exception:
        pass

    try:
        await callback.message.edit_text(
            f"✅ *Пополнение подтверждено*\n\n"
            f"🪑 Стол *{req['table_number']}*\n"
            f"👤 Пользователь ID *{req['user_id']}*\n"
            f"💰 Сумма: *{amount} MDL*",
            parse_mode="Markdown"
        )
    except Exception:
        pass

    kj_topup_lang = await get_lang(callback.from_user.id)
    await callback.answer(t(kj_topup_lang, 'kj_topup_confirm_done'), show_alert=True)

@router.callback_query(F.data.startswith("topup_request_reject_"))
async def topup_request_reject(callback: CallbackQuery):
    request_id = int(callback.data.split("_")[3])

    user = await db.get_user(callback.from_user.id)
    if not user or user.role > config.ROLE_KJ:
        await callback.answer("❌ Нет прав", show_alert=True)
        return

    async with db.get_db() as conn:
        conn.row_factory = aiosqlite.Row
        async with conn.execute(
            "SELECT * FROM requests WHERE request_id = ?",
            (request_id,)
        ) as cursor:
            req = await cursor.fetchone()

    if not req:
        await callback.answer("❌ Запрос не найден", show_alert=True)
        return

    if req["status"] != "pending":
        await callback.answer("❌ Запрос уже обработан", show_alert=True)
        return

    if req["request_type"] != "topup":
        await callback.answer("❌ Неверный тип запроса", show_alert=True)
        return

    await db.update_request_status(request_id, "rejected")

    try:
        amount = req["amount"] if req["amount"] else 0
    except (KeyError, IndexError):
        amount = 0

    try:
        client_lang = await get_lang(req["user_id"])
        await callback.bot.send_message(
            req["user_id"],
            t(client_lang, 'topup_rejected_client', amount=amount),
            parse_mode="Markdown"
        )
        await utils.send_user_menu(callback.bot, req["user_id"])
    except Exception:
        pass

    try:
        await callback.message.edit_text(
            f"❌ *Пополнение отклонено*\n\n"
            f"🪑 Стол *{req['table_number']}*\n"
            f"👤 Пользователь ID *{req['user_id']}*\n"
            f"💰 Сумма: *{amount} MDL*",
            parse_mode="Markdown"
        )
    except Exception:
        pass

    kj_topup_rlang = await get_lang(callback.from_user.id)
    await callback.answer(t(kj_topup_rlang, 'kj_topup_reject_done'), show_alert=True)

@router.callback_query(F.data.startswith("order_approve_"))
async def order_approve(callback: CallbackQuery):
    order_id = int(callback.data.split("_")[2])
    lang = await get_lang(callback.from_user.id)
    
    order = await db.get_order(order_id)
    if not order:
        await callback.answer(t(lang, 'kj_order_not_found'), show_alert=True)
        return
    
    if order.status != "waiting":
        await callback.answer(t(lang, 'kj_order_already_processed'), show_alert=True)
        return
    
    await db.update_order_status(order_id, "pending")
    
    await db.log_event('order_approved', order.venue_id, order.user_id,
                       f'Заказ #{order_id} принят: {order.song_name}')
    
    try:
        client_lang = await get_lang(order.user_id)
        await callback.bot.send_message(
            order.user_id,
            t(client_lang, 'kj_order_approved_client',
              order_id=order_id,
              song=order.song_name,
              pos=order.position),
            parse_mode="HTML"
        )
        await utils.send_user_menu(callback.bot, order.user_id)
    except Exception:
        pass
    
    await callback.answer(t(lang, 'kj_order_approved_kj'), show_alert=True)
    
    await show_table_queue(callback, order.table_number)

@router.callback_query(F.data.startswith("order_reject_"))
async def order_reject(callback: CallbackQuery):
    order_id = int(callback.data.split("_")[2])
    lang = await get_lang(callback.from_user.id)
    
    order = await db.get_order(order_id)
    if not order:
        await callback.answer(t(lang, 'kj_order_not_found'), show_alert=True)
        return
    
    if order.status != "waiting":
        await callback.answer(t(lang, 'kj_order_already_processed'), show_alert=True)
        return
    
    await db.update_order_status(order_id, "cancelled")
    
    refund = await db.refund_vip_for_order(order_id)
    
    kj_user = await db.get_user(callback.from_user.id)
    await db.log_event('order_rejected', kj_user.venue_id if kj_user else None, order.user_id,
                       f'Заказ #{order_id} отклонён KJ. Возврат: {refund} MDL')
    
    refund_text = f"\n💰 Возврат на баланс: *{refund} MDL*" if refund > 0 else ""
    try:
        client_lang = await get_lang(order.user_id)
        await callback.bot.send_message(
            order.user_id,
            t(client_lang, 'kj_order_rejected_client',
              order_id=order_id,
              song=order.song_name,
              refund_text=f'\n{t(client_lang, "order_refund", amount=refund)}' if refund > 0 else ''),
            parse_mode="HTML"
        )
        await utils.send_user_menu(callback.bot, order.user_id)
    except Exception:
        pass
    
    await callback.answer(t(lang, 'kj_order_rejected_kj'), show_alert=True)
    
    await show_table_queue(callback, order.table_number)

@router.callback_query(F.data.startswith("order_complete_confirm_"))
async def order_complete_confirmed(callback: CallbackQuery):
    order_id = int(callback.data.split("_")[3])
    lang = await get_lang(callback.from_user.id)
    
    user = await db.get_user(callback.from_user.id)
    orders = await db.get_venue_orders(user.venue_id, "pending")
    order = next((o for o in orders if o.order_id == order_id), None)
    
    if not order:
        await callback.answer(t(lang, 'kj_order_not_found'), show_alert=True)
        return
    
    await db.update_order_status(order_id, "completed")
    
    await db.log_event('order_completed', user.venue_id, order.user_id,
                       f'Заказ #{order_id} выполнен: {order.song_name}')
    
    services = await db.get_venue_services(user.venue_id)
    service = next((s for s in services if s.service_id == order.service_id), None)
    
    if service and not service.is_free:
        vip = await db.get_vip_client(order.user_id, user.venue_id)
        if vip and vip.cashback_percent > 0:
            cashback = await db.apply_cashback(order.user_id, user.venue_id, service.price, order_id)
            try:
                client_lang = await get_lang(order.user_id)
                await callback.bot.send_message(
                    order.user_id,
                    t(client_lang, 'kj_order_completed_client',
                      song=order.song_name,
                      cashback=utils.format_currency(cashback)),
                    parse_mode="HTML"
                )
                await utils.send_user_menu(callback.bot, order.user_id)
            except:
                pass
    
    await db.update_daily_stats(user.venue_id)
    
    await db.reorder_queue(user.venue_id, order.table_number)
    
    await callback.answer(t(lang, 'kj_order_completed_kj'), show_alert=True)
    
    await show_table_queue(callback, order.table_number)

@router.callback_query(F.data.startswith("order_complete_") & ~F.data.startswith("order_complete_confirm_"))
async def order_complete(callback: CallbackQuery):
    order_id = int(callback.data.split("_")[2])
    lang = await get_lang(callback.from_user.id)
    
    user = await db.get_user(callback.from_user.id)
    orders = await db.get_venue_orders(user.venue_id, "pending")
    order = next((o for o in orders if o.order_id == order_id), None)
    
    if not order:
        await callback.answer(t(lang, 'kj_order_not_found'), show_alert=True)
        return
    
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text=t(lang, 'btn_cancel'), callback_data=f"queue_table_{order.table_number}"),
        InlineKeyboardButton(text=t(lang, 'btn_confirm'), callback_data=f"order_complete_confirm_{order_id}")
    )
    
    await callback.message.edit_text(
        t(lang, 'kj_order_complete_confirm', order_id=order_id),
        parse_mode="HTML",
        reply_markup=builder.as_markup()
    )
    await callback.answer()

@router.callback_query(F.data.startswith("order_delete_confirm_"))
async def order_delete_confirmed(callback: CallbackQuery):
    order_id = int(callback.data.split("_")[3])
    lang = await get_lang(callback.from_user.id)
    
    user = await db.get_user(callback.from_user.id)
    orders = await db.get_venue_orders(user.venue_id, "pending")
    order = next((o for o in orders if o.order_id == order_id), None)
    
    if not order:
        await callback.answer(t(lang, 'kj_order_not_found'), show_alert=True)
        return
    
    table_number = order.table_number
    
    refund = await db.refund_vip_for_order(order_id)
    
    await db.delete_order(order_id)
    await db.reorder_queue(user.venue_id, table_number)
    
    await db.log_event('order_deleted', user.venue_id, order.user_id,
                       f'Заказ #{order_id} удалён KJ. Возврат: {refund} MDL')
    
    if refund > 0:
        try:
            client_lang = await get_lang(order.user_id)
            await callback.bot.send_message(
                order.user_id,
                t(client_lang, 'order_deleted_refund',
                  order_id=order_id,
                  song=order.song_name,
                  refund=refund),
                parse_mode="HTML"
            )
        except Exception:
            pass
    
    await callback.answer(t(lang, 'kj_order_deleted_kj'), show_alert=True)
    
    await show_table_queue(callback, table_number)

@router.callback_query(F.data.startswith("order_delete_") & ~F.data.startswith("order_delete_confirm_"))
async def order_delete(callback: CallbackQuery):
    order_id = int(callback.data.split("_")[2])
    lang = await get_lang(callback.from_user.id)
    
    user = await db.get_user(callback.from_user.id)
    orders = await db.get_venue_orders(user.venue_id, "pending")
    order = next((o for o in orders if o.order_id == order_id), None)
    
    if not order:
        await callback.answer(t(lang, 'kj_order_not_found'), show_alert=True)
        return
    
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text=t(lang, 'btn_kj_order_delete'), callback_data=f"order_delete_confirm_{order_id}"),
        InlineKeyboardButton(text=t(lang, 'btn_cancel'), callback_data=f"queue_table_{order.table_number}")
    )
    
    await callback.message.edit_text(
        t(lang, 'kj_order_delete_confirm', order_id=order_id),
        parse_mode="HTML",
        reply_markup=builder.as_markup()
    )
    await callback.answer()

@router.callback_query(F.data.startswith("order_move_"))
async def order_move_start(callback: CallbackQuery, state: FSMContext):
    order_id = int(callback.data.split("_")[2])
    
    user = await db.get_user(callback.from_user.id)
    orders = await db.get_venue_orders(user.venue_id, "pending")
    order = next((o for o in orders if o.order_id == order_id), None)
    
    if not order:
        await callback.answer("❌ Заказ не найден", show_alert=True)
        return
    
    await state.update_data(order_id=order_id, table_number=order.table_number)
    await callback.message.edit_text(
        f"↕️ *ПЕРЕМЕЩЕНИЕ ЗАКАЗА*\n\n"
        f"Песня: *{order.song_name}*\n"
        f"Текущая позиция: *{order.position}*\n\n"
        f"Введите новую позицию:",
        parse_mode="Markdown"
    )
    await state.set_state(MoveOrderForm.new_position)
    await callback.answer()

@router.message(MoveOrderForm.new_position)
async def order_move_execute(message: Message, state: FSMContext):
    data = await state.get_data()
    
    if 'order_id' not in data:
        return
    
    try:
        new_position = int(message.text)
    except ValueError:
        await message.answer("❌ Неверный формат. Введите число:")
        return
    
    order_id = data['order_id']
    table_number = data['table_number']
    
    user = await db.get_user(message.from_user.id)
    
    await db.update_order_position(order_id, new_position)
    await db.reorder_queue(user.venue_id, table_number)
    
    await message.answer(
        f"✅ Заказ перемещён на позицию *{new_position}*",
        reply_markup=kj_kb.get_kj_main_menu(),
        parse_mode="Markdown"
    )
    await state.clear()

@router.callback_query(F.data.startswith("confirm_close_table_"))
async def table_close_confirm(callback: CallbackQuery):
    table_number = int(callback.data.split("_")[3])
    
    user = await db.get_user(callback.from_user.id)
    orders = await db.get_table_orders(user.venue_id, table_number, "pending")
    
    for order in orders:
        await db.refund_vip_for_order(order.order_id)
        await db.update_order_status(order.order_id, "cancelled")
    
    waiting_orders = await db.get_table_orders(user.venue_id, table_number, "waiting")
    for order in waiting_orders:
        await db.refund_vip_for_order(order.order_id)
        await db.update_order_status(order.order_id, "cancelled")
    
    await db.log_event('table_closed', user.venue_id, user.user_id,
                       f'Стол #{table_number} закрыт (confirm_close)')
    
    await callback.answer(f"✅ Стол {table_number} закрыт", show_alert=True)
    await kj_queue_show(callback)

@router.callback_query(F.data == "kj_tables_edit")
async def kj_tables_edit_menu(callback: CallbackQuery):
    lang = await get_lang(callback.from_user.id)
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    from aiogram.types import InlineKeyboardButton
    
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text=t(lang, 'btn_kj_tables_count'), callback_data="tables_count"))
    builder.row(InlineKeyboardButton(text=t(lang, 'btn_kj_tables_songs'), callback_data="tables_songs"))
    builder.row(InlineKeyboardButton(text=t(lang, 'btn_kj_tables_mode'), callback_data="tables_mode"))
    builder.row(InlineKeyboardButton(text=t(lang, 'btn_kj_tables_unbind_all'), callback_data="tables_unbind_all"))
    builder.row(InlineKeyboardButton(text=t(lang, 'btn_kj_tables_unbind_venue'), callback_data="tables_unbind_venue"))
    builder.row(InlineKeyboardButton(text=t(lang, 'btn_back'), callback_data="kj_tables"))
    
    await callback.message.edit_text(
        t(lang, 'kj_tables_edit_title'),
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )
    await callback.answer()

@router.callback_query(F.data == "tables_unbind_all")
async def tables_unbind_all_confirm(callback: CallbackQuery):
    lang = await get_lang(callback.from_user.id)
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    from aiogram.types import InlineKeyboardButton
    
    user = await db.get_user(callback.from_user.id)
    
    async with db.get_db() as db_conn:
        async with db_conn.execute(
            "SELECT COUNT(*) FROM users WHERE venue_id = ? AND table_number IS NOT NULL",
            (user.venue_id,)
        ) as cursor:
            count = (await cursor.fetchone())[0]
    
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text=t(lang, 'btn_cancel'), callback_data="kj_tables_edit"),
        InlineKeyboardButton(text=t(lang, 'btn_confirm'), callback_data="confirm_unbind_all_tables")
    )
    
    await callback.message.edit_text(
        t(lang, 'kj_unbind_tables_confirm_text'),
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )
    await callback.answer()

@router.callback_query(F.data == "confirm_unbind_all_tables")
async def tables_unbind_all_execute(callback: CallbackQuery):
    lang = await get_lang(callback.from_user.id)
    user = await db.get_user(callback.from_user.id)
    
    affected_ids = await db.reset_venue_roles(user.venue_id)
    
    await db.unbind_all_tables(user.venue_id)
    
    for uid in affected_ids:
        try:
            client_lang = await get_lang(uid)
            await callback.bot.send_message(uid, t(client_lang, 'kj_session_ended_simple'))
        except Exception:
            pass
    
    await callback.answer(t(lang, 'kj_unbind_tables_done'), show_alert=True)
    
    await kj_tables_edit_menu(callback)

@router.callback_query(F.data == "tables_unbind_venue")
async def tables_unbind_venue_confirm(callback: CallbackQuery):
    lang = await get_lang(callback.from_user.id)
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    from aiogram.types import InlineKeyboardButton
    
    user = await db.get_user(callback.from_user.id)
    
    async with db.get_db() as db_conn:
        async with db_conn.execute(
            "SELECT COUNT(*) FROM users WHERE venue_id = ?",
            (user.venue_id,)
        ) as cursor:
            count = (await cursor.fetchone())[0]
    
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text=t(lang, 'btn_cancel'), callback_data="kj_tables_edit"),
        InlineKeyboardButton(text=t(lang, 'btn_confirm'), callback_data="confirm_unbind_all_venue")
    )
    
    await callback.message.edit_text(
        t(lang, 'kj_unbind_venue_confirm_text'),
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )
    await callback.answer()

@router.callback_query(F.data == "confirm_unbind_all_venue")
async def tables_unbind_venue_execute(callback: CallbackQuery):
    lang = await get_lang(callback.from_user.id)
    user = await db.get_user(callback.from_user.id)
    
    affected_ids = await db.reset_venue_roles(user.venue_id)
    
    await db.unbind_all_venue_users(user.venue_id)
    
    for uid in affected_ids:
        try:
            client_lang = await get_lang(uid)
            await callback.bot.send_message(uid, t(client_lang, 'kj_session_ended_simple'))
        except Exception:
            pass
    
    await callback.answer(t(lang, 'kj_unbind_venue_done'), show_alert=True)
    
    await kj_tables_edit_menu(callback)

@router.callback_query(F.data == "tables_count")
async def tables_count_edit(callback: CallbackQuery, state: FSMContext):
    lang = await get_lang(callback.from_user.id)
    user = await db.get_user(callback.from_user.id)
    venue = await db.get_venue(user.venue_id)
    await state.update_data(setting_type="table_count", _lang=lang)
    await callback.message.edit_text(
        t(lang, 'kj_tables_count_prompt', current=venue.table_count),
        parse_mode="HTML",
        reply_markup=kj_kb.get_back_button("kj_tables", lang)
    )
    await state.set_state(TableSettingsForm.value)
    await callback.answer()

@router.callback_query(F.data == "tables_songs")
async def tables_songs_edit(callback: CallbackQuery, state: FSMContext):
    lang = await get_lang(callback.from_user.id)
    await state.update_data(setting_type="songs_per_table", _lang=lang)
    await callback.message.edit_text(
        t(lang, 'kj_tables_songs_prompt'),
        parse_mode="HTML",
        reply_markup=kj_kb.get_back_button("kj_tables", lang)
    )
    await state.set_state(TableSettingsForm.value)
    await callback.answer()

@router.callback_query(F.data == "tables_mode")
async def tables_mode_edit(callback: CallbackQuery, state: FSMContext):
    lang = await get_lang(callback.from_user.id)
    user = await db.get_user(callback.from_user.id)
    venue = await db.get_venue(user.venue_id)
    
    new_mode = "by_order" if venue.table_mode == "sequential" else "sequential"
    await db.update_venue_settings(user.venue_id, table_mode=new_mode)
    
    mode_text = t(lang, 'kj_table_mode_sequential') if new_mode == "sequential" else t(lang, 'kj_table_mode_by_order')
    await callback.answer(t(lang, 'kj_tables_mode_changed', mode=mode_text), show_alert=True)
    await kj_tables_menu(callback, state)

@router.message(TableSettingsForm.value)
async def tables_settings_save(message: Message, state: FSMContext):
    data = await state.get_data()
    lang = data.get('_lang', 'ru')
    try:
        value = int(message.text)
        if value < 1:
            raise ValueError
    except ValueError:
        await message.answer(t(lang, 'kj_tables_count_invalid'))
        return
    
    user = await db.get_user(message.from_user.id)
    
    setting_type = data['setting_type']
    await db.update_venue_settings(user.venue_id, **{setting_type: value})
    
    await message.answer(
        t(lang, 'kj_tables_setting_saved', value=value),
        reply_markup=kj_kb.get_kj_main_menu(lang)
    )
    await state.clear()

@router.callback_query(F.data == "client_bind")
async def client_bind_info(callback: CallbackQuery):
    lang = await get_lang(callback.from_user.id)
    await callback.message.edit_text(
        t(lang, 'kj_bind_info_text'),
        reply_markup=kj_kb.get_back_button("kj_clients", lang),
        parse_mode="HTML"
    )
    await callback.answer()

async def _show_referrals_list(callback: CallbackQuery, venue_id: int, filter_type: str = "all", lang: str = "ru"):
    filter_labels = {
        "all": t(lang, 'kj_clients_filter_all'),
        "vip": t(lang, 'kj_clients_filter_vip'),
        "regular": t(lang, 'kj_clients_filter_regular'),
    }

    async with db.get_db() as db_conn:
        db_conn.row_factory = aiosqlite.Row
        
        if filter_type == "vip":
            query = """
                SELECT u.user_id, u.username, u.first_name,
                    COUNT(o.order_id) as orders_count,
                    COALESCE(SUM(CASE WHEN s.is_free = 0 THEN s.price ELSE 0 END), 0) as total_spent
                FROM users u
                JOIN vip_clients v ON u.user_id = v.user_id AND v.venue_id = ?
                LEFT JOIN orders o ON u.user_id = o.user_id AND o.venue_id = ? AND o.status = 'completed'
                LEFT JOIN services s ON o.service_id = s.service_id
                GROUP BY u.user_id
                ORDER BY total_spent DESC
                LIMIT 50"""
            params = (venue_id, venue_id)
        elif filter_type == "regular":
            query = """
                SELECT u.user_id, u.username, u.first_name,
                    COUNT(o.order_id) as orders_count,
                    COALESCE(SUM(CASE WHEN s.is_free = 0 THEN s.price ELSE 0 END), 0) as total_spent
                FROM users u
                JOIN orders o ON u.user_id = o.user_id AND o.venue_id = ? AND o.status = 'completed'
                LEFT JOIN services s ON o.service_id = s.service_id
                WHERE u.user_id NOT IN (
                    SELECT v.user_id FROM vip_clients v WHERE v.venue_id = ?
                )
                GROUP BY u.user_id
                ORDER BY total_spent DESC
                LIMIT 50"""
            params = (venue_id, venue_id)
        else:
            query = """
                SELECT user_id, username, first_name, orders_count, total_spent
                FROM (
                    SELECT u.user_id, u.username, u.first_name,
                        COUNT(o.order_id) as orders_count,
                        COALESCE(SUM(CASE WHEN s.is_free = 0 THEN s.price ELSE 0 END), 0) as total_spent
                    FROM users u
                    JOIN orders o ON u.user_id = o.user_id
                    JOIN services s ON o.service_id = s.service_id
                    WHERE o.venue_id = ? AND o.status = 'completed'
                    GROUP BY u.user_id
                    
                    UNION
                    
                    SELECT u.user_id, u.username, u.first_name,
                        0 as orders_count, 0 as total_spent
                    FROM users u
                    JOIN vip_clients v ON u.user_id = v.user_id AND v.venue_id = ?
                    WHERE u.user_id NOT IN (
                        SELECT DISTINCT o2.user_id FROM orders o2
                        WHERE o2.venue_id = ? AND o2.status = 'completed'
                    )
                )
                ORDER BY total_spent DESC
                LIMIT 50"""
            params = (venue_id, venue_id, venue_id)
        
        async with db_conn.execute(query, params) as cursor:
            rows = await cursor.fetchall()
    
    current_label = filter_labels.get(filter_type, t(lang, 'kj_clients_filter_all'))
    text = t(lang, 'kj_clients_list_title', label=current_label, total=len(rows))
    
    if rows:
        none_label = t(lang, 'kj_client_none_label')
        for idx, row in enumerate(rows, 1):
            vip = await db.get_vip_client(row['user_id'], venue_id)
            vip_badge = "⭐ " if vip else ""
            text += f"{idx}. {vip_badge}<b>{html.escape(row['first_name'] or '')}</b>\n"
            text += f"   @{row['username'] or none_label} | ID: <code>{row['user_id']}</code>\n"
            text += f"   {t(lang, 'kj_client_orders_spent', orders=row['orders_count'], spent=utils.format_currency(row['total_spent'] or 0))}\n\n"
            if idx >= 20:
                text += t(lang, 'kj_clients_more', count=len(rows) - 20)
                break
    else:
        text += t(lang, 'kj_clients_empty')
    
    builder = InlineKeyboardBuilder()
    all_label = t(lang, 'kj_clients_filter_all')
    vip_label = t(lang, 'kj_clients_filter_vip')
    reg_label = t(lang, 'kj_clients_filter_regular')
    all_btn = f"✅ {all_label.lstrip('📋 ')}" if filter_type == "all" else all_label
    vip_btn = f"✅ {vip_label.lstrip('⭐ ')}" if filter_type == "vip" else vip_label
    reg_btn = f"✅ {reg_label.lstrip('👤 ')}" if filter_type == "regular" else reg_label
    builder.row(
        InlineKeyboardButton(text=all_btn, callback_data="client_referrals_filter_all"),
        InlineKeyboardButton(text=vip_btn, callback_data="client_referrals_filter_vip"),
        InlineKeyboardButton(text=reg_btn, callback_data="client_referrals_filter_regular"),
    )
    builder.row(InlineKeyboardButton(text=t(lang, 'btn_back'), callback_data="kj_clients"))
    
    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")
    await callback.answer()

@router.callback_query(F.data == "client_referrals")
async def client_referrals_show(callback: CallbackQuery):
    lang = await get_lang(callback.from_user.id)
    user = await db.get_user(callback.from_user.id)
    await _show_referrals_list(callback, user.venue_id, "all", lang)

@router.callback_query(F.data.startswith("client_referrals_filter_"))
async def client_referrals_filtered(callback: CallbackQuery):
    lang = await get_lang(callback.from_user.id)
    filter_type = callback.data.split("_")[-1]
    user = await db.get_user(callback.from_user.id)
    await _show_referrals_list(callback, user.venue_id, filter_type, lang)

@router.callback_query(F.data.startswith("client_balance_"))
async def client_balance_manage(callback: CallbackQuery, state: FSMContext):
    user_id = int(callback.data.split("_")[2])
    lang = await get_lang(callback.from_user.id)
    kj = await db.get_user(callback.from_user.id)
    
    vip = await db.get_vip_client(user_id, kj.venue_id)
    
    if not vip:
        await callback.answer(t(lang, 'kj_not_vip'), show_alert=True)
        return
    
    client = await db.get_user(user_id)
    client_name = client.first_name if client else str(user_id)
    
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    from aiogram.types import InlineKeyboardButton
    
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text=t(lang, 'btn_kj_balance_add'), callback_data=f"balance_add_{user_id}"))
    builder.row(InlineKeyboardButton(text=t(lang, 'btn_kj_balance_sub'), callback_data=f"balance_sub_{user_id}"))
    builder.row(InlineKeyboardButton(text=t(lang, 'btn_kj_balance_set'), callback_data=f"balance_set_{user_id}"))
    builder.row(InlineKeyboardButton(text=t(lang, 'btn_back'), callback_data="kj_clients"))
    
    await callback.message.edit_text(
        t(lang, 'kj_balance_title', name=client_name, balance=utils.format_currency(vip.balance)),
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )
    await callback.answer()

@router.callback_query(F.data.startswith("balance_add_"))
async def balance_add(callback: CallbackQuery, state: FSMContext):
    user_id = int(callback.data.split("_")[2])
    lang = await get_lang(callback.from_user.id)
    await state.update_data(target_user_id=user_id, balance_action="add", _lang=lang)
    await callback.message.edit_text(t(lang, 'kj_balance_add_prompt'), parse_mode="HTML")
    await state.set_state(BalanceForm.amount)
    await callback.answer()

@router.callback_query(F.data.startswith("balance_sub_"))
async def balance_sub(callback: CallbackQuery, state: FSMContext):
    user_id = int(callback.data.split("_")[2])
    lang = await get_lang(callback.from_user.id)
    await state.update_data(target_user_id=user_id, balance_action="sub", _lang=lang)
    await callback.message.edit_text(t(lang, 'kj_balance_sub_prompt'), parse_mode="HTML")
    await state.set_state(BalanceForm.amount)
    await callback.answer()

@router.callback_query(F.data.startswith("balance_set_"))
async def balance_set(callback: CallbackQuery, state: FSMContext):
    user_id = int(callback.data.split("_")[2])
    lang = await get_lang(callback.from_user.id)
    await state.update_data(target_user_id=user_id, balance_action="set", _lang=lang)
    await callback.message.edit_text(t(lang, 'kj_balance_set_prompt'), parse_mode="HTML")
    await state.set_state(BalanceForm.amount)
    await callback.answer()

@router.message(BalanceForm.amount)
async def balance_enter_amount(message: Message, state: FSMContext):
    data = await state.get_data()
    lang = data.get('_lang', 'ru')
    try:
        amount = float(message.text.replace(',', '.'))
        if amount < 0:
            raise ValueError
    except ValueError:
        await message.answer(t(lang, 'kj_balance_invalid'))
        return

    user_id = data["target_user_id"]
    action = data["balance_action"]
    kj = await db.get_user(message.from_user.id)
    client = await db.get_user(user_id)
    client_name = client.first_name if client else str(user_id)

    old_vip = await db.get_vip_client(user_id, kj.venue_id)
    old_balance = old_vip.balance if old_vip else 0

    if action == "add":
        await db.update_vip_balance(user_id, kj.venue_id, amount, add=True)
    elif action == "sub":
        await db.update_vip_balance(user_id, kj.venue_id, amount, add=False)
    else:
        await db.set_vip_balance(user_id, kj.venue_id, amount)

    new_vip = await db.get_vip_client(user_id, kj.venue_id)
    new_balance = new_vip.balance if new_vip else amount

    await message.answer(
        t(lang, 'kj_balance_result', name=client_name,
          old=utils.format_currency(old_balance), new=utils.format_currency(new_balance)),
        reply_markup=kj_kb.get_kj_main_menu(lang)
    )
    await state.clear()

@router.callback_query(F.data.startswith("client_commission_"))
async def client_commission_manage(callback: CallbackQuery, state: FSMContext):
    user_id = int(callback.data.split("_")[2])
    lang = await get_lang(callback.from_user.id)
    kj = await db.get_user(callback.from_user.id)
    
    vip = await db.get_vip_client(user_id, kj.venue_id)
    
    if not vip:
        await callback.answer(t(lang, 'kj_not_vip'), show_alert=True)
        return
    
    await state.update_data(user_id=user_id, _lang=lang)
    await callback.message.edit_text(
        t(lang, 'kj_commission_title', cashback=vip.cashback_percent),
        parse_mode="HTML"
    )
    await state.set_state(VIPForm.cashback)
    await callback.answer()

@router.callback_query(F.data.startswith("client_block_"))
async def client_block_toggle(callback: CallbackQuery):
    user_id = int(callback.data.split("_")[2])
    lang = await get_lang(callback.from_user.id)
    user = await db.get_user(user_id)
    
    new_status = not user.is_blocked
    await db.block_user(user_id, new_status)
    
    client_name = user.first_name if user else str(user_id)
    if new_status:
        status_text = t(lang, 'kj_client_blocked', name=client_name)
    else:
        status_text = t(lang, 'kj_client_unblocked', name=client_name)
    await callback.answer(status_text, show_alert=True)

@router.callback_query(
    F.data.startswith("client_chat_")
    & ~F.data.startswith("client_chat_kj")
    & ~F.data.startswith("client_chat_reply_")
)
async def client_chat_start(callback: CallbackQuery, state: FSMContext):
    parts = callback.data.split("_")
    if len(parts) < 3 or not parts[2].isdigit():
        await callback.answer("❌ Неверные данные", show_alert=True)
        return
    user_id = int(parts[2])
    lang = await get_lang(callback.from_user.id)

    client = await db.get_user(user_id)
    if not client:
        await callback.answer(t(lang, 'kj_client_not_found'), show_alert=True)
        return

    await state.update_data(client_id=user_id, _lang=lang, _prompt_msg_id=callback.message.message_id, _prompt_chat_id=callback.message.chat.id)
    await state.set_state(KJChatForm.message)

    await callback.message.edit_text(
        t(lang, 'kj_chat_with_client', name=html.escape(client.first_name or '')),
        parse_mode="HTML"
    )
    await callback.answer()

@router.callback_query(F.data.startswith("client_unbind_table_"))
async def client_unbind_table(callback: CallbackQuery, state: FSMContext):
    user_id = int(callback.data.split("_")[3])
    lang = await get_lang(callback.from_user.id)
    user = await db.get_user(user_id)
    
    await db.unbind_user_table(user_id)
    
    client_name = user.first_name if user else str(user_id)
    await callback.answer(t(lang, 'kj_client_unbound_table', name=client_name), show_alert=True)
    
    await kj_clients_menu(callback, state)

@router.callback_query(F.data.startswith("client_unbind_venue_"))
async def client_unbind_venue(callback: CallbackQuery, state: FSMContext):
    user_id = int(callback.data.split("_")[3])
    lang = await get_lang(callback.from_user.id)
    user = await db.get_user(user_id)
    
    await db.unbind_user_venue(user_id)
    
    client_name = user.first_name if user else str(user_id)
    await callback.answer(t(lang, 'kj_client_unbound_venue', name=client_name), show_alert=True)
    
    await kj_clients_menu(callback, state)

@router.callback_query(F.data.startswith("client_delete_"))
async def client_delete_confirm(callback: CallbackQuery):
    user_id = int(callback.data.split("_")[2])
    lang = await get_lang(callback.from_user.id)
    user = await db.get_user(user_id)
    client_name = user.first_name if user else str(user_id)
    
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    from aiogram.types import InlineKeyboardButton
    
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text=t(lang, 'btn_cancel'), callback_data="kj_clients"),
        InlineKeyboardButton(text=t(lang, 'btn_kj_client_delete'), callback_data=f"confirm_delete_client_{user_id}")
    )
    
    await callback.message.edit_text(
        t(lang, 'kj_client_delete_confirm_text', name=html.escape(client_name)),
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )
    await callback.answer()

@router.callback_query(F.data.startswith("confirm_delete_client_"))
async def client_delete_execute(callback: CallbackQuery, state: FSMContext):
    user_id = int(callback.data.split("_")[3])
    lang = await get_lang(callback.from_user.id)
    kj = await db.get_user(callback.from_user.id)
    client = await db.get_user(user_id)
    client_name = html.escape(client.first_name if client else str(user_id))
    
    async with db.get_db() as db_conn:
        await db_conn.execute(
            "DELETE FROM vip_clients WHERE user_id = ? AND venue_id = ?",
            (user_id, kj.venue_id)
        )
        await db_conn.execute(
            "DELETE FROM orders WHERE user_id = ? AND venue_id = ?",
            (user_id, kj.venue_id)
        )
        await db_conn.execute(
            "DELETE FROM transactions WHERE user_id = ? AND venue_id = ?",
            (user_id, kj.venue_id)
        )
        await db_conn.execute(
            "DELETE FROM favorites WHERE user_id = ? AND venue_id = ?",
            (user_id, kj.venue_id)
        )
        await db_conn.execute(
            "DELETE FROM requests WHERE user_id = ? AND venue_id = ?",
            (user_id, kj.venue_id)
        )
        await db_conn.execute(
            "DELETE FROM chat_messages WHERE (from_user_id = ? OR to_user_id = ?) AND venue_id = ?",
            (user_id, user_id, kj.venue_id)
        )
        await db_conn.execute(
            "DELETE FROM table_join_requests WHERE user_id = ? AND venue_id = ?",
            (user_id, kj.venue_id)
        )
        await db_conn.execute(
            "DELETE FROM table_groups WHERE admin_user_id = ? AND venue_id = ?",
            (user_id, kj.venue_id)
        )
        await db_conn.execute(
            "DELETE FROM users WHERE user_id = ?",
            (user_id,)
        )
        await db_conn.commit()
    
    await callback.answer(t(lang, 'kj_client_deleted', name=client_name), show_alert=True)
    await kj_clients_menu(callback, state)

@router.callback_query(F.data.startswith("chat_reply_"))
async def chat_reply_start(callback: CallbackQuery, state: FSMContext):
    client_id = int(callback.data.split("_")[2])
    lang = await get_lang(callback.from_user.id)
    
    client = await db.get_user(client_id)
    if not client:
        await callback.answer(t(lang, 'kj_client_not_found'), show_alert=True)
        return
    
    await state.update_data(client_id=client_id, _lang=lang)
    await state.set_state(KJChatForm.message)
    
    sent = await callback.message.answer(
        t(lang, 'kj_chat_reply_prompt', name=html.escape(client.first_name or '')),
        parse_mode="HTML"
    )
    await state.update_data(_prompt_msg_id=sent.message_id, _prompt_chat_id=sent.chat.id)
    await callback.answer()

@router.message(KJChatForm.message)
async def kj_send_message(message: Message, state: FSMContext):
    data = await state.get_data()
    client_id = data['client_id']
    lang = data.get('_lang', 'ru')
    
    kj = await db.get_user(message.from_user.id)
    client = await db.get_user(client_id)
    
    if not client:
        await message.answer(t(lang, 'kj_client_not_found'))
        await state.clear()
        return
    
    await db.save_chat_message(
        venue_id=kj.venue_id,
        from_user_id=kj.user_id,
        to_user_id=client_id,
        message_text=message.text,
        table_number=client.table_number
    )
    
    try:
        client_lang = await get_lang(client_id)
        builder2 = InlineKeyboardBuilder()
        builder2.row(
            InlineKeyboardButton(text=t(client_lang, 'btn_chat_reply'), callback_data=f"client_chat_reply_{kj.user_id}")
        )
        await message.bot.send_message(
            client_id,
            t(client_lang, 'kj_chat_message', text=html.escape(message.text or '')),
            reply_markup=builder2.as_markup(),
            parse_mode="HTML"
        )
        await utils.send_user_menu(message.bot, client_id)
        await message.answer(
            t(lang, 'kj_message_sent'),
            reply_markup=kj_kb.get_kj_main_menu(lang)
        )
    except Exception:
        await message.answer(
            t(lang, 'kj_message_failed'),
            reply_markup=kj_kb.get_kj_main_menu(lang)
        )
    
    await state.clear()

@router.callback_query(F.data.startswith("table_move_start_"))
async def table_move_start(callback: CallbackQuery, state: FSMContext):
    table_number = int(callback.data.split("_")[3])
    lang = await get_lang(callback.from_user.id)
    user = await db.get_user(callback.from_user.id)
    
    await state.update_data(table_number=table_number, _lang=lang)
    await state.set_state(MoveOrderForm.new_position)
    
    count = await db.get_table_orders_count(user.venue_id, table_number)
    
    text = (
        f"⬆️ *ПЕРЕМЕСТИТЬ ЗАКАЗ*\n\n"
        f"Текущая очередь: *{count}* заказов\n\n"
        f"Введите новую позицию (1-*{count}*):\n\n"
        f"_Нажмите Enter или кнопку 'Подтвердить' после ввода_"
    )
    
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text=t(lang, 'btn_cancel'), callback_data=f"queue_table_{table_number}")
    )
    
    await callback.message.edit_text(
        t(lang, 'kj_move_order_title', count=count),
        parse_mode="HTML",
        reply_markup=builder.as_markup()
    )
    await callback.answer()

@router.message(MoveOrderForm.new_position)
async def table_move_position(message: Message, state: FSMContext):
    data = await state.get_data()
    lang = data.get('_lang', 'ru')
    try:
        new_position = int(message.text.strip())
        if new_position < 1:
            raise ValueError()
    except ValueError:
        await message.answer(t(lang, 'kj_move_position_invalid'))
        return
    
    table_number = data['table_number']
    
    user = await db.get_user(message.from_user.id)
    count = await db.get_table_orders_count(user.venue_id, table_number)
    
    if new_position > count:
        await message.answer(t(lang, 'kj_move_max_exceeded', count=count))
        return
    
    import aiosqlite
    async with db.get_db() as db_conn:
        db_conn.row_factory = aiosqlite.Row
        async with db_conn.execute(
            """SELECT order_id, song_name, position, is_next
               FROM orders
               WHERE venue_id = ? AND table_number = ? AND status IN ('pending', 'waiting')
               ORDER BY is_next DESC, marked_next_at ASC, position ASC""",
            (user.venue_id, table_number)
        ) as cursor:
            orders = await cursor.fetchall()
    
    if not orders:
        await message.answer(t(lang, 'kj_move_no_orders'))
        await state.clear()
        return
    
    text = t(lang, 'kj_move_choose')
    
    builder = InlineKeyboardBuilder()
    for idx, order in enumerate(orders, 1):
        text += f"{idx}. {order['song_name']}\n"
        builder.row(
            InlineKeyboardButton(
                text=f"#{idx} → позиция {new_position}",
                callback_data=f"move_execute_{order['order_id']}_{new_position}"
            )
        )
    
    builder.row(
        InlineKeyboardButton(text=t(lang, 'btn_cancel'), callback_data=f"queue_table_{table_number}")
    )
    
    await message.answer(text, parse_mode="HTML", reply_markup=builder.as_markup())
    await state.clear()

@router.callback_query(F.data.startswith("move_execute_"))
async def table_move_execute(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    
    parts = callback.data.split("_")
    order_id = int(parts[2])
    new_position = int(parts[3])
    
    user = await db.get_user(callback.from_user.id)
    
    import aiosqlite
    async with db.get_db() as db_conn:
        db_conn.row_factory = aiosqlite.Row
        async with db_conn.execute(
            "SELECT * FROM orders WHERE order_id = ?",
            (order_id,)
        ) as cursor:
            order = await cursor.fetchone()
    
    if not order:
        await callback.answer(t(await get_lang(callback.from_user.id), 'kj_order_not_found'), show_alert=True)
        return
    
    table_number = order['table_number']
    old_position = order['position']
    
    async with db.get_db() as db_conn:
        if new_position < old_position:
            await db_conn.execute(
                """UPDATE orders 
                   SET position = position + 1 
                   WHERE venue_id = ? AND table_number = ? AND status IN ('pending', 'waiting')
                   AND position >= ? AND position < ?""",
                (user.venue_id, table_number, new_position, old_position)
            )
        elif new_position > old_position:
            await db_conn.execute(
                """UPDATE orders 
                   SET position = position - 1 
                   WHERE venue_id = ? AND table_number = ? AND status IN ('pending', 'waiting')
                   AND position > ? AND position <= ?""",
                (user.venue_id, table_number, old_position, new_position)
            )
        
        await db_conn.execute(
            "UPDATE orders SET position = ? WHERE order_id = ?",
            (new_position, order_id)
        )
        await db_conn.commit()
    
    move_lang = await get_lang(callback.from_user.id)
    await callback.answer(t(move_lang, 'kj_order_moved'), show_alert=True)
    
    await show_table_queue(callback, table_number)

@router.callback_query(F.data.startswith("table_add_order_"))
async def table_add_order_start(callback: CallbackQuery, state: FSMContext):
    table_number = int(callback.data.split("_")[3])
    add_lang = await get_lang(callback.from_user.id)

    await state.clear()

    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text=t(add_lang, 'btn_kj_find_song'), switch_inline_query_current_chat=f"kj:{table_number} ")
    )
    builder.row(
        InlineKeyboardButton(text=t(add_lang, 'btn_cancel'), callback_data=f"queue_table_{table_number}")
    )
    
    await callback.message.edit_text(
        t(add_lang, 'kj_add_order_title', table=table_number),
        parse_mode="HTML",
        reply_markup=builder.as_markup()
    )
    await callback.answer()

@router.message(AddOrderForm.song_search)
async def table_add_order_search(message: Message, state: FSMContext):
    query = message.text.strip()
    data = await state.get_data()
    table_number = data['table_number']
    lang = data.get('_lang', 'ru')

    user = await db.get_user(message.from_user.id)

    songs = await db.search_songs(user.venue_id, query, limit=10)

    if not songs:
        await message.answer(
            t(lang, 'kj_songs_not_found'),
            reply_markup=InlineKeyboardBuilder().row(
                InlineKeyboardButton(text=t(lang, 'btn_cancel'), callback_data=f"queue_table_{table_number}")
            ).as_markup()
        )
        return

    text = t(lang, 'kj_search_results_title', count=len(songs))

    builder = InlineKeyboardBuilder()
    for song in songs:
        display_name = f"{song.artist_name} - {song.title}" if song.artist_name else song.title
        text += f"• {display_name}\n"
        builder.row(
            InlineKeyboardButton(
                text=display_name[:60],
                callback_data=f"add_song_{table_number}_{song.song_id}"
            )
        )

    builder.row(
        InlineKeyboardButton(text=t(lang, 'btn_cancel'), callback_data=f"queue_table_{table_number}")
    )

    await message.answer(text, parse_mode="Markdown", reply_markup=builder.as_markup())
    await state.clear()

@router.callback_query(F.data.startswith("add_song_"))
async def table_add_order_service(callback: CallbackQuery):
    parts = callback.data.split("_")
    table_number = int(parts[2])
    song_id = int(parts[3])
    lang = await get_lang(callback.from_user.id)

    user = await db.get_user(callback.from_user.id)
    song = await db.get_song(song_id)
    services = await db.get_venue_services(user.venue_id)

    if not song:
        await callback.answer(t(lang, 'kj_song_not_found'), show_alert=True)
        return

    song_display = f"{song.artist_name} - {song.title}" if song.artist_name else song.title
    text = t(lang, 'kj_choose_service_title', song=song_display, table=table_number)

    builder = InlineKeyboardBuilder()
    for service in services:
        price_text = t(lang, 'btn_free') if service.is_free else utils.format_currency(service.price)
        builder.row(
            InlineKeyboardButton(
                text=f"{service.name} - {price_text}",
                callback_data=f"add_service_{table_number}_{song_id}_{service.service_id}"
            )
        )

    builder.row(
        InlineKeyboardButton(text=t(lang, 'btn_cancel'), callback_data=f"queue_table_{table_number}")
    )

    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=builder.as_markup())
    await callback.answer()

@router.callback_query(F.data.startswith("add_service_"))
async def table_add_order_confirm(callback: CallbackQuery):
    parts = callback.data.split("_")
    table_number = int(parts[2])
    song_id = int(parts[3])
    service_id = int(parts[4])
    lang = await get_lang(callback.from_user.id)

    user = await db.get_user(callback.from_user.id)
    song = await db.get_song(song_id)
    service = next((s for s in await db.get_venue_services(user.venue_id) if s.service_id == service_id), None)

    if not song or not service:
        await callback.answer(t(lang, 'error_not_found'), show_alert=True)
        return

    song_display = f"{song.artist_name} - {song.title}" if song.artist_name else song.title
    price_display = t(lang, 'btn_free') if service.is_free else utils.format_currency(service.price)
    text = t(lang, 'kj_confirm_order_title',
             table=table_number, song=song_display,
             service=service.name, price=price_display)

    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text=t(lang, 'btn_cancel'), callback_data=f"queue_table_{table_number}"),
        InlineKeyboardButton(text=t(lang, 'btn_confirm'), callback_data=f"add_execute_{table_number}_{song_id}_{service_id}")
    )

    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=builder.as_markup())
    await callback.answer()

@router.callback_query(F.data.startswith("add_execute_"))
async def table_add_order_execute(callback: CallbackQuery):
    parts = callback.data.split("_")
    table_number = int(parts[2])
    song_id = int(parts[3])
    service_id = int(parts[4])
    
    user = await db.get_user(callback.from_user.id)
    song = await db.get_song(song_id)
    
    users_at_table = await db.get_table_users(user.venue_id, table_number)
    order_user_id = users_at_table[0].user_id if users_at_table else callback.from_user.id
    
    order_id = await db.create_order(
        order_user_id,
        user.venue_id,
        table_number,
        song.song_id,
        song.title,
        song.artist_name or "",
        service_id,
        status="pending"
    )
    
    lang = await get_lang(callback.from_user.id)
    await callback.answer(t(lang, 'kj_order_added'), show_alert=True)

    await show_table_queue(callback, table_number)

@router.callback_query(F.data.startswith("order_replace_"), is_kj_or_admin)
async def order_replace_start(callback: CallbackQuery, state: FSMContext):
    user = await db.get_user(callback.from_user.id)
    if not user or user.role > config.ROLE_KJ:
        return
    lang = await get_lang(callback.from_user.id)

    parts = callback.data.split("_")
    order_id = int(parts[2])

    if len(parts) >= 4:
        table_number = int(parts[3])
    else:
        orders = await db.get_venue_orders(user.venue_id, "pending")
        order = next((o for o in orders if o.order_id == order_id), None)

        if not order:
            await callback.answer(t(lang, 'kj_order_not_found'), show_alert=True)
            return

        table_number = order.table_number

    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text=t(lang, 'btn_kj_find_song'),
            switch_inline_query_current_chat=f"replace:{order_id} "
        )
    )
    builder.row(
        InlineKeyboardButton(text=t(lang, 'btn_cancel'), callback_data=f"queue_table_{table_number}")
    )

    await callback.message.edit_text(
        t(lang, 'kj_replace_order_title'),
        parse_mode="Markdown",
        reply_markup=builder.as_markup()
    )
    await callback.answer()

@router.callback_query(F.data.startswith("replace_song_"))
async def order_replace_execute(callback: CallbackQuery):
    parts = callback.data.split("_")
    order_id = int(parts[2])
    table_number = int(parts[3])
    song_id = int(parts[4])
    lang = await get_lang(callback.from_user.id)

    song = await db.get_song(song_id)
    if not song:
        await callback.answer(t(lang, 'kj_song_not_found'), show_alert=True)
        return

    import aiosqlite
    song_name = f"{song.artist} - {song.title}" if song.artist else song.title
    async with db.get_db() as db_conn:
        await db_conn.execute(
            "UPDATE orders SET song_name = ? WHERE order_id = ?",
            (song_name, order_id)
        )
        await db_conn.commit()

    await callback.answer(t(lang, 'kj_song_replaced'), show_alert=True)

    await show_table_queue(callback, table_number)

@router.callback_query(F.data.startswith("cancel_"), is_kj_or_admin)
async def cancel_action(callback: CallbackQuery, state: FSMContext):
    lang = await get_lang(callback.from_user.id)
    await state.clear()
    await callback.answer(t(lang, 'action_cancelled'))
    await cmd_kj_callback(callback)

async def cmd_kj_callback(callback: CallbackQuery):
    lang = await get_lang(callback.from_user.id)
    user = await db.get_user(callback.from_user.id)
    venue = await db.get_venue(user.venue_id)

    text = t(lang, 'kj_panel_title', venue=venue.name, city=venue.city)

    await callback.message.edit_text(text, reply_markup=kj_kb.get_kj_main_menu(lang), parse_mode="HTML")
    await callback.answer()
