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
// Ключ песни для "Новинок": исполнитель + название без учёта регистра и
// лишних пробелов (так же считает сервер).
function newSongKey(title, artist) {
  const norm = (v) => String(v || "").toLowerCase().split(/\s+/).filter(Boolean).join(" ");
  return `${norm(artist)}|${norm(title)}`;
}

function QueueTable({ queue, token, clubId }) {
  const [categories, setCategories] = useState([]);
  // Кнопка "Копировать" у песни: копирует "Исполнитель — Название".
  const [copiedIdx, setCopiedIdx] = useState(null);
  async function copySong(item, idx) {
    // Без тире: "Исполнитель Название" (отдельно стоящие - и — убираются).
    const text = `${item.artist || ""} ${item.song_title || ""}`
      .replace(/(^|\s)[—–-]+(?=\s|$)/g, " ")
      .replace(/\s+/g, " ")
      .trim();
    try {
      await navigator.clipboard.writeText(text);
    } catch {
      const ta = document.createElement("textarea");
      ta.value = text;
      document.body.appendChild(ta);
      ta.select();
      try { document.execCommand("copy"); } catch { /* ignore */ }
      document.body.removeChild(ta);
    }
    setCopiedIdx(idx);
    setTimeout(() => setCopiedIdx((cur) => (cur === idx ? null : cur)), 1500);
  }
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
  // ДОБАВЛЕНО (2026-10, запрос пользователя): в живой очереди теперь стоят и
  // принятые заказы, которых ещё нет в VirtualDJ (item.in_vdj === false).
  // renameDraft — правка названия такого заказа на точное из VirtualDJ;
  // linkingOrderId — режим "🔗 Это одна песня": KJ выбрал заказ и теперь
  // указывает, с какой "ничьей" строкой VirtualDJ его склеить.
  const [renameDraft, setRenameDraft] = useState(null); // { orderId, title, artist }
  const [linkingOrderId, setLinkingOrderId] = useState(null);
  // ДОБАВЛЕНО (2026-10, запрос пользователя): галочка "Новинка" у песни —
  // такие песни гость видит в списке "Новинки" над живой очередью.
  const [newSongKeys, setNewSongKeys] = useState(() => new Set());
  const [newSongHelpOpen, setNewSongHelpOpen] = useState(false);
  // Знак вопроса "Новинка" — на одной линии с заголовком "Живая очередь
  // VirtualDJ" и ровно над словом "Новинка" (запрос пользователя 2026-10).
  const dropzoneRef = useRef(null);
  const [newHelpPos, setNewHelpPos] = useState(null);
  useEffect(() => {
    function place() {
      const dz = dropzoneRef.current;
      const word = dz && dz.querySelector(".queue-row__new-word--first");
      const heading = dz && dz.closest("section") && dz.closest("section").querySelector("h2");
      // Если у всех песен галочки нет (все уже в "Новинках") — знак вопроса
      // всё равно стоит, у правого края первой песни.
      const firstRow = dz && dz.querySelector(".queue-row");
      if (!dz || !heading || (!word && !firstRow)) {
        setNewHelpPos(null);
        return;
      }
      const d = dz.getBoundingClientRect();
      const h = heading.getBoundingClientRect();
      let left;
      if (word) {
        const w = word.getBoundingClientRect();
        left = w.left + w.width / 2 - d.left;
      } else {
        left = firstRow.getBoundingClientRect().right - d.left - 40;
      }
      setNewHelpPos({ left, top: h.top + h.height / 2 - d.top });
    }
    place();
    window.addEventListener("resize", place);
    return () => window.removeEventListener("resize", place);
  }, [queue, newSongKeys]);
  useEffect(() => {
    let cancelled = false;
    const load = () =>
      api.listNewSongs(token)
        .then((list) => {
          if (!cancelled) setNewSongKeys(new Set((list || []).map((s) => newSongKey(s.song_title, s.artist))));
        })
        .catch(() => {});
    load();
    const id = setInterval(load, 30000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [token]);
  async function toggleNewSong(item, checked) {
    try {
      const list = await api.setNewSong(token, item.song_title, item.artist, checked);
      setNewSongKeys(new Set((list || []).map((s) => newSongKey(s.song_title, s.artist))));
    } catch {
      // не критично — галочка просто не поменяется
    }
  }

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

  async function handleSaveRename(item) {
    const title = (renameDraft?.title || "").trim();
    if (!title) {
      setRowError(item.order_id, "Название не может быть пустым");
      return;
    }
    setBusyKey(`rename-${item.order_id}`);
    setRowError(item.order_id, null);
    try {
      await api.renameOrder(token, item.order_id, title, (renameDraft?.artist || "").trim());
      setRenameDraft(null);
    } catch (err) {
      setRowError(item.order_id, err instanceof ApiError ? err.message : String(err));
    } finally {
      setBusyKey(null);
    }
  }

  async function handleLinkHere(item) {
    const orderId = linkingOrderId;
    if (orderId == null) return;
    const errorKey = `claim-${item.vdj_item_id}`;
    setBusyKey(`link-${item.vdj_item_id}`);
    setRowError(errorKey, null);
    try {
      await api.linkOrderToVdj(token, orderId, item.vdj_item_id);
      setLinkingOrderId(null);
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
    <div className="queue-dropzone" ref={dropzoneRef}>
      {newHelpPos && (
        <button
          type="button"
          className="queue-new-help__btn"
          title="Что такое «Новинка»?"
          style={{ left: newHelpPos.left, top: newHelpPos.top }}
          onClick={() => setNewSongHelpOpen(true)}
        >
          ❓
        </button>
      )}
      {newSongHelpOpen && (
        <div className="service-card-overlay" onClick={() => setNewSongHelpOpen(false)}>
          <div className="service-card" role="dialog" aria-modal="true" onClick={(e) => e.stopPropagation()}>
            <h3 className="service-card__title">Новинка</h3>
            <p className="service-card__desc">Отметьте новинку и она будет рекомендована гостям в очереди гостей.</p>
            <div className="service-card__buttons">
              <button type="button" className="service-card__close" onClick={() => setNewSongHelpOpen(false)}>
                Закрыть
              </button>
            </div>
          </div>
        </div>
      )}
      {queue.length === 0 ? (
        <p className="empty-hint">Очередь пока пуста.</p>
      ) : (
        // Вертикальный список вместо таблицы — тот же стиль строк, что и на
        // экране "Категории" (.categories-list/.category-row), по просьбе
        // пользователя. Порядок песен внутри самой очереди VirtualDJ пока не
        // меняется отсюда — это отдельная задача (KJ-09, отложена).
        <ul className="queue-list-vertical">
          {queue.map((item, idx) => (
            <li
              key={item.vdj_item_id ?? (item.order_id != null ? `order-${item.order_id}` : `no-id-${idx}`)}
              className={`queue-row${item.orphaned ? " queue-row--orphaned" : ""}`}
            >
              <span className="queue-row__position">{idx + 1}</span>
              <span className="queue-row__artist">{item.artist || "—"}</span>
              <span className="queue-row__song">{item.song_title}</span>
              {item.song_title && (
                <button
                  type="button"
                  className="queue-row__copy"
                  title="Скопировать исполнителя и название"
                  onClick={() => copySong(item, idx)}
                >
                  {copiedIdx === idx ? "✓ Скопировано" : "📋 Копировать"}
                </button>
              )}
              {/* Уже в "Новинках" — галочку и слово "Новинка" не видно, но место
              под них остаётся, чтобы знак вопроса стоял всегда на одном месте. */}
              {item.song_title && (
                <label
                  className={`queue-row__new${
                    newSongKeys.has(newSongKey(item.song_title, item.artist)) ? " queue-row__new--hidden" : ""
                  }`}
                  title="Показывать гостям в «Новинках»"
                >
                  <input
                    type="checkbox"
                    checked={false}
                    disabled={newSongKeys.has(newSongKey(item.song_title, item.artist))}
                    onChange={(e) => toggleNewSong(item, e.target.checked)}
                  />
                  <span
                    className={`queue-row__new-word${
                      idx === queue.findIndex((q) => q.song_title) ? " queue-row__new-word--first" : ""
                    }`}
                  >
                    Новинка
                  </span>
                </label>
              )}
              {item.orphaned && (
                <span className="queue-row__orphaned-badge" title="Эта песня больше не найдена в самом VirtualDJ — например, из-за перезапуска сервера. Можно только удалить.">
                  ⚠ нет в VDJ
                </span>
              )}
              {item.tone ? (
                <span className="tone-badge">🎚 Тон {item.tone > 0 ? `+${item.tone}` : item.tone}</span>
              ) : null}
              {item.guest_song_text && (
                <span className="queue-row__guest-text">гость написал: {item.guest_song_text}</span>
              )}
              {item.order_id != null && item.in_vdj === true && (
                <span className="queue-row__invdj-badge">✓ в VirtualDJ</span>
              )}
              {item.order_id != null && item.in_vdj === false && (
                <>
                  <span className="queue-row__orphaned-badge">нет в VirtualDJ</span>
                  <button
                    type="button"
                    className="btn-link"
                    onClick={() =>
                      setRenameDraft(
                        renameDraft?.orderId === item.order_id
                          ? null
                          : { orderId: item.order_id, title: item.song_title || "", artist: item.artist || "" },
                      )
                    }
                  >
                    ✏️ Название
                  </button>
                  <button
                    type="button"
                    className="btn-link"
                    onClick={() => setLinkingOrderId(linkingOrderId === item.order_id ? null : item.order_id)}
                  >
                    {linkingOrderId === item.order_id ? "✕ Отмена" : "🔗 Это одна песня"}
                  </button>
                </>
              )}
              {item.order_id == null && item.vdj_item_id && linkingOrderId != null && (
                <button
                  type="button"
                  className="btn btn--accent"
                  disabled={busyKey === `link-${item.vdj_item_id}`}
                  onClick={() => handleLinkHere(item)}
                >
                  🔗 Склеить с этой
                </button>
              )}
              {linkingOrderId === item.order_id && item.order_id != null && (
                <p className="empty-hint queue-row__error">
                  Теперь нажмите «🔗 Склеить с этой» у нужной песни из VirtualDJ выше.
                </p>
              )}
              {renameDraft?.orderId === item.order_id && item.order_id != null && (
                <span className="queue-row__rename">
                  <input
                    type="text"
                    className="vip-amount-input queue-row__rename-input"
                    placeholder="Точное название, как в VirtualDJ"
                    value={renameDraft.title}
                    onChange={(event) => setRenameDraft({ ...renameDraft, title: event.target.value })}
                  />
                  <input
                    type="text"
                    className="vip-amount-input queue-row__rename-input"
                    placeholder="Исполнитель"
                    value={renameDraft.artist}
                    onChange={(event) => setRenameDraft({ ...renameDraft, artist: event.target.value })}
                  />
                  <button
                    type="button"
                    className="btn btn--accent"
                    disabled={busyKey === `rename-${item.order_id}`}
                    onClick={() => handleSaveRename(item)}
                  >
                    Сохранить
                  </button>
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
    // ДОБАВЛЕНО (2026-09-23, жалоба пользователя "не одобрить не отклонить
    // нельзя" — заявка уже обработана): раньше решение по заявке, принятое
    // в одной вкладке/на одном устройстве, никак не доходило до других
    // открытых панелей — там заявка навсегда оставалась в списке "🔔
    // Заявки от гостей", а любой клик по Одобрить/Отклонить получал 409
    // ALREADY_DECIDED (см. sockets.py::emit_order_change_request_decided).
    // Слушаем то же событие и просто убираем заявку из списка.
    const onDecided = (changeRequest) => {
      setPending((prev) => (prev || []).filter((r) => r.id !== changeRequest.id));
    };
    socket.on("order_change_request_created", onCreated);
    socket.on("order_change_request_decided", onDecided);
    return () => {
      socket.off("order_change_request_created", onCreated);
      socket.off("order_change_request_decided", onDecided);
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
      // Заявку мог уже решить кто-то другой (другая вкладка/устройство) —
      // без перезагрузки списка она осталась бы висеть в нём навсегда,
      // раз за разом отвечая той же ошибкой на любой клик (см. докстринг
      // emit_order_change_request_decided выше).
      if (err instanceof ApiError && err.code === "ALREADY_DECIDED") {
        await reload();
      }
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
      if (err instanceof ApiError && err.code === "ALREADY_DECIDED") {
        await reload();
      }
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

// ДОБАВЛЕНО (запрос пользователя 2026-09-27, "закрыть стол по инициативе
// гостя-админа" — корневое исправление бага "первый гость навсегда админ
// стола", см. докстринг backend/models.py::TableCloseRequest). Гость-админ
// группового стола отправляет заявку на закрытие (кнопка "🔒 Закрыть стол"
// в Guest App), а KJ подтверждает или отклоняет её здесь — тот же паттерн,
// что и OrderChangeRequestsPanel выше (список + сокет-события created/
// decided), плюс чекбокс "Не показывать чек" на подтверждении: чек всё
// равно считается и сохраняется на бэкенде, просто не раздаётся гостям
// через поллинг /api/guest/me, если чекбокс отмечен.
function TableCloseRequestsPanel({ token, clubId, socket }) {
  const [pending, setPending] = useState(null);
  const [actionError, setActionError] = useState(null);
  const [busyKey, setBusyKey] = useState(null);
  const [hideReceiptByRequest, setHideReceiptByRequest] = useState({});

  async function reload() {
    try {
      const data = await api.listTableCloseRequests(token, clubId);
      setPending(data);
    } catch {
      // Тихо — как и OrderChangeRequestsPanel выше: отдельная панель не
      // должна ломать показ основного экрана заказов из-за временной
      // ошибки её собственной загрузки.
    }
  }

  useEffect(() => {
    reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [clubId]);

  useEffect(() => {
    if (!socket) return undefined;
    const onCreated = (closeRequest) => {
      setPending((prev) => {
        const list = prev || [];
        return list.some((r) => r.id === closeRequest.id) ? list : [...list, closeRequest];
      });
    };
    const onDecided = (closeRequest) => {
      setPending((prev) => (prev || []).filter((r) => r.id !== closeRequest.id));
    };
    socket.on("table_close_request_created", onCreated);
    socket.on("table_close_request_decided", onDecided);
    return () => {
      socket.off("table_close_request_created", onCreated);
      socket.off("table_close_request_decided", onDecided);
    };
  }, [socket]);

  async function handleApprove(requestId) {
    setBusyKey(requestId);
    setActionError(null);
    try {
      await api.approveTableCloseRequest(token, requestId, !!hideReceiptByRequest[requestId]);
      await reload();
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : String(err));
      // Заявку мог уже решить кто-то другой (другая вкладка/устройство) —
      // без перезагрузки списка она осталась бы висеть в нём навсегда.
      if (err instanceof ApiError && err.code === "ALREADY_DECIDED") {
        await reload();
      }
    } finally {
      setBusyKey(null);
    }
  }

  async function handleReject(requestId) {
    setBusyKey(requestId);
    setActionError(null);
    try {
      await api.rejectTableCloseRequest(token, requestId);
      await reload();
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : String(err));
      if (err instanceof ApiError && err.code === "ALREADY_DECIDED") {
        await reload();
      }
    } finally {
      setBusyKey(null);
    }
  }

  if (!pending || pending.length === 0) return null;

  return (
    <section className="table-close-requests-panel">
      <h2>🔒 Заявки на закрытие стола ({pending.length})</h2>
      {actionError && <div className="banner banner--error">{actionError}</div>}
      <ul className="vip-list">
        {pending.map((r) => (
          <li key={r.id} className="vip-row">
            <span>Стол {r.table_no}</span>
            <span className="vip-row__actions">
              <label className="table-close-hide-receipt">
                <input
                  type="checkbox"
                  checked={!!hideReceiptByRequest[r.id]}
                  onChange={(e) =>
                    setHideReceiptByRequest((prev) => ({ ...prev, [r.id]: e.target.checked }))
                  }
                />
                Не показывать чек
              </label>
              <button
                type="button" className="btn btn--accent" disabled={busyKey === r.id}
                onClick={() => handleApprove(r.id)}
              >
                Подтвердить
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
// ДОБАВЛЕНО (2026-10, запрос пользователя): статистика своего клуба.
// Экран пока СКРЫТ — кнопка "Статистика" видна только если панель открыта
// по адресу с ?stats=1 (решение пользователя: "подготовить, проверить, но
// не включать, пока всё не закончим").
const STATS_ENABLED = new URLSearchParams(window.location.search).has("stats");

function statsDay(offsetDays) {
  // "Клубный день" начинается в 08:00 — до утра считается вчерашний вечер.
  const d = new Date(Date.now() - 8 * 3600 * 1000);
  d.setDate(d.getDate() + offsetDays);
  const pad = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

const STATS_PERIODS = [
  { key: "today", label: "Сегодня", from: () => statsDay(0), to: () => statsDay(0) },
  { key: "yesterday", label: "Вчера", from: () => statsDay(-1), to: () => statsDay(-1) },
  { key: "week", label: "7 дней", from: () => statsDay(-6), to: () => statsDay(0) },
  { key: "month", label: "30 дней", from: () => statsDay(-29), to: () => statsDay(0) },
];

function statsMoney(value) {
  return Number(value || 0).toLocaleString("ru-RU", { maximumFractionDigits: 2 });
}

function StatsDelta({ current, previous }) {
  if (!previous) return <span className="stats-delta">—</span>;
  const diff = Math.round(((current - previous) / previous) * 100);
  const cls = diff > 0 ? "stats-delta stats-delta--up" : diff < 0 ? "stats-delta stats-delta--down" : "stats-delta";
  return <span className={cls}>{diff > 0 ? "+" : ""}{diff}%</span>;
}

function StatsTiles({ items }) {
  return (
    <div className="stats-tiles">
      {items.map((item) => (
        <div key={item.label} className="stats-tile">
          <div className="stats-tile__value">{item.value}</div>
          <div className="stats-tile__label">{item.label}</div>
        </div>
      ))}
    </div>
  );
}

function StatsTable({ head, rows, empty }) {
  if (!rows || rows.length === 0) return <p className="empty-hint">{empty || "Нет данных за период."}</p>;
  return (
    <table className="stats-table">
      <thead>
        <tr>{head.map((h) => <th key={h}>{h}</th>)}</tr>
      </thead>
      <tbody>
        {rows.map((row, i) => (
          <tr key={i}>{row.map((cell, j) => <td key={j}>{cell}</td>)}</tr>
        ))}
      </tbody>
    </table>
  );
}

function StatsBars({ rows }) {
  const max = Math.max(1, ...rows.map((r) => r.count));
  return (
    <div className="stats-bars">
      {rows.map((r) => (
        <div key={r.label} className="stats-bars__row">
          <span className="stats-bars__label">{r.label}</span>
          <span className="stats-bars__track">
            <span className="stats-bars__fill" style={{ width: `${(r.count / max) * 100}%` }} />
          </span>
          <span className="stats-bars__count">{r.count}</span>
        </div>
      ))}
    </div>
  );
}

function StatsPanel({ token, clubId }) {
  const [period, setPeriod] = useState("today");
  const [from, setFrom] = useState(statsDay(0));
  const [to, setTo] = useState(statsDay(0));
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    api.getClubStats(token, clubId, from, to)
      .then((result) => {
        if (cancelled) return;
        setData(result);
        setError(null);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof ApiError ? err.message : String(err));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [token, clubId, from, to]);

  function choosePeriod(p) {
    setPeriod(p.key);
    setFrom(p.from());
    setTo(p.to());
  }

  const ev = data?.evening;
  const cmp = data?.compare;

  return (
    <main className="app-main stats-panel">
      <section>
        <h2>Статистика клуба</h2>
        <div className="guest-type-filters">
          {STATS_PERIODS.map((p) => (
            <button
              key={p.key}
              type="button"
              className={`btn-link${period === p.key ? " guest-type-filters__active" : ""}`}
              onClick={() => choosePeriod(p)}
            >
              {p.label}
            </button>
          ))}
          <label className="stats-date">
            с <input type="date" value={from} onChange={(e) => { setPeriod("custom"); setFrom(e.target.value); }} />
          </label>
          <label className="stats-date">
            по <input type="date" value={to} onChange={(e) => { setPeriod("custom"); setTo(e.target.value); }} />
          </label>
        </div>
        <p className="empty-hint">
          Вечер считается с 08:00 до 08:00 — песни после полуночи относятся к тому же вечеру. Суммы — по ценам категорий
          спетых песен.
        </p>
        {error && <div className="banner banner--error">{error}</div>}
        {loading && !data && <p className="empty-hint">Загрузка…</p>}
      </section>

      {data && (
        <>
          <section>
            <h2>Итоги периода</h2>
            <StatsTiles
              items={[
                { label: "Спето песен", value: ev.sung },
                { label: "Заказано", value: ev.ordered },
                { label: "Отклонено", value: ev.rejected },
                { label: "Ждут очереди", value: ev.waiting },
                { label: "Столов пело", value: ev.tables },
                { label: "Гостей пело", value: ev.singers },
                { label: "Сумма", value: statsMoney(ev.revenue) },
                { label: "от VIP", value: statsMoney(ev.revenue_vip) },
                { label: "от обычных", value: statsMoney(ev.revenue_regular) },
                { label: "В среднем на стол", value: statsMoney(ev.avg_table) },
              ]}
            />
            {ev.top_table && (
              <p>
                Самый поющий стол: <b>№{ev.top_table.table_no}</b> — {ev.top_table.songs} песен, {statsMoney(ev.top_table.sum)}
              </p>
            )}
            {ev.top_guest && (
              <p>
                Самый активный гость: <b>{ev.top_guest.name}</b> — {ev.top_guest.songs} песен, {statsMoney(ev.top_guest.sum)}
              </p>
            )}
          </section>

          <section>
            <h2>Сравнение с прошлым периодом</h2>
            <p className="empty-hint">Прошлый период: {cmp.previous_from} — {cmp.previous_to}</p>
            <StatsTable
              head={["", "Сейчас", "Было", "Изменение"]}
              rows={[
                ["Спето песен", cmp.current.sung, cmp.previous.sung, <StatsDelta current={cmp.current.sung} previous={cmp.previous.sung} />],
                ["Сумма", statsMoney(cmp.current.revenue), statsMoney(cmp.previous.revenue), <StatsDelta current={cmp.current.revenue} previous={cmp.previous.revenue} />],
                ["Гостей пело", cmp.current.guests, cmp.previous.guests, <StatsDelta current={cmp.current.guests} previous={cmp.previous.guests} />],
              ]}
            />
          </section>

          <section>
            <h2>Гости</h2>
            <StatsTiles
              items={[
                { label: "Всего в базе", value: data.guests.total },
                { label: "VIP", value: data.guests.vip },
                { label: "Обычных", value: data.guests.regular },
                { label: "Были за период", value: data.guests.active_in_period },
                { label: "Новых", value: data.guests.new_in_period },
                { label: "Вернулись", value: data.guests.returning_in_period },
              ]}
            />
            <h3>Топ гостей по песням</h3>
            <StatsTable
              head={["Гость", "Песен", "Сумма"]}
              rows={data.guests.top_by_songs.map((g) => [g.name, g.songs, statsMoney(g.sum)])}
            />
            <h3>Топ гостей по сумме</h3>
            <StatsTable
              head={["Гость", "Песен", "Сумма"]}
              rows={data.guests.top_by_sum.map((g) => [g.name, g.songs, statsMoney(g.sum)])}
            />
            <h3>VIP, которых не было больше {data.guests.lapsed_vip_days} дней</h3>
            <StatsTable
              head={["Гость", "Последний визит", "Баланс"]}
              rows={data.guests.lapsed_vips.map((g) => [
                g.name,
                g.last_visit ? new Date(g.last_visit).toLocaleDateString("ru-RU") : "ни разу не заказывал",
                statsMoney(g.balance),
              ])}
              empty="Все VIP приходили недавно."
            />
          </section>

          <section>
            <h2>VIP</h2>
            <StatsTiles
              items={[
                { label: "VIP-гостей", value: data.vip.count },
                { label: "На балансах сейчас", value: statsMoney(data.vip.balance_total) },
                { label: "Пополнено за период", value: statsMoney(data.vip.topups) },
                { label: "Потрачено за период", value: statsMoney(data.vip.spent) },
                { label: "Заявок стать VIP", value: data.vip.requests },
                { label: "Одобрено", value: data.vip.requests_approved },
              ]}
            />
          </section>

          <section>
            <h2>Песни по категориям</h2>
            <StatsTable
              head={["Категория", "Песен", "Сумма"]}
              rows={[
                ...data.songs.by_category.map((c) => [c.name, c.songs, statsMoney(c.sum)]),
                ...(data.songs.by_category.length > 0 ? [[<b>Итого</b>, <b>{ev.sung}</b>, <b>{statsMoney(ev.revenue)}</b>]] : []),
              ]}
            />
          </section>

          <section>
            <h2>Топ песен</h2>
            <StatsTable
              head={["Исполнитель", "Песня", "Раз"]}
              rows={data.songs.top_songs.map((s) => [s.artist || "—", s.title, s.count])}
            />
            <h3>Топ исполнителей</h3>
            <StatsTable head={["Исполнитель", "Раз"]} rows={data.songs.top_artists.map((a) => [a.artist, a.count])} />
            <StatsTiles
              items={[
                { label: "Заказов с тональностью", value: data.songs.tone_total },
                { label: "Тон ниже", value: data.songs.tone_down },
                { label: "Тон выше", value: data.songs.tone_up },
                { label: "Название исправлял KJ", value: data.songs.renamed_by_kj },
              ]}
            />
          </section>

          <section>
            <h2>Откуда заказы</h2>
            <StatsTiles
              items={[
                { label: "Заказали гости", value: data.how.by_guests },
                { label: "Добавил KJ вручную", value: data.how.by_kj },
                { label: "Из VirtualDJ без заказа", value: data.how.from_virtualdj },
                { label: "«Готово» автоматически", value: data.how.done_auto },
                { label: "«Готово» вручную", value: data.how.done_manual },
              ]}
            />
          </section>

          <section>
            <h2>Время</h2>
            <p>
              Среднее ожидание от заказа до выхода:{" "}
              <b>{data.timing.avg_wait_minutes == null ? "—" : `${data.timing.avg_wait_minutes} мин`}</b>
            </p>
            <h3>Заказы по часам</h3>
            {data.timing.by_hour.length === 0 ? (
              <p className="empty-hint">Нет данных за период.</p>
            ) : (
              <StatsBars rows={data.timing.by_hour.map((h) => ({ label: `${String(h.hour).padStart(2, "0")}:00`, count: h.count }))} />
            )}
            <h3>Заказы по дням недели</h3>
            <StatsBars rows={data.timing.by_weekday.map((d) => ({ label: d.day, count: d.count }))} />
          </section>
        </>
      )}
    </main>
  );
}

// ДОБАВЛЕНО (2026-10, запрос пользователя): KJ управляет списками гостя
// над живой очередью — "История за час", "Популярные", "Новинки".
const SONG_ADMIN_TABS = [
  { key: "recent", label: "История за час" },
  { key: "popular", label: "Популярные" },
  { key: "new", label: "Новинки" },
];

function SongListsAdminPanel({ token }) {
  const [tab, setTab] = useState("recent");
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const [newTitle, setNewTitle] = useState("");
  const [newArtist, setNewArtist] = useState("");

  const load = useCallback(async () => {
    try {
      setData(await api.getSongListsAdmin(token));
      setError(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    }
  }, [token]);

  useEffect(() => {
    load();
    const id = setInterval(load, 30000);
    return () => clearInterval(id);
  }, [load]);

  async function run(action) {
    setBusy(true);
    setError(null);
    try {
      await action();
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  function removeItem(song) {
    if (tab === "new") return run(() => api.setNewSong(token, song.song_title, song.artist, false));
    if (tab === "popular") {
      return run(() => api.hideSongListItem(token, { kind: "popular", song_title: song.song_title, artist: song.artist || null }));
    }
    return run(() => api.hideSongListItem(token, { kind: "history", order_id: song.order_id }));
  }

  const items = (data && data[tab]) || [];
  const label = (s) => (s.artist ? `${s.artist} — ${s.song_title}` : s.song_title);

  return (
    <main className="app-main">
      <section>
        <h2>Списки для гостей</h2>
        <p className="empty-hint">
          То, что гость видит над активной очередью. Крестик убирает песню у гостей. В чеках и статистике ничего не меняется.
        </p>
        <div className="guest-type-filters">
          {SONG_ADMIN_TABS.map((t) => (
            <button
              key={t.key}
              type="button"
              className={`btn-link${tab === t.key ? " guest-type-filters__active" : ""}`}
              onClick={() => setTab(t.key)}
            >
              {t.label}
            </button>
          ))}
        </div>
        {error && <div className="banner banner--error">{error}</div>}
        {!data && !error && <p className="empty-hint">Загрузка…</p>}
        {tab === "new" && (
          <form
            className="song-admin__add"
            onSubmit={(e) => {
              e.preventDefault();
              if (!newTitle.trim()) return;
              run(async () => {
                await api.setNewSong(token, newTitle.trim(), newArtist.trim() || null, true);
                setNewTitle("");
                setNewArtist("");
              });
            }}
          >
            <input type="text" placeholder="Исполнитель" value={newArtist} onChange={(e) => setNewArtist(e.target.value)} />
            <input type="text" placeholder="Название песни" value={newTitle} onChange={(e) => setNewTitle(e.target.value)} />
            <button type="submit" className="btn-link" disabled={busy || !newTitle.trim()}>
              Добавить в новинки
            </button>
          </form>
        )}
        {data && items.length === 0 && <p className="empty-hint">Список пуст.</p>}
        {items.length > 0 && (
          <ol className="song-admin__list">
            {items.map((s, i) => (
              <li key={`${tab}-${s.order_id ?? s.id ?? i}-${s.song_title}`} className="song-admin__row">
                <span>{label(s)}</span>
                {tab === "popular" && s.count ? <span className="empty-hint"> · {s.count} раз</span> : null}
                <button
                  type="button"
                  className="song-admin__remove"
                  title="Убрать у гостей"
                  disabled={busy}
                  onClick={() => removeItem(s)}
                >
                  ✕
                </button>
              </li>
            ))}
          </ol>
        )}
        {tab === "popular" && data && data.hidden_popular.length > 0 && (
          <>
            <h3>Скрытые из «Популярных»</h3>
            <ul className="song-admin__list">
              {data.hidden_popular.map((h) => (
                <li key={h.id} className="song-admin__row">
                  <span>{label(h)}</span>
                  <button type="button" className="btn-link" disabled={busy} onClick={() => run(() => api.unhideSongListItem(token, h.id))}>
                    Вернуть
                  </button>
                </li>
              ))}
            </ul>
          </>
        )}
      </section>
    </main>
  );
}

// ДОБАВЛЕНО (2026-10): переключатель "Общий чат" (ссылка на группу в
// Telegram у гостя) — Вкл/Откл.
function GeneralChatToggle({ token }) {
  const [enabled, setEnabled] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  useEffect(() => {
    api.getGeneralChat(token)
      .then((data) => setEnabled(Boolean(data?.enabled)))
      .catch((err) => setError(err.message));
  }, [token]);
  async function toggle() {
    setBusy(true);
    setError(null);
    try {
      const data = await api.setGeneralChat(token, !enabled);
      setEnabled(Boolean(data?.enabled));
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="order-change-requests-panel">
      <h2>Общий чат (Telegram): {enabled == null ? "…" : enabled ? "Вкл" : "Откл"}</h2>
      {error && <div className="banner banner--error">{error}</div>}
      <button type="button" className="btn-link" disabled={busy || enabled == null} onClick={toggle}>
        {enabled ? "Отключить" : "Включить"}
      </button>
    </section>
  );
}

function AdminMessagesPanel({ token, clubId, socket }) {
  // ДОБАВЛЕНО (2026-10-03, запрос пользователя "в админке есть панель
  // управления KJ... сообщения приходят KJ в его панель сообщения. Но
  // они по умолчанию сверху и в приоритете" + "режим переписки 2 да
  // висеть пока не откроет да") — двусторонняя переписка с
  // администрацией, отдельная от чата с гостем (KjChatPanel ниже).
  const [messages, setMessages] = useState(null);
  const [loadError, setLoadError] = useState(null);
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const [sendError, setSendError] = useState(null);

  async function reload() {
    try {
      const data = await api.listAdminMessages(token, clubId);
      setMessages(data);
      setLoadError(null);
      await api.markAdminMessagesRead(token, clubId);
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
    const onMessage = (message) => {
      setMessages((prev) => {
        const list = prev || [];
        return list.some((m) => m.id === message.id) ? list : [...list, message];
      });
      if (message.from_admin) {
        api.markAdminMessagesRead(token, clubId).catch(() => {});
      }
    };
    socket.on("admin_message", onMessage);
    return () => {
      socket.off("admin_message", onMessage);
    };
  }, [socket, token, clubId]);

  async function handleSend() {
    const text = draft.trim();
    if (!text) return;
    setSending(true);
    setSendError(null);
    try {
      await api.sendAdminMessage(token, clubId, text);
      setDraft("");
      await reload();
    } catch (err) {
      setSendError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setSending(false);
    }
  }

  // ДОБАВЛЕНО (2026-10): удаление — насовсем, у KJ и у администрации.
  async function handleDelete(messageId) {
    try {
      await api.deleteAdminMessage(token, clubId, messageId);
      setMessages((prev) => (prev || []).filter((m) => m.id !== messageId));
    } catch (err) {
      setSendError(err instanceof ApiError ? err.message : String(err));
    }
  }

  async function handleClearAll() {
    if (!window.confirm("Удалить всю переписку с администрацией? Она пропадёт и у администрации.")) return;
    try {
      await api.clearAdminMessages(token, clubId);
      setMessages([]);
    } catch (err) {
      setSendError(err instanceof ApiError ? err.message : String(err));
    }
  }

  if (loadError) return <div className="banner banner--error">{loadError}</div>;

  return (
    <section className="order-change-requests-panel admin-messages-panel">
      <h2>📢 Сообщения от администрации</h2>
      {messages && messages.length > 0 && (
        <button type="button" className="btn-link" onClick={handleClearAll}>
          Очистить всё
        </button>
      )}
      {!messages ? (
        <p className="empty-hint">Загрузка…</p>
      ) : messages.length === 0 ? (
        <p className="empty-hint">Сообщений пока нет.</p>
      ) : (
        <ul className="vip-list">
          {messages.map((m) => (
            <li key={m.id} className="vip-row chat-thread-row">
              <span>{m.from_admin ? "Администрация" : "Вы"}:</span>
              <span>{m.message_text}</span>
              <button type="button" className="btn-link" title="Удалить сообщение" onClick={() => handleDelete(m.id)}>
                ✕
              </button>
            </li>
          ))}
        </ul>
      )}
      {sendError && <div className="banner banner--error">{sendError}</div>}
      <div className="vip-row__actions chat-reply-row">
        <input
          className="vip-amount-input chat-reply-input"
          type="text"
          placeholder="Сообщение администрации…"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
        />
        <button type="button" className="btn btn--accent chat-reply-send" disabled={sending || !draft.trim()} onClick={handleSend}>
          Отправить
        </button>
      </div>
    </section>
  );
}

// ДОБАВЛЕНО (2026-10-09, запрос пользователя): KJ предлагает улучшение
// приложения. Уходит администрации отдельно от переписки; в ответ сразу
// приходит автоответ в "Сообщения от администрации".
function SuggestionPanel({ token, clubId }) {
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState(null);
  const [sent, setSent] = useState(false);

  async function handleSend() {
    const text = draft.trim();
    if (!text) return;
    setSending(true);
    setError(null);
    setSent(false);
    try {
      await api.sendSuggestion(token, clubId, text);
      setDraft("");
      setSent(true);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setSending(false);
    }
  }

  return (
    <section className="order-change-requests-panel suggestion-panel">
      <h2>💡 Предложить улучшение</h2>
      <p className="empty-hint">Идея, как сделать приложение удобнее? Напишите — администрация её получит.</p>
      {error && <div className="banner banner--error">{error}</div>}
      {sent && <p className="suggestion-panel__sent">✅ Предложение отправлено администрации.</p>}
      <div className="suggestion-panel__form">
        <textarea
          className="suggestion-panel__input"
          rows={3}
          placeholder="Ваше предложение…"
          value={draft}
          onChange={(e) => {
            setDraft(e.target.value);
            setSent(false);
          }}
        />
        <button type="button" className="btn btn--accent" disabled={sending || !draft.trim()} onClick={handleSend}>
          {sending ? "Отправляем…" : "Отправить"}
        </button>
      </div>
    </section>
  );
}

function KjChatPanel({ token, clubId, socket }) {
  // ДОБАВЛЕНО (2026-10-01, запрос пользователя "кнопка Сообщения,
  // собирающая все обращения, включая личный чат с гостями") — сам чат
  // (ChatMessage, GET/POST /api/kj/chat) существовал на бэкенде уже
  // давно (см. models.ChatMessage, routes/kj.py::list_chat/reply_chat) и
  // был доступен гостю (Guest App::ChatPanel), но у KJ Panel до сих пор не
  // было экрана, чтобы это читать и отвечать — только эта панель.
  const [messages, setMessages] = useState(null);
  const [loadError, setLoadError] = useState(null);
  const [selectedGuestId, setSelectedGuestId] = useState(null);
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const [sendError, setSendError] = useState(null);
  // ДОБАВЛЕНО (2026-10-04, запрос пользователя "нигде нет кнопки удаления
  // сообщений и очистки чата") — deletingId блокирует кнопку только у
  // своего сообщения, clearing — у кнопки "Очистить чат" целиком.
  const [deletingId, setDeletingId] = useState(null);
  const [clearing, setClearing] = useState(false);

  async function reload() {
    try {
      const data = await api.listChat(token, clubId);
      setMessages(data);
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
    const onMessage = (message) => {
      setMessages((prev) => {
        const list = prev || [];
        return list.some((m) => m.id === message.id) ? list : [...list, message];
      });
    };
    socket.on("chat_message", onMessage);
    return () => {
      socket.off("chat_message", onMessage);
    };
  }, [socket]);

  async function handleSend() {
    const text = draft.trim();
    if (!text || selectedGuestId == null) return;
    setSending(true);
    setSendError(null);
    try {
      await api.replyChat(token, clubId, selectedGuestId, text);
      setDraft("");
      await reload();
    } catch (err) {
      setSendError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setSending(false);
    }
  }

  async function handleDeleteMessage(messageId) {
    setDeletingId(messageId);
    setSendError(null);
    try {
      await api.deleteChatMessage(token, messageId);
      setMessages((prev) => (prev || []).filter((m) => m.id !== messageId));
    } catch (err) {
      setSendError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setDeletingId(null);
    }
  }

  async function handleClearChat() {
    if (selectedGuestId == null) return;
    if (!window.confirm("Удалить всю переписку с этим гостем? Это действие нельзя отменить.")) return;
    setClearing(true);
    setSendError(null);
    try {
      await api.clearChat(token, clubId, selectedGuestId);
      setMessages((prev) => (prev || []).filter((m) => (m.guest_id ?? String(m.telegram_user_id)) !== selectedGuestId));
      setSelectedGuestId(null);
    } catch (err) {
      setSendError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setClearing(false);
    }
  }

  if (loadError) return <div className="banner banner--error">{loadError}</div>;
  if (!messages) return <p className="empty-hint">Загрузка…</p>;

  // Группируем по гостю — тот же приём, что докстринг list_chat на
  // бэкенде предполагает делать на фронтенде (данных в каждом сообщении
  // достаточно: telegram_user_id/table_no).
  const threads = new Map();
  for (const m of messages) {
    // guest_id — номер гостя строкой (см. ChatMessage.to_dict): числовой
    // telegram_user_id у больших номеров округляется в браузере.
    const key = m.guest_id ?? String(m.telegram_user_id);
    const existing = threads.get(key);
    if (!existing || m.created_at > existing.lastMessage.created_at) {
      threads.set(key, { guestId: key, tableNo: m.table_no, lastMessage: m });
    }
  }
  const threadList = [...threads.values()].sort(
    (a, b) => new Date(b.lastMessage.created_at) - new Date(a.lastMessage.created_at),
  );

  if (threadList.length === 0) return null;

  if (selectedGuestId == null) {
    return (
      <section className="order-change-requests-panel">
        <h2>💬 Сообщения от гостей ({threadList.length})</h2>
        <ul className="vip-list">
          {threadList.map((t) => (
            <li key={t.guestId} className="vip-row">
              <span>
                {t.lastMessage.from_guest ? "🆕 " : ""}
                Стол {t.tableNo ?? "—"} · гость #{t.guestId}: {t.lastMessage.message_text || (t.lastMessage.image_data_url ? "📷 Скриншот" : "")}
                {t.lastMessage.service_name ? ` (категория: ${t.lastMessage.service_name})` : ""}
              </span>
              <span className="vip-row__actions">
                <button type="button" className="btn-link" onClick={() => setSelectedGuestId(t.guestId)}>
                  Открыть
                </button>
              </span>
            </li>
          ))}
        </ul>
      </section>
    );
  }

  const thread = messages
    .filter((m) => (m.guest_id ?? String(m.telegram_user_id)) === selectedGuestId)
    .sort((a, b) => new Date(a.created_at) - new Date(b.created_at));

  return (
    <section className="order-change-requests-panel">
      <h2>💬 Переписка — гость #{selectedGuestId}</h2>
      <div className="chat-thread-header-actions">
        <button type="button" className="btn-link" onClick={() => setSelectedGuestId(null)}>
          ← Все сообщения
        </button>
        <button type="button" className="btn-link btn-link--danger" disabled={clearing} onClick={handleClearChat}>
          {clearing ? "Очищаем…" : "🗑 Очистить чат"}
        </button>
      </div>
      <ul className="vip-list">
        {thread.map((m) => (
          <li key={m.id} className="vip-row chat-thread-row">
            <span>{m.from_guest ? "Гость" : "Вы"}:</span>
            {m.service_name && <span className="chat-thread-row__category">Категория: {m.service_name}</span>}
            {m.image_data_url && (
              <img src={m.image_data_url} alt="Скриншот от гостя" className="chat-thread-row__image" />
            )}
            {m.message_text && <span>{m.message_text}</span>}
            <button
              type="button"
              className="btn-link btn-link--danger chat-thread-row__delete"
              disabled={deletingId === m.id}
              onClick={() => handleDeleteMessage(m.id)}
            >
              {deletingId === m.id ? "Удаляем…" : "✕ Удалить"}
            </button>
          </li>
        ))}
      </ul>
      {sendError && <div className="banner banner--error">{sendError}</div>}
      {/* ИЗМЕНЕНО (запрос пользователя 2026-10-01, "поле ввода длиннее,
      кнопка меньше") — раньше здесь переиспользовались .vip-row__actions/
      .vip-amount-input, которые другие места (пополнение баланса VIP,
      кэшбэк) используют с узким полем под несколько кнопок рядом. Для
      ответа гостю это неудобно — сделан отдельный класс-модификатор
      chat-reply-row/chat-reply-input/chat-reply-send, не трогающий те
      другие места. */}
      <div className="vip-row__actions chat-reply-row">
        <input
          className="vip-amount-input chat-reply-input"
          type="text"
          placeholder="Ответ гостю…"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
        />
        <button type="button" className="btn btn--accent chat-reply-send" disabled={sending || !draft.trim()} onClick={handleSend}>
          Отправить
        </button>
      </div>
    </section>
  );
}

function VipRequestsPanel({ token, clubId, socket }) {
  // ДОБАВЛЕНО (2026-10-01, запрос пользователя "кнопка Сообщения,
  // собирающая все обращения") — вынесено из VipPanel в отдельную панель,
  // чтобы показывать вместе со всеми остальными обращениями гостей на
  // экране "Сообщения", а не прятать внутри вкладки VIP. Тот же паттерн
  // списка + сокет-событий, что и OrderChangeRequestsPanel выше.
  const [pending, setPending] = useState(null);
  const [actionError, setActionError] = useState(null);
  const [busyKey, setBusyKey] = useState(null);

  async function reload() {
    try {
      const data = await api.listVipRequests(token, clubId, "pending");
      setPending(data);
    } catch {
      // Тихо — как и в OrderChangeRequestsPanel выше.
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
    setBusyKey(requestId);
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
    setBusyKey(requestId);
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

  if (!pending || pending.length === 0) return null;

  return (
    <section className="order-change-requests-panel">
      <h2>⭐ Заявки на VIP ({pending.length})</h2>
      {actionError && <div className="banner banner--error">{actionError}</div>}
      <ul className="vip-list">
        {pending.map((r) => (
          <li key={r.id} className="vip-row">
            <span>Стол {r.table_no ?? "—"} · гость #{r.telegram_user_id}</span>
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

function VipTopupRequestsPanel({ token, clubId, socket }) {
  // ДОБАВЛЕНО (2026-10-01) — та же логика, что раньше жила внутри
  // VipPanel ("Запросы на пополнение баланса"), вынесена сюда по той же
  // причине, что и VipRequestsPanel выше.
  const [pending, setPending] = useState(null);
  const [actionError, setActionError] = useState(null);
  const [busyKey, setBusyKey] = useState(null);

  async function reload() {
    try {
      const data = await api.listVipTopupRequests(token, clubId);
      setPending(data);
    } catch {
      // Тихо — как и в остальных панелях списка заявок.
    }
  }

  useEffect(() => {
    reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [clubId]);

  useEffect(() => {
    if (!socket) return undefined;
    const onCreated = (topupRequest) => {
      setPending((prev) => {
        const list = prev || [];
        return list.some((r) => r.id === topupRequest.id) ? list : [...list, topupRequest];
      });
    };
    const onDecided = (topupRequest) => {
      setPending((prev) => (prev || []).filter((r) => r.id !== topupRequest.id));
    };
    socket.on("vip_topup_request_created", onCreated);
    socket.on("vip_topup_request_decided", onDecided);
    return () => {
      socket.off("vip_topup_request_created", onCreated);
      socket.off("vip_topup_request_decided", onDecided);
    };
  }, [socket]);

  async function handleResolve(requestId) {
    setBusyKey(requestId);
    setActionError(null);
    try {
      await api.resolveVipTopupRequest(token, requestId);
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
      <h2>💰 Запросы на пополнение баланса ({pending.length})</h2>
      {actionError && <div className="banner banner--error">{actionError}</div>}
      <ul className="vip-list">
        {pending.map((r) => (
          <li key={r.id} className="vip-row">
            <span>Гость #{r.guest_id}</span>
            <span className="vip-row__actions">
              <button
                type="button" className="btn btn--accent" disabled={busyKey === r.id}
                onClick={() => handleResolve(r.id)}
              >
                Обработано
              </button>
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}

// ДОБАВЛЕНО (2026-10-04, запрос пользователя "бот и приложение — два
// отдельных инструмента, что в боте то и в приложении, во вкладку VIP надо
// добавить то, что есть в боте") — перенос handlers/kj.py::
// vip_description_edit старого бота: KJ сам пишет текст про преимущества
// VIP своего клуба, гость видит его в Guest App на вкладке VIP поверх
// фиксированного списка (пополнение/кешбек/повтор песен), см.
// guest-app App.jsx::VipPanel и backend/routes/kj.py::get_vip_settings/
// update_vip_settings. По образцу TableSettingsPanel выше — одна форма,
// одна кнопка "Сохранить", пустое поле = ничего не добавлено.
function VipDescriptionPanel({ token, clubId }) {
  const [draft, setDraft] = useState("");
  const [loadError, setLoadError] = useState(null);
  const [actionError, setActionError] = useState(null);
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState(false);

  async function reload() {
    try {
      const data = await api.getVipSettings(token, clubId);
      setDraft(data.vip_description || "");
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
    setBusy(true);
    setActionError(null);
    setSaved(false);
    try {
      const data = await api.updateVipSettings(token, clubId, draft);
      setDraft(data.vip_description || "");
      setSaved(true);
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  if (loadError) return <div className="banner banner--error">{loadError}</div>;

  return (
    <section className="vip-description-panel">
      <h2>Описание VIP для гостей</h2>
      <p className="empty-hint">
        Этот текст увидит гость на кнопке «Стать VIP» — над стандартным списком (пополнение баланса,
        кешбек, повтор любимых песен). Оставьте поле пустым, если ничего добавлять не нужно.
      </p>
      {actionError && <div className="banner banner--error">{actionError}</div>}
      <form className="vip-description-form" onSubmit={handleSave}>
        <textarea
          rows={4}
          placeholder="Например: именинникам — бесплатный коктейль"
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
  );
}

function VipPanel({ token, clubId }) {
  const [clients, setClients] = useState(null);
  const [loadError, setLoadError] = useState(null);
  const [actionError, setActionError] = useState(null);
  const [busyKey, setBusyKey] = useState(null);
  const [amountDrafts, setAmountDrafts] = useState({});
  const [cashbackDrafts, setCashbackDrafts] = useState({});
  // Фото клиента (запрос пользователя 2026-10-01, "возможность должна
  // быть, но по желанию") — guestId того ряда, для которого сейчас идёт
  // загрузка, просто чтобы показать "Загружаем…" только на нужной кнопке.
  const [photoBusyId, setPhotoBusyId] = useState(null);

  async function reload() {
    try {
      const clientsData = await api.listVipClients(token, clubId);
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

  // ДОБАВЛЕНО (2026-09-29, запрос пользователя "нужна кнопка обнулить
  // баланс или сбросить баланс") — раньше обнулить баланс можно было,
  // только вписав 0 в поле "Сумма" и нажав "Установить"; теперь то же
  // самое действие одним нажатием, без поля ввода. Использует тот же
  // серверный вызов setVipBalance(...,0), что и "Установить" = 0 — то же
  // самое действие, просто без ручного набора нуля.
  async function handleZeroBalance(vipClientId) {
    setBusyKey(`zero-${vipClientId}`);
    setActionError(null);
    try {
      await api.setVipBalance(token, vipClientId, 0);
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
  // VipClient, а не отдельный флаг. ИЗМЕНЕНО (2026-09-29, решение
  // пользователя): перевод в простые теперь разрешён и с ненулевым
  // балансом — старая проверка VIP_BALANCE_NOT_ZERO (требовавшая сначала
  // обнулить баланс) убрана на сервере, поэтому упоминание "обнулите перед
  // понижением" ниже больше не актуально как обязательное условие.
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

  async function handleUploadPhoto(guestId, file) {
    setPhotoBusyId(guestId);
    setActionError(null);
    try {
      const resized = await new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onerror = () => reject(reader.error || new Error("Не удалось прочитать файл"));
        reader.onload = () => {
          const img = new Image();
          img.onerror = () => reject(new Error("Не удалось прочитать изображение"));
          img.onload = () => {
            const maxSide = 300;
            const scale = Math.min(1, maxSide / Math.max(img.width, img.height));
            const canvas = document.createElement("canvas");
            canvas.width = Math.round(img.width * scale);
            canvas.height = Math.round(img.height * scale);
            canvas.getContext("2d").drawImage(img, 0, 0, canvas.width, canvas.height);
            resolve(canvas.toDataURL("image/jpeg", 0.8));
          };
          img.src = reader.result;
        };
        reader.readAsDataURL(file);
      });
      await api.setGuestPhoto(token, guestId, resized);
      await reload();
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setPhotoBusyId(null);
    }
  }

  if (loadError) return <div className="banner banner--error">{loadError}</div>;
  if (!clients) return <p className="empty-hint">Загрузка…</p>;

  return (
    <div className="vip-panel">
      <VipDescriptionPanel token={token} clubId={clubId} />

      {actionError && <div className="banner banner--error">{actionError}</div>}

      <section>
        <h2>VIP-клиенты ({clients.length})</h2>
        {clients.length === 0 && <p className="empty-hint">VIP-клиентов пока нет.</p>}
        <ul className="vip-list">
          {clients.map((c) => (
            <li key={c.id} className="vip-row vip-row--client">
              <div className="vip-row__identity">
                {c.photo_data_url ? (
                  <img src={c.photo_data_url} alt="" className="vip-row__photo" />
                ) : (
                  <span className="vip-row__photo vip-row__photo--placeholder">👤</span>
                )}
                <span>
                  {c.display_name || `Гость #${c.telegram_user_id}`} · баланс <strong>{c.balance} MDL</strong>
                  {c.is_blocked && <span className="guest-type-badge guest-type-badge--blocked"> 🚫 Заблокирован</span>}
                </span>
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
                <button type="button" className="btn-link" disabled={busyKey === `zero-${c.id}`} onClick={() => handleZeroBalance(c.id)}>
                  0️⃣ Обнулить баланс
                </button>
                {/* Фото клиента необязательное (запрос пользователя
                2026-10-01) — обычная label-обёртка над скрытым input,
                чтобы не городить отдельный модальный выбор файла. */}
                <label className="btn-link vip-photo-upload">
                  {photoBusyId === c.telegram_user_id ? "Загружаем…" : "📷 Фото"}
                  <input
                    type="file"
                    accept="image/*"
                    disabled={photoBusyId === c.telegram_user_id}
                    onChange={(e) => {
                      const file = e.target.files[0];
                      e.target.value = "";
                      if (file) handleUploadPhoto(c.telegram_user_id, file);
                    }}
                  />
                </label>
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
// ДОБАВЛЕНО (2026-09-24, запрос пользователя "нужно добавить варианты
// очереди"): значения того же поля Club.queue_mode, что и на бэкенде (см.
// services/table_board_service.py::QUEUE_MODE_MANUAL/QUEUE_MODE_SEQUENTIAL) —
// подписи для быстрого тумблера на вкладке "Столы". Режим меняет только
// отображение (порядок/номер на карточках KJ и номер очереди у гостя), а
// не саму механику постановки песни — KJ по-прежнему сам вручную ставит
// песню в VirtualDJ/"Добавить песню", когда сочтёт нужным.
const QUEUE_MODE_OPTIONS = [
  { value: "manual", label: "Как решает диджей", hint: "Порядок ведёт сам KJ, номера очереди не показываются" },
  { value: "sequential", label: "Последовательно", hint: "Круговой обход столов по номерам, CRAZY — всегда первой" },
];

// ДОБАВЛЕНО (2026-10, запрос пользователя): автозакрытие столов в заданное
// время по часам этого компьютера.
function AutoClosePanel({ token }) {
  const [enabled, setEnabled] = useState(false);
  const [time, setTime] = useState("07:00");
  const [loaded, setLoaded] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    api.getAutoClose(token)
      .then((data) => {
        setEnabled(Boolean(data?.enabled));
        setTime(data?.time || "07:00");
        setLoaded(true);
      })
      .catch((err) => setError(err instanceof ApiError ? err.message : String(err)));
  }, [token]);

  async function save(nextEnabled, nextTime) {
    setBusy(true);
    setError(null);
    setSaved(false);
    try {
      const data = await api.setAutoClose(token, nextEnabled, nextTime);
      setEnabled(Boolean(data?.enabled));
      setTime(data?.time || nextTime);
      setSaved(true);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="table-settings-panel">
      <section>
        <h2>Автозакрытие столов: {!loaded ? "…" : enabled ? "Вкл" : "Откл"}</h2>
        <p className="empty-hint">
          В указанное время все столы закроются сами — так же, как кнопкой «Закрыть все столы». Время — по часам этого
          компьютера. Если в последние 30 минут в клубе ещё заказывали или пели, закрытие подождёт, пока станет тихо.
        </p>
        {error && <div className="banner banner--error">{error}</div>}
        <div className="guest-type-filters">
          <label className="stats-date">
            Время{" "}
            <input type="time" value={time} disabled={!loaded || busy} onChange={(e) => setTime(e.target.value)} />
          </label>
          <button type="button" className="btn-link" disabled={!loaded || busy || !time} onClick={() => save(enabled, time)}>
            Сохранить время
          </button>
          <button type="button" className="btn-link" disabled={!loaded || busy || !time} onClick={() => save(!enabled, time)}>
            {enabled ? "Отключить" : "Включить"}
          </button>
          {saved && <span className="empty-hint">Сохранено</span>}
        </div>
      </section>
    </div>
  );
}

function TableSettingsPanel({ token, clubId }) {
  const [tableCountDraft, setTableCountDraft] = useState("");
  const [songsPerTableDraft, setSongsPerTableDraft] = useState("");
  const [queueMode, setQueueMode] = useState("manual");
  const [queueModeBusy, setQueueModeBusy] = useState(false);
  const [queueModeError, setQueueModeError] = useState(null);
  const [loadError, setLoadError] = useState(null);
  const [actionError, setActionError] = useState(null);
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState(false);

  async function reload() {
    try {
      const data = await api.getTableSettings(token, clubId);
      setTableCountDraft(data.table_count == null ? "" : String(data.table_count));
      setSongsPerTableDraft(data.songs_per_table == null ? "" : String(data.songs_per_table));
      setQueueMode(data.queue_mode || "manual");
      setLoadError(null);
    } catch (err) {
      setLoadError(err instanceof ApiError ? err.message : String(err));
    }
  }

  // Быстрый тумблер (запрос пользователя: "Быстрый тумблер на вкладке
  // Столы") — сохраняется сразу по клику, отдельно от формы
  // table_count/songs_per_table ниже и её кнопки "Сохранить"; шлёт только
  // { queue_mode }, не трогая остальные настройки (патч-семантика бэкенда,
  // см. api.js::updateTableSettings).
  async function handleQueueModeChange(nextMode) {
    if (nextMode === queueMode) return;
    const previous = queueMode;
    setQueueMode(nextMode);
    setQueueModeBusy(true);
    setQueueModeError(null);
    try {
      const data = await api.updateTableSettings(token, clubId, { queue_mode: nextMode });
      setQueueMode(data.queue_mode || "manual");
    } catch (err) {
      setQueueMode(previous);
      setQueueModeError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setQueueModeBusy(false);
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
        <h2>Режим очереди</h2>
        <p className="empty-hint">
          Как показывать порядок исполнения на карточках столов и номер очереди у гостя. Ни один из режимов
          не мешает KJ вручную поставить любую песню в VirtualDJ в любой момент.
        </p>
        {queueModeError && <div className="banner banner--error">{queueModeError}</div>}
        <div className="queue-mode-toggle">
          {QUEUE_MODE_OPTIONS.map((option) => (
            <button
              key={option.value}
              type="button"
              className={`queue-mode-toggle__btn ${queueMode === option.value ? "queue-mode-toggle__btn--active" : ""}`}
              disabled={queueModeBusy}
              onClick={() => handleQueueModeChange(option.value)}
              title={option.hint}
            >
              {option.label}
            </button>
          ))}
        </div>
      </section>
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

// Уменьшение фото перед отправкой (до 300px по большей стороне, JPEG) —
// общая функция для VipPanel и GuestCard (карточка гостя, запрос
// пользователя 2026-10: KJ сам загружает фото гостя).
function resizeImageToDataUrl(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(reader.error || new Error("Не удалось прочитать файл"));
    reader.onload = () => {
      const img = new Image();
      img.onerror = () => reject(new Error("Не удалось прочитать изображение"));
      img.onload = () => {
        const maxSide = 300;
        const scale = Math.min(1, maxSide / Math.max(img.width, img.height));
        const canvas = document.createElement("canvas");
        canvas.width = Math.round(img.width * scale);
        canvas.height = Math.round(img.height * scale);
        canvas.getContext("2d").drawImage(img, 0, 0, canvas.width, canvas.height);
        resolve(canvas.toDataURL("image/jpeg", 0.8));
      };
      img.src = reader.result;
    };
    reader.readAsDataURL(file);
  });
}

function GuestCard({ token, clubId, guestId, onBack, onChanged }) {
  const [guest, setGuest] = useState(null);
  const [loadError, setLoadError] = useState(null);
  const [actionError, setActionError] = useState(null);
  const [busy, setBusy] = useState(false);
  const [nameDraft, setNameDraft] = useState("");
  const [nameBusy, setNameBusy] = useState(false);
  const [photoBusy, setPhotoBusy] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [history, setHistory] = useState(null);
  const [historyError, setHistoryError] = useState(null);
  const [historyPeriod, setHistoryPeriod] = useState("week"); // today|week|month|year|custom
  const [customFrom, setCustomFrom] = useState("");
  const [customTo, setCustomTo] = useState("");
  // ДОБАВЛЕНО (2026-10, запрос пользователя: "нет кнопки Написать гостю,
  // KJ должен иметь возможность связи с гостем") — переписка с этим гостем
  // прямо в его карточке; та же переписка, что и на экране "Сообщения".
  const [chatOpen, setChatOpen] = useState(false);
  const [chatMessages, setChatMessages] = useState(null);
  const [chatDraft, setChatDraft] = useState("");
  const [chatBusy, setChatBusy] = useState(false);
  const [chatError, setChatError] = useState(null);

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

  useEffect(() => {
    if (guest) setNameDraft(guest.display_name || "");
  }, [guest]);

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

  // ИЗМЕНЕНО (2026-09-29, жалоба пользователя: нажал "Закрыть стол",
  // ожидая только освободить стол, а гостя заодно молча заблокировало —
  // "Заблокировать и Закрыть Стол. Это две отдельные кнопки"): раньше
  // (с 2026-09-19) это был один клик, который убирал гостя со стола И
  // блокировал его сразу. Теперь это только освобождает стол и отклоняет
  // ещё непроигранное с него (см. guest_status_service.close_table) —
  // блокировка сюда больше не входит, "🚫 Заблокировать" ниже полностью
  // отдельная кнопка, как и было до 2026-09-19.
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

  async function loadChat() {
    try {
      const data = await api.listChat(token, clubId, guestId);
      setChatMessages(data);
      setChatError(null);
    } catch (err) {
      setChatError(err instanceof ApiError ? err.message : String(err));
    }
  }

  useEffect(() => {
    if (chatOpen) loadChat();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [chatOpen, guestId]);

  async function handleSendChat() {
    const text = chatDraft.trim();
    if (!text) return;
    setChatBusy(true);
    setChatError(null);
    try {
      await api.replyChat(token, clubId, String(guestId), text);
      setChatDraft("");
      await loadChat();
    } catch (err) {
      setChatError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setChatBusy(false);
    }
  }

  async function handleSaveName() {
    const name = nameDraft.trim();
    if (!name) return;
    setNameBusy(true);
    setActionError(null);
    try {
      await api.renameGuest(token, guestId, name);
      await reload();
      onChanged?.();
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setNameBusy(false);
    }
  }

  async function handleUploadPhoto(file) {
    setPhotoBusy(true);
    setActionError(null);
    try {
      // Тот же приём уменьшения фото перед отправкой, что и в VipPanel
      // (canvas.toDataURL("image/jpeg", 0.8)) — переиспользуем ту же логику.
      const resized = await resizeImageToDataUrl(file);
      await api.setGuestPhoto(token, guestId, resized);
      await reload();
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setPhotoBusy(false);
    }
  }

  function periodToRange(period) {
    const now = new Date();
    const toIso = (d) => d.toISOString().slice(0, 10);
    if (period === "today") return { from: toIso(now), to: toIso(now) };
    if (period === "week") {
      const from = new Date(now); from.setDate(from.getDate() - 6);
      return { from: toIso(from), to: toIso(now) };
    }
    if (period === "month") {
      const from = new Date(now); from.setDate(from.getDate() - 29);
      return { from: toIso(from), to: toIso(now) };
    }
    if (period === "year") {
      const from = new Date(now); from.setFullYear(from.getFullYear() - 1);
      return { from: toIso(from), to: toIso(now) };
    }
    return { from: customFrom || undefined, to: customTo || undefined };
  }

  async function loadHistory() {
    setHistoryError(null);
    try {
      const range = periodToRange(historyPeriod);
      const data = await api.getGuestHistory(token, clubId, guestId, range);
      setHistory(data);
    } catch (err) {
      setHistoryError(err instanceof ApiError ? err.message : String(err));
    }
  }

  useEffect(() => {
    if (historyOpen) loadHistory();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [historyOpen, historyPeriod, customFrom, customTo]);

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
            {guest.table_no != null && (
              <button type="button" className="btn btn--complete" disabled={busy} onClick={handleCloseTable}>
                🚪 Закрыть стол
              </button>
            )}
          </div>

          {guest.guest_type !== "vip" && (
            <div style={{ marginTop: 12 }}>
              <button
                type="button"
                className="btn btn--accept"
                disabled={busy}
                onClick={async () => {
                  setBusy(true);
                  setActionError(null);
                  try {
                    await api.makeGuestVip(token, guestId);
                    await reload();
                    if (onChanged) onChanged();
                  } catch (err) {
                    setActionError(err instanceof ApiError ? err.message : String(err));
                  } finally {
                    setBusy(false);
                  }
                }}
              >
                ⭐ Сделать VIP
              </button>
            </div>
          )}

          <div className="guest-card__chat" style={{ marginTop: 12 }}>
            <button type="button" className="btn btn--accent" onClick={() => setChatOpen((v) => !v)}>
              ✉️ Написать гостю
            </button>
            {chatOpen && (
              <div className="guest-card__chat-box" style={{ marginTop: 10 }}>
                {chatError && <div className="banner banner--error">{chatError}</div>}
                {chatMessages === null && !chatError && <p className="empty-hint">Загрузка…</p>}
                {chatMessages && chatMessages.length === 0 && (
                  <p className="empty-hint">Переписки с этим гостем пока нет.</p>
                )}
                {chatMessages && chatMessages.length > 0 && (
                  <ul className="vip-list">
                    {chatMessages.slice(-10).map((m) => (
                      <li key={m.id} className="vip-row chat-thread-row">
                        <span>{m.from_guest ? "Гость" : "Вы"}:</span>
                        {m.image_data_url && (
                          <img src={m.image_data_url} alt="Скриншот от гостя" className="chat-thread-row__image" />
                        )}
                        {m.message_text && <span>{m.message_text}</span>}
                      </li>
                    ))}
                  </ul>
                )}
                <div className="vip-row__actions chat-reply-row">
                  <input
                    className="vip-amount-input chat-reply-input"
                    type="text"
                    placeholder="Сообщение гостю…"
                    value={chatDraft}
                    onChange={(e) => setChatDraft(e.target.value)}
                    disabled={chatBusy}
                  />
                  <button
                    type="button"
                    className="btn btn--accent chat-reply-send"
                    disabled={chatBusy || !chatDraft.trim()}
                    onClick={handleSendChat}
                  >
                    Отправить
                  </button>
                </div>
              </div>
            )}
          </div>

          <div className="guest-card__identity-edit" style={{ marginTop: 12 }}>
            {guest.photo_data_url ? (
              <img src={guest.photo_data_url} alt="" className="vip-row__photo" />
            ) : (
              <span className="vip-row__photo vip-row__photo--placeholder">👤</span>
            )}
            <label className="btn-link vip-photo-upload">
              {photoBusy ? "Загружаем…" : "📷 Фото"}
              <input
                type="file" accept="image/*" disabled={photoBusy}
                onChange={(e) => {
                  const file = e.target.files[0];
                  e.target.value = "";
                  if (file) handleUploadPhoto(file);
                }}
              />
            </label>
            <input
              type="text" className="vip-amount-input" placeholder="Имя гостя"
              value={nameDraft} onChange={(e) => setNameDraft(e.target.value)} disabled={nameBusy}
            />
            <button type="button" className="btn-link" disabled={nameBusy || !nameDraft.trim()} onClick={handleSaveName}>
              💾 Сохранить имя
            </button>
          </div>

          <h3 style={{ marginTop: 16 }}>
            <button type="button" className="btn-link" onClick={() => setHistoryOpen((v) => !v)}>
              {historyOpen ? "▾" : "▸"} История спетых песен
            </button>
          </h3>
          {historyOpen && (
            <div className="guest-history">
              <div className="order-history-periods">
                {[
                  { key: "today", label: "Сегодня" },
                  { key: "week", label: "Неделя" },
                  { key: "month", label: "Месяц" },
                  { key: "year", label: "Год" },
                  { key: "custom", label: "Свой период" },
                ].map((p) => (
                  <button
                    key={p.key} type="button"
                    className={`link-btn${historyPeriod === p.key ? " order-history-periods__active" : ""}`}
                    onClick={() => setHistoryPeriod(p.key)}
                  >
                    {p.label}
                  </button>
                ))}
              </div>
              {historyPeriod === "custom" && (
                <div className="guest-history__calendar">
                  <input type="date" value={customFrom} onChange={(e) => setCustomFrom(e.target.value)} />
                  <span> — </span>
                  <input type="date" value={customTo} onChange={(e) => setCustomTo(e.target.value)} />
                </div>
              )}
              {historyError && <div className="banner banner--error">{historyError}</div>}
              {!history && !historyError && <p className="empty-hint">Загрузка…</p>}
              {history && (
                <>
                  <p className="empty-hint">
                    Всего песен за период: <strong>{history.song_count}</strong>
                    {history.total_amount > 0 && <> · на сумму {history.total_amount} MDL</>}
                  </p>
                  {history.days.length === 0 && <p className="empty-hint">За этот период ничего не спето.</p>}
                  {history.days.map((day) => (
                    <div key={day.date} className="guest-history__day">
                      <div className="guest-history__day-header">
                        {new Date(day.date).toLocaleDateString()} — {day.count} песен, {day.sum} MDL
                      </div>
                      <ul className="song-search__results">
                        {day.songs.map((s) => (
                          <li key={s.order_id} style={{ padding: "6px 12px" }}>
                            {s.artist ? `${s.artist} — ${s.song_title}` : s.song_title}
                            {s.category ? ` · ${s.category}` : ""} · стол {s.table_no ?? "—"}
                          </li>
                        ))}
                      </ul>
                    </div>
                  ))}
                </>
              )}
            </div>
          )}

          <h3 style={{ marginTop: 16 }}>Избранные песни ({guest.favorites.length})</h3>
          {guest.favorites.length === 0 && <p className="empty-hint">Пока ничего не добавлено.</p>}
          {guest.favorites.length > 0 && (
            <ul className="song-search__results">
              {guest.favorites.map((f) => (
                <li key={f.id} style={{ padding: "8px 12px" }}>
                  {f.artist ? `${f.artist} — ${f.song_title}` : f.song_title}
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </div>
  );
}

// Карточка стола (запрос пользователя 2026-09-28) — открывается кликом по
// заголовку карточки стола на доске "Заказы по столам" (см. OrdersBoard
// ниже), в отличие от клика по отдельному месту (уводит сразу в карточку
// ОДНОГО гостя, см. onOpenGuest у OrdersBoardSlot). Здесь — полный состав
// компании за столом (TableGroupMember, а не только те, у кого сейчас
// активный заказ), с той же GuestCard внутри при клике на участника (тот
// же паттерн вложенности, что и в GuestsPanel ниже — свой собственный
// selectedGuestId, back просто гасит его), плюс два действия сразу на весь
// стол: закрыть (тем же груповым сервисом, что и подтверждение заявки
// гостя, backend/services/table_close_service.py::close_table_directly —
// просто KJ подтверждает от своего имени сразу, без заявки) и перенести на
// новый номер (переезжают участники, их заказы за эту сессию и живая
// очередь сама подхватит новый номер — см. докстринг table_group_service.
// move_table на бэкенде).
function TableGroupCard({ token, clubId, tableNo, onBack, onTableNoChanged, autoMove }) {
  const [group, setGroup] = useState(null);
  const [loadError, setLoadError] = useState(null);
  const [selectedGuestId, setSelectedGuestId] = useState(null);
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState(null);
  const [hideReceipt, setHideReceipt] = useState(false);
  const [moveOpen, setMoveOpen] = useState(false);
  const [moveTarget, setMoveTarget] = useState("");
  const [freeTables, setFreeTables] = useState(null);

  async function reload() {
    try {
      const data = await api.getTableGroup(token, clubId, tableNo);
      setGroup(data);
      setLoadError(null);
    } catch (err) {
      setGroup(null);
      setLoadError(err instanceof ApiError && err.code === "TABLE_EMPTY" ? "empty" : (err instanceof ApiError ? err.message : String(err)));
    }
  }

  useEffect(() => {
    reload();
    setSelectedGuestId(null);
    setMoveOpen(false);
    setActionError(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tableNo]);

  // Карточку открыли кнопкой "⇄ Переместить" прямо с доски заказов (autoMove)
  // — сразу показываем выбор нового стола, как только компания загрузилась.
  const groupLoaded = group != null;
  useEffect(() => {
    if (autoMove && groupLoaded) handleOpenMove();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoMove, groupLoaded]);

  async function handleOpenMove() {
    setMoveOpen(true);
    setMoveTarget("");
    setActionError(null);
    try {
      const data = await api.listTableGroups(token, clubId);
      if (data.table_count) {
        const occupied = new Set(data.occupied_table_nos);
        setFreeTables(
          Array.from({ length: data.table_count }, (_, i) => i + 1).filter((n) => n !== tableNo && !occupied.has(n)),
        );
      } else {
        setFreeTables(null);
      }
    } catch {
      // Форма переноса просто покажет обычное числовое поле вместо списка —
      // сам перенос всё равно перепроверит занятость на бэкенде.
      setFreeTables(null);
    }
  }

  async function handleClose() {
    setBusy(true);
    setActionError(null);
    try {
      await api.closeTableGroup(token, clubId, tableNo, hideReceipt);
      onBack();
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  // ДОБАВЛЕНО (запрос пользователя 2026-09-30, кнопка "Вернуть" на карточке
  // стола): песню, уже отмеченную сыгранной (mark_played — кнопка "Готово"
  // на карточке заказа, или в будущем автоматически по истории VirtualDJ),
  // можно передумать и вернуть обратно в любой момент, пока стол ещё не
  // закрыт — например, если мост или сам KJ ошибся с песней. Это тот же
  // самый PUT /order/<id>/reject, что и "🗑 Убрать" на доске заказов — он
  // теперь принимает и уже сыгранные (STATUS_PLAYING) заказы (см. докстринг
  // reject_order в backend/services/vdj_service.py). Деньги нигде не
  // трогаются: весь расчёт происходит одной суммой при закрытии стола, а
  // отклонённый заказ в этот расчёт просто не попадает.
  async function handleRevertPlayed(orderId) {
    setBusy(true);
    setActionError(null);
    try {
      await api.rejectOrder(token, orderId);
      await reload();
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  async function handleMove(event) {
    event.preventDefault();
    const newTableNo = Number(moveTarget);
    if (!Number.isInteger(newTableNo) || newTableNo < 1) {
      setActionError("Укажите корректный номер стола");
      return;
    }
    setBusy(true);
    setActionError(null);
    try {
      await api.moveTableGroup(token, clubId, tableNo, newTableNo);
      onTableNoChanged(newTableNo);
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  if (selectedGuestId != null) {
    return (
      <div className="table-group-card">
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
    <div className="table-group-card">
      <button type="button" className="btn-link" onClick={onBack}>← К доске</button>
      {/* ИЗМЕНЕНО (2026-10, запрос пользователя: "кнопку Переместить стол —
      рядом с именем стола"): кнопка и форма переноса теперь сразу у
      заголовка карточки, а не внизу под списком компании. */}
      <h2 className="table-group-card__title">
        Стол {tableNo}
        {group && !moveOpen && (
          <button type="button" className="btn btn--accent" disabled={busy} onClick={handleOpenMove}>
            ⇄ Переместить стол
          </button>
        )}
      </h2>
      {group && (
        <>
          {moveOpen && (
            <form className="table-group-card__move" onSubmit={handleMove}>
              {freeTables ? (
                <select value={moveTarget} onChange={(e) => setMoveTarget(e.target.value)} required>
                  <option value="" disabled>Новый номер стола…</option>
                  {freeTables.map((n) => (
                    <option key={n} value={n}>{n}</option>
                  ))}
                </select>
              ) : (
                <input
                  type="number"
                  min="1"
                  placeholder="Новый номер стола"
                  value={moveTarget}
                  onChange={(e) => setMoveTarget(e.target.value)}
                  required
                />
              )}
              <button type="submit" className="btn btn--accept" disabled={busy}>Перенести</button>
              <button type="button" className="btn-link" disabled={busy} onClick={() => setMoveOpen(false)}>
                Отмена
              </button>
            </form>
          )}
          {moveOpen && actionError && <div className="banner banner--error">{actionError}</div>}
        </>
      )}

      {loadError === "empty" && <p className="empty-hint">За этим столом сейчас никого нет.</p>}
      {loadError && loadError !== "empty" && <div className="banner banner--error">{loadError}</div>}
      {!group && !loadError && <p className="empty-hint">Загрузка…</p>}

      {group && (
        <>
          <ul className="vip-list">
            {group.members.map((member) => (
              <li key={member.guest_id} className="vip-row vip-row--client">
                <div>
                  {member.display_name || `Гость #${member.guest_id}`}{" "}
                  {member.is_admin && <span className="guest-type-badge">админ стола</span>}
                  {member.is_blocked && <span className="guest-type-badge guest-type-badge--blocked">🚫 Заблокирован</span>}
                  <br />
                  <span className="empty-hint">
                    ID {member.guest_id} · за вечер {member.orders_evening} · за неделю {member.orders_week} · за месяц {member.orders_month}
                  </span>
                </div>
                <div className="vip-row__actions">
                  <button type="button" className="btn-link" onClick={() => setSelectedGuestId(member.guest_id)}>
                    Открыть карточку →
                  </button>
                </div>
              </li>
            ))}
          </ul>

          {/* ДОБАВЛЕНО (запрос пользователя 2026-09-30): песни этой сессии
          стола, уже отмеченные сыгранными, но ещё не списанные — списание
          происходит одной суммой только при закрытии стола. "Вернуть"
          убирает песню из будущего чека, если она попала сюда по ошибке. */}
          {group.played_orders && group.played_orders.length > 0 && (
            <div className="table-group-card__played">
              <h3>Сыгранные песни этого стола</h3>
              <ul className="vip-list">
                {group.played_orders.map((order) => (
                  <li key={order.id} className="vip-row vip-row--client">
                    <div>
                      {order.song_title}
                      {order.artist && <span> — {order.artist}</span>}
                      <br />
                      <span className="empty-hint">Гость #{order.telegram_user_id}</span>
                    </div>
                    <div className="vip-row__actions">
                      <button
                        type="button"
                        className="btn btn--reject"
                        disabled={busy}
                        onClick={() => handleRevertPlayed(order.id)}
                      >
                        ↩ Вернуть
                      </button>
                    </div>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {actionError && <div className="banner banner--error">{actionError}</div>}

          <div className="table-group-card__actions">
            <label className="table-close-hide-receipt">
              <input type="checkbox" checked={hideReceipt} onChange={(e) => setHideReceipt(e.target.checked)} />
              Не показывать чек
            </label>
            <button type="button" className="btn btn--reject" disabled={busy} onClick={handleClose}>
              🔒 Закрыть стол
            </button>
          </div>

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
    // Статус "онлайн" меняется сам по себе (гость открыл/закрыл приложение) —
    // обновляем список раз в 30 секунд, пока экран открыт.
    const id = setInterval(reload, 30000);
    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [clubId, typeFilter]);

  const onlineGuests = (guests || []).filter((g) => g.is_online);
  const otherGuests = (guests || []).filter((g) => !g.is_online);
  // "Остальные" свёрнуты по умолчанию (запрос пользователя 2026-10: "их
  // может быть сотни и тысячи") — раскрываются нажатием на заголовок.
  const [othersOpen, setOthersOpen] = useState(false);

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
          <>
            <h3 className="guests-section-title guests-section-title--online">
              🟢 Онлайн — сейчас в клубе ({onlineGuests.length})
            </h3>
            {onlineGuests.length === 0 && <p className="empty-hint">Сейчас никого нет.</p>}
            {onlineGuests.length > 0 && (
          <ul className="vip-list">
            {onlineGuests.map((guest) => (
              <li key={guest.guest_id} className="vip-row vip-row--client">
                <div>
                  {guest.display_name || `Гость #${guest.guest_id}`} · {GUEST_TYPE_BADGE[guest.guest_type] || guest.guest_type}
                  {guest.is_blocked && <span className="guest-type-badge guest-type-badge--blocked"> 🚫 Заблокирован</span>}
                  <br />
                  <span className="empty-hint">
                    {guest.display_name && <>ID {guest.guest_id} · </>}
                    Стол: {guest.table_no ?? "—"} · за вечер {guest.orders_evening} · за неделю {guest.orders_week} · за месяц {guest.orders_month}
                    {guest.vip_balance != null && <> · баланс {guest.vip_balance} MDL</>}
                    {guest.app_open && <> · 📱 приложение открыто</>}
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
            <h3 className="guests-section-title">
              <button type="button" className="btn-link" onClick={() => setOthersOpen((v) => !v)}>
                {othersOpen ? "▾" : "▸"} Остальные ({otherGuests.length})
              </button>
            </h3>
            {othersOpen && otherGuests.length > 0 && (
          <ul className="vip-list">
            {otherGuests.map((guest) => (
              <li key={guest.guest_id} className="vip-row vip-row--client">
                <div>
                  {guest.display_name || `Гость #${guest.guest_id}`} · {GUEST_TYPE_BADGE[guest.guest_type] || guest.guest_type}
                  {guest.is_blocked && <span className="guest-type-badge guest-type-badge--blocked"> 🚫 Заблокирован</span>}
                  <br />
                  <span className="empty-hint">
                    {guest.display_name && <>ID {guest.guest_id} · </>}
                    Стол: {guest.table_no ?? "—"} · за вечер {guest.orders_evening} · за неделю {guest.orders_week} · за месяц {guest.orders_month}
                    {guest.vip_balance != null && <> · баланс {guest.vip_balance} MDL</>}
                    {guest.app_open && <> · 📱 приложение открыто</>}
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
          </>
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

function OrdersBoardSlot({ slot, categories, busy, onAccept, onReject, onComplete, onChangeCategory, onOpenGuest, onPushToVdj }) {
  if (slot == null) {
    return <div className="table-slot table-slot--empty">Свободен</div>;
  }
  const needsDecision = BOARD_SLOT_NEEDS_DECISION.has(slot.status);
  // Запрос пользователя 2026-09-18: подтверждение заказа больше не ставит
  // песню в VirtualDJ само (KJ ставит сам, вручную) — "queued" здесь значит
  // "KJ принял заказ", а не "песня реально в очереди VirtualDJ". Место
  // освобождается только явной кнопкой "Готово" (см. mark_played() в
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
  // ИЗМЕНЕНО (запрос пользователя 2026-09-30, полная отмена кнопки
  // "Готово" в старом виде — она списывала деньги и потому была только у
  // VIP): теперь кнопка "Готово" ничего не списывает, только убирает
  // карточку с экрана (mark_played на бэкенде, освобождает место так же,
  // как раньше это делало списание). Деньги (и с VIP, и с обычных гостей)
  // считаются одной суммой при закрытии стола — поэтому кнопка теперь
  // нужна у ЛЮБОГО заказа, а не только у VIP.
  const canComplete = isQueued;
  return (
    <div className={`table-slot table-slot--${needsDecision ? "pending" : "queued"}`}>
      <button type="button" className="table-slot__body" onClick={() => onOpenGuest(slot.guest_id)}>
        {/* ДОБАВЛЕНО (2026-09-24, режим очереди "Последовательно" — вкладка
        "Столы"): номер места в общем круговом порядке клуба. Приходит с
        бэкенда только когда у клуба включён sequential (см. docstring
        services/table_board_service.py::_slot_dict) — в режиме "Как решает
        диджей" (manual) этого поля нет вовсе, и бейдж не рисуется. */}
        {slot.queue_position != null && (
          <div className="table-slot__queue-position">№{slot.queue_position}</div>
        )}
        <div className="table-slot__song">{slot.song_title}</div>
        {slot.artist && <div className="table-slot__artist">{slot.artist}</div>}
        {slot.tone ? (
          <div className="tone-badge">🎚 Тон {slot.tone > 0 ? `+${slot.tone}` : slot.tone}</div>
        ) : null}
        {slot.song_url ? <div className="table-slot__youtube">▶ ссылка YouTube</div> : null}
        {!canEditCategory && categoryName && <div className="table-slot__category">{categoryName}</div>}
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
          <button
            type="button"
            className="btn btn--accept"
            disabled={busy}
            onClick={() => {
              // Гость прислал ссылку YouTube — после "Принять" она сразу
              // открывается в новой вкладке (запрос пользователя 2026-10-09).
              if (slot.song_url) window.open(slot.song_url, "_blank", "noopener");
              onAccept(slot.order_id);
            }}
          >
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
      "Готово" (просто убирает карточку, деньги не трогает) или разом
      "Закрыть стол" со всей карточки гостя. Кнопка ниже вызывает тот же
      PUT /order/<id>/reject, что и "❌ Отклонить" выше для pending —
      backend (vdj_service.reject_order) теперь явно разрешает это и для
      STATUS_QUEUED (см. её докстринг), деньги не списывает и не возвращает,
      потому что списание происходит только в момент "Готово". */}
      {isQueued && (
        <div className="table-slot__actions">
          {/* ДОБАВЛЕНО (запрос пользователя 2026-10, жалоба "мой заказ не
          подсвечивается зелёным" в Guest App): единственный прежний способ
          попасть в живую очередь VirtualDJ ("➕ Добавить песню") создаёт
          заказ без привязки к гостю — поэтому подсветка VIP/Крейзи/"моя
          песня" никогда не срабатывала. Эта кнопка ставит именно ЭТОТ,
          уже принятый заказ гостя в очередь VirtualDJ, сохраняя его
          личность (см. push_order_to_queue() в backend). Показывается,
          пока песня ещё не поставлена (vdj_item_id пуст) — после этого
          место само освобождается кнопкой "Готово", как и раньше. */}
          {/* Кнопка "🎵 В очередь VDJ" убрана (2026-10): принятый заказ сразу
          стоит в живой очереди, а с песней в VirtualDJ склеивается по
          названию или кнопкой "🔗 Это одна песня" (см. QueueTable). */}
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

function OrdersBoard({ token, clubId, socket, onOpenGuest, onOpenTable }) {
  const [board, setBoard] = useState(null);
  const [categories, setCategories] = useState([]);
  const [loadError, setLoadError] = useState(null);
  const [actionError, setActionError] = useState(null);
  const [busyOrderId, setBusyOrderId] = useState(null);

  // ДОБАВЛЕНО (запрос пользователя: поле выбора стола начала очереди —
  // рядом с закрытием столов, в той же строке) — то же самое поле "Начало
  // очереди", что и на вкладке "Столы" (см. TableSettingsPanel выше),
  // продублировано здесь, чтобы KJ мог задать его прямо с экрана заказов.
  // Показывается всегда: с 2026-09-30 принять заказ нельзя, пока это поле
  // не задано, независимо от режима очереди (см. backend/routes/kj.py::confirm).
  const [queueStartTableDraft, setQueueStartTableDraft] = useState("1");
  const [queueStartTableBusy, setQueueStartTableBusy] = useState(false);
  const [queueStartTableError, setQueueStartTableError] = useState(null);
  const [queueStartTableSaved, setQueueStartTableSaved] = useState(false);

  async function loadQueueSettings() {
    try {
      const data = await api.getTableSettings(token, clubId);
      setQueueStartTableDraft(String(data.queue_start_table || 1));
    } catch {
      // Не критично для этого экрана — просто не покажем поле.
    }
  }

  useEffect(() => {
    loadQueueSettings();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token, clubId]);

  async function handleSaveQueueStartTable(event) {
    event.preventDefault();
    const trimmed = queueStartTableDraft.trim();
    const value = Number(trimmed);
    if (!Number.isInteger(value) || value < 1) {
      setQueueStartTableError("Введите номер стола — целое число не меньше 1");
      return;
    }
    setQueueStartTableBusy(true);
    setQueueStartTableError(null);
    setQueueStartTableSaved(false);
    try {
      const data = await api.updateTableSettings(token, clubId, { queue_start_table: value });
      setQueueStartTableDraft(String(data.queue_start_table || 1));
      setQueueStartTableSaved(true);
    } catch (err) {
      setQueueStartTableError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setQueueStartTableBusy(false);
    }
  }

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
    // ДОБАВЛЕНО (карточка стола, перенос стола 2026-09-28): перенос меняет
    // table_no сразу у пачки заказов через bulk UPDATE на сервере (см.
    // table_group_service.move_table), минуя обычные order_updated/
    // order_rejected по одному заказу — без этого слушателя открытая доска
    // "Заказы по столам" продолжала бы показывать заказы под старым номером
    // стола до следующего ручного действия.
    socket.on("table_group_moved", reload);
    return () => {
      socket.off("order_created", reload);
      socket.off("order_updated", reload);
      socket.off("order_confirmed", reload);
      socket.off("order_rejected", reload);
      socket.off("queue_updated", reload);
      socket.off("table_group_moved", reload);
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
      await api.markPlayed(token, orderId);
      await reload();
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : String(err));
      await reload();
    } finally {
      setBusyOrderId(null);
    }
  }

  // Запрос пользователя 2026-10: ставит уже принятый заказ в живую очередь
  // VirtualDJ, сохраняя его личность (см. onPushToVdj в OrdersBoardSlot) —
  // та же схема busy/reload, что и у остальных действий на доске.
  async function handlePushToVdj(orderId) {
    setBusyOrderId(orderId);
    setActionError(null);
    try {
      await api.pushOrderToVdj(token, orderId);
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

  // ДОБАВЛЕНО (запрос пользователя 2026-09-29, "кнопка. Закрыть все столы.
  // просто закрывает вечер когда все ушли с караоке.") — конец вечера одним
  // нажатием вместо закрытия каждого занятого стола по отдельности с его
  // карточки (см. TableGroupCard::handleClose). Тот же самый api-вызов
  // closeTableGroup для каждого стола сразу, см. backend/services/
  // table_close_service.py::close_all_tables.
  const [closingAll, setClosingAll] = useState(false);
  // ДОБАВЛЕНО (запрос пользователя: закрытие всех столов через двойное
  // подтверждение, чтобы случайно не закрыть все одним нажатием) — первое
  // нажатие только "взводит" кнопку на несколько секунд, реально закрывает
  // столы только повторное нажатие. Не нажали второй раз — кнопка сама
  // возвращается в обычный вид.
  const [closeAllArmed, setCloseAllArmed] = useState(false);
  const closeAllArmedTimeoutRef = useRef(null);

  useEffect(() => {
    return () => {
      if (closeAllArmedTimeoutRef.current) clearTimeout(closeAllArmedTimeoutRef.current);
    };
  }, []);

  async function handleCloseAllTables() {
    setClosingAll(true);
    setActionError(null);
    try {
      await api.closeAllTableGroups(token, clubId);
      await reload();
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setClosingAll(false);
    }
  }

  function handleCloseAllClick() {
    if (!closeAllArmed) {
      setCloseAllArmed(true);
      closeAllArmedTimeoutRef.current = setTimeout(() => setCloseAllArmed(false), 4000);
      return;
    }
    clearTimeout(closeAllArmedTimeoutRef.current);
    setCloseAllArmed(false);
    handleCloseAllTables();
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
      <div className="orders-board__header">
        <form className="table-settings-form orders-board__queue-start" onSubmit={handleSaveQueueStartTable}>
          <label className="table-settings-field">
            <span>Начало очереди (стол)</span>
            <input
              type="number"
              min="1"
              value={queueStartTableDraft}
              onChange={(e) => {
                setQueueStartTableDraft(e.target.value);
                setQueueStartTableSaved(false);
              }}
              disabled={queueStartTableBusy}
            />
          </label>
          <button type="submit" className="btn btn--accent" disabled={queueStartTableBusy}>
            {queueStartTableBusy ? "Сохраняем…" : "Сохранить"}
          </button>
          {queueStartTableSaved && <span className="empty-hint">Сохранено.</span>}
          {queueStartTableError && <span className="banner banner--error">{queueStartTableError}</span>}
        </form>
        <button
          type="button"
          className="btn btn--danger"
          disabled={closingAll}
          onClick={handleCloseAllClick}
        >
          🌙 {closingAll ? "Закрываем…" : closeAllArmed ? "Точно? Нажмите ещё раз" : "Закрыть все столы"}
        </button>
      </div>
      {actionError && <div className="banner banner--error">{actionError}</div>}
      <div className="orders-board__grid">
        {board.map((table) => {
          // ДОБАВЛЕНО (запрос пользователя 2026-09-29: "поменяем цвет
          // описания стола, если он хоть кем-то занят") — раньше заголовок
          // "Стол N" был одного цвета всегда, занятость было видно только
          // по надписям в самих местах ("Свободен"/название песни) ниже.
          // "Занят хоть кем-то" = хотя бы одно место не пустое (slot !=
          // null — пустое место рендерится как null, см. OrdersBoardSlot).
          const occupied = table.occupied ?? table.slots.some((slot) => slot != null);
          return (
          <div className="table-card" key={table.table_no}>
            <button
              type="button"
              className={
                "table-card__title table-card__title--clickable" +
                (occupied ? " table-card__title--occupied" : "")
              }
              onClick={() => onOpenTable(table.table_no)}
            >
              Стол {table.table_no}
            </button>
            {/* ДОБАВЛЕНО (2026-10, запрос пользователя: кнопка "Переместить стол"
            рядом с именем стола) — у занятого стола, прямо на доске. */}
            {occupied && (
              <button
                type="button"
                className="btn-link table-card__move"
                title="Переместить стол на другой номер"
                onClick={() => onOpenTable(table.table_no, true)}
              >
                ⇄ Переместить стол
              </button>
            )}
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
                  onPushToVdj={handlePushToVdj}
                />
              ))}
            </div>
          </div>
          );
        })}
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
  // Мигание кнопки "Сообщения" (запрос пользователя 2026-10-01) — true, пока
  // есть хоть одна новая непрочитанная заявка/сообщение любого вида,
  // собранных на экране "Сообщения"; сбрасывается в false, когда KJ
  // открывает этот экран (см. onClick кнопки ниже).
  const [hasNewMessages, setHasNewMessages] = useState(false);
  // Мигание заголовка вкладки браузера, если KJ сейчас не смотрит в панель
  // (другая вкладка браузера или свёрнуто — запрос пользователя 2026-10:
  // "можно чтоб новое сообщение или новый заказ моргали в браузере если
  // KJ находится на другой вкладке") — отдельно от мигания кнопки
  // "Сообщения" выше: та кнопка про заявки/чат, эта про ЛЮБОЙ новый заказ
  // тоже, и реагирует на видимость вкладки браузера (Page Visibility API),
  // а не на то, какой экран открыт внутри самой панели.
  const [hasNewOrder, setHasNewOrder] = useState(false);
  const pageTitleRef = useRef(typeof document !== "undefined" ? document.title : "KJ Panel");
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
  // Запрос пользователя 2026-09-28: клик по самой карточке стола (не по
  // месту гостя) проваливается в полную карточку стола — состав компании,
  // закрытие/перенос стола (см. TableGroupCard выше) — отдельный от
  // boardGuestId стейт, т.к. это разные экраны и открываются независимо.
  const [boardTableNo, setBoardTableNo] = useState(null);
  // true — карточку стола открыли кнопкой "⇄ Переместить стол" с доски.
  const [boardTableMove, setBoardTableMove] = useState(false);
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

      // Мигание кнопки "Сообщения" сразу при открытии панели, если
      // непрочитанное уже накопилось до того, как KJ зашёл (а не только
      // после первого же сокет-события после этого) — одним запросом
      // проверяем все виды заявок/сообщений, которые собирает экран
      // "Сообщения".
      try {
        const [changeReqs, closeReqs, vipReqs, topupReqs, chatMsgs, adminMsgs] = await Promise.all([
          api.listOrderChangeRequests(token, meData.club_id),
          api.listTableCloseRequests(token, meData.club_id),
          api.listVipRequests(token, meData.club_id, "pending"),
          api.listVipTopupRequests(token, meData.club_id),
          api.listChat(token, meData.club_id),
          api.listAdminMessages(token, meData.club_id),
        ]);
        const latestByGuest = new Map();
        for (const m of chatMsgs || []) {
          const prev = latestByGuest.get(m.telegram_user_id);
          if (!prev || m.created_at > prev.created_at) latestByGuest.set(m.telegram_user_id, m);
        }
        const chatNeedsReply = [...latestByGuest.values()].some((m) => m.from_guest);
        // ДОБАВЛЕНО (2026-10-03) — непрочитанное сообщение от администрации
        // тоже должно сразу зажигать мигающую кнопку "Сообщения".
        const hasUnreadAdminMessage = (adminMsgs || []).some((m) => m.from_admin && !m.is_read_by_kj);
        if (!cancelled) {
          setHasNewMessages(
            changeReqs.length > 0 || closeReqs.length > 0 || vipReqs.length > 0 || topupReqs.length > 0 || chatNeedsReply || hasUnreadAdminMessage,
          );
        }
      } catch {
        // Не критично — просто не замигает сразу при открытии, подхватит
        // первое же сокет-событие ниже.
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

    // Мигание кнопки "Сообщения" (запрос пользователя 2026-10-01) — любое из
    // этих событий означает новую заявку/сообщение на экране "Сообщения";
    // гасится кликом по самой кнопке (сброс hasNewMessages в onClick ниже).
    socket.on("order_created", () => setHasNewOrder(true));
    socket.on("order_change_request_created", () => setHasNewMessages(true));
    socket.on("table_close_request_created", () => setHasNewMessages(true));
    socket.on("vip_request_created", () => setHasNewMessages(true));
    socket.on("vip_topup_request_created", () => setHasNewMessages(true));
    socket.on("chat_message", (message) => {
      if (message.from_guest) setHasNewMessages(true);
    });
    socket.on("admin_message", (message) => {
      if (message.from_admin) setHasNewMessages(true);
    });

    return () => {
      cancelled = true;
      socket.disconnect();
      setSocketInstance(null);
    };
  }, [token]);

  useEffect(() => {
    if (!(hasNewMessages || hasNewOrder)) return undefined;
    const base = pageTitleRef.current;
    let flip = false;
    const id = setInterval(() => {
      if (!document.hidden) {
        document.title = base;
        return;
      }
      document.title = flip ? base : "🔔 Новое — KJ Panel";
      flip = !flip;
    }, 1000);
    return () => {
      clearInterval(id);
      document.title = base;
    };
  }, [hasNewMessages, hasNewOrder]);

  useEffect(() => {
    function handleVisibility() {
      if (!document.hidden) setHasNewOrder(false);
    }
    document.addEventListener("visibilitychange", handleVisibility);
    return () => document.removeEventListener("visibilitychange", handleVisibility);
  }, []);

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
          {view !== "messages" && (
            <button
              type="button"
              className={hasNewMessages ? "btn-link btn-link--blink" : "btn-link"}
              onClick={() => {
                setHasNewMessages(false);
                setView("messages");
              }}
            >
              ✉️ Сообщения
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
          {view !== "song-lists" && (
            <button type="button" className="btn-link" onClick={() => setView("song-lists")}>
              Списки для гостей
            </button>
          )}
          {STATS_ENABLED && view !== "stats" && (
            <button type="button" className="btn-link" onClick={() => setView("stats")}>
              Статистика
            </button>
          )}
        </div>
      </header>

      <ConnectionOverviewPanel connected={connected} bridgeStatus={bridgeStatus} />

      {view === "messages" ? (
        <main className="app-main">
          {/* ДОБАВЛЕНО (2026-10-01, запрос пользователя "кнопка Сообщения,
          собирающая все обращения в одном месте, включая личный чат") —
          раньше заявки на отмену/замену и на закрытие стола сами по себе
          появлялись прямо над списком столов, а заявки на VIP и на
          пополнение баланса были спрятаны внутри вкладки VIP; личного чата
          с гостем у KJ Panel не было вообще. Теперь всё в одном месте. */}
          <AdminMessagesPanel token={token} clubId={me.club_id} socket={socketInstance} />
          <SuggestionPanel token={token} clubId={me.club_id} />
          <GeneralChatToggle token={token} />
          <OrderChangeRequestsPanel token={token} clubId={me.club_id} socket={socketInstance} />
          <TableCloseRequestsPanel token={token} clubId={me.club_id} socket={socketInstance} />
          <VipRequestsPanel token={token} clubId={me.club_id} socket={socketInstance} />
          <VipTopupRequestsPanel token={token} clubId={me.club_id} socket={socketInstance} />
          <KjChatPanel token={token} clubId={me.club_id} socket={socketInstance} />
        </main>
      ) : view === "vip" ? (
        <VipPanel token={token} clubId={me.club_id} socket={socketInstance} />
      ) : view === "categories" ? (
        <CategoriesPanel token={token} clubId={me.club_id} />
      ) : view === "tables" ? (
        <>
          <TableSettingsPanel token={token} clubId={me.club_id} />
          <AutoClosePanel token={token} />
        </>
      ) : view === "guests" ? (
        <GuestsPanel token={token} clubId={me.club_id} />
      ) : view === "song-lists" ? (
        <SongListsAdminPanel token={token} />
      ) : view === "stats" && STATS_ENABLED ? (
        <StatsPanel token={token} clubId={me.club_id} />
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
      ) : boardTableNo != null ? (
        <div className="app-main">
          <TableGroupCard
            token={token}
            clubId={me.club_id}
            tableNo={boardTableNo}
            autoMove={boardTableMove}
            onBack={() => {
              setBoardTableNo(null);
              setBoardTableMove(false);
            }}
            onTableNoChanged={(n) => {
              setBoardTableNo(n);
              setBoardTableMove(false);
            }}
          />
        </div>
      ) : (
        <main className="app-main">
          <section>
            <h2>Заказы по столам</h2>
            <OrdersBoard
              token={token}
              clubId={me.club_id}
              socket={socketInstance}
              onOpenGuest={setBoardGuestId}
              onOpenTable={(n, move) => {
                setBoardTableNo(n);
                setBoardTableMove(Boolean(move));
              }}
            />
          </section>

          <section>
            <h2>Активная очередь VirtualDJ</h2>
            <QueueTable queue={queue} token={token} clubId={me.club_id} />
          </section>
        </main>
      )}
    </div>
  );
}
