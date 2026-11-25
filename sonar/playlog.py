"""Дневник прослушиваний для «Итогов года»: что, когда и сколько секунд реально звучало.

Файл plays.jsonl в папке настроек, по строке на прослушивание (от 10 секунд). Только на
этом компьютере. Треки до появления дневника берутся приблизительно из истории.
"""
import json
import time
from collections import Counter

from PyQt6.QtCore import QObject, QTimer

from .config import config_dir

MIN_SECONDS = 10


class PlayLog(QObject):
    def __init__(self, player) -> None:
        super().__init__(player)
        self.player = player
        self.path = config_dir() / "plays.jsonl"
        self._cur = None
        self._tick = QTimer(self, interval=1000)
        self._tick.timeout.connect(self._count)
        self._tick.start()
        player.started.connect(self._started)

    def _started(self, track) -> None:
        self.flush()
        self._cur = {"t": int(time.time()), "id": track.id, "service": track.service_id, "title": track.title,
                     "artist": track.artist, "dur": int((track.duration_ms or 0) / 1000), "s": 0}

    def _count(self) -> None:
        if self._cur is not None and self.player.is_playing:
            self._cur["s"] += 1

    def flush(self) -> None:
        cur, self._cur = self._cur, None
        if cur and cur["s"] >= MIN_SECONDS:
            try:
                with open(self.path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(cur, ensure_ascii=False) + "\n")
            except OSError:
                pass


def load_events(year: int, history_entries: list | None = None) -> list[dict]:
    """Прослушивания за год: из дневника, а то, что было раньше дневника, — примерно из истории."""
    events = []
    path = config_dir() / "plays.jsonl"
    first = None
    if path.exists():
        for line in path.read_text("utf-8").splitlines():
            try:
                e = json.loads(line)
            except ValueError:
                continue
            first = e["t"] if first is None else min(first, e["t"])
            if time.localtime(e["t"]).tm_year == year:
                events.append(e)
    for h in history_entries or []:   # до дневника: число прослушиваний × длительность
        at = h.get("played_at") or 0
        if not at or time.localtime(at).tm_year != year or (first is not None and at >= first):
            continue
        dur = int((h.get("duration_ms") or 0) / 1000) or 180
        for k in range(int(h.get("plays", 1))):
            events.append({"t": int(at) - k * 3600, "id": h.get("id"), "service": h.get("service_id"),
                           "title": h.get("title", ""), "artist": h.get("artist", ""), "dur": dur,
                           "s": int(dur * 0.8), "approx": True})
    return events


def summarize(events: list[dict]) -> dict:
    if not events:
        return {"plays": 0}
    secs = sum(e["s"] for e in events)
    by_artist, by_track, by_service, by_day, by_hour = Counter(), Counter(), Counter(), Counter(), Counter()
    track_info = {}
    for e in events:
        first_artist = (e.get("artist") or "—").split(",")[0].strip() or "—"
        by_artist[first_artist] += e["s"]
        key = ((e.get("title") or "").lower(), first_artist.lower())
        by_track[key] += 1
        track_info.setdefault(key, (e.get("title") or "Без названия", first_artist))
        by_service[e.get("service") or "?"] += e["s"]
        lt = time.localtime(e["t"])
        by_day[time.strftime("%Y-%m-%d", lt)] += e["s"]
        by_hour[lt.tm_hour] += e["s"]
    night = sum(v for h, v in by_hour.items() if h < 5)
    day, day_secs = by_day.most_common(1)[0]
    hour = by_hour.most_common(1)[0][0]
    first = min(events, key=lambda e: e["t"])
    return {
        "plays": len(events), "minutes": secs // 60, "artists": len(by_artist), "tracks": len(by_track),
        "top_artists": [(a, s // 60) for a, s in by_artist.most_common(5)],
        "top_tracks": [(track_info[k][0], track_info[k][1], n) for k, n in by_track.most_common(5)],
        "services": [(sid, s // 60) for sid, s in by_service.most_common()],
        "night_share": round(100 * night / secs) if secs else 0, "hour": hour,
        "best_day": day, "best_day_minutes": day_secs // 60,
        "first": (first.get("title") or "", (first.get("artist") or "").split(",")[0]),
        "approx": any(e.get("approx") for e in events),
    }
