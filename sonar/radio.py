"""Интернет-радио: открытый каталог radio-browser.info (десятки тысяч станций, без ключей).

Станция для плеера — обычный Track сервиса «radio»: id — uuid станции, permalink — адрес потока,
длительность 0 (эфир). RadioService умеет только отдать адрес потока; ServiceManager.get("radio")
возвращает его всегда, без подключения.
"""
import logging
import random

import requests

from .services.base import MusicService, Track

log = logging.getLogger("sonar.radio")
SERVERS = ["de1", "de2", "fi1", "nl1", "at1"]
HEADERS = {"User-Agent": "Sonar/1.0 (desktop music player)"}
GENRES = [("Поп", "pop"), ("Рок", "rock"), ("Электроника", "electronic"), ("Хип-хоп", "hip hop"),
          ("Лоу-фай", "lofi"), ("Джаз", "jazz"), ("Классика", "classical"), ("Танцевальная", "dance"),
          ("Метал", "metal"), ("Шансон", "chanson"), ("Ретро", "oldies"), ("Новости", "news")]


def _get(path: str, params: dict) -> list:
    servers = SERVERS[:]
    random.shuffle(servers)
    last = None
    for name in servers[:3]:
        try:
            r = requests.get(f"https://{name}.api.radio-browser.info/json/{path}", params=params,
                             headers=HEADERS, timeout=10)
            r.raise_for_status()
            return r.json()
        except (requests.RequestException, ValueError) as exc:
            last = exc
    raise RuntimeError(f"каталог радио недоступен: {last}")


def to_track(st: dict) -> Track:
    tags = ", ".join([t for t in (st.get("tags") or "").split(",") if t][:3])
    where = st.get("country") or ""
    artist = " · ".join(x for x in (where, tags) if x) or "Интернет-радио"
    return Track(id=st.get("stationuuid") or st.get("url_resolved") or "", title=(st.get("name") or "Радио").strip()[:80],
                 artist=artist[:120], duration_ms=0, artwork_url=(st.get("favicon") or None),
                 service_id="radio", permalink=st.get("url_resolved") or st.get("url"))


def search(query: str = "", tag: str = "", country: str = "", limit: int = 60) -> list[Track]:
    params = {"limit": limit, "hidebroken": "true", "order": "clickcount", "reverse": "true"}
    if query:
        params["name"] = query
    if tag:
        params["tag"] = tag
    if country:
        params["countrycode"] = country
    seen, out = set(), []
    for st in _get("stations/search", params):
        url = st.get("url_resolved") or ""
        if not url.startswith(("http://", "https://")) or url in seen:
            continue
        seen.add(url)
        out.append(to_track(st))
    return out


def count_click(uuid: str) -> None:
    """Каталогу полезно знать, что станцию слушают (так он сортирует популярные)."""
    try:
        _get(f"url/{uuid}", {})
    except RuntimeError:
        pass


class RadioService(MusicService):
    id = "radio"
    name = "Радио"

    def __init__(self) -> None:
        super().__init__({"connected": True, "account": {"name": "Интернет-радио"}})

    def search(self, query: str) -> list[Track]:
        return search(query)

    def stream_url(self, track: Track) -> str:
        if track.id:
            count_click(track.id)
        return track.permalink or ""

    def wave(self) -> list[Track]:
        return []

    def connect(self, credentials: dict) -> dict:
        return self.settings

    def home_sections(self, force: bool = False) -> list:
        return []
