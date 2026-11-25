"""YouTube Music: библиотека и подборки через ytmusicapi, потоки через yt-dlp.

Авторизация: cookie аккаунта Google (встроенный браузер) или заголовки запроса,
скопированные из DevTools. Для извлечения потоков yt-dlp нужен Deno.
"""
import random
import re
import shutil
import sys
import threading
import time
from itertools import zip_longest
from pathlib import Path

import requests

from .base import same_artist
from .base import (Album, Artist, ArtistInfo, AuthError, BrowserLogin, CredentialField, MusicService,
                   Playlist, Section,
                   ServiceError,
                   TemporaryError, Track, UnavailableError)

FIREFOX_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:132.0) Gecko/20100101 Firefox/132.0"
LOGIN_URL = ("https://accounts.google.com/ServiceLogin?service=youtube"
             "&continue=https%3A%2F%2Fmusic.youtube.com%2F")
PARSE_ERRORS = (ValueError, KeyError, IndexError, TypeError, AttributeError)
VIDEO_TYPES = {"MUSIC_VIDEO_TYPE_OMV", "MUSIC_VIDEO_TYPE_UGC"}
AUDIO_FORMAT = "bestaudio[ext=m4a]/bestaudio/best"
VIDEO_FORMAT = ("best[vcodec!=none][acodec!=none][height<=1080]"
                "/best[vcodec!=none][acodec!=none]")
CACHE_TTL = 300
# Ошибки yt-dlp, которые означают «этот ролик здесь не послушать», а не сбой
UNAVAILABLE_MARKERS = ("video unavailable", "not available in your country", "private video",
                       "members-only", "confirm your age", "premium", "has been removed",
                       "blocked it in your country", "not made this video available")
DENO_HINT = ("Для YouTube нужен Deno: выполните в PowerShell «winget install DenoLand.Deno» "
             "и перезапустите приложение.")


def _uniq(tracks):
    seen, out = set(), []
    for t in tracks:
        if t and t.id not in seen:
            seen.add(t.id)
            out.append(t)
    return out


def _seconds(text) -> int:
    if not text:
        return 0
    try:
        total = 0
        for part in str(text).split(":"):
            total = total * 60 + int(part)
        return total
    except ValueError:
        return 0


def _best_thumb(thumbs) -> str | None:
    if not thumbs:
        return None
    url = max(thumbs, key=lambda t: t.get("width") or 0).get("url")
    if url and ("googleusercontent.com" in url or "ggpht.com" in url):
        url = re.sub(r"=w\d+-h\d+", "=w320-h320", url)
    return url


def find_deno() -> str | None:
    """Deno из PATH, рядом с программой или из стандартной папки установки."""
    found = shutil.which("deno")
    if found:
        return found
    exe = "deno.exe" if sys.platform == "win32" else "deno"
    candidates = [
        Path(sys.executable).parent / exe,                   # рядом с собранным exe
        Path(__file__).resolve().parents[2] / "bin" / exe,  # bin/ в папке проекта
        Path.home() / ".deno" / "bin" / exe,                 # install.ps1 / install.sh
    ]
    return next((str(p) for p in candidates if p.is_file()), None)


class _SilentLogger:
    """yt-dlp печатает ошибки в консоль даже с quiet; нам они нужны только в исключении."""
    def debug(self, msg): pass
    def info(self, msg): pass
    def warning(self, msg): pass
    def error(self, msg): pass


class YouTubeMusic(MusicService):
    id = "ytmusic"
    name = "YouTube Music"
    description = "Лайки, история, подборки и клипы"
    icon_letters = "YM"
    icon_color = "#d93a3a"
    supports_video = True
    browser_login = BrowserLogin(LOGIN_URL, "youtube.com", "__Secure-3PAPISID", "cookie",
                                 collect_all=True, user_agent=FIREFOX_UA)
    help_text = (
        "Если Google не пускает во встроенное окно:\n"
        "1. Откройте music.youtube.com в обычном браузере и войдите.\n"
        "2. F12 → «Network» («Сеть»), обновите страницу, выберите любой запрос browse.\n"
        "3. Скопируйте его Request Headers целиком (в Firefox: правый клик → "
        "Копировать → Заголовки запроса) и вставьте ниже."
    )
    credential_fields = [
        CredentialField("headers", "Заголовки запроса", multiline=True,
                        placeholder="cookie: …\nx-goog-authuser: 0\n…"),
    ]

    def __init__(self, settings=None):
        super().__init__(settings)
        self._lock = threading.Lock()
        self._clients: dict = {}
        self._cache: dict | None = None
        self._cache_ts = 0.0

    # ---------- клиент ----------

    @staticmethod
    def _wrap(exc: Exception) -> ServiceError:
        if isinstance(exc, ServiceError):
            return exc
        if isinstance(exc, requests.RequestException):
            return TemporaryError("Нет связи с YouTube Music.")
        if isinstance(exc, PARSE_ERRORS):
            return ServiceError(f"Не удалось разобрать ответ YouTube Music ({exc.__class__.__name__}: {exc})")
        text = str(exc)
        if exc.__class__.__name__ == "YTMusicUserError" or " 401" in text or " 403" in text:
            return AuthError("YouTube Music не принял данные входа. "
                             "Войдите заново в Настройках → Интеграция.")
        return ServiceError(text[:200])

    @staticmethod
    def _make_client(headers: dict, language: str = "ru"):
        from ytmusicapi import YTMusic
        return YTMusic(auth=headers, language=language)

    def _client(self, language: str):
        with self._lock:
            if language not in self._clients:
                try:
                    self._clients[language] = self._make_client(self.settings["headers"], language)
                except Exception as exc:
                    raise self._wrap(exc) from exc
            return self._clients[language]

    def _call(self, method: str, *args, language: str = "ru", _fallback: bool = True, **kwargs):
        """Вызов ytmusicapi. Парсер библиотеки иногда ломается на одной из локализаций
        (на русской счётчики приходят словами вместо цифр), тогда пробуем другую."""
        try:
            return getattr(self._client(language), method)(*args, **kwargs)
        except PARSE_ERRORS as exc:
            if _fallback:
                other = "ru" if language == "en" else "en"
                return self._call(method, *args, language=other, _fallback=False, **kwargs)
            raise self._wrap(exc) from exc
        except Exception as exc:
            raise self._wrap(exc) from exc

    # ---------- авторизация ----------

    @staticmethod
    def _headers_from_cookie(cookie: str) -> dict:
        from ytmusicapi.helpers import initialize_headers
        if "__Secure-3PAPISID=" not in cookie:
            raise AuthError("В cookie нет __Secure-3PAPISID. Войдите в аккаунт ещё раз.")
        headers = dict(initialize_headers())
        # authorization пересчитывается библиотекой на каждый запрос, здесь только маркер типа
        headers.update({"cookie": cookie, "x-goog-authuser": "0",
                        "authorization": "SAPISIDHASH 0_0"})
        return headers

    def _headers_from_raw(self, raw: str) -> dict:
        import json
        from ytmusicapi import setup
        if "__Secure-3PAPISID=" in raw and not re.search(r"(?im)^\s*cookie\s*:", raw):
            return self._headers_from_cookie(raw.strip())  # вставили голую строку cookie
        try:
            headers = json.loads(setup(headers_raw=raw))
        except Exception as exc:
            raise AuthError(f"Не удалось разобрать заголовки: {exc}") from exc
        if "SAPISIDHASH" not in headers.get("authorization", ""):
            headers["authorization"] = "SAPISIDHASH 0_0"
        return headers

    def connect(self, credentials: dict) -> dict:
        if credentials.get("cookie"):
            headers = self._headers_from_cookie(credentials["cookie"])
        elif (credentials.get("headers") or "").strip():
            headers = self._headers_from_raw(credentials["headers"])
        else:
            raise AuthError("Войдите через браузер или вставьте заголовки запроса.")
        try:
            client = self._make_client(headers, "ru")
            info = client.get_account_info()
        except Exception as exc:
            raise self._wrap(exc) from exc
        self._clients = {"ru": client}
        self.settings.update(
            connected=True,
            headers=headers,
            account={"name": info.get("accountName") or info.get("channelHandle") or "аккаунт"},
        )
        return self.settings

    # ---------- данные ----------

    def _track(self, item: dict | None) -> Track | None:
        if not item or not item.get("videoId") or not item.get("title"):
            return None
        artists = ", ".join(a["name"] for a in item.get("artists") or [] if a.get("name"))
        seconds = item.get("duration_seconds") or _seconds(item.get("length") or item.get("duration"))
        vid = item["videoId"]
        return Track(
            id=vid,
            title=item["title"],
            artist=artists,
            duration_ms=int(seconds) * 1000,
            artwork_url=_best_thumb(item.get("thumbnails") or item.get("thumbnail")),
            service_id=self.id,
            permalink=f"https://music.youtube.com/watch?v={vid}",
            playable=item.get("isAvailable", True) is not False and not self.is_known_unavailable(vid),
            raw={**item, "artist_id": next((a.get("id") for a in item.get("artists") or [] if a.get("id")), None),
                 "album_id": (item.get("album") or {}).get("id")},
        )

    def _tracks(self, items) -> list[Track]:
        return _uniq(self._track(i) for i in items or [])

    def _radio(self, seed: Track) -> list[Track]:
        try:
            data = self._call("get_watch_playlist", videoId=seed.id, radio=True, limit=40)
        except AuthError:
            raise
        except ServiceError:
            return []
        return self._tracks(data.get("tracks"))[1:]  # первый трек радио это сам seed

    def _load(self, force: bool = False) -> dict:
        if self._cache and not force and time.time() - self._cache_ts < CACHE_TTL:
            return self._cache
        errors: list[ServiceError] = []

        def safe(fn, default):
            try:
                return fn()
            except AuthError:
                raise
            except ServiceError as exc:
                errors.append(exc)
                return default

        # Библиотеку берём на английском: на русском парсер плейлиста «Мне нравится» падает.
        liked = safe(lambda: self._tracks(
            self._call("get_liked_songs", limit=100, language="en").get("tracks")), [])
        history = safe(lambda: self._tracks(self._call("get_history", language="en"))[:40], [])
        home = safe(lambda: self._call("get_home", limit=8), [])  # русские названия полок
        if len(errors) == 3:
            raise errors[0]
        shelves, featured = [], []
        for shelf in home:   # плейлисты с главной YouTube Music — это и есть подборки сервиса
            for item in shelf.get("contents") or []:
                if item and item.get("playlistId") and not item.get("videoId"):
                    featured.append(Playlist(item["playlistId"], item.get("title") or "Подборка",
                                             _best_thumb(item.get("thumbnails")), None, self.id,
                                             owner=shelf.get("title") or ""))
        for n, shelf in enumerate(home):
            tracks = self._tracks(shelf.get("contents"))
            if len(tracks) >= 4:  # полки из одних плейлистов/альбомов пропускаем
                shelves.append(Section(f"home-{n}", shelf.get("title") or "Для вас", tracks))

        seeds = _uniq(history[:3] + liked[:3])[:3]
        radios = [self._radio(s) for s in seeds]
        known = {t.id for t in liked}
        wave = []
        for row in zip_longest(*radios):
            for t in row:
                if t and t.playable and t.id not in known:
                    known.add(t.id)
                    wave.append(t)
        if not wave:  # пустая история и лайки: берём треки с полок главной
            wave = _uniq(t for s in shelves for t in s.tracks if t.playable)

        seen_pl, uniq_featured = set(), []
        for pl in featured:
            if pl.id not in seen_pl:
                seen_pl.add(pl.id)
                uniq_featured.append(pl)
        self._cache = {"liked": liked, "history": history, "shelves": shelves, "wave": wave,
                       "featured": uniq_featured}
        self._cache_ts = time.time()
        return self._cache

    def home_sections(self, force: bool = False) -> list[Section]:
        data = self._load(force)
        sections = list(data["shelves"])
        if data["liked"]:
            sections.append(Section("liked", "Мне нравится", data["liked"]))
        if data["history"]:
            sections.append(Section("history", "Вы недавно слушали", data["history"]))
        return sections

    def wave(self) -> list[Track]:
        data = self._load()
        pool = list(data["wave"])
        liked = [t for t in data["liked"] if t.playable]
        random.shuffle(liked)
        pool += liked[: max(10, len(pool) // 3)]
        random.shuffle(pool)
        return _uniq(pool)

    # ---------- потоки ----------

    @staticmethod
    def _extract(url: str, fmt: str) -> str:
        return extract_stream(url, fmt)

    def playlists(self) -> list[Playlist]:
        # Разбор плейлистов в ytmusicapi надёжнее на английском (счётчики приходят цифрами)
        items = self._call("get_library_playlists", limit=100, language="en")
        out = []
        for p in items or []:
            if not p.get("playlistId"):
                continue
            count = p.get("count")
            try:
                count = int(str(count).replace(",", "").split()[0]) if count else None
            except ValueError:
                count = None
            out.append(Playlist(id=p["playlistId"], title=p.get("title") or "Без названия",
                                cover_url=_best_thumb(p.get("thumbnails")), count=count,
                                service_id=self.id, raw=p))
        return out

    def playlist_tracks(self, playlist: Playlist) -> list[Track]:
        pid = playlist.id[2:] if playlist.id.startswith("VL") else playlist.id
        try:
            data = self._call("get_playlist", pid, limit=500, language="en")
            return self._tracks(data.get("tracks"))
        except (AuthError, TemporaryError):
            raise
        except ServiceError:
            if not pid.startswith("RD"):
                raise
        # «Миксы» (RD…) — это радио: треки отдаёт не плейлист, а очередь воспроизведения
        data = self._call("get_watch_playlist", playlistId=pid, limit=60)
        return self._tracks(data.get("tracks"))

    def featured_playlists(self) -> list[Playlist]:
        return list(self._load().get("featured", []))

    def _album_obj(self, a: dict, kind: str = "Альбом") -> Album | None:
        bid = a.get("browseId") or a.get("audioPlaylistId")
        if not bid:
            return None
        artists = a.get("artists") or []
        kinds = {"Album": "Альбом", "Single": "Сингл", "EP": "EP"}
        return Album(bid, a.get("title") or "Без названия", _best_thumb(a.get("thumbnails")), self.id,
                     artist=", ".join(x.get("name", "") for x in artists if isinstance(x, dict)),
                     artist_id=next((x.get("id") for x in artists if isinstance(x, dict) and x.get("id")), None),
                     date=str(a.get("year") or ""), kind=kinds.get(a.get("type") or "", kind))

    def find_artist(self, name: str) -> Artist | None:
        for a in (self._call("search", name, filter="artists", limit=5) or [])[:5]:
            title = a.get("artist") or a.get("title") or ""
            if a.get("browseId") and same_artist(name, title):
                return Artist(a["browseId"], title, _best_thumb(a.get("thumbnails")), self.id)
        return None

    def library_artists(self) -> list[Artist]:
        items = self._call("get_library_subscriptions", limit=100, language="en") or []
        return [Artist(a["browseId"], a.get("artist") or a.get("title") or "", _best_thumb(a.get("thumbnails")),
                       self.id) for a in items if a.get("browseId")]

    def library_albums(self) -> list[Album]:
        items = self._call("get_library_albums", limit=100, language="en") or []
        return [a for a in (self._album_obj(x) for x in items) if a]

    def artist_info(self, artist_id: str) -> ArtistInfo:
        data = self._call("get_artist", artist_id)   # на русском: описание на языке интерфейса
        artist = Artist(artist_id, data.get("name") or "", _best_thumb(data.get("thumbnails")), self.id)
        albums = []
        for key, kind in (("albums", "Альбом"), ("singles", "Сингл")):
            for a in (data.get(key) or {}).get("results") or []:
                album = self._album_obj(a, kind)
                if album:
                    album.artist, album.artist_id = album.artist or artist.name, album.artist_id or artist_id
                    albums.append(album)
        albums.sort(key=lambda a: a.date, reverse=True)
        top = self._tracks((data.get("songs") or {}).get("results"))[:10]
        return ArtistInfo(artist, (data.get("description") or "").strip(), albums, top)

    def album_tracks(self, album: Album) -> list[Track]:
        data = self._call("get_album", album.id, language="en")
        cover = _best_thumb(data.get("thumbnails")) or album.cover
        tracks = self._tracks(data.get("tracks"))
        for t in tracks:   # у треков альбома своих обложек нет — берём обложку альбома
            t.artwork_url = t.artwork_url or cover
        return tracks

    def search(self, query: str) -> list[Track]:
        # Тип результата («песня», «видео») ytmusicapi узнаёт по подписям в ответе YouTube.
        # На русском они расходятся с переводами библиотеки, поэтому ищем на английском.
        songs = self._tracks(self._call("search", query, filter="songs", limit=30, language="en"))
        try:  # клипы тоже ищем: их можно смотреть
            videos = self._tracks(self._call("search", query, filter="videos", limit=10,
                                             language="en"))
        except (AuthError, TemporaryError):
            raise
        except ServiceError:
            videos = []
        if not songs and not videos:  # фильтры не сработали: общий поиск, берём только треки
            items = self._call("search", query, limit=40, language="en")
            songs = self._tracks(i for i in items if i.get("resultType") in ("song", "video"))
        return _uniq(songs + videos)


    def stream_url(self, track: Track) -> str:
        return self._extract(f"https://music.youtube.com/watch?v={track.id}", AUDIO_FORMAT)

    def _video_id(self, track: Track) -> str:
        raw = track.raw
        if raw.get("videoType") in VIDEO_TYPES:
            return track.id
        counterpart = raw.get("counterpart") or {}
        if counterpart.get("videoId"):
            return counterpart["videoId"]
        data = self._call("get_watch_playlist", videoId=track.id, limit=1)
        first = (data.get("tracks") or [{}])[0]
        if first.get("videoType") in VIDEO_TYPES and first.get("videoId"):
            return first["videoId"]
        counterpart = first.get("counterpart") or {}
        if counterpart.get("videoId"):
            return counterpart["videoId"]
        raise UnavailableError("У этого трека нет клипа на YouTube.")

    def video_stream(self, track: Track) -> tuple[str, str]:
        vid = self._video_id(track)
        page = f"https://www.youtube.com/watch?v={vid}"
        return self._extract(page, VIDEO_FORMAT), page


def extract_stream(url: str, fmt: str) -> str:
    import yt_dlp
    opts = {"quiet": True, "no_warnings": True, "noplaylist": True,
            "skip_download": True, "format": fmt, "logger": _SilentLogger()}
    deno = find_deno()
    if deno:
        opts["js_runtimes"] = {"deno": {"path": deno}}
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as exc:
        text = str(exc)
        if "TransportError" in text or "Failed to resolve" in text or "timed out" in text:
            raise TemporaryError("Нет связи с YouTube.") from exc
        message = re.sub(r"^ERROR:\s*(\[[^\]]+\]\s*)?(\S+:\s*)?", "", text).strip()
        message = message.splitlines()[0][:200].rstrip(".")
        lowered = message.lower()
        if any(marker in lowered for marker in UNAVAILABLE_MARKERS):
            raise UnavailableError(message) from exc
        if not deno:
            message = f"{message}. {DENO_HINT}"
        raise ServiceError(message) from exc
    stream = info.get("url")
    if not stream:
        raise UnavailableError("YouTube не отдал подходящий поток.")
    return stream
