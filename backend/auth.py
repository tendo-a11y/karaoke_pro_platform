import time
from functools import wraps

import jwt
from flask import current_app, g, request

from errors import api_error
from extensions import db
from models import AdminUser, Club, KJOperator


def issue_kj_token(telegram_user_id: int, secret: str, ttl_seconds: int) -> str:
    """
    Выпускает JWT для KJ-панели. Токен несёт ТОЛЬКО telegram_user_id — ни роль,
    ни club_id в токене не хранятся и не используются для авторизации (ТЗ п.24):
    при каждом запросе Backend заново читает эти данные из таблицы kj_operators.
    Используется ботом (см. backend_client.py) при выдаче ссылки на панель.
    """
    now = int(time.time())
    payload = {
        "sub": str(telegram_user_id),
        "iat": now,
        "exp": now + ttl_seconds,
        "type": "kj_panel",
    }
    return jwt.encode(payload, secret, algorithm="HS256")


def issue_admin_token(telegram_user_id: int, secret: str, ttl_seconds: int) -> str:
    """
    Выпускает JWT для Admin App — по той же схеме, что issue_kj_token
    (ТЗ п.24): токен несёт только telegram_user_id, ни роль, ни club_id,
    ни is_super_admin в нём не хранятся — при каждом запросе Backend
    заново читает эти данные из admin_users.
    """
    now = int(time.time())
    payload = {
        "sub": str(telegram_user_id),
        "iat": now,
        "exp": now + ttl_seconds,
        "type": "admin_panel",
    }
    return jwt.encode(payload, secret, algorithm="HS256")


def issue_guest_token(guest_id: int, club_id: int, table_no: int | None, secret: str,
                       ttl_seconds: int) -> str:
    """
    Выпускает JWT анонимной гостевой сессии (Guest App, ТЗ Phase 4).

    ВАЖНО: это принципиально ДРУГАЯ модель доверия, чем issue_kj_token/
    issue_admin_token. Там токен несёт только идентификатор человека, а
    club_id/роль каждый раз перечитываются из БД (ТЗ п.24) — потому что KJ
    и админ заранее зарегистрированы записью в БД. У анонимного гостя такой
    записи нет и не будет (сессия создаётся на лету по факту открытия
    ссылки на столе) — поэтому club_id и table_no ЗАШИТЫ В САМ ТОКЕН и
    являются источником истины для всех /api/guest/* эндпоинтов.

    Это не новая дыра в безопасности, а точное сохранение модели доверия
    старого бота: там deep-link venue{id}_table{n} (bot.py) точно так же
    давал доступ к столу любому, кто его открыл (отсканировал QR или ввёл
    вручную) — Backend никогда не проверял "имеет ли этот Telegram-аккаунт
    физическое право сидеть за этим столом". Кто получил ссылку/QR — тот и
    гость этого стола, как и раньше.
    """
    now = int(time.time())
    payload = {
        "sub": str(guest_id),
        "club_id": club_id,
        "table_no": table_no,
        "iat": now,
        "exp": now + ttl_seconds,
        "type": "guest_session",
    }
    return jwt.encode(payload, secret, algorithm="HS256")


def _extract_bearer_token() -> str | None:
    header = request.headers.get("Authorization", "")
    if header.startswith("Bearer "):
        return header[len("Bearer "):].strip()
    return request.args.get("token")


def require_kj(view):
    """
    Декоратор для эндпоинтов KJ Panel. Проверяет подпись и срок действия JWT,
    затем САМОСТОЯТЕЛЬНО загружает KJ-оператора из БД по telegram_user_id из
    токена и кладёт его в g.kj. Ничего, что прислал клиент (club_id, order.id
    и т.п.), не считается источником прав доступа — только запись в БД.
    """

    @wraps(view)
    def wrapper(*args, **kwargs):
        token = _extract_bearer_token()
        if not token:
            return api_error(401, "UNAUTHORIZED", "Токен авторизации отсутствует")

        try:
            payload = jwt.decode(
                token, current_app.config["KJ_JWT_SECRET"], algorithms=["HS256"]
            )
        except jwt.ExpiredSignatureError:
            return api_error(401, "TOKEN_EXPIRED", "Срок действия токена истёк")
        except jwt.InvalidTokenError:
            return api_error(401, "UNAUTHORIZED", "Недействительный токен")

        try:
            telegram_user_id = int(payload.get("sub"))
        except (TypeError, ValueError):
            return api_error(401, "UNAUTHORIZED", "Недействительный токен")

        kj = KJOperator.query.filter_by(telegram_user_id=telegram_user_id).first()
        if kj is None:
            return api_error(403, "FORBIDDEN", "KJ не зарегистрирован в системе")
        if not kj.is_active:
            return api_error(403, "FORBIDDEN", "Доступ KJ заблокирован")
        if not kj.club or not kj.club.is_active:
            return api_error(403, "FORBIDDEN", "Клуб недоступен")

        g.kj = kj
        g.club_id = kj.club_id
        return view(*args, **kwargs)

    return wrapper


def require_admin(view):
    """
    Декоратор для эндпоинтов Admin App — по образцу require_kj. Обычный
    администратор (is_super_admin=False) заперт в своём клубе: если клуб
    неактивен, доступ запрещён, как и у KJ. Супер-админ (единственный
    config.ADMIN_ID старой системы) этой проверкой не ограничивается —
    у него нет привязки к активности конкретного клуба.
    """

    @wraps(view)
    def wrapper(*args, **kwargs):
        token = _extract_bearer_token()
        if not token:
            return api_error(401, "UNAUTHORIZED", "Токен авторизации отсутствует")

        try:
            payload = jwt.decode(
                token, current_app.config["ADMIN_JWT_SECRET"], algorithms=["HS256"]
            )
        except jwt.ExpiredSignatureError:
            return api_error(401, "TOKEN_EXPIRED", "Срок действия токена истёк")
        except jwt.InvalidTokenError:
            return api_error(401, "UNAUTHORIZED", "Недействительный токен")

        try:
            telegram_user_id = int(payload.get("sub"))
        except (TypeError, ValueError):
            return api_error(401, "UNAUTHORIZED", "Недействительный токен")

        admin = AdminUser.query.filter_by(telegram_user_id=telegram_user_id).first()
        if admin is None:
            return api_error(403, "FORBIDDEN", "Администратор не зарегистрирован в системе")
        if not admin.is_active:
            return api_error(403, "FORBIDDEN", "Доступ администратора заблокирован")
        if not admin.is_super_admin and (not admin.club or not admin.club.is_active):
            return api_error(403, "FORBIDDEN", "Клуб недоступен")

        g.admin = admin
        g.club_id = admin.club_id
        return view(*args, **kwargs)

    return wrapper


def require_guest(view):
    """
    Декоратор для эндпоинтов Guest App. В отличие от require_kj/require_admin,
    club_id/table_no берутся из ПОДПИСАННОГО ТОКЕНА (см. issue_guest_token),
    а не из отдельной записи в БД — у анонимного гостя её нет. Клуб всё
    равно перепроверяется в БД на каждый запрос (существует/активен) — если
    клуб отключили после выдачи токена, доступ пропадает сразу же, как и у
    KJ/админа.

    ОТКРЫТЫЙ ВОПРОС на будущее (проверено сейчас, но не закрыто навсегда):
    club_id перепроверяется живьём из БД на каждый запрос, а table_no —
    НЕТ, он всегда берётся из токена как есть. Сегодня это безопасно,
    потому что в новом Backend вообще нет понятия "стол закрыт/недоступен"
    отдельно от клуба (нет аналога старых table_groups/table_join_requests
    — это ещё не перенесено, см. PHASE1_AUDIT). Как только появится
    функция "закрыть стол" (Guest App / KJ Pro, ТЗ §47-48), здесь
    ОБЯЗАТЕЛЬНО нужно добавить такую же живую проверку table_no по БД,
    иначе гость со старым токеном сможет продолжать заказывать на уже
    закрытый стол. Не удалять этот комментарий при реализации закрытия
    стола, пока проверка не добавлена.
    """

    @wraps(view)
    def wrapper(*args, **kwargs):
        token = _extract_bearer_token()
        if not token:
            return api_error(401, "UNAUTHORIZED", "Токен гостевой сессии отсутствует")

        try:
            payload = jwt.decode(
                token, current_app.config["GUEST_JWT_SECRET"], algorithms=["HS256"]
            )
        except jwt.ExpiredSignatureError:
            return api_error(401, "TOKEN_EXPIRED", "Сессия истекла, откройте ссылку заново")
        except jwt.InvalidTokenError:
            return api_error(401, "UNAUTHORIZED", "Недействительный токен сессии")

        try:
            guest_id = int(payload.get("sub"))
            club_id = int(payload.get("club_id"))
        except (TypeError, ValueError):
            return api_error(401, "UNAUTHORIZED", "Недействительный токен сессии")
        table_no = payload.get("table_no")

        club = db.session.get(Club, club_id)
        if club is None or not club.is_active:
            return api_error(403, "FORBIDDEN", "Клуб недоступен")

        g.guest_id = guest_id
        g.club_id = club_id
        g.table_no = table_no
        return view(*args, **kwargs)

    return wrapper


def require_bot_token(view):
    """
    Проверка серверного секрета для эндпоинтов, которые вызывает только сам
    Telegram-бот (POST /api/client/order). Гость не может создать заказ
    напрямую в обход бота.
    """

    @wraps(view)
    def wrapper(*args, **kwargs):
        token = request.headers.get("X-Internal-Token")
        if not token or token != current_app.config["BOT_INTERNAL_TOKEN"]:
            return api_error(401, "UNAUTHORIZED", "Неверный внутренний токен")
        return view(*args, **kwargs)

    return wrapper
