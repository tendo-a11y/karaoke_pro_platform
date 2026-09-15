const BACKEND_URL = import.meta.env.VITE_BACKEND_URL || "http://localhost:5000";

// Гостевая сессия привязана к конкретному клубу — храним отдельно на
// случай, если один и тот же телефон когда-нибудь откроет ссылки двух
// разных клубов (маловероятно, но дешевле сразу не наступать на эти грабли,
// чем потом мигрировать формат ключа в localStorage).
function tokenStorageKey(clubId) {
  return `guest_app_token_club_${clubId}`;
}

export function loadStoredSession(clubId) {
  const raw = localStorage.getItem(tokenStorageKey(clubId));
  if (!raw) return null;
  try {
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

export function storeSession(clubId, session) {
  localStorage.setItem(tokenStorageKey(clubId), JSON.stringify(session));
}

// ТЗ п.45 (финальная единая модель входа) — постоянная идентификация
// гостя через Google, GOOGLE_AUTH_MODE=mock на бэкенде (см. services/
// google_auth_service.py): пока нет настоящего Google Client ID, сам
// credential не настоящий Google id_token, а простой {"sub"}, который
// формирует сам фронтенд, без участия гостя (гость не видит и не вводит
// ничего Google-специфичного — только номер стола). sub хранится в этом
// браузере ГЛОБАЛЬНО (не по клубам) и переиспользуется при каждом входе —
// это имитирует то, как ведёт себя настоящий Google-аккаунт: один и тот
// же человек, в любом клубе, всегда даёт один и тот же sub. Когда
// появится настоящий Client ID, эта функция заменяется на настоящую
// кнопку Google Identity Services — остальной код (вызов api.linkGoogle)
// не меняется.
const MOCK_GOOGLE_SUB_KEY = "guest_app_mock_google_sub";

export function getMockGoogleCredential() {
  let sub = localStorage.getItem(MOCK_GOOGLE_SUB_KEY);
  if (!sub) {
    sub = `mock-${crypto.randomUUID()}`;
    localStorage.setItem(MOCK_GOOGLE_SUB_KEY, sub);
  }
  return { sub };
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
  // ТЗ п.45 (финальная единая модель входа): table_no сюда больше не
  // передаётся — QR никогда не приносит номер стола, сессия всегда
  // создаётся без стола. Стол появляется только вместе со входом через
  // Google, одним действием — см. linkGoogle ниже.
  createSession: (clubId) =>
    request("/api/guest/session", { method: "POST", body: { club_id: clubId } }),
  me: (token) => request("/api/guest/me", { token }),
  // ТЗ п.45: единственный способ получить стол и постоянный профиль —
  // одним вызовом. tableNo обязателен на первом входе; когда стол уже
  // выбран и гость лишь переключается на другой Google-аккаунт, сервер
  // сам подставит уже известный стол, если его не передать (см. docstring
  // routes/guest.py::link_google) — здесь для простоты передаём всегда.
  setDisplayName: (token, displayName) =>
    request("/api/guest/profile/name", {
      method: "PUT",
      token,
      body: { display_name: displayName },
    }),
  linkGoogle: (token, tableNo, googleCredential) =>
    request("/api/guest/profile/link-google", {
      method: "POST", token, body: { table_no: tableNo, google_credential: googleCredential },
    }),
  createOrder: (token, songTitle, artist, serviceId) =>
    request("/api/guest/order", {
      method: "POST", token, body: { song_title: songTitle, artist, service_id: serviceId },
    }),
  listMyOrders: (token, days) =>
    request(`/api/guest/orders${days != null ? `?days=${days}` : ""}`, { token }),
  replaceOrder: (token, orderId, songTitle, artist, serviceId) =>
    request(`/api/guest/order/${orderId}/replace`, {
      method: "POST", token, body: { song_title: songTitle, artist, service_id: serviceId },
    }),
  getQueue: (token) => request("/api/guest/queue", { token }),
  sendChatMessage: (token, messageText) =>
    request("/api/guest/chat", { method: "POST", token, body: { message_text: messageText } }),
  listChat: (token) => request("/api/guest/chat", { token }),
  listServices: (token) => request("/api/guest/services", { token }),
  searchSongs: (token, query) =>
    request(`/api/guest/songs/search?q=${encodeURIComponent(query)}`, { token }),
  aiSearchSongs: (token, text) =>
    request("/api/guest/songs/ai-search", { method: "POST", token, body: { text } }),
  screenshotSearchSongs: (token, imageBase64, mediaType) =>
    request("/api/guest/songs/screenshot-search", {
      method: "POST", token, body: { image_base64: imageBase64, media_type: mediaType },
    }),
  requestVip: (token) => request("/api/guest/vip/request", { method: "POST", token }),
  listFavorites: (token) => request("/api/guest/favorites", { token }),
  addFavorite: (token, songTitle, artist, serviceId) =>
    request("/api/guest/favorites", {
      method: "POST", token, body: { song_title: songTitle, artist, service_id: serviceId },
    }),
  deleteFavorite: (token, favoriteId) =>
    request(`/api/guest/favorites/${favoriteId}`, { method: "DELETE", token }),
  reorderFavorite: (token, favoriteId) =>
    request(`/api/guest/favorites/${favoriteId}/reorder`, { method: "POST", token }),
  getTableGroup: (token) => request("/api/guest/table-group", { token }),
  requestTableGroupJoin: (token) => request("/api/guest/table-group/request-join", { method: "POST", token }),
  approveJoinRequest: (token, requestId) =>
    request(`/api/guest/table-group/join-requests/${requestId}/approve`, { method: "POST", token }),
  rejectJoinRequest: (token, requestId) =>
    request(`/api/guest/table-group/join-requests/${requestId}/reject`, { method: "POST", token }),
  kickTableGroupMember: (token, guestId) =>
    request(`/api/guest/table-group/kick/${guestId}`, { method: "POST", token }),
  transferTableGroupAdmin: (token, guestId) =>
    request(`/api/guest/table-group/transfer/${guestId}`, { method: "POST", token }),
  leaveTableGroup: (token) => request("/api/guest/table-group/leave", { method: "POST", token }),
  listVipTransactions: (token) => request("/api/guest/vip/transactions", { token }),
};

export { ApiError, BACKEND_URL };
