import { useEffect, useMemo, useState } from "react";
import QRCode from "qrcode";
import { api, ApiError, downloadSystemBackup, resolveToken } from "./api";
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
  const [newTelegramId, setNewTelegramId] = useState("");
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

  async function handleAssign(e) {
    e.preventDefault();
    setAssignBusy(true);
    setActionError(null);
    try {
      await api.assignKj(token, {
        telegram_user_id: Number(newTelegramId),
        display_name: newDisplayName,
        club_id: clubId,
      });
      setNewTelegramId("");
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
              <div className="kj-row__actions">
                <button type="button" className="link-btn" disabled={busyId === kj.id} onClick={() => handleRename(kj)}>
                  Сохранить имя
                </button>
                <button type="button" className="link-btn" disabled={busyId === kj.id} onClick={() => handleToggle(kj)}>
                  {kj.is_active ? "Заблокировать" : "Активировать"}
                </button>
                {isSuperAdmin && <span className="kj-row__id">ID Telegram: {kj.telegram_user_id}</span>}
              </div>
            </li>
          ))}
        </ul>
      )}

      {actionError && <div className="banner banner--error">{actionError}</div>}

      <form className="club-form" onSubmit={handleAssign}>
        <input
          placeholder="Telegram ID нового KJ"
          type="number"
          value={newTelegramId}
          onChange={(e) => setNewTelegramId(e.target.value)}
          required
        />
        <input
          placeholder="Имя KJ"
          value={newDisplayName}
          onChange={(e) => setNewDisplayName(e.target.value)}
          required
        />
        <button type="submit" disabled={assignBusy}>Назначить KJ в этот клуб</button>
      </form>
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

export default function App() {
  const token = useMemo(() => resolveToken(), []);
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
    return (
      <div className="app-shell centered">
        <h1>Karaoke Admin</h1>
        <p>Ссылка без токена доступа. Откройте панель по ссылке, которую выдаёт CLI-провижининг (manage.py admin-link).</p>
      </div>
    );
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
        {me.is_super_admin && selectedClubId == null && (
          <div className="club-detail__admin-actions">
            {view !== "clubs" && (
              <button type="button" className="link-btn" onClick={() => setView("clubs")}>← К клубам</button>
            )}
            {view !== "reports" && (
              <button type="button" className="link-btn" onClick={() => setView("reports")}>📊 Отчёты</button>
            )}
            {view !== "system" && (
              <button type="button" className="link-btn" onClick={() => setView("system")}>⚙️ Система</button>
            )}
          </div>
        )}
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
