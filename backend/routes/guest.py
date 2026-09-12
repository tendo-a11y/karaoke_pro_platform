import secrets

from flask import Blueprint, current_app, g, request

from auth import issue_guest_token, require_guest
from errors import api_error, api_ok
from extensions import db
from models import STATUS_ERROR, STATUS_REJECTED, ChatMessage, Club, Order, Service
from services import ai_search_service, guest_account_service, song_service, table_group_service, vdj_service, vip_service
from services.google_auth_service import GoogleAuthError, verify_google_credential
from sockets import emit_chat_message, emit_order_created, emit_vip_request_created
from vdj import get_vdj_client

bp = Blueprint("guest", __name__, url_prefix="/api/guest")


def _new_guest_id() -> int:
    """
    Случайный идентификатор анонимного гостя. Помещается в то же поле
    Order.telegram_user_id (BigInteger), что и настоящие Telegram ID из
    старого бота-пути (/api/client/order) — оба пути пишут в одну и ту же
    колонку, оба вида значений одинаково уникальны и используются в коде
    только как непрозрачный идентификатор "чей это заказ", так что
    смешивать их в одной колонке безопасно на этом шаге. Сам вопрос
    переименования/типизации этого поля под Guest App (ТЗ §54) остаётся
    открытым — см. комментарий у Order.telegram_user_id в models.py.
    62 бита — гарантированно помещается в BigInteger и практически
    исключает коллизии в пределах одного клуба за вечер.
    """
    return secrets.randbits(62)


@bp.post("/session")
def create_session():
    """
    Первый вызов Guest App при открытии ссылки/QR-кода — аналог старого
    deep-link venue{id}_table{n} в Telegram-боте (bot.py), но по
    финальной единой модели входа (ТЗ п.45) QR-код НИКОГДА не содержит
    номер стола: сессия всегда создаётся без стола (table_no всегда
    null), независимо от того, какой QR отсканирован. Без авторизации —
    сама возможность создать сессию для club_id и есть право находиться
    в этом клубе (см. issue_guest_token в auth.py — подробное обоснование
    модели доверия).

    Стол выбирается позже, вместе с обязательным входом через Google, в
    одном действии — см. POST /api/guest/profile/link-google. До этого
    момента доступны только просмотр очереди и выбор песни в форму
    (Role 5); сам заказ недоступен.
    """
    payload = request.get_json(silent=True) or {}
    club_id = payload.get("club_id")

    if not isinstance(club_id, int):
        return api_error(400, "VALIDATION_ERROR", "club_id обязателен и должен быть числом")

    club = db.session.get(Club, club_id)
    if club is None or not club.is_active:
        return api_error(404, "CLUB_NOT_FOUND", "Клуб не найден или отключён")

    guest_id = _new_guest_id()
    token = issue_guest_token(
        guest_id, club_id, None,
        current_app.config["GUEST_JWT_SECRET"], current_app.config["GUEST_JWT_TTL_SECONDS"],
    )

    # guest_id — строкой в JSON: см. комментарий у TableGroup.to_dict()
    # (models.py) — 62-битные значения теряют точность в JS Number, и
    # своя идентичность (сравнение "это я?" в TableGroupPanel) должна
    # совпадать посимвольно с guest_id из /table-group, который отдаётся
    # строкой по той же причине.
    return api_ok({"guest_id": str(guest_id), "club_id": club_id, "table_no": None, "token": token})


def _guest_type_and_vip(club_id: int, guest_id: int):
    """
    Единое место, где решается роль гостя (Role 3 vs Role 4/5) — по факту
    наличия VipClient с этим (club_id, guest_id), см. services/vip_service.py.
    VIP определяется так же, как определялся бы Telegram-VIP в старом боте
    (наличие строки vip_clients) — постоянство личности при этом
    обеспечивает GuestAccount (ТЗ п.45), а не сам факт быть VIP.
    """
    vip = vip_service.get_vip_client(club_id, guest_id)
    if vip is not None:
        return "vip", vip
    return None, None


@bp.get("/me")
@require_guest
def me():
    """
    Нужна фронтенду сразу после создания сессии, чтобы знать, за каким
    столом/в каком клубе он находится — по образцу /api/kj/me,
    /api/admin/me. С этого шага также определяет VIP-статус (Role 3) —
    см. _guest_type_and_vip выше.
    """
    club = db.session.get(Club, g.club_id)
    guest_type, vip = _guest_type_and_vip(g.club_id, g.guest_id)

    pending_request = vip_service.get_pending_vip_request(g.club_id, g.guest_id)
    has_permanent_profile = guest_account_service.get_by_guest_id(g.club_id, g.guest_id) is not None

    # Групповой стол — статус пересчитывается заново на каждый опрос (а не
    # берётся из токена), потому что JWT не переиздаётся при одобрении
    # (см. docstring table_group_service) — фронтенд узнаёт об одобрении
    # именно через периодический опрос этого поля.
    table_group_status = None
    if g.table_no is not None:
        group = table_group_service.get_group(g.club_id, g.table_no)
        if group is not None and group.admin_guest_id == g.guest_id:
            table_group_status = "admin"
        elif table_group_service.is_member(g.club_id, g.table_no, g.guest_id):
            table_group_status = "member"
        elif table_group_service.has_pending_request(g.club_id, g.table_no, g.guest_id):
            table_group_status = "pending"
        else:
            # Гостя кикнули, он сам вышел, или его заявку отклонили — не
            # трактуем это как "pending" (заявки сейчас нет вообще), фронтенд
            # должен предложить запросить присоединение заново
            # (POST /table-group/request-join), а не показывать "ждите".
            table_group_status = "not_joined"

    return api_ok({
        # Строкой — см. комментарий в create_session выше.
        "guest_id": str(g.guest_id),
        "club_id": g.club_id,
        "table_no": g.table_no,
        "table_group_status": table_group_status,
        "club_name": club.name if club else None,
        # Guest App использует это, чтобы решить, показывать ли вообще UI
        # чата — а не только полагаться на 403 CHAT_DISABLED после попытки
        # отправить сообщение (POST /chat уже проверяет это на сервере
        # независимо, см. send_chat_message ниже — здесь только для UX).
        "chat_enabled": bool(club.chat_enabled) if club else False,
        "is_vip": guest_type == "vip",
        # ТЗ п.45 — есть ли у гостя постоянный профиль (Google уже
        # привязан). Фронтенд использует это вместе с table_no==null, чтобы решить,
        # показывать ли единственный экран "выберите стол и войдите через
        # Google" (см. POST /profile/link-google) — до входа стола нет и
        # заказ недоступен, независимо от того, каким QR открыто приложение.
        "has_permanent_profile": has_permanent_profile,
        # Старое: handlers/vip.py::vip_profile (баланс/кэшбэк), п.9-10-11
        # отчёта по Role 3/4/5. join date (added_at) старый бот тоже нигде
        # не показывал — не добавляем и здесь, чтобы не изобретать поле,
        # которого не было в UI старой системы.
        "vip": {"balance": float(vip.balance), "cashback_percent": float(vip.cashback_percent)}
        if vip else None,
        "vip_request_pending": pending_request is not None,
    })


@bp.post("/order")
@require_guest
def create_order():
    """
    Гостевое создание заказа через Guest App — параллельный путь к
    /api/client/order (тот остаётся для старого Telegram-бота, ТЗ п.7,
    старая система не должна сломаться до полной миграции). club_id/
    table_no/telegram_user_id(=guest_id) берутся ТОЛЬКО из проверенного
    токена (g.*), а не из тела запроса — тело даёт только сами данные
    песни.

    guest_type: определяется по факту VIP-идентификации (см.
    _guest_type_and_vip выше) — "vip", иначе "no_table" при отсутствии
    стола, иначе "client" (1:1 старое деление ролей 3/4/5).

    ТЗ п.45 (финальная единая модель входа): стол и постоянный профиль
    появляются только вместе, одним действием, через POST
    /api/guest/profile/link-google — до этого гость (Role 5) может
    смотреть очередь и выбрать песню в форму, но не может нажать
    "Заказать": сначала он получит TABLE_REQUIRED (стола ещё нет вообще),
    а если стол уже выбран, но профиль почему-то не подтверждён —
    GOOGLE_LINK_REQUIRED (см. проверки ниже).

    service_id (тариф) — необязателен (заказ без выбранной услуги
    по-прежнему допустим, как и раньше в этом шаге), но если передан,
    должен существовать и принадлежать этому же клубу — иначе на
    completion (services/billing_service.py) он просто тихо не будет
    найден, лучше отклонить сразу с понятной ошибкой.

    Лимит активных песен (старое: MAX_ACTIVE_SONGS_PER_USER=2, аудит Role
    3/4/5 п.6) — проверяется здесь так же, как в старом коде, ДО создания
    заказа.

    Групповой стол (утверждённая спецификация, вариант А — полноценный
    шлюз): если у гостя есть стол, заказывать можно только будучи
    одобренным участником (или админом) группы этого стола — единственная
    проверка шлюза во всём этом эндпоинте, без переиздания токена (см.
    docstring table_group_service.ensure_session_group_state).
    """
    payload = request.get_json(silent=True) or {}
    song_title = payload.get("song_title")
    artist = payload.get("artist")
    service_id = payload.get("service_id")

    if not song_title or not isinstance(song_title, str):
        return api_error(400, "VALIDATION_ERROR", "song_title обязателен")

    # ТЗ п.45: смотреть очередь и выбирать песню в форму можно сразу после
    # открытия приложения, а заказывать — только выбрав стол (единственный
    # способ это сделать — POST /api/guest/profile/link-google ниже, где
    # стол выбирается вместе со входом через Google, одним действием).
    if g.table_no is None:
        return api_error(
            409, "TABLE_REQUIRED",
            "Чтобы заказать песню, сначала выберите стол",
        )

    if guest_account_service.get_by_guest_id(g.club_id, g.guest_id) is None:
        return api_error(
            409, "GOOGLE_LINK_REQUIRED",
            "Чтобы заказать песню, сначала войдите через Google",
        )

    if not table_group_service.is_member(g.club_id, g.table_no, g.guest_id):
        return api_error(
            403, "TABLE_ACCESS_REQUIRED",
            "У вас нет доступа к заказам за этим столом — нужно быть одобренным участником группы",
        )

    if service_id is not None:
        if not isinstance(service_id, int):
            return api_error(400, "VALIDATION_ERROR", "service_id должен быть числом")
        service = db.session.get(Service, service_id)
        if service is None or service.club_id != g.club_id:
            return api_error(404, "SERVICE_NOT_FOUND", "Услуга не найдена")

    active_count = vip_service.count_active_orders(g.club_id, g.guest_id)
    max_active = current_app.config["MAX_ACTIVE_SONGS_PER_GUEST"]
    if active_count >= max_active:
        return api_error(
            409, "ACTIVE_SONGS_LIMIT",
            f"Можно иметь не более {max_active} заказов одновременно — дождитесь, пока сыграет текущий",
        )

    detected_guest_type, _vip = _guest_type_and_vip(g.club_id, g.guest_id)
    guest_type = detected_guest_type or ("no_table" if g.table_no is None else "client")

    order = Order(
        telegram_user_id=g.guest_id,
        club_id=g.club_id,
        table_no=g.table_no,
        guest_type=guest_type,
        song_title=song_title,
        artist=artist,
        service_id=service_id,
        source="guest",
        channel="webapp",
    )
    db.session.add(order)
    db.session.commit()

    emit_order_created(order)

    return api_ok(order.to_dict(), status_code=201)


@bp.get("/services")
@require_guest
def list_services():
    """Тарифы клуба (старое: services/venue_services, аудит п.12) — гость
    видит одинаковый прайс независимо от роли; VIP просто может расплатиться
    балансом при завершении песни (billing_service), не-VIP — вне бота."""
    services = Service.query.filter_by(club_id=g.club_id).order_by(Service.id.asc()).all()
    return api_ok([s.to_dict() for s in services])


@bp.get("/songs/search")
@require_guest
def search_songs():
    """
    Старое: bot.py::inline_search без спецпрефиксов "kj:"/"replace:" (аудит
    п.1) — доступно любому гостю клуба (VIP/клиент со столом/без стола,
    Role 3/4/5 — старый код тоже не ограничивал по роли, только по наличию
    venue_id). Префиксы "kj:" (ручное добавление KJ) и "replace:" (замена
    песни, к тому же не проверявшая в старом коде владельца заказа — аудит,
    находка №3) сюда сознательно не перенесены: это отдельные, ещё не
    реализованные функции, а не часть самого поиска.
    """
    query = request.args.get("q", "")
    songs = song_service.search_songs(g.club_id, query)
    return api_ok([s.to_dict() for s in songs])


@bp.post("/songs/ai-search")
@require_guest
def ai_search_songs():
    """
    Старое: /ai команда бота + ai_search_handlers.py + ai_search.py (аудит
    п.2) — свободное текстовое описание песни -> Claude извлекает 1-3
    вероятных "исполнитель - название" -> Genius ищет реальные треки.
    Доступно любому типу гостя, как и старая команда /ai (проверки роли не
    было). Результат — НЕ из каталога клуба (нет id) и не создаёт заказ сам
    по себе; выбор конкретного варианта на фронтенде заполняет обычную форму
    заказа — та же самая адаптация под веб-UI, что и у GET /songs/search
    (п.1), тот же существующий /api/guest/order с лимитом активных песен
    подхватывается автоматически, без дублирования этой логики здесь.
    """
    payload = request.get_json(silent=True) or {}
    text = payload.get("text", "")
    if not isinstance(text, str) or not text.strip():
        return api_error(400, "VALIDATION_ERROR", "text обязателен и должен быть непустой строкой")

    results = ai_search_service.ai_powered_search(text.strip())
    return api_ok(results)


@bp.post("/vip/request")
@require_guest
def request_vip():
    """Старое: handlers/client.py::request_vip_status (аудит п.8А)."""
    existing = vip_service.get_pending_vip_request(g.club_id, g.guest_id)
    if existing is not None:
        return api_error(409, "VIP_REQUEST_PENDING", "Заявка уже отправлена, ждите решения KJ")

    existing_vip = vip_service.get_vip_client(g.club_id, g.guest_id)
    if existing_vip is not None:
        return api_error(409, "ALREADY_VIP", "Вы уже VIP")

    result = vip_service.create_vip_request(g.club_id, g.guest_id, g.table_no)
    if result.outcome == "requires_google_link":
        return api_error(
            409, "GOOGLE_LINK_REQUIRED",
            "Чтобы подать заявку на VIP, сначала сохраните профиль через Google",
        )

    emit_vip_request_created(result.request)
    return api_ok(result.request.to_dict(), status_code=201)


@bp.post("/profile/link-google")
@require_guest
def link_google():
    """
    ТЗ п.45 — единственный экран "выберите стол и войдите через Google":
    номер стола и постоянная идентификация гостя устанавливаются здесь
    ОДНИМ действием (заменяет прежний механизм access_code/redeem,
    удалён целиком, и прежнее деление на "способ 1"/"способ 2" — QR
    больше никогда не приносит номер стола сам по себе). table_no
    обязателен в теле запроса, если у гостя ещё вообще нет стола (до этого
    вызова он может только смотреть очередь и выбирать песню в форму, но
    не заказывать); если стол уже выбран этим же способом ранее, а гость
    сейчас лишь переключается на другой уже существующий Google-аккаунт —
    table_no можно не передавать снова, тогда используется уже известный
    стол. После успешного вызова гость получает стол, постоянный профиль и
    становится Role 4 (или 3, если уже был одобрен как VIP).

    guest_account_service.link_google САМ решает: если для этого
    Google-аккаунта в этом клубе уже есть постоянный профиль — им
    становится ОН (то немногое, что гость успел сделать в текущей сессии
    ДО этого вызова, теряется — редкий случай "уже привязывал с другого
    устройства", решение по п.45); если аккаунта ещё нет — постоянным
    номером становится ТЕКУЩИЙ guest_id этой сессии, поэтому всё, что
    гость уже заказал/добавил в избранное до этого вызова, никуда не
    девается — оно и так уже записано на этот номер.
    """
    payload = request.get_json(silent=True) or {}
    credential = payload.get("google_credential")
    table_no = payload.get("table_no")

    if table_no is None:
        if g.table_no is None:
            return api_error(400, "VALIDATION_ERROR", "table_no обязателен — сначала выберите стол")
        effective_table_no = g.table_no
    else:
        if not isinstance(table_no, int) or isinstance(table_no, bool) or table_no <= 0:
            return api_error(400, "VALIDATION_ERROR", "table_no должен быть положительным числом")
        # KJ-04 доп. ТЗ "KJ Pro": у клуба может быть настроено количество
        # столов (Club.table_count, KJ управляет им через
        # PUT /api/kj/table-settings/<club_id>) — старый бот проверял именно
        # здесь (bot.py/handlers/client.py: table_number > venue.table_count
        # -> "table_count_exceeded"). table_count=None означает "без
        # ограничения" (клуб ещё не настроил) — тогда пропускаем проверку.
        club = db.session.get(Club, g.club_id)
        if club is not None and club.table_count is not None and table_no > club.table_count:
            return api_error(
                400, "TABLE_OUT_OF_RANGE",
                f"В этом клубе {club.table_count} столов — выберите номер от 1 до {club.table_count}",
            )
        effective_table_no = table_no

    try:
        identity = verify_google_credential(
            current_app.config["GOOGLE_AUTH_MODE"], current_app.config["GOOGLE_CLIENT_ID"], credential,
        )
    except GoogleAuthError as exc:
        return api_error(401, "GOOGLE_AUTH_FAILED", exc.message)

    result = guest_account_service.link_google(g.club_id, g.guest_id, identity["sub"], identity.get("email"))
    new_guest_id = result.account.telegram_user_id

    # Групповой стол: если постоянная личность отличается от текущей
    # (нашёлся уже существовавший профиль) — переносим членство/заявку по
    # той же логике, что раньше применялась к погашению VIP-кода (см.
    # docstring table_group_service.transfer_identity — сама разбирается,
    # что переносить нечего, если у гостя ещё не было стола). Групповое
    # состояние на выбранном столе создаётся/подтверждается для итоговой
    # личности в любом случае — стол выбирается здесь всегда впервые.
    if new_guest_id != g.guest_id:
        table_group_service.transfer_identity(g.club_id, effective_table_no, g.guest_id, new_guest_id)
    table_group_state = table_group_service.ensure_session_group_state(g.club_id, effective_table_no, new_guest_id)

    token = issue_guest_token(
        new_guest_id, g.club_id, effective_table_no,
        current_app.config["GUEST_JWT_SECRET"], current_app.config["GUEST_JWT_TTL_SECONDS"],
    )
    return api_ok({
        # Строкой — см. комментарий в create_session выше.
        "guest_id": str(new_guest_id), "club_id": g.club_id, "table_no": effective_table_no,
        "token": token, "table_group_status": table_group_state.status,
        "account": result.account.to_dict(),
    })


@bp.get("/vip/transactions")
@require_guest
def list_vip_transactions():
    """
    Старое: handlers/vip.py::vip_finances (аудит-отчёт по Finance/cashback
    history) — 4 отдельные секции по типу с промежуточными итогами,
    Telegram-сообщение. Здесь по решению — единая хронологическая лента
    (мобильный React-список), одним запросом, включая ручные корректировки
    KJ (topup/manual_debit), которые в старом боте гостю не были видны
    вообще (аудит, найденный баг №7 по VIP-пополнению).

    ?days=N — необязательный период (как старые кнопки
    сегодня/неделя/месяц), без параметра — последние `limit` операций без
    ограничения по дате.
    """
    days = request.args.get("days", type=int)
    transactions = vip_service.list_transactions(g.club_id, g.guest_id, days=days)
    return api_ok([
        {
            "id": tx.id,
            "amount": float(tx.amount),
            "type": tx.type,
            "description": tx.description,
            "order_id": tx.order_id,
            "created_at": tx.created_at.isoformat() if tx.created_at else None,
        }
        for tx in transactions
    ])


@bp.post("/favorites")
@require_guest
def add_favorite():
    """Старое: handlers/client.py::order_favorite (аудит п.3). Здесь без
    привязки к каталогу песен (его пока нет, см. отчёт п.1) — песня
    сохраняется как есть."""
    payload = request.get_json(silent=True) or {}
    song_title = payload.get("song_title")
    artist = payload.get("artist")
    service_id = payload.get("service_id")

    if not song_title or not isinstance(song_title, str):
        return api_error(400, "VALIDATION_ERROR", "song_title обязателен")
    if service_id is not None:
        if not isinstance(service_id, int):
            return api_error(400, "VALIDATION_ERROR", "service_id должен быть числом")
        service = db.session.get(Service, service_id)
        if service is None or service.club_id != g.club_id:
            return api_error(404, "SERVICE_NOT_FOUND", "Услуга не найдена")

    favorite = vip_service.add_favorite(g.club_id, g.guest_id, song_title, artist, service_id)
    return api_ok(favorite.to_dict(), status_code=201)


@bp.get("/favorites")
@require_guest
def list_favorites():
    favorites = vip_service.list_favorites(g.club_id, g.guest_id)
    return api_ok([f.to_dict() for f in favorites])


@bp.delete("/favorites/<int:favorite_id>")
@require_guest
def delete_favorite(favorite_id):
    result = vip_service.remove_favorite(g.club_id, g.guest_id, favorite_id)
    if result.outcome == "not_found":
        return api_error(404, "FAVORITE_NOT_FOUND", "Не найдено")
    if result.outcome == "forbidden":
        return api_error(403, "FORBIDDEN", "Это не ваше избранное")
    return api_ok({"deleted": True})


@bp.post("/favorites/<int:favorite_id>/reorder")
@require_guest
def reorder_favorite(favorite_id):
    """Старое: handlers/client.py|vip.py::fav_reorder (аудит п.3-4) —
    "повторный заказ" в старой системе — это и есть заказ из избранного,
    отдельного экрана истории с кнопкой "заказать снова" не было.

    Тот же шлюз группового стола, что и в create_order выше — заказ из
    избранного создаёт настоящий Order за столом гостя, поэтому проверка
    членства обязательна и здесь, а не только в основном пути заказа.

    ТЗ п.45: тот же гейт "без стола заказ недоступен" и "без Google заказ
    недоступен", что и в create_order.
    """
    if g.table_no is None:
        return api_error(409, "TABLE_REQUIRED", "Чтобы заказать песню, сначала выберите стол")

    if guest_account_service.get_by_guest_id(g.club_id, g.guest_id) is None:
        return api_error(409, "GOOGLE_LINK_REQUIRED", "Чтобы заказать песню, сначала войдите через Google")

    if not table_group_service.is_member(g.club_id, g.table_no, g.guest_id):
        return api_error(
            403, "TABLE_ACCESS_REQUIRED",
            "У вас нет доступа к заказам за этим столом — нужно быть одобренным участником группы",
        )

    guest_type, _vip = _guest_type_and_vip(g.club_id, g.guest_id)
    guest_type = guest_type or ("no_table" if g.table_no is None else "client")
    max_active = current_app.config["MAX_ACTIVE_SONGS_PER_GUEST"]

    result = vip_service.reorder_favorite(
        g.club_id, g.guest_id, g.table_no, guest_type, favorite_id, max_active,
    )
    if result.outcome == "not_found":
        return api_error(404, "FAVORITE_NOT_FOUND", "Не найдено")
    if result.outcome == "forbidden":
        return api_error(403, "FORBIDDEN", "Это не ваше избранное")
    if result.outcome == "limit_reached":
        return api_error(
            409, "ACTIVE_SONGS_LIMIT",
            f"Можно иметь не более {max_active} заказов одновременно — дождитесь, пока сыграет текущий",
        )

    emit_order_created(result.order)
    return api_ok(result.order.to_dict(), status_code=201)


@bp.post("/order/<int:order_id>/replace")
@require_guest
def replace_order(order_id):
    """
    Замена песни в уже созданном заказе (старое: handlers/client.py
    order_action/order_replace/replace_svc_execute — согласованная и
    утверждённая пользователем спецификация замены песни).

    club_id/guest_id берутся ТОЛЬКО из проверенного токена (g.*), как и в
    create_order выше — владелец заказа проверяется в vdj_service.replace_order,
    HTTP-слой лишь маппит её outcome на коды ответа.
    """
    payload = request.get_json(silent=True) or {}
    song_title = payload.get("song_title")
    artist = payload.get("artist")
    service_id = payload.get("service_id")

    if not song_title or not isinstance(song_title, str):
        return api_error(400, "VALIDATION_ERROR", "song_title обязателен")
    if service_id is not None and not isinstance(service_id, int):
        return api_error(400, "VALIDATION_ERROR", "service_id должен быть числом")

    order, outcome = vdj_service.replace_order(
        order_id, g.guest_id, g.club_id, song_title, artist, service_id,
    )

    if outcome == "not_found":
        return api_error(404, "ORDER_NOT_FOUND", "Заказ не найден")
    if outcome == "forbidden":
        return api_error(403, "FORBIDDEN", "Это не ваш заказ")
    if outcome == "not_allowed":
        return api_error(
            409, "REPLACE_NOT_ALLOWED",
            "Эту песню уже нельзя заменить — заказ обрабатывается или скоро прозвучит",
        )
    if outcome == "service_not_found":
        return api_error(404, "SERVICE_NOT_FOUND", "Услуга не найдена")

    return api_ok(order.to_dict())


@bp.get("/orders")
@require_guest
def list_my_orders():
    """
    Заказы этого же гостя (той же анонимной сессии) в этом клубе.

    can_replace — вычисляется здесь же (по утверждённой матрице замены песни,
    см. vdj_service.can_replace_order), а не отдельным эндпоинтом: фронтенду
    нужно решить, показывать ли кнопку "Заменить" уже в списке заказов, без
    лишнего round-trip на каждую строку.

    ?days=N — необязательный фильтр по периоду (старое: handlers/vip.py
    ::vip_order_history, только для VIP, аудит по "Фильтрация истории
    заказов"). Здесь доступно всем ролям — это не новая бизнес-логика, а
    следствие того, что /orders в новой архитектуре и так один общий
    эндпоинт для всех, старое разделение по ролям для этого экрана не
    переносилось. Фильтруем по created_at (когда заказан), а не completed_at
    — иначе из ленты пропадали бы ещё не сыгранные заказы текущего периода
    (completed_at у них NULL), что было бы регрессией: гость смотрит на
    "мои заказы" как на живой список, а не только на историю сыгранного.
    Сравнение — timezone-aware datetime (тот же приём, что и в
    vip_service.list_transactions), без старого бага со строковым
    DATE('now', ...) и без бага отображения UTC как локального времени.

    Отклонённые (rejected) и с ошибкой (error) заказы сюда намеренно не
    попадают (решение пользователя, живой тест 2026-09): гостю в его
    собственном списке они не нужны и только захламляют историю — он видит
    там только то, что ещё в очереди/играется, и то, что уже спето. У KJ в
    его собственной панели эти заказы по-прежнему видны как обычно, этот
    фильтр касается только эндпоинта гостя.
    """
    query = Order.query.filter_by(club_id=g.club_id, telegram_user_id=g.guest_id).filter(
        Order.status.notin_([STATUS_REJECTED, STATUS_ERROR])
    )
    days = request.args.get("days", type=int)
    if days is not None:
        from datetime import datetime, timedelta, timezone
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        query = query.filter(Order.created_at >= cutoff)
    orders = query.order_by(Order.created_at.asc()).all()
    vdj = get_vdj_client(g.club_id)
    result = []
    for order in orders:
        data = order.to_dict()
        data["can_replace"] = vdj_service.can_replace_order(order, vdj)
        result.append(data)
    return api_ok(result)


def _require_table(f):
    """Общая проверка для всех /table-group/* эндпоинтов ниже — они имеют
    смысл только у гостя со столом (Role 5 эта механика не касается,
    утверждённое решение)."""
    from functools import wraps

    @wraps(f)
    def wrapper(*args, **kwargs):
        if g.table_no is None:
            return api_error(400, "NO_TABLE", "У вас нет стола — групповой стол недоступен")
        return f(*args, **kwargs)
    return wrapper


@bp.get("/table-group")
@require_guest
@_require_table
def get_table_group():
    """
    Состояние группового стола гостя — участники (в порядке входа, кто
    админ) и, только если сам вызывающий админ, список ожидающих заявок на
    вход (аналог старого table_group_manage, bot.py:1064-1098, но без
    сокрытия самого факта существования группы от не-админов — им тоже
    нужно видеть список участников и свою кнопку "Покинуть стол").
    """
    view = table_group_service.get_group_view(g.club_id, g.table_no, g.guest_id)
    if view.outcome == "no_group":
        return api_ok({"group": None, "members": [], "pending_requests": [], "is_admin": False})

    return api_ok({
        "group": view.group.to_dict(),
        "is_admin": view.group.admin_guest_id == g.guest_id,
        "members": [
            {**m.to_dict(), "is_admin": m.guest_id == view.group.admin_guest_id}
            for m in view.members
        ],
        "pending_requests": [r.to_dict() for r in view.pending_requests],
    })


@bp.post("/table-group/request-join")
@require_guest
@_require_table
def request_table_group_join():
    """
    Явный повторный запрос присоединения — например, после того как гостя
    кикнули, он сам вышел, или его заявку отклонили (table_group_status
    "not_joined" в /me, см. выше). В отличие от POST /api/guest/session, НЕ
    выдаёт новый guest_id/токен — гость не должен терять историю своих
    заказов ради того, чтобы попроситься обратно. Просто повторяет ту же
    атомарную логику ensure_session_group_state под уже существующей
    личностью (той же, что и раньше — быть может, снова станет админом,
    если стол за это время опустел).
    """
    state = table_group_service.ensure_session_group_state(g.club_id, g.table_no, g.guest_id)
    return api_ok({"status": state.status})


@bp.post("/table-group/join-requests/<int:request_id>/approve")
@require_guest
@_require_table
def approve_table_join_request(request_id):
    """Только текущий админ стола (bot.py:1000-1003) — авторизация внутри
    table_group_service.approve_join_request по admin_guest_id из
    TableGroup, а не по значению из тела запроса."""
    result = table_group_service.approve_join_request(
        g.club_id, g.table_no, g.guest_id, request_id, current_app.config["MAX_GROUP_SIZE"],
    )
    if result.outcome == "not_found":
        return api_error(404, "REQUEST_NOT_FOUND", "Заявка не найдена")
    if result.outcome == "forbidden":
        return api_error(403, "FORBIDDEN", "Только админ стола может одобрять заявки")
    if result.outcome == "already_decided":
        return api_error(409, "ALREADY_DECIDED", "Заявка уже обработана")
    if result.outcome == "table_full":
        return api_error(409, "TABLE_FULL", "Стол уже заполнен — заявка автоматически отклонена")
    return api_ok(result.request.to_dict())


@bp.post("/table-group/join-requests/<int:request_id>/reject")
@require_guest
@_require_table
def reject_table_join_request(request_id):
    result = table_group_service.reject_join_request(g.club_id, g.table_no, g.guest_id, request_id)
    if result.outcome == "not_found":
        return api_error(404, "REQUEST_NOT_FOUND", "Заявка не найдена")
    if result.outcome == "forbidden":
        return api_error(403, "FORBIDDEN", "Только админ стола может отклонять заявки")
    if result.outcome == "already_decided":
        return api_error(409, "ALREADY_DECIDED", "Заявка уже обработана")
    return api_ok(result.request.to_dict())


@bp.post("/table-group/kick/<int:target_guest_id>")
@require_guest
@_require_table
def kick_table_group_member(target_guest_id):
    """Настоящее удаление участника — НОВАЯ реализация (в старом коде
    кнопка "Выгнать" на самом деле передавала права админа, реального кика
    не было, см. аудит-отчёт по Групповому столу, утверждённое решение)."""
    result = table_group_service.kick_member(g.club_id, g.table_no, g.guest_id, target_guest_id)
    if result.outcome == "forbidden":
        return api_error(403, "FORBIDDEN", "Только админ стола может убирать участников")
    if result.outcome == "cannot_target_self":
        return api_error(400, "CANNOT_KICK_SELF", "Нельзя выгнать самого себя — используйте выход")
    if result.outcome == "not_a_member":
        return api_error(404, "NOT_A_MEMBER", "Этот гость не состоит в группе")
    return api_ok({"kicked": True})


@bp.post("/table-group/transfer/<int:target_guest_id>")
@require_guest
@_require_table
def transfer_table_group_admin(target_guest_id):
    """Отдельное действие — перенос РАБОЧЕЙ старой механики set_table_admin
    (bot.py:1108-1141, там ошибочно подписанной как кик), утверждённое
    решение: держим отдельно от настоящего кика выше."""
    result = table_group_service.transfer_admin(g.club_id, g.table_no, g.guest_id, target_guest_id)
    if result.outcome == "forbidden":
        return api_error(403, "FORBIDDEN", "Только текущий админ стола может передать права")
    if result.outcome == "cannot_target_self":
        return api_error(400, "VALIDATION_ERROR", "Вы уже админ стола")
    if result.outcome == "not_a_member":
        return api_error(404, "NOT_A_MEMBER", "Этот гость не состоит в группе")
    return api_ok({"transferred": True})


@bp.post("/table-group/leave")
@require_guest
@_require_table
def leave_table_group():
    """Самостоятельный выход — НОВАЯ реализация (в старом коде это были
    нерабочие мёртвые строки локализации, ни одного обработчика, см. аудит,
    утверждённое решение). При выходе админа права переходят старейшему
    оставшемуся участнику; если участников не осталось — группа удаляется
    (table_group_service._remove_member_and_reassign, 1:1 правильная
    старая логика unbind_user_table, database.py:394-435)."""
    result = table_group_service.leave_group(g.club_id, g.table_no, g.guest_id)
    if result.outcome == "not_a_member":
        return api_error(404, "NOT_A_MEMBER", "Вы не состоите в группе этого стола")
    return api_ok({"left": True})


@bp.post("/chat")
@require_guest
def send_chat_message():
    """
    Гость пишет KJ (ТЗ §20, §49). Работает только если у клуба включён
    чат (Club.chat_enabled — 1:1 перенос старого venues.chat_enabled) —
    так же, как в старом боте пункт меню чата вообще не показывался, если
    флаг выключен; здесь дополнительно проверяем на сервере, а не только
    прячем кнопку (старый баг класса "проверка только видимостью кнопки",
    который новый ТЗ явно требует не повторять — см. PHASE1_AUDIT, §54/§61).
    """
    club = db.session.get(Club, g.club_id)
    if club is None or not club.chat_enabled:
        return api_error(403, "CHAT_DISABLED", "Чат отключён в этом клубе")

    payload = request.get_json(silent=True) or {}
    message_text = payload.get("message_text")
    if not message_text or not isinstance(message_text, str):
        return api_error(400, "VALIDATION_ERROR", "message_text обязателен")

    message = ChatMessage(
        club_id=g.club_id,
        telegram_user_id=g.guest_id,
        table_no=g.table_no,
        from_guest=True,
        message_text=message_text,
    )
    db.session.add(message)
    db.session.commit()

    emit_chat_message(message)

    return api_ok(message.to_dict(), status_code=201)


@bp.get("/chat")
@require_guest
def list_chat_messages():
    """Вся переписка этого гостя с KJ, в обе стороны, по времени."""
    messages = (
        ChatMessage.query
        .filter_by(club_id=g.club_id, telegram_user_id=g.guest_id)
        .order_by(ChatMessage.created_at.asc())
        .all()
    )
    return api_ok([m.to_dict() for m in messages])


@bp.get("/queue")
@require_guest
def queue():
    """
    Живая очередь VirtualDJ клуба — единая для всех ролей (это требование
    было с самого начала задачи: очередь видна и KJ Pro, и Guest App, без
    различий по источнику заказа, ТЗ §22/§35). По структуре ответа
    идентична /api/kj/queue/<club_id>.
    """
    vdj = get_vdj_client(g.club_id)
    items = vdj.get_queue()
    return api_ok([
        {
            "vdj_item_id": i.vdj_item_id,
            "song_title": i.song_title,
            "artist": i.artist,
            "table_no": i.table_no,
        }
        for i in items
    ])
