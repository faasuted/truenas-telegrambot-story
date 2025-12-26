import telebot
from telebot import types
import math
import paramiko
import os
import logging
from threading import Thread
from dotenv import load_dotenv
import tempfile

# Загружаем переменные из .env файла
load_dotenv()

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Загрузка списка разрешенных пользователей
ALLOWED_USER_IDS = list(map(int, os.getenv('ALLOWED_USER_IDS', '').split(','))) if os.getenv('ALLOWED_USER_IDS') else []

# Проверка конфигурации белого списка
if not ALLOWED_USER_IDS:
    print("❌ ВНИМАНИЕ: ALLOWED_USER_IDS не настроен. Доступ открыт для всех!")
else:
    print(f"✅ Белый список пользователей: {len(ALLOWED_USER_IDS)} пользователей")

# Загрузка конфигурации серверов
def load_servers_config():
    """Загружает конфигурацию серверов из переменных окружения"""
    servers_config = {}
    i = 1
    
    while True:
        # Проверяем существование сервера
        host_key = f'SERVER_{i}_HOST'
        if not os.getenv(host_key):
            break  # Больше серверов нет
        
        # Получаем порт, если не указан - используем 22 по умолчанию
        port = os.getenv(f'SERVER_{i}_PORT')
        if port is not None:
            try:
                port = int(port)
            except ValueError:
                logger.warning(f"Неверный порт для сервера {i}, используется порт 22")
                port = 22
        else:
            port = 22  # порт по умолчанию
        
        # Получаем пароль (обязательное поле)
        password = os.getenv(f'SERVER_{i}_PASSWORD')
        if not password:
            logger.error(f"Пароль не указан для сервера {i}. Сервер пропущен.")
            i += 1
            continue
        
        # Получаем настройки IP адресации
        ip_base = os.getenv(f'SERVER_{i}_IP_BASE', '192.168.1.')
        ip_start = int(os.getenv(f'SERVER_{i}_IP_START', 100))
        
        server_config = {
            'name': os.getenv(f'SERVER_{i}_NAME', f'Server {i}'),
            'hostname': os.getenv(host_key),
            'port': port,
            'username': os.getenv(f'SERVER_{i}_USERNAME', 'root'),
            'password': password,
            'computers_count': int(os.getenv(f'SERVER_{i}_COMPUTERS_COUNT', 0)),
            'location': os.getenv(f'SERVER_{i}_LOCATION', 'Unknown'),
            'ip_base': ip_base,
            'ip_start': ip_start
        }
        
        servers_config[f'server_{i}'] = server_config
        i += 1
    
    return servers_config

# Загружаем конфигурацию
SERVERS_CONFIG = load_servers_config()
BOT_TOKEN = os.getenv('BOT_TOKEN')
COMPUTERS_PER_PAGE = int(os.getenv('COMPUTERS_PER_PAGE', 8))

# Проверяем загрузку конфигурации
if not BOT_TOKEN:
    raise ValueError("❌ BOT_TOKEN не найден в .env файле")

if not SERVERS_CONFIG:
    raise ValueError("❌ Не найдено ни одного сервера в .env файле")

if ALLOWED_USER_IDS:
    print(f"🔐 Режим белого списка: {len(ALLOWED_USER_IDS)} пользователей")
else:
    print("⚠️  ВНИМАНИЕ: Белый список не настроен, доступ открыт для всех!")

# Выводим информацию о загруженных серверах
print(f"✅ Загружено серверов: {len(SERVERS_CONFIG)}")
print(f"✅ Компьютеров на странице: {COMPUTERS_PER_PAGE}")
for server_id, config in SERVERS_CONFIG.items():
    print(f"   • {config['name']} - {config['computers_count']} компьютеров")

# Инициализируем бота
bot = telebot.TeleBot(BOT_TOKEN)

# Временное хранилище состояний
user_states = {}

# Функция проверки доступа
def check_access(user_id):
    """Проверяет, есть ли пользователь в белом списке"""
    if not ALLOWED_USER_IDS:  # Если список пустой - доступ для всех
        return True
    return user_id in ALLOWED_USER_IDS

# Декораторы для проверки доступа
def access_check_message(func):
    def wrapper(message):
        if not check_access(message.from_user.id):
            bot.reply_to(message, f"❌ Доступ запрещен. Ваш ID: {message.from_user.id}\n\nДля получения доступа предоставьте этот ID администратору.")
            return
        return func(message)
    return wrapper

def access_check_callback(func):
    def wrapper(call):
        if not check_access(call.from_user.id):
            bot.answer_callback_query(call.id, "❌ Доступ запрещен", show_alert=True)
            return
        return func(call)
    return wrapper

# Функция для преобразования номера компьютера в IP адрес
def number_to_ip(server_config, pc_number):
    """Преобразует номер компьютера в IP адрес согласно настройкам сервера"""
    try:
        pc_num = int(pc_number)
        ip_address = f"{server_config['ip_base']}{server_config['ip_start'] + pc_num}"
        return ip_address
    except ValueError:
        logger.error(f"Неверный номер компьютера: {pc_number}")
        return None

# Функция для выполнения SSH команд
def run_ssh_command(server_config, command):
    """Выполняет команду на удаленном сервере через SSH с использованием пароля"""
    try:
        ssh_client = paramiko.SSHClient()
        ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        
        # Параметры подключения
        connect_kwargs = {
            'hostname': server_config['hostname'],
            'username': server_config['username'],
            'password': server_config['password'],
            'port': server_config.get('port', 22),
            'timeout': 30
        }
        
        logger.info(f"Подключение к {server_config['name']}")
        ssh_client.connect(**connect_kwargs)
        
        stdin, stdout, stderr = ssh_client.exec_command(command)
        
        # Объединяем stdout и stderr в один вывод
        output = stdout.read().decode('utf-8')
        error = stderr.read().decode('utf-8')
        
        ssh_client.close()
        
        # Возвращаем полный вывод (stdout + stderr)
        full_output = output + ("\n" + error if error else "")
        return True, full_output.strip()
            
    except Exception as e:
        error_msg = f"SSH Connection failed to {server_config['name']}: {e}"
        logger.error(error_msg)
        return False, error_msg

# Функция для отправки результата (текстом или файлом)
def send_result(chat_id, server_config, pc_number, output, force=False):
    """Отправляет результат выполнения команды, при большом выводе - файлом"""
    server_name = server_config['name']
    
    if pc_number:
        ip_address = number_to_ip(server_config, pc_number)
        title = f"🖥️ **{server_name}**\nPC-{pc_number} ({ip_address})\nРежим: {'принудительный' if force else 'обычный'}\n\n"
    else:
        title = f"🖥️ **{server_name}**\nМассовое обновление\nКомпьютеров: {server_config['computers_count']}\n\n"
    
    # Если вывод слишком длинный, отправляем файлом
    if len(output) > 4000:
        try:
            # Создаем временный файл
            with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False, encoding='utf-8') as f:
                f.write(output)
                temp_filename = f.name
            
            # Отправляем файл
            with open(temp_filename, 'rb') as file:
                bot.send_document(
                    chat_id,
                    file,
                    caption=title + "Результат в файле",
                    parse_mode='Markdown'
                )
            
            # Удаляем временный файл
            os.unlink(temp_filename)
            
        except Exception as e:
            logger.error(f"Ошибка при отправке файла: {e}")
            # Если не удалось отправить файл, отправляем первые 4000 символов
            truncated_output = output[:4000] + "\n\n... [вывод обрезан, слишком длинный]"
            bot.send_message(chat_id, title + f"```\n{truncated_output}\n```", parse_mode='Markdown')
    else:
        # Отправляем вывод как сообщение
        if output:
            bot.send_message(chat_id, title + f"```\n{output}\n```", parse_mode='Markdown')
        else:
            bot.send_message(chat_id, title + "Вывод пуст", parse_mode='Markdown')

# Функция для запуска обновления в отдельном потоке
def start_update_in_thread(chat_id, server_id, pc_number=None, force=False):
    """Запускает обновление в отдельном потоке"""
    def update_thread():
        server_config = SERVERS_CONFIG[server_id]
        
        if pc_number:
            # Обновление конкретного компьютера
            ip_address = number_to_ip(server_config, pc_number)
            if not ip_address:
                bot.send_message(
                    chat_id,
                    f"❌ **Ошибка**\nНеверный номер компьютера: {pc_number}",
                    parse_mode='Markdown'
                )
                return
            
            if force:
                command = f"sudo ./fre.sh --force {ip_address}"
            else:
                command = f"sudo ./fre.sh {ip_address}"
            
            success, output = run_ssh_command(server_config, command)
            
            if success:
                send_result(chat_id, server_config, pc_number, output, force)
            else:
                bot.send_message(
                    chat_id,
                    f"❌ **Ошибка подключения**\n"
                    f"Сервер: {server_config['name']}\n"
                    f"PC-{pc_number} ({ip_address})\n\n"
                    f"Ошибка: {output}",
                    parse_mode='Markdown'
                )
        else:
            # Массовое обновление сервера
            command = "sudo ./fre.sh --all"
            success, output = run_ssh_command(server_config, command)
            
            if success:
                send_result(chat_id, server_config, None, output, False)
            else:
                bot.send_message(
                    chat_id,
                    f"❌ **Ошибка подключения**\n"
                    f"Сервер: {server_config['name']}\n\n"
                    f"Ошибка: {output}",
                    parse_mode='Markdown'
                )
    
    thread = Thread(target=update_thread)
    thread.daemon = True
    thread.start()

# Функция для показа меню выбора режима обновления
def show_update_mode_menu(chat_id, server_id, pc_number, message_id=None):
    """Показывает меню выбора режима обновления для конкретного компьютера"""
    server_config = SERVERS_CONFIG[server_id]
    ip_address = number_to_ip(server_config, pc_number)
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    
    # Кнопки выбора режима (убран "Главное меню")
    buttons = [
        types.InlineKeyboardButton("🔄 Обычное обновление", callback_data=f"update_normal:{server_id}:{pc_number}"),
        types.InlineKeyboardButton("⚠️ Принудительное обновление", callback_data=f"update_force_confirm:{server_id}:{pc_number}"),
        types.InlineKeyboardButton("◀️ Назад к компьютерам", callback_data=f"back_to_computers:{server_id}"),
    ]
    
    markup.add(buttons[0], buttons[1])
    markup.add(buttons[2])  # Только кнопка "Назад к компьютерам"
    
    text = (f"🖥️ **Выбор режима обновления**\n\n"
            f"Сервер: {server_config['name']}\n"
            f"Компьютер: PC-{pc_number}\n"
            f"IP адрес: {ip_address}\n\n"
            f"*Обычное обновление* - стандартный процесс обновления\n"
            f"*Принудительное обновление* - может привести к нестабильности!")
    
    if message_id:
        bot.edit_message_text(
            text,
            chat_id,
            message_id,
            reply_markup=markup,
            parse_mode='Markdown'
        )
    else:
        bot.send_message(
            chat_id,
            text,
            reply_markup=markup,
            parse_mode='Markdown'
        )

# Функция для подтверждения принудительного обновления
def show_force_confirmation(chat_id, server_id, pc_number, message_id):
    """Показывает подтверждение для принудительного обновления"""
    server_config = SERVERS_CONFIG[server_id]
    ip_address = number_to_ip(server_config, pc_number)
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    
    buttons = [
        types.InlineKeyboardButton("✅ Да, запустить принудительно", callback_data=f"force_update:{server_id}:{pc_number}"),
        types.InlineKeyboardButton("❌ Отмена", callback_data=f"back_to_mode:{server_id}:{pc_number}")
    ]
    
    markup.add(buttons[0])
    markup.add(buttons[1])
    
    warning_text = (f"⚠️ **ВНИМАНИЕ: Принудительное обновление!**\n\n"
                    f"Сервер: {server_config['name']}\n"
                    f"Компьютер: PC-{pc_number}\n"
                    f"IP адрес: {ip_address}\n\n"
                    f"Закройте на выбранном компьютере\n"
                    f"все открытые приложения, лаунчеры и игры!\n"
                    f"**Иначе обновление может привести к:**\n"
                    f"• Вылету игр\n"
                    f"• Ошибкам диска\n"
                    f"• Непредсказуемому поведению\n\n"
                    f"Вы уверены, что хотите продолжить?")
    
    bot.edit_message_text(
        warning_text,
        chat_id,
        message_id,
        reply_markup=markup,
        parse_mode='Markdown'
    )

# Главное меню
@bot.message_handler(commands=['start', 'help'])
@access_check_message
def send_welcome(message):
    print(f"👤 Пользователь {message.from_user.id} ({message.from_user.first_name}) запустил бота")
    
    total_computers = sum(server['computers_count'] for server in SERVERS_CONFIG.values())
    
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    buttons = [
        types.KeyboardButton('🔄 Обновить датасеты'),
        types.KeyboardButton('📊 Статус всех серверов'),
        types.KeyboardButton('❓ Помощь')
    ]
    markup.add(*buttons)
    
    # Создаем информацию о серверах для отображения (без портов)
    servers_info = ""
    for server_id, config in list(SERVERS_CONFIG.items())[:3]:
        servers_info += f"• {config['name']}\n"
    
    if len(SERVERS_CONFIG) > 3:
        servers_info += f"• ... и еще {len(SERVERS_CONFIG) - 3} серверов\n"
    
    bot.send_message(
        message.chat.id,
        f"🤖 **Бот управления TrueNAS серверами**\n\n"
        f"Серверов: {len(SERVERS_CONFIG)}\n"
        f"Компьютеров: {total_computers}\n\n"
        f"{servers_info}",
        reply_markup=markup,
        parse_mode='Markdown'
    )

# Команда для получения своего ID
@bot.message_handler(commands=['myid'])
def show_my_id(message):
    user_id = message.from_user.id
    bot.reply_to(
        message,
        f"🆔 Ваш Telegram ID: `{user_id}`\n\n"
        f"Для получения доступа к боту предоставьте этот ID администратору.",
        parse_mode='Markdown'
    )

# Функции меню
def send_servers_menu(chat_id, page=0, edit_message_id=None):
    """Отправляет меню выбора сервера"""
    servers_list = list(SERVERS_CONFIG.items())
    servers_per_page = 6
    total_pages = math.ceil(len(servers_list) / servers_per_page)
    
    start_idx = page * servers_per_page
    end_idx = min((page + 1) * servers_per_page, len(servers_list))
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    
    # Кнопки серверов
    for server_id, server_config in servers_list[start_idx:end_idx]:
        btn_text = f"{server_config['name']} ({server_config['computers_count']})"
        markup.add(types.InlineKeyboardButton(btn_text, callback_data=f"select_server:{server_id}"))
    
    # Навигация
    nav_buttons = []
    if page > 0:
        nav_buttons.append(types.InlineKeyboardButton("◀️", callback_data=f"servers_page:{page-1}"))
    
    nav_buttons.append(types.InlineKeyboardButton(f"{page+1}/{total_pages}", callback_data="current_page"))
    
    if page < total_pages - 1:
        nav_buttons.append(types.InlineKeyboardButton("▶️", callback_data=f"servers_page:{page+1}"))
    
    if nav_buttons:
        markup.add(*nav_buttons)
    
    # Убрана кнопка "Главное меню"
    
    text = f"🏢 **Выбор сервера**\n*Страница {page+1} из {total_pages}*\n\n"
    
    for server_id, server_config in servers_list[start_idx:end_idx]:
        text += f"• {server_config['name']} - {server_config['computers_count']} компьютеров\n"
    
    if edit_message_id:
        bot.edit_message_text(text, chat_id, edit_message_id, reply_markup=markup, parse_mode='Markdown')
    else:
        bot.send_message(chat_id, text, reply_markup=markup, parse_mode='Markdown')

def send_computers_menu(chat_id, server_id, page=0, edit_message_id=None):
    """Отправляет меню компьютеров для выбранного сервера"""
    server_config = SERVERS_CONFIG[server_id]
    total_computers = server_config['computers_count']
    
    start_idx = page * COMPUTERS_PER_PAGE + 1
    end_idx = min((page + 1) * COMPUTERS_PER_PAGE, total_computers)
    
    total_pages = math.ceil(total_computers / COMPUTERS_PER_PAGE)
    
    markup = types.InlineKeyboardMarkup(row_width=4)
    
    # Кнопки компьютеров
    buttons = []
    for i in range(start_idx, end_idx + 1):
        ip_address = number_to_ip(server_config, i)
        button_text = f"PC-{i:02d}" if ip_address else f"PC-{i:02d}"
        buttons.append(types.InlineKeyboardButton(button_text, callback_data=f"select_pc:{server_id}:{i}"))
    
    for i in range(0, len(buttons), 4):
        markup.add(*buttons[i:i+4])
    
    # Навигация
    nav_buttons = []
    if page > 0:
        nav_buttons.append(types.InlineKeyboardButton("◀️", callback_data=f"computers_page:{server_id}:{page-1}"))
    
    nav_buttons.append(types.InlineKeyboardButton(f"{page+1}/{total_pages}", callback_data="current_page"))
    
    if page < total_pages - 1:
        nav_buttons.append(types.InlineKeyboardButton("▶️", callback_data=f"computers_page:{server_id}:{page+1}"))
    
    markup.add(*nav_buttons)
    
    # Действия (убран "Главное меню")
    action_buttons = [
        types.InlineKeyboardButton("🔄 Обновить все компьютеры", callback_data=f"update_server:{server_id}"),
        types.InlineKeyboardButton("◀️ К серверам", callback_data="back_to_servers"),
    ]
    markup.add(action_buttons[0])
    markup.add(action_buttons[1])  # Только кнопка "К серверам"
    
    text = (f"🖥️ **{server_config['name']}**\n"
            f"*Компьютеры {start_idx}-{end_idx} из {total_computers}*\n"
            f"*Расположение: {server_config['location']}*")
    
    if edit_message_id:
        bot.edit_message_text(text, chat_id, edit_message_id, reply_markup=markup, parse_mode='Markdown')
    else:
        bot.send_message(chat_id, text, reply_markup=markup, parse_mode='Markdown')

# Обработчики сообщений
@bot.message_handler(func=lambda message: message.text == '🔄 Обновить датасеты')
@access_check_message
def show_servers_menu(message):
    send_servers_menu(message.chat.id)

@bot.message_handler(func=lambda message: message.text == '📊 Статус всех серверов')
@access_check_message
def show_global_status(message):
    status_text = "📊 **Статус всех серверов**\n\n"
    
    for server_id, config in SERVERS_CONFIG.items():
        # Упрощенная проверка доступности сервера
        try:
            test_command = "echo 'test'"
            success, _ = run_ssh_command(config, test_command)
            status_icon = "✅" if success else "❌"
            status_text_online = "Онлайн" if success else "Офлайн"
        except:
            status_icon = "❌"
            status_text_online = "Офлайн"
        
        status_text += f"{status_icon} {config['name']}\n"
        status_text += f"   Компьютеров: {config['computers_count']}\n"
        status_text += f"   Статус: {status_text_online}\n"
        status_text += f"   Расположение: {config['location']}\n\n"
    
    bot.send_message(message.chat.id, status_text, parse_mode='Markdown')

@bot.message_handler(func=lambda message: message.text == '❓ Помощь')
@access_check_message
def show_help(message):
    total_computers = sum(server['computers_count'] for server in SERVERS_CONFIG.values())
    
    help_text = (
        f"❓ **Помощь по боту**\n\n"
        f"*Для чего он нужен?*\n"
        f"- Обновляет диски c играми (D:\) на компьютерах\n"
        f"- Если игра обновлена на сервере, а на ПК нет\n"
        f"- Не является инструментом обновления игр на сервере\n\n"
        f"*Обновление:*\n"
        f"- Выберите сервер\n"
        f"- Выберите конкретный компьютер\n"
        f"- Выберите режим обновления (обычный/принудительный)\n"
        f"- Или обновите все ПК сразу\n\n"
        f"*Обычное обновление*\n"
        f"- Проверяет занятость ПК.\n"
        f"- Обновляет только если ПК выключен.\n\n"
        f"*Принудительное обновление*\n"
        f"- Принудительный режим доступен только для конкретных ПК\n"
        f"- Обновляет даже если ПК занят.\n"
        f"- Может привести к вылетам игр и ошибкам.\n"
        f"- Использовать только если все лаунчеры, игры и программы закрыты.\n\n"
        f"*Результаты выполнения:*\n"
        f"- Результат обновления отправляется сообщением\n"
        f"- Если текста много - отправляется файлом\n\n"
    )
    
    bot.send_message(message.chat.id, help_text, parse_mode='Markdown')

# Обработчики callback'ов
@bot.callback_query_handler(func=lambda call: True)
@access_check_callback
def handle_callback(call):
    user_id = call.message.chat.id
    message_id = call.message.message_id
    
    try:
        # Выбор сервера
        if call.data.startswith('select_server:'):
            server_id = call.data.replace('select_server:', '', 1)
            if server_id in SERVERS_CONFIG:
                user_states[user_id] = {'current_server': server_id, 'computers_page': 0}
                send_computers_menu(call.message.chat.id, server_id, 0, message_id)
            else:
                bot.answer_callback_query(call.id, "❌ Сервер не найден")
        
        # Пагинация серверов
        elif call.data.startswith('servers_page:'):
            page = int(call.data.replace('servers_page:', '', 1))
            send_servers_menu(call.message.chat.id, page, message_id)
        
        # Пагинация компьютеров
        elif call.data.startswith('computers_page:'):
            parts = call.data.replace('computers_page:', '', 1).split(':')
            if len(parts) == 2:
                server_id = parts[0]
                page = int(parts[1])
                if server_id in SERVERS_CONFIG:
                    user_states[user_id] = {'current_server': server_id, 'computers_page': page}
                    send_computers_menu(call.message.chat.id, server_id, page, message_id)
                else:
                    bot.answer_callback_query(call.id, "❌ Сервер не найден")
        
        # Выбор компьютера - показываем меню выбора режима
        elif call.data.startswith('select_pc:'):
            parts = call.data.replace('select_pc:', '', 1).split(':')
            if len(parts) == 2:
                server_id = parts[0]
                pc_number = parts[1]
                if server_id in SERVERS_CONFIG:
                    bot.answer_callback_query(call.id, f"Выбран PC-{pc_number}")
                    show_update_mode_menu(call.message.chat.id, server_id, pc_number, message_id)
                else:
                    bot.answer_callback_query(call.id, "❌ Сервер не найден")
        
        # Обычное обновление - сразу запускаем
        elif call.data.startswith('update_normal:'):
            parts = call.data.replace('update_normal:', '', 1).split(':')
            if len(parts) == 2:
                server_id = parts[0]
                pc_number = parts[1]
                if server_id in SERVERS_CONFIG:
                    ip_address = number_to_ip(SERVERS_CONFIG[server_id], pc_number)
                    bot.answer_callback_query(call.id, f"Запуск обычного обновления PC-{pc_number} ({ip_address})...")
                    start_update_in_thread(call.message.chat.id, server_id, pc_number, force=False)
                else:
                    bot.answer_callback_query(call.id, "❌ Сервер не найден")
        
        # Подтверждение принудительного обновления
        elif call.data.startswith('update_force_confirm:'):
            parts = call.data.replace('update_force_confirm:', '', 1).split(':')
            if len(parts) == 2:
                server_id = parts[0]
                pc_number = parts[1]
                if server_id in SERVERS_CONFIG:
                    show_force_confirmation(call.message.chat.id, server_id, pc_number, message_id)
                else:
                    bot.answer_callback_query(call.id, "❌ Сервер не найден")
        
        # Запуск принудительного обновления после подтверждения
        elif call.data.startswith('force_update:'):
            parts = call.data.replace('force_update:', '', 1).split(':')
            if len(parts) == 2:
                server_id = parts[0]
                pc_number = parts[1]
                if server_id in SERVERS_CONFIG:
                    ip_address = number_to_ip(SERVERS_CONFIG[server_id], pc_number)
                    bot.answer_callback_query(call.id, f"Запуск принудительного обновления PC-{pc_number} ({ip_address})...")
                    start_update_in_thread(call.message.chat.id, server_id, pc_number, force=True)
                else:
                    bot.answer_callback_query(call.id, "❌ Сервер не найден")
        
        # Возврат к выбору режима обновления
        elif call.data.startswith('back_to_mode:'):
            parts = call.data.replace('back_to_mode:', '', 1).split(':')
            if len(parts) == 2:
                server_id = parts[0]
                pc_number = parts[1]
                if server_id in SERVERS_CONFIG:
                    show_update_mode_menu(call.message.chat.id, server_id, pc_number, message_id)
                else:
                    bot.answer_callback_query(call.id, "❌ Сервер не найден")
        
        # Возврат к списку компьютеров
        elif call.data.startswith('back_to_computers:'):
            server_id = call.data.replace('back_to_computers:', '', 1)
            if server_id in SERVERS_CONFIG:
                user_states[user_id] = {'current_server': server_id, 'computers_page': 0}
                send_computers_menu(call.message.chat.id, server_id, 0, message_id)
            else:
                bot.answer_callback_query(call.id, "❌ Сервер не найден")
        
        # Обновление всего сервера
        elif call.data.startswith('update_server:'):
            server_id = call.data.replace('update_server:', '', 1)
            if server_id in SERVERS_CONFIG:
                server_config = SERVERS_CONFIG[server_id]
                bot.answer_callback_query(call.id, f"Массовое обновление на {server_config['name']}...")
                start_update_in_thread(call.message.chat.id, server_id)
            else:
                bot.answer_callback_query(call.id, "❌ Сервер не найден")
        
        # Возврат к серверам
        elif call.data == 'back_to_servers':
            send_servers_menu(call.message.chat.id, 0, message_id)
        
        # Текущая страница (ничего не делаем)
        elif call.data == 'current_page':
            bot.answer_callback_query(call.id)
    
    except Exception as e:
        logger.error(f"Ошибка обработки callback: {e}")
        bot.answer_callback_query(call.id, "❌ Произошла ошибка")

# Запуск бота
if __name__ == "__main__":
    print(f"🤖 Бот запускается...")
    print(f"📊 Серверов: {len(SERVERS_CONFIG)}")
    print(f"🔧 Компьютеров на странице: {COMPUTERS_PER_PAGE}")
    print("🔐 Используется аутентификация по паролю")
    print("🔄 Скрипт обновления: sudo ./fre.sh")
    print("📄 Большие выводы отправляются как .txt файлы")
    print("👤 Система белого списка активна")
    print("Для остановки нажмите Ctrl+C")
    
    try:
        bot.infinity_polling()
    except Exception as e:
        print(f"Ошибка: {e}")