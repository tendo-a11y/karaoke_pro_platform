from datetime import datetime, timezone

from extensions import db

# --- Статусы заказа (ТЗ п.10) ---
STATUS_PENDING = "pending"
STATUS_PROCESSING = "processing"
STATUS_QUEUED = "queued"
STATUS_PLAYING = "playing"
STATUS_COMPLETED = "completed"
STATUS_REJECTED = "rejected"
STATUS_ERROR = "error"

ALL_STATUSES = (
    STATUS_PENDING,
    STATUS_PROCESSING,
    STATUS_QUEUED,
    STATUS_PLAYING,
    STATUS_COMPLETED,
    STATUS_REJECTED,
    STATUS_ERROR,
)


def utcnow():
    return datetime.now(timezone.utc)


class Club(db.Model):
    """
    Клуб. club_id намеренно совпадает с venue_id существующей SQLite базы
    karaoke_pro — так новый Backend может ссылаться на тот же клуб без
    отдельной синхронизации на первом этапе (ТЗ п.8, п.25).
    """

    __tablename__ = "clubs"

    club_id = db.Column(db.Integer, primary_key=True, autoincrement=False)
    name = db.Column(db.String(255), nullable=False)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)

    # 1:1 перенос venues.chat_enabled из старой SQLite БД — чат гость↔KJ
    # (ТЗ §20, §49) включается/выключается на уровне клуба, как и раньше.
    chat_enabled = db.Column(db.Boolean, nullable=False, default=False)

    # Перенос полей старой Venue (handlers/admin.py: venue_add_*/venue_show_details/
    # venue_contacts_list) — контактные данные клуба и число столов. В старой
    # SQLite были NOT NULL (заполнялись при создании venue пошаговой формой),
    # здесь — nullable, т.к. уже существующие клубы (созданы через CLI
    # manage.py add-club ещё до Admin App) этих данных не имеют, а бэкфилл
    # не входит в задачу блока "Управление клубами" (аудит Admin App, Block #1).
    city = db.Column(db.String(255), nullable=True)
    phone = db.Column(db.String(64), nullable=True)
    email = db.Column(db.String(255), nullable=True)

    # Кол-во столов клуба — в старой Venue было table_count, читалось только
    # для подписи к QR ("QR для N столов"), диапазон table_no нигде не
    # проверялся (см. комментарий в routes/guest.py::create_session). Здесь
    # то же самое: table_count используется ТОЛЬКО для генерации QR-кодов
    # по столам (Admin App), а не как ограничение на create_session — это
    # сознательно не переносимое сейчас поведение, см. план блока.
    table_count = db.Column(db.Integer, nullable=True)

    # Секрет для локального VDJ-моста (см. vdj/bridge_client.py). Backend
    # централизован (обычно в облаке), а VirtualDJ стоит локально на
    # компьютере KJ без доступа из интернета — мостик сам подключается
    # НАРУЖУ к Backend с этим токеном, поэтому не нужен проброс портов на
    # роутере клуба. Токен — не JWT, а простой статический секрет для
    # доверенного процесса (не для людей), генерируется через manage.py.
    bridge_token = db.Column(db.String(64), nullable=True, unique=True)

    kj_operators = db.relationship("KJOperator", back_populates="club")
    admin_users = db.relationship("AdminUser", back_populates="club")
    orders = db.relationship("Order", back_populates="club")
    transactions = db.relationship("Transaction", back_populates="club")

    def to_dict(self):
        return {
            "club_id": self.club_id,
            "name": self.name,
            "is_active": self.is_active,
            "chat_enabled": self.chat_enabled,
            "city": self.city,
            "phone": self.phone,
            "email": self.email,
            "table_count": self.table_count,
        }


class KJOperator(db.Model):
    """
    KJ, которому разрешён доступ к KJ Panel. Привязка telegram_user_id -> club_id
    — источник истины для авторизации (ТЗ п.24): Backend никогда не доверяет
    club_id, присланному от React, а всегда берёт его отсюда по идентификатору
    из подписанного токена.
    """

    __tablename__ = "kj_operators"

    id = db.Column(db.Integer, primary_key=True)
    telegram_user_id = db.Column(db.BigInteger, unique=True, nullable=False, index=True)
    club_id = db.Column(db.Integer, db.ForeignKey("clubs.club_id"), nullable=False)
    display_name = db.Column(db.String(255))
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)

    club = db.relationship("Club", back_populates="kj_operators")

    def to_dict(self):
        return {
            "id": self.id,
            "telegram_user_id": self.telegram_user_id,
            "club_id": self.club_id,
            "display_name": self.display_name,
            "is_active": self.is_active,
        }


class AdminUser(db.Model):
    """
    Администратор клуба — новый Backend-эквивалент роли 1 (config.ROLE_ADMIN)
    из исходного бота. Там роль хранилась как users.role, привязка к клубу —
    users.venue_id (см. handlers/admin.py, bot.py:331-332). Здесь — отдельная
    таблица по образцу KJOperator: club_id — источник истины для авторизации,
    Backend никогда не доверяет club_id, присланному от Admin App (ТЗ п.24).

    is_super_admin соответствует единственному config.ADMIN_ID из исходной
    системы — это был не признак в БД, а жёстко заданный в переменных
    окружения Telegram ID с расширенными правами (например, только он мог
    назначать других администраторов — handlers/admin.py, гейт
    `from_user.id == config.ADMIN_ID`). Обычный администратор
    (is_super_admin=False) администрирует только свой клуб; супер-админ —
    не привязан областью действия к club_id (конкретные привилегии
    супер-админа реализуются по мере появления соответствующих эндпоинтов,
    здесь только сам признак).
    """

    __tablename__ = "admin_users"

    id = db.Column(db.Integer, primary_key=True)
    telegram_user_id = db.Column(db.BigInteger, unique=True, nullable=False, index=True)
    club_id = db.Column(db.Integer, db.ForeignKey("clubs.club_id"), nullable=False)
    display_name = db.Column(db.String(255))
    is_super_admin = db.Column(db.Boolean, nullable=False, default=False)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)

    club = db.relationship("Club", back_populates="admin_users")

    def to_dict(self):
        return {
            "id": self.id,
            "telegram_user_id": self.telegram_user_id,
            "club_id": self.club_id,
            "display_name": self.display_name,
            "is_super_admin": self.is_super_admin,
            "is_active": self.is_active,
        }


class Order(db.Model):
    """
    Заказ песни в новом централизованном процессе (ТЗ п.31-32).
    Существует параллельно с таблицей orders в существующей SQLite БД —
    удаление/замена старой таблицы не производится (ТЗ п.8).
    """

    __tablename__ = "orders"

    id = db.Column(db.Integer, primary_key=True)

    # ВНИМАНИЕ: имя поля унаследовано от Telegram-этапа проекта. С Phase 4
    # (Guest App, routes/guest.py) сюда пишутся ДВА разных вида значений:
    # настоящий Telegram user_id (путь старого бота, /api/client/order) и
    # случайный guest_id анонимной веб-сессии (/api/guest/*, см.
    # routes/guest.py::_new_guest_id) — оба одинаково уникальны и
    # используются везде только как непрозрачный "чей это заказ", так что
    # делить колонку безопасно. Само переименование в guest_id и решение
    # по VIP-идентификации в Guest App (нужна персистентная кросс-девайсная
    # личность, не просто случайная сессия) — открытый вопрос, ТЗ §54,
    # сознательно не решается в этом шаге (см. отчёт по Phase 4, шаг 1).
    telegram_user_id = db.Column(db.BigInteger, nullable=False, index=True)
    club_id = db.Column(db.Integer, db.ForeignKey("clubs.club_id"), nullable=False, index=True)
    table_no = db.Column(db.Integer, nullable=True)  # null = клиент без стола (ТЗ п.27)
    guest_type = db.Column(db.String(20), nullable=True)  # роль гостя на момент заказа: vip/client/no_table (новое ТЗ §10)

    song_title = db.Column(db.String(500), nullable=False)
    artist = db.Column(db.String(500), nullable=True)
    key = db.Column(db.SmallInteger, nullable=False, default=0)     # -2..+2, новое ТЗ §10
    tempo = db.Column(db.SmallInteger, nullable=False, default=0)   # -2..+2, новое ТЗ §10

    # Какая услуга/тариф выбрана при заказе (старая таблица services, 1:1
    # перенос — см. PHASE1_AUDIT_NOVAYA_ARKHITEKTURA.md). Нужна на completion,
    # чтобы знать актуальную цену для charge-at-completion (ТЗ §12) —
    # намеренно nullable=True на этом шаге: ни один HTTP-эндпоинт заказа пока
    # не принимает service_id (Guest App с выбором тарифа ещё не сделан),
    # колонка добавлена как подготовка данных, не как готовая интеграция.
    service_id = db.Column(db.Integer, db.ForeignKey("services.id"), nullable=True)

    status = db.Column(db.String(20), nullable=False, default=STATUS_PENDING, index=True)

    # Откуда взялся заказ — НЕ показывается в UI ни одного из приложений
    # (новое ТЗ §22, §35), нужно только для reconciliation и внутренней
    # диагностики (§34, §36).
    source = db.Column(db.String(20), nullable=False, default="guest")  # guest | manual | virtualdj

    # Через какой канал гость сделал заказ — telegram (настоящий Telegram-бот,
    # /api/client/order) | webapp (Guest App, /api/guest/order). Не путать с
    # source выше (это про "кто нажал" — гость/KJ вручную/сама VirtualDJ, а
    # channel — про "через какой интерфейс"). Нужен, чтобы отличать заказы, у
    # которых telegram_user_id — настоящий Telegram chat_id, от заказов, где
    # это поле хранит случайный guest_id анонимной веб-сессии (см. комментарий
    # у telegram_user_id выше, ТЗ §54) — иначе уведомление гостю через
    # Telegram Bot API молча уходит в никуда для веб-гостей. Раньше такого
    # различия не было вообще, оба пути было невозможно отличить друг от
    # друга по данным заказа.
    channel = db.Column(db.String(20), nullable=False, default="telegram")  # telegram | webapp

    vdj_item_id = db.Column(db.String(255), nullable=True)
    vdj_filepath = db.Column(db.Text, nullable=True)  # результат get_browsed_filepath — нужен для сопоставления с VirtualDJ History (новое ТЗ §37)
    error_message = db.Column(db.Text, nullable=True)
    confirmed_by = db.Column(db.Integer, db.ForeignKey("kj_operators.id"), nullable=True)

    # automatic (по VirtualDJ History) | manual (KJ нажал вручную, fallback) — новое ТЗ §14
    completion_source = db.Column(db.String(20), nullable=True)

    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    confirmed_at = db.Column(db.DateTime(timezone=True), nullable=True)
    queued_at = db.Column(db.DateTime(timezone=True), nullable=True)
    playing_at = db.Column(db.DateTime(timezone=True), nullable=True)
    completed_at = db.Column(db.DateTime(timezone=True), nullable=True)
    rejected_at = db.Column(db.DateTime(timezone=True), nullable=True)

    club = db.relationship("Club", back_populates="orders")
    transactions = db.relationship("Transaction", back_populates="order")
    service = db.relationship("Service")

    __table_args__ = (
        db.Index("ix_orders_club_status", "club_id", "status"),
    )

    def to_dict(self):
        return {
            "id": self.id,
            "telegram_user_id": self.telegram_user_id,
            "club_id": self.club_id,
            "table_no": self.table_no,
            "guest_type": self.guest_type,
            "song_title": self.song_title,
            "artist": self.artist,
            "key": self.key,
            "tempo": self.tempo,
            "service_id": self.service_id,
            "status": self.status,
            "source": self.source,
            "channel": self.channel,
            "vdj_item_id": self.vdj_item_id,
            "vdj_filepath": self.vdj_filepath,
            "error_message": self.error_message,
            "completion_source": self.completion_source,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "confirmed_at": self.confirmed_at.isoformat() if self.confirmed_at else None,
            "queued_at": self.queued_at.isoformat() if self.queued_at else None,
            "playing_at": self.playing_at.isoformat() if self.playing_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "rejected_at": self.rejected_at.isoformat() if self.rejected_at else None,
        }


class Service(db.Model):
    """
    Услуга/тариф, который гость выбирает при заказе (обычная песня,
    приоритет и т.п. — конкретный набор зависит от клуба). 1:1 перенос
    таблицы services из старой SQLite БД (venue_id -> club_id, остальные
    поля без изменений) — см. PHASE1_AUDIT_NOVAYA_ARKHITEKTURA.md.

    Пока не подключена ни к одному HTTP-эндпоинту (нет CRUD-роутов, Order.
    service_id nullable) — это подготовка данных под charge-at-completion
    (services/billing_service.py), а не готовая интеграция с Guest App.
    """

    __tablename__ = "services"

    id = db.Column(db.Integer, primary_key=True)
    club_id = db.Column(db.Integer, db.ForeignKey("clubs.club_id"), nullable=False, index=True)
    name = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text, nullable=True)
    price = db.Column(db.Numeric(10, 2), nullable=False, default=0)
    is_free = db.Column(db.Boolean, nullable=False, default=False)

    club = db.relationship("Club")

    def to_dict(self):
        return {
            "id": self.id,
            "club_id": self.club_id,
            "name": self.name,
            "description": self.description,
            "price": float(self.price) if self.price is not None else None,
            "is_free": self.is_free,
        }


class Song(db.Model):
    """
    Каталог песен клуба — 1:1 перенос таблицы songs из старой SQLite БД
    (venue_id -> club_id, поля без изменений). Наполняется ТОЛЬКО через CSV,
    загружаемый KJ/Admin (см. services/song_service.py::parse_csv_songs) —
    как и в старом коде, синхронизации с библиотекой VirtualDJ нет и не
    предполагается (аудит Role 3/4/5, п.1: старая система тоже не читала
    каталог из VDJ, только из ручного CSV).
    """

    __tablename__ = "songs"

    id = db.Column(db.Integer, primary_key=True)
    club_id = db.Column(db.Integer, db.ForeignKey("clubs.club_id"), nullable=False, index=True)
    artist = db.Column(db.String(255), nullable=False, default="")
    title = db.Column(db.String(255), nullable=False)
    code = db.Column(db.String(64), nullable=True)

    club = db.relationship("Club")

    def to_dict(self):
        return {
            "id": self.id,
            "club_id": self.club_id,
            "artist": self.artist,
            "title": self.title,
            "code": self.code,
        }


class GuestAccount(db.Model):
    """
    Постоянный профиль гостя Guest App (ТЗ п.45, аудит "Постоянная
    идентификация гостя"). До этого шага у Guest App не было ничего
    постоянного для обычного (не-VIP) гостя — guest_id (см. комментарий у
    Order.telegram_user_id) был случайным номером сессии, живущим только в
    localStorage одного браузера максимум GUEST_JWT_TTL_SECONDS. Утверждённое
    решение: постоянная личность появляется, когда гость добровольно
    привязывает Google-аккаунт — см. routes/guest.py::link_google.

    Здесь НЕ создаётся новый guest_id — telegram_user_id этой записи ВСЕГДА
    равен guest_id той сессии, в которой произошла привязка (если для этого
    google_sub ещё нет записи в этом клубе). Поэтому все заказы/избранное/
    транзакции, уже накопленные гостем до привязки под этим guest_id,
    остаются доступны без единой миграции строк — они и так уже на нём
    записаны, см. docstring link_google.

    club_id — своя запись на каждый клуб, как и у VipClient (один и тот же
    Google-аккаунт в разных клубах — разные постоянные номера, по аналогии
    с уже принятым в проекте club-scoping для VIP).
    """

    __tablename__ = "guest_accounts"

    id = db.Column(db.Integer, primary_key=True)
    club_id = db.Column(db.Integer, db.ForeignKey("clubs.club_id"), nullable=False, index=True)
    telegram_user_id = db.Column(db.BigInteger, nullable=False, index=True)
    google_sub = db.Column(db.String(255), nullable=False, index=True)
    email = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)

    club = db.relationship("Club")

    __table_args__ = (
        db.UniqueConstraint("club_id", "telegram_user_id", name="uq_guest_accounts_club_user"),
        db.UniqueConstraint("club_id", "google_sub", name="uq_guest_accounts_club_google_sub"),
    )

    def to_dict(self):
        return {
            "id": self.id,
            "club_id": self.club_id,
            "telegram_user_id": self.telegram_user_id,
            "email": self.email,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class VipClient(db.Model):
    """
    VIP-счёт гостя в конкретном клубе (баланс + процент кэшбэка). 1:1
    перенос vip_clients из старой SQLite БД. Там был композитный
    PRIMARY KEY (user_id, venue_id) — здесь суррогатный id + обычный
    unique-констрейнт на (club_id, telegram_user_id), чтобы не тащить
    составные внешние ключи в Transaction и другие таблицы.

    Списание/кэшбэк НЕ производятся напрямую через update — см.
    services/billing_service.py::charge_at_completion, которая делает это
    вместе с записью Transaction с idempotency_key в одной транзакции БД.

    ТЗ п.45: VIP — не отдельная личность, а надстройка над уже существующим
    постоянным профилем гостя (см. GuestAccount выше). telegram_user_id
    здесь ВСЕГДА должен совпадать с telegram_user_id какой-то существующей
    записи GuestAccount этого же клуба — это не проверяется на уровне БД
    (составные внешние ключи по (club_id, telegram_user_id) сюда не
    заводились нигде в проекте и раньше), а гарантируется на уровне
    services/vip_service.py: VIP выдаётся только через одобрение заявки, а
    заявку можно подать только уже имея GuestAccount (см.
    routes/guest.py::request_vip). Прежний механизм — секретный
    access_code, который гость "гасил" на новом устройстве вместо входа
    через Google — удалён по решению п.45: постоянная личность теперь
    всегда обеспечивается GuestAccount, отдельный код избыточен и создавал
    свою собственную (более слабую) поверхность для атаки.
    """

    __tablename__ = "vip_clients"

    id = db.Column(db.Integer, primary_key=True)
    club_id = db.Column(db.Integer, db.ForeignKey("clubs.club_id"), nullable=False, index=True)
    telegram_user_id = db.Column(db.BigInteger, nullable=False, index=True)
    balance = db.Column(db.Numeric(10, 2), nullable=False, default=0)
    cashback_percent = db.Column(db.Numeric(5, 2), nullable=False, default=0)
    added_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)

    club = db.relationship("Club")

    __table_args__ = (
        db.UniqueConstraint("club_id", "telegram_user_id", name="uq_vip_clients_club_user"),
    )

    def to_dict(self):
        return {
            "id": self.id,
            "club_id": self.club_id,
            "telegram_user_id": self.telegram_user_id,
            "balance": float(self.balance) if self.balance is not None else None,
            "cashback_percent": float(self.cashback_percent) if self.cashback_percent is not None else None,
            "added_at": self.added_at.isoformat() if self.added_at else None,
        }


STATUS_VIP_REQUEST_PENDING = "pending"
STATUS_VIP_REQUEST_APPROVED = "approved"
STATUS_VIP_REQUEST_REJECTED = "rejected"


class VipRequest(db.Model):
    """
    Заявка гостя на VIP-статус (1:1 перенос requests/request_type='vip' из
    старой SQLite БД, см. отчёт по Role 3/4/5, п.8А). Одобряет KJ клуба —
    как и в старом боте, здесь нет отдельного механизма для Admin
    (Admin App пока не трогаем на этом шаге).
    """

    __tablename__ = "vip_requests"

    id = db.Column(db.Integer, primary_key=True)
    club_id = db.Column(db.Integer, db.ForeignKey("clubs.club_id"), nullable=False, index=True)
    telegram_user_id = db.Column(db.BigInteger, nullable=False, index=True)
    table_no = db.Column(db.Integer, nullable=True)
    status = db.Column(db.String(20), nullable=False, default=STATUS_VIP_REQUEST_PENDING, index=True)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    decided_at = db.Column(db.DateTime(timezone=True), nullable=True)
    decided_by = db.Column(db.Integer, db.ForeignKey("kj_operators.id"), nullable=True)

    club = db.relationship("Club")

    def to_dict(self):
        return {
            "id": self.id,
            "club_id": self.club_id,
            "telegram_user_id": self.telegram_user_id,
            "table_no": self.table_no,
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "decided_at": self.decided_at.isoformat() if self.decided_at else None,
        }


class Favorite(db.Model):
    """
    Избранная песня гостя (1:1 перенос favorites из старой SQLite БД, см.
    отчёт по Role 3/4/5, п.3) — с одним сознательным упрощением: старая
    таблица ссылалась на локальный каталог songs(song_id), которого в
    новой архитектуре пока нет (поиск по каталогу — отдельный, ещё не
    сделанный шаг, см. отчёт). Поэтому здесь песня хранится как есть
    (song_title/artist), без FK на каталог — функционально то же самое
    избранное, без внешней зависимости от ещё не реализованного поиска.
    """

    __tablename__ = "favorites"

    id = db.Column(db.Integer, primary_key=True)
    club_id = db.Column(db.Integer, db.ForeignKey("clubs.club_id"), nullable=False, index=True)
    telegram_user_id = db.Column(db.BigInteger, nullable=False, index=True)
    song_title = db.Column(db.String(500), nullable=False)
    artist = db.Column(db.String(500), nullable=True)
    service_id = db.Column(db.Integer, db.ForeignKey("services.id"), nullable=True)
    added_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)

    club = db.relationship("Club")
    service = db.relationship("Service")

    __table_args__ = (
        db.Index("ix_favorites_club_user", "club_id", "telegram_user_id"),
    )

    def to_dict(self):
        return {
            "id": self.id,
            "club_id": self.club_id,
            "telegram_user_id": self.telegram_user_id,
            "song_title": self.song_title,
            "artist": self.artist,
            "service_id": self.service_id,
            "added_at": self.added_at.isoformat() if self.added_at else None,
        }


# --- Типы финансовых операций (новое ТЗ §12) ---
TX_TYPE_ORDER_PAYMENT = "order_payment"  # списание VIP-баланса при завершении песни
TX_TYPE_CASHBACK = "cashback"            # начисление кэшбэка после списания
TX_TYPE_TOPUP = "topup"                  # пополнение VIP-баланса (KJ/админ)
TX_TYPE_REFUND = "order_refund"          # возврат при отмене/замене песни

# Ручная корректировка баланса VIP-клиента со стороны KJ (старое: кнопки
# "➕ Начислить"/"➖ Списать"/"🔄 Установить" в карточке клиента,
# handlers/kj.py:2133-2227 — гость просит пополнение УСТНО, в баре, это не
# цифровой диалог гость↔KJ через приложение). В старом коде это действие НЕ
# писало вообще ничего в transactions/event_log (см. аудит-отчёт по
# VIP-пополнению, найденный баг №7) — здесь это исправлено: каждое ручное
# начисление/списание обязательно создаёт строку Transaction. Начисление
# использует уже существующий TX_TYPE_TOPUP; списание — отдельный тип, чтобы
# в отчётности не путать "KJ списал вручную" с "оплата заказа"/"возврат".
TX_TYPE_MANUAL_DEBIT = "manual_debit"    # ручное списание VIP-баланса (KJ)

ALL_TX_TYPES = (
    TX_TYPE_ORDER_PAYMENT,
    TX_TYPE_CASHBACK,
    TX_TYPE_TOPUP,
    TX_TYPE_REFUND,
    TX_TYPE_MANUAL_DEBIT,
)


class Transaction(db.Model):
    """
    Финансовая операция по VIP-счёту. Аналог таблицы transactions в старой
    SQLite БД (venue_id/user_id/order_id/amount/type/description), но с
    добавленной колонкой idempotency_key.

    Причина добавления: новое мастер-ТЗ переносит списание с "при создании
    заказа" на "при завершении песни" (ТЗ §12), а завершение определяется
    в первую очередь по VirtualDJ History (ТЗ §37-38) — источнику, который
    может прислать одно и то же событие повторно (переподключение моста,
    повторный опрос истории). Старый бот защищался от двойного возврата
    запросом "уже есть строка transactions с order_id+type=order_refund?"
    перед вставкой (см. database.py::refund_vip_for_order) — рабочий, но
    гоняющий состояние гонки (read-then-write) способ. idempotency_key с
    уникальным индексом в БД делает то же самое атомарно на уровне
    констрейнта: вызывающий код формирует ключ детерминированно от события
    (например, f"completion:{order_id}" для списания или
    f"cashback:{order_id}" для кэшбэка), и вторая попытка вставить ту же
    операцию упадёт на уникальном индексе, а не проскочит из-за гонки.
    """

    __tablename__ = "transactions"

    id = db.Column(db.Integer, primary_key=True)
    club_id = db.Column(db.Integer, db.ForeignKey("clubs.club_id"), nullable=False, index=True)

    # См. комментарий у Order.telegram_user_id — идентификация гостя будет
    # пересмотрена отдельным шагом (Guest App, ТЗ §54); здесь то же поле по
    # той же причине, без переименования сейчас.
    telegram_user_id = db.Column(db.BigInteger, nullable=False, index=True)

    order_id = db.Column(db.Integer, db.ForeignKey("orders.id"), nullable=True, index=True)

    # NUMERIC, а не REAL/FLOAT (как было в старой SQLite-таблице) — деньги не
    # должны накапливать ошибку двоичного округления при повторных
    # списаниях/кэшбэках. Инженерное решение в рамках уже данного разрешения
    # принимать такие решения самостоятельно; при необходимости можно
    # свернуть обратно к REAL для точного паритета со старой схемой.
    amount = db.Column(db.Numeric(10, 2), nullable=False)

    type = db.Column(db.String(20), nullable=False, index=True)
    description = db.Column(db.Text, nullable=True)

    idempotency_key = db.Column(db.String(255), nullable=False, unique=True)

    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False, index=True)

    club = db.relationship("Club", back_populates="transactions")
    order = db.relationship("Order", back_populates="transactions")

    __table_args__ = (
        db.Index("ix_transactions_club_user", "club_id", "telegram_user_id"),
    )

    def to_dict(self):
        return {
            "id": self.id,
            "club_id": self.club_id,
            "telegram_user_id": self.telegram_user_id,
            "order_id": self.order_id,
            "amount": float(self.amount) if self.amount is not None else None,
            "type": self.type,
            "description": self.description,
            "idempotency_key": self.idempotency_key,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class ChatMessage(db.Model):
    """
    Сообщение в чате гость↔KJ (ТЗ §20, §49; включается флагом
    Club.chat_enabled). Смысловой аналог старой chat_messages
    (venue_id/from_user_id/to_user_id/message_text/table_number/is_read),
    но без строгого to_user_id: направление хранится явно (from_guest),
    а адресат подразумевается — "любой KJ клуба" при from_guest=True (в
    старом боте отвечал тот KJ, кто первым нажал «Ответить», а не заранее
    назначенный), и конкретный гость по telegram_user_id при
    from_guest=False. telegram_user_id здесь всегда обозначает ГОСТЯ,
    независимо от того, кто автор сообщения — так переписка одного гостя
    достаётся одним запросом с обеих сторон.
    """

    __tablename__ = "chat_messages"

    id = db.Column(db.Integer, primary_key=True)
    club_id = db.Column(db.Integer, db.ForeignKey("clubs.club_id"), nullable=False, index=True)
    telegram_user_id = db.Column(db.BigInteger, nullable=False, index=True)
    table_no = db.Column(db.Integer, nullable=True)
    from_guest = db.Column(db.Boolean, nullable=False)
    message_text = db.Column(db.Text, nullable=False)
    is_read = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)

    club = db.relationship("Club")

    __table_args__ = (
        db.Index("ix_chat_messages_club_user", "club_id", "telegram_user_id"),
    )

    def to_dict(self):
        return {
            "id": self.id,
            "club_id": self.club_id,
            "telegram_user_id": self.telegram_user_id,
            "table_no": self.table_no,
            "from_guest": self.from_guest,
            "message_text": self.message_text,
            "is_read": self.is_read,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


# --- Групповой стол (старое: database.py::table_groups/table_join_requests,
# аудит "Групповой стол/Присоединение/Управление группой", утверждённая
# пользователем спецификация — вариант А, полноценный шлюз). Три отдельные
# таблицы вместо одного поля users.table_number из старой схемы: в новой
# архитектуре нет постоянной таблицы "пользователь", поэтому членство нужно
# хранить явно, а не выводить из побочного поля аккаунта. ---

STATUS_TABLE_JOIN_PENDING = "pending"
STATUS_TABLE_JOIN_APPROVED = "approved"
STATUS_TABLE_JOIN_REJECTED = "rejected"


class TableGroup(db.Model):
    """
    Групповой стол — старое: table_groups (database.py:191-200,
    venue_id/table_number/admin_user_id, PK по venue_id+table_number).
    Существование строки означает "стол занят, у него есть админ" — ровно
    как в старом коде (get_table_admin_user_id возвращал NULL <=> стола нет).
    """

    __tablename__ = "table_groups"

    id = db.Column(db.Integer, primary_key=True)
    club_id = db.Column(db.Integer, db.ForeignKey("clubs.club_id"), nullable=False, index=True)
    table_no = db.Column(db.Integer, nullable=False)
    admin_guest_id = db.Column(db.BigInteger, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)

    club = db.relationship("Club")

    __table_args__ = (
        db.UniqueConstraint("club_id", "table_no", name="uq_table_groups_club_table"),
    )

    def to_dict(self):
        return {
            "id": self.id,
            "club_id": self.club_id,
            "table_no": self.table_no,
            # Строкой, а не числом: guest_id — случайные 62-битные значения
            # (см. routes/guest.py::_new_guest_id), которые превышают
            # Number.MAX_SAFE_INTEGER (2^53-1) в JS. JSON.parse в браузере
            # молча округляет такие числа, из-за чего именно ЭТОТ id,
            # отправленный обратно на сервер (например, в URL кика/передачи
            # прав), переставал совпадать с настоящим значением в БД — живой
            # баг, найденный в Playwright UI-тесте (404 NOT_A_MEMBER при
            # кике). Гость видит просто "Гость <id>" в UI, арифметика над
            # значением нигде не нужна — строка ничего не ломает.
            "admin_guest_id": str(self.admin_guest_id),
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class TableGroupMember(db.Model):
    """
    Членство в групповом столе — старое: неявно, users.table_number ==
    table_number (database.py:37-49, 515-523 get_table_users). Здесь
    отдельная таблица, потому что у Guest App нет постоянного аккаунта, из
    поля которого можно было бы вывести членство — присутствие строки here
    и есть единственный источник истины "этот guest_id сейчас в этой
    группе". Удаление строки = уход/кик, не флаг is_active.
    """

    __tablename__ = "table_group_members"

    id = db.Column(db.Integer, primary_key=True)
    club_id = db.Column(db.Integer, db.ForeignKey("clubs.club_id"), nullable=False, index=True)
    table_no = db.Column(db.Integer, nullable=False)
    guest_id = db.Column(db.BigInteger, nullable=False)
    joined_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)

    club = db.relationship("Club")

    __table_args__ = (
        db.UniqueConstraint("club_id", "table_no", "guest_id", name="uq_table_group_members_unique"),
        db.Index("ix_table_group_members_lookup", "club_id", "table_no"),
    )

    def to_dict(self):
        return {
            "id": self.id,
            "club_id": self.club_id,
            "table_no": self.table_no,
            # Строкой — см. комментарий у TableGroup.to_dict() выше (потеря
            # точности больших int в JS JSON.parse).
            "guest_id": str(self.guest_id),
            "joined_at": self.joined_at.isoformat() if self.joined_at else None,
        }


class TableJoinRequest(db.Model):
    """
    Заявка на присоединение к занятому групповому столу — старое:
    table_join_requests (database.py:203-213). Тот же паттерн статусов, что
    и у VipRequest выше (STATUS_VIP_REQUEST_*), с тем же смыслом pending/
    approved/rejected.
    """

    __tablename__ = "table_join_requests"

    id = db.Column(db.Integer, primary_key=True)
    club_id = db.Column(db.Integer, db.ForeignKey("clubs.club_id"), nullable=False, index=True)
    table_no = db.Column(db.Integer, nullable=False)
    guest_id = db.Column(db.BigInteger, nullable=False)
    status = db.Column(db.String(20), nullable=False, default=STATUS_TABLE_JOIN_PENDING, index=True)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    decided_at = db.Column(db.DateTime(timezone=True), nullable=True)

    club = db.relationship("Club")

    __table_args__ = (
        db.Index("ix_table_join_requests_lookup", "club_id", "table_no", "status"),
    )

    def to_dict(self):
        return {
            "id": self.id,
            "club_id": self.club_id,
            "table_no": self.table_no,
            # Строкой — см. комментарий у TableGroup.to_dict() выше (потеря
            # точности больших int в JS JSON.parse).
            "guest_id": str(self.guest_id),
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "decided_at": self.decided_at.isoformat() if self.decided_at else None,
        }
