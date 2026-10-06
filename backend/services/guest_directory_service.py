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
from datetime import date, datetime, time, timedelta, timezone

from auth import is_guest_app_open
from models import Favorite, GuestAccount, GuestStatus, Order, STATUS_COMPLETED, Service, TableGroupMember, VipClient

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
    # ДОБАВЛЕНО (2026-10, "Гости: разделение на тех, кто онлайн, сейчас в
    # клубе, и остальных"): гость "онлайн", если он сейчас участник живого
    # стола (TableGroupMember — запись исчезает при закрытии стола) ИЛИ у
    # него в последние пару минут открыто приложение (auth.is_guest_app_open).
    table_members = {m.guest_id: m.table_no for m in TableGroupMember.query.filter_by(club_id=club_id).all()}

    for gid in set(vip_clients) | set(statuses) | set(table_members):
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

        at_table = gid in table_members
        app_open = is_guest_app_open(club_id, gid)

        result.append({
            "guest_id": str(gid),
            "guest_type": guest_type,
            "table_no": current_table_no,
            "is_blocked": is_blocked,
            "at_table": at_table,
            "app_open": app_open,
            "is_online": at_table or app_open,
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
        # ДОБАВЛЕНО (запрос пользователя 2026-10: "Kj должен иметь
        # возможность сам... добавить его фото") — поле уже существовало
        # (GuestAccount.photo_data_url, см. routes/kj.py::set_guest_photo),
        # просто не отдавалось в карточку обычного гостя — только в списке
        # VIP-клиентов (vip_service.list_clients).
        "photo_data_url": account.photo_data_url if account else None,
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


def get_guest_song_history(club_id: int, guest_id: int, date_from: date | None, date_to: date | None) -> dict:
    """
    История реально спетых песен гостя для карточки гостя в KJ Panel
    (запрос пользователя 2026-10: "какие песни были спеты нужно сохранять
    в истории Гостя по дням. По сессиям по неделям месяцам годам с
    выбором по календарю"). "Спето" — то же самое определение, что и в
    чеке стола (STATUS_COMPLETED, см. table_close_service.py::
    _build_receipt) — заказ действительно дошёл до конца, а не был снят
    кнопкой "Удалить"/"Вернуть".

    date_from/date_to — календарные границы (включительно), на усмотрение
    вызывающего кода (routes/kj.py сам переводит пресеты "день/неделя/
    месяц/год" в конкретные даты, либо принимает произвольный диапазон,
    выбранный KJ в календаре) — None с любой стороны значит "без границы".

    Группируем по дню (одна строка — один календарный день, самый
    естественный смысл "по сессиям" для karaoke-вечера, который всегда
    укладывается в один день) — так проще смотреть и считать итоги за
    период, чем плоский список без разбивки.
    """
    query = Order.query.filter(
        Order.club_id == club_id,
        Order.telegram_user_id == guest_id,
        Order.status == STATUS_COMPLETED,
    )
    if date_from is not None:
        query = query.filter(Order.created_at >= datetime.combine(date_from, time.min, tzinfo=timezone.utc))
    if date_to is not None:
        query = query.filter(Order.created_at <= datetime.combine(date_to, time.max, tzinfo=timezone.utc))
    orders = query.order_by(Order.created_at.desc()).all()

    service_ids = {o.service_id for o in orders if o.service_id is not None}
    services_by_id = {}
    if service_ids:
        services_by_id = {s.id: s for s in Service.query.filter(Service.id.in_(service_ids)).all()}

    days: dict[str, dict] = {}
    total_amount = 0.0
    for order in orders:
        service = services_by_id.get(order.service_id) if order.service_id else None
        price = float(service.price) if service is not None and service.price is not None else 0.0
        total_amount += price

        day_key = order.created_at.date().isoformat()
        day_bucket = days.setdefault(day_key, {"date": day_key, "songs": [], "count": 0, "sum": 0.0})
        day_bucket["songs"].append({
            "order_id": order.id,
            "song_title": order.song_title,
            "artist": order.artist,
            "table_no": order.table_no,
            "category": service.name if service is not None else None,
            "price": price,
            "played_at": order.created_at.isoformat(),
        })
        day_bucket["count"] += 1
        day_bucket["sum"] += price

    return {
        "song_count": len(orders),
        "total_amount": total_amount,
        "days": sorted(days.values(), key=lambda d: d["date"], reverse=True),
    }
