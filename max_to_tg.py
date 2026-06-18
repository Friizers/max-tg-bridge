"""Направление MAX -> Telegram (userbot pymax -> aiogram).

Для каждого входящего сообщения MAX находим (или создаём) Telegram-ветку,
соответствующую MAX-чату, и пересылаем туда текст и вложения."""
import asyncio
import html
import logging
from typing import Optional

import aiohttp
from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter
from aiogram.types import BufferedInputFile
from pymax import Client, Message
from pymax.types.domain.attachments.audio import AudioAttachment
from pymax.types.domain.attachments.call import CallAttachment
from pymax.types.domain.attachments.file import FileAttachment
from pymax.types.domain.attachments.photo import PhotoAttachment
from pymax.types.domain.attachments.sticker import StickerAttachment
from pymax.types.domain.attachments.video import VideoAttachment

from storage import Storage

log = logging.getLogger("max2tg")

TG_CAPTION_LIMIT = 1024


def _is_topic_gone(err: TelegramBadRequest) -> bool:
    """Ошибка Telegram, означающая, что тема/ветка больше не существует
    (её удалили) — повод пересоздать ветку."""
    msg = str(err).lower()
    return (
        "thread not found" in msg
        or "message thread" in msg
        or "chat not found" in msg
        or "topic_deleted" in msg
        or "topic deleted" in msg
    )


def setup(client: Client, bot: Bot, storage: Storage, cfg, http: aiohttp.ClientSession):
    """Регистрирует обработчики pymax. Вызывается до client.start()."""

    @client.on_start()
    async def _on_start(c: Client):  # noqa: D401
        me = c.me.contact if c.me else None
        log.info("MAX userbot подключён (user_id=%s)", getattr(me, "id", "?"))
        if getattr(cfg, "SYNC_CHATS_ON_START", True):
            await sync_chats(c, bot, storage, cfg)

    @client.on_message()
    async def _on_message(message: Message, _client: Client):
        # pymax вызывает обработчик как handler(message, client).
        try:
            await _handle(message, client, bot, storage, cfg, http)
        except Exception:
            log.exception("Ошибка обработки сообщения MAX")


MEDIA_TYPES = (PhotoAttachment, VideoAttachment, FileAttachment,
               AudioAttachment, StickerAttachment)


def _safe_dump(message) -> str:
    try:
        return str(message.model_dump(mode="python"))[:1800]
    except Exception:  # noqa: BLE001
        return "<dump failed>"


def _extract_forward(message):
    """Достаёт пересланное сообщение из непрослойки link (type=FORWARD).
    MAX заворачивает форвард в поле link с оригиналом внутри. Возвращает
    (Message, orig_chat_id) или None."""
    link = getattr(message, "link", None)
    if not isinstance(link, dict):
        extra = getattr(message, "__pydantic_extra__", None) or {}
        link = extra.get("link")
    if not isinstance(link, dict):
        return None
    if "FORWARD" not in str(link.get("type", "")).upper():
        return None
    inner = link.get("message") or link.get("attachMessage")
    if not isinstance(inner, dict):
        return None
    try:
        fwd = Message.model_validate(inner)
    except Exception:  # noqa: BLE001
        log.debug("Не удалось разобрать пересланное сообщение")
        return None
    orig_chat = link.get("chatId") or fwd.chat_id or message.chat_id
    return fwd, orig_chat


async def _handle(message, client, bot, storage, cfg, http):
    me_id = client.me.contact.id if client.me else None
    # Игнорируем собственные сообщения (в т.ч. отправленные мостом из Telegram),
    # иначе получится эхо-петля.
    if me_id is not None and message.sender == me_id:
        return

    chat_id = message.chat_id
    if chat_id is None:
        return

    attaches = message.attaches or []
    text = message.text or ""
    media = [a for a in attaches if isinstance(a, MEDIA_TYPES)]
    calls = [a for a in attaches if isinstance(a, CallAttachment)]

    media_chat_id, media_msg_id = chat_id, message.id
    forwarded_from = None

    # Пересланное сообщение: свой текст/медиа сверху пустые, контент внутри link.
    if not text and not media and not calls:
        fwd = _extract_forward(message)
        if fwd is not None:
            fwd_msg, orig_chat = fwd
            text = fwd_msg.text or ""
            fa = fwd_msg.attaches or []
            media = [a for a in fa if isinstance(a, MEDIA_TYPES)]
            calls = [a for a in fa if isinstance(a, CallAttachment)]
            media_chat_id = orig_chat or chat_id
            media_msg_id = fwd_msg.id or message.id
            forwarded_from = await _display_name(client, fwd_msg.sender)

    if not text and not media and not calls:
        if attaches:
            log.debug("Пропуск нераспознанного сообщения: %s", _safe_dump(message))
        return

    sender_name = await _display_name(client, message.sender)
    topic_id = await _get_or_create_topic(chat_id, client, storage, bot, cfg, sender_name)

    display_name = sender_name
    if forwarded_from:
        display_name = f"{sender_name} ↪️ переслано от {forwarded_from}"

    async def _deliver(tid: int) -> None:
        if calls and getattr(cfg, "NOTIFY_CALLS", True):
            for call in calls:
                note = f"<b>{html.escape(display_name)}</b>: {_format_call(call)}"
                await bot.send_message(cfg.TG_GROUP_ID, note, message_thread_id=tid)
        if text or media:
            await _forward(bot, cfg.TG_GROUP_ID, tid, display_name, text, media,
                           client, http, media_chat_id, media_msg_id)

    try:
        await _deliver(topic_id)
    except TelegramBadRequest as err:
        if not _is_topic_gone(err):
            raise
        # Ветку удалили в Telegram — выбрасываем мёртвую связь и пересоздаём.
        log.info("Ветка чата %s недоступна (удалена?) — пересоздаю", chat_id)
        storage.delete_topic(chat_id)
        topic_id = await _get_or_create_topic(chat_id, client, storage, bot, cfg, sender_name)
        await _deliver(topic_id)


async def _display_name(client: Client, user_id: Optional[int]) -> str:
    if user_id is None:
        return "MAX"
    user = client.get_cached_user(user_id)
    if user is None:
        try:
            user = await client.get_user(user_id)
        except Exception:
            user = None
    if user and user.names:
        n = user.names[0]
        return n.name or (f"{n.first_name or ''} {n.last_name or ''}").strip() or f"id{user_id}"
    return f"id{user_id}"


def _format_call(call: CallAttachment) -> str:
    dur = int(call.duration or 0)
    if dur > 0:
        m, s = divmod(dur, 60)
        if m >= 60:
            h, m = divmod(m, 60)
            return f"📞 Звонок завершён, длительность {h}:{m:02d}:{s:02d}"
        return f"📞 Звонок завершён, длительность {m:02d}:{s:02d}"
    return "📞 Пропущенный звонок"


async def _chat_title(client: Client, chat, me_id: Optional[int]) -> Optional[str]:
    """Заголовок для ветки: название группы, а для диалога — имя собеседника."""
    if getattr(chat, "title", None):
        return chat.title
    others = [uid for uid in (getattr(chat, "participants", None) or {}) if uid != me_id]
    if others:
        return await _display_name(client, others[0])
    return None


async def _create_topic(chat_id, title, storage, bot, cfg) -> int:
    title = (title or f"MAX {chat_id}").strip()[:120] or f"MAX {chat_id}"
    topic = None
    for _ in range(2):
        try:
            topic = await bot.create_forum_topic(chat_id=cfg.TG_GROUP_ID, name=title)
            break
        except TelegramRetryAfter as err:
            log.warning("Flood wait %s сек при создании ветки", err.retry_after)
            await asyncio.sleep(err.retry_after + 1)
    if topic is None:
        raise RuntimeError("create_forum_topic: превышены лимиты Telegram")
    storage.set_topic(chat_id, topic.message_thread_id, title)
    log.info("Создана ветка '%s' (thread_id=%s) для MAX-чата %s",
             title, topic.message_thread_id, chat_id)
    return topic.message_thread_id


async def _get_or_create_topic(chat_id, client, storage, bot, cfg, fallback_title):
    topic_id = storage.get_topic(chat_id)
    if topic_id:
        return topic_id

    title = None
    try:
        chat = await client.get_chat(chat_id)
        me_id = client.me.contact.id if client.me else None
        title = await _chat_title(client, chat, me_id)
    except Exception as err:  # noqa: BLE001
        log.debug("Не удалось получить чат %s: %s", chat_id, err)
    return await _create_topic(chat_id, title or fallback_title, storage, bot, cfg)


async def sync_chats(client: Client, bot: Bot, storage: Storage, cfg) -> int:
    """Создаёт ветки для всех чатов аккаунта, для которых их ещё нет.
    Идемпотентно: уже связанные чаты пропускаются. Возвращает число созданных."""
    try:
        chats = await client.fetch_chats()
    except Exception:
        log.exception("Не удалось получить список чатов MAX")
        return 0

    me_id = client.me.contact.id if client.me else None
    created = 0
    for chat in chats:
        if storage.get_topic(chat.id):
            continue
        try:
            title = await _chat_title(client, chat, me_id)
            await _create_topic(chat.id, title, storage, bot, cfg)
            created += 1
            await asyncio.sleep(1.0)  # бережём лимиты Telegram на создание тем
        except Exception:
            log.exception("Не удалось создать ветку для чата %s", chat.id)
    log.info("Синхронизация чатов: создано веток %s (всего чатов %s)", created, len(chats))
    return created


async def _download(http: aiohttp.ClientSession, url: str) -> bytes:
    async with http.get(url) as resp:
        resp.raise_for_status()
        return await resp.read()


async def _forward(bot, group_id, topic_id, sender_name, text, media,
                   client, http, chat_id, message_id):
    prefix = f"<b>{html.escape(sender_name)}</b>"

    if not media:
        out = prefix + (": " + html.escape(text) if text else "")
        await bot.send_message(group_id, out, message_thread_id=topic_id)
        return

    caption = prefix + (": " + html.escape(text) if text else "")
    if len(caption) > TG_CAPTION_LIMIT:
        await bot.send_message(group_id, caption, message_thread_id=topic_id)
        caption = ""

    for att in media:
        try:
            if isinstance(att, PhotoAttachment):
                data = await _download(http, att.base_url)
                await bot.send_photo(
                    group_id, BufferedInputFile(data, "photo.jpg"),
                    caption=caption or None, message_thread_id=topic_id)

            elif isinstance(att, VideoAttachment):
                req = await client.get_video_by_id(chat_id, message_id, att.video_id)
                data = await _download(http, req.url)
                await bot.send_video(
                    group_id, BufferedInputFile(data, "video.mp4"),
                    caption=caption or None, message_thread_id=topic_id)

            elif isinstance(att, FileAttachment):
                req = await client.get_file_by_id(chat_id, message_id, att.file_id)
                data = await _download(http, req.url)
                await bot.send_document(
                    group_id, BufferedInputFile(data, att.name or "file.bin"),
                    caption=caption or None, message_thread_id=topic_id)

            elif isinstance(att, AudioAttachment):
                if not att.url:
                    continue
                data = await _download(http, att.url)
                await bot.send_audio(
                    group_id, BufferedInputFile(data, "audio.mp3"),
                    caption=caption or None, message_thread_id=topic_id)

            elif isinstance(att, StickerAttachment):
                if not att.url:
                    continue
                data = await _download(http, att.url)
                await bot.send_photo(
                    group_id, BufferedInputFile(data, "sticker.png"),
                    caption=caption or None, message_thread_id=topic_id)

            caption = ""  # подпись прикрепляем только к первому вложению
        except TelegramBadRequest as err:
            if _is_topic_gone(err):
                raise  # пусть _handle пересоздаст ветку и повторит
            log.exception("Не удалось переслать вложение %s", type(att).__name__)
        except Exception:
            log.exception("Не удалось переслать вложение %s", type(att).__name__)
