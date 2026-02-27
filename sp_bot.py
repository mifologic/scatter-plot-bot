import asyncio
import sqlite3
from datetime import datetime, timedelta
import pandas as pd

from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery, FSInputFile, ReplyKeyboardRemove
from aiogram.filters import Command
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage

API_TOKEN = "8680938005:AAHLoCiLCkiCdsprr6bjSyjx11zLnHTejD0"

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
    datetime TEXT,
    antecedent TEXT,
    behavior TEXT,
    consequence TEXT
)
""")
conn.commit()

# ----------------------
# Категории
# ----------------------
ANTECEDENTS = [
    "Повторяющиеся действия без переключения",
    "Привлечение внимания",
    "Отказ в доступе к желаемому",
    "Свободная деятельность",
    "Требование в пространстве",
    "Требование одеваться/раздеваться",
]

BEHAVIORS = [
    "Истерика",
    "Толкает",
    "Многократно ударяет",
    "Однократно ударяет",
    "Игнорирование требований",
]

CONSEQUENCES = [
    "Сохранение требований",
    "Игнорирование",
    "Оказание помощи",
    "Переключение",
    "Корректирующая обратная связь",
    "Предоставление желаемого",
]

# ----------------------
# FSM состояния
# ----------------------
class RecordStates(StatesGroup):
    antecedent = State()
    behavior = State()
    consequences = State()

# ----------------------
# Главное меню
# ----------------------
def main_menu():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="➕ Добавить запись")],
            [KeyboardButton(text="📊 Сформировать отчёт")]
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
# Добавление записи
# ----------------------
@dp.message(F.text == "➕ Добавить запись")
async def add_record(message: Message, state: FSMContext):
    await state.clear()
    kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=a)] for a in ANTECEDENTS],
        resize_keyboard=True
    )
    await state.set_state(RecordStates.antecedent)
    await message.answer("Выберите антецедент:", reply_markup=kb)

@dp.message(RecordStates.antecedent)
async def choose_behavior(message: Message, state: FSMContext):
    await state.update_data(antecedent=message.text)
    kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=b)] for b in BEHAVIORS],
        resize_keyboard=True
    )
    await state.set_state(RecordStates.behavior)
    await message.answer("Выберите поведение:", reply_markup=kb)

# ----------------------
# Inline-клавиатура для множественного выбора последствий
# ----------------------
def consequences_keyboard(selected=None):
    selected = selected or []
    button_rows = []
    temp_row = []

    for i, c in enumerate(CONSEQUENCES, 1):
        temp_row.append(
            InlineKeyboardButton(
                text=f"{'✅ ' if c in selected else ''}{c}",
                callback_data=f"cons_{c}"
            )
        )
        if i % 2 == 0:
            button_rows.append(temp_row)
            temp_row = []
    if temp_row:
        button_rows.append(temp_row)

    button_rows.append([InlineKeyboardButton(text="Готово", callback_data="cons_done")])
    return InlineKeyboardMarkup(inline_keyboard=button_rows)

# ----------------------
# Переход к выбору последствий
# ----------------------
@dp.message(RecordStates.behavior)
async def choose_consequence(message: Message, state: FSMContext):
    await state.update_data(behavior=message.text)
    await state.set_state(RecordStates.consequences)

    # inline-кнопки для множественного выбора
    inline_kb = consequences_keyboard()

    # Отправляем одно сообщение с текстом, inline-кнопками и убираем ReplyKeyboard
    await message.answer(
        text="Выберите последствия (можно несколько):",
        reply_markup=inline_kb
    )
    await message.answer(
        text="Выбранное поведение: ✅",  # текст обязательно непустой
        reply_markup=ReplyKeyboardRemove()
    )

# ----------------------
# Обработка выбора последствий
# ----------------------
@dp.callback_query(F.data.startswith("cons_"))
async def handle_consequence_selection(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    selected = data.get("selected_consequences", [])

    action = callback.data[5:]  # убираем "cons_"

    if action == "done":
        if not selected:
            await callback.message.answer("Выберите хотя бы одно последствие!")
            return

        user_data = await state.get_data()
        antecedent = user_data.get("antecedent")
        behavior = user_data.get("behavior")
        consequence_str = "; ".join(selected)
        current_dt = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # Сохраняем запись
        cursor.execute("""
        INSERT INTO records (datetime, antecedent, behavior, consequence)
        VALUES (?, ?, ?, ?)
        """, (current_dt, antecedent, behavior, consequence_str))
        conn.commit()

        await state.clear()

        # Убираем inline-кнопки и показываем главное меню
        await callback.message.edit_text(
            f"Запись сохранена ✅\nВремя эпизода: {current_dt}\nВыбранные последствия: {consequence_str}",
            reply_markup=None
        )

        await callback.message.answer(
            "Главное меню:",
            reply_markup=main_menu()
        )
    else:
        # переключаем выбор
        if action in selected:
            selected.remove(action)
        else:
            selected.append(action)
        await state.update_data(selected_consequences=selected)
        await callback.message.edit_text(
            "Выберите последствия (можно несколько):",
            reply_markup=consequences_keyboard(selected)
        )

# ----------------------
# Формирование отчёта
# ----------------------
@dp.message(F.text == "📊 Сформировать отчёт")
async def generate_report(message: Message, state: FSMContext):
    await state.clear()

    end_date = datetime.now()
    start_date = end_date - timedelta(days=14)

    df = pd.read_sql_query("""
    SELECT * FROM records
    WHERE datetime BETWEEN ? AND ?
    """, conn, params=(
        start_date.strftime("%Y-%m-%d 00:00:00"),
        end_date.strftime("%Y-%m-%d 23:59:59")
    ))

    if df.empty:
        print("Данных нет за последние 15 дней.")
    else:
        df["column"] = pd.to_datetime(df["datetime"]).dt.strftime("%d.%m-%H:%M")

        # строки отчёта
        rows = ANTECEDENTS + ["ПОВЕДЕНИЕ"] + BEHAVIORS + ["ПОСЛЕДСТВИЯ"] + CONSEQUENCES
        columns = df["column"].tolist()

        # пустой DataFrame
        result = pd.DataFrame("", index=rows, columns=columns)

        # функция безопасного добавления "●"
        def add_dot(cell_value):
            if isinstance(cell_value, str) and cell_value.strip():
                return cell_value + " ●"
            else:
                return "●"

        # заполняем точки
        for _, row in df.iterrows():
            col = row["column"]
            # антецедент
            result.at[row["antecedent"], col] = add_dot(result.at[row["antecedent"], col])
            # поведение
            result.at[row["behavior"], col] = add_dot(result.at[row["behavior"], col])
            # последствия (множественные)
            for cons in row["consequence"].split("; "):
                result.at[cons, col] = add_dot(result.at[cons, col])

        # ----------------------
        # запись в Excel с форматированием
        # ----------------------
        file_name = "scatter_report.xlsx"
        with pd.ExcelWriter(file_name, engine="xlsxwriter") as writer:
            result.to_excel(writer, sheet_name="Отчёт")
            workbook = writer.book
            worksheet = writer.sheets["Отчёт"]

            # формат жирного текста
            bold_format = workbook.add_format({'bold': True})

            # делаем жирными заголовки "ПОВЕДЕНИЕ" и "ПОСЛЕДСТВИЯ"
            for i, idx in enumerate(result.index):
                if idx in ["ПОВЕДЕНИЕ", "ПОСЛЕДСТВИЯ"]:
                    worksheet.write(i + 1, 0, idx, bold_format)

            # увеличиваем ширину колонок и высоту строк
            for i, col_name in enumerate(result.columns, start=1):
                worksheet.set_column(i, i, 12)
            for i in range(len(result.index)):
                worksheet.set_row(i + 1, 20)

        print(f"Отчёт сохранён в {file_name}")

    await message.answer_document(
        document=FSInputFile(file_name),
        caption="Отчёт за последние 15 дней"
    )

# ----------------------
# Запуск
# ----------------------
async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())