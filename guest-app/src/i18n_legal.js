// Политика конфиденциальности и условия использования на RO / EN / UK
// (русский оригинал — в App.jsx). Смысл тот же, что в русской версии.
const MAIL = `<a href="mailto:nymfa.sv@gmail.com">nymfa.sv@gmail.com</a>`;

export const LEGAL_HTML = {
  ro: {
    privacy: `
  <h1>Politica de confidențialitate</h1>
  <div class="updated">Proiectul KARAOKE PRO · actualizat: 4 octombrie 2026</div>
  <p>
    KARAOKE PRO este un serviciu (site și aplicații) care îi ajută pe oaspeții cluburilor de karaoke
    să comande melodii, să comunice cu prezentatorul și să folosească soldul VIP. Acest document
    explică pe înțelesul tuturor ce date colectăm, de ce și ce puteți face cu ele.
  </p>
  <div class="box">
    <strong>Pe scurt:</strong> nu vindem datele dvs., nu afișăm reclame, nu transmitem
    date terților (cu excepția autentificării Google, dacă o folosiți singur(ă))
    și nu primim nicio plată prin serviciu — plata în club se face direct,
    în numerar sau cu cardul, fără participarea aplicației.
  </div>
  <h2>Ce date colectăm</h2>
  <ul>
    <li><strong>Numărul tehnic al oaspetelui</strong> — un număr aleatoriu atribuit
    la deschiderea linkului/codului QR al clubului. Singur, nu identifică pe nimeni.</li>
    <li><strong>Numele și e-mailul din contul Google</strong> — doar dacă decideți singur(ă) să vă conectați
    cu Google, pentru a păstra istoricul comenzilor și a nu pierde accesul la schimbarea dispozitivului.</li>
    <li><strong>Numele afișat</strong> — ceea ce introduceți singur(ă), pentru ca prezentatorul să vadă
    un nume, nu doar un număr.</li>
    <li><strong>Fotografia</strong> — complet opțională, se încarcă doar la dorința dvs.
    (sau de prezentatorul clubului, dacă l-ați rugat) pentru recunoaștere ușoară în lista VIP.</li>
    <li><strong>Numărul mesei, comenzile de melodii, mesajele din chat cu prezentatorul, soldul VIP</strong> —
    ceea ce este necesar pentru funcționarea serviciului în timpul serii.</li>
  </ul>
  <h2>Ce nu colectăm</h2>
  <ul>
    <li>Nu procesăm carduri bancare, nu păstrăm date de plată și nu suntem un sistem
    de plăți — toată plata are loc personal, între dvs. și club.</li>
    <li>Nu folosim sisteme de urmărire publicitare sau analitice (serviciul nu conține
    contoare precum Google Analytics sau similare).</li>
  </ul>
  <h2>Cine mai vede datele dvs.</h2>
  <p>
    Singurul serviciu extern pe care îl folosim este autentificarea Google (Google
    Identity Services), și doar dacă o folosiți. O folosim doar pentru a confirma
    că sunteți dvs.; datele dvs. Google nu le transmitem nimănui.
    Datele sunt păstrate pe servere din Uniunea Europeană (centru de date din Amsterdam, furnizor Railway).
  </p>
  <h2>Cât timp păstrăm datele</h2>
  <p>
    Cât timp folosiți serviciul sau până când cereți ștergerea lor. Istoricul comenzilor și
    soldul VIP sunt necesare clubului pentru evidența internă — dacă vă ștergeți profilul (nume, fotografie,
    legătura cu Google), acest istoric rămâne în sistemul clubului, dar fără nicio legătură
    cu numele, fotografia sau e-mailul dvs. — doar un număr anonim.
  </p>
  <h2>Drepturile dvs.</h2>
  <ul>
    <li><strong>Să vedeți și să corectați</strong> — numele și fotografia pot fi schimbate direct în aplicație
    oricând.</li>
    <li><strong>Să ștergeți</strong> — în aplicație există butonul „Șterge datele mele”: numele, fotografia
    și legătura cu Google se șterg imediat și complet. De asemenea, ne puteți scrie la ${MAIL}.</li>
    <li><strong>Să depuneți o plângere</strong> — dacă considerați că datele dvs. au fost tratate
    incorect, vă puteți adresa Centrului Național pentru Protecția Datelor cu Caracter Personal
    al Republicii Moldova.</li>
  </ul>
  <h2>Copii</h2>
  <p>
    Serviciul nu este destinat special copiilor. Dacă se constată că datele unui copil au ajuns
    în sistem fără acordul părintelui — scrieți-ne, le vom șterge la prima cerere.
  </p>
  <h2>Modificări ale acestui document</h2>
  <p>
    Putem actualiza acest text pe măsura dezvoltării serviciului. Data ultimei actualizări
    este indicată în partea de sus a paginii.
  </p>
  <h2>Contacte</h2>
  <p>Pentru orice întrebări despre datele dvs. scrieți la ${MAIL}.</p>
  <a class="back" href="javascript:window.close() || history.back()">← Înapoi</a>
`,
    terms: `
  <h1>Termeni de utilizare</h1>
  <div class="updated">Proiectul KARAOKE PRO · actualizat: 4 octombrie 2026</div>
  <p>
    Folosind KARAOKE PRO (site și aplicații pentru oaspeți, prezentatori și administratori
    ai cluburilor de karaoke), sunteți de acord cu termenii de mai jos. Dacă ceva nu este clar — scrieți la ${MAIL}.
  </p>
  <h2>Ce este KARAOKE PRO</h2>
  <p>
    Este un instrument digital auxiliar pentru cluburile de karaoke: cu ajutorul lui oaspetele
    comandă melodii, comunică cu prezentatorul, își vede soldul VIP și istoricul; prezentatorul
    gestionează rândul și clienții; administratorul clubului gestionează clubul.
    KARAOKE PRO este un program-asistent, nu clubul de karaoke în sine: pentru calitatea muzicii,
    sunetului, atmosferei și deservirii răspunde localul în care vă aflați.
  </p>
  <div class="box">
    <strong>Important despre bani:</strong> KARAOKE PRO nu primește și nu procesează plăți.
    Tot ce ține de plată (intrare, băuturi, alimentarea soldului VIP etc.) are loc
    direct între dvs. și club — în numerar sau cu cardul, pe loc. Cifrele „soldului VIP” din
    aplicație sunt doar evidența internă a clubului, nu un cont de plăți.
  </div>
  <h2>Profilul și autentificarea Google</h2>
  <p>
    Autentificarea Google este opțională. Este necesară pentru a păstra numele, fotografia și istoricul
    comenzilor între vizite. Fără Google puteți folosi funcțiile de bază
    (vedeți rândul, propuneți o melodie), dar o parte din funcții (VIP, favorite, nume) devine
    disponibilă doar după autentificare. Răspundeți singur(ă) pentru accesul la contul
    dvs. Google.
  </p>
  <h2>Reguli de comportament</h2>
  <ul>
    <li>Nu folosiți nume, mesaje sau fotografii jignitoare, ilegale sau înșelătoare.</li>
    <li>Nu încercați să împiedicați funcționarea serviciului (spargere, suprasolicitare cu cereri, ocolirea
    restricțiilor).</li>
    <li>Prezentatorul sau administratorul clubului poate bloca accesul unui oaspete care încalcă
    aceste reguli — în clubul său.</li>
  </ul>
  <h2>Disponibilitatea serviciului</h2>
  <p>
    Ne străduim ca serviciul să funcționeze stabil, dar nu garantăm funcționarea non-stop
    fără întreruperi — sunt posibile pauze tehnice, actualizări și defecțiuni temporare.
  </p>
  <h2>Răspundere</h2>
  <p>
    KARAOKE PRO este oferit „ca atare”, ca instrument auxiliar.
    Nu răspundem pentru acțiunile unui anumit club, calitatea deservirii lui, disponibilitatea
    anumitor melodii sau respectarea de către club a licențelor pentru muzica interpretată — aceasta este
    responsabilitatea localului. Nu răspundem pentru disputele privind plata făcută
    direct între dvs. și club, în afara serviciului.
  </p>
  <h2>Drepturi asupra conținutului</h2>
  <p>
    Software-ul și designul KARAOKE PRO aparțin proiectului. Conținutul pe care
    îl introduceți singur(ă) (nume, fotografie, textul mesajelor) rămâne al dvs. — doar permiteți
    folosirea lui în cadrul serviciului (de exemplu, afișarea numelui dvs. prezentatorului).
  </p>
  <h2>Ștergerea datelor</h2>
  <p>
    Puteți oricând să vă ștergeți numele, fotografia și legătura cu contul Google direct în
    aplicație („Șterge datele mele”) — detalii în
    <a href="/privacy">Politica de confidențialitate</a>.
  </p>
  <h2>Modificarea termenilor</h2>
  <p>
    Putem actualiza acești termeni pe măsura dezvoltării serviciului. Data ultimei actualizări
    este indicată în partea de sus a paginii. Continuând să folosiți serviciul după modificări,
    sunteți de acord cu noua versiune.
  </p>
  <h2>Contacte</h2>
  <p>Pentru orice întrebări scrieți la ${MAIL}.</p>
  <a class="back" href="javascript:window.close() || history.back()">← Înapoi</a>
`,
  },
  en: {
    privacy: `
  <h1>Privacy policy</h1>
  <div class="updated">KARAOKE PRO project · updated: 4 October 2026</div>
  <p>
    KARAOKE PRO is a service (website and apps) that helps karaoke club guests
    order songs, talk to the host and use their VIP balance. This document
    explains in plain words what data we collect, why, and what you can do with it.
  </p>
  <div class="box">
    <strong>In short:</strong> we don't sell your data, don't show ads, don't share
    data with third parties (except Google sign-in, if you choose to use it),
    and don't accept any payments through the service — you pay the club directly,
    in cash or by card, without the app being involved.
  </div>
  <h2>What data we collect</h2>
  <ul>
    <li><strong>Technical guest number</strong> — a random number assigned
    when you open the club's link/QR code. On its own it doesn't identify anyone.</li>
    <li><strong>Name and email from your Google account</strong> — only if you choose to sign in
    with Google, to keep your order history and not lose access when you change devices.</li>
    <li><strong>Display name</strong> — what you enter yourself, so the host sees a name
    rather than just a number.</li>
    <li><strong>Photo</strong> — completely optional, uploaded only if you want to
    (or by the club's host, if you asked them to) for easy recognition in the VIP list.</li>
    <li><strong>Table number, song orders, chat messages with the host, VIP balance</strong> —
    what the service needs to work during the evening.</li>
  </ul>
  <h2>What we don't collect</h2>
  <ul>
    <li>We don't process bank cards, don't store payment data and are not a payment
    system — all payments happen in person, between you and the club.</li>
    <li>We don't use advertising or analytics tracking (the service has no
    counters such as Google Analytics or similar).</li>
  </ul>
  <h2>Who else sees your data</h2>
  <p>
    The only external service we use is Google sign-in (Google
    Identity Services), and only if you use it. We use it only to confirm
    that you are you; we don't pass your Google data on to anyone.
    Data is stored on servers in the European Union (data centre in Amsterdam, provider Railway).
  </p>
  <h2>How long we keep data</h2>
  <p>
    As long as you use the service or until you ask us to delete it. Order history and
    VIP balance are needed by the club for internal accounting — if you delete your profile (name, photo,
    Google link), this history stays in the club's system but without any connection
    to your name, photo or email — just an anonymous number.
  </p>
  <h2>Your rights</h2>
  <ul>
    <li><strong>View and correct</strong> — you can change your name and photo in the app
    at any time.</li>
    <li><strong>Delete</strong> — the app has a “Delete my data” button: your name, photo
    and Google link are erased immediately and completely. You can also write to us at ${MAIL}.</li>
    <li><strong>Complain</strong> — if you believe your data was handled
    improperly, you can contact the National Center for Personal Data Protection
    of Moldova (Centrul Național pentru Protecția Datelor cu Caracter Personal).</li>
  </ul>
  <h2>Children</h2>
  <p>
    The service is not specifically intended for children. If it turns out that a child's data entered
    the system without a parent's consent — write to us and we will delete it on first request.
  </p>
  <h2>Changes to this document</h2>
  <p>
    We may update this text as the service develops. The date of the last update
    is shown at the top of the page.
  </p>
  <h2>Contacts</h2>
  <p>For any questions about your data write to ${MAIL}.</p>
  <a class="back" href="javascript:window.close() || history.back()">← Back</a>
`,
    terms: `
  <h1>Terms of use</h1>
  <div class="updated">KARAOKE PRO project · updated: 4 October 2026</div>
  <p>
    By using KARAOKE PRO (website and apps for guests, hosts and administrators
    of karaoke clubs), you agree to the terms below. If anything is unclear — write to ${MAIL}.
  </p>
  <h2>What KARAOKE PRO is</h2>
  <p>
    It is an auxiliary digital tool for karaoke clubs: with it, a guest
    orders songs, talks to the host, sees their VIP balance and history; the host
    manages the queue and customers; the club administrator manages the club itself.
    KARAOKE PRO is a helper program, not the karaoke club itself: the venue you are in is responsible
    for the quality of the music, sound, atmosphere and service.
  </p>
  <div class="box">
    <strong>Important about money:</strong> KARAOKE PRO does not accept or process payments.
    Everything related to payment (entry, drinks, VIP balance top-ups, etc.) happens
    directly between you and the club — in cash or by card, on site. The “VIP balance” figures in
    the app are just the club's internal records, not a payment account.
  </div>
  <h2>Profile and Google sign-in</h2>
  <p>
    Google sign-in is optional. It is needed to keep your name, photo and order history
    between visits. Without Google sign-in you can use the basic features
    (see the queue, suggest a song), but some features (VIP, favorites, name) become
    available only after signing in. You are responsible for keeping access to your
    Google account secure.
  </p>
  <h2>Rules of conduct</h2>
  <ul>
    <li>Don't use offensive, illegal or misleading names, messages or photos.</li>
    <li>Don't try to interfere with the service (hacking, flooding it with requests, bypassing
    restrictions).</li>
    <li>The club's host or administrator may block a guest who breaks
    these rules — in their club.</li>
  </ul>
  <h2>Service availability</h2>
  <p>
    We try to keep the service stable, but we don't guarantee uninterrupted
    24/7 operation — technical breaks, updates and temporary outages are possible.
  </p>
  <h2>Liability</h2>
  <p>
    KARAOKE PRO is provided “as is”, as an auxiliary tool.
    We are not responsible for the actions of a particular club, the quality of its service, the availability
    of particular songs or the club's compliance with licences for the music performed — that is
    the venue's responsibility. We are not responsible for disputes over payments made
    directly between you and the club, outside the service.
  </p>
  <h2>Content rights</h2>
  <p>
    The KARAOKE PRO software and design belong to the project. Content that
    you enter yourself (name, photo, message text) remains yours — you only allow
    it to be used for the service to work (for example, to show your name to the host).
  </p>
  <h2>Deleting data</h2>
  <p>
    You can delete your name, photo and Google account link at any time directly in the
    app (“Delete my data”) — more details in the
    <a href="/privacy">Privacy policy</a>.
  </p>
  <h2>Changes to the terms</h2>
  <p>
    We may update these terms as the service develops. The date of the last update
    is shown at the top of the page. By continuing to use the service after changes, you
    agree to the new version.
  </p>
  <h2>Contacts</h2>
  <p>For any questions write to ${MAIL}.</p>
  <a class="back" href="javascript:window.close() || history.back()">← Back</a>
`,
  },
  uk: {
    privacy: `
  <h1>Політика конфіденційності</h1>
  <div class="updated">Проєкт KARAOKE PRO · оновлено: 4 жовтня 2026</div>
  <p>
    KARAOKE PRO — це сервіс (сайт і застосунки), який допомагає гостям караоке-клубів
    замовляти пісні, спілкуватися з ведучим і користуватися VIP-балансом. Цей документ
    простими словами пояснює, які дані ми збираємо, навіщо і що ви можете з ними зробити.
  </p>
  <div class="box">
    <strong>Коротко:</strong> ми не продаємо ваші дані, не показуємо рекламу, не передаємо
    дані третім особам (окрім входу через Google, якщо ви самі ним користуєтеся)
    і не приймаємо через сервіс жодних платежів — оплата в клубі відбувається напряму,
    готівкою або карткою, без участі застосунку.
  </div>
  <h2>Які дані ми збираємо</h2>
  <ul>
    <li><strong>Технічний номер гостя</strong> — випадковий номер, який присвоюється
    під час відкриття посилання/QR-коду клубу. Сам по собі він нікого не ідентифікує.</li>
    <li><strong>Ім'я та пошта з Google-акаунта</strong> — лише якщо ви самі вирішите увійти
    через Google, щоб зберегти історію замовлень і не втрачати доступ під час зміни пристрою.</li>
    <li><strong>Ім'я для показу</strong> — те, що ви самі вводите, щоб ведучий бачив не
    просто номер, а ім'я.</li>
    <li><strong>Фото</strong> — повністю необов'язково, завантажується лише за вашим
    бажанням (або ведучим клубу, якщо ви його про це попросили) для зручного
    впізнавання у VIP-списку.</li>
    <li><strong>Номер столу, замовлення пісень, повідомлення в чаті з ведучим, VIP-баланс</strong> —
    те, що потрібно для роботи сервісу протягом вечора.</li>
  </ul>
  <h2>Чого ми не збираємо</h2>
  <ul>
    <li>Ми не обробляємо банківські картки, не зберігаємо платіжні дані й не є
    платіжною системою — уся оплата відбувається особисто, між вами та клубом.</li>
    <li>Ми не використовуємо рекламних та аналітичних систем відстеження (сервіс не містить
    лічильників на кшталт Google Analytics і подібних).</li>
  </ul>
  <h2>Хто ще бачить ваші дані</h2>
  <p>
    Єдиний зовнішній сервіс, який ми використовуємо, — це вхід через Google (Google
    Identity Services), і лише якщо ви самі ним скористаєтеся. Ми використовуємо його лише
    для підтвердження, що ви — це ви; далі ваші дані Google ми нікому не передаємо.
    Дані зберігаються на серверах у Євросоюзі (дата-центр в Амстердамі, провайдер Railway).
  </p>
  <h2>Скільки зберігаються дані</h2>
  <p>
    Поки ви користуєтеся сервісом або поки самі не попросите їх видалити. Історія замовлень і
    VIP-баланс потрібні клубу для внутрішнього обліку — якщо ви видалите свій профіль (ім'я, фото,
    прив'язку до Google), ця історія залишиться в системі клубу, але вже без жодного зв'язку
    з вашим ім'ям, фото чи поштою — лише знеособлений номер.
  </p>
  <h2>Ваші права</h2>
  <ul>
    <li><strong>Переглянути й виправити</strong> — ім'я та фото можна змінювати прямо в застосунку
    будь-коли.</li>
    <li><strong>Видалити</strong> — у застосунку є кнопка «Видалити мої дані»: ім'я, фото
    та прив'язка до Google стираються одразу й повністю. Також можна написати нам на ${MAIL}.</li>
    <li><strong>Поскаржитися</strong> — якщо вважаєте, що з вашими даними повелися
    неправильно, можна звернутися до Національного центру із захисту персональних даних
    Молдови (Centrul Național pentru Protecția Datelor cu Caracter Personal).</li>
  </ul>
  <h2>Діти</h2>
  <p>
    Сервіс не розрахований спеціально на дітей. Якщо з'ясується, що дані дитини потрапили
    в систему без згоди батьків — напишіть нам, ми видалимо їх на перший запит.
  </p>
  <h2>Зміни в цьому документі</h2>
  <p>
    Ми можемо оновлювати цей текст у міру розвитку сервісу. Дата останнього оновлення
    вказана вгорі сторінки.
  </p>
  <h2>Контакти</h2>
  <p>З будь-яких питань щодо ваших даних пишіть на ${MAIL}.</p>
  <a class="back" href="javascript:window.close() || history.back()">← Назад</a>
`,
    terms: `
  <h1>Умови використання</h1>
  <div class="updated">Проєкт KARAOKE PRO · оновлено: 4 жовтня 2026</div>
  <p>
    Використовуючи KARAOKE PRO (сайт і застосунки для гостей, ведучих та адміністраторів
    караоке-клубів), ви погоджуєтеся з умовами нижче. Якщо щось незрозуміло — пишіть на ${MAIL}.
  </p>
  <h2>Що таке KARAOKE PRO</h2>
  <p>
    Це допоміжний цифровий інструмент для караоке-клубів: з його допомогою гість
    замовляє пісні, спілкується з ведучим, бачить свій VIP-баланс та історію; ведучий
    керує чергою та клієнтами; адміністратор клубу керує самим клубом.
    KARAOKE PRO — це програма-помічник, а не сам караоке-клуб: за якість музики,
    звуку, атмосфери та обслуговування відповідає заклад, у якому ви перебуваєте.
  </p>
  <div class="box">
    <strong>Важливо про гроші:</strong> KARAOKE PRO не приймає й не обробляє платежі.
    Усе, що пов'язано з оплатою (вхід, напої, поповнення VIP-балансу тощо), відбувається
    напряму між вами та клубом — готівкою або карткою, на місці. Цифри «VIP-балансу» в
    застосунку — це лише внутрішній облік клубу, а не платіжний рахунок.
  </div>
  <h2>Профіль і вхід через Google</h2>
  <p>
    Вхід через Google — за бажанням. Він потрібен, щоб зберегти ваше ім'я, фото та історію
    замовлень між візитами. Без входу через Google можна користуватися базовими функціями
    (переглянути чергу, запропонувати пісню), але частина функцій (VIP, обране, ім'я) стане
    доступна лише після входу. Ви самі відповідаєте за збереження доступу до свого
    Google-акаунта.
  </p>
  <h2>Правила поведінки</h2>
  <ul>
    <li>Не використовуйте образливих, незаконних або оманливих імен,
    повідомлень чи фото.</li>
    <li>Не намагайтеся заважати роботі сервісу (зламувати, перевантажувати запитами, обходити
    обмеження).</li>
    <li>Ведучий або адміністратор клубу може заблокувати доступ гостю, який порушує
    ці правила, — у своєму клубі.</li>
  </ul>
  <h2>Доступність сервісу</h2>
  <p>
    Ми намагаємося, щоб сервіс працював стабільно, але не гарантуємо цілодобової
    безперебійної роботи — можливі технічні перерви, оновлення й тимчасові збої.
  </p>
  <h2>Відповідальність</h2>
  <p>
    KARAOKE PRO надається «як є», як допоміжний інструмент.
    Ми не відповідаємо за дії конкретного клубу, якість його обслуговування, доступність
    конкретних пісень чи дотримання клубом ліцензій на музику, що виконується, — це
    відповідальність самого закладу. Ми не відповідаємо за суперечки щодо оплати, яка відбулася
    напряму між вами та клубом, поза сервісом.
  </p>
  <h2>Права на контент</h2>
  <p>
    Програмне забезпечення та дизайн KARAOKE PRO належать проєкту. Контент, який
    вводите ви самі (ім'я, фото, текст повідомлень), залишається вашим — ви лише дозволяєте
    використовувати його в межах роботи сервісу (наприклад, показати ваше ім'я ведучому).
  </p>
  <h2>Видалення даних</h2>
  <p>
    Ви можете будь-коли видалити своє ім'я, фото та прив'язку до Google-акаунта прямо в
    застосунку («Видалити мої дані») — докладніше в
    <a href="/privacy">Політиці конфіденційності</a>.
  </p>
  <h2>Зміни умов</h2>
  <p>
    Ми можемо оновлювати ці умови в міру розвитку сервісу. Дата останнього оновлення
    вказана вгорі сторінки. Продовжуючи користуватися сервісом після змін, ви
    погоджуєтеся з новою версією.
  </p>
  <h2>Контакти</h2>
  <p>З будь-яких питань пишіть на ${MAIL}.</p>
  <a class="back" href="javascript:window.close() || history.back()">← Назад</a>
`,
  },
};
