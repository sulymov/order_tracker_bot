import asyncio
import logging
import os

from aiogram import Bot, Dispatcher, types
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart
from aiogram.client.default import DefaultBotProperties
from dotenv import load_dotenv

import database as db

from handlers import main_keyboard, router

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", 0))
logging.basicConfig(level=logging.INFO)

# Додаємо DefaultBotProperties для коректної роботи HTML/Markdown

bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN)
)

dp = Dispatcher()

# Підключаємо роутер

dp.include_router(router)
@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    user_id, role, status = await db.get_or_create_user(
        user_id=message.from_user.id,
        username=message.from_user.username or "",
        first_name=message.from_user.first_name or "",
        admin_id=ADMIN_ID,
    )

    if status == "pending":
        await message.answer(
            "⏳ Ваш запит на доступ відправлено адміністратору. Очікуйте підтвердження!"
        )

        if ADMIN_ID:
            approve_kb = types.InlineKeyboardMarkup(inline_keyboard=[
                [
                    types.InlineKeyboardButton(
                        text="✅ Схвалити",
                        callback_data=f"approve_user_{message.from_user.id}",
                    ),
                    types.InlineKeyboardButton(
                        text="❌ Відхилити",
                        callback_data=f"reject_user_{message.from_user.id}",
                    ),
                ]
            ])
            await bot.send_message(
                ADMIN_ID,
                f"🔔 Нова заявка на доступ!\n\n"
                f"Користувач: {message.from_user.full_name} (@{message.from_user.username})\n"
                f"ID: {message.from_user.id}",
                reply_markup=approve_kb,
            )
        return

    if status == "blocked":
        await message.answer("❌ Доступ до бота обмежено.")
        return

    await message.answer(
        f"Привіт, {message.from_user.first_name}! 👋\n"
        f"Панель управління замовленнями готова до роботи.",
        reply_markup=main_keyboard(),
    )

async def main():
    # Ініціалізація всіх таблиць БД
    await db.init_db()
    logging.info("✅ Базу даних ініціалізовано!")

    # Очищення старих апдейтів та запуск поллінгу
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":

    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.info("Бот зупинений.")