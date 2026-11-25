"""Мини-плеер: появляется, когда главное окно свёрнуто."""
from PyQt6.QtCore import QPoint, QRectF, QSize, Qt
from PyQt6.QtGui import QColor, QFont, QGuiApplication, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QSlider, QToolButton, QVBoxLayout, QWidget

from . import icons
from .theme import C, font
from .widgets import Cover, fmt_time, muted

WIDTH = 360


class MiniPlayer(QWidget):
    def __init__(self, player, config, on_restore, volume_slider=None) -> None:
        # Без родителя: дочернее окно свернулось бы вместе с главным.
        super().__init__(None, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowTitle("Sonar")
        self.player, self.config, self._restore = player, config, on_restore
        self._drag_from: QPoint | None = None
        self._dragging_slider = False
        self.dismissed = False  # закрыли крестиком: до следующего сворачивания не показываем
        self.setFixedWidth(WIDTH)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 14, 14, 12)
        lay.setSpacing(8)

        top = QHBoxLayout()
        top.setSpacing(12)
        self.cover = Cover(64, 10)
        self.cover.setCursor(Qt.CursorShape.PointingHandCursor)
        self.cover.setToolTip("Развернуть Sonar")
        self.cover.clicked.connect(self._restore)
        top.addWidget(self.cover)
        text = QVBoxLayout()
        text.setSpacing(2)
        text.addStretch(1)
        self.title = QLabel()
        self.title.setFont(font(14, QFont.Weight.DemiBold))
        self.artist = muted()
        text.addWidget(self.title)
        text.addWidget(self.artist)
        text.addStretch(1)
        top.addLayout(text, 1)
        side = QVBoxLayout()
        side.setSpacing(2)
        self.expand_btn = self._ctrl("expand", "Развернуть Sonar", self._restore, 26, 14)
        self.close_btn = self._ctrl("close", "Скрыть мини-плеер", self._dismiss, 26, 14)
        side.addWidget(self.close_btn)
        side.addWidget(self.expand_btn)
        side.addStretch(1)
        top.addLayout(side)
        lay.addLayout(top)

        progress = QHBoxLayout()
        progress.setSpacing(8)
        self.pos_lbl, self.dur_lbl = muted("0:00"), muted("0:00")
        for lbl in (self.pos_lbl, self.dur_lbl):
            lbl.setFont(font(11))
            lbl.setFixedWidth(34)
        self.pos_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.sliderPressed.connect(lambda: setattr(self, "_dragging_slider", True))
        self.slider.sliderReleased.connect(self._seek)
        progress.addWidget(self.pos_lbl)
        progress.addWidget(self.slider, 1)
        progress.addWidget(self.dur_lbl)
        lay.addLayout(progress)

        buttons = QHBoxLayout()
        buttons.setSpacing(14)
        buttons.addStretch(1)
        self.repeat_btn = self._ctrl("repeat", "Повторять трек", lambda: None, 32, 18)
        self.repeat_btn.setCheckable(True)
        self.repeat_btn.setChecked(player.repeat)
        self.repeat_btn.toggled.connect(player.set_repeat)
        self.prev_btn = self._ctrl("prev", "Предыдущий", player.prev, 32, 18)
        self.play_btn = QToolButton()
        self.play_btn.setObjectName("ctrlMain")
        self.play_btn.setFixedSize(40, 40)
        self.play_btn.setIconSize(QSize(20, 20))
        self.play_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.play_btn.setToolTip("Играть / пауза")
        self.play_btn.clicked.connect(player.toggle)
        self.next_btn = self._ctrl("next", "Следующий", player.next, 32, 18)
        for b in (self.repeat_btn, self.prev_btn, self.play_btn, self.next_btn):
            buttons.addWidget(b)
        buttons.addStretch(1)
        self.vol_icon = QLabel()
        self.vol_icon.setToolTip("Громкость")
        self.volume = QSlider(Qt.Orientation.Horizontal)
        self.volume.setRange(0, 100)
        self.volume.setFixedWidth(84)
        if volume_slider is not None:  # одна громкость на все плееры
            self.volume.setValue(volume_slider.value())
            self.volume.valueChanged.connect(volume_slider.setValue)
            volume_slider.valueChanged.connect(self.volume.setValue)
        buttons.addWidget(self.vol_icon)
        buttons.addWidget(self.volume)
        lay.addLayout(buttons)

        player.track_changed.connect(self._on_track)
        player.playing_changed.connect(self._on_playing)
        player.position_changed.connect(self._on_position)
        player.repeat_changed.connect(self._sync_repeat)
        self.apply_theme()

    def _ctrl(self, name, tip, slot, size, icon_size) -> QToolButton:
        b = QToolButton()
        b.setObjectName("ctrl")
        b.setFixedSize(size, size)
        b.setIconSize(QSize(icon_size, icon_size))
        b.setToolTip(tip)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.setProperty("icon_name", name)
        b.clicked.connect(slot)
        return b

    def apply_theme(self) -> None:
        for b in (self.prev_btn, self.next_btn, self.expand_btn, self.close_btn):
            b.setIcon(icons.icon(b.property("icon_name"), C("text")))
        self.repeat_btn.setIcon(icons.icon("repeat", C("muted"), C("text")))
        self.vol_icon.setPixmap(icons.pixmap("volume", C("muted"), 18))
        self._on_playing(self.player.is_playing)
        self.update()

    # ---------- показ ----------

    def show_mini(self) -> None:
        if self.player.current is None or self.dismissed:
            return
        self._on_track(self.player.current)
        self.adjustSize()
        self.move(self._position())
        self.show()
        self.raise_()

    def _position(self) -> QPoint:
        screen = QGuiApplication.primaryScreen().availableGeometry()
        saved = self.config.data.get("mini_pos")
        if saved:
            pos = QPoint(*saved)
            if screen.contains(pos) and screen.contains(pos + QPoint(self.width(), self.height())):
                return pos
        return QPoint(screen.right() - self.width() - 24, screen.bottom() - self.height() - 24)

    def _dismiss(self) -> None:
        self.dismissed = True
        self.hide()

    # ---------- перетаскивание за фон ----------

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_from = event.globalPosition().toPoint() - self.pos()

    def mouseMoveEvent(self, event) -> None:
        if self._drag_from is not None:
            self.move(event.globalPosition().toPoint() - self._drag_from)

    def mouseReleaseEvent(self, event) -> None:
        if self._drag_from is not None:
            self._drag_from = None
            self.config.data["mini_pos"] = [self.x(), self.y()]
            self.config.save()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        path = QPainterPath()
        path.addRoundedRect(r, 16, 16)
        p.fillPath(path, QColor(C("panel")))
        p.setPen(QPen(QColor(C("input_border")), 1))
        p.drawPath(path)

    # ---------- данные ----------

    def _on_track(self, track) -> None:
        self.cover.set_url(track.artwork_url)
        width = WIDTH - 14 * 2 - 64 - 12 - 26 - 12
        self.title.setText(self.title.fontMetrics().elidedText(track.title, Qt.TextElideMode.ElideRight, width))
        self.title.setToolTip(track.title)
        self.artist.setText(self.artist.fontMetrics().elidedText(track.artist, Qt.TextElideMode.ElideRight, width))
        self.slider.setRange(0, max(track.duration_ms, 1))
        self.slider.setValue(0)
        self.pos_lbl.setText("0:00")
        self.dur_lbl.setText(fmt_time(track.duration_ms))

    def _on_playing(self, on: bool) -> None:
        self.play_btn.setIcon(icons.icon("pause" if on else "play", C("on_accent")))

    def _on_position(self, pos: int, dur: int) -> None:
        if self._dragging_slider:
            return
        if dur and self.slider.maximum() != dur:
            self.slider.setRange(0, dur)
            self.dur_lbl.setText(fmt_time(dur))
        self.slider.setValue(pos)
        self.pos_lbl.setText(fmt_time(pos))

    def _seek(self) -> None:
        self._dragging_slider = False
        self.player.seek(self.slider.value())

    def _sync_repeat(self, on: bool) -> None:
        if self.repeat_btn.isChecked() != on:
            self.repeat_btn.setChecked(on)
