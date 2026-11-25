"""Запасной сервис: трек не играет — ищем его же в других подключённых сервисах.

Совпадение проверяется так же строго, как при поиске на YouTube: название, исполнитель
(устойчиво к транслитерации) и длительность ±10 с — ремикс или кавер вместо оригинала не включится.
"""
import logging

from .base import AuthError, ServiceError

log = logging.getLogger("sonar.fallback")
# сначала сервисы со своим звуком, затем те, что сами играют через YouTube
ORDER = ["yandex", "navidrome", "ytmusic", "soundcloud", "deezer", "spotify"]


def _first_artist(track) -> str:
    return (track.artist or "").split(",")[0].strip()


def _as_item(cand) -> dict:
    return {"title": cand.title, "duration_seconds": cand.duration_ms // 1000,
            "artists": [{"name": a.strip()} for a in (cand.artist or "").split(",") if a.strip()]}


def best_match(track, candidates):
    from .youtube_match import _score
    artist, seconds = _first_artist(track), track.duration_ms // 1000
    best, best_score = None, 0.0
    for cand in candidates[:20]:
        if not cand.playable or (cand.service_id, cand.id) == (track.service_id, track.id):
            continue
        score = _score(_as_item(cand), track.title, artist, seconds)
        if score is not None and score > best_score:
            best, best_score = cand, score
    return best


def find_alternative(manager, track):
    """В фоне. (сервис, трек) или None."""
    others = [s for s in manager.connected() if s.id != track.service_id]
    others.sort(key=lambda s: ORDER.index(s.id) if s.id in ORDER else len(ORDER))
    query = f"{_first_artist(track)} {track.title}".strip()
    for svc in others:
        try:
            candidates = svc.search(query)
        except (AuthError, ServiceError) as exc:
            log.info("запасной поиск в %s не удался: %s", svc.name, exc)
            continue
        alt = best_match(track, candidates)
        if alt is not None:
            log.info("запасной вариант для %s/%s: %s/%s", track.service_id, track.id, svc.id, alt.id)
            return svc, alt
    log.info("запасного варианта нет: %s", query)
    return None
