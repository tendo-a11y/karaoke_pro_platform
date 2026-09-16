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

    chat_enabled = db.Column(db.Boolean, nullable=False, default=False)

    city = db.Column(db.String(255), nullable=True)
    phone = db.Column(db.String(64), nullable=True)
    email = db.Column(db.String(255), nullable=True)

    table_count = db.Column(db.Integer, nullable=True)

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

    2026-09, запрос пользователя "доступ KJ Pro определяется Google-аккаунтом
    клуба": KJ физически меняются и переезжают между клубами/городами, а
    Telegram-привязка к конкретному человеку для этого неудобна — решение
    принято явно: один постоянный Google-аккаунт на клуб (не на человека)
    становится основным способом входа, Telegram (/kjpanel) остаётся
    запасным. Поэтому telegram_user_id стал nullable — запись может быть
    только с google_email, только с telegram_user_id, или с обоими сразу
    (см. services/kj_admin_service.assign_kj). google_sub — стабильный
    идентификатор Google-аккаунта, заполняется САМ при первом успешном входе
    (см. routes/kj.py::kj_google_login), сверяясь по email, который сюда
    заранее вписывает администратор клуба (Admin App) — в отличие от
    guest_accounts.google_sub, здесь привязку нельзя создать самим фактом
    входа с любой почты: ей должен предшествовать явный шаг администратора,
    иначе Google-вход давал бы доступ к управлению клубом кому попало.
    """

    __tablename__ = "kj_operators"

    id = db.Column(db.Integer, primary_key=True)
    telegram_user_id = db.Column(db.BigInteger, unique=True, nullable=True, index=True)
    google_sub = db.Column(db.String(255), unique=True, nullable=True, index=True)
    google_email = db.Column(db.String(255), unique=True, nullable=True, index=True)
    club_id = db.Column(db.Integer, db.ForeignKey("clubs.club_id"), nullable=False)
    display_name = db.Column(db.String(255))
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)

    club = db.relationship("Club", back_populates="kj_operators")

    def to_dict(self):
        return {
            "id": self.id,
            "telegram_user_id": self.telegram_user_id,
            "google_email": self.google_email,
            "google_linked": self.google_sub is not None,
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

    telegram_user_id = db.Column(db.BigInteger, nullable=False, index=True)
    club_id = db.Column(db.Integer, db.ForeignKey("clubs.club_id"), nullable=False, index=True)
    table_no = db.Column(db.Integer, nullable=True)
    guest_type = db.Column(db.String(20), nullable=True)

    song_title = db.Column(db.String(500), nullable=False)
    artist = db.Column(db.String(500), nullable=True)
    key = db.Column(db.SmallInteger, nullable=False, default=0)
    tempo = db.Column(db.SmallInteger, nullable=False, default=0)

    service_id = db.Column(db.Integer, db.ForeignKey("services.id"), nullable=True)

    status = db.Column(db.String(20), nullable=False, default=STATUS_PENDING, index=True)

    source = db.Column(db.String(20), nullable=False, default="guest")

    channel = db.Column(db.String(20), nullable=False, default="telegram")

    vdj_item_id = db.Column(db.String(255), nullable=True)
    vdj_filepath = db.Column(db.Text, nullable=True)
    error_message = db.Column(db.Text, nullable=True)
    confirmed_by = db.Column(db.Integer, db.ForeignKey("kj_operators.id"), nullable=True)

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
    Услуга/тариф, который гость выбирает при заказе.
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
    Каталог песен клуба.
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
    Постоянный профиль гостя Guest App.
    """

    __tablename__ = "guest_accounts"

    id = db.Column(db.Integer, primary_key=True)
    club_id = db.Column(db.Integer, db.ForeignKey("clubs.club_id"), nullable=False, index=True)
    telegram_user_id = db.Column(db.BigInteger, nullable=False, index=True)
    google_sub = db.Column(db.String(255), nullable=False, index=True)
    email = db.Column(db.String(255), nullable=True)

    display_name = db.Column(db.String(60), nullable=True)

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
            "display_name": self.display_name,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class VipClient(db.Model):
    """
    VIP-счёт гостя в конкретном клубе (баланс + процент кэшбэка).
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
    Заявка гостя на VIP-статус.
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
    Избранная песня гостя.
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


TX_TYPE_ORDER_PAYMENT = "order_payment"
TX_TYPE_CASHBACK = "cashback"
TX_TYPE_TOPUP = "topup"
TX_TYPE_REFUND = "order_refund"
TX_TYPE_MANUAL_DEBIT = "manual_debit"

ALL_TX_TYPES = (
    TX_TYPE_ORDER_PAYMENT,
    TX_TYPE_CASHBACK,
    TX_TYPE_TOPUP,
    TX_TYPE_REFUND,
    TX_TYPE_MANUAL_DEBIT,
)


class Transaction(db.Model):
    """
    Финансовая операция по VIP-счёту.
    """

    __tablename__ = "transactions"

    id = db.Column(db.Integer, primary_key=True)
    club_id = db.Column(db.Integer, db.ForeignKey("clubs.club_id"), nullable=False, index=True)

    telegram_user_id = db.Column(db.BigInteger, nullable=False, index=True)

    order_id = db.Column(db.Integer, db.ForeignKey("orders.id"), nullable=True, index=True)

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
    Сообщение в чате гость↔KJ.
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


STATUS_TABLE_JOIN_PENDING = "pending"
STATUS_TABLE_JOIN_APPROVED = "approved"
STATUS_TABLE_JOIN_REJECTED = "rejected"


class TableGroup(db.Model):
    """
    Групповой стол.
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
            "admin_guest_id": str(self.admin_guest_id),
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class TableGroupMember(db.Model):
    """
    Членство в групповом столе.
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
            "guest_id": str(self.guest_id),
            "joined_at": self.joined_at.isoformat() if self.joined_at else None,
        }


class TableJoinRequest(db.Model):
    """
    Заявка на присоединение к занятому групповому столу.
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
            "guest_id": str(self.guest_id),
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "decided_at": self.decided_at.isoformat() if self.decided_at else None,
        }


class GuestStatus(db.Model):
    """
    Живой статус гостя, который KJ управляет из карточки гостя в KJ Panel.
    """

    __tablename__ = "guest_statuses"

    id = db.Column(db.Integer, primary_key=True)
    club_id = db.Column(db.Integer, db.ForeignKey("clubs.club_id"), nullable=False, index=True)
    telegram_user_id = db.Column(db.BigInteger, nullable=False, index=True)
    table_no = db.Column(db.Integer, nullable=True)
    is_blocked = db.Column(db.Boolean, nullable=False, default=False)
    blocked_at = db.Column(db.DateTime(timezone=True), nullable=True)
    blocked_by = db.Column(db.Integer, db.ForeignKey("kj_operators.id"), nullable=True)
    updated_at = db.Column(db.DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)

    club = db.relationship("Club")

    __table_args__ = (
        db.UniqueConstraint("club_id", "telegram_user_id", name="uq_guest_statuses_club_user"),
    )

    def to_dict(self):
        return {
            "id": self.id,
            "club_id": self.club_id,
            "guest_id": str(self.telegram_user_id),
            "table_no": self.table_no,
            "is_blocked": self.is_blocked,
            "blocked_at": self.blocked_at.isoformat() if self.blocked_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
