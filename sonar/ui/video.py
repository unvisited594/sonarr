"""Окно для просмотра клипов."""
from PyQt6.QtCore import QSize, Qt, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices, QFont
from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer
from PyQt6.QtMultimediaWidgets import QVideoWidget
from PyQt6.QtWidgets import (QHBoxLayout, QLabel, QPushButton, QSlider, QStackedLayout,
                             QToolButton, QVBoxLayout, QWidget)

from ..workers import run_async
from . import icons
from .theme import C, font
from .widgets import fmt_time, muted


class _Video(QVideoWidget):
    double_clicked = pyqtSignal()

    def mouseDoubleClickEvent(self, event) -> None:
        self.double_clicked.emit()


class VideoWindow(QWidget):
    def __init__(self, manager, parent=None) -> None:
        super().__init__(parent, Qt.WindowType.Window)
        self.setObjectName("videoWindow")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.resize(1024, 640)
        self.manager = manager
        self._req = 0
        self._page: str | None = None
        self._start_ms = 0
        self._dragging = False

        self.mp = QMediaPlayer(self)
        self.out = QAudioOutput(self)
        self.mp.setAudioOutput(self.out)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        screen = QWidget()
        self.stack = QStackedLayout(screen)
        self.video = _Video()
        self.video.double_clicked.connect(self.toggle_fullscreen)
        self.mp.setVideoOutput(self.video)
        self.status = QLabel()
        self.status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status.setWordWrap(True)
        self.status.setFont(font(15, QFont.Weight.DemiBold))
        self.status.setObjectName("videoStatus")
        self.stack.addWidget(self.video)
        self.stack.addWidget(self.status)
        lay.addWidget(screen, 1)

        self.controls = QWidget()
        self.controls.setObjectName("videoControls")
        self.controls.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        bar = QHBoxLayout(self.controls)
        bar.setContentsMargins(16, 10, 16, 12)
        bar.setSpacing(12)
        self.play_btn = QToolButton()
        self.play_btn.setObjectName("ctrlMain")
        self.play_btn.setFixedSize(40, 40)
        self.play_btn.setIconSize(QSize(20, 20))
        self.play_btn.setIcon(icons.icon("play", C("on_accent")))
        self.play_btn.clicked.connect(self.toggle)
        self.title = QLabel()
        self.title.setFont(font(14, QFont.Weight.DemiBold))
        self.pos_lbl, self.dur_lbl = muted("0:00"), muted("0:00")
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.sliderPressed.connect(lambda: setattr(self, "_dragging", True))
        self.slider.sliderReleased.connect(self._seek)
        open_btn = QPushButton("Открыть на YouTube")
        open_btn.clicked.connect(self._open_page)
        bar.addWidget(self.play_btn)
        bar.addWidget(self.title)
        bar.addWidget(self.pos_lbl)
        bar.addWidget(self.slider, 1)
        bar.addWidget(self.dur_lbl)
        bar.addWidget(open_btn)
        lay.addWidget(self.controls)

        self.mp.playbackStateChanged.connect(lambda s: self.play_btn.setIcon(icons.icon(
            "pause" if s == QMediaPlayer.PlaybackState.PlayingState else "play", C("on_accent"))))
        self.mp.positionChanged.connect(self._on_position)
        self.mp.durationChanged.connect(lambda d: (self.slider.setRange(0, d),
                                                   self.dur_lbl.setText(fmt_time(d))))
        self.mp.mediaStatusChanged.connect(self._on_status)
        self.mp.errorOccurred.connect(lambda _e, text: self._show_status(
            f"Не удалось воспроизвести клип: {text}"))

    def open(self, track, start_ms: int = 0, volume: float = 0.7) -> None:
        self.play_btn.setIcon(icons.icon("play", C("on_accent")))  # тема могла смениться
        self._req += 1
        req = self._req
        self.mp.stop()
        self.mp.setSource(QUrl())
        self.out.setVolume(volume)
        self._start_ms = start_ms
        self._page = track.permalink
        self.setWindowTitle(f"{track.title} — {track.artist}" if track.artist else track.title)
        self.title.setText(self.title.fontMetrics().elidedText(
            track.title, Qt.TextElideMode.ElideRight, 260))
        self._show_status("Загружаем клип…")
        self.show()
        self.raise_()
        self.activateWindow()
        service = self.manager.get(track.service_id)
        if service is None:
            self._show_status("Сервис этого трека отключён.")
            return
        run_async(service.video_stream, track,
                  on_done=lambda res: self._resolved(req, res),
                  on_error=lambda err: req == self._req and self._show_status(err))

    def _resolved(self, req: int, result) -> None:
        if req != self._req or not self.isVisible():
            return
        stream, self._page = result
        self.stack.setCurrentWidget(self.video)
        self.mp.setSource(QUrl(stream))
        self.mp.play()

    def _on_status(self, status) -> None:
        if status == QMediaPlayer.MediaStatus.BufferedMedia and self._start_ms:
            self.mp.setPosition(self._start_ms)  # продолжаем с того места, где была песня
            self._start_ms = 0

    def _show_status(self, text: str) -> None:
        self.status.setText(text)
        self.stack.setCurrentWidget(self.status)

    def _on_position(self, pos: int) -> None:
        if not self._dragging:
            self.slider.setValue(pos)
        self.pos_lbl.setText(fmt_time(pos))

    def _seek(self) -> None:
        self._dragging = False
        self.mp.setPosition(self.slider.value())

    def _open_page(self) -> None:
        if self._page:
            QDesktopServices.openUrl(QUrl(self._page))
            self.mp.pause()

    def toggle(self) -> None:
        if self.mp.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.mp.pause()
        else:
            self.mp.play()

    def toggle_fullscreen(self) -> None:
        if self.isFullScreen():
            self.showNormal()
            self.controls.show()
        else:
            self.controls.hide()
            self.showFullScreen()

    def keyPressEvent(self, event) -> None:
        key = event.key()
        if key == Qt.Key.Key_Escape and self.isFullScreen():
            self.toggle_fullscreen()
        elif key == Qt.Key.Key_F:
            self.toggle_fullscreen()
        elif key == Qt.Key.Key_Space:
            self.toggle()
        else:
            super().keyPressEvent(event)

    def closeEvent(self, event) -> None:
        self._req += 1
        self.mp.stop()
        if self.isFullScreen():
            self.showNormal()
            self.controls.show()
        super().closeEvent(event)
