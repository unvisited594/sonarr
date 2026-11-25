"""Локальная медиатека: сериализация треков и «Мои лайки» (%APPDATA%/Sonar/likes.json).

Лайки живут только в Sonar: на сервисах ничего не меняется, поэтому в одном списке
лежат треки из разных сервисов.
"""
import json
import threading
import time
import uuid

from PyQt6.QtCore import QObject, QTimer, pyqtSignal

from .config import config_dir
from .services.base import Track

# Части исходных данных трека, без которых его потом не запустить заново:
# ISRC и исполнители для подбора Spotify на YouTube, тип видео и клип для YouTube Music.
# SoundCloud перезапрашивает трек по id сам.
KEEP_RAW = ("external_ids", "videoType", "counterpart", "ym_id", "isrc", "artist_id", "album_id")


def slim_raw(raw: dict) -> dict:
    slim = {k: raw[k] for k in KEEP_RAW if k in raw}
    if raw.get("artists"):
        slim["artists"] = [{"name": a.get("name", "")} for a in raw["artists"] if isinstance(a, dict)]
    return slim


def track_to_dict(track: Track) -> dict:
    return {"id": track.id, "title": track.title, "artist": track.artist,
            "duration_ms": track.duration_ms, "artwork_url": track.artwork_url,
            "service_id": track.service_id, "permalink": track.permalink,
            "raw": slim_raw(track.raw)}


def track_from_dict(entry: dict, manager) -> Track:
    """Трек отключённого сервиса или уже не запускавшийся считается недоступным."""
    service = manager.get(entry["service_id"])
    track = Track(id=entry["id"], title=entry["title"], artist=entry["artist"],
                  duration_ms=entry.get("duration_ms") or 0, artwork_url=entry.get("artwork_url"),
                  service_id=entry["service_id"], permalink=entry.get("permalink"),
                  raw=dict(entry.get("raw") or {}))
    track.playable = service is not None and not service.is_known_unavailable(track.id)
    if not track.playable:  # скачанный трек играет и без подключённого сервиса
        from .downloads import downloads
        store = downloads()
        track.playable = store is not None and track.service_id == "navidrome" and store.has(track.id)
    return track


class JsonStore(QObject):
    """Список записей в JSON-файле с отложенным сохранением."""
    changed = pyqtSignal()

    def __init__(self, filename: str) -> None:
        super().__init__()
        self.path = config_dir() / filename
        self._lock = threading.Lock()
        try:
            self.entries: list[dict] = json.loads(self.path.read_text("utf-8"))
        except (OSError, ValueError):
            self.entries = []
        self.frozen = False  # после сброса данных сохранение отключено
        self._save_timer = QTimer(self, singleShot=True, interval=1500)
        self._save_timer.timeout.connect(self.save)

    def save(self) -> None:
        if self.frozen:
            return
        with self._lock:
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.entries, ensure_ascii=False), "utf-8")
            tmp.replace(self.path)

    def _touch(self) -> None:
        self._save_timer.start()
        self.changed.emit()


class Likes(JsonStore):
    liked = pyqtSignal(object)   # трек только что лайкнули (для анимации)

    def __init__(self) -> None:
        super().__init__("likes.json")
        self._keys = {(e["service_id"], e["id"]) for e in self.entries}

    def contains(self, track: Track) -> bool:
        return (track.service_id, track.id) in self._keys

    def add(self, track: Track) -> None:
        if self.contains(track):
            return
        entry = track_to_dict(track)
        entry["liked_at"] = time.time()
        self.entries.insert(0, entry)
        self._keys.add((track.service_id, track.id))
        self._touch()
        self.liked.emit(track)

    def remove(self, track: Track) -> None:
        key = (track.service_id, track.id)
        if key not in self._keys:
            return
        self.entries = [e for e in self.entries if (e["service_id"], e["id"]) != key]
        self._keys.discard(key)
        self._touch()

    def toggle(self, track: Track) -> bool:
        """Возвращает новое состояние: True — трек теперь в лайках."""
        if self.contains(track):
            self.remove(track)
            return False
        self.add(track)
        return True

    def tracks(self, manager) -> list[Track]:
        return [track_from_dict(e, manager) for e in self.entries]


class LocalPlaylists(JsonStore):
    """Локальные плейлисты: треки из любых сервисов вперемешку."""

    def __init__(self) -> None:
        super().__init__("playlists.json")

    def all(self) -> list[dict]:
        return self.entries

    def get(self, playlist_id: str) -> dict | None:
        return next((p for p in self.entries if p["id"] == playlist_id), None)

    def create(self, title: str) -> str:
        pid = uuid.uuid4().hex[:12]
        self.entries.insert(0, {"id": pid, "title": title.strip() or "Новый плейлист",
                                "created_at": time.time(), "tracks": []})
        self._touch()
        return pid

    def rename(self, playlist_id: str, title: str) -> None:
        p = self.get(playlist_id)
        if p and title.strip():
            p["title"] = title.strip()
            self._touch()

    def delete(self, playlist_id: str) -> None:
        self.entries = [p for p in self.entries if p["id"] != playlist_id]
        self._touch()

    def contains(self, playlist_id: str, track: Track) -> bool:
        p = self.get(playlist_id)
        return bool(p) and any((t["service_id"], t["id"]) == (track.service_id, track.id)
                               for t in p["tracks"])

    def add(self, playlist_id: str, track: Track) -> bool:
        """False, если трек уже в плейлисте: дубли не добавляем."""
        p = self.get(playlist_id)
        if not p or self.contains(playlist_id, track):
            return False
        p["tracks"].append(track_to_dict(track))
        self._touch()
        return True

    def remove_at(self, playlist_id: str, index: int) -> None:
        p = self.get(playlist_id)
        if p and 0 <= index < len(p["tracks"]):
            del p["tracks"][index]
            self._touch()

    def tracks(self, playlist_id: str, manager) -> list[Track]:
        p = self.get(playlist_id)
        return [track_from_dict(t, manager) for t in (p or {}).get("tracks", [])]


class UnavailableTracks(JsonStore):
    """Треки, которые не послушать, — те, что прячет «Скрывать недоступные треки».
    Новые сверху, не больше LIMIT: при переполнении удаляются самые старые."""
    LIMIT = 1000

    def __init__(self) -> None:
        super().__init__("unavailable.json")
        self._keys = {(e["service_id"], e["id"]) for e in self.entries}

    def note(self, track: Track, reason: str = "") -> None:
        key = (track.service_id, track.id)
        if key in self._keys:
            if reason:   # уточняем причину, если она стала известна
                for e in self.entries:
                    if (e["service_id"], e["id"]) == key and not e.get("reason"):
                        e["reason"] = reason
                        self._touch()
                        break
            return
        entry = track_to_dict(track)
        entry.update(reason=reason, noted_at=time.time())
        self.entries.insert(0, entry)
        self._keys.add(key)
        for old in self.entries[self.LIMIT:]:
            self._keys.discard((old["service_id"], old["id"]))
        del self.entries[self.LIMIT:]
        self._touch()

    def discard(self, track: Track) -> None:
        """Трек всё-таки заиграл — убираем из списка."""
        key = (track.service_id, track.id)
        if key in self._keys:
            self._keys.discard(key)
            self.entries = [e for e in self.entries if (e["service_id"], e["id"]) != key]
            self._touch()

    def clear(self) -> None:
        self.entries, self._keys = [], set()
        self._touch()

    def tracks(self, manager) -> list[tuple[Track, str]]:
        out = []
        for e in self.entries:
            t = track_from_dict(e, manager)
            t.playable = False
            out.append((t, e.get("reason") or ""))
        return out


_likes: Likes | None = None
_unavailable: UnavailableTracks | None = None
_playlists: LocalPlaylists | None = None


def likes() -> Likes | None:
    """Общие лайки приложения (создаются главным окном), чтобы меню трека везде их видело."""
    return _likes


def set_likes(store: Likes) -> None:
    global _likes
    _likes = store


def unavailable() -> UnavailableTracks | None:
    return _unavailable


def set_unavailable(store: UnavailableTracks) -> None:
    global _unavailable
    _unavailable = store


def playlists() -> LocalPlaylists | None:
    return _playlists


def set_playlists(store: LocalPlaylists) -> None:
    global _playlists
    _playlists = store
