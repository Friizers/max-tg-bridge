"""Первичная авторизация MAX-аккаунта.

Запустите ОДИН раз вручную (нужно ввести код из SMS):

    python login.py

После успешного входа сессия сохраняется в каталог MAX_WORK_DIR и дальше
бот работает без ввода кода. Запускайте этот скрипт в интерактивном терминале
(на сервере — внутри tmux/screen)."""
import asyncio
import logging
import os

from pymax import Client, ConsolePasswordProvider, ConsoleSmsCodeProvider

import config as cfg


async def main() -> None:
    logging.basicConfig(level="INFO", format="%(levelname)s %(name)s: %(message)s")
    if not cfg.MAX_PHONE:
        raise SystemExit("Укажите MAX_PHONE в .env")

    os.makedirs(cfg.MAX_WORK_DIR, exist_ok=True)
    client = Client(
        phone=cfg.MAX_PHONE,
        session_name=cfg.MAX_SESSION,
        work_dir=cfg.MAX_WORK_DIR,
        sms_code_provider=ConsoleSmsCodeProvider(),
        password_provider=ConsolePasswordProvider(),
    )

    done = asyncio.Event()

    @client.on_start()
    async def _on_start(c: Client):
        uid = c.me.contact.id if c.me else "?"
        print(
            f"\n✅ Авторизация успешна. user_id={uid}.\n"
            f"   Сессия сохранена в {cfg.MAX_WORK_DIR}/{cfg.MAX_SESSION}.\n"
            f"   Теперь можно запускать бота (bot.py / systemd)."
        )
        done.set()

    task = asyncio.create_task(client.start())
    await done.wait()
    task.cancel()
    try:
        await task
    except BaseException:  # noqa: BLE001
        pass


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
