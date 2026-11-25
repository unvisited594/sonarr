from PyQt6.QtCore import QObject, pyqtSignal

from .base import MusicService
from .soundcloud import SoundCloud
from .youtube_music import YouTubeMusic
from .spotify import Spotify
from .navidrome import Navidrome
from .yandex import YandexMusic
from .deezer import Deezer

# Чтобы добавить сервис: напишите подкласс MusicService и допишите его сюда.
AVAILABLE: dict[str, type[MusicService]] = {cls.id: cls for cls in (SoundCloud, YouTubeMusic, Spotify, YandexMusic, Deezer, Navidrome)}


class ServiceManager(QObject):
    changed = pyqtSignal()
    # итог загрузки сервиса: (id, "ok" | "auth" | "error", сообщение) — для карточек и кнопок
    status = pyqtSignal(str, str, str)
    loading_finished = pyqtSignal()   # главная догрузила все сервисы

    def __init__(self, config) -> None:
        super().__init__()
        self.config = config
        self._services: dict[str, MusicService] = {}
        self.needs_login: dict[str, str] = {}   # сервис отклонил вход: id → сообщение
        for sid, cls in AVAILABLE.items():
            settings = config.service(sid)
            if settings.get("connected"):
                self._attach(cls(settings))
        self._attach_shared()

    # ---------- общий сервер Navidrome ----------

    def shared_available(self) -> bool:
        from ..shared_server import load
        return load() is not None

    def is_shared(self, service_id: str) -> bool:
        service = self._services.get(service_id)
        return bool(service and service.settings.get("shared"))

    def _attach_shared(self) -> bool:
        """Подключить общий Navidrome, если своего нет и пользователь его не отключал."""
        if Navidrome.id in self._services or self.config.data.get("shared_navidrome_off"):
            return False
        from ..shared_server import load
        settings = load()
        if settings is None:
            return False
        service = Navidrome(settings)
        self._services[service.id] = service
        service.persist = lambda: None   # общий вход не пишем в настройки пользователя
        return True

    def use_shared(self) -> None:
        """Вернуть общий сервер после отключения."""
        self.config.data.pop("shared_navidrome_off", None)
        self.config.save()
        if self._attach_shared():
            self.needs_login.pop(Navidrome.id, None)
            self.changed.emit()

    def _attach(self, service: MusicService) -> None:
        service.persist = lambda s=service: self.config.set_service(s.id, s.settings)
        self._services[service.id] = service

    def connected(self) -> list[MusicService]:
        return list(self._services.values())

    def get(self, service_id: str) -> MusicService | None:
        if service_id == "radio":   # радио доступно всегда и не считается подключённым сервисом
            if getattr(self, "_radio", None) is None:
                from ..radio import RadioService
                self._radio = RadioService()
            return self._radio
        return self._services.get(service_id)

    def register(self, service: MusicService) -> None:
        self.config.set_service(service.id, service.settings)
        self._attach(service)
        self.needs_login.pop(service.id, None)   # вошли заново — вопрос закрыт
        self.changed.emit()

    def report(self, service_id: str, state: str, message: str = "") -> None:
        """Итог загрузки сервиса. «auth» — токен отклонён: нужен повторный вход."""
        if state == "auth":
            self.needs_login[service_id] = message
        elif state == "ok":
            self.needs_login.pop(service_id, None)
        self.status.emit(service_id, state, message)

    def disconnect(self, service_id: str) -> None:
        shared = self.is_shared(service_id)
        self._services.pop(service_id, None)
        self.needs_login.pop(service_id, None)
        if shared:   # общий сервер отключили сами — больше не подключаем, пока не вернут
            self.config.data["shared_navidrome_off"] = True
            self.config.save()
        else:
            self.config.remove_service(service_id)
            if service_id == Navidrome.id:
                self._attach_shared()   # свой сервер убрали — на его место встаёт общий
        self.changed.emit()
