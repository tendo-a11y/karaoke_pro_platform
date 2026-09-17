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
                # Доп. ТЗ "KJ Pro": нужен экрану живой очереди, чтобы показать
                # и дать сменить категорию уже поставленной в очередь песни
                # (см. update_order_category() выше).
                "service_id": matched.service_id if matched else None,
                "orphaned": False,
            }
        )

    # Заказы, оставшиеся неразобранными выше — STATUS_QUEUED в базе, но нет
    # такой позиции в живой очереди VirtualDJ вообще (см. докстринг).
    #
    # Запрос пользователя 2026-09-17: раньше такие "потерянные" заказы
    # показывались KJ прямо в живой очереди с пометкой orphaned=True и
    # кнопкой "Удалить" (см. историю в докстринге выше) — но на практике это
    # только путает: KJ видит в очереди песню, которой там давно нет, и не
    # понимает, что это не настоящий заказ, а мусор от рассинхронизации.
    # Теперь вместо показа с ручным удалением — сразу молча снимаем такой
    # заказ с очереди сами (STATUS_REJECTED, тем же способом, что и ручное
    # удаление в remove_from_vdj_queue() выше), и в список живой очереди он
    # вообще не попадает — KJ просто никогда его не увидит.
    #
    # Сознательно НЕ отправляем гостю уведомление "❌ Ваша песня удалена из
    # очереди" (в отличие от remove_from_vdj_queue(), где это осознанное
    # действие KJ прямо сейчас) — здесь мы просто обнаружили постфактум, что
    # песня пропала из VirtualDJ неизвестно когда (возможно, уже давно), и
    # присылать гостю через неопределённое время после этого "уведомление",
    # никак не привязанное к моменту реального события, только сбило бы его
    # с толку.
    for order in unused_orders:
        order.status = STATUS_REJECTED
        order.rejected_at = _utcnow()
    if unused_orders:
        db.session.commit()
    return result


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
