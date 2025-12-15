# =====================
# LOAD ENV
# =====================
import os
from dotenv import load_dotenv
load_dotenv("sabin.env")

BOT_TOKEN = os.getenv("BOT_TOKEN")
SHEETS_ENDPOINT = os.getenv("SHEETS_ENDPOINT")

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN topilmadi (.env faylni tekshir)")

# =====================
# IMPORTS
# =====================
import requests
import pandas as pd
from aiogram import Bot, Dispatcher, executor, types
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from io import BytesIO
from datetime import datetime
import uuid

# =====================
# CONFIG
# =====================
EMPLOYEES_URL = "https://docs.google.com/spreadsheets/d/1F5FhOECuMHfK6lulgzCt3MnGHXd1XYHjGnoADIrwpO8/export?format=xlsx"
TOKENS_URL = "https://docs.google.com/spreadsheets/d/1alWfYFDDLtNB3aVxfLjDA4Nu5t9oxac7vCfE8_9TT14/export?format=xlsx"

USE_SHEETS = True

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(bot, storage=MemoryStorage())

# =====================
# MEMORY (MVP)
# =====================
users = {}      # user_id -> {name, role, filial}
pending = []    # HR kutayotganlar
archive = []    # HR qabul qilganlar

# =====================
# FSM
# =====================
class FireFlow(StatesGroup):
    code = State()
    reason = State()
    date = State()
    letter = State()
    confirm = State()

# =====================
# HELPERS
# =====================
def load_sheet(url):
    r = requests.get(url, timeout=20)
    return pd.read_excel(BytesIO(r.content))

def get_user_by_token(token):
    df = load_sheet(TOKENS_URL)
    df["token"] = df["token"].astype(str).str.strip()
    token = str(token).strip()

    row = df[df["token"] == token]
    if row.empty:
        return None

    return {
        "name": str(row.iloc[0]["ism"]),
        "role": str(row.iloc[0]["rol"]).upper(),
        "filial": str(row.iloc[0]["filial"])
    }

def get_employee(code):
    df = load_sheet(EMPLOYEES_URL)
    df["Код источник"] = df["Код источник"].astype(str).str.strip()
    code = str(code).strip()

    row = df[df["Код источник"] == code]
    if row.empty:
        return None

    r = row.iloc[0]
    return {
        "code": code,
        "name": r["Сотрудник"],
        "position": r["Должность"],
        "filial": r["Магазин"]
    }

def post_to_sheets(payload):
    if not USE_SHEETS:
        return
    try:
        requests.post(SHEETS_ENDPOINT, json=payload, timeout=15)
    except Exception as e:
        print("Sheets xato:", e)

# =====================
# KEYBOARDS
# =====================
def manager_menu():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add("➕ Ishdan bo‘shagan xodimni yuborish")
    return kb

def hr_menu():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add("📋 Kutilmoqda", "📦 Arxiv")
    return kb

def reason_kb():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add("Oilaviy sabablar", "O‘qishi tufayli")
    return kb

def yes_no_inline():
    kb = types.InlineKeyboardMarkup()
    kb.add(
        types.InlineKeyboardButton("✅ Ha", callback_data="yes"),
        types.InlineKeyboardButton("❌ Yo‘q", callback_data="no")
    )
    return kb

def hr_inline(item_id):
    kb = types.InlineKeyboardMarkup()
    kb.add(
        types.InlineKeyboardButton("✅ Qabul qilindi", callback_data=f"accept:{item_id}")
    )
    return kb

# =====================
# START / AUTH
# =====================
@dp.message_handler(commands=["start"])
async def start(message: types.Message):
    uid = message.from_user.id
    if uid in users:
        await show_menu(message)
    else:
        await message.answer("🔐 Tokenni kiriting:")

@dp.message_handler(lambda m: m.from_user.id not in users)
async def auth(message: types.Message):
    user = get_user_by_token(message.text)
    if not user:
        await message.answer("❌ Token noto‘g‘ri.")
        return
    users[message.from_user.id] = user
    await show_menu(message)

async def show_menu(message):
    role = users[message.from_user.id]["role"]
    if role == "MANAGER":
        await message.answer("📋 Menejer menyusi:", reply_markup=manager_menu())
    else:
        await message.answer("📋 HR menyusi:", reply_markup=hr_menu())

# =====================
# MANAGER FLOW
# =====================
@dp.message_handler(text="➕ Ishdan bo‘shagan xodimni yuborish")
async def fire_start(message: types.Message):
    await FireFlow.code.set()
    await message.answer("🔎 Xodim kodini kiriting:")

@dp.message_handler(state=FireFlow.code)
async def fire_code(message: types.Message, state: FSMContext):
    emp = get_employee(message.text)
    if not emp:
        await message.answer("❌ Xodim topilmadi.")
        return
    await state.update_data(emp=emp)
    await FireFlow.reason.set()
    await message.answer(
        f"👤 {emp['name']}\n💼 {emp['position']}\n🏬 {emp['filial']}\n\nSababni tanlang:",
        reply_markup=reason_kb()
    )

@dp.message_handler(state=FireFlow.reason)
async def fire_reason(message: types.Message, state: FSMContext):
    await state.update_data(reason=message.text)
    await FireFlow.date.set()
    await message.answer("📅 Sana (DD.MM.YYYY):")

@dp.message_handler(state=FireFlow.date)
async def fire_date(message: types.Message, state: FSMContext):
    try:
        datetime.strptime(message.text, "%d.%m.%Y")
    except:
        await message.answer("❌ Sana noto‘g‘ri. Masalan: 31.12.2024")
        return
    await state.update_data(date=message.text)
    await FireFlow.letter.set()
    await message.answer("📄 Ariza bormi?", reply_markup=yes_no_inline())

@dp.callback_query_handler(lambda c: c.data in ["yes", "no"], state=FireFlow.letter)
async def fire_letter(call: types.CallbackQuery, state: FSMContext):
    await call.message.edit_reply_markup(None)
    await state.update_data(letter="Bor" if call.data == "yes" else "Yo‘q")
    await FireFlow.confirm.set()

    data = await state.get_data()
    emp = data["emp"]

    await call.message.answer(
        f"👤 {emp['name']}\n"
        f"💼 {emp['position']}\n"
        f"🏬 {emp['filial']}\n"
        f"📌 Sabab: {data['reason']}\n"
        f"📅 Sana: {data['date']}\n"
        f"📄 Ariza: {data['letter']}\n\n"
        f"Tasdiqlaysizmi?",
        reply_markup=yes_no_inline()
    )

@dp.callback_query_handler(lambda c: c.data == "yes", state=FireFlow.confirm)
async def fire_confirm(call: types.CallbackQuery, state: FSMContext):
    await call.message.edit_reply_markup(None)

    data = await state.get_data()
    emp = data["emp"]
    user = users[call.from_user.id]
    now = datetime.now().strftime("%d.%m.%Y %H:%M:%S")

    payload = {
        "action": "create",
        "kod": emp["code"],
        "fio": emp["name"],
        "filial": emp["filial"],
        "lavozim": emp["position"],
        "sabab": data["reason"],
        "ishdan_sana": data["date"],
        "menejer_sana": now,
        "status": "pending",
        "menejer": user["name"]
    }

    post_to_sheets(payload)

    await state.finish()
    await call.message.answer("✅ HR ga yuborildi.", reply_markup=manager_menu())

# =====================
# HR FLOW
# =====================
@dp.message_handler(text="📋 Kutilmoqda")
async def hr_pending(message: types.Message):
    if not pending:
        await message.answer("📭 Kutilayotganlar yo‘q.", reply_markup=hr_menu())
        return
    for p in pending:
        await message.answer(p["text"], reply_markup=hr_inline(p["id"]))

# =====================
# RUN
# =====================
if __name__ == "__main__":
    print("🤖 Sabin HR Bot ishga tushdi")
    executor.start_polling(dp, skip_updates=True)