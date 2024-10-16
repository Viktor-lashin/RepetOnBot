import asyncio
import random
import re
import string
from datetime import datetime, timedelta
import logging

from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import Message, InlineKeyboardButton, InlineKeyboardMarkup
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.date import DateTrigger
from babel.dates import get_month_names

API_TOKEN = "7210436078:AAG-zSOSuDLWnhNn5XQnxZj5YrPZ0FKJSGY"

bot = Bot(token=API_TOKEN)
dp = Dispatcher()

scheduler = AsyncIOScheduler()
schedule = {}

logging.basicConfig(level=logging.INFO)


class ScheduleState(StatesGroup):
    time = State()
    text = State()
    select_year = State()
    select_month = State()
    select_day = State()


@dp.message(Command('start'))
async def send_welcome(message: Message):
    await message.reply("Привет! Я бот для расписания. Используй команды /add, /view.")


def generate_year_keyboard():
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=str(datetime.now().year), callback_data=f"year_{datetime.now().year}")],
        [InlineKeyboardButton(text=str(datetime.now().year + 1), callback_data=f"year_{datetime.now().year + 1}")]
    ])
    return keyboard


def generate_month_keyboard(year, locale='en'):
    month_names = get_month_names(locale=locale, width='wide')
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=month_names[month], callback_data=f"month_{year}_{month:02d}") for month in
         range(1, 7)],
        [InlineKeyboardButton(text=month_names[month], callback_data=f"month_{year}_{month:02d}") for month in
         range(7, 13)]
    ])
    return keyboard


def generate_day_keyboard(year, month):
    last_day = (datetime(year, month % 12 + 1, 1) - timedelta(days=1)).day
    buttons = [
        InlineKeyboardButton(text=f"{day:02d}", callback_data=f"day_{year}_{month:02d}_{day:02d}")
        for day in range(1, last_day + 1)
    ]
    keyboard = InlineKeyboardMarkup(inline_keyboard=[buttons[i:i + 7] for i in range(0, len(buttons), 7)])
    return keyboard


@dp.message(Command('add'))
async def add_schedule(message: Message, state: FSMContext):
    keyboard = generate_year_keyboard()
    await message.reply("Выберите год:", reply_markup=keyboard)
    await state.set_state(ScheduleState.select_year)


@dp.callback_query(lambda c: c.data.startswith('year_'))
async def process_year_selection(callback_query: types.CallbackQuery, state: FSMContext):
    year = int(callback_query.data.split('_')[1])
    await state.update_data(selected_year=year)
    keyboard = generate_month_keyboard(year, locale='ru')
    await callback_query.message.edit_text("Выберите месяц:", reply_markup=keyboard)
    await state.set_state(ScheduleState.select_month)


@dp.callback_query(lambda c: c.data.startswith('month_'))
async def process_month_selection(callback_query: types.CallbackQuery, state: FSMContext):
    year, month = map(int, callback_query.data.split('_')[1:])
    await state.update_data(selected_month=month)
    keyboard = generate_day_keyboard(year, month)
    await callback_query.message.edit_text("Выберите день:", reply_markup=keyboard)
    await state.set_state(ScheduleState.select_day)


@dp.callback_query(lambda c: c.data.startswith('day_'))
async def process_day_selection(callback_query: types.CallbackQuery, state: FSMContext):
    year, month, day = map(int, callback_query.data.split('_')[1:])
    await state.update_data(selected_day=day)
    await callback_query.message.edit_text("Теперь введите время в формате HH:MM или HH MM:")
    await state.set_state(ScheduleState.time)


@dp.message(ScheduleState.time)
async def process_add_schedule_time(message: Message, state: FSMContext):
    time_str = message.text
    time_pattern = re.compile(r"^(0[0-9]|1[0-9]|2[0-3])[: ]([0-5][0-9])$")


    if not time_pattern.match(time_str):
        await message.reply("Неверный формат времени. Используйте формат: HH:MM или HH MM")
        return

    time_str = time_str.replace(" ", ":")

    try:
        data = await state.get_data()
        year = data['selected_year']
        month = data['selected_month']
        day = data['selected_day']
        schedule_time = datetime.strptime(f"{year}-{month:02d}-{day:02d} {time_str}", "%Y-%m-%d %H:%M")
    except ValueError:
        await message.reply("Неверный формат времени. Используйте формат: HH:MM или HH MM")
        return

    if schedule_time < datetime.now():
        await message.reply("Выбранная дата и время уже прошли. Пожалуйста, перезапустите команду и выберите будущую дату и время.")
        return

    await state.update_data(schedule_time=schedule_time)
    await message.reply("Теперь введите сообщение для расписания:")

    await state.set_state(ScheduleState.text)


def uid():
    return ''.join(random.choice(string.ascii_lowercase) for _ in range(8))


@dp.message(ScheduleState.text)
async def process_add_schedule_text(message: Message, state: FSMContext):
    schedule_text = message.text

    chat_id = message.chat.id
    data = await state.get_data()
    schedule_time = data['schedule_time']
    base_schedule_id = f"{chat_id}_{schedule_time.timestamp()}_{uid()}"

    schedule_id_30min = f"{base_schedule_id}_30min"
    schedule_id_5min = f"{base_schedule_id}_5min"
    schedule_id_exact = f"{base_schedule_id}_exact"

    schedule[schedule_id_exact] = {
        'chat_id': chat_id,
        'time': schedule_time,
        'text': schedule_text
    }

    scheduler.add_job(send_schedule, DateTrigger(schedule_time - timedelta(minutes=30)), [schedule_id_30min])
    scheduler.add_job(send_schedule, DateTrigger(schedule_time - timedelta(minutes=5)), [schedule_id_5min])
    scheduler.add_job(send_schedule, DateTrigger(schedule_time), [schedule_id_exact])

    await state.clear()
    await message.reply(f"Сообщение добавлено в расписание на {schedule_time.strftime('%d-%m-%Y %H:%M')}: {schedule_text}")


@dp.message(Command('view'))
async def view_schedule(message: Message):
    chat_id = message.chat.id
    user_schedule = [(id, item['time'], item['text']) for id, item in schedule.items() if item['chat_id'] == chat_id]

    if not user_schedule:
        await bot.send_message(chat_id, "У вас нет сообщений в расписании.")
    else:
        user_schedule.sort(key=lambda x: x[1])

        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=f"{item[1].strftime('%H:%M')} - {item[2]}",
                                  callback_data=f"view_details_{item[0]}")] for item in user_schedule
        ])

        await bot.send_message(chat_id, "Ваше расписание:", reply_markup=keyboard)


@dp.callback_query(lambda c: c.data.startswith('view_details_'))
async def view_schedule_details(callback_query: types.CallbackQuery):
    parts = callback_query.data.split('_', maxsplit=2)

    if len(parts) < 3:
        await callback_query.answer("Неверный формат данных.")
        return

    schedule_id = parts[-1]

    if schedule_id not in schedule:
        await callback_query.answer("Сообщение с таким ID не найдено.")
        return

    schedule_item = schedule[schedule_id]
    schedule_text = schedule_item['text']
    schedule_time = schedule_item['time']

    details_message = f"Детали сообщения в расписании:\n\nВремя: {schedule_time.strftime('%Y-%m-%d %H:%M')}\nТекст: {schedule_text}"

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Удалить", callback_data=f"delete_{schedule_id}")],
        [InlineKeyboardButton(text="Назад", callback_data="view_schedule")]
    ])

    await callback_query.message.edit_text(details_message, reply_markup=keyboard)


@dp.callback_query(lambda c: c.data.startswith('delete_'))
async def delete_schedule_item(callback_query: types.CallbackQuery):
    base_schedule_id = callback_query.data.split('_', maxsplit=1)[1]


    base_schedule_id, *_ = base_schedule_id.rsplit('_', maxsplit=1)

    schedule_id_30min = f"{base_schedule_id}_30min"
    schedule_id_5min = f"{base_schedule_id}_5min"
    schedule_id_exact = f"{base_schedule_id}_exact"

    for schedule_id in [schedule_id_30min, schedule_id_5min, schedule_id_exact]:
        if schedule_id in scheduler.get_jobs():
            scheduler.remove_job(schedule_id)
        if schedule_id in schedule:
            del schedule[schedule_id]

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Назад", callback_data="view_schedule")]
    ])

    await callback_query.message.edit_text("Сообщение из расписания удалено.", reply_markup=keyboard)


@dp.callback_query()
async def handle_callback(callback_query: types.CallbackQuery, state: FSMContext):
    data = callback_query.data

    if data == "cancel":
        await state.clear()
        await bot.delete_message(callback_query.message.chat.id, callback_query.message.message_id)
    elif data == "view_schedule":
        try:
            await bot.delete_message(callback_query.message.chat.id, callback_query.message.message_id)
        except Exception:
            pass
        await view_schedule(callback_query.message)


async def send_schedule(schedule_id):
    base_schedule_id = schedule_id.rsplit('_', 1)[0]
    schedule_item = schedule.get(f"{base_schedule_id}_exact")
    if not schedule_item:
        return

    chat_id = schedule_item['chat_id']
    schedule_text = schedule_item['text']
    schedule_time = schedule_item['time']

    if schedule_id.endswith("_30min"):
        message = f"❗️через 30 минут❗️\n{schedule_text}"
    elif schedule_id.endswith("_5min"):
        message = f"❗️через 5 минут❗️\n{schedule_text}"
    else:
        message = f"{schedule_text}"

    await bot.send_message(chat_id, message)

    if schedule_id in scheduler.get_jobs():
        scheduler.remove_job(schedule_id)
    if schedule_id.endswith("_exact"):
        del schedule[schedule_id]


async def main():
    scheduler.start()

    commands = [
        types.BotCommand(command="start", description="Начать работу с ботом"),
        types.BotCommand(command="add", description="Добавить расписание"),
        types.BotCommand(command="view", description="Просмотреть расписание")
    ]
    await bot.set_my_commands(commands)
    await dp.start_polling(bot)


if __name__ == '__main__':
    asyncio.run(main())
