from flask import Blueprint, request

from auth import require_bot_token
from errors import api_error, api_ok
from extensions import db
from models import Club, Order
from sockets import emit_order_created

bp = Blueprint("client", __name__, url_prefix="/api/client")


@bp.post("/order")
@require_bot_token
def create_order():
    """
    ТЗ п.7: Telegram-бот присылает сюда заказ после того, как гость выбрал
    песню. Доступно только самому боту (см. require_bot_token) — гость не
    может создать заказ напрямую в обход существующей логики бота.
    """
    payload = request.get_json(silent=True) or {}

    telegram_user_id = payload.get("telegram_user_id")
    club_id = payload.get("club_id")
    table_no = payload.get("table_no")
    song_title = payload.get("song_title")
    artist = payload.get("artist")

    if not isinstance(telegram_user_id, int):
        return api_error(400, "VALIDATION_ERROR", "telegram_user_id обязателен и должен быть числом")
    if not isinstance(club_id, int):
        return api_error(400, "VALIDATION_ERROR", "club_id обязателен и должен быть числом")
    if not song_title or not isinstance(song_title, str):
        return api_error(400, "VALIDATION_ERROR", "song_title обязателен")
    if table_no is not None and not isinstance(table_no, int):
        return api_error(400, "VALIDATION_ERROR", "table_no должен быть числом или null (клиент без стола)")

    club = db.session.get(Club, club_id)
    if club is None or not club.is_active:
        return api_error(404, "CLUB_NOT_FOUND", "Клуб не найден или отключён")

    order = Order(
        telegram_user_id=telegram_user_id,
        club_id=club_id,
        table_no=table_no,
        song_title=song_title,
        artist=artist,
        channel="telegram",
    )
    db.session.add(order)
    db.session.commit()

    emit_order_created(order)

    return api_ok(order.to_dict(), status_code=201)
