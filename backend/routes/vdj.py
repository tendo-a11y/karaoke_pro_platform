from flask import Blueprint, g, request

from auth import require_kj
from errors import api_error, api_ok
from vdj import get_vdj_client
from vdj.base import VirtualDJError

bp = Blueprint("vdj", __name__, url_prefix="/api/vdj")


@bp.post("/queue/add")
@require_kj
def add_to_queue():
    """
    Низкоуровневый эндпоинт из минимального набора API (ТЗ п.23) — прямое
    добавление трека в очередь VirtualDJ без привязки к заказу (ручное
    добавление KJ, диагностика). Основной путь "заказ -> очередь" идёт через
    PUT /api/kj/order/<id>/confirm, который сам вызывает этот же адаптер и
    попутно обновляет статус заказа — см. services/vdj_service.py.
    """
    payload = request.get_json(silent=True) or {}
    song_title = payload.get("song_title")
    artist = payload.get("artist")
    table_no = payload.get("table_no")

    if not song_title:
        return api_error(400, "VALIDATION_ERROR", "song_title обязателен")

    vdj = get_vdj_client(g.club_id)
    try:
        vdj_item_id = vdj.add_to_queue(song_title, artist, table_no)
    except VirtualDJError as exc:
        return api_error(502, "VDJ_UNAVAILABLE", str(exc))

    return api_ok({"vdj_item_id": vdj_item_id}, status_code=201)


@bp.delete("/queue/<vdj_item_id>")
@require_kj
def remove_from_queue(vdj_item_id):
    """ТЗ п.20: удаление элемента, уже добавленного в очередь VirtualDJ."""
    vdj = get_vdj_client(g.club_id)
    try:
        vdj.remove_from_queue(vdj_item_id)
    except VirtualDJError as exc:
        return api_error(502, "VDJ_UNAVAILABLE", str(exc))
    return api_ok({"vdj_item_id": vdj_item_id, "removed": True})
