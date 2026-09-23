import hmac
import logging

import jwt
from flask import current_app, request
from flask_socketio import join_room

from extensions import db, socketio
from models import Club, KJOperator
from vdj import bridge_status
from vdj.bridge_registry import registry as vdj_bridge_registry

logger = logging.getLogger(__name__)


def _club_room(club_id: int) -> str:
    return f"club_{club_id}"


def _bridge_room(club_id: int) -> str:
    return f"bridge_club_{club_id}"


# register_handlers() — а не голые @socketio.on(...) декораторы прямо на
# уровне модуля — потому что flask_socketio.SocketIO.on() при уже
# существующем self.server регистрирует обработчик СРАЗУ на тот конкретный
# объект self.server, а не в переиспользуемый список (см. исходники
# flask_socketio: self.handlers используется только пока self.server ещё
# None). app.py создаёт новый self.server при каждом socketio.init_app(app)
# (например, каждый create_app() в тестах — см. tests/conftest.py::app) — и
# модуль sockets.py Python импортирует («выполняет») только один раз за
# процесс, поэтому голые декораторы на уровне модуля привязали бы
# обработчики только к самому первому созданному серверу за весь процесс, а
# все последующие app/socketio.server (все тесты, кроме первого) оставались
# бы вообще без единого обработчика — молча, без ошибки (просто ничего не
# подключалось бы и ничего никуда бы не рассылалось). В проде это было
# незаметно, потому что create_app() там вызывается ровно один раз; баг
# нашёлся только при первом тесте, который реально подключается по
# Socket.IO (tests/test_bridge_status.py, запрос пользователя 2026-09 про
# статус моста). Функция вызывается явно из app.py::create_app() после
# socketio.init_app(...) — так регистрация всегда идёт на актуальный сервер.
def register_handlers():
    @socketio.on("connect")
    def handle_connect(auth):
        """
        React KJ Panel подключается с JWT-токеном (тем же, что и для REST
        API) и попадает в комнату своего клуба. Комната определяется так
        же, как и для REST — по записи в kj_operators, а не по значению,
        присланному клиентом.

        2026-09 (найдено пользователем на живом мосту: KJ Panel вечно
        показывала "○ переподключение…" после входа через Google): здесь,
        в отличие от require_kj в auth.py, поле "identity" не проверялось
        вовсе — sub всегда трактовался как telegram_user_id, а
        int(google_sub) кидает исключение на нечисловой строке → connect
        всегда отклонялся для Google-токенов (issue_kj_google_token), REST
        при этом работал нормально (require_kj эту ветку уже умел), поэтому
        баг был незаметен, пока никто не пробовал именно живые обновления.
        Теперь — точная копия ветвления identity из require_kj.
        """
        token = None
        if isinstance(auth, dict):
            token = auth.get("token")
        if not token:
            token = request.args.get("token")

        if not token:
            logger.info("WebSocket: подключение отклонено — нет токена")
            return False

        try:
            payload = jwt.decode(token, current_app.config["KJ_JWT_SECRET"], algorithms=["HS256"])
        except Exception:
            logger.info("WebSocket: подключение отклонено — невалидный токен")
            return False

        sub = payload.get("sub")
        if not sub:
            logger.info("WebSocket: подключение отклонено — невалидный токен")
            return False

        if payload.get("identity") == "google":
            kj = KJOperator.query.filter_by(google_sub=sub, is_active=True).first()
        else:
            try:
                telegram_user_id = int(sub)
            except (TypeError, ValueError):
                logger.info("WebSocket: подключение отклонено — невалидный токен")
                return False
            kj = KJOperator.query.filter_by(telegram_user_id=telegram_user_id, is_active=True).first()

        if not kj or not kj.club or not kj.club.is_active:
            logger.info("WebSocket: подключение отклонено — KJ/клуб неактивны")
            return False

        join_room(_club_room(kj.club_id))
        logger.info("WebSocket: KJ %s подключился Kклусу %s", kj.id, kj.club_id)
        return True

    @socketio.on("connect", namespace="/bridge")
    def handle_bridge_connect(auth):
        """
        Локальный мост VirtualDJ цоммвена.py, vdj_bridge/agent.py)
        подключается седа — отдельный namespace и 0���tad�Ro подключается модель доверия от
        KJ Panel выше: это не человек с JWT-логином через браузер, а доверенный
        процесс на компьютере KJ с статическим секретом (bridge_token),
        который выдаётся клуба через 👄 manage.py set-bridge-token`.
        """
        club_id = None
        token = None
        if isinstance(auth, dict):
            club_id = auth.get("club_id")
            token = auth.get("bridge_token")

        if not club_id or not token:
            logger.info("Bridge: подключение отклонено — нет club_id/bridge_token")
            return False

        try:
            club_id = int(club_id)
        except (TypeError, ValueError):
            logger.info("Bridge: подключение отклонено — club_id не число")
            return False

        club = db.session.get(Club, club_id)
        if club is None or not club.is_active:
            logger.info("Bridge: подключение отклонено — клуб %s не найден/неактивен", club_id)
            return False

        if not club.bridge_token or not hmac.compare_digest(club.bridge_token, str(token)):
            logger.info("Bridge: подключение отклонено — неверный bridge_token для клуба %s", club_id)
            return False

        join_room(_bridge_room(club_id), namespace="/bridge")
        logger.info("Bridge: мост клуба %s подключился (sid=%s)", club_id, request.sid)

        # Запрос пользователя 2026-09: KJ Panel должна видеть живой статус
        # мост ("подключён"/"не подключён") — см. vdj/bridge_status.py про
        # то, почему это простое состояние пробемс, а не запись в БД.
        # Рассылаем в комнату клуба (не место!) — именно там сидит KJ Panel,
        # см. handle_connect выше. vdj_reachable здесь всегда None — мост
        # только что подключился и ещё не успел ни разу проверить VirtualDJ
        # (первый отчёт придёт отдельным событием bridge_vdj_status, см.
        # handle_bridge_vdj_status ниже).
        bridge_status.mark_connected(request.sid, club_id)
        socketio.emit(
            "bridge_status",
            {"connected": True, "vdj_reachable": None},
            room=_club_room(club_id),
        )
        return True

    @socketio.on("disconnect", namespace="/bridge")
    def handle_bridge_disconnect():
        """
        Пара к handle_bridge_connect выше — мост отключился (закрыли вкладки
        программу, выключили VirtualDJ и мост сам решил отключиться,
        пропало сетевое соединение и т.п.). Socket.IO не передаёт сюда
        club_id/auth повторно, только request.sid — поэтому club_id
        "вспоминаем" из bridge_status, туда он был записан при connect
        именно под этим sid.
        """
        club_id = bridge_status.mark_disconnected(request.sid)
        if club_id is None:
            # sid не был7арегистрирован как мост (например, это
            # подключение было отклонено ещё в handle_bridge_connect до
            # join_room) — рассылать нечего, KJ Panel и так не думала, что
            # мост подключён.
            return
        logger.info("Bridge: мост клуба %s отключился (sid=%s)", club_id, request.sid)
        socketio.emit(
            "bridge_status",
            {
                "connected": bridge_status.is_connected(club_id),
                "vdj_reachable": bridge_status.vdj_reachable(club_id),
            },
            room=_club_room(club_id),
        )

    @socketio.on("bridge_vdj_status", namespace="/bridge")
    def handle_bridge_vdj_status(data):
        """
        Третий индикатор панели обзора KJ ("Мост↔VirtualDJ") — запрос
        пользователя 2026-09-17: раньше KJ Panel видела только "мост
        подключён к серверу", но не видела, отвечает ли VirtualDJ САМОМУ
        мосту на компьютере KJ (мост мог быть на связи с сервером, пока
        VirtualDJ выключена или зависла — KJ узнавал об этом только когда
        песня не появлялась в очереди). Мост присылает этот отчёт сам, раз
        в QUEUE_REFRESH_SECONDS, из уже существующего фонового опроса
        VirtualDJ (см. vdj_bridge_app.py::_queue_refresh_loop) — отдельного
        опроса "жив ли VDJ" не заводим, переиспользуем то же обращение.
        """
        if not isinstance(data, dict):
            return
        reachable = data.get("reachable")
        if not isinstance(reachable, bool):
            return
        club_id = bridge_status.mark_vdj_reachable(request.sid, reachable)
        if club_id is None:
            # sid не зарегистрирован как подключённый мост (гонка при
            # отключении — отчёт пришёл чуть позже disconnect) — рассылать
            # нечего.
            return
        socketio.emit(
            "bridge_status",
            {"connected": True, "vdj_reachable": reachable},
            room=_club_room(club_id),
        )

    @socketio.on("vdj_result", namespace="/bridge")
    def handle_vdj_result(data):
        """
        Ответ моста на команду vdj_command (см. vdj/bridge_client.py и
        vdj/bridge_registry.py). Сопоставление ответа с ожидающим запросом —
        по request_id (uuid), а не по club_id: комната bridge_club_{id} и
        так гарантирует, что мост одного клуба физически не получит
        vdj_command (и, следовательно, не узнает request_id) другого клуба —
        Socket.IO не доставляет клиенту события, посланные в комнату, в
        которой тот не состоит, поэтому угадать/подделать чужой request_id
        мосту неоткуда.
        """
        if not isinstance(data, dict):
            return
        request_id = data.get("request_id")
        if not request_id:
            logger.info("Bridge: получен vdj_result без request_id, игнорирую")
            return
        resolved = vdj_bridge_registry.resolve(str(request_id), data.get("result") or {})
        if not resolved:
            logger.info(
                "Bridge: vdj_result для неизвестного/просроченного request_id=%s", request_id
            )


def emit_order_created(order):
    socketio.emit("order_created", order.to_dict(), room=_club_room(order.club_id))


def emit_order_updated(order):
    socketio.emit("order_updated", order.to_dict(), room=_club_room(order.club_id))


def emit_order_confirmed(order):
    socketio.emit("order_confirmed", order.to_dict(), room=_club_room(order.club_id))


def emit_order_rejected(order):
    socketio.emit("order_rejected", order.to_dict(), room=_club_room(order.club_id))


def emit_queue_updated(club_id: int, queue: list):
    socketio.emit("queue_updated", {"club_id": club_id, "queue": queue}, room=_club_room(club_id))


def emit_song_started(club_id: int, item: dict):
    socketio.emit("song_started", item, room=_club_room(club_id))


def emit_song_finished(club_id: int, item: dict):
    socketio.emit("song_finished", item, room=_club_room(club_id))


def emit_vip_request_created(vip_request):
    """
    Новая заявка гостя на VIP-статус (Block D KJ Pro). Аналог
    emit_order_created — старый бот уведомлял KJ мгновенно личным
    сообщением в Telegram (handlers/client.py::request_vip_status ->
    push KJ), здесь тот же эффект достигается WebSocket-событием в
    комнату клуба вместо поллинга (согласовано перед реализацией блока).
    """
    socketio.emit("vip_request_created", vip_request.to_dict(), room=_club_room(vip_request.club_id))


def emit_order_change_request_created(change_request):
    """
    ДОБАВЛЕНО 2026-09-20 — решение пользователя "Нужно одобрение KJ (запрос
    → Одобрить/Отклонить)": новая заявка гостя на отмену/замену уже
    принятого заказа (см. services/vdj_service.py::request_order_cancel/
    request_order_replace). Аналог emit_vip_request_created выше — KJ
    Panel должна узнать о заявке мгновенно (без ожидания следующего опроса)
    и показать её в панели "🔔 Заявки от гостей", как и заявки на VIP.
    """
    socketio.emit(
        "order_change_request_created", change_request.to_dict(), room=_club_room(change_request.club_id)
    )


def emit_order_change_request_decided(change_request):
    """
    ДОБАВЛЕНО (2026-09-23, жалоба пользователя "не одобрить не отклонить
    нельзя" — заявка уже обработана): раньше решение по заявке (approve/
    reject/автоматическое "stale" в vdj_service.approve_order_change_request)
    никак не сообщалось другим открытым KJ Panel — если у KJ было открыто
    несколько вкладок/устройств (или страница просто долго не
    перезагружалась), в списке "🔔 Заявки от гостей" оставалась заявка,
    которую кто-то (или та же вкладка чуть раньше) уже решил. Клик по
    "Одобрить"/"Отклонить" в таком случае всегда получал 409 ALREADY_DECIDED
    и заявка навсегда "зависала" в списке без возможности что-либо с ней
    сделать. Теперь при любом решении заявки (approve/reject/stale) все
    подключённые панели клуба получают это событие и сразу убирают заявку
    из списка — тот же паттерн, что и emit_order_change_request_created.
    """
    socketio.emit(
        "order_change_request_decided", change_request.to_dict(), room=_club_room(change_request.club_id)
    )


def emit_chat_message(message):
    """
    Новое сообщение в чате гость↔KJ (см. models.py::ChatMessage). Пока
    доставляется только KJ Panel (в комнату клуба, где она и так слушает
    order_*/queue_updated) — у Guest App ещё нет WebSocket-подключения
    (handle_connect втомф файле принимает только KJ-токен), поэтому гость
    видит новые сообщения через обычный поллинг GET /api/guest/chat.
    """
    socketio.emit("chat_message", message.to_dict(), room=_club_room(message.club_id))
