"""
Тесты категорий песни (доп. ТЗ "KJ Pro", KJ-01/KJ-03/KJ-07): категория —
то же самое, что модель Service ("услуга/тариф", уже была в проекте и
видна гостю через GET /api/guest/services) — здесь KJ получает
возможность сам добавлять/менять/удалять их, а не только через прямую
правку базы. См. services/category_service.py за полным обоснованием
(в т.ч. набор DEFAULT_CATEGORIES — реальные данные из старого бота).
"""
from models import Order, Service


def _headers(token):
    return {"Authorization": f"Bearer {token}"}


def test_requires_auth(client, db, club):
    resp = client.get(f"/api/kj/categories/{club.club_id}")
    assert resp.status_code == 401


def test_list_seeds_defaults_when_empty(client, db, club, kj):
    resp = client.get(f"/api/kj/categories/{club.club_id}", headers=_headers(kj["token"]))
    assert resp.status_code == 200
    names = [c["name"] for c in resp.get_json()["data"]]
    assert names == ["KARAOKE", "KARAOKE BACK", "INTERNET", "KJ VOCAL", "CRAZY", "BONUS"]

    # Второй вызов не должен задваивать записи.
    resp2 = client.get(f"/api/kj/categories/{club.club_id}", headers=_headers(kj["token"]))
    assert len(resp2.get_json()["data"]) == 6


def test_list_does_not_reseed_when_categories_exist(client, db, club, kj):
    db.session.add(Service(club_id=club.club_id, name="Своя категория", price=50))
    db.session.commit()

    resp = client.get(f"/api/kj/categories/{club.club_id}", headers=_headers(kj["token"]))
    names = [c["name"] for c in resp.get_json()["data"]]
    assert names == ["Своя категория"]


def test_list_scoped_to_own_club(client, db, club, other_club, kj, other_kj):
    resp = client.get(f"/api/kj/categories/{other_club.club_id}", headers=_headers(kj["token"]))
    assert resp.status_code == 403


def test_create_category(client, db, club, kj):
    resp = client.post(
        f"/api/kj/categories/{club.club_id}",
        json={"name": "Дуэт", "description": "На двоих", "price": 150, "is_free": False},
        headers=_headers(kj["token"]),
    )
    assert resp.status_code == 201
    data = resp.get_json()["data"]
    assert data["name"] == "Дуэт"
    assert data["price"] == 150.0
    assert data["is_free"] is False


def test_create_category_empty_name_rejected(client, db, club, kj):
    resp = client.post(
        f"/api/kj/categories/{club.club_id}",
        json={"name": "  ", "price": 10},
        headers=_headers(kj["token"]),
    )
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "VALIDATION_ERROR"


def test_create_category_bad_price_rejected(client, db, club, kj):
    resp = client.post(
        f"/api/kj/categories/{club.club_id}",
        json={"name": "Категория", "price": "не число"},
        headers=_headers(kj["token"]),
    )
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "VALIDATION_ERROR"


def test_update_category_price_and_free_flag(client, db, club, kj):
    category = Service(club_id=club.club_id, name="Обычная", price=35)
    db.session.add(category)
    db.session.commit()

    resp = client.put(
        f"/api/kj/categories/{club.club_id}/{category.id}",
        json={"price": 999, "is_free": True},
        headers=_headers(kj["token"]),
    )
    assert resp.status_code == 200
    data = resp.get_json()["data"]
    assert data["price"] == 999.0
    assert data["is_free"] is True
    assert data["name"] == "Обычная"  # не тронуто, т.к. не передавалось


def test_update_category_not_found(client, db, club, kj):
    resp = client.put(
        f"/api/kj/categories/{club.club_id}/999999",
        json={"price": 10},
        headers=_headers(kj["token"]),
    )
    assert resp.status_code == 404


def test_delete_unused_category(client, db, club, kj):
    category = Service(club_id=club.club_id, name="Ненужная", price=10)
    db.session.add(category)
    db.session.commit()
    category_id = category.id

    resp = client.delete(f"/api/kj/categories/{club.club_id}/{category_id}", headers=_headers(kj["token"]))
    assert resp.status_code == 200
    assert db.session.get(Service, category_id) is None


def test_delete_category_in_use_blocked(client, db, club, kj):
    category = Service(club_id=club.club_id, name="В деле", price=10)
    db.session.add(category)
    db.session.commit()

    order = Order(
        telegram_user_id=1, club_id=club.club_id, table_no=1,
        guest_type="client", song_title="Песня", source="guest",
        service_id=category.id,
    )
    db.session.add(order)
    db.session.commit()

    resp = client.delete(f"/api/kj/categories/{club.club_id}/{category.id}", headers=_headers(kj["token"]))
    assert resp.status_code == 409
    assert resp.get_json()["error"] == "CATEGORY_IN_USE"
    assert db.session.get(Service, category.id) is not None
