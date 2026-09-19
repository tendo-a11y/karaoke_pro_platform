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
from models import STATUS_ERROR, STATUS_PENDING, STATUS_PROCESSING, STATUS_QUEUED, Club, Order
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


def get_table_capacity(club: Club) -> int:
    if club.songs_per_table is not None:
        return club.songs_per_table
    return DEFAULT_SONGS_PER_TABLE


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


def _slot_dict(order: Order) -> dict:
    return {
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
    board = []
    for table_no in range(1, club.table_count + 1):
        active, _waiting = partition_table_orders(club_id, table_no, capacity)
        slots = [_slot_dict(order) for order in active]
        slots += [None] * (capacity - len(slots))
        board.append({"table_no": table_no, "capacity": capacity, "slots": slots})
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
