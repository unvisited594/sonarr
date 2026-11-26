"""Оверлей поверх игр: маленькая полупрозрачная плашка с треком в углу экрана.

Режимы (config "overlay"): "off", "change" — на 6 секунд при смене трека и по горячей клавише,
"always" — всё время, пока играет музыка. Плашка не перехватывает мышь и фокус, поэтому игре не
мешает. Видна поверх игр в оконном и «полноэкранном оконном» режимах; в эксклюзивном
полноэкранном режиме Windows сама ничего поверх игры не показывает.
"""
from PyQt6.QtCore import QPoint, QPropertyAnimation, QRectF, Qt, QTimer
from PyQt6.QtGui import QColor, QFont, QGuiApplication, QPainter, QPainterPath
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from .theme import font
from .widgets import Cover

MODES = [("off", "Выключен"), ("change", "При смене трека (6 с)"), ("always", "Всегда, пока играет музыка")]
CORNERS = [("top-right", "Справа сверху"), ("top-left", "Слева сверху"), ("bottom-right", "Справа снизу"),
           ("bottom-left", "Слева снизу")]


class GameOverlay(QWidget):
    def __init__(self, player, config) -> None:
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
                         | Qt.WindowType.Tool | Qt.WindowType.WindowDoesNotAcceptFocus
                         | Qt.WindowType.WindowTransparentForInput)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.player, self.config = player, config
        self.setFixedSize(400, 96)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 12, 18, 16)
        lay.setSpacing(12)
        self.cover = Cover(64, 10)
        lay.addWidget(self.cover)
        text = QVBoxLayout()
        text.setSpacing(2)
        self.kicker = QLabel("SONAR")
        self.kicker.setFont(font(10, QFont.Weight.Black))
        self.kicker.setStyleSheet("color: rgba(255,255,255,.55); background: transparent;")
        self.title = QLabel()
        self.title.setFont(font(15, QFont.Weight.Bold))
        self.title.setStyleSheet("color: #ffffff; background: transparent;")
        self.artist = QLabel()
        self.artist.setFont(font(12))
        self.artist.setStyleSheet("color: rgba(255,255,255,.72); background: transparent;")
        for w in (self.kicker, self.title, self.artist):
            w.setTextFormat(Qt.TextFormat.PlainText)
            text.addWidget(w)
        lay.addLayout(text, 1)
        self._progress = 0.0
        self._hide_timer = QTimer(self, singleShot=True, interval=6000)
        self._hide_timer.timeout.connect(self._fade_out)
        self._tick = QTimer(self, interval=500)
        self._tick.timeout.connect(self._update)
        self._anim = QPropertyAnimation(self, b"windowOpacity", self)
        self._anim.setDuration(250)
        player.started.connect(self._on_track)
        player.playing_changed.connect(lambda _on: self._apply())
        self._forced = False

    @property
    def mode(self) -> str:
        return self.config.data.get("overlay", "change")

    @property
    def corner(self) -> str:
        return self.config.data.get("overlay_corner", "top-right")

    def set_mode(self, mode: str) -> None:
        self.config.data["overlay"] = mode
        self.config.save()
        self._apply()

    def set_corner(self, corner: str) -> None:
        self.config.data["overlay_corner"] = corner
        self.config.save()
        self._place()

    def _place(self) -> None:
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return
        g = screen.availableGeometry()
        m = 24
        x = g.right() - self.width() - m if "right" in self.corner else g.left() + m
        y = g.top() + m if "top" in self.corner else g.bottom() - self.height() - m
        self.move(QPoint(x, y))

    def _fill(self) -> None:
        t = self.player.current
        if t is None:
            return
        self.cover.set_url(t.artwork_url)
        fm = self.title.fontMetrics()
        self.title.setText(fm.elidedText(t.title, Qt.TextElideMode.ElideRight, 280))
        self.artist.setText(self.artist.fontMetrics().elidedText(t.artist or "", Qt.TextElideMode.ElideRight, 280))

    def _on_track(self, _track) -> None:
        self._fill()
        if self.mode == "change":
            self.flash()
        else:
            self._apply()

    def flash(self) -> None:
        """Показать на 6 секунд (смена трека или горячая клавиша)."""
        if self.mode == "off" or self.player.current is None:
            return
        self._fill()
        self._show()
        if self.mode != "always":
            self._hide_timer.start()

    def toggle(self) -> None:
        if self.isVisible():
            self._fade_out()
        else:
            self.flash()

    def _apply(self) -> None:
        if self.mode == "always" and self.player.is_playing and self.player.current is not None:
            self._fill()
            self._show()
        elif self.mode in ("off", "always"):
            self._fade_out()   # выключен или музыка на паузе; в режиме «при смене» прячет таймер

    def _show(self) -> None:
        self._place()
        if not self.isVisible():
            self.setWindowOpacity(0.0)
            self.show()
        self._anim.stop()
        self._anim.setStartValue(self.windowOpacity())
        self._anim.setEndValue(0.94)
        self._anim.start()
        self._tick.start()

    def _fade_out(self) -> None:
        if not self.isVisible():
            return
        self._anim.stop()
        self._anim.setStartValue(self.windowOpacity())
        self._anim.setEndValue(0.0)
        try:
            self._anim.finished.disconnect()
        except TypeError:
            pass
        self._anim.finished.connect(lambda: self.hide() if self.windowOpacity() < 0.05 else None)
        self._anim.start()
        self._tick.stop()

    def _update(self) -> None:
        dur = self.player.mp.duration()
        self._progress = (self.player.mp.position() / dur) if dur > 0 else 0.0
        self.update()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        path = QPainterPath()
        path.addRoundedRect(r, 18, 18)
        p.fillPath(path, QColor(12, 12, 16, 215))
        p.setPen(QColor(255, 255, 255, 30))
        p.drawPath(path)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 255, 255, 40))
        p.drawRoundedRect(QRectF(92, r.bottom() - 10, r.width() - 110, 4), 2, 2)
        p.setBrush(QColor(255, 255, 255, 220))
        p.drawRoundedRect(QRectF(92, r.bottom() - 10, (r.width() - 110) * max(0.0, min(1.0, self._progress)), 4), 2, 2)
