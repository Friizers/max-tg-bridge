"""Направление Telegram -> MAX.

Слушаем сообщения внутри веток супергруппы. Если ветка связана с MAX-чатом,
отправляем сообщение в MAX от имени личного аккаунта (userbot)."""
import asyncio
import logging
import os
import tempfile
from io import BytesIO

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message as TgMessage
from pymax import Client, File, Photo, Video

import max_to_tg
from storage import Storage

try:
    from PIL import Image
    _HAS_PIL = True
except ImportError:  # Pillow не установлен — стикеры уйдут как есть/эмодзи
    _HAS_PIL = False

log = logging.getLogger("tg2max")


def _to_cropped_png(data: bytes) -> bytes:
    """Любую картинку -> PNG (RGBA) с обрезкой прозрачных полей вплотную к рисунку.
    Прозрачность сохраняется; обрезка минимизирует белую подложку, которую MAX
    подставляет под прозрачные области."""
    img = Image.open(BytesIO(data)).convert("RGBA")
    bbox = img.getchannel("A").getbbox()  # рамка непрозрачной области
    if bbox:
        img = img.crop(bbox)
    out = BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()


async def _webm_frame_to_png(data: bytes) -> bytes:
    """Извлекает кадр из видеостикера (.webm) в PNG с прозрачностью. Нужен ffmpeg."""
    with tempfile.TemporaryDirectory() as d:
        src = os.path.join(d, "s.webm")
        dst = os.path.join(d, "s.png")
        with open(src, "wb") as f:
            f.write(data)
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-y", "-i", src, "-frames:v", "1", "-c:v", "png", dst,
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
        )
        _, err = await proc.communicate()
        if proc.returncode != 0 or not os.path.exists(dst):
            raise RuntimeError("ffmpeg: " + err.decode("utf-8", "replace")[:300])
        with open(dst, "rb") as f:
            png = f.read()
    return _to_cropped_png(png) if _HAS_PIL else png


async def _ogg_to_mp3(data: bytes) -> bytes:
    """Конвертирует голосовое (ogg/opus) в mp3 — MAX чаще распознаёт его как аудио
    и показывает встроенный плеер. Нужен ffmpeg."""
    with tempfile.TemporaryDirectory() as d:
        src = os.path.join(d, "a.ogg")
        dst = os.path.join(d, "a.mp3")
        with open(src, "wb") as f:
            f.write(data)
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-y", "-i", src, "-c:a", "libmp3lame", "-q:a", "4", dst,
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
        )
        _, err = await proc.communicate()
        if proc.returncode != 0 or not os.path.exists(dst):
            raise RuntimeError("ffmpeg: " + err.decode("utf-8", "replace")[:300])
        with open(dst, "rb") as f:
            return f.read()

router = Router()


@router.message(Command("id"))
async def cmd_id(message: TgMessage):
    """Показать chat_id группы и id текущей ветки — удобно при настройке."""
    await message.reply(
        f"chat_id: <code>{message.chat.id}</code>\n"
        f"topic (message_thread_id): <code>{message.message_thread_id}</code>"
    )


@router.message(Command("sync"))
async def cmd_sync(message: TgMessage, bot: Bot, max_client: Client, storage: Storage, cfg):
    """Создать ветки для всех чатов MAX, которых ещё нет."""
    await message.reply("Синхронизирую список чатов MAX…")
    try:
        created = await max_to_tg.sync_chats(max_client, bot, storage, cfg)
        await message.reply(f"Готово. Создано новых веток: {created}")
    except Exception as err:  # noqa: BLE001
        log.exception("Ошибка /sync")
        await message.reply(f"Ошибка синхронизации: {err}")


@router.message(Command("history"))
async def cmd_history(
    message: TgMessage, command: CommandObject, bot: Bot,
    max_client: Client, storage: Storage, cfg, http,
):
    """Подгрузить последние N сообщений MAX-чата в эту ветку: /history [N]."""
    tid = message.message_thread_id
    chat_id = storage.get_chat_by_topic(tid) if tid else None
    if not chat_id:
        await message.reply("Команду нужно отправлять внутри ветки, связанной с MAX-чатом.")
        return
    limit = getattr(cfg, "BACKFILL_LIMIT", 0) or 20
    if command.args and command.args.strip().isdigit():
        limit = int(command.args.strip())
    await message.reply(f"Подгружаю последние {limit} сообщений…")
    try:
        await max_to_tg._backfill_chat(max_client, bot, storage, cfg, http, chat_id, tid, limit)
        await message.reply("Готово.")
    except Exception as err:  # noqa: BLE001
        log.exception("Ошибка /history")
        await message.reply(f"Ошибка: {err}")


@router.message(Command("start"))
async def cmd_start(message: TgMessage):
    await message.reply(
        "Я мост MAX ⇄ Telegram. Сделайте меня администратором этой группы-форума "
        "с правом «Управление темами». Ветки будут создаваться автоматически по мере "
        "появления чатов в MAX. /id покажет идентификаторы."
    )


def _is_service_message(message: TgMessage) -> bool:
    return any(
        getattr(message, attr, None) is not None
        for attr in (
            "forum_topic_created", "forum_topic_edited", "forum_topic_closed",
            "forum_topic_reopened", "new_chat_members", "left_chat_member",
            "pinned_message", "new_chat_title", "new_chat_photo",
        )
    )


@router.message(F.message_thread_id.is_not(None))
async def on_topic_message(message: TgMessage, bot: Bot, max_client: Client, storage: Storage, cfg):
    if message.chat.id != cfg.TG_GROUP_ID:
        return
    if message.from_user and message.from_user.is_bot:
        return
    if _is_service_message(message):
        return

    chat_id = storage.get_chat_by_topic(message.message_thread_id)
    if not chat_id:
        return  # ветка не связана с MAX-чатом

    try:
        # Отправляем в MAX от своего имени — без префикса с именем отправителя,
        # чтобы собеседник видел обычное сообщение от тебя.
        await _forward_to_max(message, bot, max_client, chat_id)
    except Exception:
        log.exception("Не удалось отправить сообщение в MAX (chat_id=%s)", chat_id)


async def _download_tg(bot: Bot, file_id: str) -> bytes:
    tg_file = await bot.get_file(file_id)
    buf = await bot.download_file(tg_file.file_path)
    return buf.read()


async def _forward_to_max(message: TgMessage, bot: Bot, client: Client, chat_id: int):
    caption = (message.caption or "").strip()

    if message.text:
        await client.send_message(chat_id, message.text)

    elif message.photo:
        data = await _download_tg(bot, message.photo[-1].file_id)
        await client.send_message(chat_id, caption, attachments=[Photo(raw=data, name="photo.jpg")])

    elif message.video:
        data = await _download_tg(bot, message.video.file_id)
        name = message.video.file_name or "video.mp4"
        await client.send_message(chat_id, caption, attachments=[Video(raw=data, name=name)])

    elif message.animation:  # GIF (в Telegram это mp4 без звука)
        data = await _download_tg(bot, message.animation.file_id)
        name = message.animation.file_name or "animation.mp4"
        if not name.lower().endswith(".mp4"):
            name = "animation.mp4"
        await client.send_message(chat_id, caption, attachments=[Video(raw=data, name=name)])

    elif message.voice:
        data = await _download_tg(bot, message.voice.file_id)
        try:
            mp3 = await _ogg_to_mp3(data)
            await client.send_message(chat_id, caption, attachments=[File(raw=mp3, name="voice.mp3")])
        except Exception as err:  # noqa: BLE001 — нет ffmpeg/ошибка конвертации
            log.warning("Не удалось конвертировать голосовое в mp3 (%s) — отправляю ogg", err)
            await client.send_message(chat_id, caption, attachments=[File(raw=data, name="voice.ogg")])

    elif message.audio:
        data = await _download_tg(bot, message.audio.file_id)
        name = message.audio.file_name or "audio.mp3"
        await client.send_message(chat_id, caption, attachments=[File(raw=data, name=name)])

    elif message.document:
        data = await _download_tg(bot, message.document.file_id)
        name = message.document.file_name or "file.bin"
        await client.send_message(chat_id, caption, attachments=[File(raw=data, name=name)])

    elif message.sticker:
        await _forward_sticker(message, bot, client, chat_id, caption)

    else:
        log.debug("Тип сообщения не поддерживается для пересылки в MAX")


async def _sticker_png(message: TgMessage, bot: Bot) -> "bytes | None":
    """Готовит PNG с прозрачным фоном из любого типа стикера (статичный/видео/анимированный)."""
    st = message.sticker

    if st.is_video:
        # Видеостикер (.webm) — берём кадр через ffmpeg (с прозрачностью).
        raw = await _download_tg(bot, st.file_id)
        try:
            return await _webm_frame_to_png(raw)
        except Exception as err:  # noqa: BLE001 — нет ffmpeg или ошибка декодирования
            log.warning("Не удалось извлечь кадр видеостикера (%s), беру превью", err)
            if st.thumbnail:
                data = await _download_tg(bot, st.thumbnail.file_id)
                return _to_cropped_png(data) if _HAS_PIL else data
            return None

    if st.is_animated:
        # Анимированный (.tgs/Lottie) — статичное превью.
        if st.thumbnail:
            data = await _download_tg(bot, st.thumbnail.file_id)
            return _to_cropped_png(data) if _HAS_PIL else data
        return None

    # Статичный WebP-стикер.
    data = await _download_tg(bot, st.file_id)
    return _to_cropped_png(data) if _HAS_PIL else data


async def _forward_sticker(message: TgMessage, bot: Bot, client: Client, chat_id: int, caption: str):
    st = message.sticker
    try:
        png = await _sticker_png(message, bot)
        if png:
            await client.send_message(chat_id, caption, attachments=[Photo(raw=png, name="sticker.png")])
        else:
            await client.send_message(chat_id, st.emoji or "[стикер]")
    except Exception:
        log.exception("Не удалось отправить стикер в MAX")
        try:
            await client.send_message(chat_id, st.emoji or "[стикер]")
        except Exception:
            pass
