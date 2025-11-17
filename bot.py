import telebot
from telebot import types
import math
import paramiko
import os
import logging
from threading import Thread

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ЗАМЕНИТЕ НА ВАШ ТОКЕН
BOT_TOKEN = "YOUR_BOT_TOKEN_HERE"

bot = telebot.TeleBot(BOT_TOKEN)

# КОНФИГУРАЦИЯ SSH
SSH_CONFIG = {
    'hostname': 'your_truenas_ip',  # IP вашего TrueNAS сервера
    'username': 'your_username',    # Пользователь TrueNAS
    'password': os.getenv('TRUENAS_SSH_PASSWORD'),  # Пароль из переменной окружения
    'key_filename': '/path/to/ssh/key',  # ИЛИ путь к SSH ключу
    'port': 22,
    'timeout': 10
}

# КОНФИГУРАЦИЯ БОТА
COMPUTERS_COUNT = 40
COMPUTERS_PER_PAGE = 8

# Временное хранилище
user_states = {}

# Функция для выполнения команды на удаленном сервере
def run_ssh_command(command, pc_number=None):
    """
    Выполняет команду на удаленном сервере через SSH
    """
    try:
        # Создаем SSH клиент
        ssh_client = paramiko.SSHClient()
        ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        
        # Подключаемся к серверу
        connect_kwargs = {
            'hostname': SSH_CONFIG['hostname'],
            'username': SSH_CONFIG['username'],
            'timeout': SSH_CONFIG['timeout']
        }
        
        # Используем либо пароль, либо SSH ключ
        if SSH_CONFIG.get('password'):
            connect_kwargs['password'] = SSH_CONFIG['password']
        elif SSH_CONFIG.get('key_filename'):
            connect_kwargs['key_filename'] = SSH_CONFIG['key_filename']
        
        ssh_client.connect(**connect_kwargs)
        
        # Выполняем команду
        stdin, stdout, stderr = ssh_client.exec_command(command)
        
        # Читаем вывод
        output = stdout.read().decode('utf-8')
        error = stderr.read().decode('utf-8')
        
        # Закрываем соединение
        ssh_client.close()
        
        if error and "Warning" not in error:
            logger.error(f"SSH Error for PC-{pc_number}: {error}")
            return False, error
        else:
            logger.info(f"SSH Command executed successfully for PC-{pc_number}")
            return True, output
            
    except Exception as e:
        logger.error(f"SSH Connection failed: {e}")
        return False, str(e)

# Функция для запуска обновления в отдельном потоке
def start_update_in_thread(chat_id, pc_number, is_mass_update=False):
    """
    Запускает обновление в отдельном потоке чтобы не блокировать бота
    """
    def update_thread():
        try:
            if is_mass_update:
                # Команда для массового обновления
                command = "/path/to/your/update_all_script.sh"
                success, message = run_ssh_command(command, "ALL")
                
                if success:
                    bot.send_message(
                        chat_id,
                        f"✅ **Массовое обновление завершено!**\n"
                        f"Обновлено компьютеров: {COMPUTERS_COUNT}\n"
                        f"Вывод: {message}",
                        parse_mode='Markdown'
                    )
                else:
                    bot.send_message(
                        chat_id,
                        f"❌ **Ошибка массового обновления:**\n{message}",
                        parse_mode='Markdown'
                    )
            else:
                # Команда для обновления конкретного компьютера
                command = f"/path/to/your/update_script.sh {pc_number}"
                success, message = run_ssh_command(command, pc_number)
                
                if success:
                    bot.send_message(
                        chat_id,
                        f"✅ **PC-{pc_number} успешно обновлен!**\n"
                        f"Вывод: {message}",
                        parse_mode='Markdown'
                    )
                else:
                    bot.send_message(
                        chat_id,
                        f"❌ **Ошибка обновления PC-{pc_number}:**\n{message}",
                        parse_mode='Markdown'
                    )
                    
        except Exception as e:
            bot.send_message(
                chat_id,
                f"❌ **Неожиданная ошибка:**\n{str(e)}",
                parse_mode='Markdown'
            )
    
    # Запускаем поток
    thread = Thread(target=update_thread)
    thread.daemon = True
    thread.start()

# Главное меню (без изменений)
@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    
    buttons = [
        types.KeyboardButton('🔄 Обновить датасеты'),
        types.KeyboardButton('📊 Статус обновлений'), 
        types.KeyboardButton('❓ Помощь')
    ]
    
    markup.add(*buttons)
    
    bot.send_message(
        message.chat.id,
        "🤖 Добро пожаловать! Бот для управления обновлением игровых датасетов.\n"
        f"Всего компьютеров: {COMPUTERS_COUNT}",
        reply_markup=markup
    )

# Обработчик кнопки "Обновить датасеты"
@bot.message_handler(func=lambda message: message.text == '🔄 Обновить датасеты')
def show_computers_menu(message):
    user_id = message.chat.id
    user_states[user_id] = {'page': 0}
    send_computers_page(message.chat.id, user_id)

# Функция для отправки страницы с компьютерами (без изменений)
def send_computers_page(chat_id, user_id, edit_message_id=None):
    state = user_states.get(user_id, {'page': 0})
    current_page = state['page']
    
    total_pages = math.ceil(COMPUTERS_COUNT / COMPUTERS_PER_PAGE)
    start_idx = current_page * COMPUTERS_PER_PAGE + 1
    end_idx = min((current_page + 1) * COMPUTERS_PER_PAGE, COMPUTERS_COUNT)
    
    markup = types.InlineKeyboardMarkup(row_width=4)
    
    buttons = []
    for i in range(start_idx, end_idx + 1):
        buttons.append(types.InlineKeyboardButton(f"PC-{i:02d}", callback_data=f"pc_{i}"))
    
    for i in range(0, len(buttons), 4):
        markup.add(*buttons[i:i+4])
    
    nav_buttons = []
    if current_page > 0:
        nav_buttons.append(types.InlineKeyboardButton("◀️ Назад", callback_data=f"page_{current_page-1}"))
    
    nav_buttons.append(types.InlineKeyboardButton(f"{current_page+1}/{total_pages}", callback_data="current_page"))
    
    if current_page < total_pages - 1:
        nav_buttons.append(types.InlineKeyboardButton("Вперед ▶️", callback_data=f"page_{current_page+1}"))
    
    markup.add(*nav_buttons)
    
    action_buttons = [
        types.InlineKeyboardButton("🔄 Обновить ВСЁ", callback_data="update_all"),
        types.InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")
    ]
    markup.add(*action_buttons)
    
    text = (f"🖥️ **Выбор компьютера для обновления**\n"
            f"*Страница {current_page + 1} из {total_pages}*\n"
            f"*Компьютеры {start_idx}-{end_idx} из {COMPUTERS_COUNT}*")
    
    if edit_message_id:
        bot.edit_message_text(
            text, 
            chat_id, 
            edit_message_id, 
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

# Обработчик callback-запросов с реальным выполнением команд
@bot.callback_query_handler(func=lambda call: True)
def handle_callback(call):
    user_id = call.message.chat.id
    message_id = call.message.message_id
    
    if user_id not in user_states:
        user_states[user_id] = {'page': 0}
    
    # Обработка выбора компьютера
    if call.data.startswith('pc_'):
        pc_number = call.data.replace('pc_', '')
        bot.answer_callback_query(call.id, f"Запуск обновления PC-{pc_number}...")
        
        # Отправляем сообщение о начале обновления
        progress_msg = bot.send_message(
            call.message.chat.id,
            f"🔄 **Запуск обновления PC-{pc_number}...**\n"
            f"Пожалуйста, подождите...",
            parse_mode='Markdown'
        )
        
        # Запускаем обновление в отдельном потоке
        start_update_in_thread(call.message.chat.id, pc_number)
    
    # Обработка пагинации
    elif call.data.startswith('page_'):
        page_number = int(call.data.replace('page_', ''))
        user_states[user_id]['page'] = page_number
        send_computers_page(call.message.chat.id, user_id, message_id)
        bot.answer_callback_query(call.id)
    
    # Обработка массового обновления
    elif call.data == 'update_all':
        bot.answer_callback_query(call.id, "Запуск массового обновления...")
        
        # Отправляем сообщение о начале массового обновления
        progress_msg = bot.send_message(
            call.message.chat.id,
            f"🔄 **Запуск массового обновления всех {COMPUTERS_COUNT} компьютеров**\n"
            f"Это может занять несколько минут...",
            parse_mode='Markdown'
        )
        
        # Запускаем массовое обновление в отдельном потоке
        start_update_in_thread(call.message.chat.id, None, is_mass_update=True)
    
    # Возврат в главное меню
    elif call.data == 'main_menu':
        bot.delete_message(call.message.chat.id, call.message.message_id)
        send_welcome(call.message)
        bot.answer_callback_query(call.id)
    
    # Текущая страница
    elif call.data == 'current_page':
        bot.answer_callback_query(call.id)

# Обработчики остальных кнопок (без изменений)
@bot.message_handler(func=lambda message: message.text == '📊 Статус обновлений')
def show_status(message):
    # Здесь можно добавить проверку статуса через SSH
    bot.send_message(
        message.chat.id,
        f"📊 **Статус обновлений**\n\n"
        f"Всего компьютеров: {COMPUTERS_COUNT}\n"
        f"Для получения актуального статуса используется SSH подключение к серверу.",
        parse_mode='Markdown'
    )

@bot.message_handler(func=lambda message: message.text == '❓ Помощь')
def show_help(message):
    bot.send_message(
        message.chat.id,
        f"❓ **Помощь по боту**\n\n"
        f"*Обновление датасетов:*\n"
        f"- Выберите конкретный компьютер\n"
        f"- Или обновите все сразу\n"
        f"- Используйте пагинацию для навигации\n\n"
        f"*Технология:*\n"
        f"- Бот подключается к TrueNAS серверу по SSH\n"
        f"- Запускает скрипты обновления датасетов\n"
        f"*Всего компьютеров в системе: {COMPUTERS_COUNT}*",
        parse_mode='Markdown'
    )

# Запуск бота
if __name__ == "__main__":
    # Проверяем конфигурацию SSH
    if not SSH_CONFIG.get('password') and not SSH_CONFIG.get('key_filename'):
        print("❌ Ошибка: Не настроено SSH подключение!")
        print("Добавьте пароль или путь к SSH ключу в SSH_CONFIG")
        exit(1)
    
    print(f"🤖 Бот запускается...")
    print(f"📊 Конфигурация: {COMPUTERS_COUNT} компьютеров")
    print(f"🔗 SSH подключение: {SSH_CONFIG['hostname']}")
    print("Для остановки нажмите Ctrl+C")
    
    try:
        bot.infinity_polling()
    except Exception as e:
        print(f"Ошибка: {e}")