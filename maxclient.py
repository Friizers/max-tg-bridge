"""Создание MAX-клиента с ПОСТОЯННОЙ личностью устройства.

pymax по умолчанию генерирует device_id / mt_instance_id / user-agent СЛУЧАЙНО при
каждом запуске. Из-за этого login.py и bot.py (и каждый рестарт) выглядят для MAX
как РАЗНЫЕ устройства с одним токеном → MAX срабатывает защитой и делает
FAIL_LOGOUT_ALL (сброс всех сессий).

Чтобы сессия жила, фиксируем личность устройства один раз и переиспользуем её
везде. Личность хранится рядом с сессией в <work_dir>/device.json."""
import json
import logging
import os
import uuid

from pymax import Client, ConsolePasswordProvider, ConsoleSmsCodeProvider, ExtraConfig
from pymax.api.session.payloads import MobileUserAgentPayload

import config as cfg
import maxpatch  # noqa: F401 — патчит pymax при импорте (устойчивость к кривым событиям)

log = logging.getLogger("maxclient")

IDENTITY_FILE = "device.json"


def _identity_path() -> str:
    return os.path.join(cfg.MAX_WORK_DIR, IDENTITY_FILE)


def _load_or_create_identity() -> dict:
    os.makedirs(cfg.MAX_WORK_DIR, exist_ok=True)
    path = _identity_path()
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            if data.get("device_id") and data.get("user_agent"):
                return data
        except Exception:  # noqa: BLE001 — битый файл перегенерируем
            log.warning("device.json повреждён, генерирую заново")

    # Один раз генерируем стабильную «личность» Android-устройства.
    user_agent = ExtraConfig().generate_user_agent()
    data = {
        "device_id": str(uuid.uuid4()),
        "mt_instance_id": str(uuid.uuid4()),
        "user_agent": user_agent.model_dump(),
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    log.info("Создана постоянная личность устройства: %s",
             data["user_agent"].get("device_name"))
    return data


def build_client() -> Client:
    """Строит MAX Client с зафиксированной личностью устройства."""
    ident = _load_or_create_identity()
    extra = ExtraConfig(
        device_id=ident["device_id"],
        mt_instance_id=ident["mt_instance_id"],
        user_agent=MobileUserAgentPayload(**ident["user_agent"]),
    )
    return Client(
        phone=cfg.MAX_PHONE,
        session_name=cfg.MAX_SESSION,
        work_dir=cfg.MAX_WORK_DIR,
        extra_config=extra,
        sms_code_provider=ConsoleSmsCodeProvider(),
        password_provider=ConsolePasswordProvider(),
    )
