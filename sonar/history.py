"""История прослушанного в Sonar: %APPDATA%/Sonar/history.json."""
import json
import threading
import time

from PyQt6.QtCore import QObject, QTimer, pyqtSignal

from .config import config_dir
from .library import slim_raw as _slim_raw, track_from_dict
from .services.base import Track

LIMIT = 300


class History(QObject):
    changed = pyqtSignal()

    def __init__(self) -> None:
        super().__init__()
        self.path = config_dir() / "history.json"
        self.entries: list[dict] = []
        self._lock = threading.Lock()
        try:
            self.entries = json.loads(self.path.read_text("utf-8"))
        except (OSError, ValueError):
            self.entries = []
        self.frozen = False  # после сброса данных сохранение отключено
        self._save_timer = QTimer(self, singleShot=True, interval=1500)
        self._save_timer.timeout.connect(self.save)

    def add(self, track: Track) -> None:
        key = (track.service_id, track.id)
        # Один трек показываем один раз, на месте последнего прослушивания; число раз — для статистики.
        plays = sum(e.get("plays", 1) for e in self.entries if (e["service_id"], e["id"]) == key)
        self.entries = [e for e in self.entries if (e["service_id"], e["id"]) != key]
        self.entries.insert(0, {
            "id": track.id, "title": track.title, "artist": track.artist,
            "duration_ms": track.duration_ms, "artwork_url": track.artwork_url,
            "service_id": track.service_id, "permalink": track.permalink,
            "raw": _slim_raw(track.raw), "played_at": time.time(), "plays": plays + 1,
        })
        del self.entries[LIMIT:]
        self._save_timer.start()
        self.changed.emit()

    def clear(self) -> None:
        self.entries = []
        self.save()
        self.changed.emit()

    def save(self) -> None:
        if self.frozen:
            return
        with self._lock:
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.entries, ensure_ascii=False), "utf-8")
            tmp.replace(self.path)

    def stats(self, days: int = 7) -> dict:
        """Сводка за последние дни: сколько треков, примерно сколько часов, кого слушали чаще всего."""
        since = time.time() - days * 86400
        recent = [e for e in self.entries if e.get("played_at", 0) >= since]
        artists: dict[str, int] = {}
        for e in recent:
            name = (e.get("artist") or "").split(",")[0].strip()
            if name:
                artists[name] = artists.get(name, 0) + e.get("plays", 1)
        seconds = sum((e.get("duration_ms") or 0) / 1000 * e.get("plays", 1) for e in recent)
        top = max(artists.items(), key=lambda kv: kv[1])[0] if artists else ""
        return {"tracks": len(recent), "hours": seconds / 3600, "top_artist": top}

    def tracks(self, manager) -> list[tuple[Track, float]]:
        """Треки с временем прослушивания. Трек отключённого сервиса не запустить."""
        out = []
        for e in sorted(self.entries, key=lambda e: e.get("played_at", 0), reverse=True):
            out.append((track_from_dict(e, manager), e.get("played_at", 0)))
        return out
