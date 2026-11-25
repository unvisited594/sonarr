"""Исполнители и альбомы: списки из библиотеки сервисов, профиль исполнителя, альбом."""
import random

from ..services.base import name_in
from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget

from ..services import AVAILABLE
from ..services.base import Artist
from PyQt6 import sip

from ..workers import run_async
from . import icons, nav
from .icons import service_icon
from .theme import C, font
from .visibility import is_offline, visible
from .widgets import (ArtistLabel, CardGrid, Cover, PlaylistCard, TrackRow, clear_layout, generated_cover, muted,
                      show_track_menu, tracks_word)

CARD_STEP = PlaylistCard.COVER + 16 + 4


def _scroll():
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    content = QWidget()
    lay = QVBoxLayout(content)
    lay.setContentsMargins(0, 0, 8, 28)
    lay.setSpacing(10)
    scroll.setWidget(content)
    return scroll, lay


def _title(text: str, size: int = 40) -> QLabel:
    label = QLabel(text)
    label.setFont(font(size, QFont.Weight.Black, display=True))
    label.setWordWrap(True)
    return label


def _section(text: str, icon_pm=None) -> QWidget:
    row = QWidget()
    lay = QHBoxLayout(row)
    lay.setContentsMargins(8, 14, 0, 2)
    lay.setSpacing(10)
    if icon_pm is not None:
        icon = QLabel()
        icon.setPixmap(icon_pm)
        lay.addWidget(icon)
    label = QLabel(text)
    label.setFont(font(22, QFont.Weight.Bold, display=True))
    lay.addWidget(label)
    lay.addStretch(1)
    return row


def _button(text: str, icon_name: str, primary: bool = False) -> QPushButton:
    b = QPushButton(text)
    b.setProperty("compact", True)
    if primary:
        b.setProperty("kind", "primary")
    b.setIcon(icons.icon(icon_name, C("on_accent") if primary else C("text")))
    b.setIconSize(QSize(16, 16))
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    return b


def _back_button(on_back) -> QPushButton:
    back = QPushButton("Назад")
    back.setObjectName("link")
    back.setIcon(icons.icon("chevron_left", C("muted")))
    back.setCursor(Qt.CursorShape.PointingHandCursor)
    back.clicked.connect(on_back)
    return back


def artist_card(artist: Artist, subtitle: str = "") -> PlaylistCard:
    card = PlaylistCard(artist.name, subtitle or AVAILABLE[artist.service_id].name, artist.image,
                        seed=f"artist:{artist.service_id}:{artist.id}", round_=True)
    card.clicked.connect(lambda a=artist: nav.open_artist(a.service_id, a.id, a.name))
    return card


def album_card(album) -> PlaylistCard:
    sub = " · ".join(x for x in (album.year, album.kind if album.kind != "Альбом" else "", album.artist) if x)
    card = PlaylistCard(album.title, sub or AVAILABLE[album.service_id].name, album.cover,
                        seed=f"album:{album.service_id}:{album.id}")
    card.clicked.connect(lambda a=album: nav.open_album(a))
    return card


class _LibraryList(QWidget):
    """Общая основа «Исполнителей» и «Альбомов»: секции по сервисам, загрузка при первом показе."""
    TITLE, SUBTITLE, METHOD, EMPTY = "", "", "", ""

    def __init__(self, manager, config, likes=None, parent=None) -> None:
        super().__init__(parent)
        self.manager, self.config, self.likes = manager, config, likes
        self._data: dict[str, object] = {}
        self._gen = 0
        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 32, 28, 0)
        outer.setSpacing(6)
        outer.addWidget(_title(self.TITLE))
        outer.addWidget(muted(self.SUBTITLE))
        outer.addSpacing(10)
        scroll, self.lay = _scroll()
        outer.addWidget(scroll, 1)
        manager.changed.connect(self.reload)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self._data:
            self.reload()

    def reload(self) -> None:
        self._gen += 1
        gen = self._gen
        self._data.clear()
        if not is_offline(self.config):
            for svc in self.manager.connected():
                run_async(getattr(svc, self.METHOD),
                          on_done=lambda res, s=svc: self._loaded(gen, s, res),
                          on_error=lambda err, s=svc: self._loaded(gen, s, err))
        self._render()

    def _loaded(self, gen, svc, result) -> None:
        if gen == self._gen:
            self._data[svc.id] = result
            self._render()

    def _extra(self) -> bool:
        """Дополнительная секция перед сервисами (у исполнителей — «Из ваших лайков»). True — что-то показали."""
        return False

    def _render(self) -> None:
        clear_layout(self.lay)
        if is_offline(self.config):
            note = muted("Офлайн-режим: исполнители и альбомы сервисов недоступны.")
            self.lay.addWidget(note)
            self.lay.addStretch(1)
            return
        shown = self._extra()
        for svc in self.manager.connected():
            state = self._data.get(svc.id)
            if isinstance(state, list) and not state:
                continue   # у сервиса в библиотеке пусто или раздел не поддерживается — не шумим
            shown = True
            self.lay.addWidget(_section(svc.name, service_icon(type(svc), 24)))
            if state is None:
                self.lay.addWidget(muted("Загружаем…"))
            elif isinstance(state, str):
                err = muted(state, role="error")
                err.setWordWrap(True)
                self.lay.addWidget(err)
            else:
                grid = CardGrid(CARD_STEP)
                grid.set_cards([self._card(x) for x in state])
                self.lay.addWidget(grid)
        if not shown and len(self._data) == len(self.manager.connected()):
            self.lay.addWidget(muted(self.EMPTY if self.manager.connected()
                                     else "Подключите сервис в Настройках → Интеграция."))
        self.lay.addStretch(1)


class ArtistsPage(_LibraryList):
    TITLE = "Исполнители"
    SUBTITLE = "Подписки из сервисов и исполнители, которых вы лайкаете"
    METHOD = "library_artists"
    EMPTY = "Здесь появятся исполнители: подпишитесь на них в сервисе или лайкайте их треки."

    def _card(self, artist):
        return artist_card(artist)

    def _extra(self) -> bool:
        if self.likes is None:
            return False
        counts: dict = {}
        for t in self.likes.tracks(self.manager):
            aid = t.raw.get("artist_id")
            if aid:
                key = (t.service_id, aid)
                name = t.artist.split(",")[0].strip()
                counts.setdefault(key, [name, 0])[1] += 1
        if not counts:
            return False
        top = sorted(counts.items(), key=lambda kv: kv[1][1], reverse=True)[:24]
        self.lay.addWidget(_section("Из ваших лайков"))
        grid = CardGrid(CARD_STEP)
        grid.set_cards([artist_card(Artist(aid, name, None, sid), tracks_word(n))
                        for (sid, aid), (name, n) in top if sid in AVAILABLE])
        self.lay.addWidget(grid)
        return True


class AlbumsPage(_LibraryList):
    TITLE = "Альбомы"
    SUBTITLE = "Альбомы из вашей библиотеки в сервисах"
    METHOD = "library_albums"
    EMPTY = "Здесь появятся альбомы, которые вы сохранили или лайкнули в сервисах."

    def _card(self, album):
        return album_card(album)


class _Detail(QWidget):
    """Основа страниц исполнителя и альбома: «Назад», шапка, содержимое."""
    play_requested = pyqtSignal(list, int)
    video_requested = pyqtSignal(object)

    def __init__(self, manager, config, on_back, parent=None) -> None:
        super().__init__(parent)
        self.manager, self.config = manager, config
        self._gen = 0
        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 24, 28, 0)
        outer.setSpacing(6)
        outer.addWidget(_back_button(on_back), 0, Qt.AlignmentFlag.AlignLeft)
        scroll, self.lay = _scroll()
        outer.addWidget(scroll, 1)

    def _rows(self, tracks: list, svc_cls) -> None:
        tracks = visible(tracks, self.config)
        for i, track in enumerate(tracks):
            row = TrackRow(track)
            if track.playable:
                row.clicked.connect(lambda i=i, t=tracks: self.play_requested.emit(t, i))
            row.menu_requested.connect(lambda pos, i=i, t=tracks: show_track_menu(
                self, t, i, pos, bool(svc_cls and svc_cls.supports_video),
                self.play_requested.emit, self.video_requested.emit))
            self.lay.addWidget(row)

    def _play_buttons(self, tracks: list) -> QHBoxLayout:
        playable = [t for t in tracks if t.playable]
        row = QHBoxLayout()
        row.setSpacing(8)
        play = _button("Слушать", "play", primary=True)
        play.setEnabled(bool(playable))
        play.clicked.connect(lambda: self.play_requested.emit(playable, 0))
        shuffle = _button("Перемешать", "shuffle")
        shuffle.setEnabled(bool(playable))
        shuffle.clicked.connect(lambda: self.play_requested.emit(random.sample(playable, len(playable)), 0))
        row.addWidget(play)
        row.addWidget(shuffle)
        row.addStretch(1)
        return row

    def _state(self, text: str, error: bool = False) -> None:
        clear_layout(self.lay)
        label = muted(text, role="error" if error else "muted")
        label.setWordWrap(True)
        self.lay.addWidget(label)
        self.lay.addStretch(1)


class ArtistPage(_Detail):
    def show_artist(self, service_id: str, artist_id: str, name: str = "") -> None:
        self._gen += 1
        gen = self._gen
        svc = self.manager.get(service_id)
        if svc is None:
            self._state(f"Сервис {AVAILABLE[service_id].name if service_id in AVAILABLE else ''} не подключён.")
            return
        if is_offline(self.config):
            self._state("Офлайн-режим: профиль исполнителя недоступен.")
            return
        self._state(f"Загружаем {name or 'исполнителя'}…")
        self._name, self._origin = name, service_id
        run_async(svc.artist_info, artist_id,
                  on_done=lambda info: gen == self._gen and self._loaded(gen, info),
                  on_error=lambda err: gen == self._gen and self._failed(gen, err))

    def _loaded(self, gen: int, info) -> None:
        self._render(info)
        if not info.albums:   # сервис не отдал альбомы — ищем исполнителя в других сервисах
            self._load_elsewhere(gen, info.artist.name or self._name)

    def _failed(self, gen: int, err: str) -> None:
        self._state(err, error=True)
        if self._name:
            self._load_elsewhere(gen, self._name)

    def _load_elsewhere(self, gen: int, name: str) -> None:
        others = [s for s in self.manager.connected() if s.id != self._origin]
        if not name or not others:
            return
        self._pending_label = muted(f"Ищем {name} в других сервисах…")
        self.lay.insertWidget(self.lay.count() - 1, self._pending_label)
        run_async(_find_elsewhere, others, name,
                  on_done=lambda found: gen == self._gen and self._render_elsewhere(found),
                  on_error=lambda err: gen == self._gen and self._render_elsewhere([]))

    def _render_elsewhere(self, found: list) -> None:
        label = getattr(self, "_pending_label", None)
        if label is not None and not sip.isdeleted(label):
            label.hide()
            label.deleteLater()
        stretch = self.lay.takeAt(self.lay.count() - 1)   # блоки встают перед хвостовой распоркой
        if not found:
            self.lay.addWidget(muted("В других подключённых сервисах этого исполнителя не нашлось."))
        for svc, info in found:
            self.lay.addWidget(_section(f"Также в {name_in(svc)}", service_icon(type(svc), 24)))
            if info.albums:
                grid = CardGrid(CARD_STEP)
                grid.set_cards([album_card(al) for al in info.albums])
                self.lay.addWidget(grid)
            if info.top_tracks:
                self._rows(info.top_tracks[:5], type(svc))
        if stretch is not None:
            self.lay.addItem(stretch)

    def _render(self, info) -> None:
        clear_layout(self.lay)
        a = info.artist
        cls = AVAILABLE.get(a.service_id)
        head = QHBoxLayout()
        head.setSpacing(24)
        photo = Cover(170, 85)
        if a.image:
            photo.set_url(a.image)
        else:
            photo.set_pixmap(generated_cover(f"artist:{a.service_id}:{a.id}", a.name, 340, True))
        head.addWidget(photo, 0, Qt.AlignmentFlag.AlignTop)
        col = QVBoxLayout()
        col.setSpacing(6)
        src = QHBoxLayout()
        src.setSpacing(6)
        if cls:
            ic = QLabel()
            ic.setPixmap(service_icon(cls, 18))
            src.addWidget(ic)
            src.addWidget(muted(f"Исполнитель · {cls.name}"))
        src.addStretch(1)
        col.addLayout(src)
        col.addWidget(_title(a.name or "Исполнитель", 44))
        if info.description:
            desc = QLabel()
            desc.setWordWrap(True)
            desc.setProperty("role", "help")
            # Фиксированная ширина: Qt заранее знает число строк и честно выделяет высоту. С «гибкой»
            # шириной во вложенной раскладке он сжимал строки описания друг на друга.
            desc.setFixedWidth(620)
            full = info.description
            short = full if len(full) <= 420 else full[:420].rsplit(" ", 1)[0] + "…"
            desc.setText(short)
            desc.setFixedHeight(desc.heightForWidth(620))   # высота строго по числу строк
            col.addWidget(desc)
            if short != full:   # длинное описание — свернуто, раскрывается по кнопке
                more = QPushButton("Показать полностью")
                more.setObjectName("link")
                more.setCursor(Qt.CursorShape.PointingHandCursor)
                more.clicked.connect(lambda _=False, d=desc, b=more: (
                    d.setText(full), d.setFixedHeight(d.heightForWidth(620)), b.hide()))
                col.addWidget(more, 0, Qt.AlignmentFlag.AlignLeft)
        col.addSpacing(6)
        col.addLayout(self._play_buttons(info.top_tracks))
        col.addStretch(1)
        head.addLayout(col, 1)
        holder = QWidget()
        holder.setLayout(head)
        self.lay.addWidget(holder)
        if info.top_tracks:
            self.lay.addWidget(_section("Популярные треки"))
            self._rows(info.top_tracks, cls)
        if info.albums:
            self.lay.addWidget(_section("Альбомы и синглы"))
            grid = CardGrid(CARD_STEP)
            grid.set_cards([album_card(al) for al in info.albums])
            self.lay.addWidget(grid)
        if not info.top_tracks and not info.albums:
            self.lay.addWidget(muted("Сервис не отдал треков и альбомов этого исполнителя."))
        self.lay.addStretch(1)


def _find_elsewhere(services, name: str) -> list:
    """В фоне: тот же исполнитель в других сервисах — у кого нашлись альбомы или треки."""
    from ..services.base import ServiceError
    found = []
    for svc in services:
        try:
            artist = svc.find_artist(name)
            if artist is None:
                continue
            info = svc.artist_info(artist.id)
        except ServiceError:
            continue
        if info.albums or info.top_tracks:
            found.append((svc, info))
    return found


class AlbumPage(_Detail):
    def show_album(self, album) -> None:
        self._gen += 1
        gen = self._gen
        self.album = album
        svc = self.manager.get(album.service_id)
        if svc is None:
            self._state("Сервис этого альбома не подключён.")
            return
        if is_offline(self.config):
            self._state("Офлайн-режим: альбомы сервисов недоступны.")
            return
        self._state(f"Загружаем «{album.title}»…")
        run_async(svc.album_tracks, album,
                  on_done=lambda tracks: gen == self._gen and self._render(tracks),
                  on_error=lambda err: gen == self._gen and self._state(err, error=True))

    def _render(self, tracks: list) -> None:
        clear_layout(self.lay)
        al = self.album
        cls = AVAILABLE.get(al.service_id)
        for t in tracks:   # у треков альбома часто нет своей обложки
            t.artwork_url = t.artwork_url or al.cover
        head = QHBoxLayout()
        head.setSpacing(24)
        cover = Cover(170, 14)
        if al.cover:
            cover.set_url(al.cover)
        else:
            cover.set_pixmap(generated_cover(f"album:{al.service_id}:{al.id}", al.title, 340))
        head.addWidget(cover, 0, Qt.AlignmentFlag.AlignTop)
        col = QVBoxLayout()
        col.setSpacing(6)
        col.addWidget(muted(" · ".join(x for x in (al.kind, al.date[:10] if al.date else "",
                                                   tracks_word(len(tracks))) if x)))
        col.addWidget(_title(al.title, 38))
        if al.artist:
            who = ArtistLabel(al.artist)
            who.setFont(font(16, QFont.Weight.DemiBold))
            who.set_target(al.service_id, al.artist_id, al.artist.split(",")[0].strip())
            col.addWidget(who)
        col.addSpacing(6)
        col.addLayout(self._play_buttons(tracks))
        col.addStretch(1)
        head.addLayout(col, 1)
        self.lay.addLayout(head)
        self.lay.addSpacing(10)
        self._rows(tracks, cls)
        if not tracks:
            self.lay.addWidget(muted("В альбоме нет треков, доступных через сервис."))
        self.lay.addStretch(1)
