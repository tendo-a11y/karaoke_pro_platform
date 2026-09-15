"""
Сервис для Admin App — блок "Управление клубами" (аудит handlers/admin.py:
venue_add_*/venue_show_details/venue_finance_details/venue_edit_name_*/
venue_toggle_*/venue_delete_*/venue_qr_code/venue_contacts_list).

Разграничение доступа (см. auth.py::require_admin): супер-админ видит и
управляет всеми клубами, обычный админ — только своим (admin.club_id).
Это НЕ 1:1 перенос старого бота: там venue-управление было доступно ЛЮБОМУ
пользователю с role==ROLE_ADMIN без проверки club_id вообще (единственная
привязка к конкретному человеку была у /set_admin — только config.ADMIN_ID).
Проверено чтением handlers/admin.py:34-41 и всех venue_* хэндлеров ниже —
ни один не фильтрует по клубу вызывающего админа. Новое разграничение —
осознанное решение при переходе на многоклубную модель управления (см.
docstring AdminUser в models.py, уже написанный до этого шага), принятое
явно при планировании этого блока, а не тихая отсебятина.

Финансовые окна (revenue_today/week/month) — не календарные сутки/неделя/
месяц (как старое utils.get_stats_date() + SQLite DATE('now')), а
скользящие окна "последние N дней от текущего момента" — тот же паттерн,
что уже применён в vip_service.list_transactions и list_my_orders (period
filter), чтобы не тащить сюда старый баг с бакетингом по календарным
суткам в UTC при отображении в локальном времени.
"""
import secrets
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from flask import current_app

from extensions import db
from models import Club, KJOperator, Order, Song, Transaction, TX_TYPE_ORDER_PAYMENT

_EDITABLE_STRING_FIELDS = ("city", "phone", "email")


class ClubServiceError(Exception):
    """Единая ошибка сервиса — маршрут сам решает, как её сериализовать (api_error)."""

    def __init__(self, code: str, message: str, status_code: int = 400):
        self.code = code
        self.message = message
        self.status_code = status_code
        super().__init__(message)


def _revenue_since(club_id: int, since: datetime) -> Decimal:
    """
    "Выручка" клуба = сумма Transaction.type=order_payment за окно — то есть
    реально списанные с гостей деньги за услуги (см. billing_service.py::
    charge_at_completion). Это уже единственный источник денежного движения
    по заказам в новой архитектуре (списание при создании заказа, как было в
    старом боте, здесь не делается — билинг происходит при завершении песни).
    """
    total = (
        db.session.query(db.func.coalesce(db.func.sum(Transaction.amount), 0))
        .filter(
            Transaction.club_id == club_id,
            Transaction.type == TX_TYPE_ORDER_PAYMENT,
            Transaction.created_at >= since,
        )
        .scalar()
    )
    return Decimal(total)


def _resolve_visible_club(admin, club_id: int) -> Club:
    club = db.session.get(Club, club_id)
    if club is None:
        raise ClubServiceError("NOT_FOUND", "Клуб не найден", 404)
    if not admin.is_super_admin and club.club_id != admin.club_id:
        raise ClubServiceError("FORBIDDEN", "Нет доступа к этому клубу", 403)
    return club


def _require_super_admin(admin, action_message: str):
    if not admin.is_super_admin:
        raise ClubServiceError("FORBIDDEN", action_message, 403)


def list_clubs(admin) -> list[dict]:
    if admin.is_super_admin:
        clubs = Club.query.order_by(Club.club_id.asc()).all()
    else:
        clubs = [admin.club] if admin.club else []

    since_today = datetime.now(timezone.utc) - timedelta(days=1)
    result = []
    for club in clubs:
        data = club.to_dict()
        data["revenue_today"] = float(_revenue_since(club.club_id, since_today))
        result.append(data)
    return result


def get_club_detail(admin, club_id: int) -> dict:
    club = _resolve_visible_club(admin, club_id)

    # Код доступа для программы-моста VirtualDJ (см. Club.bridge_token в
    # models.py и backend/vdj/bridge_client.py) — раньше появлялся только
    # через manage.py (нет доступа к консоли Backend в проде) или разовый
    # служебный HTTP-эндпоинт (app.py::bridge_setup, оставлен как есть, но
    # больше не нужен для новых клубов). Теперь create_club() создаёт его
    # сразу; эта проверка — просто подстраховка для клубов, заведённых ещё
    # до этого изменения (например, club_id=1 в самом начале). Запрос
    # пользователя 2026-09-14: чтобы для нового клуба в новом городе не
    # требовалось моё ручное участие — админ должен сразу видеть и сам код,
    # и готовый файл для скачивания (тот же принцип, что и у QR-кода клуба
    # ниже, get_club_qr_link() — готовый артефакт отдаётся прямо из Admin
    # App, без обращения ко мне).
    if not club.bridge_token:
        club.bridge_token = secrets.token_urlsafe(32)
        db.session.commit()

    now = datetime.now(timezone.utc)
    revenue_today = _revenue_since(club.club_id, now - timedelta(days=1))
    revenue_week = _revenue_since(club.club_id, now - timedelta(days=7))
    revenue_month = _revenue_since(club.club_id, now - timedelta(days=30))
    commission = Decimal(str(current_app.config["ADMIN_COMMISSION"]))
    admin_cashback = (revenue_month * commission).quantize(Decimal("0.01"))

    songs_count = Song.query.filter_by(club_id=club.club_id).count()
    kj_operators = [
        {"id": kj.id, "display_name": kj.display_name, "is_active": kj.is_active}
        for kj in KJOperator.query.filter_by(club_id=club.club_id).order_by(KJOperator.id.asc()).all()
    ]

    data = club.to_dict()
    data.update({
        "revenue_today": float(revenue_today),
        "revenue_week": float(revenue_week),
        "revenue_month": float(revenue_month),
        "admin_cashback": float(admin_cashback),
        "songs_count": songs_count,
        "kj_operators": kj_operators,
        # Намеренно НЕ добавлено в Club.to_dict() (используется и в
        # list_clubs() — списке сразу всех клубов админа): секрет должен
        # быть виден только на экране конкретного клуба, куда админ уже
        # авторизован, а не в общем списке.
        "bridge_token": club.bridge_token,
    })
    return data


def _validate_table_count(table_count):
    if table_count is None:
        return None
    if isinstance(table_count, bool) or not isinstance(table_count, int) or table_count < 0:
        raise ClubServiceError("VALIDATION_ERROR", "table_count должен быть неотрицательным целым числом или null")
    return table_count


def _validate_optional_string(value, field_name):
    if value is not None and not isinstance(value, str):
        raise ClubServiceError("VALIDATION_ERROR", f"{field_name} должен быть строкой или null")
    return value


def create_club(admin, *, name, city=None, phone=None, email=None, table_count=None) -> Club:
    """
    Создание клуба — только супер-админ (обычный админ уже привязан к
    своему клубу через provisioning, см. manage.py add-admin, и не создаёт
    новые клубы сам). club_id вычисляется как max(club_id)+1: PK остаётся
    ручным (autoincrement=False), т.к. это поле по-прежнему зарезервировано
    под совпадение со старым venue_id при будущей миграции (Phase 7,
    см. models.py::Club docstring) — только для клубов, ИМПОРТИРУЕМЫХ из
    старой SQLite через manage.py. Клубы, создаваемые из Admin App, новые
    и в старой базе не существуют, поэтому конфликтов с будущим импортом
    не возникает (импортируемые venue_id всегда меньше уже выданных здесь,
    т.к. старых venue в проде — конечное известное число).
    """
    _require_super_admin(admin, "Создавать клубы может только супер-админ")

    if not name or not isinstance(name, str) or not name.strip():
        raise ClubServiceError("VALIDATION_ERROR", "Укажите название клуба")

    city = _validate_optional_string(city, "city")
    phone = _validate_optional_string(phone, "phone")
    email = _validate_optional_string(email, "email")
    table_count = _validate_table_count(table_count)

    next_id = (db.session.query(db.func.max(Club.club_id)).scalar() or 0) + 1
    club = Club(
        club_id=next_id,
        name=name.strip(),
        city=city,
        phone=phone,
        email=email,
        table_count=table_count,
        is_active=True,
        # Запрос пользователя 2026-09-14: код доступа для программы-моста
        # VirtualDJ (см. Club.bridge_token в models.py) создаётся сразу при
        # создании клуба, а не отдельным ручным шагом — при открытии клуба
        # в новом городе админ сразу видит его на экране клуба (см.
        # get_club_detail() ниже) и может скачать готовый файл для KJ, без
        # обращения к разработчику.
        bridge_token=secrets.token_urlsafe(32),
    )
    db.session.add(club)
    db.session.commit()
    return club


def update_club(admin, club_id: int, **fields) -> Club:
    """
    Редактирование клуба. В старом боте venue_edit_name_* правил ТОЛЬКО имя
    (city/phone/email были доступны лишь при создании) — здесь сознательно
    расширяем на все контактные поля и table_count (решение принято при
    согласовании плана блока), доступ: супер-админ — любой клуб, обычный
    админ — только свой.
    """
    club = _resolve_visible_club(admin, club_id)

    if "name" in fields:
        name = fields["name"]
        if not isinstance(name, str) or not name.strip():
            raise ClubServiceError("VALIDATION_ERROR", "Название клуба не может быть пустым")
        club.name = name.strip()

    for field_name in _EDITABLE_STRING_FIELDS:
        if field_name in fields:
            setattr(club, field_name, _validate_optional_string(fields[field_name], field_name))

    if "table_count" in fields:
        club.table_count = _validate_table_count(fields["table_count"])

    db.session.commit()
    return club


def set_club_status(admin, club_id: int, is_active) -> Club:
    """
    Блокировка/разблокировка клуба — 1:1 перенос venue_toggle_block/
    venue_toggle_execute (меняет is_active, ничего больше). Только
    супер-админ: блокировка собственного клуба самим же обычным админом
    была бы саморазрушительной операцией без старого прецедента.
    """
    _require_super_admin(admin, "Блокировать клуб может только супер-админ")
    club = _resolve_visible_club(admin, club_id)

    if not isinstance(is_active, bool):
        raise ClubServiceError("VALIDATION_ERROR", "is_active должен быть true или false")

    club.is_active = is_active
    db.session.commit()
    return club


def delete_club(admin, club_id: int) -> None:
    """
    Guard-delete (решение принято при согласовании плана блока): старый
    venue_delete_execute удалял venue безусловно, даже если у него были
    заказы/финансы (handlers/admin.py:685-690) — здесь отказываемся от
    такого поведения и запрещаем удаление, если у клуба есть хоть один
    Order или Transaction, чтобы не терять историю данных, на которую
    ссылаются внешние ключи. Деактивация клуба — через is_active, не через
    удаление.
    """
    _require_super_admin(admin, "Удалять клуб может только супер-админ")
    club = _resolve_visible_club(admin, club_id)

    has_orders = db.session.query(Order.id).filter_by(club_id=club.club_id).first() is not None
    has_transactions = db.session.query(Transaction.id).filter_by(club_id=club.club_id).first() is not None
    if has_orders or has_transactions:
        raise ClubServiceError(
            "CLUB_HAS_DATA",
            "Нельзя удалить клуб: у него есть заказы или транзакции. Используйте блокировку клуба.",
            409,
        )

    db.session.delete(club)
    db.session.commit()


def get_club_qr_link(admin, club_id: int) -> dict:
    """
    Замена старого venue_qr_code — ОДИН QR на весь клуб, без номера стола
    в ссылке.

    ИСПРАВЛЕНО: раньше здесь генерировался отдельный QR НА КАЖДЫЙ стол (от
    1 до club.table_count), со ссылкой вида ?club_id=..&table_no=.. — это
    была версия ДО принятия финальной единой модели входа (ТЗ п.45). После
    п.45 стол больше никогда не зашивается в саму ссылку/QR: гостевая
    сессия всегда создаётся без стола (routes/guest.py::create_session,
    POST /api/guest/session), а стол гость выбирает сам уже внутри
    приложения, одним действием вместе со входом через Google (routes/
    guest.py::link_google, POST /api/guest/profile/link-google). Эта
    функция была единственным местом в проекте, которое осталось от
    прежнего, уже отменённого варианта (найдено и поправлено по прямому
    указанию пользователя) — table_count клуба тут больше не участвует,
    он остаётся отдельным полем клуба для других целей.
    """
    club = _resolve_visible_club(admin, club_id)
    base_url = current_app.config["GUEST_APP_URL"].rstrip("/")

    return {"club_id": club.club_id, "url": f"{base_url}/?club_id={club.club_id}"}
