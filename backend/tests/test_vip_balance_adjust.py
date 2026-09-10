"""
Тесты ручной корректировки VIP-баланса со стороны KJ (Role 2) — старое:
handlers/kj.py::balance_add/balance_sub/balance_set, database.py
::update_vip_balance/set_vip_balance. Гость просит пополнение УСТНО, в
баре — это не цифровая заявка гость→KJ (в отличие от VIP-заявки на
членство, test_vip.py), а прямое действие KJ над уже существующим
VIP-счётом.

Исправленные по сравнению со старым кодом баги (см. аудит-отчёт по
VIP-пополнению перед этим шагом):
  - каждое действие теперь пишет строку в Transaction (в старом коде —
    вообще ничего не писалось, найденный баг №7);
  - проверка роли гарантирована структурно (/api/kj/* + @require_kj), а не
    отсутствует внутри обработчика, как было в старом коде (баг №3);
  - проверка принадлежности VIP-клиента своему клубу (как и везде в этом
    бэкенде), которой в старом коде не было вовсе (единая SQLite на всех).

Сознательно НЕ исправлено (перенесено 1:1 из старого кода как есть):
  - нет защиты от ухода баланса в минус при списании (старый баг №2 —
    отсутствие проверки, а не активная блокировка; исправление было бы
    новой бизнес-логикой, а не переносом старой).
"""
from decimal import Decimal

from models import Transaction, TX_TYPE_MANUAL_DEBIT, TX_TYPE_TOPUP, VipClient


def _headers(token):
    return {"Authorization": f"Bearer {token}"}


def _make_vip(db, club_id, telegram_user_id=987654321, balance="10.00", cashback_percent=0):
    vip = VipClient(
        club_id=club_id, telegram_user_id=telegram_user_id,
        balance=Decimal(balance), cashback_percent=cashback_percent,
    )
    db.session.add(vip)
    db.session.commit()
    return vip


def test_topup_adds_to_balance_and_records_transaction(client, db, club, kj):
    vip = _make_vip(db, club.club_id, balance="10.00")

    resp = client.post(
        f"/api/kj/vip-clients/{vip.id}/topup", json={"amount": 25},
        headers=_headers(kj["token"]),
    )
    assert resp.status_code == 200, resp.get_json()
    data = resp.get_json()["data"]
    assert data["balance"] == 35.0

    tx = Transaction.query.filter_by(club_id=club.club_id, telegram_user_id=vip.telegram_user_id).one()
    assert tx.type == TX_TYPE_TOPUP
    assert float(tx.amount) == 25.0
    assert tx.order_id is None


def test_debit_subtracts_from_balance_and_records_transaction(client, db, club, kj):
    vip = _make_vip(db, club.club_id, balance="10.00")

    resp = client.post(
        f"/api/kj/vip-clients/{vip.id}/debit", json={"amount": 4},
        headers=_headers(kj["token"]),
    )
    assert resp.status_code == 200, resp.get_json()
    data = resp.get_json()["data"]
    assert data["balance"] == 6.0

    tx = Transaction.query.filter_by(club_id=club.club_id, telegram_user_id=vip.telegram_user_id).one()
    assert tx.type == TX_TYPE_MANUAL_DEBIT
    assert float(tx.amount) == 4.0


def test_debit_allows_going_negative_same_as_old_code(client, db, club, kj):
    """Старое поведение 1:1: нет защиты от ухода в минус (см. docstring
    модуля/аудит-отчёт, баг №2)."""
    vip = _make_vip(db, club.club_id, balance="5.00")

    resp = client.post(
        f"/api/kj/vip-clients/{vip.id}/debit", json={"amount": 20},
        headers=_headers(kj["token"]),
    )
    assert resp.status_code == 200, resp.get_json()
    assert resp.get_json()["data"]["balance"] == -15.0


def test_set_balance_computes_correct_delta_and_transaction_type(client, db, club, kj):
    vip = _make_vip(db, club.club_id, balance="10.00")

    resp = client.put(
        f"/api/kj/vip-clients/{vip.id}/balance", json={"balance": 50},
        headers=_headers(kj["token"]),
    )
    assert resp.status_code == 200, resp.get_json()
    assert resp.get_json()["data"]["balance"] == 50.0
    tx = Transaction.query.filter_by(club_id=club.club_id, telegram_user_id=vip.telegram_user_id).one()
    assert tx.type == TX_TYPE_TOPUP  # 50 > 10 -> считается начислением
    assert float(tx.amount) == 40.0

    # Установка ниже текущего значения -> считается списанием.
    resp = client.put(
        f"/api/kj/vip-clients/{vip.id}/balance", json={"balance": 5},
        headers=_headers(kj["token"]),
    )
    assert resp.status_code == 200, resp.get_json()
    assert resp.get_json()["data"]["balance"] == 5.0
    tx2 = (
        Transaction.query.filter_by(club_id=club.club_id, telegram_user_id=vip.telegram_user_id)
        .order_by(Transaction.id.desc()).first()
    )
    assert tx2.type == TX_TYPE_MANUAL_DEBIT
    assert float(tx2.amount) == 45.0


def test_set_balance_rejects_negative(client, db, club, kj):
    vip = _make_vip(db, club.club_id, balance="10.00")
    resp = client.put(
        f"/api/kj/vip-clients/{vip.id}/balance", json={"balance": -1},
        headers=_headers(kj["token"]),
    )
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "VALIDATION_ERROR"


def test_topup_rejects_non_positive_amount(client, db, club, kj):
    vip = _make_vip(db, club.club_id, balance="10.00")
    for bad in (0, -5):
        resp = client.post(
            f"/api/kj/vip-clients/{vip.id}/topup", json={"amount": bad},
            headers=_headers(kj["token"]),
        )
        assert resp.status_code == 400
        assert resp.get_json()["error"] == "VALIDATION_ERROR"


def test_topup_rejects_non_numeric_amount(client, db, club, kj):
    vip = _make_vip(db, club.club_id, balance="10.00")
    resp = client.post(
        f"/api/kj/vip-clients/{vip.id}/topup", json={"amount": "many"},
        headers=_headers(kj["token"]),
    )
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "VALIDATION_ERROR"


def test_topup_missing_vip_client_404(client, db, club, kj):
    resp = client.post(
        "/api/kj/vip-clients/999999/topup", json={"amount": 10},
        headers=_headers(kj["token"]),
    )
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "VIP_CLIENT_NOT_FOUND"


def test_kj_cannot_adjust_other_clubs_vip_client(client, db, club, other_club, kj, other_kj):
    vip = _make_vip(db, club.club_id, balance="10.00")

    resp = client.post(
        f"/api/kj/vip-clients/{vip.id}/topup", json={"amount": 10},
        headers=_headers(other_kj["token"]),
    )
    assert resp.status_code == 403
    assert resp.get_json()["error"] == "FORBIDDEN"

    resp = client.post(
        f"/api/kj/vip-clients/{vip.id}/debit", json={"amount": 10},
        headers=_headers(other_kj["token"]),
    )
    assert resp.status_code == 403

    resp = client.put(
        f"/api/kj/vip-clients/{vip.id}/balance", json={"balance": 10},
        headers=_headers(other_kj["token"]),
    )
    assert resp.status_code == 403

    # Баланс не изменился ни одной из трёх попыток.
    db.session.refresh(vip)
    assert float(vip.balance) == 10.0


def test_adjust_requires_kj_auth(client, db, club):
    vip = _make_vip(db, club.club_id, balance="10.00")
    resp = client.post(f"/api/kj/vip-clients/{vip.id}/topup", json={"amount": 10})
    assert resp.status_code == 401


def test_guest_sees_updated_balance_via_me(client, db, club, kj):
    """Гость не подаёт цифровую заявку — узнаёт о новом балансе через уже
    существующий поллинг /me, отдельный фронтенд-код не нужен."""
    resp = client.post("/api/guest/session", json={"club_id": club.club_id})
    session = resp.get_json()["data"]
    linked = client.post(
        "/api/guest/profile/link-google",
        json={"table_no": 8, "google_credential": {"sub": "mock-sub-balance-poll-test"}},
        headers=_headers(session["token"]),
    ).get_json()["data"]
    token = linked["token"]

    vip = _make_vip(db, club.club_id, telegram_user_id=int(linked["guest_id"]), balance="0.00")

    client.post(
        f"/api/kj/vip-clients/{vip.id}/topup", json={"amount": 15},
        headers=_headers(kj["token"]),
    )

    me = client.get("/api/guest/me", headers=_headers(token)).get_json()["data"]
    assert me["vip"]["balance"] == 15.0
