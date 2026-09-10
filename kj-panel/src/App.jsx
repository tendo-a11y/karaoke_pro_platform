import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, ApiError, resolveToken } from "./api";
import { connectSocket } from "./socket";
import "./App.css";

// Фоновый опрос живой очереди VirtualDJ — та же идея, что и POLL_QUEUE_MS в
// Guest App (guest-app/src/App.jsx): WebSocket ("queue_updated") ловит
// изменения, сделанные ЧЕРЕЗ наш Backend (confirm_order), но ничего не знает
// о песне, которую KJ добавил или переставил прямо в самом VirtualDJ, минуя
// Guest App — такие изменения увидит только опрос. Согласовано с
// пользователем (план "Шаг 4: добавляем постоянный polling live queue в
// KJ Pro") — без перезагрузки страницы и без действий KJ.
const POLL_QUEUE_MS = 2500;

const STATUS_LABELS = {
  pending: "⏳ Ожидает",
  processing: "⚙️ Обрабатывается",
  queued: "🎶 В очереди VDJ",
  playing: "▶️ Играет",
  completed: "✅ Завершено",
  rejected: "❌ Отклонено",
  error: "⚠️ Ошибка VDJ",
};

function formatOrderTime(isoString) {
  if (!isoString) return "";
  const date = new Date(isoString);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

// Drag-and-drop вместо кнопки "Подтвердить" — новое мастер-ТЗ требует
// управлять очередью перетаскиванием, без confirm-кнопок (карточка
// заказа перетаскивается в панель "Очередь VirtualDJ", это и есть
// подтверждение — вызывает тот же PUT /api/kj/order/<id>/confirm, что
// раньше вызывала кнопка). "Отклонить" остаётся кнопкой: это решение по
// приёму заказа, а не операция над очередью, ТЗ её не запрещает.
//
// Реализовано на нативном HTML5 Drag and Drop API, без новой зависимости
// — сознательное ограничение первого шага: нативный DnD не работает на
// touch-устройствах (нет тач-событий), только мышью на десктопе. Если KJ
// Pro должен открываться с планшета/телефона, здесь потребуется
// библиотека с pointer-событиями (например dnd-kit) — отдельный шаг.
function OrderCard({ order, busy, dragging, onReject, onDragStart, onDragEnd }) {
  const tableLabel = order.table_no == null ? "Без стола" : `Стол ${order.table_no}`;
  const draggable = order.status === "pending" && !busy;
  return (
    <div
      className={`order-card status-${order.status}${dragging ? " order-card--dragging" : ""}`}
      draggable={draggable}
      onDragStart={draggable ? (e) => onDragStart(e, order.id) : undefined}
      onDragEnd={draggable ? onDragEnd : undefined}
    >
      <div className="order-card__table">{tableLabel}</div>
      <div className="order-card__song">🎵 {order.song_title}</div>
      {order.artist && <div className="order-card__artist">🎤 {order.artist}</div>}
      <div className="order-card__meta">
        <span className="order-card__user">👤 Гость #{order.telegram_user_id}</span>
        <span className="order-card__time">🕒 {formatOrderTime(order.created_at)}</span>
      </div>
      <div className="order-card__status">{STATUS_LABELS[order.status] || order.status}</div>
      {order.error_message && <div className="order-card__error">{order.error_message}</div>}
      {draggable && <div className="order-card__drag-hint">⠿ Перетащите в очередь, чтобы подтвердить</div>}
      {order.status === "pending" && (
        <div className="order-card__actions">
          <button className="btn btn--reject" disabled={busy} onClick={() => onReject(order.id)}>
            ОТКЛОНИТЬ
          </button>
        </div>
      )}
    </div>
  );
}

// Отличаем два разных случая пустой колонки "Стол" (согласовано с
// пользователем, минимальный вариант без выдумывания нового поведения):
// order_id есть, а table_no пуст -> легитимный заказ гостя без стола
// ("Без стола"); order_id вообще нет -> позиция в очереди VirtualDJ не
// соответствует ни одному известному заказу (KJ добавил/переставил песню
// прямо в VirtualDJ) -> "без заказа". Новый заказ в базе для такой песни
// автоматически НЕ создаётся.
function tableCellLabel(item) {
  if (item.order_id == null) return "без заказа";
  return item.table_no == null ? "Без стола" : item.table_no;
}

function QueueTable({ queue, dropActive, onDragOver, onDragLeave, onDrop }) {
  return (
    <div
      className={`queue-dropzone${dropActive ? " queue-dropzone--active" : ""}`}
      onDragOver={onDragOver}
      onDragLeave={onDragLeave}
      onDrop={onDrop}
    >
      {queue.length === 0 ? (
        <p className="empty-hint">Очередь VirtualDJ пуста. Перетащите сюда карточку заказа.</p>
      ) : (
        <table className="queue-table">
          <thead>
            <tr>
              <th>№</th>
              <th>Песня</th>
              <th>Исполнитель</th>
              <th>Стол</th>
            </tr>
          </thead>
          <tbody>
            {queue.map((item, idx) => (
              <tr key={item.vdj_item_id ?? `no-id-${idx}`}>
                <td>{idx + 1}</td>
                <td>{item.song_title}</td>
                <td>{item.artist || "—"}</td>
                <td>{tableCellLabel(item)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

// KJ Pro, экран "Добавить песню" — KJ сам находит песню и указывает стол,
// минуя гостя и экран "Заказы" целиком (полное обоснование решений — см.
// add_manual_song() в backend/services/vdj_service.py). Сейчас это просто
// поля названия/исполнителя, введённые вручную, той же цепочкой, что уже
// сегодня добавляет песню по гостевому заказу (поиск в файлах VirtualDJ ->
// добавление). Список из нескольких найденных вариантов на выбор — то, о
// чём просил пользователь — здесь сознательно НЕ сделан: сначала нужно
// вживую проверить, умеет ли VirtualDJ вообще отдавать больше одного
// найденного файла за раз (открытый вопрос, ещё не проверен).
function AddManualSongForm({ onSubmit, busy, error }) {
  const [songTitle, setSongTitle] = useState("");
  const [artist, setArtist] = useState("");
  const [tableNo, setTableNo] = useState("");

  async function handleSubmit(event) {
    event.preventDefault();
    const parsedTable = Number(tableNo);
    if (!songTitle.trim() || !Number.isFinite(parsedTable) || parsedTable <= 0) return;

    const ok = await onSubmit({ songTitle: songTitle.trim(), artist: artist.trim(), tableNo: parsedTable });
    if (ok) {
      setSongTitle("");
      setArtist("");
      setTableNo("");
    }
  }

  return (
    <form className="manual-add-form" onSubmit={handleSubmit}>
      <input
        type="text"
        placeholder="Название песни"
        value={songTitle}
        onChange={(e) => setSongTitle(e.target.value)}
        disabled={busy}
      />
      <input
        type="text"
        placeholder="Исполнитель (необязательно)"
        value={artist}
        onChange={(e) => setArtist(e.target.value)}
        disabled={busy}
      />
      <input
        type="number"
        min="1"
        placeholder="Стол"
        value={tableNo}
        onChange={(e) => setTableNo(e.target.value)}
        disabled={busy}
        className="manual-add-form__table"
      />
      <button
        type="submit"
        className="btn btn--accent"
        disabled={busy || !songTitle.trim() || !tableNo}
      >
        {busy ? "Добавляем…" : "➕ Добавить в очередь"}
      </button>
      {error && <div className="banner banner--error">{error}</div>}
    </form>
  );
}

// Block D KJ Pro — заявки на VIP-статус (аудит handlers/kj.py:1291-1401,
// vip_request_approve/reject) + список VIP-клиентов с ручными операциями
// над балансом/кэшбэком (kj.py:2133-2229). ТЗ п.45 (финальная единая
// модель входа): ручное назначение VIP "из ничего" без заявки гостя, и
// одноразовый access_code, который оно выдавало, — удалены целиком вместе
// со всем механизмом access_code/redeem (см. отчёт по п.45 и routes/kj.py
// ::list_vip_clients). VIP теперь появляется только через заявку гостя,
// уже подтвердившего личность через Google, + одобрение здесь.
function VipPanel({ token, clubId, socket }) {
  const [pending, setPending] = useState(null);
  const [clients, setClients] = useState(null);
  const [loadError, setLoadError] = useState(null);
  const [actionError, setActionError] = useState(null);
  const [busyKey, setBusyKey] = useState(null);
  const [amountDrafts, setAmountDrafts] = useState({});
  const [cashbackDrafts, setCashbackDrafts] = useState({});

  async function reload() {
    try {
      const [pendingData, clientsData] = await Promise.all([
        api.listVipRequests(token, clubId, "pending"),
        api.listVipClients(token, clubId),
      ]);
      setPending(pendingData);
      setClients(clientsData);
      setLoadError(null);
    } catch (err) {
      setLoadError(err instanceof ApiError ? err.message : String(err));
    }
  }

  useEffect(() => {
    reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [clubId]);

  useEffect(() => {
    if (!socket) return undefined;
    const onCreated = (vipRequest) => {
      setPending((prev) => {
        const list = prev || [];
        return list.some((r) => r.id === vipRequest.id) ? list : [...list, vipRequest];
      });
    };
    socket.on("vip_request_created", onCreated);
    return () => {
      socket.off("vip_request_created", onCreated);
    };
  }, [socket]);

  async function handleApprove(requestId) {
    setBusyKey(`req-${requestId}`);
    setActionError(null);
    try {
      await api.approveVipRequest(token, requestId);
      await reload();
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setBusyKey(null);
    }
  }

  async function handleReject(requestId) {
    setBusyKey(`req-${requestId}`);
    setActionError(null);
    try {
      await api.rejectVipRequest(token, requestId);
      await reload();
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setBusyKey(null);
    }
  }

  async function handleTopup(vipClientId) {
    const amount = Number(amountDrafts[vipClientId]);
    if (!amount || amount <= 0) return;
    setBusyKey(`amt-${vipClientId}`);
    setActionError(null);
    try {
      await api.topupVipBalance(token, vipClientId, amount);
      await reload();
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setBusyKey(null);
    }
  }

  async function handleDebit(vipClientId) {
    const amount = Number(amountDrafts[vipClientId]);
    if (!amount || amount <= 0) return;
    setBusyKey(`amt-${vipClientId}`);
    setActionError(null);
    try {
      await api.debitVipBalance(token, vipClientId, amount);
      await reload();
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setBusyKey(null);
    }
  }

  async function handleSetBalance(vipClientId) {
    const amount = Number(amountDrafts[vipClientId]);
    if (!Number.isFinite(amount) || amount < 0) return;
    setBusyKey(`amt-${vipClientId}`);
    setActionError(null);
    try {
      await api.setVipBalance(token, vipClientId, amount);
      await reload();
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setBusyKey(null);
    }
  }

  async function handleUpdateCashback(vipClientId) {
    const value = Number(cashbackDrafts[vipClientId]);
    if (!Number.isFinite(value) || value < 0 || value > 100) return;
    setBusyKey(`cb-${vipClientId}`);
    setActionError(null);
    try {
      await api.updateVipCashback(token, vipClientId, value);
      await reload();
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setBusyKey(null);
    }
  }

  if (loadError) return <div className="banner banner--error">{loadError}</div>;
  if (!pending || !clients) return <p className="empty-hint">Загрузка…</p>;

  return (
    <div className="vip-panel">
      {actionError && <div className="banner banner--error">{actionError}</div>}

      <section>
        <h2>Заявки на VIP ({pending.length})</h2>
        {pending.length === 0 && <p className="empty-hint">Новых заявок нет.</p>}
        <ul className="vip-list">
          {pending.map((r) => (
            <li key={r.id} className="vip-row">
              <span>Стол {r.table_no ?? "—"} · гость #{r.telegram_user_id}</span>
              <span className="vip-row__actions">
                <button
                  type="button" className="btn btn--accent" disabled={busyKey === `req-${r.id}`}
                  onClick={() => handleApprove(r.id)}
                >
                  Одобрить
                </button>
                <button
                  type="button" className="btn btn--reject" disabled={busyKey === `req-${r.id}`}
                  onClick={() => handleReject(r.id)}
                >
                  Отклонить
                </button>
              </span>
            </li>
          ))}
        </ul>
      </section>

      <section>
        <h2>VIP-клиенты ({clients.length})</h2>
        {clients.length === 0 && <p className="empty-hint">VIP-клиентов пока нет.</p>}
        <ul className="vip-list">
          {clients.map((c) => (
            <li key={c.id} className="vip-row vip-row--client">
              <div>
                Гость #{c.telegram_user_id} · баланс <strong>{c.balance} MDL</strong>
              </div>
              <div className="vip-row__actions">
                <input
                  className="vip-amount-input"
                  type="number"
                  placeholder="Сумма"
                  value={amountDrafts[c.id] ?? ""}
                  onChange={(e) => setAmountDrafts((prev) => ({ ...prev, [c.id]: e.target.value }))}
                />
                <button type="button" className="btn-link" disabled={busyKey === `amt-${c.id}`} onClick={() => handleTopup(c.id)}>
                  ➕ Начислить
                </button>
                <button type="button" className="btn-link" disabled={busyKey === `amt-${c.id}`} onClick={() => handleDebit(c.id)}>
                  ➖ Списать
                </button>
                <button type="button" className="btn-link" disabled={busyKey === `amt-${c.id}`} onClick={() => handleSetBalance(c.id)}>
                  🔄 Установить
                </button>
              </div>
              <div className="vip-row__actions">
                <input
                  className="vip-amount-input"
                  type="number"
                  placeholder="Кэшбэк %"
                  value={cashbackDrafts[c.id] ?? c.cashback_percent}
                  onChange={(e) => setCashbackDrafts((prev) => ({ ...prev, [c.id]: e.target.value }))}
                />
                <button type="button" className="btn-link" disabled={busyKey === `cb-${c.id}`} onClick={() => handleUpdateCashback(c.id)}>
                  Сохранить кэшбэк
                </button>
              </div>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}

export default function App() {
  const token = useMemo(() => resolveToken(), []);
  const [me, setMe] = useState(null);
  const [orders, setOrders] = useState([]);
  const [queue, setQueue] = useState([]);
  const [loadError, setLoadError] = useState(null);
  const [actionError, setActionError] = useState(null);
  const [busyOrderId, setBusyOrderId] = useState(null);
  const [connected, setConnected] = useState(false);
  const [draggingOrderId, setDraggingOrderId] = useState(null);
  const [dropActive, setDropActive] = useState(false);
  const [manualAddBusy, setManualAddBusy] = useState(false);
  const [manualAddError, setManualAddError] = useState(null);
  // 'orders' | 'vip' — переключение верхнеуровневых экранов (Block D KJ Pro).
  const [view, setView] = useState("orders");
  // Реф нужен эффекту ниже (disconnect в cleanup без пересоздания подписок),
  // а socketInstance в state — чтобы VipPanel мог реагировать на появление
  // сокета как на обычный проп (читать socketRef.current прямо в JSX во
  // время рендера запрещено правилами React — оно не гарантирует ре-рендер).
  const socketRef = useRef(null);
  const [socketInstance, setSocketInstance] = useState(null);

  useEffect(() => {
    if (!token) return;

    let cancelled = false;

    async function bootstrap() {
      try {
        const meData = await api.me(token);
        if (cancelled) return;
        setMe(meData);

        const [ordersData, queueData] = await Promise.all([
          api.listOrders(token, meData.club_id, "pending"),
          api.getQueue(token, meData.club_id),
        ]);
        if (cancelled) return;
        setOrders(ordersData);
        setQueue(queueData);
      } catch (err) {
        if (!cancelled) setLoadError(err instanceof ApiError ? err.message : String(err));
      }
    }

    bootstrap();

    const socket = connectSocket(token);
    socketRef.current = socket;

    socket.on("connect", () => {
      setConnected(true);
      // Публикуем инстанс в state здесь, а не синхронно в теле эффекта —
      // избегаем каскадного ре-рендера прямо во время монтирования
      // (oxlint react(set-state-in-effect)); VipPanel в любом случае не
      // рендерится раньше первого успешного connect.
      setSocketInstance(socket);
    });
    socket.on("disconnect", () => setConnected(false));

    socket.on("order_created", (order) => {
      setOrders((prev) => (prev.some((o) => o.id === order.id) ? prev : [...prev, order]));
    });

    const upsertOrRemove = (order) => {
      setOrders((prev) => {
        if (order.status !== "pending") {
          return prev.filter((o) => o.id !== order.id);
        }
        return prev.map((o) => (o.id === order.id ? order : o));
      });
    };

    socket.on("order_updated", upsertOrRemove);
    socket.on("order_confirmed", upsertOrRemove);
    socket.on("order_rejected", upsertOrRemove);

    socket.on("queue_updated", (payload) => {
      setQueue(payload.queue || []);
    });

    return () => {
      cancelled = true;
      socket.disconnect();
      setSocketInstance(null);
    };
  }, [token]);

  const refreshQueue = useCallback(async () => {
    if (!me) return;
    try {
      const queueData = await api.getQueue(token, me.club_id);
      setQueue(queueData);
    } catch {
      // Живая очередь — не критично, если один опрос не удался, следующий
      // тик через POLL_QUEUE_MS подтянет актуальное состояние (тот же
      // подход, что и в Guest App).
    }
  }, [token, me]);

  useEffect(() => {
    if (!me) return undefined;
    const id = setInterval(refreshQueue, POLL_QUEUE_MS);
    return () => clearInterval(id);
  }, [me, refreshQueue]);

  async function handleAddManualSong({ songTitle, artist, tableNo }) {
    setManualAddBusy(true);
    setManualAddError(null);
    try {
      // Сокет "queue_updated" (см. emit_queue_updated в add_manual_song(),
      // backend/services/vdj_service.py) обновит очередь сам, почти сразу
      // после ответа сервера — отдельно перерисовывать её здесь не нужно.
      await api.addManualOrder(token, { songTitle, artist, tableNo });
      return true;
    } catch (err) {
      setManualAddError(err instanceof ApiError ? err.message : String(err));
      return false;
    } finally {
      setManualAddBusy(false);
    }
  }

  async function handleConfirm(orderId) {
    setBusyOrderId(orderId);
    setActionError(null);
    try {
      await api.confirmOrder(token, orderId);
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : String(err));
      if (me) {
        const fresh = await api.listOrders(token, me.club_id, "pending");
        setOrders(fresh);
      }
    } finally {
      setBusyOrderId(null);
    }
  }

  async function handleReject(orderId) {
    setBusyOrderId(orderId);
    setActionError(null);
    try {
      await api.rejectOrder(token, orderId);
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : String(err));
      if (me) {
        const fresh = await api.listOrders(token, me.club_id, "pending");
        setOrders(fresh);
      }
    } finally {
      setBusyOrderId(null);
    }
  }

  function handleDragStart(event, orderId) {
    event.dataTransfer.setData("text/plain", String(orderId));
    event.dataTransfer.effectAllowed = "move";
    setDraggingOrderId(orderId);
  }

  function handleDragEnd() {
    setDraggingOrderId(null);
    setDropActive(false);
  }

  function handleQueueDragOver(event) {
    if (draggingOrderId == null) return;
    event.preventDefault();
    event.dataTransfer.dropEffect = "move";
    setDropActive(true);
  }

  function handleQueueDragLeave() {
    setDropActive(false);
  }

  async function handleQueueDrop(event) {
    event.preventDefault();
    setDropActive(false);
    const orderId = Number(event.dataTransfer.getData("text/plain"));
    setDraggingOrderId(null);
    if (!Number.isFinite(orderId)) return;
    await handleConfirm(orderId);
  }

  if (!token) {
    return (
      <div className="app-shell centered">
        <h1>KJ Panel</h1>
        <p>Ссылка без токена доступа. Откройте панель по ссылке, которую выдаёт бот команде /kj.</p>
      </div>
    );
  }

  if (loadError) {
    return (
      <div className="app-shell centered">
        <h1>KJ Panel</h1>
        <p className="error-text">{loadError}</p>
      </div>
    );
  }

  if (!me) {
    return (
      <div className="app-shell centered">
        <p>Загрузка…</p>
      </div>
    );
  }

  return (
    <div className="app-shell">
      <header className="app-header">
        <div>
          <h1>{me.club_name || `Клуб #${me.club_id}`}</h1>
          <span className="app-header__subtitle">{me.display_name || "KJ"}</span>
        </div>
        <span className={`conn-badge ${connected ? "conn-badge--ok" : "conn-badge--off"}`}>
          {connected ? "● online" : "○ переподключение…"}
        </span>
        <button type="button" className="btn-link" onClick={() => setView(view === "orders" ? "vip" : "orders")}>
          {view === "orders" ? "⭐ VIP" : "← Заказы"}
        </button>
      </header>

      {actionError && <div className="banner banner--error">{actionError}</div>}

      {view === "vip" ? (
        <VipPanel token={token} clubId={me.club_id} socket={socketInstance} />
      ) : (
        <main className="app-main">
          <section>
            <h2>Заказы ({orders.length})</h2>
            {orders.length === 0 && <p className="empty-hint">Новых заказов нет.</p>}
            <div className="orders-grid">
              {orders.map((order) => (
                <OrderCard
                  key={order.id}
                  order={order}
                  busy={busyOrderId === order.id}
                  dragging={draggingOrderId === order.id}
                  onReject={handleReject}
                  onDragStart={handleDragStart}
                  onDragEnd={handleDragEnd}
                />
              ))}
            </div>
          </section>

          <section>
            <h2>Добавить песню</h2>
            <AddManualSongForm
              onSubmit={handleAddManualSong}
              busy={manualAddBusy}
              error={manualAddError}
            />
          </section>

          <section>
            <h2>Живая очередь VirtualDJ</h2>
            <QueueTable
              queue={queue}
              dropActive={dropActive}
              onDragOver={handleQueueDragOver}
              onDragLeave={handleQueueDragLeave}
              onDrop={handleQueueDrop}
            />
          </section>
        </main>
      )}
    </div>
  );
}
