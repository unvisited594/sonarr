from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtGui import QFont, QIcon
from PyQt6.QtWidgets import (QButtonGroup, QGridLayout, QHBoxLayout, QLabel, QPushButton, QScrollArea,
                             QToolButton, QVBoxLayout, QWidget)

from ..services import AVAILABLE
from .icons import service_icon
from . import icons
from .theme import C, font
from .visibility import visible
from .widgets import TrackCard, TrackRow, clear_layout, muted, show_track_menu

CARD_STEP = TrackCard.COVER + 16 + 4  # ширина карточки + промежуток


class LikesPage(QWidget):
    """«Мои лайки»: треки из всех сервисов в одной сетке, у каждого значок сервиса."""
    play_requested = pyqtSignal(list, int)
    video_requested = pyqtSignal(object)

    def __init__(self, likes, manager, config, parent=None) -> None:
        super().__init__(parent)
        self.likes, self.manager, self.config = likes, manager, config
        self._filter = "all"
        self._dirty = True
        self._cards: list = []
        self._columns = 0

        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 32, 28, 0)
        outer.setSpacing(6)
        title = QLabel("Мои лайки")
        title.setFont(font(40, QFont.Weight.Black, display=True))
        outer.addWidget(title)
        self.subtitle = muted()
        outer.addWidget(self.subtitle)
        outer.addSpacing(10)
        controls = QHBoxLayout()
        self.chips_row = QHBoxLayout()
        self.chips_row.setSpacing(8)
        controls.addLayout(self.chips_row)
        controls.addStretch(1)  # кнопки вида всегда справа, есть фильтры или нет
        self.view_group = QButtonGroup(self)
        self.view_btns = {}
        for key, icon_name, tip in (("grid", "grid", "Сеткой"), ("list", "list", "Списком")):
            b = QToolButton()
            b.setObjectName("viewToggle")
            b.setCheckable(True)
            b.setFixedSize(34, 34)
            b.setIconSize(QSize(18, 18))
            b.setToolTip(tip)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _=False, k=key: self._set_view(k))
            self.view_group.addButton(b)
            self.view_btns[key] = (b, icon_name)
            controls.addWidget(b)
        outer.addLayout(controls)
        outer.addSpacing(10)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        content = QWidget()
        box = QVBoxLayout(content)
        box.setContentsMargins(0, 0, 8, 28)
        self.empty = muted()
        self.empty.setWordWrap(True)
        box.addWidget(self.empty)
        self.grid = QGridLayout()
        self.grid.setHorizontalSpacing(4)
        self.grid.setVerticalSpacing(10)
        self.grid.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        box.addLayout(self.grid)
        self.rows = QVBoxLayout()
        self.rows.setSpacing(2)
        box.addLayout(self.rows)
        box.addStretch(1)
        self.scroll.setWidget(content)
        outer.addWidget(self.scroll, 1)

        likes.changed.connect(self.refresh)
        manager.changed.connect(self.refresh)

    @property
    def view(self) -> str:
        return self.config.data.get("likes_view", "grid")

    def _set_view(self, key: str) -> None:
        self.config.data["likes_view"] = key
        self.config.save()
        self._render()

    def refresh(self) -> None:
        if not self.isVisible():
            self._dirty = True  # перерисуем при показе
            return
        self._render()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._dirty:
            self._render()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self.view == "grid" and self._columns_for_width() != self._columns:
            self._layout_cards()

    def _columns_for_width(self) -> int:
        return max(1, (self.scroll.viewport().width() - 8) // CARD_STEP)

    def _render(self) -> None:
        self._dirty = False
        all_tracks = visible(self.likes.tracks(self.manager), self.config)
        counts: dict[str, int] = {}
        for t in all_tracks:
            counts[t.service_id] = counts.get(t.service_id, 0) + 1
        if self._filter != "all" and self._filter not in counts:
            self._filter = "all"
        self._build_chips(len(all_tracks), counts)
        tracks = [t for t in all_tracks if self._filter in ("all", t.service_id)]

        n = len(self.likes.entries)
        self.subtitle.setText(
            "Треки, которые вы лайкнули в Sonar. На самих сервисах лайки не меняются."
            if n else "Лайкайте треки сердечком в плеере или через правый клик по треку.")
        self.empty.setVisible(not tracks)
        self.empty.setText("Здесь пока пусто." if not n else "Все лайкнутые треки сейчас недоступны.")

        for b_key, (button, icon_name) in self.view_btns.items():
            button.setChecked(b_key == self.view)
            button.setIcon(icons.icon(icon_name, C("text")))
        for card in self._cards:
            card.deleteLater()
        self._cards = []
        clear_layout(self.rows)
        if self.view == "list":
            small = {sid: service_icon(cls, 18) for sid, cls in AVAILABLE.items()}
            for i, track in enumerate(tracks):
                row = TrackRow(track, small.get(track.service_id))
                if track.playable:
                    row.clicked.connect(lambda i=i, t=tracks: self.play_requested.emit(t, i))
                cls = AVAILABLE.get(track.service_id)
                row.menu_requested.connect(lambda pos, i=i, t=tracks, c=cls: show_track_menu(
                    self, t, i, pos, bool(c and c.supports_video),
                    self.play_requested.emit, self.video_requested.emit))
                self.rows.addWidget(row)
            self._layout_cards()
            return
        badges = {sid: service_icon(cls, 22) for sid, cls in AVAILABLE.items()}
        for i, track in enumerate(tracks):
            card = TrackCard(track, badges.get(track.service_id))
            if track.playable:
                card.clicked.connect(lambda i=i, t=tracks: self.play_requested.emit(t, i))
            cls = AVAILABLE.get(track.service_id)
            card.menu_requested.connect(lambda pos, i=i, t=tracks, c=cls: show_track_menu(
                self, t, i, pos, bool(c and c.supports_video),
                self.play_requested.emit, self.video_requested.emit))
            self._cards.append(card)
        self._layout_cards()

    def _layout_cards(self) -> None:
        self._columns = self._columns_for_width()
        while self.grid.count():
            self.grid.takeAt(0)
        for i, card in enumerate(self._cards):
            self.grid.addWidget(card, i // self._columns, i % self._columns)

    def _build_chips(self, total: int, counts: dict) -> None:
        clear_layout(self.chips_row)
        if len(counts) < 2:  # фильтр нужен, только когда сервисов несколько
            return
        group = QButtonGroup(self)
        group.setExclusive(True)
        options = [("all", f"Все  {total}", None)]
        options += [(sid, f"{AVAILABLE[sid].name}  {n}", AVAILABLE[sid])
                    for sid, n in counts.items() if sid in AVAILABLE]
        for key, text, cls in options:
            chip = QPushButton(text)
            chip.setObjectName("chip")
            chip.setCheckable(True)
            chip.setChecked(key == self._filter)
            chip.setCursor(Qt.CursorShape.PointingHandCursor)
            if cls is not None:
                chip.setIcon(QIcon(service_icon(cls, 16)))
                chip.setIconSize(QSize(16, 16))
            chip.clicked.connect(lambda _=False, k=key: self._set_filter(k))
            group.addButton(chip)
            self.chips_row.addWidget(chip)

    def _set_filter(self, key: str) -> None:
        self._filter = key
        self._render()
