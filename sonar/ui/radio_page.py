"""Вкладка «Радио»: поиск по каталогу, жанры, Россия или весь мир, избранные станции."""
from PyQt6 import sip
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (QGridLayout, QHBoxLayout, QLabel, QLineEdit, QMenu, QPushButton, QScrollArea,
                             QVBoxLayout, QWidget)

from .. import radio
from ..services.base import Track
from ..workers import run_async
from .theme import font
from .widgets import TrackRow, clear_layout, muted


class RadioPage(QWidget):
    play_requested = pyqtSignal(list, int)

    def __init__(self, config, parent=None) -> None:
        super().__init__(parent)
        self.config = config
        self._req = 0
        self._loaded = False
        self.tag = ""
        lay = QVBoxLayout(self)
        lay.setContentsMargins(36, 28, 24, 0)
        lay.setSpacing(10)
        title = QLabel("Радио")
        title.setFont(font(30, QFont.Weight.Black, display=True))
        lay.addWidget(title)
        lay.addWidget(muted("Тысячи станций со всего мира из открытого каталога radio-browser.info. "
                            "Правый клик по станции — в избранное."))
        row = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Название станции, например «Европа Плюс» или «lofi»")
        self.search.returnPressed.connect(self.load)
        row.addWidget(self.search, 1)
        self.where = QPushButton("Россия")
        self.where.setCheckable(True)
        self.where.setChecked(self.config.data.get("radio_ru", True))
        self.where.setObjectName("chip")
        self.where.setToolTip("Только российские станции или весь мир")
        self.where.toggled.connect(self._where)
        row.addWidget(self.where)
        lay.addLayout(row)
        chips = QGridLayout()
        chips.setHorizontalSpacing(6)
        chips.setVerticalSpacing(6)
        self.chips = {}
        for i, (name, tag) in enumerate([("Популярное", "")] + radio.GENRES):
            b = QPushButton(name)
            b.setObjectName("chip")
            b.setCheckable(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _=False, t=tag: self._genre(t))
            self.chips[tag] = b
            chips.addWidget(b, i // 7, i % 7)
        self.chips[""].setChecked(True)
        lay.addLayout(chips)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QWidget()
        self.list = QVBoxLayout(inner)
        self.list.setContentsMargins(0, 8, 12, 24)
        self.list.setSpacing(4)
        self.list.setAlignment(Qt.AlignmentFlag.AlignTop)
        scroll.setWidget(inner)
        lay.addWidget(scroll, 1)

    # ---------- избранное ----------

    def favorites(self) -> list[Track]:
        out = []
        for d in self.config.data.get("radio_favs", []):
            out.append(Track(id=d["id"], title=d["title"], artist=d.get("artist", ""), duration_ms=0,
                             artwork_url=d.get("cover"), service_id="radio", permalink=d["url"]))
        return out

    def _toggle_fav(self, t: Track) -> None:
        favs = self.config.data.setdefault("radio_favs", [])
        if any(f["id"] == t.id for f in favs):
            favs[:] = [f for f in favs if f["id"] != t.id]
        else:
            favs.insert(0, {"id": t.id, "title": t.title, "artist": t.artist, "cover": t.artwork_url, "url": t.permalink})
        self.config.save()
        self._render(self._last)

    # ---------- загрузка ----------

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self._loaded:
            self._loaded = True
            self.load()

    def _where(self, on: bool) -> None:
        self.config.data["radio_ru"] = on
        self.config.save()
        self.load()

    def _genre(self, tag: str) -> None:
        self.tag = tag
        for t, b in self.chips.items():
            b.setChecked(t == tag)
        self.load()

    def load(self) -> None:
        self._req += 1
        req = self._req
        clear_layout(self.list)
        self.list.addWidget(muted("Загружаю станции…"))
        country = "RU" if self.where.isChecked() else ""

        def done(tracks):
            if sip.isdeleted(self) or req != self._req:
                return
            self._render(tracks)

        def failed(msg):
            if sip.isdeleted(self) or req != self._req:
                return
            clear_layout(self.list)
            self.list.addWidget(muted(f"Не получилось загрузить: {msg}"))
        run_async(radio.search, self.search.text().strip(), self.tag, country, on_done=done, on_error=failed)

    def _render(self, tracks: list) -> None:
        self._last = tracks
        clear_layout(self.list)
        favs = self.favorites()
        if favs:
            head = QLabel("Избранное")
            head.setFont(font(17, QFont.Weight.Bold, display=True))
            self.list.addWidget(head)
            self._rows(favs)
            head = QLabel("Станции")
            head.setFont(font(17, QFont.Weight.Bold, display=True))
            self.list.addWidget(head)
        if not tracks:
            self.list.addWidget(muted("Ничего не нашлось — попробуйте другое название или «Весь мир»."))
            return
        self._rows(tracks)

    def _rows(self, tracks: list) -> None:
        fav_ids = {f["id"] for f in self.config.data.get("radio_favs", [])}
        for i, t in enumerate(tracks):
            row = TrackRow(t)
            if t.id in fav_ids:
                row.setToolTip("В избранном")
            row.clicked.connect(lambda tr=tracks, k=i: self.play_requested.emit(tr, k))
            row.menu_requested.connect(lambda pos, tr=t: self._menu(tr, pos))
            self.list.addWidget(row)

    def _menu(self, t: Track, pos) -> None:
        menu = QMenu(self)
        fav = any(f["id"] == t.id for f in self.config.data.get("radio_favs", []))
        menu.addAction("Убрать из избранного" if fav else "В избранное").triggered.connect(lambda: self._toggle_fav(t))
        menu.exec(pos)
