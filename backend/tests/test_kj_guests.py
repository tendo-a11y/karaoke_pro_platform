"""
Тесты списка гостей и карточки гостя в KJ Panel (запрос пользователя
2026-09): сортировка/фильтр VIP/Простой/Без стола, статистика по
вечеру/неделе/месяцу, избранные песни видны в карточке. Блокировка и
снятие со стола (влияние на самого гостя через require_guest) — отдельно
в test_guest_status.py, здесь только сами KJ-эндпоинты и данные списка.
"""
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from extensions import db
from models import Favorite, Order, STATUS_QUEUED, VipClient


def _headers(token):
    return {"Authorization": f"Bearer {token}"}


def _kj_headers(kj):
    return {"Authorization": f"Bearer {kj['token']}"}


def _make_vip(club_id, telegram_user_id, balance="10.00", cashback_percent=5):
    vip = VipClient(club_id=club_id, telegram_user_id=telegram_user_id, balance=Decimal(balance), cashback_percent=cashback_percent)
    db.session.add(vip)
    db.session.commit()
    return vip


def _make_order(club_id, telegram_user_id, table_no, created_at, song_title="Песня", artist="Артист"):
    order = Order(
        club_id=club_id, telegram_user_id=telegram_user_id, table_no=table_no,
        song_title=song_title, artist=artist, status=STATUS_QUEUED,
        channel="webapp", created_at=created_at,
    )
    db.session.add(order)
    db.session.commit()
    return order


def _link_google_guest(client, club_id, table_no=5):
    session = client.post("/api/guest/session", json={"club_id": club_id}).get_json()["data"]
    sub = f"mock-sub-{uuid.uuid4().hex[:12]}"
    linked = client.post(
        "/api/guest/profile/link-google",
        json={"table_no": table_no, "google_credential": {"sub": sub}},
        headers=_headers(session["token"]),
    ).get_json()["data"]
    return int(linked["guest_id"])


# --- GET /guests/<club_id> ---

def test_list_guests_requires_auth(client, club):
    resp = client.get(f"/api/kj/guests/{club.club_id}")
    assert resp.status_code == 401


def test_list_guests_groups_by_type(client, db, club, kj):
    now = datetime.now(timezone.utc)
    _make_order(club.club_id, 111, table_no=5, created_at=now)
    _make_vip(club.club_id, 222)

    resp = client.get(f"/api/kj/guests/{club.club_id}", headers=_kj_headers(kj))
    assert resp.status_code == 200
    by_id = {row["guest_id"]: row for row in resp.get_json()["data"]}
    assert by_id["111"]["guest_type"] == "client"
    assert by_id["111"]["table_no"] == 5
    assert by_id["222"]["guest_type"] == "vip"
    assert by_id["222"]["vip_balance"] == 10.0


def test_list_guests_filter_by_type(client, db, club, kj):
    now = datetime.now(timezone.utc)
    _make_order(club.club_id, 111, table_no=5, created_at=now)
    _make_vip(club.club_id, 222)

    resp = client.get(f"/api/kj/guests/{club.club_id}?type=vip", headers=_kj_headers(kj))
    assert resp.status_code == 200
    ids = {row["guest_id"] for row in resp.get_json()["data"]}
    assert ids == {"222"}

    resp = client.get(f"/api/kj/guests/{club.club_id}?type=client", headers=_kj_headers(kj))
    ids = {row["guest_id"] for row in resp.get_json()["data"]}
    assert ids == {"111"}


def test_list_guests_rejects_unknown_type(client, db, club, kj):
    resp = client.get(f"/api/kj/guests/{club.club_id}?type=nonsense", headers=_kj_headers(kj))
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "VALIDATION_ERROR"


def test_list_guests_excludes_manual_kj_orders(client, db, club, kj):
    """add_manual_song/claim_vdj_queue_item пишут telegram_user_id=-1 —
    это действие самого KJ, не гость, в списке гостей быть не должно."""
    resp = client.post(
        "/api/kj/order/manual",
        json={"song_title": "Ручная песня", "table_no": 3},
        headers=_kj_headers(kj),
    )
    assert resp.status_code == 201

    guests = client.get(f"/api/kj/guests/{club.club_id}", headers=_kj_headers(kj)).get_json()["data"]
    assert guests == []


def test_list_guests_scoped_to_own_club(client, db, club, other_club, kj):
    now = datetime.now(timezone.utc)
    _make_order(club.club_id, 111, table_no=5, created_at=now)
    _make_order(other_club.club_id, 999, table_no=1, created_at=now)

    guests = client.get(f"/api/kj/guests/{club.club_id}", headers=_kj_headers(kj)).get_json()["data"]
    ids = {row["guest_id"] for row in guests}
    assert ids == {"111"}


def test_list_guests_cannot_use_other_clubs_url(client, db, club, other_club, kj):
    resp = client.get(f"/api/kj/guests/{other_club.club_id}", headers=_kj_headers(kj))
    assert resp.status_code == 403


# --- Статистика по вечеру/неделе/месяцу ---

def test_orders_counted_into_correct_time_windows(client, db, club, kj):
    now = datetime.now(timezone.utc)
    _make_order(club.club_id, 111, table_no=5, created_at=now - timedelta(hours=2))       # вечер+неделя+месяц
    _make_order(club.club_id, 111, table_no=5, created_at=now - timedelta(days=3))         # неделя+месяц
    _make_order(club.club_id, 111, table_no=5, created_at=now - timedelta(days=20))        # только месяц
    _make_order(club.club_id, 111, table_no=5, created_at=now - timedelta(days=40))        # вне окна вообще

    guest = client.get(f"/api/kj/guests/{club.club_id}", headers=_kj_headers(kj)).get_json()["data"][0]
    assert guest["orders_evening"] == 1
    assert guest["orders_week"] == 2
    assert guest["orders_month"] == 3


# --- GET /guests/<club_id>/<guest_id> (карточка) ---

def test_get_guest_detail_not_found(client, db, club, kj):
    resp = client.get(f"/api/kj/guests/{club.club_id}/999999", headers=_kj_headers(kj))
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "GUEST_NOT_FOUND"


def test_get_guest_detail_shows_favorites(client, db, club, kj):
    guest_id = _link_google_guest(client, club.club_id, table_no=8)
    db.session.add(Favorite(club_id=club.club_id, telegram_user_id=guest_id, song_title="Любимая песня", artist="X"))
    db.session.commit()

    resp = client.get(f"/api/kj/guests/{club.club_id}/{guest_id}", headers=_kj_headers(kj))
    assert resp.status_code == 200
    data = resp.get_json()["data"]
    assert data["table_no"] == 8
    assert data["guest_type"] == "client"
    assert len(data["favorites"]) == 1
    assert data["favorites"][0]["song_title"] == "Любимая песня"


def test_get_guest_detail_invalid_id(client, db, club, kj):
    resp = client.get(f"/api/kj/guests/{club.club_id}/not-a-number", headers=_kj_headers(kj))
    assert resp.status_code == 400
