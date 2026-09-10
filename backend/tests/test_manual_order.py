"""
Тесты POST /api/kj/order/manual — KJ Pro, новый экран "Добавить песню":
KJ сам находит песню (в этом шаге ТЗ — ищет в настоящих файлах VirtualDJ,
каталог CSV сознательно не используется, согласовано с пользователем
отдельно) и указывает стол, песня сразу уходит в очередь VirtualDJ, без
"Заказы"/подтверждения перетаскиванием (см. add_manual_song() в
services/vdj_service.py за полным обоснованием решений).
"""
from extensions import db as _db
from models import STATUS_QUEUED, Order
from vdj import get_vdj_client


def _headers(token):
    return {"Authorization": f"Bearer {token}"}


def _add_manual(client, kj, song_title="Песня", artist="Артист", table_no=7):
    return client.post(
        "/api/kj/order/manual",
        json={"song_title": song_title, "artist": artist, "table_no": table_no},
        headers=_headers(kj["token"]),
    )


def test_requires_auth(client, db, club):
    resp = client.post("/api/kj/order/manual", json={"song_title": "X", "table_no": 1})
    assert resp.status_code == 401


def test_song_title_required(client, db, club, kj):
    resp = _add_manual(client, kj, song_title="")
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "VALIDATION_ERROR"


def test_table_no_required(client, db, club, kj):
    resp = client.post(
        "/api/kj/order/manual",
        json={"song_title": "Песня", "artist": "Артист"},
        headers=_headers(kj["token"]),
    )
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "VALIDATION_ERROR"


def test_table_no_must_be_positive(client, db, club, kj):
    resp = _add_manual(client, kj, table_no=0)
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "VALIDATION_ERROR"

    resp2 = _add_manual(client, kj, table_no=-3)
    assert resp2.status_code == 400


def test_table_no_rejects_non_integer(client, db, club, kj):
    resp = client.post(
        "/api/kj/order/manual",
        json={"song_title": "Песня", "table_no": "5"},
        headers=_headers(kj["token"]),
    )
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "VALIDATION_ERROR"


def test_successful_add_creates_queued_order_with_expected_fields(client, db, club, kj):
    resp = _add_manual(client, kj, song_title="Моя песня", artist="Мой артист", table_no=9)
    assert resp.status_code == 201
    data = resp.get_json()["data"]
    assert data["status"] == "queued"
    assert data["table_no"] == 9
    assert data["song_title"] == "Моя песня"
    assert data["artist"] == "Мой артист"
    assert data["vdj_item_id"]

    order = _db.session.get(Order, data["id"])
    assert order.status == STATUS_QUEUED
    assert order.source == "manual"
    assert order.channel == "webapp"
    assert order.telegram_user_id == -1
    assert order.confirmed_by == kj["operator"].id


def test_song_actually_lands_in_vdj_queue(client, db, club, kj, app):
    resp = _add_manual(client, kj, song_title="Реальная песня", table_no=3)
    vdj_item_id = resp.get_json()["data"]["vdj_item_id"]

    with app.app_context():
        vdj = get_vdj_client(club.club_id)
        assert any(i.vdj_item_id == vdj_item_id for i in vdj.get_queue())


def test_appears_in_kj_queue_view_with_correct_table(client, db, club, kj):
    resp = _add_manual(client, kj, song_title="Стол видно", table_no=12)
    order_id = resp.get_json()["data"]["id"]

    queue_resp = client.get(f"/api/kj/queue/{club.club_id}", headers=_headers(kj["token"]))
    queue = queue_resp.get_json()["data"]
    assert any(item["order_id"] == order_id and item["table_no"] == 12 for item in queue)


def test_vdj_failure_does_not_create_order(client, db, club, kj, app):
    with app.app_context():
        vdj = get_vdj_client(club.club_id)
        vdj.force_failure(True)

    before = Order.query.filter_by(club_id=club.club_id).count()
    resp = _add_manual(client, kj, table_no=1)
    assert resp.status_code == 502
    assert resp.get_json()["error"] == "VDJ_UNAVAILABLE"

    after = Order.query.filter_by(club_id=club.club_id).count()
    assert after == before


def test_kj_cannot_add_for_other_club(client, db, club, other_club, kj, other_kj):
    """club_id всегда берётся из токена KJ (g.club_id), а не из тела запроса —
    подделать чужой club_id через payload здесь просто нечем (в отличие от
    /queue/<club_id>, тут в URL club_id вообще не передаётся), но на всякий
    случай фиксируем: заказ действительно создаётся в СВОЁМ клубе KJ."""
    resp = _add_manual(client, other_kj, song_title="Чужой клуб", table_no=4)
    assert resp.status_code == 201
    order_id = resp.get_json()["data"]["id"]
    order = _db.session.get(Order, order_id)
    assert order.club_id == other_club.club_id
