"""Мост MAX (userbot, личный аккаунт) <-> Telegram (бот в супергруппе-форуме).

Запускает одновременно:
  * MAX -> Telegram: userbot pymax слушает все чаты аккаунта, авто-создаёт ветки
    и пересылает сообщения с медиа.
  * Telegram -> MAX: чтение сообщений из веток и отправка их в MAX от вашего имени.
"""
import asyncio
import logging
import os

import aiohttp
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from pymax import Client, ConsolePasswordProvider, ConsoleSmsCodeProvider

import config as cfg
import max_to_tg
import tg_to_max
from storage import Storage

log = logging.getLogger("bridge")


def build_max_client() -> Client:
    os.makedirs(cfg.MAX_WORK_DIR, exist_ok=True)
    return Client(
        phone=cfg.MAX_PHONE,
        session_name=cfg.MAX_SESSION,
        work_dir=cfg.MAX_WORK_DIR,
        sms_code_provider=ConsoleSmsCodeProvider(),
        password_provider=ConsolePasswordProvider(),
    )


async def main() -> None:
    logging.basicConfig(
        level=cfg.LOG_LEVEL,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    cfg.validate()

    storage = Storage(cfg.DB_PATH)
    http = aiohttp.ClientSession()
    client = build_max_client()

    bot = Bot(cfg.TG_BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    if cfg.FORWARD_TG_TO_MAX:
        dp.include_router(tg_to_max.router)
    else:
        log.info("Пересылка Telegram -> MAX отключена (FORWARD_TG_TO_MAX=false)")

    # Регистрируем обработчики MAX -> Telegram до запуска клиента.
    max_to_tg.setup(client, bot, storage, cfg, http)

    # MAX userbot в фоне (start() блокирует — вечный цикл с авто-reconnect).
    max_task = asyncio.create_task(client.start())

    log.info("Мост запущен. Telegram-группа: %s", cfg.TG_GROUP_ID)
    try:
        await dp.start_polling(bot, max_client=client, storage=storage, cfg=cfg)
    finally:
        max_task.cancel()
        try:
            await max_task
        except BaseException:  # noqa: BLE001 — гасим всё при остановке
            pass
        await http.close()
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
