import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ApiError, GOOGLE_CLIENT_ID, api, loadStoredSession, storeSession } from "./api";
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
// Очередь спрашивает реальный VirtualDJ через мост (не просто базу) — при
// частом опросе несколько гостей одновременно создают очередь запросов к
// мосту на компьютере KJ и подвешивают вообще всё (2026-09-14, живой
// инцидент после включения VDJ_ADAPTER=bridge). Раз в 10с достаточно —
// пользователь заметит новую песню в очереди с задержкой максимум 10с.
const POLL_QUEUE_MS = 10000;
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
