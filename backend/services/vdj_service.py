from datetime import datetime, timedelta, timezone

from extensions import db
from models import (
    ORDER_CHANGE_KIND_CANCEL,
    ORDER_CHANGE_KIND_REPLACE,
    STATUS_COMPLETED,
    STATUS_ERROR,
    STATUS_ORDER_CHANGE_APPROVED,
    STATUS_ORDER_CHANGE_PENDING,
    STATUS_ORDER_CHANGE_REJECTED,
    STATUS_PENDING,
    STATUS_PLAYING,
    STATUS_PROCESSING,
    STATUS_QUEUED,
    STATUS_REJECTED,
    ChatMessage,
    Order,
    OrderChangeRequest,
    Service,
)
from services.notify import notify_guest
from sockets import (
    emit_order_change_request_created,
    emit_order_change_request_decided,
    emit_order_confirmed,
    emit_order_rejected,
    emit_order_updated,
    emit_queue_updated,
)
from vdj import get_vdj_client
from vdj.base import VirtualDJError


def _utcnow():
    return datetime.now(timezone.utc)


def confirm_order(order_id: int, kj):
    """
    Реализует ТЗ п.14-18: проверка прав/принадлежности клубу, атомарный переход
    pending -> processing (защита от двойного нажатия, п.15), уведомление
    гостя, WebSocket.

    2026-09-18, запрос пользователя: подтверждение заказа больше НЕ передаёт
    песню в VirtualDJ само (раньше — vdj.add_to_queue() прямо здесь, с
    финальным статусом queued при успехе или error при сбое моста/VDJ). На
    практике мост VirtualDJ регулярно недоступен или нестабилен, и тогда
    кнопка "Принять" на карточке стола отвечала 502 VDJ_UNAVAILABLE, хотя KJ
    ничего не просил у VirtualDJ — он просто хочет сказать гостю "заказ
    принят", а саму песню в плеер поставит сам, вручную, когда дойдёт
    очередь (тем же способом, что и для любой другой песни — экран "➕
    Добавить" / AddManualSongForm). Поэтому теперь подтверждение сразу и
    безусловно переводит заказ в STATUS_QUEUED, минуя VirtualDJ вообще —
    vdj_item_id у такого заказа остаётся пустым.

    Место на карточке стола (services/table_board_service.py) для такого
    заказа освобождается уже не автоматически через реконсиляцию с живой
    очередью VirtualDJ (get_kj_queue_view() теперь сознательно игнорирует
    STATUS_QUEUED-заказы без vdj_item_id — см. её докстринг ниже), а явным
    действием KJ — кнопкой "Готово" (см. mark_played() ниже), когда
    песня реально отыграна.

    Возвращает (order, outcome), где outcome — один из:
        "not_found", "forbidden", "conflict", "queued"
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

    order.status = STATUS_QUEUED
    order.queued_at = _utcnow()
    db.session.commit()
    emit_order_updated(order)

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
            f"✅ Ваш заказ принят!\n\n🎵 {song_line}",
        )

    return order, "queued"


def reject_order(order_id: int, kj):
    """
    ТЗ п.19: отклонение заказа, ещё не переданного в VirtualDJ. Тоже атомарно —
    отклонить можно только заказ, ещё не сыгранный.

    2026-09-17, следом за исправлением App.jsx (карточка с ошибкой VDJ больше
    не пропадает сама, а ждёт решения KJ, и кнопка "ОТКЛОНИТЬ" на ней теперь
    показывается): здесь этого не учли, из-за чего кнопка нажималась, но
    сервер отвечал 409 "заказ уже обработан" и ничего не менял — на практике
    заказы с ошибкой оказывались вообще неудаляемыми. Поэтому отклонить
    теперь можно и STATUS_PENDING (обычный случай — новый заказ), и
    STATUS_ERROR (KJ разобрался с ошибкой и убирает карточку).

    ДОБАВЛЕНО (2026-09-20, жалоба пользователя "нет возможности удалить" —
    и у гостя, и у KJ не было способа убрать ОДИН уже принятый заказ по
    отдельности, только отклонить его, пока он ещё pending, или закрыть
    сразу весь стол): теперь можно отклонить и STATUS_QUEUED — тот же смысл,
    что и кнопка "🗑 Убрать" на карточке места KJ Panel ниже.

    ДОБАВЛЕНО (запрос пользователя 2026-09-30, кнопка "Вернуть" на карточке
    стола): теперь можно отклонить и STATUS_PLAYING — песню, которую уже
    отметили сыгранной (mark_played() выше, вручную или в будущем
    автоматически по истории VirtualDJ), но до закрытия стола решили не
    засчитывать (ошибочно распознали не ту песню и т.п.). Деньги нигде
    здесь не списываются и не возвращаются: весь расчёт происходит одной
    суммой при закрытии стола (services/table_close_service.py::
    complete_table_orders) — отклонённый заказ (в любой момент, до какого
    бы статуса он ни дошёл) в этот расчёт просто не попадает.
    """
    order = db.session.get(Order, order_id)
    if order is None:
        return None, "not_found"

    if order.club_id != kj.club_id:
        return None, "forbidden"

    updated_rows = (
        db.session.query(Order)
        .filter(Order.id == order_id, Order.status.in_([STATUS_PENDING, STATUS_QUEUED, STATUS_ERROR, STATUS_PLAYING]))
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


# ДОБАВЛЕНО (2026-09-20, жалоба пользователя "нет возможности удалить" в
# "Мои заказы" Guest App): раньше гость мог только заменить песню в своём
# заказе (replace_order ниже) или дождаться решения KJ — самостоятельно
# отменить СВОЙ ещё не сыгранный заказ было нельзя вообще. Разрешённые
# статусы намеренно совпадают с can_replace_order (PENDING/QUEUED) —
# то же самое "заказ ещё не завершил жизненный цикл", что и у замены песни;
# STATUS_PROCESSING сознательно исключён (короткое переходное состояние
# confirm_order, см. её докстринг — отменять заказ ровно в момент его
# обработки KJ так же небезопасно, как и заменять в нём песню).
CANCELABLE_BY_GUEST_STATUSES = (STATUS_PENDING, STATUS_QUEUED)


def get_pending_change_request(order_id: int) -> OrderChangeRequest | None:
    """Неразобранная (ещё не одобренная/отклонённая KJ) заявка на изменение
    конкретного заказа, если она есть — используется и request_order_cancel/
    request_order_replace ниже (не даём завести вторую заявку поверх ещё не
    решённой первой), и routes/guest.py::list_my_orders (гостю показывается
    статус "ждите решения ведущего" вместо кнопок)."""
    return (
        OrderChangeRequest.query
        .filter_by(order_id=order_id, status=STATUS_ORDER_CHANGE_PENDING)
        .order_by(OrderChangeRequest.created_at.desc())
        .first()
    )


def request_order_cancel(order_id: int, guest_id: int, club_id: int):
    """
    ПЕРЕСМОТРЕНО 2026-09-20 — решение пользователя "Нужно одобрение KJ
    (запрос → Одобрить/Отклонить)": эта функция раньше называлась
    cancel_order_by_guest и отменяла заказ НЕМЕДЛЕННО. Теперь она только
    заводит заявку (OrderChangeRequest, kind="cancel") — реальная отмена
    происходит в approve_order_change_request() ниже, когда KJ нажимает
    "Одобрить". Владелец заказа проверяется так же строго, как раньше (та
    же ранее исправленная уязвимость — владелец при подобных действиях
    вообще не проверялся, здесь сознательно не повторяем эту ошибку).

    Возвращает (change_request, outcome), где outcome — один из:
        "not_found", "forbidden", "not_allowed", "already_pending", "requested"
    (order при "not_allowed" НЕ возвращается вторым элементом, в отличие от
    старой cancel_order_by_guest, — вызывающему коду (routes/guest.py) он для
    этих исходов не нужен, а для "requested"/"already_pending" первым
    элементом уже возвращается сама заявка).
    """
    order = db.session.get(Order, order_id)
    if order is None:
        return None, "not_found"

    if order.club_id != club_id or order.telegram_user_id != guest_id:
        return None, "forbidden"

    if order.status not in CANCELABLE_BY_GUEST_STATUSES:
        return None, "not_allowed"

    existing = get_pending_change_request(order_id)
    if existing is not None:
        return existing, "already_pending"

    change_request = OrderChangeRequest(
        club_id=club_id,
        order_id=order_id,
        guest_id=guest_id,
        kind=ORDER_CHANGE_KIND_CANCEL,
    )
    db.session.add(change_request)
    db.session.commit()

    emit_order_change_request_created(change_request)

    return change_request, "requested"


def mark_played(order_id: int, kj):
    """
    ЗАМЕНЯЕТ старую complete_order() (запрос пользователя 2026-09-30:
    "никаких Готово не надо, это убрать вообще" — а затем в том же
    разговоре уточнение: кнопка на карточке заказа всё равно нужна, просто
    она больше не должна трогать деньги). Раньше кнопка "Готово" была
    только у VIP-заказов и сразу же списывала деньги (billing_service.
    charge_at_completion). Теперь кнопка доступна у ЛЮБОГО заказа (и VIP, и
    обычного) и делает только одно — переводит заказ в STATUS_PLAYING,
    освобождая место на карточке стола (services/table_board_service.py::
    ACTIVE_TABLE_STATUSES этот статус сознательно не включает, как раньше
    не включал и STATUS_COMPLETED). Деньги здесь нигде не списываются — весь
    расчёт (и с VIP, и с обычных гостей) происходит одной суммой при
    закрытии стола (services/table_close_service.py::complete_table_orders
    сама вызывает billing_service.charge_at_completion по всем ещё не
    отклонённым заказам разом).

    STATUS_PLAYING и playing_at существовали в модели заранее (задел под
    автоматическое распознавание сыгранной песни по истории VirtualDJ, ТЗ
    §37-38, пока не реализовано) — это первое место, где они реально
    используются. completion_source="manual" — как и раньше в старой
    complete_order, "automatic" зарезервировано под будущий мост.

    "Вернуть" (передумать до закрытия стола, запрос пользователя
    2026-09-30 — например, мост или сам KJ ошибся): песню, уже отмеченную
    сыгранной, можно вернуть обратно кнопкой на карточке САМОГО СТОЛА — см.
    reject_order() ниже, она теперь принимает в том числе и STATUS_PLAYING.
    По сути это то же самое "убрать эту песню из будущего чека", что и
    обычное отклонение, просто с другого места экрана.

    Возвращает (order, outcome), где outcome — один из:
        "not_found", "forbidden", "conflict", "played"
    """
    order = db.session.get(Order, order_id)
    if order is None:
        return None, "not_found"

    if order.club_id != kj.club_id:
        return None, "forbidden"

    updated_rows = (
        db.session.query(Order)
        .filter(Order.id == order_id, Order.status == STATUS_QUEUED)
        .update(
            {
                "status": STATUS_PLAYING,
                "playing_at": _utcnow(),
                "completion_source": "manual",
            },
            synchronize_session=False,
        )
    )
    db.session.commit()

    if updated_rows == 0:
        db.session.refresh(order)
        return order, "conflict"

    db.session.refresh(order)
    # ДОБАВЛЕНО (2026-10, запрос пользователя): нажатое "Готово" убирает песню
    # из живой очереди KJ и гостя, даже если в VirtualDJ она ещё стоит — та же
    # метка, что и при закрытии стола (см. _merged_live_queue).
    if order.vdj_item_id and not order.vdj_item_id.startswith("closed:"):
        order.vdj_item_id = f"closed:{int(_utcnow().timestamp())}:{order.vdj_item_id}"[:255]
        db.session.commit()
        db.session.refresh(order)
    emit_order_updated(order)

    return order, "played"


def close_table_orders(club_id: int, table_no: int):
    """
    Запрос пользователя 2026-09-19 ("Закрыть стол" из карточки гостя, когда
    компания встала и ушла, а на карточке стола ещё висят непроигранные
    заказы): массово отклоняет ВСЕ ещё активные заказы этого стола — тот
    же набор статусов, что занимает место на табло (см.
    services/table_board_service.py::ACTIVE_TABLE_STATUSES) —
    STATUS_PENDING/STATUS_PROCESSING/STATUS_QUEUED/STATUS_ERROR.

    Стол — общий физический ресурс: закрываются заказы ВСЕХ гостей этого
    стола, а не только того, чью карточку открыли (за столом могла сидеть
    компания из нескольких аккаунтов). Ничего не списывает — деньги
    (charge_at_completion) начисляются только за реально сыгранную и
    отмеченную "Готово" песню, а не за отменённые из-за ухода гостей.

    Возвращает список фактически затронутых Order (для сокет-уведомлений).
    """
    orders = (
        Order.query
        .filter(
            Order.club_id == club_id,
            Order.table_no == table_no,
            Order.status.in_([STATUS_PENDING, STATUS_PROCESSING, STATUS_QUEUED, STATUS_ERROR]),
        )
        .all()
    )
    if not orders:
        return []

    order_ids = [order.id for order in orders]
    db.session.query(Order).filter(Order.id.in_(order_ids)).update(
        {"status": STATUS_REJECTED, "rejected_at": _utcnow()},
        synchronize_session=False,
    )
    db.session.commit()

    for order in orders:
        db.session.refresh(order)
        emit_order_rejected(order)

    return orders


def close_guest_orders(club_id: int, guest_id: int):
    """
    ДОБАВЛЕНО (2026-10, запрос пользователя: "если гость ушёл — песни
    автоудаляются, очередь перестраивается"): гость встал из-за стола (сам,
    его снял админ стола или KJ) — все его ещё не спетые заказы отклоняются
    и сразу скрываются из живой очереди, даже если песня ещё стоит в
    VirtualDJ (та же метка "closed:", что и при закрытии стола). Деньги не
    списываются, уже спетое не трогается.
    """
    orders = (
        Order.query
        .filter(
            Order.club_id == club_id,
            Order.telegram_user_id == guest_id,
            Order.status.in_([STATUS_PENDING, STATUS_PROCESSING, STATUS_QUEUED, STATUS_ERROR]),
        )
        .all()
    )
    if not orders:
        return []
    now = _utcnow()
    for order in orders:
        order.status = STATUS_REJECTED
        order.rejected_at = now
        if order.vdj_item_id and not order.vdj_item_id.startswith("closed:"):
            order.vdj_item_id = f"closed:{int(now.timestamp())}:{order.vdj_item_id}"[:255]
    db.session.commit()

    for order in orders:
        db.session.refresh(order)
        emit_order_rejected(order)

    return orders


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
    Матрица правил замены песни — ПЕРЕСМОТРЕНА 2026-09-20 (жалоба
    пользователя: "нет возможности удалить / заменить / сменить категорию" —
    у гостя на карточке заказа в статусе "🎶 В очереди" кнопки "Заменить"
    не было вообще).

    Старая (согласованная ранее) матрица опиралась на позицию заказа в
    ЖИВОЙ очереди VirtualDJ:

        STATUS_PENDING                          -> можно
        STATUS_PROCESSING                        -> нельзя
        STATUS_QUEUED, rank 1 или 2 в vdj.get_queue() -> нельзя
        STATUS_QUEUED, rank >= 3                  -> можно
        STATUS_QUEUED, vdj_item_id не в очереди   -> нельзя
        STATUS_PLAYING/COMPLETED/REJECTED/ERROR   -> нельзя

    Но с 2026-09-18 confirm_order() перестала сама передавать принятый заказ
    в VirtualDJ (см. её докстринг) — STATUS_QUEUED теперь означает только
    "KJ принял заказ", а vdj_item_id у такого заказа НИКОГДА не
    проставляется. Из-за этого старая проверка ранга превратилась в
    "нельзя всегда" — ни один реально принятый заказ больше не мог пройти
    её, что и вызвало жалобу. Новая, подтверждённая пользователем матрица:

        STATUS_PENDING   -> можно
        STATUS_PROCESSING -> нельзя (короткое переходное состояние)
        STATUS_QUEUED     -> можно (гость может менять песню/исполнителя/
            категорию весь срок, пока заказ ждёт исполнения — вплоть до
            момента, когда KJ нажмёт "Готово")
        STATUS_PLAYING/COMPLETED/REJECTED/ERROR -> нельзя (заказ уже
            завершил свой жизненный цикл)

    Параметр vdj сохранён ради обратной совместимости вызовов (routes/guest.py,
    replace_order ниже) — сверка с живой очередью VirtualDJ здесь больше не
    нужна и не выполняется.
    """
    return order.status in (STATUS_PENDING, STATUS_QUEUED)


def request_order_replace(order_id: int, guest_id: int, club_id: int, song_title: str, artist, service_id):
    """
    ПЕРЕСМОТРЕНО 2026-09-20 — та же смена модели, что и у request_order_cancel
    выше (решение пользователя "Нужно одобрение KJ"): эта функция раньше
    называлась replace_order и меняла song_title/artist/service_id заказа
    НЕМЕДЛЕННО. Теперь она только заводит заявку (OrderChangeRequest,
    kind="replace", new_song_title/new_artist/new_service_id) — реальная
    замена происходит в approve_order_change_request() ниже, когда KJ
    нажимает "Одобрить". Согласованная и утверждённая пользователем
    спецификация самого действия не изменилась:
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
      - лимита на количество заявок на замену нет (лимит есть только на
        число ОДНОВРЕМЕННО НЕРАЗОБРАННЫХ заявок по одному заказу — см.
        "already_pending" ниже).

    service_id проверяется уже здесь, при создании заявки (а не только
    при одобрении) — чтобы гость сразу узнал о несуществующей категории, а
    не только когда KJ решит одобрить заявку через неопределённое время
    (see approve_order_change_request про повторную проверку "не устарело
    ли" при одобрении).

    Возвращает (change_request, outcome), где outcome — один из:
        "not_found", "forbidden", "not_allowed", "service_not_found",
        "already_pending", "requested"
    """
    order = db.session.get(Order, order_id)
    if order is None:
        return None, "not_found"

    if order.club_id != club_id or order.telegram_user_id != guest_id:
        return None, "forbidden"

    vdj = get_vdj_client(order.club_id)
    if not can_replace_order(order, vdj):
        return None, "not_allowed"

    if service_id is not None:
        service = db.session.get(Service, service_id)
        # kj_only (решение пользователя 2026-09-29: категорию "Bonus" может
        # применить только KJ) — гость не должен получить её и через заявку
        # на замену песни, а не только через обычный create_order.
        if service is None or service.club_id != club_id or service.kj_only:
            return None, "service_not_found"

    existing = get_pending_change_request(order_id)
    if existing is not None:
        return existing, "already_pending"

    change_request = OrderChangeRequest(
        club_id=club_id,
        order_id=order_id,
        guest_id=guest_id,
        kind=ORDER_CHANGE_KIND_REPLACE,
        new_song_title=song_title,
        new_artist=artist,
        new_service_id=service_id,
    )
    db.session.add(change_request)
    db.session.commit()

    emit_order_change_request_created(change_request)

    return change_request, "requested"


def approve_order_change_request(request_id: int, kj):
    """
    KJ одобряет заявку гостя на отмену/замену (см. request_order_cancel/
    request_order_replace выше и решение пользователя в докстринге
    models.OrderChangeRequest). Здесь, а не в самой заявке, происходит
    реальное изменение Order — ровно та логика, что раньше выполняли
    немедленно cancel_order_by_guest/replace_order.

    Заказ повторно проверяется на актуальность ("ещё подходит?") прямо
    перед применением, а не полагается на то, что было верно в момент
    подачи заявки — между подачей и решением KJ могло пройти любое время, и
    за него заказ мог, например, уже сыграть (STATUS_COMPLETED) или
    попасть в обработку (STATUS_PROCESSING). Если это произошло — заявка
    автоматически помечается отклонённой (outcome "stale"), а не тихо
    применяется к уже неподходящему заказу.

    Возвращает (change_request, order, outcome), где outcome — один из:
        "not_found", "forbidden", "already_decided", "stale", "approved"
    order — None при "not_found"/"forbidden"/"already_decided", иначе сам
    (возможно изменённый) Order.
    """
    change_request = db.session.get(OrderChangeRequest, request_id)
    if change_request is None:
        return None, None, "not_found"

    if change_request.club_id != kj.club_id:
        return None, None, "forbidden"

    if change_request.status != STATUS_ORDER_CHANGE_PENDING:
        return change_request, None, "already_decided"

    order = db.session.get(Order, change_request.order_id)
    if order is None:
        change_request.status = STATUS_ORDER_CHANGE_REJECTED
        change_request.decided_by = kj.id
        change_request.decided_at = _utcnow()
        db.session.commit()
        emit_order_change_request_decided(change_request)
        return change_request, None, "stale"

    if change_request.kind == ORDER_CHANGE_KIND_CANCEL:
        still_eligible = order.status in CANCELABLE_BY_GUEST_STATUSES
    else:
        vdj = get_vdj_client(order.club_id)
        still_eligible = can_replace_order(order, vdj)

    if not still_eligible:
        change_request.status = STATUS_ORDER_CHANGE_REJECTED
        change_request.decided_by = kj.id
        change_request.decided_at = _utcnow()
        db.session.commit()
        emit_order_change_request_decided(change_request)
        return change_request, order, "stale"

    if change_request.kind == ORDER_CHANGE_KIND_CANCEL:
        order.status = STATUS_REJECTED
        order.rejected_at = _utcnow()
        db.session.commit()
        db.session.refresh(order)
        emit_order_rejected(order)
    else:
        order.song_title = change_request.new_song_title
        order.artist = change_request.new_artist
        order.service_id = change_request.new_service_id
        db.session.commit()
        emit_order_updated(order)

    change_request.status = STATUS_ORDER_CHANGE_APPROVED
    change_request.decided_by = kj.id
    change_request.decided_at = _utcnow()
    db.session.commit()
    emit_order_change_request_decided(change_request)

    return change_request, order, "approved"


def reject_order_change_request(request_id: int, kj):
    """
    KJ отклоняет заявку гостя на отмену/замену — заказ остаётся как был,
    ничего в нём не меняется (в отличие от approve_order_change_request
    выше). Возвращает (change_request, outcome), где outcome — один из:
        "not_found", "forbidden", "already_decided", "rejected"
    """
    change_request = db.session.get(OrderChangeRequest, request_id)
    if change_request is None:
        return None, "not_found"

    if change_request.club_id != kj.club_id:
        return None, "forbidden"

    if change_request.status != STATUS_ORDER_CHANGE_PENDING:
        return change_request, "already_decided"

    change_request.status = STATUS_ORDER_CHANGE_REJECTED
    change_request.decided_by = kj.id
    change_request.decided_at = _utcnow()
    db.session.commit()
    emit_order_change_request_decided(change_request)

    return change_request, "rejected"


def list_pending_change_requests(club_id: int) -> list[OrderChangeRequest]:
    """Все неразобранные заявки клуба — KJ Panel, панель "🔔 Заявки от
    гостей" (см. routes/kj.py::list_order_change_requests)."""
    return (
        OrderChangeRequest.query
        .filter_by(club_id=club_id, status=STATUS_ORDER_CHANGE_PENDING)
        .order_by(OrderChangeRequest.created_at.asc())
        .all()
    )


def remove_from_vdj_queue(club_id: int, vdj_item_id: str):
    """ТЗ п.20 + доп. ТЗ "KJ Pro" (запрос пользователя убрать песню прямо с
    экрана "Живая очередь VirtualDJ"): удаление уже добавленного в очередь
    VirtualDJ элемента — отдельная операция от отклонения ещё не переданного
    заказа (reject_order выше).

    club_id обязателен по той же причине, что и в confirm_order(): в режиме
    VDJ_ADAPTER=bridge команду нужно адресовать мосту конкретного клуба,
    а не какому попало.

    Если этому элементу очереди соответствует заказ (сопоставление по
    club_id+vdj_item_id, тем же способом, что и в get_kj_queue_view() ниже,
    и только пока он ещё STATUS_QUEUED) — переводит его в STATUS_REJECTED.
    Отдельного возврата денег, в отличие от старого бота
    (handlers/kj.py::order_delete_confirmed -> db.refund_vip_for_order()),
    здесь не требуется: в новой архитектуре списание происходит только при
    ЗАВЕРШЕНИИ песни (services/billing_service.py::charge_at_completion), а
    удалённая из очереди песня никогда не будет завершена — значит, с неё и
    так ничего не спишется. Если соответствующего заказа не нашлось (песню
    добавили прямо в VirtualDJ, минуя Backend) — просто ничего, кроме самой
    VirtualDJ, не трогаем.

    Возвращает найденный Order (или None, если его не было) — вызывающему
    коду (routes/vdj.py) он не обязателен, но полезен для ответа фронтенду.

    ВАЖНО про "потерянные" (orphaned) заказы (см. докстринг get_kj_queue_view
    про то, откуда они берутся — например, старые записи ещё из тестового
    mock-режима, у которых vdj_item_id никогда не существовал в настоящей
    VirtualDJ): если такой позиции уже и так нет в живой очереди VirtualDJ —
    физически удалять там нечего, поэтому vdj.remove_from_queue() вообще не
    вызывается. Раньше он вызывался всегда, и для настоящего VirtualDJ
    (NetworkControlVDJDriver, удаление по ID не поддерживается вообще, см.
    его докстринг) это гарантированно проваливалось с ошибкой — хотя удалять
    было нечего с самого начала (живой инцидент 2026-09-14: старые заказы
    "mock-3"/"mock-4" из тестового режима не давали себя убрать после
    включения настоящей VirtualDJ). Если же позиция всё ещё правда стоит в
    очереди — вызов идёт как раньше, и для настоящего VirtualDJ он по-прежнему
    может закончиться отказом (удаление там остаётся ручным действием KJ
    прямо в VirtualDJ — это согласовано с пользователем отдельно, не баг).
    """
    vdj = get_vdj_client(club_id)

    live_queue = vdj.get_queue()
    still_in_vdj = any(
        item.vdj_item_id
        and (item.vdj_item_id == vdj_item_id or vdj_item_id.endswith(item.vdj_item_id))
        for item in live_queue
    )
    if still_in_vdj:
        vdj.remove_from_queue(vdj_item_id)

    order = (
        Order.query.filter_by(club_id=club_id, vdj_item_id=vdj_item_id, status=STATUS_QUEUED).first()
    )
    if order is not None:
        order.status = STATUS_REJECTED
        order.rejected_at = _utcnow()
        db.session.commit()
        emit_order_rejected(order)

        if order.channel == "telegram":
            song_line = f"{order.artist} — {order.song_title}" if order.artist else order.song_title
            notify_guest(order.telegram_user_id, f"❌ Ваша песня удалена из очереди KJ.\n\n🎵 {song_line}")

    emit_queue_updated(club_id, get_kj_queue_view(club_id))
    return order


def update_order_table(order_id: int, kj, table_no):
    """
    Доп. ТЗ "KJ Pro": смена номера стола у песни, уже стоящей в очереди —
    экран "Живая очередь VirtualDJ" (запрос пользователя после того, как
    выяснилось, что стол мог быть указан неверно уже постфактум). Сам
    VirtualDJ номер стола не хранит вообще (см. докстринг get_kj_queue_view
    ниже) — это чисто поле нашего Order.table_no, поэтому смена не требует
    никакого обращения к VirtualDJ, только запись в базу.

    Разрешено только пока заказ ещё STATUS_QUEUED — эта функция вызывается
    только с экрана живой очереди, где показываются именно такие заказы.

    Возвращает (order, outcome), где outcome — один из:
        "not_found", "forbidden", "not_queued", "updated"
    """
    order = db.session.get(Order, order_id)
    if order is None:
        return None, "not_found"
    if order.club_id != kj.club_id:
        return None, "forbidden"
    if order.status != STATUS_QUEUED:
        return order, "not_queued"

    order.table_no = table_no
    db.session.commit()
    emit_order_updated(order)
    emit_queue_updated(order.club_id, get_kj_queue_view(order.club_id))
    return order, "updated"


def update_order_category(order_id: int, kj, service_id):
    """
    Доп. ТЗ "KJ Pro": назначение/смена категории (Service, см. её докстринг в
    models.py) у песни, уже стоящей в очереди. До этого ни один эндпоинт
    заказа не проставлял service_id вообще (см. комментарий у
    Order.service_id в models.py) — это первое место, где KJ может сделать
    это сам, вручную, для уже поставленной в очередь песни.

    Тот же набор outcome, что и у update_order_table() выше, плюс
    "service_not_found", если указанная категория не существует или
    принадлежит другому клубу.
    """
    order = db.session.get(Order, order_id)
    if order is None:
        return None, "not_found"
    if order.club_id != kj.club_id:
        return None, "forbidden"
    if order.status != STATUS_QUEUED:
        return order, "not_queued"

    if service_id is not None:
        service = db.session.get(Service, service_id)
        if service is None or service.club_id != kj.club_id:
            return order, "service_not_found"

    order.service_id = service_id
    db.session.commit()
    emit_order_updated(order)
    emit_queue_updated(order.club_id, get_kj_queue_view(order.club_id))
    return order, "updated"


def _norm_song_name(value) -> str:
    return " ".join((value or "").lower().replace("ё", "е").split())


def _order_matches_vdj_item(order, item) -> bool:
    """
    Одна и та же песня? Сравнение названия заказа с позицией VirtualDJ без
    учёта регистра, лишних пробелов и "ё/е". Исполнитель сравнивается,
    только если он указан с обеих сторон; также учитывается, что VirtualDJ
    или гость могли записать "исполнитель - название" одной строкой.
    """
    order_title = _norm_song_name(order.song_title)
    order_artist = _norm_song_name(order.artist)
    item_title = _norm_song_name(item.song_title)
    item_artist = _norm_song_name(item.artist)
    if not order_title or not item_title:
        return False
    if order_title == item_title and (not order_artist or not item_artist or order_artist == item_artist):
        return True
    # Исполнитель записан по-разному ("Барских Макс" / "Макс Барских",
    # "Тишман" / "Марк Тишман"): считаем совпадением, если слова одного
    # варианта целиком входят в другой, в любом порядке.
    if order_title == item_title and order_artist and item_artist:
        order_words = set(order_artist.replace(",", " ").split())
        item_words = set(item_artist.replace(",", " ").split())
        if order_words and item_words and (order_words <= item_words or item_words <= order_words):
            return True
    if item_artist and order_title in (
        f"{item_artist} - {item_title}", f"{item_artist} — {item_title}",
        f"{item_title} - {item_artist}", f"{item_title} — {item_artist}",
    ):
        return True
    if order_artist and item_title in (
        f"{order_artist} - {order_title}", f"{order_artist} — {order_title}",
        f"{order_title} - {order_artist}", f"{order_title} — {order_artist}",
    ):
        return True
    return False


def _remember_guest_song_text(order) -> None:
    """Сохраняет исходный текст гостя один раз — перед первой сменой названия."""
    if order.guest_song_text is None:
        order.guest_song_text = f"{order.artist} — {order.song_title}" if order.artist else order.song_title


# ДОБАВЛЕНО (2026-10, запрос пользователя): автонажатие "Готово" по истории
# VirtualDJ. Песня попадает в историю, когда проиграла столько, сколько задано
# в настройках VirtualDJ (у клуба — 1 минута); мост на компьютере KJ читает
# файл истории, а здесь заказ с тем же файлом отмечается сыгранным сам.
_HISTORY_NEXT_CHECK: dict = {}
_HISTORY_INTERVAL_OK = 10      # секунд между опросами истории
_HISTORY_INTERVAL_FAIL = 120   # мост не ответил/старый — не дёргаем часто


def _norm_path(value) -> str:
    return (value or "").replace("/", "\\").strip().lower()


def _auto_complete_from_history(club_id: int, vdj) -> None:
    now = _utcnow()
    next_check = _HISTORY_NEXT_CHECK.get(club_id)
    if next_check is not None and now < next_check:
        return
    candidates = (
        db.session.query(Order)
        .filter(
            Order.club_id == club_id,
            Order.status == STATUS_QUEUED,
            Order.vdj_item_id.isnot(None),
        )
        .all()
    )
    candidates = [o for o in candidates if not (o.vdj_item_id or "").startswith("closed:")]
    if not candidates:
        _HISTORY_NEXT_CHECK[club_id] = now + timedelta(seconds=_HISTORY_INTERVAL_OK)
        return
    try:
        history = vdj.get_history()
    except Exception:  # мост не обновлён или не ответил — это не ошибка для KJ
        _HISTORY_NEXT_CHECK[club_id] = now + timedelta(seconds=_HISTORY_INTERVAL_FAIL)
        return
    _HISTORY_NEXT_CHECK[club_id] = now + timedelta(seconds=_HISTORY_INTERVAL_OK)

    played = []
    for entry in history or []:
        if not isinstance(entry, dict):
            continue
        path = _norm_path(entry.get("filepath"))
        try:
            played_at = float(entry.get("played_at"))
        except (TypeError, ValueError):
            continue
        if path:
            played.append((path, played_at))
    if not played:
        return

    changed = []
    for order in candidates:
        wanted = _norm_path(order.vdj_item_id)
        if not wanted:
            continue
        accepted_at = order.queued_at or order.confirmed_at or order.created_at
        accepted_ts = accepted_at.timestamp() if accepted_at else 0
        if any((path == wanted or path.endswith(wanted)) and played_at >= accepted_ts for path, played_at in played):
            order.status = STATUS_PLAYING
            order.playing_at = now
            order.completion_source = "history"
            order.vdj_item_id = f"closed:{int(now.timestamp())}:{order.vdj_item_id}"[:255]
            changed.append(order)
    if changed:
        db.session.commit()
        for order in changed:
            emit_order_updated(order)


def _merged_live_queue(club_id: int, persist: bool):
    """
    Общая основа живой очереди для KJ Panel и Guest App (запрос пользователя
    2026-10: "Принять" должно сразу отправлять песню в живую очередь, а
    заказ гостя "cvecha" и песня "Свеча", которую KJ сам поставил в
    VirtualDJ, после переименования должны стать одной строкой).

    Возвращает (rows, waiting):
      rows    — [(позиция VirtualDJ, заказ или None)] в порядке VirtualDJ;
      waiting — принятые заказы (STATUS_QUEUED), которых в VirtualDJ нет.

    Слияние: сначала по уже сохранённой связи (Order.vdj_item_id), затем —
    для ещё "ничьих" позиций VirtualDJ — по совпадению названия
    (_order_matches_vdj_item). persist=True (вызовы со стороны KJ) сохраняет
    найденную связь в заказе; persist=False (Guest App) только показывает.

    Заказ, чья позиция из VirtualDJ исчезла (песня отыграна/убрана в самом
    VirtualDJ или мост переподключился): заказ, созданный KJ из позиции
    VirtualDJ (source="virtualdj"), снимается, как и раньше; заказ гостя или
    ручной заказ KJ НЕ снимается — он просто снова считается "нет в
    VirtualDJ" и остаётся в очереди, пока KJ сам не отметит его сыгранным
    или не уберёт (иначе спетая песня пропадала бы из чека стола).
    """
    vdj = get_vdj_client(club_id)
    if persist:
        try:
            _auto_complete_from_history(club_id, vdj)
        except Exception:  # автонажатие не должно ломать показ очереди
            db.session.rollback()
    live_queue = vdj.get_queue()

    # ИЗМЕНЕНО (2026-10): из живой очереди скрываются только песни ЗАКРЫТОГО
    # стола (метка "closed:<время>:<id>" ставится при закрытии стола, см.
    # table_close_service.complete_table_orders) и только 15 минут — за это
    # время KJ успевает убрать их из VirtualDJ. Прежнее правило (любой
    # завершённый заказ за сутки) прятало и заново поставленную ту же песню.
    # ИЗМЕНЕНО (2026-10, запрос пользователя "Готово срабатывает сразу"):
    # песня с меткой скрыта из очереди, пока она стоит в VirtualDJ — без
    # ограничения по времени. Как только её убрали из VirtualDJ, метка
    # снимается, и та же песня, поставленная позже заново, показывается.
    hidden_ids = []
    released = False
    for marked_order in (
        db.session.query(Order)
        .filter(
            Order.club_id == club_id,
            Order.status.in_((STATUS_COMPLETED, STATUS_PLAYING, STATUS_REJECTED)),
            Order.vdj_item_id.like("closed:%"),
        )
        .all()
    ):
        parts = (marked_order.vdj_item_id or "").split(":", 2)
        hid = parts[2] if len(parts) == 3 else ""
        still_in_vdj = bool(hid) and any(
            item.vdj_item_id and (item.vdj_item_id == hid or item.vdj_item_id.endswith(hid))
            for item in live_queue
        )
        if still_in_vdj:
            hidden_ids.append(hid)
        elif persist:
            marked_order.vdj_item_id = None
            released = True
    if released:
        db.session.commit()
    if hidden_ids:
        live_queue = [
            item
            for item in live_queue
            if not (
                item.vdj_item_id
                and any(item.vdj_item_id == hid or item.vdj_item_id.endswith(hid) for hid in hidden_ids)
            )
        ]

    linked_orders = (
        db.session.query(Order)
        .filter(
            Order.club_id == club_id,
            Order.status == STATUS_QUEUED,
            Order.vdj_item_id.isnot(None),
        )
        .order_by(Order.queued_at.asc())
        .all()
    )
    waiting = (
        db.session.query(Order)
        .filter(
            Order.club_id == club_id,
            Order.status == STATUS_QUEUED,
            Order.vdj_item_id.is_(None),
        )
        .order_by(Order.queued_at.asc(), Order.id.asc())
        .all()
    )

    rows = []
    for item in live_queue:
        matched = None
        if item.vdj_item_id:
            for order in linked_orders:
                if order.vdj_item_id == item.vdj_item_id or item.vdj_item_id.endswith(order.vdj_item_id):
                    matched = order
                    break
            if matched is not None:
                linked_orders.remove(matched)
        rows.append([item, matched])

    changed = False
    for order in linked_orders:
        if order.source == "virtualdj":
            if persist:
                order.status = STATUS_REJECTED
                order.rejected_at = _utcnow()
                changed = True
        else:
            if persist:
                order.vdj_item_id = None
                changed = True
            waiting.append(order)

    for row in rows:
        item, matched = row
        if matched is not None or not item.vdj_item_id:
            continue
        for order in waiting:
            if _order_matches_vdj_item(order, item):
                row[1] = order
                waiting.remove(order)
                if persist:
                    order.vdj_item_id = item.vdj_item_id
                    changed = True
                break

    if changed:
        db.session.commit()

    # ИЗМЕНЕНО (2026-10, запрос пользователя): в режиме "Последовательно"
    # принятые заказы, которых нет в VirtualDJ, выстраиваются по кругу столов
    # от стола "Начало очереди" — так же, как номера на карточках столов.
    # В режиме "Как решает диджей" порядок прежний — по времени принятия.
    positions = {}
    try:
        from services import table_board_service  # ленивый импорт: иначе круговая зависимость

        club = db.session.get(table_board_service.Club, club_id)
        if club is not None and (
            table_board_service.get_queue_mode(club) == table_board_service.QUEUE_MODE_SEQUENTIAL
        ):
            positions = table_board_service.get_club_queue_positions(club_id)
    except Exception:  # порядок — не повод ронять показ очереди
        positions = {}
    waiting.sort(key=lambda o: (positions.get(o.id, 10**9), o.queued_at or o.created_at, o.id))
    _SEQ_POSITIONS[club_id] = positions
    return [(item, matched) for item, matched in rows], waiting


# ДОБАВЛЕНО (2026-10, запрос пользователя: "сначала песни стола 2, потом 10" при
# начале очереди со стола 11): в режиме "Последовательно" по кругу столов
# выстраиваются ВСЕ заказы — и те, что уже стоят в VirtualDJ. Песни из
# VirtualDJ без заказа (их поставил сам диджей) остаются сверху, как были.
_SEQ_POSITIONS: dict = {}


def _apply_table_round(club_id: int, entries: list) -> list[dict]:
    """entries — [(order_id или None, строка очереди)] в исходном порядке."""
    positions = _SEQ_POSITIONS.get(club_id) or {}
    if not positions:
        return [row for _order_id, row in entries]
    indexed = list(enumerate(entries))
    indexed.sort(
        key=lambda pair: (
            (0, 0, pair[0]) if pair[1][0] is None
            else (1, positions.get(pair[1][0], 10**9), pair[0])
        )
    )
    return [row for _index, (_order_id, row) in indexed]


def rename_order(order_id: int, kj, song_title: str, artist):
    """
    KJ исправляет название песни в заказе на точное (как в VirtualDJ) —
    кнопка "✏️ Название" в живой очереди. Исходный текст гостя сохраняется
    в guest_song_text. Если после этого название совпало с "ничьей"
    позицией VirtualDJ — они сольются при пересборке очереди ниже.
    Возвращает (order, outcome): not_found | forbidden | not_allowed | ok.
    """
    order = db.session.get(Order, order_id)
    if order is None:
        return None, "not_found"
    if order.club_id != kj.club_id:
        return None, "forbidden"
    if order.status not in (STATUS_PENDING, STATUS_QUEUED):
        return order, "not_allowed"

    _remember_guest_song_text(order)
    order.song_title = song_title
    order.artist = artist or None
    db.session.commit()

    emit_order_updated(order)
    emit_queue_updated(kj.club_id, get_kj_queue_view(kj.club_id))
    db.session.refresh(order)
    return order, "ok"


def link_order_to_vdj_item(order_id: int, kj, vdj_item_id: str):
    """
    Кнопка "🔗 Это одна песня": KJ вручную указывает, что принятый заказ и
    позиция VirtualDJ — одна и та же песня. Заказ получает точное название
    из VirtualDJ (исходный текст гостя сохраняется) и связь с позицией.
    Возвращает (order, outcome): not_found | forbidden | not_allowed |
    vdj_error | item_not_found | already_linked | ok.
    """
    order = db.session.get(Order, order_id)
    if order is None:
        return None, "not_found"
    if order.club_id != kj.club_id:
        return None, "forbidden"
    if order.status != STATUS_QUEUED:
        return order, "not_allowed"

    vdj = get_vdj_client(kj.club_id)
    try:
        live_queue = vdj.get_queue()
    except VirtualDJError:
        return order, "vdj_error"
    item = next((i for i in live_queue if i.vdj_item_id and i.vdj_item_id == vdj_item_id), None)
    if item is None:
        return order, "item_not_found"

    taken = (
        Order.query
        .filter(
            Order.club_id == kj.club_id,
            Order.status == STATUS_QUEUED,
            Order.vdj_item_id == vdj_item_id,
            Order.id != order.id,
        )
        .first()
    )
    if taken is not None:
        return order, "already_linked"

    _remember_guest_song_text(order)
    if item.song_title:
        order.song_title = item.song_title
    if item.artist:
        order.artist = item.artist
    order.vdj_item_id = vdj_item_id
    db.session.commit()

    emit_order_updated(order)
    emit_queue_updated(kj.club_id, get_kj_queue_view(kj.club_id))
    db.session.refresh(order)
    return order, "ok"


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

    Обратный случай — заказ в базе всё ещё STATUS_QUEUED, но его
    vdj_item_id уже не встречается в живой очереди VirtualDJ вообще (после
    того, как unused_orders разобраны выше, здесь остаются именно такие) —
    "потерянный" заказ. В тестовом режиме (VDJ_ADAPTER=mock) это возникает
    при каждом перезапуске Backend: очередь mock-клиента хранится в памяти
    процесса (vdj/mock_client.py) и обнуляется, а STATUS_QUEUED в постоянной
    базе — нет (живой пример: пользователь столкнулся с этим 2026-09-14,
    после нескольких перезапусков во время загрузки файлов гость упёрся в
    лимит "не более 2 заказов одновременно" из-за пары таких заказов). В
    реальном VirtualDJ то же самое возможно при разрыве и переподключении
    моста. Раньше такие заказы нигде не показывались и KJ не мог их снять —
    добавляем их в конец списка с order_id (он есть) и пометкой
    "orphaned": true, чтобы уже существующая кнопка "Удалить" в KJ Pro (см.
    remove_from_vdj_queue выше — она ищет заказ по vdj_item_id независимо от
    того, жив ли он в самом VirtualDJ) могла закрыть и их тоже.

    2026-09-18, запрос пользователя: confirm_order() больше не передаёт
    песню в VirtualDJ сама — такой STATUS_QUEUED-заказ рождается сразу без
    vdj_item_id (он остаётся пустым навсегда, пока KJ явно не нажмёт
    "Готово", см. mark_played()). Без явного исключения такие заказы
    выше просто никогда бы не нашли себе пару в live_queue (не с чем
    сравнивать) и на следующей же строчке ниже были бы молча объявлены
    "потерянными" и отклонены — притом что песню никто никуда не терял, KJ
    просто ещё не успел поставить её в плеер вручную. Поэтому такие заказы
    здесь целиком исключены из рассмотрения: их жизненным циклом теперь
    управляет только явное действие KJ (кнопка "Готово"), а не сверка с
    живой очередью VirtualDJ.
    """
    # ИЗМЕНЕНО (2026-10, запрос пользователя): живая очередь теперь — это
    # позиции VirtualDJ ПЛЮС принятые заказы, которых в VirtualDJ ещё нет
    # (in_vdj=False). Заказ и позиция VirtualDJ с одинаковым названием
    # сливаются в одну строку автоматически — см. _merged_live_queue().
    rows, waiting = _merged_live_queue(club_id, persist=True)

    result = []
    for item, matched in rows:
        result.append(
            {
                "vdj_item_id": item.vdj_item_id,
                "song_title": item.song_title,
                "artist": item.artist,
                "table_no": matched.table_no if matched else None,
                "order_id": matched.id if matched else None,
                "service_id": matched.service_id if matched else None,
                "orphaned": False,
                "in_vdj": True,
                "guest_song_text": matched.guest_song_text if matched else None,
                "tone": matched.tone if matched else None,
            }
        )
    for order in waiting:
        result.append(
            {
                "vdj_item_id": None,
                "song_title": order.song_title,
                "artist": order.artist,
                "table_no": order.table_no,
                "order_id": order.id,
                "service_id": order.service_id,
                "orphaned": False,
                "in_vdj": False,
                "guest_song_text": order.guest_song_text,
                "tone": order.tone,
            }
        )
    return _apply_table_round(club_id, [(row["order_id"], row) for row in result])


def get_guest_queue_view(club_id: int, guest_id: int) -> list[dict]:
    """
    Живая очередь VirtualDJ для Guest App — то же сопоставление с Order по
    vdj_item_id, что и в get_kj_queue_view() выше (см. её докстринг про
    "равно или заканчивается на" и разбор дублей среди одинаковых песен в
    очереди), но без раскрытия самих заказов гостю — только три признака
    для подсветки в интерфейсе (запрос пользователя, 2026-10): is_vip
    (заказ оформлен VIP-гостем — Order.guest_type, проставляется при
    создании заказа), is_mine (это заказ самого гостя, который сейчас
    смотрит очередь — сравнение с Order.telegram_user_id, см. require_guest
    в auth.py про то, что это то же значение, что и g.guest_id) и is_crazy
    (заказ оформлен с платной категорией "Крейзи" — своего флага у
    категории нет, поэтому определяется по названию Service, т.к. набор
    категорий у каждого клуба свой и задаётся KJ/админом вручную).

    Сознательно не трогает unused_orders и не помечает "потерянные" заказы
    STATUS_REJECTED, как это делает get_kj_queue_view() — это обслуживание
    очереди должно происходить только один раз за опрос, и её уже выполняет
    KJ Panel (оба экрана опрашивают один и тот же club_id параллельно).
    """
    # ИЗМЕНЕНО (2026-10): та же объединённая очередь, что и у KJ (позиции
    # VirtualDJ + принятые заказы, которых там ещё нет), но без записи в базу.
    rows, waiting = _merged_live_queue(club_id, persist=False)

    service_names = {
        s.id: (s.name or "")
        for s in db.session.query(Service).filter(Service.club_id == club_id).all()
    }

    def _is_crazy(service_id):
        # Та же категория, что и в services/table_board_service.py::
        # CRAZY_CATEGORY_NAME ("CRAZY" — приоритетная категория, всегда
        # идёт первой в очереди) — сравниваем точно так же, по имени
        # Service, не импортируя константу напрямую, чтобы не создавать
        # цикл импорта (table_board_service уже импортирует из этого файла).
        name = service_names.get(service_id, "").strip()
        return name.upper() == "CRAZY"

    result = []
    order_ids = []
    for item, matched in rows:
        order_ids.append(matched.id if matched else None)
        result.append(
            {
                "key": f"vdj-{item.vdj_item_id}",
                "vdj_item_id": item.vdj_item_id,
                "song_title": item.song_title,
                "artist": item.artist,
                "table_no": matched.table_no if matched else None,
                "is_vip": bool(matched and matched.guest_type == "vip"),
                "is_mine": bool(matched and matched.telegram_user_id == guest_id),
                "is_crazy": bool(matched and _is_crazy(matched.service_id)),
            }
        )
    for order in waiting:
        order_ids.append(order.id)
        result.append(
            {
                "key": f"order-{order.id}",
                "vdj_item_id": None,
                "song_title": order.song_title,
                "artist": order.artist,
                "table_no": order.table_no,
                "is_vip": order.guest_type == "vip",
                "is_mine": order.telegram_user_id == guest_id,
                "is_crazy": _is_crazy(order.service_id),
            }
        )

    result = _apply_table_round(club_id, list(zip(order_ids, result)))

    try:
        _notify_guest_turn_soon(club_id, guest_id, result)
    except Exception:  # уведомление не должно ломать показ очереди
        db.session.rollback()

    return result


# Что уже отправляли (сообщение удаляется через 10 минут, а повторять его нельзя).
_TURN_NOTICE_SENT: dict = {}


def _notify_guest_turn_soon(club_id: int, guest_id: int, queue_view: list[dict]) -> None:
    """
    ДОБАВЛЕНО (2026-10, запрос пользователя): за две песни и за одну песню
    до выхода гостю приходит сообщение в чат с KJ. Каждое — один раз на
    песню (проверка по тексту сообщения за последние 6 часов).
    """
    # Уведомления живут 10 минут, потом удаляются сами (запрос пользователя).
    now = datetime.now(timezone.utc)
    deleted = (
        db.session.query(ChatMessage)
        .filter(
            ChatMessage.club_id == club_id,
            ChatMessage.telegram_user_id == guest_id,
            ChatMessage.from_guest.is_(False),
            db.or_(
                ChatMessage.message_text.like("🎤 Приготовьтесь! До вашей песни%"),
                ChatMessage.message_text.like("🎤 Вы следующий! Ваша песня%"),
            ),
            ChatMessage.created_at < now - timedelta(minutes=10),
        )
        .delete(synchronize_session=False)
    )
    if deleted:
        db.session.commit()
    for key, sent_at in list(_TURN_NOTICE_SENT.items()):
        if sent_at < now - timedelta(hours=6):
            _TURN_NOTICE_SENT.pop(key, None)

    texts = []
    for index, item in enumerate(queue_view):
        if not item.get("is_mine") or index not in (1, 2):
            continue
        title = (item.get("song_title") or "").strip() or "без названия"
        if index == 2:
            texts.append(f"🎤 Приготовьтесь! До вашей песни «{title}» осталось 2 песни.")
        else:
            texts.append(f"🎤 Вы следующий! Ваша песня «{title}» — сразу после этой.")
    if not texts:
        return
    since = datetime.now(timezone.utc) - timedelta(hours=6)
    created = False
    for text in texts:
        exists = (
            db.session.query(ChatMessage.id)
            .filter(
                ChatMessage.club_id == club_id,
                ChatMessage.telegram_user_id == guest_id,
                ChatMessage.from_guest.is_(False),
                ChatMessage.message_text == text,
                ChatMessage.created_at >= since,
            )
            .first()
        )
        if exists or (club_id, guest_id, text) in _TURN_NOTICE_SENT:
            continue
        _TURN_NOTICE_SENT[(club_id, guest_id, text)] = now
        db.session.add(
            ChatMessage(
                club_id=club_id,
                telegram_user_id=guest_id,
                from_guest=False,
                message_text=text,
            )
        )
        created = True
    if created:
        db.session.commit()


def claim_vdj_queue_item(kj, vdj_item_id: str, song_title: str, artist, table_no, service_id):
    """
    Доп. ТЗ "KJ Pro" (запрос пользователя 2026-09-14, после первого живого
    теста с настоящей VirtualDJ: KJ добавил песни прямо в VirtualDJ, они
    появились в живой очереди KJ Pro как позиции "без заказа" — get_kj_
    queue_view() отдаёт их с order_id=None, см. её докстринг). У такой
    позиции просто негде хранить стол/категорию — без Order они относятся
    только к самой VirtualDJ, которая про стол/категорию ничего не знает
    (см. тот же докстринг). "Присвоить" здесь означает: завести для уже
    существующей в VirtualDJ позиции свой Order, НЕ трогая саму VirtualDJ
    (песня там уже есть, add_to_queue не вызывается) — после этого позиция
    перестаёт быть "без заказа" (сопоставляется по vdj_item_id как любой
    другой Order) и дальше её стол/категория меняются уже обычными
    update_order_table()/update_order_category() выше, как у любого другого
    заказа.

    source="virtualdj" — до сих пор только предусмотренное в модели значение
    (см. комментарий у Order.source в models.py: "guest | manual |
    virtualdj"), это первое место, где оно реально проставляется.
    telegram_user_id=-1 и channel="webapp" — та же причина, что и в
    add_manual_song() ниже (не гость, уведомлять некого).

    Не перепроверяет, что vdj_item_id прямо сейчас всё ещё есть в
    vdj.get_queue() — экран KJ Pro и так строит список из свежего вызова
    get_kj_queue_view() непосредственно перед показом кнопки "Присвоить",
    гонка в несколько секунд не критична: если песню за это время уже убрали
    из VirtualDJ вручную, получится тот же случай, что уже существует —
    "потерянный" заказ (см. докстринг get_kj_queue_view), просто с самого
    начала.

    Возвращает (order, outcome), outcome — один из: "already_claimed"
    (для этой позиции уже есть заказ — race двух одновременных нажатий),
    "service_not_found", "claimed".
    """
    existing = Order.query.filter_by(
        club_id=kj.club_id, vdj_item_id=vdj_item_id, status=STATUS_QUEUED
    ).first()
    if existing is not None:
        return existing, "already_claimed"

    if service_id is not None:
        service = db.session.get(Service, service_id)
        if service is None or service.club_id != kj.club_id:
            return None, "service_not_found"

    order = Order(
        telegram_user_id=-1,
        club_id=kj.club_id,
        table_no=table_no,
        song_title=song_title,
        artist=artist,
        status=STATUS_QUEUED,
        source="virtualdj",
        channel="webapp",
        vdj_item_id=vdj_item_id,
        service_id=service_id,
        queued_at=_utcnow(),
        confirmed_by=kj.id,
        confirmed_at=_utcnow(),
    )
    db.session.add(order)
    db.session.commit()

    emit_queue_updated(kj.club_id, get_kj_queue_view(kj.club_id))

    return order, "claimed"


def push_order_to_queue(order_id: int, kj):
    """
    KJ Pro, кнопка "🎵 В очередь VDJ" на уже принятом (STATUS_QUEUED) заказе
    на карточке стола (OrdersBoardSlot) — запрос пользователя 2026-10.

    Раньше единственным способом что-либо добавить в живую очередь
    VirtualDJ был add_manual_song() ниже — он специально создаёт "ничей"
    заказ (telegram_user_id=-1, см. её докстринг), потому что рассчитан на
    случай, когда KJ сам вводит песню с нуля, без заказа гостя вообще.
    confirm_order() же выше принципиально не трогает VirtualDJ сама. В
    результате ни один настоящий заказ гостя не получал vdj_item_id, и
    get_kj_queue_view()/get_guest_queue_view() никогда не находили для живой
    очереди подходящий заказ — значит не могли подсветить ни VIP, ни
    "Крейзи", ни "это моя песня" (жалоба пользователя: "мой заказ не
    подсвечивается зелёным").

    Эта функция — третий путь: берёт УЖЕ существующий настоящий заказ
    гостя и добавляет именно его песню в VirtualDJ, записывая vdj_item_id
    в тот же Order — guest_type/telegram_user_id/service_id остаются от
    настоящего заказа (не трогаем их), поэтому дальше оба queue-view
    находят его и подсвечивают правильно.

    Разрешено только для STATUS_QUEUED без vdj_item_id — иначе одна и та же
    песня оказалась бы в очереди VirtualDJ дважды.

    Возвращает (order, outcome), outcome — один из:
        "not_found", "forbidden", "already_queued", "vdj_error", "queued".
    """
    order = db.session.get(Order, order_id)
    if order is None:
        return None, "not_found"
    if order.club_id != kj.club_id:
        return None, "forbidden"
    if order.status != STATUS_QUEUED or order.vdj_item_id:
        return order, "already_queued"

    vdj = get_vdj_client(kj.club_id)
    try:
        vdj_item_id = vdj.add_to_queue(order.song_title, order.artist, order.table_no)
    except VirtualDJError:
        return order, "vdj_error"

    order.vdj_item_id = vdj_item_id
    db.session.commit()

    emit_queue_updated(kj.club_id, get_kj_queue_view(kj.club_id))

    return order, "queued"


def add_manual_song(kj, song_title: str, artist, table_no: int):
    """
    KJ добавляет песню на карточку стола прямо из панели KJ Pro, минуя
    гостя и Guest App целиком — экран "Добавить песню" (например, гостя
    попросили на ухо, диджей вписывает песню за него).

    ОБНОВЛЕНО (запрос пользователя 2026-10: "Не удалось добавить песню в
    VirtualDJ. Нужно не в виртуал добавлять, а на стол указанный в панели
    заказов — это к примеру если диджею на ухо сделали заказ и он вместо
    гостя добавил песню на стол"): раньше эта функция сразу пыталась
    поставить песню в живую очередь VirtualDJ (vdj.add_to_queue()) прямо в
    момент нажатия "Добавить" — если мост VirtualDJ был недоступен или
    нестабилен (та же самая практическая причина, что и у confirm_order()
    выше, см. её докстринг), KJ получал ошибку "Не удалось добавить песню
    в VirtualDJ" и не мог воспользоваться экраном вообще, хотя сам он
    ничего от VirtualDJ в этот момент не просил — ему нужно было просто
    положить песню на карточку стола, как обычный принятый заказ. Теперь
    эта функция ведёт себя как хвост confirm_order(): создаёт заказ сразу
    в STATUS_QUEUED, с пустым vdj_item_id — он появляется на доске
    "Заказы по столам" тем же способом, что и обычный подтверждённый заказ
    гостя, а в живую очередь VirtualDJ его потом ставит сам KJ той же
    кнопкой "🎵 В очередь VDJ" (push_order_to_queue() выше), когда дойдёт
    очередь. VirtualDJ здесь больше не трогаем вообще — значит, outcome
    "vdj_error" для этой функции больше не бывает, она всегда "queued".

    Стол обязателен (в отличие от гостевого заказа, где table_no=None —
    легитимный "заказ без стола", ТЗ п.27): здесь стол не выбирает гость,
    его указывает KJ, так что null означал бы просто "забыли ввести", а не
    осознанный выбор — поэтому пустой/нулевой table_no отклоняется вызывающим
    кодом (маршрутом) ещё до этой функции.

    telegram_user_id = -1 / source="manual" / channel="webapp" — как и
    раньше, см. подробности в предыдущей версии докстринга (не гость,
    уведомлять через Telegram некого).

    Возвращает (order, outcome), outcome всегда "queued".
    """
    order = Order(
        telegram_user_id=-1,
        club_id=kj.club_id,
        table_no=table_no,
        song_title=song_title,
        artist=artist,
        status=STATUS_QUEUED,
        source="manual",
        channel="webapp",
        vdj_item_id=None,
        queued_at=_utcnow(),
        confirmed_by=kj.id,
        confirmed_at=_utcnow(),
    )
    db.session.add(order)
    db.session.commit()

    emit_order_updated(order)

    return order, "queued"
