"""Общий интерфейс музыкального сервиса. Новый сервис = новый подкласс MusicService."""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class Track:
    id: str
    title: str
    artist: str
    duration_ms: int
    artwork_url: str | None
    service_id: str
    permalink: str | None = None
    playable: bool = True
    preview: bool = False          # доступен только фрагмент (например, Go+)
    raw: dict = field(default_factory=dict, repr=False)


@dataclass
class Playlist:
    id: str
    title: str
    cover_url: str | None
    count: int | None
    service_id: str
    owner: str = ""
    raw: dict = field(default_factory=dict, repr=False)


@dataclass
class Artist:
    id: str
    name: str
    image: str | None
    service_id: str


@dataclass
class Album:
    id: str
    title: str
    cover: str | None
    service_id: str
    artist: str = ""
    artist_id: str | None = None
    date: str = ""          # «2024-03-15» или «2024»
    kind: str = "Альбом"    # Альбом / Сингл / EP
    raw: dict = field(default_factory=dict, repr=False)

    @property
    def year(self) -> str:
        return self.date[:4] if self.date else ""


@dataclass
class ArtistInfo:
    artist: Artist
    description: str = ""
    albums: list = field(default_factory=list)       # list[Album], новые сверху
    top_tracks: list = field(default_factory=list)   # list[Track]


@dataclass
class Section:
    key: str
    title: str
    tracks: list[Track]


@dataclass
class CredentialField:
    key: str
    label: str
    secret: bool = False
    required: bool = True
    placeholder: str = ""
    multiline: bool = False


@dataclass
class BrowserLogin:
    """Вход через встроенный браузер: открываем url и ждём cookie с данными входа."""
    url: str
    domain: str
    cookie: str         # cookie, появление которой означает успешный вход
    field: str          # ключ в credentials, куда положить результат
    collect_all: bool = False   # отдать все cookie домена строкой "a=1; b=2"
    user_agent: str | None = None
    # OAuth: окно перехватывает переход на этот адрес и отдаёт полный URL редиректа
    redirect_prefix: str | None = None
    extra: dict = field(default_factory=dict)   # добавить в credentials (например, PKCE verifier)


class ServiceError(Exception):
    pass


class AuthError(ServiceError):
    pass


class UnavailableError(ServiceError):
    """Сам трек нельзя послушать: регион, подписка, удалён. Повтор не поможет."""


class TemporaryError(ServiceError):
    """Сбой сети или лимит запросов: трек может заработать позже."""


class MusicService(ABC):
    id: str = ""
    name: str = ""
    description: str = ""
    help_text: str = ""
    credential_fields: list[CredentialField] = []
    browser_login: BrowserLogin | None = None
    supports_video = False
    # падежные формы названия для фраз «из …» и «в …» (у латинских названий совпадают с name)
    name_from: str = ""
    name_in: str = ""
    download_before_play = False   # скачать трек целиком и играть из файла (вместо потока)
    icon_letters = ""        # монограмма для плитки, если нет файла assets/<id>.png
    icon_color = "#3a3a3a"
    login_needs_fields = False  # «Войти» требует заполненных полей (например, Client ID)

    def __init__(self, settings: dict | None = None) -> None:
        self.settings = dict(settings or {})
        self.persist = None  # менеджер подставляет функцию сохранения настроек
        self._unavailable = set(self.settings.get("unavailable_ids", []))

    def is_known_unavailable(self, track_id: str) -> bool:
        return track_id in self._unavailable

    def mark_unavailable(self, track_id: str) -> None:
        """Трек не запустился по своей вине: запоминаем, чтобы помечать его сразу."""
        ids = self.settings.setdefault("unavailable_ids", [])
        if track_id in self._unavailable:
            return
        ids.append(track_id)
        del ids[:-1000]
        self._unavailable = set(ids)
        self.save_settings()

    def save_settings(self) -> None:
        """Вызывать, когда сервис сам обновил настройки (например, обновил токен)."""
        if self.persist:
            self.persist()

    def prepare_login(self, credentials: dict) -> BrowserLogin | None:
        """Параметры входа через браузер; сервис может собрать их по введённым полям."""
        return self.browser_login

    def search(self, query: str) -> list[Track]:
        return []

    def playlists(self) -> list[Playlist]:
        """Плейлисты пользователя в сервисе (свои и сохранённые, что отдаёт API)."""
        return []

    def playlist_tracks(self, playlist: Playlist) -> list[Track]:
        return []

    # --- исполнители, альбомы, подборки сервиса ---
    def library_artists(self) -> list[Artist]:
        """Исполнители из библиотеки пользователя (подписки, лайки)."""
        return []

    def library_albums(self) -> list[Album]:
        return []

    def artist_info(self, artist_id: str) -> ArtistInfo:
        raise ServiceError(f"{self.name} не отдаёт профили исполнителей.")

    def album_tracks(self, album: Album) -> list[Track]:
        return []

    def find_artist(self, name: str) -> Artist | None:
        """Исполнитель с таким именем в этом сервисе (для профиля из других сервисов)."""
        return None

    def featured_playlists(self) -> list[Playlist]:
        """Подборки самого сервиса: «Плейлист дня», чарты, «Заряд энергии» и т. п."""
        return []

    @property
    def connected(self) -> bool:
        return bool(self.settings.get("connected"))

    @property
    def account_name(self) -> str:
        return (self.settings.get("account") or {}).get("name", "")

    @abstractmethod
    def connect(self, credentials: dict) -> dict:
        """Проверяет данные входа. Возвращает настройки для сохранения."""

    @abstractmethod
    def home_sections(self, force: bool = False) -> list[Section]:
        """Полки для главной: моя музыка, рекомендации и т.д."""

    @abstractmethod
    def wave(self) -> list[Track]:
        """Очередь для «Моей волны»."""

    @abstractmethod
    def stream_url(self, track: Track) -> str:
        """Свежая ссылка на аудиопоток."""

    def video_stream(self, track: Track) -> tuple[str, str]:
        """Клип к треку: (ссылка на поток, страница для браузера)."""
        raise ServiceError(f"{self.name} не поддерживает клипы.")


def name_from(service) -> str:
    """«из Яндекс Музыки», «из SoundCloud»."""
    return getattr(service, "name_from", "") or service.name


def name_in(service) -> str:
    """«в Яндекс Музыке», «в SoundCloud»."""
    return getattr(service, "name_in", "") or service.name


def same_artist(a: str, b: str) -> bool:
    """Одно и то же имя исполнителя — с учётом транслитерации («Кино» и «KINO»)."""
    from .youtube_match import _match, _words
    wa, wb = _words(a), _words(b)
    return bool(wa and wb) and _match(wa, wb) >= 0.99 and _match(wb, wa) >= 0.99
