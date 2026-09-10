
STRINGS: dict = {
    'ru': {
        'btn_back': '↩️ Назад',
        'btn_cancel': '❌ Отмена',
        'btn_confirm': '✅ Подтвердить',
        'btn_reject': '❌ Отклонить',
        'btn_yes': '✅ Да',
        'btn_no': '❌ Нет',
        'btn_free': 'Бесплатно',
        'error_not_found': '❌ Не найдено',
        'error_no_rights': '❌ Нет прав',
        'error_data': '❌ Ошибка данных',
        'action_cancelled': '❌ Отменено',
        'choose_action': 'Выберите действие:',

        'menu_btn': '🎵 Меню',
        'lang_btn': '🌐 Язык',

        'lang_title': '🌐 *ВЫБОР ЯЗЫКА*\n\nВыберите язык интерфейса:',
        'lang_ru': '🇷🇺 Русский',
        'lang_ro': '🇷🇴 Română',
        'lang_changed_ru': '✅ Язык изменён на Русский',
        'lang_changed_ro': '✅ Lingua schimbată la Română',

        'blocked_user': '🚫 Вы заблокированы. Обратитесь к KJ или администратору.',
        'start_first': '❌ Сначала запустите бота командой /start',
        'session_ended': '🎶 Сессия завершена.\n\nДля нового сеанса нажмите /start или отсканируйте QR-код.',
        'welcome_new': '👋 Привет, {name}!\n\nДобро пожаловать в Karaoke Absolutis!\n\nЭто бот для управления очередью в караоке.\nДля начала работы выберите ваше заведение.',

        'venue_attached': '✅ Вы привязаны к:\n🎵 {venue}\n🪑 Стол #{table}',
        'venue_attached_admin': '✅ Вы привязаны к:\n🎵 {venue}\n🪑 Стол #{table}\n\n👑 Вы главный стола',
        'select_table': '🎵 <b>{venue}</b>\n\n🪑 Выберите ваш стол:',
        'all_tables_full': '🎵 <b>{venue}</b>\n\n⚠️ Все столы заняты.\n\nХотите присоединиться как гость без стола?\nВаш заказ потребует подтверждения у KJ на месте.',
        'table_full_choose': '🎵 <b>{venue}</b>\n\n❌ Стол #{table} заполнен. Выберите свободный стол:',
        'join_request_sent': '⏳ Запрос отправлен администратору стола. Ожидайте подтверждения.',
        'already_at_table': '✅ Вы уже за столом #{table}',
        'table_selected': '✅ Стол #{table} выбран!',
        'no_table_joined': '✅ Вы присоединились к <b>{venue}</b> как гость.\nВаш виртуальный номер: <b>#{num}</b>\n\nИспользуйте /client для доступа к меню.',
        'no_table_cancelled': '❌ Отменено. Попробуйте позже или выберите другое заведение.',
        'btn_no_table_confirm': '✅ Подтвердить',
        'btn_no_table_cancel': '❌ Отмена',

        'client_main_title': '🎵 <b>ГЛАВНОЕ МЕНЮ</b>',
        'client_main_body': (
            '🏢 Клуб: <b>{venue}</b>\n'
            '👤 Статус: <b>{status}</b>\n'
            'ID: <b>{uid}</b>\n\n'
            '—————————\n\n'
            '📌 Стол: <b>{table}</b>\n'
            '📋 Ваша очередь через <b>{tables_before}</b> {tables_word} {playing_info}\n\n'
            'Выберите действие:'
        ),
        'client_status_guest': 'Гость',
        'client_status_no_table': 'Гость (без стола)',
        'client_table_no_table': 'Без стола (#{num})',
        'no_venues': '❌ Нет доступных клубов. Обратитесь к администратору.',
        'select_club': '👋 Добро пожаловать!\n\nПожалуйста, выберите ваш клуб:',
        'club_selected': '✅ Клуб <b>{venue}</b> выбран!\n\nИспользуйте /client чтобы продолжить.',
        'enter_table': '👋 Добро пожаловать!\n\nПожалуйста, введите номер вашего стола:',
        'table_set': '✅ Вы привязаны к столу {table}.\n\nИспользуйте /client для доступа к меню.',
        'venue_not_found': '❌ Клуб не найден. Выберите клуб заново командой /start',
        'table_must_be_positive': '❌ Номер стола должен быть больше 0. Попробуйте снова:',
        'no_venue_selected': '❌ Сначала выберите клуб.\nИспользуйте /client для начала.',
        'table_count_exceeded': '❌ В клубе только {count} столов.\nВведите номер от 1 до {count}:',
        'enter_table_number': '❌ Пожалуйста, введите число:',
        'you_are_table_admin': '✅ Стол {table} выбран!\n\n👑 Вы главный стола\nИспользуйте /client для доступа к меню.',
        'table_join_request_msg': '👥 Запрос на присоединение к столу\n\n🪑 Стол: {table}\n👤 Пользователь: {name} (@{username})',

        'btn_make_order': '🎵 Сделать заказ',
        'btn_my_orders': '📋 Мои заказы',
        'btn_queue': '🔄 Очередь круга',
        'btn_become_vip': '⭐ Стать VIP',
        'btn_chat_kj': '💬 Чат с KJ',
        'btn_manage_table': '👑 Управление столом',
        'btn_join_group': '👥 Вступить в группу',
        'btn_find_song': '🔍 Найти песню',
        'btn_favorites': '⭐ Избранное',
        'btn_replace_song': '🔄 Заменить песню',
        'btn_replace_blocked': '🔒 Замена недоступна (поз. 1–2)',
        'btn_add_favorite': '⭐ Добавить в избранное',
        'btn_reorder': '🔄 Повторить заказ',
        'btn_delete_favorite': '🗑️ Удалить из избранного',
        'btn_get_vip': '✨ Получить VIP статус',

        'order_menu_title': '🎵 *СДЕЛАТЬ ЗАКАЗ:*\n\n📌 Нажмите на кнопку ниже и начните вводить название песни и выберите из списка',
        'order_limit_reached': '❌ Достигнут лимит активных песен ({limit}). Дождитесь выполнения предыдущих заказов.',
        'song_not_found': '❌ Песня не найдена',
        'order_sent': (
            '⏳ <b>Заказ #{order_id} отправлен</b>\n\n'
            '🎵 {song}\n💰 {service}\n'
            '📍 Позиция в очереди: #{pos}\n\n'
            'Ожидайте подтверждения от KJ...'
        ),
        'order_sent_no_table_suffix': '\n\n⚠️ <b>ВАЖНО:</b> Подойдите к KJ для подтверждения заказа и оплаты!',
        'approach_kj': '⚠️ Подойдите к KJ для подтверждения!',
        'no_services': '❌ В клубе нет доступных услуг',
        'insufficient_balance': '❌ Недостаточно средств. Пополните у KJ',
        'insufficient_balance_detail': '❌ Недостаточно средств\nБаланс: {balance} MDL\nТребуется: {price} MDL',

        'favorites_title': '🎵 <b>МОИ ПЕСНИ</b>\nЗаказанные ранее:\n\n',
        'favorites_empty': '🎵 <b>МОИ ПЕСНИ</b>\n\nУ вас пока нет избранных песен',
        'favorite_added': '✅ Добавлено в избранное',
        'favorite_removed': '✅ Удалено из избранного',

        'my_orders_title': '📋 *МОИ ЗАКАЗЫ*\n\n',
        'my_orders_empty': '📋 *МОИ ЗАКАЗЫ*\n\nУ вас пока нет активных заказов',

        'queue_title': '📋 <b>Очередь круга</b>\n\n',
        'queue_now_playing': '▶️ <b>СЕЙЧАС:</b> <b>{table}</b>\n    └ 🎤 {song}\n\n—————————\n\n',
        'queue_table_str': 'Стол {num}',
        'queue_no_table_str': 'Без стола (#{num})',
        'queue_now_playing_info': '(сейчас исполняет {table}/{pos})',
        'queue_empty': 'Очередь пуста',
        'queue_next_header': '🔥 <b>ВНЕ ОЧЕРЕДИ:</b>\n\n',
        'queue_regular_header': '🔄 <b>ОБЩАЯ ОЧЕРЕДЬ</b>\n\n',

        'replace_title': '🔄 <b>ЗАМЕНА ПЕСНИ</b>\n\nНажмите \'🔍 Найти песню\' для поиска новой песни.',
        'btn_find_song_replace': '🔍 Найти песню',
        'replace_blocked': '❌ Замена недоступна: ваша песня #{rank} в очереди.\nЗамена разрешена только с 3-й позиции.',
        'replace_unavailable': '❌ Замена невозможна: ваша песня #{rank} в очереди.\nЗамена доступна только с 3-й позиции и дальше.',
        'order_not_found': '❌ Заказ не найден',

        'become_vip_text': (
            '⭐ *СТАТЬ VIP*\n\n{desc}\n\n'
            'VIP клиенты получают:\n'
            '• Пополнение баланса через бота\n'
            '• Кешбек с заказов\n'
            '• Повтор любимых песен\n\n'
            'Для получения VIP статуса нажмите кнопку ниже и администратор рассмотрит вашу заявку.'
        ),
        'vip_request_sent': '✅ Заявка на VIP статус отправлена!\nОжидайте подтверждения от KJ.',
        'vip_request_already': '⏳ Ваша заявка уже рассмотривается',
        'vip_access_denied': '❌ У вас нет прав VIP клиента',
        'vip_select_venue_first': '❌ Сначала выберите клуб и стол.\nОтсканируйте QR-код вашего стола.',

        'vip_menu_title': '🎵 *VIP МЕНЮ*',
        'vip_menu_body': (
            '🏢 Клуб: *{venue}*\n'
            '👤 Статус: *VIP*\n'
            'ID: *{uid}*\n'
            '💰 Баланс: *{balance} MDL*\n\n'
            '—————————\n\n'
            '📌 Стол: *{table}*\n'
            '📋 Ваша очередь через *{tables_before}* {tables_word} {playing_info}\n\n'
            'Выберите действие:'
        ),
        'vip_profile_text': (
            '👤 *ПРОФИЛЬ*\n\n'
            '👤 Имя: *{name}*\n'
            'Telegram: @{username}\n'
            '🏢 Клуб: *{venue}*\n'
            '🪑 Стол: *{table}*\n'
            '⭐ Статус: *VIP*\n'
            '💰 Баланс: *{balance} MDL*\n'
            '🎁 Кешбек: *{cashback}%*'
        ),
        'not_specified': 'не указан',

        'btn_vip_make_order': '🎵 Сделать заказ',
        'btn_vip_my_orders': '📋 Мои заказы',
        'btn_vip_queue': '🔄 Очередь круга',
        'btn_vip_balance': '💳 Мой баланс',
        'btn_vip_chat_kj': '💬 Чат с KJ',
        'btn_vip_manage_table': '👑 Управление столом',
        'btn_vip_topup': '💰 Пополнить баланс',
        'btn_vip_order_history': '📊 История заказов',
        'btn_vip_finances': '💸 Финансы',
        'btn_profile': '👤 Профиль',
        'btn_history_today': '📅 За сегодня',
        'btn_history_week': '📅 За неделю',
        'btn_history_month': '📅 За месяц',

        'balance_title': '💳 *МОЙ БАЛАНС*\n\n💰 Текущий баланс: *{balance} MDL*\n\nВыберите действие:',
        'topup_title': '💰 *ПОПОЛНЕНИЕ БАЛАНСА*\n\nВведите сумму для пополнения (в MDL):',
        'topup_invalid': '❌ Неверная сумма. Введите положительное число:',
        'topup_sent': '✅ Запрос на пополнение {amount} MDL отправлен KJ\nОжидайте подтверждения.',
        'topup_approved_client': '✅ Ваш баланс пополнен на {amount} MDL!\nНовый баланс: {balance} MDL',
        'topup_rejected_client': '❌ Запрос на пополнение {amount} MDL отклонён.',

        'order_history_title': '📊 *ИСТОРИЯ ЗАКАЗОВ*\n\nВыберите период:',
        'order_history_period': '📊 *ИСТОРИЯ ЗАКАЗОВ*\n\nЗа {period}:\n\n',
        'order_history_empty': 'Заказов нет',
        'period_today': 'Сегодня',
        'period_week': 'Неделю',
        'period_month': 'Месяц',
        'period_today_low': 'сегодня',
        'period_week_low': 'неделю',
        'period_month_low': 'месяц',

        'finances_title': '💸 *ФИНАНСЫ*\n\nВыберите период:',
        'finances_period': '💸 *ФИНАНСЫ*\n\nЗа {period}:\n\n',
        'finances_topups': '💰 *Пополнения:*\n',
        'finances_no_topups': '  Нет пополнений\n',
        'finances_total_plus': '  _Итого: +{total} MDL_\n',
        'finances_total_minus': '  _Итого: -{total} MDL_\n',
        'finances_payments': '\n🎵 *Оплата заказов:*\n',
        'finances_no_payments': '  Нет списаний\n',
        'finances_refunds': '\n↩️ *Возвраты:*\n',
        'finances_no_refunds': '  Нет возвратов\n',
        'finances_cashbacks': '\n🎁 *Кешбек:*\n',
        'finances_no_cashbacks': '  Нет кешбека\n',
        'finances_balance': '\n💳 *Текущий баланс: {balance} MDL*',

        'vip_order_title': '🎵 *СДЕЛАТЬ ЗАКАЗ:*\n\n📌 Нажмите на кнопку ниже и начните вводить название песни и выберите из списка',
        'choose_service_title': '💰 <b>ВЫБОР УСЛУГИ</b>{balance_line}',
        'choose_service_body': '\n\nДоступные услуги:\n{services}\n\nВыберите тип заказа:',
        'order_created': '✅ Заказ создан!',
        'balance_line': '\n💰 Ваш баланс: <b>{balance} MDL</b>',
        'service_free': 'Бесплатно',

        'chat_title': '💬 <b>ЧАТ С KJ</b>\n\nНапишите ваше сообщение:',
        'chat_sent': '✅ Сообщение отправлено KJ',
        'chat_failed': '❌ Не удалось отправить сообщение',
        'chat_msg_to_kj': '📨 <b>Сообщение от клиента</b>\n\n🪑 Стол <b>{table}</b>\n👤 <b>{name}</b> {vip_badge}\n\n💬 {text}',
        'btn_chat_reply': '💬 Ответить',

        'kj_new_order': (
            '🎵 <b>НОВЫЙ ЗАКАЗ #{order_id}</b>\n\n'
            '{table}\n'
            '👤 Клиент: <b>{name}</b> {vip_badge}\n'
            '🎵 Песня: <b>{song}</b>\n'
            '💼 Услуга: <b>{service}</b>\n'
            '📍 Позиция: <b>#{pos}</b>\n\n'
            '📋 Активных заказов клиента: <b>{active}/{max}</b>'
        ),
        'kj_new_order_no_table_warn': '\n\n⚠️⚠️⚠️ <b>КЛИЕНТ БЕЗ СТОЛА!</b>\n❗ <b>ТРЕБУЕТСЯ ПОДТВЕРЖДЕНИЕ НА МЕСТЕ!</b> ⚠️⚠️⚠️',
        'kj_order_approved_client': '✅ <b>Ваш заказ #{order_id} принят!</b>\n\n🎵 <b>{song}</b>\n📍 Позиция в очереди: <b>#{pos}</b>\n\nОжидайте своей очереди...',
        'kj_order_rejected_client': '❌ Ваш заказ <b>#{order_id}</b> отклонён\n🎵 <b>{song}</b>{refund_text}\n\nВы можете выбрать другую песню',
        'kj_refund_line': '\n💰 Возврат на баланс: <b>{amount} MDL</b>',
        'order_refund': '💰 Возврат на баланс: <b>{amount} MDL</b>',
        'kj_order_completed_client': '✅ Ваша песня выполнена: <b>{song}</b>\n💰 Кешбек: <b>{cashback}</b>',
        'order_deleted_refund': '❌ Ваш заказ <b>#{order_id}</b> удалён\n🎵 <b>{song}</b>\n💰 Возврат на баланс: <b>{refund} MDL</b>',
        'vip_approved': '✅ Ваш VIP статус подтверждён! Используйте /vip для входа в VIP меню.',
        'vip_rejected': '❌ Запрос на VIP статус отклонён.',
        'kj_chat_message': '💬 <b>Сообщение от KJ</b>\n\n{text}',
        'kj_topup_request': (
            '💰 *ЗАПРОС НА ПОПОЛНЕНИЕ БАЛАНСА*\n\n'
            '🪑 Стол *{table}*\n'
            '👤 *{name}* (@{username})\n'
            '💵 Сумма: *{amount} MDL*\n\n'
            'Подтвердите пополнение баланса:'
        ),
        'kj_topup_approved': '✅ Ваш запрос на пополнение баланса подтвержден!\nПополнено: *{amount} MDL*\nНовый баланс: *{balance} MDL*',
        'kj_topup_rejected': '❌ Ваш запрос на пополнение *{amount} MDL* отклонён.',
        'kj_table_label': '🪑 Стол: <b>{table}</b>',
        'kj_no_table_label': '🪑 Клиент без стола (#{num})',
        'btn_order_cancel': '❌ Отменить',
        'btn_order_approve': '✅ Принять',
        'btn_approve': '✅ Принять',
        'btn_topup_approve': '✅ Подтвердить',
        'btn_topup_reject': '❌ Отменить',

        'vip_request_to_kj': '⭐ *ЗАЯВКА VIP*\n\n🪑 Стол *{table}*\n👤 *{name}* (@{username})\n\nКлиент хочет получить VIP статус.',
        'btn_vip_approve': '✅ Подтвердить VIP',
        'btn_vip_reject': '❌ Отклонить',

        'table_join_approved_client': '✅ Вас добавили к столу {table}!\n\nИспользуйте /client для доступа к меню.',
        'table_join_rejected_client': '❌ Ваш запрос на присоединение к столу {table} отклонён.',
        'table_group_title': '👥 *УПРАВЛЕНИЕ СТОЛОМ*\n\n🪑 Стол: *{table}*\n👑 Вы главный стола\n\nУчастники ({count}/{max}):',
        'table_group_no_other_members': 'Только вы',
        'table_group_kick': '🚪 Выгнать',
        'table_group_leave': '🚪 Покинуть стол',
        'table_group_leave_confirm': '⚠️ Вы хотите покинуть стол?',
        'table_kick_confirm': '⚠️ Выгнать {name} со стола?',
        'table_kick_done': '✅ {name} выгнан(а) со стола',
        'table_leave_done': '✅ Вы покинули стол',

        'tables_0': 'столов',
        'tables_1': 'стол',
        'tables_2_4': 'стола',
        'tables_other': 'столов',

        'no_client_access': '❌ У вас нет доступа. Используйте /client',
        'select_club_notable': '🏢 Выберите клуб:',
        'no_venues_available': '❌ Нет доступных клубов',
        'notable_venue_selected': '✅ Вы выбрали клуб: {venue}\nВаш виртуальный номер: {num}\n\nИспользуйте /notable или /client для доступа к меню',

        'admin_panel_main': (
            '👑 *Администратор системы*\n\n'
            'Клубов: *{clubs}* | Активных: *{active}*\n'
            'Выручка сегодня: *{revenue}*'
        ),
        'admin_no_rights': '❌ У вас нет прав администратора',
        'admin_not_main_admin': '❌ Эта команда доступна только главному администратору',
        'admin_venues_title': '🏢 *Управление клубами* | Всего: *{total}*\n\n',
        'admin_venues_empty': '🏢 *Управление клубами*\n\nКлубов пока нет',
        'admin_venue_status_online': '🟢 Онлайн',
        'admin_venue_status_blocked': '🔴 Заблокирован',
        'admin_add_venue_title': '🏢 *ДОБАВЛЕНИЕ НОВОГО КЛУБА*\n\nВведите название клуба:',
        'admin_enter_city': 'Введите город:',
        'admin_enter_phone': 'Телефон владельца:',
        'admin_enter_email': 'Email владельца:',
        'admin_venue_created': "✅ Клуб '{name}' создан! ID: {vid}\nНазначьте KJ для активации.",
        'admin_choose_venue': '📋 Выберите клуб:',
        'admin_venue_details': (
            '🏢 *ДЕТАЛИ КЛУБА: {name} (ID:{vid})*\n\n'
            'Статус: *{status}*\n'
            'KJ: *{kj}*\n'
            'Создан: *{created}*\n'
            'Столов: *{tables}*\n'
            '🎵 Песен в базе: *{songs}*\n'
            'Выручка сегодня: *{revenue}*\n'
            'Город: *{city}*\n'
            'Телефон: *{phone}*\n'
            'Email: *{email}*'
        ),
        'admin_venue_active_status': '🟢 Активен',
        'admin_venue_finance': (
            '💰 *ФИНАНСЫ: {name}*\n\n'
            '📅 *За сегодня:*\n'
            'Выручка: *{today}*\n\n'
            '📆 *За неделю:*\n'
            'Выручка: *{week}*\n\n'
            '📈 *За месяц:*\n'
            'Выручка: *{month}*\n'
            'Кешбек админу (5%): *{admin_fee}*\n'
        ),
        'admin_venue_songs': (
            '🎵 *УПРАВЛЕНИЕ ПЕСНЯМИ: {name}*\n\n'
            'Всего песен в базе: *{count}*\n\n'
            "Для импорта новых песен используйте функцию\n'Импорт CSV базы' в меню KJ."
        ),
        'admin_edit_name_prompt': 'Текущее название: *{name}*\n\nВведите новое название:',
        'admin_name_changed': '✅ Название клуба изменено на: *{name}*',
        'admin_unbind_tables_confirm': (
            '⚠️ *ОТВЯЗАТЬ ВСЕХ ОТ СТОЛОВ*\n\n'
            'Заведение: *{venue}*\n'
            'За столами сейчас: *{count} чел.*\n\n'
            'Все пользователи будут отвязаны от столов\n'
            '(останутся привязаны к заведению)\n\n'
            'Подтвердить?'
        ),
        'admin_unbind_tables_done': (
            '✅ Все пользователи отвязаны от столов\n\n'
            'Заведение: *{venue}*\n'
            'Отвязано: *{count} чел.*'
        ),
        'admin_unbind_venue_confirm': (
            '⚠️ *ОТВЯЗАТЬ ВСЕХ ОТ ЗАВЕДЕНИЯ*\n\n'
            'Заведение: *{venue}*\n'
            'Привязано пользователей: *{count} чел.*\n\n'
            'ВСЕ пользователи будут полностью отвязаны от заведения\n\n'
            'Подтвердить?'
        ),
        'admin_unbind_venue_done': (
            '✅ Все пользователи отвязаны от заведения\n\n'
            'Заведение: *{venue}*\n'
            'Отвязано: *{count} чел.*'
        ),
        'admin_venue_contacts_header': '📞 *КОНТАКТЫ КЛУБОВ*\n\n',
        'admin_venue_contacts_empty': 'Клубов пока нет',
        'admin_venue_block_select': '🚫 Выберите клуб для изменения статуса:',
        'admin_venue_delete_select': '🗑️ Выберите клуб для удаления:',
        'admin_venue_toggle_block_confirm': '⚠️ Заблокировать клуб *{name}*?',
        'admin_venue_toggle_unblock_confirm': '⚠️ Разблокировать клуб *{name}*?',
        'admin_kj_list_header': '👥 <b>УПРАВЛЕНИЕ KJ ОПЕРАТОРАМИ</b> | Всего: <b>{total}</b>\n\n',
        'admin_kj_list_empty': 'KJ операторов пока нет',
        'admin_kj_blocked_status': '🔴 Заблокирован',
        'admin_kj_remove_select': '➖ Выберите KJ для снятия:',
        'admin_kj_assign_title': '➕ *НАЗНАЧЕНИЕ KJ*\n\nВыберите клуб:',
        'admin_kj_enter_username': '👥 *НАЗНАЧЕНИЕ KJ ДЛЯ КЛУБА*\n\nВведите Telegram username нового KJ (например: @username):',
        'admin_kj_not_found': '❌ Пользователь @{username} не найден в базе.\nПользователь должен сначала запустить бота командой /start',
        'admin_kj_cant_be_admin': '❌ Нельзя назначить главного администратора на роль KJ',
        'admin_kj_assigned': '✅ Пользователь @{username} назначен KJ\n🏢 Клуб: *{venue}*\n\nУведомление отправлено пользователю.',
        'admin_kj_assigned_no_notify': '✅ Пользователь @{username} назначен KJ\n🏢 Клуб: *{venue}*\n\n⚠️ Не удалось отправить уведомление (пользователь заблокировал бота)',
        'admin_kj_welcome': '🎵 *ПОЗДРАВЛЯЕМ!*\n\nВы назначены KJ оператором заведения:\n🏢 *{venue}*\n📍 *{city}*',
        'admin_kj_remove_confirm': '⚠️ Снять @{username} с должности KJ?',
        'admin_kj_stats_header': '📋 *СТАТИСТИКА РАБОТЫ KJ*\n\n',
        'admin_kj_contacts_header': '📞 *КОНТАКТЫ KJ ОПЕРАТОРОВ*\n\n',
        'admin_kj_contacts_empty': 'KJ операторов пока нет',
        'admin_kj_select_toggle': '🚫 Выберите KJ для изменения статуса:',
        'admin_reports_header': '📊 *ФИНАНСОВЫЕ ОТЧЁТЫ*\n\nСегодня: *{today}*\nМесяц: (в разработке)',
        'admin_report_today_title': '📊 *ОТЧЁТ ЗА {date}*\n\n',
        'admin_report_revenue_total': '*ВЫРУЧКА:* *{revenue}*\n',
        'admin_report_orders_total': '*ЗАКАЗОВ:* *{count}*\n',
        'admin_report_commission': '*Комиссия админу (5%):* *{amount}*\n',
        'admin_report_week_title': '📆 *ОТЧЁТ ЗА НЕДЕЛЮ*\n\n',
        'admin_report_week_revenue': '*ВЫРУЧКА ЗА НЕДЕЛЮ:* *{revenue}*\n',
        'admin_report_month_title': '📈 *ОТЧЁТ ЗА МЕСЯЦ*\n\n',
        'admin_report_month_revenue': '*ВЫРУЧКА ЗА МЕСЯЦ:* *{revenue}*\n',
        'admin_report_venues_title': '🏢 *СРАВНИТЕЛЬНЫЙ ОТЧЁТ ПО КЛУБАМ*\n\n',
        'admin_report_cashback_title': '💸 *КЕШБЭК ОТ KJ АДМИНУ*\n\n',
        'admin_report_export_title': '📤 *ЭКСПОРТ ДАННЫХ*\n\nВыберите формат экспорта:',
        'admin_system_header': (
            '⚙️ *СИСТЕМНЫЕ НАСТРОЙКИ БОТА*\n\n'
            'Статус бота: 🟢 Работает\n'
            'Клубов: *{clubs}*\n'
            'KJ операторов: *{kj}*\n'
            'Всего пользователей: *{users}*\n'
            'Последнее обновление: *{time}*'
        ),
        'admin_support_header': (
            '🛠️ *ТЕХНИЧЕСКАЯ ПОДДЕРЖКА*\n\n'
            '*Статус:* 🟢 Работает\n'
            '*Использование памяти:* {memory} МБ\n'
            '*CPU:* {cpu}%\n'
            '*Время работы:* {time}\n\n'
            '*База данных:* SQLite\n'
            '*Путь:* {db_path}\n'
        ),
        'admin_support_db_size': '*Размер БД:* {size} МБ\n',
        'admin_support_db_na': '*Размер БД:* Н/Д\n',
        'admin_logs_header': '📝 *ЖУРНАЛ ДЕЙСТВИЙ*\n\nПоследние 20 транзакций:\n\n',
        'admin_logs_empty': 'Журнал пуст',
        'admin_restart_confirm': (
            '🔄 *ПЕРЕЗАПУСК БОТА*\n\n'
            '⚠️ Вы уверены, что хотите перезапустить бота?\n'
            'Это прервёт все текущие операции.'
        ),
        'admin_restarting': '🔄 Перезапуск бота...\n\nБот будет перезапущен вручную.',
        'admin_set_admin_prompt': (
            '👑 *НАЗНАЧЕНИЕ АДМИНИСТРАТОРА*\n\n'
            'Введите Telegram ID или username пользователя, которого хотите сделать администратором:\n\n'
            'Например:\n'
            '• 123456789\n'
            '• @username'
        ),
        'admin_unset_admin_prompt': (
            '👤 *СНЯТИЕ ПРАВ АДМИНИСТРАТОРА*\n\n'
            'Введите Telegram ID или username администратора, которого хотите разжаловать:\n\n'
            'Например:\n'
            '• 123456789\n'
            '• @username'
        ),
        'admin_invalid_identifier': '❌ Неверный формат. Введите Telegram ID (123456789) или username (@username):',
        'admin_user_not_found': '❌ Пользователь не найден в базе данных.\nПользователь должен сначала запустить бота командой /start',
        'admin_already_admin': 'ℹ️ Пользователь {name} (@{username}) уже является администратором',
        'admin_set_done': '✅ Пользователь {name} (@{username}) назначен администратором!\nID: {uid}',
        'admin_cant_unset_main': '❌ Нельзя снять права главного администратора',
        'admin_not_admin_user': 'ℹ️ Пользователь {name} (@{username}) не является администратором',
        'admin_unset_done': '✅ Права администратора сняты с пользователя {name} (@{username})\nID: {uid}',
        'admin_new_admin_notify': '👑 *ПОЗДРАВЛЯЕМ!*\n\nВам назначены права администратора системы.\nИспользуйте /admin для доступа к панели управления.',
        'admin_admin_revoked_notify': 'ℹ️ Ваши права администратора были отозваны.\nТеперь у вас роль обычного пользователя.',
        'btn_admin_clubs': '🏢 Клубы',
        'btn_admin_kj': '👥 KJ операторы',
        'btn_admin_reports': '📊 Отчёты',
        'btn_admin_system': '⚙️ Система',
        'btn_admin_refresh': '🔄 Обновить',
        'btn_venue_add': '➕ Добавить клуб',
        'btn_venue_detailed': '📋 Подробно',
        'btn_venue_block_toggle': '🚫 Блокировать/Разблокировать',
        'btn_venue_delete': '🗑️ Удалить клуб',
        'btn_venue_contacts_btn': '📞 Контакты',
        'btn_edit_venue_name': '✏️ Изменить название',
        'btn_venue_assign_kj': '👥 Назначить/Сменить KJ',
        'btn_venue_finance': '📊 Финансы клуба',
        'btn_venue_songs_btn': '🎵 Управление песнями',
        'btn_venue_qr': '📱 QR код клуба',
        'btn_unbind_tables': '🪑 Отвязать все столы',
        'btn_unbind_venue': '🚪 Отвязать всех от заведения',
        'btn_venue_refresh': '🔄 Обновить данные',
        'btn_kj_assign_new': '➕ Назначить нового KJ',
        'btn_kj_remove': '➖ Снять KJ',
        'btn_kj_work_stats': '📋 Статистика работы',
        'btn_kj_contacts': '📞 Контакты всех KJ',
        'btn_kj_block_toggle': '🚫 Блокировка/Разблокировка',
        'btn_report_today': '📅 За сегодня',
        'btn_report_week': '📆 За неделю',
        'btn_report_month': '📈 За месяц',
        'btn_report_venues': '🏢 По клубам',
        'btn_report_cashback': '💸 Кешбэк от KJ',
        'btn_export_data': '📤 Экспорт данных',
        'btn_sys_support': '🛠️ Техническая поддержка',
        'btn_sys_logs': '📝 Журнал действий',
        'btn_sys_backup': '💾 Резервное копирование',
        'btn_sys_restart': '🔄 Перезапуск бота',
        'admin_venue_qr_caption': '📱 Отсканируйте QR — бот предложит выбрать стол.\nСтолов: *{tables}*',
        'admin_backup_caption': '💾 Резервная копия базы данных\n{time}',
        'admin_backup_done': '✅ Резервная копия создана и отправлена',
        'admin_backup_error': '❌ Ошибка создания копии: {error}',
        'admin_restart_manual': '⚠️ Перезапустите бота вручную в терминале',
        'admin_csv_col_club': 'Клуб',
        'admin_csv_col_city': 'Город',
        'admin_csv_col_revenue_today': 'Выручка сегодня',
        'admin_csv_col_revenue_week': 'Выручка за неделю',
        'admin_csv_col_revenue_month': 'Выручка за месяц',
        'admin_csv_col_status': 'Статус',
        'admin_csv_status_active': 'Активен',
        'admin_csv_status_blocked': 'Заблокирован',
        'admin_csv_caption': '📊 Отчёт в формате CSV',
        'admin_csv_sent': '✅ Файл отправлен',
        'admin_excel_soon': '📈 Экспорт в Excel будет добавлен позже',

        'kj_panel_title': '🎵 <b>KJ панель</b>\n\n🏢 Заведение: <b>{venue}</b>\n🌐 Город: <b>{city}</b>',
        'kj_no_rights': '❌ У вас нет прав KJ оператора',
        'kj_no_venue': '❌ Вы не привязаны к заведению',
        'btn_kj_club_settings': '⚙️ Настройка клуба',
        'btn_kj_work_evening': '🎵 Работа в течение вечера',

        'kj_settings_warn_text': (
            '⚙️ <b>НАСТРОЙКИ КЛУБА</b>\n\n'
            '⚠️ Вы переходите в раздел настроек клуба.\n'
            'Изменения вступают в силу немедленно.\n\n'
            'Подтвердить вход?'
        ),
        'kj_settings_title': (
            '⚙️ <b>НАСТРОЙКИ КЛУБА</b>\n\n'
            '🏢 Заведение: <b>{venue}</b>\n'
            '📌 Лимит столов: <b>{table_count}</b>\n'
            '🎵 Лимит песен на гостя: <b>{songs_limit}</b>'
        ),
        'btn_kj_import_csv': '📁 Импорт базы',
        'btn_kj_services': '💼 Услуги и цены',
        'btn_kj_tables_settings': '🪑 Столы',
        'btn_kj_clients': '👥 Клиенты',
        'btn_kj_vip_settings': '⭐ Настройка VIP',
        'btn_kj_chat_on': '✅ Чат: вкл.',
        'btn_kj_chat_off': '💬 Чат: выкл.',
        'btn_kj_chat_link_change': '🔗 Изменить ссылку чата',
        'btn_kj_free_evening': '🎁 Бесплатный Вечер',

        'kj_import_csv_title': (
            '📁 *ИМПОРТ CSV БАЗЫ*\n\n'
            'Отправьте CSV файл с песнями.\n'
            'Формат: artist,title,code\n\n'
            'Пример:\n'
            'Imagine Dragons,Believer,ID123\n'
            'The Beatles,Yesterday,BT456'
        ),
        'kj_csv_format_error': '❌ Файл должен быть в формате CSV',

        'kj_services_title': '💼 <b>УСЛУГИ И ЦЕНЫ</b>\n\n',
        'kj_services_empty': 'Услуг пока нет',
        'btn_kj_service_add': '➕ Добавить услугу',
        'btn_kj_service_edit': '📝 Редактировать услугу',
        'btn_kj_service_delete': '🗑️ Удалить услугу',
        'kj_service_add_title': '➕ *ДОБАВЛЕНИЕ УСЛУГИ*\n\nВведите название услуги:',
        'kj_service_add_desc_prompt': 'Введите описание услуги:',
        'kj_service_add_price_prompt': 'Введите цену услуги (число):',
        'kj_service_created': "✅ Услуга '{name}' создана!",
        'kj_service_price_invalid': '❌ Неверный формат цены. Введите число:',
        'kj_service_none': '❌ Услуг нет',
        'kj_service_edit_choose': '📝 Выберите услугу для редактирования:',
        'kj_service_edit_title': (
            '📝 <b>РЕДАКТИРОВАНИЕ УСЛУГИ</b>\n\n'
            'Текущие данные:\n'
            'Название: <b>{name}</b>\n'
            'Описание: <b>{desc}</b>\n'
            'Цена: <b>{price} MDL</b>\n\n'
            'Введите новое название (или /skip для пропуска):'
        ),
        'kj_service_edit_desc_prompt': 'Введите новое описание (или /skip для пропуска):',
        'kj_service_edit_price_prompt': 'Введите новую цену (или /skip для пропуска):',
        'kj_service_updated': '✅ Услуга обновлена!',
        'kj_service_no_changes': 'Изменения не внесены',
        'kj_service_delete_choose': '🗑️ Выберите услугу для удаления:',
        'kj_service_deleted': '✅ Услуга удалена',
        'kj_service_not_found': '❌ Услуга не найдена',

        'kj_tables_title': (
            '🪑 *УПРАВЛЕНИЕ СТОЛАМИ*\n\n'
            '🔹 Количество столов: *{count}*\n'
            '🔹 Лимит песен на гостя: *{songs}*\n'
            '🔹 Режим нумерации: *{mode}*'
        ),
        'kj_table_mode_sequential': 'Последовательный',
        'kj_table_mode_by_order': 'По мере заказов',
        'btn_kj_tables_count': '🔢 Количество столов',
        'btn_kj_tables_songs': '🎵 Песен на стол',
        'btn_kj_tables_mode': '🔄 Режим нумерации',
        'btn_kj_tables_unbind_all': '🪑 Отвязать все столы',
        'kj_tables_edit_title': '⚙️ <b>РЕДАКТИРОВАНИЕ СТОЛОВ</b>\n\nВыберите параметр:',
        'btn_kj_tables_unbind_venue': '🚪 Отвязать всех от заведения',
        'kj_tables_count_prompt': '🔢 Введите новое количество столов\n(текущее: {current}):',
        'kj_tables_songs_prompt': '🎵 Функция в разработке',
        'kj_tables_setting_saved': '✅ Сохранено: {value}',
        'kj_tables_mode_choose': '🔄 *РЕЖИМ НУМЕРАЦИИ*\n\nВыберите режим очереди:',
        'kj_tables_mode_changed': '✅ Режим изменён: *{mode}*',
        'kj_tables_count_invalid': '❌ Введите положительное целое число:',
        'kj_unbind_tables_confirm_text': '⚠️ Отвязать все текущие столы? Все сессии будут завершены.',
        'kj_unbind_venue_confirm_text': '⚠️ Отвязать всех клиентов от заведения? Все сессии будут завершены.',
        'kj_unbind_tables_done': '✅ Все столы отвязаны',
        'kj_unbind_venue_done': '✅ Все клиенты отвязаны от заведения',

        'kj_vip_settings_title': '⭐ *НАСТРОЙКИ VIP*',
        'btn_kj_vip_add': '➕ Добавить VIP',
        'btn_kj_vip_cashback': '💰 Настройка кешбека',
        'btn_kj_vip_description': '📝 Описание VIP (RU)',
        'btn_kj_vip_description_ro': '📝 Описание VIP (RO)',
        'kj_vip_cashback_title': (
            '💰 *НАСТРОЙКА КЕШБЕКА VIP*\n\n'
            'Текущий процент кешбека: *{current}%*\n\n'
            'Введите новый процент кешбека для VIP клиентов\n'
            '(например: 5 для 5%):'
        ),
        'kj_vip_cashback_saved': '✅ Процент кешбека для VIP установлен: *{value}%*',
        'kj_vip_cashback_invalid': '❌ Процент должен быть от 0 до 100',
        'kj_vip_cashback_format_error': '❌ Неверный формат. Введите число:',
        'kj_vip_desc_title': (
            '📝 *ОПИСАНИЕ ПРЕИМУЩЕСТВ VIP*\n\n'
            'Текущее описание:\n*{current}*\n\n'
            'Введите новое описание преимуществ VIP статуса:'
        ),
        'kj_vip_desc_saved': '✅ Описание VIP статуса обновлено!',
        'kj_vip_desc_ro_title': (
            '📝 *ОПИСАНИЕ VIP (RO)*\n\n'
            'Текущее описание на румынском:\n*{current}*\n\n'
            'Введите новое описание на румынском языке:'
        ),
        'kj_vip_desc_ro_saved': '✅ Румынское описание VIP сохранено!',
        'kj_vip_add_title': '➕ *ДОБАВЛЕНИЕ VIP*\n\nВведите Telegram ID пользователя:',
        'kj_vip_add_cashback_prompt': 'Введите процент кешбека (например: 5):',
        'kj_vip_added': '✅ VIP статус выдан пользователю {name}!',
        'kj_vip_user_not_found': '❌ Пользователь не найден в базе',
        'kj_vip_id_invalid': '❌ Неверный формат ID. Введите число:',
        'kj_vip_cashback_format': '❌ Неверный формат. Введите число:',
        'btn_kj_venue_not_found': '❌ Клуб не найден',

        'kj_clients_title': '👥 *КЛИЕНТЫ*\n\nВыберите действие:',
        'btn_kj_client_search': '🔍 Поиск по ID',
        'btn_kj_client_bind': '🔗 Привязка клиента',
        'btn_kj_client_referrals': '📋 Показать всех рефералов',
        'kj_client_search_prompt': '🔍 *ПОИСК КЛИЕНТА*\n\nВведите Telegram ID клиента:',
        'kj_client_not_found': '❌ Клиент не найден',
        'kj_client_id_invalid': '❌ Неверный формат ID',
        'kj_client_status_vip': 'VIP',
        'kj_client_status_regular': 'Обычный',
        'kj_client_none_label': 'нет',
        'kj_client_info': (
            '👤 <b>КЛИЕНТ</b>\n\n'
            'ID: <b>{uid}</b>\n'
            'Имя: <b>{name}</b>\n'
            'Username: <b>@{username}</b>\n'
            'Статус: <b>{status}</b>\n'
            'Стол: <b>{table}</b>\n'
            'Баланс: <b>{balance} MDL</b>\n'
            'Комиссия: <b>{commission}%</b>\n'
            'Заблокирован: <b>{blocked}</b>'
        ),
        'kj_no_referrals': 'Рефералов нет',
        'kj_referrals_title': '📋 <b>РЕФЕРАЛЫ</b>\n\n',
        'kj_referral_item': '{n}. {name} (@{username}) — ID: {uid}',
        'kj_clients_list_title': '📋 <b>СПИСОК КЛИЕНТОВ</b> — {label}\n\nВсего: <b>{total}</b>\n\n',
        'kj_clients_filter_all': '📋 Все',
        'kj_clients_filter_vip': '⭐ VIP',
        'kj_clients_filter_regular': '👤 Обычные',
        'kj_clients_empty': 'Клиентов пока нет',
        'kj_clients_more': '... и ещё <b>{count}</b> клиентов',
        'kj_client_orders_spent': 'Заказов: <b>{orders}</b> | Потрачено: <b>{spent}</b>',

        'btn_kj_client_balance': '💰 Баланс',
        'btn_kj_client_unbind_table': '🔓 Отвязать от стола',
        'btn_kj_client_unbind_venue': '🚪 Отвязать от заведения',
        'btn_kj_client_block': '🔒 Заблокировать',
        'btn_kj_client_unblock': '🔓 Разблокировать',
        'btn_kj_client_commission': '📊 Настройки % комиссии',
        'btn_kj_client_chat': '💬 Начать диалог',
        'btn_kj_client_delete': '🗑️ Удалить из базы',
        'btn_kj_bind_info': '📋 Информация о привязке',

        'kj_balance_title': '💰 <b>УПРАВЛЕНИЕ БАЛАНСОМ</b>\n\n👤 {name}\nТекущий баланс: <b>{balance} MDL</b>',
        'btn_kj_balance_add': '➕ Начислить',
        'btn_kj_balance_sub': '➖ Списать',
        'btn_kj_balance_set': '🔄 Установить',
        'kj_balance_add_prompt': 'Введите сумму для начисления:',
        'kj_balance_sub_prompt': 'Введите сумму для списания:',
        'kj_balance_set_prompt': 'Введите новое значение баланса:',
        'kj_balance_result': '✅ Баланс {name}:\n{old} MDL → {new} MDL',
        'kj_balance_invalid': '❌ Неверная сумма. Введите число:',

        'kj_commission_title': (
            '📊 <b>КОМИССИЯ КЛИЕНТА</b>\n\n'
            '👤 {name}\n'
            'Текущая комиссия: <b>{current}%</b>\n\n'
            'Введите новый процент комиссии (0–100):'
        ),
        'kj_commission_saved': '✅ Комиссия установлена: {value}%',
        'kj_commission_invalid': '❌ Процент должен быть от 0 до 100',
        'kj_commission_format': '❌ Неверный формат. Введите число:',

        'kj_client_blocked': '✅ Клиент {name} заблокирован',
        'kj_client_unblocked': '✅ Клиент {name} разблокирован',
        'kj_client_unbound_table': '✅ Клиент {name} отвязан от стола',
        'kj_client_unbound_venue': '✅ Клиент {name} отвязан от заведения',
        'kj_client_delete_confirm_text': '🗑️ Подтвердите удаление клиента <b>{name}</b> из базы данных.\nДействие необратимо!',
        'kj_client_deleted': '✅ Клиент {name} удалён из базы',

        'kj_chat_toggle_enabled': '✅ Чат с клиентами включён',
        'kj_chat_toggle_disabled': '❌ Чат с клиентами отключён',
        'kj_chat_link_prompt': '🔗 Введите ссылку на общий чат клуба\n(должна начинаться с https://t.me/):',
        'kj_chat_link_saved': '✅ Ссылка на чат сохранена',
        'kj_chat_link_invalid': '❌ Ссылка должна начинаться с https://t.me/',
        'kj_chat_change_link_prompt': '🔗 Введите новую ссылку на чат\n(должна начинаться с https://t.me/):',
        'kj_chat_with_client': '💬 <b>ЧАТ С КЛИЕНТОМ</b>\n\n👤 {name}\n\nВведите сообщение:',
        'kj_message_sent': '✅ Сообщение отправлено',
        'kj_message_failed': '❌ Не удалось отправить сообщение',
        'kj_chat_reply_prompt': '✏️ Введите ответ клиенту {name}:',

        'kj_free_title': '🎁 <b>БЕСПЛАТНЫЙ ВЕЧЕР</b>\n\n',
        'kj_free_label_free': 'бесплатной',
        'kj_free_label_paid': 'платной',
        'kj_free_service_line_free': '🟢 {name} — Бесплатно',
        'kj_free_service_line_paid': '🔴 {name} — {price} MDL',
        'kj_free_toggle_to_free': '🆓 Сделать бесплатной',
        'kj_free_toggle_to_paid': '💰 Сделать платной',
        'kj_free_toggled_to_free': '✅ Услуга «{name}» теперь бесплатная',
        'kj_free_toggled_to_paid': '✅ Услуга «{name}» снова платная ({price} MDL)',
        'kj_free_service_not_found': '❌ Услуга не найдена',
        'kj_free_empty': 'Услуг пока нет',

        'kj_work_title': '🎵 <b>РАБОТА В ТЕЧЕНИЕ ВЕЧЕРА</b>\n\nВыберите действие:',
        'btn_kj_queue': '📋 Управление очередью',
        'btn_kj_global_queue': '📋 Общая очередь',
        'btn_kj_stats': '📊 Статистика вечера',

        'kj_global_queue_title': '📋 <b>ОБЩАЯ ОЧЕРЕДЬ</b>',
        'kj_queue_no_table_label': 'Без стола (#{num})',
        'kj_queue_table_label': 'Стол {num}',
        'kj_queue_now_header': '▶️ <b>СЕЙЧАС:</b>',
        'kj_queue_vne_header': '⏸ <b>ВНЕ ОЧЕРЕДИ:</b>',
        'kj_queue_circle_header': '🔄 <b>Очередь круга</b>',
        'kj_queue_empty': 'Очередь пуста',
        'btn_kj_refresh_queue': '🔄 Обновить',
        'kj_table_header_virtual': '📋 <b>БЕЗ СТОЛА #{num}</b> {status}',
        'kj_table_header': '📋 <b>СТОЛ {num}</b> {status}',
        'kj_table_status_active': '🟢',
        'kj_table_status_free': '⚪',
        'kj_order_next_marker': ' ⏭ СЛЕДУЮЩАЯ',
        'kj_order_waiting_status': 'Ожидает подтверждения',
        'btn_kj_close_table': '🔒 Закрыть стол',
        'btn_kj_close_table_virtual': '🔒 Закрыть сессию',
        'btn_kj_add_order': '➕ Добавить заказ',
        'kj_order_set_next': '✅ Следующим',
        'kj_order_cleared_next': '✅ Убрано из следующих',
        'kj_next_song_ready': '🎶 Ваша песня поставлена следующей, готовьтесь!',

        'kj_table_close_title': '🔒 <b>ЗАКРЫТИЕ СТОЛА {num}</b>',
        'kj_table_close_songs': 'Исполнено песен: <b>{count}</b>',
        'kj_table_close_total': 'Итого: <b>{total} MDL</b>',
        'kj_table_close_free': 'Бесплатный вечер',
        'kj_receipt_title': '🧾 <b>ВАШ ЧЕК</b>',
        'kj_receipt_item': '{n}. {song} — {price}',
        'kj_session_ended_receipt': '🎶 Ваша сессия завершена!\n\n{receipt}',
        'kj_session_ended_simple': '🎶 Ваша сессия завершена! Спасибо за посещение!',
        'kj_queue_manage_title': '📋 <b>УПРАВЛЕНИЕ ОЧЕРЕДЬЮ</b>\n\nВыберите стол:',

        'kj_stats_title': '📊 <b>СТАТИСТИКА ВЕЧЕРА</b>',
        'kj_stats_no_data': 'Нет данных за сегодня',

        'kj_vip_confirm_done': '✅ VIP статус выдан',
        'kj_vip_reject_done': '❌ VIP запрос отклонён',
        'kj_topup_confirm_done': '✅ Пополнение подтверждено',
        'kj_topup_reject_done': '❌ Пополнение отклонено',
        'kj_order_approved_kj': '✅ Заказ принят',
        'kj_order_rejected_kj': '❌ Заказ отклонён',
        'kj_order_completed_kj': '✅ Заказ выполнен',
        'kj_order_deleted_kj': '🗑️ Заказ удалён',
        'kj_order_complete_confirm': '✅ Подтвердить выполнение заказа #{order_id}?',
        'kj_order_delete_confirm': '🗑️ Удалить заказ #{order_id}?\nБаланс клиента будет возвращён.',
        'kj_table_closed_alert': '✅ Стол закрыт',
        'kj_order_already_processed': '❌ Заказ уже обработан',
        'btn_kj_order_complete': '✅ Выполнен',
        'btn_kj_order_delete': '❌ Удалить',
        'btn_kj_order_replace': '🔄 Заменить',

        'kj_add_order_title': '➕ *ДОБАВЛЕНИЕ ЗАКАЗА*\n\nСтол: {table}\n\nНажмите кнопку, чтобы найти песню:',
        'kj_choose_service_title': '🎵 *ВЫБОР УСЛУГИ*\n\nПесня: *{song}*\nСтол: *{table}*\n\nВыберите услугу:',
        'kj_confirm_order_title': (
            '✅ *ПОДТВЕРЖДЕНИЕ*\n\n'
            'Стол: *{table}*\n'
            'Песня: *{song}*\n'
            'Услуга: *{service}*\n'
            'Цена: *{price}*'
        ),
        'kj_order_added': '✅ Заказ добавлен',
        'kj_song_not_found': '❌ Песня не найдена',
        'kj_order_not_found': '❌ Заказ не найден',
        'kj_replace_order_title': '🔄 *ЗАМЕНА ПЕСНИ*\n\nНажмите \'🔍 Найти песню\' для поиска новой песни.',
        'kj_song_replaced': '✅ Песня заменена',
        'btn_kj_find_song': '🔍 Найти песню',
        'kj_move_order_title': (
            '⬆️ *ПЕРЕМЕЩЕНИЕ ЗАКАЗА*\n\n'
            '🎵 Песня: *{song}*\n'
            'Текущая позиция: *{pos}* из *{count}*\n\n'
            'Введите новую позицию (1-*{count}*):\n\n'
            '_Нажмите Enter или кнопку \'Подтвердить\' после ввода_'
        ),
        'kj_move_position_invalid': '❌ Введите число больше 0',
        'kj_move_max_exceeded': '❌ Позиция не может быть больше {count}',
        'kj_move_no_orders': '❌ Нет заказов для перемещения',
        'kj_move_choose': '⬆️ *ВЫБЕРИТЕ ЗАКАЗ ДЛЯ ПЕРЕМЕЩЕНИЯ*\n\n',
        'kj_order_moved': '✅ Заказ перемещён',
        'btn_kj_search_song': '🔍 Найти песню',

        'kj_not_vip': '❌ Клиент не является VIP',
        'kj_bind_info_text': '📋 <b>ПРИВЯЗКА КЛИЕНТОВ</b>\n\nКлиенты привязываются к заведению автоматически при первом заказе.\n\nПосле привязки вы можете:\n• Управлять балансом\n• Выдавать VIP-статус\n• Блокировать клиентов\n• Начать личный чат',
        'kj_songs_not_found': '❌ Песни не найдены.\n\nПопробуйте другой запрос:',
        'kj_search_results_title': '🔍 *РЕЗУЛЬТАТЫ ПОИСКА*\n\nНайдено песен: *{count}*\n\n',
    },

    'ro': {
        'btn_back': '↩️ Înapoi',
        'btn_cancel': '❌ Anulare',
        'btn_confirm': '✅ Confirmare',
        'btn_reject': '❌ Respingere',
        'btn_yes': '✅ Da',
        'btn_no': '❌ Nu',
        'btn_free': 'Gratuit',
        'error_not_found': '❌ Nu a fost găsit',
        'error_no_rights': '❌ Nu aveți drepturi',
        'error_data': '❌ Eroare de date',
        'action_cancelled': '❌ Anulat',
        'choose_action': 'Alegeți acțiunea:',

        'menu_btn': '🎵 Meniu',
        'lang_btn': '🌐 Limbă',

        'lang_title': '🌐 *SELECTARE LIMBĂ*\n\nAlegeți limba interfeței:',
        'lang_ru': '🇷🇺 Русский',
        'lang_ro': '🇷🇴 Română',
        'lang_changed_ru': '✅ Язык изменён на Русский',
        'lang_changed_ro': '✅ Limba schimbată la Română',

        'blocked_user': '🚫 Ați fost blocat. Contactați KJ sau administratorul.',
        'start_first': '❌ Mai întâi lansați botul cu comanda /start',
        'session_ended': '🎶 Sesiunea s-a încheiat.\n\nPentru o nouă sesiune apăsați /start sau scanați codul QR.',
        'welcome_new': '👋 Bună, {name}!\n\nBun venit la Karaoke Absolutis!\n\nAcesta este un bot pentru gestionarea cozii la karaoke.\nPentru a începe, selectați locația dvs.',

        'venue_attached': '✅ Sunteți atașat la:\n🎵 {venue}\n🪑 Masă #{table}',
        'venue_attached_admin': '✅ Sunteți atașat la:\n🎵 {venue}\n🪑 Masă #{table}\n\n👑 Sunteți administratorul mesei',
        'select_table': '🎵 <b>{venue}</b>\n\n🪑 Selectați masa dvs.:',
        'all_tables_full': '🎵 <b>{venue}</b>\n\n⚠️ Toate mesele sunt ocupate.\n\nDoriți să vă alăturați ca oaspete fără masă?\nComanda dvs. va necesita confirmarea la KJ pe loc.',
        'table_full_choose': '🎵 <b>{venue}</b>\n\n❌ Masa #{table} este plină. Alegeți o altă masă:',
        'join_request_sent': '⏳ Cererea a fost trimisă administratorului mesei. Așteptați confirmarea.',
        'already_at_table': '✅ Sunteți deja la masa #{table}',
        'table_selected': '✅ Masa #{table} selectată!',
        'no_table_joined': '✅ V-ați alăturat la <b>{venue}</b> ca oaspete.\nNumărul dvs. virtual: <b>#{num}</b>\n\nFolosiți /client pentru a accesa meniul.',
        'no_table_cancelled': '❌ Anulat. Încercați mai târziu sau alegeți altă locație.',
        'btn_no_table_confirm': '✅ Confirmare',
        'btn_no_table_cancel': '❌ Anulare',

        'client_main_title': '🎵 <b>MENIU PRINCIPAL</b>',
        'client_main_body': (
            '🏢 Club: <b>{venue}</b>\n'
            '👤 Statut: <b>{status}</b>\n'
            'ID: <b>{uid}</b>\n\n'
            '—————————\n\n'
            '📌 Masă: <b>{table}</b>\n'
            '📋 Coada dvs. peste <b>{tables_before}</b> {tables_word} {playing_info}\n\n'
            'Alegeți acțiunea:'
        ),
        'client_status_guest': 'Oaspete',
        'client_status_no_table': 'Oaspete (fără masă)',
        'client_table_no_table': 'Fără masă (#{num})',
        'no_venues': '❌ Nu sunt cluburi disponibile. Contactați administratorul.',
        'select_club': '👋 Bun venit!\n\nVă rugăm să selectați clubul dvs.:',
        'club_selected': '✅ Clubul <b>{venue}</b> selectat!\n\nFolosiți /client pentru a continua.',
        'enter_table': '👋 Bun venit!\n\nVă rugăm să introduceți numărul mesei:',
        'table_set': '✅ Sunteți atașat la masa {table}.\n\nFolosiți /client pentru a accesa meniul.',
        'venue_not_found': '❌ Clubul nu a fost găsit. Selectați clubul din nou cu comanda /start',
        'table_must_be_positive': '❌ Numărul mesei trebuie să fie mai mare decât 0. Încercați din nou:',
        'no_venue_selected': '❌ Mai întâi selectați clubul.\nFolosiți /client pentru a începe.',
        'table_count_exceeded': '❌ Clubul are doar {count} mese.\nIntroduceți numărul de la 1 la {count}:',
        'enter_table_number': '❌ Vă rugăm să introduceți un număr:',
        'you_are_table_admin': '✅ Masa {table} selectată!\n\n👑 Sunteți administratorul mesei\nFolosiți /client pentru a accesa meniul.',
        'table_join_request_msg': '👥 Cerere de alăturare la masă\n\n🪑 Masă: {table}\n👤 Utilizator: {name} (@{username})',

        'btn_make_order': '🎵 Comandă melodie',
        'btn_my_orders': '📋 Comenzile mele',
        'btn_queue': '🔄 Coada rundei',
        'btn_become_vip': '⭐ Devino VIP',
        'btn_chat_kj': '💬 Chat cu KJ',
        'btn_manage_table': '👑 Gestionare masă',
        'btn_join_group': '👥 Alătură-te grupului',
        'btn_find_song': '🔍 Caută melodie',
        'btn_favorites': '⭐ Favorite',
        'btn_replace_song': '🔄 Înlocuiți melodia',
        'btn_replace_blocked': '🔒 Înlocuirea indisponibilă (poz. 1–2)',
        'btn_add_favorite': '⭐ Adaugă la favorite',
        'btn_reorder': '🔄 Repetați comanda',
        'btn_delete_favorite': '🗑️ Șterge din favorite',
        'btn_get_vip': '✨ Obțineți statut VIP',

        'order_menu_title': '🎵 *COMANDĂ MELODIE:*\n\n📌 Apăsați butonul de mai jos și introduceți titlul melodiei',
        'order_limit_reached': '❌ Limita melodiilor active ({limit}) a fost atinsă. Așteptați finalizarea comenzilor anterioare.',
        'song_not_found': '❌ Melodia nu a fost găsită',
        'order_sent': (
            '⏳ <b>Comanda #{order_id} trimisă</b>\n\n'
            '🎵 {song}\n💰 {service}\n'
            '📍 Poziție în coadă: #{pos}\n\n'
            'Așteptați confirmarea de la KJ...'
        ),
        'order_sent_no_table_suffix': '\n\n⚠️ <b>IMPORTANT:</b> Mergeți la KJ pentru a confirma comanda și a plăti!',
        'approach_kj': '⚠️ Mergeți la KJ pentru confirmare!',
        'no_services': '❌ Nu există servicii disponibile în club',
        'insufficient_balance': '❌ Fonduri insuficiente. Reîncărcați la KJ',
        'insufficient_balance_detail': '❌ Fonduri insuficiente\nSold: {balance} MDL\nNecesar: {price} MDL',

        'favorites_title': '🎵 <b>MELODIILE MELE</b>\nComenzile anterioare:\n\n',
        'favorites_empty': '🎵 <b>MELODIILE MELE</b>\n\nNu aveți încă melodii favorite',
        'favorite_added': '✅ Adăugat la favorite',
        'favorite_removed': '✅ Șters din favorite',

        'my_orders_title': '📋 *COMENZILE MELE*\n\n',
        'my_orders_empty': '📋 *COMENZILE MELE*\n\nNu aveți comenzi active',

        'queue_title': '📋 <b>Coada rundei</b>\n\n',
        'queue_now_playing': '▶️ <b>ACUM:</b> <b>{table}</b>\n    └ 🎤 {song}\n\n—————————\n\n',
        'queue_table_str': 'Masă {num}',
        'queue_no_table_str': 'Fără masă (#{num})',
        'queue_now_playing_info': '(acum cântă {table}/{pos})',
        'queue_empty': 'Coada este goală',
        'queue_next_header': '🔥 <b>ÎN AFARA COZII:</b>\n\n',
        'queue_regular_header': '🔄 <b>COADA GENERALĂ</b>\n\n',

        'replace_title': '🔄 <b>ÎNLOCUIRE MELODIE</b>\n\nApăsați \'🔍 Caută melodie\' pentru a căuta o melodie nouă.',
        'btn_find_song_replace': '🔍 Caută melodie',
        'replace_blocked': '❌ Înlocuirea nu este disponibilă: melodia dvs. este pe poziția #{rank}.\nÎnlocuirea este permisă doar de la poziția 3.',
        'replace_unavailable': '❌ Înlocuirea este imposibilă: melodia dvs. este pe poziția #{rank}.\nÎnlocuirea este disponibilă doar de la poziția 3 și mai departe.',
        'order_not_found': '❌ Comanda nu a fost găsită',

        'become_vip_text': (
            '⭐ *DEVINO VIP*\n\n{desc}\n\n'
            'Clienții VIP primesc:\n'
            '• Reîncărcarea soldului prin bot\n'
            '• Cashback din comenzi\n'
            '• Repetarea melodiilor preferate\n\n'
            'Pentru a obține statutul VIP apăsați butonul de mai jos și administratorul vă va analiza cererea.'
        ),
        'vip_request_sent': '✅ Cererea pentru statut VIP a fost trimisă!\nAșteptați confirmarea de la KJ.',
        'vip_request_already': '⏳ Cererea dvs. este deja în curs de examinare',
        'vip_access_denied': '❌ Nu aveți drepturi de client VIP',
        'vip_select_venue_first': '❌ Mai întâi selectați clubul și masa.\nScanați codul QR al mesei dvs.',

        'vip_menu_title': '🎵 *MENIU VIP*',
        'vip_menu_body': (
            '🏢 Club: *{venue}*\n'
            '👤 Statut: *VIP*\n'
            'ID: *{uid}*\n'
            '💰 Sold: *{balance} MDL*\n\n'
            '—————————\n\n'
            '📌 Masă: *{table}*\n'
            '📋 Coada dvs. peste *{tables_before}* {tables_word} {playing_info}\n\n'
            'Alegeți acțiunea:'
        ),
        'vip_profile_text': (
            '👤 *PROFIL*\n\n'
            '👤 Nume: *{name}*\n'
            'Telegram: @{username}\n'
            '🏢 Club: *{venue}*\n'
            '🪑 Masă: *{table}*\n'
            '⭐ Statut: *VIP*\n'
            '💰 Sold: *{balance} MDL*\n'
            '🎁 Cashback: *{cashback}%*'
        ),
        'not_specified': 'nespecificat',

        'btn_vip_make_order': '🎵 Comandă melodie',
        'btn_vip_my_orders': '📋 Comenzile mele',
        'btn_vip_queue': '🔄 Coada rundei',
        'btn_vip_balance': '💳 Soldul meu',
        'btn_vip_chat_kj': '💬 Chat cu KJ',
        'btn_vip_manage_table': '👑 Gestionare masă',
        'btn_vip_topup': '💰 Reîncarcă soldul',
        'btn_vip_order_history': '📊 Istoricul comenzilor',
        'btn_vip_finances': '💸 Finanțe',
        'btn_profile': '👤 Profil',
        'btn_history_today': '📅 Astăzi',
        'btn_history_week': '📅 Săptămâna',
        'btn_history_month': '📅 Luna',

        'balance_title': '💳 *SOLDUL MEU*\n\n💰 Sold curent: *{balance} MDL*\n\nAlegeți acțiunea:',
        'topup_title': '💰 *REÎNCĂRCARE SOLD*\n\nIntroduceți suma pentru reîncărcare (în MDL):',
        'topup_invalid': '❌ Sumă incorectă. Introduceți un număr pozitiv:',
        'topup_sent': '✅ Cererea de reîncărcare {amount} MDL a fost trimisă la KJ\nAșteptați confirmarea.',
        'topup_approved_client': '✅ Soldul dvs. a fost reîncărcat cu {amount} MDL!\nSold nou: {balance} MDL',
        'topup_rejected_client': '❌ Cererea de reîncărcare {amount} MDL a fost respinsă.',

        'order_history_title': '📊 *ISTORICUL COMENZILOR*\n\nAlegeți perioada:',
        'order_history_period': '📊 *ISTORICUL COMENZILOR*\n\nPentru {period}:\n\n',
        'order_history_empty': 'Nu există comenzi',
        'period_today': 'Astăzi',
        'period_week': 'Săptămâna',
        'period_month': 'Luna',
        'period_today_low': 'astăzi',
        'period_week_low': 'săptămână',
        'period_month_low': 'lună',

        'finances_title': '💸 *FINANȚE*\n\nAlegeți perioada:',
        'finances_period': '💸 *FINANȚE*\n\nPentru {period}:\n\n',
        'finances_topups': '💰 *Reîncărcări:*\n',
        'finances_no_topups': '  Fără reîncărcări\n',
        'finances_total_plus': '  _Total: +{total} MDL_\n',
        'finances_total_minus': '  _Total: -{total} MDL_\n',
        'finances_payments': '\n🎵 *Plata comenzilor:*\n',
        'finances_no_payments': '  Fără plăți\n',
        'finances_refunds': '\n↩️ *Rambursări:*\n',
        'finances_no_refunds': '  Fără rambursări\n',
        'finances_cashbacks': '\n🎁 *Cashback:*\n',
        'finances_no_cashbacks': '  Fără cashback\n',
        'finances_balance': '\n💳 *Sold curent: {balance} MDL*',

        'vip_order_title': '🎵 *COMANDĂ MELODIE:*\n\n📌 Apăsați butonul de mai jos și introduceți titlul melodiei',
        'choose_service_title': '💰 <b>SELECTARE SERVICIU</b>{balance_line}',
        'choose_service_body': '\n\nServicii disponibile:\n{services}\n\nAlegeți tipul comenzii:',
        'order_created': '✅ Comanda a fost creată!',
        'balance_line': '\n💰 Soldul dvs.: <b>{balance} MDL</b>',
        'service_free': 'Gratuit',

        'chat_title': '💬 <b>CHAT CU KJ</b>\n\nScriți mesajul dvs.:',
        'chat_sent': '✅ Mesajul a fost trimis la KJ',
        'chat_failed': '❌ Mesajul nu a putut fi trimis',
        'chat_msg_to_kj': '📨 <b>Mesaj de la client</b>\n\n🪑 Masă <b>{table}</b>\n👤 <b>{name}</b> {vip_badge}\n\n💬 {text}',
        'btn_chat_reply': '💬 Răspunde',

        'kj_new_order': (
            '🎵 <b>COMANDĂ NOUĂ #{order_id}</b>\n\n'
            '{table}\n'
            '👤 Client: <b>{name}</b> {vip_badge}\n'
            '🎵 Melodie: <b>{song}</b>\n'
            '💼 Serviciu: <b>{service}</b>\n'
            '📍 Poziție: <b>#{pos}</b>\n\n'
            '📋 Comenzi active ale clientului: <b>{active}/{max}</b>'
        ),
        'kj_new_order_no_table_warn': '\n\n⚠️⚠️⚠️ <b>CLIENT FĂRĂ MASĂ!</b>\n❗ <b>NECESITĂ CONFIRMARE PE LOC!</b> ⚠️⚠️⚠️',
        'kj_order_approved_client': '✅ <b>Comanda dvs. #{order_id} a fost acceptată!</b>\n\n🎵 <b>{song}</b>\n📍 Poziție în coadă: <b>#{pos}</b>\n\nAșteptați rândul dvs...',
        'kj_order_rejected_client': '❌ Comanda dvs. <b>#{order_id}</b> a fost respinsă\n🎵 <b>{song}</b>{refund_text}\n\nPuteți alege o altă melodie',
        'kj_refund_line': '\n💰 Rambursare pe sold: <b>{amount} MDL</b>',
        'order_refund': '💰 Rambursare pe sold: <b>{amount} MDL</b>',
        'kj_order_completed_client': '✅ Melodia dvs. a fost interpretată: <b>{song}</b>\n💰 Cashback: <b>{cashback}</b>',
        'order_deleted_refund': '❌ Comanda dvs. <b>#{order_id}</b> a fost ștearsă\n🎵 <b>{song}</b>\n💰 Rambursare pe sold: <b>{refund} MDL</b>',
        'vip_approved': '✅ Statutul dvs. VIP a fost confirmat! Utilizați /vip pentru a intra în meniul VIP.',
        'vip_rejected': '❌ Cererea pentru statut VIP a fost respinsă.',
        'kj_chat_message': '💬 <b>Mesaj de la KJ</b>\n\n{text}',
        'kj_topup_request': (
            '💰 *CERERE DE REÎNCĂRCARE SOLD*\n\n'
            '🪑 Masă *{table}*\n'
            '👤 *{name}* (@{username})\n'
            '💵 Sumă: *{amount} MDL*\n\n'
            'Confirmați reîncărcarea soldului:'
        ),
        'kj_topup_approved': '✅ Cererea dvs. de reîncărcare a soldului a fost confirmată!\nReîncărcat: *{amount} MDL*\nSold nou: *{balance} MDL*',
        'kj_topup_rejected': '❌ Cererea dvs. de reîncărcare *{amount} MDL* a fost respinsă.',
        'kj_table_label': '🪑 Masă: <b>{table}</b>',
        'kj_no_table_label': '🪑 Client fără masă (#{num})',
        'btn_order_cancel': '❌ Anulare',
        'btn_order_approve': '✅ Acceptare',
        'btn_approve': '✅ Acceptare',
        'btn_topup_approve': '✅ Confirmare',
        'btn_topup_reject': '❌ Anulare',

        'vip_request_to_kj': '⭐ *CERERE VIP*\n\n🪑 Masă *{table}*\n👤 *{name}* (@{username})\n\nClientul dorește să obțină statut VIP.',
        'btn_vip_approve': '✅ Confirmare VIP',
        'btn_vip_reject': '❌ Respingere',

        'table_join_approved_client': '✅ Ați fost adăugat la masa {table}!\n\nFolosiți /client pentru a accesa meniul.',
        'table_join_rejected_client': '❌ Cererea dvs. de alăturare la masa {table} a fost respinsă.',
        'table_group_title': '👥 *GESTIONARE MASĂ*\n\n🪑 Masă: *{table}*\n👑 Sunteți administratorul mesei\n\nParticipanți ({count}/{max}):',
        'table_group_no_other_members': 'Doar dvs.',
        'table_group_kick': '🚪 Eliminare',
        'table_group_leave': '🚪 Părăsiți masa',
        'table_group_leave_confirm': '⚠️ Doriți să părăsiți masa?',
        'table_kick_confirm': '⚠️ Eliminați {name} de la masă?',
        'table_kick_done': '✅ {name} a fost eliminat(ă) de la masă',
        'table_leave_done': '✅ Ați părăsit masa',

        'tables_0': 'mese',
        'tables_1': 'masă',
        'tables_2_4': 'mese',
        'tables_other': 'mese',

        'no_client_access': '❌ Nu aveți acces. Folosiți /client',
        'select_club_notable': '🏢 Selectați clubul:',
        'no_venues_available': '❌ Nu există cluburi disponibile',
        'notable_venue_selected': '✅ Ați selectat clubul: {venue}\nNumărul dvs. virtual: {num}\n\nFolosiți /notable sau /client pentru a accesa meniul',

        'admin_panel_main': (
            '👑 *Administrator sistem*\n\n'
            'Cluburi: *{clubs}* | Active: *{active}*\n'
            'Venituri astăzi: *{revenue}*'
        ),
        'admin_no_rights': '❌ Nu aveți drepturi de administrator',
        'admin_not_main_admin': '❌ Această comandă este disponibilă doar administratorului principal',
        'admin_venues_title': '🏢 *Gestionare cluburi* | Total: *{total}*\n\n',
        'admin_venues_empty': '🏢 *Gestionare cluburi*\n\nNu există cluburi încă',
        'admin_venue_status_online': '🟢 Online',
        'admin_venue_status_blocked': '🔴 Blocat',
        'admin_add_venue_title': '🏢 *ADĂUGARE CLUB NOU*\n\nIntroduceți numele clubului:',
        'admin_enter_city': 'Introduceți orașul:',
        'admin_enter_phone': 'Telefonul proprietarului:',
        'admin_enter_email': 'Email-ul proprietarului:',
        'admin_venue_created': "✅ Clubul '{name}' a fost creat! ID: {vid}\nAtribuiți un KJ pentru activare.",
        'admin_choose_venue': '📋 Selectați clubul:',
        'admin_venue_details': (
            '🏢 *DETALII CLUB: {name} (ID:{vid})*\n\n'
            'Status: *{status}*\n'
            'KJ: *{kj}*\n'
            'Creat: *{created}*\n'
            'Mese: *{tables}*\n'
            '🎵 Melodii în bază: *{songs}*\n'
            'Venituri astăzi: *{revenue}*\n'
            'Oraș: *{city}*\n'
            'Telefon: *{phone}*\n'
            'Email: *{email}*'
        ),
        'admin_venue_active_status': '🟢 Activ',
        'admin_venue_finance': (
            '💰 *FINANȚE: {name}*\n\n'
            '📅 *Astăzi:*\n'
            'Venituri: *{today}*\n\n'
            '📆 *Săptămâna:*\n'
            'Venituri: *{week}*\n\n'
            '📈 *Luna:*\n'
            'Venituri: *{month}*\n'
            'Cashback admin (5%): *{admin_fee}*\n'
        ),
        'admin_venue_songs': (
            '🎵 *GESTIONARE MELODII: {name}*\n\n'
            'Total melodii în bază: *{count}*\n\n'
            "Pentru importul melodiilor noi folosiți funcția\n'Import CSV' din meniul KJ."
        ),
        'admin_edit_name_prompt': 'Numele actual: *{name}*\n\nIntroduceți noul nume:',
        'admin_name_changed': '✅ Numele clubului a fost schimbat în: *{name}*',
        'admin_unbind_tables_confirm': (
            '⚠️ *DEZLEAGĂ TOȚI DE LA MESE*\n\n'
            'Local: *{venue}*\n'
            'La mese acum: *{count} pers.*\n\n'
            'Toți utilizatorii vor fi dezlegați de la mese\n'
            '(vor rămâne legați de local)\n\n'
            'Confirmați?'
        ),
        'admin_unbind_tables_done': (
            '✅ Toți utilizatorii au fost dezlegați de la mese\n\n'
            'Local: *{venue}*\n'
            'Dezlegați: *{count} pers.*'
        ),
        'admin_unbind_venue_confirm': (
            '⚠️ *DEZLEAGĂ TOȚI DE LA LOCAL*\n\n'
            'Local: *{venue}*\n'
            'Utilizatori legați: *{count} pers.*\n\n'
            'TOȚI utilizatorii vor fi complet dezlegați de la local\n\n'
            'Confirmați?'
        ),
        'admin_unbind_venue_done': (
            '✅ Toți utilizatorii au fost dezlegați de la local\n\n'
            'Local: *{venue}*\n'
            'Dezlegați: *{count} pers.*'
        ),
        'admin_venue_contacts_header': '📞 *CONTACTE CLUBURI*\n\n',
        'admin_venue_contacts_empty': 'Nu există cluburi încă',
        'admin_venue_block_select': '🚫 Selectați clubul pentru modificarea statusului:',
        'admin_venue_delete_select': '🗑️ Selectați clubul pentru ștergere:',
        'admin_venue_toggle_block_confirm': '⚠️ Blocați clubul *{name}*?',
        'admin_venue_toggle_unblock_confirm': '⚠️ Deblocați clubul *{name}*?',
        'admin_kj_list_header': '👥 <b>GESTIONARE OPERATORI KJ</b> | Total: <b>{total}</b>\n\n',
        'admin_kj_list_empty': 'Nu există operatori KJ',
        'admin_kj_blocked_status': '🔴 Blocat',
        'admin_kj_remove_select': '➖ Selectați KJ pentru eliminare:',
        'admin_kj_assign_title': '➕ *ATRIBUIRE KJ*\n\nSelectați clubul:',
        'admin_kj_enter_username': '👥 *ATRIBUIRE KJ PENTRU CLUB*\n\nIntroduceți Telegram username-ul noului KJ (ex: @username):',
        'admin_kj_not_found': '❌ Utilizatorul @{username} nu a fost găsit în bază.\nUtilizatorul trebuie să pornească mai întâi botul cu comanda /start',
        'admin_kj_cant_be_admin': '❌ Nu se poate atribui administratorul principal în rolul de KJ',
        'admin_kj_assigned': '✅ Utilizatorul @{username} a fost atribuit ca KJ\n🏢 Club: *{venue}*\n\nNotificarea a fost trimisă utilizatorului.',
        'admin_kj_assigned_no_notify': '✅ Utilizatorul @{username} a fost atribuit ca KJ\n🏢 Club: *{venue}*\n\n⚠️ Nu s-a putut trimite notificarea (utilizatorul a blocat botul)',
        'admin_kj_welcome': '🎵 *FELICITĂRI!*\n\nAți fost atribuit ca operator KJ al localului:\n🏢 *{venue}*\n📍 *{city}*',
        'admin_kj_remove_confirm': '⚠️ Eliminați @{username} din funcția de KJ?',
        'admin_kj_stats_header': '📋 *STATISTICI MUNCĂ KJ*\n\n',
        'admin_kj_contacts_header': '📞 *CONTACTE OPERATORI KJ*\n\n',
        'admin_kj_contacts_empty': 'Nu există operatori KJ',
        'admin_kj_select_toggle': '🚫 Selectați KJ pentru modificarea statusului:',
        'admin_reports_header': '📊 *RAPOARTE FINANCIARE*\n\nAstăzi: *{today}*\nLuna: (în dezvoltare)',
        'admin_report_today_title': '📊 *RAPORT PENTRU {date}*\n\n',
        'admin_report_revenue_total': '*VENITURI:* *{revenue}*\n',
        'admin_report_orders_total': '*COMENZI:* *{count}*\n',
        'admin_report_commission': '*Comision admin (5%):* *{amount}*\n',
        'admin_report_week_title': '📆 *RAPORT SĂPTĂMÂNAL*\n\n',
        'admin_report_week_revenue': '*VENITURI SĂPTĂMÂNA:* *{revenue}*\n',
        'admin_report_month_title': '📈 *RAPORT LUNAR*\n\n',
        'admin_report_month_revenue': '*VENITURI LUNA:* *{revenue}*\n',
        'admin_report_venues_title': '🏢 *RAPORT COMPARATIV PE CLUBURI*\n\n',
        'admin_report_cashback_title': '💸 *CASHBACK DE LA KJ ADMIN*\n\n',
        'admin_report_export_title': '📤 *EXPORT DATE*\n\nSelectați formatul de export:',
        'admin_system_header': (
            '⚙️ *SETĂRI SISTEM BOT*\n\n'
            'Status bot: 🟢 Funcționează\n'
            'Cluburi: *{clubs}*\n'
            'Operatori KJ: *{kj}*\n'
            'Total utilizatori: *{users}*\n'
            'Ultima actualizare: *{time}*'
        ),
        'admin_support_header': (
            '🛠️ *SUPORT TEHNIC*\n\n'
            '*Status:* 🟢 Funcționează\n'
            '*Utilizare memorie:* {memory} MB\n'
            '*CPU:* {cpu}%\n'
            '*Timp funcționare:* {time}\n\n'
            '*Baza de date:* SQLite\n'
            '*Cale:* {db_path}\n'
        ),
        'admin_support_db_size': '*Dimensiune BD:* {size} MB\n',
        'admin_support_db_na': '*Dimensiune BD:* N/D\n',
        'admin_logs_header': '📝 *JURNAL ACȚIUNI*\n\nUltimele 20 tranzacții:\n\n',
        'admin_logs_empty': 'Jurnalul este gol',
        'admin_restart_confirm': (
            '🔄 *REPORNIRE BOT*\n\n'
            '⚠️ Sunteți sigur că doriți să reporniți botul?\n'
            'Aceasta va întrerupe toate operațiunile curente.'
        ),
        'admin_restarting': '🔄 Repornire bot...\n\nBotul va fi repornit manual.',
        'admin_set_admin_prompt': (
            '👑 *ATRIBUIRE ADMINISTRATOR*\n\n'
            'Introduceți Telegram ID sau username-ul utilizatorului pe care doriți să îl faceți administrator:\n\n'
            'De exemplu:\n'
            '• 123456789\n'
            '• @username'
        ),
        'admin_unset_admin_prompt': (
            '👤 *REVOCARE DREPTURI ADMINISTRATOR*\n\n'
            'Introduceți Telegram ID sau username-ul administratorului pe care doriți să îl retrogrădiți:\n\n'
            'De exemplu:\n'
            '• 123456789\n'
            '• @username'
        ),
        'admin_invalid_identifier': '❌ Format incorect. Introduceți Telegram ID (123456789) sau username (@username):',
        'admin_user_not_found': '❌ Utilizatorul nu a fost găsit în baza de date.\nUtilizatorul trebuie să pornească mai întâi botul cu comanda /start',
        'admin_already_admin': 'ℹ️ Utilizatorul {name} (@{username}) este deja administrator',
        'admin_set_done': '✅ Utilizatorul {name} (@{username}) a fost atribuit ca administrator!\nID: {uid}',
        'admin_cant_unset_main': '❌ Nu se pot revoca drepturile administratorului principal',
        'admin_not_admin_user': 'ℹ️ Utilizatorul {name} (@{username}) nu este administrator',
        'admin_unset_done': '✅ Drepturile de administrator au fost revocate utilizatorului {name} (@{username})\nID: {uid}',
        'admin_new_admin_notify': '👑 *FELICITĂRI!*\n\nVi s-au atribuit drepturi de administrator de sistem.\nFolosiți /admin pentru a accesa panoul de control.',
        'admin_admin_revoked_notify': 'ℹ️ Drepturile dvs. de administrator au fost revocate.\nAcum aveți rolul de utilizator obișnuit.',
        'btn_admin_clubs': '🏢 Cluburi',
        'btn_admin_kj': '👥 Operatori KJ',
        'btn_admin_reports': '📊 Rapoarte',
        'btn_admin_system': '⚙️ Sistem',
        'btn_admin_refresh': '🔄 Actualizare',
        'btn_venue_add': '➕ Adaugă club',
        'btn_venue_detailed': '📋 Detalii',
        'btn_venue_block_toggle': '🚫 Blocare/Deblocare',
        'btn_venue_delete': '🗑️ Șterge club',
        'btn_venue_contacts_btn': '📞 Contacte',
        'btn_edit_venue_name': '✏️ Editează numele',
        'btn_venue_assign_kj': '👥 Atribuie/Schimbă KJ',
        'btn_venue_finance': '📊 Finanțe club',
        'btn_venue_songs_btn': '🎵 Gestionare melodii',
        'btn_venue_qr': '📱 QR cod club',
        'btn_unbind_tables': '🪑 Dezleagă toate mesele',
        'btn_unbind_venue': '🚪 Dezleagă toți de la local',
        'btn_venue_refresh': '🔄 Actualizare date',
        'btn_kj_assign_new': '➕ Atribuie KJ nou',
        'btn_kj_remove': '➖ Elimină KJ',
        'btn_kj_work_stats': '📋 Statistici muncă',
        'btn_kj_contacts': '📞 Contacte KJ',
        'btn_kj_block_toggle': '🚫 Blocare/Deblocare',
        'btn_report_today': '📅 Astăzi',
        'btn_report_week': '📆 Săptămâna',
        'btn_report_month': '📈 Luna',
        'btn_report_venues': '🏢 Pe cluburi',
        'btn_report_cashback': '💸 Cashback de la KJ',
        'btn_export_data': '📤 Export date',
        'btn_sys_support': '🛠️ Suport tehnic',
        'btn_sys_logs': '📝 Jurnal acțiuni',
        'btn_sys_backup': '💾 Backup',
        'btn_sys_restart': '🔄 Repornire bot',
        'admin_venue_qr_caption': '📱 Scanați QR — botul vă va propune să alegeți masa.\nMese: *{tables}*',
        'admin_backup_caption': '💾 Copie de rezervă a bazei de date\n{time}',
        'admin_backup_done': '✅ Copia de rezervă a fost creată și trimisă',
        'admin_backup_error': '❌ Eroare la crearea copiei: {error}',
        'admin_restart_manual': '⚠️ Reporniți botul manual în terminal',
        'admin_csv_col_club': 'Club',
        'admin_csv_col_city': 'Oraș',
        'admin_csv_col_revenue_today': 'Venituri azi',
        'admin_csv_col_revenue_week': 'Venituri săptămâna',
        'admin_csv_col_revenue_month': 'Venituri luna',
        'admin_csv_col_status': 'Status',
        'admin_csv_status_active': 'Activ',
        'admin_csv_status_blocked': 'Blocat',
        'admin_csv_caption': '📊 Raport în format CSV',
        'admin_csv_sent': '✅ Fișier trimis',
        'admin_excel_soon': '📈 Exportul în Excel va fi adăugat mai târziu',

        'kj_panel_title': '🎵 <b>Panou KJ</b>\n\n🏢 Local: <b>{venue}</b>\n🌐 Oraș: <b>{city}</b>',
        'kj_no_rights': '❌ Nu aveți drepturi de operator KJ',
        'kj_no_venue': '❌ Nu sunteți legat de un local',
        'btn_kj_club_settings': '⚙️ Setări club',
        'btn_kj_work_evening': '🎵 Lucru în cursul serii',

        'kj_settings_warn_text': (
            '⚙️ <b>SETĂRI CLUB</b>\n\n'
            '⚠️ Accesați secțiunea setărilor clubului.\n'
            'Modificările intră în vigoare imediat.\n\n'
            'Confirmare acces?'
        ),
        'kj_settings_title': (
            '⚙️ <b>SETĂRI CLUB</b>\n\n'
            '🏢 Local: <b>{venue}</b>\n'
            '📌 Limită mese: <b>{table_count}</b>\n'
            '🎵 Limită melodii per oaspete: <b>{songs_limit}</b>'
        ),
        'btn_kj_import_csv': '📁 Import bază',
        'btn_kj_services': '💼 Servicii și prețuri',
        'btn_kj_tables_settings': '🪑 Mese',
        'btn_kj_clients': '👥 Clienți',
        'btn_kj_vip_settings': '⭐ Setări VIP',
        'btn_kj_chat_on': '✅ Chat: activ',
        'btn_kj_chat_off': '💬 Chat: inactiv',
        'btn_kj_chat_link_change': '🔗 Modifică link chat',
        'btn_kj_free_evening': '🎁 Seară gratuită',

        'kj_import_csv_title': (
            '📁 *IMPORT BAZĂ CSV*\n\n'
            'Trimiteți fișierul CSV cu melodii.\n'
            'Format: artist,titlu,cod\n\n'
            'Exemplu:\n'
            'Imagine Dragons,Believer,ID123\n'
            'The Beatles,Yesterday,BT456'
        ),
        'kj_csv_format_error': '❌ Fișierul trebuie să fie în format CSV',

        'kj_services_title': '💼 <b>SERVICII ȘI PREȚURI</b>\n\n',
        'kj_services_empty': 'Nu există servicii',
        'btn_kj_service_add': '➕ Adaugă serviciu',
        'btn_kj_service_edit': '📝 Editează serviciu',
        'btn_kj_service_delete': '🗑️ Șterge serviciu',
        'kj_service_add_title': '➕ *ADĂUGARE SERVICIU*\n\nIntroduceți numele serviciului:',
        'kj_service_add_desc_prompt': 'Introduceți descrierea serviciului:',
        'kj_service_add_price_prompt': 'Introduceți prețul serviciului (număr):',
        'kj_service_created': "✅ Serviciul '{name}' a fost creat!",
        'kj_service_price_invalid': '❌ Format incorect. Introduceți un număr:',
        'kj_service_none': '❌ Nu există servicii',
        'kj_service_edit_choose': '📝 Selectați serviciul pentru editare:',
        'kj_service_edit_title': (
            '📝 <b>EDITARE SERVICIU</b>\n\n'
            'Date curente:\n'
            'Nume: <b>{name}</b>\n'
            'Descriere: <b>{desc}</b>\n'
            'Preț: <b>{price} MDL</b>\n\n'
            'Introduceți noul nume (sau /skip pentru a omite):'
        ),
        'kj_service_edit_desc_prompt': 'Introduceți noua descriere (sau /skip pentru a omite):',
        'kj_service_edit_price_prompt': 'Introduceți noul preț (sau /skip pentru a omite):',
        'kj_service_updated': '✅ Serviciu actualizat!',
        'kj_service_no_changes': 'Nicio modificare efectuată',
        'kj_service_delete_choose': '🗑️ Selectați serviciul pentru ștergere:',
        'kj_service_deleted': '✅ Serviciu șters',
        'kj_service_not_found': '❌ Serviciu negăsit',

        'kj_tables_title': (
            '🪑 *GESTIONARE MESE*\n\n'
            '🔹 Număr de mese: *{count}*\n'
            '🔹 Limită melodii per oaspete: *{songs}*\n'
            '🔹 Mod coadă: *{mode}*'
        ),
        'kj_table_mode_sequential': 'Secvențial',
        'kj_table_mode_by_order': 'La comandă',
        'btn_kj_tables_count': '🔢 Număr de mese',
        'btn_kj_tables_songs': '🎵 Melodii per masă',
        'btn_kj_tables_mode': '🔄 Mod coadă',
        'btn_kj_tables_unbind_all': '🪑 Dezleagă toate mesele',
        'kj_tables_edit_title': '⚙️ <b>EDITARE MESE</b>\n\nSelectați parametrul:',
        'btn_kj_tables_unbind_venue': '🚪 Dezleagă pe toți de la local',
        'kj_tables_count_prompt': '🔢 Introduceți noul număr de mese\n(actual: {current}):',
        'kj_tables_songs_prompt': '🎵 Funcție în curs de dezvoltare',
        'kj_tables_setting_saved': '✅ Salvat: {value}',
        'kj_tables_mode_choose': '🔄 *MOD COADĂ*\n\nSelectați modul de coadă:',
        'kj_tables_mode_changed': '✅ Mod schimbat: *{mode}*',
        'kj_tables_count_invalid': '❌ Introduceți un număr întreg pozitiv:',
        'kj_unbind_tables_confirm_text': '⚠️ Dezlegați toate mesele curente? Toate sesiunile vor fi terminate.',
        'kj_unbind_venue_confirm_text': '⚠️ Dezlegați toți clienții de la local? Toate sesiunile vor fi terminate.',
        'kj_unbind_tables_done': '✅ Toate mesele au fost dezlegate',
        'kj_unbind_venue_done': '✅ Toți clienții au fost dezlegați de la local',

        'kj_vip_settings_title': '⭐ *SETĂRI VIP*',
        'btn_kj_vip_add': '➕ Adaugă VIP',
        'btn_kj_vip_cashback': '💰 Setare cashback',
        'btn_kj_vip_description': '📝 Descriere VIP (RU)',
        'btn_kj_vip_description_ro': '📝 Descriere VIP (RO)',
        'kj_vip_cashback_title': (
            '💰 *SETARE CASHBACK VIP*\n\n'
            'Procent curent: *{current}%*\n\n'
            'Introduceți noul procent de cashback pentru clienții VIP\n'
            '(ex: 5 pentru 5%):'
        ),
        'kj_vip_cashback_saved': '✅ Procentul de cashback VIP a fost setat: *{value}%*',
        'kj_vip_cashback_invalid': '❌ Procentul trebuie să fie între 0 și 100',
        'kj_vip_cashback_format_error': '❌ Format incorect. Introduceți un număr:',
        'kj_vip_desc_title': (
            '📝 *DESCRIERE BENEFICII VIP*\n\n'
            'Descrierea curentă:\n*{current}*\n\n'
            'Introduceți noua descriere a beneficiilor VIP:'
        ),
        'kj_vip_desc_saved': '✅ Descrierea VIP a fost actualizată!',
        'kj_vip_desc_ro_title': (
            '📝 *DESCRIERE VIP (RO)*\n\n'
            'Descrierea curentă în română:\n*{current}*\n\n'
            'Introduceți noua descriere a beneficiilor VIP în română:'
        ),
        'kj_vip_desc_ro_saved': '✅ Descrierea VIP în română a fost salvată!',
        'kj_vip_add_title': '➕ *ADĂUGARE VIP*\n\nIntroduceți Telegram ID-ul utilizatorului:',
        'kj_vip_add_cashback_prompt': 'Introduceți procentul de cashback (ex: 5):',
        'kj_vip_added': '✅ Statut VIP acordat utilizatorului {name}!',
        'kj_vip_user_not_found': '❌ Utilizatorul nu a fost găsit în bază',
        'kj_vip_id_invalid': '❌ Format incorect. Introduceți un număr:',
        'kj_vip_cashback_format': '❌ Format incorect. Introduceți un număr:',
        'btn_kj_venue_not_found': '❌ Localul nu a fost găsit',

        'kj_clients_title': '👥 *CLIENȚI*\n\nSelectați acțiunea:',
        'btn_kj_client_search': '🔍 Căutare după ID',
        'btn_kj_client_bind': '🔗 Legare client',
        'btn_kj_client_referrals': '📋 Toți referalii',
        'kj_client_search_prompt': '🔍 *CĂUTARE CLIENT*\n\nIntroduceți Telegram ID-ul clientului:',
        'kj_client_not_found': '❌ Clientul nu a fost găsit',
        'kj_client_id_invalid': '❌ Format incorect de ID',
        'kj_client_status_vip': 'VIP',
        'kj_client_status_regular': 'Obișnuit',
        'kj_client_none_label': 'nu există',
        'kj_client_info': (
            '👤 <b>CLIENT</b>\n\n'
            'ID: <b>{uid}</b>\n'
            'Nume: <b>{name}</b>\n'
            'Username: <b>@{username}</b>\n'
            'Status: <b>{status}</b>\n'
            'Masă: <b>{table}</b>\n'
            'Sold: <b>{balance} MDL</b>\n'
            'Comision: <b>{commission}%</b>\n'
            'Blocat: <b>{blocked}</b>'
        ),
        'kj_no_referrals': 'Nu există referali',
        'kj_referrals_title': '📋 <b>REFERALI</b>\n\n',
        'kj_referral_item': '{n}. {name} (@{username}) — ID: {uid}',
        'kj_clients_list_title': '📋 <b>LISTA CLIENȚILOR</b> — {label}\n\nTotal: <b>{total}</b>\n\n',
        'kj_clients_filter_all': '📋 Toți',
        'kj_clients_filter_vip': '⭐ VIP',
        'kj_clients_filter_regular': '👤 Obișnuiți',
        'kj_clients_empty': 'Momentan nu există clienți',
        'kj_clients_more': '... și încă <b>{count}</b> clienți',
        'kj_client_orders_spent': 'Comenzi: <b>{orders}</b> | Cheltuit: <b>{spent}</b>',

        'btn_kj_client_balance': '💰 Sold',
        'btn_kj_client_unbind_table': '🔓 Dezleagă de la masă',
        'btn_kj_client_unbind_venue': '🚪 Dezleagă de la local',
        'btn_kj_client_block': '🔒 Blochează',
        'btn_kj_client_unblock': '🔓 Deblochează',
        'btn_kj_client_commission': '📊 Setări comision %',
        'btn_kj_client_chat': '💬 Porniri dialog',
        'btn_kj_client_delete': '🗑️ Șterge din bază',
        'btn_kj_bind_info': '📋 Informații legătură',

        'kj_balance_title': '💰 <b>GESTIONARE SOLD</b>\n\n👤 {name}\nSold curent: <b>{balance} MDL</b>',
        'btn_kj_balance_add': '➕ Adaugă',
        'btn_kj_balance_sub': '➖ Scade',
        'btn_kj_balance_set': '🔄 Setează',
        'kj_balance_add_prompt': 'Introduceți suma de adăugat:',
        'kj_balance_sub_prompt': 'Introduceți suma de scăzut:',
        'kj_balance_set_prompt': 'Introduceți noua valoare a soldului:',
        'kj_balance_result': '✅ Sold {name}:\n{old} MDL → {new} MDL',
        'kj_balance_invalid': '❌ Sumă incorectă. Introduceți un număr:',

        'kj_commission_title': (
            '📊 <b>COMISION CLIENT</b>\n\n'
            '👤 {name}\n'
            'Comision curent: <b>{current}%</b>\n\n'
            'Introduceți noul procent de comision (0–100):'
        ),
        'kj_commission_saved': '✅ Comision setat: {value}%',
        'kj_commission_invalid': '❌ Procentul trebuie să fie între 0 și 100',
        'kj_commission_format': '❌ Format incorect. Introduceți un număr:',

        'kj_client_blocked': '✅ Clientul {name} a fost blocat',
        'kj_client_unblocked': '✅ Clientul {name} a fost deblocat',
        'kj_client_unbound_table': '✅ Clientul {name} a fost dezlegat de la masă',
        'kj_client_unbound_venue': '✅ Clientul {name} a fost dezlegat de la local',
        'kj_client_delete_confirm_text': '🗑️ Confirmați ștergerea clientului <b>{name}</b> din baza de date.\nAcțiunea este ireversibilă!',
        'kj_client_deleted': '✅ Clientul {name} a fost șters din bază',

        'kj_chat_toggle_enabled': '✅ Chat-ul cu clienții a fost activat',
        'kj_chat_toggle_disabled': '❌ Chat-ul cu clienții a fost dezactivat',
        'kj_chat_link_prompt': '🔗 Introduceți link-ul chatului general al clubului\n(trebuie să înceapă cu https://t.me/):',
        'kj_chat_link_saved': '✅ Link-ul chatului a fost salvat',
        'kj_chat_link_invalid': '❌ Link-ul trebuie să înceapă cu https://t.me/',
        'kj_chat_change_link_prompt': '🔗 Introduceți noul link de chat\n(trebuie să înceapă cu https://t.me/):',
        'kj_chat_with_client': '💬 <b>CHAT CU CLIENTUL</b>\n\n👤 {name}\n\nIntroduceți mesajul:',
        'kj_message_sent': '✅ Mesaj trimis',
        'kj_message_failed': '❌ Nu s-a putut trimite mesajul',
        'kj_chat_reply_prompt': '✏️ Introduceți răspunsul pentru clientul {name}:',

        'kj_free_title': '🎁 <b>SEARĂ GRATUITĂ</b>\n\n',
        'kj_free_label_free': 'gratuit',
        'kj_free_label_paid': 'contra cost',
        'kj_free_service_line_free': '🟢 {name} — Gratuit',
        'kj_free_service_line_paid': '🔴 {name} — {price} MDL',
        'kj_free_toggle_to_free': '🆓 Faceți gratuit',
        'kj_free_toggle_to_paid': '💰 Faceți contra cost',
        'kj_free_toggled_to_free': '✅ Serviciul «{name}» este acum gratuit',
        'kj_free_toggled_to_paid': '✅ Serviciul «{name}» este din nou contra cost ({price} MDL)',
        'kj_free_service_not_found': '❌ Serviciu negăsit',
        'kj_free_empty': 'Nu există servicii',

        'kj_work_title': '🎵 <b>LUCRU ÎN CURSUL SERII</b>\n\nSelectați acțiunea:',
        'btn_kj_queue': '📋 Gestionare coadă',
        'btn_kj_global_queue': '📋 Coada generală',
        'btn_kj_stats': '📊 Statistici seară',

        'kj_global_queue_title': '📋 <b>COADA GENERALĂ</b>',
        'kj_queue_no_table_label': 'Fără masă (#{num})',
        'kj_queue_table_label': 'Masa {num}',
        'kj_queue_now_header': '▶️ <b>ACUM:</b>',
        'kj_queue_vne_header': '⏸ <b>ÎN AȘTEPTARE:</b>',
        'kj_queue_circle_header': '🔄 <b>Coada rundei</b>',
        'kj_queue_empty': 'Coada este goală',
        'btn_kj_refresh_queue': '🔄 Actualizare',
        'kj_table_header_virtual': '📋 <b>FĂRĂ MASĂ #{num}</b> {status}',
        'kj_table_header': '📋 <b>MASA {num}</b> {status}',
        'kj_table_status_active': '🟢',
        'kj_table_status_free': '⚪',
        'kj_order_next_marker': ' ⏭ URMĂTOR',
        'kj_order_waiting_status': 'Așteaptă confirmare',
        'btn_kj_close_table': '🔒 Închide masa',
        'btn_kj_close_table_virtual': '🔒 Închide sesiunea',
        'btn_kj_add_order': '➕ Adaugă comandă',
        'kj_order_set_next': '✅ Setat următor',
        'kj_order_cleared_next': '✅ Eliminat din următori',
        'kj_next_song_ready': '🎶 Melodia dvs. a fost pusă pe locul următor, pregătiți-vă!',

        'kj_table_close_title': '🔒 <b>ÎNCHIDERE MASĂ {num}</b>',
        'kj_table_close_songs': 'Melodii interpretate: <b>{count}</b>',
        'kj_table_close_total': 'Total: <b>{total} MDL</b>',
        'kj_table_close_free': 'Seară gratuită',
        'kj_receipt_title': '🧾 <b>BONUL DVSTRĂ</b>',
        'kj_receipt_item': '{n}. {song} — {price}',
        'kj_session_ended_receipt': '🎶 Sesiunea dvs. s-a încheiat!\n\n{receipt}',
        'kj_session_ended_simple': '🎶 Sesiunea dvs. s-a încheiat! Vă mulțumim!',
        'kj_queue_manage_title': '📋 <b>GESTIONARE COADĂ</b>\n\nSelectați masa:',

        'kj_stats_title': '📊 <b>STATISTICI SEARĂ</b>',
        'kj_stats_no_data': 'Nu există date pentru astăzi',

        'kj_vip_confirm_done': '✅ Statut VIP acordat',
        'kj_vip_reject_done': '❌ Cerere VIP respinsă',
        'kj_topup_confirm_done': '✅ Reîncărcare confirmată',
        'kj_topup_reject_done': '❌ Reîncărcare respinsă',
        'kj_order_approved_kj': '✅ Comandă acceptată',
        'kj_order_rejected_kj': '❌ Comandă respinsă',
        'kj_order_completed_kj': '✅ Comandă finalizată',
        'kj_order_deleted_kj': '🗑️ Comandă ștearsă',
        'kj_order_complete_confirm': '✅ Confirmați finalizarea comenzii #{order_id}?',
        'kj_order_delete_confirm': '🗑️ Ștergeți comanda #{order_id}?\nSoldul clientului va fi returnat.',
        'kj_table_closed_alert': '✅ Masă închisă',
        'kj_order_already_processed': '❌ Comandă deja procesată',
        'btn_kj_order_complete': '✅ Finalizat',
        'btn_kj_order_delete': '❌ Șterge',
        'btn_kj_order_replace': '🔄 Înlocuiește',

        'kj_add_order_title': '➕ *ADĂUGARE COMANDĂ*\n\nMasă: {table}\n\nApăsați butonul pentru a căuta melodia:',
        'kj_choose_service_title': '🎵 *ALEGERE SERVICIU*\n\nMelodie: *{song}*\nMasă: *{table}*\n\nSelectați serviciul:',
        'kj_confirm_order_title': (
            '✅ *CONFIRMARE*\n\n'
            'Masă: *{table}*\n'
            'Melodie: *{song}*\n'
            'Serviciu: *{service}*\n'
            'Preț: *{price}*'
        ),
        'kj_order_added': '✅ Comandă adăugată',
        'kj_song_not_found': '❌ Melodia nu a fost găsită',
        'kj_order_not_found': '❌ Comanda nu a fost găsită',
        'kj_replace_order_title': '🔄 *ÎNLOCUIRE MELODIE*\n\nApăsați \'🔍 Caută melodie\' pentru a căuta melodia nouă.',
        'kj_song_replaced': '✅ Melodie înlocuită',
        'btn_kj_find_song': '🔍 Caută melodie',
        'kj_move_order_title': (
            '⬆️ *DEPLASARE COMANDĂ*\n\n'
            '🎵 Melodie: *{song}*\n'
            'Poziție curentă: *{pos}* din *{count}*\n\n'
            'Introduceți noua poziție (1-*{count}*):\n\n'
            '_Apăsați Enter sau butonul \'Confirmare\' după introducere_'
        ),
        'kj_move_position_invalid': '❌ Introduceți un număr mai mare ca 0',
        'kj_move_max_exceeded': '❌ Poziția nu poate fi mai mare de {count}',
        'kj_move_no_orders': '❌ Nu există comenzi pentru deplasare',
        'kj_move_choose': '⬆️ *SELECTAȚI COMANDA PENTRU DEPLASARE*\n\n',
        'kj_order_moved': '✅ Comandă deplasată',
        'btn_kj_search_song': '🔍 Caută melodie',

        'kj_not_vip': '❌ Clientul nu este VIP',
        'kj_bind_info_text': '📋 <b>ATAȘARE CLIENȚI</b>\n\nClienții sunt atașați la local automat la prima comandă.\n\nDupă atașare puteți:\n• Gestiona soldul\n• Acorda statut VIP\n• Bloca clienți\n• Porni chat personal',
        'kj_songs_not_found': '❌ Melodii negăsite.\n\nÎncercați alt query:',
        'kj_search_results_title': '🔍 *REZULTATE CĂUTARE*\n\nMelodii găsite: *{count}*\n\n',
    },
}

def t(lang: str, key: str, **kwargs) -> str:
    lang = lang if lang in STRINGS else 'ru'
    text = STRINGS[lang].get(key) or STRINGS['ru'].get(key, f'[{key}]')
    if kwargs:
        try:
            return text.format(**kwargs)
        except (KeyError, IndexError):
            return text
    return text

def pluralize_tables(n: int, lang: str) -> str:
    if lang == 'ro':
        if n == 1:
            return t(lang, 'tables_1')
        return t(lang, 'tables_0')
    if 11 <= n % 100 <= 14:
        return t(lang, 'tables_0')
    r = n % 10
    if r == 1:
        return t(lang, 'tables_1')
    if 2 <= r <= 4:
        return t(lang, 'tables_2_4')
    return t(lang, 'tables_0')
