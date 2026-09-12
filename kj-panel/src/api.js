const BACKEND_URL = import.meta.env.VITE_BACKEND_URL || "http://localhost:5000";

const TOKEN_STORAGE_KEY = "kj_panel_token";

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
  me: (token) => request("/api/kj/me", { token }),
  listOrders: (token, clubId, status = "pending") =>
    request(`/api/kj/orders/${clubId}?status=${status}`, { token }),
  confirmOrder: (token, orderId) =>
    request(`/api/kj/order/${orderId}/confirm`, { method: "PUT", token }),
  rejectOrder: (token, orderId) =>
    request(`/api/kj/order/${orderId}/reject`, { method: "PUT", token }),
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
};

export { ApiError, BACKEND_URL };
