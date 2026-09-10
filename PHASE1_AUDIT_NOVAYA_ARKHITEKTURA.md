# Phase 1 — аудит и планирование под мастер-ТЗ (Admin App + Guest App + KJ Pro + Backend + VirtualDJ)

Это пакет из 12 пунктов, которые раздел 76 нового ТЗ требует предоставить до начала кодирования. Опирается на уже готовый `ANALIZ_ORIGINALA_GLUBOKIY.md` (структура, роли, схема БД, статусы, деньги, баги — там же полные `file:line` цитаты) — здесь не дублирую то, что там уже разобрано построчно, а перевожу это в форму, которую требует новое ТЗ: маппинги, списки API/событий, план миграции.

---

## Критические развороты относительно того, что делалось раньше (фиксирую явно)

1. **Telegram полностью убирается.** Всё, что раньше было ботом (`bot.py`, `handlers/*`, `keyboards/*`), становится только источником бизнес-логики для переноса, не работающим кодом в финальной системе.
2. **VIP платит не при создании заказа, а при завершении.** Прямо противоположно текущему коду (`charge_vip_for_order` вызывается в момент создания — `bot.py:1252`, `vip.py`, `client.py`). Это явно предписано новым ТЗ (п.12), не мой произвол.
3. **Завершение — по VirtualDJ History, а не по кнопке KJ.** Кнопка остаётся как fallback (п.14), но основной источник другой.
4. **Единая очередь без разделения по источнику** (Guest/Manual/VirtualDJ) — визуально неразличимо, но Backend обязан помнить источник для internal-нужд (аудит, reconciliation).
5. **Drag & Drop вместо кнопок подтверждения** в Orders→Queue.
6. Приятное следствие архитектуры: денежный баг из старого аудита (`replace_svc_execute` не списывает деньги при замене услуги) **исчезает сам собой** — при charge-at-completion списание происходит один раз, в момент завершения, по актуальным на тот момент `service_id`/цене. Раньше баг был в том, что списание должно было происходить в момент замены, но не происходило — при новой модели самого этого шага просто не существует.

---

## 1. Структура проекта (кратко; полная версия — в ANALIZ_ORIGINALA_GLUBOKIY.md)

```
karaoke_pro/                    # оригинал — источник бизнес-логики, не трогаем до полного acceptance test
├── bot.py, handlers/, keyboards/, database.py, config.py, models.py, utils.py, lang.py, locales.py
├── backend/                    # уже начатый Flask+Postgres Backend (создан в предыдущей фазе работы)
├── kj-panel/                   # React KJ Panel (нужно будет переработать под требования KJ Pro из нового ТЗ — drag&drop, Orders+Queue сплит-экран)
├── vdj_bridge/                 # локальный мост для VirtualDJ (сетевая часть уже решена; протокол VDJScript — дорабатывается ниже)
├── ai_search.py, ai_search_handlers.py   # AI-поиск — Задача №1, отдельная от переезда с Telegram
└── ANALIZ_ORIGINALA_GLUBOKIY.md, PHASE1_AUDIT_NOVAYA_ARKHITEKTURA.md (этот файл)
```
Новые приложения, которые предстоит создать/адаптировать: `admin-app/`, `guest-app/` (оба с нуля — Admin и Guest никогда не существовали как отдельные веб-интерфейсы, только как разделы Telegram-бота), `kj-pro/` (переработка существующего `kj-panel/` под workspace Queue+Orders с drag&drop).

## 2. Список функций — см. разделы 0-8 `ANALIZ_ORIGINALA_GLUBOKIY.md` (роли, меню по ролям, деньги, статусы). Здесь не повторяю.

## 3. Список ролей — без изменений: `ROLE_ADMIN=1, ROLE_KJ=2, ROLE_VIP=3, ROLE_USER=4(→ROLE_CLIENT), ROLE_NO_TABLE=5`. Новое ТЗ (п.54) переименовывает `ROLE_USER` в `ROLE_CLIENT` только по названию — числовое значение то же.

## 4. Mapping: старые функции → новые приложения

| Старая функция (файл:строка) | Новое приложение | Примечание |
|---|---|---|
| `/set_admin`, `/unset_admin` (`admin.py:60-146`) | Admin App | становится обычным auth-flow, не Telegram-командой |
| Управление клубами (`admin.py`, создание/правка/блок/удаление/QR) | Admin App | § 6 нового ТЗ |
| Управление KJ (назначение/снятие/статистика/блокировка) | Admin App | БАГ старой системы: блокировка KJ не работала (`BlockedUserMiddleware`) — в новом Backend это должно проверяться реально, см. раздел «Конфликты» |
| Отчёты (`report_today/week/month/venues/cashback`, CSV) | Admin App | переносить логику расчёта, не таблицу `daily_stats` (она write-only, см. ниже) |
| Системный бэкап БД (`admin.py:1208`) | Admin App / инфраструктура Backend | для Postgres — штатный `pg_dump`, а не копирование файла |
| Настройки клуба, KJ-меню целиком (`kj.py`, `kj_kb.py`) | KJ Pro | §16-19 нового ТЗ |
| Очередь по столам / глобальная очередь (`kj.py: kj_queue_show`, `kj_global_queue_show`) | KJ Pro (Queue + Orders workspace, §64) | заменяется единым Queue+Orders сплит-экраном, старый текстовый вид не переносится 1:1 |
| Подтверждение/отклонение заказа (`order_approve/order_reject`) | KJ Pro | заменяется Drag&Drop (§23) — сама операция «принять» пропадает как отдельная кнопка, заказ просто перетаскивается |
| Ручное добавление заказа KJ (рабочий путь через инлайн, `bot.py:1144-1190`; мёртвый FSM-путь в `kj.py` — не переносить) | KJ Pro → «Manual» источник заказа (§21) | |
| Замена песни (`bot.py:861-966`, `kj.py:2757` — старт) | Guest App (инициирует гость/VIP) + правило `get_order_global_rank` (`database.py:803`) | правило ранга 1-2/0/≥3 подтверждено реальным кодом, переносится как есть (§7 нового ТЗ) |
| Чат KJ↔гость (`kj.py: chat_reply_*`, `client.py`, `vip.py`) | Guest App (гость) + KJ Pro (KJ) | §20, §49 — realtime через Backend |
| VIP-заявка/одобрение, топ-ап (`client.py:838-877`, `kj.py:1291-1475`) | Guest App (заявка/топ-ап) + KJ Pro (одобрение) | |
| Избранное (`client.py:407`, `vip.py:597`) | Guest App | |
| Стол/группа/join request/админ стола (`table_groups`, `table_join_requests`) | Guest App (участник) + KJ Pro (закрытие, §47-48) | Guest теперь только «запрашивает» закрытие, не закрывает сам — это уже так в § 47 нового ТЗ, но в СТАРОЙ системе тоже нет самостоятельного закрытия гостем (закрывает KJ/админ стола) — то есть это не новое ограничение, а точное соответствие текущему поведению |
| AI-поиск (`ai_search.py`, `ai_search_handlers.py`) | Guest App | Задача №1 — независима, интерфейс меняется с Telegram-диалога на форму/чат в Guest App, сам поиск (Claude+Genius) переносится как есть |
| VirtualDJ-адаптер (`backend/vdj/*`, `vdj_bridge/*`) | Backend + VirtualDJ Integration | сетевая часть (мост) готова, протокол — уточняется в разделе 9 ниже |

## 5. Mapping: SQLite → PostgreSQL

| SQLite таблица | Postgres назначение | Ключевые преобразования |
|---|---|---|
| `users` | `users` (новая) | `role` — тот же int; добавить `password_hash`/`auth_provider` (Telegram ID был встроенной идентичностью, Guest App нужен отдельный auth — см. §54, вероятно телефон/email/ссылка с токеном для гостя без пароля, аналогично текущему deep-link `venue{id}_table{n}`) |
| `venues` | `clubs` (уже создана в `backend/models.py`) | добавить все настройки клуба из §16 (songs per table, queue mode, chat_link, free_evening, vip cashback default), которых в текущей `Club`-модели ещё нет |
| `services` | `services` (новая) | 1:1, без изменений полей |
| `orders` | `orders` (уже создана, но требует полей: `key`, `tempo`, `guest_type`, `source`, `completion_source`, `vdj_filepath`, `history_matched_at` — см. §10, §14, §21) | статусы — маппинг ниже (раздел 6) |
| `vip_clients` | `vip_profiles` или расширение `users` (per-club: `balance`, `cashback_percent`) | сохранить составной ключ (user_id, club_id) |
| `songs` | `songs` (новая) | внимание: 3 конфликтующих определения `search_songs` в оригинале (`database.py:1242,1473,1688`) — при переносе логики поиска использовать только последнюю (рабочую) версию, остальные не переносить вообще |
| `transactions` | `transactions` (новая, для нового charge-at-completion) | тип операции + `idempotency_key` — **новое обязательное поле**, старая таблица его не имела (см. §12 — Idempotency) |
| `favorites` | `favorites` (новая) | 1:1 |
| `chat_messages` | `chat_messages` (новая) | добавить realtime-доставку через WebSocket, старая — только polling ботом |
| `requests` (vip/topup) | `requests` (новая) | 1:1 по смыслу |
| `table_groups`, `table_join_requests` | `table_groups`, `table_join_requests` | 1:1, включая `admin_user_id` |
| `event_log` | `event_log` / `audit_log` | требование §61 (audit logging для админских операций) — расширить, не просто перенести |
| `daily_stats` | **не переносить как таблицу-агрегат.** | В оригинале она write-only (ни один экран её не читает — подтверждено `grep`, см. `ANALIZ_ORIGINALA_GLUBOKIY.md` п.0.9). В новой системе статистику (§58) считать запросами к `orders`/`transactions` напрямую (как это и так уже делают старые отчёты), либо строить настоящий read-path, если нужна именно предрасчитанная агрегация под нагрузку. |

Для каждой из этих таблиц нужен отдельный технический migration-скрипт (Phase 2) — здесь дан только концептуальный mapping, не DDL.

## 6. Mapping статусов заказа

| Старый статус | Новый статус | Когда происходит переход |
|---|---|---|
| `waiting` (нужно одобрение KJ) | `pending` | создание заказа, ждёт действия KJ |
| `pending` (уже одобрен, просто в списке) | `pending` (то же) | новая система не разделяет «ждёт одобрения» и «одобрен, ждёт очереди» — в KJ Pro это один экран Orders, оба старых статуса сливаются в один новый |
| (новое, нет аналога) | `processing` | атомарный переходный статус во время drag-в-Queue, защита от Double Queue Add (§57), уже реализовано в `backend/services/vdj_service.py::confirm_order` через CAS |
| (новое, нет аналога) | `queued` | успешно добавлен в очередь VirtualDJ (после `get_browsed_filepath`+`automix_add_next`) |
| `playing` (в оригинале никогда не устанавливался — мёртвый статус) | `playing` | теперь реально используется — либо KJ Pro получает событие от VirtualDJ (History/queue-position), либо ручной fallback KJ (§14) |
| `completed` | `completed` | по VirtualDJ History (§37) или ручному fallback; именно на этом переходе — списание VIP (§12), не раньше |
| `cancelled`, `deleted` (обе — до фактического проигрывания) | `rejected` | по новой модели charge-at-completion, до completion денег не было — значит и возврата не нужно (упрощение по сравнению со старым `refund_vip_for_order`); полностью удаляется из основной системы (§45), не остаётся в истории гостя |
| (новое) | `error` | сбой при обращении к VirtualDJ (файл не найден — НЕ ведёт в `error`, см. §32: остаётся в `pending`/Orders; `error` — скорее для реальных сбоев соединения/протокола) |

Важно: `error` в новом ТЗ — не то же самое, что «файл не найден». §32 прямо говорит: отсутствие файла не должно отклонять заказ, заказ просто остаётся в Orders. Значит `error`-статус нужен для другого класса сбоев (сетевой обрыв с мостом, VDJScript вернул неожиданный ответ), а не для «песни нет в библиотеке» — это тонкое различие, которое легко перепутать при реализации.

## 7. Список API endpoints (по неймспейсам из §62 нового ТЗ)

```
/api/auth        POST /login, POST /refresh, POST /logout
/api/admin       /clubs (CRUD), /kj (CRUD), /reports/{today|week|month|venues|cashback}, /system/status
/api/guest       /login (по ссылке/токену, аналог текущего deep-link), /profile, /favorites, /orders (create/list/replace), /vip/topup, /vip/request, /table/close-request
/api/kj          /me, /clubs/{id}/settings, /services (CRUD), /clients (search/list/block/vip), /vip (add/edit/approve/reject)
/api/orders      GET /orders?club_id=&status=, PATCH /orders/{id} (assign table/guest_type, KJ-правки), DELETE /orders/{id} (reject)
/api/queue       GET /queue?club_id=, POST /queue/reorder (drag&drop payload: order_id, new_position), DELETE /queue/{item_id}
/api/tables      /tables, /tables/{n}/join-request, /tables/{n}/close (KJ), /tables/{n}/admin
/api/services    CRUD (уже есть в KJ-разделе выше — дублируется по смыслу, оставить один канонический путь)
/api/vip         /balance, /transactions, /cashback-settings
/api/chat        GET /chat/{thread_id}, POST /chat/{thread_id}/message, WS-канал для realtime
/api/stats       /stats/{club_id}?period=
/api/virtualdj   internal-only (§61: не должен быть открыт для произвольного внешнего доступа) — /virtualdj/status, /virtualdj/command (используется только мостом vdj_bridge, уже защищено bridge_token — см. backend/sockets.py)
```
Существующие эндпоинты Backend (`backend/routes/client.py`, `kj.py`, `vdj.py`) частично уже покрывают `/api/kj`, `/api/orders`, `/api/queue`, `/api/virtualdj` — при реализации нужно свести их под эту неймспейс-схему, не плодить дублирующих путей (прямое требование §62).

## 8. Список WebSocket событий

Уже реализованные в `backend/sockets.py`: `order_created`, `order_updated`, `order_confirmed`, `order_rejected`, `queue_updated`, `song_started`, `song_finished`.

Новые, требуемые §56/§50 нового ТЗ и ещё не реализованные: `order_processing` (для UI-обратной связи атомарного лока), `order_completed_with_charge` (или расширить `order_updated` полем charge-info), `chat_message`, `table_close_requested`, `table_closed`, `vip_topup_approved`, `vip_request_approved`, `vdj_connection_status` (§39 — 🟢/🔴 индикатор), `queue_reordered` (отдельно от `queue_updated`, если drag&drop должен давать более лёгкий diff, а не полный снимок очереди — решить при реализации).

## 9. VirtualDJ integration points (по результатам исследования официальной документации)

Подтверждено официальными источниками VirtualDJ:
- **Network Control Plugin** — HTTP, настраиваемый порт, опциональный bearer-token, эндпоинты `/query?script=...` и `/execute?script=...`.
- `search "Artist Title"` — реальный VDJScript-глагол, ставит фокус/фильтрует браузер по тексту.
- `get_browsed_filepath` — реальный, возвращает путь к выделенной в браузере записи.
- `automix_add_next "<filepath>"` — подтверждено форумным примером с прямым путём к файлу как аргументом (не только «выделенное в браузере»).
- `get_automix_song`, `get_automix_position`, `get_loaded_song`, `file_count` — для чтения состояния очереди/текущей песни.

Не подтверждено / требует стенда:
- `karaoke_add` (упомянут в §31 нового ТЗ) — у VirtualDJ есть отдельная панель Karaoke SideView (ротация певцов), но единственный задокументированный глагол для неё — `karaoke_show` (вкл/выкл отображения). Возможно, добавление туда программно не поддерживается вообще (по мануалу — только drag&drop), и реальный путь — через обычный `automix_add_next`/`playlist_add`, а Karaoke SideView — это просто способ ОТОБРАЖЕНИЯ той же очереди с именами певцов, не отдельная очередь. Нужно проверить на реальной установке VirtualDJ с включенным Karaoke-режимом.
- Удаление конкретного элемента очереди по идентификатору — документированные глаголы (`browser_remove`, `playlist_clear`, `playlist_remove_played`) работают с «выделенным»/«всем»/«уже сыгранным», не с произвольным ID. Нужно проверять, можно ли сначала программно выделить нужный элемент по позиции (`get_automix_position`, `browser_move` и т.п.), прежде чем удалять.
- Структурированное получение ВСЕЙ очереди целиком одним вызовом (не по одному свойству) — не найдено в документации.
- Путь к VirtualDJ History (§37) указан в ТЗ как `C:\Users\Voice\Documents\VirtualDJ\History` — это путь конкретного компьютера конкретного KJ, в коде должен быть настраиваемым параметром на клуб/агент, не константой.

План закрытия этих пробелов: тестовый стенд с реальным VirtualDJ + Network Control Plugin (Phase 6 по плану миграции), пробные вызовы `/query`/`execute` вручную (curl/Postman) до того, как это зашивается в `vdj_bridge/driver.py`.

## 10. Конфликты старой логики и нового ТЗ

| Конфликт | Разрешение |
|---|---|
| Старое: charge при создании заказа. Новое: charge при completion. | Прямое указание нового ТЗ (§12) — новое побеждает, это не потеря функциональности, а явно предписанное изменение. |
| Старый баг: `replace_svc_execute` не списывал/не возвращал деньги при замене услуги. | Снимается архитектурой — списания при замене больше не существует как отдельного шага. |
| Старый баг: блокировка KJ через `BlockedUserMiddleware` не действовала (роли ADMIN/KJ исключены из проверки). | Новый Backend обязан (§54) проверять `blocked` для всех ролей без исключения — явно чинить, не переносить старое поведение. |
| Старый баг: большинство денежных операций в `kj.py` не проверяли роль внутри обработчика (только видимостью кнопки). | §54/§61 нового ТЗ требуют server-side проверки на каждый запрос — это не опция, а обязательное требование новой архитектуры. |
| Старая механика возврата (`refund_vip_for_order`) при отмене/удалении заказа. | Не переносится как отдельный денежный поток — при charge-at-completion до завершения денег не было, значит и возвращать нечего (§45, §48 подтверждают: rejected — без финансовой операции). |
| `daily_stats` — write-only в оригинале. | Не переносить таблицу как есть; статистику (§58) считать напрямую, либо строить новый, реально читаемый агрегат. |
| Три версии `search_songs` в оригинале. | Переносить логику только последней (активной) версии. |
| Правило ранга при замене песни (`get_order_global_rank`, rank 1-2 запрещено) | Подтверждено реальным кодом — переносится как есть (§7 нового ТЗ это же и требует). |
| Мёртвые ветки (`AddOrderForm.song_search`, `order_replace_execute`/`replace_song_`) | Не переносить вообще — источник для миграции есть в рабочих (не мёртвых) путях тех же функций. |

## 11. Список функций, которые нельзя потерять

Полный список — раздел 5 нового ТЗ (пользователи/VIP/баланс/cashback/услуги/столы/группы/join-request/заказы/избранное/замена/очередь/next/чаты/статистика/отчёты/закрытие стола/уведомления/ограничения/настройки клуба/музыкальная база/режимы/free evening/управление клиентами/блокировка/виртуальные столы/no-table) — совпадает с тем, что уже подтверждено рабочим в `ANALIZ_ORIGINALA_GLUBOKIY.md`. Отдельно подчёркиваю: правило ранга при замене (п.10 выше) и лимит `MAX_ACTIVE_SONGS_PER_USER` — оба легко упустить, так как они «спрятаны» внутри обработчиков, а не являются отдельными видимыми экранами.

## 12. План миграции по фазам

- **Phase 1 (этот документ + `ANALIZ_ORIGINALA_GLUBOKIY.md`)** — аудит, готово.
- **Phase 2** — Backend + PostgreSQL: расширить уже существующий `backend/` (модели, статусы, idempotency-ключи для транзакций, роли/club isolation на каждый эндпоинт).
- **Phase 3** — Admin App (с нуля, веб).
- **Phase 4** — Guest App (с нуля, веб; заменяет Telegram-часть для ролей 3/4/5).
- **Phase 5** — KJ Pro (переработка существующего `kj-panel/` под Queue+Orders drag&drop workspace).
- **Phase 6** — VirtualDJ integration: тестовый стенд, подтверждение/опровержение `karaoke_add` и механики удаления по ID, History-парсинг.
- **Phase 7** — Migration: перенос данных SQLite→Postgres по mapping из раздела 5, с сохранением `karaoke.db` нетронутым до полного acceptance test.
- **Phase 8** — End-to-end testing по сценариям §72 (Client/VIP/No-table/KJ/VirtualDJ/Missing file/Table close).

Каждая фаза — отдельная точка проверки с тобой перед переходом к следующей, как и раньше.
