"""Мост MAX (userbot, личный аккаунт) <-> Telegram (бот в супергруппе-форуме).

Запускает одновременно:
  * MAX -> Telegram: userbot pymax слушает все чаты аккаунта, авто-создаёт ветки
    и пересылает сообщения с медиа.
  * Telegram -> MAX: чтение сообщений из веток и отправка их в MAX от вашего имени.

Если сессия MAX слетает (недействительна), мост шлёт уведомление в Telegram и
останавливается с кодом 69, чтобы systemd (RestartPreventExitStatus=69) не крутил
рестарт-петлю. Восстановление — команда relogin.sh на сервере.
"""
import asyncio
import html
import logging
import os

import aiohttp
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

import config as cfg
import max_to_tg
import maxclient
import tg_to_max
from storage import Storage

log = logging.getLogger("bridge")

# Спец-код выхода «сессия MAX мертва» — systemd не перезапускает (см. unit).
SESSION_DEAD_EXIT = 69


async def _notify_session_down(bot: Bot, reason) -> None:
    projdir = os.path.dirname(os.path.abspath(__file__))
    text = (
        "⚠️ <b>Сессия MAX недоступна — мост остановлен.</b>\n"
        f"Причина: <code>{html.escape(str(reason))[:300]}</code>\n\n"
        "Нужен повторный вход в MAX. Зайди на сервер и выполни:\n"
        f"<code>cd {projdir} && sudo bash relogin.sh</code>\n"
        "Введёшь код из SMS — мост поднимется автоматически."
    )
    try:
        await bot.send_message(cfg.TG_GROUP_ID, text)
    except Exception:
        log.exception("Не удалось отправить уведомление о сессии в Telegram")


async def main() -> None:
    logging.basicConfig(
        level=cfg.LOG_LEVEL,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    cfg.validate()

    storage = Storage(cfg.DB_PATH)
    http = aiohttp.ClientSession()
    client = maxclient.build_client()

    bot = Bot(cfg.TG_BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    if cfg.FORWARD_TG_TO_MAX:
        dp.include_router(tg_to_max.router)
    else:
        log.info("Пересылка Telegram -> MAX отключена (FORWARD_TG_TO_MAX=false)")

    # Регистрируем обработчики MAX -> Telegram до запуска клиента.
    max_to_tg.setup(client, bot, storage, cfg, http)

    # MAX userbot и Telegram-поллинг работают параллельно. start() сам реконнектит
    # сетевые обрывы; наружу пробрасывается только смерть сессии/авторизации.
    max_task = asyncio.create_task(client.start(), name="max-userbot")
    poll_task = asyncio.create_task(
        dp.start_polling(bot, max_client=client, storage=storage, cfg=cfg),
        name="tg-polling",
    )

    log.info("Мост запущен. Telegram-группа: %s", cfg.TG_GROUP_ID)

    session_dead = False
    try:
        done, _pending = await asyncio.wait(
            {max_task, poll_task}, return_when=asyncio.FIRST_COMPLETED
        )
        if max_task in done:
            session_dead = True
            reason = None
            if not max_task.cancelled():
                reason = max_task.exception() or "соединение с MAX закрыто"
            log.error("MAX userbot остановился: %s", reason)
            await _notify_session_down(bot, reason)
    finally:
        for task in (max_task, poll_task):
            task.cancel()
        for task in (max_task, poll_task):
            try:
                await task
            except BaseException:  # noqa: BLE001 — гасим всё при остановке
                pass
        await http.close()
        await bot.session.close()

    if session_dead:
        raise SystemExit(SESSION_DEAD_EXIT)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
