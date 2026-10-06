from datetime import date
from decimal import Decimal, InvalidOperation

from flask import Blueprint, current_app, g, jsonify, request

from auth import issue_kj_google_token, require_kj
from errors import api_error, api_ok
from extensions import db
from models import AdminKjMessage, ChatMessage, Club, GuestAccount, KJOperator, Order, STATUS_PLAYING, TableGroupMember, VipClient, VipRequest
from services import category_service, guest_account_service, guest_directory_service, guest_status_service, song_service, table_close_service, table_group_service, vip_service, vip_topup_request_service
from services.guest_directory_service import GUEST_TYPES, GuestDirectoryError
from services.category_service import CategoryServiceError
from services.google_auth_service import GoogleAuthError, verify_google_credential
from services.table_board_service import (
    QUEUE_MODE_CHOICES,
    get_orders_board,
    get_queue_mode,
    get_queue_start_table,
)
from services.vdj_service import (
    add_manual_song,
    approve_order_change_request,
    claim_vdj_queue_item,
    confirm_order,
    get_kj_queue_view,
    list_pending_change_requests,
    mark_played,
    push_order_to_queue,
    reject_order,
    reject_order_change_request,
    update_order_category,
    update_order_table,
)
from sockets import emit_admin_message, emit_chat_message, emit_table_group_moved
from vdj import bridge_status

bp = Blueprint("kj", __name__, url_prefix="/api/kj")


@bp.post("/auth/google")
def kj_google_login():
    """
    Вход в KJ Panel через клубный Google-аккаунт (запрос пользователя
    2026-09: "доступ KJ Pro определяется Google-аккаунтом клуба" — основной
    способ входа наряду с /kjpanel через бота, см. auth.py::issue_kj_google_token
    и docstring KJOperator в models.py). Без @require_kj — это как раз тот
    эндпоинт, который выдаёт токен, а не проверяет его.

    В отличие от routes/guest.py::link_google, здесь Google-аккаунт НЕ
    привязывается сам фактом входа с любой почты — сначала администратор
    клуба должен явно вписать разрешённую почту в KJOperator.google_email
    (Admin App, см. services/kj_admin_service.assign_kj). Первый успешный
    вход с этой почтой заполняет google_sub — дальше уже он, а не email,
    служит источником истины (сверка по email при каждом входе была бы
    менее надёжной: email технически можно сменить на стороне Google).
    """
    payload = request.get_json(silent=True) or {}
    credential = payload.get("credential")
    try:
        identity = verify_google_credential(
            current_app.config["GOOGLE_AUTH_MODE"], current_app.config.get("GOOGLE_CLIENT_ID"), credential,
        )
    except GoogleAuthError as exc:
        return api_error(400, "GOOGLE_AUTH_ERROR", exc.message)

    sub = identity["sub"]
    email = identity.get("email")

    kj = KJOperator.query.filter_by(google_sub=sub).first()
    if kj is None and email:
        kj = KJOperator.query.filter_by(google_email=email.lower(), google_sub=None).first()
        if kj is not None:
            kj.google_sub = sub
            db.session.commit()

    if kj is None:
        return api_error(
            403, "GOOGLE_NOT_REGISTERED",
            "Этот Google-аккаунт не привязан ни к одному клубу — обратитесь к администратору",
        )
    if not kj.is_active:
        return api_error(403, "FORBIDDEN", "Доступ KJ заблокирован")
    if not kj.club or not kj.club.is_active:
        return api_error(403, "FORBIDDEN", "Клуб недоступен")

    token = issue_kj_google_token(
        sub, current_app.config["KJ_JWT_SECRET"], current_app.config["KJ_JWT_TTL_SECONDS"],
    )
    return api_ok({"token": token})


def _ensure_own_club(club_id: int):
    """ТЗ п.24-25: KJ одного клуба не должен иметь доступ к заказам/очереди
    другого клуба, даже если он подставит чужой club_id в URL."""
    if club_id != g.club_id:
        return api_error(403, "FORBIDDEN", "Нет доступа к этому клубу")
    return None


@bp.get("/me")
@require_kj
def me():
    """
    Не входит в минимальный список ТЗ п.23, но необходима React KJ Panel,
    чтобы узнать свой club_id и имя сразу после перехода по ссылке с
    токеном — без этого фронтенду неоткуда взять club_id для остальных
    запросов. Данные берутся из g.kj (см. require_kj), т.е. из БД, а не из
    токена.
    """
    return api_ok({
        "kj_id": g.kj.id,
        "display_name": g.kj.display_name,
        "club_id": g.kj.club_id,
        "club_name": g.kj.club.name if g.kj.club else None,
    })


@bp.get("/orders/<int:club_id>")
@require_kj
def list_orders(club_id):
    denied = _ensure_own_club(club_id)
    if denied:
        return denied

    status = request.args.get("status", "pending")
    query = Order.query.filter_by(club_id=club_id)
    if status != "all":
        query = query.filter_by(status=status)
    orders = query.order_by(Order.created_at.asc()).all()
    return api_ok([o.to_dict() for o in orders])


@bp.get("/orders-board/<int:club_id>")
@require_kj
def orders_board(club_id):
    """
    Доп. ТЗ "KJ Pro" (запрос пользователя 2026-09-18): сетка карточек
    столов для экрана "Заказы" — по одной карточке на стол, с местами по
    числу Club.songs_per_table. См. докстринг
    services/table_board_service.py::get_orders_board про то, что именно
    попадает на карточку и почему заказы сверх лимита стола сюда не
    попадают вовсе.
    """
    denied = _ensure_own_club(club_id)
    if denied:
        return denied
    return api_ok(get_orders_board(club_id))


@bp.get("/order/<int:order_id>")
@require_kj
def get_order(order_id):
    order = db.session.get(Order, order_id)
    if order is None:
        return api_error(404, "ORDER_NOT_FOUND", "Заказ не найден")
    denied = _ensure_own_club(order.club_id)
    if denied:
        return denied
    return api_ok(order.to_dict())


_OUTCOME_HTTP = {
    "not_found": (404, "ORDER_NOT_FOUND", "Заказ не найден"),
    "forbidden": (403, "FORBIDDEN", "Нет доступа к этому заказу"),
    "conflict": (409, "ORDER_ALREADY_PROCESSED", "Заказ уже обработан"),
}


@bp.put("/order/<int:order_id>/confirm")
@require_kj
def confirm(order_id):
    # ДОБАВЛЕНО (запрос пользователя: KJ не должен принимать заказы, пока
    # не выбрано, с какого стола начинается очередь) — проверяется всегда,
    # независимо от режима показа очереди (QUEUE_MODE_SEQUENTIAL в
    # services/table_board_service.py — это только про отображение порядка
    # на карточках, а это отдельная и обязательная для любого режима проверка).
    club = db.session.get(Club, g.kj.club_id)
    if club is not None and not club.queue_start_table:
        return api_error(
            400,
            "QUEUE_START_TABLE_REQUIRED",
            "Сначала укажите, с какого стола начинается очередь — поле рядом с кнопкой \"Закрыть все столы\" на экране \"Заказы по столам\"",
        )

    order, outcome = confirm_order(order_id, g.kj)

    if outcome == "queued":
        return api_ok(order.to_dict())

    if outcome in _OUTCOME_HTTP:
        status_code, error_code, message = _OUTCOME_HTTP[outcome]
        payload = {"success": False, "error": error_code, "message": message}
        if order is not None:
            payload["order"] = order.to_dict()
        response = jsonify(payload)
        response.status_code = status_code
        return response

    return api_error(500, "INTERNAL_ERROR", "Неизвестный результат обработки заказа")


@bp.put("/order/<int:order_id>/reject")
@require_kj
def reject(order_id):
    order, outcome = reject_order(order_id, g.kj)

    if outcome == "rejected":
        return api_ok(order.to_dict())

    if outcome in _OUTCOME_HTTP:
        status_code, error_code, message = _OUTCOME_HTTP[outcome]
        return api_error(status_code, error_code, message)

    return api_error(500, "INTERNAL_ERROR", "Неизвестный результат обработки заказа")


@bp.put("/order/<int:order_id>/mark-played")
@require_kj
def mark_played_route(order_id):
    """
    ЗАМЕНЯЕТ старую ручку /order/<id>/complete (запрос пользователя
    2026-09-30 — см. подробности в docstring mark_played() в
    services/vdj_service.py). Кнопка "Готово" теперь есть у ЛЮБОЙ карточки
    в очереди (и VIP, и обычной, см. kj-panel/src/App.jsx), а не только у
    VIP — раньше фронтенд показывал её только для VIP-заказов, потому что
    только они что-то списывали. Теперь она ничего не списывает — только
    убирает карточку с экрана. Деньги (и с VIP, и с обычных гостей)
    считаются одной суммой при закрытии стола.
    """
    order, outcome = mark_played(order_id, g.kj)

    if outcome == "played":
        return api_ok(order.to_dict())

    if outcome in _OUTCOME_HTTP:
        status_code, error_code, message = _OUTCOME_HTTP[outcome]
        return api_error(status_code, error_code, message)

    return api_error(500, "INTERNAL_ERROR", "Неизвестный результат обработки заказа")


@bp.put("/order/<int:order_id>/push-to-vdj")
@require_kj
def push_order_to_vdj_route(order_id):
    """
    KJ Pro, кнопка "🎵 В очередь VDJ" на уже принятом заказе (OrdersBoardSlot,
    запрос пользователя 2026-10 — жалоба "мой заказ не подсвечивается
    зелёным", см. docstring push_order_to_queue() в services/vdj_service.py
    за полным обоснованием). Ставит именно этот, настоящий заказ гостя в
    живую очередь VirtualDJ, не теряя его личность — в отличие от "➕
    Добавить песню" ниже (add_manual_order), которая всегда создаёт
    "ничей" заказ. Только так подсветка VIP/Крейзи/"моя песня" в Guest App
    может сработать.
    """
    order, outcome = push_order_to_queue(order_id, g.kj)

    if outcome == "queued":
        return api_ok(order.to_dict())

    if outcome == "vdj_error":
        return api_error(502, "VDJ_UNAVAILABLE", "Не удалось добавить песню в VirtualDJ")

    if outcome == "already_queued":
        return api_error(409, "ALREADY_IN_VDJ_QUEUE", "Эта песня уже в очереди VirtualDJ")

    if outcome in _OUTCOME_HTTP:
        status_code, error_code, message = _OUTCOME_HTTP[outcome]
        return api_error(status_code, error_code, message)

    return api_error(500, "INTERNAL_ERROR", "Неизвестный результат обработки заказа")


_QUEUE_EDIT_OUTCOME_HTTP = {
    "not_found": (404, "ORDER_NOT_FOUND", "Заказ не найден"),
    "forbidden": (403, "FORBIDDEN", "Нет доступа к этому заказу"),
    "not_queued": (409, "ORDER_NOT_QUEUED", "Менять можно только у песни, ещё стоящей в очереди"),
    "service_not_found": (404, "SERVICE_NOT_FOUND", "Категория не найдена"),
}


@bp.put("/order/<int:order_id>/table")
@require_kj
def update_order_table_route(order_id):
    """
    Доп. ТЗ "KJ Pro": смена номера стола у песни, уже стоящей в очереди —
    экран "Живая очередь VirtualDJ" (см. update_order_table() в
    services/vdj_service.py). table_no: null — снять стол ("Без стола").
    """
    payload = request.get_json(silent=True) or {}
    table_no = payload.get("table_no")

    if table_no is not None and (
        isinstance(table_no, bool) or not isinstance(table_no, int) or table_no <= 0
    ):
        return api_error(400, "VALIDATION_ERROR", "table_no должен быть положительным числом, либо null (без стола)")

    # KJ-04: то же ограничение по количеству столов клуба, что и в
    # /order/manual и /table-settings выше.
    club = db.session.get(Club, g.club_id)
    if table_no is not None and club is not None and club.table_count is not None and table_no > club.table_count:
        return api_error(
            400, "TABLE_OUT_OF_RANGE",
            f"В этом клубе {club.table_count} столов — выберите номер от 1 до {club.table_count}",
        )

    order, outcome = update_order_table(order_id, g.kj, table_no)
    if outcome == "updated":
        return api_ok(order.to_dict())
    if outcome in _QUEUE_EDIT_OUTCOME_HTTP:
        status_code, error_code, message = _QUEUE_EDIT_OUTCOME_HTTP[outcome]
        return api_error(status_code, error_code, message)
    return api_error(500, "INTERNAL_ERROR", "Неизвестный результат обработки заказа")


@bp.put("/order/<int:order_id>/category")
@require_kj
def update_order_category_route(order_id):
    """
    Доп. ТЗ "KJ Pro": назначение/смена категории у песни, уже стоящей в
    очереди (см. update_order_category() в services/vdj_service.py).
    service_id: null — снять категорию ("Без категории").
    """
    payload = request.get_json(silent=True) or {}
    service_id = payload.get("service_id")

    if service_id is not None and (isinstance(service_id, bool) or not isinstance(service_id, int)):
        return api_error(400, "VALIDATION_ERROR", "service_id должен быть числом, либо null (без категории)")

    order, outcome = update_order_category(order_id, g.kj, service_id)
    if outcome == "updated":
        return api_ok(order.to_dict())
    if outcome in _QUEUE_EDIT_OUTCOME_HTTP:
        status_code, error_code, message = _QUEUE_EDIT_OUTCOME_HTTP[outcome]
        return api_error(status_code, error_code, message)
    return api_error(500, "INTERNAL_ERROR", "Неизвестный результат обработки заказа")


@bp.get("/chat/<int:club_id>")
@require_kj
def list_chat(club_id):
    """
    Вся переписка клуба, по умолчанию сгруппированной по гостю фронтенд
    сделает сам (данных достаточно — telegram_user_id/table_no в каждом
    сообщении). ?telegram_user_id=... сужает до переписки с одним гостем —
    именно так KJ Panel будет открывать конкретный диалог для ответа.
    """
    denied = _ensure_own_club(club_id)
    if denied:
        return denied

    query = ChatMessage.query.filter_by(club_id=club_id)
    telegram_user_id = request.args.get("telegram_user_id", type=int)
    if telegram_user_id is not None:
        query = query.filter_by(telegram_user_id=telegram_user_id)
    messages = query.order_by(ChatMessage.created_at.asc()).all()
    return api_ok([m.to_dict() for m in messages])


@bp.post("/chat/<int:club_id>")
@require_kj
def reply_chat(club_id):
    """
    Ответ KJ конкретному гостю. В старом боте отвечал тот KJ, кто первым
    нажал «Ответить» под сообщением — отдельного назначения "чей это
    диалог" не было и здесь не вводится: любой активный KJ этого клуба
    может ответить любому гостю клуба.
    """
    denied = _ensure_own_club(club_id)
    if denied:
        return denied

    payload = request.get_json(silent=True) or {}
    telegram_user_id = payload.get("telegram_user_id")
    message_text = payload.get("message_text")

    # ИЗМЕНЕНО (2026-10): номер гостя принимается и строкой из цифр — так
    # его теперь присылает KJ Panel, чтобы большие номера не округлялись в
    # браузере (см. "guest_id" в ChatMessage.to_dict).
    if isinstance(telegram_user_id, str) and telegram_user_id.strip().lstrip("-").isdigit():
        telegram_user_id = int(telegram_user_id.strip())
    if isinstance(telegram_user_id, bool) or not isinstance(telegram_user_id, int):
        return api_error(400, "VALIDATION_ERROR", "telegram_user_id обязателен и должен быть числом")
    if not message_text or not isinstance(message_text, str):
        return api_error(400, "VALIDATION_ERROR", "message_text обязателен")

    message = ChatMessage(
        club_id=club_id,
        telegram_user_id=telegram_user_id,
        from_guest=False,
        message_text=message_text,
    )
    db.session.add(message)
    db.session.commit()

    emit_chat_message(message)

    return api_ok(message.to_dict(), status_code=201)


# ДОБАВЛЕНО (2026-10-04, запрос пользователя "нигде нет кнопки удаления
# сообщений и очистки чата") — реальное удаление строки(строк)
# ChatMessage, без мягкого флага: переписка короткая и ситуативная (на
# один вечер), отдельной истории версий для неё, в отличие от заказов/
# транзакций, в проекте никогда не было. KJ может удалить любое
# сообщение в переписке своего клуба — и гостя, и своё — та же логика
# модерации, что и везде в KJ Panel (блокировка гостя, удаление его
# фото и т.п.).
@bp.delete("/chat/<int:message_id>")
@require_kj
def delete_chat_message(message_id):
    message = db.session.get(ChatMessage, message_id)
    if message is None:
        return api_error(404, "MESSAGE_NOT_FOUND", "Сообщение не найдено")
    if message.club_id != g.club_id:
        return api_error(403, "FORBIDDEN", "Нет доступа к этому сообщению")
    db.session.delete(message)
    db.session.commit()
    return api_ok({"deleted": True})


@bp.delete("/chat/<int:club_id>/<int:telegram_user_id>")
@require_kj
def clear_chat(club_id, telegram_user_id):
    """"Очистить чат" — удаляет всю переписку с одним гостем целиком, та
    же модерация, что и у отдельного сообщения выше, но на весь диалог."""
    denied = _ensure_own_club(club_id)
    if denied:
        return denied
    ChatMessage.query.filter_by(club_id=club_id, telegram_user_id=telegram_user_id).delete()
    db.session.commit()
    return api_ok({"cleared": True})


@bp.get("/admin-messages/<int:club_id>")
@require_kj
def list_admin_messages(club_id):
    """
    Переписка с администрацией клуба (запрос пользователя 2026-10-03:
    "в админке есть панель управления KJ... сообщения приходят KJ в его
    панель сообщений"). Отдельная от ChatMessage (гость↔KJ) переписка —
    см. models.py::AdminKjMessage.
    """
    denied = _ensure_own_club(club_id)
    if denied:
        return denied
    messages = AdminKjMessage.query.filter_by(club_id=club_id).order_by(AdminKjMessage.created_at.asc()).all()
    return api_ok([m.to_dict() for m in messages])


@bp.post("/admin-messages/<int:club_id>")
@require_kj
def reply_admin_message(club_id):
    """Ответ KJ администрации (режим переписки двусторонний, запрос
    пользователя 2026-10-03: "режим переписки 2 да")."""
    denied = _ensure_own_club(club_id)
    if denied:
        return denied
    payload = request.get_json(silent=True) or {}
    message_text = payload.get("message_text")
    if not message_text or not isinstance(message_text, str) or not message_text.strip():
        return api_error(400, "VALIDATION_ERROR", "message_text обязателен")
    message = AdminKjMessage(club_id=club_id, from_admin=False, message_text=message_text.strip())
    db.session.add(message)
    db.session.commit()
    emit_admin_message(message)
    return api_ok(message.to_dict(), status_code=201)


@bp.put("/admin-messages/<int:club_id>/read")
@require_kj
def mark_admin_messages_read(club_id):
    """Отметка прочтения — сообщение от администрации должно "висеть,
    пока не откроет" (запрос пользователя 2026-10-03), поэтому снимается
    только явным действием, а не автоматически при списке."""
    denied = _ensure_own_club(club_id)
    if denied:
        return denied
    AdminKjMessage.query.filter_by(club_id=club_id, from_admin=True, is_read_by_kj=False).update(
        {"is_read_by_kj": True}
    )
    db.session.commit()
    return api_ok({"marked_read": True})


@bp.get("/vip-requests/<int:club_id>")
@require_kj
def list_vip_requests(club_id):
    """Старое: KJ видел заявки на VIP как личное сообщение в Telegram с
    кнопками — здесь тот же смысл списком (KJ Pro ещё не имеет экрана для
    этого, эндпоинт готовится заранее, как и /queue раньше)."""
    denied = _ensure_own_club(club_id)
    if denied:
        return denied
    status = request.args.get("status", "pending")
    query = VipRequest.query.filter_by(club_id=club_id)
    if status != "all":
        query = query.filter_by(status=status)
    requests_ = query.order_by(VipRequest.created_at.asc()).all()
    return api_ok([r.to_dict() for r in requests_])


@bp.put("/vip-requests/<int:request_id>/approve")
@require_kj
def approve_vip_request(request_id):
    """
    Старое: handlers/kj.py::vip_request_approve (аудит п.8А). ТЗ п.45:
    VIP выдаётся на уже существующий постоянный профиль гостя (см.
    docstring services/vip_service.py::approve_vip_request) — прежний
    ответ с одноразовым access_code удалён вместе со всем этим механизмом.
    """
    result = vip_service.approve_vip_request(request_id, g.kj)
    if result.outcome == "not_found":
        return api_error(404, "VIP_REQUEST_NOT_FOUND", "Заявка не найдена")
    if result.outcome == "forbidden":
        return api_error(403, "FORBIDDEN", "Нет доступа к этой заявке")
    if result.outcome == "already_decided":
        return api_error(409, "ALREADY_DECIDED", "Заявка уже обработана")
    if result.outcome == "guest_account_missing":
        return api_error(
            409, "GUEST_ACCOUNT_MISSING",
            "У заявителя больше нет постоянного профиля — заявку нужно отклонить",
        )
    return api_ok({
        "request": result.request.to_dict(),
        "vip_client": result.vip_client.to_dict(),
    })


@bp.put("/vip-requests/<int:request_id>/reject")
@require_kj
def reject_vip_request(request_id):
    result = vip_service.reject_vip_request(request_id, g.kj)
    if result.outcome == "not_found":
        return api_error(404, "VIP_REQUEST_NOT_FOUND", "Заявка не найдена")
    if result.outcome == "forbidden":
        return api_error(403, "FORBIDDEN", "Нет доступа к этой заявке")
    if result.outcome == "already_decided":
        return api_error(409, "ALREADY_DECIDED", "Заявка уже обработана")
    return api_ok(result.request.to_dict())


@bp.get("/vip-topup-requests/<int:club_id>")
@require_kj
def list_vip_topup_requests(club_id):
    """
    Запросы VIP-гостей "хочу пополнить баланс" (см. докстринг
    services/vip_topup_request_service.py) — тот же вид списка, что и
    /vip-requests выше. Решённые заявки KJ Panel не показывает, поэтому
    без параметра ?status, в отличие от /vip-requests.
    """
    denied = _ensure_own_club(club_id)
    if denied:
        return denied
    requests_ = vip_topup_request_service.list_pending(club_id)
    return api_ok([r.to_dict() for r in requests_])


@bp.put("/vip-topup-requests/<int:request_id>/resolve")
@require_kj
def resolve_vip_topup_request(request_id):
    """
    KJ отмечает заявку на пополнение обработанной — деньги он уже зачислил
    вручную через POST /vip-clients/<id>/topup (как и раньше), эта кнопка
    только убирает уведомление из списка во всех открытых панелях клуба.
    """
    result = vip_topup_request_service.resolve_request(g.club_id, request_id, g.kj)
    if result.outcome == "not_found":
        return api_error(404, "VIP_TOPUP_REQUEST_NOT_FOUND", "Заявка не найдена")
    if result.outcome == "forbidden":
        return api_error(403, "FORBIDDEN", "Нет доступа к этой заявке")
    if result.outcome == "already_decided":
        return api_error(409, "ALREADY_DECIDED", "Заявка уже обработана")
    return api_ok(result.request.to_dict())


@bp.get("/order-change-requests/<int:club_id>")
@require_kj
def list_order_change_requests(club_id):
    """
    ДОБАВЛЕНО 2026-09-20 — решение пользователя "Нужно одобрение KJ (запрос
    → Одобрить/Отклонить)": неразобранные заявки гостей на отмену/замену
    уже принятых заказов (см. services/vdj_service.py::request_order_cancel/
    request_order_replace). Аналог list_vip_requests выше, но всегда только
    pending — уже решённые заявки (approved/rejected) отдельного экрана
    "истории заявок" в этом шаге не получают (то же решение, что и у
    отклонённых/сыгранных заказов в routes/guest.py::list_my_orders — не
    захламлять текущий список).

    order_song_title/order_artist/table_no — не хранятся в самой заявке
    (см. models.OrderChangeRequest), а подтягиваются здесь же из
    связанного Order одним заходом, чтобы KJ Panel могла показать заявку
    сразу с понятным текстом ("стол 5: Билет на самолёт"), без отдельного
    запроса самого заказа по order_id.
    """
    denied = _ensure_own_club(club_id)
    if denied:
        return denied
    requests_ = list_pending_change_requests(club_id)

    order_ids = [r.order_id for r in requests_]
    orders_by_id = {}
    if order_ids:
        orders_by_id = {
            o.id: o for o in Order.query.filter(Order.id.in_(order_ids)).all()
        }

    result = []
    for r in requests_:
        data = r.to_dict()
        order = orders_by_id.get(r.order_id)
        data["table_no"] = order.table_no if order else None
        data["order_song_title"] = order.song_title if order else None
        data["order_artist"] = order.artist if order else None
        result.append(data)
    return api_ok(result)


@bp.put("/order-change-requests/<int:request_id>/approve")
@require_kj
def approve_order_change_request_route(request_id):
    """
    KJ одобряет заявку — см. vdj_service.approve_order_change_request про
    то, что именно происходит с самим заказом (отмена/замена) и почему
    заявка может автоматически стать "устаревшей" (outcome "stale"), если
    заказ успел измениться, пока заявка ждала решения.
    """
    change_request, order, outcome = approve_order_change_request(request_id, g.kj)
    if outcome == "not_found":
        return api_error(404, "REQUEST_NOT_FOUND", "Заявка не найдена")
    if outcome == "forbidden":
        return api_error(403, "FORBIDDEN", "Нет доступа к этой заявке")
    if outcome == "already_decided":
        return api_error(409, "ALREADY_DECIDED", "Заявка уже обработана")
    if outcome == "stale":
        return api_error(
            409, "ORDER_CHANGED",
            "Заказ уже изменился, пока заявка ждала решения — заявка автоматически отклонена",
        )
    return api_ok({
        "request": change_request.to_dict(),
        "order": order.to_dict() if order else None,
    })


@bp.put("/order-change-requests/<int:request_id>/reject")
@require_kj
def reject_order_change_request_route(request_id):
    """KJ отклоняет заявку — сам заказ остаётся без изменений."""
    change_request, outcome = reject_order_change_request(request_id, g.kj)
    if outcome == "not_found":
        return api_error(404, "REQUEST_NOT_FOUND", "Заявка не найдена")
    if outcome == "forbidden":
        return api_error(403, "FORBIDDEN", "Нет доступа к этой заявке")
    if outcome == "already_decided":
        return api_error(409, "ALREADY_DECIDED", "Заявка уже обработана")
    return api_ok(change_request.to_dict())


@bp.get("/vip-clients/<int:club_id>")
@require_kj
def list_vip_clients(club_id):
    """
    Block D KJ Pro — список VIP-клиентов клуба, нужен фронтенду, чтобы
    вообще было над кем вызывать /cashback|/topup|/debit|/balance ниже
    (см. services/vip_service.py::list_vip_clients docstring про то,
    почему это простой список, а не поиск, как в старом боте).

    ТЗ п.45: ручное создание VIP "из ничего" (POST /vip-clients) удалено —
    VIP всегда возникает через заявку гостя (см. approve_vip_request
    выше), KJ его никогда не создаёт напрямую.
    """
    denied = _ensure_own_club(club_id)
    if denied:
        return denied
    clients = vip_service.list_vip_clients(club_id)
    # ДОБАВЛЕНО (2026-09-23, запрос пользователя "нужно иметь возможность
    # блокировать VIP"): is_blocked нужен фронтенду вкладки VIP, чтобы
    # показать актуальное состояние кнопки "Заблокировать"/"Разблокировать"
    # — сами эндпоинты блокировки уже существуют и не менялись
    # (POST /guests/<id>/block|unblock ниже, до этого использовались только
    # из карточки гостя во вкладке "Гости").
    result = []
    for c in clients:
        row = c.to_dict()
        status = guest_status_service.get_status(club_id, c.telegram_user_id)
        row["is_blocked"] = bool(status.is_blocked) if status else False
        # ДОБАВЛЕНО (запрос пользователя 2026-10-01, "не видно имя гостя во
        # вкладке VIP"): у VipClient своего имени нет — оно живёт в
        # постоянном профиле гостя (GuestAccount, см. его докстринг), сюда
        # просто подмешиваем display_name и фото оттуда по тому же
        # (club_id, telegram_user_id), по которому уже ищем guest_status
        # выше.
        account = GuestAccount.query.filter_by(club_id=club_id, telegram_user_id=c.telegram_user_id).first()
        row["display_name"] = account.display_name if account else None
        row["photo_data_url"] = account.photo_data_url if account else None
        result.append(row)
    return api_ok(result)


@bp.put("/vip-clients/<int:vip_client_id>/cashback")
@require_kj
def update_vip_cashback(vip_client_id):
    """
    Старое: handlers/kj.py::vip_add_cashback / client_commission_manage
    (аудит п.8Б/11) — единственное реальное место, где cashback_percent
    когда-либо менялся (venues.vip_cashback был декоративным, аудит п.11,
    сюда намеренно не переносится как единственный "настоящий" рычаг).
    """
    vip_client = db.session.get(VipClient, vip_client_id)
    if vip_client is None:
        return api_error(404, "VIP_CLIENT_NOT_FOUND", "VIP-клиент не найден")
    if vip_client.club_id != g.club_id:
        return api_error(403, "FORBIDDEN", "Нет доступа к этому VIP-клиенту")

    payload = request.get_json(silent=True) or {}
    cashback_percent = payload.get("cashback_percent")
    if not isinstance(cashback_percent, (int, float)) or not (0 <= cashback_percent <= 100):
        return api_error(400, "VALIDATION_ERROR", "cashback_percent должен быть числом от 0 до 100")

    vip_client.cashback_percent = cashback_percent
    db.session.commit()
    return api_ok(vip_client.to_dict())


def _parse_amount(payload: dict, field: str):
    """
    Общая валидация денежной суммы для ручных корректировок баланса ниже.
    Decimal(str(x)), а не Decimal(x) — чтобы не тащить двоичную погрешность
    float внутрь Numeric(10,2)-колонки (тот же приём, что и в
    services/billing_service.py). Возвращает (Decimal, None) или (None, str
    с текстом ошибки).
    """
    raw = payload.get(field)
    if not isinstance(raw, (int, float)) or isinstance(raw, bool):
        return None, f"{field} должен быть числом"
    try:
        value = Decimal(str(raw)).quantize(Decimal("0.01"))
    except InvalidOperation:
        return None, f"{field} должен быть корректным числом"
    return value, None


@bp.post("/vip-clients/<int:vip_client_id>/topup")
@require_kj
def topup_vip_balance(vip_client_id):
    """
    ➕ Начислить (старое: handlers/kj.py::balance_add, аудит по
    VIP-пополнению). Гость просит пополнение УСТНО, в баре — это не
    цифровая заявка гость→KJ, а прямое действие KJ над уже существующим
    VIP-счётом, поэтому здесь нет request/approve, только сама операция.
    """
    payload = request.get_json(silent=True) or {}
    amount, error = _parse_amount(payload, "amount")
    if error:
        return api_error(400, "VALIDATION_ERROR", error)
    if amount <= 0:
        return api_error(400, "VALIDATION_ERROR", "amount должен быть положительным")

    result = vip_service.topup_balance(g.club_id, vip_client_id, amount)
    if result.outcome == "not_found":
        return api_error(404, "VIP_CLIENT_NOT_FOUND", "VIP-клиент не найден")
    if result.outcome == "forbidden":
        return api_error(403, "FORBIDDEN", "Нет доступа к этому VIP-клиенту")
    return api_ok(result.vip_client.to_dict())


@bp.post("/vip-clients/<int:vip_client_id>/debit")
@require_kj
def debit_vip_balance(vip_client_id):
    """➖ Списать (старое: handlers/kj.py::balance_sub). Сознательно без
    защиты от ухода в минус — см. docstring vip_service.debit_balance."""
    payload = request.get_json(silent=True) or {}
    amount, error = _parse_amount(payload, "amount")
    if error:
        return api_error(400, "VALIDATION_ERROR", error)
    if amount <= 0:
        return api_error(400, "VALIDATION_ERROR", "amount должен быть положительным")

    result = vip_service.debit_balance(g.club_id, vip_client_id, amount)
    if result.outcome == "not_found":
        return api_error(404, "VIP_CLIENT_NOT_FOUND", "VIP-клиент не найден")
    if result.outcome == "forbidden":
        return api_error(403, "FORBIDDEN", "Нет доступа к этому VIP-клиенту")
    return api_ok(result.vip_client.to_dict())


@bp.put("/vip-clients/<int:vip_client_id>/balance")
@require_kj
def set_vip_balance(vip_client_id):
    """🔄 Установить (старое: handlers/kj.py::balance_set) — прямое
    назначение абсолютного значения баланса, а не относительное
    изменение."""
    payload = request.get_json(silent=True) or {}
    balance, error = _parse_amount(payload, "balance")
    if error:
        return api_error(400, "VALIDATION_ERROR", error)
    if balance < 0:
        return api_error(400, "VALIDATION_ERROR", "balance не может быть отрицательным")

    result = vip_service.set_balance(g.club_id, vip_client_id, balance)
    if result.outcome == "not_found":
        return api_error(404, "VIP_CLIENT_NOT_FOUND", "VIP-клиент не найден")
    if result.outcome == "forbidden":
        return api_error(403, "FORBIDDEN", "Нет доступа к этому VIP-клиенту")
    return api_ok(result.vip_client.to_dict())


@bp.delete("/vip-clients/<int:vip_client_id>")
@require_kj
def remove_vip_client(vip_client_id):
    """
    "🗑 Удалить" во вкладке VIP (запрос пользователя 2026-09-23) — переводит
    VIP-гостя обратно в простые, см. docstring
    vip_service.remove_vip_client про то, почему это именно удаление
    строки VipClient, а не отдельный флаг, и почему баланс должен быть
    предварительно обнулён.
    """
    result = vip_service.remove_vip_client(g.club_id, vip_client_id)
    if result.outcome == "not_found":
        return api_error(404, "VIP_CLIENT_NOT_FOUND", "VIP-клиент не найден")
    if result.outcome == "forbidden":
        return api_error(403, "FORBIDDEN", "Нет доступа к этому VIP-клиенту")
    if result.outcome == "balance_not_zero":
        return api_error(
            409, "VIP_BALANCE_NOT_ZERO",
            "Сначала обнулите баланс (кнопка «Установить» = 0), потом можно перевести в простые",
        )
    return api_ok({"removed": True})


@bp.post("/songs/import")
@require_kj
def import_songs():
    """
    Старое: handlers/kj.py::handle_csv_upload (аудит п.1) — загрузка CSV с
    каталогом песен клуба, доступная KJ/Admin. Здесь доступна только KJ
    (Admin App ещё не начат — см. явное указание не переходить к нему).
    Формат/парсинг/дедупликация — 1:1 см. services/song_service.py.
    """
    file = request.files.get("file")
    if file is None or not file.filename:
        return api_error(400, "VALIDATION_ERROR", "Файл не передан")
    if not file.filename.lower().endswith(".csv"):
        return api_error(400, "VALIDATION_ERROR", "Ожидается файл .csv")

    file_content = file.read()
    songs, status_msg = song_service.parse_csv_songs(file_content)

    if not songs:
        return api_error(400, "CSV_EMPTY_OR_INVALID", status_msg)

    added = song_service.bulk_add_songs(g.club_id, songs)
    skipped = len(songs) - added
    return api_ok({"added": added, "skipped": skipped, "message": status_msg}, status_code=201)


@bp.get("/queue/<int:club_id>")
@require_kj
def queue(club_id):
    denied = _ensure_own_club(club_id)
    if denied:
        return denied

    return api_ok(get_kj_queue_view(club_id))


_CLAIM_OUTCOME_HTTP = {
    "already_claimed": (409, "ALREADY_CLAIMED", "Этой позиции уже назначен заказ"),
    "service_not_found": (404, "SERVICE_NOT_FOUND", "Категория не найдена"),
}


@bp.post("/queue/claim")
@require_kj
def claim_queue_item():
    """
    Доп. ТЗ "KJ Pro" (запрос пользователя 2026-09-14): назначить стол и/или
    категорию позиции живой очереди, у которой ещё нет заказа (KJ добавил
    песню прямо в VirtualDJ, минуя Guest App — GET /api/kj/queue/<club_id>
    отдаёт такую позицию с order_id=null). vdj_item_id/song_title/artist
    берутся из того же ответа очереди — фронтенд отправляет их обратно как
    есть. См. claim_vdj_queue_item() в services/vdj_service.py.
    """
    payload = request.get_json(silent=True) or {}
    vdj_item_id = payload.get("vdj_item_id")
    song_title = payload.get("song_title")
    artist = payload.get("artist")
    table_no = payload.get("table_no")
    service_id = payload.get("service_id")

    if not vdj_item_id or not isinstance(vdj_item_id, str):
        return api_error(400, "VALIDATION_ERROR", "vdj_item_id обязателен")
    if not song_title or not isinstance(song_title, str):
        return api_error(400, "VALIDATION_ERROR", "song_title обязателен")
    if table_no is not None and (
        isinstance(table_no, bool) or not isinstance(table_no, int) or table_no <= 0
    ):
        return api_error(400, "VALIDATION_ERROR", "table_no должен быть положительным числом, либо null")
    if service_id is not None and (isinstance(service_id, bool) or not isinstance(service_id, int)):
        return api_error(400, "VALIDATION_ERROR", "service_id должен быть числом, либо null")

    # KJ-04: то же ограничение по количеству столов клуба, что и у остальных
    # мест, где KJ сам вводит номер стола (см. /order/manual ниже).
    club = db.session.get(Club, g.club_id)
    if table_no is not None and club is not None and club.table_count is not None and table_no > club.table_count:
        return api_error(
            400, "TABLE_OUT_OF_RANGE",
            f"В этом клубе {club.table_count} столов — выберите номер от 1 до {club.table_count}",
        )

    order, outcome = claim_vdj_queue_item(g.kj, vdj_item_id, song_title, artist, table_no, service_id)
    if outcome == "claimed":
        return api_ok(order.to_dict(), status_code=201)
    if outcome in _CLAIM_OUTCOME_HTTP:
        status_code, error_code, message = _CLAIM_OUTCOME_HTTP[outcome]
        return api_error(status_code, error_code, message)
    return api_error(500, "INTERNAL_ERROR", "Неизвестный результат")


@bp.post("/order/manual")
@require_kj
def add_manual_order():
    """
    KJ Pro, экран "Добавить песню" (см. add_manual_song() в vdj_service.py
    за полным обоснованием решений) — KJ сам находит песню в VirtualDJ и
    указывает стол, заказ сразу уходит в очередь, без "Заказы"/подтверждения.
    club_id берётся из токена KJ (g.club_id, см. require_kj), а не из тела
    запроса — так же, как /songs/import выше, а не как /queue/<club_id>,
    потому что у ещё не существующего заказа нет чужого club_id, который
    нужно было бы сверять.
    """
    payload = request.get_json(silent=True) or {}
    song_title = payload.get("song_title")
    artist = payload.get("artist")
    table_no = payload.get("table_no")

    if not song_title or not isinstance(song_title, str):
        return api_error(400, "VALIDATION_ERROR", "song_title обязателен")
    if artist is not None and not isinstance(artist, str):
        return api_error(400, "VALIDATION_ERROR", "artist должен быть строкой")
    if not isinstance(table_no, int) or isinstance(table_no, bool) or table_no <= 0:
        return api_error(400, "VALIDATION_ERROR", "table_no обязателен и должен быть положительным числом")

    # KJ-04: то же ограничение по количеству столов клуба, что и у гостя в
    # routes/guest.py::link_google — иначе KJ мог бы вручную создать заказ на
    # несуществующий стол, пока для гостя этот же номер уже недоступен.
    club = db.session.get(Club, g.club_id)
    if club is not None and club.table_count is not None and table_no > club.table_count:
        return api_error(
            400, "TABLE_OUT_OF_RANGE",
            f"В этом клубе {club.table_count} столов — выберите номер от 1 до {club.table_count}",
        )

    order, outcome = add_manual_song(g.kj, song_title, artist, table_no)

    if outcome == "queued":
        return api_ok(order.to_dict(), status_code=201)

    return api_error(502, "VDJ_UNAVAILABLE", "Не удалось добавить песню в VirtualDJ")


# --- Категории песни (доп. ТЗ "KJ Pro", KJ-01/KJ-03/KJ-07) ---
# Категория = уже существовавшая модель Service ("услуга/тариф", см. её
# докстринг в models.py и docstring services/category_service.py) — по
# решению пользователя это одно и то же понятие, просто KJ теперь может
# им управлять сам, а не только через прямую правку базы данных.

@bp.get("/categories/<int:club_id>")
@require_kj
def list_categories(club_id):
    denied = _ensure_own_club(club_id)
    if denied:
        return denied
    categories = category_service.list_categories(club_id)
    return api_ok([c.to_dict() for c in categories])


@bp.post("/categories/<int:club_id>")
@require_kj
def create_category(club_id):
    denied = _ensure_own_club(club_id)
    if denied:
        return denied
    payload = request.get_json(silent=True) or {}
    try:
        category = category_service.create_category(
            club_id,
            payload.get("name"),
            payload.get("description"),
            payload.get("price", 0),
            payload.get("is_free", False),
        )
    except CategoryServiceError as exc:
        return api_error(400, exc.code, exc.message)
    return api_ok(category.to_dict(), status_code=201)


@bp.put("/categories/<int:club_id>/<int:category_id>")
@require_kj
def update_category(club_id, category_id):
    denied = _ensure_own_club(club_id)
    if denied:
        return denied
    payload = request.get_json(silent=True) or {}
    fields = {k: payload[k] for k in ("name", "description", "price", "is_free") if k in payload}
    try:
        category = category_service.update_category(club_id, category_id, **fields)
    except CategoryServiceError as exc:
        status = 404 if exc.code == "NOT_FOUND" else 400
        return api_error(status, exc.code, exc.message)
    return api_ok(category.to_dict())


@bp.delete("/categories/<int:club_id>/<int:category_id>")
@require_kj
def delete_category(club_id, category_id):
    denied = _ensure_own_club(club_id)
    if denied:
        return denied
    try:
        category_service.delete_category(club_id, category_id)
    except CategoryServiceError as exc:
        status = 404 if exc.code == "NOT_FOUND" else 409
        return api_error(status, exc.code, exc.message)
    return api_ok({"deleted": True})


# --- Настройки столов (доп. ТЗ "KJ Pro", KJ-04) ---
# В старом боте это была настройка самого KJ, не админа (handlers/kj.py:
# tables_count_edit/tables_settings_save, FSM TableSettingsForm ->
# database.py::update_venue_settings(venue_id, table_count=...), с проверкой
# int(text) >= 1). У клубов разное число столов — это Club.table_count,
# поле уже существует в модели (models.py) и уже используется для Admin App
# (services/club_service.py::create_club/update_club, там же
# _validate_table_count) и для генерации QR — здесь просто даём это же поле
# в руки KJ напрямую, отдельным эндпоинтом, а не через Admin App (KJ не
# имеет доступа к admin-эндпоинтам). None означает "не ограничено" — старое
# поведение по умолчанию, пока KJ явно не задал число.
#
# 2026-09-17, запрос пользователя: рядом со столами добавлено второе число —
# songs_per_table (сколько песен от одного стола может быть в очереди
# одновременно; см. models.py::Club.songs_per_table — это пока только
# хранение, переключение самого лимита заказа с общего
# MAX_ACTIVE_SONGS_PER_GUEST на это поле сюда не входит).
_TABLE_SETTINGS_FIELDS = {
    "table_count": "table_count должен быть положительным целым числом, либо null (без ограничения)",
    "songs_per_table": "songs_per_table должен быть положительным целым числом, либо null (не задано)",
}

# ДОБАВЛЕНО (2026-09-24, "варианты очереди" — быстрый тумблер на вкладке
# "Столы"): queue_mode отдельно от числовых полей выше — это строка из
# фиксированного набора QUEUE_MODE_CHOICES, а не число/null, поэтому у неё
# своя валидация и она не может быть null (см. models.py::Club.queue_mode,
# server_default="manual").
_QUEUE_MODE_ERROR = f"queue_mode должен быть одним из: {', '.join(QUEUE_MODE_CHOICES)}"

# ДОБАВЛЕНО (2026-09-25, запрос пользователя после бага с обгоном стола 3
# стола 16 в круговом обходе): "Начало очереди" — номер стола, с которого
# KJ вручную запускает круг QUEUE_MODE_SEQUENTIAL (см. models.py::
# Club.queue_start_table и докстринг services/table_board_service.py::
# QUEUE_MODE_SEQUENTIAL). Число, как table_count/songs_per_table, но
# дополнительно не может быть больше текущего table_count клуба — стола с
# таким номером просто не существует.
_QUEUE_START_TABLE_ERROR = (
    "queue_start_table должен быть положительным целым числом не больше "
    "table_count, либо null (не задано)"
)


@bp.get("/table-settings/<int:club_id>")
@require_kj
def get_table_settings(club_id):
    denied = _ensure_own_club(club_id)
    if denied:
        return denied
    club = db.session.get(Club, club_id)
    if club is None:
        return api_error(404, "CLUB_NOT_FOUND", "Клуб не найден")
    return api_ok({
        "table_count": club.table_count,
        "songs_per_table": club.songs_per_table,
        "queue_mode": get_queue_mode(club),
        "queue_start_table": get_queue_start_table(club),
    })


@bp.put("/table-settings/<int:club_id>")
@require_kj
def update_table_settings(club_id):
    denied = _ensure_own_club(club_id)
    if denied:
        return denied
    payload = request.get_json(silent=True) or {}

    club = db.session.get(Club, club_id)
    if club is None:
        return api_error(404, "CLUB_NOT_FOUND", "Клуб не найден")

    # Патч-семантика (а не "всегда переустановить оба поля"): значение
    # меняется только для ключей, реально присутствующих в теле запроса.
    # Это специально сделано так из-за порядка выкладки — фронтенд и бэкенд
    # этого эндпоинта обновляются раздельными коммитами (см. историю
    # деплоя), и старый фронтенд, знающий только про table_count, не должен
    # тихо обнулять songs_per_table каждым своим сохранением, пока не
    # обновлён сам. queue_mode/queue_start_table — тот же принцип: тумблер и
    # поле "Начало очереди" на вкладке "Столы" шлют только свои ключи, не
    # трогая остальные настройки.
    updates = {}
    for field, error_message in _TABLE_SETTINGS_FIELDS.items():
        if field not in payload:
            continue
        value = payload.get(field)
        if value is not None and (isinstance(value, bool) or not isinstance(value, int) or value < 1):
            return api_error(400, "VALIDATION_ERROR", error_message)
        updates[field] = value

    if "queue_mode" in payload:
        value = payload.get("queue_mode")
        if value not in QUEUE_MODE_CHOICES:
            return api_error(400, "VALIDATION_ERROR", _QUEUE_MODE_ERROR)
        updates["queue_mode"] = value

    if "queue_start_table" in payload:
        value = payload.get("queue_start_table")
        if value is not None:
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                return api_error(400, "VALIDATION_ERROR", _QUEUE_START_TABLE_ERROR)
            effective_table_count = updates.get("table_count", club.table_count)
            if effective_table_count is not None and value > effective_table_count:
                return api_error(400, "VALIDATION_ERROR", _QUEUE_START_TABLE_ERROR)
        updates["queue_start_table"] = value

    for field, value in updates.items():
        setattr(club, field, value)
    db.session.commit()
    return api_ok({
        "table_count": club.table_count,
        "songs_per_table": club.songs_per_table,
        "queue_mode": get_queue_mode(club),
        "queue_start_table": get_queue_start_table(club),
    })


# ДОБАВЛЕНО (2026-10-04, запрос пользователя "бот и приложение — два
# отдельных инструмента, что в боте то и в приложении, во вкладку VIP надо
# добавить то, что есть в боте") — перенос handlers/kj.py::
# vip_description_edit старого бота (кнопка "📝 Описание VIP (RU)"): KJ сам
# вписывает текст про преимущества VIP своего клуба, он показывается
# гостю в Guest App на вкладке VIP поверх фиксированного списка
# (пополнение/кешбек/повтор песен), см. routes/guest.py::me и
# guest-app App.jsx::VipPanel. По образцу table-settings выше — тот же
# паттерн get/put по club_id с _ensure_own_club.
@bp.get("/vip-settings/<int:club_id>")
@require_kj
def get_vip_settings(club_id):
    denied = _ensure_own_club(club_id)
    if denied:
        return denied
    club = db.session.get(Club, club_id)
    if club is None:
        return api_error(404, "CLUB_NOT_FOUND", "Клуб не найден")
    return api_ok({"vip_description": club.vip_description})


@bp.put("/vip-settings/<int:club_id>")
@require_kj
def update_vip_settings(club_id):
    denied = _ensure_own_club(club_id)
    if denied:
        return denied
    payload = request.get_json(silent=True) or {}
    club = db.session.get(Club, club_id)
    if club is None:
        return api_error(404, "CLUB_NOT_FOUND", "Клуб не найден")
    if "vip_description" in payload:
        value = payload.get("vip_description")
        if value is not None and not isinstance(value, str):
            return api_error(400, "VALIDATION_ERROR", "vip_description должен быть строкой или null")
        club.vip_description = (value or "").strip() or None
        db.session.commit()
    return api_ok({"vip_description": club.vip_description})


# --- Список гостей / карточка гостя (запрос пользователя 2026-09: сортировка
# VIP/Простой/Без стола, переход в карточку, блокировка, снятие со стола,
# статистика по вечеру/неделе/месяцу, избранные песни видны). guest_id —
# BigInteger, приходит строкой в URL (JS теряет точность на больших int,
# тот же принцип, что и у TableGroup.to_dict()/guest_id в токене), поэтому
# путь принимает его как строку и парсит вручную, а не через <int:...>.

def _parse_guest_id(raw: str):
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


@bp.get("/guests/<int:club_id>")
@require_kj
def list_guests(club_id):
    denied = _ensure_own_club(club_id)
    if denied:
        return denied
    guest_type = request.args.get("type")
    if guest_type is not None and guest_type not in GUEST_TYPES:
        return api_error(400, "VALIDATION_ERROR", f"type должен быть одним из: {', '.join(GUEST_TYPES)}")
    return api_ok(guest_directory_service.list_guests(club_id, guest_type))


@bp.get("/guests/<int:club_id>/<guest_id>")
@require_kj
def get_guest(club_id, guest_id):
    denied = _ensure_own_club(club_id)
    if denied:
        return denied
    parsed_id = _parse_guest_id(guest_id)
    if parsed_id is None:
        return api_error(400, "VALIDATION_ERROR", "guest_id должен быть числом")
    try:
        return api_ok(guest_directory_service.get_guest_detail(club_id, parsed_id))
    except GuestDirectoryError as exc:
        return api_error(exc.status_code, exc.code, exc.message)


@bp.get("/guests/<int:club_id>/<guest_id>/history")
@require_kj
def get_guest_history(club_id, guest_id):
    """
    История спетых песен гостя по дням, с выбором периода (запрос
    пользователя 2026-10) — см. docstring guest_directory_service.py::
    get_guest_song_history. from/to — YYYY-MM-DD, оба необязательны
    (без них — вся история целиком).
    """
    denied = _ensure_own_club(club_id)
    if denied:
        return denied
    parsed_id = _parse_guest_id(guest_id)
    if parsed_id is None:
        return api_error(400, "VALIDATION_ERROR", "guest_id должен быть числом")

    def _parse_date(raw):
        if not raw:
            return None, None
        try:
            return date.fromisoformat(raw), None
        except ValueError:
            return None, api_error(400, "VALIDATION_ERROR", "Дата должна быть в формате YYYY-MM-DD")

    date_from, err = _parse_date(request.args.get("from"))
    if err:
        return err
    date_to, err = _parse_date(request.args.get("to"))
    if err:
        return err

    return api_ok(guest_directory_service.get_guest_song_history(club_id, parsed_id, date_from, date_to))


@bp.post("/guests/<guest_id>/block")
@require_kj
def block_guest(guest_id):
    parsed_id = _parse_guest_id(guest_id)
    if parsed_id is None:
        return api_error(400, "VALIDATION_ERROR", "guest_id должен быть числом")
    status = guest_status_service.block(g.club_id, parsed_id, g.kj)
    return api_ok(status.to_dict())


@bp.put("/guests/<guest_id>/photo")
@require_kj
def set_guest_photo(guest_id):
    """
    Фото VIP-клиента в карточке/списке (запрос пользователя 2026-10-01,
    вкладка "VIP-клиенты": "давай сделаем возможным загрузить фото клиента.
    по желанию можно и не загружать. но возможность должна быть") —
    необязательное поле GuestAccount.photo_data_url (см. его докстринг в
    models.py). photo_data_url: null — убрать фото; иначе строка вида
    "data:image/...;base64,..." — фронтенд должен прислать уже уменьшенную
    картинку, здесь только защитный предел на размер самой строки.
    """
    parsed_id = _parse_guest_id(guest_id)
    if parsed_id is None:
        return api_error(400, "VALIDATION_ERROR", "guest_id должен быть числом")
    data = request.get_json(silent=True) or {}
    photo_data_url = data.get("photo_data_url")
    if photo_data_url is not None:
        if not isinstance(photo_data_url, str) or not photo_data_url.startswith("data:image/"):
            return api_error(400, "VALIDATION_ERROR", "photo_data_url должен быть изображением")
        if len(photo_data_url) > 2_000_000:
            return api_error(400, "VALIDATION_ERROR", "Фото слишком большое")
    account = GuestAccount.query.filter_by(club_id=g.club_id, telegram_user_id=parsed_id).first()
    if account is None:
        return api_error(404, "GUEST_ACCOUNT_NOT_FOUND", "Профиль гостя не найден")
    account.photo_data_url = photo_data_url
    db.session.commit()
    return api_ok(account.to_dict())


@bp.put("/guests/<guest_id>/name")
@require_kj
def rename_guest(guest_id):
    """
    KJ переименовывает гостя из своей панели (запрос пользователя 2026-10:
    "Kj должен иметь возможность сам переименовать гостя") — то же самое
    поле GuestAccount.display_name, которое гость обычно меняет себе сам
    (routes/guest.py::set_display_name) — здесь делает роль 2, той же
    функцией сервиса и тем же ограничением длины.
    """
    parsed_id = _parse_guest_id(guest_id)
    if parsed_id is None:
        return api_error(400, "VALIDATION_ERROR", "guest_id должен быть числом")
    payload = request.get_json(silent=True) or {}
    raw_name = payload.get("display_name")
    if not isinstance(raw_name, str):
        return api_error(400, "VALIDATION_ERROR", "display_name обязателен и должен быть строкой")
    name = raw_name.strip()
    if not name:
        return api_error(400, "VALIDATION_ERROR", "Имя не может быть пустым")
    if len(name) > guest_account_service.MAX_DISPLAY_NAME_LEN:
        return api_error(
            400, "VALIDATION_ERROR",
            f"Имя не должно быть длиннее {guest_account_service.MAX_DISPLAY_NAME_LEN} символов",
        )
    account = guest_account_service.set_display_name(g.club_id, parsed_id, name)
    if account is None:
        return api_error(
            404, "GUEST_ACCOUNT_NOT_FOUND",
            "У гостя ещё нет постоянного профиля — он ни разу не входил через Google",
        )
    return api_ok(account.to_dict())


@bp.post("/guests/<guest_id>/unblock")
@require_kj
def unblock_guest(guest_id):
    parsed_id = _parse_guest_id(guest_id)
    if parsed_id is None:
        return api_error(400, "VALIDATION_ERROR", "guest_id должен быть числом")
    status = guest_status_service.unblock(g.club_id, parsed_id)
    return api_ok(status.to_dict() if status else {"guest_id": guest_id, "is_blocked": False})


@bp.post("/guests/<guest_id>/remove-table")
@require_kj
def remove_guest_from_table(guest_id):
    parsed_id = _parse_guest_id(guest_id)
    if parsed_id is None:
        return api_error(400, "VALIDATION_ERROR", "guest_id должен быть числом")
    status = guest_status_service.set_table(g.club_id, parsed_id, None)
    return api_ok(status.to_dict())


@bp.post("/guests/<guest_id>/close-table")
@require_kj
def close_guest_table(guest_id):
    """
    "Закрыть стол" (запрос пользователя 2026-09-19, из карточки гостя):
    снимает гостя со стола, блокирует его и отклоняет всё ещё непроигранное
    с этого стола одним действием — см. докстринг guest_status_service.
    close_table для полной мотивации.
    """
    parsed_id = _parse_guest_id(guest_id)
    if parsed_id is None:
        return api_error(400, "VALIDATION_ERROR", "guest_id должен быть числом")
    try:
        result = guest_status_service.close_table(g.club_id, parsed_id, g.kj)
    except GuestDirectoryError as exc:
        return api_error(exc.status_code, exc.code, exc.message)
    return api_ok({
        "status": result["status"].to_dict(),
        "closed_order_ids": [order.id for order in result["closed_orders"]],
    })


# --- Запросы гостей на закрытие группового стола (запрос пользователя
# 2026-09-27, см. докстринг models.TableCloseRequest) — инициатива у
# гостя-админа стола, а не у KJ (в отличие от close_guest_table выше).
# Подтверждение освобождает TableGroup для следующей компании и считает
# чек за эту сессию стола.

@bp.get("/table-close-requests/<int:club_id>")
@require_kj
def list_table_close_requests(club_id):
    """Неразобранные (pending) заявки клуба — тот же паттерн, что и
    list_order_change_requests выше: только pending, без экрана истории."""
    denied = _ensure_own_club(club_id)
    if denied:
        return denied
    return api_ok([r.to_dict() for r in table_close_service.list_pending(club_id)])


@bp.put("/table-close-requests/<int:request_id>/approve")
@require_kj
def approve_table_close_request_route(request_id):
    """
    Подтверждение закрытия стола. hide_receipt (тело запроса, необязательно,
    по умолчанию False) — чекбокс "Не показывать чек" на экране
    подтверждения: чек всё равно считается и сохраняется, просто не
    раздаётся гостям через поллинг /api/guest/me.
    """
    payload = request.get_json(silent=True) or {}
    hide_receipt = bool(payload.get("hide_receipt", False))

    result = table_close_service.approve_request(request_id, g.kj, hide_receipt)
    if result.outcome == "not_found":
        return api_error(404, "REQUEST_NOT_FOUND", "Заявка не найдена")
    if result.outcome == "forbidden":
        return api_error(403, "FORBIDDEN", "Нет доступа к этой заявке")
    if result.outcome == "already_decided":
        return api_error(409, "ALREADY_DECIDED", "Заявка уже обработана")
    return api_ok({
        "request": result.request.to_dict(),
        "closed_order_ids": [order.id for order in result.closed_orders],
    })


@bp.put("/table-close-requests/<int:request_id>/reject")
@require_kj
def reject_table_close_request_route(request_id):
    """KJ отклоняет заявку — стол остаётся как есть, ничего не закрывается."""
    result = table_close_service.reject_request(request_id, g.kj)
    if result.outcome == "not_found":
        return api_error(404, "REQUEST_NOT_FOUND", "Заявка не найдена")
    if result.outcome == "forbidden":
        return api_error(403, "FORBIDDEN", "Нет доступа к этой заявке")
    if result.outcome == "already_decided":
        return api_error(409, "ALREADY_DECIDED", "Заявка уже обработана")
    return api_ok(result.request.to_dict())


# --- Карточка стола в KJ Panel (запрос пользователя 2026-09-28): полный
# состав компании за столом (не только те, у кого сейчас активный заказ, как
# на доске "Заказы по столам", см. table_board_service), закрытие стола сразу
# действием KJ без ожидания заявки гостя (table_close_service.
# close_table_directly) и перенос стола на новый номер целиком (table_group_
# service.move_table).

@bp.get("/table-groups/<int:club_id>")
@require_kj
def list_table_groups(club_id):
    """
    Номера сейчас занятых столов + Club.table_count — KJ Panel считает по
    ним, какие номера свободны, чтобы предложить их для переноса стола
    (см. карточку стола ниже). Сам перенос (move_table) список из
    интерфейса не использует и перепроверяет занятость по БД заново —
    это чисто подсказка для выпадающего списка, а не источник истины.
    """
    denied = _ensure_own_club(club_id)
    if denied:
        return denied
    club = db.session.get(Club, club_id)
    return api_ok({
        "table_count": club.table_count if club else None,
        "occupied_table_nos": sorted(table_group_service.list_occupied_table_nos(club_id)),
    })


@bp.get("/table-groups/<int:club_id>/<int:table_no>")
@require_kj
def get_table_group(club_id, table_no):
    """
    Карточка стола — полный список гостей за столом (TableGroupMember), в
    отличие от доски "Заказы по столам", которая показывает только места с
    активными заказами. Каждый участник — тем же форматом, что и в самой
    карточке гостя (guest_directory_service.get_guest_detail), без списка
    избранного — он не нужен на этом экране, только когда KJ провалится в
    карточку конкретного гостя кликом.
    """
    denied = _ensure_own_club(club_id)
    if denied:
        return denied
    group = table_group_service.get_group(club_id, table_no)
    if group is None:
        return api_error(404, "TABLE_EMPTY", "За этим столом сейчас никого нет")

    members = (
        TableGroupMember.query
        .filter_by(club_id=club_id, table_no=table_no)
        .order_by(TableGroupMember.joined_at.asc())
        .all()
    )
    roster = []
    for member in members:
        try:
            detail = guest_directory_service.get_guest_detail(club_id, member.guest_id)
        except GuestDirectoryError:
            # Строка членства есть, а собрать карточку гостя не вышло —
            # не должно происходить в штатной работе (членство появляется
            # вместе с первым выбором стола, см. docstring table_group_
            # service.ensure_session_group_state), но карточку стола из-за
            # одного гостя всё равно не роняем.
            detail = {
                "guest_id": str(member.guest_id), "display_name": None, "email": None,
                "guest_type": "client", "table_no": table_no, "is_blocked": False,
                "orders_evening": 0, "orders_week": 0, "orders_month": 0,
                "vip_balance": None, "vip_cashback_percent": None,
                "last_song_title": None, "last_artist": None, "last_activity_at": None,
            }
        detail.pop("favorites", None)
        detail["is_admin"] = member.guest_id == group.admin_guest_id
        roster.append(detail)

    # ДОБАВЛЕНО (запрос пользователя 2026-09-30, кнопка "Вернуть" на
    # карточке стола): песни этой сессии стола, уже отмеченные сыгранными
    # (mark_played(), вручную или в будущем автоматически по истории
    # VirtualDJ), но ещё не списанные — списание происходит только одной
    # суммой при закрытии стола (table_close_service.complete_table_orders).
    # KJ видит их здесь и может передумать по любой из них ДО закрытия —
    # см. PUT /order/<id>/reject выше, он теперь принимает и STATUS_PLAYING.
    played_orders = (
        Order.query
        .filter(
            Order.club_id == club_id,
            Order.table_no == table_no,
            Order.status == STATUS_PLAYING,
            Order.created_at >= group.created_at,
        )
        .order_by(Order.playing_at.asc())
        .all()
    )

    return api_ok({
        "table_no": table_no,
        "created_at": group.created_at.isoformat() if group.created_at else None,
        "admin_guest_id": str(group.admin_guest_id),
        "members": roster,
        "played_orders": [o.to_dict() for o in played_orders],
    })


@bp.put("/table-groups/<int:club_id>/<int:table_no>/close")
@require_kj
def close_table_group_route(club_id, table_no):
    """Закрыть стол сразу с его карточки, без заявки гостя — см. docstring
    table_close_service.close_table_directly. Тело как и у approve заявки:
    {"hide_receipt": bool}, необязательно, по умолчанию False."""
    denied = _ensure_own_club(club_id)
    if denied:
        return denied
    payload = request.get_json(silent=True) or {}
    hide_receipt = bool(payload.get("hide_receipt", False))

    result = table_close_service.close_table_directly(club_id, table_no, g.kj, hide_receipt)
    if result.outcome == "not_found":
        return api_error(404, "TABLE_EMPTY", "За этим столом сейчас никого нет")
    return api_ok({
        "request": result.request.to_dict(),
        "closed_order_ids": [order.id for order in result.closed_orders],
    })


@bp.put("/table-groups/<int:club_id>/close-all")
@require_kj
def close_all_table_groups_route(club_id):
    """"Закрыть все столы" (запрос пользователя 2026-09-29: "просто закрывает
    вечер, когда все ушли с караоке") — см. docstring table_close_service.
    close_all_tables. Без тела и без чека (уточнение пользователя: "столы,
    на которые требуются чеки, я закрываю отдельно. Потом отдельной кнопкой
    я закрываю столы") — в отличие от закрытия одного стола, здесь нет
    выбора "показать чек или нет", чек не показывается никогда."""
    denied = _ensure_own_club(club_id)
    if denied:
        return denied

    result = table_close_service.close_all_tables(club_id, g.kj)
    return api_ok({
        "closed_table_nos": result.closed_table_nos,
    })


@bp.put("/table-groups/<int:club_id>/<int:table_no>/move")
@require_kj
def move_table_group_route(club_id, table_no):
    """
    Перенести стол на новый номер целиком — см. docstring table_group_
    service.move_table. Тело: {"new_table_no": int}. KJ Panel сама не даёт
    выбрать занятый стол назначения (см. list_table_groups выше), поэтому
    "занято" здесь — по сути только защита от гонки, а не ожидаемый путь.
    """
    denied = _ensure_own_club(club_id)
    if denied:
        return denied
    payload = request.get_json(silent=True) or {}
    new_table_no = payload.get("new_table_no")
    if not isinstance(new_table_no, int) or isinstance(new_table_no, bool) or new_table_no < 1:
        return api_error(400, "VALIDATION_ERROR", "new_table_no должен быть положительным числом")

    club = db.session.get(Club, club_id)
    if club and club.table_count and new_table_no > club.table_count:
        return api_error(400, "VALIDATION_ERROR", f"В клубе только {club.table_count} столов")

    result = table_group_service.move_table(club_id, table_no, new_table_no)
    if result.outcome == "not_found":
        return api_error(404, "TABLE_EMPTY", "За этим столом сейчас никого нет")
    if result.outcome == "same_table":
        return api_error(400, "VALIDATION_ERROR", "Новый номер совпадает с текущим")
    if result.outcome == "destination_occupied":
        return api_error(409, "TABLE_OCCUPIED", "Стол назначения уже занят другой компанией")

    emit_table_group_moved(club_id, table_no, new_table_no)
    return api_ok({
        "table_no": new_table_no,
        "member_guest_ids": [str(guest_id) for guest_id in result.member_guest_ids],
    })


# --- Статус моста VirtualDJ (запрос пользователя 2026-09: "переключатель"
# для контроля — светофор в KJ Panel, подключён ли сейчас мост). Живое
# состояние, не БД — см. докстринг vdj/bridge_status.py. Здесь REST-эндпоинт
# только для первого запроса при открытии KJ Panel (пока WebSocket ещё не
# успел получить ни одного события bridge_status, см. sockets.py) —
# дальнейшие изменения статуса приходят уже сокетом, без поллинга.

@bp.get("/bridge/status/<int:club_id>")
@require_kj
def get_bridge_status(club_id):
    denied = _ensure_own_club(club_id)
    if denied:
        return denied
    since = bridge_status.connected_since(club_id)
    return api_ok({
        "connected": bridge_status.is_connected(club_id),
        "connected_since": since.isoformat() if since else None,
        # 2026-09-17 (панель обзора KJ, индикатор "Мост↔VirtualDJ"): True/
        # False — мост проверял VirtualDJ и получил/не получил ответ; None —
        # мост либо не подключён вовсе (connected=False), либо подключён,
        # но ещё не успел ни разу проверить (первые секунды после connect).
        "vdj_reachable": bridge_status.vdj_reachable(club_id),
    })
