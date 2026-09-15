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
// Основные обновления очереди приходят мгновенно через WebSocket-событие
// queue_updated — этот опрос лишь подстраховка на случай пропущенного
// события. При настоящем VirtualDJ (мост через компьютер KJ) слишком частый
// опрос вместе с гостевым приложением перегружает мост и подвешивает всю
// систему (живой инцидент 2026-09-14 после включения VDJ_ADAPTER=bridge) —
// 10с достаточно для подстраховки.
const POLL_QUEUE_MS = 10000;

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

// KJ Pro: смена стола/категории и удаление песни, уже стоящей в очереди
// (запрос пользователя, после того как выяснилось, что перестановку порядка
// в самой очереди VirtualDJ пока не сделать надёжно — см. обсуждение про
// vdj_bridge/driver.py — договорились начать с этих трёх пунктов, порядок
// песен отложен). Категории подтягиваются тем же способом, что и в
// CategoriesPanel (см. её reload()) — свой собственный небольшой список
// внутри компонента, отдельный от него.
function QueueTable({ queue, dropActive, onDragOver, onDragLeave, onDrop, token, clubId }) {
  const [categories, setCategories] = useState([]);
  const [tableDrafts, setTableDrafts] = useState({});
  const [busyKey, setBusyKey] = useState(null);
  const [rowErrors, setRowErrors] = useState({});
  // Черновики "Стол"/"Категория" для позиций БЕЗ заказа (order_id == null —
  // KJ добавил песню прямо в VirtualDJ, минуя Guest App, см. докстринг
  // tableCellLabel выше). Ключ — vdj_item_id, а не order_id, потому что у
  // таких позиций order_id ещё нет вообще (запрос пользователя 2026-09-14,
  // после первого живого теста: 3 песни, добавленные прямо в VirtualDJ,
  // попали в живую очередь KJ Pro, но назначить им стол было нельзя).
  const [claimDrafts, setClaimDrafts] = useState({});

  useEffect(() => {
    let cancelled = false;
    api
      .listCategories(token, clubId)
      .then((data) => {
        if (!cancelled) setCategories(data);
      })
      .catch(() => {
        // Список категорий здесь не критичен — если не загрузился, просто
        // не покажем выпадающий список смены категории в этот раз.
      });
    return () => {
      cancelled = true;
    };
  }, [token, clubId]);

  function draftTableFor(item) {
    return item.order_id in tableDrafts ? tableDrafts[item.order_id] : String(item.table_no ?? "");
  }

  function setRowError(orderId, message) {
    setRowErrors((prev) => ({ ...prev, [orderId]: message }));
  }

  async function handleSaveTable(item) {
    const raw = draftTableFor(item).trim();
    const tableNo = raw === "" ? null : Number(raw);
    if (raw !== "" && (!Number.isInteger(tableNo) || tableNo <= 0)) {
      setRowError(item.order_id, "Стол — положительное число или пусто");
      return;
    }
    setBusyKey(`table-${item.order_id}`);
    setRowError(item.order_id, null);
    try {
      await api.updateOrderTable(token, item.order_id, tableNo);
      setTableDrafts((prev) => {
        const next = { ...prev };
        delete next[item.order_id];
        return next;
      });
    } catch (err) {
      setRowError(item.order_id, err instanceof ApiError ? err.message : String(err));
    } finally {
      setBusyKey(null);
    }
  }

  async function handleChangeCategory(item, rawValue) {
    const serviceId = rawValue === "" ? null : Number(rawValue);
    setBusyKey(`category-${item.order_id}`);
    setRowError(item.order_id, null);
    try {
      await api.updateOrderCategory(token, item.order_id, serviceId);
    } catch (err) {
      setRowError(item.order_id, err instanceof ApiError ? err.message : String(err));
    } finally {
      setBusyKey(null);
    }
  }

  function claimDraftFor(item) {
    // По умолчанию сразу подставляем первую категорию (запрос пользователя
    // 2026-09-14 — "Без категории" убрана из списка совсем, см. select
    // ниже), чтобы то, что видно в форме, совпадало с тем, что реально
    // отправится при нажатии "Присвоить".
    const fallbackServiceId = categories[0] ? String(categories[0].id) : "";
    return claimDrafts[item.vdj_item_id] || { table: "", serviceId: fallbackServiceId };
  }

  function setClaimDraft(item, patch) {
    setClaimDrafts((prev) => ({
      ...prev,
      [item.vdj_item_id]: { ...claimDraftFor(item), ...patch },
    }));
  }

  async function handleClaim(item) {
    const draft = claimDraftFor(item);
    const rawTable = draft.table.trim();
    const tableNo = rawTable === "" ? null : Number(rawTable);
    const errorKey = `claim-${item.vdj_item_id}`;
    if (rawTable !== "" && (!Number.isInteger(tableNo) || tableNo <= 0)) {
      setRowError(errorKey, "Стол — положительное число или пусто");
      return;
    }
    const serviceId = draft.serviceId === "" ? null : Number(draft.serviceId);
    setBusyKey(errorKey);
    setRowError(errorKey, null);
    try {
      await api.claimQueueItem(token, {
        vdjItemId: item.vdj_item_id,
        songTitle: item.song_title,
        artist: item.artist,
        tableNo,
        serviceId,
      });
      setClaimDrafts((prev) => {
        const next = { ...prev };
        delete next[item.vdj_item_id];
        return next;
      });
    } catch (err) {
      setRowError(errorKey, err instanceof ApiError ? err.message : String(err));
    } finally {
      setBusyKey(null);
    }
  }

  async function handleRemove(item) {
    const key = item.vdj_item_id ?? `no-id-${item.order_id}`;
    setBusyKey(`remove-${key}`);
    if (item.order_id != null) setRowError(item.order_id, null);
    try {
      await api.removeFromVdjQueue(token, item.vdj_item_id);
    } catch (err) {
      if (item.order_id != null) setRowError(item.order_id, err instanceof ApiError ? err.message : String(err));
    } finally {
      setBusyKey(null);
    }
  }

  return (
    <div
      className={`queue-dropzone${dropActive ? " queue-dropzone--active" : ""}`}
      onDragOver={onDragOver}
      onDragLeave={onDragLeave}
      onDrop={onDrop}
    >
      {/* Постоянная подсказка — видна всегда, а не только при пустой
          очереди, чтобы было понятно, куда именно тащить карточку заказа
          (пользователь жаловался, что после первой же песни в очереди
          подсказка пропадала). */}
      <p className="queue-dropzone__hint">⬇ Сюда перетаскивайте карточку заказа из списка «Заказы»</p>
      {queue.length === 0 ? (
        <p className="empty-hint">Очередь VirtualDJ пока пуста.</p>
      ) : (
        // Вертикальный список вместо таблицы — тот же стиль строк, что и на
        // экране "Категории" (.categories-list/.category-row), по просьбе
        // пользователя. Порядок песен внутри самой очереди VirtualDJ пока не
        // меняется отсюда — это отдельная задача (KJ-09, отложена).
        <ul className="queue-list-vertical">
          {queue.map((item, idx) => (
            <li
              key={item.vdj_item_id ?? `no-id-${idx}`}
              className={`queue-row${item.orphaned ? " queue-row--orphaned" : ""}`}
            >
              <span className="queue-row__position">{idx + 1}</span>
              <span className="queue-row__song">🎵 {item.song_title}</span>
              <span className="queue-row__artist">{item.artist ? `🎤 ${item.artist}` : "—"}</span>
              {item.orphaned && (
                <span className="queue-row__orphaned-badge" title="Эта песня больше не найдена в самом VirtualDJ — например, из-за перезапуска сервера. Можно только удалить.">
                  ⚠ нет в VDJ
                </span>
              )}
              {item.order_id != null ? (
                <>
                  <span className="queue-row__edit">
                    <input
                      type="number"
                      min="1"
                      className="queue-row__table-input"
                      placeholder="Стол"
                      value={draftTableFor(item)}
                      onChange={(event) =>
                        setTableDrafts((prev) => ({ ...prev, [item.order_id]: event.target.value }))
                      }
                    />
                    <button
                      type="button"
                      className="btn-link"
                      disabled={busyKey === `table-${item.order_id}`}
                      onClick={() => handleSaveTable(item)}
                    >
                      ✓
                    </button>
                  </span>
                  {categories.length > 0 && (
                    // "Без категории" убран из списка (запрос пользователя
                    // 2026-09-14 — категория есть всегда). Если у заказа
                    // категория исторически не назначена (service_id ==
                    // null, заказы до этого изменения), показываем первую
                    // из списка — но это только отображение, само по себе
                    // оно ничего не сохраняет, пока KJ не тронет select.
                    <select
                      className="queue-row__category-select"
                      value={item.service_id ?? categories[0]?.id ?? ""}
                      disabled={busyKey === `category-${item.order_id}`}
                      onChange={(event) => handleChangeCategory(item, event.target.value)}
                    >
                      {categories.map((category) => (
                        <option key={category.id} value={category.id}>
                          {category.name}
                        </option>
                      ))}
                    </select>
                  )}
                </>
              ) : (
                // Позиция реально есть в живой очереди VirtualDJ, но заказа
                // на неё нет (KJ добавил песню прямо в VirtualDJ) — раньше
                // тут был просто текст "без заказа" без возможности что-то
                // назначить (запрос пользователя 2026-09-14 — сделать это
                // возможным, см. claim_vdj_queue_item в vdj_service.py).
                <span className="queue-row__edit">
                  <input
                    type="number"
                    min="1"
                    className="queue-row__table-input"
                    placeholder="Стол"
                    value={claimDraftFor(item).table}
                    onChange={(event) => setClaimDraft(item, { table: event.target.value })}
                  />
                  {categories.length > 0 && (
                    // "Без категории" убран из списка (запрос пользователя
                    // 2026-09-14 — категория есть всегда), см. claimDraftFor
                    // выше про то, чем заполняется значение по умолчанию.
                    <select
                      className="queue-row__category-select"
                      value={claimDraftFor(item).serviceId}
                      onChange={(event) => setClaimDraft(item, { serviceId: event.target.value })}
                    >
                      {categories.map((category) => (
                        <option key={category.id} value={category.id}>
                          {category.name}
                        </option>
                      ))}
                    </select>
                  )}
                  <button
                    type="button"
                    className="btn-link"
                    disabled={busyKey === `claim-${item.vdj_item_id}`}
                    onClick={() => handleClaim(item)}
                  >
                    ✓ Присвоить
                  </button>
                </span>
              )}
              <button
                type="button"
                className="btn-link queue-row__remove"
                disabled={busyKey === `remove-${item.vdj_item_id ?? `no-id-${item.order_id}`}`}
                onClick={() => handleRemove(item)}
              >
                🗑 Удалить
              </button>
              {item.order_id != null && rowErrors[item.order_id] && (
                <p className="error-text queue-row__error">{rowErrors[item.order_id]}</p>
              )}
              {item.order_id == null && rowErrors[`claim-${item.vdj_item_id}`] && (
                <p className="error-text queue-row__error">{rowErrors[`claim-${item.vdj_item_id}`]}</p>
              )}
            </li>
          ))}
        </ul>
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

// Экран категорий песни (доп. ТЗ "KJ Pro", пункты KJ-01/KJ-03/KJ-07) —
// категория это переиспользованная модель Service ("услуга/тариф"), её же
// видит гость при заказе (routes/guest.py::list_services, не менялось);
// здесь роль 2 (KJ) сама ведёт список — добавляет, меняет
// название/описание/цену, включает "бесплатно" для конкретной категории
// (галочка is_free — отдельный переключатель, НЕ совпадает с общим клубным
// "Бесплатным вечером" из KJ-02, тот будет сделан отдельно) и удаляет
// неиспользуемые. Деньги за категорию по факту не проходят через эту
// систему как настоящий платёж (решение пользователя) — цена нужна для
// учёта/отчётности. Если у клуба ещё нет ни одной категории, бэкенд сам
// подставит набор по умолчанию из реальных данных старого бота (см.
// backend/services/category_service.py::DEFAULT_CATEGORIES) — экран не
// должен показывать пустой список при первом открытии.
function CategoriesPanel({ token, clubId }) {
  const [categories, setCategories] = useState(null);
  const [loadError, setLoadError] = useState(null);
  const [actionError, setActionError] = useState(null);
  const [busyKey, setBusyKey] = useState(null);
  const [drafts, setDrafts] = useState({});
  const [newDraft, setNewDraft] = useState({ name: "", description: "", price: "", isFree: false });

  async function reload() {
    try {
      const data = await api.listCategories(token, clubId);
      setCategories(data);
      setDrafts({});
      setLoadError(null);
    } catch (err) {
      setLoadError(err instanceof ApiError ? err.message : String(err));
    }
  }

  useEffect(() => {
    reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [clubId]);

  function draftFor(category) {
    return (
      drafts[category.id] || {
        name: category.name,
        description: category.description || "",
        price: String(category.price),
        isFree: category.is_free,
      }
    );
  }

  function updateDraft(categoryId, category, patch) {
    setDrafts((prev) => {
      const base =
        prev[categoryId] || {
          name: category.name,
          description: category.description || "",
          price: String(category.price),
          isFree: category.is_free,
        };
      return { ...prev, [categoryId]: { ...base, ...patch } };
    });
  }

  async function handleSave(category) {
    const draft = draftFor(category);
    setBusyKey(`save-${category.id}`);
    setActionError(null);
    try {
      await api.updateCategory(token, clubId, category.id, {
        name: draft.name,
        description: draft.description,
        price: draft.price,
        is_free: draft.isFree,
      });
      await reload();
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setBusyKey(null);
    }
  }

  async function handleDelete(categoryId) {
    setBusyKey(`del-${categoryId}`);
    setActionError(null);
    try {
      await api.deleteCategory(token, clubId, categoryId);
      await reload();
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setBusyKey(null);
    }
  }

  async function handleCreate(event) {
    event.preventDefault();
    if (!newDraft.name.trim() || newDraft.price === "") return;
    setBusyKey("create");
    setActionError(null);
    try {
      await api.createCategory(token, clubId, {
        name: newDraft.name.trim(),
        description: newDraft.description.trim(),
        price: newDraft.price,
        isFree: newDraft.isFree,
      });
      setNewDraft({ name: "", description: "", price: "", isFree: false });
      await reload();
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setBusyKey(null);
    }
  }

  // KJ-02 "Бесплатный вечер" — по решению пользователя реализовано здесь же,
  // одной кнопкой поверх уже существующих галочек "бесплатно" у каждой
  // категории (is_free, KJ-07): "Выбрать все" одним действием проставляет
  // (или снимает) is_free сразу всем категориям клуба — так роль 2 включает
  // "весь вечер бесплатно" и выключает обратно, без отдельного клубного
  // переключателя.
  const allFree = categories != null && categories.length > 0 && categories.every((c) => c.is_free);

  async function handleToggleAllFree(checked) {
    setBusyKey("free-evening");
    setActionError(null);
    try {
      await Promise.all(
        categories
          .filter((c) => c.is_free !== checked)
          .map((c) => api.updateCategory(token, clubId, c.id, { is_free: checked }))
      );
      await reload();
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setBusyKey(null);
    }
  }

  if (loadError) return <div className="banner banner--error">{loadError}</div>;
  if (!categories) return <p className="empty-hint">Загрузка…</p>;

  return (
    <div className="categories-panel">
      {actionError && <div className="banner banner--error">{actionError}</div>}

      <section className="free-evening-banner">
        <h2>🎉 Бесплатный вечер</h2>
        <label className="category-row__free">
          <input
            type="checkbox"
            checked={allFree}
            disabled={busyKey === "free-evening"}
            onChange={(e) => handleToggleAllFree(e.target.checked)}
          />
          {busyKey === "free-evening" ? "Применяем…" : "Выбрать все — сделать все категории бесплатными"}
        </label>
      </section>

      <section>
        <h2>Категории песни ({categories.length})</h2>
        <ul className="categories-list">
          {categories.map((category) => {
            const draft = draftFor(category);
            const saving = busyKey === `save-${category.id}`;
            const deleting = busyKey === `del-${category.id}`;
            return (
              <li key={category.id} className="category-row">
                <input
                  className="category-row__name"
                  type="text"
                  value={draft.name}
                  onChange={(e) => updateDraft(category.id, category, { name: e.target.value })}
                  disabled={saving || deleting}
                />
                <input
                  className="category-row__description"
                  type="text"
                  placeholder="Описание"
                  value={draft.description}
                  onChange={(e) => updateDraft(category.id, category, { description: e.target.value })}
                  disabled={saving || deleting}
                />
                <input
                  className="category-row__price"
                  type="number"
                  min="0"
                  value={draft.price}
                  onChange={(e) => updateDraft(category.id, category, { price: e.target.value })}
                  disabled={saving || deleting}
                />
                <label className="category-row__free">
                  <input
                    type="checkbox"
                    checked={draft.isFree}
                    onChange={(e) => updateDraft(category.id, category, { isFree: e.target.checked })}
                    disabled={saving || deleting}
                  />
                  Бесплатно
                </label>
                <div className="category-row__actions">
                  <button
                    type="button" className="btn-link" disabled={saving || deleting}
                    onClick={() => handleSave(category)}
                  >
                    {saving ? "Сохраняем…" : "💾 Сохранить"}
                  </button>
                  <button
                    type="button" className="btn btn--reject" disabled={saving || deleting}
                    onClick={() => handleDelete(category.id)}
                  >
                    {deleting ? "Удаляем…" : "🗑 Удалить"}
                  </button>
                </div>
              </li>
            );
          })}
        </ul>
      </section>

      <section>
        <h2>Добавить категорию</h2>
        <form className="category-add-form" onSubmit={handleCreate}>
          <input
            type="text"
            placeholder="Название"
            value={newDraft.name}
            onChange={(e) => setNewDraft((prev) => ({ ...prev, name: e.target.value }))}
            disabled={busyKey === "create"}
          />
          <input
            type="text"
            placeholder="Описание (необязательно)"
            value={newDraft.description}
            onChange={(e) => setNewDraft((prev) => ({ ...prev, description: e.target.value }))}
            disabled={busyKey === "create"}
          />
          <input
            type="number"
            min="0"
            placeholder="Цена"
            value={newDraft.price}
            onChange={(e) => setNewDraft((prev) => ({ ...prev, price: e.target.value }))}
            disabled={busyKey === "create"}
          />
          <label className="category-row__free">
            <input
              type="checkbox"
              checked={newDraft.isFree}
              onChange={(e) => setNewDraft((prev) => ({ ...prev, isFree: e.target.checked }))}
              disabled={busyKey === "create"}
            />
            Бесплатно
          </label>
          <button
            type="submit" className="btn btn--accent"
            disabled={busyKey === "create" || !newDraft.name.trim() || newDraft.price === ""}
          >
            {busyKey === "create" ? "Добавляем…" : "➕ Добавить категорию"}
          </button>
        </form>
      </section>
    </div>
  );
}

// Настройки столов (доп. ТЗ "KJ Pro", KJ-04) — в старом боте это была
// настройка самого KJ (handlers/kj.py: tables_count_edit/
// tables_settings_save), не админа: у каждого клуба своё количество
// столов. Здесь тот же смысл — одно число, пустое значение (null) означает
// "не ограничено" (пока KJ явно не задал число, как было по умолчанию и в
// старом боте до первой настройки).
function TableSettingsPanel({ token, clubId }) {
  const [draft, setDraft] = useState("");
  const [loadError, setLoadError] = useState(null);
  const [actionError, setActionError] = useState(null);
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState(false);

  async function reload() {
    try {
      const data = await api.getTableSettings(token, clubId);
      setDraft(data.table_count == null ? "" : String(data.table_count));
      setLoadError(null);
    } catch (err) {
      setLoadError(err instanceof ApiError ? err.message : String(err));
    }
  }

  useEffect(() => {
    reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [clubId]);

  async function handleSave(event) {
    event.preventDefault();
    const value = draft.trim() === "" ? null : Number(draft);
    if (value !== null && (!Number.isInteger(value) || value < 1)) return;
    setBusy(true);
    setActionError(null);
    setSaved(false);
    try {
      const data = await api.updateTableSettings(token, clubId, value);
      setDraft(data.table_count == null ? "" : String(data.table_count));
      setSaved(true);
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  if (loadError) return <div className="banner banner--error">{loadError}</div>;

  return (
    <div className="table-settings-panel">
      <section>
        <h2>Настройки столов</h2>
        <p className="empty-hint">
          Сколько столов в клубе. Гость не сможет выбрать номер больше этого при входе, KJ — при ручном
          добавлении песни. Оставьте поле пустым, если ограничивать не нужно.
        </p>
        {actionError && <div className="banner banner--error">{actionError}</div>}
        <form className="table-settings-form" onSubmit={handleSave}>
          <input
            type="number"
            min="1"
            placeholder="Без ограничения"
            value={draft}
            onChange={(e) => {
              setDraft(e.target.value);
              setSaved(false);
            }}
            disabled={busy}
          />
          <button type="submit" className="btn btn--accent" disabled={busy}>
            {busy ? "Сохраняем…" : "Сохранить"}
          </button>
        </form>
        {saved && <p className="empty-hint">Сохранено.</p>}
      </section>
    </div>
  );
}

// Экран "Гости" (запрос пользователя 2026-09): сортировка/фильтр гостей по
// типу VIP/Простой/Без стола, переход в карточку гостя, блокировка и
// снятие со стола (реально действующие — см. backend/auth.py::
// require_guest и models.py::GuestStatus, а не просто отметка в интерфейсе),
// статистика по вечеру/неделе/месяцу, избранные песни гостя видны в карточке.
const GUEST_TYPE_FILTERS = [
  { key: "", label: "Все" },
  { key: "vip", label: "⭐ VIP" },
  { key: "client", label: "🙂 Простой" },
  { key: "no_table", label: "🚪 Без стола" },
];

const GUEST_TYPE_BADGE = {
  vip: "⭐ VIP",
  client: "🙂 Простой",
  no_table: "🚪 Без стола",
};

function GuestCard({ token, clubId, guestId, onBack, onChanged }) {
  const [guest, setGuest] = useState(null);
  const [loadError, setLoadError] = useState(null);
  const [actionError, setActionError] = useState(null);
  const [busy, setBusy] = useState(false);

  async function reload() {
    try {
      const data = await api.getGuest(token, clubId, guestId);
      setGuest(data);
      setLoadError(null);
    } catch (err) {
      setLoadError(err instanceof ApiError ? err.message : String(err));
    }
  }

  useEffect(() => {
    reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [guestId]);

  async function handleToggleBlock() {
    setBusy(true);
    setActionError(null);
    try {
      if (guest.is_blocked) {
        await api.unblockGuest(token, guestId);
      } else {
        await api.blockGuest(token, guestId);
      }
      await reload();
      onChanged?.();
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  async function handleRemoveTable() {
    setBusy(true);
    setActionError(null);
    try {
      await api.removeGuestFromTable(token, guestId);
      await reload();
      onChanged?.();
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="guest-card">
      <button type="button" className="btn-link" onClick={onBack}>← К списку гостей</button>

      {loadError && <div className="banner banner--error">{loadError}</div>}
      {!guest && !loadError && <p className="empty-hint">Загрузка…</p>}

      {guest && (
        <>
          <h2>
            Гость #{guest.guest_id}{" "}
            <span className="guest-type-badge">{GUEST_TYPE_BADGE[guest.guest_type] || guest.guest_type}</span>
            {guest.is_blocked && <span className="guest-type-badge guest-type-badge--blocked">🚫 Заблокирован</span>}
          </h2>
          {guest.email && <p className="empty-hint">Почта: {guest.email}</p>}
          <p className="empty-hint">
            Стол: {guest.table_no ?? "—"}
            {guest.last_song_title && (
              <> · последняя песня: {guest.last_artist ? `${guest.last_artist} — ` : ""}{guest.last_song_title}</>
            )}
          </p>

          {guest.vip_balance != null && (
            <p className="empty-hint">
              Баланс: <strong>{guest.vip_balance} MDL</strong> · кэшбэк {guest.vip_cashback_percent}%
            </p>
          )}

          <div className="vip-stat-row"><span>Заказов за вечер</span><strong>{guest.orders_evening}</strong></div>
          <div className="vip-stat-row"><span>Заказов за неделю</span><strong>{guest.orders_week}</strong></div>
          <div className="vip-stat-row"><span>Заказов за месяц</span><strong>{guest.orders_month}</strong></div>

          {actionError && <div className="banner banner--error">{actionError}</div>}

          <div className="vip-row__actions" style={{ marginTop: 10 }}>
            <button type="button" className="btn btn--reject" disabled={busy} onClick={handleToggleBlock}>
              {guest.is_blocked ? "Разблокировать" : "🚫 Заблокировать"}
            </button>
            {guest.table_no != null && (
              <button type="button" className="btn-link" disabled={busy} onClick={handleRemoveTable}>
                Снять со стола
              </button>
            )}
          </div>

          <h3 style={{ marginTop: 16 }}>Избранные песни ({guest.favorites.length})</h3>
          {guest.favorites.length === 0 && <p className="empty-hint">Пока ничего не добавлено.</p>}
          {guest.favorites.length > 0 && (
            <ul className="song-search__results">
              {guest.favorites.map((f) => (
                <li key={f.id} style={{ padding: "8px 12px" }}>
                  🎵 {f.artist ? `${f.artist} — ${f.song_title}` : f.song_title}
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </div>
  );
}

function GuestsPanel({ token, clubId }) {
  const [typeFilter, setTypeFilter] = useState("");
  const [guests, setGuests] = useState(null);
  const [loadError, setLoadError] = useState(null);
  const [selectedGuestId, setSelectedGuestId] = useState(null);

  async function reload() {
    try {
      const data = await api.listGuests(token, clubId, typeFilter || undefined);
      setGuests(data);
      setLoadError(null);
    } catch (err) {
      setLoadError(err instanceof ApiError ? err.message : String(err));
    }
  }

  useEffect(() => {
    reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [clubId, typeFilter]);

  if (selectedGuestId != null) {
    return (
      <div className="guests-panel">
        <GuestCard
          token={token}
          clubId={clubId}
          guestId={selectedGuestId}
          onBack={() => setSelectedGuestId(null)}
          onChanged={reload}
        />
      </div>
    );
  }

  return (
    <div className="guests-panel">
      <section>
        <h2>Гости</h2>
        <div className="guest-type-filters">
          {GUEST_TYPE_FILTERS.map((f) => (
            <button
              key={f.key || "all"}
              type="button"
              className={`btn-link${typeFilter === f.key ? " guest-type-filters__active" : ""}`}
              onClick={() => setTypeFilter(f.key)}
            >
              {f.label}
            </button>
          ))}
        </div>

        {loadError && <div className="banner banner--error">{loadError}</div>}
        {!guests && !loadError && <p className="empty-hint">Загрузка…</p>}
        {guests && guests.length === 0 && <p className="empty-hint">Гостей пока нет.</p>}

        {guests && guests.length > 0 && (
          <ul className="vip-list">
            {guests.map((guest) => (
              <li key={guest.guest_id} className="vip-row vip-row--client">
                <div>
                  Гость #{guest.guest_id} · {GUEST_TYPE_BADGE[guest.guest_type] || guest.guest_type}
                  {guest.is_blocked && <span className="guest-type-badge guest-type-badge--blocked"> 🚫 Заблокирован</span>}
                  <br />
                  <span className="empty-hint">
                    Стол: {guest.table_no ?? "—"} · за вечер {guest.orders_evening} · за неделю {guest.orders_week} · за месяц {guest.orders_month}
                    {guest.vip_balance != null && <> · баланс {guest.vip_balance} MDL</>}
                  </span>
                </div>
                <div className="vip-row__actions">
                  <button type="button" className="btn-link" onClick={() => setSelectedGuestId(guest.guest_id)}>
                    Открыть карточку →
                  </button>
                </div>
              </li>
            ))}
          </ul>
        )}
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
  // 'orders' | 'vip' | 'categories' | 'tables' | 'guests' — переключение
  // верхнеуровневых экранов (Block D KJ Pro; 'categories'/'tables' добавлены
  // доп. ТЗ "KJ Pro", KJ-01/03/07 и KJ-04 соответственно; 'guests' — запрос
  // пользователя 2026-09, список гостей VIP/Простой/Без стола с карточкой).
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
        <div className="app-header__nav">
          {view !== "orders" && (
            <button type="button" className="btn-link" onClick={() => setView("orders")}>
              ← Заказы
            </button>
          )}
          {view !== "vip" && (
            <button type="button" className="btn-link" onClick={() => setView("vip")}>
              ⭐ VIP
            </button>
          )}
          {view !== "categories" && (
            <button type="button" className="btn-link" onClick={() => setView("categories")}>
              🎚 Категории
            </button>
          )}
          {view !== "tables" && (
            <button type="button" className="btn-link" onClick={() => setView("tables")}>
              🪑 Столы
            </button>
          )}
          {view !== "guests" && (
            <button type="button" className="btn-link" onClick={() => setView("guests")}>
              👥 Гости
            </button>
          )}
        </div>
      </header>

      {actionError && <div className="banner banner--error">{actionError}</div>}

      {view === "vip" ? (
        <VipPanel token={token} clubId={me.club_id} socket={socketInstance} />
      ) : view === "categories" ? (
        <CategoriesPanel token={token} clubId={me.club_id} />
      ) : view === "tables" ? (
        <TableSettingsPanel token={token} clubId={me.club_id} />
      ) : view === "guests" ? (
        <GuestsPanel token={token} clubId={me.club_id} />
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
              token={token}
              clubId={me.club_id}
            />
          </section>
        </main>
      )}
    </div>
  );
}
