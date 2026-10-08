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
  // routes/kj.py::mark_played_route / services/vdj_service.py::mark_played.
  // ИЗМЕНЕНО (запрос пользователя 2026-09-30): раньше называлась completeOrder
  // и списывала деньги — теперь только убирает карточку с экрана, деньги
  // считаются одной суммой при закрытии стола.
  markPlayed: (token, orderId) =>
    request(`/api/kj/order/${orderId}/mark-played`, { method: "PUT", token }),
  // Запрос пользователя 2026-10 (жалоба "мой заказ не подсвечивается
  // зелёным" в Guest App): ставит УЖЕ принятый заказ в живую очередь
  // VirtualDJ, не создавая отдельный "ничей" заказ, как это делает
  // addManualOrder ниже — см. routes/kj.py::push_order_to_vdj_route.
  pushOrderToVdj: (token, orderId) =>
    request(`/api/kj/order/${orderId}/push-to-vdj`, { method: "PUT", token }),
  getQueue: (token, clubId) => request(`/api/kj/queue/${clubId}`, { token }),
  // Живая очередь (2026-10): исправить название заказа на точное из
  // VirtualDJ и склеить заказ с позицией VirtualDJ ("это одна песня").
  renameOrder: (token, orderId, songTitle, artist) =>
    request(`/api/kj/order/${orderId}/rename`, {
      method: "PUT", token, body: { song_title: songTitle, artist },
    }),
  linkOrderToVdj: (token, orderId, vdjItemId) =>
    request(`/api/kj/order/${orderId}/link-vdj`, {
      method: "PUT", token, body: { vdj_item_id: vdjItemId },
    }),
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
  // ДОБАВЛЕНО (2026-09-30, запрос пользователя "баланс VIP и пополнение") —
  // список заявок "хочу пополнить баланс" и отметка "обработано" (сама
  // сумма зачисляется через уже существующую topupVipBalance).
  listVipTopupRequests: (token, clubId) =>
    request(`/api/kj/vip-topup-requests/${clubId}`, { token }),
  resolveVipTopupRequest: (token, requestId) =>
    request(`/api/kj/vip-topup-requests/${requestId}/resolve`, { method: "PUT", token }),
  // ДОБАВЛЕНО (2026-10-01, запрос пользователя "кнопка Сообщения,
  // собирающая все обращения, включая личный чат с гостями") — чат уже
  // был готов на бэкенде (routes/kj.py::list_chat/reply_chat), здесь не
  // хватало только обёртки на фронтенде.
  listChat: (token, clubId, telegramUserId) =>
    request(
      `/api/kj/chat/${clubId}${telegramUserId ? `?telegram_user_id=${telegramUserId}` : ""}`,
      { token },
    ),
  replyChat: (token, clubId, telegramUserId, messageText) =>
    request(`/api/kj/chat/${clubId}`, {
      method: "POST", token, body: { telegram_user_id: telegramUserId, message_text: messageText },
    }),
  // Удаление сообщения / очистка чата (запрос пользователя 2026-10-04,
  // "нигде нет кнопки удаления сообщений и очистки чата") — см.
  // backend/routes/kj.py::delete_chat_message/clear_chat.
  deleteChatMessage: (token, messageId) =>
    request(`/api/kj/chat/${messageId}`, { method: "DELETE", token }),
  clearChat: (token, clubId, telegramUserId) =>
    request(`/api/kj/chat/${clubId}/${telegramUserId}`, { method: "DELETE", token }),
  // ДОБАВЛЕНО (2026-10-03, запрос пользователя "в админке есть панель
  // управления KJ... сообщения приходят KJ в его панель сообщения") —
  // переписка с администрацией, режим двусторонний.
  listAdminMessages: (token, clubId) => request(`/api/kj/admin-messages/${clubId}`, { token }),
  sendAdminMessage: (token, clubId, messageText) =>
    request(`/api/kj/admin-messages/${clubId}`, { method: "POST", token, body: { message_text: messageText } }),
  deleteAdminMessage: (token, clubId, messageId) =>
    request(`/api/kj/admin-messages/${clubId}/${messageId}`, { method: "DELETE", token }),
  clearAdminMessages: (token, clubId) =>
    request(`/api/kj/admin-messages/${clubId}`, { method: "DELETE", token }),
  markAdminMessagesRead: (token, clubId) =>
    request(`/api/kj/admin-messages/${clubId}/read`, { method: "PUT", token }),
  // ДОБАВЛЕНО (2026-09-20, решение пользователя "Нужно одобрение KJ (запрос
  // → Одобрить/Отклонить)") — заявки гостей на отмену/замену уже принятого
  // заказа, см. backend/routes/kj.py::list_order_change_requests и
  // services/vdj_service.py::approve_order_change_request.
  listOrderChangeRequests: (token, clubId) =>
    request(`/api/kj/order-change-requests/${clubId}`, { token }),
  approveOrderChangeRequest: (token, requestId) =>
    request(`/api/kj/order-change-requests/${requestId}/approve`, { method: "PUT", token }),
  rejectOrderChangeRequest: (token, requestId) =>
    request(`/api/kj/order-change-requests/${requestId}/reject`, { method: "PUT", token }),
  listVipClients: (token, clubId) => request(`/api/kj/vip-clients/${clubId}`, { token }),
  // Описание VIP клуба (запрос пользователя 2026-10-04, перенос из бота) —
  // текст, который видит гость в Guest App на вкладке VIP поверх
  // фиксированного списка преимуществ, см. backend/routes/kj.py::
  // get_vip_settings/update_vip_settings.
  getVipSettings: (token, clubId) => request(`/api/kj/vip-settings/${clubId}`, { token }),
  updateVipSettings: (token, clubId, description) =>
    request(`/api/kj/vip-settings/${clubId}`, {
      method: "PUT", token, body: { vip_description: description },
    }),
  // Фото гостя в карточке VIP-клиента (запрос пользователя 2026-10-01) —
  // необязательное, photoDataUrl === null убирает уже загруженное фото.
  setGuestPhoto: (token, guestId, photoDataUrl) =>
    request(`/api/kj/guests/${guestId}/photo`, {
      method: "PUT", token, body: { photo_data_url: photoDataUrl },
    }),
  getClubStats: (token, clubId, from, to) => {
    const params = new URLSearchParams();
    if (from) params.set("from", from);
    if (to) params.set("to", to);
    params.set("tz", String(-new Date().getTimezoneOffset()));
    return request(`/api/kj/stats/${clubId}?${params.toString()}`, { token });
  },
  getSongListsAdmin: (token) => request("/api/kj/song-lists", { token }),
  hideSongListItem: (token, body) => request("/api/kj/song-lists/hide", { method: "POST", token, body }),
  unhideSongListItem: (token, id) => request(`/api/kj/song-lists/unhide/${id}`, { method: "POST", token }),
  listNewSongs: (token) => request("/api/kj/new-songs", { token }),
  setNewSong: (token, songTitle, artist, isNew) =>
    request("/api/kj/new-songs", {
      method: "PUT", token, body: { song_title: songTitle, artist: artist || null, is_new: isNew },
    }),
  getAutoClose: (token) => request("/api/kj/auto-close", { token }),
  setAutoClose: (token, enabled, time) =>
    request("/api/kj/auto-close", {
      method: "PUT", token, body: { enabled, time, tz_offset: -new Date().getTimezoneOffset() },
    }),
  getGeneralChat: (token) => request("/api/kj/general-chat", { token }),
  setGeneralChat: (token, enabled) =>
    request("/api/kj/general-chat", { method: "PUT", token, body: { enabled } }),
  makeGuestVip: (token, guestId) =>
    request(`/api/kj/guests/${encodeURIComponent(guestId)}/make-vip`, { method: "POST", token }),
  renameGuest: (token, guestId, displayName) =>
    request(`/api/kj/guests/${encodeURIComponent(guestId)}/name`, {
      method: "PUT", token, body: { display_name: displayName },
    }),
  getGuestHistory: (token, clubId, guestId, { from, to } = {}) => {
    const params = new URLSearchParams();
    if (from) params.set("from", from);
    if (to) params.set("to", to);
    const qs = params.toString();
    return request(
      `/api/kj/guests/${clubId}/${encodeURIComponent(guestId)}/history${qs ? `?${qs}` : ""}`,
      { token },
    );
  },
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
  // "Удалить" во вкладке VIP = перевести обратно в простые (запрос
  // пользователя 2026-09-23) — см. docstring vip_service.remove_vip_client.
  removeVipClient: (token, vipClientId) =>
    request(`/api/kj/vip-clients/${vipClientId}`, { method: "DELETE", token }),
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
  // fields — объект с любым подмножеством {table_count, songs_per_table,
  // queue_mode}; бэкенд меняет только те ключи, что реально присутствуют в
  // теле запроса (см. routes/kj.py::update_table_settings), остальные не
  // трогает — этим же пользуется быстрый тумблер режима очереди (см.
  // App.jsx::TableSettingsPanel), отправляя один только queue_mode, не
  // трогая table_count/songs_per_table.
  updateTableSettings: (token, clubId, fields) =>
    request(`/api/kj/table-settings/${clubId}`, { method: "PUT", token, body: fields }),
  // Сброс застрявшего группового стола (жалоба пользователя 2026-09-22):
  // полностью удаляет группу/участников/заявки для table_no — следующий
  // гость за этим столом станет новым админом свежей группы.
  resetTableGroup: (token, clubId, tableNo) =>
    request(`/api/kj/table-group/${clubId}/${tableNo}/reset`, { method: "POST", token }),
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
  // Запрос пользователя 2026-09-19 "Закрыть стол": снять со стола +
  // заблокировать + отклонить оставшиеся заказы стола одним действием —
  // см. guest_status_service.close_table на бэкенде.
  closeGuestTable: (token, guestId) =>
    request(`/api/kj/guests/${encodeURIComponent(guestId)}/close-table`, { method: "POST", token }),
  getBridgeStatus: (token, clubId) => request(`/api/kj/bridge/status/${clubId}`, { token }),
  // ДОБАВЛЕНО (запрос пользователя 2026-09-27, "закрыть стол по инициативе
  // гостя-админа") — заявки гостя-админа группового стола на закрытие
  // (backend/routes/kj.py::list_table_close_requests/approve_table_close_
  // request_route/reject_table_close_request_route). hideReceipt — чекбокс
  // "Не показывать чек" на экране подтверждения; чек всё равно считается и
  // сохраняется на бэкенде, просто не раздаётся гостям.
  listTableCloseRequests: (token, clubId) =>
    request(`/api/kj/table-close-requests/${clubId}`, { token }),
  approveTableCloseRequest: (token, requestId, hideReceipt) =>
    request(`/api/kj/table-close-requests/${requestId}/approve`, {
      method: "PUT", token, body: { hide_receipt: hideReceipt },
    }),
  rejectTableCloseRequest: (token, requestId) =>
    request(`/api/kj/table-close-requests/${requestId}/reject`, { method: "PUT", token }),
  // ДОБАВЛЕНО (запрос пользователя 2026-09-28, "карточка стола") — полный
  // состав компании за столом (в отличие от доски "Заказы по столам", где
  // видны только активные заказы), закрытие стола сразу действием KJ без
  // заявки гостя и перенос стола на новый номер целиком (backend/routes/
  // kj.py::list_table_groups/get_table_group/close_table_group_route/
  // move_table_group_route).
  listTableGroups: (token, clubId) => request(`/api/kj/table-groups/${clubId}`, { token }),
  getTableGroup: (token, clubId, tableNo) =>
    request(`/api/kj/table-groups/${clubId}/${tableNo}`, { token }),
  closeTableGroup: (token, clubId, tableNo, hideReceipt) =>
    request(`/api/kj/table-groups/${clubId}/${tableNo}/close`, {
      method: "PUT", token, body: { hide_receipt: hideReceipt },
    }),
  moveTableGroup: (token, clubId, tableNo, newTableNo) =>
    request(`/api/kj/table-groups/${clubId}/${tableNo}/move`, {
      method: "PUT", token, body: { new_table_no: newTableNo },
    }),
  // ДОБАВЛЕНО (запрос пользователя 2026-09-29, "кнопка. Закрыть все столы.
  // просто закрывает вечер когда все ушли с караоке.") — то же самое
  // закрытие, что и closeTableGroup выше, но сразу для всех занятых столов
  // клуба одним нажатием (backend/routes/kj.py::close_all_table_groups_route).
  // Без hideReceipt — в отличие от закрытия одного стола, эта кнопка НИКОГДА
  // не показывает чек (уточнение пользователя: чеки по нужным столам KJ уже
  // выдал вручную ДО нажатия этой кнопки, см. докстринг table_close_service.
  // close_all_tables), тела запроса вообще нет.
  closeAllTableGroups: (token, clubId) =>
    request(`/api/kj/table-groups/${clubId}/close-all`, {
      method: "PUT", token,
    }),
};

export { ApiError, BACKEND_URL };
