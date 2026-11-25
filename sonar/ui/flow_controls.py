"""Элементы настройки фона большого плеера: в настройках и во всплывающей панели плеера."""
from PyQt6.QtCore import QRectF, QSize, Qt, QTimer
from PyQt6.QtGui import QColor, QFont, QIcon, QLinearGradient, QPainter, QPixmap
from PyQt6.QtWidgets import (QButtonGroup, QColorDialog, QGridLayout, QHBoxLayout, QLabel, QPushButton,
                             QSlider, QToolButton, QVBoxLayout, QWidget)

from .flow_settings import COVER, CUSTOM, PRESETS, normalize
from .theme import font


def swatch(colors, size: int = 16, round_: bool = True) -> QPixmap:
    """Кружок с градиентом цветов палитры — значок на кнопке выбора."""
    ratio = 2
    pm = QPixmap(size * ratio, size * ratio)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    grad = QLinearGradient(0, 0, size * ratio, size * ratio)
    for i, c in enumerate(colors):
        grad.setColorAt(i / max(len(colors) - 1, 1), QColor(c))
    p.setBrush(grad)
    p.setPen(Qt.PenStyle.NoPen)
    r = QRectF(0, 0, size * ratio, size * ratio)
    if round_:
        p.drawEllipse(r)
    else:
        p.drawRoundedRect(r, 6 * ratio, 6 * ratio)
    p.end()
    pm.setDevicePixelRatio(ratio)
    return pm


class FlowControls(QWidget):
    """Выбор цветов, свои цвета, размытие, скорость. Меняет FlowSettings и следит за ним."""

    def __init__(self, flow, compact: bool = False, parent=None) -> None:
        super().__init__(parent)
        self.flow = flow
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)

        lay.addWidget(self._title("Цвета"))
        chips = QGridLayout()
        chips.setHorizontalSpacing(8)
        chips.setVerticalSpacing(8)
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.chip_buttons: dict[str, QPushButton] = {}
        options = [(COVER, "Из обложки", None)] + \
                  [(key, p["title"], p["colors"]) for key, p in PRESETS.items()] + [(CUSTOM, "Свои", None)]
        per_row = 2 if compact else 4
        for i, (key, title, colors) in enumerate(options):
            b = QPushButton(title)
            b.setObjectName("chip")
            b.setCheckable(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            if colors:
                b.setIcon(QIcon(swatch(colors)))
                b.setIconSize(QSize(16, 16))
            b.clicked.connect(lambda _=False, k=key: self.flow.set("flow_source", k))
            self.group.addButton(b)
            self.chip_buttons[key] = b
            chips.addWidget(b, i // per_row, i % per_row)
        lay.addLayout(chips)

        self.custom_row = QWidget()
        cr = QHBoxLayout(self.custom_row)
        cr.setContentsMargins(0, 2, 0, 0)
        cr.setSpacing(8)
        self.color_buttons = []
        for i in range(3):
            b = QToolButton()
            b.setObjectName("colorSwatch")
            b.setFixedSize(34, 34)
            b.setIconSize(QSize(26, 26))
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setToolTip("Выбрать цвет")
            b.clicked.connect(lambda _=False, k=i: self._pick(k))
            self.color_buttons.append(b)
            cr.addWidget(b)
        shuffle = QPushButton("Случайные")
        shuffle.setProperty("compact", True)
        shuffle.setCursor(Qt.CursorShape.PointingHandCursor)
        shuffle.clicked.connect(self.flow.randomize_custom)
        cr.addSpacing(6)
        cr.addWidget(shuffle)
        cr.addStretch(1)
        lay.addWidget(self.custom_row)

        lay.addSpacing(4)
        self.blur, self.blur_value = self._slider(lay, "Размытие", "flow_blur")
        self.speed, self.speed_value = self._slider(lay, "Скорость движения", "flow_speed")
        from .widgets import Toggle
        vinyl_row = QHBoxLayout()
        vinyl_row.addWidget(self._title("Обложка-пластинка"))
        vinyl_row.addStretch(1)
        self.vinyl = Toggle()
        self.vinyl.toggled.connect(lambda on: self.flow.set("vinyl", on))
        vinyl_row.addWidget(self.vinyl)
        lay.addLayout(vinyl_row)
        viz_row = QHBoxLayout()
        viz_row.addWidget(self._title("Визуализатор"))
        viz_row.addStretch(1)
        self.viz = Toggle()
        self.viz.setToolTip("Фон и полоски прыгают под бас и ритм трека")
        self.viz.toggled.connect(lambda on: self.flow.set("visualizer", on))
        viz_row.addWidget(self.viz)
        lay.addLayout(viz_row)
        video_row = QHBoxLayout()
        video_row.addWidget(self._title("Видео на фоне"))
        video_row.addStretch(1)
        self.video = Toggle()
        self.video.toggled.connect(lambda on: self.flow.set("video_bg", on))
        video_row.addWidget(self.video)
        lay.addLayout(video_row)
        video_hint = QLabel("Тот же трек с YouTube — клип, если он есть, — беззвучно и в такт музыке. "
                            "Только пока открыт большой плеер.")
        video_hint.setProperty("role", "muted")
        video_hint.setWordWrap(True)
        lay.addWidget(video_hint)
        self.transparency, self.transparency_value = self._slider(lay, "Прозрачность видео", "video_transparency")
        self.transparency.setRange(0, 90)   # совсем прозрачное видео — это просто выключенное видео
        reset = QPushButton("Вернуть как было")
        reset.setObjectName("link")
        reset.setCursor(Qt.CursorShape.PointingHandCursor)
        reset.clicked.connect(self.flow.reset)
        lay.addWidget(reset, 0, Qt.AlignmentFlag.AlignLeft)

        flow.changed.connect(self.sync)
        self.sync()

    @staticmethod
    def _title(text: str) -> QLabel:
        label = QLabel(text)
        label.setFont(font(14, QFont.Weight.Bold))
        return label

    def _slider(self, lay, title: str, key: str):
        head = QHBoxLayout()
        head.addWidget(self._title(title))
        head.addStretch(1)
        value = QLabel()
        value.setProperty("role", "muted")
        head.addWidget(value)
        lay.addLayout(head)
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(0, 100)
        # пишем в настройки, когда ползунок отпустили или сдвинули стрелками: без записи на каждый пиксель
        slider.valueChanged.connect(lambda v, lbl=value: lbl.setText(f"{v}%"))
        slider.valueChanged.connect(lambda v, k=key, s=slider: None if s.isSliderDown() else self.flow.set(k, v))
        slider.sliderMoved.connect(lambda v, k=key: self._live(k, v))
        slider.sliderReleased.connect(lambda k=key, s=slider: self._commit(k, s.value()))
        lay.addWidget(slider)
        return slider, value

    def _commit(self, key: str, value: int) -> None:
        # значение уже стоит в настройках после «живого» перетаскивания: set() его не сохранил бы
        self.flow.config.data[key] = value
        self.flow.config.save()
        self.flow.changed.emit()

    def _live(self, key: str, value: int) -> None:
        """Пока тянем ползунок — меняем фон сразу, но в файл не пишем."""
        self.flow.config.data[key] = value
        self.flow.changed.emit()

    def _pick(self, index: int) -> None:
        colors = list(self.flow.get("flow_custom"))
        chosen = QColorDialog.getColor(QColor(colors[index]), self.window(), "Цвет фона")
        if chosen.isValid():
            colors[index] = chosen.name()
            self.flow.config.data["flow_custom"] = colors
            self.flow.set("flow_source", CUSTOM)
            self.flow.changed.emit()
            self.flow.config.save()

    def sync(self) -> None:
        source = self.flow.get("flow_source")
        for key, b in self.chip_buttons.items():
            b.setChecked(key == source)
        self.custom_row.setVisible(source == CUSTOM)
        for b, c in zip(self.color_buttons, self.flow.get("flow_custom")):
            b.setIcon(QIcon(swatch([c, c], 26)))
        for slider, key in ((self.blur, "flow_blur"), (self.speed, "flow_speed")):
            if not slider.isSliderDown():
                slider.blockSignals(True)
                slider.setValue(int(self.flow.get(key)))
                slider.blockSignals(False)
        self.vinyl.blockSignals(True)
        self.vinyl.setChecked(bool(self.flow.get("vinyl")))
        self.vinyl.blockSignals(False)
        self.viz.blockSignals(True)
        self.viz.setChecked(bool(self.flow.get("visualizer")))
        self.viz.blockSignals(False)
        self.video.blockSignals(True)
        self.video.setChecked(bool(self.flow.get("video_bg")))
        self.video.blockSignals(False)
        if not self.transparency.isSliderDown():
            self.transparency.blockSignals(True)
            self.transparency.setValue(int(self.flow.get("video_transparency")))
            self.transparency.blockSignals(False)
        self.transparency_value.setText(f"{self.transparency.value()}%")
        self.transparency.setEnabled(bool(self.flow.get("video_bg")))
        self.blur_value.setText(f"{self.blur.value()}%")
        self.speed_value.setText(f"{self.speed.value()}%")


class FlowPreview(QWidget):
    """Живое превью фона в настройках."""

    def __init__(self, flow, cover_colors, parent=None) -> None:
        super().__init__(parent)
        self.flow, self._cover_colors = flow, cover_colors
        self.setFixedHeight(220)
        self.setMinimumWidth(360)
        self._t = 0.0
        self._timer = QTimer(self, interval=40)
        self._timer.timeout.connect(self._tick)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._timer.start()

    def hideEvent(self, event) -> None:
        super().hideEvent(event)
        self._timer.stop()  # невидимое превью не тратит процессор

    def _tick(self) -> None:
        self._t += 0.04 * 1.8 * self.flow.speed
        self.update()

    def paintEvent(self, _event) -> None:
        from PyQt6.QtGui import QPainterPath
        from .full_player import paint_flow
        colors, base = self.flow.palette()
        vivid = colors is not None
        if colors is None:
            colors = self._cover_colors()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        clip = QPainterPath()
        clip.addRoundedRect(QRectF(self.rect()), 16, 16)
        p.setClipPath(clip)
        paint_flow(p, self.rect(), normalize(colors), self._t, 0.8, self.flow.blur, base, vivid)
        p.setPen(QColor(255, 255, 255, 200))
        p.setFont(font(13, QFont.Weight.DemiBold))
        p.drawText(self.rect().adjusted(16, 0, -16, -14),
                   Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignLeft, "Так будет выглядеть большой плеер")
