import hmac
import logging

import jwt
from flask import current_app, request
from flask_socketio import join_room

from extensions import db, socketio
from models import Club, KJOperator
from vdj.bridge_registry import registry as vdj_bridge_registry

logger = logging.getLogger(__name__)


def _club_room(club_id: int) -> str:
    return f"club_{club_id}"


def _bridge_room(club_id: int) -> str:
    return f"bridge_club_{club_id}"


@socketio.on("connect")
def handle_connect(auth):
    """
    React KJ Panel подключается с JWT-токеном (тем же, что и для REST API) и
    попадает в комнату своего клуба. Комната определяется так же, как и для
    REST — по записи в kj_operators, а не по значению, присланному клиентом.
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
        telegram_user_id = int(payload.get("sub"))
    except Exception:
        logger.info("WebSocket: подключение отклонено — невалидный токен")
        return False

    kj = KJOperator.query.filter_by(telegram_user_id=telegram_user_id, is_active=True).first()
    if not kj or not kj.club or not kj.club.is_active:
        logger.info("WebSocket: подключение отклонено — KJ/клуб неактивны")
        return False

    join_room(_club_room(kj.club_id))
    logger.info("WebSocket: KJ %s подключился к клубу %s", telegram_user_id, kj.club_id)
    return True


@socketio.on("connect", namespace="/bridge")
def handle_bridge_connect(auth):
    """
    Локальный мост VirtualDJ (см. vdj/bridge_client.py, vdj_bridge/agent.py)
    подключается сюда — отдельный namespace и отдельная модель доверия от
    KJ Panel выше: это не человек с JWT-логином через браузер, а доверенный
    процесс на компьютере KJ со статическим секретом (bridge_token),
    который выдаётся клубу через `manage.py set-bridge-token`.
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
    return True


@socketio.on("vdj_result", namespace="/bridge")
def handle_vdj_result(data):
    """
    Ответ моста на команду vdj_command (см. vdj/bridge_client.py и
    vdj/bridge_registry.py). Сопоставление ответа с ожидающим запросом — по
    request_id (uuid), а не по club_id: комната bridge_club_{id} и так
    гарантирует, что мост одного клуба физически не получит vdj_command (и,
    следовательно, не узнает request_id) другого клуба — Socket.IO не
    доставляет клиенту события, посланные в комнату, в которой тот не
    состоит, поэтому угадать/подделать чужой request_id мосту неоткуда.
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


def emit_chat_message(message):
    """
    Новое сообщение в чате гость↔KJ (см. models.py::ChatMessage). Пока
    доставляется только KJ Panel (в комнату клуба, где она и так слушает
    order_*/queue_updated) — у Guest App ещё нет WebSocket-подключения
    (handle_connect в этом файле принимает только KJ-токен), поэтому гость
    видит новые сообщения через обычный поллинг GET /api/guest/chat.
    """
    socketio.emit("chat_message", message.to_dict(), room=_club_room(message.club_id))
