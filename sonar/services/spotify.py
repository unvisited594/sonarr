"""Spotify: библиотека и поиск через Web API, звук через тот же трек на YouTube.

Spotify не отдаёт аудио сторонним приложениям (только DRM), поэтому каждый трек
сопоставляется с YouTube Music по ISRC или по «исполнитель + название» с проверкой
длительности. Вход: OAuth 2.0 PKCE с собственным Client ID пользователя.
"""
import base64
import hashlib
import random
import secrets
import threading
import time
from itertools import zip_longest
from urllib.parse import parse_qs, urlencode, urlparse

import requests

from . import youtube_match
from .base import same_artist
from .base import (Album, Artist, ArtistInfo, AuthError, BrowserLogin, CredentialField, MusicService,
                   Playlist, Section,
                   ServiceError,
                   TemporaryError, Track)
from .youtube_music import AUDIO_FORMAT, VIDEO_FORMAT, extract_stream

API = "https://api.spotify.com/v1"
AUTH_URL = "https://accounts.spotify.com/authorize"
TOKEN_URL = "https://accounts.spotify.com/api/token"
REDIRECT_URI = "http://127.0.0.1:8898/callback"
SCOPES = ("user-library-read user-read-recently-played user-top-read user-read-private "
          "playlist-read-private playlist-read-collaborative")
CACHE_TTL = 300
SEARCH_PAGE = 10  # с февраля 2026 больше 10 за запрос Spotify не отдаёт


def _uniq(tracks):
    seen, out = set(), []
    for t in tracks:
        if t and t.id not in seen:
            seen.add(t.id)
            out.append(t)
    return out


class Spotify(MusicService):
    id = "spotify"
    name = "Spotify"
    description = "Лайки, топ и история; звук через YouTube"
    icon_letters = "SP"
    icon_color = "#1db954"
    supports_video = True
    login_needs_fields = True
    help_text = (
        "Spotify пускает сторонние программы только через ваше приложение разработчика:\n"
        "1. Откройте developer.spotify.com/dashboard и создайте приложение "
        "(нужен Spotify Premium у владельца).\n"
        f"2. В Redirect URIs добавьте {REDIRECT_URI}, в APIs отметьте Web API.\n"
        "3. Скопируйте Client ID сюда и нажмите «Войти».\n"
        "Сами треки играют через тот же трек на YouTube: Spotify не отдаёт звук "
        "сторонним программам."
    )
    credential_fields = [
        CredentialField("client_id", "Client ID", placeholder="Например, 3f9a…c21b"),
    ]

    def __init__(self, settings=None):
        super().__init__(settings)
        self.http = requests.Session()
        self._token_lock = threading.Lock()
        self._cache: dict | None = None
        self._cache_ts = 0.0

    # ---------- OAuth PKCE ----------

    def prepare_login(self, credentials: dict) -> BrowserLogin:
        client_id = (credentials.get("client_id") or "").strip()
        if not client_id:
            raise ServiceError("Укажите Client ID вашего приложения Spotify: как его получить, написано выше.")
        verifier = secrets.token_urlsafe(64)
        challenge = base64.urlsafe_b64encode(
            hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
        state = secrets.token_urlsafe(16)
        url = AUTH_URL + "?" + urlencode({
            "client_id": client_id, "response_type": "code", "redirect_uri": REDIRECT_URI,
            "code_challenge_method": "S256", "code_challenge": challenge,
            "scope": SCOPES, "state": state,
        })
        return BrowserLogin(url, "spotify.com", "", "redirect", redirect_prefix=REDIRECT_URI,
                            extra={"verifier": verifier, "state": state})

    def _token_request(self, data: dict) -> dict:
        try:
            resp = self.http.post(TOKEN_URL, data=data, timeout=20)
        except requests.RequestException as exc:
            raise ServiceError("Нет связи со Spotify.") from exc
        body = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
        if resp.status_code >= 400:
            reason = body.get("error_description") or body.get("error") or f"HTTP {resp.status_code}"
            raise AuthError(f"Spotify отказал во входе: {reason}. Войдите заново.")
        return body

    def _store_token(self, body: dict) -> None:
        self.settings["access_token"] = body["access_token"]
        self.settings["expires_at"] = time.time() + int(body.get("expires_in", 3600)) - 60
        if body.get("refresh_token"):  # Spotify может выдать новый refresh_token
            self.settings["refresh_token"] = body["refresh_token"]

    def connect(self, credentials: dict) -> dict:
        redirect = credentials.get("redirect") or ""
        params = parse_qs(urlparse(redirect).query)
        if "error" in params:
            raise AuthError("Вход в Spotify отменён." if params["error"][0] == "access_denied"
                            else f"Spotify вернул ошибку: {params['error'][0]}")
        if params.get("state", [None])[0] != credentials.get("state"):
            raise AuthError("Ответ Spotify не прошёл проверку. Попробуйте войти ещё раз.")
        code = params.get("code", [None])[0]
        if not code:
            raise AuthError("Spotify не вернул код входа.")
        client_id = credentials["client_id"].strip()
        body = self._token_request({
            "grant_type": "authorization_code", "code": code, "redirect_uri": REDIRECT_URI,
            "client_id": client_id, "code_verifier": credentials["verifier"],
        })
        self.settings["client_id"] = client_id
        self._store_token(body)
        me = self._get("/me", account_check=True)
        self.settings.update(connected=True,
                             account={"id": me.get("id"), "name": me.get("display_name") or me.get("id")})
        return self.settings

    def _access_token(self) -> str:
        with self._token_lock:
            if time.time() >= self.settings.get("expires_at", 0):
                if not self.settings.get("refresh_token"):
                    raise AuthError("Сессия Spotify истекла. Войдите заново в Настройках → Интеграция.")
                self._store_token(self._token_request({
                    "grant_type": "refresh_token", "client_id": self.settings["client_id"],
                    "refresh_token": self.settings["refresh_token"],
                }))
                self.save_settings()
            return self.settings["access_token"]

    def _get(self, path: str, params=None, _retry=True, account_check=False) -> dict:
        try:
            resp = self.http.get(API + path, params=params, timeout=20,
                                 headers={"Authorization": f"Bearer {self._access_token()}"})
        except requests.RequestException as exc:
            raise TemporaryError("Нет связи со Spotify.") from exc
        if resp.status_code == 401 and _retry:
            self.settings["expires_at"] = 0  # токен отозван раньше срока: обновляем
            return self._get(path, params, _retry=False, account_check=account_check)
        if resp.status_code == 401:
            raise AuthError("Spotify не принял токен. Войдите заново в Настройках → Интеграция.")
        if resp.status_code == 403:
            if account_check:  # /me не пускает: аккаунт не в списке пользователей приложения
                raise AuthError("Spotify запретил доступ: проверьте, что ваш аккаунт добавлен "
                                "в Users Management приложения и у владельца есть Premium.")
            raise ServiceError("Spotify закрыл этот раздел для приложений в режиме разработки.")
        if resp.status_code == 429:
            raise TemporaryError("Spotify ограничил частоту запросов. Попробуйте через минуту.")
        if resp.status_code >= 400:
            raise ServiceError(f"Spotify ответил ошибкой HTTP {resp.status_code}.")
        return resp.json()

    # ---------- данные ----------

    def _track(self, t: dict | None) -> Track | None:
        if not t or not t.get("id") or t.get("type", "track") != "track":
            return None
        images = (t.get("album") or {}).get("images") or []
        image = min((i for i in images if (i.get("width") or 0) >= 200),
                    key=lambda i: i.get("width") or 0, default=images[0] if images else None)
        return Track(
            id=t["id"],
            title=t.get("name") or "Без названия",
            artist=", ".join(a.get("name", "") for a in t.get("artists") or []),
            duration_ms=int(t.get("duration_ms") or 0),
            artwork_url=image.get("url") if image else None,
            service_id=self.id,
            permalink=(t.get("external_urls") or {}).get("spotify"),
            playable=(t.get("is_playable", True) is not False and not t.get("is_local")
                      and not self.is_known_unavailable(t["id"])),
            raw={**t, "artist_id": next((a.get("id") for a in t.get("artists") or [] if a.get("id")), None),
                 "album_id": (t.get("album") or {}).get("id")},
        )

    def _tracks(self, items, key=None) -> list[Track]:
        return _uniq(self._track(i.get(key) if key else i) for i in items or [])

    def _load(self, force: bool = False) -> dict:
        if self._cache and not force and time.time() - self._cache_ts < CACHE_TTL:
            return self._cache
        errors: list[ServiceError] = []

        def part(path, params, key=None):
            try:
                return self._tracks(self._get(path, params).get("items"), key)
            except AuthError:
                raise
            except ServiceError as exc:
                errors.append(exc)
                return []

        liked = part("/me/tracks", {"limit": 50, "market": "from_token"}, "track")
        top = part("/me/top/tracks", {"limit": 50, "time_range": "short_term"})
        recent = part("/me/player/recently-played", {"limit": 50}, "track")
        if len(errors) == 3:
            raise errors[0]
        self._cache = {"liked": liked, "top": top, "recent": recent}
        self._cache_ts = time.time()
        return self._cache

    def home_sections(self, force: bool = False) -> list[Section]:
        data = self._load(force)
        sections = [
            Section("top", "Ваш топ за месяц", data["top"]),
            Section("liked", "Мне нравится", data["liked"]),
            Section("recent", "Вы недавно слушали", data["recent"]),
        ]
        return [s for s in sections if s.tracks]

    def wave(self) -> list[Track]:
        # Рекомендации Spotify закрыл для новых приложений: волна из топа, лайков и истории.
        data = self._load()
        rows = zip_longest(data["top"], data["liked"], data["recent"])
        pool = _uniq(t for row in rows for t in row if t and t.playable)
        random.shuffle(pool)
        return pool

    def search(self, query: str) -> list[Track]:
        found = []
        for offset in range(0, 30, SEARCH_PAGE):
            data = self._get("/search", {"q": query, "type": "track", "limit": SEARCH_PAGE,
                                         "offset": offset, "market": "from_token"})
            page = self._tracks((data.get("tracks") or {}).get("items"))
            found += page
            if len(page) < SEARCH_PAGE:
                break
        return _uniq(found)

    # ---------- плейлисты ----------

    def playlists(self) -> list[Playlist]:
        me = (self.settings.get("account") or {}).get("id")
        out, offset = [], 0
        while offset < 200:
            data = self._get("/me/playlists", {"limit": 50, "offset": offset})
            for p in data.get("items") or []:
                if not p or not p.get("id"):
                    continue
                # С 2026 года содержимое отдаётся только для своих и совместных плейлистов
                if (p.get("owner") or {}).get("id") != me and not p.get("collaborative"):
                    continue
                images = p.get("images") or []
                total = (p.get("items") or p.get("tracks") or {}).get("total")
                out.append(Playlist(id=p["id"], title=p.get("name") or "Без названия",
                                    cover_url=images[0].get("url") if images else None, count=total,
                                    service_id=self.id, owner=(p.get("owner") or {}).get("display_name", ""),
                                    raw={"id": p["id"]}))
            if not data.get("next"):
                break
            offset += 50
        return out

    def playlist_tracks(self, playlist: Playlist) -> list[Track]:
        out, offset = [], 0
        while offset < 1000:
            data = self._get(f"/playlists/{playlist.id}/items",
                             {"limit": 50, "offset": offset, "market": "from_token"})
            for entry in data.get("items") or []:
                # поле переименовали: было track, стало item
                out.append(self._track((entry or {}).get("item") or (entry or {}).get("track")))
            if not data.get("next"):
                break
            offset += 50
        return _uniq(out)

    # ---------- исполнители и альбомы ----------
    # Редакционные подборки Spotify (Top 50 и т. п.) приложениям в режиме разработки недоступны:
    # их нельзя ни найти, ни прочитать — featured_playlists() остаётся пустым.

    @staticmethod
    def _image(images, minimum: int = 200) -> str | None:
        images = images or []
        best = min((i for i in images if (i.get("width") or 0) >= minimum),
                   key=lambda i: i.get("width") or 0, default=images[0] if images else None)
        return best.get("url") if best else None

    def _album_obj(self, a: dict) -> Album | None:
        if not a or not a.get("id"):
            return None
        kinds = {"album": "Альбом", "single": "Сингл", "compilation": "Сборник"}
        artists = a.get("artists") or []
        return Album(a["id"], a.get("name") or "Без названия", self._image(a.get("images")), self.id,
                     artist=", ".join(x.get("name", "") for x in artists),
                     artist_id=artists[0].get("id") if artists else None,
                     date=a.get("release_date") or "", kind=kinds.get(a.get("album_type") or "", "Альбом"))

    def find_artist(self, name: str) -> Artist | None:
        data = self._get("/search", {"q": name, "type": "artist", "limit": 5})
        for a in (data.get("artists") or {}).get("items") or []:
            if a.get("id") and same_artist(name, a.get("name") or ""):
                return Artist(a["id"], a["name"], self._image(a.get("images")), self.id)
        return None

    def library_artists(self) -> list[Artist]:
        data = self._get("/me/following", {"type": "artist", "limit": 50})
        return [Artist(a["id"], a.get("name") or "", self._image(a.get("images")), self.id)
                for a in (data.get("artists") or {}).get("items") or [] if a.get("id")]

    def library_albums(self) -> list[Album]:
        data = self._get("/me/albums", {"limit": 50, "market": "from_token"})
        return [a for a in (self._album_obj((i or {}).get("album")) for i in data.get("items") or []) if a]

    def artist_info(self, artist_id: str) -> ArtistInfo:
        a = self._get(f"/artists/{artist_id}")
        artist = Artist(artist_id, a.get("name") or "", self._image(a.get("images"), 300), self.id)

        def optional(fn, default):
            try:
                return fn()
            except AuthError:
                raise
            except ServiceError:   # часть разделов Spotify закрыл для режима разработки
                return default

        albums = optional(lambda: [x for x in (self._album_obj(i) for i in self._get(
            f"/artists/{artist_id}/albums", {"include_groups": "album,single", "limit": 20,
                                              "market": "from_token"}).get("items") or []) if x], [])
        top = optional(lambda: self._tracks(self._get(f"/artists/{artist_id}/top-tracks",
                                                      {"market": "from_token"}).get("tracks"))[:10], [])
        albums.sort(key=lambda x: x.date, reverse=True)
        genres = ", ".join(a.get("genres") or [])
        return ArtistInfo(artist, f"Жанры: {genres}" if genres else "", albums, top)

    def album_tracks(self, album: Album) -> list[Track]:
        data = self._get(f"/albums/{album.id}", {"market": "from_token"})
        out = []
        for t in (data.get("tracks") or {}).get("items") or []:
            t = {**t, "album": {"id": album.id, "images": data.get("images") or []}}
            out.append(self._track(t))
        return _uniq(out)

    # ---------- звук и клипы через YouTube ----------

    def _youtube_id(self, track: Track) -> str:
        isrc = (track.raw.get("external_ids") or {}).get("isrc")
        first_artist = (track.raw.get("artists") or [{}])[0].get("name", track.artist)
        return youtube_match.find_video_id(track.title, first_artist, track.duration_ms, isrc)

    def stream_url(self, track: Track) -> str:
        vid = self._youtube_id(track)
        return extract_stream(f"https://music.youtube.com/watch?v={vid}", AUDIO_FORMAT)

    def video_stream(self, track: Track) -> tuple[str, str]:
        clip = youtube_match.find_clip_id(self._youtube_id(track))
        page = f"https://www.youtube.com/watch?v={clip}"
        return extract_stream(page, VIDEO_FORMAT), page
