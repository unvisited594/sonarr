"""Переходы между страницами, доступные из любого виджета (клик по исполнителю в карточке и т. п.).
Главное окно подставляет обработчики при запуске."""
_handlers: dict = {}


def set_handlers(**handlers) -> None:
    _handlers.update(handlers)


def open_artist(service_id: str, artist_id: str, name: str = "") -> None:
    if "artist" in _handlers and artist_id:
        _handlers["artist"](service_id, artist_id, name)


def open_album(album) -> None:
    if "album" in _handlers:
        _handlers["album"](album)


def open_playlist(service_id: str, playlist) -> None:
    if "playlist" in _handlers:
        _handlers["playlist"](service_id, playlist)


def toast(text: str) -> None:
    if "toast" in _handlers:
        _handlers["toast"](text)
