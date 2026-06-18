"""Конфигурация моста MAX (userbot) <-> Telegram. Значения берутся из переменных
окружения или из файла .env рядом с проектом."""
import os

from dotenv import load_dotenv

load_dotenv()


def _bool(name: str, default: bool) -> bool:
    val = os.environ.get(name)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on", "да")


# --- Telegram (обычный бот в супергруппе-форуме) ---
TG_BOT_TOKEN = os.environ.get("TG_BOT_TOKEN", "").strip()
# ID супергруппы-форума (отрицательное число вида -100xxxxxxxxxx).
TG_GROUP_ID = int(os.environ.get("TG_GROUP_ID", "0") or "0")

# --- MAX (личный аккаунт = userbot) ---
# Телефон аккаунта MAX в международном формате, напр. +79991234567
MAX_PHONE = os.environ.get("MAX_PHONE", "").strip()
# Где хранить файл сессии MAX (создаётся при первой авторизации).
MAX_WORK_DIR = os.environ.get("MAX_WORK_DIR", "max_session")
MAX_SESSION = os.environ.get("MAX_SESSION", "session.db")

# --- Поведение моста ---
# Пересылать ли сообщения из Telegram-веток обратно в MAX.
FORWARD_TG_TO_MAX = _bool("FORWARD_TG_TO_MAX", True)
# Добавлять имя отправителя префиксом к сообщению.
SHOW_SENDER_NAME = _bool("SHOW_SENDER_NAME", True)
# При старте создавать ветки для всех уже существующих чатов MAX.
SYNC_CHATS_ON_START = _bool("SYNC_CHATS_ON_START", True)
# Присылать в Telegram уведомления о звонках MAX.
NOTIFY_CALLS = _bool("NOTIFY_CALLS", True)
# Сколько последних сообщений подгрузить в ветку при первом её появлении
# (0 = выключено). Делается один раз на чат.
BACKFILL_LIMIT = int(os.environ.get("BACKFILL_LIMIT", "0") or "0")

# --- Прочее ---
DB_PATH = os.environ.get("DB_PATH", "bridge.db")
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()


def validate() -> None:
    missing = []
    if not TG_BOT_TOKEN:
        missing.append("TG_BOT_TOKEN")
    if not TG_GROUP_ID:
        missing.append("TG_GROUP_ID")
    if not MAX_PHONE:
        missing.append("MAX_PHONE")
    if missing:
        raise SystemExit(
            "Не заданы обязательные переменные окружения: "
            + ", ".join(missing)
            + ".\nЗаполните их в файле .env (см. .env.example)."
        )
