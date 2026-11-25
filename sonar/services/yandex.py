"""Яндекс Музыка через неофициальную библиотеку yandex-music (MarshalX).

Вход: OAuth-токен Яндекса. Встроенное окно открывает вход в Яндекс и перехватывает
токен из адреса редиректа (music.yandex.ru/#access_token=…). Можно вставить токен вручную.
Звук — прямые ссылки на файлы с серверов Яндекса; полные треки — с подпиской Плюс.
"""
import random
import threading
import time
from urllib.parse import parse_qs

from .base import same_artist
from .base import (Album, Artist, ArtistInfo, AuthError, BrowserLogin, CredentialField, MusicService,
                   Playlist, Section,
                   ServiceError, TemporaryError, Track, UnavailableError)

# client_id приложения Яндекс Музыки: так токен получают все сторонние клиенты библиотеки
OAUTH_URL = ("https://oauth.yandex.ru/authorize?response_type=token"
             "&client_id=23cabbbdc6cd418abb4b39c32c41195d")
REDIRECT_PREFIX = "https://music.yandex.ru/#access_token"
WAVE = "user:onyourwave"   # «Моя волна» Яндекса
CACHE_TTL = 300


def _uniq(tracks):
    seen, out = set(), []
    for t in tracks:
        if t and t.id not in seen:
            seen.add(t.id)
            out.append(t)
    return out


def _cover(uri: str | None, size: str = "400x400") -> str | None:
    if not uri:
        return None
    return "https://" + uri.replace("%%", size)


class YandexMusic(MusicService):
    id = "yandex"
    name = "Яндекс Музыка"
    name_from = "Яндекс Музыки"
    name_in = "Яндекс Музыке"
    description = "Моя волна, лайки, плейлисты и поиск"
    icon_letters = "Я"
    icon_color = "#ffcc00"
    download_before_play = True   # прямые mp3 Яндекса при долгом чтении обрываются сервером
    browser_login = BrowserLogin(OAUTH_URL, "yandex.ru", "", "redirect", redirect_prefix=REDIRECT_PREFIX)
    help_text = (
        "«Войти» откроет вход в Яндекс; после него окно закроется само.\n"
        "Если не получается, вставьте OAuth-токен вручную (его выдаёт та же страница входа: "
        "после входа он в адресной строке после access_token=).\n"
        "Полные треки играют с подпиской Плюс, без неё — только фрагменты."
    )
    credential_fields = [CredentialField("token", "OAuth-токен", secret=True, placeholder="y0_…")]

    def __init__(self, settings=None):
        super().__init__(settings)
        self._client = None
        self._lock = threading.Lock()
        self._cache: dict | None = None
        self._cache_ts = 0.0

    # ---------- клиент ----------

    @staticmethod
    def _wrap(exc: Exception) -> ServiceError:
        from yandex_music.exceptions import NetworkError, NotFoundError, TimedOutError, UnauthorizedError
        if isinstance(exc, ServiceError):
            return exc
        if isinstance(exc, UnauthorizedError):
            return AuthError("Яндекс не принял токен. Войдите заново в Настройках → Интеграция.")
        if isinstance(exc, (NetworkError, TimedOutError)):
            return TemporaryError("Нет связи с Яндекс Музыкой.")
        if isinstance(exc, NotFoundError):
            return UnavailableError("Не найдено в Яндекс Музыке.")
        return ServiceError(f"Яндекс Музыка: {str(exc)[:200]}")

    @staticmethod
    def _make_client(token: str):
        from yandex_music import Client
        import logging
        logging.getLogger("yandex_music").setLevel(logging.ERROR)
        return Client(token, report_unknown_fields=False).init()

    def _yc(self):
        with self._lock:
            if self._client is None:
                try:
                    self._client = self._make_client(self.settings["token"])
                except Exception as exc:
                    raise self._wrap(exc) from exc
            return self._client

    def _call(self, fn):
        try:
            return fn(self._yc())
        except Exception as exc:
            raise self._wrap(exc) from exc

    # ---------- вход ----------

    def connect(self, credentials: dict) -> dict:
        token = (credentials.get("token") or "").strip()
        redirect = credentials.get("redirect") or ""
        if redirect and "#" in redirect:
            token = parse_qs(redirect.split("#", 1)[1]).get("access_token", [""])[0]
        if not token:
            raise AuthError("Войдите через Яндекс или вставьте OAuth-токен.")
        try:
            client = self._make_client(token)
            account = client.me.account if client.me else None
        except Exception as exc:
            raise self._wrap(exc) from exc
        self._client = client
        name = ((account.display_name or account.login) if account else None) or "аккаунт"
        self.settings.update(connected=True, token=token, account={"name": name})
        return self.settings

    # ---------- данные ----------

    def _track(self, t) -> Track | None:
        if t is None or not getattr(t, "id", None) or not t.title:
            return None
        album_id = t.albums[0].id if t.albums else None
        full_id = f"{t.id}:{album_id}" if album_id else str(t.id)
        artists = ", ".join(a.name for a in (t.artists or []) if a.name)
        return Track(
            id=str(t.id), title=t.title + (f" ({t.version})" if getattr(t, "version", None) else ""),
            artist=artists, duration_ms=int(t.duration_ms or 0),
            artwork_url=_cover(t.cover_uri or t.og_image), service_id=self.id,
            permalink=f"https://music.yandex.ru/album/{album_id}/track/{t.id}" if album_id else None,
            playable=t.available is not False and not self.is_known_unavailable(str(t.id)),
            raw={"ym_id": full_id, "artist_id": str(t.artists[0].id) if t.artists and t.artists[0].id else None,
                 "album_id": str(album_id) if album_id else None},
        )

    def _wave_tracks(self, batches: int = 3) -> list[Track]:
        """Несколько порций «Моей волны»: каждая следующая продолжает предыдущую."""
        out, queue = [], None
        for _ in range(batches):
            result = self._call(lambda c, q=queue: c.rotor_station_tracks(WAVE, queue=q))
            seq = [item.track for item in (result.sequence if result else []) if item.track]
            if not seq:
                break
            out += [self._track(t) for t in seq]
            queue = seq[-1].id
        return _uniq(out)

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

        likes = part(lambda: _uniq(self._track(t) for t in
                                   self._call(lambda c: c.users_likes_tracks().fetch_tracks()[:100])))
        wave = part(self._wave_tracks)
        if len(errors) == 2:
            raise errors[0]
        self._cache = {"likes": likes, "wave": wave}
        self._cache_ts = time.time()
        return self._cache

    def home_sections(self, force: bool = False) -> list[Section]:
        d = self._load(force)
        sections = [Section("wave", "Моя волна Яндекса", d["wave"]), Section("likes", "Мне нравится", d["likes"])]
        return [s for s in sections if s.tracks]

    def wave(self) -> list[Track]:
        d = self._load()
        pool = [t for t in d["wave"] if t.playable]
        extra = [t for t in d["likes"] if t.playable]
        random.shuffle(extra)
        return _uniq(pool + extra[: max(10, len(pool) // 3)])

    def search(self, query: str) -> list[Track]:
        result = self._call(lambda c: c.search(query, type_="track"))
        items = result.tracks.results if result and result.tracks else []
        return _uniq(self._track(t) for t in items[:30])

    def playlists(self) -> list[Playlist]:
        items = self._call(lambda c: c.users_playlists_list()) or []
        out = []
        for p in items:
            cover = None
            if p.cover and getattr(p.cover, "uri", None):
                cover = _cover(p.cover.uri)
            elif p.og_image:
                cover = _cover(p.og_image)
            out.append(Playlist(id=str(p.kind), title=p.title or "Без названия", cover_url=cover,
                                count=p.track_count, service_id=self.id))
        return out

    def playlist_tracks(self, playlist: Playlist) -> list[Track]:
        def fetch(c):
            if playlist.id == "chart":
                return [item.track for item in (c.chart().chart.tracks or []) if item.track]
            if ":" in playlist.id:   # чужой плейлист (подборка Яндекса): «uid:kind»
                uid, kind = playlist.id.split(":", 1)
                pl = c.users_playlists(kind, user_id=uid)
            else:
                pl = c.users_playlists(playlist.id)
            return [ts.track or ts.fetch_track() for ts in (pl.tracks or pl.fetch_tracks())]
        return _uniq(self._track(t) for t in self._call(fetch))

    # ---------- подборки, исполнители, альбомы ----------

    def featured_playlists(self) -> list[Playlist]:
        """«Плейлист дня», «Премьера», «Тайник», «Дежавю» и чарт Яндекса."""
        out = []
        feed = self._call(lambda c: c.feed())
        for gp in (feed.generated_playlists if feed else None) or []:
            pl = gp.data
            if pl is None or pl.kind is None:
                continue
            uid = pl.owner.uid if pl.owner else pl.uid
            cover = _cover(pl.cover.uri) if pl.cover and getattr(pl.cover, "uri", None) else _cover(pl.og_image)
            out.append(Playlist(f"{uid}:{pl.kind}", pl.title or "Подборка", cover, pl.track_count, self.id,
                                owner="Яндекс Музыка"))
        try:
            chart = self._call(lambda c: c.chart())
            if chart and chart.chart:
                out.append(Playlist("chart", chart.title or "Чарт", _cover(chart.chart.og_image) or None,
                                    len(chart.chart.tracks or []), self.id, owner="Яндекс Музыка"))
        except (AuthError, TemporaryError):
            raise
        except ServiceError:
            pass
        return out

    def _artist_obj(self, a) -> Artist | None:
        if a is None or not getattr(a, "id", None):
            return None
        cover = _cover(a.cover.uri) if getattr(a, "cover", None) and getattr(a.cover, "uri", None) else _cover(a.og_image)
        return Artist(str(a.id), a.name or "", cover, self.id)

    def _album_obj(self, a) -> Album | None:
        if a is None or not getattr(a, "id", None):
            return None
        kinds = {"single": "Сингл", "compilation": "Сборник", "podcast": "Подкаст"}
        first = (a.artists or [None])[0]
        return Album(str(a.id), a.title or "Без названия", _cover(a.cover_uri), self.id,
                     artist=", ".join(x.name for x in (a.artists or []) if x.name),
                     artist_id=str(first.id) if first is not None and first.id else None,
                     date=(a.release_date or "")[:10] or str(a.year or ""), kind=kinds.get(a.type or "", "Альбом"))

    def find_artist(self, name: str) -> Artist | None:
        result = self._call(lambda c: c.search(name, type_="artist"))
        for a in ((result.artists.results if result and result.artists else None) or [])[:5]:
            if same_artist(name, a.name or ""):
                return self._artist_obj(a)
        return None

    def library_artists(self) -> list[Artist]:
        likes = self._call(lambda c: c.users_likes_artists()) or []
        return [x for x in (self._artist_obj(like.artist) for like in likes) if x]

    def library_albums(self) -> list[Album]:
        likes = self._call(lambda c: c.users_likes_albums()) or []
        return [x for x in (self._album_obj(like.album) for like in likes) if x]

    def artist_info(self, artist_id: str) -> ArtistInfo:
        info = self._call(lambda c: c.artists_brief_info(artist_id))
        if info is None or info.artist is None:
            raise UnavailableError("Исполнитель не найден в Яндекс Музыке.")
        artist = self._artist_obj(info.artist)
        desc = info.artist.description
        text = (getattr(desc, "text", None) or (desc if isinstance(desc, str) else "") or "").strip()
        albums = [x for x in (self._album_obj(a) for a in (info.albums or [])) if x]
        albums.sort(key=lambda x: x.date, reverse=True)
        top = _uniq(self._track(t) for t in (info.popular_tracks or []))[:10]
        return ArtistInfo(artist, text, albums, top)

    def album_tracks(self, album: Album) -> list[Track]:
        full = self._call(lambda c: c.albums_with_tracks(album.id))
        tracks = [t for volume in ((full.volumes if full else None) or []) for t in volume]
        return _uniq(self._track(t) for t in tracks)

    def stream_url(self, track: Track) -> str:
        infos = self._call(lambda c: c.tracks_download_info(track.raw.get("ym_id") or track.id,
                                                            get_direct_links=True))
        full = [i for i in infos or [] if not i.preview and i.direct_link]
        if not full:
            raise UnavailableError("Полностью этот трек доступен только с подпиской Плюс.")
        # лучший mp3, иначе лучший из остального
        best = max(full, key=lambda i: (i.codec == "mp3", i.bitrate_in_kbps or 0))
        return best.direct_link
