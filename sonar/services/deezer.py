"""Deezer через открытый API (api.deezer.com) — без ключей и входа.

Регистрацию новых приложений Deezer давно закрыл, поэтому берём то, что API отдаёт публично:
лайки и плейлисты публичного профиля, чарт и поиск. Потоки Deezer зашифрованы, звук идёт
через тот же трек на YouTube (по ISRC или исполнителю и названию), как у Spotify.
"""
import random
import re
import time

import requests

from . import youtube_match
from .base import same_artist
from .base import (Album, Artist, ArtistInfo, AuthError, CredentialField, MusicService, Playlist, Section,
                   ServiceError,
                   TemporaryError, Track, UnavailableError)
from .youtube_music import AUDIO_FORMAT, VIDEO_FORMAT, extract_stream

API = "https://api.deezer.com"
CACHE_TTL = 300


def _uniq(tracks):
    seen, out = set(), []
    for t in tracks:
        if t and t.id not in seen:
            seen.add(t.id)
            out.append(t)
    return out


def parse_profile(text: str) -> str | None:
    """ID профиля из ссылки (deezer.com/ru/profile/123…) или из самого числа."""
    text = (text or "").strip()
    m = re.search(r"profile/(\d+)", text) or re.fullmatch(r"(\d+)", text)
    return m.group(1) if m else None


class Deezer(MusicService):
    id = "deezer"
    name = "Deezer"
    description = "Лайки и плейлисты профиля, чарт; звук через YouTube"
    icon_letters = "DZ"
    icon_color = "#a238ff"
    supports_video = True
    help_text = (
        "Входа не нужно — нужен ваш публичный профиль:\n"
        "1. На deezer.com откройте свой профиль и скопируйте ссылку из адресной строки "
        "(вида deezer.com/ru/profile/123456789).\n"
        "2. Проверьте, что профиль открыт (Настройки Deezer → Конфиденциальность).\n"
        "Сами треки играют через YouTube: Deezer шифрует свои потоки."
    )
    credential_fields = [CredentialField("profile", "Ссылка на профиль или ID",
                                         placeholder="https://www.deezer.com/ru/profile/123456789")]

    def __init__(self, settings=None):
        super().__init__(settings)
        self.http = requests.Session()
        self._cache: dict | None = None
        self._cache_ts = 0.0

    def _get(self, path: str, **params) -> dict:
        try:
            resp = self.http.get(API + path, params=params, timeout=20)
        except requests.RequestException as exc:
            raise TemporaryError("Нет связи с Deezer.") from exc
        if resp.status_code >= 500:
            raise TemporaryError(f"Deezer ответил ошибкой HTTP {resp.status_code}.")
        try:
            body = resp.json()
        except ValueError as exc:
            raise ServiceError("Deezer вернул неожиданный ответ.") from exc
        err = body.get("error") if isinstance(body, dict) else None
        if err:
            code = err.get("code")
            if code == 4:  # слишком много запросов
                raise TemporaryError("Deezer ограничил частоту запросов. Попробуйте через минуту.")
            if code == 800:
                raise UnavailableError("Не найдено на Deezer.")
            if code in (200, 300):  # нет доступа: профиль закрыт
                raise AuthError("Профиль Deezer закрыт. Откройте его в настройках конфиденциальности Deezer.")
            raise ServiceError(f"Deezer: {err.get('message', 'ошибка')}")
        return body

    def connect(self, credentials: dict) -> dict:
        uid = parse_profile(credentials.get("profile", ""))
        if not uid:
            raise AuthError("Не похоже на ссылку на профиль Deezer. Нужна ссылка вида "
                            "deezer.com/ru/profile/123456789 или просто число.")
        user = self._get(f"/user/{uid}")
        self.settings.update(connected=True, user_id=uid, account={"name": user.get("name") or uid})
        return self.settings

    def _track(self, t: dict | None) -> Track | None:
        if not t or not t.get("id") or t.get("type", "track") != "track":
            return None
        album = t.get("album") or {}
        return Track(
            id=str(t["id"]), title=t.get("title") or "Без названия",
            artist=(t.get("artist") or {}).get("name", ""), duration_ms=int(t.get("duration") or 0) * 1000,
            artwork_url=album.get("cover_medium") or album.get("cover"), service_id=self.id,
            permalink=t.get("link"),
            playable=t.get("readable", True) is not False and not self.is_known_unavailable(str(t["id"])),
            raw={"isrc": t.get("isrc"), "artists": [{"name": (t.get("artist") or {}).get("name", "")}],
                 "artist_id": str((t.get("artist") or {}).get("id")) if (t.get("artist") or {}).get("id") else None,
                 "album_id": str(album.get("id")) if album.get("id") else None},
        )

    def _tracks(self, data) -> list[Track]:
        return _uniq(self._track(t) for t in (data or {}).get("data", []))

    def _load(self, force: bool = False) -> dict:
        if self._cache and not force and time.time() - self._cache_ts < CACHE_TTL:
            return self._cache
        uid = self.settings["user_id"]
        errors: list[ServiceError] = []

        def part(fn):
            try:
                return fn()
            except AuthError:
                raise
            except ServiceError as exc:
                errors.append(exc)
                return []

        likes = part(lambda: self._tracks(self._get(f"/user/{uid}/tracks", limit=100)))
        chart = part(lambda: self._tracks(self._get("/chart/0/tracks", limit=50)))
        if len(errors) == 2:
            raise errors[0]
        self._cache = {"likes": likes, "chart": chart}
        self._cache_ts = time.time()
        return self._cache

    def home_sections(self, force: bool = False) -> list[Section]:
        d = self._load(force)
        sections = [Section("likes", "Мне нравится", d["likes"]), Section("chart", "Чарт Deezer", d["chart"])]
        return [s for s in sections if s.tracks]

    def wave(self) -> list[Track]:
        d = self._load()
        pool = _uniq(d["likes"] + d["chart"][:20])
        random.shuffle(pool)
        return [t for t in pool if t.playable]

    def search(self, query: str) -> list[Track]:
        return self._tracks(self._get("/search", q=query, limit=30))

    def playlists(self) -> list[Playlist]:
        data = self._get(f"/user/{self.settings['user_id']}/playlists", limit=100)
        return [Playlist(id=str(p["id"]), title=p.get("title") or "Без названия",
                         cover_url=p.get("picture_medium"), count=p.get("nb_tracks"), service_id=self.id,
                         owner=(p.get("creator") or {}).get("name", ""))
                for p in data.get("data", []) if p.get("id")]

    def playlist_tracks(self, playlist: Playlist) -> list[Track]:
        return self._tracks(self._get(f"/playlist/{playlist.id}/tracks", limit=300))

    def featured_playlists(self) -> list[Playlist]:
        """Редакционные плейлисты-чарты Deezer — открыты без входа."""
        data = self._get("/chart/0/playlists", limit=20)
        return [Playlist(str(p["id"]), p.get("title") or "Подборка", p.get("picture_medium"), p.get("nb_tracks"),
                         self.id, owner="Deezer") for p in data.get("data", []) if p.get("id")]

    def _album_obj(self, a: dict, artist: dict | None = None) -> Album | None:
        if not a or not a.get("id"):
            return None
        artist = a.get("artist") or artist or {}
        kinds = {"album": "Альбом", "single": "Сингл", "ep": "EP", "compile": "Сборник"}
        return Album(str(a["id"]), a.get("title") or "Без названия", a.get("cover_medium") or a.get("cover"), self.id,
                     artist=artist.get("name", ""), artist_id=str(artist["id"]) if artist.get("id") else None,
                     date=a.get("release_date") or "", kind=kinds.get(a.get("record_type") or "", "Альбом"))

    def find_artist(self, name: str) -> Artist | None:
        for a in self._get("/search/artist", q=name, limit=5).get("data", []):
            if a.get("id") and same_artist(name, a.get("name") or ""):
                return Artist(str(a["id"]), a["name"], a.get("picture_medium"), self.id)
        return None

    def library_artists(self) -> list[Artist]:
        data = self._get(f"/user/{self.settings['user_id']}/artists", limit=100)
        return [Artist(str(a["id"]), a.get("name") or "", a.get("picture_medium"), self.id)
                for a in data.get("data", []) if a.get("id")]

    def library_albums(self) -> list[Album]:
        data = self._get(f"/user/{self.settings['user_id']}/albums", limit=100)
        return [x for x in (self._album_obj(a) for a in data.get("data", [])) if x]

    def artist_info(self, artist_id: str) -> ArtistInfo:
        a = self._get(f"/artist/{artist_id}")
        artist = Artist(artist_id, a.get("name") or "", a.get("picture_xl") or a.get("picture_medium"), self.id)
        albums = [x for x in (self._album_obj(al, a) for al in self._get(f"/artist/{artist_id}/albums", limit=50)
                              .get("data", [])) if x]
        albums.sort(key=lambda x: x.date, reverse=True)
        try:
            top = self._tracks(self._get(f"/artist/{artist_id}/top", limit=10))
        except (AuthError, TemporaryError):
            raise
        except ServiceError:
            top = []
        fans = a.get("nb_fan")
        return ArtistInfo(artist, f"Слушателей на Deezer: {fans:,}".replace(",", " ") if fans else "", albums, top)

    def album_tracks(self, album: Album) -> list[Track]:
        data = self._get(f"/album/{album.id}")
        out = []
        for t in (data.get("tracks") or {}).get("data", []):
            t = {**t, "album": {"id": album.id, "cover_medium": data.get("cover_medium")}}
            out.append(self._track(t))
        return _uniq(out)

    def _youtube_id(self, track: Track) -> str:
        isrc = track.raw.get("isrc")
        if not isrc:  # в списках ISRC нет — берём из карточки трека
            try:
                isrc = self._get(f"/track/{track.id}").get("isrc")
            except ServiceError:
                isrc = None
        return youtube_match.find_video_id(track.title, track.artist, track.duration_ms, isrc)

    def stream_url(self, track: Track) -> str:
        return extract_stream(f"https://music.youtube.com/watch?v={self._youtube_id(track)}", AUDIO_FORMAT)

    def video_stream(self, track: Track) -> tuple[str, str]:
        clip = youtube_match.find_clip_id(self._youtube_id(track))
        page = f"https://www.youtube.com/watch?v={clip}"
        return extract_stream(page, VIDEO_FORMAT), page
