import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ApiError, GOOGLE_CLIENT_ID, api, loadStoredSession, storeSession } from "./api";
import "./App.css";
import { LANG, LANGS, setLang } from "./i18n.js";
import { LEGAL_HTML } from "./i18n_legal.js";

// ДОБАВЛЕНО (2026-10-13): доп. столы между обычными — внутренний номер 7001
// показывается как "7/1".
function tableLabel(n) {
  if (n == null || n === "") return "—";
  const v = Number(n);
  return Number.isInteger(v) && v >= 1000 ? `${Math.floor(v / 1000)}/${v % 1000}` : String(n);
}

// Флажки под кнопками языков (рисунком, чтобы были видны на любом телефоне).
const LANG_FLAGS = {
  ru: (
    <svg viewBox="0 0 9 6" aria-hidden="true">
      <rect width="9" height="2" fill="#fff" />
      <rect y="2" width="9" height="2" fill="#0039a6" />
      <rect y="4" width="9" height="2" fill="#d52b1e" />
    </svg>
  ),
  ro: (
    <svg viewBox="0 0 9 6" aria-hidden="true">
      <rect width="3" height="6" fill="#002b7f" />
      <rect x="3" width="3" height="6" fill="#fcd116" />
      <rect x="6" width="3" height="6" fill="#ce1126" />
    </svg>
  ),
  en: (
    <svg viewBox="0 0 60 30" aria-hidden="true">
      <clipPath id="lang-flag-gb">
        <path d="M30,15 h30 v15 z v15 h-30 z h-30 v-15 z v-15 h30 z" />
      </clipPath>
      <path d="M0,0 v30 h60 v-30 z" fill="#012169" />
      <path d="M0,0 L60,30 M60,0 L0,30" stroke="#fff" strokeWidth="6" />
      <path d="M0,0 L60,30 M60,0 L0,30" clipPath="url(#lang-flag-gb)" stroke="#c8102e" strokeWidth="4" />
      <path d="M30,0 v30 M0,15 h60" stroke="#fff" strokeWidth="10" />
      <path d="M30,0 v30 M0,15 h60" stroke="#c8102e" strokeWidth="6" />
    </svg>
  ),
  uk: (
    <svg viewBox="0 0 3 2" aria-hidden="true">
      <rect width="3" height="1" fill="#0057b7" />
      <rect y="1" width="3" height="1" fill="#ffd700" />
    </svg>
  ),
};

// Переключатель языка RU / RO / EN / UA (запрос пользователя 2026-10).
function LangSwitcher() {
  return (
    <div className="lang-switch">
      {LANGS.map((l) => (
        <button
          key={l.code}
          type="button"
          className={`lang-switch__btn${LANG === l.code ? " lang-switch__btn--active" : ""}`}
          onClick={() => {
            if (LANG !== l.code) setLang(l.code);
          }}
        >
          <span>{l.label}</span>
          <span className="lang-switch__flag">{LANG_FLAGS[l.code]}</span>
        </button>
      ))}
    </div>
  );
}

// ИЗМЕНЕНО (запрос пользователя 2026-09-28: "Мои заказы — это заказы,
// которые ждут своей очереди занять место в карточке стола. НЕ надо нигде
// никаких СПЕТО. Это тупость. Если гость песню не пел то не будет Спето. А
// если даже и пел он знает что он спел песню и ему не надо это писать").
// Раньше здесь был словарь текстовых статусов на каждый order.status (в т.ч.
// "✅ Спето" для уже сыгранных, "🎶 В очереди" и т.п.) — решение пользователя
// сейчас: никакого текстового статуса нигде не показывать, только номер
// места в очереди, когда он есть. Вкладка и так говорит гостю всё нужное
// ("Мои заказы" — ещё не сыграно, "История" — уже было), лишний текст не
// нужен; для уже сыгранных (completed) статус вообще не рендерится (см.
// OrderRow ниже) — гость и так знает, что сам спел свою песню.
//
// QUEUE_POSITION_STATUSES — 1:1 ACTIVE_TABLE_STATUSES на бэкенде
// (table_board_service.py), кроме "playing" — старое значение статуса из
// другого, более раннего пути заказов, у которого своего queue_position не
// считается.
const QUEUE_POSITION_STATUSES = ["pending", "processing", "queued", "error"];

function orderStatusLabel(order) {
  // ДОБАВЛЕНО (2026-10): заказ сверх вместимости стола ждёт своей очереди
  // невидимо для ведущего (order.waiting_position, см. routes/guest.py::
  // list_my_orders) — показываем это гостю явно, а не просто номером.
  if (order.waiting_position != null) {
    return order.queue_position != null
      ? `⏳ Ждёт очереди · #${order.queue_position}`
      : "⏳ Ждёт очереди";
  }
  if (QUEUE_POSITION_STATUSES.includes(order.status) && order.queue_position != null) {
    return `#${order.queue_position}`;
  }
  return null;
}

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
// Опрос новых сообщений ведущего для всплывающего уведомления (2026-10-13).
const POLL_CHAT_POPUP_MS = 8000;
const POLL_ME_MS = 5000;
const POLL_FAVORITES_MS = 5000;
const POLL_TABLE_GROUP_MS = 5000;
const POLL_VIP_TRANSACTIONS_MS = 8000;

// Пикер периода для вкладки "История" (см. ORDERS_TABS ниже) — старое:
// handlers/vip.py::vip_order_history (days_map = {"today":1,"week":7,
// "month":30}, только VIP). Здесь тот же набор периодов, но доступно всем
// ролям.
// ДОБАВЛЕНО (2026-10-09, запрос пользователя): очистка статистики за
// день/неделю/месяц/год с двойным подтверждением. Очищается только в этой
// панели — в других (и в чеках/балансах) всё остаётся.
const CLEAR_PERIODS = [
  { key: "day", label: "За день" },
  { key: "week", label: "За неделю" },
  { key: "month", label: "За месяц" },
  { key: "year", label: "За год" },
];

function ClearStatsControl({ onClear }) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  async function choose(p) {
    if (!window.confirm(`Очистить статистику: ${p.label.toLowerCase()}? Она пропадёт только здесь.`)) return;
    if (!window.confirm("Точно очистить? Вернуть будет нельзя.")) return;
    setBusy(true);
    setError(null);
    try {
      await onClear(p.key);
      setOpen(false);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="clear-stats">
      {!open ? (
        <button type="button" className="link-btn clear-stats__toggle" onClick={() => setOpen(true)}>
          🗑 Очистить
        </button>
      ) : (
        <div className="order-history-periods clear-stats__row">
          {CLEAR_PERIODS.map((p) => (
            <button key={p.key} type="button" className="link-btn" disabled={busy} onClick={() => choose(p)}>
              {p.label}
            </button>
          ))}
          <button type="button" className="link-btn" disabled={busy} onClick={() => setOpen(false)}>
            Отмена
          </button>
        </div>
      )}
      {error && <div className="banner banner--error">{error}</div>}
    </div>
  );
}

const ORDER_HISTORY_PERIODS = [
  { label: "Сегодня", days: 1 },
  { label: "Неделя", days: 7 },
  { label: "Месяц", days: 30 },
  { label: "Все", days: null },
];

// ДОБАВЛЕНО (2026-09-24, запрос пользователя "правильно разделить на две
// вкладки история и мои заказы. Мои заказы это то что происходит в рамках
// одной сессии") — раньше был один список "Мои заказы" с кнопками периода
// (см. ORDER_HISTORY_PERIODS выше), по умолчанию "Сегодня" (фикс от
// 2026-09-22 на жалобу "вижу уже спетые песни из прошлых визитов"). Этого
// оказалось недостаточно: guest_id у вошедшего через Google гостя
// постоянный между визитами (см. docstring routes/guest.py::link_google), а
// "Сегодня" — календарный день, а не "с момента как я в этот раз открыл
// ссылку", так что гость, вернувшийся тем же вечером, снова видел
// вперемешку старое и новое. Теперь два раздельных экрана: "current" — то,
// что происходит в РАМКАХ ЭТОЙ СЕССИИ (?scope=session, см. докстринг
// routes/guest.py::list_my_orders), без кнопок периода вообще — там всегда
// показывается всё с момента выпуска текущего токена; "history" — прежний
// список с кнопками периода, для сознательного просмотра прошлого.
const ORDERS_TABS = [
  { key: "current", label: "Мои заказы" },
  { key: "history", label: "История" },
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

// Статичные документы (политика конфиденциальности / условия использования —
// запрос пользователя 2026-10-04, право на удаление данных + ссылки на эти
// документы в профиле). Раньше лежали отдельными файлами в public/, но
// раздающая статику программа на сервере отдаёт по этим адресам само же
// приложение (как и на любой другой неизвестный адрес) — поэтому текст
// документа показывается прямо здесь, в React, по пути /privacy и /terms
// (а также по старым /privacy.html и /terms.html — на случай, если где-то
// уже есть такая ссылка).
function getLegalPage() {
  const path = window.location.pathname.replace(/\/+$/, "") || "/";
  if (path === "/privacy" || path === "/privacy.html") return "privacy";
  if (path === "/terms" || path === "/terms.html") return "terms";
  return null;
}

const PRIVACY_PAGE_HTML = `
  <h1>Политика конфиденциальности</h1>
  <div class="updated">Проект KARAOKE PRO · обновлено: 4 октября 2026</div>

  <p>
    KARAOKE PRO — это сервис (сайт и приложения), который помогает гостям караоке-клубов
    заказывать песни, общаться с ведущим и пользоваться VIP-балансом. Этот документ
    объясняет простыми словами, какие данные мы собираем, зачем и что вы можете с ними сделать.
  </p>

  <div class="box">
    <strong>Коротко:</strong> мы не продаём ваши данные, не показываем рекламу, не передаём
    данные третьим лицам (кроме входа через Google, если вы сами его используете),
    и не принимаем через сервис никаких платежей — оплата в клубе происходит напрямую,
    наличными или картой, без участия приложения.
  </div>

  <h2>Какие данные мы собираем</h2>
  <ul>
    <li><strong>Технический номер гостя</strong> — случайный номер, который присваивается
    при открытии ссылки/QR-кода клуба. Сам по себе он никого не опознаёт.</li>
    <li><strong>Имя и почта из Google-аккаунта</strong> — только если вы сами решите войти
    через Google, чтобы сохранить историю заказов и не терять доступ при смене устройства.</li>
    <li><strong>Отображаемое имя</strong> — то, что вы сами вводите, чтобы ведущий видел не
    голый номер, а имя.</li>
    <li><strong>Фото</strong> — полностью необязательно, загружается только по вашему
    собственному желанию (или ведущим клуба, если вы его об этом попросили) для удобного
    опознания в VIP-списке.</li>
    <li><strong>Номер стола, заказы песен, сообщения в чате с ведущим, VIP-баланс</strong> —
    то, что нужно для работы самого сервиса в течение вечера.</li>
  </ul>

  <h2>Чего мы не собираем</h2>
  <ul>
    <li>Мы не обрабатываем банковские карты, не храним платёжные данные и не являемся
    платёжной системой — вся оплата происходит лично, между вами и клубом.</li>
    <li>Мы не используем рекламные и аналитические системы отслеживания (сервис не содержит
    счётчиков вроде Google Analytics и подобных).</li>
  </ul>

  <h2>Кто ещё видит ваши данные</h2>
  <p>
    Единственный внешний сервис, который мы используем — это вход через Google (Google
    Identity Services), и только если вы сами им воспользуетесь. Мы используем его лишь
    для подтверждения, что вы — это вы; дальше ваши данные Google мы никому не передаём.
    Данные хранятся на серверах в Евросоюзе (дата-центр в Амстердаме, провайдер Railway).
  </p>

  <h2>Сколько хранятся данные</h2>
  <p>
    Пока вы пользуетесь сервисом или пока сами не попросите их удалить. История заказов и
    VIP-баланс нужны клубу для внутреннего учёта — если вы удалите свой профиль (имя, фото,
    привязку к Google), эта история остаётся в системе клуба, но уже без какой-либо связи
    с вашим именем, фото или почтой — только обезличенный номер.
  </p>

  <h2>Ваши права</h2>
  <ul>
    <li><strong>Посмотреть и исправить</strong> — имя и фото можно менять прямо в приложении
    в любой момент.</li>
    <li><strong>Удалить</strong> — в приложении есть кнопка «Удалить мои данные»: имя, фото
    и привязка к Google стираются сразу и полностью. Также можно написать нам на
    <a href="mailto:nymfa.sv@gmail.com">nymfa.sv@gmail.com</a>.</li>
    <li><strong>Пожаловаться</strong> — если считаете, что с вашими данными обошлись
    неправильно, можно обратиться в Национальный центр по защите персональных данных
    Молдовы (Centrul Național pentru Protecția Datelor cu Caracter Personal).</li>
  </ul>

  <h2>Дети</h2>
  <p>
    Сервис не рассчитан специально на детей. Если выяснится, что данные ребёнка попали
    в систему без согласия родителя — напишите нам, мы удалим их по первому запросу.
  </p>

  <h2>Изменения в этом документе</h2>
  <p>
    Мы можем обновлять этот текст по мере развития сервиса. Дата последнего обновления
    указана вверху страницы.
  </p>

  <h2>Контакты</h2>
  <p>
    По любым вопросам о ваших данных пишите на
    <a href="mailto:nymfa.sv@gmail.com">nymfa.sv@gmail.com</a>.
  </p>

  <a class="back" href="javascript:window.close() || history.back()">← Назад</a>
`;

const TERMS_PAGE_HTML = `
  <h1>Условия использования</h1>
  <div class="updated">Проект KARAOKE PRO · обновлено: 4 октября 2026</div>

  <p>
    Используя KARAOKE PRO (сайт и приложения для гостей, ведущих и администраторов
    караоке-клубов), вы соглашаетесь с условиями ниже. Если что-то непонятно — пишите на
    <a href="mailto:nymfa.sv@gmail.com">nymfa.sv@gmail.com</a>.
  </p>

  <h2>Что такое KARAOKE PRO</h2>
  <p>
    Это вспомогательный цифровой инструмент для караоке-клубов: с его помощью гость
    заказывает песни, общается с ведущим, видит свой VIP-баланс и историю; ведущий
    управляет очередью и клиентами; администратор клуба управляет самим клубом.
    KARAOKE PRO — это программа-помощник, а не сам караоке-клуб: за качество музыки,
    звука, атмосферы и обслуживания в заведении отвечает само заведение, где вы находитесь.
  </p>

  <div class="box">
    <strong>Важно про деньги:</strong> KARAOKE PRO не принимает и не обрабатывает платежи.
    Всё, что связано с оплатой (вход, напитки, пополнение VIP-баланса и т.п.), происходит
    напрямую между вами и клубом — наличными или картой, на месте. Цифры «VIP-баланса» в
    приложении — это просто внутренний учёт клуба, а не платёжный счёт.
  </div>

  <h2>Профиль и вход через Google</h2>
  <p>
    Вход через Google — по желанию. Он нужен, чтобы сохранить ваше имя, фото и историю
    заказов между визитами. Без входа через Google можно пользоваться базовыми функциями
    (посмотреть очередь, предложить песню), но часть функций (VIP, избранное, имя) станет
    доступна только после входа. Вы сами отвечаете за сохранность доступа к своему
    Google-аккаунту.
  </p>

  <h2>Правила поведения</h2>
  <ul>
    <li>Не используйте оскорбительные, незаконные или вводящие в заблуждение имена,
    сообщения или фото.</li>
    <li>Не пытайтесь мешать работе сервиса (взламывать, перегружать запросами, обходить
    ограничения).</li>
    <li>Ведущий или администратор клуба может заблокировать доступ гостю, нарушающему
    эти правила — в своём клубе.</li>
  </ul>

  <h2>Доступность сервиса</h2>
  <p>
    Мы стараемся, чтобы сервис работал стабильно, но не гарантируем круглосуточную
    бесперебойную работу — возможны технические перерывы, обновления и временные сбои.
  </p>

  <h2>Ответственность</h2>
  <p>
    KARAOKE PRO предоставляется «как есть», в качестве вспомогательного инструмента.
    Мы не отвечаем за действия конкретного клуба, качество его обслуживания, доступность
    конкретных песен или соблюдение клубом лицензий на исполняемую музыку — это
    ответственность самого заведения. Мы не отвечаем за споры об оплате, которая прошла
    напрямую между вами и клубом, в обход сервиса.
  </p>

  <h2>Права на контент</h2>
  <p>
    Программное обеспечение и дизайн KARAOKE PRO принадлежат проекту. Контент, который
    вводите вы сами (имя, фото, текст сообщений), остаётся вашим — вы только разрешаете
    использовать его в рамках работы сервиса (например, показать ваше имя ведущему).
  </p>

  <h2>Удаление данных</h2>
  <p>
    Вы можете в любой момент удалить своё имя, фото и привязку к Google-аккаунту прямо в
    приложении («Удалить мои данные») — подробнее в
    <a href="/privacy">Политике конфиденциальности</a>.
  </p>

  <h2>Изменения условий</h2>
  <p>
    Мы можем обновлять эти условия по мере развития сервиса. Дата последнего обновления
    указана вверху страницы. Продолжая пользоваться сервисом после изменений, вы
    соглашаетесь с новой версией.
  </p>

  <h2>Контакты</h2>
  <p>
    По любым вопросам пишите на <a href="mailto:nymfa.sv@gmail.com">nymfa.sv@gmail.com</a>.
  </p>

  <a class="back" href="javascript:window.close() || history.back()">← Назад</a>
`;

function LegalPageScreen({ page }) {
  const html =
    (LEGAL_HTML[LANG] && LEGAL_HTML[LANG][page]) || (page === "privacy" ? PRIVACY_PAGE_HTML : TERMS_PAGE_HTML);
  return (
    <div className="legal-page">
      <div className="wrap" dangerouslySetInnerHTML={{ __html: html }} />
    </div>
  );
}

// ДОБАВЛЕНО (2026-10): общий выбор категории с кнопкой "❓" (описание
// категории) и подтверждением цены для Crazy — то же, что уже есть в
// главной форме заказа, теперь и в "Заказать снова", "Заменить песню" и
// "Заказ через скриншот", чтобы предупреждение о цене нельзя было обойти.
// Отсеки списка категорий: основные и дополнительные (поле section у категории).
const SECTION_KEYS = ["main", "extra"];
const SECTION_TITLES = { main: "Основные", extra: "Дополнительные" };

function ServiceSelect({ services, value, onChange, disabled, highlight = false, onOpen, onOpenChange }) {
  // Свой список выбора категории вместо системного (запрос пользователя
  // 2026-10): в раскрытом списке у каждой категории кнопка "❓", которая
  // открывает карточку категории поверх экрана (название, цена, описание,
  // "Выбрать"/"Закрыть"). CRAZY выбирается ТОЛЬКО через карточку — нажатие
  // на её название тоже открывает карточку, и подтверждение цены находится
  // внутри неё, рядом с описанием ("выбор должен быть осознанным").
  const [open, setOpen] = useState(false);
  useEffect(() => {
    onOpenChange?.(open);
  }, [open]);
  const [cardId, setCardId] = useState(null);
  const selected = services.find((s) => String(s.id) === String(value));
  const card = services.find((s) => String(s.id) === String(cardId));
  const isCrazy = (s) => (s.name || "").trim().toUpperCase() === "CRAZY";
  const labelOf = (s) => `${s.name}${s.is_free ? " (бесплатно)" : ` — ${s.price}`}`;

  function choose(service) {
    if (isCrazy(service)) {
      setCardId(service.id);
      return;
    }
    setOpen(false);
    onChange(String(service.id));
  }

  function confirmCard() {
    onChange(String(card.id));
    setCardId(null);
    setOpen(false);
  }

  return (
    <div className="service-picker">
      {/* Невидимое обязательное поле — чтобы форму по-прежнему нельзя было
      отправить без выбранной категории (раньше это делал required у select). */}
      <input
        className="service-picker__required"
        tabIndex={-1}
        aria-hidden="true"
        required
        value={value || ""}
        onChange={() => {}}
      />
      <button
        type="button"
        className={`service-picker__toggle${highlight && !value && !open ? " step-blink" : ""}`}
        disabled={disabled}
        aria-expanded={open}
        onClick={() => {
          if (!open) onOpen?.();
          setOpen(!open);
        }}
      >
        <span>{selected ? labelOf(selected) : "Выберите категорию…"}</span>
        <span>{open ? "▲" : "▼"}</span>
      </button>
      {open && (
        <div className="service-picker__list">
          {SECTION_KEYS.map((sectionKey) => {
            const group = services
              .map((s, index) => ({ s, index }))
              .filter(({ s }) => (s.section || "main") === sectionKey);
            if (group.length === 0) return null;
            return (
            <div className="service-picker__section" key={sectionKey}>
            <div className="service-picker__section-title">{SECTION_TITLES[sectionKey]}</div>
            <ul className="service-picker__group">
              {group.map(({ s, index }) => (
                <li
                  key={s.id}
                  className={
                    selected && selected.id === s.id
                      ? "service-picker__item--selected"
                      : highlight && !value
                        ? "step-blink-item"
                        : undefined
                  }
                  style={highlight && !value ? { animationDelay: `${index}s `, animationDuration: `${Math.max(services.length, 3)}s ` } : undefined}
                >
                  <div className="service-picker__row">
                    <button type="button" className="service-picker__option" style={s.display_color ? { color: s.display_color } : undefined} onClick={() => choose(s)}>
                      {labelOf(s)}
                      {s.description ? ` (${s.description})` : ""}
                    </button>
                    <button
                      type="button"
                      className="service-picker__info"
                      title="Описание категории"
                      onClick={() => setCardId(s.id)}
                    >
                      ❓
                    </button>
                  </div>
                </li>
              ))}
            </ul>
            </div>
            );
          })}
          <button type="button" className="service-picker__cancel" onClick={() => setOpen(false)}>
            Отмена
          </button>
        </div>
      )}
      {card && (
        <div className="service-card-overlay" onClick={() => setCardId(null)}>
          <div className="service-card" role="dialog" aria-modal="true" onClick={(e) => e.stopPropagation()}>
            <h3 className="service-card__title">{card.name}</h3>
            <p className="service-card__price">{card.is_free ? "Бесплатно" : `Цена: ${card.price}`}</p>
            <p className="service-card__desc">{card.description || "Описание пока не добавлено."}</p>
            {isCrazy(card) && (
              <p className="service-card__warning">
                ⚠️ Это самая дорогая категория: песня вне очереди стоит {card.price} лей.
                Подтвердите, что выбираете её осознанно.
              </p>
            )}
            <div className="service-card__buttons">
              <button type="button" disabled={disabled} onClick={confirmCard}>
                {isCrazy(card) ? `Да, выбираю за ${card.price} лей` : "Выбрать"}
              </button>
              <button type="button" className="service-card__close" onClick={() => setCardId(null)}>
                Закрыть
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// ДОБАВЛЕНО (2026-10, запрос пользователя): небольшие кнопки над живой
// очередью — "История за час", "Популярные" (по 10 в блоке), "Новинки".
// Песню можно сразу заказать: категория -> "Заказать", с подсказками.
const SONG_LIST_TABS = [
  { key: "recent", label: "История за час", empty: "За последний час ещё ничего не спели." },
  { key: "popular", label: "Популярные", empty: "Пока нет данных." },
  { key: "new", label: "Новинки", empty: "Новинок пока нет." },
];
const SONG_LIST_PAGE = 10;
// ДОБАВЛЕНО (2026-10, запрос пользователя "сортировка по алфавиту и по частоте"):
// варианты сортировки для каждого блока. "По частоте" — порядок с сервера
// (сервер уже отдаёт популярные по числу воспроизведений).
const SONG_LIST_SORTS = {
  popular: [
    { key: "freq", label: "По частоте" },
    { key: "alpha", label: "А–Я" },
  ],
  new: [
    { key: "freq", label: "По частоте" },
    { key: "alpha", label: "А–Я" },
  ],
};

function SongListRow({ song, onPick }) {
  // ИЗМЕНЕНО (2026-10, запрос пользователя: "заказ стандартно — с морганием
  // кнопок"): нажатие "Заказать" подставляет песню в обычную форму заказа
  // наверху, дальше всё как всегда — категория, тон, "Заказать".
  return (
    <li className="song-lists__row">
      <div className="song-lists__line">
        <span className="song-lists__title">
          {song.artist ? `${song.artist} — ` : ""}
          {song.song_title}
        </span>
        {typeof song.count === "number" && (
          <span className="song-lists__count">{song.count}</span>
        )}
        <button type="button" className="link-btn" onClick={() => onPick(song)}>
          Заказать
        </button>
      </div>
    </li>
  );
}

function SongListsPanel({ token, onPick, tab, onTab }) {
  // Три кнопки в стиле "ИИ-поиск / Ссылка / Скриншот": нажали — открылся
  // список, а активная очередь свернулась; нажали ещё раз — закрылся.
  const [lists, setLists] = useState(null);
  const [error, setError] = useState(null);
  const [page, setPage] = useState(0);
  const [sortBy, setSortBy] = useState(null);
  // ДОБАВЛЕНО (2026-10, запрос пользователя "свернуть всю панель"): один
  // треугольник сворачивает весь блок; выбранная вкладка запоминается.
  const [collapsed, setCollapsed] = useState(false);
  const [lastTab, setLastTab] = useState(null);

  function toggleCollapsed() {
    if (!collapsed) {
      setLastTab(tab);
      setCollapsed(true);
      onTab(null);
    } else {
      setCollapsed(false);
      if (lastTab) onTab(lastTab);
    }
  }

  const load = useCallback(async () => {
    try {
      setLists(await api.getSongLists(token));
      setError(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    }
  }, [token]);

  useEffect(() => {
    if (!tab) return undefined;
    load();
    const id = setInterval(load, 30000);
    return () => clearInterval(id);
  }, [tab, load]);

  if (collapsed) {
    return (
      <div className="song-lists">
        <div className="finder-modes song-lists__modes">
          <button type="button" className="link-btn song-lists__collapse" onClick={toggleCollapsed} aria-expanded="false">
            Списки песен ▼
          </button>
        </div>
      </div>
    );
  }

  const current = SONG_LIST_TABS.find((t) => t.key === tab);
  const rawItems = (lists && tab && lists[tab]) || [];
  const sortOptions = (tab && SONG_LIST_SORTS[tab]) || [];
  const activeSort = sortOptions.some((o) => o.key === sortBy) ? sortBy : sortOptions[0] && sortOptions[0].key;
  const items = activeSort === "alpha"
    ? [...rawItems].sort((a, b) => {
        const name = (x) => `${x.artist ? `${x.artist} — ` : ""}${x.song_title || ""}`;
        return name(a).localeCompare(name(b), undefined, { sensitivity: "base" });
      })
    : activeSort === "freq"
      ? [...rawItems].sort((a, b) => (b.count || 0) - (a.count || 0))
      : rawItems;
  const pages = tab === "popular" ? Math.ceil(items.length / SONG_LIST_PAGE) : 1;
  const shown = tab === "popular" ? items.slice(page * SONG_LIST_PAGE, (page + 1) * SONG_LIST_PAGE) : items;

  return (
    <div className="song-lists">
      <div className="finder-modes song-lists__modes">
        <div className="finder-group">
          {SONG_LIST_TABS.map((t) => (
            <button
              key={t.key}
              type="button"
              className={`link-btn${tab === t.key ? " finder-modes__active" : ""}`}
              onClick={() => {
                onTab(tab === t.key ? null : t.key);
                setPage(0);
              }}
            >
              {t.label}{" "}
              <span className={`collapsible-caret${tab === t.key ? " collapsible-caret--blink" : ""}`}>
                {tab === t.key ? "▲" : "▼"}
              </span>
            </button>
          ))}
          <button type="button" className="link-btn song-lists__collapse" onClick={toggleCollapsed} aria-expanded="true" aria-label="Свернуть списки">
            ▲
          </button>
        </div>
      </div>
      {current && sortOptions.length > 0 && (
        <div className="song-lists__sort">
          {sortOptions.map((o) => (
            <button
              key={o.key}
              type="button"
              className={`link-btn song-lists__sort-btn${activeSort === o.key ? " song-lists__sort-btn--active" : ""}`}
              onClick={() => {
                setSortBy(o.key);
                setPage(0);
              }}
            >
              {o.label}
            </button>
          ))}
        </div>
      )}
      {current && (
        <div className="song-lists__body">
          {error && <div className="banner banner--error">{error}</div>}
          {!lists && !error && <p className="empty-hint">Загрузка…</p>}
          {lists && items.length === 0 && <p className="empty-hint">{current.empty}</p>}
          {shown.length > 0 && (
            <ol className="song-lists__list" start={tab === "popular" ? page * SONG_LIST_PAGE + 1 : 1}>
              {shown.map((song, i) => (
                <SongListRow key={`${tab}-${page}-${i}-${song.song_title}`} song={song} onPick={onPick} />
              ))}
            </ol>
          )}
          {pages > 1 && (
            <div className="song-lists__pages">
              {Array.from({ length: pages }, (_, i) => (
                <button
                  key={i}
                  type="button"
                  className={`song-lists__page${page === i ? " song-lists__page--active" : ""}`}
                  onClick={() => {
                    setPage(i);
                  }}
                >
                  {i * SONG_LIST_PAGE + 1}–{Math.min((i + 1) * SONG_LIST_PAGE, items.length)}
                </button>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// Приоритет песни за столом (2026-10): гость просит поднять свою песню.
// Заявка уходит KJ; песня встаёт первой или второй только после его подтверждения.
function PriorityRequestButton({ token, orderId }) {
  const [busy, setBusy] = useState(false);
  const [sent, setSent] = useState(false);
  const [error, setError] = useState(null);
  async function handleRequest() {
    setBusy(true);
    setError(null);
    try {
      await api.requestOrderPriority(token, orderId);
      setSent(true);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }
  if (sent) return <span className="empty-hint"> · Запрос приоритета отправлен KJ</span>;
  return (
    <>
      {error && <span className="banner banner--error">{error}</span>}
      <button type="button" className="link-btn" disabled={busy} onClick={handleRequest}>
        {busy ? "Отправляем…" : "⭐ Поставить первой"}
      </button>
    </>
  );
}

function OrderRow({
  order, onFavorite, favoriteBusy,
  token, services, isReplacing, onToggleReplace, onReplace, replaceBusy,
  onCancel, cancelBusy,
  reorder = false, onReordered,
  reorderPickedId = null, onReorderPick,
}) {
  // ДОБАВЛЕНО (2026-10, запрос пользователя): заказ песни прямо из истории —
  // выбор категории и "Заказать снова", с теми же подсказками-морганиями.
  const [reorderServiceId, setReorderServiceId] = useState("");
  const [reorderBusy, setReorderBusy] = useState(false);
  const [reorderError, setReorderError] = useState(null);
  const [reorderDone, setReorderDone] = useState(false);
  const [reorderQueuePos, setReorderQueuePos] = useState(0);
  async function handleReorderFromHistory() {
    setReorderBusy(true);
    setReorderError(null);
    setReorderDone(false);
    try {
      const created = await createOrderMarked(token, order.song_title, order.artist || null, Number(reorderServiceId));
      setReorderServiceId("");
      setReorderQueuePos(created?.queue_position ?? 0);
      setReorderDone(true);
      if (onReordered) await onReordered();
    } catch (err) {
      setReorderError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setReorderBusy(false);
    }
  }
  const label = orderStatusLabel(order);
  // ИЗМЕНЕНО (2026-09-20, решение пользователя "Нужно одобрение KJ (запрос
  // → Одобрить/Отклонить)"): "❌ Отменить заказ"/"🔁 Заменить песню" больше
  // не применяют изменение сразу — они создают заявку (OrderChangeRequest
  // на бэкенде), которую должен одобрить/отклонить KJ. Пока по заказу есть
  // неразобранная заявка (order.pending_change_request, см. routes/guest.py
  // ::list_my_orders), обе кнопки скрываются и вместо них показывается
  // статус ожидания — той же формулировкой, что и у заявки на VIP
  // (VipPanel ниже, "Заявка отправлена — ждите решения ведущего."), чтобы
  // не плодить разные фразы для одного и того же по смыслу состояния.
  const pendingRequest = order.pending_change_request;
  return (
    <li className={`order-row status-${order.status}`}>
      <div className="order-row__song">🎵 {order.song_title}</div>
      {order.artist && <div className="order-row__artist">🎤 {order.artist}</div>}
      {order.tone ? (
        <div>
          🎚 Тон <span className="tone-badge">{order.tone > 0 ? `+${order.tone}` : order.tone}</span>
        </div>
      ) : null}
      {label && <div className="order-row__status">{label}</div>}
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
        замены песни (см. vdj_service.can_replace_order) — это флаг "можно
        ли ВООБЩЕ подать заявку на замену", а не "заказ уже заменён"; сама
        замена происходит только после одобрения KJ (см. pendingRequest
        выше). Фронтенд не дублирует эту логику, только показывает/прячет
        кнопку по флагу. */}
        {!pendingRequest && order.can_replace && (
          <button type="button" className="link-btn" onClick={() => onToggleReplace(order.id)}>
            {isReplacing ? "Свернуть" : "🔁 Заменить песню"}
          </button>
        )}
        {/* ДОБАВЛЕНО (2026-09-20, жалоба "нет возможности удалить"): кнопка
        отмены заказа гостем — показываем по тому же флагу can_replace, что
        и "Заменить песню", потому что backend разрешает подать заявку на
        то и другое ровно для одного и того же набора статусов (PENDING/
        QUEUED, см. vdj_service.CANCELABLE_BY_GUEST_STATUSES == та же
        матрица, что и у can_replace_order) — заводить отдельный флаг
        can_cancel было бы дублированием одной и той же проверки на
        бэкенде. */}
        {order.priority_slot != null && (
          <span className="empty-hint"> · ⭐ приоритет, место {order.priority_slot}</span>
        )}
        {order.priority_requested && order.priority_slot == null && (
          <span className="empty-hint"> · ⭐ запрос приоритета ждёт KJ</span>
        )}
        {!pendingRequest && order.table_no != null && order.priority_slot == null && !order.priority_requested
          && ["pending", "processing", "queued", "error"].includes(order.status) && (
          <PriorityRequestButton token={token} orderId={order.id} />
        )}
        {!pendingRequest && order.can_replace && onCancel && (
          <button
            type="button"
            className="link-btn link-btn--danger"
            disabled={cancelBusy}
            onClick={() => onCancel(order.id)}
          >
            {cancelBusy ? "Отправляем…" : "❌ Отменить заказ"}
          </button>
        )}
      </div>
      {reorder && services.length > 0 && (
        <>
          <ServiceSelect
            services={services}
            value={reorderServiceId}
            onChange={(v) => {
              setReorderServiceId(v);
              setReorderDone(false);
              // Выбрали песню — остальные строки перестают моргать (2026-10-14).
              onReorderPick?.(order.id);
            }}
            disabled={reorderBusy}
            highlight={!reorderPickedId || reorderPickedId === order.id}
            onOpen={() => onReorderPick?.(order.id)}
          />
          <div className="favorite-actions">
            <button
              type="button"
              disabled={reorderBusy || !reorderServiceId}
              className={!reorderBusy && reorderServiceId ? "step-blink-fill" : undefined}
              onClick={handleReorderFromHistory}
            >
              {reorderBusy ? "Отправляем…" : "🔁 Заказать снова"}
            </button>
          </div>
          {reorderError && <div className="banner banner--error">{reorderError}</div>}
          {reorderDone && (
            <div className="banner banner--ok">
              {reorderQueuePos > 0
                ? `«${order.song_title}» — ваш номер в очереди: ${reorderQueuePos}.`
                : `«${order.song_title}» — заказ отправлен ✅`}
            </div>
          )}
        </>
      )}
      {pendingRequest && (
        <p className="empty-hint order-row__pending-request">
          {pendingRequest.kind === "cancel"
            ? "⏳ Заявка на отмену отправлена — ждите решения ведущего."
            : "⏳ Заявка на замену песни отправлена — ждите решения ведущего."}
        </p>
      )}
      {isReplacing && !pendingRequest && (
        <ReplaceForm
          order={order}
          token={token}
          services={services}
          busy={replaceBusy}
          onSubmit={onReplace}
          onCancel={() => onToggleReplace(order.id)}
        />
      )}
    </li>
  );
}

// VIP-панель (Role 3, аудит п.8-9-10-11): "стать VIP" — это заявка,
// которую одобряет KJ, ставя статус на постоянный профиль гостя (ТЗ
// п.45). Старый одноразовый access_code/redeem для входа под VIP на
// другом устройстве удалён целиком вместе с самим механизмом — постоянство
// личности теперь целиком держится на Google (см. GuestAccount), новый
// вход под тем же Google-аккаунтом сам восстанавливает VIP-статус, никакой
// код для этого предъявлять не нужно.
// ИЗМЕНЕНО (запрос пользователя 2026-10-01, "Сообщения" у гостя): раньше
// одна и та же панель показывала и баланс VIP, и кнопку "Стать VIP" для
// ещё не VIP-гостей. Баланс+пополнение переехали в экран "Сообщения" (см.
// VipBalancePanel ниже) — эта панель остаётся на главном экране и теперь
// только про "Стать VIP" (уже VIP-гостям ничего не показывает).
function VipPanel({ token, meInfo, embedded = false }) {
  const [requesting, setRequesting] = useState(false);
  const [requestSent, setRequestSent] = useState(false);
  const [error, setError] = useState(null);

  async function handleRequestVip() {
    setRequesting(true);
    setError(null);
    try {
      await api.requestVip(token);
      setRequestSent(true);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setRequesting(false);
    }
  }

  if (meInfo.is_vip) return null;

  return (
    <section className={embedded ? "vip-panel profile-finance" : "panel vip-panel"}>
      <h2>⭐ VIP-статус</h2>
      {/* ДОБАВЛЕНО (2026-10-04, запрос пользователя "бот и приложение —
      два отдельных инструмента, что в боте то и в приложении, во вкладку
      VIP надо добавить то, что есть в боте") — перенос locales.py::
      become_vip_text старого бота: фиксированный список из трёх пунктов
      (как в боте — пополнение/кешбек/повтор песен) плюс, если KJ его
      заполнил, свой текст клуба сверху (см. backend/routes/guest.py::me,
      club.vip_description; KJ редактирует его в KJ Panel, вкладка VIP). */}
      {meInfo.vip_description && (
        <p className="empty-hint vip-panel__custom-desc">{meInfo.vip_description}</p>
      )}
      <ul className="vip-benefits-list">
        <li>Пополнение баланса через приложение</li>
        <li>Кешбек с заказов</li>
        <li>Повтор любимых песен</li>
      </ul>
      {error && <div className="banner banner--error">{error}</div>}
      {meInfo.vip_request_pending || requestSent ? (
        <p className="empty-hint">Заявка отправлена — ждите решения ведущего.</p>
      ) : (
        <button type="button" onClick={handleRequestVip} disabled={requesting}>
          {requesting ? "Отправляем…" : "🎟 Стать VIP"}
        </button>
      )}
    </section>
  );
}

// ДОБАВЛЕНО (запрос пользователя 2026-10-01, "Сообщения" у гостя): баланс
// VIP, кэшбэк и кнопка "Запросить пополнение" — раньше часть VipPanel выше,
// теперь отдельная панель, которая показывается только на экране
// "Сообщения" (см. App() ниже, view === "messages") и только VIP-гостям.
function VipBalancePanel({ token, meInfo }) {
  const [requestingTopup, setRequestingTopup] = useState(false);
  const [topupSent, setTopupSent] = useState(false);
  const [topupError, setTopupError] = useState(null);

  async function handleRequestTopup() {
    setRequestingTopup(true);
    setTopupError(null);
    try {
      await api.requestVipTopup(token);
      setTopupSent(true);
    } catch (err) {
      setTopupError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setRequestingTopup(false);
    }
  }

  if (!meInfo.is_vip) return null;

  return (
    <section className="panel vip-panel vip-panel--active">
      <h2>⭐ VIP-профиль</h2>
      <div className="vip-stat-row">
        <span>Баланс</span>
        <strong>{meInfo.vip.balance.toFixed(2)}</strong>
      </div>
      <div className="vip-stat-row">
        <span>Кэшбэк</span>
        <strong>{meInfo.vip.cashback_percent}%</strong>
      </div>
      {meInfo.vip_balance_blocked && (
        <>
          <div className="banner banner--error">Пополните баланс, чтобы заказывать новые песни.</div>
          {topupError && <div className="banner banner--error">{topupError}</div>}
          {meInfo.vip_topup_pending || topupSent ? (
            <p className="empty-hint">Запрос на пополнение отправлен — ведущий уже знает.</p>
          ) : (
            <button type="button" onClick={handleRequestTopup} disabled={requestingTopup}>
              {requestingTopup ? "Отправляем…" : "Запросить пополнение"}
            </button>
          )}
        </>
      )}
    </section>
  );
}

// Финансы/история транзакций (Role 3, старое: handlers/vip.py::vip_finances
// — там 4 отдельные секции по типу с промежуточными итогами каждая, здесь
// по принятому решению единая хронологическая лента, см. отчёт по
// Finance/cashback history). Показываем только VIP-гостям — у обычных
// гостей эта лента всегда пуста (транзакции существуют только у VIP).
function VipHistoryPanel({ token, embedded = false }) {
  const [transactions, setTransactions] = useState([]);
  const [error, setError] = useState(null);
  const [loaded, setLoaded] = useState(false);
  // ДОБАВЛЕНО (2026-09-26, запрос пользователя): раньше вся лента операций
  // сразу разворачивалась под заголовком — на экране гостя это занимало
  // много места без необходимости. Теперь список свёрнут по умолчанию и
  // раскрывается только по клику на сам заголовок "Финансы".
  const [open, setOpen] = useState(false);
  // ДОБАВЛЕНО (2026-10, запрос пользователя: "Финансы: Сегодня / Неделя /
  // Месяц / Год") — период, за который показываются операции.
  const [periodDays, setPeriodDays] = useState(7);

  const refresh = useCallback(async () => {
    try {
      const data = await api.listVipTransactions(token, periodDays);
      setTransactions(data);
      setError(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setLoaded(true);
    }
  }, [token, periodDays]);

  // Поллинг, а не разовая загрузка — баланс/история меняются асинхронно
  // (ручная корректировка KJ, завершение песни с кэшбэком), у Guest App
  // нет WebSocket-подключения (см. комментарий у POLL_*_MS выше). Тот же
  // принятый oxlint "set-state-in-effect" случай, что и в остальных
  // поллинг-панелях этого файла.
  useEffect(() => {
    refresh();
    const id = setInterval(refresh, POLL_VIP_TRANSACTIONS_MS);
    return () => clearInterval(id);
  }, [refresh]);

  if (!loaded) return null;

  return (
    <section className={embedded ? "vip-history-panel profile-finance" : "panel vip-history-panel"}>
      <h2
        className="collapsible-header"
        role="button"
        tabIndex={0}
        aria-expanded={open}
        onClick={() => setOpen((prev) => !prev)}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            setOpen((prev) => !prev);
          }
        }}
      >
        🧾 Финансы
        <span className="collapsible-caret">{open ? "▲" : "▼"}</span>
      </h2>
      {open && (
        <>
          <ClearStatsControl
            onClear={async (period) => {
              await api.clearMyHistory(token, "finance", period);
              await refresh();
            }}
          />
          <div className="order-history-periods">
            {[
              { label: "Сегодня", days: 1 },
              { label: "Неделя", days: 7 },
              { label: "Месяц", days: 30 },
              { label: "Год", days: 365 },
            ].map((p) => (
              <button
                key={p.days}
                type="button"
                className={`link-btn${periodDays === p.days ? " order-history-periods__active" : ""}`}
                onClick={() => setPeriodDays(p.days)}
              >
                {p.label}
              </button>
            ))}
          </div>
          {error && <div className="banner banner--error">{error}</div>}
          {transactions.length === 0 ? (
            <p className="empty-hint">За этот период операций по счёту нет.</p>
          ) : (
            <ul className="order-list">
              {transactions.map((tx) => {
                const meta = TX_TYPE_META[tx.type] || { icon: "•", label: tx.type, sign: "" };
                return (
                  <li key={tx.id} className="order-row vip-tx-row">
                    <div className="vip-tx-row__main">
                      <span>{meta.icon} {meta.label}</span>
                      <strong className={meta.sign === "+" ? "vip-tx-amount--credit" : "vip-tx-amount--debit"}>
                        {meta.sign}{tx.amount.toFixed(2)}
                      </strong>
                    </div>
                    {tx.description && <div className="order-row__artist">{tx.description}</div>}
                    <div className="order-row__status">{new Date(tx.created_at).toLocaleString()}</div>
                  </li>
                );
              })}
            </ul>
          )}
        </>
      )}
    </section>
  );
}

function FavoritesPanel({ token, services, onOrdered, orderingDisabled, embedded = false }) {
  const [favorites, setFavorites] = useState([]);
  const [error, setError] = useState(null);
  const [orderMessage, setOrderMessage] = useState(null);
  const [busyId, setBusyId] = useState(null);
  const [serviceSelections, setServiceSelections] = useState({});
  // ДОБАВЛЕНО (2026-10): тон для каждой строки избранного — { [id]: { on, tone } }.
  const [toneSelections, setToneSelections] = useState({});
  // Избранное, где уже начали выбирать категорию — у остальных строк подсказка-мигание гаснет (2026-10-14).
  const [pickedFavoriteId, setPickedFavoriteId] = useState(null);
  // ДОБАВЛЕНО (2026-10, запрос пользователя "раздел избранное должен
  // открываться, там может быть много песен") — раздел свёрнут по
  // умолчанию и раскрывается по нажатию на заголовок (тот же приём, что и
  // у "Финансы" ниже, .collapsible-header).
  const [open, setOpen] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const data = await api.listFavorites(token);
      setFavorites(data);
    } catch {
      // Список избранного не критичен для основного потока заказа.
    }
  }, [token]);

  // Опрос, а не разовая загрузка: добавление в избранное происходит из
  // OrderRow в родительском App (кнопка "В избранное" под заказом), у
  // которого нет прямой ссылки на состояние этой панели — без периодического
  // опроса свежедобавленная песня не появилась бы в списке до перезагрузки
  // страницы. Тот же принятый oxlint "set-state-in-effect" случай, что и в
  // ChatPanel/опросе заказов/очереди/профиля выше (нет WebSocket у Guest App).
  useEffect(() => {
    refresh();
    const id = setInterval(refresh, POLL_FAVORITES_MS);
    return () => clearInterval(id);
  }, [refresh]);

  async function handleReorder(favoriteId) {
    const serviceId = serviceSelections[favoriteId];
    if (!serviceId) return;
    setBusyId(favoriteId);
    setError(null);
    setOrderMessage(null);
    try {
      const rowTone = toneSelections[favoriteId];
      const toneValue = rowTone && rowTone.on && rowTone.tone != null ? rowTone.tone : null;
      const created = await api.reorderFavorite(token, favoriteId, Number(serviceId), toneValue);
      const pos = created?.queue_position ?? 0;
      const title = favorites.find((x) => x.id === favoriteId)?.song_title || "Песня";
      setOrderMessage(pos > 0 ? `«${title}» — ваш номер в очереди: ${pos}.` : `«${title}» — заказ отправлен ✅`);
      setServiceSelections((prev) => {
        const next = { ...prev };
        delete next[favoriteId];
        return next;
      });
      setToneSelections((prev) => {
        const next = { ...prev };
        delete next[favoriteId];
        return next;
      });
      await onOrdered();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setBusyId(null);
    }
  }

  function setRowTone(favoriteId, value) {
    setToneSelections((prev) => ({ ...prev, [favoriteId]: { on: true, tone: value } }));
  }

  async function handleDelete(favoriteId) {
    setBusyId(favoriteId);
    try {
      await api.deleteFavorite(token, favoriteId);
      await refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setBusyId(null);
    }
  }

  return (
    <section className={embedded ? "profile-finance" : "panel"}>
      {embedded ? (
        <h2>Избранное ({favorites.length})</h2>
      ) : (
      <h2
        className="collapsible-header"
        role="button"
        tabIndex={0}
        aria-expanded={open}
        onClick={() => setOpen((prev) => !prev)}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            setOpen((prev) => !prev);
          }
        }}
      >
        Избранное ({favorites.length})
        <span className="collapsible-caret">{open ? "▲" : "▼"}</span>
      </h2>
      )}
      {error && <div className="banner banner--error">{error}</div>}
      {orderMessage && <div className="banner banner--ok">{orderMessage}</div>}
      {!open && !embedded ? null : favorites.length === 0 ? (
        <p className="empty-hint">Пока пусто — добавляйте песни из "Моих заказов".</p>
      ) : (
        <ul className="order-list">
          {favorites.map((f) => (
            <li key={f.id} className="order-row">
              <div className="order-row__song">🎵 {f.song_title}</div>
              {f.artist && <div className="order-row__artist">🎤 {f.artist}</div>}
              {services.length > 0 && (
                <ServiceSelect
                  services={services}
                  value={serviceSelections[f.id] || ""}
                  onChange={(v) => setServiceSelections((prev) => ({ ...prev, [f.id]: v }))}
                  disabled={busyId === f.id || orderingDisabled}
                  highlight={!orderingDisabled && (!pickedFavoriteId || pickedFavoriteId === f.id)}
                  onOpen={() => setPickedFavoriteId(f.id)}
                />
              )}
              <div className="tone-picker">
                <label className="tone-picker__check">
                  <input
                    type="checkbox"
                    checked={!!(toneSelections[f.id] && toneSelections[f.id].on)}
                    disabled={busyId === f.id || orderingDisabled}
                    onChange={(e) => {
                      const on = e.target.checked;
                      setToneSelections((prev) => ({
                        ...prev,
                        [f.id]: { on, tone: on ? (prev[f.id] && prev[f.id].tone) ?? null : null },
                      }));
                    }}
                  />
                  🎚 Тон
                  {toneSelections[f.id] && toneSelections[f.id].on && toneSelections[f.id].tone != null ? (
                    <span className="tone-badge">
                      {toneSelections[f.id].tone > 0 ? `+${toneSelections[f.id].tone}` : toneSelections[f.id].tone}
                    </span>
                  ) : null}
                  {toneSelections[f.id] && toneSelections[f.id].on && toneSelections[f.id].tone == null ? (
                    <span className="tone-picker__hint">выберите</span>
                  ) : null}
                </label>
                {toneSelections[f.id] && toneSelections[f.id].on && (
                  <div className="tone-picker__row">
                    <div className="tone-picker__side">
                      {[-6, -5, -4, -3, -2, -1].map((t) => (
                        <button key={t} type="button" className={`tone-picker__btn${toneSelections[f.id].tone === t ? " tone-picker__btn--active" : ""}`} disabled={busyId === f.id || orderingDisabled} onClick={() => setRowTone(f.id, t)}>
                          {t}
                        </button>
                      ))}
                    </div>
                    <div className="tone-picker__side">
                      {[1, 2, 3, 4, 5, 6].map((t) => (
                        <button key={t} type="button" className={`tone-picker__btn${toneSelections[f.id].tone === t ? " tone-picker__btn--active" : ""}`} disabled={busyId === f.id || orderingDisabled} onClick={() => setRowTone(f.id, t)}>
                          +{t}
                        </button>
                      ))}
                    </div>
                  </div>
                )}
              </div>
              <div className="favorite-actions">
                <button
                  type="button"
                  disabled={busyId === f.id || orderingDisabled || !serviceSelections[f.id]}
                  className={
                    busyId !== f.id && !orderingDisabled && serviceSelections[f.id] ? "step-blink-fill" : undefined
                  }
                  onClick={() => handleReorder(f.id)}
                  title={orderingDisabled ? "Недоступно, пока вы не одобренный участник группового стола" : undefined}
                >
                  🔁 Заказать снова
                </button>
                <button
                  type="button"
                  className="link-btn"
                  disabled={busyId === f.id}
                  onClick={() => handleDelete(f.id)}
                >
                  🗑 Удалить
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

// Поиск по каталогу клуба (Role 3/4/5, аудит п.1). Каталог заполняется
// только через CSV-импорт KJ (POST /api/kj/songs/import) — как и в старом
// боте, синхронизации с VirtualDJ нет. Выбор результата не создаёт заказ
// сам по себе (в отличие от старого инлайн-поиска Telegram, где выбор
// вставлял текст в чат) — здесь это просто заполняет форму заказа ниже,
// потому что в Guest App нет аналога "отправить сообщение в чат боту": сам
// алгоритм поиска (подстрока/сортировка/лимит 50) перенесён 1:1, а способ
// передать выбор в форму — необходимая адаптация под веб-UI, не новая
// бизнес-логика поиска.
//
// РЕШЕНИЕ ПОЛЬЗОВАТЕЛЯ (2026-09): этот компонент больше НЕ показывается
// гостю нигде в интерфейсе — практика показала, что каталог клуба обычно
// пуст (пока KJ не загрузит CSV), из-за чего гость видит только "ничего не
// найдено" и путает это с поломкой. Убрано намеренно только само поле у
// гостя — сама возможность (поиск по каталогу, импорт CSV у KJ) оставлена
// в коде на будущее, ничего не удалялось из backend. Компонент оставлен
// неиспользуемым сознательно (см. предупреждение линтера "не используется"
// — это ожидаемо), а не забыт.
const SEARCH_DEBOUNCE_MS = 300;

function SongSearch({ token, onPick }) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState([]);
  const [searching, setSearching] = useState(false);

  // oxlint "set-state-in-effect" — принятый случай, как и у остальных
  // опросов выше: этот эффект синхронизирует результаты поиска с внешней
  // системой (backend), реагируя на изменение query, а не на прямое
  // событие ввода (нужен debounce через setTimeout, не в обработчике).
  useEffect(() => {
    const q = query.trim();
    if (!q) {
      setResults([]);
      setSearching(false);
      return undefined;
    }
    setSearching(true);
    let cancelled = false;
    const id = setTimeout(async () => {
      try {
        const data = await api.searchSongs(token, q);
        if (!cancelled) setResults(data);
      } catch {
        if (!cancelled) setResults([]);
      } finally {
        if (!cancelled) setSearching(false);
      }
    }, SEARCH_DEBOUNCE_MS);
    return () => {
      cancelled = true;
      clearTimeout(id);
    };
  }, [query, token]);

  return (
    <div className="song-search">
      <input
        type="text"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        placeholder="🔍 Поиск по каталогу клуба"
      />
      {searching && <p className="empty-hint">Ищем…</p>}
      {!searching && query.trim() && results.length === 0 && (
        <p className="empty-hint">Ничего не найдено в каталоге клуба.</p>
      )}
      {results.length > 0 && (
        <ul className="song-search__results">
          {results.map((s) => (
            <li key={s.id} className={s.ordered_today ? "song-search__item--ordered" : undefined}>
              <button
                type="button"
                className="link-btn"
                onClick={() => {
                  onPick(s);
                  setQuery("");
                  setResults([]);
                }}
              >
                🎵 {s.artist ? `${s.artist} — ${s.title}` : s.title}
                {s.ordered_today && <span className="song-search__ordered-badge"> · уже заказана сегодня</span>}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

// Поиск песни тремя способами (Role 3/4/5). Раньше это было одно окошко
// свободного текста (AiSearch) — гость мог вставить туда же ссылку, и
// backend сам определял, что это ссылка, а не описание (см.
// backend/services/ai_search_service.py::_looks_like_link/_resolve_link).
// По просьбе пользователя (2026-09) это теперь явные три кнопки-режима, а
// не спрятанное автоопределение: гость сам выбирает, чем ищет. "Ссылка" и
// "ИИ-поиск" отправляют текст в тот же самый эндпоинт api.aiSearchSongs —
// вся разница только в подсказке и плейсхолдере, backend не поменялся.
// "Скриншот" (2026-09) отправляет картинку в отдельный эндпоинт
// api.screenshotSearchSongs — Клод сам смотрит на картинку
// (backend/services/ai_search_service.py::_ask_claude_vision) и определяет
// название/исполнителя, дальше поиск в iTunes идёт так же, как у двух
// других режимов.
const FINDER_MODES = [
  { key: "text", label: "🤖 ИИ-поиск" },
  { key: "link", label: "🔗 Ссылка" },
  { key: "screenshot", label: "📷 Скриншот" },
];

// Скриншот с телефона может весить несколько мегабайт — сжимаем через
// canvas перед отправкой (быстрее для гостя на мобильном интернете и не
// упирается в лимит размера картинки у Claude API). Результат — всегда
// JPEG, независимо от исходного формата (PNG со скриншота и так почти
// всегда без прозрачности, а на распознавание текста Клодом это не влияет).
const SCREENSHOT_MAX_DIM = 1280;
const SCREENSHOT_JPEG_QUALITY = 0.82;

function resizeImageToBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(new Error("Не удалось прочитать файл"));
    reader.onload = () => {
      const img = new Image();
      img.onerror = () => reject(new Error("Не удалось открыть изображение"));
      img.onload = () => {
        let { width, height } = img;
        if (width > SCREENSHOT_MAX_DIM || height > SCREENSHOT_MAX_DIM) {
          if (width >= height) {
            height = Math.round((height * SCREENSHOT_MAX_DIM) / width);
            width = SCREENSHOT_MAX_DIM;
          } else {
            width = Math.round((width * SCREENSHOT_MAX_DIM) / height);
            height = SCREENSHOT_MAX_DIM;
          }
        }
        const canvas = document.createElement("canvas");
        canvas.width = width;
        canvas.height = height;
        canvas.getContext("2d").drawImage(img, 0, 0, width, height);
        const dataUrl = canvas.toDataURL("image/jpeg", SCREENSHOT_JPEG_QUALITY);
        const base64 = dataUrl.split(",")[1];
        if (!base64) {
          reject(new Error("Не удалось обработать изображение"));
          return;
        }
        resolve({ base64, mediaType: "image/jpeg" });
      };
      img.src = reader.result;
    };
    reader.readAsDataURL(file);
  });
}

const TYPING_PHRASES = ["Рюмка водки Лепс", "Oriunde ai fi Balan"];

function useTypingPlaceholder(phrases, enabled) {
  const [hint, setHint] = useState("");
  useEffect(() => {
    if (!enabled) { setHint(""); return; }
    if (window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) {
      setHint(phrases[0]);
      return;
    }
    let phraseIdx = 0, charIdx = 0, deleting = false, timer;
    const tick = () => {
      const phrase = phrases[phraseIdx];
      if (!deleting) {
        charIdx++;
        setHint(phrase.slice(0, charIdx));
        if (charIdx === phrase.length) { deleting = true; timer = setTimeout(tick, 1800); return; }
        timer = setTimeout(tick, 70);
      } else {
        charIdx--;
        setHint(phrase.slice(0, charIdx));
        if (charIdx === 0) { deleting = false; phraseIdx = (phraseIdx + 1) % phrases.length; timer = setTimeout(tick, 400); return; }
        timer = setTimeout(tick, 40);
      }
    };
    timer = setTimeout(tick, 400);
    return () => clearTimeout(timer);
  }, [enabled, phrases]);
  return hint;
}

function AiSearch({ token, onPick, onScreenshotHelp, extra = null, onExtra, onSuggestOther, onSearchStart, onAiStatus, active = false, showProfileTabs = true }) {
  // "Не эта" под найденной песней: подсказываем другие способы — моргают "Ссылка" и "Скриншот".
  const [suggestOther, setSuggestOther] = useState(false);
  // Неудачный поиск — пусть ещё моргает поле "Название песни" (запрос пользователя 2026-10).
  useEffect(() => {
    if (onSuggestOther) onSuggestOther(suggestOther);
  }, [suggestOther, onSuggestOther]);
  const [mode, setMode] = useState("text");
  const [text, setText] = useState("");
  const [results, setResults] = useState([]);
  const [searching, setSearching] = useState(false);
  const [searched, setSearched] = useState(false);
  const [error, setError] = useState(null);
  const screenshotInputRef = useRef(null);

  function switchMode(nextMode) {
    setMode(nextMode);
    setText("");
    setResults([]);
    setSearched(false);
    setError(null);
    if (screenshotInputRef.current) screenshotInputRef.current.value = "";
  }

  async function handleScreenshotChange(event) {
    const file = event.target.files && event.target.files[0];
    if (!file) return;
    if (onSearchStart) onSearchStart();
    setSearching(true);
    setError(null);
    setSearched(false);
    setResults([]);
    try {
      const { base64, mediaType } = await resizeImageToBase64(file);
      const data = await api.screenshotSearchSongs(token, base64, mediaType);
      setResults(data);
      setSearched(true);
      // Не нашли — подсказываем другие способы (моргают "Ссылка" и "Скриншот").
      if (!data || data.length === 0) setSuggestOther(true);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
      setSuggestOther(true);
    } finally {
      setSearching(false);
      event.target.value = "";
    }
  }

  async function handleSearch(event) {
    event.preventDefault();
    if (!text.trim()) return;
    // Режим "Ссылка": принимаем только ссылку с YouTube (запрос пользователя 2026-10-09).
    if (mode === "link" && !/^https?:\/\/(www\.|m\.|music\.)?(youtube\.com|youtu\.be)\//i.test(text.trim())) {
      setError("Нужна ссылка с YouTube — откройте песню в YouTube, нажмите «Поделиться» и вставьте ссылку сюда.");
      setResults([]);
      setSearched(false);
      return;
    }
    if (onSearchStart) onSearchStart();
    setSearching(true);
    setError(null);
    setSearched(false);
    try {
      const data = await api.aiSearchSongs(token, text.trim());
      setResults(data);
      setSearched(true);
      // ДОБАВЛЕНО (2026-10-18): ИИ-поиск отвечает — поля ввода песни остаются скрыты.
      if (onAiStatus) onAiStatus(true);
      // ДОБАВЛЕНО (2026-10, запрос пользователя): неудачный поиск — сразу
      // моргают "Ссылка" и "Скриншот", как после "Не эта".
      if (!data || data.length === 0) setSuggestOther(true);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
      setSuggestOther(true);
      // ДОБАВЛЕНО (2026-10-18): ИИ-поиск не ответил — открываем поля названия и исполнителя.
      if (onAiStatus) onAiStatus(false);
    } finally {
      setSearching(false);
    }
  }

  const typingHint = useTypingPlaceholder(TYPING_PHRASES, mode === "text" && !text);
  const placeholder = mode === "link"
    ? "🔗 Вставьте ссылку на песню с YouTube"
    : (typingHint || "🤖 Опишите песню своими словами");
  const emptyHint = mode === "link"
    ? "По этой ссылке не удалось определить песню — проверьте, что это ссылка на конкретный трек."
    : "Ничего не нашлось по описанию — попробуйте другой режим поиска.";

  return (
    <div className={`ai-search${searching || active ? " is-searching" : ""}`}>
      <div className="finder-modes">
        <div className="finder-group">
        {/* Распознавание скриншота отключено (2026-10-09): кнопка "Скриншот"
        есть только там, где она отправляет картинку ведущему. */}
        {FINDER_MODES.filter((m) => m.key !== "screenshot" || onScreenshotHelp).map((m) => (
          <button
            key={m.key}
            type="button"
            className={`link-btn${mode === m.key && !extra ? " finder-modes__active" : ""}${suggestOther && (m.key === "link" || m.key === "screenshot") ? " step-blink" : ""}`}
            onClick={() => {
              setSuggestOther(false);
              if (extra && onExtra) onExtra(null);
              if (m.key === "screenshot" && onScreenshotHelp) onScreenshotHelp();
              else switchMode(m.key);
            }}
          >
            {m.label}
          </button>
        ))}
        </div>
        {onExtra ? (
          <div className="finder-group finder-group--extra">
            {[
              { key: "orders", label: "Мои заказы" },
              { key: "fav", label: "Избранное" },
              { key: "history", label: "История" },
            ].filter((b) => showProfileTabs || (b.key !== "fav" && b.key !== "history")).map((b) => (
              <button
                key={b.key}
                type="button"
                className={`link-btn finder-modes__fav${extra === b.key ? " finder-modes__active" : ""}`}
                onClick={() => onExtra(b.key)}
              >
                {b.label}
              </button>
            ))}
          </div>
        ) : null}
      </div>

      {extra ? null : mode === "screenshot" ? (
        <div className="screenshot-search">
          <p className="empty-hint">
            Загрузите скриншот из Shazam, Spotify, ВКонтакте или похожего приложения — определим песню по картинке.
          </p>
          <input
            ref={screenshotInputRef}
            type="file"
            accept="image/*"
            className="screenshot-search__input"
            onChange={handleScreenshotChange}
            disabled={searching}
          />
          {searching && <p className="empty-hint">Распознаём…</p>}
          {error && <div className="banner banner--error">{error}</div>}
          {searched && !searching && results.length === 0 && (
            <p className="empty-hint">Не удалось разобрать песню на скриншоте — попробуйте другой скриншот или другой режим поиска.</p>
          )}
          {results.length > 0 && (
            <ul className="song-search__results">
              {results.map((s, idx) => (
                <li key={idx} className={s.ordered_today ? "song-search__item--ordered" : undefined}>
                  <button
                    type="button"
                    className="link-btn"
                    onClick={() => {
                      onPick(mode === "link" ? { ...s, link: text.trim() } : s);
                      setResults([]);
                      setSearched(false);
                      if (screenshotInputRef.current) screenshotInputRef.current.value = "";
                    }}
                  >
                    🎵 {s.artist ? `${s.artist} — ${s.title}` : s.title}
                    {s.ordered_today && <span className="song-search__ordered-badge"> · уже заказана сегодня</span>}
                  </button>
                  <div className="song-confirm-row">
                    <button
                      type="button"
                      className="song-confirm song-confirm--yes step-blink"
                      onClick={() => {
                        onPick(mode === "link" ? { ...s, link: text.trim() } : s);
                        setResults([]);
                        setSearched(false);
                        setSuggestOther(false);
                        if (screenshotInputRef.current) screenshotInputRef.current.value = "";
                      }}
                    >
                      ✅ Эта?
                    </button>
                    <button
                      type="button"
                      className="song-confirm song-confirm--no"
                      onClick={() => {
                        const next = results.filter((_, i) => i !== idx);
                        setResults(next);
                        if (next.length === 0) {
                          setSearched(false);
                          setSuggestOther(true);
                        }
                      }}
                    >
                      ✕ Не эта
                    </button>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>
      ) : (
        <>
          <form className="order-form" onSubmit={handleSearch}>
            <input
              type="text"
              value={text}
              onChange={(e) => setText(e.target.value)}
              placeholder={placeholder}
              maxLength={300}
            />
            <button type="submit" className={searching ? "is-searching" : undefined} disabled={searching || !text.trim()}>
              {searching ? "Ищем песню. Ждите..." : "Найти"}
            </button>
          </form>
          {error && <div className="banner banner--error">{error}</div>}
          {searched && !searching && results.length === 0 && (
            <p className="empty-hint">{emptyHint}</p>
          )}
          {results.length > 0 && (
            <ul className="song-search__results">
              {results.map((s, idx) => (
                <li key={idx} className={s.ordered_today ? "song-search__item--ordered" : undefined}>
                  <button
                    type="button"
                    className="link-btn"
                    onClick={() => {
                      onPick(mode === "link" ? { ...s, link: text.trim() } : s);
                      setText("");
                      setResults([]);
                      setSearched(false);
                    }}
                  >
                    🎵 {s.artist ? `${s.artist} — ${s.title}` : s.title}
                    {s.ordered_today && <span className="song-search__ordered-badge"> · уже заказана сегодня</span>}
                  </button>
                  <div className="song-confirm-row">
                    <button
                      type="button"
                      className="song-confirm song-confirm--yes step-blink"
                      onClick={() => {
                        onPick(mode === "link" ? { ...s, link: text.trim() } : s);
                        setResults([]);
                        setSearched(false);
                        setSuggestOther(false);
                        if (screenshotInputRef.current) screenshotInputRef.current.value = "";
                      }}
                    >
                      ✅ Эта?
                    </button>
                    <button
                      type="button"
                      className="song-confirm song-confirm--no"
                      onClick={() => {
                        const next = results.filter((_, i) => i !== idx);
                        setResults(next);
                        if (next.length === 0) {
                          setSearched(false);
                          setSuggestOther(true);
                        }
                      }}
                    >
                      ✕ Не эта
                    </button>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </div>
  );
}

// Форма замены песни в уже существующем заказе (согласованная и утверждённая
// пользователем спецификация замены песни). Переиспользует SongSearch/
// AiSearch — тот же способ выбрать песню, что и в основной форме заказа
// выше, без дублирования логики поиска. Разрешённость самой замены (кнопка
// "Заменить песню" в OrderRow) решается на бэкенде по order.can_replace —
// эта форма ничего не решает сама, только собирает новые song_title/artist/
// service_id и вызывает POST /api/guest/order/<id>/replace.
function ReplaceForm({ order, token, services, busy, onSubmit, onCancel }) {
  const [songTitle, setSongTitle] = useState(order.song_title);
  const [artist, setArtist] = useState(order.artist || "");
  // ИЗМЕНЕНО (2026-09-23, запрос пользователя): категория раньше
  // подставлялась автоматически (см. историю — сначала первый тариф по id,
  // потом принудительно "KARAOKE — 35") — и оба раза гость не замечал сам
  // факт выбора категории, потому что его уже сделали за него. Явная
  // моргающая подсветка тоже не помогла (не отображалась на части
  // устройств — нативный <select> может игнорировать box-shadow/border).
  // Решение пользователя: категория выбирается КАЖДЫЙ раз заново — и при
  // новом заказе, и при замене песни (в отличие от входа через Google,
  // который остаётся один раз за сессию) — поэтому здесь всегда пустое
  // значение, никакого автоподставленного тарифа, даже если он уже был
  // указан у заменяемого заказа (order.service_id).
  const [serviceId, setServiceId] = useState("");
  const [error, setError] = useState(null);

  async function handleSubmit(event) {
    event.preventDefault();
    if (!songTitle.trim()) return;
    setError(null);
    try {
      await onSubmit(order.id, songTitle.trim(), artist.trim() || null, serviceId ? Number(serviceId) : null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    }
  }

  return (
    <div className="replace-form">
      <AiSearch
        token={token}
        onPick={(song) => {
          setSongTitle(song.title);
          setArtist(song.artist || "");
        }}
      />
      <form className="order-form" onSubmit={handleSubmit}>
        <input
          type="text"
          value={songTitle}
          onChange={(e) => setSongTitle(e.target.value)}
          placeholder="Название песни"
          maxLength={200}
          required
        />
        <input
          type="text"
          value={artist}
          onChange={(e) => setArtist(e.target.value)}
          placeholder="Исполнитель (обязательно)"
          maxLength={200}
          required
        />
        {services.length > 0 && (
          <ServiceSelect services={services} value={serviceId} onChange={setServiceId} />
        )}
        <div className="replace-form__buttons">
          <button type="submit" disabled={busy || !songTitle.trim() || !artist.trim()}>
            {busy ? "Сохраняем…" : "✅ Сохранить замену"}
          </button>
          <button type="button" className="link-btn" onClick={onCancel} disabled={busy}>
            Отмена
          </button>
        </div>
      </form>
      {error && <div className="banner banner--error">{error}</div>}
    </div>
  );
}

// Групповой стол (Role 3/4/5) — утверждённая пользователем спецификация,
// вариант А: полноценный шлюз (backend/services/table_group_service.py).
// Компонент сам опрашивает своё состояние (тот же паттерн, что и
// FavoritesPanel/ChatPanel выше — нет WebSocket у Guest App), а не получает
// его через props — это позволяет ему обновляться независимо от остальной
// страницы, но onGroupChanged даёт родителю знать, когда стоит немедленно
// перечитать /me (одобрили/выгнали/приняты права), не дожидаясь общего опроса.
function TableGroupPanel({ token, guestId, hasTable, status, onGroupChanged, tableNo = null }) {
  // ДОБАВЛЕНО (2026-10, запрос пользователя): блок сворачивается, как "Профиль".
  const [groupOpen, setGroupOpen] = useState(false);
  const [view, setView] = useState(null);
  // ДОБАВЛЕНО (2026-10, запрос пользователя): права админа стола переходят
  // следующему гостю автоматически — новому админу показываем уведомление.
  const [adminNotice, setAdminNotice] = useState(null);
  const prevAdminRef = useRef(null);
  useEffect(() => {
    if (!view || !Array.isArray(view.members)) return;
    const admin = view.members.find((m) => m.is_admin);
    if (!admin) return;
    const prev = prevAdminRef.current;
    if (admin.guest_id === guestId && prev && prev.id !== guestId) {
      const stillHere = view.members.some((m) => m.guest_id === prev.id);
      const who = prev.name || "Админ стола";
      setAdminNotice(
        stillHere
          ? `${who} передал(а) вам права — теперь вы админ стола.`
          : `${who} ушёл(а) — теперь вы админ стола.`,
      );
      try {
        if (navigator.vibrate) navigator.vibrate([200, 100, 200]);
      } catch {
        // вибрация недоступна — не страшно
      }
    }
    prevAdminRef.current = { id: admin.guest_id, name: admin.display_name || null };
  }, [view, guestId]);
  const [error, setError] = useState(null);
  const [busyKey, setBusyKey] = useState(null);
  const [requestingJoin, setRequestingJoin] = useState(false);
  // ДОБАВЛЕНО (2026-10, запрос пользователя): кнопка "❓" с пояснением
  // для админа стола — что значит быть админом.
  const [showAdminInfo, setShowAdminInfo] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const data = await api.getTableGroup(token);
      setView(data);
    } catch {
      // Временный сбой опроса группы — не критично, следующий тик подтянет.
    }
  }, [token]);

  // oxlint "set-state-in-effect" — тот же принятый случай опроса внешнего
  // состояния, что и у остальных польщиков в этом файле (нет WebSocket).
  useEffect(() => {
    if (!hasTable) return undefined;
    refresh();
    const id = setInterval(refresh, POLL_TABLE_GROUP_MS);
    return () => clearInterval(id);
  }, [hasTable, refresh]);

  async function runAction(key, action) {
    setBusyKey(key);
    setError(null);
    try {
      await action();
      await refresh();
      await onGroupChanged();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setBusyKey(null);
    }
  }

  // Встал из-за стола — гость остаётся без стола, поэтому состав стола
  // заново не запрашиваем, только обновляем его собственный статус.
  async function handleLeave() {
    setBusyKey("leave");
    setError(null);
    try {
      await api.leaveTableGroup(token);
      await onGroupChanged();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setBusyKey(null);
    }
  }

  async function handleRequestJoin() {
    setRequestingJoin(true);
    setError(null);
    try {
      await api.requestTableGroupJoin(token);
      await refresh();
      await onGroupChanged();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setRequestingJoin(false);
    }
  }

  // ДОБАВЛЕНО (запрос пользователя 2026-09-27, "закрыть стол по инициативе
  // гостя-админа") — только заявка (backend/services/table_close_service.py
  // ::request_close), реальное закрытие происходит после подтверждения KJ.
  // closeState живёт только в этом компоненте (нет отдельного эндпоинта
  // "статус моей заявки на закрытие" — не нужен: после approve группа
  // удаляется и status снаружи станет "not_joined", после reject админ
  // просто может нажать кнопку ещё раз), поэтому сбрасываем его всякий раз,
  // когда status реально меняется — иначе после approve/reject эта ветка
  // осталась бы навсегда висеть поверх новой (другой) ветки ниже.
  const [closeState, setCloseState] = useState(null); // null | "requesting" | "pending"

  useEffect(() => {
    setCloseState(null);
  }, [status]);

  async function handleRequestClose() {
    setCloseState("requesting");
    setError(null);
    try {
      await api.requestTableClose(token);
      setCloseState("pending");
    } catch (err) {
      setCloseState(null);
      setError(err instanceof ApiError ? err.message : String(err));
    }
  }

  if (!hasTable) return null;

  // status приходит из /api/guest/me (см. routes/guest.py::me) — источник
  // истины для "могу ли я сейчас заказывать", а не наличие/отсутствие
  // group.id здесь: группа продолжает существовать даже когда ЭТОТ гость
  // из неё вышел/кикнут — get_table_group у неё же и спрашиваем, поэтому
  // ветвим именно по status, а не по view.group.
  const isMember = status === "admin" || status === "member";
  // Кто принимает на стол (запрос пользователя 2026-10): имя того, кто сел первым, если он его задал.
  const tableAdmin = view && Array.isArray(view.members) ? view.members.find((m) => m.is_admin) : null;
  // Раскрыт сам, когда от гостя что-то требуется: заявка не подана/ждёт
  // ответа, или к нему (админу стола) кто-то просится за стол.
  const needsAttention =
    status === "pending" ||
    status === "not_joined" ||
    Boolean(view && view.is_admin && view.pending_requests && view.pending_requests.length > 0);
  const open = needsAttention || groupOpen;
  // Надпись под "Групповой стол" для админа (запрос пользователя 2026-10):
  // с именем из профиля, если оно задано; без имени — просто "Вы".
  const myMember = view && Array.isArray(view.members) ? view.members.find((m) => m.guest_id === guestId) : null;
  const adminLine = status === "admin"
    ? (myMember && myMember.display_name
      ? `Вы «${myMember.display_name}» — админ стола. Только вы разрешаете, кому сесть за стол. Чужие сесть не могут.`
      : "Вы — админ стола. Только вы разрешаете, кому сесть за стол. Чужие сесть не могут.")
    : null;
  const acceptsText = tableAdmin && tableAdmin.display_name
    ? `Принимает на стол ${tableAdmin.display_name}.`
    : "Тот, кто первым сел за стол, должен подтвердить.";

  return (
    <section className="panel table-group-panel">
      {adminNotice ? (
        <button type="button" className="turn-toast" onClick={() => setAdminNotice(null)}>
          👑 {adminNotice} Только вы решаете, кому сесть за стол.
          <span className="turn-toast__close">Нажмите, чтобы закрыть</span>
        </button>
      ) : null}
      <h2
        className="collapsible-header"
        role="button"
        tabIndex={0}
        aria-expanded={open}
        onClick={() => setGroupOpen((prev) => !prev)}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            setGroupOpen((prev) => !prev);
          }
        }}
      >
        👥 Групповой стол{tableNo != null ? ` · ${tableLabel(tableNo)}` : ""}
        <span className={`collapsible-caret${open ? " collapsible-caret--blink" : ""}`}>{open ? "▲" : "▼"}</span>
      </h2>
      {adminLine && <p className="table-admin-line">{adminLine}</p>} {tableNo != null && <GuestPrecheck token={token} />}
      {open && (
      <>
      {error && <div className="banner banner--error">{error}</div>}

      {status === "not_joined" && (
        <>
          <p className="empty-hint">
            Вы присоединяетесь к столу{tableNo != null ? ` ${tableLabel(tableNo)}` : ""}. {acceptsText}
          </p>
          <button type="button" onClick={handleRequestJoin} disabled={requestingJoin}>
            {requestingJoin ? "Отправляем…" : `🙋 Присоединиться к столу${tableNo != null ? ` ${tableLabel(tableNo)}` : ""}`}
          </button>
        </>
      )}

      {!view ? (
        <p className="empty-hint">Загрузка…</p>
      ) : (
        <>
          {view.members.length > 0 && (
            <ul className="order-list table-group-members">
              {view.members.map((m) => (
                <li key={m.guest_id} className="order-row table-group-member">
                  <span className="table-group-who">
                    {m.photo_data_url ? <img src={m.photo_data_url} alt="" className="table-group-who__photo" /> : null}
                    {m.is_admin ? "👑 " : "🙂 "}
                    {m.guest_id === guestId
                      ? `Вы${m.display_name ? ` · ${m.display_name}` : ""}`
                      : m.display_name || `Гость ${m.guest_id}`}
                    {m.is_admin && m.guest_id === guestId && (
                      <button
                        type="button"
                        className="service-picker__info table-admin-info"
                        title="Что значит админ стола"
                        onClick={() => setShowAdminInfo(true)}
                      >
                        ❓
                      </button>
                    )}
                  </span>
                  {m.is_admin && m.guest_id === guestId && (
                    <p
                      style={{
                        flexBasis: "100%",
                        width: "100%",
                        margin: "6px 0 0",
                        padding: "8px 10px",
                        borderRadius: 8,
                        borderLeft: "3px solid var(--accent)",
                        background: "rgba(255, 176, 32, 0.12)",
                        color: "var(--text)",
                        fontSize: 14,
                        fontWeight: 600,
                        lineHeight: 1.35,
                      }}
                    >
                      Вы — админ стола. Только вы разрешаете, кому сесть за стол. Чужие сесть не могут.
                    </p>
                  )}
                  {/* Та же карточка поверх экрана, что и у "❓" в категориях. */}
                  {m.is_admin && m.guest_id === guestId && showAdminInfo && (
                    <div className="service-card-overlay" onClick={() => setShowAdminInfo(false)}>
                      <div className="service-card" role="dialog" aria-modal="true" onClick={(e) => e.stopPropagation()}>
                        <h3 className="service-card__title">👑 Админ стола</h3>
                        <p className="service-card__desc">
                          Вы — админ стола. Только вы разрешаете, кому сесть за стол. Чужие сесть не могут.
                        </p>
                        <div className="service-card__buttons">
                          <button type="button" className="service-card__close" onClick={() => setShowAdminInfo(false)}>
                            Закрыть
                          </button>
                        </div>
                      </div>
                    </div>
                  )}
                  {view.is_admin && !m.is_admin && (
                    <div className="favorite-actions">
                      <button
                        type="button"
                        className="link-btn"
                        disabled={busyKey === `kick-${m.guest_id}`}
                        onClick={() => runAction(`kick-${m.guest_id}`, () => api.kickTableGroupMember(token, m.guest_id))}
                      >
                        🚪 Снять со стола
                      </button>
                      <button
                        type="button"
                        className="link-btn"
                        disabled={busyKey === `transfer-${m.guest_id}`}
                        onClick={() => runAction(`transfer-${m.guest_id}`, () => api.transferTableGroupAdmin(token, m.guest_id))}
                      >
                        👑 Передать права
                      </button>
                    </div>
                  )}
                </li>
              ))}
            </ul>
          )}

          {view.is_admin && view.pending_requests.length > 0 && (
            <div className="table-group-requests">
              <h3>Заявки на присоединение</h3>
              <ul className="order-list">
                {view.pending_requests.map((r) => (
                  <li key={r.id} className="order-row table-group-member">
                    <span className="table-group-who">
                      {r.photo_data_url ? <img src={r.photo_data_url} alt="" className="table-group-who__photo" /> : null}
                      🙋 {r.display_name || `Гость ${r.guest_id}`}
                    </span>
                    <div className="favorite-actions">
                      <button
                        type="button"
                        disabled={busyKey === `approve-${r.id}`}
                        onClick={() => runAction(`approve-${r.id}`, () => api.approveJoinRequest(token, r.id))}
                      >
                        ✅ Принять
                      </button>
                      <button
                        type="button"
                        className="link-btn"
                        disabled={busyKey === `reject-${r.id}`}
                        onClick={() => runAction(`reject-${r.id}`, () => api.rejectJoinRequest(token, r.id))}
                      >
                        ❌ Отклонить
                      </button>
                    </div>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {status === "pending" && (
            <button
              type="button"
              className="link-btn"
              disabled={busyKey === "leave"}
              onClick={handleLeave}
            >
              🚪 Передумал — встать из-за стола
            </button>
          )}

          {isMember && (
            <button
              type="button"
              className="link-btn"
              disabled={busyKey === "leave"}
              onClick={handleLeave}
            >
              🚪 Встать со стола
            </button>
          )}

          {status === "admin" && (
            <div className="table-group-close">
              {closeState === "pending" ? (
                <p className="empty-hint">⏳ Запрос на закрытие стола отправлен — ждите подтверждения KJ.</p>
              ) : (
                <button type="button" disabled={closeState === "requesting"} onClick={handleRequestClose}>
                  {closeState === "requesting" ? "Отправляем…" : "🔒 Закрыть стол"}
                </button>
              )}
            </div>
          )}
        </>
      )}
      </>
      )}
    </section>
  );
}

function ChatPanel({ token }) {
  const [messages, setMessages] = useState([]);
  const [draft, setDraft] = useState("");
  const [pendingImage, setPendingImage] = useState(null);
  const [imageBusy, setImageBusy] = useState(false);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState(null);
  const listEndRef = useRef(null);
  // ДОБАВЛЕНО (2026-10-04, запрос пользователя "нигде нет кнопки удаления
  // сообщений и очистки чата") — то же самое, что и в KJ Panel.
  const [deletingId, setDeletingId] = useState(null);
  const [clearing, setClearing] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const data = await api.listChat(token);
      setMessages(data);
    } catch {
      // Молча пропускаем один неудачный опрос чата — не хотим перекрывать
      // основной интерфейс заказа баннером ошибки из-за временного сбоя сети.
    }
  }, [token]);

  // oxlint предупреждает "set-state-in-effect" здесь — это ожидаемо и
  // осознанно: это опрос чата (нет WebSocket для Guest App, см. комментарий
  // у POLL_*_MS выше в этом файле), а не побочный эффект от рендера,
  // который надо было бы вычислить иначе.
  useEffect(() => {
    refresh();
    const id = setInterval(refresh, POLL_CHAT_MS);
    return () => clearInterval(id);
  }, [refresh]);

  useEffect(() => {
    listEndRef.current?.scrollIntoView({ block: "nearest" });
  }, [messages.length]);

  async function handleAttachImage(file) {
    setImageBusy(true);
    setError(null);
    try {
      const resized = await new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onerror = () => reject(reader.error || new Error("Не удалось прочитать файл"));
        reader.onload = () => {
          const img = new Image();
          img.onerror = () => reject(new Error("Не удалось прочитать изображение"));
          img.onload = () => {
            const maxSide = 800;
            const scale = Math.min(1, maxSide / Math.max(img.width, img.height));
            const canvas = document.createElement("canvas");
            canvas.width = Math.round(img.width * scale);
            canvas.height = Math.round(img.height * scale);
            canvas.getContext("2d").drawImage(img, 0, 0, canvas.width, canvas.height);
            resolve(canvas.toDataURL("image/jpeg", 0.82));
          };
          img.src = reader.result;
        };
        reader.readAsDataURL(file);
      });
      setPendingImage(resized);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setImageBusy(false);
    }
  }

  async function handleSend(event) {
    event.preventDefault();
    const text = draft.trim();
    if (!text && !pendingImage) return;
    setSending(true);
    setError(null);
    try {
      await api.sendChatMessage(token, text, pendingImage || undefined);
      setDraft("");
      setPendingImage(null);
      await refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setSending(false);
    }
  }

  async function handleDeleteMessage(messageId) {
    setDeletingId(messageId);
    setError(null);
    try {
      await api.deleteChatMessage(token, messageId);
      setMessages((prev) => prev.filter((m) => m.id !== messageId));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setDeletingId(null);
    }
  }

  async function handleClearChat() {
    if (!window.confirm("Удалить всю переписку с ведущим? Это действие нельзя отменить.")) return;
    setClearing(true);
    setError(null);
    try {
      await api.clearChat(token);
      setMessages([]);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setClearing(false);
    }
  }

  return (
    <section className="panel chat-panel">
      <div className="chat-panel__header">
        <h2>💬 Чат с ведущим</h2>
        {messages.length > 0 && (
          <button type="button" className="link-btn link-btn--danger" disabled={clearing} onClick={handleClearChat}>
            {clearing ? "Очищаем…" : "🗑 Очистить чат"}
          </button>
        )}
      </div>
      <ul className="chat-list">
        {messages.length === 0 && <li className="empty-hint">Сообщений пока нет.</li>}
        {messages.map((m) => (
          <li key={m.id} className={`chat-message ${m.from_guest ? "chat-message--mine" : "chat-message--kj"}`}>
            <span className="chat-message__author">{m.from_guest ? "Вы" : "KJ"}</span>
            {m.image_data_url && (
              <img src={m.image_data_url} alt="Скриншот" className="chat-message__image" />
            )}
            {m.message_text && <span className="chat-message__text">{m.message_text}</span>}
            <button
              type="button"
              className="chat-message__delete"
              disabled={deletingId === m.id}
              onClick={() => handleDeleteMessage(m.id)}
            >
              {deletingId === m.id ? "Удаляем…" : "✕"}
            </button>
          </li>
        ))}
        <li ref={listEndRef} />
      </ul>
      {error && <div className="banner banner--error">{error}</div>}
      {pendingImage && (
        <div className="chat-attachment-preview">
          <img src={pendingImage} alt="" className="chat-attachment-preview__image" />
          <button type="button" className="btn-link" onClick={() => setPendingImage(null)}>
            ✕ Убрать
          </button>
        </div>
      )}
      <form className="chat-form" onSubmit={handleSend}>
        <input
          type="text"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder="Написать ведущему…"
          maxLength={500}
        />
        <label className="chat-attach-btn" aria-disabled={imageBusy}>
          📎
          <input
            type="file"
            accept="image/*"
            disabled={imageBusy}
            onChange={(e) => {
              const file = e.target.files[0];
              e.target.value = "";
              if (file) handleAttachImage(file);
            }}
          />
        </label>
        <button type="submit" disabled={sending || imageBusy || (!draft.trim() && !pendingImage)}>
          Отправить
        </button>
      </form>
    </section>
  );
}

// Отдельный пункт "Заказ через скриншот" (запрос пользователя 2026-10-01):
// раньше кнопка "Скриншот" в поиске песни сама пыталась распознать песню
// по картинке через ИИ — пользователь решил, что это больше не нужно (ИИ
// не всегда справляется), и попросил вместо этого отдельное, понятное
// место в Сообщениях специально для отправки скриншота ведущему — не
// внутри общего чата с ведущим (ChatPanel) и не внутри "Заказ новой
// песни" (это про другое — заказ создания ещё не существующей песни).
// Технически сообщение всё равно uходит в ту же переписку ChatMessage,
// что и обычный чат — чтобы у ведущего было одно место, где смотреть все
// сообщения от гостя, см. KjChatPanel в kj-panel.
function ScreenshotOrderPanel({ token, services, autoFocus, onFocused }) {
  const [pendingImage, setPendingImage] = useState(null);
  const [comment, setComment] = useState("");
  const [serviceId, setServiceId] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [sent, setSent] = useState(false);
  const sectionRef = useRef(null);

  useEffect(() => {
    if (autoFocus && sectionRef.current) {
      sectionRef.current.scrollIntoView({ behavior: "smooth", block: "start" });
      onFocused?.();
    }
  }, [autoFocus, onFocused]);

  async function handleFile(file) {
    setBusy(true);
    setError(null);
    setSent(false);
    // ИЗМЕНЕНО (2026-10, запрос пользователя: "читать скриншот не надо —
    // картинка просто уходит ведущему"): картинку только уменьшаем, чтобы
    // быстрее ушла. Если телефон отдал формат, который браузер не умеет
    // уменьшить, отправляем файл как есть — без ошибки "не удалось прочитать".
    try {
      const original = await new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onerror = () => reject(new Error("Не удалось открыть файл — попробуйте другой скриншот"));
        reader.onload = () => resolve(reader.result);
        reader.readAsDataURL(file);
      });
      const shrink = (source) => {
        const maxSide = 1200;
        const scale = Math.min(1, maxSide / Math.max(source.width, source.height));
        const canvas = document.createElement("canvas");
        canvas.width = Math.max(1, Math.round(source.width * scale));
        canvas.height = Math.max(1, Math.round(source.height * scale));
        canvas.getContext("2d").drawImage(source, 0, 0, canvas.width, canvas.height);
        return canvas.toDataURL("image/jpeg", 0.85);
      };
      let result = null;
      try {
        result = await new Promise((resolve, reject) => {
          const img = new Image();
          img.onerror = () => reject(new Error("decode"));
          img.onload = () => resolve(shrink(img));
          img.src = original;
        });
      } catch {
        try {
          if (window.createImageBitmap) result = shrink(await window.createImageBitmap(file));
        } catch {
          result = null;
        }
      }
      if (!result) {
        if (typeof original === "string" && original.startsWith("data:image/") && original.length <= 1900000) {
          result = original;
        } else {
          throw new Error("Это фото слишком большое — сделайте обычный скриншот экрана и выберите его.");
        }
      }
      setPendingImage(result);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  async function handleSend() {
    if (!pendingImage || !serviceId) return;
    setBusy(true);
    setError(null);
    try {
      await api.sendChatMessage(token, comment.trim(), pendingImage, Number(serviceId));
      setPendingImage(null);
      setComment("");
      setServiceId("");
      setSent(true);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="panel" ref={sectionRef}>
      <h2>📷 Заказ через скриншот</h2>
      <p className="empty-hint">
        Пришлите скриншот нужной песни (например, из Shazam, Spotify или ВКонтакте) — ведущий посмотрит и оформит заказ сам.
      </p>
      {error && <div className="banner banner--error">{error}</div>}
      {sent && !pendingImage && <p className="empty-hint">Скриншот отправлен ведущему ✅</p>}
      {pendingImage && (
        <div className="chat-attachment-preview">
          <img src={pendingImage} alt="" className="chat-attachment-preview__image" />
          <button type="button" className="btn-link" onClick={() => setPendingImage(null)}>
            ✕ Убрать
          </button>
        </div>
      )}
      <label className={`profile-photo-upload screenshot-pick${!busy && !pendingImage ? " screenshot-pick--blink" : ""}`}>
        {busy ? "Загружаем…" : pendingImage ? "Заменить скриншот / фото" : "📷 Выберите скриншот / Фото"}
        <input
          type="file"
          accept="image/*"
          disabled={busy}
          onChange={(e) => {
            const file = e.target.files[0];
            e.target.value = "";
            if (file) handleFile(file);
          }}
        />
      </label>
      {services.length > 0 && (
        <ServiceSelect services={services} value={serviceId} onChange={setServiceId} />
      )}
      <input
        type="text"
        value={comment}
        onChange={(e) => setComment(e.target.value)}
        placeholder="Комментарий (необязательно)"
        maxLength={300}
      />
      <button type="button" disabled={busy || !pendingImage || !serviceId} onClick={handleSend}>
        Отправить ведущему
      </button>
    </section>
  );
}

// Имя, которое гость сам себе задаёт (запрос пользователя 2026-09,
// "самопереименование гостя") — видно ведущему в KJ Panel (список гостей и
// карточка гостя), вместо голого номера guest_id. Доступно только ПОСЛЕ
// входа через Google (см. ActivationPanel/handleActivated ниже) — до этого
// нет постоянного профиля, к которому можно привязать имя (см.
// backend/routes/guest.py::set_display_name, GOOGLE_LINK_REQUIRED). Можно
// менять сколько угодно раз — это переименование, а не разовая настройка.
const MAX_DISPLAY_NAME_LEN = 40;

function ProfileNamePanel({ token, meInfo, onNameChanged }) {
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(meInfo.display_name || "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  // Фото гостя (запрос пользователя 2026-10-01, "клиент сам загружает своё
  // фото, но это не обязательно, там же где Изменить имя") — отдельные
  // busy/error от редактирования имени выше, чтобы крутилка на одной
  // кнопке не блокировала другую.
  const [photoBusy, setPhotoBusy] = useState(false);
  const [photoError, setPhotoError] = useState(null);
  // ДОБАВЛЕНО (2026-10, запрос пользователя: "раздел Имя Фото сделаем
  // раскрывающимся, по умолчанию свёрнут") — тот же приём, что и у
  // "Избранное"/"Финансы" (.collapsible-header).
  const [profileOpen, setProfileOpen] = useState(false);
  // "Удалить мои данные" (запрос пользователя 2026-10-04, право на
  // удаление персональных данных) — сразу и полностью, без отдельного
  // экрана, с одним окном подтверждения (window.confirm).
  const [deleteBusy, setDeleteBusy] = useState(false);
  const [deleteError, setDeleteError] = useState(null);

  // Если имя обновилось извне (например, опрос /me после действия в другой
  // вкладке) — подхватываем новое значение, но только пока сами не
  // редактируем, чтобы не затереть то, что гость уже печатает.
  useEffect(() => {
    if (!editing) setName(meInfo.display_name || "");
  }, [meInfo.display_name, editing]);

  async function handleSave(event) {
    event.preventDefault();
    const trimmed = name.trim();
    if (!trimmed) {
      setError("Имя не может быть пустым");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await api.setDisplayName(token, trimmed);
      setEditing(false);
      await onNameChanged();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  // Уменьшаем фото прямо в браузере перед отправкой — так же, как и в KJ
  // Panel (routes/guest.py::set_my_photo ограничивает длину строки на
  // сервере, но без сжатия на телефоне фото с камеры легко превысило бы
  // этот предел).
  async function handleUploadPhoto(file) {
    setPhotoBusy(true);
    setPhotoError(null);
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
      await api.setMyPhoto(token, resized);
      await onNameChanged();
    } catch (err) {
      setPhotoError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setPhotoBusy(false);
    }
  }

  async function handleRemovePhoto() {
    setPhotoBusy(true);
    setPhotoError(null);
    try {
      await api.setMyPhoto(token, null);
      await onNameChanged();
    } catch (err) {
      setPhotoError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setPhotoBusy(false);
    }
  }

  async function handleDeleteMyData() {
    if (!window.confirm("Удалить имя, фото и привязку к Google-аккаунту? Это действие нельзя отменить.")) {
      return;
    }
    setDeleteBusy(true);
    setDeleteError(null);
    try {
      await api.deleteMyProfile(token);
      await onNameChanged();
    } catch (err) {
      setDeleteError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setDeleteBusy(false);
    }
  }

  if (!editing) {
    return (
      <section className="panel profile-panel">
        <h2
          className="collapsible-header"
          role="button"
          tabIndex={0}
          aria-expanded={profileOpen}
          onClick={() => setProfileOpen((prev) => !prev)}
          onKeyDown={(e) => {
            if (e.key === "Enter" || e.key === " ") {
              e.preventDefault();
              setProfileOpen((prev) => !prev);
            }
          }}
        >
          👤 Профиль{meInfo.display_name ? ` · ${meInfo.display_name}` : ""}
          <span className={`collapsible-caret${profileOpen ? " collapsible-caret--blink" : ""}`}>{profileOpen ? "▲" : "▼"}</span>
        </h2>
        {profileOpen && (
        <>
        <p className="empty-hint">
          {meInfo.display_name
            ? <>Ведущий видит вас как «{meInfo.display_name}».</>
            : "Вы ещё не задали имя — ведущий видит только номер гостя."}
        </p>
        {photoError && <div className="banner banner--error">{photoError}</div>}

        {/* ИЗМЕНЕНО (запрос пользователя 2026-10-01, "Изменить имя и
        Загрузить фото смотрятся некрасиво, выровняй по одной линии") —
        раньше кнопка "Изменить имя" была отдельным блоком перед
        .profile-photo-row, из-за чего вставала на свою строку; теперь она
        просто первый элемент внутри той же flex-строки. */}
        <div className="profile-photo-row">
          <button type="button" className="btn-link" onClick={() => setEditing(true)}>
            {meInfo.display_name ? "Изменить имя" : "Задать имя"}
          </button>

          {meInfo.photo_data_url ? (
            <img src={meInfo.photo_data_url} alt="" className="profile-photo-row__photo" />
          ) : (
            <span className="profile-photo-row__photo profile-photo-row__photo--placeholder">👤</span>
          )}
          <label className="btn-link profile-photo-upload">
            {photoBusy ? "Загружаем…" : meInfo.photo_data_url ? "Заменить фото" : "Загрузить фото (необязательно)"}
            <input
              type="file"
              accept="image/*"
              disabled={photoBusy}
              onChange={(e) => {
                const file = e.target.files[0];
                e.target.value = "";
                if (file) handleUploadPhoto(file);
              }}
            />
          </label>
          {meInfo.photo_data_url && (
            <button type="button" className="btn-link" disabled={photoBusy} onClick={handleRemovePhoto}>
              ✕ Убрать фото
            </button>
          )}
        </div>

        {/* Финансы VIP-гостя — внутри профиля (запрос пользователя 2026-10). */}
        {meInfo.is_vip && <VipHistoryPanel token={token} embedded />}
        <VipPanel token={token} meInfo={meInfo} embedded />

        {/* ДОБАВЛЕНО (запрос пользователя 2026-10-04) — ссылки на
        политику конфиденциальности/условия использования и кнопка
        "Удалить мои данные" (право на удаление персональных данных),
        рядом с остальными действиями над профилем. */}
        <div className="profile-legal-row">
          <a href="/privacy.html" target="_blank" rel="noopener noreferrer" className="btn-link">
            Политика конфиденциальности
          </a>
          <a href="/terms.html" target="_blank" rel="noopener noreferrer" className="btn-link">
            Условия использования
          </a>
        </div>
        {meInfo.has_permanent_profile && (
          <div className="profile-legal-row">
            {deleteError && <div className="banner banner--error">{deleteError}</div>}
            <button type="button" className="btn-link" disabled={deleteBusy} onClick={handleDeleteMyData}>
              {deleteBusy ? "Удаляем…" : "🗑 Удалить мои данные"}
            </button>
          </div>
        )}
        </>
        )}
      </section>
    );
  }

  return (
    <section className="panel profile-panel">
      <h2>👤 Ваше имя</h2>
      {error && <div className="banner banner--error">{error}</div>}
      <form className="order-form" onSubmit={handleSave}>
        <input
          type="text"
          value={name}
          onChange={(e) => setName(e.target.value)}
          maxLength={MAX_DISPLAY_NAME_LEN}
          placeholder="Как вас называть?"
          autoFocus
        />
        <button type="submit" disabled={busy || !name.trim()}>
          {busy ? "Сохраняем…" : "Сохранить"}
        </button>
        <button
          type="button"
          className="link-btn"
          onClick={() => { setEditing(false); setError(null); }}
          disabled={busy}
        >
          Отмена
        </button>
      </form>
    </section>
  );
}

// ТЗ п.45 (финальная единая модель входа) — единственный способ стать
// Role 4: гость вводит номер своего стола и подтверждает личность через
// Google одним действием (см. api.linkGoogle). До этого он мог только
// смотреть очередь и заполнить форму заказа (Role 5) — именно попытка
// нажать "Заказать" открывает этот экран (см. App::handleSubmitOrder), а
// не отдельная навигация.
//
// 2026-09: настоящая кнопка Google Identity Services (см. index.html —
// подключён https://accounts.google.com/gsi/client) вместо прежней
// имитации (getMockGoogleCredential убран). Кнопка рендерится Google'ом
// в отдельный div и не является частью обычной формы — по нажатию
// открывается всплывающее окно Google, а её результат (id_token) приходит
// в колбэк асинхронно, отдельно от React-состояния submit. Номер стола
// при этом должен быть уже введён — колбэк проверяет актуальное значение
// через ref (см. stateRef ниже), чтобы не захватить устаревшее замыкание
// от момента регистрации колбэка (она происходит один раз при монтировании).
function ActivationPanel({ token, onActivated, onCancel }) {
  const [tableNo, setTableNo] = useState("");
  // Доп. столы клуба ("7/1 (Vip)", 2026-10-13) — гость выбирает их кнопкой.
  const [extraTables, setExtraTables] = useState([]);
  const [selectedExtra, setSelectedExtra] = useState(null);

  useEffect(() => {
    api.listExtraTables(token).then((items) => setExtraTables(items || [])).catch(() => setExtraTables([]));
  }, [token]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const panelRef = useRef(null);
  const googleButtonRef = useRef(null);
  const [skipHint, setSkipHint] = useState(false);

  // Живой тест показал: гость нажимал "Заказать", этот экран появлялся
  // ниже видимой части страницы, гость его не замечал и решал, что кнопка
  // вообще не сработала (не видел ни ошибки, ни сообщения об отправке).
  // Раз без этого экрана заказ не может уйти дальше, при появлении он сам
  // прокручивается в поле зрения и ненадолго подсвечивается рамкой — см.
  // анимацию .activation-panel в App.css.
  useEffect(() => {
    panelRef.current?.scrollIntoView({ behavior: "smooth", block: "center" });
  }, []);

  const parsedTableNo = selectedExtra != null ? selectedExtra : Number(tableNo);
  const tableNoValid =
    selectedExtra != null || (tableNo.trim() !== "" && Number.isInteger(parsedTableNo) && parsedTableNo > 0);

  const stateRef = useRef({ tableNoValid, parsedTableNo, busy });
  useEffect(() => {
    stateRef.current = { tableNoValid, parsedTableNo, busy };
  });

  async function handleGoogleCredential(response) {
    const { tableNoValid: valid, parsedTableNo: n, busy: isBusy } = stateRef.current;
    if (isBusy) return;
    if (!valid) {
      setError("Сначала укажите номер своего стола, потом нажмите кнопку Google ещё раз");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const result = await api.linkGoogle(token, n, { id_token: response.credential });
      await onActivated(result);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  // Вход без Google (2026-10): только стол, без постоянного профиля.
  async function handleNoLogin() {
    if (busy) return;
    if (!tableNoValid) {
      setError("Сначала укажите номер своего стола");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const result = await api.chooseTableNoLogin(token, parsedTableNo);
      await onActivated(result);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  // ИСПРАВЛЕНО (жалоба пользователя 2026-09-28 "нету у меня входа"): скрипт
  // https://accounts.google.com/gsi/client подключён в index.html как
  // async defer — он грузится параллельно с самим React-приложением, и
  // нет никакой гарантии, что window.google.accounts.id уже существует
  // именно в момент, когда монтируется этот экран (медленная сеть, первый
  // заход без кэша браузера на accounts.google.com — на практике вполне
  // обычная ситуация, не редкий крайний случай). Раньше здесь была ОДНА
  // проверка сразу при монтировании: если скрипт Google в этот момент ещё
  // не успел подгрузиться — гость навсегда получал ошибку "не удалось
  // загрузить вход через Google" и кнопка так и не появлялась, даже если
  // скрипт долетал долей секунды позже. Теперь вместо одной проверки —
  // опрос каждые 150мс в течение 10 секунд, чего с большим запасом хватает
  // на реальную загрузку внешнего скрипта; ошибка показывается только если
  // за 10 секунд скрипт так и не появился (это уже настоящий сбой сети, а
  // не гонка при рендере).
  useEffect(() => {
    let cancelled = false;
    let attempts = 0;
    const maxAttempts = 67; // ~10 секунд при шаге 150мс

    function tryInit() {
      if (cancelled) return;
      if (window.google?.accounts?.id && googleButtonRef.current) {
        window.google.accounts.id.initialize({
          client_id: GOOGLE_CLIENT_ID,
          callback: handleGoogleCredential,
        });
        window.google.accounts.id.renderButton(googleButtonRef.current, {
          theme: "outline", size: "large", text: "signin_with", locale: "ru", width: 280,
        });
        return;
      }
      attempts += 1;
      if (attempts >= maxAttempts) {
        setError("Не удалось загрузить вход через Google — проверьте подключение к интернету и обновите страницу");
        return;
      }
      setTimeout(tryInit, 150);
    }

    tryInit();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <section ref={panelRef} className="panel activation-panel">
      <h2>Выберите стол и войдите через Google</h2>
      <p className="empty-hint">
        Укажите номер своего стола и войдите через Google одним действием — это нужно один раз,
        дальше ваш стол, история заказов и избранное сохранятся.
      </p>
      <p className="empty-hint">
        Или нажмите «Заказать без входа» — тогда доступны только заказы песен, без избранного, кэшбэка и VIP.
      </p>
      {error && <div className="banner banner--error">{error}</div>}
      <div className="order-form">
        <input
          type="number"
          min="1"
          className={!tableNoValid ? "step-blink" : "step-dim"}
          value={tableNo}
          onChange={(e) => {
            setTableNo(e.target.value);
            setSelectedExtra(null);
          }}
          placeholder="Номер стола"
          required={selectedExtra == null}
        />
        {extraTables.length > 0 && (
          <details className="extra-table-picker-wrap">
            <summary className="extra-table-picker__summary">Доп. столы</summary>
            <div className="extra-table-picker">
            {extraTables.map((t) => (
              <button
                key={t.table_no}
                type="button"
                className={`extra-table-picker__btn${selectedExtra === t.table_no ? " extra-table-picker__btn--active" : ""}`}
                onClick={() => {
                  setSelectedExtra(t.table_no);
                  setTableNo("");
                }}
              >
                {t.title}
              </button>
            ))}
            </div>
          </details>
        )}
        <div className="activation-zone">
          <button type="button" className={`activation-nologin ${tableNoValid ? "step-blink-alt" : "step-dim"}`} onClick={handleNoLogin} disabled={busy || !tableNoValid}>
            Заказать без входа
          </button>
          {/* Шаг 2: моргает, когда стол уже выбран (первый шаг — номер стола). */}
          <div ref={googleButtonRef} className={`activation-google${tableNoValid && !busy ? " step-blink" : ""}`} />
          {!tableNoValid && <div className="activation-zone__guard" onClick={() => setSkipHint(true)} />}
        </div>
        {skipHint && (
          <>
            <div style={{ position: "fixed", top: 0, left: 0, right: 0, bottom: 0, background: "rgba(0,0,0,0.6)", zIndex: 1000 }} />
            <section role="alert" style={{ position: "fixed", top: "50%", left: "50%", transform: "translate(-50%, -50%)", zIndex: 1001, width: "calc(100% - 32px)", maxWidth: 460, boxSizing: "border-box", padding: "28px 22px", borderRadius: 16, textAlign: "center", fontSize: 26, fontWeight: 800, lineHeight: 1.3, boxShadow: "0 12px 40px rgba(0,0,0,0.5)", margin: 0, background: "#facc15", color: "#422006" }}>
              <p style={{ margin: 0 }}>⚠️ Сначала выберите номер стола</p>
              <button type="button" style={{ display: "block", width: "100%", padding: "18px", borderRadius: 12, border: "none", fontWeight: 800, fontSize: 22, marginTop: 14, color: "#fff", background: "#422006", cursor: "pointer" }} onClick={() => setSkipHint(false)}>ОК</button>
            </section>
          </>
        )}
        {busy && <p className="empty-hint">Входим…</p>}
        <button type="button" className="link-btn" onClick={onCancel} disabled={busy}>
          Отмена
        </button>
      </div>
    </section>
  );
}

// Чек закрытия стола (запрос пользователя 2026-09-27) — после того как KJ
// подтвердил закрытие группового стола (см. docstring
// services/table_close_service.py::approve_request), гость какое-то время
// видит чек через обычный поллинг /api/guest/me — у Guest App нет
// WebSocket-подключения (см. докстринг backend/sockets.py::
// emit_chat_message), поэтому доставка только так, пока не истекло окно
// RECEIPT_POLL_WINDOW_SECONDS на бэкенде. table_close_receipt в /me — это
// весь TableCloseRequest.to_dict() (не только сами цифры), сами цифры
// чека лежат в receipt.receipt (см. pending_receipt_for_guest). Дедупликация
// "показать один раз", как и предполагает докстринг на бэкенде, — здесь,
// по id заявки: закрыли баннер — тот же чек больше не всплывёт, даже если
// следующий опрос ещё вернёт его (окно не истекает мгновенно).
function TableCloseReceiptBanner({ closeRequest, onDismiss }) {
  if (!closeRequest || !closeRequest.receipt) return null;
  const receipt = closeRequest.receipt;

  return (
    <section className="panel table-close-receipt">
      <h2>🧾 Чек стола {tableLabel(receipt.table_no)}</h2>
      {/* ДОБАВЛЕНО (запрос пользователя 2026-09-28, "VIP и обычный гость за
      одним столом"): разбивка по гостям вместо одной общей суммы — VIP уже
      списан с баланса за свои песни при каждом "Готово" (см. docstring
      table_close_service.py::_build_receipt), поэтому у стола со смешанной
      компанией нужно явно видеть, чья доля уже оплачена, а чья ещё нет,
      иначе за столом могли попросить оплатить чек ещё раз целиком. */}
      {receipt.guests && receipt.guests.length > 0 && (
        <ul className="order-list">
          {receipt.guests.map((g) => (
            <li key={g.guest_id} className="order-row">
              <div className="order-row__song">
                {g.display_name || `Гость #${g.guest_id}`}
                {g.guest_type === "vip" ? " · VIP" : ""}
              </div>
              <div className="order-row__artist">
                {g.count} шт. · {g.sum.toFixed(2)}
                {g.paid ? " · оплачено с баланса" : ""}
              </div>
            </li>
          ))}
        </ul>
      )}
      {receipt.categories.length > 0 && (
        <ul className="order-list">
          {receipt.categories.map((c) => (
            <li key={c.category} className="order-row">
              <div className="order-row__song">{c.category}</div>
              <div className="order-row__artist">
                {c.count} шт. × {c.price.toFixed(2)} = {c.sum.toFixed(2)}
              </div>
            </li>
          ))}
        </ul>
      )}
      <p className="empty-hint">
        Песен: {receipt.song_count} · Общая сумма чека: {receipt.total.toFixed(2)}
        {" · К оплате: "}
        {receipt.payable_total.toFixed(2)}
      </p>
      <button type="button" className="link-btn" onClick={onDismiss}>
        Закрыть
      </button>
    </section>
  );
}

// ДОБАВЛЕНО (запрос пользователя 2026-10-01, "как зайти без QR-кода каждый
// раз") — подсказка "сохранить сайт на экран", чтобы гость мог вернуться
// позже одним нажатием значка на телефоне, а не просить снова показать
// QR-код. Специально НЕ используем настоящую кнопку "Установить"
// (beforeinstallprompt/manifest c фиксированным start_url) — один и тот
// же файл манифеста обслуживает все клубы сразу, и жёстко прописанный
// адрес в нём перепутает клуб при автоустановке. Обычное "На экран
// Домой" браузера сохраняет именно текущую ссылку гостя (с его клубом),
// поэтому это просто подсказка из двух шагов, без автоматизации.
const FIRST_ORDER_NOTICE_KEY = "first_order_notice_seen";
function isFirstOrderNoticeSeen() {
  try {
    return localStorage.getItem(FIRST_ORDER_NOTICE_KEY) === "1";
  } catch {
    return false;
  }
}
function markFirstOrderNoticeSeen() {
  try {
    localStorage.setItem(FIRST_ORDER_NOTICE_KEY, "1");
  } catch {
    // localStorage недоступен — плашка может показаться ещё раз, это не критично
  }
}

function AddToHomeScreenHint() {
  const [dismissed, setDismissed] = useState(() => {
    try {
      return localStorage.getItem("add_to_home_hint_dismissed") === "1";
    } catch {
      return false;
    }
  });

  const ua = typeof navigator !== "undefined" ? navigator.userAgent : "";
  const isIOS = /iPhone|iPad|iPod/i.test(ua);
  const isMobile = isIOS || /Android/i.test(ua);
  const isStandalone =
    (typeof window !== "undefined" && window.matchMedia?.("(display-mode: standalone)").matches) ||
    window.navigator.standalone === true;

  if (dismissed || isStandalone || !isMobile) return null;

  function dismiss() {
    try {
      localStorage.setItem("add_to_home_hint_dismissed", "1");
    } catch {
      // localStorage недоступен — просто скрываем на этот показ
    }
    setDismissed(true);
  }

  return (
    <section className="panel add-to-home-hint">
      <p>
        📲 Сохраните сайт на экран телефона — зайдёте в следующий раз одним
        нажатием, без QR-кода.{" "}
        {isIOS
          ? 'Нажмите значок "Поделиться" внизу браузера, затем "На экран Домой".'
          : 'Откройте меню браузера (⋮) и выберите "Добавить на главный экран".'}
      </p>
      <button type="button" className="btn-link" onClick={dismiss}>
        Понятно, скрыть
      </button>
    </section>
  );
}

export default function App() {
  const { clubId } = useMemo(() => parseLinkParams(), []);

  const [session, setSession] = useState(null);
  const [meInfo, setMeInfo] = useState(null);
  const [closedSignal, setClosedSignal] = useState(0);
  // Дедупликация показа чека закрытия стола "один раз" по id заявки — см.
  // докстринг TableCloseReceiptBanner выше.
  // ИЗМЕНЕНО (2026-10, запрос пользователя): закрытый чек запоминается на
  // телефоне гостя и больше не появляется — даже после обновления страницы.
  const [dismissedCloseRequestIds, setDismissedCloseRequestIds] = useState(() => {
    try {
      const saved = JSON.parse(window.localStorage.getItem("kp_dismissed_receipts") || "[]");
      return new Set(Array.isArray(saved) ? saved : []);
    } catch {
      return new Set();
    }
  });
  useEffect(() => {
    try {
      window.localStorage.setItem(
        "kp_dismissed_receipts",
        JSON.stringify([...dismissedCloseRequestIds].slice(-50)),
      );
    } catch {
      // память телефона недоступна — чек просто скроется до обновления страницы
    }
  }, [dismissedCloseRequestIds]);
  // !clubId — не результат асинхронной операции, а сразу известное по URL
  // состояние, поэтому это часть рендера, а не setState в эффекте.
  const linkInvalid = !clubId;
  const [initError, setInitError] = useState(null);
  // "home" | "messages" — новый отдельный экран "Сообщения" (запрос
  // пользователя 2026-10-01): собирает в одном месте пополнение VIP-баланса,
  // чат с ведущим и ещё две кнопки-заглушки под будущие функции, вместо
  // того чтобы всё это было разбросано по главному экрану.
  const [view, setView] = useState("home");
  // ДОБАВЛЕНО (2026-10-13, запрос пользователя "сообщения легко пропустить"):
  // новое сообщение от ведущего всплывает окном поверх любого экрана.
  const [chatPopup, setChatPopup] = useState(null);
  const chatSeenKey = session ? `kp_chat_seen_${session.club_id}_${session.guest_id}` : null;

  function markChatSeen(id) {
    if (!chatSeenKey || id == null) return;
    try {
      const prev = Number(window.localStorage.getItem(chatSeenKey) || 0);
      if (id > prev) window.localStorage.setItem(chatSeenKey, String(id));
    } catch {
      // localStorage недоступен — просто не запоминаем
    }
  }

  useEffect(() => {
    if (!session?.token || !chatSeenKey) return undefined;
    let cancelled = false;
    async function check() {
      try {
        const list = await api.listChat(session.token);
        if (cancelled) return;
        const fromKj = (list || []).filter((m) => !m.from_guest);
        if (!fromKj.length) return;
        const latest = fromKj.reduce((a, b) => (b.id > a.id ? b : a));
        let seen = null;
        try {
          seen = window.localStorage.getItem(chatSeenKey);
        } catch {
          seen = String(latest.id);
        }
        if (seen == null) {
          // Первый запуск — старые сообщения не всплывают.
          markChatSeen(latest.id);
          return;
        }
        if (view === "messages") {
          markChatSeen(latest.id);
          setChatPopup(null);
          return;
        }
        // Автоматическое "Вы следующий" / "Приготовьтесь" уже видно зелёной плашкой очереди — окно не всплывает.
        const autoQueue = /^🎤 (Вы следующий|Приготовьтесь)/.test(latest.message_text || "");
        if (latest.id > Number(seen)) {
          if (autoQueue) markChatSeen(latest.id);
          else setChatPopup(latest);
        }
      } catch {
        // молча — следующий опрос попробует снова
      }
    }
    check();
    const id = setInterval(check, POLL_CHAT_POPUP_MS);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session?.token, chatSeenKey, view]);

  const chatPopupEl = chatPopup ? (
    <div className="msg-popup-overlay" role="alertdialog" aria-live="assertive">
      <div className="msg-popup">
        <div className="msg-popup__title">💬 Сообщение от ведущего</div>
        <div className="msg-popup__text">{chatPopup.message_text || (chatPopup.image_data_url ? "📷 Фото" : "")}</div>
        <div className="msg-popup__actions">
          <button
            type="button"
            onClick={() => {
              markChatSeen(chatPopup.id);
              setChatPopup(null);
              setView("messages");
            }}
          >
            Открыть сообщения
          </button>
          <button
            type="button"
            className="link-btn"
            onClick={() => {
              markChatSeen(chatPopup.id);
              setChatPopup(null);
            }}
          >
            Закрыть
          </button>
        </div>
      </div>
    </div>
  ) : null;
  // ДОБАВЛЕНО (2026-10-01, запрос пользователя "заказ через скриншот") —
  // при переходе из кнопки "Скриншот" в форме заказа сразу прокручиваем к
  // отдельному разделу для скриншота в Сообщениях, чтобы не искать его
  // среди остальных пунктов.
  const [focusScreenshotOrder, setFocusScreenshotOrder] = useState(false);

  const [songTitle, setSongTitle] = useState("");
  // Поиск песни начат — панель "Заказать песню" перестаёт мигать до отправки заказа.
  const [aiSearchStarted, setAiSearchStarted] = useState(false);
  const [aiSearchFailed, setAiSearchFailed] = useState(false);
  // Предупреждение "Вы заказываете через Интернет" — показываем один раз, при первом
  // автовыборе категории по ссылке. Флаг запоминаем в браузере гостя (localStorage, с try/catch).
  const [internetHint, setInternetHint] = useState(null);
  const [internetHintOff, setInternetHintOff] = useState(() => {
    try { return window.localStorage.getItem("internetHintOff") === "1"; } catch { return false; }
  });
  const [artist, setArtist] = useState("");
  const [serviceId, setServiceId] = useState("");
  const [showCategoryInfo, setShowCategoryInfo] = useState(false);
  const [pendingCrazyServiceId, setPendingCrazyServiceId] = useState(null);
  // ОЗНАКОМИТЕЛЬНАЯ ПЛАШКА: показывается один раз, при первом заказе в этом браузере.
  const [showFirstOrderNotice, setShowFirstOrderNotice] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState(null);
  // ДОБАВЛЕНО (2026-09-19, запрос пользователя): держим не просто "успех
  // да/нет", а сам номер места в очереди из ответа сервера (order.
  // queue_position, см. routes/guest.py::create_order) — баннер ниже
  // показывает именно его, а не текст про ожидание чьего-то подтверждения.
  const [submitOk, setSubmitOk] = useState(null);

  const [orders, setOrders] = useState([]);
  // ДОБАВЛЕНО (2026-09-24, см. докстринг ORDERS_TABS выше) — какая из двух
  // вкладок открыта. "current" по умолчанию: это то, ради чего гость обычно
  // и открывает "Мои заказы" — увидеть свою очередь прямо сейчас, а не
  // копаться в истории.
  const [ordersTab, setOrdersTab] = useState("current");
  // null = "Все", иначе количество дней (см. ORDER_HISTORY_PERIODS выше) —
  // старое: handlers/vip.py::vip_order_history, только для VIP; здесь
  // доступно всем ролям (аудит по "Фильтрация истории заказов"). Актуально
  // только для вкладки "История" (ordersTab === "history") — у "Мои заказы"
  // своя, не календарная, фильтрация: см. ORDERS_TABS выше и докстринг
  // routes/guest.py::list_my_orders про ?scope=session.
  //
  // ИЗМЕНЕНО (2026-09-22, жалоба пользователя: гость открывает "Мои
  // заказы" и видит уже спетые песни из прошлых визитов) — по умолчанию
  // было выставлено "Сегодня" (days=1), потому что "Мои заказы" тогда было
  // одним общим списком без вкладок. ИЗМЕНЕНО ЕЩЁ РАЗ (2026-09-24, тот же
  // разбор жалобы до конца, см. ORDERS_TABS) — раз "текущее" теперь у своей
  // вкладки со ?scope=session, "История" — уже сознательный просмотр
  // прошлого, и дефолт "Все" для неё удобнее (не приходится лишний раз
  // щёлкать, чтобы увидеть весь список, который и так уже отфильтрован по
  // вкладке от "текущего").
  const [orderHistoryDays, setOrderHistoryDays] = useState(1);
  const [orderExtra, setOrderExtra] = useState(null);
  // ДОБАВЛЕНО (2026-10, запрос пользователя): выбор тональности при заказе.
  const [toneOn, setToneOn] = useState(false);
  const [tone, setTone] = useState(null);
  const [queue, setQueue] = useState([]);
  // KJ может скрыть живую очередь от гостей (кнопка "Показывать очередь гостям") —
  // тогда блок остаётся, но вместо списка пишем "Очередь не отображается".
  const [queueVisible, setQueueVisible] = useState(true);
  // ДОБАВЛЕНО (2026-10): всплывающее сообщение "скоро ваша очередь" — за
  // две песни и за одну песню до выхода гостя, один раз на песню.
  const [turnToast, setTurnToast] = useState(null);
  const [songListsTab, setSongListsTab] = useState(null);
  const [titleHint, setTitleHint] = useState(false);
  const [categoryPicking, setCategoryPicking] = useState(false);
  // Ссылка, по которой гость нашёл песню ("🔗 Ссылка") — уходит с заказом.
  const [songUrl, setSongUrl] = useState(null);
  const songListsOpen = songListsTab != null;
  const turnToastShownRef = useRef(new Set());
  useEffect(() => {
    let text = null;
    queue.forEach((item, index) => {
      if (!item.is_mine || (index !== 1 && index !== 2)) return;
      const mark = `${item.song_title}|${index}`;
      if (turnToastShownRef.current.has(mark)) return;
      turnToastShownRef.current.add(mark);
      if (text && index === 2) return;
      text =
        index === 2
          ? `🎤 Приготовьтесь! До вашей песни «${item.song_title}» осталось 2 песни.`
          : `🎤 Вы следующий! Ваша песня «${item.song_title}» — сразу после этой.`;
    });
    if (!text) return;
    setTurnToast(text);
    try {
      if (navigator.vibrate) navigator.vibrate([200, 100, 200]);
    } catch {
      // вибрация недоступна — не страшно
    }
  }, [queue]);
  useEffect(() => {
    if (!turnToast) return undefined;
    const timer = setTimeout(() => setTurnToast(null), 30000);
    return () => clearTimeout(timer);
  }, [turnToast]);
  const [services, setServices] = useState([]);
  const [favoriteBusyOrderId, setFavoriteBusyOrderId] = useState(null);
  const [favoriteMessage, setFavoriteMessage] = useState(null);
  const [replacingOrderId, setReplacingOrderId] = useState(null);
  // Строка в "Мои заказы", где уже выбрали песню (категорию) для повторного заказа —
  // у остальных строк подсказка-мигание гаснет (2026-10-14).
  const [reorderPickedId, setReorderPickedId] = useState(null);
  const [replaceBusyOrderId, setReplaceBusyOrderId] = useState(null);
  // ДОБАВЛЕНО (2026-09-20, жалоба "нет возможности удалить" в "Мои заказы").
  const [cancelBusyOrderId, setCancelBusyOrderId] = useState(null);
  const [cancelError, setCancelError] = useState(null);
  // ДОБАВЛЕНО (2026-10): массовое удаление не спетых заказов (без KJ).
  const [bulkCancelBusy, setBulkCancelBusy] = useState(false);
  const [bulkCancelInfo, setBulkCancelInfo] = useState(null);
  // ТЗ п.45 (финальная единая модель входа) — показывает ли экран "стол +
  // Google" прямо сейчас; открывается попыткой заказать, будучи Role 5
  // (см. handleSubmitOrder), закрывается после успешной активации (см.
  // handleActivated) или если гость сам передумал.
  const [showActivation, setShowActivation] = useState(false);

  // Шаг 1: получить/создать гостевую сессию для этого клуба (ТЗ: аналог
  // старого deep-link venue{id}_table{n} — сама возможность открыть
  // ссылку с club_id и есть право заказывать за этим столом, см.
  // backend/routes/guest.py::create_session).
  //
  // bootstrapPromiseRef — React 18 StrictMode в dev-режиме намеренно
  // монтирует этот эффект дважды подряд (mount -> cleanup -> mount), чтобы
  // ловить именно такой класс багов. Раньше повторный POST
  // /api/guest/session был безобиден — оба вызова создавали одинаково
  // валидную независимую гостевую сессию, лишняя просто не использовалась.
  // С групповым столом (утверждённая спецификация) это уже НЕ безобидно:
  // два реальных запроса для одного и того же стола — это два разных
  // guest_id, и только один может стать админом, второй попадёт в pending
  // — а применённым в состоянии React мог оказаться именно "проигравший".
  // Найдено живым Playwright-тестом на реальном Vite dev server (там
  // StrictMode активен). Фикс — расшарить сам промис между обоими вызовами
  // эффекта через ref: реальный сетевой запрос уходит только один раз, а
  // применяет результат тот вызов эффекта, который не будет отменён
  // (в паре StrictMode это второй — его cleanup сработает только при
  // настоящем размонтировании).
  const bootstrapPromiseRef = useRef(null);
  useEffect(() => {
    if (linkInvalid) return undefined;

    let cancelled = false;

    async function loadOrCreateSession() {
      const stored = loadStoredSession(clubId);
      if (stored?.token) {
        try {
          const me = await api.me(stored.token);
          return { session: stored, meInfo: me };
        } catch {
          // Токен истёк/невалиден — создаём новую сессию ниже, как будто
          // гость открыл ссылку впервые.
        }
      }
      const created = await api.createSession(clubId);
      storeSession(clubId, created);
      const me = await api.me(created.token);
      return { session: created, meInfo: me };
    }

    async function bootstrap() {
      if (!bootstrapPromiseRef.current) {
        bootstrapPromiseRef.current = loadOrCreateSession();
      }
      try {
        const result = await bootstrapPromiseRef.current;
        if (cancelled) return;
        setSession(result.session);
        setMeInfo(result.meInfo);
      } catch (err) {
        if (!cancelled) {
          setInitError(err instanceof ApiError ? err.message : String(err));
        }
      }
    }

    bootstrap();
    return () => {
      cancelled = true;
    };
  }, [clubId, linkInvalid]);

  // ИЗМЕНЕНО (2026-09-24, см. ORDERS_TABS выше) — какой запрос уйдёт на
  // сервер, зависит от открытой вкладки: "current" всегда ?scope=session
  // (весь список гостя за этот визит, без кнопок периода), "history" —
  // прежний ?days=N по orderHistoryDays. И то, и другое кладём в общий
  // orders — сами вкладки на экране никогда не видны одновременно, так что
  // отдельное состояние на каждую было бы лишним.
  const refreshOrders = useCallback(async () => {
    if (!session) return;
    try {
      const data = await api.listMyOrders(
        session.token,
        ordersTab === "current" ? { scope: "session" } : { days: orderHistoryDays },
      );
      // История: последние заказы сверху (запрос пользователя 2026-10).
      setOrders(
        ordersTab === "history" && Array.isArray(data)
          ? [...data].sort((a, b) => (b.id || 0) - (a.id || 0))
          : data,
      );
    } catch {
      // Временный сбой поллинга — не блокируем форму заказа баннером.
    }
  }, [session, ordersTab, orderHistoryDays]);

  const refreshQueue = useCallback(async () => {
    if (!session) return;
    try {
      const data = await api.getQueue(session.token);
      // Скрыто KJ: сервер отдаёт {visible: false}; иначе — обычный список.
      const hidden = !Array.isArray(data) && data?.visible === false;
      setQueueVisible(!hidden);
      setQueue(Array.isArray(data) ? data : []);
    } catch {
      // Живая очередь — не критично, если один опрос не удался.
    }
  }, [session]);

  // Баланс/кэшбэк VIP меняются на бэкенде асинхронно — в момент
  // charge_at_completion(), т.е. когда песня реально доиграна в VirtualDJ,
  // а не по действию самого гостя в этой вкладке. Без отдельного опроса
  // meInfo обновлялся бы только один раз при входе и оставался бы
  // "замороженным" на старом балансе до перезагрузки страницы — гость не
  // увидел бы списание/кэшбэк за уже спетую песню. Найдено и исправлено
  // по итогам live-теста (см. финальный отчёт, п. VIP balance).
  const refreshMe = useCallback(async () => {
    if (!session) return;
    try {
      const data = await api.me(session.token);
      setMeInfo(data);
    } catch (err) {
      // Блокировка KJ (закрытие стола из панели) — показываем плашку "Стол закрыт".
      if (err instanceof ApiError && err.code === "GUEST_BLOCKED") {
        setClosedSignal((n) => n + 1);
        setMeInfo((prev) => (prev ? { ...prev, table_no: null } : prev));
      }
      // Иначе — временный сбой опроса, не критично, следующий тик подтянет.
    }
  }, [session]);

  // oxlint: "set-state-in-effect" ожидаемо и здесь, и в следующих эффектах —
  // то же самое опросное обновление внешнего состояния (заказов/очереди/
  // профиля), что и в ChatPanel выше, по той же причине (нет WebSocket у
  // Guest App).
  useEffect(() => {
    if (!session) return undefined;
    refreshOrders();
    const id = setInterval(refreshOrders, POLL_ORDERS_MS);
    return () => clearInterval(id);
  }, [session, refreshOrders]);

  // ДОБАВЛЕНО (2026-10-18, запрос пользователя): ведущий изменил категорию
  // песни — гость подтверждает («Да») или удаляет песню. Пока гость не ответил,
  // песня стоит в очереди со старой категорией (см. vdj_service.respond_category_change).
  const pendingCategoryOrder = useMemo(
    () => (Array.isArray(orders) ? orders.find((o) => o.pending_category_at) || null : null),
    [orders],
  );
  const [categoryBusy, setCategoryBusy] = useState(false);
  const pendingCategory = pendingCategoryOrder
    ? services.find((s) => String(s.id) === String(pendingCategoryOrder.pending_service_id)) || null
    : null;
  const pendingCategoryName = pendingCategory?.name || "Без категории";
  const pendingCategoryPrice = !pendingCategory
    ? ""
    : pendingCategory.is_free
      ? "Бесплатно"
      : `Цена: ${pendingCategory.price} лей`;

  async function answerCategoryChange(accept) {
    if (!pendingCategoryOrder || !session || categoryBusy) return;
    setCategoryBusy(true);
    try {
      await api.respondCategoryChange(session.token, pendingCategoryOrder.id, accept);
    } catch {
      // уже ответили или сбой сети — список обновим ниже
    } finally {
      setCategoryBusy(false);
      refreshOrders();
    }
  }

  const categoryPopupEl = pendingCategoryOrder ? (
    <div className="msg-popup-overlay" role="alertdialog" aria-modal="true">
      <div className="msg-popup">
        <div className="msg-popup__title">🎚️ Смена категории</div>
        <div className="msg-popup__text">
          {`Ведущий изменил категорию песни „${pendingCategoryOrder.song_title}“ на „${pendingCategoryName}“`}
        </div>
        {pendingCategoryPrice && <div className="msg-popup__text">{pendingCategoryPrice}</div>}
        <div className="msg-popup__actions">
          <button type="button" disabled={categoryBusy} onClick={() => answerCategoryChange(true)}>
            Да
          </button>
          <button
            type="button"
            className="link-btn"
            disabled={categoryBusy}
            onClick={() => answerCategoryChange(false)}
          >
            Удалить песню
          </button>
        </div>
      </div>
    </div>
  ) : null;

  useEffect(() => {
    if (!session) return undefined;
    refreshQueue();
    const id = setInterval(refreshQueue, POLL_QUEUE_MS);
    return () => clearInterval(id);
  }, [session, refreshQueue]);

  useEffect(() => {
    if (!session) return undefined;
    const id = setInterval(refreshMe, POLL_ME_MS);
    return () => clearInterval(id);
  }, [session, refreshMe]);

  // Тарифы клуба — статичны на время сессии, опрос не нужен, достаточно
  // загрузить один раз после готовности сессии (аудит Role 3/4/5, п.12).
  useEffect(() => {
    if (!session) return;
    api.listServices(session.token).then(setServices).catch(() => {});
  }, [session]);

  // ИЗМЕНЕНО (2026-09-23, запрос пользователя): раньше здесь автоматически
  // подставлялся тариф (сначала первый по id, потом принудительно "KARAOKE
  // — 35"), как только загружался список услуг — именно поэтому гость не
  // замечал сам факт выбора категории, за него уже выбрали. Решение
  // пользователя: категория выбирается заново при КАЖДОМ заказе (и при
  // каждой замене песни — см. ReplaceForm), поэтому автоподстановки больше
  // нет — select ниже начинается пустым, с плейсхолдером "Выберите
  // категорию…", и через required/disabled-плейсхолдер браузер не даст
  // отправить форму без осознанного выбора.

  // Вынесено из handleSubmitOrder, чтобы этим же кодом мог воспользоваться
  // handleActivated выше — после единственного экрана "стол + Google"
  // нужно закончить то же самое действие уже настоящим (новым) токеном, а
  // не токеном, который был в session на момент нажатия "Заказать".
  async function submitOrderWithToken(token) {
    setSubmitting(true);
    setSubmitError(null);
    setSubmitOk(null);
    try {
      const created = await createOrderMarked(
        token, songTitle.trim(), artist.trim() || null,
        serviceId ? Number(serviceId) : null,
        toneOn && tone != null ? tone : null,
        songUrl,
      );
      setSongTitle("");
      setArtist("");
      setSongUrl(null);
      setAiSearchStarted(false);
      setServiceId("");
      setToneOn(false);
      setTone(null);
      // queue_position — номер места в общей очереди клуба (см. docstring
      // table_board_service.get_club_queue_positions на бэкенде); "0" — на
      // случай (не должен происходить в штатной работе), если сервер по
      // какой-то причине его не прислал, тогда просто "Заказ отправлен!".
      setSubmitOk(created.queue_position ?? 0);
      await refreshOrders();
    } catch (err) {
      setSubmitError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setSubmitting(false);
    }
  }

  function isCrazyService(service) {
    return !!service && (service.name || "").trim().toUpperCase() === "CRAZY";
  }

  function handleSelectService(rawValue) {
    const service = services.find((s) => String(s.id) === rawValue);
    if (isCrazyService(service)) {
      setPendingCrazyServiceId(rawValue);
      return; // подтверждение в модалке ниже решит, применять ли выбор
    }
    setServiceId(rawValue);
  }

  function confirmCrazySelection() {
    setServiceId(pendingCrazyServiceId);
    setPendingCrazyServiceId(null);
  }

  function cancelCrazySelection() {
    setPendingCrazyServiceId(null);
  }

  async function handleSubmitOrder(event) {
    event.preventDefault();
    if (!session || !songTitle.trim()) return;

    // Ознакомительная плашка перед первым заказом (один раз в этом браузере).
    if (meInfo?.first_order_banner?.enabled && !isFirstOrderNoticeSeen()) {
      setShowFirstOrderNotice(true);
      return;
    }
    await proceedSubmitOrder();
  }

  function acknowledgeFirstOrderNotice() {
    markFirstOrderNoticeSeen();
    setShowFirstOrderNotice(false);
    proceedSubmitOrder();
  }

  async function proceedSubmitOrder() {
    if (!session || !songTitle.trim()) return;

    // ТЗ п.45 (финальная единая модель входа): до выбора стола и входа
    // через Google заказ фактически не отправляется — вместо запроса
    // открывается единственный экран активации (см. ActivationPanel и
    // handleActivated выше), который сам довершит именно это действие.
    if (!activated) {
      setSubmitError(null);
      setShowActivation(true);
      return;
    }

    await submitOrderWithToken(session.token);
  }

  async function handleAddFavorite(order) {
    setFavoriteBusyOrderId(order.id);
    setFavoriteMessage(null);
    try {
      await api.addFavorite(session.token, order.song_title, order.artist, order.service_id);
      setFavoriteMessage("Добавлено в избранное");
    } catch (err) {
      setFavoriteMessage(err instanceof ApiError ? err.message : String(err));
    } finally {
      setFavoriteBusyOrderId(null);
    }
  }

  function handleToggleReplace(orderId) {
    setReplacingOrderId((prev) => (prev === orderId ? null : orderId));
  }

  // Ошибка (например, гонка: заказ как раз перешёл в processing между
  // опросом списка и нажатием "Сохранить") намеренно НЕ перехватывается
  // здесь — она пробрасывается наверх, в ReplaceForm.handleSubmit, чтобы
  // показаться прямо рядом с формой замены, а не общим баннером страницы.
  //
  // ИЗМЕНЕНО (2026-09-20, решение пользователя "Нужно одобрение KJ"):
  // api.replaceOrder теперь создаёт только заявку (OrderChangeRequest) —
  // песня в самом заказе ещё не изменилась. refreshOrders() после этого
  // подтянет order.pending_change_request (см. routes/guest.py::
  // list_my_orders), и OrderRow сам покажет "ждите решения ведущего"
  // вместо формы замены — здесь менять больше нечего, просто перезагружаем
  // список, как и раньше.
  async function handleReplaceOrder(orderId, songTitle, artist, serviceId) {
    setReplaceBusyOrderId(orderId);
    try {
      await api.replaceOrder(session.token, orderId, songTitle, artist, serviceId);
      setReplacingOrderId(null);
      await refreshOrders();
    } finally {
      setReplaceBusyOrderId(null);
    }
  }

  // ДОБАВЛЕНО (2026-09-20, жалоба "нет возможности удалить" в "Мои заказы").
  //
  // ИЗМЕНЕНО ТЕМ ЖЕ ДНЁМ (решение пользователя "Нужно одобрение KJ (запрос
  // → Одобрить/Отклонить)"): api.cancelOrder больше не отменяет заказ
  // немедленно — она создаёт заявку (см. vdj_service.request_order_cancel),
  // которую должен одобрить KJ. Заказ поэтому НЕ пропадает из списка сразу
  // после нажатия — он останется на месте (просто с показанным статусом
  // ожидания, см. OrderRow выше) и уйдёт из "Мои заказы" только когда KJ
  // одобрит заявку и заказ реально станет rejected.
  async function handleCancelOrder(orderId) {
    setCancelBusyOrderId(orderId);
    setCancelError(null);
    try {
      await api.cancelOrder(session.token, orderId);
      await refreshOrders();
    } catch (err) {
      setCancelError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setCancelBusyOrderId(null);
    }
  }

  // ДОБАВЛЕНО (2026-10, решение пользователя "без контроля KJ, удалять можно,
  // если это не первая или вторая песня"): гость удаляет все свои не спетые
  // заказы сразу. Первые две песни стола сервер не трогает.
  async function handleCancelUnplayed() {
    if (!window.confirm("Удалить все не спетые песни? Первые две песни стола останутся.")) return;
    setBulkCancelBusy(true);
    setCancelError(null);
    setBulkCancelInfo(null);
    try {
      const data = await api.cancelUnplayedOrders(session.token);
      setBulkCancelInfo(
        data && data.cancelled
          ? `Удалено песен: ${data.cancelled}`
          : "Удалять нечего: первые две песни стола не удаляются"
      );
      await refreshOrders();
    } catch (err) {
      setCancelError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setBulkCancelBusy(false);
    }
  }

  // ТЗ п.45 (финальная единая модель входа): вызывается один раз, сразу
  // после успешного "стол + Google" в ActivationPanel — единственного
  // способа стать Role 4. Не переиспользуем refreshOrders/refreshMe-
  // замыкания старой сессии — редкий случай "уже входил с другого
  // устройства" меняет guest_id, поэтому запросы явно делаются с НОВЫМ
  // токеном, а не через стейт предыдущего рендера (существующие данные
  // гостя — избранное/заказы — при этом никуда не деваются, см. отчёт по
  // п.45: они уже записаны на постоянный номер).
  async function handleActivated(result) {
    const activatedSession = { guest_id: result.guest_id, club_id: result.club_id, table_no: result.table_no, token: result.token };
    storeSession(clubId, activatedSession);
    setSession(activatedSession);
    setShowActivation(false);
    try {
      const me = await api.me(result.token);
      setMeInfo(me);
    } catch {
      // следующий опрос подтянет актуальное состояние
    }
    // Гость уже нажимал «Заказать» до того, как открылся этот экран
    // (иначе он бы не открылся, см. handleSubmitOrder) — значит форма
    // заказа уже заполнена, и после активации нужно сразу закончить то же
    // самое действие, а не заставлять нажимать «Заказать» второй раз.
    if (songTitle.trim()) {
      await submitOrderWithToken(result.token);
    } else {
      await refreshOrders();
    }
  }

  const legalPage = getLegalPage();
  if (legalPage) {
    return <LegalPageScreen page={legalPage} />;
  }

  if (linkInvalid) {
    return (
      <div className="app-shell centered">
        <h1>🎤 Karaoke</h1>
        <p className="error-text">
          Ссылка недействительна — не указан клуб. Отсканируйте QR-код на столе ещё раз.
        </p>
      </div>
    );
  }

  if (initError) {
    return (
      <div className="app-shell centered">
        <h1>🎤 Karaoke</h1>
        <p className="error-text">{initError}</p>
      </div>
    );
  }

  if (!session || !meInfo) {
    return (
      <div className="app-shell centered">
        <p>Загрузка…</p>
      </div>
    );
  }

  // ТЗ п.45 (финальная единая модель входа): гость может заказать только
  // пройдя единственный экран "стол + Google" — до этого он Role 5
  // (смотрит очередь, выбирает песню в форму, но не заказывает). Источник
  // истины — те же две проверки, что и на бэкенде в create_order
  // (TABLE_REQUIRED, затем GOOGLE_LINK_REQUIRED); это чисто UI-отражение,
  // а не отдельное правило.
  // Вход без Google (2026-10): стол выбран — заказ открыт (решает сервер,
  // см. create_order); постоянный профиль нужен только для избранного и VIP.
  const activated = meInfo.table_no != null;

  // Групповой стол (утверждённая спецификация, вариант А — полноценный
  // шлюз): без стола эта механика не действует вообще; со столом —
  // заказывать можно, только пока сервер считает гостя admin/member
  // (табличная проверка в create_order — источник истины, это чисто
  // UI-отражение того же самого условия, а не отдельное правило).
  const hasTable = meInfo.table_no != null;
  const groupOk = !hasTable || meInfo.table_group_status === "admin" || meInfo.table_group_status === "member";
  const canOrder = activated && groupOk;
  // ДОБАВЛЕНО (2026-10-18): поля названия и исполнителя скрыты, пока работает ИИ-поиск.
  // Показываются, если ИИ-поиск недоступен, или если выбранная песня пришла без исполнителя.
  // ДОБАВЛЕНО (2026-10-18): если ИИ-поиск не ответил хоть раз — поля названия и исполнителя открываются.

  // Экран "Сообщения" (запрос пользователя 2026-10-01) — собирает в одном
  // месте пополнение VIP-баланса, чат с ведущим и ещё два пункта-заглушки
  // под будущие функции ("Общий чат", "Заказ новой песни"), вместо того
  // чтобы это было разбросано по главному экрану.
  if (view === "screenshot") {
    return (
      <div className="app-shell">
        {chatPopupEl}
{categoryPopupEl}
        <header className="app-header">
          <h1>📷 Заказ через скриншот</h1>
          <button type="button" className="btn-link" onClick={() => setView("home")}>
            ← Назад
          </button>
        </header>
        <ScreenshotOrderPanel token={session.token} services={services} />
      </div>
    );
  }

  if (view === "messages") {
    return (
      <div className="app-shell">
        {chatPopupEl}
{categoryPopupEl}
        <header className="app-header">
          <h1>✉️ Сообщения</h1>
          <button type="button" className="btn-link" onClick={() => setView("home")}>
            ← Назад
          </button>
        </header>

        <VipBalancePanel token={session.token} meInfo={meInfo} />

        {/* ИЗМЕНЕНО (запрос пользователя 2026-10-01, "чат Гости-KJ работает
        всегда") — раньше оба пункта ниже показывались только при
        meInfo.chat_enabled; пользователь явно уточнил, что чат с ведущим и
        заказ через скриншот должны работать всегда. chat_enabled остаётся
        зарезервирован под будущий отдельный чат "гость-гость" (пункт
        "Общий чат" ниже, пока заглушка). Порядок пунктов — по просьбе
        пользователя: 1) чат с ведущим, 2) заказ через скриншот, 3) общий
        чат (заглушка), 4) заказ новой песни (заглушка). */}
        <ChatPanel token={session.token} />

        {meInfo?.chat_enabled && (
        <section className="panel">
          <h2>💬 Общий чат</h2>
          <a
            className="btn-link"
            href="https://t.me/voicevocalclub/1"
            target="_blank"
            rel="noopener noreferrer"
            style={{ display: "inline-block", textDecoration: "none" }}
          >
            Открыть чат в Telegram
          </a>
        </section>
        )}

        <section className="panel">
          <h2>🎵 Заказ новой песни</h2>
          <p className="empty-hint">🛠 В разработке. Скоро заработает.</p>
        </section>
      </div>
    );
  }

  return (
    <div className={`app-shell${categoryPicking ? " app-shell--picking" : ""}`}>
      {chatPopupEl}
{categoryPopupEl}
      {showFirstOrderNotice && (
        <div className="msg-popup-overlay" role="alertdialog" aria-modal="true">
          <div className="msg-popup">
            <div className="msg-popup__title">ℹ️ Внимание</div>
            <div className="msg-popup__text">{meInfo?.first_order_banner?.text || ""}</div>
            <div className="msg-popup__actions">
              <button type="button" onClick={acknowledgeFirstOrderNotice}>
                Понятно
              </button>
            </div>
          </div>
        </div>
      )}
      
      <header className="app-header">
        <h1>🎤 {meInfo.club_name || "Karaoke"}</h1>
        <LanguageButton /><span className="app-header__table" style={{ display: guestHasOrdered() ? undefined : "none" }}>
          {meInfo.table_no != null ? `Стол ${tableLabel(meInfo.table_no)}` : "Без стола"}
        </span>
        <button type="button" className="btn-link" style={{ display: guestHasOrdered() ? undefined : "none" }} onClick={() => setView("messages")}>
          ✏️
        </button>
      </header>

      <AddToHomeScreenHint /><OfflineBanner />
      <TableJoinBanner token={session?.token} status={meInfo.table_group_status} hasTable={meInfo.table_no != null} tableNo={meInfo.table_no} onGoOrders={() => { setOrdersTab("current"); setOrderExtra("orders"); }} />
      <TableClosedBanner tableNo={meInfo?.table_no} enabled={Boolean(session)} signal={closedSignal} />

      {meInfo.table_close_receipt && !dismissedCloseRequestIds.has(meInfo.table_close_receipt.id) && (
        <TableCloseReceiptBanner
          closeRequest={meInfo.table_close_receipt}
          onDismiss={() =>
            setDismissedCloseRequestIds((prev) => new Set(prev).add(meInfo.table_close_receipt.id))
          }
        />
      )}

      {activated && (
        <ProfileNamePanel token={session.token} meInfo={meInfo} onNameChanged={refreshMe} />
      )}

      <section className="panel order-form-panel">
        <h2>Заказать песню</h2>
        {/* ИЗМЕНЕНО (жалоба пользователя 2026-09-22: "возможность выбрать
        песню была у всех независимо от стола — а вот заказать только после
        выбора стола и входа в Google"): раньше AiSearch был внутри той же
        ветки, что и сама форма/кнопка "Заказать", поэтому пропадал вместе с
        ней, как только гость активирован (стол+Google), но ещё не одобрен в
        групповом столе (groupOk) — это две разные, не связанные вещи:
        групповой стол должен ограничивать только сам ЗАКАЗ (submit), а не
        возможность посмотреть/выбрать песню. Теперь AiSearch вынесен из
        ветки и виден всегда, независимо ни от activated, ни от groupOk —
        ограничивается (веткой ниже) только форма ввода со кнопкой
        "Заказать". */}
        <AiSearch
          token={session.token}
          active={aiSearchStarted}
          onSearchStart={() => setAiSearchStarted(true)}
          onAiStatus={(ok) => setAiSearchFailed(!ok)}
          onScreenshotHelp={() => {
            setView("screenshot");
          }}
          onSuggestOther={setTitleHint}
          onPick={(song) => {
            setSongTitle(song.title);
            setArtist(song.artist || "");
            setSongUrl(song.link || null);
            // Заказ по ссылке — сразу категория "Интернет", если она есть в списке гостя
            // (скрытые "Временно убрать" в /services не приходят).
            if (song.link) {
              const internet = services.find((s) => s.link_default);
              if (internet) {
                setServiceId(String(internet.id));
                if (!internetHintOff) {
                  setInternetHint({ price: internet.price });
                  setInternetHintOff(true);
                  try { window.localStorage.setItem("internetHintOff", "1"); } catch {}
                }
              }
            }
          }}
          extra={orderExtra}
          showProfileTabs={!!meInfo.has_permanent_profile}
          onExtra={(key) => {
            if (key === "orders") setOrdersTab("current");
            if (key === "history") setOrdersTab("history");
            setOrderExtra((prev) => (prev === key ? null : key));
          }}
        />
        {internetHint ? (
          <div className="internet-hint" role="alert">
            <p>
              Вы заказываете через Интернет. Цена {Number(internetHint.price)} за заказ.
            </p>
            <button
              type="button"
              className="btn-link"
              onClick={() => setInternetHint(null)}
            >
              Понятно
            </button>
          </div>
        ) : null}
        {orderExtra === "fav" ? (
          <FavoritesPanel
            token={session.token}
            services={services}
            onOrdered={refreshOrders}
            orderingDisabled={!canOrder}
            embedded
          />
        ) : null}
        {orderExtra === "orders" || orderExtra === "history" ? (
          <div className="profile-finance">
          <h2>{ordersTab === "history" ? "История" : "Мои заказы"}</h2> {ordersTab !== "history" && <GuestPrecheck token={session?.token} />}
        {ordersTab !== "history" && orders.some((o) => o.status === "pending" || o.status === "queued") && (
          <button
            type="button"
            className="link-btn bulk-cancel-btn"
            disabled={bulkCancelBusy}
            onClick={handleCancelUnplayed}
          >
            {bulkCancelBusy ? "Удаляем…" : "🗑 Удалить все не спетые"}
          </button>
        )}
        {bulkCancelInfo && <div className="empty-hint">{bulkCancelInfo}</div>}
        {ordersTab === "history" && (
          <ClearStatsControl
            onClear={async (period) => {
              await api.clearMyHistory(session.token, "history", period);
              await refreshOrders();
            }}
          />
        )}
        {ordersTab === "history" && (
          <div className="order-history-periods">
            {ORDER_HISTORY_PERIODS.map((p) => (
              <button
                key={p.label}
                type="button"
                className={`link-btn${orderHistoryDays === p.days ? " order-history-periods__active" : ""}`}
                onClick={() => setOrderHistoryDays(p.days)}
              >
                {p.label}
              </button>
            ))}
          </div>
        )}
        {favoriteMessage && <div className="banner banner--ok">{favoriteMessage}</div>}
        {cancelError && <div className="banner banner--error">{cancelError}</div>}
        {orders.length === 0 ? (
          <p className="empty-hint">
            {ordersTab === "current"
              ? "Заказов пока нет — закажите первую песню выше."
              : orderHistoryDays === null
                ? "Заказов пока нет."
                : "Заказов за этот период нет."}
          </p>
        ) : (
          <ul className="order-list">
            {orders.map((o) => (
              <OrderRow
                key={o.id}
                order={o}
                token={session.token}
                services={services}
                isReplacing={replacingOrderId === o.id}
                onToggleReplace={handleToggleReplace}
                onReplace={handleReplaceOrder}
                replaceBusy={replaceBusyOrderId === o.id}
                onCancel={handleCancelOrder}
                cancelBusy={cancelBusyOrderId === o.id}
                // ДОБАВЛЕНО (2026-09-29, жалоба пользователя "нет
                // возможности добавить песню в избранное из Мои заказы и из
                // истории"): кнопка "➕ В избранное" в OrderRow уже была
                // готова (как и handleAddFavorite ниже) — не хватало только
                // этих двух свойств, чтобы она показалась в обоих списках
                // (эта секция рендерит и "Мои заказы", и "Историю" —
                // переключение между ними меняет только сам список orders).
                // Показывается у каждой песни без исключений.
                onFavorite={handleAddFavorite}
                favoriteBusy={favoriteBusyOrderId === o.id}
                reorder={ordersTab === "history" && canOrder}
                onReordered={refreshOrders}
                reorderPickedId={reorderPickedId}
                onReorderPick={setReorderPickedId}
              />
            ))}
          </ul>
        )}
          </div>
        ) : null}
        {activated && !groupOk ? (
          <p className="empty-hint">
            Пока вы не одобренный участник группового стола — см. панель «Групповой стол» выше.
          </p>
        ) : (
          <>
            <form className={`order-form${categoryPicking ? " order-form--picking" : ""}`} onSubmit={handleSubmitOrder}>
              <input
                type="text"
                value={songTitle}
                onChange={(e) => setSongTitle(e.target.value)}
                placeholder="Название песни"
                className={titleHint && !songTitle.trim() ? "step-blink" : undefined}
                maxLength={200}
                required
              />
              <input
                type="text"
                value={artist}
                onChange={(e) => setArtist(e.target.value)}
                placeholder="Исполнитель (обязательно)"
                maxLength={200}
                required
                className={songTitle.trim() && !artist.trim() ? "step-blink" : undefined}
              />
              {services.length > 0 && (
                // "Без тарифа" убран из списка (запрос пользователя
                // 2026-09-14 — тариф в клубе есть всегда). Значение всегда
                // начинается пустым (запрос пользователя 2026-09-23) —
                // плейсхолдер-опция ниже недоступна для повторного выбора
                // (disabled), поэтому required реально не даёт отправить
                // заказ без осознанного выбора категории каждый раз.
                <ServiceSelect
                  services={services}
                  value={serviceId}
                  onChange={setServiceId}
                  highlight={Boolean(songTitle.trim() && artist.trim())}
                  onOpenChange={setCategoryPicking}
                />
              )}
              <div className="tone-picker">
                <label className="tone-picker__check">
                  <input
                    type="checkbox"
                    checked={toneOn}
                    onChange={(e) => {
                      setToneOn(e.target.checked);
                      if (!e.target.checked) setTone(null);
                    }}
                  />
                  🎚 Тон
                  {toneOn && tone != null ? (
                    <span className="tone-badge">{tone > 0 ? `+${tone}` : tone}</span>
                  ) : null}
                  {toneOn && tone == null ? <span className="tone-picker__hint">выберите</span> : null}
                </label>
                {toneOn && (
                  <div className="tone-picker__row">
                    <div className="tone-picker__side">
                      {[-6, -5, -4, -3, -2, -1].map((t) => (
                        <button
                          key={t}
                          type="button"
                          className={`tone-picker__btn${tone === t ? " tone-picker__btn--active" : ""}`}
                          onClick={() => setTone(t)}
                        >
                          {t}
                        </button>
                      ))}
                    </div>
                    <div className="tone-picker__side">
                      {[1, 2, 3, 4, 5, 6].map((t) => (
                        <button
                          key={t}
                          type="button"
                          className={`tone-picker__btn${tone === t ? " tone-picker__btn--active" : ""}`}
                          onClick={() => setTone(t)}
                        >
                          +{t}
                        </button>
                      ))}
                    </div>
                  </div>
                )}
              </div>
              <button
                type="submit"
                disabled={submitting || !songTitle.trim() || !artist.trim()}
                className={
                  // Пока гость выбирает стол и входит через Google (showActivation),
                  // моргает только этот шаг, а не кнопка "Заказать".
                  !submitting && !showActivation && songTitle.trim() && artist.trim() && (serviceId || services.length === 0)
                    ? "step-blink"
                    : undefined
                }
              >
                {submitting ? "Отправляем…" : "🎶 Заказать"}
              </button>
            </form>
            {submitError && <div className="banner banner--error">{submitError}</div>}
            {submitOk != null && (
              <div className="banner banner--ok">
                {submitOk > 0
                  ? `Заказ отправлен! Ваш номер в очереди: ${submitOk}.`
                  : "Заказ отправлен!"}
              </div>
            )}
            {/* ТЗ п.45: единственный способ стать Role 4 — эта попытка
            заказать (будучи ещё Role 5) и открывает данный экран, см.
            handleSubmitOrder/handleActivated выше. */}
            {showActivation && (
              <ActivationPanel
                token={session.token}
                onActivated={handleActivated}
                onCancel={() => setShowActivation(false)}
              />
            )}
          </>
        )}
      </section>

      <TableGroupPanel
        token={session.token}
        guestId={session.guest_id}
        hasTable={hasTable}
        status={meInfo.table_group_status}
        tableNo={meInfo.table_no}
        onGroupChanged={refreshMe}
      />

      <section className="panel">
        {turnToast ? (
          <button type="button" className="turn-toast" onClick={() => setTurnToast(null)}>
            {turnToast}
            <span className="turn-toast__close">Нажмите, чтобы закрыть</span>
          </button>
        ) : null}
        <SongListsPanel
          token={session.token}
          tab={songListsTab}
          onTab={setSongListsTab}
          onPick={(song) => {
            setSongTitle(song.song_title);
            setArtist(song.artist || "");
            setSongUrl(null);
            setOrderExtra(null);
            const panel = document.querySelector(".order-form-panel");
            if (panel) panel.scrollIntoView({ behavior: "smooth", block: "start" });
          }}
        />
        {songListsOpen ? (
          <h2
            className="collapsible-header active-queue-title"
            role="button"
            tabIndex={0}
            aria-expanded={false}
            onClick={() => setSongListsTab(null)}
            onKeyDown={(e) => {
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                setSongListsTab(null);
              }
            }}
          >
            Активная очередь
            <span className="collapsible-caret">▼</span>
          </h2>
        ) : (
          <h2 className="active-queue-title">Активная очередь</h2>
        )}
        {songListsOpen ? null : !queueVisible ? (
          <p className="empty-hint">Очередь не отображается.</p>
        ) : queue.length === 0 ? (
          <p className="empty-hint">Очередь пуста.</p>
        ) : (
          <>
          {/* ДОБАВЛЕНО (2026-10, запрос пользователя: "гость должен визуально
          видеть в очереди, где его песня; пусть моргает зелёным; Crazy —
          красные"): подсказка с номером ближайшей песни гостя над очередью. */}
          {(() => {
            const mineIndex = queue.findIndex((q) => q.is_mine);
            if (mineIndex < 0) return null;
            return (
              <p className="queue-mine-summary">
                🎤 Ваша песня — {mineIndex + 1}-я в очереди
                {mineIndex > 0 ? `, перед вами ${mineIndex}` : " — вы следующие!"}
              </p>
            );
          })()}
          <ol className="queue-list">
            {queue.map((item, index) => {
              const itemClasses = ["queue-item"];
              const isMyTable =
                !item.is_mine && item.table_no != null && item.table_no === meInfo.table_no;
              if (item.is_vip) itemClasses.push("queue-item--vip");
              if (item.is_crazy) itemClasses.push("queue-item--crazy");
              if (isMyTable) itemClasses.push("queue-item--my-table");
              if (item.is_mine) itemClasses.push("queue-item--mine");
              return (
                <li key={item.key ?? item.vdj_item_id} className={itemClasses.join(" ")}
                  style={item.category_color ? { borderLeft: "4px solid " + item.category_color } : undefined}>
                  {item.is_vip ? "👑 " : ""}
                  {item.is_crazy ? "🔥 " : ""}
                  🎵 {item.artist ? `${item.artist} — ` : ""}
                  {item.song_title}
                  {item.is_crazy ? " — CRAZY 🔥" : ""}
                  {item.is_mine ? (
                    <span className="queue-item__mine-badge"> — {index + 1} в очереди · ваша песня</span>
                  ) : null}
                  {isMyTable ? <span className="queue-item__table-badge"> — ваш стол</span> : null}
                </li>
              );
            })}
          </ol>
          </>
        )}
      </section>
    </div>
  );
}

function GuestPrecheck({ token }) {
  const [open, setOpen] = useState(false);
  const [data, setData] = useState(null);
  const [err, setErr] = useState(null);
  const [busy, setBusy] = useState(false);
  async function toggle() {
    if (open) {
      setOpen(false);
      return;
    }
    setOpen(true);
    setData(null);
    setErr(null);
    setBusy(true);
    try {
      setData(await api.getGuestPrecheck(token));
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }
  const money = (v) => `${Number(v || 0).toFixed(2)} MDL`;
  return (
    <div className="guest-precheck">
      <button type="button" className="btn" disabled={busy} onClick={toggle}>
        {open ? "Скрыть пречек" : "🧾 Пречек"}
      </button>
      {open && (
        <div className="precheck">
          <h3>🧾 Пречек стола</h3>
          <p className="empty-hint">Так будет выглядеть чек, если закрыть стол сейчас. Стол не закрывается.</p>
          {err && <div className="banner banner--error">{err}</div>}
          {!data && !err && <p className="empty-hint">Загрузка…</p>}
          {data && (
            <>
              {data.items.length === 0 ? (
                <p className="empty-hint">Песен пока нет.</p>
              ) : (
                <ul className="precheck__items">
                  {data.items.map((it) => (
                    <li key={it.order_id} className="precheck__item">
                      <span>
                        {it.sung ? "✅" : "⏳"} {it.artist ? `${it.artist} — ` : ""}{it.song_title}
                        <span className="empty-hint">
                          {" "}· {it.category}{it.paid ? " · оплачено с VIP" : ""}
                        </span>
                      </span>
                    </li>
                  ))}
                </ul>
              )}
              <div className="precheck__totals">
                <div>Песен: <b>{data.song_count}</b></div>
                <div>Итого: <b>{money(data.total)}</b></div>
                <div>К оплате на месте: <b>{money(data.payable_total)}</b></div>
              </div>
              <p className="empty-hint">✅ — уже спета, ⏳ — ещё не спета.</p>
            </>
          )}
        </div>
      )}
    </div>
  );
}
function TableJoinBanner({ token, status, hasTable, tableNo, onGoOrders }) {
  const [view, setView] = useState(null);
  const [notice, setNotice] = useState(null);
  const [busy, setBusy] = useState(false);
  const prevStatusRef = useRef(status);
  const isAdmin = status === "admin";
  const tableText = tableNo != null ? tableLabel(tableNo) : "";

  useEffect(() => {
    const prev = prevStatusRef.current;
    prevStatusRef.current = status;
    if (prev === "pending" && (status === "member" || status === "admin")) setNotice("approved");
    else if (prev === "pending" && status === "not_joined") setNotice("rejected");
  }, [status]);

  const loadView = useCallback(async () => {
    if (!token) return;
    try {
      setView(await api.getTableGroup(token));
    } catch {
      // Временный сбой опроса — следующий тик подтянет.
    }
  }, [token]);

  useEffect(() => {
    if (!isAdmin || !hasTable) return undefined;
    loadView();
    const id = setInterval(loadView, POLL_TABLE_GROUP_MS);
    return () => clearInterval(id);
  }, [isAdmin, hasTable, loadView]);

  const requests = isAdmin && view && Array.isArray(view.pending_requests) ? view.pending_requests : [];
  const first = requests[0];

  async function act(kind) {
    if (!first || busy) return;
    setBusy(true);
    try {
      if (kind === "approve") await api.approveJoinRequest(token, first.id);
      else await api.rejectJoinRequest(token, first.id);
      await loadView();
    } catch {
      // ошибка действия — заявка останется, можно нажать ещё раз
    } finally {
      setBusy(false);
    }
  }

  const bigBox = { position: "fixed", top: "50%", left: "50%", transform: "translate(-50%, -50%)", zIndex: 1001, width: "calc(100% - 32px)", maxWidth: 460, boxSizing: "border-box", padding: "22px 18px", borderRadius: 16, textAlign: "center", fontSize: 22, fontWeight: 800, lineHeight: 1.3, boxShadow: "0 12px 40px rgba(0,0,0,0.5)", margin: 0 };
  const bigBtn = { display: "block", width: "100%", padding: "16px", borderRadius: 12, border: "none", fontWeight: 800, fontSize: 20, marginTop: 12, color: "#fff", cursor: "pointer" };
  const overlay = { position: "fixed", top: 0, left: 0, right: 0, bottom: 0, background: "rgba(0,0,0,0.6)", zIndex: 1000 };

  if (notice === "approved") {
    return (
      <section role="alert" style={{ ...bigBox, background: "#bbf7d0", color: "#14532d" }}>
        <p style={{ margin: 0 }}>✅ Вас приняли за стол {tableText}. Вы можете заказывать.</p>
        <button type="button" style={{ ...bigBtn, background: "#14532d" }} onClick={() => { setNotice(null); onGoOrders(); }}>ОК</button>
      </section>
    );
  }
  if (notice === "rejected") {
    return (
      <section role="alert" style={{ ...bigBox, background: "#fecaca", color: "#7f1d1d" }}>
        <p style={{ margin: 0 }}>❌ Заявка на стол {tableText} отклонена.</p>
        <button type="button" style={{ ...bigBtn, background: "#7f1d1d" }} onClick={() => setNotice(null)}>ОК</button>
      </section>
    );
  }
  if (status === "pending") {
    return (
      <section role="status" style={{ ...bigBox, background: "#bfdbfe", color: "#1e3a8a", animation: "kpPendingBlink 1s ease-in-out infinite" }}>
        <style>{"@keyframes kpPendingBlink{0%,100%{opacity:1}50%{opacity:0.35}}"}</style>
        <p style={{ margin: 0 }}>⏳ Запрос отправлен админу стола. Админ стола — тот, кто первым сел за стол. Ждите подтверждения.</p>
      </section>
    );
  }
  if (first) {
    const who = first.display_name || "Гость " + first.guest_id;
    return (
      <>
        <div style={overlay} />
        <section role="alert" style={{ ...bigBox, background: "#facc15", color: "#422006", animation: "kpJoinBlink 1s ease-in-out infinite" }}>
          <style>{"@keyframes kpJoinBlink{0%,100%{opacity:1}50%{opacity:0.5}}"}</style>
          <p style={{ margin: 0 }}>🙋 {who}</p>
          <p style={{ margin: "8px 0 0", fontSize: 18 }}>хочет присоединиться к столу {tableText}</p>
          <button type="button" disabled={busy} style={{ ...bigBtn, background: "#15803d" }} onClick={() => act("approve")}>✅ Принять</button>
          <button type="button" disabled={busy} style={{ ...bigBtn, background: "#991b1b" }} onClick={() => act("reject")}>✖ Отклонить</button>
        </section>
      </>
    );
  }
  return null;
}

function TableClosedBanner({ tableNo, enabled, signal }) {
  const [show, setShow] = useState(false);
  const prevTableRef = useRef(tableNo);
  useEffect(() => {
    const prev = prevTableRef.current;
    prevTableRef.current = tableNo;
    if (enabled && prev != null && tableNo == null) setShow(true);
  }, [tableNo, enabled]);
  useEffect(() => {
    if (enabled && signal > 0 && tableNo != null) setShow(true);
  }, [signal]);
  if (!show) return null;
  const box = { position: "fixed", top: "50%", left: "50%", transform: "translate(-50%, -50%)", zIndex: 1001, width: "calc(100% - 32px)", maxWidth: 460, boxSizing: "border-box", padding: "22px 18px", borderRadius: 16, textAlign: "center", fontSize: 22, fontWeight: 800, lineHeight: 1.3, boxShadow: "0 12px 40px rgba(0,0,0,0.5)", margin: 0, background: "#e5e7eb", color: "#111827" };
  return (
    <>
      <div style={{ position: "fixed", top: 0, left: 0, right: 0, bottom: 0, background: "rgba(0,0,0,0.6)", zIndex: 1000 }} />
      <section role="alert" style={box}>
        <p style={{ margin: 0 }}>🔒 Стол закрыт. Повторите вход.</p>
        <button type="button" style={{ display: "block", width: "100%", padding: "16px", borderRadius: 12, border: "none", fontWeight: 800, fontSize: 20, marginTop: 12, color: "#fff", background: "#111827", cursor: "pointer" }} onClick={() => setShow(false)}>ОК</button>
      </section>
    </>
  );
}

function OfflineBanner() {
  const [offline, setOffline] = useState(() => typeof navigator !== "undefined" && navigator.onLine === false);
  useEffect(() => {
    const on = () => setOffline(false);
    const off = () => setOffline(true);
    window.addEventListener("online", on);
    window.addEventListener("offline", off);
    return () => {
      window.removeEventListener("online", on);
      window.removeEventListener("offline", off);
    };
  }, []);
  if (!offline) return null;
  return (
    <section role="alert" style={{ background: "#fde68a", color: "#7c2d12", padding: "10px 12px", margin: "8px 12px", borderRadius: 8 }}>
      <p style={{ margin: 0 }}>⚠️ Нет связи с интернетом. Заказы сейчас не отправятся. Пожалуйста, оформите заказ у ведущего на бумажке.</p>
    </section>
  );
}

function guestHasOrdered() {
  try {
    return localStorage.getItem("guest_has_ordered") === "1";
  } catch {
    return false;
  }
}

async function createOrderMarked(...args) {
  const result = await api.createOrder(...args);
  try {
    localStorage.setItem("guest_has_ordered", "1");
  } catch {
    // localStorage недоступен: кнопки останутся скрытыми до перезагрузки
  }
  return result;
}

function LanguageButton() {
  const [open, setOpen] = useState(false);
  return (
    <div style={{ position: "relative", display: "inline-block" }}>
      <button type="button" className="btn-link" onClick={() => setOpen((v) => !v)}>
        🌐 Язык
      </button>
      {open && (
        <div style={{ position: "absolute", right: 0, top: "100%", background: "#fff", border: "1px solid #ccc", borderRadius: 8, padding: 4, zIndex: 50 }}>
          {LANGS.map((l) => (
            <button
              key={l.code}
              type="button"
              className={`lang-switch__btn${LANG === l.code ? " lang-switch__btn--active" : ""}`}
              onClick={() => {
                setOpen(false);
                if (LANG !== l.code) setLang(l.code);
              }}
            >
              <span>{l.label}</span>
              <span className="lang-switch__flag">{LANG_FLAGS[l.code]}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
