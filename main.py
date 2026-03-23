import os
import logging
import asyncio
import json
import sqlite3
import threading
from flask import Flask, request, jsonify
from flask_cors import CORS
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
from aiogram.utils.keyboard import InlineKeyboardBuilder

# === НАСТРОЙКИ ===
TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", 8043971654))
MINI_APP_URL = os.getenv("MINI_APP_URL", "https://твой-ник.github.io/твой-репо/")

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

bot = Bot(token=TOKEN)
dp = Dispatcher()
app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})
DB_PATH = 'shop.db'

# === ФУНКЦИЯ ОТПРАВКИ СООБЩЕНИЙ ИЗ FLASK ===
def send_telegram_message(chat_id, text):
    """Отправляет сообщение через бота из синхронного кода (Flask)"""
    async def _send():
        try:
            await bot.send_message(chat_id, text, parse_mode="HTML")
        except Exception as e:
            logger.error(f"❌ Ошибка отправки: {e}")
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(_send())
        loop.close()
    except Exception as e:
        logger.error(f"❌ Ошибка цикла: {e}")

# === БАЗА ДАННЫХ ===
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        username TEXT,
        item_name TEXT,
        total_amount INTEGER,
        customer_name TEXT,
        customer_phone TEXT,
        customer_address TEXT,
        customer_comment TEXT,
        status TEXT DEFAULT 'Новый',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        balance INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    conn.commit()
    conn.close()
    logger.info("✅ База данных готова")

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

# === API: ПОЛУЧЕНИЕ ЗАКАЗОВ ===
@app.route('/get_orders', methods=['GET', 'OPTIONS'])
def get_orders():
    if request.method == 'OPTIONS':
        return '', 204
    try:
        user_id = request.args.get('user_id', type=int)
        if not user_id:
            return jsonify({'success': False, 'error': 'user_id required'}), 400
        conn = get_db_connection()
        orders = conn.execute('''
            SELECT id, item_name, total_amount, status, customer_comment, created_at 
            FROM orders WHERE user_id = ? ORDER BY id DESC LIMIT 50
        ''', (user_id,)).fetchall()
        conn.close()
        result = []
        for o in orders:
            result.append({
                'id': o['id'], 'items': o['item_name'], 'total': o['total_amount'],
                'status': o['status'], 'comment': o['customer_comment'], 'date': o['created_at']
            })
        logger.info(f"📩 GET /get_orders: user {user_id}, found {len(result)} orders")
        return jsonify({'success': True, 'orders': result})
    except Exception as e:
        logger.error(f"❌ Ошибка get_orders: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

# === API: СОЗДАНИЕ ЗАКАЗА ===
@app.route('/create_order', methods=['POST', 'OPTIONS'])
def create_order():
    if request.method == 'OPTIONS':
        return '', 204
    try:
        data = request.json
        logger.info(f"📩 POST /create_order: {json.dumps(data, ensure_ascii=False)}")
        items = data.get('items', [])
        total = data.get('total', 0)
        customer = data.get('customer', {})
        user_id = data.get('user_id', 0)
        username = data.get('username', 'unknown')
        items_text = ', '.join([f"{i.get('title', 'Товар')} x{i.get('quantity', 1)}" for i in items])
        
        conn = get_db_connection()
        c = conn.cursor()
        c.execute('''INSERT INTO orders 
            (user_id, username, item_name, total_amount, customer_name, customer_phone, customer_address, customer_comment, status) 
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
            (user_id, username, items_text, total, customer.get('name', ''), customer.get('phone', ''), 
             customer.get('address', ''), customer.get('comment', ''), 'Новый'))
        order_id = c.lastrowid
        conn.commit()
        conn.close()
        logger.info(f"✅ Заказ #{order_id} сохранён")
        
        # Уведомление пользователю (только оповещение!)
        user_msg = (
            f"✅ <b>Спасибо за заказ #{order_id}!</b>\n\n"
            f"📦 {items_text}\n\n"
            f"💰 <b>{total:,} ₽</b>\n\n"
            f"📊 Статус: <b>Новый</b>\n\n"
            f"🔍 <b>Следите за статусом в профиле приложения</b>\n"
            f"📱 Раздел: <b>Мои заказы</b> 👆"
        )
        send_telegram_message(user_id, user_msg)
        
        # Уведомление админу (полная информация)
        admin_msg = (
            f"🔥 <b>НОВЫЙ ЗАКАЗ #{order_id}!</b>\n\n"
            f"📦 <b>Товары:</b>\n{items_text}\n\n"
            f"💰 <b>Сумма: {total:,} ₽</b>\n\n"
            f"👤 <b>Клиент:</b> {customer.get('name', '')}\n"
            f"📞 <b>Телефон:</b> {customer.get('phone', '')}\n"
            f"📍 <b>Адрес:</b> {customer.get('address', '')}\n"
            f"💬 <b>Комментарий:</b> {customer.get('comment', 'Нет')}\n\n"
            f"🔗 Telegram: @{username} (ID: {user_id})"
        )
        send_telegram_message(ADMIN_ID, admin_msg)
        
        return jsonify({'success': True, 'order_id': order_id, 'items': items_text, 'total': total, 'status': 'Новый'})
    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/health')
def health():
    return jsonify({'status': 'ok', 'service': 'RZ SHOP API'})

# === БОТ: АДМИН-КЛАВИАТУРА ===
def get_admin_kb():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="📊 Заказы")],
        [KeyboardButton(text="📈 Статистика")],
        [KeyboardButton(text="📢 Рассылка")]
    ], resize_keyboard=True)

# === БОТ: ХЕНДЛЕРЫ ===
@dp.message(Command("start"))
async def cmd_start(message: Message):
    # Сохраняем пользователя
    conn = get_db_connection()
    conn.execute('INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)', 
                (message.from_user.id, message.from_user.username))
    conn.commit()
    conn.close()
    
    # Кнопка входа в магазин (для всех)
    inline_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛍 ОТКРЫТЬ МАГАЗИН", web_app=WebAppInfo(url=MINI_APP_URL))]
    ])
    
    if message.from_user.id == ADMIN_ID:
        # Админ видит меню управления
        await message.answer(
            "👋 <b>Добро пожаловать, Администратор!</b>\n\n"
            "Управляйте заказами и рассылками 👇",
            reply_markup=get_admin_kb(), 
            parse_mode="HTML"
        )
    else:
        # Обычный пользователь видит только приветствие + кнопку магазина
        name = message.from_user.first_name or "Друг"
        await message.answer(
            f"✨ <b>Добро пожаловать в RZ SHOP, {name}!</b>\n\n"
            f"📱 Премиум электроника по лучшим ценам\n"
            f"🚀 Быстрая доставка по всей стране\n"
            f"💎 Гарантия качества на все товары\n\n"
            f"👇 <b>Нажмите кнопку ниже для покупок:</b>",
            reply_markup=inline_kb,
            parse_mode="HTML"
        )

@dp.message(F.text == "🛍 ОТКРЫТЬ МАГАЗИН")
async def open_shop(message: Message):
    """Если пользователь нажал текстовую кнопку (редко, но бывает)"""
    inline_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛍 ОТКРЫТЬ МАГАЗИН", web_app=WebAppInfo(url=MINI_APP_URL))]
    ])
    await message.answer("🛍 <b>Открываю магазин...</b>", reply_markup=inline_kb, parse_mode="HTML")

# === АДМИН: ПРОСМОТР ЗАКАЗОВ ===
@dp.message(F.text == "📊 Заказы")
async def admin_orders(message: Message):
    if message.from_user.id != ADMIN_ID: return
    conn = get_db_connection()
    orders = conn.execute('SELECT id, item_name, status, total_amount FROM orders ORDER BY id DESC LIMIT 20').fetchall()
    conn.close()
    if not orders: return await message.answer("📭 Нет заказов")
    
    builder = InlineKeyboardBuilder()
    for o in orders:
        builder.button(text=f"#{o[0]} | {o[2]} | {o[3]:,}₽", callback_data=f"edit_{o[0]}")
    builder.button(text="🔙 Назад", callback_data="admin_back")
    builder.adjust(1)
    await message.answer("📦 Заказы:", reply_markup=builder.as_markup())

# === АДМИН: СТАТИСТИКА ===
@dp.message(F.text == "📈 Статистика")
async def admin_stats(message: Message):
    if message.from_user.id != ADMIN_ID: return
    conn = get_db_connection()
    total = conn.execute('SELECT COUNT(*) FROM orders').fetchone()[0]
    revenue = conn.execute('SELECT SUM(total_amount) FROM orders').fetchone()[0] or 0
    users = conn.execute('SELECT COUNT(*) FROM users').fetchone()[0]
    conn.close()
    await message.answer(f"📈 Заказов: {total}\n💰 Выручка: {revenue:,} ₽\n👥 Пользователей: {users}")

# === АДМИН: РАССЫЛКА (заготовка) ===
@dp.message(F.text == "📢 Рассылка")
async def admin_broadcast(message: Message):
    if message.from_user.id != ADMIN_ID: return
    await message.answer(
        "📢 <b>Рассылка</b>\n\n"
        "Функция в разработке. Для отправки новостей используйте:\n"
        "<code>/broadcast Текст сообщения</code>",
        parse_mode="HTML"
    )

@dp.message(F.text == "🔙 Назад")
async def admin_back(message: Message):
    if message.from_user.id == ADMIN_ID:
        await message.answer("👋 Админ меню", reply_markup=get_admin_kb())

# === АДМИН: УПРАВЛЕНИЕ СТАТУСОМ ЗАКАЗА ===
@dp.callback_query(F.data.startswith("edit_"))
async def edit_order(callback):
    if callback.from_user.id != ADMIN_ID: return await callback.answer("❌", show_alert=True)
    
    oid = int(callback.data.split("_")[1])
    conn = get_db_connection()
    row = conn.execute('SELECT * FROM orders WHERE id = ?', (oid,)).fetchone()
    conn.close()
    
    if not row: return await callback.answer("Не найден", show_alert=True)
    
    builder = InlineKeyboardBuilder()
    for k, v in {"processing": "⏳ В работе", "packed": "📦 Собран", "delivered": "✅ Доставлен"}.items():
        builder.button(text=v, callback_data=f"status_{oid}_{k}")
    builder.button(text="🔙 Назад", callback_data="admin_back")
    builder.adjust(2)
    
    await callback.message.edit_text(
        f"📦 Заказ #{oid}\nСтатус: {row['status']}\n\nВыберите новый статус:",
        reply_markup=builder.as_markup()
    )

@dp.callback_query(F.data.startswith("status_"))
async def change_status(callback):
    if callback.from_user.id != ADMIN_ID: return await callback.answer("❌", show_alert=True)
    
    parts = callback.data.split("_")
    oid, new_status = int(parts[1]), parts[2]
    status_map = {"processing": "В обработке", "packed": "Собран", "delivered": "Доставлен"}
    
    conn = get_db_connection()
    conn.execute('UPDATE orders SET status = ? WHERE id = ?', (status_map[new_status], oid))
    row = conn.execute('SELECT user_id FROM orders WHERE id = ?', (oid,)).fetchone()
    conn.commit()
    conn.close()
    
    await callback.answer("✅ Статус изменён")
    
    # Уведомление клиенту об изменении статуса
    if row and row['user_id']:
        send_telegram_message(row['user_id'], f"📦 Заказ #{oid}\n🔄 Новый статус: <b>{status_map[new_status]}</b>")
    
    await asyncio.sleep(1)
    await callback.message.edit_text(f"✅ Статус заказа #{oid} изменён на: {status_map[new_status]}")

@dp.callback_query(F.data == "admin_back")
async def admin_back_callback(callback):
    if callback.from_user.id != ADMIN_ID: return
    await callback.message.edit_text("👋 Админ меню", reply_markup=get_admin_kb())

# === КОМАНДА /broadcast ДЛЯ РАССЫЛОК (админ) ===
@dp.message(Command("broadcast"))
async def broadcast_cmd(message: Message):
    if message.from_user.id != ADMIN_ID: return
    
    text = message.text.replace("/broadcast", "").strip()
    if not text:
        return await message.answer("❌ Используйте: <code>/broadcast Текст сообщения</code>", parse_mode="HTML")
    
    # Отправляем всем пользователям (кроме админа)
    conn = get_db_connection()
    users = conn.execute('SELECT user_id FROM users WHERE user_id != ?', (ADMIN_ID,)).fetchall()
    conn.close()
    
    sent = 0
    for user in users:
        try:
            await bot.send_message(user[0], f"📢 <b>Новости RZ SHOP</b>\n\n{text}", parse_mode="HTML")
            sent += 1
            await asyncio.sleep(0.1)  # Пауза чтобы не забанили
        except Exception as e:
            logger.error(f"❌ Не отправлено пользователю {user[0]}: {e}")
    
    await message.answer(f"✅ Рассылка отправлена: {sent} пользователей")

# === ЗАПУСК ===
def run_flask():
    logger.info("🌐 Flask стартует...")
    app.run(host='0.0.0.0', port=8000, debug=False, use_reloader=False, threaded=True)

async def run_bot():
    logger.info("🤖 Бот стартует...")
    await dp.start_polling(bot)

def main():
    init_db()
    threading.Thread(target=run_flask, daemon=True).start()
    import time; time.sleep(2)
    logger.info("✅ Flask в фоне | 🚀 RZ SHOP готов!")
    asyncio.run(run_bot())

if __name__ == '__main__':
    main()
