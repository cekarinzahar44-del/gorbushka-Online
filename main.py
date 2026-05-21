import os
import logging
import asyncio
import json
import sqlite3
import threading
from flask import Flask, request, jsonify
from flask_cors import CORS
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.types import (Message, ReplyKeyboardMarkup, KeyboardButton,
                           InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

# ── НАСТРОЙКИ ─────────────────────────────────────────────────────────
TOKEN        = os.getenv("BOT_TOKEN")
ADMIN_ID     = int(os.getenv("ADMIN_ID", 8043971654))
MINI_APP_URL = os.getenv("MINI_APP_URL", "https://твой-ник.github.io/твой-репо/")

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

bot     = Bot(token=TOKEN)
storage = MemoryStorage()
dp      = Dispatcher(storage=storage)
app     = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})
DB_PATH = 'shop.db'

# ── FSM состояния ─────────────────────────────────────────────────────
class SupportStates(StatesGroup):
    waiting_support_msg  = State()   # ждём сообщение поддержки
    waiting_receipt_photo = State()  # ждём фото чека

# ── Хранилище активных обращений: { user_id: { type, order_id } } ────
active_support = {}

# ── ОТПРАВКА ИЗ FLASK ─────────────────────────────────────────────────
def send_telegram_message(chat_id, text):
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

# ── БД ────────────────────────────────────────────────────────────────
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER, username TEXT, item_name TEXT,
        total_amount INTEGER, customer_name TEXT,
        customer_phone TEXT, customer_address TEXT,
        customer_comment TEXT, status TEXT DEFAULT 'Новый',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY, username TEXT,
        balance INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    conn.commit(); conn.close()
    logger.info("✅ БД готова")

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

# ── FLASK API ─────────────────────────────────────────────────────────
@app.route('/get_orders', methods=['GET','OPTIONS'])
def get_orders():
    if request.method == 'OPTIONS': return '', 204
    try:
        user_id = request.args.get('user_id', type=int)
        if not user_id: return jsonify({'success':False,'error':'user_id required'}), 400
        conn = get_db()
        rows = conn.execute(
            'SELECT id,item_name,total_amount,status,customer_comment,created_at '
            'FROM orders WHERE user_id=? ORDER BY id DESC LIMIT 50', (user_id,)
        ).fetchall()
        conn.close()
        return jsonify({'success':True, 'orders':[
            {'id':r['id'],'items':r['item_name'],'total':r['total_amount'],
             'status':r['status'],'comment':r['customer_comment'],'date':r['created_at']}
            for r in rows
        ]})
    except Exception as e:
        return jsonify({'success':False,'error':str(e)}), 500

@app.route('/create_order', methods=['POST','OPTIONS'])
def create_order():
    if request.method == 'OPTIONS': return '', 204
    try:
        data     = request.json
        items    = data.get('items', [])
        total    = data.get('total', 0)
        customer = data.get('customer', {})
        user_id  = data.get('user_id', 0)
        username = data.get('username', 'unknown')
        items_text = ', '.join([f"{i.get('title','Товар')} x{i.get('quantity',1)}" for i in items])

        conn = get_db(); c = conn.cursor()
        c.execute('''INSERT INTO orders
            (user_id,username,item_name,total_amount,customer_name,
             customer_phone,customer_address,customer_comment,status)
            VALUES (?,?,?,?,?,?,?,?,?)''',
            (user_id, username, items_text, total,
             customer.get('name',''), customer.get('phone',''),
             customer.get('address',''), customer.get('comment',''), 'Новый'))
        order_id = c.lastrowid
        conn.commit(); conn.close()

        # Уведомление пользователю
        send_telegram_message(user_id,
            f"✅ <b>Заказ #{order_id} создан!</b>\n\n"
            f"📦 {items_text}\n"
            f"💰 <b>{total:,} ₽</b>\n\n"
            f"📊 Статус: <b>Новый</b>\n"
            f"📸 Отправьте скриншот оплаты боту командой /receipt"
        )
        # Уведомление админу
        send_telegram_message(ADMIN_ID,
            f"🔥 <b>НОВЫЙ ЗАКАЗ #{order_id}!</b>\n\n"
            f"📦 {items_text}\n"
            f"💰 <b>{total:,} ₽</b>\n\n"
            f"👤 {customer.get('name','')}\n"
            f"📞 {customer.get('phone','')}\n"
            f"📍 {customer.get('address','')}\n"
            f"💬 {customer.get('comment','Нет')}\n\n"
            f"🔗 @{username} (ID: {user_id})"
        )
        return jsonify({'success':True,'order_id':order_id,'items':items_text,'total':total})
    except Exception as e:
        logger.error(f"❌ {e}")
        return jsonify({'success':False,'error':str(e)}), 500

@app.route('/health')
def health(): return jsonify({'status':'ok'})

# ── БОТ: /start ───────────────────────────────────────────────────────
@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    uid = message.from_user.id

    # Сохраняем юзера
    conn = get_db()
    conn.execute('INSERT OR IGNORE INTO users (user_id,username) VALUES (?,?)',
                 (uid, message.from_user.username))
    conn.commit(); conn.close()

    args = message.text.split(maxsplit=1)
    param = args[1].strip() if len(args) > 1 else ''

    # ── Поддержка из магазина ──────────────────────────────────────────
    if param == 'support':
        # Удаляем сообщение со /start чтобы не показывать команду
        try: await message.delete()
        except: pass
        await bot.send_message(
            uid,
            "💬 <b>Поддержка RZ SHOP</b>\n\n"
            "Напишите ваш вопрос — текст, фото или скриншот.\n"
            "Мы ответим в ближайшее время 👇",
            parse_mode="HTML"
        )
        active_support[uid] = {'type': 'support'}
        await state.set_state(SupportStates.waiting_support_msg)
        return

    # ── Отправить чек ──────────────────────────────────────────────────
    if param == 'receipt':
        # Удаляем сообщение со /start чтобы не показывать команду
        try: await message.delete()
        except: pass
        await bot.send_message(
            uid,
            "📸 <b>Отправка чека об оплате</b>\n\n"
            "Пришлите скриншот или фото чека оплаты.\n"
            "Администратор проверит и подтвердит заказ 👇",
            parse_mode="HTML"
        )
        active_support[uid] = {'type': 'receipt'}
        await state.set_state(SupportStates.waiting_receipt_photo)
        return

    # ── Реферальная ссылка ─────────────────────────────────────────────
    if param.startswith('ref_'):
        ref_id = param[4:]
        logger.info(f"Реферал от {ref_id} → {uid}")
        # Можно начислить бонус рефереру

    # ── Обычный старт ─────────────────────────────────────────────────
    shop_btn = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛍 ОТКРЫТЬ МАГАЗИН", web_app=WebAppInfo(url=MINI_APP_URL))]
    ])

    if uid == ADMIN_ID:
        await message.answer(
            "👋 <b>Админ-панель RZ SHOP</b>",
            reply_markup=_admin_kb(), parse_mode="HTML"
        )
    else:
        name = message.from_user.first_name or "Друг"
        await message.answer(
            f"✨ <b>Добро пожаловать в RZ SHOP, {name}!</b>\n\n"
            f"📱 Премиум электроника по лучшим ценам\n"
            f"🚀 Быстрая доставка по всей России\n"
            f"💎 Гарантия качества на все товары\n\n"
            f"👇 Нажмите чтобы открыть магазин:",
            reply_markup=shop_btn, parse_mode="HTML"
        )

# ── ПОЛУЧАЕМ СООБЩЕНИЕ ПОДДЕРЖКИ ─────────────────────────────────────
@dp.message(SupportStates.waiting_support_msg)
async def receive_support_msg(message: Message, state: FSMContext):
    uid  = message.from_user.id
    name = message.from_user.first_name or 'Аноним'
    uname = f"@{message.from_user.username}" if message.from_user.username else f"ID:{uid}"

    # Пересылаем админу
    await bot.send_message(
        ADMIN_ID,
        f"💬 <b>Обращение в поддержку</b>\n\n"
        f"👤 {name} ({uname})\n"
        f"🆔 ID: {uid}\n\n"
        f"📝 <b>Сообщение:</b>\n{message.text or '[медиа файл]'}",
        parse_mode="HTML"
    )

    # Если есть фото — пересылаем
    if message.photo:
        await bot.send_photo(
            ADMIN_ID,
            photo=message.photo[-1].file_id,
            caption=f"📎 Фото от {name} ({uname})"
        )
    elif message.document:
        await bot.send_document(
            ADMIN_ID,
            document=message.document.file_id,
            caption=f"📎 Файл от {name} ({uname})"
        )

    await message.answer(
        "✅ <b>Сообщение отправлено!</b>\n\n"
        "Мы ответим вам в течение нескольких минут.",
        parse_mode="HTML"
    )
    active_support.pop(uid, None)
    await state.clear()

# ── ПОЛУЧАЕМ ФОТО ЧЕКА ────────────────────────────────────────────────
@dp.message(SupportStates.waiting_receipt_photo)
async def receive_receipt(message: Message, state: FSMContext):
    uid  = message.from_user.id
    name = message.from_user.first_name or 'Аноним'
    uname = f"@{message.from_user.username}" if message.from_user.username else f"ID:{uid}"

    sent = False

    if message.photo:
        await bot.send_photo(
            ADMIN_ID,
            photo=message.photo[-1].file_id,
            caption=(
                f"💳 <b>ЧЕК ОБ ОПЛАТЕ</b>\n\n"
                f"👤 {name} ({uname})\n"
                f"🆔 ID: {uid}\n\n"
                f"✅ Проверьте платёж и подтвердите заказ"
            ),
            parse_mode="HTML"
        )
        sent = True
    elif message.document:
        await bot.send_document(
            ADMIN_ID,
            document=message.document.file_id,
            caption=(
                f"💳 <b>ЧЕК ОБ ОПЛАТЕ (файл)</b>\n\n"
                f"👤 {name} ({uname})\n"
                f"🆔 ID: {uid}"
            ),
            parse_mode="HTML"
        )
        sent = True
    elif message.text:
        await bot.send_message(
            ADMIN_ID,
            f"💳 <b>ЧЕК (текст)</b>\n\n"
            f"👤 {name} ({uname})\n"
            f"🆔 ID: {uid}\n\n"
            f"{message.text}",
            parse_mode="HTML"
        )
        sent = True

    if sent:
        await message.answer(
            "✅ <b>Чек отправлен администратору!</b>\n\n"
            "Мы проверим платёж и обновим статус заказа в течение нескольких минут.\n\n"
            "📦 Статус заказа: Мои заказы → Профиль в магазине",
            parse_mode="HTML"
        )
    else:
        await message.answer("⚠️ Пожалуйста, отправьте фото или скриншот чека.")
        return

    active_support.pop(uid, None)
    await state.clear()

# ── ОТВЕТ АДМИНА ПОЛЬЗОВАТЕЛЮ ─────────────────────────────────────────
@dp.message(F.text.startswith('/reply'))
async def admin_reply(message: Message):
    if message.from_user.id != ADMIN_ID: return
    # /reply 123456789 Текст ответа
    parts = message.text.split(maxsplit=2)
    if len(parts) < 3:
        return await message.answer("❌ Формат: /reply USER_ID Текст ответа")
    try:
        target_id = int(parts[1])
        text = parts[2]
        await bot.send_message(target_id,
            f"📨 <b>Ответ поддержки RZ SHOP:</b>\n\n{text}",
            parse_mode="HTML")
        await message.answer(f"✅ Ответ отправлен пользователю {target_id}")
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")

# ── АДМИН КЛАВИАТУРА ──────────────────────────────────────────────────
def _admin_kb():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="📊 Заказы")],
        [KeyboardButton(text="📈 Статистика")],
        [KeyboardButton(text="📢 Рассылка")]
    ], resize_keyboard=True)

@dp.message(F.text == "📊 Заказы")
async def admin_orders(message: Message):
    if message.from_user.id != ADMIN_ID: return
    conn = get_db()
    rows = conn.execute(
        'SELECT id,item_name,status,total_amount FROM orders ORDER BY id DESC LIMIT 20'
    ).fetchall()
    conn.close()
    if not rows: return await message.answer("📭 Нет заказов")
    b = InlineKeyboardBuilder()
    for r in rows:
        b.button(text=f"#{r[0]} | {r[2]} | {r[3]:,}₽", callback_data=f"edit_{r[0]}")
    b.adjust(1)
    await message.answer("📦 Последние заказы:", reply_markup=b.as_markup())

@dp.message(F.text == "📈 Статистика")
async def admin_stats(message: Message):
    if message.from_user.id != ADMIN_ID: return
    conn = get_db()
    total   = conn.execute('SELECT COUNT(*) FROM orders').fetchone()[0]
    revenue = conn.execute('SELECT SUM(total_amount) FROM orders').fetchone()[0] or 0
    users   = conn.execute('SELECT COUNT(*) FROM users').fetchone()[0]
    new_ord = conn.execute("SELECT COUNT(*) FROM orders WHERE status='Новый'").fetchone()[0]
    conn.close()
    await message.answer(
        f"📈 <b>Статистика магазина</b>\n\n"
        f"📦 Всего заказов: <b>{total}</b>\n"
        f"🆕 Новых: <b>{new_ord}</b>\n"
        f"💰 Выручка: <b>{revenue:,} ₽</b>\n"
        f"👥 Пользователей: <b>{users}</b>",
        parse_mode="HTML"
    )

@dp.message(F.text == "📢 Рассылка")
async def admin_broadcast_info(message: Message):
    if message.from_user.id != ADMIN_ID: return
    await message.answer(
        "📢 <b>Рассылка</b>\n\n"
        "Используйте команду:\n"
        "<code>/broadcast Текст сообщения</code>",
        parse_mode="HTML"
    )

# ── ИЗМЕНЕНИЕ СТАТУСА ЗАКАЗА ──────────────────────────────────────────
@dp.callback_query(F.data.startswith("edit_"))
async def edit_order(callback):
    if callback.from_user.id != ADMIN_ID:
        return await callback.answer("❌", show_alert=True)
    oid = int(callback.data.split("_")[1])
    conn = get_db()
    row = conn.execute('SELECT * FROM orders WHERE id=?', (oid,)).fetchone()
    conn.close()
    if not row: return await callback.answer("Заказ не найден", show_alert=True)

    b = InlineKeyboardBuilder()
    statuses = {
        "in_work":   "⏳ В обработке",
        "packed":    "📦 Собран",
        "shipped":   "🚚 Отправлен",
        "delivered": "✅ Доставлен",
        "cancelled": "❌ Отменён"
    }
    for k,v in statuses.items():
        b.button(text=v, callback_data=f"status_{oid}_{k}")
    b.adjust(2)

    await callback.message.edit_text(
        f"📦 <b>Заказ #{oid}</b>\n"
        f"📊 Статус: {row['status']}\n"
        f"📝 {row['item_name']}\n"
        f"💰 {row['total_amount']:,} ₽\n"
        f"👤 {row['customer_name']} · {row['customer_phone']}",
        reply_markup=b.as_markup(), parse_mode="HTML"
    )

@dp.callback_query(F.data.startswith("status_"))
async def change_status(callback):
    if callback.from_user.id != ADMIN_ID:
        return await callback.answer("❌", show_alert=True)
    parts = callback.data.split("_", 2)
    oid, key = int(parts[1]), parts[2]
    status_map = {
        "in_work":"В обработке","packed":"Собран",
        "shipped":"Отправлен","delivered":"Доставлен","cancelled":"Отменён"
    }
    new_status = status_map.get(key, "Новый")
    conn = get_db()
    conn.execute('UPDATE orders SET status=? WHERE id=?', (new_status, oid))
    row = conn.execute('SELECT user_id FROM orders WHERE id=?', (oid,)).fetchone()
    conn.commit(); conn.close()

    await callback.answer("✅ Статус обновлён")

    # Уведомляем клиента
    if row and row['user_id']:
        status_emoji = {"В обработке":"⏳","Собран":"📦","Отправлен":"🚚","Доставлен":"✅","Отменён":"❌"}
        emoji = status_emoji.get(new_status, "📋")
        try:
            await bot.send_message(
                row['user_id'],
                f"{emoji} <b>Статус заказа #{oid} изменён</b>\n\n"
                f"Новый статус: <b>{new_status}</b>\n\n"
                f"Следите за заказами в разделе «Мои заказы» в магазине 🛍",
                parse_mode="HTML"
            )
        except Exception as e:
            logger.error(f"Не удалось уведомить клиента: {e}")

    await callback.message.edit_text(
        f"✅ Статус заказа #{oid} → <b>{new_status}</b>",
        parse_mode="HTML"
    )

# ── РАССЫЛКА ──────────────────────────────────────────────────────────
@dp.message(Command("broadcast"))
async def broadcast(message: Message):
    if message.from_user.id != ADMIN_ID: return
    text = message.text.replace("/broadcast", "").strip()
    if not text:
        return await message.answer("❌ Используйте: <code>/broadcast Текст</code>", parse_mode="HTML")
    conn = get_db()
    users = conn.execute('SELECT user_id FROM users WHERE user_id!=?', (ADMIN_ID,)).fetchall()
    conn.close()
    sent = 0
    for u in users:
        try:
            await bot.send_message(u[0], f"📢 <b>RZ SHOP</b>\n\n{text}", parse_mode="HTML")
            sent += 1
            await asyncio.sleep(0.05)
        except: pass
    await message.answer(f"✅ Отправлено {sent} пользователям")

# ── ЗАПУСК ────────────────────────────────────────────────────────────
def run_flask():
    logger.info("🌐 Flask запускается...")
    app.run(host='0.0.0.0', port=8000, debug=False, use_reloader=False, threaded=True)

async def run_bot():
    logger.info("🤖 Бот запускается...")
    # Скрываем команды из меню (чтобы /start не светился)
    from aiogram.types import BotCommand
    await bot.set_my_commands([
        BotCommand(command="start", description="Открыть магазин"),
    ])
    await dp.start_polling(bot)

def main():
    init_db()
    threading.Thread(target=run_flask, daemon=True).start()
    import time; time.sleep(1)
    logger.info("✅ Всё готово | RZ SHOP работает!")
    asyncio.run(run_bot())

if __name__ == '__main__':
    main()
