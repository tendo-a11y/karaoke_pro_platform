import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ApiError, api, getMockGoogleCredential, loadStoredSession, storeSession } from "./api";
import "./App.css";

const STATUS_LABELS = {
  pending: "⏳ Ожидает подтверждения KJ",
  processing: "⚙️ Обрабатывается",
  queued: "🎶 В очереди",
  playing: "▶️ Играет",
  completed: "✅ Спето",
  rejected: "❌ Отклонено",
  error: "⚠️ Ошибка, обратитесь к KJ",
};

// Опрос вместо WebSocket — сознательное ограничение первого шага: у
// Backend пока нет WebSocket-подключения для Guest App (см.
// backend/sockets.py::handle_connect — принимает только KJ JWT, и
// комментарий у emit_chat_message о том, что гость видит сообщения через
// поллинг). Как только появится guest-подключение к сокету — эти интервалы
// заменяются на socket-события, сам API (api.js) не изменится.
const POLL_ORDERS_MS = 4000;
const POLL_QUEUE_MS = 5000;
const POLL_CHAT_MS = 4000;
const POLL_ME_MS = 5000;
const POLL_FAVORITES_MS = 5000;
const POLL_TABLE_GROUP_MS = 5000;
const POLL_VIP_TRANSACTIONS_MS = 8000;

// Пикер периода для "Моих заказов" — старое: handlers/vip.py
// ::vip_order_history (days_map = {"today":1,"week":7,"month":30}, только
// VIP). Здесь тот же набор периодов, но доступно всем ролям.
const ORDER_HISTORY_PERIODS = [
  { label: "Сегодня", days: 1 },
  { label: "Неделя", days: 7 },
  { label: "Месяц", days: 30 },
  { label: "Все", days: null },
];

// Иконка+знак по типу операции для единой ленты "Финансы" — старое:
// handlers/vip.py::vip_finances показывал 4 отдельные Telegram-секции по
// типу с промежуточными итогами; здесь одна хронологическая лента (см.
// отчёт по Finance/cashback history), но подпись по типу сохраняем.
const TX_TYPE_META = {
  topup: { icon: "➕", label: "Начисление", sign: "+" },
  manual_debit: { icon: "➖", label: "Списание KJ", sign: "−" },
  order_payment: { icon: "🎵", label: "Оплата заказа", sign: "−" },
  cashback: { icon: "🎁", label: "Кэшбэк", sign: "+" },
  order_refund: { icon: "↩️", label: "Возврат", sign: "+" },
};

// ТЗ п.45 (финальная единая модель входа): QR-код больше никогда не
// приносит номер стола — сессия всегда создаётся без стола, независимо
// от того, что зашито в самой ссылке. Отсюда убран разбор table_no/table
// из URL (старая ветка "стол уже известен из QR" полностью убрана).
function parseLinkParams() {
  const url = new URL(window.location.href);
  const clubIdRaw = url.searchParams.get("club_id") ?? url.searchParams.get("club");
  const clubId = clubIdRaw != null ? Number(clubIdRaw) : null;
  return { clubId: Number.isFinite(clubId) ? clubId : null };
}

function OrderRow({
  order, onFavorite, favoriteBusy,
  token, services, isReplacing, onToggleReplace, onReplace, replaceBusy,
}) {
  const label = STATUS_LABELS[order.status] || order.status;
  return (
    <li className={`order-row status-${order.status}`}>
      <div className="order-row__song">🎵 {order.song_title}</div>
      {order.artist && <div className="order-row__artist">🎤 {order.artist}</div>}
      <div className="order-row__status">{label}</div>
      {order.error_message && <div className="order-row__error">{order.error_message}</div>}
      <div className="order-row__actions">
        {onFavorite && (
          <button
            type="button"
            className="link-btn"
            disabled={favoriteBusy}
            onClick={() => onFavorite(order)}
          >
            ➕ В избранное
          </button>
        )}
        {/* order.can_replace вычисляется на бэкенде по утверждённой матрице
        замены песни (см. vdj_service.can_replace_order) — фронтенд не
        дублирует эту логику, только показывает/прячет кнопку по флагу. */}
        {order.can_replace && (
          <button type="button" className="link-btn" onClick={() => onToggleReplace(order.id)}>
            {isReplacing ? "Свернуть" : "🔁 Заменить песню"}
          </button>
        )}
      </div>
      {isReplacing && (
        <ReplaceForm
          order={order}
          token={token}
          services={services}
          busy={replaceBusy}
          onSubmit={onReplace}
          onCancel={() => onToggleReplace(order.id)}
        />
      )}
    </li>
  );
}

// VIP-панель (Role 3, аудит п.8-9-10-11): "стать VIP" — это заявка,
// которую одобряет KJ, ставя статус на постоянный профиль гостя (ТЗ
// п.45). Старый одноразовый access_code/redeem для входа под VIP на
// другом устройстве удалён целиком вместе с самим механизмом — постоянство
// личности теперь целиком держится на Google (см. GuestAccount), новый
// вход под тем же Google-аккаунтом сам восстанавливает VIP-статус, никакой
// код для этого предъявлять не нужно.
function VipPanel({ token, meInfo }) {
  const [requesting, setRequesting] = useState(false);
  const [requestSent, setRequestSent] = useState(false);
  const [error, setError] = useState(null);

  async function handleRequestVip() {
    setRequesting(true);
    setError(null);
    try {
      await api.requestVip(token);
      setRequestSent(true);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setRequesting(false);
    }
  }

  if (meInfo.is_vip) {
    return (
      <section className="panel vip-panel vip-panel--active">
        <h2>⭐ VIP-профиль</h2>
        <div className="vip-stat-row">
          <span>Баланс</span>
          <strong>{meInfo.vip.balance.toFixed(2)}</strong>
        </div>
        <div className="vip-stat-row">
          <span>Кэшбэк</span>
          <strong>{meInfo.vip.cashback_percent}%</strong>
        </div>
      </section>
    );
  }

  return (
    <section className="panel vip-panel">
      <h2>⭐ VIP-статус</h2>
      {error && <div className="banner banner--error">{error}</div>}
      {meInfo.vip_request_pending || requestSent ? (
        <p className="empty-hint">Заявка отправлена — ждите решения ведущего.</p>
      ) : (
        <button type="button" onClick={handleRequestVip} disabled={requesting}>
          {requesting ? "Отправляем…" : "🎟 Стать VIP"}
        </button>
      )}
    </section>
  );
}

// Финансы/история транзакций (Role 3, старое: handlers/vip.py::vip_finances
// — там 4 отдельные секции по типу с промежуточными итогами каждая, здесь
// по принятому решению единая хронологическая лента, см. отчёт по
// Finance/cashback history). Показываем только VIP-гостям — у обычных
// гостей эта лента всегда пуста (транзакции существуют только у VIP).
function VipHistoryPanel({ token }) {
  const [transactions, setTransactions] = useState([]);
  const [error, setError] = useState(null);
  const [loaded, setLoaded] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const data = await api.listVipTransactions(token);
      setTransactions(data);
      setError(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setLoaded(true);
    }
  }, [token]);

  // Поллинг, а не разовая загрузка — баланс/история меняются асинхронно
  // (ручная корректировка KJ, завершение песни с кэшбэком), у Guest App
  // нет WebSocket-подключения (см. комментарий у POLL_*_MS выше). Тот же
  // принятый oxlint "set-state-in-effect" случай, что и в остальных
  // поллинг-панелях этого файла.
  useEffect(() => {
    refresh();
    const id = setInterval(refresh, POLL_VIP_TRANSACTIONS_MS);
    return () => clearInterval(id);
  }, [refresh]);

  if (!loaded) return null;

  return (
    <section className="panel vip-history-panel">
      <h2>🧾 Финансы</h2>
      {error && <div className="banner banner--error">{error}</div>}
      {transactions.length === 0 ? (
        <p className="empty-hint">Пока нет операций по счёту.</p>
      ) : (
        <ul className="order-list">
          {transactions.map((tx) => {
            const meta = TX_TYPE_META[tx.type] || { icon: "•", label: tx.type, sign: "" };
            return (
              <li key={tx.id} className="order-row vip-tx-row">
                <div className="vip-tx-row__main">
                  <span>{meta.icon} {meta.label}</span>
                  <strong className={meta.sign === "+" ? "vip-tx-amount--credit" : "vip-tx-amount--debit"}>
                    {meta.sign}{tx.amount.toFixed(2)}
                  </strong>
                </div>
                {tx.description && <div className="order-row__artist">{tx.description}</div>}
                <div className="order-row__status">{new Date(tx.created_at).toLocaleString()}</div>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}

function FavoritesPanel({ token, onOrdered, orderingDisabled }) {
  const [favorites, setFavorites] = useState([]);
  const [error, setError] = useState(null);
  const [busyId, setBusyId] = useState(null);

  const refresh = useCallback(async () => {
    try {
      const data = await api.listFavorites(token);
      setFavorites(data);
    } catch {
      // Список избранного не критичен для основного потока заказа.
    }
  }, [token]);

  // Опрос, а не разовая загрузка: добавление в избранное происходит из
  // OrderRow в родительском App (кнопка "В избранное" под заказом), у
  // которого нет прямой ссылки на состояние этой панели — без периодического
  // опроса свежедобавленная песня не появилась бы в списке до перезагрузки
  // страницы. Тот же принятый oxlint "set-state-in-effect" случай, что и в
  // ChatPanel/опросе заказов/очереди/профиля выше (нет WebSocket у Guest App).
  useEffect(() => {
    refresh();
    const id = setInterval(refresh, POLL_FAVORITES_MS);
    return () => clearInterval(id);
  }, [refresh]);

  async function handleReorder(favoriteId) {
    setBusyId(favoriteId);
    setError(null);
    try {
      await api.reorderFavorite(token, favoriteId);
      await onOrdered();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setBusyId(null);
    }
  }

  async function handleDelete(favoriteId) {
    setBusyId(favoriteId);
    try {
      await api.deleteFavorite(token, favoriteId);
      await refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setBusyId(null);
    }
  }

  return (
    <section className="panel">
      <h2>☆ Избранное</h2>
      {error && <div className="banner banner--error">{error}</div>}
      {favorites.length === 0 ? (
        <p className="empty-hint">Пока пусто — добавляйте песни из "Моих заказов".</p>
      ) : (
        <ul className="order-list">
          {favorites.map((f) => (
            <li key={f.id} className="order-row">
              <div className="order-row__song">🎵 {f.song_title}</div>
              {f.artist && <div className="order-row__artist">🎤 {f.artist}</div>}
              <div className="favorite-actions">
                <button
                  type="button"
                  disabled={busyId === f.id || orderingDisabled}
                  onClick={() => handleReorder(f.id)}
                  title={orderingDisabled ? "Недоступно, пока вы не одобренный участник группового стола" : undefined}
                >
                  🔁 Заказать снова
                </button>
                <button
                  type="button"
                  className="link-btn"
                  disabled={busyId === f.id}
                  onClick={() => handleDelete(f.id)}
                >
                  🗑 Удалить
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

// Поиск по каталогу клуба (Role 3/4/5, аудит п.1). Каталог заполняется
// только через CSV-импорт KJ (POST /api/kj/songs/import) — как и в старом
// боте, синхронизации с VirtualDJ нет. Выбор результата не создаёт заказ
// сам по себе (в отличие от старого инлайн-поиска Telegram, где выбор
// вставлял текст в чат) — здесь это просто заполняет форму заказа ниже,
// потому что в Guest App нет аналога "отправить сообщение в чат боту": сам
// алгоритм поиска (подстрока/сортировка/лимит 50) перенесён 1:1, а способ
// передать выбор в форму — необходимая адаptация под веб-UI, не новая
// бизнес-логика поиска.
//
// РЕШЕНИЕ ПОЛЬЗОВАТЕЛЯ (2026-09): этот компонент больше НЕ показывается
// гостю нигде в интерфейсе — практика показала, что каталог клуба обычно
// пуст (пока KJ не загрузит CSV), из-за чего гость видит только "ничего не
// найдено" и путает это с поломкой. Убрано намеренно только само поле у
// гостя — сама возможность (поиск по каталогу, импорт CSV у KJ) оставлена
// в коде на будущее, ничего не удалялось из backend. Компонент оставлен
// неиспользуемым сознательно (см. предупреждение линтера "не используется"
// — это ожидаемо), а не забыт.
const SEARCH_DEBOUNCE_MS = 300;

function SongSearch({ token, onPick }) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState([]);
  const [searching, setSearching] = useState(false);

  // oxlint "set-state-in-effect" — принятый случай, как и у остальных
  // опросов выше: этот эффект синхронизирует результаты поиска с внешней
  // системой (backend), реагируя на изменение query, а не на прямое
  // событие ввода (нужен debounce через setTimeout, не в обработчике).
  useEffect(() => {
    const q = query.trim();
    if (!q) {
      setResults([]);
      setSearching(false);
      return undefined;
    }
    setSearching(true);
    let cancelled = false;
    const id = setTimeout(async () => {
      try {
        const data = await api.searchSongs(token, q);
        if (!cancelled) setResults(data);
      } catch {
        if (!cancelled) setResults([]);
      } finally {
        if (!cancelled) setSearching(false);
      }
    }, SEARCH_DEBOUNCE_MS);
    return () => {
      cancelled = true;
      clearTimeout(id);
    };
  }, [query, token]);

  return (
    <div className="song-search">
      <input
        type="text"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        placeholder="🔍 Поиск по каталогу клуба"
      />
      {searching && <p className="empty-hint">Ищем…</p>}
      {!searching && query.trim() && results.length === 0 && (
        <p className="empty-hint">Ничего не найдено в каталоге клуба.</p>
      )}
      {results.length > 0 && (
        <ul className="song-search__results">
          {results.map((s) => (
            <li key={s.id}>
              <button
                type="button"
                className="link-btn"
                onClick={() => {
                  onPick(s);
                  setQuery("");
                  setResults([]);
                }}
              >
                🎵 {s.artist ? `${s.artist} — ${s.title}` : s.title}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

// AI-поиск по свободному описанию (Role 3/4/5, аудит п.2). Старое: команда
// /ai — гость явно отправляет описание, а не ищет "на лету" по мере ввода
// (в отличие от поиска по каталогу выше) — это внешние платные API
// (Claude + Genius), а не локальная БД, поэтому здесь сознательно оставлен
// явный сабмит, а не debounce-автопоиск: это сохраняет старую UX-модель
// команды, а не изобретает новую.
function AiSearch({ token, onPick }) {
  const [text, setText] = useState("");
  const [results, setResults] = useState([]);
  const [searching, setSearching] = useState(false);
  const [searched, setSearched] = useState(false);
  const [error, setError] = useState(null);

  async function handleSearch(event) {
    event.preventDefault();
    if (!text.trim()) return;
    setSearching(true);
    setError(null);
    setSearched(false);
    try {
      const data = await api.aiSearchSongs(token, text.trim());
      setResults(data);
      setSearched(true);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setSearching(false);
    }
  }

  return (
    <div className="ai-search">
      <form className="order-form" onSubmit={handleSearch}>
        <input
          type="text"
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="🤖 Опишите песню своими словами"
          maxLength={300}
        />
        <button type="submit" disabled={searching || !text.trim()}>
          {searching ? "Ищем…" : "Найти с помощью AI"}
        </button>
      </form>
      {error && <div className="banner banner--error">{error}</div>}
      {searched && !searching && results.length === 0 && (
        <p className="empty-hint">Ничего не нашлось по описанию — попробуйте обычный поиск выше.</p>
      )}
      {results.length > 0 && (
        <ul className="song-search__results">
          {results.map((s, idx) => (
            <li key={idx}>
              <button
                type="button"
                className="link-btn"
                onClick={() => {
                  onPick(s);
                  setText("");
                  setResults([]);
                  setSearched(false);
                }}
              >
                🎵 {s.artist ? `${s.artist} — ${s.title}` : s.title}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

// Форма замены песни в уже существующем заказе (согласованная и утверждённая
// пользователем спецификация замены песни). Переиспользует SongSearch/
// AiSearch — тот же способ выбрать песню, что и в основной форме заказа
// выше, без дублирования логики поиска. Разрешённость самой замены (кнопка
// "Заменить песню" в OrderRow) решается на бэкенде по order.can_replace —
// эта форма ничего не решает сама, только собирает новые song_title/artist/
// service_id и вызывает POST /api/guest/order/<id>/replace.
function ReplaceForm({ order, token, services, busy, onSubmit, onCancel }) {
  const [songTitle, setSongTitle] = useState(order.song_title);
  const [artist, setArtist] = useState(order.artist || "");
  const [serviceId, setServiceId] = useState(order.service_id ? String(order.service_id) : "");
  const [error, setError] = useState(null);

  async function handleSubmit(event) {
    event.preventDefault();
    if (!songTitle.trim()) return;
    setError(null);
    try {
      await onSubmit(order.id, songTitle.trim(), artist.trim() || null, serviceId ? Number(serviceId) : null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    }
  }

  return (
    <div className="replace-form">
      <AiSearch
        token={token}
        onPick={(song) => {
          setSongTitle(song.title);
          setArtist(song.artist || "");
        }}
      />
      <form className="order-form" onSubmit={handleSubmit}>
        <input
          type="text"
          value={songTitle}
          onChange={(e) => setSongTitle(e.target.value)}
          placeholder="Название песни"
          maxLength={200}
          required
        />
        <input
          type="text"
          value={artist}
          onChange={(e) => setArtist(e.target.value)}
          placeholder="Исполнитель (необязательно)"
          maxLength={200}
        />
        {services.length > 0 && (
          <select value={serviceId} onChange={(e) => setServiceId(e.target.value)}>
            <option value="">Без тарифа</option>
            {services.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name}{s.is_free ? " (бесплатно)" : ` — ${s.price}`}
              </option>
            ))}
          </select>
        )}
        <div className="replace-form__buttons">
          <button type="submit" disabled={busy || !songTitle.trim()}>
            {busy ? "Сохраняем…" : "✅ Сохранить замену"}
          </button>
          <button type="button" className="link-btn" onClick={onCancel} disabled={busy}>
            Отмена
          </button>
        </div>
      </form>
      {error && <div className="banner banner--error">{error}</div>}
    </div>
  );
}

// Групповой стол (Role 3/4/5) — утверждённая пользователем спецификация,
// вариант А: полноценный шлюз (backend/services/table_group_service.py).
// Компонент сам опрашивает своё состояние (тот же паттерн, что и
// FavoritesPanel/ChatPanel выше — нет WebSocket у Guest App), а не получает
// его через props — это позволяет ему обновляться независимо от остальной
// страницы, но onGroupChanged даёт родителю знать, когда стоит немедленно
// перечитать /me (одобрили/выгнали/приняты права), не дожидаясь общего опроса.
function TableGroupPanel({ token, guestId, hasTable, status, onGroupChanged }) {
  const [view, setView] = useState(null);
  const [error, setError] = useState(null);
  const [busyKey, setBusyKey] = useState(null);
  const [requestingJoin, setRequestingJoin] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const data = await api.getTableGroup(token);
      setView(data);
    } catch {
      // Временный сбой опроса группы — не критично, следующий тик подтянет.
    }
  }, [token]);

  // oxlint "set-state-in-effect" — тот же принятый случай опроса внешнего
  // состояния, что и у остальных польщиков в этом файле (нет WebSocket).
  useEffect(() => {
    if (!hasTable) return undefined;
    refresh();
    const id = setInterval(refresh, POLL_TABLE_GROUP_MS);
    return () => clearInterval(id);
  }, [hasTable, refresh]);

  async function runAction(key, action) {
    setBusyKey(key);
    setError(null);
    try {
      await action();
      await refresh();
      await onGroupChanged();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setBusyKey(null);
    }
  }

  async function handleRequestJoin() {
    setRequestingJoin(true);
    setError(null);
    try {
      await api.requestTableGroupJoin(token);
      await refresh();
      await onGroupChanged();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setRequestingJoin(false);
    }
  }

  if (!hasTable) return null;

  // status приходит из /api/guest/me (см. routes/guest.py::me) — источник
  // истины для "могу ли я сейчас заказывать", а не наличие/отсутствие
  // group.id здесь: группа продолжает существовать даже когда ЭТОТ гость
  // из неё вышел/кикнут — get_table_group у неё же и спрашиваем, поэтому
  // ветвим именно по status, а не по view.group.
  const isMember = status === "admin" || status === "member";

  return (
    <section className="panel table-group-panel">
      <h2>👥 Групповой стол</h2>
      {error && <div className="banner banner--error">{error}</div>}

      {status === "pending" && (
        <p className="empty-hint">⏳ Заявка отправлена — ждите одобрения админа стола.</p>
      )}
      {status === "not_joined" && (
        <>
          <p className="empty-hint">Вы не состоите в группе этого стола.</p>
          <button type="button" onClick={handleRequestJoin} disabled={requestingJoin}>
            {requestingJoin ? "Отправляем…" : "🙋 Запросить присоединение"}
          </button>
        </>
      )}

      {!view ? (
        <p className="empty-hint">Загрузка…</p>
      ) : (
        <>
          {view.members.length > 0 && (
            <ul className="order-list table-group-members">
              {view.members.map((m) => (
                <li key={m.guest_id} className="order-row table-group-member">
                  <span>
                    {m.is_admin ? "👑 " : "🙂 "}
                    {m.guest_id === guestId ? "Вы" : `Гость ${m.guest_id}`}
                  </span>
                  {view.is_admin && !m.is_admin && (
                    <div className="favorite-actions">
                      <button
                        type="button"
                        className="link-btn"
                        disabled={busyKey === `kick-${m.guest_id}`}
                        onClick={() => runAction(`kick-${m.guest_id}`, () => api.kickTableGroupMember(token, m.guest_id))}
                      >
                        🚪 Выгнать
                      </button>
                      <button
                        type="button"
                        className="link-btn"
                        disabled={busyKey === `transfer-${m.guest_id}`}
                        onClick={() => runAction(`transfer-${m.guest_id}`, () => api.transferTableGroupAdmin(token, m.guest_id))}
                      >
                        👑 Передать права
                      </button>
                    </div>
                  )}
                </li>
              ))}
            </ul>
          )}

          {view.is_admin && view.pending_requests.length > 0 && (
            <div className="table-group-requests">
              <h3>Заявки на присоединение</h3>
              <ul className="order-list">
                {view.pending_requests.map((r) => (
                  <li key={r.id} className="order-row table-group-member">
                    <span>Гость {r.guest_id}</span>
                    <div className="favorite-actions">
                      <button
                        type="button"
                        disabled={busyKey === `approve-${r.id}`}
                        onClick={() => runAction(`approve-${r.id}`, () => api.approveJoinRequest(token, r.id))}
                      >
                        ✅ Принять
                      </button>
                      <button
                        type="button"
                        className="link-btn"
                        disabled={busyKey === `reject-${r.id}`}
                        onClick={() => runAction(`reject-${r.id}`, () => api.rejectJoinRequest(token, r.id))}
                      >
                        ❌ Отклонить
                      </button>
                    </div>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {isMember && (
            <button
              type="button"
              className="link-btn"
              disabled={busyKey === "leave"}
              onClick={() => runAction("leave", () => api.leaveTableGroup(token))}
            >
              🚪 Покинуть стол
            </button>
          )}
        </>
      )}
    </section>
  );
}

function ChatPanel({ token }) {
  const [messages, setMessages] = useState([]);
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState(null);
  const listEndRef = useRef(null);

  const refresh = useCallback(async () => {
    try {
      const data = await api.listChat(token);
      setMessages(data);
    } catch {
      // Молча пропускаем один неудачный опрос чата — не хотим перекрывать
      // основной интерфейс заказа баннером ошибки из-за временного сбоя сети.
    }
  }, [token]);

  // oxlint предупреждает "set-state-in-effect" здесь — это ожидаемо и
  // осознанно: это опрос чата (нет WebSocket для Guest App, см. комментарий
  // у POLL_*_MS выше в этом файле), а не побочный эффект от рендера,
  // который надо было бы вычислить иначе.
  useEffect(() => {
    refresh();
    const id = setInterval(refresh, POLL_CHAT_MS);
    return () => clearInterval(id);
  }, [refresh]);

  useEffect(() => {
    listEndRef.current?.scrollIntoView({ block: "nearest" });
  }, [messages.length]);

  async function handleSend(event) {
    event.preventDefault();
    const text = draft.trim();
    if (!text) return;
    setSending(true);
    setError(null);
    try {
      await api.sendChatMessage(token, text);
      setDraft("");
      await refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setSending(false);
    }
  }

  return (
    <section className="panel chat-panel">
      <h2>💬 Чат с ведущим</h2>
      <ul className="chat-list">
        {messages.length === 0 && <li className="empty-hint">Сообщений пока нет.</li>}
        {messages.map((m) => (
          <li key={m.id} className={`chat-message ${m.from_guest ? "chat-message--mine" : "chat-message--kj"}`}>
            <span className="chat-message__author">{m.from_guest ? "Вы" : "KJ"}</span>
            <span className="chat-message__text">{m.message_text}</span>
          </li>
        ))}
        <li ref={listEndRef} />
      </ul>
      {error && <div className="banner banner--error">{error}</div>}
      <form className="chat-form" onSubmit={handleSend}>
        <input
          type="text"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder="Написать ведущему…"
          maxLength={500}
        />
        <button type="submit" disabled={sending || !draft.trim()}>
          Отправить
        </button>
      </form>
    </section>
  );
}

// ТЗ п.45 (финальная единая модель входа) — единственный способ стать
// Role 4: гость вводит номер своего стола и подтверждает личность через
// Google одним действием (см. api.linkGoogle). До этого он мог только
// смотреть очередь и заполнить форму заказа (Role 5) — именно попытка
// нажать "Заказать" открывает этот экран (см. App::handleSubmitOrder), а
// не отдельная навигация. Google в этом экране — не настоящая кнопка
// Google Identity Services: пока нет боевого Client ID (см. docstring
// backend/services/google_auth_service.py), фронтенд сам формирует
// подтверждение в фоне (getMockGoogleCredential) — гость ничего для этого
// не вводит и не видит, только номер стола.
function ActivationPanel({ token, onActivated, onCancel }) {
  const [tableNo, setTableNo] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const parsedTableNo = Number(tableNo);
  const tableNoValid = tableNo.trim() !== "" && Number.isInteger(parsedTableNo) && parsedTableNo > 0;

  async function handleActivate(event) {
    event.preventDefault();
    if (!tableNoValid) return;
    setBusy(true);
    setError(null);
    try {
      const credential = getMockGoogleCredential();
      const result = await api.linkGoogle(token, parsedTableNo, credential);
      await onActivated(result);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="panel activation-panel">
      <h2>Выберите стол и войдите через Google</h2>
      <p className="empty-hint">
        Укажите номер своего стола и войдите через Google одним действием — это нужно один раз,
        дальше ваш стол, история заказов и избранное сохранятся.
      </p>
      {error && <div className="banner banner--error">{error}</div>}
      <form className="order-form" onSubmit={handleActivate}>
        <input
          type="number"
          min="1"
          value={tableNo}
          onChange={(e) => setTableNo(e.target.value)}
          placeholder="Номер стола"
          required
        />
        <button type="submit" disabled={busy || !tableNoValid}>
          {busy ? "Входим…" : "Войти через Google"}
        </button>
        <button type="button" className="link-btn" onClick={onCancel} disabled={busy}>
          Отмена
        </button>
      </form>
    </section>
  );
}

export default function App() {
  const { clubId } = useMemo(() => parseLinkParams(), []);

  const [session, setSession] = useState(null);
  const [meInfo, setMeInfo] = useState(null);
  // !clubId — не результат асинхронной операции, а сразу известное по URL
  // состояние, поэтому это часть рендера, а не setState в эффекте.
  const linkInvalid = !clubId;
  const [initError, setInitError] = useState(null);

  const [songTitle, setSongTitle] = useState("");
  const [artist, setArtist] = useState("");
  const [serviceId, setServiceId] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState(null);
  const [submitOk, setSubmitOk] = useState(false);

  const [orders, setOrders] = useState([]);
  // null = "Все", иначе количество дней (см. ORDER_HISTORY_PERIODS ниже) —
  // старое: handlers/vip.py::vip_order_history, только для VIP; здесь
  // доступно всем ролям (аудит по "Фильтрация истории заказов").
  const [orderHistoryDays, setOrderHistoryDays] = useState(null);
  const [queue, setQueue] = useState([]);
  const [services, setServices] = useState([]);
  const [favoriteBusyOrderId, setFavoriteBusyOrderId] = useState(null);
  const [favoriteMessage, setFavoriteMessage] = useState(null);
  const [replacingOrderId, setReplacingOrderId] = useState(null);
  const [replaceBusyOrderId, setReplaceBusyOrderId] = useState(null);
  // ТЗ п.45 (финальная единая модель входа) — показывает ли экран "стол +
  // Google" прямо сейчас; открывается попыткой заказать, будучи Role 5
  // (см. handleSubmitOrder), закрывается после успешной активации (см.
  // handleActivated) или если гость сам передумал.
  const [showActivation, setShowActivation] = useState(false);

  // Шаг 1: получить/создать гостевую сессию для этого клуба (ТЗ: аналог
  // старого deep-link venue{id}_table{n} — сама возможность открыть
  // ссылку с club_id и есть право заказывать за этим столом, см.
  // backend/routes/guest.py::create_session).
  //
  // bootstrapPromiseRef — React 18 StrictMode в dev-режиме намеренно
  // монтирует этот эффект дважды подряд (mount -> cleanup -> mount), чтобы
  // ловить именно такой класс багов. Раньше повторный POST
  // /api/guest/session был безобиден — оба вызова создавали одинаково
  // валидную независимую гостевую сессию, лишняя просто не использовалась.
  // С групповым столом (утверждённая спецификация) это уже НЕ безобидно:
  // два реальных запроса для одного и того же стола — это два разных
  // guest_id, и только один может стать админом, второй попадёт в pending
  // — а применённым в состоянии React мог оказаться именно "проигравший".
  // Найдено живым Playwright-тестом на реальном Vite dev server (там
  // StrictMode активен). Фикс — расшарить сам промис между обоими вызовами
  // эффекта через ref: реальный сетевой запрос уходит только один раз, а
  // применяет результат тот вызов эффекта, который не будет отменён
  // (в паре StrictMode это второй — его cleanup сработает только при
  // настоящем размонтировании).
  const bootstrapPromiseRef = useRef(null);
  useEffect(() => {
    if (linkInvalid) return undefined;

    let cancelled = false;

    async function loadOrCreateSession() {
      const stored = loadStoredSession(clubId);
      if (stored?.token) {
        try {
          const me = await api.me(stored.token);
          return { session: stored, meInfo: me };
        } catch {
          // Токен истёк/невалиден — создаём новую сессию ниже, как будто
          // гость открыл ссылку впервые.
        }
      }
      const created = await api.createSession(clubId);
      storeSession(clubId, created);
      const me = await api.me(created.token);
      return { session: created, meInfo: me };
    }

    async function bootstrap() {
      if (!bootstrapPromiseRef.current) {
        bootstrapPromiseRef.current = loadOrCreateSession();
      }
      try {
        const result = await bootstrapPromiseRef.current;
        if (cancelled) return;
        setSession(result.session);
        setMeInfo(result.meInfo);
      } catch (err) {
        if (!cancelled) {
          setInitError(err instanceof ApiError ? err.message : String(err));
        }
      }
    }

    bootstrap();
    return () => {
      cancelled = true;
    };
  }, [clubId, linkInvalid]);

  const refreshOrders = useCallback(async () => {
    if (!session) return;
    try {
      const data = await api.listMyOrders(session.token, orderHistoryDays);
      setOrders(data);
    } catch {
      // Временный сбой поллинга — не блокируем форму заказа баннером.
    }
  }, [session, orderHistoryDays]);

  const refreshQueue = useCallback(async () => {
    if (!session) return;
    try {
      const data = await api.getQueue(session.token);
      setQueue(data);
    } catch {
      // Живая очередь — не критично, если один опрос не удался.
    }
  }, [session]);

  // Баланс/кэшбэк VIP меняются на бэкенде асинхронно — в момент
  // charge_at_completion(), т.е. когда песня реально доиграна в VirtualDJ,
  // а не по действию самого гостя в этой вкладке. Без отдельного опроса
  // meInfo обновлялся бы только один раз при входе и оставался бы
  // "замороженным" на старом балансе до перезагрузки страницы — гость не
  // увидел бы списание/кэшбэк за уже спетую песню. Найдено и исправлено
  // по итогам live-теста (см. финальный отчёт, п. VIP balance).
  const refreshMe = useCallback(async () => {
    if (!session) return;
    try {
      const data = await api.me(session.token);
      setMeInfo(data);
    } catch {
      // Временный сбой опроса баланса — не критично, следующий тик подтянет.
    }
  }, [session]);

  // oxlint: "set-state-in-effect" ожидаемо и здесь, и в следующих эффектах —
  // то же самое опросное обновление внешнего состояния (заказов/очереди/
  // профиля), что и в ChatPanel выше, по той же причине (нет WebSocket у
  // Guest App).
  useEffect(() => {
    if (!session) return undefined;
    refreshOrders();
    const id = setInterval(refreshOrders, POLL_ORDERS_MS);
    return () => clearInterval(id);
  }, [session, refreshOrders]);

  useEffect(() => {
    if (!session) return undefined;
    refreshQueue();
    const id = setInterval(refreshQueue, POLL_QUEUE_MS);
    return () => clearInterval(id);
  }, [session, refreshQueue]);

  useEffect(() => {
    if (!session) return undefined;
    const id = setInterval(refreshMe, POLL_ME_MS);
    return () => clearInterval(id);
  }, [session, refreshMe]);

  // Тарифы клуба — статичны на время сессии, опрос не нужен, достаточно
  // загрузить один раз после готовности сессии (аудит Role 3/4/5, п.12).
  useEffect(() => {
    if (!session) return;
    api.listServices(session.token).then(setServices).catch(() => {});
  }, [session]);

  // Вынесено из handleSubmitOrder, чтобы этим же кодом мог воспользоваться
  // handleActivated выше — после единственного экрана "стол + Google"
  // нужно закончить то же самое действие уже настоящим (новым) токеном, а
  // не токеном, который был в session на момент нажатия "Заказать".
  async function submitOrderWithToken(token) {
    setSubmitting(true);
    setSubmitError(null);
    setSubmitOk(false);
    try {
      await api.createOrder(
        token, songTitle.trim(), artist.trim() || null,
        serviceId ? Number(serviceId) : null,
      );
      setSongTitle("");
      setArtist("");
      setServiceId("");
      setSubmitOk(true);
      await refreshOrders();
    } catch (err) {
      setSubmitError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setSubmitting(false);
    }
  }

  async function handleSubmitOrder(event) {
    event.preventDefault();
    if (!session || !songTitle.trim()) return;

    // ТЗ п.45 (финальная единая модель входа): до выбора стола и входа
    // через Google заказ фактически не отправляется — вместо запроса
    // открывается единственный экран активации (см. ActivationPanel и
    // handleActivated выше), который сам довершит именно это действие.
    if (!activated) {
      setSubmitError(null);
      setShowActivation(true);
      return;
    }

    await submitOrderWithToken(session.token);
  }

  async function handleAddFavorite(order) {
    setFavoriteBusyOrderId(order.id);
    setFavoriteMessage(null);
    try {
      await api.addFavorite(session.token, order.song_title, order.artist, order.service_id);
      setFavoriteMessage("Добавлено в избранное");
    } catch (err) {
      setFavoriteMessage(err instanceof ApiError ? err.message : String(err));
    } finally {
      setFavoriteBusyOrderId(null);
    }
  }

  function handleToggleReplace(orderId) {
    setReplacingOrderId((prev) => (prev === orderId ? null : orderId));
  }

  // Ошибка (например, гонка: заказ как раз перешёл в processing/rank 1-2
  // между опросом списка и нажатием "Сохранить") намеренно НЕ перехватывается
  // здесь — она пробрасывается наверх, в ReplaceForm.handleSubmit, чтобы
  // показаться прямо рядом с формой замены, а не общим баннером страницы.
  async function handleReplaceOrder(orderId, songTitle, artist, serviceId) {
    setReplaceBusyOrderId(orderId);
    try {
      await api.replaceOrder(session.token, orderId, songTitle, artist, serviceId);
      setReplacingOrderId(null);
      await refreshOrders();
    } finally {
      setReplaceBusyOrderId(null);
    }
  }

  // ТЗ п.45 (финальная единая модель входа): вызывается один раз, сразу
  // после успешного "стол + Google" в ActivationPanel — единственного
  // способа стать Role 4. Не переиспользуем refreshOrders/refreshMe-
  // замыкания старой сессии — редкий случай "уже входил с другого
  // устройства" меняет guest_id, поэтому запросы явно делаются с НОВЫМ
  // токеном, а не через стейт предыдущего рендера (существующие данные
  // гостя — избранное/заказы — при этом никуда не деваются, см. отчёт по
  // п.45: они уже записаны на постоянный номер).
  async function handleActivated(result) {
    const activatedSession = { guest_id: result.guest_id, club_id: result.club_id, table_no: result.table_no, token: result.token };
    storeSession(clubId, activatedSession);
    setSession(activatedSession);
    setShowActivation(false);
    try {
      const me = await api.me(result.token);
      setMeInfo(me);
    } catch {
      // следующий опрос подтянет актуальное состояние
    }
    // Гость уже нажимал «Заказать» до того, как открылся этот экран
    // (иначе он бы не открылся, см. handleSubmitOrder) — значит форма
    // заказа уже заполнена, и после активации нужно сразу закончить то же
    // самое действие, а не заставлять нажимать «Заказать» второй раз.
    if (songTitle.trim()) {
      await submitOrderWithToken(result.token);
    } else {
      await refreshOrders();
    }
  }

  if (linkInvalid) {
    return (
      <div className="app-shell centered">
        <h1>🎤 Karaoke</h1>
        <p className="error-text">
          Ссылка недействительна — не указан клуб. Отсканируйте QR-код на столе ещё раз.
        </p>
      </div>
    );
  }

  if (initError) {
    return (
      <div className="app-shell centered">
        <h1>🎤 Karaoke</h1>
        <p className="error-text">{initError}</p>
      </div>
    );
  }

  if (!session || !meInfo) {
    return (
      <div className="app-shell centered">
        <p>Загрузка…</p>
      </div>
    );
  }

  // ТЗ п.45 (финальная единая модель входа): гость может заказать только
  // пройдя единственный экран "стол + Google" — до этого он Role 5
  // (смотрит очередь, выбирает песню в форму, но не заказывает). Источник
  // истины — те же две проверки, что и на бэкенде в create_order
  // (TABLE_REQUIRED, затем GOOGLE_LINK_REQUIRED); это чисто UI-отражение,
  // а не отдельное правило.
  const activated = meInfo.table_no != null && meInfo.has_permanent_profile;

  // Групповой стол (утверждённая спецификация, вариант А — полноценный
  // шлюз): без стола эта механика не действует вообще; со столом —
  // заказывать можно, только пока сервер считает гостя admin/member
  // (табличная проверка в create_order — источник истины, это чисто
  // UI-отражение того же самого условия, а не отдельное правило).
  const hasTable = meInfo.table_no != null;
  const groupOk = !hasTable || meInfo.table_group_status === "admin" || meInfo.table_group_status === "member";
  const canOrder = activated && groupOk;

  return (
    <div className="app-shell">
      <header className="app-header">
        <h1>🎤 {meInfo.club_name || "Karaoke"}</h1>
        <span className="app-header__table">
          {meInfo.table_no != null ? `Стол ${meInfo.table_no}` : "Без стола"}
        </span>
      </header>

      <VipPanel token={session.token} meInfo={meInfo} />

      {meInfo.is_vip && <VipHistoryPanel token={session.token} />}

      <TableGroupPanel
        token={session.token}
        guestId={session.guest_id}
        hasTable={hasTable}
        status={meInfo.table_group_status}
        onGroupChanged={refreshMe}
      />

      <section className="panel order-form-panel">
        <h2>Заказать песню</h2>
        {/* ТЗ п.45 (финальная единая модель входа): очередь и выбор песни
        доступны всегда, даже до активации (Role 5) — форма ниже видна
        независимо от activated. Единственное, что остаётся закрытым уже
        ПОСЛЕ активации — членство в групповом столе (groupOk), это другая,
        не связанная с Google проверка. */}
        {activated && !groupOk ? (
          <p className="empty-hint">
            Пока вы не одобренный участник группового стола — см. панель «Групповой стол» выше.
          </p>
        ) : (
          <>
            <AiSearch
              token={session.token}
              onPick={(song) => {
                setSongTitle(song.title);
                setArtist(song.artist || "");
              }}
            />
            <form className="order-form" onSubmit={handleSubmitOrder}>
              <input
                type="text"
                value={songTitle}
                onChange={(e) => setSongTitle(e.target.value)}
                placeholder="Название песни"
                maxLength={200}
                required
              />
              <input
                type="text"
                value={artist}
                onChange={(e) => setArtist(e.target.value)}
                placeholder="Исполнитель (необязательно)"
                maxLength={200}
              />
              {services.length > 0 && (
                <select value={serviceId} onChange={(e) => setServiceId(e.target.value)}>
                  <option value="">Без тарифа</option>
                  {services.map((s) => (
                    <option key={s.id} value={s.id}>
                      {s.name}{s.is_free ? " (бесплатно)" : ` — ${s.price}`}
                    </option>
                  ))}
                </select>
              )}
              <button type="submit" disabled={submitting || !songTitle.trim()}>
                {submitting ? "Отправляем…" : "🎶 Заказать"}
              </button>
            </form>
            {submitError && <div className="banner banner--error">{submitError}</div>}
            {submitOk && <div className="banner banner--ok">Заказ отправлен! Ждите подтверждения KJ.</div>}
            {/* ТЗ п.45: единственный способ стать Role 4 — эта попытка
            заказать (будучи ещё Role 5) и открывает данный экран, см.
            handleSubmitOrder/handleActivated выше. */}
            {showActivation && (
              <ActivationPanel
                token={session.token}
                onActivated={handleActivated}
                onCancel={() => setShowActivation(false)}
              />
            )}
          </>
        )}
      </section>

      <section className="panel">
        <h2>Мои заказы</h2>
        <div className="order-history-periods">
          {ORDER_HISTORY_PERIODS.map((p) => (
            <button
              key={p.label}
              type="button"
              className={`link-btn${orderHistoryDays === p.days ? " order-history-periods__active" : ""}`}
              onClick={() => setOrderHistoryDays(p.days)}
            >
              {p.label}
            </button>
          ))}
        </div>
        {favoriteMessage && <div className="banner banner--ok">{favoriteMessage}</div>}
        {orders.length === 0 ? (
          <p className="empty-hint">
            {orderHistoryDays === null ? "Заказов пока нет." : "Заказов за этот период нет."}
          </p>
        ) : (
          <ul className="order-list">
            {orders.map((o) => (
              <OrderRow
                key={o.id}
                order={o}
                onFavorite={handleAddFavorite}
                favoriteBusy={favoriteBusyOrderId === o.id}
                token={session.token}
                services={services}
                isReplacing={replacingOrderId === o.id}
                onToggleReplace={handleToggleReplace}
                onReplace={handleReplaceOrder}
                replaceBusy={replaceBusyOrderId === o.id}
              />
            ))}
          </ul>
        )}
      </section>

      <FavoritesPanel token={session.token} onOrdered={refreshOrders} orderingDisabled={!canOrder} />

      <section className="panel">
        <h2>Живая очередь</h2>
        {queue.length === 0 ? (
          <p className="empty-hint">Очередь пуста.</p>
        ) : (
          <ol className="queue-list">
            {queue.map((item) => (
              <li key={item.vdj_item_id}>
                🎵 {item.song_title}
                {item.artist ? ` — ${item.artist}` : ""}
              </li>
            ))}
          </ol>
        )}
      </section>

      {meInfo.chat_enabled && <ChatPanel token={session.token} />}
    </div>
  );
}
