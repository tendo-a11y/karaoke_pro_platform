from decimal import Decimal, InvalidOperation

from flask import Blueprint, g, jsonify, request

from auth import require_kj
from errors import api_error, api_ok
from extensions import db
from models import ChatMessage, Order, VipClient, VipRequest
from services import category_service, song_service, vip_service
from services.category_service import CategoryServiceError
from services.vdj_service import add_manual_song, confirm_order, get_kj_queue_view, reject_order
from sockets import emit_chat_message

bp = Blueprint("kj", __name__, url_prefix="/api/kj")


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
    "vdj_error": (502, "VDJ_UNAVAILABLE", "Не удалось добавить песню в VirtualDJ"),
}


@bp.put("/order/<int:order_id>/confirm")
@require_kj
def confirm(order_id):
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

    if not isinstance(telegram_user_id, int):
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
    return api_ok([c.to_dict() for c in clients])


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
