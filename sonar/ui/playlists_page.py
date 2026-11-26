import random

from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (QHBoxLayout, QInputDialog, QLabel, QMessageBox, QPushButton, QScrollArea,
                             QStackedWidget, QVBoxLayout, QWidget)

from ..services import AVAILABLE
from ..workers import run_async
from . import icons
from .icons import service_icon
from .theme import C, font
from .visibility import is_offline, visible
from .widgets import (CardGrid, Cover, PlaylistCard, TrackRow, clear_layout, generated_cover, muted,
                      show_track_menu,
                      tracks_word)

CARD_STEP = PlaylistCard.COVER + 16 + 4


def _button(text: str, primary: bool = False, icon_name: str | None = None) -> QPushButton:
    b = QPushButton(text)
    b.setProperty("compact", True)
    if primary:
        b.setProperty("kind", "primary")
    if icon_name:
        b.setIcon(icons.icon(icon_name, C("on_accent") if primary else C("text")))
        b.setIconSize(QSize(16, 16))
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    return b


def _scroll() -> tuple[QScrollArea, QVBoxLayout]:
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    content = QWidget()
    lay = QVBoxLayout(content)
    lay.setContentsMargins(0, 0, 8, 28)
    lay.setSpacing(10)
    scroll.setWidget(content)
    return scroll, lay


class PlaylistsPage(QWidget):
    play_requested = pyqtSignal(list, int)
    video_requested = pyqtSignal(object)

    def __init__(self, local, manager, config, parent=None) -> None:
        super().__init__(parent)
        self.local, self.manager, self.config = local, manager, config
        self.smart_sources = None   # (лайки, история) — передаёт главное окно
        self._smart_at = -1e9
        self._remote: dict[str, object] = {}   # id сервиса -> list[Playlist] | str (ошибка)
        self._featured: dict[str, list] = {}   # подборки самих сервисов
        self._gen = 0
        self._open: tuple | None = None        # ("local", id) | ("service", svc, playlist)
        self._detail_gen = 0
        self._dirty = True

        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 32, 28, 0)
        self.stack = QStackedWidget()
        outer.addWidget(self.stack)

        # обзор
        overview = QWidget()
        ov = QVBoxLayout(overview)
        ov.setContentsMargins(0, 0, 0, 0)
        ov.setSpacing(6)
        head = QHBoxLayout()
        title = QLabel("Плейлисты")
        title.setFont(font(40, QFont.Weight.Black, display=True))
        head.addWidget(title)
        head.addStretch(1)
        self.refresh_btn = _button("Обновить плейлисты", icon_name="refresh")
        self.refresh_btn.setToolTip("Заново загрузить плейлисты из всех сервисов")
        self.refresh_btn.clicked.connect(self.reload_playlists)
        head.addWidget(self.refresh_btn, 0, Qt.AlignmentFlag.AlignVCenter)
        self.new_btn = _button("Новый плейлист", primary=True, icon_name="plus")
        self.new_btn.clicked.connect(self._create)
        head.addWidget(self.new_btn, 0, Qt.AlignmentFlag.AlignVCenter)
        ov.addLayout(head)
        ov.addWidget(muted("Ваши плейлисты в Sonar и плейлисты из подключённых сервисов"))
        ov.addSpacing(14)
        scroll, self.ov_lay = _scroll()
        ov.addWidget(scroll, 1)
        self.stack.addWidget(overview)

        # плейлист
        detail = QWidget()
        dv = QVBoxLayout(detail)
        dv.setContentsMargins(0, 0, 0, 0)
        dv.setSpacing(10)
        back = QPushButton("Плейлисты")
        back.setObjectName("link")
        back.setIcon(icons.icon("chevron_left", C("muted")))
        back.setCursor(Qt.CursorShape.PointingHandCursor)
        back.clicked.connect(self.show_overview)
        self.back_btn = back
        dv.addWidget(back, 0, Qt.AlignmentFlag.AlignLeft)
        self.detail_head = QHBoxLayout()
        self.detail_head.setSpacing(22)
        dv.addLayout(self.detail_head)
        dv.addSpacing(8)
        scroll, self.rows = _scroll()
        self.rows.setSpacing(2)
        dv.addWidget(scroll, 1)
        self.stack.addWidget(detail)

        local.changed.connect(self._local_changed)
        manager.changed.connect(self._services_changed)

    # ---------- общее ----------

    def _visible(self, tracks: list) -> list:
        return visible(tracks, self.config)

    def refresh_smart(self, force: bool = False) -> None:
        """Умные плейлисты пересобираются не чаще раза в минуту."""
        import time as _time
        if self.smart_sources is None or (not force and _time.monotonic() - self._smart_at < 60):
            return
        self._smart_at = _time.monotonic()
        from .. import smart
        likes, history = self.smart_sources
        smart.refresh(self.local, likes, history)
        self._dirty = True

    def refresh(self) -> None:
        if not self.isVisible():
            self._dirty = True
            return
        self._render_current()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.refresh_smart()
        if not self._remote and self.manager.connected() and not is_offline(self.config):
            self._load_remote()
        if self._dirty:
            self._render_current()

    def _render_current(self) -> None:
        self._dirty = False
        if self.stack.currentIndex() == 0:
            self._render_overview()
        elif self._open:
            self._render_detail(reload=False)

    def _local_changed(self) -> None:
        if self._open and self._open[0] == "local" and not self.local.get(self._open[1]):
            self.show_overview()  # плейлист удалили
            return
        self.refresh()

    def _services_changed(self) -> None:
        self._remote.clear()
        if self._open and self._open[0] == "service":
            self.show_overview()
        if self.isVisible():
            self._load_remote()
        self.refresh()

    def reload_playlists(self) -> None:
        """Перезагружает плейлисты сервисов; открытый плейлист сервиса — тоже."""
        self._load_remote()
        if self._open and self._open[0] == "service":
            self._render_detail(reload=True)
        else:
            self._render_overview()

    def _load_remote(self) -> None:
        if is_offline(self.config):
            return  # офлайн: плейлисты сервисов не запрашиваем
        self._gen += 1
        gen = self._gen
        self._remote.clear()
        self._featured.clear()
        for svc in self.manager.connected():
            run_async(svc.playlists,
                      on_done=lambda res, s=svc: self._remote_loaded(gen, s, res),
                      on_error=lambda err, s=svc: self._remote_loaded(gen, s, err))
            run_async(svc.featured_playlists,
                      on_done=lambda res, s=svc: self._featured_loaded(gen, s, res),
                      on_error=lambda err: None)   # нет подборок — просто не показываем раздел

    def _featured_loaded(self, gen, svc, result) -> None:
        if gen == self._gen and result:
            self._featured[svc.id] = result
            self.refresh()

    def _remote_loaded(self, gen, svc, result) -> None:
        if gen != self._gen:
            return
        self._remote[svc.id] = result
        self.refresh()

    # ---------- обзор ----------

    def show_overview(self) -> None:
        self._open = None
        self._detail_gen += 1
        self.stack.setCurrentIndex(0)
        self._render_overview()

    def _section_title(self, text: str, icon_pm=None) -> QWidget:
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

    def _render_overview(self) -> None:
        clear_layout(self.ov_lay)
        self.ov_lay.addWidget(self._section_title("Мои плейлисты"))
        mine = self.local.all()
        if not mine:
            hint = muted("Создайте плейлист и добавляйте в него треки из любых сервисов: "
                         "правый клик по треку → «Добавить в плейлист».")
            hint.setWordWrap(True)
            hint.setContentsMargins(8, 0, 0, 0)
            self.ov_lay.addWidget(hint)
        else:
            grid = CardGrid(CARD_STEP)
            cards = []
            for pl in mine:
                # плейлисты, созданные в Sonar, — со своей цветной обложкой (постоянной для плейлиста)
                card = PlaylistCard(pl["title"], tracks_word(len(pl["tracks"])), None, seed=f"local:{pl['id']}")
                card.clicked.connect(lambda pid=pl["id"]: self.open_local(pid))
                cards.append(card)
            grid.set_cards(cards)
            self.ov_lay.addWidget(grid)

        if is_offline(self.config):
            note = muted("Офлайн-режим: плейлисты сервисов недоступны, в своих плейлистах видны "
                         "только скачанные треки Navidrome.")
            note.setWordWrap(True)
            self.ov_lay.addWidget(self._indent(note))
            self.ov_lay.addStretch(1)
            return
        if self._featured:
            self.ov_lay.addWidget(self._section_title("Подборки сервисов"))
            grid = CardGrid(CARD_STEP)
            cards = []
            for svc in self.manager.connected():
                for pl in self._featured.get(svc.id, []):
                    sub = tracks_word(pl.count) if pl.count else (pl.owner or svc.name)
                    card = PlaylistCard(pl.title, sub, pl.cover_url, service_icon(type(svc), 22),
                                        seed=f"featured:{svc.id}:{pl.id}")
                    card.clicked.connect(lambda s_=svc, p=pl: self.open_service(s_, p))
                    cards.append(card)
            grid.set_cards(cards)
            self.ov_lay.addWidget(grid)
        for svc in self.manager.connected():
            self.ov_lay.addWidget(self._section_title(svc.name, service_icon(type(svc), 24)))
            state = self._remote.get(svc.id)
            if state is None:
                self.ov_lay.addWidget(self._indent(muted("Загружаем плейлисты…")))
            elif isinstance(state, str):
                err = muted(state, role="error")
                err.setWordWrap(True)
                self.ov_lay.addWidget(self._indent(err))
            elif not state:
                self.ov_lay.addWidget(self._indent(muted(f"В {svc.name} нет плейлистов, "
                                                         "которые сервис отдаёт сторонним приложениям.")))
            else:
                grid = CardGrid(CARD_STEP)
                cards = []
                for pl in state:
                    sub = tracks_word(pl.count) if pl.count is not None else (pl.owner or svc.name)
                    card = PlaylistCard(pl.title, sub, pl.cover_url)
                    card.clicked.connect(lambda s=svc, p=pl: self.open_service(s, p))
                    cards.append(card)
                grid.set_cards(cards)
                self.ov_lay.addWidget(grid)
        self.ov_lay.addStretch(1)

    @staticmethod
    def _indent(widget: QWidget) -> QWidget:
        widget.setContentsMargins(8, 0, 0, 0)
        return widget

    def _create(self) -> None:
        title, ok = QInputDialog.getText(self, "Новый плейлист", "Название плейлиста:")
        if ok and title.strip():
            self.open_local(self.local.create(title))

    # ---------- плейлист ----------

    def open_local(self, playlist_id: str) -> None:
        self._open = ("local", playlist_id)
        self.stack.setCurrentIndex(1)
        self._render_detail(reload=True)

    def open_service(self, svc, playlist) -> None:
        self._open = ("service", svc, playlist, None)
        self.stack.setCurrentIndex(1)
        self._render_detail(reload=True)

    def _render_detail(self, reload: bool) -> None:
        kind = self._open[0]
        if kind == "local":
            pl = self.local.get(self._open[1])
            if pl is None:
                self.show_overview()
                return
            entries = list(enumerate(self.local.tracks(pl["id"], self.manager)))
            keep = {id(t) for t in self._visible([t for _, t in entries])}
            entries = [(i, t) for i, t in entries if id(t) in keep]
            cover = next((t.artwork_url for _, t in entries if t.artwork_url), None)
            self._fill_head(pl["title"], f"Плейлист Sonar  ·  {tracks_word(len(pl['tracks']))}",
                            cover, None, [t for _, t in entries], local_id=pl["id"])
            self._fill_rows(entries, local_id=pl["id"])
            return

        _, svc, playlist, loaded = self._open
        if reload or loaded is None:
            self._detail_gen += 1
            gen = self._detail_gen
            self._fill_head(playlist.title, svc.name, playlist.cover_url, service_icon(type(svc), 18), [])
            clear_layout(self.rows)
            self.rows.addWidget(muted("Загружаем треки…"))
            run_async(svc.playlist_tracks, playlist,
                      on_done=lambda res: self._service_loaded(gen, res),
                      on_error=lambda err: self._service_loaded(gen, err))
            return
        if isinstance(loaded, str):
            self._fill_head(playlist.title, svc.name, playlist.cover_url, service_icon(type(svc), 18), [])
            clear_layout(self.rows)
            err = muted(loaded, role="error")
            err.setWordWrap(True)
            self.rows.addWidget(err)
            return
        tracks = self._visible(loaded)
        self._fill_head(playlist.title, f"{svc.name}  ·  {tracks_word(len(loaded))}",
                        playlist.cover_url, service_icon(type(svc), 18), tracks)
        self._fill_rows(list(enumerate(tracks)))

    def _service_loaded(self, gen, result) -> None:
        if gen != self._detail_gen or not self._open or self._open[0] != "service":
            return
        _, svc, playlist, _ = self._open
        self._open = ("service", svc, playlist, result)
        self._render_detail(reload=False)

    def _fill_head(self, title: str, subtitle: str, cover_url, source_icon, tracks: list,
                   local_id: str | None = None) -> None:
        clear_layout(self.detail_head)
        cover = Cover(140, 14)
        if local_id:   # та же цветная обложка, что на карточке плейлиста
            cover.set_pixmap(generated_cover(f"local:{local_id}", title, 280))
        elif cover_url:
            cover.set_url(cover_url)
        else:
            cover.set_pixmap(generated_cover(f"playlist:{title}", title, 280))
        self.detail_head.addWidget(cover)
        col = QVBoxLayout()
        col.setSpacing(6)
        col.addStretch(1)
        name = QLabel(title)
        name.setFont(font(34, QFont.Weight.Black, display=True))
        name.setWordWrap(True)
        col.addWidget(name)
        sub_row = QHBoxLayout()
        sub_row.setSpacing(6)
        if source_icon is not None:
            icon = QLabel()
            icon.setPixmap(source_icon)
            sub_row.addWidget(icon)
        sub_row.addWidget(muted(subtitle))
        sub_row.addStretch(1)
        col.addLayout(sub_row)
        col.addSpacing(8)
        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        playable = [t for t in tracks if t.playable]
        play = _button("Слушать", primary=True, icon_name="play")
        play.setEnabled(bool(playable))
        play.clicked.connect(lambda: self.play_requested.emit(playable, 0))
        shuffle = _button("Перемешать", icon_name="shuffle")
        shuffle.setEnabled(bool(playable))
        shuffle.clicked.connect(lambda: self.play_requested.emit(random.sample(playable, len(playable)), 0))
        buttons.addWidget(play)
        buttons.addWidget(shuffle)
        move = _button("Собрать в другом сервисе")
        move.setToolTip("Найти эти треки в другом сервисе и собрать из них новый плейлист")
        move.setEnabled(bool(tracks))
        move.clicked.connect(lambda: self._transfer(move, title, tracks))
        buttons.addWidget(move)
        if local_id and local_id.startswith("smart-"):
            buttons.addWidget(muted("Собирается сам: " + ((self.local.get(local_id) or {}).get("about") or "")))
        elif local_id:
            rename = _button("Переименовать")
            rename.clicked.connect(lambda: self._rename(local_id))
            delete = _button("Удалить")
            delete.clicked.connect(lambda: self._delete(local_id))
            buttons.addWidget(rename)
            buttons.addWidget(delete)
        buttons.addStretch(1)
        col.addLayout(buttons)
        col.addStretch(1)
        self.detail_head.addLayout(col, 1)

    def _fill_rows(self, entries: list, local_id: str | None = None) -> None:
        clear_layout(self.rows)
        if not entries:
            self.rows.addWidget(muted(
                "Плейлист пуст. Добавляйте треки через правый клик → «Добавить в плейлист»."
                if local_id else "В этом плейлисте нет треков."))
            self.rows.addStretch(1)
            return
        tracks = [t for _, t in entries]
        badges = {sid: service_icon(cls, 18) for sid, cls in AVAILABLE.items()}
        for pos, (orig_index, track) in enumerate(entries):
            row = TrackRow(track, badges.get(track.service_id))
            if track.playable:
                row.clicked.connect(lambda p=pos: self.play_requested.emit(tracks, p))
            cls = AVAILABLE.get(track.service_id)
            extra = ()
            if local_id and not local_id.startswith("smart-"):
                extra = (("Убрать из плейлиста",
                          lambda _=False, i=orig_index: self.local.remove_at(local_id, i)),)
            row.menu_requested.connect(lambda point, p=pos, c=cls, ex=extra: show_track_menu(
                self, tracks, p, point, bool(c and c.supports_video),
                self.play_requested.emit, self.video_requested.emit, ex))
            self.rows.addWidget(row)
        self.rows.addStretch(1)

    def _transfer(self, anchor, title: str, tracks: list) -> None:
        from .endless import offer_transfer
        offer_transfer(self, anchor, title, tracks, self.local, self.open_local)

    def _rename(self, playlist_id: str) -> None:
        pl = self.local.get(playlist_id)
        title, ok = QInputDialog.getText(self, "Переименовать плейлист", "Название плейлиста:",
                                         text=pl["title"] if pl else "")
        if ok and title.strip():
            self.local.rename(playlist_id, title)

    def _delete(self, playlist_id: str) -> None:
        pl = self.local.get(playlist_id)
        answer = QMessageBox.question(self, "Удалить плейлист",
                                      f"Удалить плейлист «{pl['title'] if pl else ''}»? "
                                      "Треки в сервисах не пострадают.")
        if answer == QMessageBox.StandardButton.Yes:
            self.local.delete(playlist_id)
