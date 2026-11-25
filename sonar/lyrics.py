"""Тексты песен с разметкой по времени (LRC) для караоке в большом плеере.

Источник — LRCLIB (lrclib.net): открытая база текстов, без ключей и входа. Ответы кешируются в
папке данных (lyrics/), так что повторное открытие трека не ходит в сеть, а «не найдено» тоже
запоминается на сутки, чтобы не дёргать сервер на каждом переключении.
"""
import hashlib
import json
import logging
import re
import time
from dataclasses import dataclass, field

import requests

from . import paths

log = logging.getLogger("sonar.lyrics")

API = "https://lrclib.net/api"
HEADERS = {"User-Agent": "Sonar desktop player (https://github.com/)"}
MISS_TTL = 24 * 3600

_TIME = re.compile(r"\[(\d{1,3}):(\d{1,2})(?:[.:](\d{1,3}))?\]")
_WORD = re.compile(r"<(\d{1,3}):(\d{1,2})(?:[.:](\d{1,3}))?>")
_JUNK = re.compile(r"\s*[\(\[](?:[^)\]]*?(?:official|video|audio|lyric|clip|клип|visuali[sz]er|remaster|hd|hq|"
                   r"mv|m/v|live|explicit)[^)\]]*)[\)\]]", re.I)
_FEAT = re.compile(r"\s*[\(\[]?\s*(?:feat\.?|ft\.?|featuring|при уч\.)\s.*$", re.I)


@dataclass
class Line:
    start: int                 # мс
    text: str
    end: int = 0               # когда строка допета (мс); считается в Lyrics.finish()
    words: list = field(default_factory=list)   # [(мс, индекс символа)] из расширенного LRC


@dataclass
class Lyrics:
    lines: list[Line]
    synced: bool

    duration: int = 0

    def finish(self, duration_ms: int | None = None, char_ms: float = 110) -> "Lyrics":
        """Когда строка допета: до начала следующей, но не дольше, чем её реально поют —
        иначе на длинном проигрыше последние буквы ползли бы полминуты. char_ms — темп пения
        (мс на символ): его меняет ползунок «Скорость заливки»."""
        if duration_ms is not None:
            self.duration = duration_ms or 0
        for i, line in enumerate(self.lines):
            nxt = self.lines[i + 1].start if i + 1 < len(self.lines) else (self.duration or line.start + 6000)
            gap = max(nxt - line.start, 300)
            sing = int(len(line.text) * char_ms + 900)
            line.end = line.start + max(300, min(int(gap * 0.95), sing))
        return self

    def index_at(self, ms: int) -> int:
        """Номер текущей строки (−1 — ещё до первой)."""
        lo, hi, ans = 0, len(self.lines) - 1, -1
        while lo <= hi:
            mid = (lo + hi) // 2
            if self.lines[mid].start <= ms:
                ans, lo = mid, mid + 1
            else:
                hi = mid - 1
        return ans


def _ms(m, s, frac) -> int:
    frac = frac or "0"
    return (int(m) * 60 + int(s)) * 1000 + int(frac.ljust(3, "0")[:3])


def parse_lrc(text: str) -> Lyrics:
    """LRC → строки. Понимает несколько меток на строке и пословные метки <мм:сс.xx>."""
    lines: list[Line] = []
    offset = 0
    for raw in text.splitlines():
        m = re.match(r"\[offset:\s*([+-]?\d+)\]", raw.strip(), re.I)
        if m:
            offset = int(m.group(1))
            continue
        stamps = list(_TIME.finditer(raw))
        if not stamps:
            continue
        body = raw[stamps[-1].end():]
        words, plain, pos = [], [], 0
        for wm in _WORD.finditer(body):   # разбираем пословные метки
            plain.append(body[pos:wm.start()])
            words.append((_ms(*wm.groups()), len("".join(plain))))
            pos = wm.end()
        plain.append(body[pos:])
        clean = re.sub(r"\s+", " ", "".join(plain)).strip()
        if words:   # индексы считались до strip — поправляем на ведущие пробелы
            lead = len("".join(plain)) - len("".join(plain).lstrip())
            words = [(t - offset, max(0, i - lead)) for t, i in words]
        for st in stamps:
            lines.append(Line(_ms(*st.groups()) - offset, clean, words=list(words)))
    lines.sort(key=lambda ln: ln.start)
    lines = [ln for ln in lines if ln.text]   # пустые строки — паузы, их время уже учтено
    return Lyrics(lines, True)


def parse_plain(text: str) -> Lyrics:
    return Lyrics([Line(0, ln.strip()) for ln in text.splitlines() if ln.strip()], False)


def clean_title(title: str) -> str:
    t = _JUNK.sub("", title)
    t = _FEAT.sub("", t)
    return re.sub(r"\s+", " ", t).strip(" -–—") or title


def clean_artist(artist: str) -> str:
    a = re.split(r"\s*(?:,|&| x | и |feat\.?|ft\.?)\s*", artist, maxsplit=1, flags=re.I)[0]
    return a.strip() or artist


def _cache_path(track):
    key = hashlib.sha1(f"{track.artist}\n{track.title}".lower().encode()).hexdigest()[:20]
    folder = paths.data_dir() / "lyrics"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / f"{key}.json"


def _pick(items: list, duration_s: float) -> dict | None:
    """Из результатов поиска — с синхронизацией и подходящей длиной."""
    def score(it):
        d = abs((it.get("duration") or 0) - duration_s) if duration_s else 0
        return (0 if it.get("syncedLyrics") else 1, d if d <= 8 else 100 + d)
    good = [it for it in items if (it.get("syncedLyrics") or it.get("plainLyrics")) and not it.get("instrumental")]
    if not good:
        return None
    best = min(good, key=score)
    if duration_s and best.get("duration") and abs(best["duration"] - duration_s) > 15:
        return None   # совсем другая длина — скорее всего, другая песня или версия
    return best


def _fetch(track) -> dict | None:
    title, artist = clean_title(track.title), clean_artist(track.artist)
    dur = (track.duration_ms or 0) / 1000
    session = requests.Session()
    session.headers.update(HEADERS)
    if dur:
        r = session.get(f"{API}/get", params={"track_name": title, "artist_name": artist,
                                              "duration": int(round(dur))}, timeout=10)
        if r.ok:
            data = r.json()
            if data.get("syncedLyrics") or data.get("plainLyrics"):
                return data
    for params in ({"track_name": title, "artist_name": artist}, {"q": f"{artist} {title}"}):
        r = session.get(f"{API}/search", params=params, timeout=10)
        if r.ok:
            best = _pick(r.json() or [], dur)
            if best:
                return best
    return None


def load(track) -> Lyrics | None:
    """Найти текст трека (блокирующий вызов — запускать через run_async)."""
    cache = _cache_path(track)
    data = None
    if cache.exists():
        try:
            stored = json.loads(cache.read_text("utf-8"))
            if stored.get("miss"):
                if time.time() - stored.get("at", 0) < MISS_TTL:
                    return None
            else:
                data = stored
        except (OSError, ValueError):
            data = None
    if data is None:
        data = _fetch(track)
        try:
            cache.write_text(json.dumps(data or {"miss": True, "at": time.time()}, ensure_ascii=False), "utf-8")
        except OSError:
            pass
        log.info("текст «%s — %s»: %s", track.artist, track.title,
                 "с синхронизацией" if data and data.get("syncedLyrics") else ("без времени" if data else "не найден"))
    if not data:
        return None
    if data.get("syncedLyrics"):
        lyr = parse_lrc(data["syncedLyrics"])
        if lyr.lines:
            return lyr.finish(track.duration_ms)
    if data.get("plainLyrics"):
        return parse_plain(data["plainLyrics"])
    return None


# ---------- перевод ----------

TRANSLATE = "https://translate.googleapis.com/translate_a/single"


def _translate_chunk(text: str, target: str) -> tuple[str, str]:
    r = requests.get(TRANSLATE, params={"client": "gtx", "sl": "auto", "tl": target, "dt": "t", "q": text},
                     headers=HEADERS, timeout=12)
    r.raise_for_status()
    data = r.json()
    out = "".join(seg[0] or "" for seg in (data[0] or []) if seg)
    return out, (data[2] if len(data) > 2 and isinstance(data[2], str) else "")


def translate(track, lyrics: "Lyrics", target: str = "ru") -> list[str] | None:
    """Перевод строк (блокирующий вызов). None — песня уже на нужном языке или перевода нет."""
    cache = _cache_path(track).with_suffix(f".{target}.json")
    try:
        stored = json.loads(cache.read_text("utf-8"))
        if stored.get("n") == len(lyrics.lines):
            return stored.get("lines")
    except (OSError, ValueError):
        pass
    texts = [ln.text for ln in lyrics.lines]
    result, src = [], ""
    chunk: list[str] = []

    def flush():
        nonlocal src
        if not chunk:
            return
        joined, lang = _translate_chunk("\n".join(chunk), target)
        src = src or lang
        parts = joined.split("\n")
        if len(parts) != len(chunk):   # переводчик склеил строки — переводим поштучно
            parts = [_translate_chunk(t, target)[0] for t in chunk]
        result.extend(p.strip() for p in parts)
        chunk.clear()

    size = 0
    for t in texts:
        if size + len(t) > 1500:
            flush()
            size = 0
        chunk.append(t)
        size += len(t) + 1
    flush()
    lines = None if src == target else result
    try:
        cache.write_text(json.dumps({"n": len(texts), "lines": lines}, ensure_ascii=False), "utf-8")
    except OSError:
        pass
    return lines
