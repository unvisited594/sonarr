"""Скачанные треки Navidrome для офлайна: папка downloads (см. sonar/paths.py).

downloads/index.json хранит, что скачано; сами файлы лежат рядом, обложки — в covers/.
"""
import json
from pathlib import Path

from PyQt6.QtCore import QObject, QUrl, pyqtSignal

from .services.base import Track
from .workers import run_async

SERVICE_ID = "navidrome"


def downloads_dir() -> Path:
    from .paths import downloads_dir as _resolve
    return _resolve()


class Downloads(QObject):
    changed = pyqtSignal()
    finished = pyqtSignal(str)        # название трека
    failed = pyqtSignal(str, str)     # название, причина

    def __init__(self, manager, folder: Path | None = None) -> None:
        super().__init__()
        self.manager = manager
        self.dir = folder or downloads_dir()
        self.index_path = self.dir / "index.json"
        self.pending: set[str] = set()
        try:
            entries = json.loads(self.index_path.read_text("utf-8"))
        except (OSError, ValueError):
            entries = []
        # файл могли удалить руками: такие записи не считаем скачанными
        self.entries = {e["id"]: e for e in entries if (self.dir / e["file"]).exists()}

    def _save(self) -> None:
        tmp = self.index_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(list(self.entries.values()), ensure_ascii=False, indent=1), "utf-8")
        tmp.replace(self.index_path)

    def has(self, track_id: str) -> bool:
        return track_id in self.entries

    def local_path(self, track_id: str) -> Path | None:
        e = self.entries.get(track_id)
        return self.dir / e["file"] if e else None

    def track(self, e: dict) -> Track:
        cover = self.dir / "covers" / e["cover"] if e.get("cover") else None
        return Track(id=e["id"], title=e["title"], artist=e["artist"], duration_ms=e.get("duration_ms") or 0,
                     artwork_url=QUrl.fromLocalFile(str(cover)).toString() if cover and cover.exists() else None,
                     service_id=SERVICE_ID, permalink=e.get("permalink"), playable=True,
                     raw={"local_file": str(self.dir / e["file"])})

    def tracks(self) -> list[Track]:
        return [self.track(e) for e in reversed(list(self.entries.values()))]  # новые сверху

    def start(self, track: Track) -> None:
        service = self.manager.get(SERVICE_ID)
        if track.service_id != SERVICE_ID or track.id in self.pending or self.has(track.id):
            return
        if service is None:
            self.failed.emit(track.title, "Navidrome не подключён.")
            return
        self.pending.add(track.id)
        run_async(service.download, track, self.dir,
                  on_done=lambda entry, t=track: self._done(t, entry),
                  on_error=lambda err, t=track: self._error(t, err))
        self.changed.emit()

    def _done(self, track: Track, entry: dict) -> None:
        self.pending.discard(track.id)
        self.entries[track.id] = entry
        self._save()
        self.changed.emit()
        self.finished.emit(track.title)

    def _error(self, track: Track, err: str) -> None:
        self.pending.discard(track.id)
        self.changed.emit()
        self.failed.emit(track.title, err)

    def remove(self, track_id: str) -> None:
        e = self.entries.pop(track_id, None)
        if not e:
            return
        (self.dir / e["file"]).unlink(missing_ok=True)
        if e.get("cover"):
            (self.dir / "covers" / e["cover"]).unlink(missing_ok=True)
        self._save()
        self.changed.emit()


_downloads: Downloads | None = None


def downloads() -> Downloads | None:
    return _downloads


def set_downloads(store: Downloads) -> None:
    global _downloads
    _downloads = store
