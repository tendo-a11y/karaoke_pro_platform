"""
Тесты "вариантов очереди" (доп. ТЗ "KJ Pro", запрос пользователя
2026-09-24, вкладка "Столы" — быстрый тумблер QUEUE_MODE_MANUAL /
QUEUE_MODE_SEQUENTIAL) — см. подробный докстринг
services/table_board_service.py про сам алгоритм кругового обхода столов и
про категорию CRAZY.
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from models import STATUS_PENDING, Order, Service
from services.table_board_service import (
    QUEUE_MODE_MANUAL,
    QUEUE_MODE_SEQUENTIAL,
    compute_queue_order,
    get_club_queue_positions,
)


def _headers(token):
    return {"Authorization": f"Bearer {token}"}


_BASE_TIME = datetime(2026, 9, 24, 20, 0, 0, tzinfo=timezone.utc)


def _make_order(db, club_id, table_no, offset_seconds, guest_id=1, service_id=None,
                 song_title="Песня", status=STATUS_PENDING):
    order = Order(
        telegram_user_id=guest_id, club_id=club_id, table_no=table_no,
        guest_type="client", song_title=song_title, artist="Артист", service_id=service_id,
        source="guest", status=status,
        created_at=_BASE_TIME + timedelta(seconds=offset_seconds),
    )
    db.session.add(order)
    db.session.commit()
    return order


def _crazy_service(db, club_id):
    service = Service(club_id=club_id, name="CRAZY", description="Песня вне очереди",
                       price=Decimal("1000"), is_free=False)
    db.session.add(service)
    db.session.commit()
    return service


# --- Настройка режима через /api/kj/table-settings ---

def test_default_queue_mode_is_manual(client, db, club, kj):
    resp = client.get(f"/api/kj/table-settings/{club.club_id}", headers=_headers(kj["token"]))
    assert resp.status_code == 200
    assert resp.get_json()["data"]["queue_mode"] == "manual"


def test_can_switch_queue_mode_without_touching_other_fields(client, db, club, kj):
    club.table_count = 5
    club.songs_per_table = 3
    db.session.commit()

    resp = client.put(
        f"/api/kj/table-settings/{club.club_id}", json={"queue_mode": "sequential"},
        headers=_headers(kj["token"]),
    )
    assert resp.status_code == 200
    data = resp.get_json()["data"]
    assert data["queue_mode"] == "sequential"
    assert data["table_count"] == 5
    assert data["songs_per_table"] == 3


def test_invalid_queue_mode_rejected(client, db, club, kj):
    resp = client.put(
        f"/api/kj/table-settings/{club.club_id}", json={"queue_mode": "random"},
        headers=_headers(kj["token"]),
    )
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "VALIDATION_ERROR"


# --- orders-board: queue_position появляется только в sequential ---

def test_manual_mode_board_has_no_queue_position(client, db, club, kj):
    club.table_count = 2
    club.songs_per_table = 2
    db.session.commit()
    _make_order(db, club.club_id, table_no=1, offset_seconds=0)

    resp = client.get(f"/api/kj/orders-board/{club.club_id}", headers=_headers(kj["token"]))
    slot = resp.get_json()["data"][0]["slots"][0]
    assert "queue_position" not in slot


def test_sequential_mode_board_has_queue_position(client, db, club, kj):
    club.table_count = 2
    club.songs_per_table = 2
    club.queue_mode = "sequential"
    db.session.commit()
    order = _make_order(db, club.club_id, table_no=1, offset_seconds=0)

    resp = client.get(f"/api/kj/orders-board/{club.club_id}", headers=_headers(kj["token"]))
    board = resp.get_json()["data"]
    assert board[0]["queue_mode"] == "sequential"
    slot = board[0]["slots"][0]
    assert slot["order_id"] == order.id
    assert slot["queue_position"] == 1


# --- Круговой обход (compute_queue_order) в режиме sequential ---

def test_sequential_skips_empty_tables(db, club):
    """Пример пользователя: очередь начата со стола 3 (2 песни), столы 4 и
    5 свободны — следующим должен быть стол 6, а не 4/5."""
    club.table_count = 6
    club.songs_per_table = 2
    club.queue_mode = "sequential"
    db.session.commit()

    o3a = _make_order(db, club.club_id, table_no=3, offset_seconds=0)
    o3b = _make_order(db, club.club_id, table_no=3, offset_seconds=1)
    o6 = _make_order(db, club.club_id, table_no=6, offset_seconds=2)

    ordered = compute_queue_order(club.club_id)
    assert [o.id for o in ordered] == [o3a.id, o3b.id, o6.id]


def test_sequential_inserts_new_order_at_tables_own_turn(db, club):
    """Пока стол 3 "поёт", появляется заказ стола 5 — он должен встать
    между столом 3 и столом 6, а не в конец очереди."""
    club.table_count = 6
    club.songs_per_table = 2
    club.queue_mode = "sequential"
    db.session.commit()

    o3a = _make_order(db, club.club_id, table_no=3, offset_seconds=0)
    o3b = _make_order(db, club.club_id, table_no=3, offset_seconds=1)
    o6 = _make_order(db, club.club_id, table_no=6, offset_seconds=2)
    o5 = _make_order(db, club.club_id, table_no=5, offset_seconds=3)

    ordered = compute_queue_order(club.club_id)
    assert [o.id for o in ordered] == [o3a.id, o3b.id, o5.id, o6.id]


def test_sequential_extra_order_over_capacity_waits_for_next_circle(db, club):
    """Запрос пользователя: "если заняты только до 10 стола и в очереди уже
    есть 3 стол, то он начинает новый круг" — третий заказ стола 3 (сверх
    capacity=2) не встраивается в первый круг, а уходит во второй, и там
    круг снова идёт по номерам столов (стол 1 раньше стола 3)."""
    club.table_count = 10
    club.songs_per_table = 2
    club.queue_mode = "sequential"
    db.session.commit()

    o1a = _make_order(db, club.club_id, table_no=1, offset_seconds=0)
    o1b = _make_order(db, club.club_id, table_no=1, offset_seconds=1)
    o1c = _make_order(db, club.club_id, table_no=1, offset_seconds=2)
    o3a = _make_order(db, club.club_id, table_no=3, offset_seconds=3)
    o3b = _make_order(db, club.club_id, table_no=3, offset_seconds=4)
    o3c = _make_order(db, club.club_id, table_no=3, offset_seconds=5)

    ordered = compute_queue_order(club.club_id)
    assert [o.id for o in ordered] == [o1a.id, o1b.id, o3a.id, o3b.id, o1c.id, o3c.id]


def test_manual_mode_keeps_old_creation_order_behaviour(db, club):
    """Без sequential — поведение как раньше, просто по времени создания,
    без кругового расчёта по столам."""
    club.table_count = 6
    club.songs_per_table = 2
    db.session.commit()  # queue_mode остаётся "manual" по умолчанию

    o3a = _make_order(db, club.club_id, table_no=3, offset_seconds=0)
    o6 = _make_order(db, club.club_id, table_no=6, offset_seconds=1)
    o3b = _make_order(db, club.club_id, table_no=3, offset_seconds=2)

    ordered = compute_queue_order(club.club_id)
    assert [o.id for o in ordered] == [o3a.id, o6.id, o3b.id]


# --- CRAZY всегда первый, в обоих режимах ---

def test_crazy_order_goes_first_in_manual_mode(db, club):
    club.table_count = 6
    club.songs_per_table = 2
    db.session.commit()
    crazy_service = _crazy_service(db, club.club_id)

    o1 = _make_order(db, club.club_id, table_no=1, offset_seconds=0)
    o_crazy = _make_order(db, club.club_id, table_no=4, offset_seconds=1, service_id=crazy_service.id)

    ordered = compute_queue_order(club.club_id)
    assert [o.id for o in ordered] == [o_crazy.id, o1.id]


def test_crazy_order_goes_first_in_sequential_mode_regardless_of_table(db, club):
    club.table_count = 6
    club.songs_per_table = 2
    club.queue_mode = "sequential"
    db.session.commit()
    crazy_service = _crazy_service(db, club.club_id)

    o1 = _make_order(db, club.club_id, table_no=1, offset_seconds=0)
    o2 = _make_order(db, club.club_id, table_no=2, offset_seconds=1)
    # CRAZY-заказ стола 5 — по номеру стола он бы встал последним в круге,
    # но категория обязана вывести его на первое место в любом случае.
    o_crazy = _make_order(db, club.club_id, table_no=5, offset_seconds=2, service_id=crazy_service.id)

    ordered = compute_queue_order(club.club_id)
    assert [o.id for o in ordered] == [o_crazy.id, o1.id, o2.id]


def test_guest_queue_position_reflects_sequential_order(client, db, club):
    """get_club_queue_positions (номер в "Мои заказы" у гостя) тоже
    переключается на круговой расчёт вместе с queue_mode."""
    club.table_count = 6
    club.songs_per_table = 2
    club.queue_mode = "sequential"
    db.session.commit()

    o3a = _make_order(db, club.club_id, table_no=3, offset_seconds=0)
    o6 = _make_order(db, club.club_id, table_no=6, offset_seconds=1)
    o5 = _make_order(db, club.club_id, table_no=5, offset_seconds=2)

    positions = get_club_queue_positions(club.club_id)
    assert positions[o3a.id] == 1
    assert positions[o5.id] == 2
    assert positions[o6.id] == 3
