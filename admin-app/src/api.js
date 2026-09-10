const BACKEND_URL = import.meta.env.VITE_BACKEND_URL || "http://localhost:5000";

// Токен приходит по ссылке (см. backend/manage.py::admin-link, по образцу
// kj-panel/src/api.js::resolveToken) — /set_admin в старом боте больше не
// существует как отдельный флоу, ссылку выдаёт CLI-провижининг (аудит
// PHASE1_AUDIT: "/set_admin ... становится обычным auth-flow").
const TOKEN_STORAGE_KEY = "admin_app_token";

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
  me: (token) => request("/api/admin/me", { token }),
  listClubs: (token) => request("/api/admin/clubs", { token }),
  getClub: (token, clubId) => request(`/api/admin/clubs/${clubId}`, { token }),
  createClub: (token, payload) =>
    request("/api/admin/clubs", { method: "POST", token, body: payload }),
  updateClub: (token, clubId, payload) =>
    request(`/api/admin/clubs/${clubId}`, { method: "PUT", token, body: payload }),
  setClubStatus: (token, clubId, isActive) =>
    request(`/api/admin/clubs/${clubId}/status`, {
      method: "PUT", token, body: { is_active: isActive },
    }),
  deleteClub: (token, clubId) =>
    request(`/api/admin/clubs/${clubId}`, { method: "DELETE", token }),
  getClubQr: (token, clubId) => request(`/api/admin/clubs/${clubId}/qr`, { token }),
  listKj: (token) => request("/api/admin/kj", { token }),
  assignKj: (token, payload) => request("/api/admin/kj", { method: "POST", token, body: payload }),
  updateKj: (token, kjId, payload) =>
    request(`/api/admin/kj/${kjId}`, { method: "PUT", token, body: payload }),
  setKjStatus: (token, kjId, isActive) =>
    request(`/api/admin/kj/${kjId}/status`, { method: "PUT", token, body: { is_active: isActive } }),
  getReportsOverview: (token) => request("/api/admin/reports/overview", { token }),
  getSystemOverview: (token) => request("/api/admin/system/overview", { token }),
  getSystemLogs: (token) => request("/api/admin/system/logs", { token }),
};

// Скачивание бэкапа БД — отдельно от api.request(), т.к. это не JSON-ответ
// {success, data}, а бинарный/текстовый файл (Content-Disposition
// attachment). Bearer-токен нельзя передать через обычную <a href> ссылку,
// поэтому: fetch с заголовком → blob → программное скачивание (та же
// техника, что и для CSV в блоке "Отчёты", только источник данных — сам
// HTTP-ответ сервера, а не JSON, собранный на клиенте).
export async function downloadSystemBackup(token) {
  const resp = await fetch(`${BACKEND_URL}/api/admin/system/backup`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!resp.ok) {
    let message = `Ошибка запроса (${resp.status})`;
    try {
      const json = await resp.json();
      message = json?.message || message;
    } catch {
      // тело может быть не-JSON
    }
    throw new ApiError(resp.status, "BACKUP_ERROR", message);
  }
  const disposition = resp.headers.get("Content-Disposition") || "";
  const match = disposition.match(/filename=([^;]+)/);
  const filename = match ? match[1].trim() : "backup.sql";
  const blob = await resp.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

export { ApiError, BACKEND_URL };
