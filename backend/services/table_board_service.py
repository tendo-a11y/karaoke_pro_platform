"""
Панель заказов по столам (доп. ТЗ "KJ Pro", запрос пользователя 2026-09-18,
обсуждение перед реализацией — "делай посмотрим"): экран "Заказы" в KJ
Panel — сетка карточек по числу столов клуба (Club.table_count), в каждой
карточке столько мест, сколько задано в Club.songs_per_table (оба поля —
services/../models.py::Club, добавлены предыдущим шагом "настройки столов
KJ-04").

Место на карточке занимает не любой заказ этого стола, а только "активное
окно" — первые (по времени создания) songs_per_table ещё не отклонённых и
не завершённых заказа стола. Все следующие заказы того же стола сверх
этого окна (запрос пользователя: "заказы 3,4,5,6 от одного стола висят
невидимо и видны только у заказавшего как ожидающие очереди") этой панелью
KJ вообще не показываются — ни на карточке, ни где-либо ещё. Гость же видит
их в своём разделе "Мои заказы" как ожидание с номером места в очереди (см.
get_waiting_positions() ниже, используется в routes/guest.py::
list_my_orders).

Как только место освобождается — KJ отклонил стоящий на нём заказ
(STATUS_REJECTED, reject_order()), либо принятый заказ реально отыгран и KJ
сам отметил это кнопкой "Готово" (STATUS_COMPLETED, complete_order()) —
следующий по времени "невидимый" заказ того же стола сам занимает
освободившееся место: окно каждый раз считается заново по текущим данным,
никакого отдельного шага "продвижения в очереди" не требуется. Он
появляется у KJ как обычная заявка, ждущая решения (запрос пользователя:
"всегда с моим решением новый заказ") — confirm_order/reject_order не
менялись в этой части, они и так уже требуют явного действия KJ по каждому
заказу.

2026-09-18, запрос пользователя: confirm_order() (services/vdj_service.py)
больше не передаёт принятый заказ в VirtualDJ сама — мост VirtualDJ часто
недоступен, а KJ и так предпочитает ставить песню в плеер вручную. Поэтому
STATUS_QUEUED теперь означает не "реально стоит в очереди VirtualDJ", а
"KJ принял заказ и сам поставит песню, когда дойдёт очередь" — место на
карточке освобождается только явной кнопкой "Готово" (complete_order()), а
не сверкой с живой очередью VirtualDJ (get_kj_queue_view() теперь
сознательно игнорирует такие заказы — у них никогда не будет vdj_item_id).
"""
from extensions import db
from models import STATUS_ERROR, STATUS_PENDING, STATUS_PROCESSING, STATUS_QUEUED, Club, Order, Service
from services.vdj_service import get_kj_queue_view

# Заказ занимает место на карточке, пока не отклонён и не ушёл из очереди —
# то же самое "ещё не решено" состояние, что и в старом списке заявок KJ
# Panel (см. kj-panel/src/App.jsx::ORDER_STAYS_IN_LIST_STATUSES), плюс
# STATUS_QUEUED (уже в очереди — тоже занимает место, просто в другом
# визуальном виде на карточке) и STATUS_PROCESSING (короткий переходный
# статус confirm_order между pending и queued/error, см. её докстринг).
ACTIVE_TABLE_STATUSES = (STATUS_PENDING, STATUS_PROCESSING, STATUS_QUEUED, STATUS_ERROR)

# Пока KJ явно не задал Club.songs_per_table (nullable=True, без
# server_default — см. models.py) — старое поведение системы и так
# ограничивало гостя двумя одновременными заказами в принципе
# (config.py::MAX_ACTIVE_SONGS_PER_GUEST, по умолчанию тоже 2), так что для
# стола с одним гостем это на практике и означало "2 песни от стола
# одновременно". Оставляем то же число здесь по умолчанию, чтобы для уже
# существующих клубов, ещё не заходивших в новые настройки столов, картина
# на этой панели не изменилась внезапно сама по себе.
DEFAULT_SONGS_PER_TABLE = 2

# ДОБАВЛЕНО (2026-09-24, запрос пользователя "нужно добавить варианты
# очереди" на вкладке "Столы" KJ Panel):
#
# QUEUE_MODE_MANUAL ("непоследовательный", значение по умолчанию для уже
#   существующих клубов — старое поведение вообще не меняется) — очередь
#   ведёт сам KJ вручную, номера очереди на карточках не показываются.
#
# QUEUE_MODE_SEQUENTIAL ("последовательный") — обсуждение с пользователем:
#   режим меняет ТОЛЬКО отображение (порядок/номер на карточках KJ и номер
#   очереди у гостя в "Мои заказы"), а не саму механику постановки песни —
#   KJ по-прежнему сам вручную ставит песню в VirtualDJ/"Добавить песню"
#   когда сочтёт нужным, никакой блокировки нет.
#
#   Порядок в этом режиме — круговой обход столов по возрастанию номера
#   (1..Club.table_count, а не только "занятых" столов), на каждом проходе
#   с каждого стола берётся не больше capacity (то же "Песен на стол
#   одновременно") его старейших ещё не взятых заказов; если у стола
#   заказов больше или новый заказ стола пришёл уже после того, как место
#   стола в текущем проходе определено — лишнее уходит в СЛЕДУЮЩИЙ проход,
#   а не встраивается задним числом в текущий (пример пользователя: "если
#   заняты только до 10 стола и в очереди уже есть 3 стол, то он начинает
#   новый круг"). Пустые на момент расчёта столы просто пропускаются, их
#   место никуда не переносится. Считается заново при каждом обращении —
#   отдельного счётчика "номер круга" в БД не заводим, тот же приём, что и
#   у get_club_queue_positions ниже.
#
# ИСПРАВЛЕНО/ДОБАВЛЕНО (2026-09-25, баг от пользователя: заказ со стола 3
# показал гостю номер в очереди 1, хотя перед этим уже стояли 3 заказа со
# стола 16): круг ВСЕГДА начинался с 1-го стола, поэтому любой новый заказ
# стола с номером МЕНЬШЕ, чем у уже стоящих в очереди столов, обгонял их,
# даже если очередь клуба фактически "началась" с гораздо большего номера
# (пользователь: "не указано с какого стола началась очередь, а началась с
# 16-го"). Решение пользователя — не угадывать это автоматически по данным
# заказов, а завести явную ручную настройку: Club.queue_start_table
# ("Начало очереди" на вкладке "Столы", задаёт Роль 2/KJ) — номер стола, с
# которого начинается обход. Круг идёт по возрастанию от этого стола до
# table_count, затем оборачивается на 1 и до queue_start_table-1 (см.
# _round_robin_order) — например, при table_count=18 и queue_start_table=17
# первый отрезок до оборота короткий (столы 17, 18), дальше обход
# продолжает 1..16, оставаясь тем же кругом. Пока KJ явно не задал — по
# умолчанию 1 (то же самое поведение, что было до этой настройки).
QUEUE_MODE_MANUAL = "manual"
QUEUE_MODE_SEQUENTIAL = "sequential"
QUEUE_MODE_CHOICES = (QUEUE_MODE_MANUAL, QUEUE_MODE_SEQUENTIAL)
DEFAULT_QUEUE_MODE = QUEUE_MODE_MANUAL
DEFAULT_QUEUE_START_TABLE = 1

# Категория CRAZY ("Песня вне очереди", см. services/category_service.py::
# DEFAULT_CATEGORIES) — запрос пользователя 2026-09-24: заказ этой
# категории всегда встаёт первым в очереди, ДО кругового расчёта, в ОБОИХ
# режимах (manual и sequential), независимо от того, кто его выбрал — гость
# при заказе или сам KJ через "Добавить песню"/"Присвоить". Определяем по
# названию категории (Service.name), как и сама категория задаётся сейчас —
# отдельного флага не заводим (решение пользователя: "категория Crazy есть
# и зашита в код сейчас").
CRAZY_CATEGORY_NAME = "CRAZY"


def get_table_capacity(club: Club) -> int:
    if club.songs_per_table is not None:
        return club.songs_per_table
    return DEFAULT_SONGS_PER_TABLE


def get_queue_mode(club: Club) -> str:
    return club.queue_mode or DEFAULT_QUEUE_MODE


def get_queue_start_table(club: Club) -> int:
    if club.queue_start_table:
        return club.queue_start_table
    return DEFAULT_QUEUE_START_TABLE


def _split_crazy_orders(orders: list[Order]) -> tuple[list[Order], list[Order]]:
    """(crazy, остальные) — crazy отсортированы между собой по времени
    создания, остальные возвращаются в том же порядке, что и на входе."""
    if not orders:
        return [], []
    service_ids = {o.service_id for o in orders if o.service_id is not None}
    if not service_ids:
        return [], orders
    crazy_ids = {
        row.id for row in Service.query.filter(
            Service.id.in_(service_ids), Service.name == CRAZY_CATEGORY_NAME,
        ).all()
    }
    if not crazy_ids:
        return [], orders
    crazy = sorted(
        (o for o in orders if o.service_id in crazy_ids),
        key=lambda o: (o.created_at, o.id),
    )
    rest = [o for o in orders if o.service_id not in crazy_ids]
    return crazy, rest


def _round_robin_order(
    orders: list[Order], table_count: int, capacity: int, anchor_table: int = 1,
) -> list[Order]:
    """Круговой обход столов, начиная с anchor_table и далее по кругу
    (anchor_table..table_count, затем 1..anchor_table-1) — см. докстринг
    QUEUE_MODE_SEQUENTIAL выше про сам приём и его исправление 2026-09-25
    (обход больше не зашит на старт с 1-го стола). orders — заказы С заданным
    table_no."""
    by_table: dict[int, list[Order]] = {}
    for order in orders:
        by_table.setdefault(order.table_no, []).append(order)
    for bucket in by_table.values():
        bucket.sort(key=lambda o: (o.created_at, o.id))

    if table_count > 0:
        anchor = ((anchor_table - 1) % table_count) + 1
    else:
        anchor = 1
    table_sequence = list(range(anchor, table_count + 1)) + list(range(1, anchor))

    cursor = {table_no: 0 for table_no in by_table}
    sequence: list[Order] = []
    remaining = len(orders)
    while remaining > 0:
        progressed = False
        for table_no in table_sequence:
            bucket = by_table.get(table_no)
            if not bucket:
                continue
            start = cursor[table_no]
            if start >= len(bucket):
                continue
            take = bucket[start:start + capacity]
            sequence.extend(take)
            cursor[table_no] = start + len(take)
            remaining -= len(take)
            progressed = True
        if not progressed:
            # Остались заказы столов вне диапазона 1..table_count (номер
            # стола больше текущего table_count клуба, например, после
            # уменьшения числа столов) — не зацикливаемся, а докидываем их
            # в конец по времени создания.
            leftover = []
            for table_no, bucket in by_table.items():
                leftover.extend(bucket[cursor[table_no]:])
                cursor[table_no] = len(bucket)
            leftover.sort(key=lambda o: (o.created_at, o.id))
            sequence.extend(leftover)
            remaining = 0
    return sequence


def compute_queue_order(club_id: int) -> list[Order]:
    """
    Глобальный порядок исполнения по всему клубу — используется и для
    номера очереди у гостя (get_club_queue_positions), и, только в режиме
    QUEUE_MODE_SEQUENTIAL, для номеров на карточках KJ (get_orders_board).

    CRAZY — всегда в начале, в обоих режимах (см. докстринг
    CRAZY_CATEGORY_NAME). Всё остальное — круговым обходом столов
    (_round_robin_order) в режиме sequential, иначе как и раньше — просто
    по времени создания (никакого поведенческого изменения для клубов,
    ещё не включивших sequential).
    """
    club = db.session.get(Club, club_id)
    orders = (
        Order.query
        .filter(Order.club_id == club_id, Order.status.in_(ACTIVE_TABLE_STATUSES))
        .order_by(Order.created_at.asc(), Order.id.asc())
        .all()
    )
    crazy, rest = _split_crazy_orders(orders)

    if club is not None and get_queue_mode(club) == QUEUE_MODE_SEQUENTIAL:
        tableless = [o for o in rest if o.table_no is None]
        tabled = [o for o in rest if o.table_no is not None]
        table_count = club.table_count or max((o.table_no for o in tabled), default=0)
        if table_count > 0:
            # Якорь — Club.queue_start_table, задаётся вручную KJ на
            # вкладке "Столы" ("Начало очереди", см. докстринг
            # QUEUE_MODE_SEQUENTIAL выше) — не автоматика, число тех, кто
            # первым сделал заказ, может не совпадать со столом, откуда KJ
            # реально решил начать вечер.
            anchor_table = get_queue_start_table(club)
            ordered_tabled = _round_robin_order(tabled, table_count, get_table_capacity(club), anchor_table)
        else:
            ordered_tabled = sorted(tabled, key=lambda o: (o.created_at, o.id))
        tableless_sorted = sorted(tableless, key=lambda o: (o.created_at, o.id))
        rest = ordered_tabled + tableless_sorted

    return crazy + rest


def partition_table_orders(club_id: int, table_no: int, capacity: int):
    """
    (активные, ожидающие) заказы одного стола, отсортированные по времени
    создания — первые capacity штук активны (их видит KJ), остальные ждут
    невидимо (см. докстринг файла).
    """
    orders = (
        Order.query
        .filter(Order.club_id == club_id, Order.table_no == table_no, Order.status.in_(ACTIVE_TABLE_STATUSES))
        .order_by(Order.created_at.asc())
        .all()
    )
    return orders[:capacity], orders[capacity:]


def _slot_dict(order: Order, queue_positions: dict | None = None) -> dict:
    data = {
        "order_id": order.id,
        "guest_id": order.telegram_user_id,
        "song_title": order.song_title,
        "artist": order.artist,
        "service_id": order.service_id,
        "status": order.status,
        "error_message": order.error_message,
        # Запрос пользователя 2026-09-19: "Готово" (списывает оплату по
        # тарифу, см. complete_order/charge_at_completion) должно быть
        # видно только у VIP-заказов — обычным гостям оплата не положена
        # в принципе. Фронтенду нужен guest_type самого заказа (а не
        # текущий guest_type гостя из guest_status/directory — берём
        # именно "снимок" на момент заказа, ту же колонку, которую уже
        # читает charge_at_completion), чтобы решить, показывать кнопку.
        "guest_type": order.guest_type,
    }
    # ДОБАВЛЕНО (2026-09-24, режим очереди QUEUE_MODE_SEQUENTIAL) — номер
    # места в общем круговом порядке клуба. Ключ появляется в ответе,
    # только когда режим клуба sequential (queue_positions передан не
    # None) — в manual (по умолчанию) ответ побайтово как раньше.
    if queue_positions is not None:
        data["queue_position"] = queue_positions.get(order.id)
    return data


def get_orders_board(club_id: int) -> list[dict]:
    """
    Данные для сетки карточек столов — GET /api/kj/orders-board/<club_id>.

    Сначала прогоняем живую очередь через get_kj_queue_view() — ту же
    функцию, что использует экран "Живая очередь VirtualDJ". Она уже умеет
    находить заказы, пропавшие из очереди VirtualDJ (песня отыграна и
    ушла), и переводит их в STATUS_REJECTED (см. её докстринг в
    vdj_service.py) — это и есть механизм освобождения места на карточке,
    отдельно его реализовывать не нужно.

    Если у клуба ещё не задано число столов (Club.table_count is None —
    "не ограничено", исторический смысл поля для номера стола у заказа) —
    сетку карточек строить не из чего, возвращаем пустой список: экран
    столов в KJ Panel и так уже просит сначала задать число столов в
    настройках (см. TableSettingsPanel, kj-panel/src/App.jsx).
    """
    get_kj_queue_view(club_id)

    club = db.session.get(Club, club_id)
    if club is None or not club.table_count:
        return []

    capacity = get_table_capacity(club)
    mode = get_queue_mode(club)
    # Номера очереди на карточках считаем только в режиме sequential — в
    # manual (умолчание, старое поведение) queue_positions остаётся None,
    # и _slot_dict вообще не добавляет ключ "queue_position" в ответ (см.
    # её докстринг) — ответ для уже существующих клубов не меняется.
    queue_positions = None
    if mode == QUEUE_MODE_SEQUENTIAL:
        ordered = compute_queue_order(club_id)
        queue_positions = {order.id: index for index, order in enumerate(ordered, start=1)}

    board = []
    for table_no in range(1, club.table_count + 1):
        active, _waiting = partition_table_orders(club_id, table_no, capacity)
        slots = [_slot_dict(order, queue_positions) for order in active]
        slots += [None] * (capacity - len(slots))
        board.append({"table_no": table_no, "capacity": capacity, "queue_mode": mode, "slots": slots})
    return board


def get_waiting_positions(club_id: int, guest_id: int) -> dict:
    """
    {order_id: позиция (с 1) в невидимом ожидании} для заказов ЭТОГО
    гостя — используется в routes/guest.py::list_my_orders, чтобы гость
    видел "вы ждёте своей очереди, вы N-й" по заказам сверх лимита стола
    (см. докстринг файла). Заказы, уже попавшие в активное окно (их и так
    видит KJ на карточке), в этот словарь не попадают — номер очереди у
    себя гость по ним не должен видеть (по аналогии с решением пользователя
    про саму карточку KJ: "номер очереди тут не надо").
    """
    club = db.session.get(Club, club_id)
    if club is None:
        return {}
    capacity = get_table_capacity(club)

    # Гостю может принадлежать несколько активных заказов на разных столах
    # сразу (например, один отклонён на одном столе, другой новый — на
    # другом) — окно считаем по каждому встретившемуся столу отдельно.
    guest_orders = (
        Order.query
        .filter(Order.club_id == club_id, Order.telegram_user_id == guest_id, Order.status.in_(ACTIVE_TABLE_STATUSES))
        .all()
    )
    tables = {o.table_no for o in guest_orders if o.table_no is not None}

    positions = {}
    for table_no in tables:
        _active, waiting = partition_table_orders(club_id, table_no, capacity)
        for index, order in enumerate(waiting, start=1):
            if order.telegram_user_id == guest_id:
                positions[order.id] = index
    return positions


def get_club_queue_positions(club_id: int) -> dict:
    """
    {order_id: позиция (с 1)} в ОБЩЕЙ очереди клуба — по всем столам сразу,
    а не по отдельному столу (запрос пользователя 2026-09-19: сообщение
    после отправки заказа звучало как "ждите подтверждения KJ", будто нужно
    чьё-то ручное разрешение — по факту гостю нужен номер в очереди на
    исполнение, "12 столов по 2 песни — значит впереди меня может быть до
    24 песен, а моя, скажем, 23-я"; число пересчитывается заново на каждый
    запрос и меняется по ходу вечера, никакой отдельный "шаг подтверждения"
    гостю показывать не нужно).

    В очередь считаются все ещё не сыгранные и не отклонённые заказы клуба
    (тот же набор статусов ACTIVE_TABLE_STATUSES, что и на карточках KJ —
    pending/processing/queued/error), по всем столам вместе. Это отдельное
    понятие от get_waiting_positions() выше (та — служебная, только для
    "невидимого" излишка сверх songs_per_table на ОДНОМ столе, для экрана
    KJ) — здесь же считаем позицию НЕЗАВИСИМО от лимита мест на карточке,
    потому что гостю важно место во всей очереди клуба, а не то, видит ли
    её уже KJ на доске.

    ОБНОВЛЕНО (2026-09-24, "варианты очереди"): порядок теперь берём из
    compute_queue_order() — CRAZY всегда первым (в обоих режимах очереди),
    а для остальных заказов — круговой обход столов в режиме sequential,
    иначе как и раньше просто по времени создания. Для клубов, ещё не
    включивших sequential и без заказов категории CRAZY, результат
    побайтово совпадает со старым поведением.
    """
    ordered = compute_queue_order(club_id)
    return {order.id: index for index, order in enumerate(ordered, start=1)}
