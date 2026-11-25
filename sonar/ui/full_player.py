"""Большой плеер на всё окно: обложка по центру, название, управление.
Фон — плавно движущийся градиент из цветов обложки."""
import math

from PyQt6 import sip
from PyQt6.QtCore import (QEasingCurve, QPoint, QPointF, QPropertyAnimation, QRectF, QSize, Qt,
                          QTimer, pyqtSignal)
from PyQt6.QtGui import QColor, QFont, QImage, QLinearGradient, QPainter, QPainterPath, QRadialGradient
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QMenu, QSlider, QToolButton, QVBoxLayout, QWidget

from ..services import AVAILABLE
from . import icons
from .icons import service_icon
from .theme import C, font
from .anim import pop
from .flow_settings import flow as flow_settings, normalize
from .widgets import Cover, ImageLoader, add_to_playlist_menu, fmt_time

DEFAULT_COLORS = [QColor("#3b2a6e"), QColor("#1d5c74"), QColor("#7a2d4f")]
BG_W, BG_H = 96, 60   # фон считается в маленькой картинке и растягивается: мягко и дёшево
FRAME_MS = 40


def palette_from(image: QImage, count: int = 3) -> list[QColor]:
    """Преобладающие цвета обложки: оттенки по корзинам с весом за насыщенность и яркость."""
    small = image.scaled(32, 32, Qt.AspectRatioMode.IgnoreAspectRatio,
                         Qt.TransformationMode.SmoothTransformation)
    buckets: dict[int, list[float]] = {}
    for y in range(small.height()):
        for x in range(small.width()):
            c = QColor(small.pixel(x, y))
            h, s, v = c.hsvHueF(), c.hsvSaturationF(), c.valueF()
            if v < 0.12:
                continue  # почти чёрное ничего не говорит о характере обложки
            key = int(max(h, 0) * 12) if s > 0.18 else 12
            weight = 0.25 + s * v * 2
            acc = buckets.setdefault(key, [0.0, 0.0, 0.0, 0.0])
            acc[0] += c.redF() * weight
            acc[1] += c.greenF() * weight
            acc[2] += c.blueF() * weight
            acc[3] += weight
    ranked = sorted(buckets.values(), key=lambda a: a[3], reverse=True)[:count]
    colors = [QColor.fromRgbF(a[0] / a[3], a[1] / a[3], a[2] / a[3]) for a in ranked if a[3]]
    if not colors:
        return list(DEFAULT_COLORS)
    while len(colors) < count:  # мало разных цветов: добавляем соседние оттенки
        base = colors[0]
        colors.append(QColor.fromHsvF(((base.hsvHueF() if base.hsvHueF() >= 0 else 0) + 0.08 * len(colors)) % 1,
                                      max(base.hsvSaturationF(), 0.4), base.valueF()))
    out = []
    for c in colors:  # выравниваем: достаточно насыщенно и не слишком ярко, чтобы читался текст
        h = c.hsvHueF() if c.hsvHueF() >= 0 else 0
        out.append(QColor.fromHsvF(h, min(max(c.hsvSaturationF(), 0.35), 0.85),
                                   min(max(c.valueF(), 0.38), 0.72)))
    return out


def hires_url(url: str | None) -> str | None:
    """Для большой обложки просим у сервиса картинку крупнее, чем для карточек."""
    if not url:
        return url
    return (url.replace("-t300x300.", "-t500x500.")            # SoundCloud
               .replace("=w320-h320", "=w600-h600")             # YouTube Music
               .replace("size=300", "size=600"))                 # Navidrome


def _mix(a: QColor, b: QColor, k: float) -> QColor:
    return QColor.fromRgbF(a.redF() + (b.redF() - a.redF()) * k,
                           a.greenF() + (b.greenF() - a.greenF()) * k,
                           a.blueF() + (b.blueF() - a.blueF()) * k)


class FullPlayer(QWidget):
    video_requested = pyqtSignal(object)

    def __init__(self, window, player, likes, volume_slider) -> None:
        super().__init__(window)
        self.player, self.likes, self.bar_volume = player, likes, volume_slider
        # Фон закрашивается целиком: Qt не нужно перерисовывать то, что под нами, на каждом кадре
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._t = 0.0
        self._speed = 0.4   # плавно растёт, когда играет музыка, и затихает на паузе
        self._from = normalize(DEFAULT_COLORS)
        self._to = normalize(DEFAULT_COLORS)
        self._from_base: QColor | None = None   # None — тёмный оттенок самой палитры
        self._to_base: QColor | None = None
        self._vivid = False
        self._cover_colors = normalize(DEFAULT_COLORS)
        self._blend = 1.0
        self._art_url = None
        self._dragging = False
        self._anim: QPropertyAnimation | None = None
        self._timer = QTimer(self)
        self._timer.setInterval(FRAME_MS)
        self._timer.timeout.connect(self._tick)
        self._flow_panel = None
        self._lyrics_panel = None
        self._lyrics_hooked = False
        from .video_bg import VideoBackground
        self.video_bg = VideoBackground(player.manager, self)
        self._sync_ticks = 0
        self.hide()

        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 22, 28, 34)
        lay.setSpacing(0)

        top = QHBoxLayout()
        self.close_btn = self._button("chevron", "Свернуть (Esc)", self.close_player, 40, 22)
        top.addWidget(self.close_btn)
        top.addStretch(1)
        self.source_icon = QLabel()
        self.source = QLabel()
        self.source.setFont(font(13, QFont.Weight.DemiBold))
        _text_color(self.source, "rgba(255,255,255,0.75)")
        top.addWidget(self.source_icon)
        top.addSpacing(6)
        top.addWidget(self.source)
        top.addStretch(1)
        self.flow_btn = self._button("palette", "Настроить фон: цвета, размытие, скорость", self._toggle_flow_panel, 40, 22)
        self.flow_btn.setCheckable(True)
        self.lyrics_set_btn = self._button("settings", "Настроить текст: вид, цвета, шрифт, скорость",
                                           self._toggle_lyrics_panel, 40, 22)
        self.lyrics_set_btn.setCheckable(True)
        self.lyrics_set_btn.hide()   # только когда показан текст песни
        top.addWidget(self.lyrics_set_btn)
        top.addWidget(self.flow_btn)
        lay.addLayout(top)
        lay.addStretch(1)

        self.cover = Cover(360, 18)
        lay.addWidget(self.cover, 0, Qt.AlignmentFlag.AlignHCenter)
        from .lyrics_view import LyricsView
        self.lyrics_view = LyricsView()   # текст песни на месте обложки (караоке)
        self.lyrics_view.seek_requested.connect(self.player.seek)
        self.lyrics_view.hide()
        lay.addWidget(self.lyrics_view, 0, Qt.AlignmentFlag.AlignHCenter)
        self._lyrics_key = None
        lay.addSpacing(28)

        self.title = QLabel()
        self.title.setFont(font(30, QFont.Weight.Black, display=True))
        self.title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        _text_color(self.title, "#ffffff")
        lay.addWidget(self.title)
        lay.addSpacing(4)
        from .widgets import ArtistLabel
        self.artist = ArtistLabel()
        self.artist.setFont(font(16, QFont.Weight.DemiBold))
        self.artist.setAlignment(Qt.AlignmentFlag.AlignCenter)
        _text_color(self.artist, "rgba(255,255,255,0.72)")
        lay.addWidget(self.artist)
        lay.addSpacing(22)

        self.progress_box = QWidget()
        prow = QHBoxLayout(self.progress_box)
        prow.setContentsMargins(0, 0, 0, 0)
        prow.setSpacing(12)
        self.pos_lbl, self.dur_lbl = QLabel("0:00"), QLabel("0:00")
        for lbl in (self.pos_lbl, self.dur_lbl):
            lbl.setFont(font(12, QFont.Weight.DemiBold))
            _text_color(lbl, "rgba(255,255,255,0.72)")
            lbl.setFixedWidth(42)
        self.pos_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setObjectName("bigSlider")
        self.slider.sliderPressed.connect(lambda: setattr(self, "_dragging", True))
        self.slider.sliderReleased.connect(self._seek)
        prow.addWidget(self.pos_lbl)
        prow.addWidget(self.slider, 1)
        prow.addWidget(self.dur_lbl)
        lay.addWidget(self.progress_box, 0, Qt.AlignmentFlag.AlignHCenter)
        lay.addSpacing(16)

        controls = QHBoxLayout()
        controls.setSpacing(22)
        controls.addStretch(1)
        self.like_btn = self._button("heart", "Добавить в мои лайки", self._toggle_like, 44, 22)
        self.like_btn.clicked.connect(lambda: pop(self.like_btn))
        self.prev_btn = self._button("prev", "Предыдущий", player.prev, 52, 28)
        self.play_btn = QToolButton()
        self.play_btn.clicked.connect(lambda: pop(self.play_btn, 0.18))
        self.play_btn.setObjectName("bigPlay")
        self.play_btn.setFixedSize(76, 76)
        self.play_btn.setIconSize(QSize(34, 34))
        self.play_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.play_btn.setToolTip("Играть / пауза (пробел)")
        self.play_btn.clicked.connect(player.toggle)
        self.next_btn = self._button("next", "Следующий", player.next, 52, 28)
        self.repeat_btn = self._button("repeat", "Повторять трек", lambda: None, 44, 22)
        self.repeat_btn.setCheckable(True)
        self.repeat_btn.toggled.connect(player.set_repeat)
        player.repeat_changed.connect(self._sync_repeat)
        self.add_btn = self._button("plus", "Добавить в плейлист", self._playlist_menu, 36, 18)
        for b in (self.like_btn, self.prev_btn, self.play_btn, self.next_btn, self.repeat_btn):
            controls.addWidget(b)
        controls.addStretch(1)
        lay.addLayout(controls)
        lay.addSpacing(14)

        extra = QHBoxLayout()
        extra.setSpacing(10)
        extra.addStretch(1)
        self.video_btn = self._button("video", "Смотреть клип", self._video, 36, 18)
        self.lyrics_btn = self._button("lyrics", "Текст песни", self._toggle_lyrics, 36, 18)
        self.lyrics_btn.setCheckable(True)
        extra.addWidget(self.add_btn)
        extra.addWidget(self.lyrics_btn)
        extra.addWidget(self.video_btn)
        extra.addSpacing(10)
        self.vol_icon = QLabel()
        extra.addWidget(self.vol_icon)
        self.volume = QSlider(Qt.Orientation.Horizontal)
        self.volume.setObjectName("bigSlider")
        self.volume.setRange(0, 100)
        self.volume.setFixedWidth(130)
        self.volume.setValue(volume_slider.value())
        self.volume.valueChanged.connect(volume_slider.setValue)
        volume_slider.valueChanged.connect(self.volume.setValue)
        extra.addWidget(self.volume)
        extra.addStretch(1)
        lay.addLayout(extra)
        lay.addStretch(1)

        player.track_changed.connect(self._on_track)
        player.playing_changed.connect(self._on_playing)
        player.position_changed.connect(self._on_position)
        player.loading_changed.connect(self._on_loading)
        if likes is not None:
            likes.changed.connect(self._update_like)
        window.installEventFilter(self)
        self.apply_theme()

    # ---------- построение ----------

    def _button(self, icon_name, tip, slot, size, icon_size) -> QToolButton:
        b = QToolButton()
        b.setObjectName("bigCtrl")
        b.setFixedSize(size, size)
        b.setIconSize(QSize(icon_size, icon_size))
        b.setToolTip(tip)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.setProperty("icon_name", icon_name)
        b.clicked.connect(slot)
        return b

    def apply_theme(self) -> None:
        # Поверх цветного фона иконки всегда белые; у круглой кнопки — цвет темы.
        for b in (self.close_btn, self.like_btn, self.prev_btn, self.next_btn, self.add_btn, self.video_btn,
                  self.flow_btn, self.lyrics_set_btn):
            b.setIcon(icons.icon(b.property("icon_name"), "#ffffff"))
        self.repeat_btn.setIcon(icons.icon("repeat", "#c8c8c8", "#ffffff"))
        self.lyrics_btn.setIcon(icons.icon("lyrics", "#c8c8c8", "#ffffff"))
        self.vol_icon.setPixmap(icons.pixmap("volume", "#ffffff", 18))
        self._on_playing(self.player.is_playing)
        self._update_like()

    def eventFilter(self, obj, event) -> bool:
        if obj is self.parent() and event.type() == event.Type.Resize and self.isVisible():
            self.setGeometry(self.parent().rect())
        return False

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        # Обложка подстраивается под окно: заметно крупнее на большом экране, влезает на маленьком
        size = int(max(200, min(self.width() * 0.42, self.height() - 420, 520)))
        self.cover.setFixedSize(size, size)
        self.lyrics_view.setFixedSize(int(max(320, min(self.width() - 120, 1000))), size)
        self.progress_box.setFixedWidth(min(max(size + 160, 420), self.width() - 80))
        for panel in (self._flow_panel, self._lyrics_panel):
            if panel is not None:
                panel.move(self.width() - panel.width() - 24, 70)
        self._update_texts()

    # ---------- открыть / закрыть ----------

    def open_player(self) -> None:
        if self.player.current is None:
            return
        parent = self.parent()
        self.setGeometry(parent.rect())
        self._on_track(self.player.current)
        self._apply_lyrics_mode()
        self.show()
        self.raise_()
        self.setFocus()
        self._timer.start()
        self._slide(QPoint(0, parent.height()), QPoint(0, 0))
        self._update_video()
        self._update_viz()

    def close_player(self) -> None:
        if not self.isVisible():
            return
        if self._flow_panel is not None and self._flow_panel.isVisible():
            self._toggle_flow_panel()
        self._slide(self.pos(), QPoint(0, self.parent().height()), on_done=self._hide_now)

    # ---------- визуализатор ----------

    def _viz_wanted(self) -> bool:
        fs = flow_settings()
        return bool(fs is not None and fs.get("visualizer")) and self.isVisible()

    def _update_viz(self) -> None:
        """Звук для визуализатора берём, только пока большой плеер открыт и визуализатор включён."""
        tap = getattr(self.player, "tap", None)
        if tap is None:
            return
        if not hasattr(self, "analyzer"):
            from .audio_tap import Analyzer
            self.analyzer = Analyzer()
            tap.listen("viz", self.analyzer.feed)
            fs = flow_settings()
            if fs is not None:
                fs.changed.connect(self._update_viz)
        tap.need("viz", self._viz_wanted())

    def _viz_levels(self):
        an = getattr(self, "analyzer", None)
        if an is None or not self._viz_wanted():
            return None
        an.decay()
        return an

    def _hide_now(self) -> None:
        tap = getattr(self.player, "tap", None)
        if tap is not None:
            tap.need("viz", False)
        self._timer.stop()
        self.video_bg.stop()   # плеер свёрнут — видео не нужно, трафик не тратим
        self.hide()

    def _update_video(self) -> None:
        """Включить, сменить или выключить видео на фоне — по настройке, треку и видимости плеера."""
        from .visibility import is_offline
        fs = flow_settings()
        track = self.player.current
        want = (fs is not None and fs.get("video_bg") and self.isVisible() and track is not None
                and not is_offline(fs.config))
        if want:
            self.video_bg.start(track, self.player.mp.position())
            self.video_bg.set_playing(self.player.is_playing)
        elif self.video_bg.active:
            self.video_bg.stop()

    def _slide(self, start: QPoint, end: QPoint, on_done=None) -> None:
        if self._anim is not None:
            self._anim.stop()
        self._anim = QPropertyAnimation(self, b"pos", self)
        self._anim.setDuration(280)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.setStartValue(start)
        self._anim.setEndValue(end)
        if on_done:
            self._anim.finished.connect(on_done)
        self._anim.start()

    def keyPressEvent(self, event) -> None:
        key = event.key()
        if key == Qt.Key.Key_Escape:
            self.close_player()
        elif key == Qt.Key.Key_Space:
            self.player.toggle()
        elif key == Qt.Key.Key_Right:
            self.player.next()
        elif key == Qt.Key.Key_Left:
            self.player.prev()
        else:
            super().keyPressEvent(event)

    # ---------- данные трека ----------

    def _on_track(self, track) -> None:
        from .widgets import artist_target
        self._track = track
        if self.isVisible():
            self._update_video()
        self.artist.set_target(*artist_target(track))
        self.cover.set_url(hires_url(track.artwork_url))
        self._update_texts()
        cls = AVAILABLE.get(track.service_id)
        if cls is not None:
            self.source_icon.setPixmap(service_icon(cls, 18))
            self.source.setText(cls.name)
        self.slider.setRange(0, max(track.duration_ms, 1))
        self.slider.setValue(0)
        self.pos_lbl.setText("0:00")
        self.dur_lbl.setText(fmt_time(track.duration_ms))
        service = self.player.manager.get(track.service_id)
        self.video_btn.setVisible(bool(service and service.supports_video))
        self._update_like()
        self._load_palette(track.artwork_url)
        if self.lyrics_view.isVisible() or (self.isVisible() and self._lyrics_wanted()):
            self._load_lyrics()

    def _update_texts(self) -> None:
        track = getattr(self, "_track", None)
        if track is None:
            return
        width = max(200, self.width() - 160)
        self.title.setText(self.title.fontMetrics().elidedText(track.title, Qt.TextElideMode.ElideRight, width))
        self.title.setToolTip(track.title)
        self.artist.setText(self.artist.fontMetrics().elidedText(track.artist, Qt.TextElideMode.ElideRight, width))

    def _load_palette(self, url: str | None) -> None:
        self._art_url = url
        if not url:
            self._cover_colors = normalize(DEFAULT_COLORS)
            self.apply_flow()
            return

        def apply(pm, wanted=url):
            if sip.isdeleted(self) or self._art_url != wanted:
                return
            self._cover_colors = normalize(palette_from(pm.toImage()))
            self.apply_flow()
        ImageLoader.instance().load(url, apply)

    def apply_flow(self) -> None:
        """Цвета фона по настройке: из обложки, готовая палитра или свои."""
        self._update_video()
        fs = flow_settings()
        colors, base = fs.palette() if fs is not None else (None, None)
        self._vivid = colors is not None
        self._set_colors(normalize(colors) if colors else self._cover_colors, base)

    def _set_colors(self, colors: list[QColor], base: QColor | None = None) -> None:
        """Плавный переход от текущих цветов к новым."""
        if [c.name() for c in colors] == [c.name() for c in self._to] and base == self._to_base:
            return  # то же самое: не перезапускаем переход
        self._from_base = self._current_base()
        self._from = self._current_colors()
        self._to = list(colors)
        self._to_base = base
        self._blend = 0.0

    def _current_colors(self) -> list[QColor]:
        k = min(self._blend, 1.0)
        return [_mix(a, b, k) for a, b in zip(self._from, self._to)]

    def _current_base(self) -> QColor:
        k = min(self._blend, 1.0)
        default = _mix(self._current_colors()[-1], QColor("#000000"), 0.45)
        return _mix(self._from_base or default, self._to_base or default, k)

    def _toggle_flow_panel(self) -> None:
        if self._flow_panel is None:
            from PyQt6.QtWidgets import QFrame
            from .flow_controls import FlowControls
            from PyQt6.QtWidgets import QLayout
            panel = QFrame(self)
            panel.setObjectName("flowPanel")
            pl = QVBoxLayout(panel)
            pl.setContentsMargins(18, 16, 18, 16)
            # панель всегда по размеру содержимого: появился ряд «своих» цветов — она выросла
            pl.setSizeConstraint(QLayout.SizeConstraint.SetFixedSize)
            controls = FlowControls(flow_settings(), compact=True)
            controls.setFixedWidth(304)
            pl.addWidget(controls)
            self._flow_panel = panel
        panel = self._flow_panel
        if panel.isVisible():
            panel.hide()
        else:
            self._hide_lyrics_panel()
            panel.adjustSize()
            panel.move(self.width() - panel.width() - 24, 70)
            panel.show()
            panel.raise_()
        self.flow_btn.setChecked(panel.isVisible())

    # ---------- текст песни ----------

    def _lyrics_wanted(self) -> bool:
        fs = flow_settings()
        return bool(fs is not None and fs.get("lyrics_on"))

    def _toggle_lyrics(self) -> None:
        fs = flow_settings()
        if fs is not None:
            fs.set("lyrics_on", self.lyrics_btn.isChecked())
        self._apply_lyrics_mode()

    def _load_translation(self) -> None:
        """Перевод текста — только если включён в настройках текста и песня не на русском."""
        fs = flow_settings()
        got = getattr(self, "_lyrics_obj", None)
        if fs is None or not fs.get("lyrics_translate") or not got or not got[1] or not got[1].lines:
            self.lyrics_view.set_translations(None)
            return
        track, lyr = got
        from .. import lyrics as lyrics_mod
        from ..workers import run_async
        key = self._lyrics_key

        def done(lines):
            if not sip.isdeleted(self) and self._lyrics_key == key:
                self.lyrics_view.set_translations(lines)
        run_async(lyrics_mod.translate, track, lyr, on_done=done, on_error=lambda _m: None)

    def _toggle_lyrics_panel(self) -> None:
        if self._lyrics_panel is None:
            from PyQt6.QtWidgets import QFrame, QScrollArea
            from .lyrics_controls import LyricsControls
            panel = QFrame(self)
            panel.setObjectName("flowPanel")
            pl = QVBoxLayout(panel)
            pl.setContentsMargins(6, 10, 6, 10)
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            inner = QWidget()
            il = QVBoxLayout(inner)
            il.setContentsMargins(12, 6, 12, 6)
            controls = LyricsControls(flow_settings(), compact=True)
            controls.setFixedWidth(304)
            il.addWidget(controls)
            scroll.setWidget(inner)
            pl.addWidget(scroll)
            self._lyrics_panel = panel
        panel = self._lyrics_panel
        if panel.isVisible():
            panel.hide()
        else:
            if self._flow_panel is not None and self._flow_panel.isVisible():
                self._flow_panel.hide()
                self.flow_btn.setChecked(False)
            # настроек много: панель по высоте окна, внутри — прокрутка
            panel.setFixedSize(346, max(260, min(760, self.height() - 110)))
            panel.move(self.width() - panel.width() - 24, 70)
            panel.show()
            panel.raise_()
        self.lyrics_set_btn.setChecked(panel.isVisible())

    def _translation_setting(self) -> None:
        fs = flow_settings()
        want = bool(fs and fs.get("lyrics_translate"))
        if want != (self.lyrics_view.translations is not None or getattr(self, "_tr_wanted", False)):
            self._tr_wanted = want
            self._load_translation()

    def _hide_lyrics_panel(self) -> None:
        if self._lyrics_panel is not None:
            self._lyrics_panel.hide()
        self.lyrics_set_btn.setChecked(False)

    def _apply_lyrics_mode(self) -> None:
        fs = flow_settings()
        if fs is not None and not self._lyrics_hooked:
            fs.changed.connect(lambda: self.lyrics_view.apply_settings(flow_settings()))
            fs.changed.connect(self._translation_setting)
            self._lyrics_hooked = True
        self.lyrics_view.apply_settings(fs)
        on = self._lyrics_wanted()
        self.lyrics_set_btn.setVisible(on)
        if not on:
            self._hide_lyrics_panel()
        self.lyrics_btn.setChecked(on)
        self.lyrics_btn.setToolTip("Показать обложку" if on else "Текст песни")
        self.cover.setVisible(not on)
        self.lyrics_view.setVisible(on)
        if on:
            self._load_lyrics()

    def _load_lyrics(self) -> None:
        track = self.player.current
        if track is None:
            return
        key = (track.service_id, track.id)
        if key == self._lyrics_key:
            return
        self._lyrics_key = key
        self.lyrics_view.set_loading()
        from .. import lyrics
        from ..workers import run_async

        def done(result, wanted=key):
            if not sip.isdeleted(self) and self._lyrics_key == wanted:
                self.lyrics_view.set_lyrics(result)
                self._lyrics_obj = (track, result)
                self._load_translation()

        def failed(_msg, wanted=key):
            if not sip.isdeleted(self) and self._lyrics_key == wanted:
                self._lyrics_key = None   # сеть подвела — попробуем снова при следующем открытии
                self.lyrics_view.set_lyrics(None)
        run_async(lyrics.load, track, on_done=done, on_error=failed)

    def _on_playing(self, on: bool) -> None:
        self.play_btn.setIcon(icons.icon("pause" if on else "play", C("on_accent")))
        self.video_bg.set_playing(on)

    def _sync_repeat(self, on: bool) -> None:
        if self.repeat_btn.isChecked() != on:
            self.repeat_btn.setChecked(on)
        self.repeat_btn.setToolTip("Повтор включён" if on else "Повторять трек")

    def _on_loading(self, loading: bool) -> None:
        track = getattr(self, "_track", None)
        if loading:
            self.artist.setText("Загрузка…")
        elif track is not None:
            self._update_texts()

    def _on_position(self, pos: int, dur: int) -> None:
        if self._dragging:
            return
        if dur and self.slider.maximum() != dur:
            self.slider.setRange(0, dur)
            self.dur_lbl.setText(fmt_time(dur))
        self.slider.setValue(pos)
        self.pos_lbl.setText(fmt_time(pos))

    def _seek(self) -> None:
        self._dragging = False
        self.player.seek(self.slider.value())

    def _update_like(self) -> None:
        track = self.player.current
        liked = bool(track and self.likes and self.likes.contains(track))
        self.like_btn.setIcon(icons.icon("heart_fill" if liked else "heart", "#ffffff"))
        self.like_btn.setToolTip("Убрать из моих лайков" if liked else "Добавить в мои лайки")

    def _toggle_like(self) -> None:
        if self.player.current is not None and self.likes is not None:
            self.likes.toggle(self.player.current)

    def _playlist_menu(self) -> None:
        if self.player.current is None:
            return
        menu = QMenu(self)
        add_to_playlist_menu(menu, self.player.current, self, as_submenu=False)
        menu.exec(self.add_btn.mapToGlobal(QPoint(0, self.add_btn.height())))

    def _video(self) -> None:
        if self.player.current is not None:
            self.close_player()
            self.video_requested.emit(self.player.current)

    # ---------- фон ----------

    def _tick(self) -> None:
        fs_ = flow_settings()
        vinyl = bool(fs_ and fs_.get("vinyl"))
        if self.cover._vinyl != vinyl:
            self.cover.set_vinyl(vinyl)
        if vinyl and self.player.is_playing:
            self.cover.angle = (self.cover.angle + 100 * FRAME_MS / 1000) % 360  # ≈17 об/мин: спокойно
        target = 1.0 if self.player.is_playing else 0.3
        self._speed += (target - self._speed) * 0.05
        fs = flow_settings()
        self._t += FRAME_MS / 1000 * self._speed * 1.8 * (fs.speed if fs is not None else 1.0)
        if self._blend < 1.0:
            self._blend = min(1.0, self._blend + FRAME_MS / 1400)
        if self.lyrics_view.isVisible():
            eq = getattr(self.player, "eq", None)   # звук через эквалайзер чуть запаздывает
            self.lyrics_view.set_position(self.player.mp.position() - (eq.latency_ms() if eq else 0))
        self._sync_ticks += 1
        if self._sync_ticks % 50 == 0 and self.video_bg.active:   # раз в ~2 с сверяем видео с музыкой
            self.video_bg.sync(self.player.mp.position())
        self.update()

    def _paint_bars(self, painter: QPainter, levels) -> None:
        """Спектр полосками по низу экрана — тихо, чтобы не спорить с кнопками."""
        n = len(levels)
        w, h = self.width(), self.height()
        gap = 6
        bw = (w - gap * (n + 1)) / n
        maxh = h * 0.16
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        for i, v in enumerate(levels):
            bh = 4 + float(v) * maxh
            grad = QLinearGradient(0, h - bh, 0, h)
            grad.setColorAt(0, QColor(255, 255, 255, 70))
            grad.setColorAt(1, QColor(255, 255, 255, 10))
            painter.setBrush(grad)
            painter.drawRoundedRect(QRectF(gap + i * (bw + gap), h - bh, bw, bh), 4, 4)
        painter.restore()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        fs = flow_settings()
        an = self._viz_levels()
        paint_flow(painter, self.rect(), self._current_colors(), self._t, self._speed,
                   fs.blur if fs is not None else 0.55, self._current_base(), self._vivid,
                   pulse=an.bass if an is not None else 0.0)
        if an is not None:
            self._paint_bars(painter, an.levels)
        frame = self.video_bg.image(self.width(), self.height()) if self.video_bg.active else None
        if frame is not None:   # видео поверх градиента; пока ролик грузится — виден градиент
            opacity = 1 - (fs.get("video_transparency") if fs is not None else 40) / 100
            painter.setOpacity(opacity)
            painter.drawImage(QPointF((self.width() - frame.width()) / 2, (self.height() - frame.height()) / 2),
                              frame)
            painter.setOpacity(1.0)
            shade = QLinearGradient(0, 0, 0, self.height())   # чтобы текст и кнопки читались на любом кадре
            shade.setColorAt(0, QColor(0, 0, 0, int(70 * opacity)))
            shade.setColorAt(0.55, QColor(0, 0, 0, int(40 * opacity)))
            shade.setColorAt(1, QColor(0, 0, 0, int(150 * opacity)))
            painter.fillRect(self.rect(), shade)
        if not self.cover.isVisible():
            return   # вместо обложки текст песни — тень не нужна
        # мягкая тень под обложкой (круглая — под пластинкой)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        g = QRectF(self.cover.geometry())
        vinyl = self.cover._vinyl
        for i in range(8):
            spread = 4 + i * 5
            painter.setBrush(QColor(0, 0, 0, 14))
            box = g.adjusted(-spread, -spread + 10, spread, spread + 14)
            if vinyl:
                painter.drawEllipse(box)
            else:
                painter.drawRoundedRect(box, 18 + spread, 18 + spread)


def _blob(cx: float, cy: float, radius: float, t: float, seed: int) -> QPainterPath:
    """Бесформенное пятно вместо круга: контур колышется двумя волнами и медленно меняет форму."""
    path = QPainterPath()
    steps = 40
    for k in range(steps + 1):
        a = math.tau * k / steps
        wobble = (0.16 * math.sin(3 * a + t * 0.5 + seed * 1.7)
                  + 0.10 * math.sin(5 * a - t * 0.37 + seed * 2.9)
                  + 0.06 * math.sin(2 * a + t * 0.21 + seed))
        r = radius * (1.0 + wobble)
        x, y = cx + r * math.cos(a), cy + r * math.sin(a)
        if k == 0:
            path.moveTo(x, y)
        else:
            path.lineTo(x, y)
    path.closeSubpath()
    return path


def _text_color(widget, color: str) -> None:
    """Цвет текста только для самого виджета. Стиль без селектора наследует и всплывающая
    подсказка виджета: в светлой теме выходил белый текст на белом фоне подсказки."""
    if not widget.objectName():
        widget.setObjectName(f"fp{id(widget)}")
    widget.setStyleSheet(f"#{widget.objectName()} {{ color: {color}; }}")


def extended_colors(colors: list[QColor], t: float, vivid: bool = False) -> list[QColor]:
    """Базовые цвета + два производных; оттенки дрейфуют по цветовому кругу.
    vivid — яркие палитры: цвета не приглушаются и дрейфуют сильнее."""
    out = []
    # Для обложек добавляем два соседних оттенка — так фон богаче. У готовых палитр цвета подобраны
    # вручную: производные (например, жёлто-зелёный из оранжевого) их только портят.
    derived = [] if vivid else [(colors[0], 0.11), (colors[1 % len(colors)], -0.13)]
    amp = 0.025 if vivid else 0.045
    for i, (c, shift) in enumerate([(c, 0.0) for c in colors] + derived):
        h = c.hsvHueF() if c.hsvHueF() >= 0 else 0.0
        drift = amp * math.sin(t * 0.17 + i * 1.9)
        if vivid:
            sat, val = max(c.hsvSaturationF(), 0.55), max(c.valueF(), 0.8)
        else:
            sat = min(1.0, max(c.hsvSaturationF(), 0.45) * (1.08 if shift else 1.0))
            val = min(0.82, c.valueF() * (1.12 if shift else 1.0))
        out.append(QColor.fromHsvF((h + shift + drift) % 1.0, sat, val))
    return out


def paint_flow(painter: QPainter, rect, base_colors: list[QColor], t: float, speed: float,
               blur: float = 0.55, base: QColor | None = None, vivid: bool = False, pulse: float = 0.0) -> None:
    """Живой градиент: цветовые пятна плывут, перетекают и «дышат».

    Считается в маленькой картинке и растягивается со сглаживанием. blur (0..1) задаёт, насколько
    маленькой: чем сильнее размытие, тем меньше картинка и мягче края пятен.
    base — цвет под пятнами (по умолчанию тёмный оттенок палитры)."""
    colors = extended_colors(base_colors, t, vivid)
    sharp = 1 - blur
    w = int(24 + sharp ** 1.5 * 296)                     # 24 px — туман, 320 px — чёткие кружки
    h = max(24, int(w * rect.height() / max(rect.width(), 1)))
    bg = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
    bg.fill(base if base is not None else _mix(colors[-1], QColor("#000000"), 0.45))
    p = QPainter(bg)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    n = len(colors)
    edge = 0.3 + 0.62 * sharp                            # где пятно начинает таять: у чётких — у самого края
    edge_alpha = int(150 + 90 * sharp)
    for i, color in enumerate(colors):
        # каждое пятно плывёт по своей траектории и перетекает в соседний цвет
        mix = 0.5 + 0.5 * math.sin(t * 0.09 + i * 2.1)
        # яркие палитры смешиваем слабее: жёлтый с фиолетовым дают грязно-серый
        shade = _mix(color, colors[(i + 1) % n], mix * (0.35 if vivid else 1.0))
        angle = t * (0.12 + 0.03 * i) + i * math.tau / n
        wobble = 0.08 * math.sin(t * 0.23 + i * 1.7)
        cx = w * (0.5 + (0.32 + wobble) * math.cos(angle))
        cy = h * (0.5 + (0.4 + wobble) * math.sin(angle * 1.3 + i))
        breath = (0.05 + 0.05 * speed) * math.sin(t * 0.9 + i * 1.3)   # «дыхание» радиуса
        # у ярких палитр пятна чуть меньше: между ними виден тёмный фон, как в «Моей волне»
        # сильнее размытие — шире пятно, иначе туман тускнеет: размытое пятно «теряет» площадь
        radius = w * ((0.31 if vivid else 0.36) + 0.12 * blur + breath) * (1 + 0.16 * min(1.0, pulse))   # удар баса
        # Чётко: заливка шире контура, форму задаёт колышущийся контур (языки пламени).
        # Размыто: заливка затухает раньше контура — края мягкие, без граней.
        fill = radius * (0.68 + 0.62 * sharp ** 2)
        grad = QRadialGradient(QPointF(0, 0), fill)
        outer = QColor(shade)
        outer.setAlpha(0)
        grad.setColorAt(0, shade)
        grad.setColorAt(edge, QColor(shade.red(), shade.green(), shade.blue(), edge_alpha))
        grad.setColorAt(1, outer)
        p.save()
        # пятно вытянуто в эллипс и медленно поворачивается: облако, а не круг
        p.translate(cx, cy)
        p.rotate(math.degrees(t * 0.07 * (1 if i % 2 else -1) + i * 1.3))
        stretch = 1.0 + 0.28 * math.sin(t * 0.13 + i * 2.2)
        p.scale(stretch, 1.0 / stretch)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(grad)
        p.drawPath(_blob(0, 0, radius, t, i))
        p.restore()
    p.end()
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    painter.drawImage(QRectF(rect), bg)
    shade = QLinearGradient(0, 0, 0, rect.height())  # затемнение, чтобы текст читался на любых цветах
    shade.setColorAt(0, QColor(0, 0, 0, 25 if vivid else 40))
    shade.setColorAt(0.5, QColor(0, 0, 0, 0 if vivid else 15))
    shade.setColorAt(1, QColor(0, 0, 0, 110 if vivid else 120))
    painter.fillRect(rect, shade)
