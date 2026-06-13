"""Узнать ID группы (TG_GROUP_ID). Нужен ТОЛЬКО TG_BOT_TOKEN из .env.

Запуск:
    python get_group_id.py

Затем напишите любое сообщение в группе, где уже есть ваш бот. Скрипт выведет
chat_id (и id ветки, если писали в теме). Скопируйте chat_id в .env -> TG_GROUP_ID.

ВАЖНО: чтобы бот видел сообщения в группе, он должен быть АДМИНОМ группы
(или у него отключён Privacy Mode через @BotFather -> /setprivacy -> Disable).
"""
import asyncio
import os

from aiogram import Bot, Dispatcher
from aiogram.types import Message
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.environ.get("TG_BOT_TOKEN", "").strip()


async def main() -> None:
    if not TOKEN:
        raise SystemExit("Укажите TG_BOT_TOKEN в .env")

    bot = Bot(TOKEN)
    dp = Dispatcher()

    @dp.message()
    async def any_message(message: Message):
        print("-" * 50)
        print(f"chat_id  = {message.chat.id}")
        print(f"тип      = {message.chat.type}")
        print(f"название = {message.chat.title}")
        if message.message_thread_id:
            print(f"ветка (message_thread_id) = {message.message_thread_id}")
        print("-> впишите chat_id в .env как TG_GROUP_ID")
        try:
            await message.reply(f"chat_id: <code>{message.chat.id}</code>", parse_mode="HTML")
        except Exception:
            pass

    me = await bot.get_me()
    print(f"Бот @{me.username} слушает. Напишите любое сообщение в группе.")
    print("Выход: Ctrl+C")
    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
