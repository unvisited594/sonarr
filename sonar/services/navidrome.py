"""Navidrome (и любой Subsonic-совместимый сервер): избранное, случайное, новое,
плейлисты и поиск. Звук идёт прямым потоком с сервера.

Вход по токену Subsonic: на диске хранятся md5(пароль + соль) и соль, но не сам пароль.
"""
import hashlib
import random
import secrets
import time
from urllib.parse import urlencode

import requests

from .base import same_artist
from .base import (Album, Artist, ArtistInfo, AuthError, CredentialField, MusicService, Playlist, Section,
                   ServiceError,
                   TemporaryError, Track, UnavailableError)

API_VERSION = "1.16.1"
CLIENT = "Sonar"
CACHE_TTL = 300


def _uniq(tracks):
    seen, out = set(), []
    for t in tracks:
        if t and t.id not in seen:
            seen.add(t.id)
            out.append(t)
    return out


def _normalize_url(url: str) -> str:
    url = url.strip().rstrip("/")
    if url and "://" not in url:
        url = "http://" + url
    if url.endswith("/app"):  # частая ошибка: скопировали адрес веб-интерфейса
        url = url[:-4]
    return url


class Navidrome(MusicService):
    id = "navidrome"
    name = "Navidrome"
    description = "Ваш сервер: избранное, случайное, новое, плейлисты"
    icon_letters = "ND"
    icon_color = "#0b84ff"
    help_text = (
        "Подходит Navidrome и другие Subsonic-совместимые серверы.\n"
        "Адрес — тот же, что открываете в браузере, например http://192.168.1.10:4533.\n"
        "Пароль на диске не хранится: сохраняется только токен для входа."
    )
    credential_fields = [
        CredentialField("url", "Адрес сервера", placeholder="http://192.168.1.10:4533"),
        CredentialField("user", "Имя пользователя", placeholder="admin"),
        CredentialField("password", "Пароль", secret=True),
    ]

    def __init__(self, settings=None):
        super().__init__(settings)
        self.http = requests.Session()
        self._cache: dict | None = None
        self._cache_ts = 0.0

    # ---------- Subsonic API ----------

    def _auth(self) -> dict:
        s = self.settings
        return {"u": s["user"], "t": s["token"], "s": s["salt"],
                "v": API_VERSION, "c": CLIENT, "f": "json"}

    def _url(self, endpoint: str, **params) -> str:
        return f"{self.settings['url']}/rest/{endpoint}.view?" + urlencode({**self._auth(), **params})

    def _get(self, endpoint: str, **params) -> dict:
        try:
            resp = self.http.get(f"{self.settings['url']}/rest/{endpoint}.view",
                                 params={**self._auth(), **params}, timeout=20)
        except requests.exceptions.SSLError as exc:
            raise ServiceError("Сервер Navidrome не прошёл проверку сертификата (HTTPS).") from exc
        except requests.RequestException as exc:
            raise TemporaryError("Нет связи с сервером Navidrome.") from exc
        if resp.status_code == 404:
            raise ServiceError("По этому адресу нет Subsonic API. Проверьте адрес сервера.")
        if resp.status_code >= 500:
            raise TemporaryError(f"Сервер Navidrome ответил ошибкой HTTP {resp.status_code}.")
        try:
            body = resp.json()["subsonic-response"]
        except (ValueError, KeyError) as exc:
            raise ServiceError("По этому адресу не Navidrome: ответ не похож на Subsonic API.") from exc
        if body.get("status") != "ok":
            err = body.get("error") or {}
            code, message = err.get("code"), err.get("message") or "неизвестная ошибка"
            if code in (40, 41, 44):  # неверный логин/пароль, токен, нет доступа
                raise AuthError("Navidrome не принял имя пользователя или пароль.")
            if code == 70:
                raise UnavailableError("Не найдено на сервере.")
            raise ServiceError(f"Navidrome: {message}")
        return body

    def connect(self, credentials: dict) -> dict:
        url = _normalize_url(credentials.get("url") or "")
        user = (credentials.get("user") or "").strip()
        password = credentials.get("password") or ""
        if not url or not user or not password:
            raise AuthError("Заполните адрес, имя пользователя и пароль.")
        salt = secrets.token_hex(8)
        self.settings.update(url=url, user=user, salt=salt,
                             token=hashlib.md5((password + salt).encode()).hexdigest())
        self._get("ping")
        self.settings.update(connected=True, account={"name": f"{user} @ {url.split('://', 1)[-1]}"})
        return self.settings

    # ---------- данные ----------

    def _track(self, song: dict | None) -> Track | None:
        if not song or not song.get("id") or song.get("isDir"):
            return None
        cover = song.get("coverArt")
        return Track(
            id=str(song["id"]),
            title=song.get("title") or "Без названия",
            artist=song.get("artist") or song.get("displayArtist") or "",
            duration_ms=int(song.get("duration") or 0) * 1000,
            artwork_url=self._url("getCoverArt", id=cover, size=300) if cover else None,
            service_id=self.id,
            permalink=(f"{self.settings['url']}/app/#/album/{song['albumId']}/show"
                       if song.get("albumId") else None),
            playable=not self.is_known_unavailable(str(song["id"])),
            raw={"albumId": song.get("albumId"), "coverArt": cover, "suffix": song.get("suffix"),
                 "artist_id": song.get("artistId"), "album_id": song.get("albumId")},
        )

    def _tracks(self, songs) -> list[Track]:
        return _uniq(self._track(s) for s in songs or [])

    def _newest(self) -> list[Track]:
        albums = (self._get("getAlbumList2", type="newest", size=6).get("albumList2") or {}).get("album") or []
        out = []
        for album in albums:
            try:
                out += self._tracks((self._get("getAlbum", id=album["id"]).get("album") or {}).get("song"))
            except (AuthError, TemporaryError):
                raise
            except ServiceError:
                continue
        return out[:40]

    def _load(self, force: bool = False) -> dict:
        if self._cache and not force and time.time() - self._cache_ts < CACHE_TTL:
            return self._cache
        errors: list[ServiceError] = []

        def part(fn):
            try:
                return fn()
            except AuthError:
                raise
            except ServiceError as exc:
                errors.append(exc)
                return []

        starred = part(lambda: self._tracks((self._get("getStarred2").get("starred2") or {}).get("song")))
        rnd = part(lambda: self._tracks((self._get("getRandomSongs", size=50).get("randomSongs") or {})
                                        .get("song")))
        newest = part(self._newest)
        if len(errors) == 3:
            raise errors[0]
        self._cache = {"starred": starred, "random": rnd, "newest": newest}
        self._cache_ts = time.time()
        return self._cache

    def home_sections(self, force: bool = False) -> list[Section]:
        d = self._load(force)
        sections = [Section("starred", "Избранное", d["starred"]),
                    Section("newest", "Новое на сервере", d["newest"]),
                    Section("random", "Случайное с сервера", d["random"])]
        return [s for s in sections if s.tracks]

    def wave(self) -> list[Track]:
        d = self._load()
        pool = _uniq(d["random"] + d["starred"])
        random.shuffle(pool)
        return [t for t in pool if t.playable]

    def search(self, query: str) -> list[Track]:
        data = self._get("search3", query=query, songCount=30, artistCount=0, albumCount=0)
        return self._tracks((data.get("searchResult3") or {}).get("song"))

    def playlists(self) -> list[Playlist]:
        items = (self._get("getPlaylists").get("playlists") or {}).get("playlist") or []
        return [Playlist(id=str(p["id"]), title=p.get("name") or "Без названия",
                         cover_url=self._url("getCoverArt", id=p["coverArt"], size=300)
                         if p.get("coverArt") else None,
                         count=p.get("songCount"), service_id=self.id, owner=p.get("owner", ""))
                for p in items if p.get("id")]

    def playlist_tracks(self, playlist: Playlist) -> list[Track]:
        data = self._get("getPlaylist", id=playlist.id)
        return self._tracks((data.get("playlist") or {}).get("entry"))

    def download(self, track: Track, folder) -> dict:
        """Скачивает исходный файл и обложку. Возвращает запись для индекса загрузок.
        Выполняется в фоне; файл пишется во временный .part, чтобы обрыв не оставил битый трек."""
        import re
        from pathlib import Path
        folder = Path(folder)
        (folder / "covers").mkdir(parents=True, exist_ok=True)
        safe = re.sub(r'[\\/:*?"<>|]+', "_", f"{track.artist} - {track.title}").strip(" .")[:150] or track.id
        suffix = (track.raw.get("suffix") or "").strip(".") or "mp3"
        target = folder / f"{safe} [{track.id}].{suffix}"
        part = target.with_suffix(target.suffix + ".part")
        try:
            # download.view отдаёт оригинал; если у пользователя нет права на скачивание — берём поток
            for endpoint in ("download", "stream"):
                with self.http.get(f"{self.settings['url']}/rest/{endpoint}.view",
                                   params={**self._auth(), "id": track.id}, stream=True, timeout=60) as resp:
                    kind = resp.headers.get("content-type", "")
                    if resp.status_code != 200 or "json" in kind or "xml" in kind:
                        continue  # ошибка Subsonic приходит JSON-ом вместо файла
                    with open(part, "wb") as out:
                        for chunk in resp.iter_content(256 * 1024):
                            out.write(chunk)
                    part.replace(target)
                    break
            else:
                raise UnavailableError("Сервер не отдал файл трека.")
        except requests.RequestException as exc:
            part.unlink(missing_ok=True)
            raise TemporaryError("Скачивание прервалось: нет связи с сервером.") from exc
        cover_file = None
        if track.raw.get("coverArt"):
            try:
                resp = self.http.get(f"{self.settings['url']}/rest/getCoverArt.view",
                                     params={**self._auth(), "id": track.raw["coverArt"], "size": 600}, timeout=30)
                if resp.status_code == 200 and resp.headers.get("content-type", "").startswith("image/"):
                    cover_file = folder / "covers" / f"{track.id}.jpg"
                    cover_file.write_bytes(resp.content)
            except requests.RequestException:
                pass  # без обложки трек всё равно играет
        return {"id": track.id, "title": track.title, "artist": track.artist,
                "duration_ms": track.duration_ms, "file": target.name,
                "cover": cover_file.name if cover_file else None, "permalink": track.permalink}

    def _cover_url(self, cover_id, size: int = 300) -> str | None:
        return self._url("getCoverArt", id=cover_id, size=size) if cover_id else None

    def _album_obj(self, a: dict) -> Album | None:
        if not a or not a.get("id"):
            return None
        return Album(str(a["id"]), a.get("name") or a.get("title") or "Без названия", self._cover_url(a.get("coverArt")),
                     self.id, artist=a.get("artist") or "", artist_id=a.get("artistId"),
                     date=str(a.get("year") or ""), kind="Альбом")

    def find_artist(self, name: str) -> Artist | None:
        found = (self._get("search3", query=name, artistCount=5, albumCount=0, songCount=0)
                 .get("searchResult3") or {}).get("artist") or []
        for a in found:
            if a.get("id") and same_artist(name, a.get("name") or ""):
                return Artist(a["id"], a["name"], a.get("artistImageUrl") or self._cover_url(a.get("coverArt")), self.id)
        return None

    def library_artists(self) -> list[Artist]:
        """Избранные исполнители сервера, затем самые «альбомные»."""
        out, seen = [], set()
        starred = (self._get("getStarred2").get("starred2") or {}).get("artist") or []
        everyone = [a for idx in (self._get("getArtists").get("artists") or {}).get("index") or []
                    for a in idx.get("artist") or []]
        everyone.sort(key=lambda a: a.get("albumCount") or 0, reverse=True)
        for a in starred + everyone[:100]:
            if a.get("id") and a["id"] not in seen:
                seen.add(a["id"])
                out.append(Artist(a["id"], a.get("name") or "", a.get("artistImageUrl") or
                                  self._cover_url(a.get("coverArt")), self.id))
        return out

    def library_albums(self) -> list[Album]:
        data = self._get("getAlbumList2", type="newest", size=80)
        return [x for x in (self._album_obj(a) for a in (data.get("albumList2") or {}).get("album") or []) if x]

    def artist_info(self, artist_id: str) -> ArtistInfo:
        import html
        import re as _re
        a = self._get("getArtist", id=artist_id).get("artist") or {}
        try:
            info = self._get("getArtistInfo2", id=artist_id).get("artistInfo2") or {}
        except (AuthError, TemporaryError):
            raise
        except ServiceError:
            info = {}
        bio = _re.sub(r"<a\b[^>]*>.*?</a>", "", info.get("biography") or "", flags=_re.S)   # «Read more on Last.fm»
        bio = html.unescape(_re.sub(r"<[^>]+>", "", bio)).strip()
        image = info.get("largeImageUrl") or a.get("artistImageUrl") or self._cover_url(a.get("coverArt"), 600)
        artist = Artist(artist_id, a.get("name") or "", image, self.id)
        albums = [x for x in (self._album_obj(al) for al in a.get("album") or []) if x]
        albums.sort(key=lambda x: x.date, reverse=True)
        try:
            top = self._tracks((self._get("getTopSongs", artist=artist.name, count=10).get("topSongs") or {})
                               .get("song")) if artist.name else []
        except (AuthError, TemporaryError):
            raise
        except ServiceError:
            top = []
        return ArtistInfo(artist, bio, albums, top)

    def album_tracks(self, album: Album) -> list[Track]:
        return self._tracks((self._get("getAlbum", id=album.id).get("album") or {}).get("song"))

    def stream_url(self, track: Track) -> str:
        # Прямой поток с сервера: QMediaPlayer играет его сам, без промежуточных запросов.
        return self._url("stream", id=track.id)
