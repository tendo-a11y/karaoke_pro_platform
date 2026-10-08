// Языки панели гостя (запрос пользователя 2026-10): RU (исходный), RO, EN, UK.
// Весь текст в App.jsx остаётся на русском, а этот модуль на лету заменяет
// показанный на экране текст (и сообщения сервера) по словарю ниже. Так
// новые правки интерфейса не ломаются: непереведённая строка просто
// останется русской. Выбор языка запоминается на телефоне; при первом
// входе — по языку телефона (ru → RU, ro/mo → RO, uk → UK, иначе EN).

export const LANGS = [
  { code: "ru", label: "RU" },
  { code: "ro", label: "RO" },
  { code: "en", label: "EN" },
  { code: "uk", label: "UA" },
];
const KEY = "kp_lang";
const CODES = LANGS.map((l) => l.code);

function detectLang() {
  try {
    const saved = localStorage.getItem(KEY);
    if (CODES.includes(saved)) return saved;
  } catch {
    /* ignore */
  }
  const list = (navigator.languages && navigator.languages.length ? navigator.languages : [navigator.language || ""])
    .map((x) => String(x).toLowerCase());
  for (const l of list) {
    if (l.startsWith("ru")) return "ru";
    if (l.startsWith("ro") || l.startsWith("mo")) return "ro";
    if (l.startsWith("uk")) return "uk";
    if (l.startsWith("en")) return "en";
  }
  return "en";
}

export const LANG = detectLang();

export function setLang(code) {
  try {
    localStorage.setItem(KEY, code);
  } catch {
    /* ignore */
  }
  window.location.reload();
}

const IDX = { ro: 0, en: 1, uk: 2 };

// Ключ — русский текст, значение — [румынский, английский, украинский].
const D = {
  // --- Очередь, заказы ---
  "⏳ Ждёт очереди": ["⏳ Așteaptă rândul", "⏳ Waiting in queue", "⏳ Чекає черги"],
  "Сегодня": ["Astăzi", "Today", "Сьогодні"],
  "Неделя": ["Săptămâna", "Week", "Тиждень"],
  "Месяц": ["Luna", "Month", "Місяць"],
  "Год": ["Anul", "Year", "Рік"],
  "Все": ["Toate", "All", "Усі"],
  "Мои заказы": ["Comenzile mele", "My orders", "Мої замовлення"],
  "История": ["Istoric", "History", "Історія"],
  "Начисление": ["Alimentare", "Top-up", "Нарахування"],
  "Списание KJ": ["Debitare KJ", "KJ charge", "Списання KJ"],
  "Оплата заказа": ["Plata comenzii", "Order payment", "Оплата замовлення"],
  "Кэшбэк": ["Cashback", "Cashback", "Кешбек"],
  "Возврат": ["Rambursare", "Refund", "Повернення"],
  "(бесплатно)": ["(gratuit)", "(free)", "(безкоштовно)"],
  "Выберите категорию…": ["Alegeți categoria…", "Choose a category…", "Оберіть категорію…"],
  "Описание категории": ["Descrierea categoriei", "Category description", "Опис категорії"],
  "Бесплатно": ["Gratuit", "Free", "Безкоштовно"],
  "Описание пока не добавлено.": ["Descrierea nu a fost adăugată încă.", "No description yet.", "Опис ще не додано."],
  "⚠️ Это самая дорогая категория: песня вне очереди стоит": [
    "⚠️ Aceasta este cea mai scumpă categorie: o melodie fără rând costă",
    "⚠️ This is the most expensive category: a song out of turn costs",
    "⚠️ Це найдорожча категорія: пісня поза чергою коштує",
  ],
  "лей. Подтвердите, что выбираете её осознанно.": [
    "lei. Confirmați că o alegeți în mod conștient.",
    "lei. Please confirm you are choosing it on purpose.",
    "лей. Підтвердіть, що обираєте її свідомо.",
  ],
  "Выбрать": ["Alege", "Choose", "Обрати"],
  "Закрыть": ["Închide", "Close", "Закрити"],
  "История за час": ["Ultima oră", "Last hour", "Остання година"],
  "За последний час ещё ничего не спели.": [
    "În ultima oră nu s-a cântat încă nimic.",
    "Nothing has been sung in the last hour yet.",
    "За останню годину ще нічого не співали.",
  ],
  "Популярные": ["Populare", "Popular", "Популярні"],
  "Пока нет данных.": ["Deocamdată nu sunt date.", "No data yet.", "Поки немає даних."],
  "Новинки": ["Noutăți", "New songs", "Новинки"],
  "Новинок пока нет.": ["Deocamdată nu sunt noutăți.", "No new songs yet.", "Новинок поки немає."],
  "Заказать": ["Comandă", "Order", "Замовити"],
  "Загрузка…": ["Se încarcă…", "Loading…", "Завантаження…"],
  "🎚 Тон": ["🎚 Ton", "🎚 Key", "🎚 Тон"],
  "➕ В избранное": ["➕ La favorite", "➕ Add to favorites", "➕ До обраного"],
  "Свернуть": ["Restrânge", "Collapse", "Згорнути"],
  "🔁 Заменить песню": ["🔁 Înlocuiește melodia", "🔁 Replace song", "🔁 Замінити пісню"],
  "Отправляем…": ["Se trimite…", "Sending…", "Надсилаємо…"],
  "❌ Отменить заказ": ["❌ Anulează comanda", "❌ Cancel order", "❌ Скасувати замовлення"],
  "🔁 Заказать снова": ["🔁 Comandă din nou", "🔁 Order again", "🔁 Замовити знову"],
  "Заказ отправлен ✅": ["Comanda a fost trimisă ✅", "Order sent ✅", "Замовлення надіслано ✅"],
  "⏳ Заявка на отмену отправлена — ждите решения ведущего.": [
    "⏳ Cererea de anulare a fost trimisă — așteptați decizia prezentatorului.",
    "⏳ Cancellation request sent — wait for the host's decision.",
    "⏳ Запит на скасування надіслано — чекайте рішення ведучого.",
  ],
  "⏳ Заявка на замену песни отправлена — ждите решения ведущего.": [
    "⏳ Cererea de înlocuire a melodiei a fost trimisă — așteptați decizia prezentatorului.",
    "⏳ Song replacement request sent — wait for the host's decision.",
    "⏳ Запит на заміну пісні надіслано — чекайте рішення ведучого.",
  ],
  "Без стола": ["Fără masă", "No table", "Без столу"],
  "Заказать песню": ["Comandă o melodie", "Order a song", "Замовити пісню"],
  "Заказов пока нет — закажите первую песню выше.": [
    "Deocamdată nu sunt comenzi — comandați prima melodie mai sus.",
    "No orders yet — order your first song above.",
    "Замовлень поки немає — замовте першу пісню вище.",
  ],
  "Заказов пока нет.": ["Deocamdată nu sunt comenzi.", "No orders yet.", "Замовлень поки немає."],
  "Заказов за этот период нет.": ["Nu sunt comenzi în această perioadă.", "No orders for this period.", "Замовлень за цей період немає."],
  "Пока вы не одобренный участник группового стола — см. панель «Групповой стол» выше.": [
    "Încă nu sunteți membru aprobat al mesei de grup — vedeți panoul „Masă de grup” mai sus.",
    "You're not yet an approved member of the group table — see the “Group table” panel above.",
    "Поки ви не схвалений учасник групового столу — див. панель «Груповий стіл» вище.",
  ],
  "выберите": ["alegeți", "choose", "оберіть"],
  "🎶 Заказать": ["🎶 Comandă", "🎶 Order", "🎶 Замовити"],
  "Заказ отправлен!": ["Comanda a fost trimisă!", "Order sent!", "Замовлення надіслано!"],
  "Активная очередь": ["Rândul activ", "Active queue", "Активна черга"],
  "Очередь пуста.": ["Rândul este gol.", "The queue is empty.", "Черга порожня."],
  "🎤 Ваша песня —": ["🎤 Melodia dvs. — a", "🎤 Your song is number", "🎤 Ваша пісня —"],
  "-я в очереди": ["-a la rând", " in the queue", "-а в черзі"],
  "— вы следующие!": ["— sunteți următorii!", "— you're next!", "— ви наступні!"],
  "в очереди · ваша песня": ["la rând · melodia dvs.", "in queue · your song", "у черзі · ваша пісня"],
  "— ваш стол": ["— masa dvs.", "— your table", "— ваш стіл"],
  "🎵 Заказ новой песни": ["🎵 Comanda unei melodii noi", "🎵 Order a new song", "🎵 Замовлення нової пісні"],
  "🛠 В разработке. Скоро заработает.": ["🛠 În lucru. Va funcționa în curând.", "🛠 In development. Coming soon.", "🛠 У розробці. Скоро запрацює."],

  // --- VIP, финансы, избранное ---
  "⭐ VIP-статус": ["⭐ Statut VIP", "⭐ VIP status", "⭐ VIP-статус"],
  "Пополнение баланса через приложение": ["Alimentarea soldului prin aplicație", "Top up your balance in the app", "Поповнення балансу через застосунок"],
  "Кешбек с заказов": ["Cashback la comenzi", "Cashback on orders", "Кешбек із замовлень"],
  "Повтор любимых песен": ["Repetarea melodiilor preferate", "Repeat your favorite songs", "Повтор улюблених пісень"],
  "Заявка отправлена — ждите решения ведущего.": [
    "Cererea a fost trimisă — așteptați decizia prezentatorului.",
    "Request sent — wait for the host's decision.",
    "Заявку надіслано — чекайте рішення ведучого.",
  ],
  "🎟 Стать VIP": ["🎟 Devino VIP", "🎟 Become VIP", "🎟 Стати VIP"],
  "⭐ VIP-профиль": ["⭐ Profil VIP", "⭐ VIP profile", "⭐ VIP-профіль"],
  "Баланс": ["Sold", "Balance", "Баланс"],
  "Пополните баланс, чтобы заказывать новые песни.": [
    "Alimentați soldul pentru a comanda melodii noi.",
    "Top up your balance to order new songs.",
    "Поповніть баланс, щоб замовляти нові пісні.",
  ],
  "Запрос на пополнение отправлен — ведущий уже знает.": [
    "Cererea de alimentare a fost trimisă — prezentatorul știe deja.",
    "Top-up request sent — the host already knows.",
    "Запит на поповнення надіслано — ведучий уже знає.",
  ],
  "Запросить пополнение": ["Solicită alimentare", "Request top-up", "Запросити поповнення"],
  "🧾 Финансы": ["🧾 Finanțe", "🧾 Finances", "🧾 Фінанси"],
  "За этот период операций по счёту нет.": ["Nu există operațiuni în această perioadă.", "No transactions for this period.", "За цей період операцій немає."],
  "Избранное (": ["Favorite (", "Favorites (", "Обране ("],
  "Избранное": ["Favorite", "Favorites", "Обране"],
  "Пока пусто — добавляйте песни из \"Моих заказов\".": [
    "Deocamdată e gol — adăugați melodii din „Comenzile mele”.",
    "Empty for now — add songs from “My orders”.",
    "Поки порожньо — додавайте пісні з «Моїх замовлень».",
  ],
  "Недоступно, пока вы не одобренный участник группового стола": [
    "Indisponibil până nu sunteți membru aprobat al mesei de grup",
    "Unavailable until you are an approved member of the group table",
    "Недоступно, доки ви не схвалений учасник групового столу",
  ],
  "🗑 Удалить": ["🗑 Șterge", "🗑 Delete", "🗑 Видалити"],
  "Добавлено в избранное": ["Adăugat la favorite", "Added to favorites", "Додано до обраного"],

  // --- Поиск песни ---
  "🔍 Поиск по каталогу клуба": ["🔍 Căutare în catalogul clubului", "🔍 Search the club catalog", "🔍 Пошук у каталозі клубу"],
  "Ищем…": ["Căutăm…", "Searching…", "Шукаємо…"],
  "Ничего не найдено в каталоге клуба.": ["Nu s-a găsit nimic în catalogul clubului.", "Nothing found in the club catalog.", "У каталозі клубу нічого не знайдено."],
  "· уже заказана сегодня": ["· deja comandată azi", "· already ordered today", "· вже замовлена сьогодні"],
  "🤖 ИИ-поиск": ["🤖 Căutare AI", "🤖 AI search", "🤖 ШІ-пошук"],
  "🔗 Ссылка": ["🔗 Link", "🔗 Link", "🔗 Посилання"],
  "📷 Скриншот": ["📷 Captură", "📷 Screenshot", "📷 Скриншот"],
  "Не удалось прочитать файл": ["Fișierul nu a putut fi citit", "Could not read the file", "Не вдалося прочитати файл"],
  "Не удалось открыть изображение": ["Imaginea nu a putut fi deschisă", "Could not open the image", "Не вдалося відкрити зображення"],
  "Не удалось обработать изображение": ["Imaginea nu a putut fi procesată", "Could not process the image", "Не вдалося обробити зображення"],
  "Не удалось прочитать изображение": ["Imaginea nu a putut fi citită", "Could not read the image", "Не вдалося прочитати зображення"],
  "🔗 Вставьте ссылку на YouTube, Apple Music или Spotify": [
    "🔗 Lipiți un link de pe YouTube, Apple Music sau Spotify",
    "🔗 Paste a YouTube, Apple Music or Spotify link",
    "🔗 Вставте посилання на YouTube, Apple Music або Spotify",
  ],
  "🤖 Опишите песню своими словами": ["🤖 Descrieți melodia cu propriile cuvinte", "🤖 Describe the song in your own words", "🤖 Опишіть пісню своїми словами"],
  "По этой ссылке не удалось определить песню — проверьте, что это ссылка на конкретный трек.": [
    "Nu am putut identifica melodia după acest link — verificați că este linkul unei piese anume.",
    "Couldn't identify the song from this link — make sure it links to a specific track.",
    "За цим посиланням не вдалося визначити пісню — перевірте, що це посилання на конкретний трек.",
  ],
  "Ничего не нашлось по описанию — попробуйте другой режим поиска.": [
    "Nu s-a găsit nimic după descriere — încercați alt mod de căutare.",
    "Nothing found for this description — try another search mode.",
    "За описом нічого не знайшлося — спробуйте інший режим пошуку.",
  ],
  "Загрузите скриншот из Shazam, Spotify, ВКонтакте или похожего приложения — определим песню по картинке.": [
    "Încărcați o captură de ecran din Shazam, Spotify, VKontakte sau o aplicație similară — vom identifica melodia după imagine.",
    "Upload a screenshot from Shazam, Spotify, VK or a similar app — we'll identify the song from the picture.",
    "Завантажте скриншот із Shazam, Spotify, ВКонтакте або схожого застосунку — визначимо пісню за картинкою.",
  ],
  "Распознаём…": ["Recunoaștem…", "Recognizing…", "Розпізнаємо…"],
  "Не удалось разобрать песню на скриншоте — попробуйте другой скриншот или другой режим поиска.": [
    "Nu am putut recunoaște melodia din captură — încercați altă captură sau alt mod de căutare.",
    "Couldn't recognize the song in the screenshot — try another screenshot or another search mode.",
    "Не вдалося розпізнати пісню на скриншоті — спробуйте інший скриншот або інший режим пошуку.",
  ],
  "✅ Эта?": ["✅ Aceasta?", "✅ This one?", "✅ Ця?"],
  "✕ Не эта": ["✕ Nu aceasta", "✕ Not this one", "✕ Не ця"],
  "Найти": ["Caută", "Find", "Знайти"],
  "Название песни": ["Numele melodiei", "Song title", "Назва пісні"],
  "Исполнитель (обязательно)": ["Interpret (obligatoriu)", "Artist (required)", "Виконавець (обов'язково)"],
  "Сохраняем…": ["Se salvează…", "Saving…", "Зберігаємо…"],
  "✅ Сохранить замену": ["✅ Salvează înlocuirea", "✅ Save replacement", "✅ Зберегти заміну"],
  "Отмена": ["Anulare", "Cancel", "Скасувати"],

  // --- Групповой стол ---
  "Админ стола": ["Admin masă", "Table admin", "Адмін столу"],
  "Тот, кто первым сел за стол, должен подтвердить.": [
    "Cel care s-a așezat primul la masă trebuie să confirme.",
    "Whoever sat at the table first must confirm.",
    "Той, хто першим сів за стіл, має підтвердити.",
  ],
  "Только вы решаете, кому сесть за стол.": [
    "Doar dvs. decideți cine se așază la masă.",
    "Only you decide who sits at the table.",
    "Тільки ви вирішуєте, хто сяде за стіл.",
  ],
  "Нажмите, чтобы закрыть": ["Apăsați pentru a închide", "Tap to close", "Натисніть, щоб закрити"],
  "👥 Групповой стол": ["👥 Masă de grup", "👥 Group table", "👥 Груповий стіл"],
  "⏳ Заявка на стол": ["⏳ Cererea pentru masa", "⏳ Request for table", "⏳ Заявку на стіл"],
  "отправлена. Ждите.": ["a fost trimisă. Așteptați.", "has been sent. Please wait.", "надіслано. Чекайте."],
  "Вы присоединяетесь к столу": ["Vă alăturați mesei", "You are joining table", "Ви приєднуєтеся до столу"],
  "Что значит админ стола": ["Ce înseamnă admin masă", "What a table admin is", "Що означає адмін столу"],
  "Вы — админ стола. Только вы разрешаете, кому сесть за стол. Чужие сесть не могут.": [
    "Sunteți admin masă. Doar dvs. permiteți cine se așază la masă. Străinii nu se pot așeza.",
    "You are the table admin. Only you allow who sits at the table. Strangers can't join.",
    "Ви — адмін столу. Тільки ви дозволяєте, хто сяде за стіл. Чужі сісти не можуть.",
  ],
  "👑 Админ стола": ["👑 Admin masă", "👑 Table admin", "👑 Адмін столу"],
  "🚪 Снять со стола": ["🚪 Scoate de la masă", "🚪 Remove from table", "🚪 Зняти зі столу"],
  "👑 Передать права": ["👑 Transmite drepturile", "👑 Hand over admin", "👑 Передати права"],
  "Заявки на присоединение": ["Cereri de alăturare", "Join requests", "Заявки на приєднання"],
  "✅ Принять": ["✅ Acceptă", "✅ Accept", "✅ Прийняти"],
  "❌ Отклонить": ["❌ Respinge", "❌ Decline", "❌ Відхилити"],
  "🚪 Передумал — встать из-за стола": ["🚪 M-am răzgândit — plec de la masă", "🚪 Changed my mind — leave the table", "🚪 Передумав — встати з-за столу"],
  "🚪 Встать со стола": ["🚪 Plec de la masă", "🚪 Leave the table", "🚪 Встати з-за столу"],
  "⏳ Запрос на закрытие стола отправлен — ждите подтверждения KJ.": [
    "⏳ Cererea de închidere a mesei a fost trimisă — așteptați confirmarea KJ.",
    "⏳ Table closing request sent — wait for the KJ to confirm.",
    "⏳ Запит на закриття столу надіслано — чекайте підтвердження KJ.",
  ],
  "🔒 Закрыть стол": ["🔒 Închide masa", "🔒 Close table", "🔒 Закрити стіл"],
  "Вы": ["Dvs.", "You", "Ви"],

  // --- Сообщения, чат, скриншот ---
  "Удалить всю переписку с ведущим? Это действие нельзя отменить.": [
    "Ștergeți toată corespondența cu prezentatorul? Acțiunea nu poate fi anulată.",
    "Delete the whole chat with the host? This cannot be undone.",
    "Видалити все листування з ведучим? Цю дію не можна скасувати.",
  ],
  "💬 Чат с ведущим": ["💬 Chat cu prezentatorul", "💬 Chat with the host", "💬 Чат із ведучим"],
  "Очищаем…": ["Se șterge…", "Clearing…", "Очищаємо…"],
  "🗑 Очистить чат": ["🗑 Golește chatul", "🗑 Clear chat", "🗑 Очистити чат"],
  "Сообщений пока нет.": ["Deocamdată nu sunt mesaje.", "No messages yet.", "Повідомлень поки немає."],
  "Скриншот": ["Captură de ecran", "Screenshot", "Скриншот"],
  "Удаляем…": ["Se șterge…", "Deleting…", "Видаляємо…"],
  "✕ Убрать": ["✕ Elimină", "✕ Remove", "✕ Прибрати"],
  "Написать ведущему…": ["Scrieți prezentatorului…", "Message the host…", "Написати ведучому…"],
  "Отправить": ["Trimite", "Send", "Надіслати"],
  "Не удалось открыть файл — попробуйте другой скриншот": [
    "Fișierul nu a putut fi deschis — încercați altă captură",
    "Could not open the file — try another screenshot",
    "Не вдалося відкрити файл — спробуйте інший скриншот",
  ],
  "Это фото слишком большое — сделайте обычный скриншот экрана и выберите его.": [
    "Fotografia este prea mare — faceți o captură de ecran obișnuită și alegeți-o.",
    "This photo is too large — take a regular screenshot and choose it.",
    "Це фото завелике — зробіть звичайний скриншот екрана й оберіть його.",
  ],
  "📷 Заказ через скриншот": ["📷 Comandă prin captură de ecran", "📷 Order by screenshot", "📷 Замовлення через скриншот"],
  "Пришлите скриншот нужной песни (например, из Shazam, Spotify или ВКонтакте) — ведущий посмотрит и оформит заказ сам.": [
    "Trimiteți o captură cu melodia dorită (de exemplu, din Shazam, Spotify sau VKontakte) — prezentatorul o va vedea și va face comanda singur.",
    "Send a screenshot of the song you want (e.g. from Shazam, Spotify or VK) — the host will look at it and place the order.",
    "Надішліть скриншот потрібної пісні (наприклад, із Shazam, Spotify або ВКонтакте) — ведучий подивиться й оформить замовлення сам.",
  ],
  "Скриншот отправлен ведущему ✅": ["Captura a fost trimisă prezentatorului ✅", "Screenshot sent to the host ✅", "Скриншот надіслано ведучому ✅"],
  "Загружаем…": ["Se încarcă…", "Uploading…", "Завантажуємо…"],
  "Заменить скриншот / фото": ["Înlocuiește captura / fotografia", "Replace screenshot / photo", "Замінити скриншот / фото"],
  "📷 Выберите скриншот / Фото": ["📷 Alegeți captura / fotografia", "📷 Choose screenshot / photo", "📷 Оберіть скриншот / фото"],
  "Комментарий (необязательно)": ["Comentariu (opțional)", "Comment (optional)", "Коментар (необов'язково)"],
  "Отправить ведущему": ["Trimite prezentatorului", "Send to the host", "Надіслати ведучому"],
  "← Назад": ["← Înapoi", "← Back", "← Назад"],
  "✉️ Сообщения": ["✉️ Mesaje", "✉️ Messages", "✉️ Повідомлення"],
  "💬 Общий чат": ["💬 Chat comun", "💬 Group chat", "💬 Загальний чат"],
  "Открыть чат в Telegram": ["Deschide chatul în Telegram", "Open the chat in Telegram", "Відкрити чат у Telegram"],

  // --- Профиль, вход ---
  "Имя не может быть пустым": ["Numele nu poate fi gol", "Name cannot be empty", "Ім'я не може бути порожнім"],
  "Удалить имя, фото и привязку к Google-аккаунту? Это действие нельзя отменить.": [
    "Ștergeți numele, fotografia și legătura cu contul Google? Acțiunea nu poate fi anulată.",
    "Delete your name, photo and Google account link? This cannot be undone.",
    "Видалити ім'я, фото та прив'язку до Google-акаунта? Цю дію не можна скасувати.",
  ],
  "👤 Профиль": ["👤 Profil", "👤 Profile", "👤 Профіль"],
  "Ведущий видит вас как «": ["Prezentatorul vă vede ca „", "The host sees you as “", "Ведучий бачить вас як «"],
  "Вы ещё не задали имя — ведущий видит только номер гостя.": [
    "Încă nu v-ați setat numele — prezentatorul vede doar numărul de oaspete.",
    "You haven't set a name yet — the host only sees your guest number.",
    "Ви ще не вказали ім'я — ведучий бачить лише номер гостя.",
  ],
  "Изменить имя": ["Schimbă numele", "Change name", "Змінити ім'я"],
  "Задать имя": ["Setează numele", "Set name", "Вказати ім'я"],
  "Заменить фото": ["Înlocuiește fotografia", "Replace photo", "Замінити фото"],
  "Загрузить фото (необязательно)": ["Încarcă o fotografie (opțional)", "Upload a photo (optional)", "Завантажити фото (необов'язково)"],
  "✕ Убрать фото": ["✕ Elimină fotografia", "✕ Remove photo", "✕ Прибрати фото"],
  "Политика конфиденциальности": ["Politica de confidențialitate", "Privacy policy", "Політика конфіденційності"],
  "Условия использования": ["Termeni de utilizare", "Terms of use", "Умови використання"],
  "🗑 Удалить мои данные": ["🗑 Șterge datele mele", "🗑 Delete my data", "🗑 Видалити мої дані"],
  "👤 Ваше имя": ["👤 Numele dvs.", "👤 Your name", "👤 Ваше ім'я"],
  "Как вас называть?": ["Cum să vă spunem?", "What should we call you?", "Як до вас звертатися?"],
  "Сохранить": ["Salvează", "Save", "Зберегти"],
  "Сначала укажите номер своего стола, потом нажмите кнопку Google ещё раз": [
    "Mai întâi indicați numărul mesei, apoi apăsați din nou butonul Google",
    "First enter your table number, then press the Google button again",
    "Спочатку вкажіть номер свого столу, потім натисніть кнопку Google ще раз",
  ],
  "Не удалось загрузить вход через Google — проверьте подключение к интернету и обновите страницу": [
    "Autentificarea Google nu s-a încărcat — verificați conexiunea la internet și reîncărcați pagina",
    "Google sign-in failed to load — check your internet connection and refresh the page",
    "Не вдалося завантажити вхід через Google — перевірте підключення до інтернету й оновіть сторінку",
  ],
  "Выберите стол и войдите через Google": ["Alegeți masa și conectați-vă cu Google", "Choose your table and sign in with Google", "Оберіть стіл і увійдіть через Google"],
  "Укажите номер своего стола и войдите через Google одним действием — это нужно один раз, дальше ваш стол, история заказов и избранное сохранятся.": [
    "Indicați numărul mesei și conectați-vă cu Google dintr-o singură mișcare — e nevoie doar o dată, apoi masa, istoricul comenzilor și favoritele se vor păstra.",
    "Enter your table number and sign in with Google in one step — you only need to do it once; your table, order history and favorites will be saved.",
    "Вкажіть номер свого столу й увійдіть через Google однією дією — це потрібно один раз, далі ваш стіл, історія замовлень і обране збережуться.",
  ],
  "Номер стола": ["Numărul mesei", "Table number", "Номер столу"],
  "Входим…": ["Ne conectăm…", "Signing in…", "Входимо…"],

  // --- Чек стола ---
  "🧾 Чек стола": ["🧾 Nota mesei", "🧾 Table bill", "🧾 Чек столу"],
  "шт. ·": ["buc. ·", "pcs ·", "шт. ·"],
  "· оплачено с баланса": ["· plătit din sold", "· paid from balance", "· оплачено з балансу"],
  "шт. ×": ["buc. ×", "pcs ×", "шт. ×"],
  "Песен:": ["Melodii:", "Songs:", "Пісень:"],
  "· Общая сумма чека:": ["· Suma totală:", "· Bill total:", "· Загальна сума чеку:"],
  "· К оплате:": ["· De plată:", "· To pay:", "· До сплати:"],

  // --- Подсказка «на экран телефона», ошибки ссылки ---
  "📲 Сохраните сайт на экран телефона — зайдёте в следующий раз одним нажатием, без QR-кода.": [
    "📲 Salvați site-ul pe ecranul telefonului — data viitoare intrați dintr-o atingere, fără cod QR.",
    "📲 Save the site to your home screen — next time you'll get in with one tap, no QR code.",
    "📲 Збережіть сайт на екран телефона — наступного разу зайдете одним натисканням, без QR-коду.",
  ],
  "Нажмите значок \"Поделиться\" внизу браузера, затем \"На экран Домой\".": [
    "Apăsați pictograma „Partajare” din josul browserului, apoi „Adaugă pe ecranul principal”.",
    "Tap the “Share” icon at the bottom of the browser, then “Add to Home Screen”.",
    "Натисніть значок «Поділитися» внизу браузера, потім «На екран Додому».",
  ],
  "Откройте меню браузера (⋮) и выберите \"Добавить на главный экран\".": [
    "Deschideți meniul browserului (⋮) și alegeți „Adaugă pe ecranul de pornire”.",
    "Open the browser menu (⋮) and choose “Add to Home screen”.",
    "Відкрийте меню браузера (⋮) і виберіть «Додати на головний екран».",
  ],
  "Понятно, скрыть": ["Am înțeles, ascunde", "Got it, hide", "Зрозуміло, сховати"],
  "Ссылка недействительна — не указан клуб. Отсканируйте QR-код на столе ещё раз.": [
    "Link nevalid — clubul nu este indicat. Scanați din nou codul QR de pe masă.",
    "Invalid link — no club specified. Scan the QR code on the table again.",
    "Посилання недійсне — не вказано клуб. Відскануйте QR-код на столі ще раз.",
  ],
  "Karaoke — заказ песни": ["Karaoke — comandă o melodie", "Karaoke — order a song", "Karaoke — замовлення пісні"],

  // --- Описания категорий (как их ввёл клуб) ---
  "Обычное караоке": ["Karaoke obișnuit", "Regular karaoke", "Звичайне караоке"],
  "Караоке с бэквокалом": ["Karaoke cu backing vocal", "Karaoke with backing vocals", "Караоке з бек-вокалом"],
  "Любой заказ послушать или спеть из интернета. Послушать — можно вне очереди. Спеть — строго по очереди.": [
    "Orice melodie de pe internet — de ascultat sau de cântat. Ascultare — se poate fără rând. Cântare — strict la rând.",
    "Any song from the internet to listen to or sing. Listening — can be out of turn. Singing — strictly in turn.",
    "Будь-яке замовлення послухати або заспівати з інтернету. Послухати — можна поза чергою. Заспівати — суворо по черзі.",
  ],
  "Заказ спеть KJ лично, или спеть с KJ дуэтом": [
    "Comandă ca KJ să cânte personal sau cântați în duet cu KJ",
    "Ask the KJ to sing, or sing a duet with the KJ",
    "Замовлення, щоб KJ заспівав особисто, або заспівати з KJ дуетом",
  ],
  "Песня вне очереди": ["Melodie fără rând", "Song out of turn", "Пісня поза чергою"],
  "Бесплатный бонус — ставит только KJ": ["Bonus gratuit — îl pune doar KJ", "Free bonus — only the KJ can add it", "Безкоштовний бонус — ставить лише KJ"],
  "Без категории": ["Fără categorie", "No category", "Без категорії"],
  "без названия": ["fără titlu", "untitled", "без назви"],

  // --- Сообщения сервера ---
  "Клуб не найден или отключён": ["Clubul nu a fost găsit sau este dezactivat", "Club not found or disabled", "Клуб не знайдено або вимкнено"],
  "Чтобы заказать песню, сначала выберите стол": ["Pentru a comanda o melodie, alegeți mai întâi masa", "To order a song, choose a table first", "Щоб замовити пісню, спочатку оберіть стіл"],
  "Чтобы заказать песню, сначала войдите через Google": [
    "Pentru a comanda o melodie, conectați-vă mai întâi cu Google",
    "To order a song, sign in with Google first",
    "Щоб замовити пісню, спочатку увійдіть через Google",
  ],
  "У вас нет доступа к заказам за этим столом — нужно быть одобренным участником группы": [
    "Nu aveți acces la comenzile acestei mese — trebuie să fiți membru aprobat al grupului",
    "You don't have access to orders at this table — you need to be an approved group member",
    "У вас немає доступу до замовлень за цим столом — потрібно бути схваленим учасником групи",
  ],
  "Эта песня уже заказана — вами или за вашим столом. Чтобы поменять категорию, откройте «Мои заказы» и нажмите «Заменить песню».": [
    "Această melodie a fost deja comandată — de dvs. sau la masa dvs. Pentru a schimba categoria, deschideți „Comenzile mele” și apăsați „Înlocuiește melodia”.",
    "This song has already been ordered — by you or at your table. To change the category, open “My orders” and tap “Replace song”.",
    "Цю пісню вже замовлено — вами або за вашим столом. Щоб змінити категорію, відкрийте «Мої замовлення» і натисніть «Замінити пісню».",
  ],
  "Пополните баланс, чтобы заказать ещё одну песню": [
    "Alimentați soldul pentru a comanda încă o melodie",
    "Top up your balance to order another song",
    "Поповніть баланс, щоб замовити ще одну пісню",
  ],
  "Изображение слишком большое": ["Imaginea este prea mare", "The image is too large", "Зображення завелике"],
  "Заявка уже отправлена, ждите решения KJ": ["Cererea a fost deja trimisă, așteptați decizia KJ", "Request already sent, wait for the KJ's decision", "Заявку вже надіслано, чекайте рішення KJ"],
  "Вы уже VIP": ["Sunteți deja VIP", "You're already VIP", "Ви вже VIP"],
  "Чтобы подать заявку на VIP, сначала сохраните профиль через Google": [
    "Pentru a cere statut VIP, salvați mai întâi profilul prin Google",
    "To apply for VIP, save your profile via Google first",
    "Щоб подати заявку на VIP, спочатку збережіть профіль через Google",
  ],
  "Запрос на пополнение доступен только VIP-гостям": [
    "Cererea de alimentare este disponibilă doar oaspeților VIP",
    "Top-up requests are available to VIP guests only",
    "Запит на поповнення доступний лише VIP-гостям",
  ],
  "Чтобы задать имя, сначала войдите через Google": ["Pentru a seta numele, conectați-vă mai întâi cu Google", "To set a name, sign in with Google first", "Щоб вказати ім'я, спочатку увійдіть через Google"],
  "Чтобы загрузить фото, сначала войдите через Google": [
    "Pentru a încărca o fotografie, conectați-vă mai întâi cu Google",
    "To upload a photo, sign in with Google first",
    "Щоб завантажити фото, спочатку увійдіть через Google",
  ],
  "Постоянный профиль не найден — нечего удалять": ["Profilul permanent nu a fost găsit — nu e nimic de șters", "No saved profile found — nothing to delete", "Постійний профіль не знайдено — нічого видаляти"],
  "Не найдено": ["Nu a fost găsit", "Not found", "Не знайдено"],
  "Это не ваше избранное": ["Aceasta nu este favorita dvs.", "This isn't your favorite", "Це не ваше обране"],
  "Услуга не найдена": ["Categoria nu a fost găsită", "Category not found", "Категорію не знайдено"],
  "Заказ не найден": ["Comanda nu a fost găsită", "Order not found", "Замовлення не знайдено"],
  "Это не ваш заказ": ["Aceasta nu este comanda dvs.", "This isn't your order", "Це не ваше замовлення"],
  "Эту песню уже нельзя заменить — заказ обрабатывается или скоро прозвучит": [
    "Această melodie nu mai poate fi înlocuită — comanda este în lucru sau va suna în curând",
    "This song can no longer be replaced — the order is being processed or will play soon",
    "Цю пісню вже не можна замінити — замовлення обробляється або скоро прозвучить",
  ],
  "Заявка по этому заказу уже отправлена — дождитесь решения KJ": [
    "O cerere pentru această comandă a fost deja trimisă — așteptați decizia KJ",
    "A request for this order was already sent — wait for the KJ's decision",
    "Заявку щодо цього замовлення вже надіслано — дочекайтеся рішення KJ",
  ],
  "Этот заказ уже нельзя отменить — он обрабатывается или уже сыгран": [
    "Această comandă nu mai poate fi anulată — este în lucru sau a fost deja cântată",
    "This order can no longer be cancelled — it's being processed or has already played",
    "Це замовлення вже не можна скасувати — воно обробляється або вже зігране",
  ],
  "Заявка не найдена": ["Cererea nu a fost găsită", "Request not found", "Заявку не знайдено"],
  "Только админ стола может одобрять заявки": ["Doar adminul mesei poate aproba cereri", "Only the table admin can approve requests", "Лише адмін столу може схвалювати заявки"],
  "Заявка уже обработана": ["Cererea a fost deja procesată", "The request has already been processed", "Заявку вже оброблено"],
  "Стол уже заполнен — заявка автоматически отклонена": [
    "Masa este deja plină — cererea a fost respinsă automat",
    "The table is already full — the request was declined automatically",
    "Стіл уже заповнений — заявку автоматично відхилено",
  ],
  "Только админ стола может отклонять заявки": ["Doar adminul mesei poate respinge cereri", "Only the table admin can decline requests", "Лише адмін столу може відхиляти заявки"],
  "Только админ стола может убирать участников": ["Doar adminul mesei poate scoate participanți", "Only the table admin can remove members", "Лише адмін столу може прибирати учасників"],
  "Нельзя выгнать самого себя — используйте выход": ["Nu vă puteți scoate singur — folosiți ieșirea", "You can't remove yourself — use leave instead", "Не можна вигнати самого себе — скористайтеся виходом"],
  "Этот гость не состоит в группе": ["Acest oaspete nu face parte din grup", "This guest isn't in the group", "Цей гість не входить до групи"],
  "Только текущий админ стола может передать права": [
    "Doar adminul actual al mesei poate transmite drepturile",
    "Only the current table admin can hand over rights",
    "Лише поточний адмін столу може передати права",
  ],
  "Вы уже админ стола": ["Sunteți deja admin masă", "You're already the table admin", "Ви вже адмін столу"],
  "Вы не состоите в группе этого стола": ["Nu faceți parte din grupul acestei mese", "You're not in this table's group", "Ви не входите до групи цього столу"],
  "Только админ стола может запросить закрытие": ["Doar adminul mesei poate cere închiderea", "Only the table admin can request closing", "Лише адмін столу може запросити закриття"],
  "Клуб не найден": ["Clubul nu a fost găsit", "Club not found", "Клуб не знайдено"],
  "club не найден": ["Clubul nu a fost găsit", "Club not found", "Клуб не знайдено"],
  "Нужно указать текст или изображение": ["Trebuie să indicați un text sau o imagine", "Enter text or add an image", "Потрібно вказати текст або зображення"],
  "Сообщение не найдено": ["Mesajul nu a fost găsit", "Message not found", "Повідомлення не знайдено"],
  "Нет доступа к этому сообщению": ["Nu aveți acces la acest mesaj", "No access to this message", "Немає доступу до цього повідомлення"],
  "Фото слишком большое": ["Fotografia este prea mare", "The photo is too large", "Фото завелике"],
  "У вас нет стола — групповой стол недоступен": ["Nu aveți masă — masa de grup nu este disponibilă", "You have no table — group table is unavailable", "У вас немає столу — груповий стіл недоступний"],
  "Такой категории нет": ["Nu există o astfel de categorie", "No such category", "Такої категорії немає"],
  "table_no обязателен — сначала выберите стол": ["Alegeți mai întâi masa", "Choose a table first", "Спочатку оберіть стіл"],
  "table_no должен быть положительным числом": ["Numărul mesei trebuie să fie un număr pozitiv", "Table number must be a positive number", "Номер столу має бути додатним числом"],
  "Клуб недоступен": ["Clubul nu este disponibil", "Club unavailable", "Клуб недоступний"],
  "Токен гостевой сессии отсутствует": ["Sesiunea lipsește — reîncărcați pagina", "Session missing — reload the page", "Сесія відсутня — перезавантажте сторінку"],
  "Срок действия токена истёк": ["Sesiunea a expirat", "Session expired", "Термін дії сесії минув"],
  "Сессия истекла, откройте ссылку заново": ["Sesiunea a expirat, deschideți linkul din nou", "Session expired, open the link again", "Сесія закінчилась, відкрийте посилання знову"],
  "Недействительный токен сессии": ["Sesiune nevalidă — reîncărcați pagina", "Invalid session — reload the page", "Недійсна сесія — перезавантажте сторінку"],
  "Недействительный токен": ["Sesiune nevalidă", "Invalid session", "Недійсна сесія"],
  "Доступ ограничен — обратитесь к диджею": ["Acces restricționat — adresați-vă DJ-ului", "Access restricted — please talk to the DJ", "Доступ обмежено — зверніться до діджея"],
};

// Строки с подставляемыми значениями: $1, $2 — то, что меняется (%1 — только число).
const P = [
  ["⏳ Ждёт очереди · #%1", ["⏳ Așteaptă rândul · #$1", "⏳ Waiting in queue · #$1", "⏳ Чекає черги · #$1"]],
  ["Цена: $1", ["Preț: $1", "Price: $1", "Ціна: $1"]],
  ["Да, выбираю за $1 лей", ["Da, aleg pentru $1 lei", "Yes, I choose it for $1 lei", "Так, обираю за $1 лей"]],
  ["$1 передал(а) вам права — теперь вы админ стола.", [
    "$1 v-a transmis drepturile — acum sunteți admin masă.",
    "$1 handed admin rights to you — you are now the table admin.",
    "$1 передав(ла) вам права — тепер ви адмін столу.",
  ]],
  ["$1 ушёл(а) — теперь вы админ стола.", ["$1 a plecat — acum sunteți admin masă.", "$1 left — you are now the table admin.", "$1 пішов(ла) — тепер ви адмін столу."]],
  ["Принимает на стол $1.", ["La masă primește: $1.", "Admitted by: $1.", "Приймає за стіл: $1."]],
  ["🙋 Присоединиться к столу", ["🙋 Alăturați-vă mesei", "🙋 Join the table", "🙋 Приєднатися до столу"]],
  ["🙋 Присоединиться к столу %1", ["🙋 Alăturați-vă mesei $1", "🙋 Join table $1", "🙋 Приєднатися до столу $1"]],
  ["Вы · $1", ["Dvs. · $1", "You · $1", "Ви · $1"]],
  ["Гость #%1", ["Oaspete #$1", "Guest #$1", "Гість #$1"]],
  ["Гость %1", ["Oaspete $1", "Guest $1", "Гість $1"]],
  ["🎤 Приготовьтесь! До вашей песни «$1» осталось 2 песни.", [
    "🎤 Pregătiți-vă! Până la melodia dvs. „$1” au mai rămas 2 melodii.",
    "🎤 Get ready! 2 songs left before your song “$1”.",
    "🎤 Готуйтеся! До вашої пісні «$1» залишилось 2 пісні.",
  ]],
  ["🎤 Вы следующий! Ваша песня «$1» — сразу после этой.", [
    "🎤 Sunteți următorul! Melodia dvs. „$1” urmează imediat după aceasta.",
    "🎤 You're next! Your song “$1” is right after this one.",
    "🎤 Ви наступний! Ваша пісня «$1» — одразу після цієї.",
  ]],
  ["Стол %1", ["Masa $1", "Table $1", "Стіл $1"]],
  ["Заказ отправлен! Ваш номер в очереди: $1.", [
    "Comanda a fost trimisă! Numărul dvs. la rând: $1.",
    "Order sent! Your place in the queue: $1.",
    "Замовлення надіслано! Ваш номер у черзі: $1.",
  ]],
  [", перед вами %1", [", înaintea dvs.: $1", ", ahead of you: $1", ", перед вами $1"]],
  ["Ошибка запроса ($1)", ["Eroare de cerere ($1)", "Request error ($1)", "Помилка запиту ($1)"]],
  ["Можно иметь не более $1 заказов одновременно — дождитесь, пока сыграет текущий", [
    "Puteți avea cel mult $1 comenzi simultan — așteptați să se cânte cea curentă",
    "You can have at most $1 orders at once — wait until the current one is played",
    "Можна мати не більше $1 замовлень одночасно — дочекайтеся, поки зіграє поточне",
  ]],
  ["Имя не должно быть длиннее $1 символов", ["Numele nu trebuie să depășească $1 caractere", "Name must not exceed $1 characters", "Ім'я не повинно бути довшим за $1 символів"]],
  ["В этом клубе $1 столов — выберите номер от 1 до $2", [
    "În acest club sunt $1 mese — alegeți un număr de la 1 la $2",
    "This club has $1 tables — choose a number from 1 to $2",
    "У цьому клубі $1 столів — оберіть номер від 1 до $2",
  ]],
  ["Не удалось подтвердить Google-токен: $1", ["Autentificarea Google nu a putut fi confirmată: $1", "Couldn't verify Google sign-in: $1", "Не вдалося підтвердити вхід Google: $1"]],
  ["Начисление KJ: +$1", ["Alimentare KJ: +$1", "KJ top-up: +$1", "Нарахування KJ: +$1"]],
  ["Списание KJ: -$1", ["Debitare KJ: -$1", "KJ charge: -$1", "Списання KJ: -$1"]],
  ["Установка баланса KJ: $1 → $2", ["Setare sold KJ: $1 → $2", "KJ balance set: $1 → $2", "Встановлення балансу KJ: $1 → $2"]],
  ["Оплата заказа #$1: $2", ["Plata comenzii #$1: $2", "Order payment #$1: $2", "Оплата замовлення #$1: $2"]],
  ["Кэшбэк за заказ #$1: $2", ["Cashback pentru comanda #$1: $2", "Cashback for order #$1: $2", "Кешбек за замовлення #$1: $2"]],
];

const norm = (s) => s.replace(/\s+/g, " ").trim();
const DN = {};
for (const k of Object.keys(D)) DN[norm(k)] = D[k];
const PR = P.map(([src, out]) => {
  const re = new RegExp(
    "^" + norm(src).replace(/[.*+?^$(){}|[\]\\]/g, "\\$&").replace(/\\\$(\d)/g, "(.+?)").replace(/%(\d)/g, "(\\d+)") + "$",
    "s",
  );
  return [re, out];
});
const CYR = /[А-Яа-яЁё]/;

// Перевести одну строку (весь текст узла целиком). Непонятное — как есть.
export function tr(text) {
  if (LANG === "ru" || typeof text !== "string" || !CYR.test(text)) return text;
  const m = text.match(/^(\s*)([\s\S]*?)(\s*)$/);
  const core = norm(m[2]);
  const i = IDX[LANG];
  let out = DN[core] ? DN[core][i] : null;
  if (out == null) {
    for (const [re, vals] of PR) {
      const mm = core.match(re);
      if (mm) {
        out = vals[i].replace(/\$(\d)/g, (_, n) => mm[Number(n)] ?? "");
        break;
      }
    }
  }
  return out == null ? text : m[1] + out + m[3];
}

// --- Перевод того, что на экране ---
const ATTRS = ["placeholder", "title", "aria-label"];
const done = new WeakMap();

function trText(node) {
  const p = node.parentNode;
  if (!p || p.nodeName === "SCRIPT" || p.nodeName === "STYLE" || p.nodeName === "TEXTAREA") return;
  const v = node.nodeValue;
  if (done.get(node) === v) return;
  const t = tr(v);
  if (t !== v) node.nodeValue = t;
  done.set(node, t);
}

function trAttrs(el) {
  for (const a of ATTRS) {
    if (el.hasAttribute && el.hasAttribute(a)) {
      const v = el.getAttribute(a);
      const t = tr(v);
      if (t !== v) el.setAttribute(a, t);
    }
  }
}

function trTree(root) {
  if (root.nodeType === 3) return trText(root);
  if (root.nodeType !== 1) return;
  trAttrs(root);
  const w = document.createTreeWalker(root, NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_TEXT);
  let n;
  while ((n = w.nextNode())) {
    if (n.nodeType === 3) trText(n);
    else trAttrs(n);
  }
}

export function startTranslation() {
  document.documentElement.lang = LANG === "uk" ? "uk" : LANG;
  if (LANG === "ru") return;
  document.title = tr(document.title);
  const origConfirm = window.confirm.bind(window);
  const origAlert = window.alert.bind(window);
  window.confirm = (msg) => origConfirm(tr(String(msg)));
  window.alert = (msg) => origAlert(tr(String(msg)));
  trTree(document.body);
  new MutationObserver((list) => {
    for (const m of list) {
      if (m.type === "characterData") trText(m.target);
      else if (m.type === "attributes") trAttrs(m.target);
      else m.addedNodes.forEach(trTree);
    }
  }).observe(document.body, {
    subtree: true,
    childList: true,
    characterData: true,
    attributes: true,
    attributeFilter: ATTRS,
  });
}
