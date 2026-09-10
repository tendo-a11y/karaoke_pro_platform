from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from locales import t

def get_kj_main_menu(lang: str = 'ru') -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text=t(lang, 'btn_kj_club_settings'), callback_data="kj_settings_warn")
    )
    builder.row(
        InlineKeyboardButton(text=t(lang, 'btn_kj_work_evening'), callback_data="kj_work")
    )
    return builder.as_markup()

def get_kj_settings_menu(chat_enabled: bool = False, lang: str = 'ru') -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text=t(lang, 'btn_kj_import_csv'), callback_data="kj_import_csv"),
        InlineKeyboardButton(text=t(lang, 'btn_kj_services'), callback_data="kj_services")
    )
    builder.row(
        InlineKeyboardButton(text=t(lang, 'btn_kj_tables_settings'), callback_data="kj_tables"),
        InlineKeyboardButton(text=t(lang, 'btn_kj_clients'), callback_data="kj_clients")
    )
    chat_btn_text = t(lang, 'btn_kj_chat_on') if chat_enabled else t(lang, 'btn_kj_chat_off')
    builder.row(
        InlineKeyboardButton(text=t(lang, 'btn_kj_vip_settings'), callback_data="kj_vip_settings"),
        InlineKeyboardButton(text=chat_btn_text, callback_data="kj_chat_toggle")
    )
    if chat_enabled:
        builder.row(
            InlineKeyboardButton(text=t(lang, 'btn_kj_chat_link_change'), callback_data="kj_set_chat_link")
        )
    builder.row(
        InlineKeyboardButton(text=t(lang, 'btn_kj_free_evening'), callback_data="kj_free_options")
    )
    builder.row(
        InlineKeyboardButton(text=t(lang, 'btn_back'), callback_data="kj_main")
    )
    return builder.as_markup()

def get_kj_work_menu(lang: str = 'ru') -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text=t(lang, 'btn_kj_queue'), callback_data="kj_queue")
    )
    builder.row(
        InlineKeyboardButton(text=t(lang, 'btn_kj_global_queue'), callback_data="kj_global_queue")
    )
    builder.row(
        InlineKeyboardButton(text=t(lang, 'btn_kj_stats'), callback_data="kj_stats")
    )
    builder.row(
        InlineKeyboardButton(text=t(lang, 'btn_back'), callback_data="kj_main")
    )
    return builder.as_markup()

def get_services_menu(lang: str = 'ru') -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text=t(lang, 'btn_kj_service_add'), callback_data="service_add")
    )
    builder.row(
        InlineKeyboardButton(text=t(lang, 'btn_kj_service_edit'), callback_data="service_edit")
    )
    builder.row(
        InlineKeyboardButton(text=t(lang, 'btn_kj_service_delete'), callback_data="service_delete")
    )
    builder.row(
        InlineKeyboardButton(text=t(lang, 'btn_back'), callback_data="kj_settings")
    )
    return builder.as_markup()

def get_services_list_keyboard(services: list, action: str, lang: str = 'ru') -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for service in services:
        price_text = t(lang, 'btn_free') if service.is_free else f"{service.price} MDL"
        builder.row(
            InlineKeyboardButton(
                text=f"{service.name} - {price_text}",
                callback_data=f"{action}_{service.service_id}"
            )
        )
    builder.row(
        InlineKeyboardButton(text=t(lang, 'btn_back'), callback_data="kj_services")
    )
    return builder.as_markup()

def get_vip_settings_menu(lang: str = 'ru') -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text=t(lang, 'btn_kj_vip_add'), callback_data="vip_add")
    )
    builder.row(
        InlineKeyboardButton(text=t(lang, 'btn_kj_vip_cashback'), callback_data="vip_cashback")
    )
    builder.row(
        InlineKeyboardButton(text=t(lang, 'btn_kj_vip_description'), callback_data="vip_description")
    )
    builder.row(
        InlineKeyboardButton(text=t(lang, 'btn_kj_vip_description_ro'), callback_data="vip_description_ro")
    )
    builder.row(
        InlineKeyboardButton(text=t(lang, 'btn_back'), callback_data="kj_settings")
    )
    return builder.as_markup()

def get_clients_menu(lang: str = 'ru') -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text=t(lang, 'btn_kj_client_search'), callback_data="client_search")
    )
    builder.row(
        InlineKeyboardButton(text=t(lang, 'btn_kj_client_bind'), callback_data="client_bind")
    )
    builder.row(
        InlineKeyboardButton(text=t(lang, 'btn_kj_client_referrals'), callback_data="client_referrals")
    )
    builder.row(
        InlineKeyboardButton(text=t(lang, 'btn_back'), callback_data="kj_settings")
    )
    return builder.as_markup()

def get_table_numbers_keyboard(table_count: int, action: str, lang: str = 'ru') -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    
    buttons = []
    for i in range(1, table_count + 1):
        buttons.append(
            InlineKeyboardButton(text=str(i), callback_data=f"{action}_{i}")
        )
    
    for i in range(0, len(buttons), 4):
        builder.row(*buttons[i:i+4])
    
    builder.row(
        InlineKeyboardButton(text=t(lang, 'btn_back'), callback_data="kj_work")
    )
    return builder.as_markup()

def get_order_actions_keyboard(order_id: int, lang: str = 'ru') -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text=t(lang, 'btn_kj_order_complete'), callback_data=f"order_complete_{order_id}"),
        InlineKeyboardButton(text=t(lang, 'btn_kj_order_delete'), callback_data=f"order_delete_{order_id}")
    )
    builder.row(
        InlineKeyboardButton(text=t(lang, 'btn_kj_order_replace'), callback_data=f"order_replace_{order_id}")
    )
    builder.row(
        InlineKeyboardButton(text=t(lang, 'btn_back'), callback_data="kj_queue")
    )
    return builder.as_markup()

def get_table_actions_keyboard(table_number: int, lang: str = 'ru') -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text=t(lang, 'btn_kj_add_order'), callback_data=f"table_add_order_{table_number}")
    )
    builder.row(
        InlineKeyboardButton(text=t(lang, 'btn_kj_close_table'), callback_data=f"table_close_{table_number}")
    )
    builder.row(
        InlineKeyboardButton(text=t(lang, 'btn_back'), callback_data="kj_queue")
    )
    return builder.as_markup()

def get_confirm_keyboard(action: str, data: str = "", lang: str = 'ru') -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text=t(lang, 'btn_cancel'), callback_data=f"cancel_{action}"),
        InlineKeyboardButton(text=t(lang, 'btn_confirm'), callback_data=f"confirm_{action}_{data}")
    )
    return builder.as_markup()

def get_back_button(callback_data: str = "kj_main", lang: str = 'ru') -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text=t(lang, 'btn_back'), callback_data=callback_data)
    )
    return builder.as_markup()

def get_client_actions_keyboard(user_id: int, venue_id: int, is_blocked: bool = False, lang: str = 'ru') -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text=t(lang, 'btn_kj_client_balance'), callback_data=f"client_balance_{user_id}")
    )
    builder.row(
        InlineKeyboardButton(text=t(lang, 'btn_kj_client_unbind_table'), callback_data=f"client_unbind_table_{user_id}")
    )
    builder.row(
        InlineKeyboardButton(text=t(lang, 'btn_kj_client_unbind_venue'), callback_data=f"client_unbind_venue_{user_id}")
    )
    block_btn = t(lang, 'btn_kj_client_unblock') if is_blocked else t(lang, 'btn_kj_client_block')
    builder.row(
        InlineKeyboardButton(text=block_btn, callback_data=f"client_block_{user_id}")
    )
    builder.row(
        InlineKeyboardButton(text=t(lang, 'btn_kj_client_commission'), callback_data=f"client_commission_{user_id}")
    )
    builder.row(
        InlineKeyboardButton(text=t(lang, 'btn_kj_client_chat'), callback_data=f"client_chat_{user_id}")
    )
    builder.row(
        InlineKeyboardButton(text=t(lang, 'btn_kj_client_delete'), callback_data=f"client_delete_{user_id}")
    )
    builder.row(
        InlineKeyboardButton(text=t(lang, 'btn_back'), callback_data="kj_clients")
    )
    return builder.as_markup()
