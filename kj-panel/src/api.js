const BACKEND_URL = import.meta.env.VITE_BACKEND_URL || "http://localhost:5000";

const TOKEN_STORAGE_KEY = "kj_panel_token";

// 2026-09: "доступ KJ Pro определяется Google-аккаунтом клуба" — Client ID
// не секрет (виден в открытом виде на любой странице с кнопкой входа
// Google), поэтому хранится прямо в коде фронтенда, как и в guest-app.
export const GOOGLE_CLIENT_ID = "798456512733-iiel465aq3g5nprap64mq8ovrvcjqsfd.apps.googleusercontent.com";

export function resolveToken() {
  const url = new URL(window.location.href);
  const fromUrl = url.searchParams.get("token");
  if (fromUrl) {
    localStorage.setItem(TOKEN_STORAGE_KEY, fromUrl);
    // Убираем токен из адресной строки, чтобы он не остался в истории браузера.
    url.searchParams.delete("token");
    window.history.replaceState({}, "", url.toString());
    return fromUrl;
  }
  return localStorage.getItem(TOKEN_STORAGE_KEY);
}

// Токен, полученный входом через Google (см. loginWithGoogle ниже),
// сохраняется тем же способом, что и токен из ссылки бота — дальше оба
// неотличимы друг от друга для остального кода панели.
export function storeToken(token) {
  localStorage.setItem(TOKEN_STORAGE_KEY, token);
}

export function clearToken() {
  localStorage.removeItem(TOKEN_STORAGE_KEY);
}

class ApiError extends Error {
  constructor(status, code, message) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

async function request(path, { method = "GET", token, body } = {}) {
  const resp = await fetch(`${BACKEND_URL}${path}`, {
    method,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: body ? JSON.stringify(body) : undefined,
  });

  let json = null;
  try {
    json = await resp.json();
  } catch {
    // тело может отсутствовать
  }

  if (!resp.ok) {
    const code = json?.error || "UNKNOWN_ERROR";
    const message = json?.message || `Ошибка запроса (${resp.status})`;
    throw new ApiError(resp.status, code, message);
  }

  return json?.data;
}

export const api = {
  // Без токена — это как раз тот эндпоинт, который его выдаёт (см.
  // routes/kj.py::kj_google_login). credential — {id_token} от настоящей
  // кнопки Google Identity Services (см. KjLoginScreen в App.jsx).
  loginWithGoogle: (credential) =>
    request("/api/kj/auth/google", { method: "POST", body: { credential } }),
  me: (token) => request("/api/kj/me", { token }),
  listOrders: (token, clubId, status = "pending") =>
    request(`/api/kj/orders/${clubId}?status=${status}`, { token }),
  // Доп. ТЗ "KJ Pro", запрос пользователя 2026-09-18: сетка карточек
  // столов — по одной на стол, с местами по числу Club.songs_per_table
  // (см. routes/kj.py::orders_board, services/table_board_service.py).
  getOrdersBoard: (token, clubId) => request(`/api/kj/orders-board/${clubId}`, { token }),
  confirmOrder: (token, orderId) =>
    request(`/api/kj/order/${orderId}/confirm`, { method: "PUT", token }),
  rejectOrder: (token, orderId) =>
    request(`/api/kj/order/${orderId}/reject`, { method: "PUT", token }),
  // Запрос пользователя 2026-09-18: подтверждение заказа больше не ставит
  // песню в VirtualDJ само (KJ делает это вручную) — кнопка "Готово" на
  // занятой карточке стола освобождает место явным образом, см.
  // routes/kj.py::complete / services/vdj_service.py::complete_order.
  completeOrder: (token, orderId) =>
    request(`/api/kj/order/${orderId}/complete`, { method: "PUT", token }),
  getQueue: (token, clubId) => request(`/api/kj/queue/${clubId}`, { token }),
  addManualOrder: (token, { songTitle, artist, tableNo }) =>
    request(`/api/kj/order/manual`, {
      method: "POST",
      token,
      body: { song_title: songTitle, artist: artist || null, table_no: tableNo },
    }),
  listVipRequests: (token, clubId, status = "pending") =>
    request(`/api/kj/vip-requests/${clubId}?status=${status}`, { token }),
  approveVipRequest: (token, requestId) =>
    request(`/api/kj/vip-requests/${requestId}/approve`, { method: "PUT", token }),
  rejectVipRequest: (token, requestId) =>
    request(`/api/kj/vip-requests/${requestId}/reject`, { method: "PUT", token }),
  listVipClients: (token, clubId) => request(`/api/kj/vip-clients/${clubId}`, { token }),
  updateVipCashback: (token, vipClientId, cashbackPercent) =>
    request(`/api/kj/vip-clients/${vipClientId}/cashback`, {
      method: "PUT", token, body: { cashback_percent: cashbackPercent },
    }),
  topupVipBalance: (token, vipClientId, amount) =>
    request(`/api/kj/vip-clients/${vipClientId}/topup`, { method: "POST", token, body: { amount } }),
  debitVipBalance: (token, vipClientId, amount) =>
    request(`/api/kj/vip-clients/${vipClientId}/debit`, { method: "POST", token, body: { amount } }),
  setVipBalance: (token, vipClientId, balance) =>
    request(`/api/kj/vip-clients/${vipClientId}/balance`, { method: "PUT", token, body: { balance } }),
  listCategories: (token, clubId) => request(`/api/kj/categories/${clubId}`, { token }),
  createCategory: (token, clubId, { name, description, price, isFree }) =>
    request(`/api/kj/categories/${clubId}`, {
      method: "POST", token, body: { name, description: description || null, price, is_free: isFree },
    }),
  updateCategory: (token, clubId, categoryId, fields) =>
    request(`/api/kj/categories/${clubId}/${categoryId}`, { method: "PUT", token, body: fields }),
  deleteCategory: (token, clubId, categoryId) =>
    request(`/api/kj/categories/${clubId}/${categoryId}`, { method: "DELETE", token }),
  getTableSettings: (token, clubId) => request(`/api/kj/table-settings/${clubId}`, { token }),
  // fields — объект с любым подмножеством {table_count, songs_per_table};
  // бэкенд меняет только те ключи, что реально присутствуют в теле запроса
  // (см. routes/kj.py::update_table_settings), остальные не трогает.
  updateTableSettings: (token, clubId, fields) =>
    request(`/api/kj/table-settings/${clubId}`, { method: "PUT", token, body: fields }),
  updateOrderTable: (token, orderId, tableNo) =>
    request(`/api/kj/order/${orderId}/table`, { method: "PUT", token, body: { table_no: tableNo } }),
  updateOrderCategory: (token, orderId, serviceId) =>
    request(`/api/kj/order/${orderId}/category`, { method: "PUT", token, body: { service_id: serviceId } }),
  removeFromVdjQueue: (token, vdjItemId) =>
    request(`/api/vdj/queue/${encodeURIComponent(vdjItemId)}`, { method: "DELETE", token }),
  claimQueueItem: (token, { vdjItemId, songTitle, artist, tableNo, serviceId }) =>
    request(`/api/kj/queue/claim`, {
      method: "POST",
      token,
      body: {
        vdj_item_id: vdjItemId,
        song_title: songTitle,
        artist: artist || null,
        table_no: tableNo,
        service_id: serviceId,
      },
    }),
  listGuests: (token, clubId, guestType) =>
    request(`/api/kj/guests/${clubId}${guestType ? `?type=${encodeURIComponent(guestType)}` : ""}`, { token }),
  getGuest: (token, clubId, guestId) =>
    request(`/api/kj/guests/${clubId}/${encodeURIComponent(guestId)}`, { token }),
  blockGuest: (token, guestId) =>
    request(`/api/kj/guests/${encodeURIComponent(guestId)}/block`, { method: "POST", token }),
  unblockGuest: (token, guestId) =>
    request(`/api/kj/guests/${encodeURIComponent(guestId)}/unblock`, { method: "POST", token }),
  removeGuestFromTable: (token, guestId) =>
    request(`/api/kj/guests/${encodeURIComponent(guestId)}/remove-table`, { method: "POST", token }),
  getBridgeStatus: (token, clubId) => request(`/api/kj/bridge/status/${clubId}`, { token }),
};

export { ApiError, BACKEND_URL };
