"""
Тесты get_kj_queue_view() / GET /api/kj/queue/<club_id> — сопоставление живой
очереди VirtualDJ с заказами (Order) в статусе STATUS_QUEUED, добавленное как
шаг перед фоновой синхронизацией KJ Pro (согласованный с пользователем план:
Шаг 1-3 — уже сделанная починка vdj_item_id/filepath, Шаг 4 — polling в
KJ Pro, для которого нужен номер стола рядом с песней).

Ключевая идея, которую проверяют эти тесты: сам VirtualDJ номер стола не
хранит вообще, поэтому "Стол" в KJ Pro можно получить только сопоставлением
живой позиции очереди с заказом по vdj_item_id — а не наугад беря то, что
случайно хранит MockVirtualDJClient у себя (у настоящего VirtualDJ такого
поля вообще нет).
"""
from datetime import datetime, timezone

from extensions import db as _db
from models import STATUS_QUEUED, Order
from services.vdj_service import get_kj_queue_view
from vdj import get_vdj_client


def _make_queued_order(club_id, table_no, vdj_item_id, song_title="Песня", artist="Артист"):
    order = Order(
        telegram_user_id=1,
        club_id=club_id,
        table_no=table_no,
        song_title=song_title,
        artist=artist,
        status=STATUS_QUEUED,
        vdj_item_id=vdj_item_id,
        queued_at=datetime.now(timezone.utc),
    )
    _db.session.add(order)
    _db.session.commit()
    return order


def test_matches_live_queue_item_to_its_order_and_returns_table_no(db, club, app):
    with app.app_context():
        vdj = get_vdj_client(club.club_id)
        # table_no=42 передаётся в mock-очередь так же, как в реальном
        # add_to_queue() — но get_kj_queue_view() не должен доверять этому
        # полю напрямую (см. docstring файла), поэтому у заказа в базе
        # намеренно указан ДРУГОЙ table_no, чтобы тест точно проверял, что
        # в ответе окажется значение из Order, а не из драйвера.
        vdj_item_id = vdj.add_to_queue("Песня A", "Артист A", table_no=42)
        order = _make_queued_order(club.club_id, table_no=7, vdj_item_id=vdj_item_id,
                                    song_title="Песня A", artist="Артист A")

        result = get_kj_queue_view(club.club_id)

    assert result == [
        {
            "vdj_item_id": vdj_item_id,
            "song_title": "Песня A",
            "artist": "Артист A",
            "table_no": 7,
            "order_id": order.id,
        }
    ]


def test_live_item_without_matching_order_shown_with_order_id_none(db, club, app):
    """Песня, добавленная прямо в VirtualDJ в обход Guest App/Backend (KJ
    вручную перетащил файл) — соответствующего Order в базе нет вообще. Такая
    позиция всё равно должна попасть в ответ (KJ должен её видеть), но с
    order_id=None и table_no=None — по этому и отличается от заказа без
    стола (у которого order_id есть, а table_no пуст)."""
    with app.app_context():
        vdj = get_vdj_client(club.club_id)
        vdj.add_to_queue("Ручная песня", "Кто-то", table_no=99)

        result = get_kj_queue_view(club.club_id)

    assert len(result) == 1
    assert result[0]["order_id"] is None
    assert result[0]["table_no"] is None
    assert result[0]["song_title"] == "Ручная песня"


def test_each_order_matched_at_most_once_and_order_preserved(db, club, app):
    with app.app_context():
        vdj = get_vdj_client(club.club_id)
        item_a = vdj.add_to_queue("A", None, table_no=None)
        item_b = vdj.add_to_queue("B", None, table_no=None)
        order_a = _make_queued_order(club.club_id, table_no=1, vdj_item_id=item_a, song_title="A")
        order_b = _make_queued_order(club.club_id, table_no=2, vdj_item_id=item_b, song_title="B")

        result = get_kj_queue_view(club.club_id)

    live_positions = [i.vdj_item_id for i in vdj.get_queue()]
    assert [r["vdj_item_id"] for r in result] == live_positions
    matched_order_ids = [r["order_id"] for r in result]
    assert sorted(matched_order_ids) == sorted([order_a.id, order_b.id])


def test_orders_from_other_club_are_never_matched(db, club, other_club, app):
    with app.app_context():
        vdj = get_vdj_client(club.club_id)
        vdj_item_id = vdj.add_to_queue("Чужая песня клубу", None, table_no=None)
        # Тот же самый vdj_item_id "случайно" оказался в базе, но у ЧУЖОГО
        # клуба — не должен считаться совпадением (та же изоляция по
        # club_id, что и везде в проекте, ТЗ п.24-25).
        _make_queued_order(other_club.club_id, table_no=5, vdj_item_id=vdj_item_id)

        result = get_kj_queue_view(club.club_id)

    assert result[0]["order_id"] is None
    assert result[0]["table_no"] is None


def test_route_returns_correlated_queue(client, db, club, kj, app):
    with app.app_context():
        vdj = get_vdj_client(club.club_id)
        vdj_item_id = vdj.add_to_queue("Песня из маршрута", "Артист", table_no=3)
        order = _make_queued_order(club.club_id, table_no=3, vdj_item_id=vdj_item_id,
                                    song_title="Песня из маршрута", artist="Артист")
        order_id = order.id

    resp = client.get(f"/api/kj/queue/{club.club_id}", headers=kj["headers"])
    assert resp.status_code == 200
    data = resp.get_json()["data"]
    assert data == [
        {
            "vdj_item_id": vdj_item_id,
            "song_title": "Песня из маршрута",
            "artist": "Артист",
            "table_no": 3,
            "order_id": order_id,
        }
    ]
