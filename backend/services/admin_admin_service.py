"""
Сервис для Admin App — блок "Управление администраторами" (запрос
пользователя 2026-09, сразу после "нормальный вход через Google в
админку": до этого единственный способ вписать google_email
администратору был manage.py set-admin-google-email по SSH — этот блок
как раз убирает необходимость в SSH для ЛЮБОГО следующего администратора,
не только для уже забутстрапленного первого супер-админа). Точная копия
kj_admin_service.py, адаптированная под admin_users — см. её докстринг
про upsert по telegram_user_id/google_email.

Доступ — только super_admin, в отличие от "Управление KJ" (там обычный
админ управляет KJ своего клуба). Управление другими администраторами —
это не то же самое, что управление своим клубом: как и "Отчёты"/"Система"
(Block #3/#4), это общесистемная функция.

В отличие от KJ, у администратора есть is_super_admin — это право
присваивает/снимает тоже только super_admin (соответствует единственному
config.ADMIN_ID старой системы, см. docstring AdminUser в models.py).

Две защиты от случайной потери доступа ко всей системе (некому будет
чинить через SSH, как только что чинили в этот раз):
  - нельзя заблокировать (is_active=False) самого себя;
  - нельзя снять права супер-админа (ни с себя, ни с кого-либо ещё), если
    после этого не останется ни одного активного супер-админа.
"""
from extensions import db
from models import AdminUser, Club


class AdminAdminServiceError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 400):
        self.code = code
        self.message = message
        self.status_code = status_code
        super().__init__(message)


def _require_super_admin(admin):
    if not admin.is_super_admin:
        raise AdminAdminServiceError(
            "FORBIDDEN", "Управление администраторами доступно только супер-админу", 403,
        )


def list_admins(admin) -> list[dict]:
    _require_super_admin(admin)
    admins = AdminUser.query.order_by(AdminUser.id.asc()).all()
    result = []
    for a in admins:
        data = a.to_dict()
        data["club_name"] = a.club.name if a.club else None
        result.append(data)
    return result


def _validate_telegram_user_id(value):
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise AdminAdminServiceError("VALIDATION_ERROR", "telegram_user_id должен быть положительным целым числом")
    return value


def _validate_google_email(value):
    if not isinstance(value, str) or not value.strip():
        raise AdminAdminServiceError("VALIDATION_ERROR", "google_email должен быть непустой строкой")
    return value.strip().lower()


def _ensure_not_last_super_admin(excluding: AdminUser):
    remaining = AdminUser.query.filter(
        AdminUser.is_super_admin.is_(True),
        AdminUser.is_active.is_(True),
        AdminUser.id != excluding.id,
    ).count()
    if remaining == 0:
        raise AdminAdminServiceError(
            "LAST_SUPER_ADMIN",
            "Нельзя снять права супер-админа — это единственный активный супер-админ в системе",
        )


def assign_admin(admin, *, telegram_user_id=None, google_email=None, display_name, club_id,
                  is_super_admin=False) -> AdminUser:
    """
    Upsert по telegram_user_id и/или google_email — аналог manage.py::
    cmd_add_admin/cmd_set_admin_google_email, объединённых в один вызов
    (см. kj_admin_service.assign_kj docstring). club_id обязателен всегда,
    даже для будущего супер-админа — см. docstring AdminUser.club_id в
    models.py (супер-админ тоже привязан к "домашнему" клубу схемой, хоть
    областью действия и не ограничен).
    """
    _require_super_admin(admin)

    if telegram_user_id is None and not google_email:
        raise AdminAdminServiceError("VALIDATION_ERROR", "Укажите telegram_user_id и/или google_email")

    if telegram_user_id is not None:
        telegram_user_id = _validate_telegram_user_id(telegram_user_id)
    if google_email:
        google_email = _validate_google_email(google_email)

    if not display_name or not isinstance(display_name, str) or not display_name.strip():
        raise AdminAdminServiceError("VALIDATION_ERROR", "Укажите имя администратора")
    display_name = display_name.strip()

    if club_id is None or isinstance(club_id, bool) or not isinstance(club_id, int):
        raise AdminAdminServiceError("VALIDATION_ERROR", "Укажите club_id")
    club = db.session.get(Club, club_id)
    if club is None:
        raise AdminAdminServiceError("NOT_FOUND", "Клуб не найден", 404)

    if not isinstance(is_super_admin, bool):
        raise AdminAdminServiceError("VALIDATION_ERROR", "is_super_admin должен быть true или false")

    target = None
    if telegram_user_id is not None:
        target = AdminUser.query.filter_by(telegram_user_id=telegram_user_id).first()
    if target is None and google_email:
        target = AdminUser.query.filter_by(google_email=google_email).first()

    if google_email:
        conflict = AdminUser.query.filter(
            AdminUser.google_email == google_email,
            AdminUser.id != (target.id if target is not None else None),
        ).first()
        if conflict is not None:
            raise AdminAdminServiceError("VALIDATION_ERROR", "Эта почта уже привязана к другому администратору")

    if target is not None and target.is_super_admin and not is_super_admin:
        _ensure_not_last_super_admin(target)

    if target is None:
        target = AdminUser(
            telegram_user_id=telegram_user_id, google_email=google_email, club_id=club_id,
            display_name=display_name, is_super_admin=is_super_admin, is_active=True,
        )
        db.session.add(target)
    else:
        if telegram_user_id is not None:
            target.telegram_user_id = telegram_user_id
        if google_email:
            # Смена почты на другую сбрасывает уже привязанный google_sub —
            # прежний вход больше не должен работать под новой почтой без
            # повторного явного входа (тот же приём, что и в kj_admin_service).
            if google_email != (target.google_email or ""):
                target.google_sub = None
            target.google_email = google_email
        target.club_id = club_id
        target.display_name = display_name
        target.is_super_admin = is_super_admin
        target.is_active = True

    db.session.commit()
    return target


def update_admin(admin, admin_id: int, **fields) -> AdminUser:
    _require_super_admin(admin)
    target = db.session.get(AdminUser, admin_id)
    if target is None:
        raise AdminAdminServiceError("NOT_FOUND", "Администратор не найден", 404)

    if "display_name" in fields:
        display_name = fields["display_name"]
        if not isinstance(display_name, str) or not display_name.strip():
            raise AdminAdminServiceError("VALIDATION_ERROR", "Имя администратора не может быть пустым")
        target.display_name = display_name.strip()

    if "google_email" in fields:
        raw = fields["google_email"]
        if raw is None or (isinstance(raw, str) and not raw.strip()):
            # Явная отвязка Google-аккаунта — вместе с почтой сбрасываем и
            # google_sub, иначе прежний вход продолжил бы работать без почты.
            target.google_email = None
            target.google_sub = None
        else:
            if not isinstance(raw, str):
                raise AdminAdminServiceError("VALIDATION_ERROR", "google_email должен быть строкой")
            new_email = raw.strip().lower()
            conflict = AdminUser.query.filter(
                AdminUser.google_email == new_email, AdminUser.id != target.id,
            ).first()
            if conflict is not None:
                raise AdminAdminServiceError("VALIDATION_ERROR", "Эта почта уже привязана к другому администратору")
            if new_email != (target.google_email or ""):
                target.google_sub = None
            target.google_email = new_email

    if "club_id" in fields:
        club_id = fields["club_id"]
        if isinstance(club_id, bool) or not isinstance(club_id, int):
            raise AdminAdminServiceError("VALIDATION_ERROR", "club_id должен быть числом")
        club = db.session.get(Club, club_id)
        if club is None:
            raise AdminAdminServiceError("NOT_FOUND", "Клуб не найден", 404)
        target.club_id = club_id

    if "is_super_admin" in fields:
        new_value = fields["is_super_admin"]
        if not isinstance(new_value, bool):
            raise AdminAdminServiceError("VALIDATION_ERROR", "is_super_admin должен быть true или false")
        if target.is_super_admin and not new_value:
            _ensure_not_last_super_admin(target)
        target.is_super_admin = new_value

    db.session.commit()
    return target


def set_admin_status(admin, admin_id: int, is_active) -> AdminUser:
    _require_super_admin(admin)
    target = db.session.get(AdminUser, admin_id)
    if target is None:
        raise AdminAdminServiceError("NOT_FOUND", "Администратор не найден", 404)
    if not isinstance(is_active, bool):
        raise AdminAdminServiceError("VALIDATION_ERROR", "is_active должен быть true или false")

    if not is_active:
        if target.id == admin.id:
            raise AdminAdminServiceError("FORBIDDEN", "Нельзя заблокировать самого себя", 400)
        if target.is_super_admin:
            _ensure_not_last_super_admin(target)

    target.is_active = is_active
    db.session.commit()
    return target
