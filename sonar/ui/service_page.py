"""Страница одного сервиса: только его полки и его «волна»."""
import random

from ..services.base import name_from
from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget

from ..downloads import SERVICE_ID, downloads
from ..services import AVAILABLE
from . import icons
from .icons import service_icon
from .theme import C, font
from .visibility import is_offline, visible
from .widgets import Shelf, clear_layout, muted


class ServicePage(QWidget):
    play_requested = pyqtSignal(list, int)
    video_requested = pyqtSignal(object)

    def __init__(self, home, manager, config, parent=None) -> None:
        super().__init__(parent)
        self.home, self.manager, self.config = home, manager, config
        self.service_id: str | None = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 32, 28, 0)
        outer.setSpacing(6)
        self.head = QHBoxLayout()
        self.head.setSpacing(16)
        outer.addLayout(self.head)
        outer.addSpacing(16)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        content = QWidget()
        self.body = QVBoxLayout(content)
        self.body.setContentsMargins(0, 0, 8, 28)
        self.body.setSpacing(30)
        scroll.setWidget(content)
        outer.addWidget(scroll, 1)

        home.sections_updated.connect(self.refresh)

    def show_service(self, service_id: str) -> None:
        self.service_id = service_id
        self._render()

    def refresh(self) -> None:
        if self.isVisible() and self.service_id:
            self._render()

    def _tracks_pool(self, sections) -> list:
        seen, out = set(), []
        for section in sections:
            for t in section.tracks:
                if t.id not in seen:
                    seen.add(t.id)
                    out.append(t)
        return visible(out, self.config)

    def _render(self) -> None:
        cls = AVAILABLE.get(self.service_id)
        svc = self.manager.get(self.service_id)
        clear_layout(self.head)
        clear_layout(self.body)
        if cls is None:
            return
        icon = QLabel()
        icon.setPixmap(service_icon(cls, 56))
        self.head.addWidget(icon)
        col = QVBoxLayout()
        col.setSpacing(2)
        title = QLabel(cls.name)
        title.setFont(font(40, QFont.Weight.Black, display=True))
        col.addWidget(title)
        col.addWidget(muted(f"Подключено: {svc.account_name}" if svc else "Сервис не подключён"))
        self.head.addLayout(col, 1)

        offline = is_offline(self.config)
        if offline and self.service_id == SERVICE_ID:
            store = downloads()
            from ..services.base import Section
            sections = [Section("downloads", "Скачанное", store.tracks() if store else [])]
        elif offline:
            self.body.addWidget(muted(f"Офлайн-режим: {cls.name} недоступен. Доступны только "
                                      "скачанные треки Navidrome."))
            self.body.addStretch(1)
            return
        else:
            state = self.home._sections.get(self.service_id)
            if svc is None:
                self.body.addWidget(muted("Подключите сервис в Настройках → Интеграция."))
                self.body.addStretch(1)
                return
            if state is None:
                self.body.addWidget(muted(f"Загружаем музыку из {name_from(cls)}…"))
                self.body.addStretch(1)
                return
            from .home import AuthNeeded
            if isinstance(state, AuthNeeded):
                self.body.addWidget(self.home._login_row(svc, state.message))
                self.body.addStretch(1)
                return
            if isinstance(state, str):
                err = muted(state, role="error")
                err.setWordWrap(True)
                self.body.addWidget(err)
                self.body.addStretch(1)
                return
            sections = state

        pool = self._tracks_pool(sections)
        for text, icon_name, shuffle in (("Слушать всё", "play", False), ("Перемешать", "shuffle", True)):
            b = QPushButton(text)
            b.setProperty("compact", True)
            if not shuffle:
                b.setProperty("kind", "primary")
            b.setIcon(icons.icon(icon_name, C("on_accent") if not shuffle else C("text")))
            b.setIconSize(QSize(16, 16))
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setEnabled(bool(pool))
            b.clicked.connect(lambda _=False, sh=shuffle: self.play_requested.emit(
                random.sample(pool, len(pool)) if sh else pool, 0))
            self.head.addWidget(b, 0, Qt.AlignmentFlag.AlignVCenter)

        shown = 0
        for section in sections:
            tracks = visible(section.tracks, self.config)
            if not tracks:
                continue
            shelf = Shelf(section.title, tracks, None, cls.supports_video)
            shelf.play_requested.connect(self.play_requested)
            shelf.video_requested.connect(self.video_requested)
            self.body.addWidget(shelf)
            shown += 1
        if not shown:
            self.body.addWidget(muted("Здесь пока нечего показать."))
        self.body.addStretch(1)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self.service_id:
            self._render()
