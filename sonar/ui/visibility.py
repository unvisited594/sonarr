"""Единый фильтр треков для всех страниц: офлайн-режим и «скрывать недоступные»."""
from ..downloads import SERVICE_ID, downloads


def is_offline(config) -> bool:
    return bool(config.data.get("offline"))


def visible(tracks: list, config) -> list:
    out = list(tracks)
    from ..library import unavailable
    log = unavailable()
    if log is not None:   # всё, что показывают недоступным, попадает в «Данные → Недоступные треки»
        for t in out:
            if not t.playable:
                log.note(t)
    if is_offline(config):  # офлайн: только скачанные треки Navidrome
        store = downloads()
        out = [t for t in out if t.service_id == SERVICE_ID and store is not None and store.has(t.id)]
    if config.data.get("hide_unavailable"):
        out = [t for t in out if t.playable]
    return out
