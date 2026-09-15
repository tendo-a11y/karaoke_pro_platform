"""
Список гостей клуба и карточка одного гостя для KJ Panel (запрос
пользователя 2026-09): сортировка/фильтр VIP / Простой (с столом) / Без
стола, статистика по вечеру/неделе/месяцу, избранные песни, блокировка и
снятие со стола (реально действующие — см. models.py::GuestStatus и
auth.py::require_guest).

В системе нет отдельной таблицы "гости, которые сейчас в зале" — гость
существует как строка в БД только через то, что он УЖЕ сделал (заказ,
избранное, VIP-заявка) или через то, что над ним уже совершил действие KJ
(GuestStatus). Поэтому список собирается из трёх источников и объединяется
по guest_id: Order (кто заказывал за последние 30 дней — это же и даёт
"текущий" стол/тип и статистику), VipClient (VIP мог ещё ничего не
заказать) и GuestStatus (гость, которого KJ уже заблокировал/снял со
стола, должен быть виден и найти его снова, даже если давно молчит).

Окна "вечер/неделя/месяц" — те же скользящие "последние N дней от текущего
момента", что уже применяются в club_service.py (revenue_today/week/month)
и vip_service.list_transactions, а не календарные сутки — см. докстринг
club_service.py про это решение.
"""
from datetime import datetime, timedelta, timezone

from models import Favorite, GuestAccount, GuestStatus, Order, VipClient

WINDOW_EVENING_DAYS = 1
WINDOW_WEEK_DAYS = 7
WINDOW_MONTH_DAYS = 30

GUEST_TYPES = ("vip", "client", "no_table")

# services/vdj_service.py: add_manual_song и claim_vdj_queue_item пишут
# заказ от лица самого KJ, не гостя, фиксированным telegram_user_id=-1.
MANUAL_ORDER_SENTINEL_ID = -1


class GuestDirectoryError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 404):
        self.code = code
        self.message = message
        self.status_code = status_code
        super().__init__(message)


def _empty_entry(guest_id: int) -> dict:
    return {
        "guest_id": guest_id,
        "last_song_title": None,
        "last_artist": None,
        "last_activity_at": None,
        "latest_table_no": None,
        "orders_evening": 0,
        "orders_week": 0,
        "orders_month": 0,
    }


def _collect_order_stats(club_id: int, since_month: datetime, since_week: datetime, since_evening: datetime) -> dict:
    """
    Один проход по заказам клуба за последние 30 дней — дальше в Python,
    без хитрых оконных SQL-запросов (см. докстринг файла: для караоке-бара
    это разумный объём строк, а плоский Python-цикл проще проверить и
    прочитать, чем group-by с условным SUM на каждое окно). Заказы уже
    отсортированы по created_at по убыванию, поэтому первая встреченная
    запись для guest_id — самая свежая (даёт текущий стол/тип/последнюю
    песню).
    """
    orders = (
        Order.query
        .filter(Order.club_id == club_id, Order.created_at >= since_month)
        .order_by(Order.created_at.desc())
        .all()
    )

    guests: dict[int, dict] = {}
    for order in orders:
        gid = order.telegram_user_id
        if gid == MANUAL_ORDER_SENTINEL_ID:
            # KJ добавил вручную (add_manual_song) или "присвоил" песню,
            # найденную прямо в VirtualDJ (claim_vdj_queue_item) — оба пути
            # пишут фиксированный telegram_user_id=-1 (см. services/
            # vdj_service.py), потому что это не реальный гость с личным
            # guest_id, а действие самого KJ. В списке гостей это не гость,
            # его сюда включать нельзя — иначе все такие заказы слипаются в
            # одну фальшивую "персону" №-1.
            continue
        entry = guests.setdefault(gid, _empty_entry(gid))
        if entry["last_activity_at"] is None:
            entry["last_activity_at"] = order.created_at
            entry["latest_table_no"] = order.table_no
            entry["last_song_title"] = order.song_title
            entry["last_artist"] = order.artist
        entry["orders_month"] += 1
        if order.created_at >= since_week:
            entry["orders_week"] += 1
        if order.created_at >= since_evening:
            entry["orders_evening"] += 1
    return guests


def _guest_type(status: GuestStatus | None, is_vip: bool, latest_table_no) -> str:
    if is_vip:
        return "vip"
    table_no = status.table_no if status is not None else latest_table_no
    return "client" if table_no is not None else "no_table"


def list_guests(club_id: int, guest_type_filter: str | None = None) -> list[dict]:
    now = datetime.now(timezone.utc)
    since_evening = now - timedelta(days=WINDOW_EVENING_DAYS)
    since_week = now - timedelta(days=WINDOW_WEEK_DAYS)
    since_month = now - timedelta(days=WINDOW_MONTH_DAYS)

    guests = _collect_order_stats(club_id, since_month, since_week, since_evening)

    vip_clients = {v.telegram_user_id: v for v in VipClient.query.filter_by(club_id=club_id).all()}
    statuses = {s.telegram_user_id: s for s in GuestStatus.query.filter_by(club_id=club_id).all()}
    accounts = {a.telegram_user_id: a for a in GuestAccount.query.filter_by(club_id=club_id).all()}

    # VIP без единого заказа (только что одобрен) и гости, над которыми KJ
    # уже что-то делал (блок/снятие со стола), должны быть в списке тоже —
    # иначе их не найти и не разблокировать позже.
    for gid in set(vip_clients) | set(statuses):
        guests.setdefault(gid, _empty_entry(gid))

    result = []
    for gid, entry in guests.items():
        status = statuses.get(gid)
        vip = vip_clients.get(gid)
        account = accounts.get(gid)
        is_blocked = bool(status.is_blocked) if status else False
        guest_type = _guest_type(status, vip is not None, entry["latest_table_no"])
        current_table_no = status.table_no if status is not None else entry["latest_table_no"]

        if guest_type_filter and guest_type != guest_type_filter:
            continue

        result.append({
            "guest_id": str(gid),
            "guest_type": guest_type,
            "table_no": current_table_no,
            "is_blocked": is_blocked,
            "email": account.email if account else None,
            # Имя, которое гость сам себе задал (запрос пользователя
            # 2026-09, "самопереименование гостя") — null, если гость ещё
            # не входил через Google или ещё не задал имя, см.
            # routes/guest.py::set_display_name.
            "display_name": account.display_name if account else None,
            "last_song_title": entry["last_song_title"],
            "last_artist": entry["last_artist"],
            "last_activity_at": entry["last_activity_at"].isoformat() if entry["last_activity_at"] else None,
            "orders_evening": entry["orders_evening"],
            "orders_week": entry["orders_week"],
            "orders_month": entry["orders_month"],
            "vip_balance": float(vip.balance) if vip else None,
            "vip_cashback_percent": float(vip.cashback_percent) if vip else None,
        })

    result.sort(key=lambda g: g["last_activity_at"] or "", reverse=True)
    return result


def get_guest_detail(club_id: int, guest_id: int) -> dict:
    now = datetime.now(timezone.utc)
    since_evening = now - timedelta(days=WINDOW_EVENING_DAYS)
    since_week = now - timedelta(days=WINDOW_WEEK_DAYS)
    since_month = now - timedelta(days=WINDOW_MONTH_DAYS)

    guests = _collect_order_stats(club_id, since_month, since_week, since_evening)
    entry = guests.get(guest_id, _empty_entry(guest_id))

    status = GuestStatus.query.filter_by(club_id=club_id, telegram_user_id=guest_id).first()
    vip = VipClient.query.filter_by(club_id=club_id, telegram_user_id=guest_id).first()
    account = GuestAccount.query.filter_by(club_id=club_id, telegram_user_id=guest_id).first()

    if entry["last_activity_at"] is None and status is None and vip is None and account is None:
        raise GuestDirectoryError("GUEST_NOT_FOUND", "Гость не найден")

    favorites = (
        Favorite.query
        .filter_by(club_id=club_id, telegram_user_id=guest_id)
        .order_by(Favorite.added_at.desc())
        .all()
    )

    guest_type = _guest_type(status, vip is not None, entry["latest_table_no"])
    current_table_no = status.table_no if status is not None else entry["latest_table_no"]

    return {
        "guest_id": str(guest_id),
        "guest_type": guest_type,
        "table_no": current_table_no,
        "is_blocked": bool(status.is_blocked) if status else False,
        "email": account.email if account else None,
        "display_name": account.display_name if account else None,
        "last_song_title": entry["last_song_title"],
        "last_artist": entry["last_artist"],
        "last_activity_at": entry["last_activity_at"].isoformat() if entry["last_activity_at"] else None,
        "orders_evening": entry["orders_evening"],
        "orders_week": entry["orders_week"],
        "orders_month": entry["orders_month"],
        "vip_balance": float(vip.balance) if vip else None,
        "vip_cashback_percent": float(vip.cashback_percent) if vip else None,
        "favorites": [f.to_dict() for f in favorites],
    }
