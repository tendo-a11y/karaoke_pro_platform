from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from locales import t

def get_admin_main_menu(lang: str = 'ru') -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text=t(lang, 'btn_admin_clubs'), callback_data="admin_venues")
    )
    builder.row(
        InlineKeyboardButton(text=t(lang, 'btn_admin_kj'), callback_data="admin_kj_list")
    )
    builder.row(
        InlineKeyboardButton(text=t(lang, 'btn_admin_reports'), callback_data="admin_reports")
    )
    builder.row(
        InlineKeyboardButton(text=t(lang, 'btn_admin_system'), callback_data="admin_system")
    )
    builder.row(
        InlineKeyboardButton(text=t(lang, 'btn_admin_refresh'), callback_data="admin_refresh")
    )
    return builder.as_markup()

def get_venues_menu(lang: str = 'ru') -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text=t(lang, 'btn_venue_add'), callback_data="venue_add")
    )
    builder.row(
        InlineKeyboardButton(text=t(lang, 'btn_venue_detailed'), callback_data="venue_details")
    )
    builder.row(
        InlineKeyboardButton(text=t(lang, 'btn_venue_block_toggle'), callback_data="venue_toggle_block")
    )
    builder.row(
        InlineKeyboardButton(text=t(lang, 'btn_venue_delete'), callback_data="venue_delete")
    )
    builder.row(
        InlineKeyboardButton(text=t(lang, 'btn_venue_contacts_btn'), callback_data="venue_contacts")
    )
    builder.row(
        InlineKeyboardButton(text=t(lang, 'btn_back'), callback_data="admin_main")
    )
    return builder.as_markup()

def get_venue_list_keyboard(venues: list, action: str, lang: str = 'ru') -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for venue in venues:
        status = "🟢" if venue.is_active else "🔴"
        builder.row(
            InlineKeyboardButton(
                text=f"{status} {venue.name} (ID:{venue.venue_id})",
                callback_data=f"{action}_{venue.venue_id}"
            )
        )
    builder.row(
        InlineKeyboardButton(text=t(lang, 'btn_back'), callback_data="admin_venues")
    )
    return builder.as_markup()

def get_venue_details_menu(venue_id: int, lang: str = 'ru') -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text=t(lang, 'btn_edit_venue_name'), callback_data=f"venue_edit_name_{venue_id}")
    )
    builder.row(
        InlineKeyboardButton(text=t(lang, 'btn_venue_assign_kj'), callback_data=f"venue_assign_kj_{venue_id}")
    )
    builder.row(
        InlineKeyboardButton(text=t(lang, 'btn_venue_finance'), callback_data=f"venue_finance_{venue_id}")
    )
    builder.row(
        InlineKeyboardButton(text=t(lang, 'btn_venue_songs_btn'), callback_data=f"venue_songs_{venue_id}")
    )
    builder.row(
        InlineKeyboardButton(text=t(lang, 'btn_venue_qr'), callback_data=f"venue_qr_{venue_id}")
    )
    builder.row(
        InlineKeyboardButton(text=t(lang, 'btn_unbind_tables'), callback_data=f"venue_unbind_tables_{venue_id}")
    )
    builder.row(
        InlineKeyboardButton(text=t(lang, 'btn_unbind_venue'), callback_data=f"venue_unbind_all_{venue_id}")
    )
    builder.row(
        InlineKeyboardButton(text=t(lang, 'btn_venue_refresh'), callback_data=f"venue_refresh_{venue_id}")
    )
    builder.row(
        InlineKeyboardButton(text=t(lang, 'btn_back'), callback_data="admin_venues")
    )
    return builder.as_markup()

def get_kj_menu(lang: str = 'ru') -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text=t(lang, 'btn_kj_assign_new'), callback_data="kj_assign")
    )
    builder.row(
        InlineKeyboardButton(text=t(lang, 'btn_kj_remove'), callback_data="kj_remove")
    )
    builder.row(
        InlineKeyboardButton(text=t(lang, 'btn_kj_work_stats'), callback_data="admin_kj_stats")
    )
    builder.row(
        InlineKeyboardButton(text=t(lang, 'btn_kj_contacts'), callback_data="kj_contacts")
    )
    builder.row(
        InlineKeyboardButton(text=t(lang, 'btn_kj_block_toggle'), callback_data="kj_toggle_block")
    )
    builder.row(
        InlineKeyboardButton(text=t(lang, 'btn_back'), callback_data="admin_main")
    )
    return builder.as_markup()

def get_reports_menu(lang: str = 'ru') -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text=t(lang, 'btn_report_today'), callback_data="report_today")
    )
    builder.row(
        InlineKeyboardButton(text=t(lang, 'btn_report_week'), callback_data="report_week")
    )
    builder.row(
        InlineKeyboardButton(text=t(lang, 'btn_report_month'), callback_data="report_month")
    )
    builder.row(
        InlineKeyboardButton(text=t(lang, 'btn_report_venues'), callback_data="report_venues")
    )
    builder.row(
        InlineKeyboardButton(text=t(lang, 'btn_report_cashback'), callback_data="report_cashback")
    )
    builder.row(
        InlineKeyboardButton(text=t(lang, 'btn_export_data'), callback_data="report_export")
    )
    builder.row(
        InlineKeyboardButton(text=t(lang, 'btn_back'), callback_data="admin_main")
    )
    return builder.as_markup()

def get_system_menu(lang: str = 'ru') -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text=t(lang, 'btn_sys_support'), callback_data="system_support")
    )
    builder.row(
        InlineKeyboardButton(text=t(lang, 'btn_sys_logs'), callback_data="system_logs")
    )
    builder.row(
        InlineKeyboardButton(text=t(lang, 'btn_sys_backup'), callback_data="system_backup")
    )
    builder.row(
        InlineKeyboardButton(text=t(lang, 'btn_sys_restart'), callback_data="system_restart")
    )
    builder.row(
        InlineKeyboardButton(text=t(lang, 'btn_back'), callback_data="admin_main")
    )
    return builder.as_markup()

def get_confirm_keyboard(action: str, data: str = "", lang: str = 'ru') -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text=t(lang, 'btn_cancel'), callback_data=f"cancel_{action}"),
        InlineKeyboardButton(text=t(lang, 'btn_confirm'), callback_data=f"confirm_{action}_{data}")
    )
    return builder.as_markup()

def get_confirmation_keyboard(action: str, data: str = "", lang: str = 'ru') -> InlineKeyboardMarkup:
    return get_confirm_keyboard(action, data, lang)

def get_back_button(callback_data: str = "admin_main", lang: str = 'ru') -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text=t(lang, 'btn_back'), callback_data=callback_data)
    )
    return builder.as_markup()

