from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from locales import t

def get_vip_main_menu(is_table_admin: bool = False, chat_enabled: bool = False, chat_link: str = None, lang: str = 'ru') -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text=t(lang, 'btn_vip_make_order'), callback_data="vip_make_order")
    )
    builder.row(
        InlineKeyboardButton(text=t(lang, 'btn_vip_my_orders'), callback_data="vip_my_orders"),
        InlineKeyboardButton(text=t(lang, 'btn_vip_queue'), callback_data="vip_queue")
    )
    builder.row(
        InlineKeyboardButton(text=t(lang, 'btn_vip_balance'), callback_data="vip_balance")
    )
    if is_table_admin:
        builder.row(
            InlineKeyboardButton(text=t(lang, 'btn_vip_chat_kj'), callback_data="vip_chat_kj"),
            InlineKeyboardButton(text=t(lang, 'btn_vip_manage_table'), callback_data="table_group_manage")
        )
    else:
        builder.row(
            InlineKeyboardButton(text=t(lang, 'btn_vip_chat_kj'), callback_data="vip_chat_kj")
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
        InlineKeyboardButton(text=t(lang, 'btn_back'), callback_data="vip_main")
    )
    return builder.as_markup()

def get_balance_menu(lang: str = 'ru') -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text=t(lang, 'btn_vip_topup'), callback_data="vip_topup_request")
    )
    builder.row(
        InlineKeyboardButton(text=t(lang, 'btn_vip_order_history'), callback_data="vip_order_history")
    )
    builder.row(
        InlineKeyboardButton(text=t(lang, 'btn_vip_finances'), callback_data="vip_finances")
    )
    builder.row(
        InlineKeyboardButton(text=t(lang, 'btn_back'), callback_data="vip_main")
    )
    return builder.as_markup()

def get_history_period_menu(lang: str = 'ru') -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text=t(lang, 'btn_history_today'), callback_data="history_today")
    )
    builder.row(
        InlineKeyboardButton(text=t(lang, 'btn_history_week'), callback_data="history_week")
    )
    builder.row(
        InlineKeyboardButton(text=t(lang, 'btn_history_month'), callback_data="history_month")
    )
    builder.row(
        InlineKeyboardButton(text=t(lang, 'btn_back'), callback_data="vip_balance")
    )
    return builder.as_markup()

def get_finances_period_menu(lang: str = 'ru') -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text=t(lang, 'btn_history_today'), callback_data="finances_today")
    )
    builder.row(
        InlineKeyboardButton(text=t(lang, 'btn_history_week'), callback_data="finances_week")
    )
    builder.row(
        InlineKeyboardButton(text=t(lang, 'btn_history_month'), callback_data="finances_month")
    )
    builder.row(
        InlineKeyboardButton(text=t(lang, 'btn_back'), callback_data="vip_balance")
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
        InlineKeyboardButton(text=t(lang, 'btn_back'), callback_data="vip_my_orders")
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

def get_back_to_main(lang: str = 'ru') -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text=t(lang, 'btn_back'), callback_data="vip_main")
    )
    return builder.as_markup()

def get_cancel_keyboard(lang: str = 'ru') -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text=t(lang, 'btn_cancel'), callback_data="vip_main")
    )
    return builder.as_markup()
