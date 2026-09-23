import { useCallback, useEffect, useRef, useState } from "react";
import { GOOGLE_CLIENT_ID, api, ApiError, resolveToken, storeToken } from "./api";
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

// До 2026-09-18 здесь была карточка заявки (OrderCard) со списком
// подтверждения через drag-and-drop в "Живую очередь VirtualDJ" — доп. ТЗ
// "KJ Pro" (запрос пользователя "только на карточке") убрало этот список с
// экрана "Заказы" целиком в пользу мест на карточках столов (см.
// OrdersBoard ниже) с кнопками "Принять"/"Отклонить" прямо на месте —
// решение по каждому месту принимается на карточке его стола.

// KJ Pro: смена стола/категории и удаление песни, уже стоящей в очереди
// (запрос пользователя, после того как выяснилось, что перестановку порядка
// в самой очереди VirtualDJ пока не сделать надёжно — см. обсуждение про
// vdj_bridge/driver.py — договорились начать с этих трёх пунктов, порядок
// песен отложен). Категории подтягиваются тем же способом, что и в
// CategoriesPanel (см. её reload()) — свой собственный небольшой список
// внутри компонента, отдельный от него.
function QueueTable({ queue, token, clubId }) {
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
    <div className="queue-dropzone">
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
              {/* ИЗМЕНЕНО (жалоба пользователя 2026-09-21: "кнопка удалить не
              работает"): для настоящего VirtualDJ (адаптер bridge) удаление
              элемента из ЖИВОЙ очереди по ID не поддерживается самой
              VirtualDJ — см. докстринг remove_from_vdj_queue() в
              vdj_service.py ("это согласовано с пользователем отдельно, не
              баг"). Раньше кнопка показывалась всегда и всегда падала с
              ошибкой на реальных песнях — путало KJ. Теперь показываем её
              только для "осиротевших" записей (item.orphaned — есть в нашей
              базе, но уже пропали из самой VirtualDJ, например после
              перезапуска сервера), где удаление — это просто чистка нашей
              записи и реально работает. Убрать реальную песню из очереди
              VirtualDJ по-прежнему можно только вручную, прямо в VirtualDJ. */}
              {item.orphaned && (
                <button
                  type="button"
                  className="btn-link queue-row__remove"
                  disabled={busyKey === `remove-${item.vdj_item_id ?? `no-id-${item.order_id}`}`}
                  onClick={() => handleRemove(item)}
                >
                  🗑 Удалить
                </button>
              )}
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

// ДОБАВЛЕНО (2026-09-20, решение пользователя по итогам жалобы "нет
// возможности удалить / заменить / сменить категорию": "Гость Удалить или
// заменить может только с согласия роли 2 — об этом роли 2 должно прийти
// уведомление о замене или удалении" -> "Нужно одобрение KJ (запрос →
// Одобрить/Отклонить)"). Гость больше не отменяет/меняет заказ сам —
// кнопки "❌ Отменить заказ"/"🔁 Заменить песню" в Guest App теперь только
// создают заявку (backend/models.py::OrderChangeRequest), и эта панель —
// единственное место, где KJ может её одобрить или отклонить.
//
// Показана прямо на главном экране "Заказы по столам" (а не спрятана за
// отдельной вкладкой, как VipPanel ниже) и рендерится, только когда
// заявки реально есть — так же, как banner ошибки: KJ не должен идти
// искать, что там появилось, он должен увидеть это сразу, ровно так же,
// как раньше сразу видел новый заказ на карточке стола. Структура и
// стилевые классы (vip-list/vip-row/vip-row__actions) намеренно
// переиспользованы у VipPanel — та же самая форма "запрос -> Одобрить/
// Отклонить", нет смысла заводить для неё отдельный набор CSS-классов.
function OrderChangeRequestsPanel({ token, clubId, socket }) {
  const [pending, setPending] = useState(null);
  const [actionError, setActionError] = useState(null);
  const [busyKey, setBusyKey] = useState(null);

  async function reload() {
    try {
      const data = await api.listOrderChangeRequests(token, clubId);
      setPending(data);
    } catch {
      // Тихо — отдельная панель не должна ломать показ основного экрана
      // заказов из-за временной ошибки её собственной загрузки; при
      // следующем действии (approve/reject) ошибка всё равно всплывёт.
    }
  }

  useEffect(() => {
    reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [clubId]);

  useEffect(() => {
    if (!socket) return undefined;
    const onCreated = (changeRequest) => {
      setPending((prev) => {
        const list = prev || [];
        return list.some((r) => r.id === changeRequest.id) ? list : [...list, changeRequest];
      });
    };
    socket.on("order_change_request_created", onCreated);
    return () => {
      socket.off("order_change_request_created", onCreated);
    };
  }, [socket]);

  async function handleApprove(requestId) {
    setBusyKey(requestId);
    setActionError(null);
    try {
      await api.approveOrderChangeRequest(token, requestId);
      await reload();
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setBusyKey(null);
    }
  }

  async function handleReject(requestId) {
    setBusyKey(requestId);
    setActionError(null);
    try {
      await api.rejectOrderChangeRequest(token, requestId);
      await reload();
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setBusyKey(null);
    }
  }

  if (!pending || pending.length === 0) return null;

  return (
    <section className="order-change-requests-panel">
      <h2>🔔 Заявки от гостей ({pending.length})</h2>
      {actionError && <div className="banner banner--error">{actionError}</div>}
      <ul className="vip-list">
        {pending.map((r) => (
          <li key={r.id} className="vip-row">
            <span>
              {r.kind === "cancel" ? "❌ Отменить" : "🔁 Заменить"} — стол {r.table_no ?? "—"}:{" "}
              {r.order_song_title}
              {r.order_artist ? ` (${r.order_artist})` : ""}
              {r.kind === "replace" && (
                <>
                  {" "}→ {r.new_song_title}
                  {r.new_artist ? ` (${r.new_artist})` : ""}
                </>
              )}
            </span>
            <span className="vip-row__actions">
              <button
                type="button" className="btn btn--accent" disabled={busyKey === r.id}
                onClick={() => handleApprove(r.id)}
              >
                Одобрить
              </button>
              <button
                type="button" className="btn btn--reject" disabled={busyKey === r.id}
                onClick={() => handleReject(r.id)}
              >
                Отклонить
              </button>
            </span>
          </li>
        ))}
      </ul>
    </section>
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

  // ДОБАВЛЕНО (2026-09-23, запрос пользователя "нужно иметь возможность
  // блокировать вип") — раньше заблокировать VIP-гостя можно было, только
  // предварительно найдя его во вкладке "Гости" и открыв его карточку; сам
  // эндпоинт (POST /guests/<id>/block|unblock) уже существовал и не
  // менялся, здесь просто прямой доступ к нему из вкладки VIP.
  async function handleToggleBlock(client) {
    const key = `block-${client.id}`;
    setBusyKey(key);
    setActionError(null);
    try {
      if (client.is_blocked) {
        await api.unblockGuest(token, client.telegram_user_id);
      } else {
        await api.blockGuest(token, client.telegram_user_id);
      }
      await reload();
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setBusyKey(null);
    }
  }

  // ДОБАВЛЕНО (2026-09-23, запрос пользователя "нет кнопки удалить. это
  // означает перевести его в простые") — см. docstring
  // vip_service.remove_vip_client про то, почему это удаление строки
  // VipClient, а не отдельный флаг, и почему сервер откажет, если на
  // счету ещё остались деньги (VIP_BALANCE_NOT_ZERO) — тогда ошибка
  // покажется в actionError, и её видно прямо тут, объясняющей, что делать
  // (обнулить баланс кнопкой "🔄 Установить" выше).
  async function handleRemove(vipClientId) {
    setBusyKey(`remove-${vipClientId}`);
    setActionError(null);
    try {
      await api.removeVipClient(token, vipClientId);
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
                {c.is_blocked && <span className="guest-type-badge guest-type-badge--blocked"> 🚫 Заблокирован</span>}
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
              {/* ДОБАВЛЕНО (2026-09-23, запрос пользователя): блокировка и
              перевод обратно в простые — раньше во вкладке VIP не было ни
              того, ни другого. */}
              <div className="vip-row__actions">
                <button
                  type="button" className="btn btn--reject" disabled={busyKey === `block-${c.id}`}
                  onClick={() => handleToggleBlock(c)}
                >
                  {c.is_blocked ? "Разблокировать" : "🚫 Заблокировать"}
                </button>
                <button
                  type="button" className="btn btn--reject" disabled={busyKey === `remove-${c.id}`}
                  onClick={() => handleRemove(c.id)}
                  title="Перевести обратно в простые"
                >
                  {busyKey === `remove-${c.id}` ? "Переводим…" : "🗑 Удалить (в простые)"}
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
//
// 2026-09-17, запрос пользователя: рядом со столами появилось второе поле —
// сколько песен от одного стола может стоять в очереди одновременно.
// Оба поля сохраняются вместе, одной кнопкой (см. handleSave ниже) —
// это подстраховка от рассинхронизации бэкенда и фронтенда при раздельном
// деплое (backend/routes/kj.py::update_table_settings меняет только те
// ключи, что реально пришли в запросе, но раз оба поля тут в одной форме,
// они и уходят вместе одним PUT).
function TableSettingsPanel({ token, clubId }) {
  const [tableCountDraft, setTableCountDraft] = useState("");
  const [songsPerTableDraft, setSongsPerTableDraft] = useState("");
  const [loadError, setLoadError] = useState(null);
  const [actionError, setActionError] = useState(null);
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState(false);

  async function reload() {
    try {
      const data = await api.getTableSettings(token, clubId);
      setTableCountDraft(data.table_count == null ? "" : String(data.table_count));
      setSongsPerTableDraft(data.songs_per_table == null ? "" : String(data.songs_per_table));
      setLoadError(null);
    } catch (err) {
      setLoadError(err instanceof ApiError ? err.message : String(err));
    }
  }

  useEffect(() => {
    reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [clubId]);

  function parseDraft(draft) {
    const trimmed = draft.trim();
    if (trimmed === "") return { ok: true, value: null };
    const value = Number(trimmed);
    if (!Number.isInteger(value) || value < 1) return { ok: false, value: null };
    return { ok: true, value };
  }

  async function handleSave(event) {
    event.preventDefault();
    const tableCount = parseDraft(tableCountDraft);
    const songsPerTable = parseDraft(songsPerTableDraft);
    if (!tableCount.ok || !songsPerTable.ok) return;

    setBusy(true);
    setActionError(null);
    setSaved(false);
    try {
      const data = await api.updateTableSettings(token, clubId, {
        table_count: tableCount.value,
        songs_per_table: songsPerTable.value,
      });
      setTableCountDraft(data.table_count == null ? "" : String(data.table_count));
      setSongsPerTableDraft(data.songs_per_table == null ? "" : String(data.songs_per_table));
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
          <label className="table-settings-field">
            <span>Столов в клубе</span>
            <input
              type="number"
              min="1"
              placeholder="Без ограничения"
              value={tableCountDraft}
              onChange={(e) => {
                setTableCountDraft(e.target.value);
                setSaved(false);
              }}
              disabled={busy}
            />
          </label>
          <label className="table-settings-field">
            <span>Песен на стол одновременно</span>
            <input
              type="number"
              min="1"
              placeholder="Не задано"
              value={songsPerTableDraft}
              onChange={(e) => {
                setSongsPerTableDraft(e.target.value);
                setSaved(false);
              }}
              disabled={busy}
            />
          </label>
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

  // ДОБАВЛЕНО (2026-09-19, запрос пользователя "закрыть стол... убрать со
  // стола и заблокировать, это всё внутри карточки"): один клик вместо
  // двух отдельных ("Снять со стола" + "Заблокировать" ниже, они остаются
  // на месте как есть) — плюс, чего эти две кнопки сами по себе не делали,
  // отклоняет всё ещё непроигранное с этого стола, чтобы места на табло
  // "Заказы" реально освободились (см. guest_status_service.close_table).
  async function handleCloseTable() {
    setBusy(true);
    setActionError(null);
    try {
      await api.closeGuestTable(token, guestId);
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
            {guest.display_name || `Гость #${guest.guest_id}`}{" "}
            <span className="guest-type-badge">{GUEST_TYPE_BADGE[guest.guest_type] || guest.guest_type}</span>
            {guest.is_blocked && <span className="guest-type-badge guest-type-badge--blocked">🚫 Заблокирован</span>}
          </h2>
          {/* Имя — самоназвание гостя (запрос пользователя 2026-09), ID
          показываем отдельно всегда, чтобы не терять однозначную ссылку на
          гостя, если имя выглядит неоднозначно (совпадает у двух гостей). */}
          {guest.display_name && <p className="empty-hint">ID гостя: {guest.guest_id}</p>}
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
            {!guest.is_blocked && (
              <button type="button" className="btn btn--complete" disabled={busy} onClick={handleCloseTable}>
                🚪 Закрыть стол
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
                  {guest.display_name || `Гость #${guest.guest_id}`} · {GUEST_TYPE_BADGE[guest.guest_type] || guest.guest_type}
                  {guest.is_blocked && <span className="guest-type-badge guest-type-badge--blocked"> 🚫 Заблокирован</span>}
                  <br />
                  <span className="empty-hint">
                    {guest.display_name && <>ID {guest.guest_id} · </>}
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

// Доп. ТЗ "KJ Pro", запрос пользователя 2026-09-18 — обсуждение перед
// реализацией, см. backend/services/table_board_service.py за полным
// докстрингом механики. Место на карточке, которое ждёт решения KJ (ещё
// не подтверждено/отклонено, включая "error" — не удалось добавить в
// VirtualDJ, KJ может нажать "Принять" ещё раз, чтобы попробовать снова),
// показывает две маленькие кнопки прямо на себе, а не как раньше — списком
// заявок с drag-and-drop (см. OrderCard выше, из которого этот список
// подтверждения на экране "Заказы" теперь убран целиком, по решению
// пользователя "только на карточке").
const BOARD_SLOT_NEEDS_DECISION = new Set(["pending", "processing", "error"]);

function OrdersBoardSlot({ slot, categories, busy, onAccept, onReject, onComplete, onChangeCategory, onOpenGuest }) {
  if (slot == null) {
    return <div className="table-slot table-slot--empty">Свободен</div>;
  }
  const needsDecision = BOARD_SLOT_NEEDS_DECISION.has(slot.status);
  // Запрос пользователя 2026-09-18: подтверждение заказа больше не ставит
  // песню в VirtualDJ само (KJ ставит сам, вручную) — "queued" здесь значит
  // "KJ принял заказ", а не "песня реально в очереди VirtualDJ". Место
  // освобождается только явной кнопкой "Готово" (см. complete_order() в
  // backend/services/vdj_service.py), а не само по себе.
  const isQueued = slot.status === "queued";
  const categoryName = categories.find((c) => c.id === slot.service_id)?.name;
  // ИСПРАВЛЕНО (2026-09-19, жалоба пользователя "не сделано изменение
  // категории песни"): смена категории у уже принятого заказа была только
  // в QueueTable (строки живой очереди VirtualDJ) — но после отвязки
  // confirm_order() от VirtualDJ (см. коммит выше) заказ обычно сидит в
  // статусе "queued" на этой самой карточке места ЗАДОЛГО до того, как KJ
  // нажмёт "Готово" и он попадёт в живую очередь. До этой правки сменить
  // категорию в этот промежуток было нельзя — на карточке было только
  // название категории текстом, без выбора. Бэкенд (PUT
  // /order/<id>/category, см. update_order_category в vdj_service.py)
  // всегда это позволял для queued-заказов — не хватало только кнопки
  // здесь. QueueTable и её выпадающий список остаются как есть — тот
  // экран отвечает уже за позиции в самой очереди VirtualDJ (после
  // "Готово" или чужие, добавленные мимо приложения).
  const canEditCategory = isQueued && categories.length > 0;
  // ДОБАВЛЕНО (2026-09-19, запрос пользователя "оплата происходит только у
  // випа, если человек не вип то у него и не должна появляться кнопка
  // готово"): "Готово" теперь и списывает деньги по тарифу (см.
  // complete_order/charge_at_completion на бэкенде) — для обычных гостей
  // списывать нечего, а значит и кнопке тут делать нечего. Их заказы со
  // стола убираются не по одной песне, а разом кнопкой "Закрыть стол" из
  // карточки гостя (см. GuestCard.handleCloseTable), когда компания ушла.
  const isVip = slot.guest_type === "vip";
  const canComplete = isQueued && isVip;
  return (
    <div className={`table-slot table-slot--${needsDecision ? "pending" : "queued"}`}>
      <button type="button" className="table-slot__body" onClick={() => onOpenGuest(slot.guest_id)}>
        <div className="table-slot__song">🎵 {slot.song_title}</div>
        {slot.artist && <div className="table-slot__artist">🎤 {slot.artist}</div>}
        {!canEditCategory && categoryName && <div className="table-slot__category">{categoryName}</div>}
        {isQueued && <div className="table-slot__badge">✅ Принят</div>}
        {slot.status === "error" && slot.error_message && (
          <div className="table-slot__error">{slot.error_message}</div>
        )}
      </button>
      {canEditCategory && (
        <select
          className="table-slot__category-select"
          value={slot.service_id ?? categories[0]?.id ?? ""}
          disabled={busy}
          onClick={(event) => event.stopPropagation()}
          onChange={(event) => onChangeCategory(slot.order_id, Number(event.target.value))}
        >
          {categories.map((category) => (
            <option key={category.id} value={category.id}>
              {category.name}
            </option>
          ))}
        </select>
      )}
      {needsDecision && (
        <div className="table-slot__actions">
          <button type="button" className="btn btn--accept" disabled={busy} onClick={() => onAccept(slot.order_id)}>
            ✅ Принять
          </button>
          <button type="button" className="btn btn--reject" disabled={busy} onClick={() => onReject(slot.order_id)}>
            ❌ Отклонить
          </button>
        </div>
      )}
      {/* ДОБАВЛЕНО (2026-09-20, жалоба пользователя "нет возможности удалить"
      — то же самое, что и в Guest App "Мои заказы"): раньше у уже принятого
      (queued) заказа не было способа убрать его по отдельности — только
      "Готово" для VIP (списывает деньги, не подходит для отмены) или разом
      "Закрыть стол" со всей карточки гостя. Кнопка ниже вызывает тот же
      PUT /order/<id>/reject, что и "❌ Отклонить" выше для pending —
      backend (vdj_service.reject_order) теперь явно разрешает это и для
      STATUS_QUEUED (см. её докстринг), деньги не списывает и не возвращает,
      потому что списание происходит только в момент "Готово". */}
      {isQueued && (
        <div className="table-slot__actions">
          {canComplete && (
            <button type="button" className="btn btn--complete" disabled={busy} onClick={() => onComplete(slot.order_id)}>
              🏁 Готово
            </button>
          )}
          <button type="button" className="btn btn--reject" disabled={busy} onClick={() => onReject(slot.order_id)}>
            🗑 Убрать
          </button>
        </div>
      )}
    </div>
  );
}

function OrdersBoard({ token, clubId, socket, onOpenGuest }) {
  const [board, setBoard] = useState(null);
  const [categories, setCategories] = useState([]);
  const [loadError, setLoadError] = useState(null);
  const [actionError, setActionError] = useState(null);
  const [busyOrderId, setBusyOrderId] = useState(null);

  async function reload() {
    try {
      const data = await api.getOrdersBoard(token, clubId);
      setBoard(data);
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
    api
      .listCategories(token, clubId)
      .then(setCategories)
      .catch(() => {
        // Не критично — просто не покажем название категории в этот раз
        // (см. тот же приём в QueueTable выше).
      });
  }, [token, clubId]);

  // Живые обновления — те же события, что уже используются на этом экране
  // для списка заявок и живой очереди VirtualDJ (см. эффект в App() ниже);
  // здесь просто целиком перезапрашиваем доску, тем же приёмом, что и
  // handleConfirm/handleReject в App() при ошибке.
  useEffect(() => {
    if (!socket) return undefined;
    socket.on("order_created", reload);
    socket.on("order_updated", reload);
    socket.on("order_confirmed", reload);
    socket.on("order_rejected", reload);
    socket.on("queue_updated", reload);
    return () => {
      socket.off("order_created", reload);
      socket.off("order_updated", reload);
      socket.off("order_confirmed", reload);
      socket.off("order_rejected", reload);
      socket.off("queue_updated", reload);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [socket]);

  async function handleAccept(orderId) {
    setBusyOrderId(orderId);
    setActionError(null);
    try {
      await api.confirmOrder(token, orderId);
      await reload();
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : String(err));
      await reload();
    } finally {
      setBusyOrderId(null);
    }
  }

  async function handleReject(orderId) {
    setBusyOrderId(orderId);
    setActionError(null);
    try {
      await api.rejectOrder(token, orderId);
      await reload();
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : String(err));
      await reload();
    } finally {
      setBusyOrderId(null);
    }
  }

  // Запрос пользователя 2026-09-18: единственный способ освободить занятое
  // место на карточке для принятого (не через VirtualDJ) заказа — та же
  // схема busy/reload, что и у handleAccept/handleReject выше.
  async function handleComplete(orderId) {
    setBusyOrderId(orderId);
    setActionError(null);
    try {
      await api.completeOrder(token, orderId);
      await reload();
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : String(err));
      await reload();
    } finally {
      setBusyOrderId(null);
    }
  }

  // ДОБАВЛЕНО (2026-09-19, жалоба пользователя "не сделано изменение
  // категории песни"): смена категории прямо на карточке места, пока заказ
  // ещё "queued" (см. onChangeCategory в OrdersBoardSlot выше) — та же
  // схема busy/reload, что и у остальных действий на доске.
  async function handleChangeCategory(orderId, serviceId) {
    setBusyOrderId(orderId);
    setActionError(null);
    try {
      await api.updateOrderCategory(token, orderId, serviceId);
      await reload();
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : String(err));
      await reload();
    } finally {
      setBusyOrderId(null);
    }
  }

  if (loadError) {
    return <div className="banner banner--error">{loadError}</div>;
  }
  if (board == null) {
    return <p className="empty-hint">Загрузка…</p>;
  }
  if (board.length === 0) {
    return <p className="empty-hint">Сначала задайте число столов клуба на вкладке "Столы".</p>;
  }

  return (
    <div className="orders-board">
      {actionError && <div className="banner banner--error">{actionError}</div>}
      <div className="orders-board__grid">
        {board.map((table) => (
          <div className="table-card" key={table.table_no}>
            <div className="table-card__title">Стол {table.table_no}</div>
            <div className="table-card__slots">
              {table.slots.map((slot, index) => (
                <OrdersBoardSlot
                  // order_id не подходит на ключ — свободное место (null)
                  // повторяется у каждого стола, номер места стабилен
                  key={index}
                  slot={slot}
                  categories={categories}
                  busy={slot != null && busyOrderId === slot.order_id}
                  onAccept={handleAccept}
                  onReject={handleReject}
                  onComplete={handleComplete}
                  onChangeCategory={handleChangeCategory}
                  onOpenGuest={onOpenGuest}
                />
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// 2026-09: "доступ KJ Pro определяется Google-аккаунтом клуба" — основной
// способ входа (см. docstring KJOperator в models.py и auth.py::
// issue_kj_google_token), показывается только когда resolveToken() не
// нашёл токен ни в ссылке, ни в localStorage. Ссылка от бота (/kjpanel)
// по-прежнему сама кладёт токен в localStorage при первом же открытии
// (см. resolveToken) и минует этот экран целиком — она остаётся резервным
// способом, полностью равноценным по правам после входа.
function KjLoginScreen({ onLoggedIn }) {
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const buttonRef = useRef(null);

  async function handleGoogleCredential(response) {
    setBusy(true);
    setError(null);
    try {
      const { token } = await api.loginWithGoogle({ id_token: response.credential });
      storeToken(token);
      onLoggedIn(token);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
      setBusy(false);
    }
  }

  useEffect(() => {
    if (!window.google?.accounts?.id || !buttonRef.current) {
      setError("Не удалось загрузить вход через Google — проверьте подключение к интернету и обновите страницу");
      return;
    }
    window.google.accounts.id.initialize({
      client_id: GOOGLE_CLIENT_ID,
      callback: handleGoogleCredential,
    });
    window.google.accounts.id.renderButton(buttonRef.current, {
      theme: "outline", size: "large", text: "signin_with", locale: "ru", width: 280,
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="app-shell centered">
      <h1>KJ Panel</h1>
      <p>Войдите через Google-аккаунт клуба — основной способ входа.</p>
      {error && <p className="error-text">{error}</p>}
      <div ref={buttonRef} />
      {busy && <p>Входим…</p>}
      <p className="app-header__subtitle">
        Резервный способ: ссылка из команды /kjpanel в Telegram-боте.
      </p>
    </div>
  );
}

// Панель обзора связи (запрос пользователя 2026-09-17: "небольшая панель
// обзора для kj, везде ли есть подключение"). Три звена одной цепочки
// "гость заказал -> KJ увидел -> песня попала в VirtualDJ" — раньше KJ
// узнавал о разрыве где-то в середине только когда песня просто не
// появлялась в очереди, без единой подсказки, где именно оборвалось.
// Каждый кружок кликабелен — по клику разворачивается пояснение обычными
// словами, без терминов вроде "WebSocket"/"namespace" (KJ не техник).
const OVERVIEW_ITEMS = [
  {
    key: "guest_kj",
    label: "Гость → KJ",
    explain: (ok, unknown) =>
      unknown
        ? "Проверяем связь панели с сервером…"
        : ok
        ? "Ваша панель на связи с сервером — новые заказы гостей и обновления очереди приходят сразу, без задержки."
        : "Панель потеряла связь с сервером — заказы гостей могут не появляться сами собой. Обновите страницу (F5).",
  },
  {
    key: "kj_bridge",
    label: "Сервер → Мост",
    explain: (ok, unknown) =>
      unknown
        ? "Проверяем, подключена ли программа-мост к серверу…"
        : ok
        ? "Программа-мост (на компьютере, где стоит VirtualDJ) на связи с сервером — подтверждённые заказы могут доходить до VirtualDJ."
        : "Программа-мост не подключена к серверу. Откройте программу-мост на компьютере с VirtualDJ и нажмите «Подключиться» — иначе подтверждённые заказы не попадут в очередь VirtualDJ.",
  },
  {
    key: "bridge_vdj",
    label: "Мост → VirtualDJ",
    explain: (ok, unknown) =>
      unknown
        ? "Мост ещё не проверил связь с VirtualDJ — подождите несколько секунд после подключения."
        : ok
        ? "Мост видит VirtualDJ на своём компьютере — песни должны добавляться в очередь нормально."
        : "Мост не видит VirtualDJ. Проверьте на компьютере с VirtualDJ: сама VirtualDJ запущена и в ней включён Network Control Plugin (в настройках VirtualDJ).",
  },
];

function OverviewDot({ state }) {
  // state: true (зелёный) | false (красный) | "unknown" (серый — ещё не знаем)
  const cls =
    state === "unknown" ? "overview-dot--unknown" : state ? "overview-dot--ok" : "overview-dot--off";
  return <span className={`overview-dot ${cls}`} aria-hidden="true" />;
}

function ConnectionOverviewPanel({ connected, bridgeStatus }) {
  const [openKey, setOpenKey] = useState(null);

  // bridgeStatus === null — ещё не пришёл ни разу (первые мгновения после
  // входа, пока не отработал ни начальный GET, ни первое событие сокета).
  const bridgeConnectedState = bridgeStatus == null ? "unknown" : bridgeStatus.connected;
  const vdjReachableState =
    bridgeStatus == null || !bridgeStatus.connected || bridgeStatus.vdj_reachable == null
      ? "unknown"
      : bridgeStatus.vdj_reachable;

  const states = {
    guest_kj: connected,
    kj_bridge: bridgeConnectedState,
    bridge_vdj: vdjReachableState,
  };

  return (
    <div className="overview-panel">
      <div className="overview-panel__row">
        {OVERVIEW_ITEMS.map((item) => (
          <button
            key={item.key}
            type="button"
            className={`overview-item${openKey === item.key ? " overview-item--open" : ""}`}
            onClick={() => setOpenKey((prev) => (prev === item.key ? null : item.key))}
          >
            <OverviewDot state={states[item.key]} />
            <span className="overview-item__label">{item.label}</span>
            <span className="overview-item__info" aria-hidden="true">ⓘ</span>
          </button>
        ))}
      </div>
      {openKey && (
        <div className="overview-panel__explain">
          {(() => {
            const item = OVERVIEW_ITEMS.find((i) => i.key === openKey);
            const state = states[openKey];
            return item.explain(state === true, state === "unknown");
          })()}
        </div>
      )}
    </div>
  );
}

export default function App() {
  const [token, setToken] = useState(() => resolveToken());
  const [me, setMe] = useState(null);
  const [queue, setQueue] = useState([]);
  const [loadError, setLoadError] = useState(null);
  const [connected, setConnected] = useState(false);
  // Панель обзора связи (запрос пользователя 2026-09-17) — null, пока не
  // пришёл ни начальный GET /api/kj/bridge/status, ни первое сокет-событие
  // "bridge_status"; дальше обновляется живым сокетом без поллинга (тот же
  // принцип, что и остальные live-обновления панели).
  const [bridgeStatus, setBridgeStatus] = useState(null);
  const [manualAddBusy, setManualAddBusy] = useState(false);
  const [manualAddError, setManualAddError] = useState(null);
  // 'orders' | 'vip' | 'categories' | 'tables' | 'guests' | 'manual' —
  // переключение верхнеуровневых экранов (Block D KJ Pro; 'categories'/
  // 'tables' добавлены доп. ТЗ "KJ Pro", KJ-01/03/07 и KJ-04 соответственно;
  // 'guests' — запрос пользователя 2026-09, список гостей VIP/Простой/Без
  // стола с карточкой; 'manual' — запрос пользователя 2026-09-18: форма
  // "Добавить песню" перенесена с экрана "Заказы" в свой собственный экран,
  // чтобы разгрузить панель столов).
  const [view, setView] = useState("orders");
  // Доп. ТЗ "KJ Pro", запрос пользователя 2026-09-18: клик по месту на
  // карточке стола проваливается в подробности о гости, тем же компонентом
  // GuestCard, что и вкладка "Гости" (см. GuestsPanel::selectedGuestId
  // выше) — здесь свой собственный стейт, потому что это разные экраны.
  const [boardGuestId, setBoardGuestId] = useState(null);
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
      let meData;
      try {
        meData = await api.me(token);
        if (cancelled) return;
        setMe(meData);

        const queueData = await api.getQueue(token, meData.club_id);
        if (cancelled) return;
        setQueue(queueData);
      } catch (err) {
        if (!cancelled) setLoadError(err instanceof ApiError ? err.message : String(err));
        return;
      }

      // Отдельно от основной загрузки (см. докстринг GET /api/kj/bridge/
      // status в routes/kj.py) — только чтобы показать правильное
      // состояние ДО первого сокет-события, а не после него. Не критично,
      // если не удастся: панель обзора просто покажет "проверяем…", пока
      // не придёт первое событие "bridge_status".
      try {
        const status = await api.getBridgeStatus(token, meData.club_id);
        if (!cancelled) setBridgeStatus(status);
      } catch {
        // см. комментарий выше — не критично.
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

    // Панель обзора связи: сервер сам рассылает это событие в комнату
    // клуба при каждом изменении состояния моста (подключился/отключился/
    // отчитался о VirtualDJ) — см. sockets.py::handle_bridge_connect/
    // handle_bridge_disconnect/handle_bridge_vdj_status. Никакого поллинга
    // не нужно, ровно как и для остальных live-обновлений этой панели.
    socket.on("bridge_status", (payload) => setBridgeStatus(payload));

    // order_created/order_updated/order_confirmed/order_rejected раньше
    // поддерживали здесь список заявок на подтверждение — он убран с этого
    // экрана целиком (доп. ТЗ "KJ Pro", запрос пользователя 2026-09-18:
    // "только на карточке"), теперь эти же события слушает сама OrdersBoard
    // ниже, у себя.

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

  if (!token) {
    return <KjLoginScreen onLoggedIn={setToken} />;
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
          {view !== "manual" && (
            <button type="button" className="btn-link" onClick={() => setView("manual")}>
              ➕ Добавить
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

      <ConnectionOverviewPanel connected={connected} bridgeStatus={bridgeStatus} />

      {view === "vip" ? (
        <VipPanel token={token} clubId={me.club_id} socket={socketInstance} />
      ) : view === "categories" ? (
        <CategoriesPanel token={token} clubId={me.club_id} />
      ) : view === "tables" ? (
        <TableSettingsPanel token={token} clubId={me.club_id} />
      ) : view === "guests" ? (
        <GuestsPanel token={token} clubId={me.club_id} />
      ) : view === "manual" ? (
        <main className="app-main">
          <section>
            <h2>Добавить песню</h2>
            <AddManualSongForm
              onSubmit={handleAddManualSong}
              busy={manualAddBusy}
              error={manualAddError}
            />
          </section>
        </main>
      ) : boardGuestId != null ? (
        <div className="app-main">
          <GuestCard
            token={token}
            clubId={me.club_id}
            guestId={boardGuestId}
            onBack={() => setBoardGuestId(null)}
          />
        </div>
      ) : (
        <main className="app-main">
          <OrderChangeRequestsPanel token={token} clubId={me.club_id} socket={socketInstance} />

          <section>
            <h2>Заказы по столам</h2>
            <OrdersBoard
              token={token}
              clubId={me.club_id}
              socket={socketInstance}
              onOpenGuest={setBoardGuestId}
            />
          </section>

          <section>
            <h2>Живая очередь VirtualDJ</h2>
            <QueueTable queue={queue} token={token} clubId={me.club_id} />
          </section>
        </main>
      )}
    </div>
  );
}
