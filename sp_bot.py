import asyncio
import sqlite3
from datetime import datetime, timedelta
import pandas as pd
import os

from aiogram import Bot, Dispatcher, F
from aiogram.types import (
    Message,
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from aiogram.types.input_file import FSInputFile
from aiogram.filters import Command
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage

# ----------------------
# Токен
# ----------------------
API_TOKEN = os.getenv("TELEGRAM_TOKEN")

bot = Bot(token=API_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# ----------------------
# База данных
# ----------------------
conn = sqlite3.connect("data.db")
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT,
    datetime TEXT,
    antecedent TEXT,
    behavior TEXT,
    consequence TEXT
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS antecedents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT,
    name TEXT
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS behaviors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT,
    name TEXT
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS consequences (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT,
    name TEXT
)
""")

conn.commit()

# ----------------------
# FSM состояния
# ----------------------
class RecordStates(StatesGroup):
    antecedent = State()
    behavior = State()
    consequence = State()
    add_category_name = State()
    add_category_type = State()
    delete_category_type = State()
    delete_category_name = State()

# ----------------------
# Главное меню
# ----------------------
def main_menu():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="➕ Добавить запись")],
            [KeyboardButton(text="📊 Сформировать отчёт")],
            [KeyboardButton(text="⚙️ Категории")],
            [KeyboardButton(text="🔄 Перезапустить бот")]
        ],
        resize_keyboard=True
    )

# ----------------------
# Старт
# ----------------------
@dp.message(Command("start"))
async def start(message: Message):
    await message.answer("Главное меню:", reply_markup=main_menu())

# ----------------------
# Загрузка категорий
# ----------------------
def load_categories(table: str, user_id: int):
    cursor.execute(f"SELECT name FROM {table} WHERE user_id = ?", (user_id,))
    user_rows = [r[0] for r in cursor.fetchall()]

    default_rows = []
    if table == "antecedents":
        default_rows = [
            "Повторяющиеся действия без переключения",
            "Привлечение внимания",
            "Отказ в доступе к желаемому",
            "Свободная деятельность",
            "Требование в пространстве",
            "Требование одеваться/раздеваться",
        ]
    elif table == "behaviors":
        default_rows = [
            "Истерика",
            "Толкает",
            "Многократно ударяет",
            "Однократно ударяет",
            "Игнорирование требований",
        ]
    elif table == "consequences":
        default_rows = [
            "Сохранение требований",
            "Игнорирование",
            "Оказание помощи",
            "Переключение",
            "Корректирующая обратная связь",
            "Предоставление желаемого",
        ]

    return default_rows + user_rows

# ----------------------
# Добавление записи
# ----------------------
@dp.message(F.text == "➕ Добавить запись")
async def add_record(message: Message, state: FSMContext):
    await state.clear()
    user_id = message.from_user.id
    antecedents = load_categories("antecedents", user_id)

    kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=a)] for a in antecedents],
        resize_keyboard=True
    )

    await state.set_state(RecordStates.antecedent)
    await message.answer("Выберите антецедент:", reply_markup=kb)

@dp.message(RecordStates.antecedent)
async def choose_behavior(message: Message, state: FSMContext):
    await state.update_data(antecedent=message.text)
    user_id = message.from_user.id
    behaviors = load_categories("behaviors", user_id)

    kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=b)] for b in behaviors],
        resize_keyboard=True
    )

    await state.set_state(RecordStates.behavior)
    await message.answer("Выберите поведение:", reply_markup=kb)

@dp.message(RecordStates.behavior)
async def choose_consequence(message: Message, state: FSMContext):
    await state.update_data(behavior=message.text)
    user_id = message.from_user.id
    consequences = load_categories("consequences", user_id)

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=c, callback_data=f"cons:{c}")]
            for c in consequences
        ] + [[InlineKeyboardButton(text="✅ Готово", callback_data="cons:done")]]
    )

    await state.update_data(selected_consequences=[])
    await state.set_state(RecordStates.consequence)
    await message.answer("Выберите последствия (можно несколько):", reply_markup=kb)

# ----------------------
# Callback последствий
# ----------------------
@dp.callback_query(F.data.startswith("cons:"))
async def process_consequence(callback, state: FSMContext):
    data = await state.get_data()
    selected = data.get("selected_consequences", [])
    value = callback.data.split(":", 1)[1]

    if value == "done":
        if not selected:
            await callback.message.answer("Выберите хотя бы одно последствие.")
            return

        await state.update_data(consequence="; ".join(selected))
        user_id = callback.from_user.id
        record_data = await state.get_data()

        current_dt = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        cursor.execute("""
            INSERT INTO records (user_id, datetime, antecedent, behavior, consequence)
            VALUES (?, ?, ?, ?, ?)
        """, (
            user_id,
            current_dt,
            record_data["antecedent"],
            record_data["behavior"],
            record_data["consequence"]
        ))

        conn.commit()
        await state.clear()

        await callback.message.answer(
            f"Запись сохранена ✅\nВремя эпизода: {current_dt}",
            reply_markup=main_menu()
        )
    else:
        if value in selected:
            selected.remove(value)
        else:
            selected.append(value)

        await state.update_data(selected_consequences=selected)
        await callback.answer(
            f"Выбрано: {', '.join(selected) if selected else 'ничего'}"
        )

# ----------------------
# Запуск через polling
# ----------------------
async def main():
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())