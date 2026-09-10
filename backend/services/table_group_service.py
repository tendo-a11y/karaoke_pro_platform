"""
Групповой стол (Role 3/4/5) — утверждённая пользователем спецификация,
вариант А: полноценный шлюз, как в старом боте (нельзя заказывать за
занятым столом без одобрения текущего админа стола). Старое: database.py
table_groups/table_join_requests + bot.py/handlers/client.py обработчики
join/approve/reject/manage/transfer (см. согласованный аудит-отчёт по
Групповому столу перед этим шагом).

Отличия от старого кода — все согласованы отдельно, не мои произвольные
решения:
  - три отдельные таблицы вместо users.table_number (нет постоянного
    аккаунта в новой архитектуре, см. docstring моделей в models.py);
  - создание группы делается атомарно (уникальный индекс + перехват
    IntegrityError) — старая гонка (update_user_table+set_table_admin
    двумя отдельными запросами) не переносится;
  - JWT не переиздаётся при одобрении — авторизация на заказ проверяется
    по актуальному членству в TableGroupMember в момент создания заказа
    (routes/guest.py::create_order), а не по содержимому токена;
  - кик — новая реализация (в старом коде кнопка "Выгнать" на самом деле
    передавала админку, реального кика не было);
  - передача прав админа — отдельное действие, перенос РАБОЧЕЙ старой
    механики set_table_admin (bot.py:1108-1141), только с правильным
    названием, отдельно от кика;
  - самостоятельный выход ("leave") — новая реализация (в старом коде это
    были нерабочие мёртвые строки локализации, ни одного обработчика).
"""
from datetime import datetime, timezone

from sqlalchemy.exc import IntegrityError

from extensions import db
from models import (
    STATUS_TABLE_JOIN_APPROVED,
    STATUS_TABLE_JOIN_PENDING,
    STATUS_TABLE_JOIN_REJECTED,
    TableGroup,
    TableGroupMember,
    TableJoinRequest,
)


def _utcnow():
    return datetime.now(timezone.utc)


def get_group(club_id: int, table_no: int) -> TableGroup | None:
    return TableGroup.query.filter_by(club_id=club_id, table_no=table_no).first()


def get_membership(club_id: int, table_no: int, guest_id: int) -> TableGroupMember | None:
    return TableGroupMember.query.filter_by(club_id=club_id, table_no=table_no, guest_id=guest_id).first()


def has_pending_request(club_id: int, table_no: int, guest_id: int) -> bool:
    return (
        TableJoinRequest.query
        .filter_by(club_id=club_id, table_no=table_no, guest_id=guest_id, status=STATUS_TABLE_JOIN_PENDING)
        .first()
        is not None
    )


def is_member(club_id: int, table_no: int, guest_id: int) -> bool:
    """
    Используется в routes/guest.py::create_order как единственная проверка
    шлюза — 1:1 смысл старого "у пользователя проставлен table_number", но
    без переиздания токена (см. docstring модуля).
    """
    return get_membership(club_id, table_no, guest_id) is not None


class SessionGroupState:
    def __init__(self, status: str, group: TableGroup | None = None, request: TableJoinRequest | None = None):
        self.status = status  # "admin" | "member" | "pending"
        self.group = group
        self.request = request


def ensure_session_group_state(club_id: int, table_no: int, guest_id: int) -> SessionGroupState:
    """
    Вызывается из create_session при наличии стола (table_no is not None).
    Гость без стола (Role 5) сюда не попадает вообще — по утверждённому
    решению групповая механика на них не распространяется.
    """
    membership = get_membership(club_id, table_no, guest_id)
    if membership is not None:
        group = get_group(club_id, table_no)
        status = "admin" if group and group.admin_guest_id == guest_id else "member"
        return SessionGroupState(status=status, group=group)

    group = get_group(club_id, table_no)
    if group is None:
        # Атомарное создание: уникальный индекс (club_id, table_no) на
        # TableGroup защищает от гонки двух гостей, открывших один и тот же
        # пустой стол одновременно (старый баг #6 — здесь не переносится).
        group = TableGroup(club_id=club_id, table_no=table_no, admin_guest_id=guest_id)
        db.session.add(group)
        try:
            db.session.flush()
        except IntegrityError:
            db.session.rollback()
            group = get_group(club_id, table_no)
            # Кто-то создал группу первым между нашей проверкой и вставкой —
            # обрабатываем это как обычное присоединение к уже занятому
            # столу (см. ветку ниже), а не как ошибку.
        else:
            member = TableGroupMember(club_id=club_id, table_no=table_no, guest_id=guest_id)
            db.session.add(member)
            db.session.commit()
            return SessionGroupState(status="admin", group=group)

    # Стол уже занят (группа существует) — если гость сам её админ, но по
    # какой-то причине строка членства потерялась (не должно происходить в
    # штатной работе, но не должно и ронять сессию) — чиним молча.
    if group.admin_guest_id == guest_id:
        db.session.add(TableGroupMember(club_id=club_id, table_no=table_no, guest_id=guest_id))
        db.session.commit()
        return SessionGroupState(status="admin", group=group)

    existing_request = (
        TableJoinRequest.query
        .filter_by(club_id=club_id, table_no=table_no, guest_id=guest_id, status=STATUS_TABLE_JOIN_PENDING)
        .first()
    )
    if existing_request is None:
        # Отклонённая ранее заявка не мешает подать новую — как и в старом
        # коде (has_pending_table_join_request проверяет только 'pending').
        existing_request = TableJoinRequest(club_id=club_id, table_no=table_no, guest_id=guest_id)
        db.session.add(existing_request)
        db.session.commit()

    return SessionGroupState(status="pending", group=group, request=existing_request)


class GroupViewResult:
    def __init__(self, group=None, members=None, pending_requests=None, outcome="ok"):
        self.group = group
        self.members = members or []
        self.pending_requests = pending_requests or []
        self.outcome = outcome  # "ok" | "no_group"


def get_group_view(club_id: int, table_no: int, guest_id: int) -> GroupViewResult:
    group = get_group(club_id, table_no)
    if group is None:
        return GroupViewResult(outcome="no_group")

    members = (
        TableGroupMember.query
        .filter_by(club_id=club_id, table_no=table_no)
        .order_by(TableGroupMember.joined_at.asc())
        .all()
    )
    pending_requests = []
    if group.admin_guest_id == guest_id:
        pending_requests = (
            TableJoinRequest.query
            .filter_by(club_id=club_id, table_no=table_no, status=STATUS_TABLE_JOIN_PENDING)
            .order_by(TableJoinRequest.created_at.asc())
            .all()
        )
    return GroupViewResult(group=group, members=members, pending_requests=pending_requests)


class JoinDecisionResult:
    def __init__(self, request=None, outcome=None):
        self.request = request
        self.outcome = outcome
        # not_found | forbidden | already_decided | table_full | approved | rejected


def approve_join_request(club_id: int, table_no: int, admin_guest_id: int, request_id: int,
                          max_group_size: int) -> JoinDecisionResult:
    request = db.session.get(TableJoinRequest, request_id)
    if request is None or request.club_id != club_id or request.table_no != table_no:
        return JoinDecisionResult(outcome="not_found")

    group = get_group(club_id, table_no)
    if group is None or group.admin_guest_id != admin_guest_id:
        return JoinDecisionResult(outcome="forbidden")

    if request.status != STATUS_TABLE_JOIN_PENDING:
        return JoinDecisionResult(request=request, outcome="already_decided")

    # Повторная проверка лимита в момент одобрения — 1:1 bot.py:1005-1009
    # (стол мог заполниться, пока заявка висела).
    current_count = TableGroupMember.query.filter_by(club_id=club_id, table_no=table_no).count()
    if current_count >= max_group_size:
        request.status = STATUS_TABLE_JOIN_REJECTED
        request.decided_at = _utcnow()
        db.session.commit()
        return JoinDecisionResult(request=request, outcome="table_full")

    request.status = STATUS_TABLE_JOIN_APPROVED
    request.decided_at = _utcnow()
    db.session.add(TableGroupMember(club_id=club_id, table_no=table_no, guest_id=request.guest_id))
    db.session.commit()
    return JoinDecisionResult(request=request, outcome="approved")


def reject_join_request(club_id: int, table_no: int, admin_guest_id: int, request_id: int) -> JoinDecisionResult:
    request = db.session.get(TableJoinRequest, request_id)
    if request is None or request.club_id != club_id or request.table_no != table_no:
        return JoinDecisionResult(outcome="not_found")

    group = get_group(club_id, table_no)
    if group is None or group.admin_guest_id != admin_guest_id:
        return JoinDecisionResult(outcome="forbidden")

    if request.status != STATUS_TABLE_JOIN_PENDING:
        return JoinDecisionResult(request=request, outcome="already_decided")

    request.status = STATUS_TABLE_JOIN_REJECTED
    request.decided_at = _utcnow()
    db.session.commit()
    return JoinDecisionResult(request=request, outcome="rejected")


class MemberActionResult:
    def __init__(self, outcome=None):
        self.outcome = outcome
        # not_found | forbidden | not_a_member | cannot_target_self | ok


def _remove_member_and_reassign(club_id: int, table_no: int, departing_guest_id: int):
    """
    Общая логика ухода участника (сам вышел или его кикнули) — 1:1 ПРАВИЛЬНАЯ
    версия из трёх старых (database.py:394-435, unbind_user_table): если
    уходит админ — новым назначается старейший оставшийся участник по
    joined_at; если участников не осталось — группа и её заявки удаляются.
    Две другие старые версии (баги #4/#5 — зависший или пропавший без
    переназначения админ) сознательно не переносятся.
    """
    member_row = get_membership(club_id, table_no, departing_guest_id)
    if member_row is None:
        return
    db.session.delete(member_row)
    db.session.flush()

    group = get_group(club_id, table_no)
    if group is None or group.admin_guest_id != departing_guest_id:
        db.session.commit()
        return

    oldest_remaining = (
        TableGroupMember.query
        .filter_by(club_id=club_id, table_no=table_no)
        .order_by(TableGroupMember.joined_at.asc())
        .first()
    )
    if oldest_remaining is not None:
        group.admin_guest_id = oldest_remaining.guest_id
    else:
        TableJoinRequest.query.filter_by(club_id=club_id, table_no=table_no).delete()
        db.session.delete(group)
    db.session.commit()


def kick_member(club_id: int, table_no: int, admin_guest_id: int, target_guest_id: int) -> MemberActionResult:
    group = get_group(club_id, table_no)
    if group is None or group.admin_guest_id != admin_guest_id:
        return MemberActionResult(outcome="forbidden")
    if target_guest_id == admin_guest_id:
        # Админ не может кикнуть сам себя — для этого leave (или сначала
        # transfer, если хочет передать права перед уходом).
        return MemberActionResult(outcome="cannot_target_self")
    member_row = get_membership(club_id, table_no, target_guest_id)
    if member_row is None:
        return MemberActionResult(outcome="not_a_member")

    # Кикнутый — никогда не админ (проверено выше), поэтому переназначение
    # админа здесь не требуется — просто убираем строку членства.
    db.session.delete(member_row)
    db.session.commit()
    return MemberActionResult(outcome="ok")


def transfer_admin(club_id: int, table_no: int, admin_guest_id: int, target_guest_id: int) -> MemberActionResult:
    """1:1 перенос РАБОЧЕЙ старой механики set_table_admin (bot.py:1108-1141,
    там ошибочно подписанной как "кик") — отдельное явное действие."""
    group = get_group(club_id, table_no)
    if group is None or group.admin_guest_id != admin_guest_id:
        return MemberActionResult(outcome="forbidden")
    if target_guest_id == admin_guest_id:
        return MemberActionResult(outcome="cannot_target_self")
    if get_membership(club_id, table_no, target_guest_id) is None:
        return MemberActionResult(outcome="not_a_member")

    group.admin_guest_id = target_guest_id
    db.session.commit()
    return MemberActionResult(outcome="ok")


def transfer_identity(club_id: int, table_no: int, old_guest_id: int, new_guest_id: int) -> None:
    """
    Вызывается из routes/guest.py::link_google — единственное место, где
    guest_id одной и той же физической сессии меняется (временная личность
    -> уже существующий постоянный профиль, найденный по Google-аккаунту,
    см. docstring link_google). Без этого шага гость, уже состоявший в
    группе (или
    бывший её админом, или ждавший одобрения) под старым guest_id, потерял
    бы доступ к столу сразу после входа как VIP — это не про правила
    группового стола, а про то, что смена личности не должна выглядеть как
    "новый человек пришёл и должен спросить разрешения заново".

    table_no может быть None (гость без стола) — тогда переносить нечего.
    """
    if table_no is None or old_guest_id == new_guest_id:
        return

    member_row = get_membership(club_id, table_no, old_guest_id)
    if member_row is not None:
        member_row.guest_id = new_guest_id
        group = get_group(club_id, table_no)
        if group is not None and group.admin_guest_id == old_guest_id:
            group.admin_guest_id = new_guest_id
        db.session.commit()
        return

    pending_request = (
        TableJoinRequest.query
        .filter_by(club_id=club_id, table_no=table_no, guest_id=old_guest_id, status=STATUS_TABLE_JOIN_PENDING)
        .first()
    )
    if pending_request is not None:
        pending_request.guest_id = new_guest_id
        db.session.commit()


def leave_group(club_id: int, table_no: int, guest_id: int) -> MemberActionResult:
    if get_membership(club_id, table_no, guest_id) is None:
        return MemberActionResult(outcome="not_a_member")
    _remove_member_and_reassign(club_id, table_no, guest_id)
    return MemberActionResult(outcome="ok")
