import datetime

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (QHBoxLayout, QLabel, QMessageBox, QPushButton, QScrollArea,
                             QVBoxLayout, QWidget)

from ..services import AVAILABLE
from .icons import service_icon
from .theme import font
from .visibility import visible
from .widgets import tracks_word, TrackRow, clear_layout, muted, show_track_menu

MONTHS = ("января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа",
          "сентября", "октября", "ноября", "декабря")


def day_title(day: datetime.date) -> str:
    today = datetime.date.today()
    if day == today:
        return "Сегодня"
    if day == today - datetime.timedelta(days=1):
        return "Вчера"
    title = f"{day.day} {MONTHS[day.month - 1]}"
    return title if day.year == today.year else f"{title} {day.year}"


class HistoryPage(QWidget):
    play_requested = pyqtSignal(list, int)
    video_requested = pyqtSignal(object)

    def __init__(self, history, manager, config, parent=None) -> None:
        super().__init__(parent)
        self.history, self.manager, self.config = history, manager, config
        self._dirty = True

        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 32, 28, 0)
        outer.setSpacing(6)
        head = QHBoxLayout()
        title = QLabel("Прослушанное")
        title.setFont(font(40, QFont.Weight.Black, display=True))
        head.addWidget(title)
        head.addStretch(1)
        self.clear_btn = QPushButton("Очистить")
        self.clear_btn.setProperty("compact", True)
        self.clear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.clear_btn.clicked.connect(self._clear)
        head.addWidget(self.clear_btn, 0, Qt.AlignmentFlag.AlignVCenter)
        outer.addLayout(head)
        outer.addWidget(muted("Треки, которые вы слушали в Sonar, из всех сервисов"))
        self.stats = muted()
        self.stats.setProperty("role", "help")
        outer.addWidget(self.stats)
        outer.addSpacing(12)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        content = QWidget()
        self.list = QVBoxLayout(content)
        self.list.setContentsMargins(0, 0, 8, 28)
        self.list.setSpacing(2)
        scroll.setWidget(content)
        outer.addWidget(scroll, 1)

        history.changed.connect(self.refresh)
        manager.changed.connect(self.refresh)

    def refresh(self) -> None:
        # Пока страница скрыта, не перерисовываем на каждый трек: отложим до показа.
        if not self.isVisible():
            self._dirty = True
            return
        self._render()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._dirty:
            self._render()

    def _render(self) -> None:
        self._dirty = False
        clear_layout(self.list)
        st = self.history.stats(7)
        if st["tracks"]:
            hours = st["hours"]
            spent = f"около {hours:.0f} ч".replace(".", ",") if hours >= 1 else f"около {max(1, round(hours * 60))} мин"
            top = f" · чаще всего — {st['top_artist']}" if st["top_artist"] else ""
            self.stats.setText(f"За 7 дней: {tracks_word(st['tracks'])} · {spent}{top}")
        else:
            self.stats.setText("За 7 дней ничего не слушали")
        items = self.history.tracks(self.manager)
        keep = {id(t) for t in visible([t for t, _ in items], self.config)}
        items = [(t, at) for t, at in items if id(t) in keep]
        self.clear_btn.setVisible(bool(self.history.entries))
        if not items:
            empty = muted("Здесь появятся треки, которые вы послушаете." if not self.history.entries
                          else "Все треки в истории сейчас недоступны.")
            self.list.addWidget(empty)
            self.list.addStretch(1)
            return
        tracks = [t for t, _ in items]
        icons_cache = {sid: service_icon(cls, 18) for sid, cls in AVAILABLE.items()}
        current_day = None
        for i, (track, played_at) in enumerate(items):
            day = datetime.date.fromtimestamp(played_at)
            if day != current_day:
                current_day = day
                header = QLabel(day_title(day))
                header.setFont(font(17, QFont.Weight.Bold, display=True))
                header.setContentsMargins(8, 18 if i else 0, 0, 6)
                self.list.addWidget(header)
            row = TrackRow(track, icons_cache.get(track.service_id))
            if track.playable:
                row.clicked.connect(lambda i=i: self.play_requested.emit(tracks, i))
            service_cls = AVAILABLE.get(track.service_id)
            row.menu_requested.connect(lambda pos, i=i, c=service_cls: show_track_menu(
                self, tracks, i, pos, bool(c and c.supports_video),
                self.play_requested.emit, self.video_requested.emit))
            self.list.addWidget(row)
        self.list.addStretch(1)

    def _clear(self) -> None:
        answer = QMessageBox.question(self, "Очистить историю",
                                      "Удалить все треки из «Прослушанного»?")
        if answer == QMessageBox.StandardButton.Yes:
            self.history.clear()
