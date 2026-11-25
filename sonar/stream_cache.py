"""Кеш треков, которые надёжнее скачать целиком, чем играть потоком.

Прямые ссылки Яндекса — это файлы mp3. Если играть их потоком, плеер держит соединение открытым
минутами, и сервер его обрывает («Unable to read from socket» → трек прерывается). Скачанный
файл (~7 МБ) обрываться не может, а перемотка по нему мгновенная. Следующий трек очереди
подкачивается заранее.
"""
import logging
import tempfile
import threading
import time
from pathlib import Path

import requests

from .services.base import TemporaryError, UnavailableError

log = logging.getLogger("sonar.cache")
KEEP_FILES = 40
ATTEMPTS = 4


class StreamCache:
    def __init__(self, folder: Path | None = None) -> None:
        self.dir = folder or Path(tempfile.gettempdir()) / "Sonar" / "cache"
        self.dir.mkdir(parents=True, exist_ok=True)
        self._locks: dict[str, threading.Lock] = {}
        self._guard = threading.Lock()
        self.http = requests.Session()
        self.prune()

    def path_for(self, track) -> Path:
        safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in f"{track.service_id}_{track.id}")
        return self.dir / f"{safe}.audio"

    def has(self, track) -> bool:
        return self.path_for(track).exists()

    def _lock(self, key: str) -> threading.Lock:
        with self._guard:
            return self._locks.setdefault(key, threading.Lock())

    def fetch(self, service, track) -> str:
        """Скачивает трек (если ещё нет) и возвращает путь. Вызывать в фоновом потоке."""
        target = self.path_for(track)
        with self._lock(target.name):   # основная загрузка и упреждающая не дублируют друг друга
            if target.exists():
                return str(target)
            part = target.with_suffix(".part")
            url = service.stream_url(track)
            written, total = 0, None
            started = time.monotonic()
            for attempt in range(ATTEMPTS):
                headers = {"Range": f"bytes={written}-"} if written else {}
                try:
                    with self.http.get(url, stream=True, timeout=(10, 30), headers=headers) as resp:
                        if resp.status_code in (403, 404, 410) and attempt < ATTEMPTS - 1:
                            log.warning("ссылка устарела (HTTP %s), беру новую", resp.status_code)
                            url, written, total = service.stream_url(track), 0, None
                            continue
                        if resp.status_code not in (200, 206):
                            raise TemporaryError(f"Сервер ответил HTTP {resp.status_code} при загрузке трека.")
                        if resp.status_code == 200:   # докачка не поддержана — начинаем заново
                            written = 0
                        if total is None:
                            length = resp.headers.get("Content-Length")
                            total = int(length) + written if length else None
                        with open(part, "ab" if written else "wb") as out:
                            for chunk in resp.iter_content(64 * 1024):
                                out.write(chunk)
                                written += len(chunk)
                    if total is None or written >= total:
                        break
                    log.warning("загрузка оборвалась на %s из %s байт, докачиваю", written, total)
                except requests.RequestException as exc:
                    log.warning("сбой загрузки (%s), попытка %s из %s, скачано %s байт",
                                exc.__class__.__name__, attempt + 1, ATTEMPTS, written)
                    time.sleep(0.6 * (attempt + 1))
            else:
                part.unlink(missing_ok=True)
                raise TemporaryError("Не удалось скачать трек: соединение несколько раз оборвалось.")
            if written == 0:
                part.unlink(missing_ok=True)
                raise UnavailableError("Сервер отдал пустой файл.")
            part.replace(target)
            log.info("скачан %s: %.1f МБ за %.1f с", track.id, written / 1048576, time.monotonic() - started)
        self.prune()
        return str(target)

    def prune(self) -> None:
        try:
            files = sorted((f for f in self.dir.glob("*.audio")), key=lambda f: f.stat().st_mtime, reverse=True)
            for old in files[KEEP_FILES:]:
                old.unlink(missing_ok=True)
            for stale in self.dir.glob("*.part"):   # оборванные загрузки прошлых запусков
                if time.time() - stale.stat().st_mtime > 3600:
                    stale.unlink(missing_ok=True)
        except OSError:
            pass


_cache: StreamCache | None = None


def cache() -> StreamCache:
    global _cache
    if _cache is None:
        _cache = StreamCache()
    return _cache
