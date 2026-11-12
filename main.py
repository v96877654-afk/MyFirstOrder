
import asyncio
import os
import sqlite3
import logging
import html

from datetime import datetime

from dotenv import load_dotenv

from aiogram import Bot, Dispatcher, Router, F
from aiogram.filters import Command, StateFilter
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger


# ==========================================
# НАСТРОЙКИ
# ==========================================

# Установка:
# pip install aiogram apscheduler python-dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = os.getenv("ADMIN_ID")

if not BOT_TOKEN or not ADMIN_ID:
    raise ValueError("Заполните BOT_TOKEN и ADMIN_ID в .env")

ADMIN_ID = int(ADMIN_ID)

DB_NAME = "applications.db"

logging.basicConfig(level=logging.INFO)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
router = Router()

scheduler = AsyncIOScheduler(timezone="Europe/Moscow")


# ==========================================
# БАЗА ДАННЫХ
# ==========================================

def init_db():
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS applications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                contact TEXT NOT NULL,
                task TEXT NOT NULL
            )
        """)

        conn.commit()


def save_application(name, contact, task):
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.execute("""
            INSERT INTO applications (name, contact, task)
            VALUES (?, ?, ?)
        """, (name, contact, task))

        return cursor.lastrowid


def get_applications():
    with sqlite3.connect(DB_NAME) as conn:
        return conn.execute("""
            SELECT id, name, contact, task
            FROM applications
            ORDER BY id DESC
        """).fetchall()


# ==========================================
# FSM СОСТОЯНИЯ
# ==========================================

class Application(StatesGroup):
    name = State()
    contact = State()
    task = State()


# ==========================================
# /START
# ==========================================

@router.message(Command("start"))
async def start(message: Message, state: FSMContext):

    await state.clear()

    await message.answer(
        "Здравствуйте! 👋\n\n"
        "Добро пожаловать в нашего бота!\n"
        "Давайте оформим заявку.\n\n"
        "Введите ваше имя:"
    )

    await state.set_state(Application.name)


# ==========================================
# /HELP
# ==========================================

@router.message(Command("help"))
async def help_command(message: Message):

    await message.answer(
        "📚 <b>Список команд:</b>\n\n"
        "/start — создать заявку\n"
        "/help — помощь\n"
        "/list — список заявок (администратор)",
        parse_mode="HTML"
    )


# ==========================================
# FSM: ИМЯ
# ==========================================

@router.message(StateFilter(Application.name), F.text)
async def get_name(message: Message, state: FSMContext):

    name = message.text.strip()

    if not name or len(name) > 100:
        await message.answer("Введите корректное имя.")
        return

    await state.update_data(name=name)

    await message.answer(
        "Отлично! Теперь введите номер телефона "
        "или другой контакт:"
    )

    await state.set_state(Application.contact)


# ==========================================
# FSM: КОНТАКТ
# ==========================================

@router.message(StateFilter(Application.contact), F.text)
async def get_contact(message: Message, state: FSMContext):

    contact = message.text.strip()

    if not contact or len(contact) > 100:
        await message.answer("Введите корректный контакт.")
        return

    await state.update_data(contact=contact)

    await message.answer(
        "Теперь подробно опишите вашу задачу:"
    )

    await state.set_state(Application.task)


# ==========================================
# FSM: ЗАДАЧА
# ==========================================

@router.message(StateFilter(Application.task), F.text)
async def get_task(message: Message, state: FSMContext):

    task = message.text.strip()

    if not task or len(task) > 3000:
        await message.answer(
            "Описание должно быть от 1 до 3000 символов."
        )
        return

    data = await state.get_data()

    name = data["name"]
    contact = data["contact"]

    # Сохраняем заявку
    application_id = save_application(name, contact, task)

    # Формируем уведомление
    admin_text = (
        "📩 <b>НОВАЯ ЗАЯВКА</b>\n\n"
        f"🆔 Номер: {application_id}\n"
        f"👤 Имя: {html.escape(name)}\n"
        f"📞 Контакт: {html.escape(contact)}\n"
        f"📝 Задача: {html.escape(task)}\n"
        f"🕒 Дата: {datetime.now().strftime('%d.%m.%Y %H:%M')}"
    )

    try:
        await bot.send_message(
            ADMIN_ID,
            admin_text,
            parse_mode="HTML"
        )
    except Exception:
        logging.exception("Ошибка отправки заявки администратору")

    await message.answer(
        "✅ Спасибо, заявка принята!\n\n"
        "Мы свяжемся с вами в ближайшее время."
    )

    await state.clear()


# ==========================================
# /LIST — СПИСОК ЗАЯВОК
# ==========================================

@router.message(Command("list"))
async def list_applications(message: Message):

    if message.from_user.id != ADMIN_ID:
        await message.answer("⛔ Доступ запрещён.")
        return

    applications = get_applications()

    if not applications:
        await message.answer("📭 Заявок пока нет.")
        return

    current_text = "📋 <b>СПИСОК ЗАЯВОК</b>\n\n"

    for app in applications:

        app_id, name, contact, task = app

        item = (
            f"🆔 <b>Заявка №{app_id}</b>\n"
            f"👤 Имя: {html.escape(name)}\n"
            f"📞 Контакт: {html.escape(contact)}\n"
            f"📝 Задача: {html.escape(task)}\n"
            "━━━━━━━━━━━━━━\n"
        )

        if len(current_text) + len(item) > 3500:
            await message.answer(
                current_text,
                parse_mode="HTML"
            )
            current_text = ""

        current_text += item

    if current_text:
        await message.answer(
            current_text,
            parse_mode="HTML"
        )


# ==========================================
# УМНЫЕ ОТВЕТЫ
# ==========================================

SMART_ANSWERS = {
    "привет": "Здравствуйте! Чем могу помочь?",
    "как дела": "Отлично, готов к работе!"
}


@router.message(StateFilter(None), F.text)
async def smart_answers(message: Message):

    text = message.text.lower().strip()

    answer = SMART_ANSWERS.get(text)

    if answer:
        await message.answer(answer)


# ==========================================
# НАПОМИНАНИЕ АДМИНУ
# ==========================================

async def send_daily_reminder():

    try:
        await bot.send_message(
            ADMIN_ID,
            "🔔 Проверь новые заявки!"
        )

    except Exception:
        logging.exception("Ошибка отправки напоминания")


# ==========================================
# ЗАПУСК
# ==========================================

async def main():

    init_db()

    # Регистрируем все обработчики
    dp.include_router(router)

    # Ежедневно в 12:00 по Москве
    scheduler.add_job(
        send_daily_reminder,
        CronTrigger(hour=12, minute=0),
        id="daily_reminder",
        replace_existing=True
    )

    scheduler.start()

    logging.info("Бот запущен!")

    try:
        await dp.start_polling(bot)

    finally:
        scheduler.shutdown(wait=False)
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
