"""Обходы багов парсинга входящих событий в pymax.

pymax (2.1–2.2) строго типизирует часть полей, а MAX иногда присылает другой тип
(например, messageId в событии реакции приходит числом, а модель ждёт строку).
При маппинге такого события парсинг фрейма падает. Сама по себе ошибка не фатальна
(pymax её ловит в _dispatch_event), но засоряет лог ERROR-трейсбеками.

Здесь мы оборачиваем EventMapper.map: некорректное событие просто пропускается —
возвращаем raw-фрейм (как делает map в штатном fallthrough), без шума и без риска
уронить обработку. Импортировать ДО создания клиента."""
import logging

from pymax.dispatch import mapping

log = logging.getLogger("maxpatch")

_orig_map = mapping.EventMapper.map


def _safe_map(self, event_type, frame):
    try:
        return _orig_map(self, event_type, frame)
    except Exception as err:  # noqa: BLE001 — кривое событие не должно ломать приём
        log.debug("пропущено некорректное событие %s: %s", event_type, err)
        return frame


if getattr(mapping.EventMapper.map, "__name__", "") != "_safe_map":
    mapping.EventMapper.map = _safe_map
    log.debug("EventMapper.map обёрнут для устойчивости к кривым событиям")
