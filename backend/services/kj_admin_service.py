"""
Сервис для Admin App — блок "Управление KJ" (аудит handlers/admin.py:
show_kj_list/kj_assign_start/kj_remove_*/admin_kj_stats/kj_contacts/
kj_toggle_block_*). План блока согласован с пользователем перед реализацией:

  - "уволить" (kj_remove_execute) и "заблокировать" (kj_toggle_execute) —
    в старом боте два независимых состояния (role/venue_id сброшены —
    "уволен"; is_blocked=True, venue_id не тронут — "временно отстранён").
    В новой модели KJOperator есть только одно поле is_active — оба
    действия объединяются в него (решение принято явно, не тихая отсебятина);
  - никакого DELETE — в старом боте жёсткого удаления строки никогда не
    было (update_user_role просто менял role, запись в users оставалась);
  - статистика KJ — ПЕРСОНАЛЬНАЯ, через Order.confirmed_by (в старом коде
    это поле не использовалось вообще: admin_kj_stats показывал выручку
    ВСЕГО venue как "статистику KJ", неявно предполагая ровно одного KJ на
    клуб). Здесь по прямому назначению уже существующей колонки: только
    заказы, которые реально подтвердил этот KJ;
  - разграничение доступа — по уже принятому в блоке "Управление клубами"
    принципу: super_admin — все KJ всех клубов, обычный админ — только
    KJ своего клуба; переносить KJ между клубами может только super_admin;
  - POST /api/admin/kj — upsert по telegram_user_id, как уже делает
    manage.py::cmd_add_kj (создать или переназначить+реактивировать).

2026-09, запрос пользователя "доступ KJ Pro определяется Google-аккаунтом
клуба": assign_kj теперь принимает ещё и google_email — один постоянный
служебный Google-аккаунт на клуб (не на конкретного человека), т.к. KJ
физически меняются и переезжают между клубами/городами. Нужен хотя бы один
из двух идентификаторов (telegram_user_id/google_email), можно оба сразу —
тогда один и тот же KJ доступен и по ссылке от бота, и по клубной почте.
Сама привязка google_sub (кто именно вошёл) заполняется не здесь, а при
первом успешном входе через Google (см. routes/kj.py::kj_google_login) —
здесь администратор лишь заранее объявляет, какая почта имеет право войти.
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from extensions import db
from models import Club, KJOperator, Order, STATUS_COMPLETED, Transaction, TX_TYPE_ORDER_PAYMENT


class KjAdminServiceError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 400):
        self.code = code
        self.message = message
        self.status_code = status_code
        super().__init__(message)


def _stats_since(kj_id: int, since: datetime) -> dict:
    """
    Персональная статистика KJ (не клуба целиком, см. docstring модуля):
    число завершённых заказов и сумма реально списанных с гостей денег
    (Transaction.type=order_payment) по заказам, подтверждённым ИМЕННО
    этим KJ (Order.confirmed_by), за окно.
    """
    orders_completed = (
        Order.query.filter(
            Order.confirmed_by == kj_id,
            Order.status == STATUS_COMPLETED,
            Order.completed_at >= since,
        ).count()
    )
    revenue = (
        db.session.query(db.func.coalesce(db.func.sum(Transaction.amount), 0))
        .join(Order, Transaction.order_id == Order.id)
        .filter(
            Order.confirmed_by == kj_id,
            Transaction.type == TX_TYPE_ORDER_PAYMENT,
            Transaction.created_at >= since,
        )
        .scalar()
    )
    return {"orders_completed_today": orders_completed, "revenue_today": float(Decimal(revenue))}


def _visible_kj_query(admin):
    if admin.is_super_admin:
        return KJOperator.query
    return KJOperator.query.filter_by(club_id=admin.club_id)


def _resolve_visible_kj(admin, kj_id: int) -> KJOperator:
    kj = db.session.get(KJOperator, kj_id)
    if kj is None:
        raise KjAdminServiceError("NOT_FOUND", "KJ не найден", 404)
    if not admin.is_super_admin and kj.club_id != admin.club_id:
        raise KjAdminServiceError("FORBIDDEN", "Нет доступа к этому KJ", 403)
    return kj


def list_kj(admin) -> list[dict]:
    kj_list = _visible_kj_query(admin).order_by(KJOperator.id.asc()).all()
    since_today = datetime.now(timezone.utc) - timedelta(days=1)
    result = []
    for kj in kj_list:
        data = kj.to_dict()
        data["club_name"] = kj.club.name if kj.club else None
        data.update(_stats_since(kj.id, since_today))
        result.append(data)
    return result


def _validate_telegram_user_id(value):
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise KjAdminServiceError("VALIDATION_ERROR", "telegram_user_id должен быть положительным целым числом")
    return value


def _validate_google_email(value):
    if not isinstance(value, str) or not value.strip():
        raise KjAdminServiceError("VALIDATION_ERROR", "google_email должен быть непустой строкой")
    return value.strip().lower()


def assign_kj(admin, *, telegram_user_id=None, google_email=None, display_name, club_id=None) -> KJOperator:
    """
    Upsert по telegram_user_id и/или по google_email (см. докстринг модуля) —
    аналог manage.py::cmd_add_kj, расширенный под клубный Google-аккаунт.
    Нужен хотя бы один идентификатор. Для обычного админа club_id
    принудительно = его собственный клуб (поле в форме фронтенда не
    показывается вообще, но и на бэкенде перепроверяем — ТЗ п.24, фронтенду
    не доверяем). Если найденный KJ уже привязан к ДРУГОМУ клубу — обычному
    админу переносить его нельзя, только super_admin.
    """
    if telegram_user_id is None and not google_email:
        raise KjAdminServiceError("VALIDATION_ERROR", "Укажите telegram_user_id и/или google_email")

    if telegram_user_id is not None:
        telegram_user_id = _validate_telegram_user_id(telegram_user_id)
    if google_email:
        google_email = _validate_google_email(google_email)

    if not display_name or not isinstance(display_name, str) or not display_name.strip():
        raise KjAdminServiceError("VALIDATION_ERROR", "Укажите имя KJ")
    display_name = display_name.strip()

    if admin.is_super_admin:
        if club_id is None:
            raise KjAdminServiceError("VALIDATION_ERROR", "Укажите club_id")
        if isinstance(club_id, bool) or not isinstance(club_id, int):
            raise KjAdminServiceError("VALIDATION_ERROR", "club_id должен быть числом")
        target_club_id = club_id
    else:
        if club_id is not None and club_id != admin.club_id:
            raise KjAdminServiceError("FORBIDDEN", "Можно назначать KJ только в свой клуб", 403)
        target_club_id = admin.club_id

    club = db.session.get(Club, target_club_id)
    if club is None:
        raise KjAdminServiceError("NOT_FOUND", "Клуб не найден", 404)

    # Ищем существующую запись сначала по telegram_user_id, потом по
    # google_email — так к уже привязанному по одному способу KJ можно тем
    # же вызовом довесить второй, не создавая дубликат строки.
    kj = None
    if telegram_user_id is not None:
        kj = KJOperator.query.filter_by(telegram_user_id=telegram_user_id).first()
    if kj is None and google_email:
        kj = KJOperator.query.filter_by(google_email=google_email).first()

    if kj is not None and not admin.is_super_admin and kj.club_id != admin.club_id:
        raise KjAdminServiceError(
            "FORBIDDEN", "Этот KJ уже привязан к другому клубу — перенести может только супер-админ", 403,
        )

    if google_email:
        conflict = KJOperator.query.filter(
            KJOperator.google_email == google_email,
            KJOperator.id != (kj.id if kj is not None else None),
        ).first()
        if conflict is not None:
            raise KjAdminServiceError("VALIDATION_ERROR", "Эта почта уже привязана к другому KJ")

    if kj is None:
        kj = KJOperator(telegram_user_id=telegram_user_id, google_email=google_email, club_id=target_club_id,
                         display_name=display_name, is_active=True)
        db.session.add(kj)
    else:
        if telegram_user_id is not None:
            kj.telegram_user_id = telegram_user_id
        if google_email:
            # Смена почты на другую сбрасывает уже привязанный google_sub —
            # прежний вход больше не должен работать под новой почтой без
            # повторного явного входа (см. докстринг update_kj про тот же принцип).
            if google_email != (kj.google_email or ""):
                kj.google_sub = None
            kj.google_email = google_email
        kj.club_id = target_club_id
        kj.display_name = display_name
        kj.is_active = True

    db.session.commit()
    return kj


def update_kj(admin, kj_id: int, **fields) -> KJOperator:
    kj = _resolve_visible_kj(admin, kj_id)

    if "display_name" in fields:
        display_name = fields["display_name"]
        if not isinstance(display_name, str) or not display_name.strip():
            raise KjAdminServiceError("VALIDATION_ERROR", "Имя KJ не может быть пустым")
        kj.display_name = display_name.strip()

    if "google_email" in fields:
        raw = fields["google_email"]
        if raw is None or (isinstance(raw, str) and not raw.strip()):
            # Явная отвязка клубного Google-аккаунта (например, он
            # скомпрометирован) — вместе с почтой сбрасываем и google_sub,
            # иначе прежний вход продолжил бы работать без всякой почты.
            kj.google_email = None
            kj.google_sub = None
        else:
            if not isinstance(raw, str):
                raise KjAdminServiceError("VALIDATION_ERROR", "google_email должен быть строкой")
            new_email = raw.strip().lower()
            conflict = KJOperator.query.filter(
                KJOperator.google_email == new_email, KJOperator.id != kj.id,
            ).first()
            if conflict is not None:
                raise KjAdminServiceError("VALIDATION_ERROR", "Эта почта уже привязана к другому KJ")
            if new_email != (kj.google_email or ""):
                kj.google_sub = None
            kj.google_email = new_email

    if "club_id" in fields:
        if not admin.is_super_admin:
            raise KjAdminServiceError("FORBIDDEN", "Переносить KJ между клубами может только супер-админ", 403)
        club_id = fields["club_id"]
        if isinstance(club_id, bool) or not isinstance(club_id, int):
            raise KjAdminServiceError("VALIDATION_ERROR", "club_id должен быть числом")
        club = db.session.get(Club, club_id)
        if club is None:
            raise KjAdminServiceError("NOT_FOUND", "Клуб не найден", 404)
        kj.club_id = club_id

    db.session.commit()
    return kj


def set_kj_status(admin, kj_id: int, is_active) -> KJOperator:
    """Объединяет старые kj_remove_execute и kj_toggle_execute в одно действие (см. docstring модуля)."""
    kj = _resolve_visible_kj(admin, kj_id)
    if not isinstance(is_active, bool):
        raise KjAdminServiceError("VALIDATION_ERROR", "is_active должен быть true или false")
    kj.is_active = is_active
    db.session.commit()
    return kj
