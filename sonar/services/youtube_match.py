"""Поиск того же трека на YouTube Music: для сервисов, чей звук сторонним
приложениям недоступен (Spotify отдаёт аудио только под DRM), и для видео на фоне.

Работает без аккаунта YouTube: поиск ytmusicapi доступен анонимно.

Сравнение названий устойчиво к языку: YouTube Music в английском интерфейсе показывает
русских исполнителей латиницей («Кино» → «KINO», «Группа крови» → «Gruppa krovi»), а разные
системы транслитерации пишут «Цой» как Tsoy, Tsoi или Coi. Поэтому обе стороны приводятся
к единому латинскому написанию, слова сравниваются с небольшим допуском, а поиск идёт
и на русском, и на английском.
"""
import logging
import re
import threading
import time
from difflib import SequenceMatcher

from .base import ServiceError, TemporaryError, UnavailableError

log = logging.getLogger("sonar.ytmatch")
_lock = threading.Lock()
_clients: dict = {}
_cache: dict[str, tuple[str | None, float]] = {}
MAX_DURATION_DIFF = 10        # секунд: другая длительность — другая версия (ремикс, live)
CLIP_DURATION_DIFF = 90       # у клипов бывают интро и концовки
NEGATIVE_TTL = 600            # «не нашли» помним 10 минут, а не до перезапуска
WORD_SIMILARITY = 0.8

_CYR = {"а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e", "ж": "zh", "з": "z", "и": "i",
        "й": "i", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t",
        "у": "u", "ф": "f", "х": "h", "ц": "c", "ч": "ch", "ш": "sh", "щ": "sch", "ъ": "", "ы": "i", "ь": "",
        "э": "e", "ю": "yu", "я": "ya", "і": "i", "ї": "i", "є": "e", "ґ": "g"}
# разные системы транслитерации → одно написание (порядок важен: сначала длинные сочетания)
_FOLD = (("shch", "sch"), ("tsch", "ch"), ("ts", "c"), ("tz", "c"), ("kh", "h"), ("zh", "j"), ("iy", "i"),
         ("yi", "i"), ("ye", "e"), ("yo", "e"), ("yu", "u"), ("ju", "u"), ("ya", "a"), ("ja", "a"),
         ("w", "v"), ("y", "i"), ("x", "ks"))


def _client(language: str):
    with _lock:
        if language not in _clients:
            from ytmusicapi import YTMusic
            try:
                _clients[language] = YTMusic(language=language)
            except Exception as exc:
                raise TemporaryError("Нет связи с YouTube Music для поиска трека.") from exc
        return _clients[language]


def _yt():   # совместимость: прежний единственный клиент
    return _client("en")


def _norm_word(word: str) -> str:
    word = "".join(_CYR.get(ch, ch) for ch in word)
    for a, b in _FOLD:
        word = word.replace(a, b)
    return re.sub(r"(.)\1+", r"\1", word)   # «Kinno» и «Kino», «Alla» и «Ala» — одно и то же


def _words(text: str) -> set[str]:
    text = re.sub(r"\((feat|ft|with|при уч)[^)]*\)|\[[^\]]*\]", " ", (text or "").lower())
    return {_norm_word(w) for w in re.findall(r"\w+", text) if len(w) > 1}


def _match(want: set[str], got: set[str]) -> float:
    """Доля нужных слов, нашедших пару (точную или почти точную)."""
    if not want:
        return 0.0
    hit = 0
    for w in want:
        if w in got or any(SequenceMatcher(None, w, g).ratio() >= WORD_SIMILARITY for g in got):
            hit += 1
    return hit / len(want)


def _score(item: dict, title: str, artist: str, seconds: int, max_diff: int = MAX_DURATION_DIFF) -> float | None:
    found = item.get("duration_seconds") or 0
    if seconds and found and abs(found - seconds) > max_diff:
        return None
    want_title, got_title = _words(title), _words(item.get("title") or "")
    if not want_title or not got_title:
        return None
    got_artist = _words(" ".join(a.get("name", "") for a in item.get("artists") or []))
    want_artist = _words(artist)
    title_match = _match(want_title, got_title | got_artist)   # бывает «Исполнитель — Название» в названии
    artist_match = _match(want_artist, got_artist | got_title) if want_artist else 0.5
    close_duration = bool(seconds and found and abs(found - seconds) <= 3)
    if title_match < 0.5:
        return None
    if artist_match == 0 and not (title_match >= 0.99 and close_duration):
        return None   # исполнитель не совпал — берём только полное название с той же длительностью
    closeness = 1 - (abs(found - seconds) / max_diff if seconds and found else 0.5)
    return title_match * 2 + artist_match * 2 + closeness


def _cached(key: str):
    hit = _cache.get(key)
    if hit is None:
        return False, None
    value, ts = hit
    if value is None and time.time() - ts > NEGATIVE_TTL:
        _cache.pop(key, None)
        return False, None
    return True, value


def _search(query: str, kind: str, language: str) -> list[dict]:
    try:
        return _client(language).search(query, filter=kind, limit=10) or []
    except ServiceError:
        raise
    except Exception as exc:
        raise TemporaryError(f"Поиск на YouTube не удался: {exc}") from exc


def _find(query: str, kind: str, title, artist, seconds, max_diff=MAX_DURATION_DIFF):
    """Сначала на русском (кириллица как есть), английский — только если русский ничего не дал:
    иначе каждый запуск трека Spotify/Deezer ждал бы два поиска вместо одного."""
    seen = []
    for language in ("ru", "en"):
        results = _search(query, kind, language)
        best = _best(results, title, artist, seconds, max_diff)
        if best:
            return best
        seen += results
    # для журнала: что предлагал YouTube — по нему видно, почему не подошло (другая длина, исполнитель)
    for item in seen[:4]:
        log.info("  кандидат: %s — %s (%s с, искали %s с)",
                 ", ".join(a.get("name", "") for a in item.get("artists") or []), item.get("title"),
                 item.get("duration_seconds"), seconds)
    return None


def _best(results, title, artist, seconds, max_diff=MAX_DURATION_DIFF):
    best, best_score = None, 0.0
    for item in results:
        if not item.get("videoId"):
            continue
        score = _score(item, title, artist, seconds, max_diff)
        if score is not None and score > best_score:
            best, best_score = item, score
    return best


def find_video_id(title: str, artist: str, duration_ms: int, isrc: str | None = None) -> str:
    """Песня (аудио) на YouTube Music."""
    key = "song|" + (isrc or f"{artist}|{title}|{duration_ms // 1000}")
    known, value = _cached(key)
    if known:
        if value is None:
            raise UnavailableError("Не нашли этот трек на YouTube.")
        return value
    seconds = duration_ms // 1000
    queries = ([isrc] if isrc else []) + [f"{artist} {title}".strip()]
    best = None
    for query in queries:
        best = _find(query, "songs", title, artist, seconds)
        if best:  # по ISRC нашлось и проверка прошла: второй запрос не нужен
            break
    _cache[key] = (best["videoId"] if best else None, time.time())
    if not best:
        log.info("не нашли песню: %s — %s (%s с)", artist, title, seconds)
        raise UnavailableError("Не нашли этот трек на YouTube.")
    return best["videoId"]


def find_music_video(title: str, artist: str, duration_ms: int, isrc: str | None = None) -> str:
    """Видео к треку (для фона): официальный клип, если есть; иначе — сама песня."""
    key = "clip|" + (isrc or f"{artist}|{title}|{duration_ms // 1000}")
    known, value = _cached(key)
    if known:
        if value is None:
            raise UnavailableError("Не нашли видео к этому треку на YouTube.")
        return value
    seconds = duration_ms // 1000
    clip = _find(f"{artist} {title}".strip(), "videos", title, artist, seconds, CLIP_DURATION_DIFF)
    vid = clip["videoId"] if clip else None
    if vid is None:
        try:   # клипа в поиске нет — песня и её видео-пара
            song = find_video_id(title, artist, duration_ms, isrc)
            try:
                vid = find_clip_id(song)
            except ServiceError:
                vid = song
        except UnavailableError:
            vid = None
    _cache[key] = (vid, time.time())
    if vid is None:
        log.info("не нашли видео: %s — %s", artist, title)
        raise UnavailableError("Не нашли видео к этому треку на YouTube.")
    return vid


def find_clip_id(video_id: str) -> str:
    """Клип к песне: видео-пара из «радио» YouTube Music."""
    try:
        data = _client("en").get_watch_playlist(videoId=video_id, limit=1)
    except Exception as exc:
        raise ServiceError(f"Не удалось найти клип: {exc}") from exc
    first = (data.get("tracks") or [{}])[0]
    if first.get("videoType") in ("MUSIC_VIDEO_TYPE_OMV", "MUSIC_VIDEO_TYPE_UGC"):
        return first["videoId"]
    counterpart = first.get("counterpart") or {}
    if counterpart.get("videoId"):
        return counterpart["videoId"]
    raise UnavailableError("У этого трека нет клипа на YouTube.")
