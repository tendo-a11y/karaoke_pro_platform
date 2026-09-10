import csv
import io
from typing import List, Tuple
from datetime import datetime, timedelta
import config

def get_stats_date() -> str:
    """Return the current statistical date. Day boundary is at 12:00 (noon)."""
    now = datetime.now()
    if now.hour < 12:
        return (now - timedelta(days=1)).strftime("%Y-%m-%d")
    return now.strftime("%Y-%m-%d")

def format_currency(amount: float) -> str:
    formatted = int(amount) if amount == int(amount) else round(amount, 2)
    return f"{formatted} {config.DEFAULT_CURRENCY}"

def calculate_cashback(amount: float, percent: float) -> float:
    return round(amount * (percent / 100), 2)

def calculate_admin_commission(amount: float) -> float:
    return round(amount * config.ADMIN_COMMISSION, 2)

def _detect_delimiter(content: str) -> str:
    first_line = content.split('\n')[0]
    return ';' if first_line.count(';') > first_line.count(',') else ','

def _parse_songs_from_content(content: str) -> List[dict]:
    delimiter = _detect_delimiter(content)
    reader = csv.DictReader(io.StringIO(content), delimiter=delimiter)
    songs = []
    for row in reader:
        row_lower = {k.strip().lower(): v for k, v in row.items() if k}
        artist_val = row_lower.get('artist') or row_lower.get('artis', '')
        title_val = row_lower.get('title', '')
        if artist_val or title_val:
            songs.append({
                'artist': artist_val.strip(),
                'title': title_val.strip(),
                'code': (row_lower.get('code') or '').strip() or None
            })
    return songs

async def parse_csv_songs(file_content: bytes) -> Tuple[List[dict], str]:
    for encoding in ('utf-8', 'utf-8-sig', 'windows-1251'):
        try:
            content = file_content.decode(encoding)
            songs = _parse_songs_from_content(content)
            if songs:
                return songs, f"✅ Успешно загружено {len(songs)} песен"
            return [], "❌ Файл пуст или неверный формат (нет колонок artist/artis и title)"
        except UnicodeDecodeError:
            continue
        except Exception as e:
            return [], f"❌ Ошибка парсинга: {str(e)}"
    return [], "❌ Ошибка декодирования файла"

def format_table_queue(orders: List, services_dict: dict) -> str:
    if not orders:
        return "Очередь пуста"
    
    result = []
    for idx, order in enumerate(orders, 1):
        service = services_dict.get(order.service_id, {})
        service_name = service.get('name', 'Неизвестно')
        result.append(
            f"{idx}. {order.song_name}\n"
            f"   Услуга: {service_name}"
        )
    
    return "\n".join(result)

def format_venue_report(stats: List) -> str:
    if not stats:
        return "Нет данных за этот период"
    
    result = []
    total_revenue = 0
    total_count = 0
    
    for row in stats:
        name = row['name']
        count = row['count']
        total = row['total']
        total_revenue += total
        total_count += count
        
        result.append(f"*{name}*: {format_currency(total)} | {count} шт")
    
    result.append("-" * 25)
    result.append(f"Выручка за день: {format_currency(total_revenue)}")
    result.append(f"Всего заказов: {total_count}")
    
    return "\n".join(result)

def get_table_label(table_number: int, table_count: int) -> str:
    if table_number > table_count:
        return f"Без стола (#{table_number})"
    return f"Стол {table_number}"


def is_virtual_table(table_number: int, table_count: int) -> bool:
    return table_number > table_count


async def send_user_menu(bot, user_id: int, chat_id: int = None) -> None:
    """Send the appropriate menu to a regular user based on their role.
    Should be called after every new message sent to a regular user so the menu
    is always visible at the bottom of the chat.
    """
    if chat_id is None:
        chat_id = user_id
    try:
        from database import Database
        from lang import get_lang, t
        import config as _config
        _db = Database()
        user = await _db.get_user(user_id)
        if not user or user.role in (_config.ROLE_NONE, _config.ROLE_KJ, _config.ROLE_ADMIN):
            return
        if not user.venue_id:
            return
        venue = await _db.get_venue(user.venue_id)
        if not venue:
            return
        lang = await get_lang(user_id)
        if user.role == _config.ROLE_VIP:
            from keyboards import vip_kb
            admin_user_id = await _db.get_table_admin_user_id(user.venue_id, user.table_number) if user.table_number else None
            markup = vip_kb.get_vip_main_menu(
                admin_user_id == user.user_id if admin_user_id else False,
                venue.chat_enabled, venue.chat_link, lang
            )
        else:
            from keyboards import client_kb
            is_no_table = user.role == _config.ROLE_NO_TABLE
            admin_user_id = await _db.get_table_admin_user_id(user.venue_id, user.table_number) if not is_no_table and user.table_number else None
            show_table_admin = (not is_no_table) and (admin_user_id == user.user_id)
            markup = client_kb.get_client_main_menu(show_table_admin, venue.chat_enabled, venue.chat_link, lang)
        await bot.send_message(chat_id, t(lang, 'choose_action'), reply_markup=markup)
    except Exception:
        pass

def get_role_name(role: int) -> str:
    roles = {
        config.ROLE_ADMIN: "Администратор",
        config.ROLE_KJ: "KJ оператор",
        config.ROLE_VIP: "VIP клиент",
        config.ROLE_USER: "Посетитель",
        config.ROLE_NO_TABLE: "Гость (без стола)"
    }
    return roles.get(role, "Неизвестно")

def pluralize_song(count: int) -> str:
    count = abs(count)
    if count % 10 == 1 and count % 100 != 11:
        return "песня"
    if 2 <= count % 10 <= 4 and not 12 <= count % 100 <= 14:
        return "песни"
    return "песен"

def pluralize_table(count: int) -> str:
    count = abs(count)
    if count % 10 == 1 and count % 100 != 11:
        return "стол"
    if 2 <= count % 10 <= 4 and not 12 <= count % 100 <= 14:
        return "стола"
    return "столов"

def validate_phone(phone: str) -> bool:
    cleaned = ''.join(filter(str.isdigit, phone))
    return len(cleaned) >= 10

def validate_email(email: str) -> bool:
    return '@' in email and '.' in email.split('@')[1]
