import asyncio
import sqlite3
from datetime import datetime, timedelta
import pandas as pd
import os

from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.filters import Command
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage

API_TOKEN = os.getenv("TELEGRAM_TOKEN")  # токен через переменные окружения

bot = Bot(token=API_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# ----------------------
# База данных
# ----------------------
conn = sqlite3.connect("data.db")
cursor = conn.cursor()

# Таблицы
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
# Загрузка категорий для пользователя
# ----------------------
def load_categories(table: str, user_id: int):
    cursor.execute(f"SELECT name FROM {table} WHERE user_id = ?", (user_id,))
    rows = [r[0] for r in cursor.fetchall()]
    # стандартные категории, если пользователь ещё ничего не добавил
    if table == "antecedents" and not rows:
        rows = [
            "Повторяющиеся действия без переключения",
            "Привлечение внимания",
            "Отказ в доступе к желаемому",
            "Свободная деятельность",
            "Требование в пространстве",
            "Требование одеваться/раздеваться",
        ]
    elif table == "behaviors" and not rows:
        rows = [
            "Истерика",
            "Толкает",
            "Многократно ударяет",
            "Однократно ударяет",
            "Игнорирование требований",
        ]
    elif table == "consequences" and not rows:
        rows = [
            "Сохранение требований",
            "Игнорирование",
            "Оказание помощи",
            "Переключение",
            "Корректирующая обратная связь",
            "Предоставление желаемого",
        ]
    return rows


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
                            [InlineKeyboardButton(text=c, callback_data=f"cons:{c}")] for c in consequences
                        ] + [[InlineKeyboardButton(text="✅ Готово", callback_data="cons:done")]]
    )
    await state.update_data(selected_consequences=[])
    await state.set_state(RecordStates.consequence)
    await message.answer("Выберите последствия (можно несколько):", reply_markup=kb)


# ----------------------
# Обработка множественного выбора последствий
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
        """, (user_id, current_dt, record_data["antecedent"], record_data["behavior"], record_data["consequence"]))
        conn.commit()
        await state.clear()
        await callback.message.answer(f"Запись сохранена ✅\nВремя эпизода: {current_dt}", reply_markup=main_menu())
    else:
        if value in selected:
            selected.remove(value)
        else:
            selected.append(value)
        await state.update_data(selected_consequences=selected)
        # отметка выбранных кнопок (необязательно: можно визуально через callback_data)
        await callback.answer(f"Выбрано: {', '.join(selected) if selected else 'ничего'}")


# ----------------------
# Формирование отчёта
# ----------------------
@dp.message(F.text == "📊 Сформировать отчёт")
async def generate_report(message: Message, state: FSMContext):
    user_id = message.from_user.id
    end_date = datetime.now()
    start_date = end_date - timedelta(days=14)
    df = pd.read_sql_query("""
        SELECT * FROM records
        WHERE user_id = ? AND datetime BETWEEN ? AND ?
    """, conn, params=(user_id, start_date.strftime("%Y-%m-%d 00:00:00"), end_date.strftime("%Y-%m-%d 23:59:59")))

    if df.empty:
        await message.answer("За последние 15 дней данных нет.")
        return

    df["column"] = pd.to_datetime(df["datetime"]).dt.strftime("%d.%m-%H:%M")
    rows = load_categories("antecedents", user_id) + ["ПОВЕДЕНИЕ"] + load_categories("behaviors", user_id) + [
        "ПОСЛЕДСТВИЯ"] + load_categories("consequences", user_id)
    columns = df["column"].tolist()
    result = pd.DataFrame("", index=rows, columns=columns)

    def add_dot(cell_value):
        if isinstance(cell_value, str) and cell_value.strip():
            return cell_value + " ●"
        else:
            return "●"

    for _, row in df.iterrows():
        col = row["column"]
        result.at[row["antecedent"], col] = add_dot(result.at[row["antecedent"], col])
        result.at[row["behavior"], col] = add_dot(result.at[row["behavior"], col])
        for cons in row["consequence"].split("; "):
            result.at[cons, col] = add_dot(result.at[cons, col])

    # запись в Excel с жирными заголовками
    file_name = f"scatter_report_{user_id}.xlsx"
    with pd.ExcelWriter(file_name, engine="xlsxwriter") as writer:
        result.to_excel(writer, sheet_name="Отчёт")
        workbook = writer.book
        worksheet = writer.sheets["Отчёт"]
        bold_format = workbook.add_format({'bold': True})
        for i, idx in enumerate(result.index):
            if idx in ["ПОВЕДЕНИЕ", "ПОСЛЕДСТВИЯ"]:
                worksheet.write(i + 1, 0, idx, bold_format)
        for i, col_name in enumerate(result.columns, start=1):
            worksheet.set_column(i, i, 12)
        for i in range(len(result.index)):
            worksheet.set_row(i + 1, 20)

    await message.answer_document(open(file_name, "rb"), caption="Отчёт за последние 15 дней")


# ----------------------
# Управление категориями
# ----------------------
@dp.message(F.text == "⚙️ Категории")
async def manage_categories(message: Message):
    kb = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="➕ Добавить категорию")],
            [KeyboardButton(text="⬅️ Назад")]
        ],
        resize_keyboard=True
    )
    await message.answer("Управление категориями:", reply_markup=kb)


@dp.message(F.text == "➕ Добавить категорию")
async def add_category_start(message: Message, state: FSMContext):
    kb = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Антецедент"), KeyboardButton(text="Поведение"), KeyboardButton(text="Последствие")],
            [KeyboardButton(text="⬅️ Отмена")]
        ],
        resize_keyboard=True
    )
    await state.set_state(RecordStates.add_category_type)
    await message.answer("Выберите тип категории:", reply_markup=kb)


@dp.message(RecordStates.add_category_type)
async def add_category_type(message: Message, state: FSMContext):
    if message.text not in ["Антецедент", "Поведение", "Последствие"]:
        await message.answer("Выберите корректный тип категории.")
        return
    await state.update_data(new_category_type=message.text)
    await state.set_state(RecordStates.add_category_name)
    await message.answer("Введите название новой категории:")


@dp.message(RecordStates.add_category_name)
async def add_category_name(message: Message, state: FSMContext):
    data = await state.get_data()
    category_type = data["new_category_type"]
    table = "antecedents" if category_type == "Антецедент" else "behaviors" if category_type == "Поведение" else "consequences"
    user_id = message.from_user.id
    cursor.execute(f"INSERT INTO {table} (user_id, name) VALUES (?, ?)", (user_id, message.text))
    conn.commit()
    await state.clear()
    await message.answer(f"Категория '{message.text}' добавлена в {category_type}.", reply_markup=main_menu())


# ----------------------
# Перезапуск бота
# ----------------------
@dp.message(F.text == "🔄 Перезапустить бот")
async def reset_user_data(message: Message):
    user_id = message.from_user.id
    # Удаляем только записи (выбранные значения) текущего пользователя
    cursor.execute("DELETE FROM records WHERE user_id = ?", (user_id,))
    conn.commit()
    await message.answer(
        "Ваши записи были очищены. Вы можете начать заново.",
        reply_markup=main_menu()
    )

# ----------------------
# Запуск
# ----------------------
async def main():
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())