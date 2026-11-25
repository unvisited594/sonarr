"""SoundCloud через api-v2 (тот же API, что использует сайт soundcloud.com).

Авторизация: cookie oauth_token из браузера. client_id находится автоматически
в JS-бандле сайта, либо задаётся вручную.
"""
import random
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from itertools import zip_longest

import requests

from .base import same_artist
from .base import (Album, Artist, ArtistInfo, AuthError, BrowserLogin, CredentialField, MusicService,
                   Playlist, Section,
                   ServiceError,
                   TemporaryError, Track, UnavailableError)

API = "https://api-v2.soundcloud.com"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0 Safari/537.36")
SCRIPT_RE = re.compile(r'<script[^>]+src="(https://a-v2\.sndcdn\.com/assets/[^"]+\.js)"')
CLIENT_ID_RE = re.compile(r'client_id\s*[:=]\s*"([A-Za-z0-9]{32})"')
CACHE_TTL = 300


def _uniq(tracks):
    seen, out = set(), []
    for t in tracks:
        if t and t.id not in seen:
            seen.add(t.id)
            out.append(t)
    return out


class SoundCloud(MusicService):
    id = "soundcloud"
    name = "SoundCloud"
    description = "Лайки, история и рекомендации"
    icon_letters = "SC"
    icon_color = "#f26f23"
    help_text = (
        "Как получить токен вручную:\n"
        "1. Откройте soundcloud.com в браузере и войдите в аккаунт.\n"
        "2. Нажмите F12 → «Application» (в Firefox «Хранилище») → Cookies → soundcloud.com.\n"
        "3. Скопируйте значение cookie oauth_token и вставьте его ниже.\n"
        "Токен хранится только на этом компьютере."
    )
    browser_login = BrowserLogin("https://soundcloud.com/signin", "soundcloud.com",
                                 "oauth_token", "oauth_token")
    credential_fields = [
        CredentialField("oauth_token", "OAuth-токен", secret=True, placeholder="2-123456-…"),
        CredentialField("client_id", "client_id", required=False,
                        placeholder="Необязательно: определится автоматически"),
    ]

    def __init__(self, settings=None):
        super().__init__(settings)
        self.http = requests.Session()
        self.http.headers["User-Agent"] = UA
        self._cid_lock = threading.Lock()
        self._cache: dict | None = None
        self._cache_ts = 0.0

    # ---------- HTTP ----------

    def _fetch_client_id(self) -> str:
        try:
            html = self.http.get("https://soundcloud.com/", timeout=15).text
            for url in reversed(SCRIPT_RE.findall(html)):
                match = CLIENT_ID_RE.search(self.http.get(url, timeout=15).text)
                if match:
                    return match.group(1)
        except requests.RequestException as exc:
            raise ServiceError(f"Нет связи с SoundCloud ({exc.__class__.__name__})") from exc
        raise ServiceError("Не удалось определить client_id. Укажите его вручную в настройках.")

    def _client_id(self, refresh: bool = False) -> str:
        with self._cid_lock:
            if refresh or not self.settings.get("client_id"):
                self.settings["client_id"] = self._fetch_client_id()
            return self.settings["client_id"]

    def _get(self, path: str, params=None, token=None, _retry=True):
        url = path if path.startswith("http") else API + path
        query = dict(params or {})
        query["client_id"] = self._client_id()
        token = token or self.settings.get("oauth_token")
        headers = {"Authorization": f"OAuth {token}"} if token else {}
        try:
            resp = self.http.get(url, params=query, headers=headers, timeout=20)
        except requests.RequestException as exc:
            raise TemporaryError(f"Нет связи с SoundCloud ({exc.__class__.__name__})") from exc

        if resp.status_code == 401:
            if _retry:  # чаще всего протух client_id
                self._client_id(refresh=True)
                return self._get(path, params, token, _retry=False)
            raise AuthError("SoundCloud не принял токен. Обновите его в Настройках → Интеграция.")
        if resp.status_code == 429:
            raise TemporaryError("SoundCloud ограничил частоту запросов. Попробуйте через минуту.")
        if resp.status_code == 404:
            raise ServiceError("Не найдено на SoundCloud.")
        if resp.status_code >= 500:
            raise TemporaryError(f"SoundCloud ответил ошибкой HTTP {resp.status_code}.")
        if resp.status_code >= 400:
            raise ServiceError(f"SoundCloud ответил ошибкой HTTP {resp.status_code}.")
        try:
            return resp.json()
        except ValueError as exc:
            raise ServiceError("SoundCloud вернул неожиданный ответ.") from exc

    # ---------- Модель ----------

    def _track(self, t: dict | None) -> Track | None:
        if not t or "title" not in t:
            return None
        user = t.get("user") or {}
        art = t.get("artwork_url") or user.get("avatar_url")
        if art:
            art = art.replace("-large.", "-t300x300.")
        publisher = t.get("publisher_metadata") or {}
        media = t.get("media")
        transcodings = (media or {}).get("transcodings") or []
        full = [tr for tr in transcodings if not tr.get("snipped")]
        playable = (
            t.get("streamable", True) is not False
            and t.get("policy") != "BLOCK"
            and t.get("state", "finished") == "finished"
            and not (media is not None and not transcodings)  # потоков нет совсем
            and not (transcodings and not full)               # только 30-секундный фрагмент (Go+)
            and not self.is_known_unavailable(str(t["id"]))   # уже не запускался раньше
        )
        return Track(
            id=str(t["id"]),
            title=t.get("title") or "Без названия",
            artist=publisher.get("artist") or user.get("username") or "",
            duration_ms=int(t.get("full_duration") or t.get("duration") or 0),
            artwork_url=art,
            service_id=self.id,
            permalink=t.get("permalink_url"),
            playable=playable,
            preview=bool(transcodings) and not full,
            raw={**t, "artist_id": str(user["id"]) if user.get("id") else None},
        )

    def _tracks(self, collection, key=None) -> list[Track]:
        return _uniq(self._track(item.get(key) if key else item) for item in collection or [])

    # ---------- MusicService ----------

    def connect(self, credentials: dict) -> dict:
        token = (credentials.get("oauth_token") or "").strip()
        if token.lower().startswith("oauth "):
            token = token[6:].strip()
        if not token:
            raise AuthError("Укажите OAuth-токен.")
        if credentials.get("client_id"):
            self.settings["client_id"] = credentials["client_id"].strip()
        me = self._get("/me", token=token)
        self.settings.update(
            oauth_token=token,
            connected=True,
            account={
                "id": me["id"],
                "name": me.get("username") or me.get("full_name") or "",
                "avatar": me.get("avatar_url"),
            },
        )
        return self.settings

    def _related(self, seed: Track) -> list[Track]:
        try:
            data = self._get(f"/tracks/{seed.id}/related", {"limit": 20})
        except ServiceError:
            return []
        return self._tracks(data.get("collection"))

    def _load(self, force: bool = False) -> dict:
        if self._cache and not force and time.time() - self._cache_ts < CACHE_TTL:
            return self._cache
        uid = self.settings["account"]["id"]
        likes = self._tracks(
            self._get(f"/users/{uid}/track_likes", {"limit": 60}).get("collection"), "track")
        try:
            history = self._tracks(
                self._get("/me/play-history/tracks", {"limit": 40}).get("collection"), "track")
        except AuthError:
            raise
        except ServiceError:
            history = []

        # Рекомендации: похожие треки на недавно прослушанные и лайкнутые.
        seeds = _uniq(history[:4] + likes[:6])[:8]
        with ThreadPoolExecutor(max_workers=4) as pool:
            related = list(pool.map(self._related, seeds))
        known = {t.id for t in likes}
        recs = []
        for row in zip_longest(*related):
            for t in row:
                if t and t.playable and t.id not in known:
                    known.add(t.id)
                    recs.append(t)

        self._cache = {"likes": likes, "history": history, "recs": recs[:60]}
        self._cache_ts = time.time()
        return self._cache

    def home_sections(self, force: bool = False) -> list[Section]:
        data = self._load(force)
        sections = [
            Section("recs", "Рекомендации", data["recs"]),
            Section("likes", "Мне нравится", data["likes"]),
            Section("history", "Вы недавно слушали", data["history"]),
        ]
        return [s for s in sections if s.tracks]

    def wave(self) -> list[Track]:
        data = self._load()
        pool = list(data["recs"])
        likes = [t for t in data["likes"] if t.playable]
        random.shuffle(likes)
        pool += likes[: max(10, len(pool) // 3)]
        random.shuffle(pool)
        return _uniq(pool)

    def _playlist(self, p: dict | None) -> Playlist | None:
        if not p or not p.get("id"):
            return None
        art = p.get("artwork_url") or next(
            (t.get("artwork_url") for t in p.get("tracks") or [] if t.get("artwork_url")), None)
        if art:
            art = art.replace("-large.", "-t300x300.")
        return Playlist(id=str(p["id"]), title=p.get("title") or "Без названия", cover_url=art,
                        count=p.get("track_count"), service_id=self.id,
                        owner=(p.get("user") or {}).get("username", ""), raw=p)

    def playlists(self) -> list[Playlist]:
        uid = self.settings["account"]["id"]
        found = []
        for path, key in ((f"/users/{uid}/playlists", None), (f"/users/{uid}/playlist_likes", "playlist")):
            try:
                items = self._get(path, {"limit": 50}).get("collection") or []
            except (AuthError, TemporaryError):
                raise
            except ServiceError:
                continue  # одного из списков может не быть: показываем то, что есть
            found += [self._playlist(i.get(key) if key else i) for i in items]
        seen, out = set(), []
        for p in found:
            if p and p.id not in seen:
                seen.add(p.id)
                out.append(p)
        return out

    def playlist_tracks(self, playlist: Playlist) -> list[Track]:
        if playlist.id.startswith("soundcloud:system-playlists"):   # подборки самого SoundCloud
            data = self._get(f"/system-playlists/{playlist.id}")
        else:
            data = self._get(f"/playlists/{playlist.id}")
        return self._hydrate(data.get("tracks") or [])

    def _hydrate(self, items: list) -> list[Track]:
        """Полностью приходят только первые треки, у остальных лишь id: догружаем пачками по 50."""
        missing = [str(t["id"]) for t in items if "title" not in t and t.get("id")]
        full = {str(t["id"]): t for t in items if "title" in t}
        for i in range(0, len(missing), 50):
            batch = self._get("/tracks", {"ids": ",".join(missing[i:i + 50])})
            for t in batch if isinstance(batch, list) else batch.get("collection", []):
                full[str(t["id"])] = t
        return [tr for tr in (self._track(full.get(str(t.get("id")))) for t in items) if tr]

    @staticmethod
    def _art(url: str | None) -> str | None:
        return url.replace("-large.", "-t300x300.") if url else None

    def _artist(self, u: dict) -> Artist | None:
        if not u or not u.get("id"):
            return None
        return Artist(str(u["id"]), u.get("username") or "", self._art(u.get("avatar_url")), self.id)

    def _album(self, p: dict) -> Album | None:
        if not p or not p.get("id"):
            return None
        art = p.get("artwork_url") or next((t.get("artwork_url") for t in p.get("tracks") or []
                                            if t.get("artwork_url")), None)
        user = p.get("user") or {}
        kinds = {"album": "Альбом", "ep": "EP", "single": "Сингл", "compilation": "Сборник"}
        return Album(str(p["id"]), p.get("title") or "Без названия", self._art(art), self.id,
                     artist=user.get("username", ""), artist_id=str(user.get("id")) if user.get("id") else None,
                     date=(p.get("release_date") or p.get("published_at") or p.get("created_at") or "")[:10],
                     kind=kinds.get(p.get("set_type") or "", "Альбом"))

    def find_artist(self, name: str) -> Artist | None:
        for u in self._get("/search/users", {"q": name, "limit": 5}).get("collection") or []:
            if same_artist(name, u.get("username") or ""):
                return self._artist(u)
        return None

    def library_artists(self) -> list[Artist]:
        uid = self.settings["account"]["id"]
        items = self._get(f"/users/{uid}/followings", {"limit": 100}).get("collection") or []
        return [a for a in (self._artist(u) for u in items) if a]

    def library_albums(self) -> list[Album]:
        return [self._album(p.raw) for p in self.playlists()
                if p.raw.get("is_album") or (p.raw.get("set_type") or "") in ("album", "ep", "single")]

    def artist_info(self, artist_id: str) -> ArtistInfo:
        user = self._get(f"/users/{artist_id}")
        artist = self._artist(user) or Artist(artist_id, "", None, self.id)
        try:
            albums = [a for a in (self._album(p) for p in
                                  self._get(f"/users/{artist_id}/albums", {"limit": 30}).get("collection") or []) if a]
        except (AuthError, TemporaryError):
            raise
        except ServiceError:
            albums = []
        try:
            top = self._tracks(self._get(f"/users/{artist_id}/toptracks", {"limit": 10}).get("collection"))
        except (AuthError, TemporaryError):
            raise
        except ServiceError:
            top = []
        albums.sort(key=lambda a: a.date, reverse=True)
        return ArtistInfo(artist, (user.get("description") or "").strip(), albums, top)

    def album_tracks(self, album: Album) -> list[Track]:
        return self._hydrate(self._get(f"/playlists/{album.id}").get("tracks") or [])

    def featured_playlists(self) -> list[Playlist]:
        """Подборки SoundCloud с главной сайта (системные плейлисты и тематические)."""
        out = []
        for sel in self._get("/mixed-selections", {"limit": 10}).get("collection") or []:
            for p in (sel.get("items") or {}).get("collection") or []:
                pid = p.get("urn") if (p.get("kind") or "").startswith("system") else p.get("id")
                if not pid:
                    continue
                art = p.get("calculated_artwork_url") or p.get("artwork_url")
                out.append(Playlist(str(pid), p.get("title") or p.get("short_title") or "Подборка",
                                    self._art(art), p.get("track_count"), self.id,
                                    owner=(p.get("user") or {}).get("username", "SoundCloud")))
        return out

    def search(self, query: str) -> list[Track]:
        data = self._get("/search/tracks", {"q": query, "limit": 30})
        return self._tracks(data.get("collection"))

    def stream_url(self, track: Track) -> str:
        raw = track.raw
        transcodings = (raw.get("media") or {}).get("transcodings") or []
        if not transcodings:  # в некоторых списках приходят «урезанные» объекты
            try:
                raw = self._get(f"/tracks/{track.id}")
            except (AuthError, TemporaryError):
                raise
            except ServiceError as exc:
                raise UnavailableError("Трек удалён или скрыт на SoundCloud.") from exc
            transcodings = (raw.get("media") or {}).get("transcodings") or []

        def rank(tr):
            fmt = tr.get("format") or {}
            return (fmt.get("protocol") != "progressive",
                    "mpeg" not in (fmt.get("mime_type") or ""),
                    bool(tr.get("snipped")))

        # Зашифрованные потоки (ctr/cbc-encrypted-hls) плеер не откроет.
        candidates = [tr for tr in transcodings
                      if (tr.get("format") or {}).get("protocol") in ("progressive", "hls")]
        params = {}
        if raw.get("track_authorization"):
            params["track_authorization"] = raw["track_authorization"]
        candidates = [tr for tr in candidates if not tr.get("snipped")]  # фрагмент не считаем треком
        for tr in sorted(candidates, key=rank):
            try:
                url = self._get(tr["url"], params).get("url")
            except (AuthError, TemporaryError):
                raise
            except ServiceError:
                continue  # 403/404 на этот формат: пробуем следующий
            if url:
                return url
        raise UnavailableError("SoundCloud не отдаёт этот трек (регион, подписка Go+ или правообладатель).")
