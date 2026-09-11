from flask import Blueprint, Response, current_app, g, request

from auth import require_admin
from errors import api_error, api_ok
from services import club_service, kj_admin_service, report_service, system_admin_service
from services.club_service import ClubServiceError
from services.kj_admin_service import KjAdminServiceError
from services.report_service import ReportServiceError
from services.system_admin_service import SystemAdminServiceError

bp = Blueprint("admin", __name__, url_prefix="/api/admin")


def _service_error_response(exc):
    return api_error(exc.status_code, exc.code, exc.message)


@bp.get("/me")
@require_admin
def me():
    """
    Первый эндпоинт Admin App (Phase 3, шаг 1) — по образцу routes/kj.py::me.
    Нужен фронтенду сразу после перехода по ссылке с токеном, чтобы узнать
    свой club_id/роль (супер-админ или обычный) — без этого неоткуда взять
    контекст для остальных запросов. Данные из g.admin (см. require_admin),
    т.е. из БД, а не из токена.
    """
    admin = g.admin
    return api_ok({
        "admin_id": admin.id,
        "display_name": admin.display_name,
        "club_id": admin.club_id,
        "club_name": admin.club.name if admin.club else None,
        "is_super_admin": admin.is_super_admin,
    })


@bp.get("/clubs")
@require_admin
def list_clubs():
    """
    Блок "Управление клубами" (аудит handlers/admin.py::show_venues).
    Супер-админ видит все клубы (с выручкой за сегодня), обычный админ —
    массив из одного своего клуба — см. services/club_service.py docstring
    про разграничение доступа (осознанное отличие от старого бота).
    """
    return api_ok(club_service.list_clubs(g.admin))


@bp.post("/clubs")
@require_admin
def create_club():
    payload = request.get_json(silent=True) or {}
    try:
        club = club_service.create_club(
            g.admin,
            name=payload.get("name"),
            city=payload.get("city"),
            phone=payload.get("phone"),
            email=payload.get("email"),
            table_count=payload.get("table_count"),
        )
    except ClubServiceError as exc:
        return _service_error_response(exc)
    return api_ok(club.to_dict(), status_code=201)


@bp.get("/clubs/<int:club_id>")
@require_admin
def get_club(club_id):
    """
    Детали клуба (аудит venue_show_details + venue_finance_details,
    объединены в один эндпоинт) — выручка today/week/month, admin_cashback,
    число песен в каталоге, список привязанных KJ (read-only — назначение/
    снятие KJ переносится в блок "Управление KJ").
    """
    try:
        data = club_service.get_club_detail(g.admin, club_id)
    except ClubServiceError as exc:
        return _service_error_response(exc)
    return api_ok(data)


@bp.put("/clubs/<int:club_id>")
@require_admin
def update_club(club_id):
    """
    Аудит venue_edit_name_* — в старом боте правилось только имя,
    здесь расширено на все контактные поля и table_count (см.
    club_service.update_club docstring). Присылаются только те поля,
    которые нужно изменить (частичное обновление).
    """
    payload = request.get_json(silent=True) or {}
    fields = {
        key: payload[key]
        for key in ("name", "city", "phone", "email", "table_count")
        if key in payload
    }
    try:
        club = club_service.update_club(g.admin, club_id, **fields)
    except ClubServiceError as exc:
        return _service_error_response(exc)
    return api_ok(club.to_dict())


@bp.put("/clubs/<int:club_id>/status")
@require_admin
def set_club_status(club_id):
    """Аудит venue_toggle_block/venue_toggle_execute — блокировка/разблокировка клуба."""
    payload = request.get_json(silent=True) or {}
    try:
        club = club_service.set_club_status(g.admin, club_id, payload.get("is_active"))
    except ClubServiceError as exc:
        return _service_error_response(exc)
    return api_ok(club.to_dict())


@bp.delete("/clubs/<int:club_id>")
@require_admin
def delete_club(club_id):
    """Аудит venue_delete_execute — здесь guard-delete, см. club_service.delete_club docstring."""
    try:
        club_service.delete_club(g.admin, club_id)
    except ClubServiceError as exc:
        return _service_error_response(exc)
    return api_ok({"deleted": True, "club_id": club_id})


@bp.get("/clubs/<int:club_id>/qr")
@require_admin
def get_club_qr(club_id):
    """Аудит venue_qr_code — один QR на весь клуб, см. club_service.get_club_qr_link docstring (ТЗ п.45)."""
    try:
        data = club_service.get_club_qr_link(g.admin, club_id)
    except ClubServiceError as exc:
        return _service_error_response(exc)
    return api_ok(data)


# --- Управление KJ (Block #2) ---

@bp.get("/kj")
@require_admin
def list_kj():
    """
    Аудит show_kj_list/admin_kj_stats — объединены в один список со
    статистикой (см. kj_admin_service.list_kj docstring про персональную
    статистику через Order.confirmed_by вместо общей выручки клуба).
    """
    return api_ok(kj_admin_service.list_kj(g.admin))


@bp.post("/kj")
@require_admin
def assign_kj():
    """
    Аудит kj_assign_start/venue_assign_kj — здесь без поиска по @username
    (в новой архитектуре нет реестра пользователей бота), telegram_user_id
    вводится напрямую, как в manage.py add-kj. Upsert по telegram_user_id —
    см. kj_admin_service.assign_kj docstring.
    """
    payload = request.get_json(silent=True) or {}
    try:
        kj = kj_admin_service.assign_kj(
            g.admin,
            telegram_user_id=payload.get("telegram_user_id"),
            display_name=payload.get("display_name"),
            club_id=payload.get("club_id"),
        )
    except KjAdminServiceError as exc:
        return _service_error_response(exc)
    return api_ok(kj.to_dict(), status_code=201)


@bp.put("/kj/<int:kj_id>")
@require_admin
def update_kj(kj_id):
    """Редактирование display_name; club_id — только для super_admin (перенос между клубами)."""
    payload = request.get_json(silent=True) or {}
    fields = {key: payload[key] for key in ("display_name", "club_id") if key in payload}
    try:
        kj = kj_admin_service.update_kj(g.admin, kj_id, **fields)
    except KjAdminServiceError as exc:
        return _service_error_response(exc)
    return api_ok(kj.to_dict())


@bp.put("/kj/<int:kj_id>/status")
@require_admin
def set_kj_status(kj_id):
    """
    Аудит kj_remove_execute + kj_toggle_execute — объединены в один
    is_active (решение согласовано при планировании блока, см.
    kj_admin_service.set_kj_status docstring).
    """
    payload = request.get_json(silent=True) or {}
    try:
        kj = kj_admin_service.set_kj_status(g.admin, kj_id, payload.get("is_active"))
    except KjAdminServiceError as exc:
        return _service_error_response(exc)
    return api_ok(kj.to_dict())


# --- Отчёты (Block #3, только super_admin) ---

@bp.get("/reports/overview")
@require_admin
def reports_overview():
    """
    Аудит report_today/report_week/report_month/report_venues/
    report_cashback — объединены в один эндпоинт (см. report_service.py
    docstring про исправленный расчёт процента и про то, что Excel-экспорт
    из старого бота не переносится — CSV собирается на фронтенде).
    """
    try:
        data = report_service.get_overview(g.admin)
    except ReportServiceError as exc:
        return _service_error_response(exc)
    return api_ok(data)


# --- Системные функции (Block #4, только super_admin) ---

@bp.get("/system/overview")
@require_admin
def system_overview():
    """
    Аудит show_system_menu (handlers/admin.py:1131-1149) — счётчики клубов/
    KJ/заказов + размер БД + время сервера. См. system_admin_service.py
    docstring про замену "Всего пользователей" на "Заказов всего" и про
    перенос размера БД сюда из старого system_support.
    """
    try:
        data = system_admin_service.get_overview(g.admin)
    except SystemAdminServiceError as exc:
        return _service_error_response(exc)
    return api_ok(data)


@bp.get("/system/logs")
@require_admin
def system_logs():
    """Аудит system_logs (handlers/admin.py:1180-1206) — последние 20 транзакций, поля 1:1."""
    try:
        data = system_admin_service.get_recent_transactions(g.admin)
    except SystemAdminServiceError as exc:
        return _service_error_response(exc)
    return api_ok(data)


@bp.get("/system/backup")
@require_admin
def system_backup():
    """
    Аудит system_backup (handlers/admin.py:1208-1229) — там copy2 SQLite-
    файла и отправка документом в Telegram; здесь pg_dump (Plain SQL,
    --no-owner --no-privileges), стримится сразу клиенту без временного
    файла на диске (см. system_admin_service.stream_backup docstring).
    """
    try:
        database_uri = current_app.config["SQLALCHEMY_DATABASE_URI"]
        generator, _proc = system_admin_service.stream_backup(g.admin, database_uri)
    except SystemAdminServiceError as exc:
        return _service_error_response(exc)

    filename = system_admin_service.backup_filename()
    return Response(
        generator,
        mimetype="application/sql",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
