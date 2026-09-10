from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from locales import t

def get_client_main_menu(is_table_admin: bool = False, chat_enabled: bool = False, chat_link: str = None, lang: str = 'ru') -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text=t(lang, 'btn_make_order'), callback_data="client_make_order")
    )
    builder.row(
        InlineKeyboardButton(text=t(lang, 'btn_my_orders'), callback_data="client_my_orders"),
        InlineKeyboardButton(text=t(lang, 'btn_queue'), callback_data="client_queue")
    )
    builder.row(
        InlineKeyboardButton(text=t(lang, 'btn_become_vip'), callback_data="client_become_vip")
    )
    if is_table_admin:
        builder.row(
            InlineKeyboardButton(text=t(lang, 'btn_chat_kj'), callback_data="client_chat_kj"),
            InlineKeyboardButton(text=t(lang, 'btn_manage_table'), callback_data="table_group_manage")
        )
    else:
        builder.row(
            InlineKeyboardButton(text=t(lang, 'btn_chat_kj'), callback_data="client_chat_kj")
        )
    if chat_enabled and chat_link:
        builder.row(
            InlineKeyboardButton(text=t(lang, 'btn_join_group'), url=chat_link)
        )
    return builder.as_markup()

def get_order_type_menu(lang: str = 'ru') -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text=t(lang, 'btn_find_song'), switch_inline_query_current_chat="")
    )
    builder.row(
        InlineKeyboardButton(text=t(lang, 'btn_favorites'), callback_data="order_favorites")
    )
    builder.row(
        InlineKeyboardButton(text=t(lang, 'btn_back'), callback_data="client_main")
    )
    return builder.as_markup()

def get_order_actions(order_id: int, can_replace: bool = True, lang: str = 'ru') -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if can_replace:
        builder.row(
            InlineKeyboardButton(text=t(lang, 'btn_replace_song'), callback_data=f"order_replace_{order_id}")
        )
    else:
        builder.row(
            InlineKeyboardButton(text=t(lang, 'btn_replace_blocked'), callback_data=f"replace_blocked_{order_id}")
        )
    builder.row(
        InlineKeyboardButton(text=t(lang, 'btn_add_favorite'), callback_data=f"order_favorite_{order_id}")
    )
    builder.row(
        InlineKeyboardButton(text=t(lang, 'btn_back'), callback_data="client_my_orders")
    )
    return builder.as_markup()

def get_favorite_actions(song_id: int, lang: str = 'ru') -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text=t(lang, 'btn_reorder'), callback_data=f"fav_reorder_{song_id}")
    )
    builder.row(
        InlineKeyboardButton(text=t(lang, 'btn_delete_favorite'), callback_data=f"fav_delete_{song_id}")
    )
    builder.row(
        InlineKeyboardButton(text=t(lang, 'btn_back'), callback_data="order_favorites")
    )
    return builder.as_markup()

def get_become_vip_menu(lang: str = 'ru') -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text=t(lang, 'btn_get_vip'), callback_data="request_vip_status")
    )
    builder.row(
        InlineKeyboardButton(text=t(lang, 'btn_back'), callback_data="client_main")
    )
    return builder.as_markup()

def get_back_to_main(lang: str = 'ru') -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text=t(lang, 'btn_back'), callback_data="client_main")
    )
    return builder.as_markup()

def get_cancel_keyboard(lang: str = 'ru') -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text=t(lang, 'btn_cancel'), callback_data="client_main")
    )
    return builder.as_markup()
