#!/data/data/com.termux/files/usr/bin/python3

import os
import sys
import time
import logging
import sqlite3
import requests
from threading import Thread, Lock
from datetime import datetime, timedelta
import telebot
from telebot import types

# ===================== КОНФИГУРАЦИЯ =====================
TOKEN = "7932981986:AAEa94uFnMkGNjUKK_qEyoSiRo7L_gF67r0"
ADMIN_ID = 796652393
LOG_FILE = "bot.log"
DB_FILE = "users.db"
CACHE_TTL = 300
API_URL = "https://api.coingecko.com/api/v3"
API_TIMEOUT = 30

CRYPTO_LIST = [
    "₿ BTC", "Ξ ETH", "Ⓝ BNB", "◎ SOL", "✕ XRP",
    "₳ ADA", "Ð DOGE", "● DOT", "🐕 SHIB", "🔼 AVAX",
    "◈ MATIC", "🔗 LINK", "⚛ ATOM", "🦄 UNI", "Ł LTC",
    "★ XLM", "∆ ALGO", "📁 FIL", "Ⓥ VET", "ϴ THETA",
    "ꜩ XTZ", "ε EOS"
]

CRYPTO_IDS = {
    "BTC": "bitcoin", "ETH": "ethereum", "BNB": "binancecoin",
    "SOL": "solana", "XRP": "ripple", "ADA": "cardano",
    "DOGE": "dogecoin", "DOT": "polkadot", "SHIB": "shiba-inu",
    "AVAX": "avalanche-2", "MATIC": "matic-network",
    "LINK": "chainlink", "ATOM": "cosmos", "UNI": "uniswap",
    "LTC": "litecoin", "XLM": "stellar", "ALGO": "algorand",
    "FIL": "filecoin", "VET": "vechain", "THETA": "theta-token",
    "XTZ": "tezos", "EOS": "eos"
}

# ===================== НАСТРОЙКА =====================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger('CRYPTO_BOT')

bot = telebot.TeleBot(TOKEN, parse_mode='HTML')
cache_lock = Lock()
user_data_lock = Lock()
crypto_cache = {'rates': {}, 'last_updated': None}
user_data = {}

# ===================== БАЗА ДАННЫХ =====================
def init_db():
    """Инициализация базы данных"""
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        
        cursor.execute('''CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            last_name TEXT,
            premium_until REAL DEFAULT 0,
            join_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        
        cursor.execute('''CREATE TABLE IF NOT EXISTS alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            crypto TEXT,
            threshold REAL,
            direction TEXT CHECK(direction IN ('above', 'below')),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(user_id)
        )''')
        
        conn.commit()
        return True
    except sqlite3.Error as e:
        logger.error(f"DB error: {e}")
        return False
    finally:
        conn.close()

# ===================== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ =====================
def is_premium(user_id):
    """Проверка премиум-статуса"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT premium_until FROM users WHERE user_id=?", (user_id,))
    result = cursor.fetchone()
    conn.close()
    return result and result[0] > time.time() if result else False

def get_crypto_rates():
    """Получение курсов валют"""
    try:
        with cache_lock:
            if crypto_cache['last_updated'] and \
               (time.time() - crypto_cache['last_updated']) < CACHE_TTL:
                return crypto_cache['rates']
            
            ids = ','.join(CRYPTO_IDS.values())
            response = requests.get(
                f"{API_URL}/simple/price?ids={ids}&vs_currencies=usd,rub",
                timeout=API_TIMEOUT
            )
            data = response.json()
            
            rates = {
                symbol: {'usd': data[coin_id]['usd'], 'rub': data[coin_id]['rub']}
                for symbol, coin_id in CRYPTO_IDS.items()
            }
            
            crypto_cache.update({
                'rates': rates,
                'last_updated': time.time()
            })
            return rates
    except Exception as e:
        logger.error(f"API error: {e}")
        return None

# ===================== КЛАВИАТУРЫ =====================
def main_menu_keyboard():
    """Главное меню"""
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    buttons = [
        types.KeyboardButton('💰 Калькулятор'),
        types.KeyboardButton('📊 Курсы'),
        types.KeyboardButton('🔔 Алерты'),
        types.KeyboardButton('ℹ️ Помощь')
    ]
    markup.add(*buttons)
    return markup

def crypto_select_keyboard(action='select'):
    """Клавиатура выбора криптовалюты"""
    markup = types.InlineKeyboardMarkup(row_width=4)
    for i in range(0, len(CRYPTO_LIST), 4):
        row = CRYPTO_LIST[i:i+4]
        buttons = [
            types.InlineKeyboardButton(
                crypto,
                callback_data=f'{action}_{crypto.split()[-1]}'
            ) for crypto in row if crypto.split()[-1] in CRYPTO_IDS
        ]
        markup.add(*buttons)
    markup.add(types.InlineKeyboardButton("❌ Отмена", callback_data='cancel'))
    return markup

def alert_direction_keyboard():
    """Клавиатура направления алерта"""
    markup = types.InlineKeyboardMarkup()
    markup.row(
        types.InlineKeyboardButton("Выше цены", callback_data='alert_above'),
        types.InlineKeyboardButton("Ниже цены", callback_data='alert_below')
    )
    markup.row(types.InlineKeyboardButton("❌ Отмена", callback_data='cancel'))
    return markup

# ===================== ОБРАБОТЧИКИ КОМАНД =====================
@bot.message_handler(commands=['start', 'help'])
def start(message):
    """Обработчик стартового сообщения"""
    try:
        init_db()
        with sqlite3.connect(DB_FILE) as conn:
            conn.execute(
                "INSERT OR IGNORE INTO users (user_id, username, first_name, last_name) VALUES (?, ?, ?, ?)",
                (message.from_user.id, message.from_user.username, 
                 message.from_user.first_name, message.from_user.last_name)
            )
        
        bot.send_message(
            message.chat.id,
            "🪙 <b>Крипто-бот с 22+ валютами</b>\n\n"
            "• Конвертация с иконками\n• Уведомления о ценах\n\n"
            "Выберите действие:",
            reply_markup=main_menu_keyboard()
        )
    except Exception as e:
        logger.error(f"Start error: {e}")
        bot.send_message(message.chat.id, "⚠️ Ошибка. Попробуйте позже.")

@bot.message_handler(func=lambda m: m.text == '💰 Калькулятор')
def calculator_start(message):
    """Запуск калькулятора"""
    with user_data_lock:
        user_data[message.from_user.id] = {'action': 'select_from'}
    bot.send_message(
        message.chat.id,
        "🔄 <b>Выберите исходную валюту:</b>",
        reply_markup=crypto_select_keyboard('calc_from')
    )

@bot.message_handler(func=lambda m: m.text == '📊 Курсы')
def show_rates(message):
    """Показать курсы валют"""
    rates = get_crypto_rates()
    if not rates:
        bot.send_message(message.chat.id, "⚠️ Не удалось получить курсы")
        return
    
    response = "📈 <b>Текущие курсы:</b>\n\n"
    for crypto in CRYPTO_LIST:
        symbol = crypto.split()[-1]
        if symbol in rates:
            response += f"{crypto}: {rates[symbol]['usd']:.4f} USD | {rates[symbol]['rub']:.2f} RUB\n"
    
    bot.send_message(message.chat.id, response)

@bot.message_handler(func=lambda m: m.text == '🔔 Алерты')
def alerts_menu(message):
    """Меню алертов"""
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT crypto, threshold, direction FROM alerts WHERE user_id=?",
            (message.from_user.id,)
        )
        alerts = cursor.fetchall()
        
    text = "📋 <b>Ваши алерты:</b>\n\n" + "\n".join(
        f"{a[0]} {'выше' if a[2] == 'above' else 'ниже'} {a[1]:.4f} USD" 
        for a in alerts
    ) if alerts else "У вас нет активных алертов"
    
    markup = types.InlineKeyboardMarkup()
    markup.row(
        types.InlineKeyboardButton("➕ Добавить алерт", callback_data='add_alert'),
        types.InlineKeyboardButton("🗑️ Удалить алерт", callback_data='delete_alert')
    )
    bot.send_message(message.chat.id, text, reply_markup=markup)

@bot.message_handler(func=lambda m: m.text == 'ℹ️ Помощь')
def show_help(message):
    """Показать справку"""
    help_text = (
        "ℹ️ <b>Помощь по боту</b>\n\n"
        "<b>💰 Калькулятор</b> - конвертация между криптовалютами\n"
        "<b>📊 Курсы</b> - текущие курсы всех валют\n"
        "<b>🔔 Алерты</b> - установка уведомлений о ценах\n\n"
        "Для начала работы просто выберите нужное действие в меню"
    )
    bot.send_message(message.chat.id, help_text)

# ===================== ОБРАБОТЧИКИ CALLBACK =====================
@bot.callback_query_handler(func=lambda call: call.data.startswith('calc_from_'))
def handle_calc_from(call):
    """Выбор исходной валюты для калькулятора"""
    symbol = call.data.split('_')[2]
    with user_data_lock:
        user_data[call.from_user.id] = {
            'action': 'calc_to',
            'from_currency': symbol
        }
    bot.edit_message_text(
        f"➡️ Выбрано: {symbol}\n\n<b>Выберите целевую валюту:</b>",
        call.message.chat.id,
        call.message.message_id,
        reply_markup=crypto_select_keyboard('calc_to')
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith('calc_to_'))
def handle_calc_to(call):
    """Выбор целевой валюты для калькулятора"""
    symbol = call.data.split('_')[2]
    user_id = call.from_user.id
    
    with user_data_lock:
        state = user_data.get(user_id, {})
        if not state or state.get('action') != 'calc_to':
            bot.answer_callback_query(call.id, "⚠️ Сессия устарела")
            return
            
        if symbol == state.get('from_currency'):
            bot.answer_callback_query(call.id, "⚠️ Выберите другую валюту")
            return
            
        user_data[user_id] = {
            'action': 'calc_amount',
            'from_currency': state['from_currency'],
            'to_currency': symbol
        }
    
    bot.edit_message_text(
        f"🔢 <b>Введите сумму для конвертации:</b>\n\n{state['from_currency']} → {symbol}",
        call.message.chat.id,
        call.message.message_id
    )

@bot.callback_query_handler(func=lambda call: call.data == 'add_alert')
def handle_add_alert(call):
    """Добавление нового алерта"""
    with user_data_lock:
        user_data[call.from_user.id] = {'action': 'alert_select'}
    bot.edit_message_text(
        "🔄 <b>Выберите валюту для алерта:</b>",
        call.message.chat.id,
        call.message.message_id,
        reply_markup=crypto_select_keyboard('alert_crypto')
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith('alert_crypto_'))
def handle_alert_crypto(call):
    """Выбор криптовалюты для алерта"""
    symbol = call.data.split('_')[2]
    with user_data_lock:
        user_data[call.from_user.id] = {
            'action': 'alert_direction',
            'alert_crypto': symbol
        }
    bot.edit_message_text(
        f"Выбрано: {symbol}\n\n<b>Выберите тип алерта:</b>",
        call.message.chat.id,
        call.message.message_id,
        reply_markup=alert_direction_keyboard()
    )

@bot.callback_query_handler(func=lambda call: call.data in ['alert_above', 'alert_below'])
def handle_alert_direction(call):
    """Выбор направления алерта"""
    direction = 'above' if call.data == 'alert_above' else 'below'
    
    with user_data_lock:
        state = user_data.get(call.from_user.id, {})
        if not state or state.get('action') != 'alert_direction':
            bot.answer_callback_query(call.id, "⚠️ Сессия устарела")
            return
            
        user_data[call.from_user.id] = {
            'action': 'alert_threshold',
            'alert_crypto': state['alert_crypto'],
            'alert_direction': direction
        }
    
    bot.edit_message_text(
        f"💰 <b>Введите пороговую цену (USD):</b>\n\n"
        f"Валюта: {state['alert_crypto']}\n"
        f"Тип: {'выше' if direction == 'above' else 'ниже'} указанной цены",
        call.message.chat.id,
        call.message.message_id
    )

@bot.callback_query_handler(func=lambda call: call.data == 'delete_alert')
def handle_delete_alert(call):
    """Удаление существующего алерта"""
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, crypto, threshold, direction FROM alerts WHERE user_id=?",
            (call.from_user.id,)
        )
        alerts = cursor.fetchall()
        
        if not alerts:
            bot.answer_callback_query(call.id, "Нет алертов для удаления")
            return
            
        markup = types.InlineKeyboardMarkup()
        for alert in alerts:
            alert_id, crypto, threshold, direction = alert
            markup.add(types.InlineKeyboardButton(
                f"{crypto} {direction} {threshold:.4f}",
                callback_data=f"delete_{alert_id}"
            ))
        markup.add(types.InlineKeyboardButton("❌ Отмена", callback_data='cancel'))
        
        bot.edit_message_text(
            "Выберите алерт для удаления:",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=markup
        )

@bot.callback_query_handler(func=lambda call: call.data.startswith('delete_'))
def handle_delete_confirm(call):
    """Подтверждение удаления алерта"""
    alert_id = call.data.split('_')[1]
    
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "DELETE FROM alerts WHERE id=? AND user_id=?",
            (alert_id, call.from_user.id)
        )
        conn.commit()
        
        if cursor.rowcount > 0:
            bot.answer_callback_query(call.id, "Алерт удален")
            bot.edit_message_text(
                "✅ Алерт успешно удален",
                call.message.chat.id,
                call.message.message_id
            )
        else:
            bot.answer_callback_query(call.id, "Алерт не найден")

@bot.callback_query_handler(func=lambda call: call.data == 'cancel')
def handle_cancel(call):
    """Отмена действия"""
    with user_data_lock:
        user_data.pop(call.from_user.id, None)
    bot.edit_message_text(
        "❌ Действие отменено",
        call.message.chat.id,
        call.message.message_id
    )

# ===================== ОБРАБОТЧИКИ СООБЩЕНИЙ =====================
@bot.message_handler(func=lambda m: user_data.get(m.from_user.id, {}).get('action') == 'calc_amount')
def handle_calc_amount(message):
    """Расчет конвертации"""
    try:
        amount = float(message.text)
        if amount <= 0:
            raise ValueError
            
        with user_data_lock:
            state = user_data.get(message.from_user.id, {})
            if not state:
                raise ValueError
                
            from_curr = state['from_currency']
            to_curr = state['to_currency']
            user_data.pop(message.from_user.id, None)
            
        rates = get_crypto_rates()
        if not rates or from_curr not in rates or to_curr not in rates:
            raise ValueError
            
        result = (amount * rates[from_curr]['usd']) / rates[to_curr]['usd']
        
        response = (
            f"📊 <b>Результат конвертации:</b>\n\n"
            f"{amount:.4f} {from_curr} = {result:.8f} {to_curr}\n\n"
            f"<b>Курс:</b> 1 {from_curr} = {rates[from_curr]['usd']/rates[to_curr]['usd']:.8f} {to_curr}"
        )
        
        bot.send_message(
            message.chat.id,
            response,
            reply_markup=main_menu_keyboard()
        )
    except:
        bot.send_message(
            message.chat.id,
            "⚠️ Введите корректную положительную сумму",
            reply_markup=main_menu_keyboard()
        )

@bot.message_handler(func=lambda m: user_data.get(m.from_user.id, {}).get('action') == 'alert_threshold')
def handle_alert_threshold(message):
    """Установка порога для алерта"""
    try:
        threshold = float(message.text)
        if threshold <= 0:
            raise ValueError
            
        with user_data_lock:
            state = user_data.get(message.from_user.id, {})
            if not state:
                raise ValueError
                
            crypto = state['alert_crypto']
            direction = state['alert_direction']
            user_data.pop(message.from_user.id, None)
            
        with sqlite3.connect(DB_FILE) as conn:
            conn.execute(
                "INSERT INTO alerts (user_id, crypto, threshold, direction) VALUES (?, ?, ?, ?)",
                (message.from_user.id, crypto, threshold, direction)
            )
            
        bot.send_message(
            message.chat.id,
            f"✅ Алерт установлен!\n\n{crypto} {direction} {threshold:.4f} USD",
            reply_markup=main_menu_keyboard()
        )
    except:
        bot.send_message(
            message.chat.id,
            "⚠️ Введите корректную положительную цену",
            reply_markup=main_menu_keyboard()
        )

# ===================== СИСТЕМА ПРОВЕРКИ АЛЕРТОВ =====================
def check_alerts():
    """Фоновая проверка срабатывания алертов"""
    while True:
        try:
            with sqlite3.connect(DB_FILE) as conn:
                cursor = conn.cursor()
                rates = get_crypto_rates()
                
                if not rates:
                    time.sleep(60)
                    continue
                
                cursor.execute("SELECT * FROM alerts")
                for alert in cursor.fetchall():
                    alert_id, user_id, crypto, threshold, direction, _ = alert
                    
                    if crypto in rates:
                        current_price = rates[crypto]['usd']
                        if (direction == 'above' and current_price >= threshold) or \
                           (direction == 'below' and current_price <= threshold):
                            try:
                                bot.send_message(
                                    user_id,
                                    f"🚨 Алерт! {crypto} {'достиг' if direction == 'above' else 'упал до'} {current_price:.2f} USD"
                                )
                                cursor.execute(
                                    "DELETE FROM alerts WHERE id=?",
                                    (alert_id,)
                                )
                                conn.commit()
                            except Exception as e:
                                if "blocked" in str(e):
                                    cursor.execute(
                                        "DELETE FROM alerts WHERE id=?",
                                        (alert_id,)
                                    )
                                    conn.commit()
            
            time.sleep(60)
        except Exception as e:
            logger.error(f"Alert check error: {e}")
            time.sleep(60)

# ===================== ЗАПУСК =====================
if __name__ == "__main__":
    try:
        if os.path.exists(DB_FILE):
            os.remove(DB_FILE)
        
        init_db()
        Thread(target=check_alerts, daemon=True).start()
        
        logger.info("Бот запущен")
        bot.infinity_polling()
    except Exception as e:
        logger.critical(f"Startup failed: {e}")
        sys.exit(1)
