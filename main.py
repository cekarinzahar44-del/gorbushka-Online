import os
import logging
import asyncio
import json
import sqlite3
import threading
from flask import Flask, request, jsonify
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
from aiogram.utils.keyboard import InlineKeyboardBuilder

# === НАСТРОЙКИ ===
TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", 8043971654))
MINI_APP_URL = os.getenv("MINI_APP_URL", "https://cekarinzahar44-del.github.io/gorbushka-Online/")

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

bot = Bot(token=TOKEN)
dp = Dispatcher()
app = Flask(__name__)
DB_PATH = 'shop.db'

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

# === API ДЛЯ ПРИЁМА ЗАКАЗОВ ===
@app.route('/create_order', methods=['POST'])
def create_order():
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
                 (user_id, username, items_text, total, 
                  customer.get('name', ''), customer.get('phone', ''), 
                  customer.get('address', ''), customer.get('comment', ''), 'Новый'))
        order_id = c.lastrowid
        conn.commit()
        conn.close()
        
        logger.info(f"✅ Заказ #{order_id} сохранён в БД")
        
        # Уведомление пользователю
        user_msg = (
            f"✅ <b>Заказ #{order_id} принят!</b>\n\n"
            f"📦 {items_text}\n\n"
            f"💰 <b>{total:,} ₽</b>\n\n"
            f"👤 {customer.get('name', '')}\n"
            f"📞 {customer.get('phone', '')}\n"
            f"📍 {customer.get('address', '')}\n\n"
            f"Менеджер свяжется с вами!"
        )
        asyncio.run_coroutine_threadsafe(bot.send_message(user_id, user_msg, parse_mode="HTML"), bot.loop)
        
        # Уведомление админу
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
        asyncio.run_coroutine_threadsafe(bot.send_message(ADMIN_ID, admin_msg, parse_mode="HTML"), bot.loop)
        
        return jsonify({'success': True, 'order_id': order_id})
        
    except Exception as e:
        logger.error(f"❌ Ошибка API: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/health')
def health():
    return jsonify({'status': 'ok', 'service': 'RZ SHOP API'})

# === БОТ ===
def get_admin_kb():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="📊 Заказы")],
        [KeyboardButton(text="📈 Статистика")],
        [KeyboardButton(text="🔙 В меню")]
    ], resize_keyboard=True)

def get_user_kb():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="📦 Мои заказы")],
        [KeyboardButton(text="💰 Бонусы")],
        [KeyboardButton(text="ℹ️ Поддержка")]
    ], resize_keyboard=True)

@dp.message(Command("start"))
async def cmd_start(message: Message):
    logger.info(f"👤 /start от {message.from_user.id} (@{message.from_user.username})")
    
    conn = get_db_connection()
    conn.execute('INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)', 
                (message.from_user.id, message.from_user.username))
    conn.commit()
    conn.close()
    
    inline_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛍 ОТКРЫТЬ МАГАЗИН", web_app=WebAppInfo(url=MINI_APP_URL))]
    ])
    
    if message.from_user.id == ADMIN_ID:
        await message.answer("👋 <b>Добро пожаловать, Администратор!</b>", 
                           reply_markup=get_admin_kb(), parse_mode="HTML")
        await asyncio.sleep(0.5)
        await message.answer("👇 <b>Быстрый доступ к магазину:</b>", 
                           reply_markup=inline_kb, parse_mode="HTML")
    else:
        await message.answer(
            f"👋 <b>Добро пожаловать в RZ SHOP!</b>\n\n"
            f"🛍 <b>Нажмите кнопку ниже чтобы открыть магазин:</b>",
            reply_markup=inline_kb,
            parse_mode="HTML"
        )
        await asyncio.sleep(0.5)
        await message.answer("📂 <b>Меню:</b>", reply_markup=get_user_kb(), parse_mode="HTML")

@dp.message(F.text == "📊 Заказы")
async def admin_orders(message: Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("❌ Доступ запрещен")
        return
    
    conn = get_db_connection()
    orders = conn.execute('SELECT id, item_name, status, total_amount, customer_name, created_at FROM orders ORDER BY id DESC LIMIT 20').fetchall()
    conn.close()
    
    if not orders:
        await message.answer("📭 Нет активных заказов")
        return
    
    builder = InlineKeyboardBuilder()
    for order in orders:
        oid, items, status, total, name, date = order
        builder.button(text=f"#{oid} | {status} | {total:,}₽", callback_data=f"edit_{oid}")
    builder.button(text="🔙 Назад", callback_data="admin_back")
    builder.adjust(1)
    
    await message.answer("📦 <b>Последние заказы:</b>\n\nВыберите заказ:", 
                        reply_markup=builder.as_markup(), parse_mode="HTML")

@dp.message(F.text == "📦 Мои заказы")
async def my_orders(message: Message):
    conn = get_db_connection()
    orders = conn.execute('SELECT id, item_name, status, total_amount, created_at FROM orders WHERE user_id = ? ORDER BY id DESC LIMIT 10', 
                         (message.from_user.id,)).fetchall()
    conn.close()
    
    if not orders:
        await message.answer("📭 У вас пока нет заказов")
        return
    
    text = "📦 <b>Ваши заказы:</b>\n\n"
    for oid, items, status, total, date in orders:
        emoji = {"Новый": "🆕", "В обработке": "⏳", "Собран": "📦", "Отправлен": "🚚", "Доставлен": "✅"}.get(status, "📋")
        text += f"{emoji} <b>Заказ #{oid}</b>\nТовары: {items}\nСумма: {total:,} ₽\nСтатус: <b>{status}</b>\n\n"
    
    await message.answer(text, parse_mode="HTML")

@dp.message(F.text == "💰 Бонусы")
async def my_bonus(message: Message):
    conn = get_db_connection()
    res = conn.execute('SELECT balance FROM users WHERE user_id = ?', (message.from_user.id,)).fetchone()
    conn.close()
    bal = res[0] if res else 0
    await message.answer(f"💰 <b>Ваш баланс:</b> {bal} ₽", parse_mode="HTML")

@dp.message(F.text == "ℹ️ Поддержка")
async def support(message: Message):
    await message.answer("📞 <b>Поддержка</b>\n\nПо всем вопросам: @support_manager", parse_mode="HTML")

@dp.message(F.text == "📈 Статистика")
async def admin_stats(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    conn = get_db_connection()
    total_orders = conn.execute('SELECT COUNT(*) FROM orders').fetchone()[0]
    total_revenue = conn.execute('SELECT SUM(total_amount) FROM orders').fetchone()[0] or 0
    total_users = conn.execute('SELECT COUNT(*) FROM users').fetchone()[0]
    conn.close()
    await message.answer(
        f"📈 <b>Статистика:</b>\n\n"
        f"📦 Заказов: {total_orders}\n"
        f"💰 Выручка: {total_revenue:,} ₽\n"
        f"👥 Пользователей: {total_users}",
        parse_mode="HTML"
    )

@dp.message(F.text == "🔙 В меню")
async def back_menu(message: Message):
    kb = get_admin_kb() if message.from_user.id == ADMIN_ID else get_user_kb()
    await message.answer("📂 <b>Меню:</b>", reply_markup=kb, parse_mode="HTML")

# === СМЕНА СТАТУСА ===
@dp.callback_query(F.data.startswith("edit_"))
async def edit_order(callback):
    oid = int(callback.data.split("_")[1])
    conn = get_db_connection()
    row = conn.execute('SELECT * FROM orders WHERE id = ?', (oid,)).fetchone()
    conn.close()
    
    if not row:
        await callback.answer("❌ Заказ не найден", show_alert=True)
        return
    
    builder = InlineKeyboardBuilder()
    statuses = {"processing": "⏳ В обработке", "packed": "📦 Собран", "shipped": "🚚 Отправлен", "delivered": "✅ Доставлен", "cancelled": "❌ Отменен"}
    for key, val in statuses.items():
        builder.button(text=val, callback_data=f"status_{oid}_{key}")
    builder.button(text="🔙 Назад", callback_data="admin_back")
    builder.adjust(2)
    
    await callback.message.edit_text(
        f"📦 <b>Заказ #{oid}</b>\n\n"
        f"Товары: {row['item_name']}\n"
        f"Сумма: {row['total_amount']:,} ₽\n"
        f"Клиент: {row['customer_name']}\n"
        f"Статус: <b>{row['status']}</b>\n\n"
        f"Выберите новый статус:",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )

@dp.callback_query(F.data.startswith("status_"))
async def change_status(callback):
    parts = callback.data.split("_")
    oid, new_status_key = int(parts[1]), parts[2]
    status_map = {"processing": "В обработке", "packed": "Собран", "shipped": "Отправлен", "delivered": "Доставлен", "cancelled": "Отменен"}
    status_emoji = {"processing": "⏳", "packed": "📦", "shipped": "🚚", "delivered": "✅", "cancelled": "❌"}
    
    conn = get_db_connection()
    conn.execute('UPDATE orders SET status = ? WHERE id = ?', (status_map[new_status_key], oid))
    row = conn.execute('SELECT user_id FROM orders WHERE id = ?', (oid,)).fetchone()
    conn.commit()
    conn.close()
    
    await callback.answer(f"✅ Статус изменен")
    
    if row and row['user_id']:
        await bot.send_message(row['user_id'], f"📦 Заказ #{oid}\nНовый статус: <b>{status_map[new_status_key]}</b>", parse_mode="HTML")
    
    await asyncio.sleep(1.5)
    conn = get_db_connection()
    orders = conn.execute('SELECT id, item_name, status, total_amount FROM orders ORDER BY id DESC LIMIT 20').fetchall()
    conn.close()
    
    builder = InlineKeyboardBuilder()
    for order in orders:
        oid, items, status, total = order
        builder.button(text=f"#{oid} | {status} | {total:,}₽", callback_data=f"edit_{oid}")
    builder.button(text="🔙 Назад", callback_data="admin_back")
    builder.adjust(1)
    await callback.message.edit_text("📦 <b>Последние заказы:</b>", reply_markup=builder.as_markup(), parse_mode="HTML")

@dp.callback_query(F.data == "admin_back")
async def admin_back(callback):
    await callback.message.edit_text("👋 <b>Админ меню:</b>", reply_markup=get_admin_kb(), parse_mode="HTML")

# === ЗАПУСК (ИСПРАВЛЕННЫЙ) ===
def run_flask():
    """Запуск Flask в отдельном потоке"""
    logger.info("🌐 Запуск веб-сервера на порту 8000...")
    app.run(host='0.0.0.0', port=8000, debug=False, use_reloader=False)

async def main():
    """Главная функция — запускает бота в главном потоке"""
    init_db()
    
    # Запускаем Flask в фоновом потоке
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    
    logger.info("✅ Flask запущен в фоне")
    logger.info("=" * 60)
    logger.info("🚀 RZ SHOP - Бот + API готовы к работе!")
    logger.info("=" * 60)
    
    # Запускаем бота в главном потоке (это важно!)
    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())
