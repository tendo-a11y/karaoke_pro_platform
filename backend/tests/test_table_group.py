"""
Тесты группового стола (Role 3/4/5) — утверждённая пользователем
спецификация, вариант А: полноценный шлюз (нельзя заказывать за занятым
столом без одобрения текущего админа). См. services/table_group_service.py
и согласованный аудит-отчёт по "Групповому столу/Присоединению/Управлению
группой" перед этим шагом.
"""
import uuid

from extensions import db as _db
from models import STATUS_TABLE_JOIN_PENDING, TableGroup, TableGroupMember, TableJoinRequest


def _headers(token):
    return {"Authorization": f"Bearer {token}"}


def _session(client, club_id, table_no=5):
    """ТЗ п.45 (финальная единая модель входа): QR никогда не приносит
    номер стола — сессия всегда создаётся без стола, а стол выбирается
    вместе с обязательным входом через Google, одним действием. Групповая
    механика стола (весь этот файл) начинается именно с этого действия, а
    не с создания сессии — здесь оба шага объединены в один помощник,
    чтобы не переписывать раскладку каждого теста ниже. table_no=None
    означает, что гость сознательно останавливается на Role 5 — второй шаг
    (стол + Google) не выполняется вовсе, group-механика его не касается.
    guest_id не меняется (аккаунт с этим mock-sub создаётся впервые),
    поэтому исходный guest_id остаётся тем же самым и дальше по тесту."""
    resp = client.post("/api/guest/session", json={"club_id": club_id})
    session = resp.get_json()["data"]
    if table_no is None:
        return session

    sub = f"mock-sub-{uuid.uuid4().hex[:12]}"
    linked = client.post(
        "/api/guest/profile/link-google",
        json={"table_no": table_no, "google_credential": {"sub": sub}},
        headers=_headers(session["token"]),
    )
    assert linked.status_code == 200
    return linked.get_json()["data"]


def _create_order(client, token, song_title="Песня"):
    return client.post(
        "/api/guest/order", json={"song_title": song_title}, headers=_headers(token),
    )


# --- Первый гость на пустом столе становится админом сразу ---
def test_first_guest_becomes_admin_immediately(client, db, club):
    session = _session(client, club.club_id, table_no=10)
    assert session["table_group_status"] == "admin"

    resp = _create_order(client, session["token"])
    assert resp.status_code == 201


def test_no_table_guest_unaffected_by_group_mechanics(client, db, club):
    """Role 5 — эта механика на них не распространяется вообще (утверждённое
    решение). ТЗ п.45: заказ без стола теперь заблокирован (см.
    tests/test_guest_identity.py::test_order_blocked_until_table_and_google_done)
    — здесь проверяем только то, что групповой стол их по-прежнему не
    трогает."""
    session = _session(client, club.club_id, table_no=None)
    assert "table_group_status" not in session or session.get("table_group_status") is None

    resp = _create_order(client, session["token"])
    assert resp.status_code == 409
    assert resp.get_json()["error"] == "TABLE_REQUIRED"

    resp = client.get("/api/guest/table-group", headers=_headers(session["token"]))
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "NO_TABLE"


def test_reopening_session_does_not_create_duplicate_group_or_request(client, db, club):
    """Гость, уже являющийся админом/участником, при повторном
    /api/guest/session не должен ни создавать вторую группу, ни попадать в
    pending."""
    session = _session(client, club.club_id, table_no=11)
    assert session["table_group_status"] == "admin"

    # Тот же guest_id пришёл снова (например, переоткрыл вкладку — сервер
    # не знает разницы, идентичность определяется тем же guest_id, которого
    # в реальном фронтенде обеспечивает localStorage) — здесь эмулируем
    # прямым вызовом сервиса тем же guest_id.
    from services import table_group_service
    state = table_group_service.ensure_session_group_state(club.club_id, 11, int(session["guest_id"]))
    assert state.status == "admin"
    assert TableGroup.query.filter_by(club_id=club.club_id, table_no=11).count() == 1


# --- Присоединение к занятому столу ---
def test_second_guest_at_occupied_table_is_pending(client, db, club):
    admin_session = _session(client, club.club_id, table_no=20)
    guest_session = _session(client, club.club_id, table_no=20)

    assert admin_session["table_group_status"] == "admin"
    assert guest_session["table_group_status"] == "pending"

    resp = _create_order(client, guest_session["token"])
    assert resp.status_code == 403
    assert resp.get_json()["error"] == "TABLE_ACCESS_REQUIRED"


def test_pending_guest_sees_pending_via_me(client, db, club):
    _session(client, club.club_id, table_no=21)
    guest_session = _session(client, club.club_id, table_no=21)

    resp = client.get("/api/guest/me", headers=_headers(guest_session["token"]))
    assert resp.get_json()["data"]["table_group_status"] == "pending"


def test_reopening_pending_session_does_not_create_duplicate_request(client, db, club):
    _session(client, club.club_id, table_no=22)
    guest_session = _session(client, club.club_id, table_no=22)
    _session_again = _session(client, club.club_id, table_no=22)  # same club/table, NEW guest_id though

    # Повторный запрос ТЕМ ЖЕ guest_id не должен плодить вторую заявку.
    # guest_id из API — строка (см. models.py::TableGroup.to_dict()), а
    # сервис/колонка BigInteger ждут int — приводим явно.
    from services import table_group_service
    table_group_service.ensure_session_group_state(club.club_id, 22, int(guest_session["guest_id"]))
    count = TableJoinRequest.query.filter_by(
        club_id=club.club_id, table_no=22, guest_id=int(guest_session["guest_id"]),
    ).count()
    assert count == 1


def test_table_full_returns_409_on_session_create(client, db, club, app):
    _session(client, club.club_id, table_no=23)
    with app.app_context():
        # Заполняем стол до MAX_GROUP_SIZE (дефолт 4) руками — 3 участника + админ = 4.
        for i in range(3):
            _db.session.add(TableGroupMember(club_id=club.club_id, table_no=23, guest_id=9000 + i))
        _db.session.commit()

    late_guest = _session(client, club.club_id, table_no=23)
    assert late_guest["table_group_status"] == "pending"  # заявку подать можно, стол просто ждёт одобрения


# --- Одобрение / отклонение ---
def test_admin_approves_join_request(client, db, club):
    admin_session = _session(client, club.club_id, table_no=30)
    guest_session = _session(client, club.club_id, table_no=30)

    view = client.get("/api/guest/table-group", headers=_headers(admin_session["token"])).get_json()["data"]
    assert view["is_admin"] is True
    assert len(view["pending_requests"]) == 1
    request_id = view["pending_requests"][0]["id"]

    resp = client.post(
        f"/api/guest/table-group/join-requests/{request_id}/approve", headers=_headers(admin_session["token"]),
    )
    assert resp.status_code == 200
    assert resp.get_json()["data"]["status"] == "approved"

    # Теперь одобренный гость может заказывать.
    order_resp = _create_order(client, guest_session["token"])
    assert order_resp.status_code == 201

    me = client.get("/api/guest/me", headers=_headers(guest_session["token"])).get_json()["data"]
    assert me["table_group_status"] == "member"


def test_non_admin_cannot_approve(client, db, club):
    admin_session = _session(client, club.club_id, table_no=31)
    guest_session = _session(client, club.club_id, table_no=31)

    view = client.get("/api/guest/table-group", headers=_headers(admin_session["token"])).get_json()["data"]
    request_id = view["pending_requests"][0]["id"]

    resp = client.post(
        f"/api/guest/table-group/join-requests/{request_id}/approve", headers=_headers(guest_session["token"]),
    )
    assert resp.status_code == 403
    assert resp.get_json()["error"] == "FORBIDDEN"


def test_admin_rejects_join_request(client, db, club):
    admin_session = _session(client, club.club_id, table_no=32)
    guest_session = _session(client, club.club_id, table_no=32)

    view = client.get("/api/guest/table-group", headers=_headers(admin_session["token"])).get_json()["data"]
    request_id = view["pending_requests"][0]["id"]

    resp = client.post(
        f"/api/guest/table-group/join-requests/{request_id}/reject", headers=_headers(admin_session["token"]),
    )
    assert resp.status_code == 200
    assert resp.get_json()["data"]["status"] == "rejected"

    order_resp = _create_order(client, guest_session["token"])
    assert order_resp.status_code == 403


def test_rejected_guest_can_request_again(client, db, club):
    """Как и в старом коде — повторная заявка после отказа не блокируется,
    защита только от дубликата PENDING заявки."""
    admin_session = _session(client, club.club_id, table_no=33)
    guest_session = _session(client, club.club_id, table_no=33)
    view = client.get("/api/guest/table-group", headers=_headers(admin_session["token"])).get_json()["data"]
    request_id = view["pending_requests"][0]["id"]
    client.post(f"/api/guest/table-group/join-requests/{request_id}/reject", headers=_headers(admin_session["token"]))

    from services import table_group_service
    state = table_group_service.ensure_session_group_state(club.club_id, 33, int(guest_session["guest_id"]))
    assert state.status == "pending"
    pending_count = TableJoinRequest.query.filter_by(
        club_id=club.club_id, table_no=33, guest_id=int(guest_session["guest_id"]), status=STATUS_TABLE_JOIN_PENDING,
    ).count()
    assert pending_count == 1


def test_approve_rechecks_limit_and_autorejects_when_full(client, db, club, app):
    admin_session = _session(client, club.club_id, table_no=34)
    guest_session = _session(client, club.club_id, table_no=34)
    view = client.get("/api/guest/table-group", headers=_headers(admin_session["token"])).get_json()["data"]
    request_id = view["pending_requests"][0]["id"]

    with app.app_context():
        for i in range(3):
            _db.session.add(TableGroupMember(club_id=club.club_id, table_no=34, guest_id=9100 + i))
        _db.session.commit()

    resp = client.post(
        f"/api/guest/table-group/join-requests/{request_id}/approve", headers=_headers(admin_session["token"]),
    )
    assert resp.status_code == 409
    assert resp.get_json()["error"] == "TABLE_FULL"

    order_resp = _create_order(client, guest_session["token"])
    assert order_resp.status_code == 403


def test_approve_nonexistent_request_404(client, db, club):
    admin_session = _session(client, club.club_id, table_no=35)
    resp = client.post(
        "/api/guest/table-group/join-requests/999999/approve", headers=_headers(admin_session["token"]),
    )
    assert resp.status_code == 404


def test_approve_already_decided_returns_409(client, db, club):
    admin_session = _session(client, club.club_id, table_no=36)
    guest_session = _session(client, club.club_id, table_no=36)
    view = client.get("/api/guest/table-group", headers=_headers(admin_session["token"])).get_json()["data"]
    request_id = view["pending_requests"][0]["id"]
    client.post(f"/api/guest/table-group/join-requests/{request_id}/approve", headers=_headers(admin_session["token"]))

    resp = client.post(
        f"/api/guest/table-group/join-requests/{request_id}/approve", headers=_headers(admin_session["token"]),
    )
    assert resp.status_code == 409
    assert resp.get_json()["error"] == "ALREADY_DECIDED"


# --- Кик ---
def test_admin_kicks_member(client, db, club):
    admin_session = _session(client, club.club_id, table_no=40)
    guest_session = _session(client, club.club_id, table_no=40)
    view = client.get("/api/guest/table-group", headers=_headers(admin_session["token"])).get_json()["data"]
    request_id = view["pending_requests"][0]["id"]
    client.post(f"/api/guest/table-group/join-requests/{request_id}/approve", headers=_headers(admin_session["token"]))

    resp = client.post(
        f"/api/guest/table-group/kick/{guest_session['guest_id']}", headers=_headers(admin_session["token"]),
    )
    assert resp.status_code == 200
    assert resp.get_json()["data"]["kicked"] is True

    order_resp = _create_order(client, guest_session["token"])
    assert order_resp.status_code == 403


def test_non_admin_cannot_kick(client, db, club):
    admin_session = _session(client, club.club_id, table_no=41)
    guest_session = _session(client, club.club_id, table_no=41)
    view = client.get("/api/guest/table-group", headers=_headers(admin_session["token"])).get_json()["data"]
    request_id = view["pending_requests"][0]["id"]
    client.post(f"/api/guest/table-group/join-requests/{request_id}/approve", headers=_headers(admin_session["token"]))

    resp = client.post(
        f"/api/guest/table-group/kick/{admin_session['guest_id']}", headers=_headers(guest_session["token"]),
    )
    assert resp.status_code == 403


def test_admin_cannot_kick_self(client, db, club):
    admin_session = _session(client, club.club_id, table_no=42)
    resp = client.post(
        f"/api/guest/table-group/kick/{admin_session['guest_id']}", headers=_headers(admin_session["token"]),
    )
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "CANNOT_KICK_SELF"


def test_kick_non_member_404(client, db, club):
    admin_session = _session(client, club.club_id, table_no=43)
    resp = client.post(
        "/api/guest/table-group/kick/123456789", headers=_headers(admin_session["token"]),
    )
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "NOT_A_MEMBER"


def test_kicked_orders_are_not_cancelled(client, db, club):
    """Утверждённое решение: заказы при кике/выходе не отменяются и не
    удаляются — меняется только членство."""
    admin_session = _session(client, club.club_id, table_no=44)
    guest_session = _session(client, club.club_id, table_no=44)
    view = client.get("/api/guest/table-group", headers=_headers(admin_session["token"])).get_json()["data"]
    request_id = view["pending_requests"][0]["id"]
    client.post(f"/api/guest/table-group/join-requests/{request_id}/approve", headers=_headers(admin_session["token"]))
    order_resp = _create_order(client, guest_session["token"], song_title="Останется")
    order_id = order_resp.get_json()["data"]["id"]

    client.post(
        f"/api/guest/table-group/kick/{guest_session['guest_id']}", headers=_headers(admin_session["token"]),
    )

    orders = client.get("/api/guest/orders", headers=_headers(guest_session["token"])).get_json()["data"]
    assert any(o["id"] == order_id for o in orders)


# --- Передача прав администратора ---
def test_admin_transfers_rights(client, db, club):
    admin_session = _session(client, club.club_id, table_no=50)
    guest_session = _session(client, club.club_id, table_no=50)
    view = client.get("/api/guest/table-group", headers=_headers(admin_session["token"])).get_json()["data"]
    request_id = view["pending_requests"][0]["id"]
    client.post(f"/api/guest/table-group/join-requests/{request_id}/approve", headers=_headers(admin_session["token"]))

    resp = client.post(
        f"/api/guest/table-group/transfer/{guest_session['guest_id']}", headers=_headers(admin_session["token"]),
    )
    assert resp.status_code == 200

    new_view = client.get("/api/guest/table-group", headers=_headers(guest_session["token"])).get_json()["data"]
    assert new_view["is_admin"] is True

    old_view = client.get("/api/guest/table-group", headers=_headers(admin_session["token"])).get_json()["data"]
    assert old_view["is_admin"] is False
    # старый админ остаётся участником стола — передача прав не выгоняет его
    assert any(m["guest_id"] == admin_session["guest_id"] for m in old_view["members"])


def test_non_admin_cannot_transfer(client, db, club):
    admin_session = _session(client, club.club_id, table_no=51)
    guest_session = _session(client, club.club_id, table_no=51)
    resp = client.post(
        f"/api/guest/table-group/transfer/{admin_session['guest_id']}", headers=_headers(guest_session["token"]),
    )
    assert resp.status_code == 403


def test_transfer_to_non_member_404(client, db, club):
    admin_session = _session(client, club.club_id, table_no=52)
    resp = client.post(
        "/api/guest/table-group/transfer/123456789", headers=_headers(admin_session["token"]),
    )
    assert resp.status_code == 404


# --- Самостоятельный выход ---
def test_member_leaves_voluntarily(client, db, club):
    admin_session = _session(client, club.club_id, table_no=60)
    guest_session = _session(client, club.club_id, table_no=60)
    view = client.get("/api/guest/table-group", headers=_headers(admin_session["token"])).get_json()["data"]
    request_id = view["pending_requests"][0]["id"]
    client.post(f"/api/guest/table-group/join-requests/{request_id}/approve", headers=_headers(admin_session["token"]))

    resp = client.post("/api/guest/table-group/leave", headers=_headers(guest_session["token"]))
    assert resp.status_code == 200
    assert resp.get_json()["data"]["left"] is True

    order_resp = _create_order(client, guest_session["token"])
    assert order_resp.status_code == 403


def test_admin_leaves_and_oldest_member_becomes_new_admin(client, db, club):
    admin_session = _session(client, club.club_id, table_no=61)
    guest1 = _session(client, club.club_id, table_no=61)
    guest2 = _session(client, club.club_id, table_no=61)

    view = client.get("/api/guest/table-group", headers=_headers(admin_session["token"])).get_json()["data"]
    for req in view["pending_requests"]:
        client.post(f"/api/guest/table-group/join-requests/{req['id']}/approve", headers=_headers(admin_session["token"]))

    resp = client.post("/api/guest/table-group/leave", headers=_headers(admin_session["token"]))
    assert resp.status_code == 200

    new_view = client.get("/api/guest/table-group", headers=_headers(guest1["token"])).get_json()["data"]
    # guest1 присоединился раньше guest2 -> должен стать новым админом
    assert new_view["is_admin"] is True

    guest2_view = client.get("/api/guest/table-group", headers=_headers(guest2["token"])).get_json()["data"]
    assert guest2_view["is_admin"] is False

    # старый админ реально ушёл — не заказывает без нового одобрения
    order_resp = _create_order(client, admin_session["token"])
    assert order_resp.status_code == 403


def test_last_member_leaves_group_is_deleted(client, db, club):
    admin_session = _session(client, club.club_id, table_no=62)
    resp = client.post("/api/guest/table-group/leave", headers=_headers(admin_session["token"]))
    assert resp.status_code == 200

    assert TableGroup.query.filter_by(club_id=club.club_id, table_no=62).count() == 0

    # стол снова свободен — следующий гость становится админом сразу
    next_session = _session(client, club.club_id, table_no=62)
    assert next_session["table_group_status"] == "admin"


def test_leave_non_member_404(client, db, club):
    session = _session(client, club.club_id, table_no=63)
    _db.session.query(TableGroupMember).filter_by(
        club_id=club.club_id, table_no=63, guest_id=int(session["guest_id"]),
    ).delete()
    _db.session.commit()

    resp = client.post("/api/guest/table-group/leave", headers=_headers(session["token"]))
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "NOT_A_MEMBER"


# --- После выхода/кика статус не "pending", а "not_joined"; можно запросить снова ---
def test_status_after_leaving_is_not_joined_not_pending(client, db, club):
    admin_session = _session(client, club.club_id, table_no=64)
    guest_session = _session(client, club.club_id, table_no=64)
    view = client.get("/api/guest/table-group", headers=_headers(admin_session["token"])).get_json()["data"]
    request_id = view["pending_requests"][0]["id"]
    client.post(f"/api/guest/table-group/join-requests/{request_id}/approve", headers=_headers(admin_session["token"]))

    client.post("/api/guest/table-group/leave", headers=_headers(guest_session["token"]))

    me = client.get("/api/guest/me", headers=_headers(guest_session["token"])).get_json()["data"]
    assert me["table_group_status"] == "not_joined"


def test_status_after_being_kicked_is_not_joined(client, db, club):
    admin_session = _session(client, club.club_id, table_no=65)
    guest_session = _session(client, club.club_id, table_no=65)
    view = client.get("/api/guest/table-group", headers=_headers(admin_session["token"])).get_json()["data"]
    request_id = view["pending_requests"][0]["id"]
    client.post(f"/api/guest/table-group/join-requests/{request_id}/approve", headers=_headers(admin_session["token"]))
    client.post(
        f"/api/guest/table-group/kick/{guest_session['guest_id']}", headers=_headers(admin_session["token"]),
    )

    me = client.get("/api/guest/me", headers=_headers(guest_session["token"])).get_json()["data"]
    assert me["table_group_status"] == "not_joined"


def test_request_join_after_leaving_creates_new_pending_request(client, db, club):
    admin_session = _session(client, club.club_id, table_no=66)
    guest_session = _session(client, club.club_id, table_no=66)
    view = client.get("/api/guest/table-group", headers=_headers(admin_session["token"])).get_json()["data"]
    request_id = view["pending_requests"][0]["id"]
    client.post(f"/api/guest/table-group/join-requests/{request_id}/approve", headers=_headers(admin_session["token"]))
    client.post("/api/guest/table-group/leave", headers=_headers(guest_session["token"]))

    resp = client.post("/api/guest/table-group/request-join", headers=_headers(guest_session["token"]))
    assert resp.status_code == 200
    assert resp.get_json()["data"]["status"] == "pending"

    me = client.get("/api/guest/me", headers=_headers(guest_session["token"])).get_json()["data"]
    assert me["table_group_status"] == "pending"


def test_request_join_same_identity_does_not_issue_new_guest_id(client, db, club):
    """Отличие от POST /api/guest/session: та же личность, история заказов
    гостя не должна теряться."""
    admin_session = _session(client, club.club_id, table_no=67)
    guest_session = _session(client, club.club_id, table_no=67)
    view = client.get("/api/guest/table-group", headers=_headers(admin_session["token"])).get_json()["data"]
    request_id = view["pending_requests"][0]["id"]
    client.post(f"/api/guest/table-group/join-requests/{request_id}/approve", headers=_headers(admin_session["token"]))
    order_resp = _create_order(client, guest_session["token"], song_title="До выхода")
    order_id = order_resp.get_json()["data"]["id"]

    client.post("/api/guest/table-group/leave", headers=_headers(guest_session["token"]))
    client.post("/api/guest/table-group/request-join", headers=_headers(guest_session["token"]))

    orders = client.get("/api/guest/orders", headers=_headers(guest_session["token"])).get_json()["data"]
    assert any(o["id"] == order_id for o in orders)


# --- Постоянная идентификация (ТЗ п.45): вход под уже существующим
# Google-профилем переносит членство/заявку на новую личность ---
def test_google_link_to_existing_profile_carries_over_membership(client, db, club, app):
    admin_session = _session(client, club.club_id, table_no=70)
    guest_session = _session(client, club.club_id, table_no=70)
    view = client.get("/api/guest/table-group", headers=_headers(admin_session["token"])).get_json()["data"]
    request_id = view["pending_requests"][0]["id"]
    client.post(f"/api/guest/table-group/join-requests/{request_id}/approve", headers=_headers(admin_session["token"]))

    # Постоянный профиль уже существует (как если бы гость привязал Google
    # в прошлый визит) — здесь важен только перенос членства при входе под
    # уже существующим постоянным номером, см. transfer_identity.
    from models import GuestAccount
    with app.app_context():
        account = GuestAccount(club_id=club.club_id, telegram_user_id=555555, google_sub="existing-sub-70")
        _db.session.add(account)
        _db.session.commit()

    resp = client.post(
        "/api/guest/profile/link-google",
        json={"google_credential": {"sub": "existing-sub-70"}},
        headers=_headers(guest_session["token"]),
    )
    assert resp.status_code == 200
    new_token = resp.get_json()["data"]["token"]

    # Уже существующий постоянный профиль должен быть полноправным
    # участником стола, без повторного одобрения.
    order_resp = _create_order(client, new_token)
    assert order_resp.status_code == 201

    me = client.get("/api/guest/me", headers=_headers(new_token)).get_json()["data"]
    assert me["table_group_status"] == "member"


def test_google_link_to_existing_profile_carries_over_admin_status(client, db, club, app):
    from models import GuestAccount

    admin_session = _session(client, club.club_id, table_no=71)
    with app.app_context():
        account = GuestAccount(club_id=club.club_id, telegram_user_id=555556, google_sub="existing-sub-71")
        _db.session.add(account)
        _db.session.commit()

    resp = client.post(
        "/api/guest/profile/link-google",
        json={"google_credential": {"sub": "existing-sub-71"}},
        headers=_headers(admin_session["token"]),
    )
    new_token = resp.get_json()["data"]["token"]

    view = client.get("/api/guest/table-group", headers=_headers(new_token)).get_json()["data"]
    assert view["is_admin"] is True


def test_google_link_to_existing_profile_carries_over_pending_request(client, db, club, app):
    from models import GuestAccount

    _session(client, club.club_id, table_no=72)  # admin
    guest_session = _session(client, club.club_id, table_no=72)  # pending

    with app.app_context():
        account = GuestAccount(club_id=club.club_id, telegram_user_id=555557, google_sub="existing-sub-72")
        _db.session.add(account)
        _db.session.commit()

    resp = client.post(
        "/api/guest/profile/link-google",
        json={"google_credential": {"sub": "existing-sub-72"}},
        headers=_headers(guest_session["token"]),
    )
    new_token = resp.get_json()["data"]["token"]

    me = client.get("/api/guest/me", headers=_headers(new_token)).get_json()["data"]
    assert me["table_group_status"] == "pending"

    pending_count = TableJoinRequest.query.filter_by(
        club_id=club.club_id, table_no=72, guest_id=555557, status=STATUS_TABLE_JOIN_PENDING,
    ).count()
    assert pending_count == 1


# --- Групповое избранное (reorder тоже должен уважать шлюз) ---
def test_reorder_favorite_blocked_while_pending(client, db, club):
    admin_session = _session(client, club.club_id, table_no=80)
    guest_session = _session(client, club.club_id, table_no=80)

    fav_resp = client.post(
        "/api/guest/favorites", json={"song_title": "Избранная"}, headers=_headers(guest_session["token"]),
    )
    assert fav_resp.status_code == 201
    favorite_id = fav_resp.get_json()["data"]["id"]

    resp = client.post(
        f"/api/guest/favorites/{favorite_id}/reorder", headers=_headers(guest_session["token"]),
    )
    assert resp.status_code == 403
    assert resp.get_json()["error"] == "TABLE_ACCESS_REQUIRED"


# --- Требуется авторизация ---
def test_table_group_endpoints_require_auth(client, db, club):
    resp = client.get("/api/guest/table-group")
    assert resp.status_code == 401
