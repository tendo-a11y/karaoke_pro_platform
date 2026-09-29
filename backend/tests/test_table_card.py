"""
Тесты карточки стола в KJ Panel (запрос пользователя 2026-09-28): полный
состав компании за столом, закрытие стола сразу действием KJ (без ожидания
заявки гостя, см. services/table_close_service.py::close_table_directly) и
перенос стола на новый номер целиком (см. services/table_group_service.py::
move_table). См. также tests/test_table_close.py и tests/test_table_group.py
для базовой механики группового стола, которую этот файл не повторяет.

Ключевые решения пользователя, которые здесь проверяются:
  - карточка стола показывает ВСЕХ участников (TableGroupMember), а не
    только тех, у кого сейчас активный заказ (в отличие от доски "Заказы");
  - KJ может закрыть стол сразу с карточки, без предварительной заявки
    гостя — но точно той же механикой (чек, автоотклонение непроигранного,
    освобождение TableGroup);
  - если у стола уже висела не решённая заявка гостя на закрытие, прямое
    закрытие KJ помечает её отклонённой, а не оставляет висеть;
  - перенос стола (move) — по свободному номеру назначения, переносит
    группу, участников, ещё не решённые заявки на присоединение, живой
    стол каждого участника (GuestStatus) и ВСЕ заказы участников с текущим
    (старым) номером стола — и сыгранные, и ещё нет;
  - перенос на уже занятый стол назначения отклоняется, не сливает группы.
"""
import uuid

from extensions import db as _db
from models import (
    GuestStatus,
    STATUS_COMPLETED,
    STATUS_QUEUED,
    STATUS_TABLE_CLOSE_REJECTED,
    STATUS_TABLE_JOIN_PENDING,
    Order,
    TableCloseRequest,
    TableGroup,
    TableGroupMember,
    TableJoinRequest,
)


def _headers(token):
    return {"Authorization": f"Bearer {token}"}


def _session(client, club_id, table_no):
    """Тот же двухшаговый вход, что и в test_table_group.py::_session
    (ТЗ п.45: стол выбирается только вместе со входом через Google)."""
    resp = client.post("/api/guest/session", json={"club_id": club_id})
    session = resp.get_json()["data"]
    sub = f"mock-sub-{uuid.uuid4().hex[:12]}"
    linked = client.post(
        "/api/guest/profile/link-google",
        json={"table_no": table_no, "google_credential": {"sub": sub}},
        headers=_headers(session["token"]),
    )
    assert linked.status_code == 200
    return linked.get_json()["data"]


def _me(client, token):
    return client.get("/api/guest/me", headers=_headers(token)).get_json()["data"]


def _order(db, club_id, table_no, guest_id, status, song_title="Песня"):
    o = Order(
        telegram_user_id=guest_id, club_id=club_id, table_no=table_no, guest_type="client",
        song_title=song_title, status=status,
    )
    db.session.add(o)
    db.session.commit()
    return o


# --- Карточка стола: полный состав ---

def test_get_table_group_roster_lists_all_members(client, db, kj, club):
    admin_session = _session(client, club.club_id, table_no=40)
    guest_session = _session(client, club.club_id, table_no=40)
    request_id = client.get(
        "/api/guest/table-group", headers=_headers(admin_session["token"]),
    ).get_json()["data"]["pending_requests"][0]["id"]
    client.post(
        f"/api/guest/table-group/join-requests/{request_id}/approve", headers=_headers(admin_session["token"]),
    )

    resp = client.get("/api/kj/table-groups/1/40", headers=kj["headers"])
    assert resp.status_code == 200
    data = resp.get_json()["data"]
    assert data["table_no"] == 40
    assert data["admin_guest_id"] == admin_session["guest_id"]
    assert {m["guest_id"] for m in data["members"]} == {admin_session["guest_id"], guest_session["guest_id"]}
    admin_entry = next(m for m in data["members"] if m["guest_id"] == admin_session["guest_id"])
    member_entry = next(m for m in data["members"] if m["guest_id"] == guest_session["guest_id"])
    assert admin_entry["is_admin"] is True
    assert member_entry["is_admin"] is False
    assert "favorites" not in admin_entry


def test_get_table_group_empty_table_is_404(client, db, kj, club):
    resp = client.get("/api/kj/table-groups/1/41", headers=kj["headers"])
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "TABLE_EMPTY"


def test_list_table_groups_reports_occupied_numbers(client, db, kj, club):
    _session(client, club.club_id, table_no=42)
    _session(client, club.club_id, table_no=43)

    resp = client.get("/api/kj/table-groups/1", headers=kj["headers"])
    assert resp.status_code == 200
    data = resp.get_json()["data"]
    assert 42 in data["occupied_table_nos"]
    assert 43 in data["occupied_table_nos"]


# --- Закрытие стола сразу с карточки, без заявки гостя ---

def test_kj_closes_table_directly_without_guest_request(client, db, kj, club):
    admin_session = _session(client, club.club_id, table_no=50)
    guest_id = int(admin_session["guest_id"])
    _order(db, club.club_id, 50, guest_id, STATUS_COMPLETED, "Сыгранная")
    pending = _order(db, club.club_id, 50, guest_id, STATUS_QUEUED, "Ещё не сыграна")

    resp = client.put("/api/kj/table-groups/1/50/close", headers=kj["headers"], json={})
    assert resp.status_code == 200
    data = resp.get_json()["data"]
    assert data["request"]["status"] == "approved"
    assert data["request"]["receipt"]["song_count"] == 1
    assert pending.id in data["closed_order_ids"]

    with client.application.app_context():
        assert TableGroup.query.filter_by(club_id=1, table_no=50).first() is None
        assert Order.query.get(pending.id).status == "rejected"

    me = _me(client, admin_session["token"])
    assert me["table_close_receipt"]["receipt"]["song_count"] == 1


def test_kj_close_directly_clears_guest_status_table(client, db, kj, club):
    """
    ДОБАВЛЕНО (2026-09-29, отдельная находка при починке карточки стола):
    закрытие стола прямо с карточки должно освобождать не только
    TableGroup/TableGroupMember, но и GuestStatus.table_no у каждого, кто
    там сидел — иначе гость после закрытия продолжал бы числиться "за
    столом N" в своей собственной карточке (guest_directory_service.
    get_guest_detail) и в /api/guest/me, пока не зайдёт заново через
    Google. Проверяем и на админе, и на обычном участнике (не только на
    том, чей id использован для requested_by_guest_id).
    """
    admin_session = _session(client, club.club_id, table_no=54)
    member_session = _session(client, club.club_id, table_no=54)
    request_id = client.get(
        "/api/guest/table-group", headers=_headers(admin_session["token"]),
    ).get_json()["data"]["pending_requests"][0]["id"]
    client.post(
        f"/api/guest/table-group/join-requests/{request_id}/approve", headers=_headers(admin_session["token"]),
    )

    resp = client.put("/api/kj/table-groups/1/54/close", headers=kj["headers"], json={})
    assert resp.status_code == 200

    with client.application.app_context():
        admin_status = GuestStatus.query.filter_by(
            club_id=club.club_id, telegram_user_id=int(admin_session["guest_id"]),
        ).first()
        member_status = GuestStatus.query.filter_by(
            club_id=club.club_id, telegram_user_id=int(member_session["guest_id"]),
        ).first()
        assert admin_status.table_no is None
        assert member_status.table_no is None

    assert _me(client, admin_session["token"])["table_no"] is None
    assert _me(client, member_session["token"])["table_no"] is None


def test_kj_close_directly_hide_receipt(client, db, kj, club):
    admin_session = _session(client, club.club_id, table_no=51)
    guest_id = int(admin_session["guest_id"])
    _order(db, club.club_id, 51, guest_id, STATUS_COMPLETED)

    resp = client.put("/api/kj/table-groups/1/51/close", headers=kj["headers"], json={"hide_receipt": True})
    assert resp.status_code == 200

    me = _me(client, admin_session["token"])
    assert me.get("table_close_receipt") is None


def test_kj_close_directly_on_empty_table_is_404(client, db, kj, club):
    resp = client.put("/api/kj/table-groups/1/52/close", headers=kj["headers"], json={})
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "TABLE_EMPTY"


def test_kj_close_directly_resolves_stale_guest_request(client, db, kj, club):
    """Гость успел подать заявку на закрытие, а KJ в это же время закрыл
    стол прямо с карточки — старая заявка не должна зависнуть в списке
    "Заявки на закрытие стола" как будто ничего не произошло."""
    admin_session = _session(client, club.club_id, table_no=53)
    resp = client.post(
        "/api/guest/table-group/request-close", headers=_headers(admin_session["token"]),
    )
    request_id = resp.get_json()["data"]["id"]

    close_resp = client.put("/api/kj/table-groups/1/53/close", headers=kj["headers"], json={})
    assert close_resp.status_code == 200

    with client.application.app_context():
        stale = _db.session.get(TableCloseRequest, request_id)
        assert stale.status == STATUS_TABLE_CLOSE_REJECTED

    # Список заявок больше не показывает эту (или любую другую) как pending.
    pending_list = client.get("/api/kj/table-close-requests/1", headers=kj["headers"]).get_json()["data"]
    assert all(r["id"] != request_id for r in pending_list)


# --- "Закрыть все столы" (запрос пользователя 2026-09-29: "просто закрывает
# вечер, когда все ушли с караоке") — та же механика закрытия, что и у
# одного стола (close_table_directly), для всех занятых столов клуба сразу,
# но с двумя отличиями, которые здесь и проверяются (уточнения пользователя
# 2026-09-29):
#   - БЕЗ чека — "столы, на которые требуются чеки, я закрываю отдельно
#     [обычной кнопкой одного стола]. Потом отдельной кнопкой я закрываю
#     столы" — эта кнопка чек не показывает никогда;
#   - у КАЖДОГО гостя клуба (не только тех, кто сидел за только что
#     закрытыми столами) сбрасывается стол — "клуб закрывается", гость
#     заново увидит экран выбора стола при следующем визите, но тем же
#     Google-аккаунтом, так что имя/VIP/история не теряются (вариант "1").

def test_close_all_tables_closes_every_occupied_table(client, db, kj, club):
    admin_60 = _session(client, club.club_id, table_no=60)
    admin_61 = _session(client, club.club_id, table_no=61)
    _order(db, club.club_id, 60, int(admin_60["guest_id"]), STATUS_QUEUED, "Ещё не сыграна")
    _order(db, club.club_id, 61, int(admin_61["guest_id"]), STATUS_COMPLETED, "Сыграна")

    resp = client.put("/api/kj/table-groups/1/close-all", headers=kj["headers"], json={})
    assert resp.status_code == 200
    data = resp.get_json()["data"]
    assert set(data["closed_table_nos"]) == {60, 61}

    with client.application.app_context():
        assert TableGroup.query.filter_by(club_id=1, table_no=60).first() is None
        assert TableGroup.query.filter_by(club_id=1, table_no=61).first() is None

    # Без чека — в отличие от закрытия одного стола (test_table_close.py и
    # соседние тесты этого файла), где table_close_receipt приходит гостю.
    me_60 = _me(client, admin_60["token"])
    assert me_60["table_close_receipt"] is None
    me_61 = _me(client, admin_61["token"])
    assert me_61["table_close_receipt"] is None

    # Стол сброшен у обоих — токен всё ещё помнит старый номер, но живая
    # проверка (GuestStatus, см. auth.py::require_guest) главнее токена.
    assert me_60["table_no"] is None
    assert me_61["table_no"] is None


def test_close_all_tables_resets_every_guest_even_without_live_table_group(client, db, kj, club):
    """"Закрыть все столы" = конец вечера для ВСЕХ гостей клуба, а не только
    тех, кто сидел за только что закрытыми столами (решение пользователя
    2026-09-29) — гость, чей стол уже опустел раньше (например, KJ снял его
    со стола карточкой гостя) и у которого сейчас вообще нет TableGroup, всё
    равно должен заново увидеть выбор стола."""
    lone_admin = _session(client, club.club_id, table_no=70)

    with client.application.app_context():
        TableGroup.query.filter_by(club_id=1, table_no=70).delete()
        _db.session.commit()

    resp = client.put("/api/kj/table-groups/1/close-all", headers=kj["headers"], json={})
    assert resp.status_code == 200
    assert resp.get_json()["data"]["closed_table_nos"] == []

    me = _me(client, lone_admin["token"])
    assert me["table_no"] is None


def test_close_all_tables_does_not_touch_other_club(client, db, kj, other_club):
    """Закрытие всех столов клуба kj не должно трогать стол или гостя в
    другом клубе — та же изоляция по club_id, что и everywhere else."""
    other_session = _session(client, other_club.club_id, table_no=62)

    resp = client.put("/api/kj/table-groups/1/close-all", headers=kj["headers"], json={})
    assert resp.status_code == 200
    assert resp.get_json()["data"]["closed_table_nos"] == []

    with client.application.app_context():
        assert TableGroup.query.filter_by(club_id=other_club.club_id, table_no=62).first() is not None

    other_me = _me(client, other_session["token"])
    assert other_me["table_no"] == 62


def test_close_all_tables_with_nothing_occupied_is_ok(client, db, kj, club):
    resp = client.put("/api/kj/table-groups/1/close-all", headers=kj["headers"], json={})
    assert resp.status_code == 200
    assert resp.get_json()["data"]["closed_table_nos"] == []


def test_close_all_tables_forbidden_for_other_club_url(client, db, other_club, kj):
    resp = client.put(f"/api/kj/table-groups/{other_club.club_id}/close-all", headers=kj["headers"], json={})
    assert resp.status_code == 403


# --- Перенос стола ---

def test_move_table_moves_group_members_and_orders(client, db, kj, club):
    admin_session = _session(client, club.club_id, table_no=60)
    guest_session = _session(client, club.club_id, table_no=60)
    join_request_id = client.get(
        "/api/guest/table-group", headers=_headers(admin_session["token"]),
    ).get_json()["data"]["pending_requests"][0]["id"]
    client.post(
        f"/api/guest/table-group/join-requests/{join_request_id}/approve", headers=_headers(admin_session["token"]),
    )
    admin_id = int(admin_session["guest_id"])
    completed = _order(db, club.club_id, 60, admin_id, STATUS_COMPLETED)
    pending_order = _order(db, club.club_id, 60, admin_id, STATUS_QUEUED)

    # Третий гость просится за тот же стол, пока админ ещё не решил его
    # заявку — она должна переехать вместе со столом, а не потеряться.
    late_guest = _session(client, club.club_id, table_no=60)
    assert late_guest["table_group_status"] == "pending"

    resp = client.put("/api/kj/table-groups/1/60/move", headers=kj["headers"], json={"new_table_no": 61})
    assert resp.status_code == 200
    data = resp.get_json()["data"]
    assert data["table_no"] == 61
    assert set(data["member_guest_ids"]) == {admin_session["guest_id"], guest_session["guest_id"]}

    with client.application.app_context():
        group = TableGroup.query.filter_by(club_id=1, table_no=61).first()
        assert group is not None
        assert TableGroup.query.filter_by(club_id=1, table_no=60).first() is None

        member_tables = {
            m.guest_id: m.table_no
            for m in TableGroupMember.query.filter_by(club_id=1).all()
        }
        assert member_tables[admin_id] == 61

        assert Order.query.get(completed.id).table_no == 61
        assert Order.query.get(pending_order.id).table_no == 61

        moved_join_request = TableJoinRequest.query.filter_by(
            club_id=1, guest_id=int(late_guest["guest_id"]), status=STATUS_TABLE_JOIN_PENDING,
        ).first()
        assert moved_join_request is not None
        assert moved_join_request.table_no == 61

        admin_status = GuestStatus.query.filter_by(club_id=1, telegram_user_id=admin_id).first()
        assert admin_status is not None
        assert admin_status.table_no == 61

    # Гость теперь видит себя за новым столом на следующем же опросе — без
    # переиздания токена (см. docstring GuestStatus/auth.py::require_guest).
    me = _me(client, admin_session["token"])
    assert me["table_no"] == 61


def test_move_table_rejects_occupied_destination(client, db, kj, club):
    _session(client, club.club_id, table_no=70)
    _session(client, club.club_id, table_no=71)

    resp = client.put("/api/kj/table-groups/1/70/move", headers=kj["headers"], json={"new_table_no": 71})
    assert resp.status_code == 409
    assert resp.get_json()["error"] == "TABLE_OCCUPIED"

    with client.application.app_context():
        assert TableGroup.query.filter_by(club_id=1, table_no=70).first() is not None


def test_move_table_not_found(client, db, kj, club):
    resp = client.put("/api/kj/table-groups/1/72/move", headers=kj["headers"], json={"new_table_no": 73})
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "TABLE_EMPTY"


def test_move_table_same_number_rejected(client, db, kj, club):
    _session(client, club.club_id, table_no=80)

    resp = client.put("/api/kj/table-groups/1/80/move", headers=kj["headers"], json={"new_table_no": 80})
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "VALIDATION_ERROR"
