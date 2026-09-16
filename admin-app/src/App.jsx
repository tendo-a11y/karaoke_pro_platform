import { useEffect, useRef, useState } from "react";
import QRCode from "qrcode";
import { GOOGLE_CLIENT_ID, api, ApiError, clearToken, downloadSystemBackup, resolveToken, storeToken } from "./api";
import "./App.css";

// 1:1 перенос utils.format_currency старого бота (config.DEFAULT_CURRENCY="MDL") —
// только форматирование на фронтенде, бизнес-логика не меняется.
function formatMoney(amount) {
  const n = Number(amount);
  const rounded = Number.isInteger(n) ? n : n.toFixed(2);
  return `${rounded} MDL`;
}

// Один QR-код на весь клуб (ТЗ п.45, финальная единая модель входа —
// см. backend/services/club_service.py::get_club_qr_link). ИСПРАВЛЕНО: до
// этого здесь был отдельный QR на каждый стол клуба, с номером стола в
// самой ссылке — это была версия ДО п.45; сервер и Guest App уже давно
// работают по-новому (гость выбирает стол сам внутри приложения, вместе
// со входом через Google), только эта карточка осталась от старого
// варианта. Рендерим QR как data URL прямо в браузере (qrcode, без
// обращения к бэкенду за картинкой — он отдаёт только ссылку).
function QrCodeImage({ url }) {
  const [dataUrl, setDataUrl] = useState(null);

  useEffect(() => {
    let cancelled = false;
    QRCode.toDataURL(url, { width: 180, margin: 1 }).then((result) => {
      if (!cancelled) setDataUrl(result);
    });
    return () => {
      cancelled = true;
    };
  }, [url]);

  return (
    <div className="qr-card">
      <div className="qr-card__label">Общий QR-код клуба</div>
      {dataUrl ? <img src={dataUrl} alt="QR-код входа в клуб" /> : <p className="empty-hint">Генерация…</p>}
      <div className="qr-card__url">{url}</div>
    </div>
  );
}

function ClubForm({ initial, submitLabel, onSubmit, busy, error }) {
  const [name, setName] = useState(initial?.name ?? "");
  const [city, setCity] = useState(initial?.city ?? "");
  const [phone, setPhone] = useState(initial?.phone ?? "");
  const [email, setEmail] = useState(initial?.email ?? "");
  const [tableCount, setTableCount] = useState(
    initial?.table_count != null ? String(initial.table_count) : "",
  );

  function handleSubmit(e) {
    e.preventDefault();
    onSubmit({
      name,
      city: city || null,
      phone: phone || null,
      email: email || null,
      table_count: tableCount === "" ? null : Number(tableCount),
    });
  }

  return (
    <form className="club-form" onSubmit={handleSubmit}>
      <input placeholder="Название клуба" value={name} onChange={(e) => setName(e.target.value)} required />
      <input placeholder="Город" value={city} onChange={(e) => setCity(e.target.value)} />
      <input placeholder="Телефон" value={phone} onChange={(e) => setPhone(e.target.value)} />
      <input placeholder="Email" value={email} onChange={(e) => setEmail(e.target.value)} />
      <input
        placeholder="Число столов"
        type="number"
        min="0"
        value={tableCount}
        onChange={(e) => setTableCount(e.target.value)}
      />
      {error && <div className="banner banner--error">{error}</div>}
      <button type="submit" disabled={busy}>{submitLabel}</button>
    </form>
  );
}

// Блок "Управление KJ" (аудит show_kj_list/kj_assign_start/kj_remove_*/
// admin_kj_stats/kj_toggle_block_*) — живёт внутри карточки клуба, т.к. KJ
// всегда принадлежит ровно одному клубу. GET /api/admin/kj отдаёт ВСЕХ KJ,
// видимых текущему админу (у super_admin — по всем клубам), поэтому здесь
// фильтруем по clubId на клиенте, а не заводим отдельный query-параметр на
// бэкенде — списки заведомо небольшие (число KJ клуба).
function KjManagementPanel({ token, clubId, isSuperAdmin }) {
  const [kjList, setKjList] = useState(null);
  const [loadError, setLoadError] = useState(null);
  const [actionError, setActionError] = useState(null);
  const [busyId, setBusyId] = useState(null);
  const [renameDrafts, setRenameDrafts] = useState({});
  // 2026-09: "доступ KJ Pro определяется Google-аккаунтом клуба" — почта
  // клубного Google-аккаунта редактируется точно так же, как имя (черновик
  // на строку + отдельная кнопка сохранения), см. handleUpdateEmail ниже.
  const [emailDrafts, setEmailDrafts] = useState({});
  const [newTelegramId, setNewTelegramId] = useState("");
  const [newGoogleEmail, setNewGoogleEmail] = useState("");
  const [newDisplayName, setNewDisplayName] = useState("");
  const [assignBusy, setAssignBusy] = useState(false);

  async function reload() {
    try {
      const all = await api.listKj(token);
      setKjList(all.filter((kj) => kj.club_id === clubId));
      setLoadError(null);
    } catch (err) {
      setLoadError(err instanceof ApiError ? err.message : String(err));
    }
  }

  useEffect(() => {
    setKjList(null);
    reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [clubId]);

  // И Telegram ID, и Google-почта — необязательны по отдельности, но нужен
  // хотя бы один (см. kj_admin_service.assign_kj docstring) — раньше
  // telegram_user_id был единственным способом назначить KJ и был required,
  // теперь это просто одно из двух полей формы.
  const canAssign = newTelegramId.trim() !== "" || newGoogleEmail.trim() !== "";

  async function handleAssign(e) {
    e.preventDefault();
    if (!canAssign) {
      setActionError("Укажите Telegram ID и/или Google-почту клуба");
      return;
    }
    setAssignBusy(true);
    setActionError(null);
    try {
      await api.assignKj(token, {
        telegram_user_id: newTelegramId.trim() !== "" ? Number(newTelegramId) : null,
        google_email: newGoogleEmail.trim() !== "" ? newGoogleEmail.trim() : null,
        display_name: newDisplayName,
        club_id: clubId,
      });
      setNewTelegramId("");
      setNewGoogleEmail("");
      setNewDisplayName("");
      await reload();
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setAssignBusy(false);
    }
  }

  async function handleToggle(kj) {
    setBusyId(kj.id);
    setActionError(null);
    try {
      await api.setKjStatus(token, kj.id, !kj.is_active);
      await reload();
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setBusyId(null);
    }
  }

  async function handleRename(kj) {
    const newName = (renameDrafts[kj.id] ?? kj.display_name ?? "").trim();
    if (!newName || newName === kj.display_name) return;
    setBusyId(kj.id);
    setActionError(null);
    try {
      await api.updateKj(token, kj.id, { display_name: newName });
      await reload();
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setBusyId(null);
    }
  }

  async function handleUpdateEmail(kj) {
    const draft = (emailDrafts[kj.id] ?? kj.google_email ?? "").trim();
    if (draft === (kj.google_email ?? "")) return;
    setBusyId(kj.id);
    setActionError(null);
    try {
      // Пустая строка = отвязать Google-аккаунт (сервер трактует null/""
      // как явную очистку google_email и google_sub — см. kj_admin_service
      // update_kj docstring).
      await api.updateKj(token, kj.id, { google_email: draft || null });
      await reload();
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setBusyId(null);
    }
  }

  if (loadError) return <div className="banner banner--error">{loadError}</div>;
  if (!kjList) return <p className="empty-hint">Загрузка…</p>;

  return (
    <div>
      {kjList.length === 0 ? (
        <p className="empty-hint">KJ пока не назначены.</p>
      ) : (
        <ul className="order-list">
          {kjList.map((kj) => (
            <li key={kj.id} className="order-row kj-row">
              <div className="kj-row__main">
                <input
                  className="kj-row__name-input"
                  value={renameDrafts[kj.id] ?? kj.display_name ?? ""}
                  onChange={(e) => setRenameDrafts((prev) => ({ ...prev, [kj.id]: e.target.value }))}
                />
                <span>{kj.is_active ? "🟢" : "🔴"}</span>
              </div>
              <div className="kj-row__stats">
                Сегодня: {kj.orders_completed_today} заказ(ов) · {formatMoney(kj.revenue_today)}
              </div>
              {/* 2026-09: "доступ KJ Pro определяется Google-аккаунтом клуба" —
                  основной способ входа (наряду с /kjpanel через бота, который
                  остаётся резервным), см. docstring KJOperator в models.py. */}
              <div className="kj-row__main">
                <input
                  className="kj-row__name-input"
                  placeholder="Google-почта клуба (не привязана)"
                  value={emailDrafts[kj.id] ?? kj.google_email ?? ""}
                  onChange={(e) => setEmailDrafts((prev) => ({ ...prev, [kj.id]: e.target.value }))}
                />
                <span title={kj.google_linked ? "Google-аккаунт уже входил" : "Ещё ни разу не входили через Google"}>
                  {kj.google_linked ? "🔗" : "⛓️‍💥"}
                </span>
              </div>
              <div className="kj-row__actions">
                <button type="button" className="link-btn" disabled={busyId === kj.id} onClick={() => handleRename(kj)}>
                  Сохранить имя
                </button>
                <button type="button" className="link-btn" disabled={busyId === kj.id} onClick={() => handleUpdateEmail(kj)}>
                  Сохранить почту
                </button>
                <button type="button" className="link-btn" disabled={busyId === kj.id} onClick={() => handleToggle(kj)}>
                  {kj.is_active ? "Заблокировать" : "Активировать"}
                </button>
                {isSuperAdmin && (
                  <span className="kj-row__id">
                    ID Telegram: {kj.telegram_user_id ?? "—"}
                  </span>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}

      {actionError && <div className="banner banner--error">{actionError}</div>}

      <form className="club-form" onSubmit={handleAssign}>
        <input
          placeholder="Telegram ID нового KJ (резервный способ)"
          type="number"
          value={newTelegramId}
          onChange={(e) => setNewTelegramId(e.target.value)}
        />
        <input
          placeholder="Google-почта клуба (основной способ)"
          type="email"
          value={newGoogleEmail}
          onChange={(e) => setNewGoogleEmail(e.target.value)}
        />
        <input
          placeholder="Имя KJ"
          value={newDisplayName}
          onChange={(e) => setNewDisplayName(e.target.value)}
          required
        />
        <button type="submit" disabled={assignBusy || !canAssign}>Назначить KJ в этот клуб</button>
      </form>
      <p className="empty-hint">
        Укажите Telegram ID и/или Google-почту клуба — можно оба сразу. Google-вход основной,
        Telegram /kjpanel через бота остаётся резервным способом.
      </p>
    </div>
  );
}

function ClubDetail({ token, clubId, isSuperAdmin, onClubChanged, onBack }) {
  const [club, setClub] = useState(null);
  const [loadError, setLoadError] = useState(null);
  const [actionError, setActionError] = useState(null);
  const [busy, setBusy] = useState(false);
  const [showQr, setShowQr] = useState(false);
  const [qrData, setQrData] = useState(null);
  const [qrError, setQrError] = useState(null);
  const [showBridgeToken, setShowBridgeToken] = useState(false);

  async function reload() {
    try {
      const data = await api.getClub(token, clubId);
      setClub(data);
      setLoadError(null);
    } catch (err) {
      setLoadError(err instanceof ApiError ? err.message : String(err));
    }
  }

  useEffect(() => {
    setClub(null);
    setLoadError(null);
    setShowQr(false);
    setQrData(null);
    reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [clubId]);

  async function handleEdit(payload) {
    setBusy(true);
    setActionError(null);
    try {
      // PUT /clubs/<id> отдаёт "короткий" club.to_dict() (без kj_operators/
      // revenue_*/songs_count, которые есть только у GET /clubs/<id>) —
      // подставлять его напрямую в club-state нельзя, ниже по дереву
      // рендерится club.kj_operators.length и т.п. Перезапрашиваем полную
      // деталь вместо доверия форме ответа PUT.
      await api.updateClub(token, clubId, payload);
      await reload();
      onClubChanged?.();
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  async function handleToggleStatus() {
    setBusy(true);
    setActionError(null);
    try {
      await api.setClubStatus(token, clubId, !club.is_active);
      await reload();
      onClubChanged?.();
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  async function handleDelete() {
    setBusy(true);
    setActionError(null);
    try {
      await api.deleteClub(token, clubId);
      onClubChanged?.();
      onBack?.();
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  async function handleShowQr() {
    setShowQr(true);
    setQrError(null);
    try {
      const data = await api.getClubQr(token, clubId);
      setQrData(data);
    } catch (err) {
      setQrError(err instanceof ApiError ? err.message : String(err));
    }
  }

  // Запрос пользователя 2026-09-14: для клуба в новом городе не должно
  // требоваться моё ручное участие, чтобы подключить настоящую VirtualDJ —
  // club.bridge_token теперь приходит прямо в ответе GET /clubs/<id> (см.
  // club_service.get_club_detail), здесь только собираем из него готовый
  // файл club_config.txt — тот же формат, что программа-мост (vdj_bridge/
  // vdj_bridge_app.py, см. её докстринг про _load_config) сама подхватывает
  // из своей папки. Как и CSV в ReportsPanel ниже — обычный клиентский
  // download из уже полученного JSON, отдельный authenticated-эндпоинт для
  // файла не нужен.
  function handleDownloadBridgeConfig() {
    if (!club) return;
    const content = `club_id=${club.club_id}\nbridge_token=${club.bridge_token}\n`;
    const blob = new Blob([content], { type: "text/plain;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "club_config.txt";
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  }

  if (loadError) return <div className="banner banner--error">{loadError}</div>;
  if (!club) return <p className="empty-hint">Загрузка…</p>;

  return (
    <div className="panel club-detail">
      {isSuperAdmin && (
        <button type="button" className="link-btn" onClick={onBack}>← Ко всем клубам</button>
      )}
      <h2>{club.name} (ID {club.club_id}) {club.is_active ? "🟢" : "🔴"}</h2>

      <div className="vip-stat-row"><span>Выручка сегодня</span><span>{formatMoney(club.revenue_today)}</span></div>
      <div className="vip-stat-row"><span>Выручка за 7 дней</span><span>{formatMoney(club.revenue_week)}</span></div>
      <div className="vip-stat-row"><span>Выручка за 30 дней</span><span>{formatMoney(club.revenue_month)}</span></div>
      <div className="vip-stat-row"><span>Комиссия админа (30 дней)</span><span>{formatMoney(club.admin_cashback)}</span></div>
      <div className="vip-stat-row"><span>Песен в каталоге</span><span>{club.songs_count}</span></div>

      <h3>KJ клуба</h3>
      <KjManagementPanel token={token} clubId={club.club_id} isSuperAdmin={isSuperAdmin} />

      <h3>Редактировать</h3>
      <ClubForm initial={club} submitLabel="Сохранить" onSubmit={handleEdit} busy={busy} error={actionError} />

      {isSuperAdmin && (
        <div className="club-detail__admin-actions">
          <button type="button" onClick={handleToggleStatus} disabled={busy}>
            {club.is_active ? "Заблокировать клуб" : "Разблокировать клуб"}
          </button>
          <button type="button" className="btn--danger" onClick={handleDelete} disabled={busy}>
            Удалить клуб
          </button>
        </div>
      )}

      <h3>QR-код входа</h3>
      {!showQr && <button type="button" className="link-btn" onClick={handleShowQr}>Показать QR-код</button>}
      {qrError && <div className="banner banner--error">{qrError}</div>}
      {showQr && qrData && (
        <div className="qr-grid">
          <QrCodeImage url={qrData.url} />
        </div>
      )}

      <h3>Мост VirtualDJ</h3>
      <p className="empty-hint">
        Файл club_config.txt нужно положить рядом с программой VDJBridge.exe
        на компьютере KJ — она сама подставит номер клуба и код доступа, и
        KJ останется только нажать «Подключиться», ничего не вводя вручную.
      </p>
      <div className="club-detail__bridge-actions">
        <button type="button" className="link-btn" onClick={() => setShowBridgeToken((v) => !v)}>
          {showBridgeToken ? "Скрыть код доступа" : "Показать код доступа"}
        </button>
        <button type="button" onClick={handleDownloadBridgeConfig}>⬇ Скачать club_config.txt</button>
      </div>
      {showBridgeToken && <code className="club-detail__bridge-token">{club.bridge_token}</code>}
    </div>
  );
}

// Блок "Отчёты" (Block #3, только super_admin) — аудит show_reports_menu/
// report_today/report_week/report_month/report_venues/report_cashback,
// объединённых на бэкенде в один GET /api/admin/reports/overview (см.
// report_service.py docstring). CSV собирается здесь же, на фронтенде, из
// уже полученного JSON — отдельного authenticated download-эндпоинта нет
// (см. согласованный план: обычная ссылка <a href> не может нести
// Bearer-токен). Excel-экспорт старого бота (export_excel/admin_excel_soon)
// был лишь заглушкой "скоро" и сюда не переносится — только CSV.
function ReportsPanel({ token }) {
  const [data, setData] = useState(null);
  const [loadError, setLoadError] = useState(null);

  async function reload() {
    try {
      const overview = await api.getReportsOverview(token);
      setData(overview);
      setLoadError(null);
    } catch (err) {
      setLoadError(err instanceof ApiError ? err.message : String(err));
    }
  }

  useEffect(() => {
    reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function handleDownloadCsv() {
    if (!data) return;
    const header = ["Клуб", "Город", "Выручка сегодня", "Выручка за 7 дней", "Выручка за 30 дней", "Статус"];
    const rows = data.clubs.map((row) => [
      row.name,
      row.city || "",
      row.revenue_today,
      row.revenue_week,
      row.revenue_month,
      row.is_active ? "Активен" : "Заблокирован",
    ]);
    const csv = [header, ...rows]
      .map((line) => line.map((cell) => `"${String(cell).replaceAll('"', '""')}"`).join(","))
      .join("\r\n");
    // \uFEFF — BOM, чтобы Excel на Windows корректно распознал UTF-8 (кириллица).
    const blob = new Blob(["\uFEFF" + csv], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `reports_${new Date().toISOString().slice(0, 10)}.csv`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  }

  if (loadError) return <div className="banner banner--error">{loadError}</div>;
  if (!data) return <p className="empty-hint">Загрузка…</p>;

  return (
    <div>
      <div className="vip-stat-row"><span>Выручка сегодня (все клубы)</span><span>{formatMoney(data.totals.revenue_today)}</span></div>
      <div className="vip-stat-row"><span>Выручка за 7 дней</span><span>{formatMoney(data.totals.revenue_week)}</span></div>
      <div className="vip-stat-row"><span>Выручка за 30 дней</span><span>{formatMoney(data.totals.revenue_month)}</span></div>
      <div className="vip-stat-row"><span>Заказов завершено сегодня</span><span>{data.totals.orders_completed_today}</span></div>
      <div className="vip-stat-row"><span>Комиссия админа сегодня</span><span>{formatMoney(data.totals.admin_commission_today)}</span></div>
      <div className="vip-stat-row"><span>Комиссия админа за 7 дней</span><span>{formatMoney(data.totals.admin_commission_week)}</span></div>
      <div className="vip-stat-row"><span>Комиссия админа за 30 дней</span><span>{formatMoney(data.totals.admin_commission_month)}</span></div>

      <h3>По клубам (сортировка по выручке за 30 дней)</h3>
      {data.clubs.length === 0 ? (
        <p className="empty-hint">Клубов пока нет.</p>
      ) : (
        <ul className="order-list">
          {data.clubs.map((row) => (
            <li key={row.club_id} className="order-row">
              <div className="kj-row__main">
                <span>{row.is_active ? "🟢" : "🔴"} {row.name}{row.city ? ` (${row.city})` : ""}</span>
              </div>
              <div className="kj-row__stats">
                Сегодня: {formatMoney(row.revenue_today)} ({row.percent_of_total_today.toFixed(1)}% от общей) ·
                {" "}7д: {formatMoney(row.revenue_week)} · 30д: {formatMoney(row.revenue_month)} ·
                {" "}заказов сегодня: {row.orders_completed_today}
              </div>
            </li>
          ))}
        </ul>
      )}

      <button type="button" onClick={handleDownloadCsv} style={{ marginTop: 12 }}>
        Скачать CSV
      </button>
    </div>
  );
}

// Блок "Системные функции" (Block #4, только super_admin) — аудит
// show_system_menu/system_logs/system_backup (handlers/admin.py:1131-1229).
// system_support (memory/CPU процесса бота) и system_restart не
// переносятся (см. согласованный план и историю переписки про то, что
// придумывать замену этим экранам не нужно) — единственное, что выжило из
// system_support, это размер БД, перенесённый в overview по прямому
// указанию. "Всего пользователей" заменено на "Заказов всего"
// (COUNT(*) по Order, без интерпретации telegram_user_id как гостя).
function SystemPanel({ token }) {
  const [overview, setOverview] = useState(null);
  const [logs, setLogs] = useState(null);
  const [loadError, setLoadError] = useState(null);
  const [backupBusy, setBackupBusy] = useState(false);
  const [backupError, setBackupError] = useState(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const [overviewData, logsData] = await Promise.all([
          api.getSystemOverview(token),
          api.getSystemLogs(token),
        ]);
        if (cancelled) return;
        setOverview(overviewData);
        setLogs(logsData);
        setLoadError(null);
      } catch (err) {
        if (!cancelled) setLoadError(err instanceof ApiError ? err.message : String(err));
      }
    }
    load();
    return () => {
      cancelled = true;
    };
  }, [token]);

  async function handleDownloadBackup() {
    setBackupBusy(true);
    setBackupError(null);
    try {
      await downloadSystemBackup(token);
    } catch (err) {
      setBackupError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setBackupBusy(false);
    }
  }

  if (loadError) return <div className="banner banner--error">{loadError}</div>;
  if (!overview || !logs) return <p className="empty-hint">Загрузка…</p>;

  return (
    <div>
      <div className="vip-stat-row"><span>Клубов</span><span>{overview.clubs_count}</span></div>
      <div className="vip-stat-row"><span>KJ-операторов (активных)</span><span>{overview.kj_count} ({overview.kj_active_count})</span></div>
      <div className="vip-stat-row"><span>Заказов всего</span><span>{overview.orders_count}</span></div>
      <div className="vip-stat-row"><span>Размер БД</span><span>{overview.db_size_mb} МБ</span></div>
      <div className="vip-stat-row"><span>Время сервера</span><span>{new Date(overview.server_time).toLocaleString()}</span></div>

      <h3>Последние 20 транзакций</h3>
      {logs.length === 0 ? (
        <p className="empty-hint">Журнал пуст.</p>
      ) : (
        <ul className="order-list">
          {logs.map((row, i) => (
            <li key={i} className="order-row">
              <div className="kj-row__stats">
                {row.type}: {formatMoney(row.amount)}
                {row.description ? ` — ${row.description}` : ""}
                <br />
                {new Date(row.created_at).toLocaleString()}
              </div>
            </li>
          ))}
        </ul>
      )}

      {backupError && <div className="banner banner--error">{backupError}</div>}
      <button type="button" onClick={handleDownloadBackup} disabled={backupBusy} style={{ marginTop: 12 }}>
        {backupBusy ? "Формирование бэкапа…" : "Скачать бэкап БД"}
      </button>
    </div>
  );
}

// Блок "Управление администраторами" (запрос пользователя 2026-09, сразу
// после появления входа через Google — до этого единственный способ
// вписать google_email администратору был manage.py по SSH). По образцу
// KjManagementPanel, но: (1) top-level экран, а не внутри карточки клуба —
// администраторы не привязаны к экрану ровно одного клуба так плотно, как
// KJ, и супер-админ должен видеть/заводить их для любого клуба сразу; (2)
// виден только супер-админу (см. admin_admin_service.py docstring про
// то, почему это не то же самое, что "Управление KJ").
function AdminManagementPanel({ token, clubs, currentAdminId }) {
  const [adminsList, setAdminsList] = useState(null);
  const [loadError, setLoadError] = useState(null);
  const [actionError, setActionError] = useState(null);
  const [busyId, setBusyId] = useState(null);
  const [renameDrafts, setRenameDrafts] = useState({});
  const [emailDrafts, setEmailDrafts] = useState({});
  const [newTelegramId, setNewTelegramId] = useState("");
  const [newGoogleEmail, setNewGoogleEmail] = useState("");
  const [newDisplayName, setNewDisplayName] = useState("");
  const [newClubId, setNewClubId] = useState(clubs[0]?.club_id ?? "");
  const [newIsSuperAdmin, setNewIsSuperAdmin] = useState(false);
  const [assignBusy, setAssignBusy] = useState(false);

  async function reload() {
    try {
      const data = await api.listAdmins(token);
      setAdminsList(data);
      setLoadError(null);
    } catch (err) {
      setLoadError(err instanceof ApiError ? err.message : String(err));
    }
  }

  useEffect(() => {
    reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const canAssign = newTelegramId.trim() !== "" || newGoogleEmail.trim() !== "";

  async function handleAssign(e) {
    e.preventDefault();
    if (!canAssign) {
      setActionError("Укажите Telegram ID и/или Google-почту");
      return;
    }
    if (newClubId === "") {
      setActionError("Выберите клуб");
      return;
    }
    setAssignBusy(true);
    setActionError(null);
    try {
      await api.assignAdmin(token, {
        telegram_user_id: newTelegramId.trim() !== "" ? Number(newTelegramId) : null,
        google_email: newGoogleEmail.trim() !== "" ? newGoogleEmail.trim() : null,
        display_name: newDisplayName,
        club_id: Number(newClubId),
        is_super_admin: newIsSuperAdmin,
      });
      setNewTelegramId("");
      setNewGoogleEmail("");
      setNewDisplayName("");
      setNewIsSuperAdmin(false);
      await reload();
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setAssignBusy(false);
    }
  }

  async function handleToggleStatus(a) {
    setBusyId(a.id);
    setActionError(null);
    try {
      await api.setAdminStatus(token, a.id, !a.is_active);
      await reload();
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setBusyId(null);
    }
  }

  async function handleRename(a) {
    const newName = (renameDrafts[a.id] ?? a.display_name ?? "").trim();
    if (!newName || newName === a.display_name) return;
    setBusyId(a.id);
    setActionError(null);
    try {
      await api.updateAdmin(token, a.id, { display_name: newName });
      await reload();
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setBusyId(null);
    }
  }

  async function handleUpdateEmail(a) {
    const draft = (emailDrafts[a.id] ?? a.google_email ?? "").trim();
    if (draft === (a.google_email ?? "")) return;
    setBusyId(a.id);
    setActionError(null);
    try {
      await api.updateAdmin(token, a.id, { google_email: draft || null });
      await reload();
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setBusyId(null);
    }
  }

  async function handleToggleSuperAdmin(a) {
    setBusyId(a.id);
    setActionError(null);
    try {
      await api.updateAdmin(token, a.id, { is_super_admin: !a.is_super_admin });
      await reload();
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setBusyId(null);
    }
  }

  if (loadError) return <div className="banner banner--error">{loadError}</div>;
  if (!adminsList) return <p className="empty-hint">Загрузка…</p>;

  return (
    <div>
      <ul className="order-list">
        {adminsList.map((a) => (
          <li key={a.id} className="order-row kj-row">
            <div className="kj-row__main">
              <input
                className="kj-row__name-input"
                value={renameDrafts[a.id] ?? a.display_name ?? ""}
                onChange={(e) => setRenameDrafts((prev) => ({ ...prev, [a.id]: e.target.value }))}
              />
              <span>{a.is_active ? "🟢" : "🔴"}</span>
              {a.id === currentAdminId && <span className="empty-hint">(это вы)</span>}
            </div>
            <div className="kj-row__stats">
              {a.club_name || `Клуб #${a.club_id}`} · {a.is_super_admin ? "супер-админ" : "админ клуба"}
            </div>
            <div className="kj-row__main">
              <input
                className="kj-row__name-input"
                placeholder="Google-почта (не привязана)"
                value={emailDrafts[a.id] ?? a.google_email ?? ""}
                onChange={(e) => setEmailDrafts((prev) => ({ ...prev, [a.id]: e.target.value }))}
              />
              <span title={a.google_linked ? "Google-аккаунт уже входил" : "Ещё ни разу не входили через Google"}>
                {a.google_linked ? "🔗" : "⛓️‍💥"}
              </span>
            </div>
            <div className="kj-row__actions">
              <button type="button" className="link-btn" disabled={busyId === a.id} onClick={() => handleRename(a)}>
                Сохранить имя
              </button>
              <button type="button" className="link-btn" disabled={busyId === a.id} onClick={() => handleUpdateEmail(a)}>
                Сохранить почту
              </button>
              <button
                type="button" className="link-btn" disabled={busyId === a.id}
                onClick={() => handleToggleSuperAdmin(a)}
              >
                {a.is_super_admin ? "Снять права супер-админа" : "Сделать супер-админом"}
              </button>
              <button
                type="button" className="link-btn" disabled={busyId === a.id || a.id === currentAdminId}
                title={a.id === currentAdminId ? "Нельзя заблокировать самого себя" : undefined}
                onClick={() => handleToggleStatus(a)}
              >
                {a.is_active ? "Заблокировать" : "Активировать"}
              </button>
              <span className="kj-row__id">ID Telegram: {a.telegram_user_id ?? "—"}</span>
            </div>
          </li>
        ))}
      </ul>

      {actionError && <div className="banner banner--error">{actionError}</div>}

      <form className="club-form" onSubmit={handleAssign}>
        <input
          placeholder="Telegram ID нового администратора"
          type="number"
          value={newTelegramId}
          onChange={(e) => setNewTelegramId(e.target.value)}
        />
        <input
          placeholder="Google-почта администратора"
          type="email"
          value={newGoogleEmail}
          onChange={(e) => setNewGoogleEmail(e.target.value)}
        />
        <input
          placeholder="Имя администратора"
          value={newDisplayName}
          onChange={(e) => setNewDisplayName(e.target.value)}
          required
        />
        <select value={newClubId} onChange={(e) => setNewClubId(e.target.value)}>
          {clubs.map((c) => (
            <option key={c.club_id} value={c.club_id}>{c.name} (ID {c.club_id})</option>
          ))}
        </select>
        <label className="empty-hint">
          <input
            type="checkbox"
            checked={newIsSuperAdmin}
            onChange={(e) => setNewIsSuperAdmin(e.target.checked)}
          />
          {" "}Супер-админ (доступ ко всем клубам, отчётам, системе и этому блоку)
        </label>
        <button type="submit" disabled={assignBusy || !canAssign}>Добавить администратора</button>
      </form>
      <p className="empty-hint">
        Укажите Telegram ID и/или Google-почту — можно оба сразу. После первого входа через Google
        почта навсегда привязывается к тому аккаунту, который её подтвердил.
      </p>
    </div>
  );
}

function ClubList({ clubs, onSelect }) {
  return (
    <ul className="order-list">
      {clubs.map((club) => (
        <li key={club.club_id} className="order-row">
          <button type="button" className="link-btn club-list__item" onClick={() => onSelect(club.club_id)}>
            {club.is_active ? "🟢" : "🔴"} {club.name} (ID {club.club_id}) — {formatMoney(club.revenue_today)} сегодня
          </button>
        </li>
      ))}
    </ul>
  );
}

// 2026-09: "нормальный вход через Google в админку" — основной способ
// входа (см. docstring AdminUser в models.py и auth.py::
// issue_admin_google_token), показывается только когда resolveToken() не
// нашёл токен ни в ссылке, ни в localStorage. Ссылка manage.py admin-link
// по-прежнему сама кладёт токен в localStorage при первом же открытии
// (см. resolveToken) и минует этот экран целиком — она остаётся резервным
// способом, полностью равноценным по правам после входа (по образцу
// KjLoginScreen в kj-panel/src/App.jsx).
function AdminLoginScreen({ onLoggedIn }) {
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
      <h1>Karaoke Admin</h1>
      <p>Войдите через свой Google-аккаунт администратора.</p>
      {error && <p className="error-text">{error}</p>}
      <div ref={buttonRef} />
      {busy && <p>Входим…</p>}
      <p className="empty-hint">
        Резервный способ: ссылка, которую выдаёт manage.py admin-link.
      </p>
    </div>
  );
}

export default function App() {
  const [token, setToken] = useState(() => resolveToken());
  const [me, setMe] = useState(null);
  const [clubs, setClubs] = useState([]);
  const [selectedClubId, setSelectedClubId] = useState(null);
  const [loadError, setLoadError] = useState(null);
  const [showCreate, setShowCreate] = useState(false);
  const [createBusy, setCreateBusy] = useState(false);
  const [createError, setCreateError] = useState(null);
  // 'clubs' | 'reports' | 'system' — переключение верхнеуровневых экранов
  // super_admin (обычный админ видит только 'clubs', см. рендер ниже).
  const [view, setView] = useState("clubs");

  async function reloadClubs() {
    try {
      const data = await api.listClubs(token);
      setClubs(data);
    } catch (err) {
      setLoadError(err instanceof ApiError ? err.message : String(err));
    }
  }

  useEffect(() => {
    if (!token) return;

    let cancelled = false;

    async function bootstrap() {
      try {
        const meData = await api.me(token);
        if (cancelled) return;
        setMe(meData);

        const clubsData = await api.listClubs(token);
        if (cancelled) return;
        setClubs(clubsData);
        if (!meData.is_super_admin && clubsData.length === 1) {
          setSelectedClubId(clubsData[0].club_id);
        }
      } catch (err) {
        if (!cancelled) setLoadError(err instanceof ApiError ? err.message : String(err));
      }
    }

    bootstrap();
    return () => {
      cancelled = true;
    };
  }, [token]);

  // Кнопка "Выйти" (запрос пользователя 2026-09, сразу после появления
  // входа через Google — до этого выйти из панели штатно было нельзя
  // вообще, ни через Google, ни по ссылке admin-link). Просто стирает
  // токен и возвращает на экран входа — сама Google-сессия в браузере
  // (аккаунт, выбранный в её окне выбора) не трогается, при следующем
  // входе Google может даже не спросить заново, какой аккаунт выбрать.
  function handleLogout() {
    clearToken();
    setToken(null);
    setMe(null);
  }

  async function handleCreate(payload) {
    setCreateBusy(true);
    setCreateError(null);
    try {
      const created = await api.createClub(token, payload);
      setShowCreate(false);
      await reloadClubs();
      setSelectedClubId(created.club_id);
    } catch (err) {
      setCreateError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setCreateBusy(false);
    }
  }

  if (!token) {
    return <AdminLoginScreen onLoggedIn={setToken} />;
  }

  if (loadError) {
    return (
      <div className="app-shell centered">
        <h1>Karaoke Admin</h1>
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
          <h1>Karaoke Admin</h1>
          <span className="app-header__table">
            {me.display_name || "Админ"} {me.is_super_admin ? "(супер-админ)" : `— ${me.club_name || `Клуб #${me.club_id}`}`}
          </span>
        </div>
        <div className="club-detail__admin-actions">
          {me.is_super_admin && selectedClubId == null && (
            <>
              {view !== "clubs" && (
                <button type="button" className="link-btn" onClick={() => setView("clubs")}>← К клубам</button>
              )}
              {view !== "reports" && (
                <button type="button" className="link-btn" onClick={() => setView("reports")}>📊 Отчёты</button>
              )}
              {view !== "system" && (
                <button type="button" className="link-btn" onClick={() => setView("system")}>⚙️ Система</button>
              )}
              {view !== "admins" && (
                <button type="button" className="link-btn" onClick={() => setView("admins")}>👥 Администраторы</button>
              )}
            </>
          )}
          <button type="button" className="link-btn" onClick={handleLogout}>Выйти</button>
        </div>
      </header>

      <main>
        {selectedClubId == null ? (
          view === "reports" ? (
            <div className="panel">
              <h2>Отчёты по всем клубам</h2>
              <ReportsPanel token={token} />
            </div>
          ) : view === "system" ? (
            <div className="panel">
              <h2>Система</h2>
              <SystemPanel token={token} />
            </div>
          ) : view === "admins" ? (
            <div className="panel">
              <h2>Администраторы</h2>
              <AdminManagementPanel token={token} clubs={clubs} currentAdminId={me.admin_id} />
            </div>
          ) : (
            <div className="panel">
              <h2>Клубы ({clubs.length})</h2>
              {clubs.length === 0 && <p className="empty-hint">Клубов пока нет.</p>}
              <ClubList clubs={clubs} onSelect={setSelectedClubId} />
              {me.is_super_admin && (
                <>
                  {!showCreate && (
                    <button type="button" className="link-btn" onClick={() => setShowCreate(true)}>
                      ➕ Добавить клуб
                    </button>
                  )}
                  {showCreate && (
                    <ClubForm
                      submitLabel="Создать клуб"
                      onSubmit={handleCreate}
                      busy={createBusy}
                      error={createError}
                    />
                  )}
                </>
              )}
            </div>
          )
        ) : (
          <ClubDetail
            token={token}
            clubId={selectedClubId}
            isSuperAdmin={me.is_super_admin}
            onClubChanged={reloadClubs}
            onBack={me.is_super_admin ? () => setSelectedClubId(null) : undefined}
          />
        )}
      </main>
    </div>
  );
}
