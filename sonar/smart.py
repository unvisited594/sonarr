"""Умные плейлисты: собираются сами из лайков, истории и дневника прослушиваний.

Хранятся среди «Моих плейлистов» с id «smart-…» и пометкой smart: переименовать, удалить или
добавить в них трек вручную нельзя — содержимое пересобирается при каждом открытии плейлистов.
"""
import json
import time
from collections import Counter

from .config import config_dir

MONTH = 30 * 86400
SMART = [
    ("smart-likes-month", "✦ Лайки за месяц", "Всё, что вы лайкнули за последние 30 дней"),
    ("smart-top", "✦ Самое заслушанное", "Треки, которые вы слушаете чаще всего"),
    ("smart-forgotten", "✦ Давно не слушал", "Любимые треки, которые давно не звучали"),
    ("smart-night", "✦ Ночное", "Что вы слушаете с полуночи до пяти утра"),
]


def _plays() -> list[dict]:
    path = config_dir() / "plays.jsonl"
    out = []
    try:
        for line in path.read_text("utf-8").splitlines():
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
    except OSError:
        pass
    return out


def build(likes, history) -> dict[str, list[dict]]:
    """Содержимое каждого умного плейлиста — записи треков (как в playlists.json)."""
    now = time.time()
    hist = getattr(history, "entries", []) or []
    by_key = {(e.get("service_id"), e.get("id")): e for e in hist}
    for e in likes.entries:
        by_key.setdefault((e.get("service_id"), e.get("id")), e)
    plays = _plays()
    count = Counter((p.get("service"), p.get("id")) for p in plays)
    for e in hist:   # до дневника — по истории
        count[(e.get("service_id"), e.get("id"))] += int(e.get("plays", 0) or 0)
    night = Counter((p.get("service"), p.get("id")) for p in plays if time.localtime(p["t"]).tm_hour < 5)
    last_played = {}
    for p in plays:
        k = (p.get("service"), p.get("id"))
        last_played[k] = max(last_played.get(k, 0), p["t"])
    for e in hist:
        k = (e.get("service_id"), e.get("id"))
        last_played[k] = max(last_played.get(k, 0), e.get("played_at") or 0)

    def entries(keys, limit=100):
        out = []
        for k in keys:
            e = by_key.get(k)
            if e is not None:
                out.append({kk: v for kk, v in e.items() if kk not in ("plays", "played_at", "liked_at")})
            if len(out) >= limit:
                break
        return out

    liked_month = [(e["service_id"], e["id"]) for e in likes.entries if now - (e.get("liked_at") or 0) < MONTH]
    forgotten = sorted(((e["service_id"], e["id"]) for e in likes.entries
                        if now - last_played.get((e["service_id"], e["id"]), 0) > MONTH),
                       key=lambda k: last_played.get(k, 0))
    return {
        "smart-likes-month": entries(liked_month),
        "smart-top": entries([k for k, n in count.most_common() if n >= 2], 50),
        "smart-forgotten": entries(forgotten, 60),
        "smart-night": entries([k for k, _n in night.most_common()], 60),
    }


def refresh(store, likes, history) -> None:
    """Пересобрать умные плейлисты в хранилище «Моих плейлистов» (сверху списка)."""
    content = build(likes, history)
    others = [p for p in store.entries if not p.get("smart")]
    smart = [{"id": pid, "title": title, "smart": True, "about": about, "created_at": 0,
              "tracks": content.get(pid, [])} for pid, title, about in SMART]
    store.entries = smart + others
    store._touch()


def is_smart(playlist_id: str | None) -> bool:
    return bool(playlist_id) and playlist_id.startswith("smart-")

