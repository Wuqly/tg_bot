import telebot
from telebot import types
from docx import Document
import logging
import sqlite3
import requests
import time
from APITOKEN import TOKEN
from ADMIN_ID import ID

bot = telebot.TeleBot(TOKEN, parse_mode='HTML')

url = "https://api.telegram.org/bot/getMe"
params = {}


def init_db():
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (id INTEGER PRIMARY KEY, username TEXT, telegram_id INTEGER, is_blocked INTEGER DEFAULT 0, needs_restart BOOLEAN DEFAULT 0, current_exam TEXT)''')
    conn.commit()
    conn.close()
init_db()


def make_telegram_request(url, params):
    while True:
        response = requests.get(url, params=params)
        if response.status_code == 429:
            retry_after = int(response.headers.get('Retry-After', 5))
            print(f"Too Many Requests: Retrying after {retry_after} seconds")
            time.sleep(retry_after)
        elif response.status_code == 200:
            return response.json()
        else:
            print(f"Request failed with status code {response.status_code}")
            response.raise_for_status()

try:
    result = make_telegram_request(url, params)
    print(result)
except Exception as e:
    print(f"An error occurred: {e}")

class RateLimiter:
    def __init__(self, max_requests, period):
        self.max_requests = max_requests
        self.period = period
        self.request_times = []

    def allow_request(self):
        current_time = time.time()
        self.request_times = [t for t in self.request_times if t > current_time - self.period]
        if len(self.request_times) < self.max_requests:
            self.request_times.append(current_time)
            return True, 0
        else:
            wait_time = self.period - (current_time - self.request_times[0])
            return False, wait_time
rate_limiter = RateLimiter(max_requests=70, period=60) 


def load_questions_from_docx(filename):
    document = Document(filename)
    qa_pairs = []
    current_question = None
    current_answer = []

    for para in document.paragraphs:
        text = para.text.strip()
        if text.startswith("Вопрос"):
            if current_question:
                qa_pairs.append((current_question, "\n".join(current_answer)))
                current_answer = []
            current_question = text
        else:
            current_answer.append(text)

    if current_question:
        qa_pairs.append((current_question, "\n".join(current_answer)))
    return qa_pairs

    
def read_file_txt(file_path):
    with open(file_path, 'r', encoding='utf- ') as file:
        return file.read()


available_files = {
#    "Вопросы ПМ05 21.06.24": '/opt/tgbot/file/Вопросы 2ИСиП4 ПМ05 21.06.2024.docx',
    "Вопросы ПМ10 27.06.24": '/opt/tgbot/file/Вопросы_ПМ10_27_06_24.docx',
}

available_files_txt = {
    "Пример импорта": '/opt/tgbot/file/Пример импорта.txt',
    "Пример расчёта общей стоимости при формировании заказа": '/opt/tgbot/file/Пример расчета стоимости.txt'

}

exams = {
#    "Экзамен ПМ05 21.06.24": load_questions_from_docx(available_files["Вопросы ПМ05 21.06.24"]),
    "Экзамен ПМ10 27.06.24": load_questions_from_docx(available_files["Вопросы ПМ10 27.06.24"]),
#    "Дэмоэкзамен": read_file_txt(available_files_txt["Пример импорта"]),
}

current_exam = []

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('bot.log'),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)



def add_user_exam(user_id, exam_name):
    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET current_exam = ? WHERE telegram_id = ?", (exam_name, user_id))
    conn.commit()
    conn.close()

def get_all_users():
    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    cursor.execute("SELECT telegram_id FROM users")
    users = cursor.fetchall()
    conn.close()
    return [user[0] for user in users]

def get_users_data():
    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    cursor.execute("SELECT id, telegram_id, username, is_blocked, needs_restart FROM users")
    rows = cursor.fetchall()
    conn.close()
    return rows

def check_user_ban(user_id):
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    c.execute("SELECT is_blocked FROM users WHERE telegram_id = ?", (user_id,))
    result = c.fetchone()
    conn.close()
    if result:
        return result[0]  
    return None  

def check_user_exists(user_id):
    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM users WHERE telegram_id = ?", (user_id,))
    exists = cursor.fetchone()[0] > 0
    conn.close()
    return exists

def add_user_to_db(user_id, username):
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE telegram_id = ?", (user_id,))
    user = c.fetchone()
    if not user:
        c.execute("INSERT INTO users (username, telegram_id, is_blocked, needs_restart, current_exam) VALUES (?, ?, ?, ?, ?)",
                  (username, user_id, False, False, None)) 
        conn.commit()
    elif user[1] != username:
        c.execute("UPDATE users SET username = ? WHERE telegram_id = ?", (username, user_id))
        conn.commit()
    conn.close()

def set_restart_flag_for_all_users():
    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET needs_restart = 1")
    conn.commit()
    conn.close()


def get_user_exam(user_id):
    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    cursor.execute("SELECT current_exam FROM users WHERE telegram_id = ?", (user_id,))
    result = cursor.fetchone()
    conn.close()
    return result[0] if result else None

def clear_restart_flag(user_id):
    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET needs_restart = 0 WHERE telegram_id = ?", (user_id,))
    conn.commit()
    conn.close()

@bot.message_handler(commands=['users'])
def users(message):
    users_data = get_users_data()
    allowed, wait_time = rate_limiter.allow_request()
    user_id  = message.from_user.id
    if allowed:
        if user_id  in ID:
            if not users_data:
                logger.info(f"{message.from_user.username, message.from_user.first_name, message.from_user.id} посмотрел список пользователей")
                bot.reply_to(message, "Таблица пользователей пуста.")
                return

            total_users = len(users_data)
            logger.info(f"{message.from_user.username, message.from_user.first_name, message.from_user.id} посмотрел список пользователей")
            message_text = f'<b>Таблица пользователей (всего: {total_users}):</b>\n'
            for row in users_data:

                telegram_id = row[1]
                username = row[2]
                if username:
                    message_text += f'{row}<a href="tg://user?id={telegram_id}"> {username}</a>\n'
                else:
                    message_text += f'{row}<a href="tg://user?id={telegram_id}"> {username}</a> (нет username)\n'
            bot.reply_to(message, message_text, parse_mode='HTML')
        else:
            logger.info(f"{message.from_user.username, message.from_user.first_name, message.from_user.id} пытался выполнить команду '{message.text}'")
            bot.send_message(message.chat.id, "У вас нет прав для выполнения этой команды.")
    else:  
        bot.send_message(message.chat.id, f"Большое количество запросов, отправьте сообщение через {wait_time:.2f} секунд")
        time.sleep(wait_time)
        return

@bot.message_handler(commands=['b'])
def block_user(message):
    user_id = message.from_user.id
    allowed, wait_time = rate_limiter.allow_request()
    if allowed:
        if user_id in ID:  
            args = message.text.split()
            if len(args) < 2:
                bot.send_message(message.chat.id, "Пожалуйста, укажите ID пользователя или username после команды /block.")
                return
            
            identifier_value = args[1]
            
            conn = sqlite3.connect('users.db')
            c = conn.cursor()
            c.execute("SELECT * FROM users WHERE telegram_id = ?", (identifier_value,))
            user = c.fetchone()
            if user is None:
                c.execute("SELECT * FROM users WHERE username = ?", (identifier_value,))
                user = c.fetchone()
            
            if user is None:
                logger.info(f"{message.from_user.username, message.from_user.first_name, message.from_user.id} такого пользователя не существует '{identifier_value}', выполнил команду '{message.text}'")
                bot.send_message(message.chat.id, f"Пользователя {identifier_value} не существует.")
            else:
                if isinstance(identifier_value, int) or (isinstance(identifier_value, str) and identifier_value.isdigit()):  
                    c.execute("UPDATE users SET is_blocked = 1 WHERE telegram_id = ?", (identifier_value,))
                else:
                    c.execute("UPDATE users SET is_blocked = 1 WHERE username = ?", (identifier_value,))
                
                conn.commit()
                logger.info(f"{message.from_user.username, message.from_user.first_name, message.from_user.id} заблокировал {identifier_value}")
                bot.send_message(message.chat.id, f"Пользователь {identifier_value} заблокирован.")
                conn.close()
        else:
            logger.info(f"{message.from_user.username, message.from_user.first_name, message.from_user.id} пытался выполнить команду '{message.text}'")
            bot.send_message(message.chat.id, "У вас нет прав для выполнения этой команды.")
    else:  
        bot.send_message(message.chat.id, f"Большое количество запросов, отправьте сообщение через {wait_time:.2f} секунд")
        time.sleep(wait_time)
        return

@bot.message_handler(commands=['unb'])
def unblock_user(message):
    user_id = message.from_user.id
    allowed, wait_time = rate_limiter.allow_request()
    if allowed:
        if user_id in ID:  
            args = message.text.split()
            if len(args) < 2:
                bot.send_message(message.chat.id, "Пожалуйста, укажите ID пользователя или username после команды /unb.")
                return
            
            identifier_value = args[1]
            
            conn = sqlite3.connect('users.db')
            c = conn.cursor()
            c.execute("SELECT * FROM users WHERE telegram_id = ?", (identifier_value,))
            user = c.fetchone()

            if user is None:

                c.execute("SELECT * FROM users WHERE username = ?", (identifier_value,))
                user = c.fetchone()

            if user is None:
                logger.info(f"{message.from_user.username, message.from_user.first_name, message.from_user.id} такого пользователя не существует '{identifier_value}', выполнил команду '{message.text}'")
                bot.send_message(message.chat.id, f"Пользователя {identifier_value} не существует.")
            else:
                if isinstance(identifier_value, int) or (isinstance(identifier_value, str) and identifier_value.isdigit()): 
                    c.execute("UPDATE users SET is_blocked = 0 WHERE telegram_id = ?", (identifier_value,))
                else:
                    c.execute("UPDATE users SET is_blocked = 0 WHERE username = ?", (identifier_value,))
                
                conn.commit()
                logger.info(f"{message.from_user.username, message.from_user.first_name, message.from_user.id} разбанил {identifier_value}")
                bot.send_message(message.chat.id, f"Пользователь {identifier_value} разбанен.")
                conn.close()
                
        else:
            logger.info(f"{message.from_user.username, message.from_user.first_name, message.from_user.id} пытался выполнить команду '{message.text}'")
            bot.send_message(message.chat.id, "У вас нет прав для выполнения этой команды.")
    else:  
        bot.send_message(message.chat.id, f"Большое количество запросов, отправьте сообщение через {wait_time:.2f} секунд")
        time.sleep(wait_time)
        return

@bot.message_handler(commands=['del'])
def delete_user(message):
    user_id = message.from_user.id
    allowed, wait_time = rate_limiter.allow_request()
    if allowed:
        if user_id in ID:  
            args = message.text.split()
            if len(args) < 2:
                bot.send_message(message.chat.id, "Пожалуйста, укажите ID пользователя или username после команды /del.")
                return
            
            identifier_value = args[1]
            
            conn = sqlite3.connect('users.db')
            c = conn.cursor()
            c.execute("SELECT * FROM users WHERE telegram_id = ?", (identifier_value,))
            user = c.fetchone()
            if user is None:
                c.execute("SELECT * FROM users WHERE username = ?", (identifier_value,))
                user = c.fetchone()
            
            if user is None:
                logger.info(f"{message.from_user.username, message.from_user.first_name, message.from_user.id} такого пользователя не существует '{identifier_value}', выполнил команду '{message.text}'")
                bot.send_message(message.chat.id, f"Пользователя {identifier_value} не существует.")
            else:
                if isinstance(identifier_value, int) or (isinstance(identifier_value, str) and identifier_value.isdigit()): 
                    c.execute("DELETE FROM users WHERE telegram_id = ?", (identifier_value,))
                else:
                    c.execute("DELETE FROM users WHERE username = ?", (identifier_value,))
                
                conn.commit()
                logger.info(f"{message.from_user.username, message.from_user.first_name, message.from_user.id} удалил {identifier_value}")
                bot.send_message(message.chat.id, f"Пользователь {identifier_value} удален из базы данных.")
                conn.close()
        else:
            logger.info(f"{message.from_user.username, message.from_user.first_name, message.from_user.id} пытался выполнить команду '{message.text}'")
            bot.send_message(message.chat.id, "У вас нет прав для выполнения этой команды.")
    else:  
        bot.send_message(message.chat.id, f"Большое количество запросов, отправьте сообщение через {wait_time:.2f} секунд")
        time.sleep(wait_time)
        return


@bot.message_handler(commands=['start'])
def start(message):
    user_id = message.from_user.id
    username = message.from_user.username

    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    cursor.execute("SELECT needs_restart FROM users WHERE telegram_id = ?", (user_id,))
    result = cursor.fetchone()

    if check_user_ban(user_id):
        bot.send_message(message.chat.id, f"Вы заблокированы")
        return

    if result and result[0]:
        clear_restart_flag(user_id)

    if not check_user_exists(user_id):
        add_user_to_db(user_id, username)
        logger.info(f"{message.from_user.username, message.from_user.first_name, message.from_user.id} зарегистрировался")

    try:
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
        for exam in exams.keys():
            markup.row(types.KeyboardButton(exam))
        logger.info(f"{message.from_user.username, message.from_user.first_name, message.from_user.id} запускает бота")
        bot.send_message(message.chat.id, "Выберите экзамен:", reply_markup=markup)
    except Exception as e:
        logger.error(f"Error processing command {message.text}: {e}")
        bot.send_message(message.chat.id, "Произошла ошибка. Пожалуйста, попробуйте позже.")
    finally:
        conn.close()

@bot.message_handler(commands=['switch'])
def switch(message):
    user_id = message.from_user.id
    username = message.from_user.username

    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    cursor.execute("SELECT needs_restart FROM users WHERE telegram_id = ?", (user_id,))
    result = cursor.fetchone()

    if check_user_ban(user_id):
        bot.send_message(message.chat.id, f"Вы заблокированы")
        return

    if result and result[0]:
        bot.send_message(message.chat.id, "Бот был обновлен. Пожалуйста, перезапустите бота командой /start для получения новой версии.")
        conn.close()
        return

    if not check_user_exists(user_id):
        add_user_to_db(user_id, username)
        logger.info(f"{message.from_user.username, message.from_user.first_name, message.from_user.id} зарегистрировался")

    try:
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
        for exam in exams.keys():
            markup.row(types.KeyboardButton(exam))
        logger.info(f"{message.from_user.username, message.from_user.first_name, message.from_user.id} меняет экзамен")
        bot.send_message(message.chat.id, "Выберите экзамен:", reply_markup=markup)
    except Exception as e:
        logger.error(f"Error processing command {message.text}: {e}")
        bot.send_message(message.chat.id, "Произошла ошибка. Пожалуйста, попробуйте позже.")
    finally:
        conn.close()

@bot.message_handler(func=lambda message: message.text in exams.keys())
def select_exam(message):
    user_id = message.from_user.id
    username = message.from_user.username
    exam_name = message.text

    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    cursor.execute("SELECT needs_restart FROM users WHERE telegram_id = ?", (user_id,))
    result = cursor.fetchone()

    if result and result[0]:
        bot.send_message(message.chat.id, "Бот был обновлен. Пожалуйста, перезапустите бота командой /start для получения новой версии.")
        conn.close()
        return

    if check_user_ban(user_id):
        bot.send_message(message.chat.id, f"Вы заблокированы")
        return

    if not check_user_exists(user_id):
        add_user_to_db(user_id, username)
        logger.info(f"{message.from_user.username, message.from_user.first_name, message.from_user.id} зарегистрировался")

    try:
        add_user_exam(user_id, exam_name)  
        global current_exam
        current_exam = exams.get(exam_name, [])
        logger.info(f"{message.from_user.username, message.from_user.first_name, message.from_user.id} выбрал {message.text}")
        markup = types.ReplyKeyboardMarkup(resize_keyboard=False)
        markup.row(types.KeyboardButton("Выбрать экзамен"))
        for i, (question, _) in enumerate(current_exam, start=1):
            button_text = f"Вопрос {i}: {question.split(':', 1)[1].strip()}"
            markup.add(types.KeyboardButton(button_text))
        bot.send_message(message.chat.id, f"Вы выбрали {exam_name}. Выберите вопрос:", reply_markup=markup)
    except Exception as e:
        logger.error(f"Error selecting exam {message.text}: {e}")
        bot.send_message(message.chat.id, "Произошла ошибка при выборе экзамена. Пожалуйста, попробуйте позже.")
    finally:
        conn.close()

@bot.message_handler(func=lambda message: message.text.startswith("Вопрос "))
def answer_question(message):
    user_id = message.from_user.id

    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    cursor.execute("SELECT needs_restart FROM users WHERE telegram_id = ?", (user_id,))
    result = cursor.fetchone()

    if check_user_ban(user_id):
        bot.send_message(message.chat.id, f"Вы заблокированы")
        return


    if result and result[0]:
        bot.send_message(message.chat.id, "Бот был обновлен. Пожалуйста, перезапустите бота командой /start для получения новой версии.")
        conn.close()
        return

    if not check_user_exists(user_id):
        bot.send_message(message.chat.id, "Вы не зарегистрированы, выполните команду /start или /switch")
        conn.close()
        return

    try:
        user_exam = get_user_exam(user_id)
        if user_exam:
            current_exam = exams.get(user_exam, [])
            question_number = int(message.text.split()[1].split(':')[0])
            if 0 < question_number <= len(current_exam):
                question, answer = current_exam[question_number - 1]
                logger.info(f"{message.from_user.username, message.from_user.first_name, message.from_user.id} выбрал Вопрос {question_number}")
                response = f"<b>{question}</b>\n\nОтвет:\n{answer}"
                bot.send_message(message.chat.id, response, parse_mode='HTML')
            else:
                bot.send_message(message.chat.id, "Неверный номер вопроса.")
        else:
            bot.send_message(message.chat.id, "Выберите экзамен сначала командой /start или /switch")
    except Exception as e:
        logger.error(f"Error answering question {message.text}: {e}")
        bot.send_message(message.chat.id, "Произошла ошибка при ответе на вопрос. Пожалуйста, попробуйте позже.")
    finally:
        conn.close()


@bot.message_handler(func=lambda message: message.text == "Выбрать экзамен")
def go_back(message):
    start(message)


@bot.message_handler(commands=['send_docx'])
def send_docx(message):
    user_id = message.from_user.id
    username = message.from_user.username

    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    cursor.execute("SELECT needs_restart FROM users WHERE telegram_id = ?", (user_id,))
    result = cursor.fetchone()

    if check_user_ban(user_id):
        bot.send_message(message.chat.id, f"Вы заблокированы")
        return

    if result and result[0]:
        bot.send_message(message.chat.id, "Бот был обновлен. Пожалуйста, перезапустите бота командой /start для получения новой версии.")
        conn.close()
        return
    
    if not check_user_exists(user_id):
        bot.send_message(message.chat.id, "Вы не зарегистрированы, выполните команду /start или /switch")
        conn.close()
        return

    command = message.text.split()[0]
    if command == '/send_docx':
        logger.info(f"{message.from_user.username, message.from_user.first_name, message.from_user.id} выбирает файл для отправки")
        try:
            markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
            for file_name in available_files.keys():
                markup.row(types.KeyboardButton(file_name))
            bot.send_message(message.chat.id, "Выберите исходный файл с вопросами:", reply_markup=markup)
        except Exception as e:
            logger.error(f"Error sending docx file: {e}")
            bot.send_message(message.chat.id, "Произошла ошибка при отправке файла. Пожалуйста, попробуйте снова.")


@bot.message_handler(func=lambda message: message.text in available_files.keys())
def send_selected_docx(message):
    user_id = message.from_user.id
    username = message.from_user.username

    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    cursor.execute("SELECT needs_restart FROM users WHERE telegram_id = ?", (user_id,))
    result = cursor.fetchone()

    if check_user_ban(user_id):
        bot.send_message(message.chat.id, f"Вы заблокированы")
        return


    if result and result[0]:
        bot.send_message(message.chat.id, "Бот был обновлен. Пожалуйста, перезапустите бота командой /start для получения новой версии.")
        conn.close()
        return
    
    if not check_user_exists(user_id):
        bot.send_message(message.chat.id, "Вы не зарегестрированы, выполните команду /start или /switch")
        return
    
    allowed, wait_time = rate_limiter.allow_request()
    if allowed:
        try:
            file_path = available_files[message.text]
            file_extension = file_path.split('.')[-1].lower()
            logger.info(f"{message.from_user.username, message.from_user.first_name, message.from_user.id} выбрал файл '{message.text}'")
            if file_extension == 'docx':
                with open(file_path, 'rb') as docx_file:
                    bot.send_document(message.chat.id, docx_file)
            else:
                bot.send_message(message.chat.id, "Неподдерживаемый тип файла.")
        except Exception as e:
            logger.error(f"Error sending selected docx file: {e}")
            bot.send_message(message.chat.id, "Произошла ошибка при отправке выбранного файла. Пожалуйста, попробуйте снова.")
    else:  
        bot.send_message(message.chat.id, f"Большое количество запросов, отправьте сообщение через {wait_time:.2f} секунд")
        time.sleep(wait_time)
        return
        
@bot.message_handler(commands=['send_cod'])
def send_cod(message):
    user_id = message.from_user.id
    username = message.from_user.username

    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    cursor.execute("SELECT needs_restart FROM users WHERE telegram_id = ?", (user_id,))
    result = cursor.fetchone()


    if check_user_ban(user_id):
        bot.send_message(message.chat.id, f"Вы заблокированы")
        return

    if result and result[0]:
        bot.send_message(message.chat.id, "Бот был обновлен. Пожалуйста, перезапустите бота командой /start для получения новой версии.")
        conn.close()
        return
    
    if not check_user_exists(user_id):
        bot.send_message(message.chat.id, "Вы не зарегестрированы, выполните команду /start или /switch")
        return
    
    command = message.text.split()[0]
    if command == '/send_cod':
        logger.info(f"{message.from_user.username, message.from_user.first_name, message.from_user.id} выбирает пример кода")
        try:
            markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
            for file_name in available_files_txt.keys():
                markup.row(types.KeyboardButton(file_name))
            bot.send_message(message.chat.id, "Выберите пример кода:", reply_markup=markup)
        except Exception as e:
            logger.error(f"Error sending docx file: {e}")
            bot.send_message(message.chat.id, "Произошла ошибка при отправке файла. Пожалуйста, попробуйте снова.")


@bot.message_handler(func=lambda message: message.text in available_files_txt.keys())
def send_selected_cod(message):
    user_id = message.from_user.id
    username = message.from_user.username

    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    cursor.execute("SELECT needs_restart FROM users WHERE telegram_id = ?", (user_id,))
    result = cursor.fetchone()

    if check_user_ban(user_id):
        bot.send_message(message.chat.id, f"Вы заблокированы")
        return

    if result and result[0]:
        bot.send_message(message.chat.id, "Бот был обновлен. Пожалуйста, перезапустите бота командой /start для получения новой версии.")
        conn.close()
        return
    
    if not check_user_exists(user_id):
        bot.send_message(message.chat.id, "Вы не зарегестрированы, выполните команду /start или /switch")
        return

    allowed, wait_time = rate_limiter.allow_request()
    if allowed:
        try:
            file_path = available_files_txt[message.text]
            file_extension = file_path.split('.')[-1].lower()
            logger.info(f"{message.from_user.username, message.from_user.first_name, message.from_user.id} выбрал '{message.text}'")
            if file_extension == 'txt':
                with open(file_path, 'r', encoding='utf-8') as txt_file:
                    content = txt_file.read()
                    escaped_content = escape_html(content)
                    bot.send_message(message.chat.id, f"<pre>{escaped_content}</pre>", parse_mode='HTML')
            else:
                bot.send_message(message.chat.id, "Неподдерживаемый тип файла.")

        except Exception as e:
            logger.error(f"Error sending selected docx file: {e}")
            bot.send_message(message.chat.id, "Произошла ошибка при отправке выбранного файла. Пожалуйста, попробуйте снова.")

    else:  
        bot.send_message(message.chat.id, f"Большое количество запросов, отправьте сообщение через {wait_time:.2f} секунд")
        time.sleep(wait_time)
        return

@bot.message_handler(func=lambda message: True)
def log_message(message):
    logger.info(f"{message.from_user.username, message.from_user.first_name, message.from_user.id}) написал {message.text}")

def notify_all_users():
    users = get_all_users()
    
    message = "Бот был обновлен. Изменились ответы на вопросы в экзамене. Пожалуйста, перезапустите бота командой /start или /switch для получения новой версии."
    logger.info(f"Сообщение '{message}' было отправлено")
    for user_id in users:
        try:
            bot.send_message(user_id, message, disable_notification=True)
        except Exception as e:
            logger.error(f"Не удалось отправить сообщение пользователю {user_id}: {e}")

def escape_html(text):
    return text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')

def add_column_to_users():
    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(users)")
    columns = [column[1] for column in cursor.fetchall()]
    if 'current_exam' not in columns:
        cursor.execute("ALTER TABLE users ADD COLUMN current_exam TEXT")
    conn.commit()
    conn.close()

add_column_to_users()

if __name__ == "__main__":
#    set_restart_flag_for_all_users()
#    notify_all_users()
    try:
        bot.polling(none_stop=True)
    except Exception as e:
        logger.error(f"Error starting bot polling: {e}")