"""Первичная авторизация MAX-аккаунта.

Запустите ОДИН раз вручную (нужно ввести код из SMS):

    python login.py

После успешного входа сессия сохраняется в каталог MAX_WORK_DIR и дальше
бот работает без ввода кода. Запускайте этот скрипт в интерактивном терминале
(на сервере — внутри tmux/screen)."""
import asyncio
import logging

from pymax import Client

import config as cfg
import maxclient


async def main() -> None:
    logging.basicConfig(level="INFO", format="%(levelname)s %(name)s: %(message)s")
    if not cfg.MAX_PHONE:
        raise SystemExit("Укажите MAX_PHONE в .env")

    # Тот же клиент с фиксированной личностью устройства, что и в bot.py.
    client = maxclient.build_client()

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
    done_task = asyncio.create_task(done.wait())

    # Ждём либо успешный on_start, либо завершение клиента (= ошибка авторизации).
    finished, _ = await asyncio.wait(
        {task, done_task}, return_when=asyncio.FIRST_COMPLETED
    )

    ok = done_task in finished
    for t in (task, done_task):
        t.cancel()
    err = None
    try:
        await task
    except BaseException as e:  # noqa: BLE001
        if not isinstance(e, asyncio.CancelledError):
            err = e

    if not ok:
        raise SystemExit(
            f"❌ Авторизация не удалась: {err or 'клиент завершился'}\n"
            "Если MAX требует пароль для входа с новых устройств — установи\n"
            "облачный пароль в приложении MAX (Настройки → Конфиденциальность),\n"
            "затем запусти снова. После SMS появится запрос «Enter 2FA password»."
        )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
