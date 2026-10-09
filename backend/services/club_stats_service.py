"""
Статистика клуба для KJ Panel (запрос пользователя 2026-10: "мне нужна
статистика клуба" — не общая админская по всем клубам, а своего клуба).

Только чтение: ничего не меняет в базе. Всё считается из уже накопленных
данных (заказы, категории, VIP, транзакции, заявки).

"Клубный день": вечер в клубе переходит за полночь, поэтому сутки
считаются с 08:00 до 08:00 местного времени — песня, спетая в 02:30,
относится ко вчерашнему вечеру. Местное время берётся из браузера KJ
(tz_offset_minutes, как у JS getTimezoneOffset с обратным знаком).

Деньги: сумма = цена категории (Service.price) каждой спетой песни;
бесплатные категории и песни без категории считаются как 0. Это оценка
"на сколько напели", а не кассовый отчёт.
"""
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone

from services.category_service import not_bonus_filter
from services.stats_clear_service import exclude as _cleared_exclude
from models import (
    STATUS_COMPLETED,
    STATUS_ERROR,
    STATUS_PLAYING,
    STATUS_REJECTED,
    GuestAccount,
    Order,
    Service,
    Transaction,
    VipClient,
    VipRequest,
    TX_TYPE_ORDER_PAYMENT,
    TX_TYPE_TOPUP,
)

DAY_START_HOUR = 8
SUNG_STATUSES = (STATUS_PLAYING, STATUS_COMPLETED)
LAPSED_VIP_DAYS = 30
TOP_LIMIT = 10
WEEKDAYS = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]


def _norm(text) -> str:
    return " ".join(str(text or "").lower().split())


def _aware(dt):
    if dt is None:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _club_day(dt, tz_offset_minutes: int) -> date:
    local = _aware(dt) + timedelta(minutes=tz_offset_minutes)
    return (local - timedelta(hours=DAY_START_HOUR)).date()


def _window(date_from: date, date_to: date, tz_offset_minutes: int):
    start_local = datetime(date_from.year, date_from.month, date_from.day, DAY_START_HOUR, tzinfo=timezone.utc)
    end_local = datetime(date_to.year, date_to.month, date_to.day, DAY_START_HOUR, tzinfo=timezone.utc) + timedelta(days=1)
    shift = timedelta(minutes=tz_offset_minutes)
    return start_local - shift, end_local - shift


def today_club_day(tz_offset_minutes: int) -> date:
    return _club_day(datetime.now(timezone.utc), tz_offset_minutes)


def _price(order, services) -> float:
    service = services.get(order.service_id)
    if service is None or service.is_free:
        return 0.0
    return float(service.price or 0)


def _summary(orders, services) -> dict:
    sung = [o for o in orders if o.status in SUNG_STATUSES]
    guests = {o.telegram_user_id for o in sung if o.source == "guest"}
    return {
        "sung": len(sung),
        "revenue": round(sum(_price(o, services) for o in sung), 2),
        "guests": len(guests),
    }


def _orders_between(club_id: int, start, end):
    return (
        Order.query
        .filter(
            Order.club_id == club_id, Order.created_at >= start, Order.created_at < end, not_bonus_filter(),
            # Очищенные KJ отрезки (2026-10-09) в статистике не показываются.
            _cleared_exclude(Order.created_at, "kj", club_id),
        )
        .all()
    )


def get_stats(club_id: int, date_from: date, date_to: date, tz_offset_minutes: int = 0) -> dict:
    if date_to < date_from:
        date_from, date_to = date_to, date_from
    start, end = _window(date_from, date_to, tz_offset_minutes)
    now = datetime.now(timezone.utc)

    services = {s.id: s for s in Service.query.filter_by(club_id=club_id).all()}
    accounts = {a.telegram_user_id: a for a in GuestAccount.query.filter_by(club_id=club_id).all()}
    vip_clients = {v.telegram_user_id: v for v in VipClient.query.filter_by(club_id=club_id).all()}

    def guest_name(gid) -> str:
        account = accounts.get(gid)
        if account is not None and account.display_name:
            return account.display_name
        if account is not None and account.email:
            return account.email
        return f"Гость {str(gid)[-4:]}"

    orders = _orders_between(club_id, start, end)
    sung = [o for o in orders if o.status in SUNG_STATUSES]
    guest_orders = [o for o in orders if o.source == "guest"]
    guest_sung = [o for o in sung if o.source == "guest"]

    # --- Вечер в цифрах ---
    revenue_total = sum(_price(o, services) for o in sung)
    revenue_vip = sum(_price(o, services) for o in sung if o.guest_type == "vip")
    table_songs = Counter(o.table_no for o in sung if o.table_no is not None)
    table_sum = defaultdict(float)
    for o in sung:
        if o.table_no is not None:
            table_sum[o.table_no] += _price(o, services)
    guest_songs = Counter(o.telegram_user_id for o in guest_sung)
    guest_sum = defaultdict(float)
    for o in guest_sung:
        guest_sum[o.telegram_user_id] += _price(o, services)

    top_table = None
    if table_songs:
        no, count = table_songs.most_common(1)[0]
        top_table = {"table_no": no, "songs": count, "sum": round(table_sum[no], 2)}
    top_guest = None
    if guest_songs:
        gid, count = guest_songs.most_common(1)[0]
        top_guest = {"name": guest_name(gid), "songs": count, "sum": round(guest_sum[gid], 2)}

    evening = {
        "ordered": len(orders),
        "sung": len(sung),
        "rejected": sum(1 for o in orders if o.status == STATUS_REJECTED),
        "errors": sum(1 for o in orders if o.status == STATUS_ERROR),
        "waiting": sum(1 for o in orders if o.status not in SUNG_STATUSES + (STATUS_REJECTED, STATUS_ERROR)),
        "tables": len(table_songs),
        "singers": len(guest_songs),
        "revenue": round(revenue_total, 2),
        "revenue_vip": round(revenue_vip, 2),
        "revenue_regular": round(revenue_total - revenue_vip, 2),
        "avg_table": round(revenue_total / len(table_songs), 2) if table_songs else 0,
        "top_table": top_table,
        "top_guest": top_guest,
    }

    # --- Гости ---
    first_last = {}
    for gid, created_at in (
        Order.query.with_entities(Order.telegram_user_id, Order.created_at)
        .filter(Order.club_id == club_id, Order.source == "guest")
        .all()
    ):
        created_at = _aware(created_at)
        current = first_last.get(gid)
        if current is None:
            first_last[gid] = [created_at, created_at]
        else:
            if created_at < current[0]:
                current[0] = created_at
            if created_at > current[1]:
                current[1] = created_at

    all_guest_ids = set(first_last) | set(vip_clients) | set(accounts)
    period_guest_ids = {o.telegram_user_id for o in guest_orders}
    new_ids = {gid for gid in period_guest_ids if first_last.get(gid) and first_last[gid][0] >= start}
    returning_ids = period_guest_ids - new_ids

    lapsed_border = now - timedelta(days=LAPSED_VIP_DAYS)
    lapsed_vips = []
    for gid in vip_clients:
        last = first_last.get(gid, [None, None])[1]
        if last is None or last < lapsed_border:
            lapsed_vips.append({
                "name": guest_name(gid),
                "last_visit": last.isoformat() if last else None,
                "balance": float(vip_clients[gid].balance or 0),
            })
    lapsed_vips.sort(key=lambda row: row["last_visit"] or "")

    guests = {
        "total": len(all_guest_ids),
        "vip": len(vip_clients),
        "regular": len(all_guest_ids) - len(set(vip_clients) & all_guest_ids),
        "active_in_period": len(period_guest_ids),
        "new_in_period": len(new_ids),
        "returning_in_period": len(returning_ids),
        "top_by_songs": [
            {"name": guest_name(gid), "songs": count, "sum": round(guest_sum[gid], 2)}
            for gid, count in guest_songs.most_common(TOP_LIMIT)
        ],
        "top_by_sum": [
            {"name": guest_name(gid), "songs": guest_songs[gid], "sum": round(total, 2)}
            for gid, total in sorted(guest_sum.items(), key=lambda pair: -pair[1])[:TOP_LIMIT]
            if total > 0
        ],
        "lapsed_vips": lapsed_vips[:30],
        "lapsed_vip_days": LAPSED_VIP_DAYS,
    }

    # --- VIP ---
    transactions = (
        Transaction.query
        .filter(
            Transaction.club_id == club_id, Transaction.created_at >= start, Transaction.created_at < end,
            _cleared_exclude(Transaction.created_at, "kj", club_id),
        )
        .all()
    )
    vip_requests = (
        VipRequest.query
        .filter(
            VipRequest.club_id == club_id, VipRequest.created_at >= start, VipRequest.created_at < end,
            _cleared_exclude(VipRequest.created_at, "kj", club_id),
        )
        .all()
    )
    vip = {
        "count": len(vip_clients),
        "balance_total": round(sum(float(v.balance or 0) for v in vip_clients.values()), 2),
        "topups": round(sum(abs(float(t.amount or 0)) for t in transactions if t.type == TX_TYPE_TOPUP), 2),
        "spent": round(sum(abs(float(t.amount or 0)) for t in transactions if t.type == TX_TYPE_ORDER_PAYMENT), 2),
        "requests": len(vip_requests),
        "requests_approved": sum(1 for r in vip_requests if r.status == "approved"),
    }

    # --- Песни ---
    song_counter = Counter()
    song_label = {}
    artist_counter = Counter()
    artist_label = {}
    for o in sung:
        key = (_norm(o.song_title), _norm(o.artist))
        song_counter[key] += 1
        song_label.setdefault(key, (o.song_title, o.artist))
        if key[1]:
            artist_counter[key[1]] += 1
            artist_label.setdefault(key[1], o.artist)

    by_category = defaultdict(lambda: {"songs": 0, "sum": 0.0})
    for o in sung:
        service = services.get(o.service_id)
        name = service.name if service is not None else "Без категории"
        by_category[name]["songs"] += 1
        by_category[name]["sum"] += _price(o, services)

    tones = [o.tone for o in guest_orders if o.tone]
    songs = {
        "top_songs": [
            {"title": song_label[key][0], "artist": song_label[key][1], "count": count}
            for key, count in song_counter.most_common(TOP_LIMIT)
        ],
        "top_artists": [
            {"artist": artist_label[key], "count": count}
            for key, count in artist_counter.most_common(TOP_LIMIT)
        ],
        "by_category": sorted(
            ({"name": name, "songs": row["songs"], "sum": round(row["sum"], 2)} for name, row in by_category.items()),
            key=lambda row: -row["songs"],
        ),
        "renamed_by_kj": sum(1 for o in guest_orders if o.guest_song_text),
        "tone_total": len(tones),
        "tone_down": sum(1 for t in tones if t < 0),
        "tone_up": sum(1 for t in tones if t > 0),
    }

    # --- Как заказывают / как закрываются ---
    how = {
        "by_guests": len(guest_orders),
        "by_kj": sum(1 for o in orders if o.source == "manual"),
        "from_virtualdj": sum(1 for o in orders if o.source == "virtualdj"),
        "done_auto": sum(1 for o in sung if o.completion_source in ("history", "automatic")),
        "done_manual": sum(1 for o in sung if o.completion_source not in ("history", "automatic")),
    }

    # --- Время ---
    by_hour = Counter()
    by_weekday = Counter()
    waits = []
    for o in orders:
        local = _aware(o.created_at) + timedelta(minutes=tz_offset_minutes)
        by_hour[local.hour] += 1
        by_weekday[_club_day(o.created_at, tz_offset_minutes).weekday()] += 1
    for o in guest_sung:
        if o.playing_at is not None:
            minutes = (_aware(o.playing_at) - _aware(o.created_at)).total_seconds() / 60
            if 0 <= minutes <= 24 * 60:
                waits.append(minutes)
    hours_order = list(range(DAY_START_HOUR, 24)) + list(range(0, DAY_START_HOUR))
    timing = {
        "by_hour": [{"hour": h, "count": by_hour[h]} for h in hours_order if by_hour[h]],
        "by_weekday": [{"day": WEEKDAYS[i], "count": by_weekday[i]} for i in range(7)],
        "avg_wait_minutes": round(sum(waits) / len(waits), 1) if waits else None,
    }

    # --- Сравнение с предыдущим таким же периодом ---
    days = (date_to - date_from).days + 1
    shift_days = 7 if days == 1 else days
    prev_from = date_from - timedelta(days=shift_days)
    prev_to = date_to - timedelta(days=shift_days)
    prev_start, prev_end = _window(prev_from, prev_to, tz_offset_minutes)
    compare = {
        "current": _summary(orders, services),
        "previous": _summary(_orders_between(club_id, prev_start, prev_end), services),
        "previous_from": prev_from.isoformat(),
        "previous_to": prev_to.isoformat(),
    }

    return {
        "from": date_from.isoformat(),
        "to": date_to.isoformat(),
        "evening": evening,
        "guests": guests,
        "vip": vip,
        "songs": songs,
        "how": how,
        "timing": timing,
        "compare": compare,
    }
