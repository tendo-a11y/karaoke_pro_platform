from datetime import datetime, timezone

from extensions import db
from models import (
    STATUS_ERROR,
    STATUS_PENDING,
    STATUS_PROCESSING,
    STATUS_QUEUED,
    STATUS_REJECTED,
    Order,
    Service,
)
from services.notify import notify_guest
from sockets import emit_order_confirmed, emit_order_rejected, emit_order_updated, emit_queue_updated
from vdj import get_vdj_client
from vdj.base import VirtualDJError


def _utcnow():
    return datetime.now(timezone.utc)


def confirm_order(order_id: int, kj):
    """
    Реализует ТЗ п.14-18: проверка прав/принадлежности клубу, атомарный переход
    pending -> processing (защита от двойного нажатия, п.15), передача в
    VirtualDJ, финальный статус queued/error, уведомление гостя, WebSocket.

    Возвращает (order, outcome), где outcome — один из:
        "not_found", "forbidden", "conflict", "queued", "vdj_error"
    """
    order = db.session.get(Order, order_id)
    if order is None:
        return None, "not_found"

    if order.club_id != kj.club_id:
        return None, "forbidden"

    # Атомарный CAS: строка обновится только если статус всё ещё pending —
    # это и есть защита от повторного подтверждения (ТЗ п.15). Второй
    # одновременный запрос получит updated_rows == 0 и вернёт 409.
    updated_rows = (
        db.session.query(Order)
        .filter(Order.id == order_id, Order.status == STATUS_PENDING)
        .update(
            {
                "status": STATUS_PROCESSING,
                "confirmed_at": _utcnow(),
                "confirmed_by": kj.id,
            },
            synchronize_session=False,
        )
    )
    db.session.commit()

    if updated_rows == 0:
        db.session.refresh(order)
        return order, "conflict"

    db.session.refresh(order)
    emit_order_confirmed(order)

    vdj = get_vdj_client(order.club_id)
    try:
        vdj_item_id = vdj.add_to_queue(order.song_title, order.artist, order.table_no)
    except VirtualDJError as exc:
        order.status = STATUS_ERROR
        order.error_message = str(exc)
        db.session.commit()
        emit_order_updated(order)
        return order, "vdj_error"

    order.status = STATUS_QUEUED
    order.vdj_item_id = vdj_item_id
    order.queued_at = _utcnow()
    db.session.commit()
    emit_order_updated(order)

    # Раньше здесь список строился прямо из vdj.get_queue() (table_no —
    # как есть у драйвера), без сопоставления с заказами — тот же пробел,
    # что был у GET /api/kj/queue/<club_id> и который закрыл
    # get_kj_queue_view() (см. её докстринг ниже): у настоящего
    # NetworkControlVDJDriver номера стола там никогда и не было бы.
    # get_kj_queue_view() делает то же самое, но правильно — через Order.
    emit_queue_updated(order.club_id, get_kj_queue_view(order.club_id))

    # Уведомляем через Telegram Bot API только тех гостей, что реально
    # пришли через настоящего Telegram-бота (channel="telegram") — у гостей
    # Guest App (channel="webapp") telegram_user_id хранит не chat_id, а
    # случайный guest_id анонимной сессии, и попытка отправки туда ничего
    # не доставляет, только тихо проваливается и засоряет журнал. Гость
    # Guest App и так видит смену статуса в разделе "Мои заказы" (опрос
    # каждые несколько секунд, см. guest-app/src/App.jsx::refreshOrders).
    if order.channel == "telegram":
        song_line = f"{order.artist} — {order.song_title}" if order.artist else order.song_title
        notify_guest(
            order.telegram_user_id,
            f"✅ Ваша песня добавлена в очередь.\n\n🎵 {song_line}",
        )

    return order, "queued"


def reject_order(order_id: int, kj):
    """
    ТЗ п.19: отклонение заказа, ещё не переданного в VirtualDJ. Тоже атомарно —
    отклонить можно только заказ, всё ещё находящийся в pending.
    """
    order = db.session.get(Order, order_id)
    if order is None:
        return None, "not_found"

    if order.club_id != kj.club_id:
        return None, "forbidden"

    updated_rows = (
        db.session.query(Order)
        .filter(Order.id == order_id, Order.status == STATUS_PENDING)
        .update({"status": STATUS_REJECTED, "rejected_at": _utcnow()}, synchronize_session=False)
    )
    db.session.commit()

    if updated_rows == 0:
        db.session.refresh(order)
        return order, "conflict"

    db.session.refresh(order)
    emit_order_rejected(order)

    # См. пояснение в confirm_order() выше — только реальные Telegram-гости.
    if order.channel == "telegram":
        song_line = f"{order.artist} — {order.song_title}" if order.artist else order.song_title
        notify_guest(order.telegram_user_id, f"❌ Ваш заказ отклонён KJ.\n\n🎵 {song_line}")

    return order, "rejected"


def _queue_rank(vdj, vdj_item_id: str):
    """
    1-based позиция заказа в текущей очереди VirtualDJ клуба — по образцу
    /api/guest/queue и /api/kj/queue/<club_id> (см. queue() в routes/guest.py),
    единственный источник истины о положении в очереди сейчас (у нового Order
    нет аналога старых orders.position/is_next/marked_next_at — они не
    переносятся, решение согласовано с пользователем при утверждении правил
    замены песни). Возвращает None, если vdj_item_id не найден в очереди.

    Сравнение не строго "равно", а ещё и "заканчивается на" — подтверждено
    живым тестом (vdj_bridge/PHASE6_VDJ_NETWORK_CONTROL.md, раздел 3.8):
    NetworkControlVDJDriver.add_to_queue() сохраняет ПОЛНЫЙ путь с буквой
    диска (например "D:\\...\\файл.mp4", получен от get_browsed_filepath), а
    NetworkControlVDJDriver.get_queue() возвращает путь БЕЗ буквы диска
    (получен из отдельных свойств "filepath"+"filename" — VirtualDJ не
    отдаёт букву диска через них). Это два представления одного и того же
    файла, а не разные файлы — отсюда "заканчивается на" вместо "равно".
    Пустая строка/None никогда не считается совпадением (иначе "abc".
    endswith("") дал бы ложное совпадение с чем угодно).

    Известное ограничение (см. тот же раздел 3.8): если одна и та же песня
    стоит в очереди VirtualDJ дважды одновременно (подтверждено вживую как
    нормальная реальная ситуация), обе записи дадут одинаковый vdj_item_id,
    и здесь вернётся позиция ПЕРВОЙ из них — при заказе той же песни дважды
    ранг может быть определён не совсем точно. Показ живой очереди гостям и
    KJ это не затрагивает (там просто название/исполнитель по позициям).
    """
    if not vdj_item_id:
        return None
    for idx, item in enumerate(vdj.get_queue(), start=1):
        candidate = item.vdj_item_id
        if not candidate:
            continue
        if candidate == vdj_item_id or vdj_item_id.endswith(candidate):
            return idx
    return None


def can_replace_order(order, vdj) -> bool:
    """
    Утверждённая пользователем матрица правил замены песни (см. согласованную
    спецификацию замены песни):

        STATUS_PENDING                          -> можно
        STATUS_PROCESSING                        -> нельзя (переходное
            состояние между подтверждением KJ и добавлением в VDJ — нельзя
            одновременно подтверждать/добавлять в очередь и менять содержимое
            того же заказа)
        STATUS_QUEUED, rank 1 или 2               -> нельзя (слишком близко к
            воспроизведению)
        STATUS_QUEUED, rank >= 3                  -> можно
        STATUS_QUEUED, vdj_item_id не найден в
            текущей vdj.get_queue()                -> нельзя (система не может
            достоверно определить его позицию — безопаснее запретить замену,
            чем случайно позволить изменить песню, которая уже находится на
            границе воспроизведения или была вручную изменена KJ)
        STATUS_PLAYING/COMPLETED/REJECTED/ERROR   -> нельзя (заказ уже
            завершил свой жизненный цикл в очереди/на сцене)
    """
    if order.status == STATUS_PENDING:
        return True
    if order.status == STATUS_QUEUED:
        rank = _queue_rank(vdj, order.vdj_item_id)
        return rank is not None and rank >= 3
    return False


def replace_order(order_id: int, guest_id: int, club_id: int, song_title: str, artist, service_id):
    """
    Замена песни в уже существующем заказе гостя (Role 3/4/5). Согласованная
    и утверждённая пользователем спецификация:
      - менять может только владелец заказа (старая уязвимость old
        handlers/client.py::order_replace / replace_svc_execute, где владелец
        НЕ проверялся вообще ни на одном из трёх шагов, сознательно не
        переносится);
      - меняются только song_title/artist/service_id — без отдельной денежной
        операции (старая денежная логика replace_svc_execute, которая
        проверяла баланс, но не списывала и не возвращала деньги, тоже не
        переносится: charge-at-completion спишет по тому service_id, который
        будет актуален на момент завершения песни — новая архитектура,
        установленная ранее в проекте);
      - лимита на количество замен нет.

    Возвращает (order, outcome), где outcome — один из:
        "not_found", "forbidden", "not_allowed", "service_not_found", "replaced"
    """
    order = db.session.get(Order, order_id)
    if order is None:
        return None, "not_found"

    if order.club_id != club_id or order.telegram_user_id != guest_id:
        return None, "forbidden"

    vdj = get_vdj_client(order.club_id)
    if not can_replace_order(order, vdj):
        return order, "not_allowed"

    if service_id is not None:
        service = db.session.get(Service, service_id)
        if service is None or service.club_id != club_id:
            return order, "service_not_found"

    order.song_title = song_title
    order.artist = artist
    order.service_id = service_id
    db.session.commit()

    emit_order_updated(order)

    return order, "replaced"


def remove_from_vdj_queue(club_id: int, vdj_item_id: str):
    """ТЗ п.20: удаление уже добавленного в очередь VirtualDJ элемента —
    отдельная операция от отклонения ещё не переданного заказа.

    club_id обязателен по той же причине, что и в confirm_order(): в режиме
    VDJ_ADAPTER=bridge команду нужно адресовать мосту конкретного клуба,
    а не какому попало (сейчас у функции нет вызывающего кода, но сигнатура
    сразу сделана консистентной с остальными местами, использующими
    get_vdj_client(), чтобы не отставить "молчаливую" точку отказа на потом)."""
    vdj = get_vdj_client(club_id)
    vdj.remove_from_queue(vdj_item_id)


def get_kj_queue_view(club_id: int) -> list[dict]:
    """
    Живая очередь VirtualDJ клуба, где каждая позиция по возможности
    сопоставлена с конкретным заказом (Order) в статусе STATUS_QUEUED — нужно
    KJ Pro, чтобы показывать номер стола рядом с песней. Сам VirtualDJ номер
    стола никогда не хранит (об этом знает только наша база), поэтому без
    такого сопоставления колонка "Стол" всегда была бы пустой при работе с
    настоящим VirtualDJ (см. обсуждение с пользователем про фоновую
    синхронизацию живой очереди в KJ Pro).

    Сопоставление — по vdj_item_id, тем же способом "равно или заканчивается
    на", что и _queue_rank() выше (см. её докстринг про букву диска и
    дубликаты), но здесь сразу для ВСЕЙ очереди целиком, а не для одного
    заказа. Каждый Order используется как совпадение не более одного раза:
    если одна и та же песня стоит в очереди VirtualDJ дважды одновременно
    (подтверждено вживую как нормальный реальный случай, не баг), позиции
    разбираются по порядку живой очереди, и каждой достаётся ещё не занятый
    заказ — так же, как если бы KJ сам сверял список сверху вниз.

    Если для позиции живой очереди подходящего заказа не нашлось — значит
    песню добавили (или переместили сюда) прямо в VirtualDJ, в обход Guest
    App и Backend (KJ вручную перетащил файл в очередь). Согласовано с
    пользователем: автоматически заводить для такой позиции новый заказ в
    базе нельзя (мы не знаем ни стола, ни гостя) — она просто показывается
    KJ Pro "как есть", с order_id=None. Именно по наличию order_id (а не по
    значению table_no) экран отличает такую позицию от легитимного заказа
    без стола (order_id есть, table_no=None, гость сам не указал стол).
    """
    vdj = get_vdj_client(club_id)
    live_queue = vdj.get_queue()

    unused_orders = (
        db.session.query(Order)
        .filter(Order.club_id == club_id, Order.status == STATUS_QUEUED)
        .order_by(Order.queued_at.asc())
        .all()
    )

    result = []
    for item in live_queue:
        matched = None
        if item.vdj_item_id:
            for order in unused_orders:
                if not order.vdj_item_id:
                    continue
                if order.vdj_item_id == item.vdj_item_id or item.vdj_item_id.endswith(order.vdj_item_id):
                    matched = order
                    break
            if matched is not None:
                unused_orders.remove(matched)

        result.append(
            {
                "vdj_item_id": item.vdj_item_id,
                "song_title": item.song_title,
                "artist": item.artist,
                "table_no": matched.table_no if matched else None,
                "order_id": matched.id if matched else None,
            }
        )
    return result


def add_manual_song(kj, song_title: str, artist, table_no: int):
    """
    KJ добавляет песню в очередь VirtualDJ прямо из панели KJ Pro, минуя
    гостя и Guest App целиком — новый экран "Добавить песню" (следующий
    после фоновой синхронизации живой очереди блок ТЗ). Согласовано с
    пользователем отдельно, двумя решениями:
      1) песню ищем в настоящих файлах VirtualDJ, а не в загруженном CSV-
         каталоге клуба (services/song_service.py) — тот годится только
         гостю как подсказка при наборе текста, реального пути к файлу не
         хранит и здесь не подходит;
      2) стол указывает сам KJ, заказ создаётся и уходит в очередь СРАЗУ,
         одним действием — без промежуточного "pending" и без отдельного
         подтверждения перетаскиванием, как в confirm_order() выше (KJ уже
         принял решение в момент нажатия "Добавить").

    Стол обязателен (в отличие от гостевого заказа, где table_no=None —
    легитимный "заказ без стола", ТЗ п.27): здесь стол не выбирает гость,
    его указывает KJ, так что null означал бы просто "забыли ввести", а не
    осознанный выбор — поэтому пустой/нулевой table_no отклоняется вызывающим
    кодом (маршрутом) ещё до этой функции.

    telegram_user_id = -1: единственное безопасно "не гость" значение —
    настоящие Telegram ID (старый бот) и id анонимных веб-сессий (см.
    routes/guest.py::_new_guest_id, secrets.randbits(62)) всегда
    неотрицательные, поэтому -1 гарантированно не совпадёт ни с одним
    реальным гостем и никогда не попадёт в чьё-то "Мои заказы".

    source="manual" — то самое значение, для которого поле Order.source уже
    было заведено (см. комментарий у него в models.py: "guest | manual |
    virtualdj"), просто раньше нигде не проставлялось.
    channel="webapp" (не "telegram") — единственная его роль в остальном
    коде (см. confirm_order() выше) — решать, пытаться ли уведомить гостя
    через Telegram Bot API; здесь уведомлять некого, "webapp" это надёжно
    выключает, не требуя заводить в этом поле третье значение.

    Если VirtualDJ отклонил добавление (VirtualDJError) — заказ вообще не
    создаётся (в отличие от confirm_order(), где заказ уже существовал до
    попытки и в случае неудачи помечается STATUS_ERROR): здесь заказа до
    успешного добавления в VirtualDJ просто не было, создавать его "уже
    сломанным" незачем.

    Возвращает (order, outcome), outcome — один из: "vdj_error", "queued".
    Валидация song_title/table_no (тип, пустота) — на маршруте, как и у
    POST /api/guest/order (routes/guest.py), эта функция получает уже
    проверенные значения.
    """
    vdj = get_vdj_client(kj.club_id)
    try:
        vdj_item_id = vdj.add_to_queue(song_title, artist, table_no)
    except VirtualDJError:
        return None, "vdj_error"

    order = Order(
        telegram_user_id=-1,
        club_id=kj.club_id,
        table_no=table_no,
        song_title=song_title,
        artist=artist,
        status=STATUS_QUEUED,
        source="manual",
        channel="webapp",
        vdj_item_id=vdj_item_id,
        queued_at=_utcnow(),
        confirmed_by=kj.id,
        confirmed_at=_utcnow(),
    )
    db.session.add(order)
    db.session.commit()

    emit_queue_updated(kj.club_id, get_kj_queue_view(kj.club_id))

    return order, "queued"
