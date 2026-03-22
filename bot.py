import asyncio
import logging
import os
import json
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
from aiogram.utils.keyboard import InlineKeyboardBuilder
import aiosqlite

# === НАСТРОЙКИ ===
TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = 8043971654
MINI_APP_URL = os.getenv("MINI_APP_URL", "https://cekarinzahar44-del.github.io/gorbushka-Online/")

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

bot = Bot(token=TOKEN)
dp = Dispatcher()
DB_PATH = 'shop.db'

# === БАЗА ДАННЫХ ===
async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('''CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            item_name TEXT,
            status TEXT DEFAULT 'Новый',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        await db.execute('''CREATE TABLE IF NOT EXISTS order_details (
            order_id INTEGER PRIMARY KEY,
            customer_name TEXT,
            customer_phone TEXT,
            customer_address TEXT,
            total_amount INTEGER
        )''')
        await db.execute('''CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            balance INTEGER DEFAULT 0
        )''')
        await db.commit()
    logger.info("✅ База данных готова")

# === КЛАВИАТУРЫ ===
def get_admin_kb():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="📊 Заказы")],
        [KeyboardButton(text="🔙 В меню")]
    ], resize_keyboard=True)

def get_user_kb():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="📦 Мои заказы")],
        [KeyboardButton(text="💰 Бонусы")],
        [KeyboardButton(text="ℹ️ Помощь")]
    ], resize_keyboard=True)

# === ХЕНДЛЕРЫ ===
@dp.message(Command("start"))
async def cmd_start(message: Message):
    logger.info(f"👤 /start от {message.from_user.id}")
    
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)', 
                        (message.from_user.id, message.from_user.username))
        await db.commit()
    
    # INLINE КНОПКА — КРИТИЧЕСКИ ВАЖНО!
    inline_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛍 ОТКРЫТЬ МАГАЗИН", web_app=WebAppInfo(url=MINI_APP_URL))]
    ])
    
    if message.from_user.id == ADMIN_ID:
        await message.answer("👋 <b>Админ меню:</b>", reply_markup=get_admin_kb(), parse_mode="HTML")
        await asyncio.sleep(0.5)
        await message.answer("👇 <b>Магазин:</b>", reply_markup=inline_kb, parse_mode="HTML")
    else:
        await message.answer(
            "👋 <b>Добро пожаловать в RZ SHOP!</b>\n\n"
            "🛍 <b>Нажми кнопку ниже чтобы открыть магазин:</b>",
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
    
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute('SELECT id, item_name, status FROM orders ORDER BY id DESC') as cursor:
            orders = await cursor.fetchall()
    
    if not orders:
        await message.answer("📭 Нет заказов")
        return
    
    builder = InlineKeyboardBuilder()
    for oid, item, status in orders:
        builder.button(text=f"#{oid} | {status}", callback_data=f"edit_{oid}")
    builder.button(text="🔙 Назад", callback_data="admin_back")
    builder.adjust(1)
    
    await message.answer("📦 <b>Заказы:</b>\n\nВыберите заказ:", reply_markup=builder.as_markup(), parse_mode="HTML")

@dp.message(F.text == "📦 Мои заказы")
async def my_orders(message: Message):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute('SELECT id, item_name, status FROM orders WHERE user_id = ? ORDER BY id DESC', (message.from_user.id,)) as cursor:
            orders = await cursor.fetchall()
    
    if not orders:
        await message.answer("📭 У вас нет заказов")
        return
    
    text = "📦 <b>Ваши заказы:</b>\n\n"
    for oid, item, status in orders:
        text += f"№{oid}: {item}\nСтатус: <b>{status}</b>\n\n"
    
    await message.answer(text, parse_mode="HTML")

@dp.message(F.text == "💰 Бонусы")
async def my_bonus(message: Message):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute('SELECT balance FROM users WHERE user_id = ?', (message.from_user.id,)) as cursor:
            res = await cursor.fetchone()
            bal = res[0] if res else 0
    await message.answer(f"💰 <b>Ваш баланс:</b> {bal} ₽", parse_mode="HTML")

@dp.message(F.text == "ℹ️ Помощь")
async def help_cmd(message: Message):
    await message.answer("📞 <b>Поддержка:</b> @support_manager", parse_mode="HTML")

@dp.message(F.text == "🔙 В меню")
async def back_menu(message: Message):
    kb = get_admin_kb() if message.from_user.id == ADMIN_ID else get_user_kb()
    await message.answer("📂 <b>Меню:</b>", reply_markup=kb, parse_mode="HTML")

# === ГЛАВНОЕ: ПРИЁМ ЗАКАЗА ИЗ MINI APP ===
@dp.message(F.web_app_data)
async def handle_webapp_order(message: Message):
    logger.info("=" * 60)
    logger.info("📩 === ПОЛУЧЕНЫ ДАННЫЕ ИЗ MINI APP ===")
    logger.info(f"📩 От пользователя: {message.from_user.id} (@{message.from_user.username})")
    logger.info(f"📩 Data: {message.web_app_data.data}")
    logger.info("=" * 60)
    
    try:
        data = json.loads(message.web_app_data.data)
        
        if data.get('type') != 'new_order':
            logger.warning("⚠️ Неверный тип данных")
            await message.answer("❌ Неверный формат заказа")
            return
        
        items = data['items']
        total = data['total']
        customer = data['customer']
        user_id = message.from_user.id
        
        items_text = ', '.join([f"{i['title']} x{i['quantity']}" for i in items])
        
        logger.info(f"📦 Заказ: {items_text} | Сумма: {total} ₽")
        
        # Сохраняем в БД
        async with aiosqlite.connect(DB_PATH) as db:
            cursor = await db.execute(
                'INSERT INTO orders (user_id, item_name, status) VALUES (?, ?, ?)',
                (user_id, items_text, 'Новый')
            )
            order_id = cursor.lastrowid
            
            await db.execute(
                'INSERT INTO order_details (order_id, customer_name, customer_phone, customer_address, total_amount) VALUES (?, ?, ?, ?, ?)',
                (order_id, customer['name'], customer['phone'], customer['address'], total)
            )
            await db.commit()
        
        logger.info(f"✅ Заказ #{order_id} сохранён в БД")
        
        # Ответ пользователю
        await message.answer(
            f"✅ <b>Заказ #{order_id} принят!</b>\n\n"
            f"📦 {items_text}\n"
            f"💰 {total:,} ₽\n\n"
            f"Менеджер свяжется с вами в ближайшее время!",
            parse_mode="HTML"
        )
        
        # Уведомление админу
        admin_msg = (
            f"🔥 <b>НОВЫЙ ЗАКАЗ #{order_id}!</b>\n\n"
            f"📦 {items_text}\n\n"
            f"💰 <b>{total:,} ₽</b>\n\n"
            f"👤 {customer['name']}\n"
            f"📞 {customer['phone']}\n"
            f"📍 {customer['address']}\n\n"
            f"<i>Для управления: /start → 📊 Заказы</i>"
        )
        await bot.send_message(ADMIN_ID, admin_msg, parse_mode="HTML")
        logger.info("✅ Админ уведомлён")
        logger.info("=" * 60)
        
    except json.JSONDecodeError as e:
        logger.error(f"❌ Ошибка JSON: {e}")
        await message.answer(f"❌ Ошибка формата: {e}")
    except Exception as e:
        logger.error(f"❌ Ошибка обработки: {e}")
        await message.answer("❌ Произошла ошибка. Напишите в поддержку!")

# === СМЕНА СТАТУСА ЗАКАЗА ===
@dp.callback_query(F.data.startswith("edit_"))
async def edit_order(callback):
    oid = int(callback.data.split("_")[1])
    
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute('SELECT * FROM orders WHERE id = ?', (oid,)) as cursor:
            order = await cursor.fetchone()
    
    if not order:
        await callback.answer("❌ Заказ не найден", show_alert=True)
        return
    
    builder = InlineKeyboardBuilder()
    statuses = {"processing": "⏳ В работе", "packed": "📦 Собран", "shipped": "🚚 Едет", "delivered": "✅ Доставлен"}
    for key, val in statuses.items():
        builder.button(text=val, callback_data=f"status_{oid}_{key}")
    builder.button(text="🔙 Назад", callback_data="admin_back")
    builder.adjust(2)
    
    await callback.message.edit_text(
        f"📦 <b>Заказ #{oid}</b>\n\n"
        f"Товары: {order[2]}\n"
        f"Текущий статус: <b>{order[3]}</b>\n\n"
        f"Выберите новый статус:",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )

@dp.callback_query(F.data.startswith("status_"))
async def change_status(callback):
    parts = callback.data.split("_")
    oid = int(parts[1])
    new_status = parts[2]
    
    status_map = {
        "processing": "В обработке",
        "packed": "Собран",
        "shipped": "Едет к клиенту",
        "delivered": "Доставлен"
    }
    status_emoji = {"processing": "⏳", "packed": "📦", "shipped": "🚚", "delivered": "✅"}
    
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('UPDATE orders SET status = ? WHERE id = ?', (status_map[new_status], oid))
        async with db.execute('SELECT user_id FROM orders WHERE id = ?', (oid,)) as cursor:
            res = await cursor.fetchone()
            user_id = res[0] if res else None
        await db.commit()
    
    await callback.answer(f"✅ Статус изменен на: {status_map[new_status]}")
    
    # Уведомление клиенту
    if user_id:
        bonus_text = ""
        if new_status == "delivered":
            bonus_text = "\n\n🎁 Вам начислено 500 бонусов!"
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute('UPDATE users SET balance = balance + 500 WHERE user_id = ?', (user_id,))
                await db.commit()
        
        await bot.send_message(
            user_id,
            f"{status_emoji.get(new_status, '📦')} <b>Статус заказа #{oid} изменен!</b>\n\n"
            f"Новый статус: <b>{status_map[new_status]}</b>{bonus_text}",
            parse_mode="HTML"
        )
    
    await callback.message.edit_text(f"✅ Статус заказа #{oid} изменен на: {status_map[new_status]}")

@dp.callback_query(F.data == "admin_back")
async def admin_back(callback):
    await callback.message.edit_text("👋 <b>Админ меню:</b>", reply_markup=get_admin_kb(), parse_mode="HTML")

@dp.callback_query(F.data == "none")
async def none_cb(callback):
    await callback.answer()

# === ЗАПУСК ===
async def main():
    logger.info("=" * 60)
    logger.info("🚀 ЗАПУСК RZ SHOP BOT")
    logger.info(f"💾 Bothost Plan: 4 vCPU, 2 GB RAM")
    logger.info("=" * 60)
    
    await init_db()
    
    # Убираем кнопку меню слева (ОБЯЗАТЕЛЬНО!)
    await bot.set_chat_menu_button()
    logger.info("✅ Кнопка меню убрана")
    logger.info("🤖 Бот готов к работе!")
    logger.info("=" * 60)
    
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
