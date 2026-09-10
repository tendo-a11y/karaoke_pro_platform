# Доработка karaoke_pro — отчёт и инструкция по запуску

Реализовано по ТЗ «Доработка существующего Telegram-бота karaoke_pro».
Существующая функциональность бота не удалялась и не заменялась — новый
Backend, React-панель и AI-поиск подключены как дополнительный слой поверх
неё (см. раздел «Что сохранено» ниже).

## 0. Срочно: утечка токена бота

В исходном репозитории в корне лежал файл `download` — это был `.env` с
**реальным токеном Telegram-бота**, закоммиченный в публичный GitHub-репозиторий.
Файл вынесен в `secrets_quarantine/leaked_env_DO_NOT_USE.txt` и нигде не
используется, но токен уже виден в истории публичного репо.

**Нужно сделать до запуска в проде:** зайти в @BotFather → `/revoke` →
получить новый токен → положить его в свой локальный `.env` (не коммитить).
Заодно стоит переписать git-историю (`git filter-repo`/BFG) или создать
репозиторий заново, если история важна.

## 1. Что было не так с самим репозиторием (Фаза 1 ТЗ)

Выгруженный на GitHub код не запускался: `bot.py` импортирует
`from handlers import admin, kj, ...` и `from keyboards import kj_kb`, но
папок `handlers/` и `keyboards/` в репозитории не было — все файлы лежали
плоско в корне (сохранились два `__init__.py` с одинаковым именем,
один был переименован в `__init__ (1).py` — явный след того, что при
выгрузке/архивации структура папок потерялась).

Исправлено: файлы разложены обратно по `handlers/` и `keyboards/`, бот
запускается (доходит до реального обращения к Telegram API — проверено).

## 2. Что сохранено без изменений

Как требует ТЗ (п.3): роли Admin/KJ/VIP/клиент/клиент без стола, существующий
inline-поиск песен, существующая очередь и её ручное управление KJ прямо в
Telegram, статистика, отчётность, вся SQLite-модель данных. Единственная
правка существующего кода — 12 строк в `bot.py` (`handle_service_selection`):
после того как заказ создан как обычно, он ещё и параллельно (фоновой
таской, best-effort) отправляется в новый Backend. Ни один существующий путь
выполнения не изменён и не удалён.

## 3. Новые компоненты

### 3.1 Backend API — `backend/`
Flask + SQLAlchemy + PostgreSQL. Реализованы все эндпоинты из ТЗ п.23,
статусы из п.10, атомарная защита от двойного подтверждения (п.15, через
`UPDATE ... WHERE status='pending'` — не через блокировки в коде), проверка
прав KJ и изоляция клубов исключительно по данным из БД (п.24-26, п.34 —
единый формат ошибок), WebSocket-события из п.22 (`flask-socketio`).

Запуск:
```bash
cd backend
pip install -r requirements.txt
createdb karaoke_orders          # реальный Postgres, не SQLite
export DATABASE_URL=postgresql+psycopg2://user:pass@localhost/karaoke_orders
python manage.py init-db
python manage.py add-club --club-id 1 --name "Absolutis"   # club_id = venue_id из основного бота
python manage.py add-kj --telegram-id 123456789 --club-id 1 --name "DJ Vasile"
python wsgi.py
```

Тесты (16 шт., реальный Postgres, включая настоящую гонку из 5 потоков на
двойное подтверждение — не только последовательные вызовы):
```bash
createdb karaoke_orders_test
export TEST_DATABASE_URL=postgresql+psycopg2://user:pass@localhost/karaoke_orders_test
pytest backend/tests/ -v
```

### 3.2 React KJ Panel — `kj-panel/`
Vite + React, `socket.io-client`. Список новых заказов клуба,
ПОДТВЕРДИТЬ/ОТКЛОНИТЬ, живая очередь VirtualDJ, обновление в реальном
времени по WebSocket (проверено вживую в браузере с настоящим backend).

```bash
cd kj-panel
npm install
npm run dev      # http://localhost:3000
```

KJ получает персональную ссылку на панель командой `/kjpanel` в Telegram
(файл `kj_panel_link.py` в боте) — ссылка содержит JWT, привязанный к его
`telegram_user_id`; какой клуб ему показывать, панель узнаёт не из ссылки,
а из `GET /api/kj/me`, который смотрит это в БД.

### 3.3 VirtualDJ — `backend/vdj/`
ТЗ (п.16) прямо запрещает фиксировать непроверенный URL VirtualDJ — у меня
нет доступа к реально установленному VDJ клуба, чтобы определить протокол.
Сделан адаптер `VirtualDJClient` с двумя реализациями:
- `MockVirtualDJClient` — рабочая имитация очереди в памяти процесса,
  на ней проверены статусы `queued`/`error` и вся защита от двойной обработки;
- `HttpVirtualDJClient` — заготовка под REST-подобный протокол
  (`VDJ_API_URL`/`VDJ_API_TOKEN`), которую нужно свести с фактическим
  способом подключения (родной плагин VDJ, VDJScript, чтение плейлиста и
  т.п.) **на месте, на установленной версии VirtualDJ**, прежде чем включать
  `VDJ_ADAPTER=http` в проде. Это единственная часть ТЗ, которую нельзя
  закрыть без доступа к реальному VirtualDJ клуба.

### 3.4 AI-поиск (Claude + Genius) — `ai_search.py`, `ai_search_handlers.py`
Команда `/ai` в боте — дополнение к существующему inline-поиску, не замена
(ТЗ п.30). Claude только анализирует текст гостя и предлагает варианты
"исполнитель - название" для поиска; сами треки достаёт Genius. Если найдено
меньше 3 результатов — показываются реально найденные, без выдумывания
(проверено тестами `tests_bot/test_ai_search.py`). Дальше — тот же путь
создания заказа, что и в обычном сценарии (тот же `db.create_order`,
то же уведомление KJ), плюс отправка в новый Backend.

Требует `ANTHROPIC_API_KEY` и `GENIUS_API_KEY` в `.env` — без них команда
`/ai` отвечает, что ничего не найдено, вместо падения.

## 4. Переменные окружения

См. `.env.example` (бот) и `backend/.env.example`-эквивалент в
`backend/config.py`. Ключевое: `BACKEND_INTERNAL_TOKEN` и
`KJ_PANEL_JWT_SECRET` должны совпадать у бота и у Backend — это общие
секреты, а не публичные ключи.

## 5. Тесты и сценарии из ТЗ (раздел 42)

| # | Сценарий | Где проверено |
|---|----------|----------------|
| 1 | Обычный заказ | `test_guest_order_is_visible_to_kj` |
| 2 | Подтверждение | `test_confirm_moves_order_to_vdj_queue` + вживую в браузере |
| 3 | Двойное нажатие | `test_double_confirm_returns_409` + `test_concurrent_double_confirm_adds_song_once` (настоящая гонка потоков) |
| 4 | Ошибка VirtualDJ | `test_vdj_failure_sets_error_status` |
| 5 | Несколько заказов | `test_multiple_orders_per_table_all_visible` |
| 6 | Несколько клубов | `test_kj_cannot_see_other_club_orders`, `test_kj_cannot_confirm_other_club_order` |
| 7 | Отклонение | `test_reject_order` |
| 8 | Перезапуск backend | `test_orders_persist_in_postgres_across_sessions` (данные в Postgres, не в памяти процесса) |

Итого: 16 тестов backend + 5 тестов AI-поиска = 21 автотест, все проходят.

## 6. Что осталось сделать перед продакшеном

1. Отозвать и заменить утёкший `BOT_TOKEN` (см. раздел 0).
2. Определить реальный протокол подключения к установленному в клубе
   VirtualDJ и реализовать его в `backend/vdj/http_client.py` (ТЗ п.16).
3. Решить вопрос миграции данных из существующей SQLite в новую
   централизованную модель — по ТЗ (п.8) это отдельный этап уже после того,
   как новая система обкатана параллельно со старой.
4. Задеплоить Backend за настоящим Postgres (не тем, что поднят для тестов
   в этой сессии) и настроить продовый WSGI-сервер (`gunicorn` указан в
   `requirements.txt`).
