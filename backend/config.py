import os


def _normalize_database_url(url):
    """
    В requirements.txt зафиксирован конкретный драйвер psycopg2-binary —
    другой (например psycopg v3) в образе просто не установлен. Railway
    подставляет DATABASE_URL из встроенного Postgres-плагина как есть, без
    суффикса драйвера ("postgresql://..."), и то, какой драйвер SQLAlchemy
    выберет по умолчанию для такой голой схемы, зависит от установленной
    версии SQLAlchemy (она не запинена в requirements.txt и подтягивается
    последней доступной при каждой сборке образа) — 26.09.2026 это привело
    к падению бэкенда при старте (ModuleNotFoundError: No module named
    'psycopg', т.к. SQLAlchemy выбрал драйвер psycopg v3, которого нет в
    образе), хотя код и переменные окружения не менялись. Чтобы это не
    зависело от версии SQLAlchemy, здесь драйвер всегда прописывается явно.
    """
    if not url:
        return None
    prefix, sep, rest = url.partition("://")
    if not sep:
        return url
    base_scheme = prefix.split("+", 1)[0]
    if base_scheme in ("postgres", "postgresql"):
        return f"postgresql+psycopg2://{rest}"
    return url


class Config:
    """
    Конфигурация Backend API.
    Все секреты берутся из переменных окружения (см. .env.example) — ТЗ п.33.
    """

    SQLALCHEMY_DATABASE_URI = _normalize_database_url(
        os.getenv("DATABASE_URL")
    ) or "postgresql+psycopg2://postgres:postgres@localhost:5432/karaoke_orders"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True}

    # Общий секрет между Telegram-ботом и Backend для эндпоинта POST /api/client/order.
    # Гость никогда не должен иметь возможность создать заказ напрямую в обход бота.
    BOT_INTERNAL_TOKEN = os.getenv("BACKEND_INTERNAL_TOKEN", "change_me_shared_secret")

    # Секрет для подписи JWT токенов KJ-панели. Тот же секрет должен быть
    # прописан у бота (KJ_PANEL_JWT_SECRET), т.к. именно бот выпускает токен
    # для конкретного KJ по кнопке в Telegram — см. backend_client.py в боте.
    KJ_JWT_SECRET = os.getenv("KJ_PANEL_JWT_SECRET", "change_me_jwt_secret")
    KJ_JWT_TTL_SECONDS = int(os.getenv("KJ_JWT_TTL_SECONDS", "43200"))  # 12 часов

    # Отдельный секрет для Admin App (Phase 3) — намеренно не тот же, что у
    # KJ Panel: компрометация одного токена не должна давать доступ к
    # эндпоинтам другой роли.
    ADMIN_JWT_SECRET = os.getenv("ADMIN_PANEL_JWT_SECRET", "change_me_admin_jwt_secret")
    ADMIN_JWT_TTL_SECONDS = int(os.getenv("ADMIN_JWT_TTL_SECONDS", "43200"))  # 12 часов

    # Guest App (Phase 4) — токен анонимной гостевой сессии. В отличие от
    # KJ/Admin, гость не регистрируется в БД заранее: сессия выпускается
    # сразу по QR/ссылке на столе (аналог старого deep-link
    # venue{id}_table{n} в Telegram-боте — см. bot.py). TTL длиннее, чем у
    # KJ/Admin, — гостя не должно разлогинивать посреди вечера.
    GUEST_JWT_SECRET = os.getenv("GUEST_JWT_SECRET", "change_me_guest_jwt_secret")
    GUEST_JWT_TTL_SECONDS = int(os.getenv("GUEST_JWT_TTL_SECONDS", "43200"))  # 12 часов

    TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("BOT_TOKEN")

    # --- VirtualDJ ---
    # ВАЖНО (ТЗ п.16): конкретный протокол подключения к VirtualDJ должен быть
    # определён по фактически установленной версии/конфигурации VDJ. Пока это
    # не сделано, используется VDJ_ADAPTER=mock — рабочая имитация очереди,
    # позволяющая полностью реализовать и протестировать всё вокруг интеграции
    # (статусы, защита от двойной обработки, WebSocket, KJ Panel), не выдумывая
    # несуществующий API. Когда реальный способ подключения будет определён,
    # включается VDJ_ADAPTER=http и заполняются VDJ_API_URL/VDJ_API_TOKEN.
    VDJ_ADAPTER = os.getenv("VDJ_ADAPTER", "mock")
    VDJ_API_URL = os.getenv("VDJ_API_URL")
    VDJ_API_TOKEN = os.getenv("VDJ_API_TOKEN")

    CORS_ORIGINS = os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",")

    # 1:1 перенос config.py::ADMIN_COMMISSION старого бота (0.05, не
    # настраивалось по клубам) — используется в финансах клуба Admin App
    # (аудит "Управление клубами", handlers/admin.py::venue_finance_details):
    # admin_cashback = revenue_month * ADMIN_COMMISSION.
    ADMIN_COMMISSION = float(os.getenv("ADMIN_COMMISSION", "0.05"))

    # Базовый URL Guest App — нужен Admin App для генерации ссылок на QR-код
    # стола (аналог старого deep-link venue{id} в Telegram, только теперь на
    # Guest App с явным table_no в query, см. план блока "Управление клубами").
    GUEST_APP_URL = os.getenv("GUEST_APP_URL", "http://localhost:5174")

    # 1:1 перенос config.py::MAX_ACTIVE_SONGS_PER_USER из старого бота —
    # лимит одновременных pending/queued заказов на одного гостя за столом
    # (см. PHASE1_AUDIT аудит Role 3/4/5, п.6). В старом коде хардкод, не
    # настраиваемый по клубам (venues.songs_per_table существовал в схеме,
    # но нигде не читался) — сохраняем то же самое поведение один в один,
    # а не "чиним" то, что не было частью задачи на этом шаге.
    MAX_ACTIVE_SONGS_PER_GUEST = int(os.getenv("MAX_ACTIVE_SONGS_PER_GUEST", "2"))

    # Групповой стол (аудит "Групповой стол/Присоединение/Управление
    # группой") — 1:1 перенос config.py::MAX_GROUP_SIZE старого бота (там
    # было захардкожено 4, не настраиваемо по клубам — сохраняем то же
    # самое поведение, просто через переменную окружения с тем же дефолтом).
    MAX_GROUP_SIZE = int(os.getenv("MAX_GROUP_SIZE", "4"))

    # AI-поиск (Role 3/4/5, аудит п.2) — 1:1 перенос ai_search.py старого
    # бота: Claude анализирует свободный текст гостя, Genius ищет реальные
    # треки. Оба ключа опциональны — без них соответствующий внешний вызов
    # просто не делается и функция честно возвращает пустой список (как и
    # в старом коде), без падения бэкенда.
    ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
    # Старый дефолт "claude-3-5-haiku-20241022" (модель того же класса —
    # самая быстрая/дешёвая, только для этого лёгкого анализа текста, не
    # музыкальная база) снят с обслуживания API (проверено вживую: 404
    # model not found) — заменён на актуальную модель того же класса,
    # без изменения самой логики промпта/парсинга ответа.
    ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001")
    GENIUS_API_KEY = os.getenv("GENIUS_API_KEY")

    # Постоянная идентификация гостя через Google (ТЗ п.45) — тот же приём,
    # что уже принят в проекте для VirtualDJ (см. VDJ_ADAPTER выше): пока
    # реальный Google OAuth Client ID не заведён владельцем проекта,
    # GOOGLE_AUTH_MODE=mock даёт полностью рабочую (для наших же тестов и
    # живого E2E) имитацию проверки токена — см.
    # services/google_auth_service.py. Как только ключ появится,
    # включается GOOGLE_AUTH_MODE=real и заполняется GOOGLE_CLIENT_ID —
    # остальной код (guest_account_service, routes/guest.py) не меняется
    # вообще, ровно как и было решено для VDJ_ADAPTER.
    GOOGLE_AUTH_MODE = os.getenv("GOOGLE_AUTH_MODE", "mock")
    GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")


class TestingConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = _normalize_database_url(
        os.getenv("TEST_DATABASE_URL")
    ) or "postgresql+psycopg2://postgres:postgres@localhost:5432/karaoke_orders_test"
    VDJ_ADAPTER = "mock"
    BOT_INTERNAL_TOKEN = "test_bot_token"
    KJ_JWT_SECRET = "test_jwt_secret"
    ADMIN_JWT_SECRET = "test_admin_jwt_secret"
    GUEST_JWT_SECRET = "test_guest_jwt_secret"
    GOOGLE_AUTH_MODE = "mock"
