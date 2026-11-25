"""Настройки текста песни: вид, цвета, шрифт, выравнивание, скорость, сдвиг, прокрутка.
Одни и те же элементы — во всплывающей панели большого плеера и во вкладке «Плеер» настроек."""
import time

from PyQt6.QtCore import QSize, Qt, QTimer
from PyQt6.QtGui import QColor, QFont, QIcon, QLinearGradient, QPainter
from PyQt6.QtWidgets import (QButtonGroup, QColorDialog, QFontComboBox, QGridLayout, QHBoxLayout, QLabel,
                             QPushButton, QSlider, QToolButton, QVBoxLayout, QWidget)

from .flow_controls import swatch
from .theme import font

STYLES = [("dotify", "Как в Dotify"), ("karaoke", "Караоке")]
ALIGNS = [("left", "Слева"), ("center", "По центру")]
# Готовые пары: (название, цвет текста, цвет спетого)
COLOR_PRESETS = [("Белый и чёрный", "#ffffff", "#000000"), ("Белый и золото", "#ffffff", "#ffc93c"),
                 ("Неон", "#9ef6ff", "#ff2bd6"), ("Мягкий", "#bfc4d6", "#ffffff"), ("Тёмный", "#1c1c22", "#ffffff")]
# Ползунки: ключ → (подпись, мин, макс, шаг, как показывать значение)
SLIDERS = {
    "lyrics_size": ("Размер", 16, 64, 1, lambda v: f"{v} px"),
    "lyrics_speed": ("Скорость заливки", 25, 300, 5, lambda v: f"{v}%"),
    "lyrics_offset": ("Сдвиг по времени", -3000, 3000, 100,
                      lambda v: "без сдвига" if v == 0 else f"{'раньше' if v > 0 else 'позже'} на {abs(v) / 1000:.1f} с"),
    "lyrics_scroll": ("Плавность прокрутки", 0, 100, 5, lambda v: f"{v}%"),
}
DEMO_LRC = """[00:00.50]Тёплый свет в окне напротив
[00:04.00]Город тихо засыпает
[00:07.50]Я включаю нашу волну
[00:11.00]И слова плывут по кругу
[00:14.50]Строка за строкой, буква за буквой
"""


class LyricsControls(QWidget):
    """Меняет настройки lyrics_* во FlowSettings и следит за ними."""

    def __init__(self, flow, compact: bool = False, parent=None) -> None:
        super().__init__(parent)
        self.flow = flow
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)

        lay.addWidget(self._title("Вид"))
        self.style_buttons = self._chips(lay, STYLES, "lyrics_style", 2)

        lay.addWidget(self._title("Цвета"))
        colors = QHBoxLayout()
        colors.setSpacing(8)
        self.color_buttons = {}
        for key, tip in (("lyrics_color", "Цвет текста (ещё не спето)"), ("lyrics_sung", "Цвет спетого")):
            b = QToolButton()
            b.setObjectName("colorSwatch")
            b.setFixedSize(34, 34)
            b.setIconSize(QSize(26, 26))
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setToolTip(tip)
            b.clicked.connect(lambda _=False, k=key, t=tip: self._pick(k, t))
            self.color_buttons[key] = b
            colors.addWidget(b)
            label = QLabel("текст" if key == "lyrics_color" else "спетое")
            label.setProperty("role", "muted")
            colors.addWidget(label)
            colors.addSpacing(6)
        colors.addStretch(1)
        lay.addLayout(colors)
        presets = QGridLayout()
        presets.setHorizontalSpacing(8)
        presets.setVerticalSpacing(8)
        per_row = 2 if compact else 3
        for i, (title, a, b) in enumerate(COLOR_PRESETS):
            btn = QPushButton(title)
            btn.setObjectName("chip")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setIcon(QIcon(swatch([a, b])))
            btn.setIconSize(QSize(16, 16))
            btn.clicked.connect(lambda _=False, a=a, b=b: self._preset(a, b))
            presets.addWidget(btn, i // per_row, i % per_row)
        lay.addLayout(presets)
        self.halo = self._toggle(lay, "Обводка букв", "lyrics_halo")
        self.translate = self._toggle(lay, "Перевод на русский под строками", "lyrics_translate")

        lay.addSpacing(4)
        lay.addWidget(self._title("Шрифт"))
        font_row = QHBoxLayout()
        self.font_box = QFontComboBox()
        self.font_box.setEditable(False)
        self.font_box.setMinimumWidth(150)
        self.font_box.currentFontChanged.connect(lambda f: self.flow.set("lyrics_font", f.family()))
        font_row.addWidget(self.font_box, 1)
        default_font = QPushButton("Как в Sonar")
        default_font.setProperty("compact", True)
        default_font.setCursor(Qt.CursorShape.PointingHandCursor)
        default_font.setToolTip("Шрифт заголовков самого Sonar")
        default_font.clicked.connect(lambda: self.flow.set("lyrics_font", ""))
        font_row.addWidget(default_font)
        lay.addLayout(font_row)
        self.sliders = {}
        self._slider(lay, "lyrics_size")
        self.bold = self._toggle(lay, "Жирный", "lyrics_bold")

        lay.addWidget(self._title("Выравнивание"))
        self.align_buttons = self._chips(lay, ALIGNS, "lyrics_align", 2)

        lay.addSpacing(4)
        self._slider(lay, "lyrics_speed")
        hint = QLabel("Как быстро буквы заливаются цветом в караоке.")
        hint.setProperty("role", "muted")
        hint.setWordWrap(True)
        lay.addWidget(hint)
        self._slider(lay, "lyrics_offset")
        hint = QLabel("Если текст спешит или отстаёт от песни — подвиньте его здесь.")
        hint.setProperty("role", "muted")
        hint.setWordWrap(True)
        lay.addWidget(hint)
        self._slider(lay, "lyrics_scroll")

        reset = QPushButton("Вернуть как было")
        reset.setObjectName("link")
        reset.setCursor(Qt.CursorShape.PointingHandCursor)
        reset.clicked.connect(self.flow.reset_lyrics)
        lay.addWidget(reset, 0, Qt.AlignmentFlag.AlignLeft)

        flow.changed.connect(self.sync)
        self.sync()

    # ---------- строительные блоки ----------

    @staticmethod
    def _title(text: str) -> QLabel:
        label = QLabel(text)
        label.setFont(font(14, QFont.Weight.Bold))
        return label

    def _chips(self, lay, options, key: str, per_row: int) -> dict:
        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(8)
        group = QButtonGroup(self)
        group.setExclusive(True)
        buttons = {}
        for i, (value, title) in enumerate(options):
            b = QPushButton(title)
            b.setObjectName("chip")
            b.setCheckable(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _=False, k=key, v=value: self.flow.set(k, v))
            group.addButton(b)
            buttons[value] = b
            grid.addWidget(b, i // per_row, i % per_row)
        lay.addLayout(grid)
        return buttons

    def _toggle(self, lay, title: str, key: str):
        from .widgets import Toggle
        row = QHBoxLayout()
        row.addWidget(self._title(title))
        row.addStretch(1)
        t = Toggle()
        t.toggled.connect(lambda on, k=key: self.flow.set(k, on))
        row.addWidget(t)
        lay.addLayout(row)
        return t

    def _slider(self, lay, key: str) -> None:
        title, lo, hi, step, fmt = SLIDERS[key]
        head = QHBoxLayout()
        head.addWidget(self._title(title))
        head.addStretch(1)
        value = QLabel()
        value.setProperty("role", "muted")
        head.addWidget(value)
        lay.addLayout(head)
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(lo, hi)
        slider.setSingleStep(step)
        slider.setPageStep(step * 5)
        slider.valueChanged.connect(lambda v, lbl=value, f=fmt: lbl.setText(f(v)))
        # пишем в файл, когда ползунок отпустили или сдвинули стрелками; пока тянем — меняем вживую
        slider.valueChanged.connect(lambda v, k=key, s=slider: None if s.isSliderDown() else self.flow.set(k, v))
        slider.sliderMoved.connect(lambda v, k=key: self._live(k, v))
        slider.sliderReleased.connect(lambda k=key, s=slider: self._commit(k, s.value()))
        lay.addWidget(slider)
        self.sliders[key] = (slider, value, fmt)

    # ---------- действия ----------

    def _live(self, key: str, value: int) -> None:
        self.flow.config.data[key] = value
        self.flow.changed.emit()

    def _commit(self, key: str, value: int) -> None:
        self.flow.config.data[key] = value
        self.flow.config.save()
        self.flow.changed.emit()

    def _pick(self, key: str, title: str) -> None:
        chosen = QColorDialog.getColor(QColor(self.flow.get(key)), self.window(), title)
        if chosen.isValid():
            self.flow.set(key, chosen.name())

    def _preset(self, text: str, sung: str) -> None:
        self.flow.config.data["lyrics_color"] = text
        self.flow.config.data["lyrics_sung"] = sung
        self.flow.config.save()
        self.flow.changed.emit()

    def sync(self) -> None:
        for key, buttons in (("lyrics_style", self.style_buttons), ("lyrics_align", self.align_buttons)):
            current = self.flow.get(key)
            for value, b in buttons.items():
                b.setChecked(value == current)
        for key, b in self.color_buttons.items():
            c = self.flow.get(key)
            b.setIcon(QIcon(swatch([c, c], 26)))
        for key, toggle in (("lyrics_halo", self.halo), ("lyrics_bold", self.bold),
                            ("lyrics_translate", self.translate)):
            toggle.blockSignals(True)
            toggle.setChecked(bool(self.flow.get(key)))
            toggle.blockSignals(False)
        family = self.flow.get("lyrics_font")
        self.font_box.blockSignals(True)
        # без своего шрифта показываем тот, которым рисует Sonar
        self.font_box.setCurrentFont(QFont(family) if family else font(14, display=True))
        self.font_box.blockSignals(False)
        for key, (slider, label, fmt) in self.sliders.items():
            if not slider.isSliderDown():
                slider.blockSignals(True)
                slider.setValue(int(self.flow.get(key)))
                slider.blockSignals(False)
            label.setText(fmt(slider.value()))


class LyricsPreview(QWidget):
    """Живое превью в настройках: свои строки на тёмном фоне, идут по кругу."""

    def __init__(self, flow, parent=None) -> None:
        super().__init__(parent)
        from .. import lyrics
        from .lyrics_view import LyricsView
        self.flow = flow
        self.setFixedHeight(230)
        self.view = LyricsView(self)
        self.view.scale = 0.75
        self.view.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.demo = lyrics.parse_lrc(DEMO_LRC).finish(18500)
        self.view.set_lyrics(self.demo)
        self.view.apply_settings(flow)
        flow.changed.connect(lambda: self.view.apply_settings(flow))
        self._t0 = time.monotonic() - 4.5   # сразу с середины: видно и спетое, и будущее
        self._timer = QTimer(self)
        self._timer.setInterval(33)
        self._timer.timeout.connect(self._tick)

    def showEvent(self, event) -> None:
        self._timer.start()
        super().showEvent(event)

    def hideEvent(self, event) -> None:
        self._timer.stop()
        super().hideEvent(event)

    def resizeEvent(self, event) -> None:
        self.view.setGeometry(self.rect().adjusted(12, 12, -12, -12))
        super().resizeEvent(event)

    def _tick(self) -> None:
        ms = int((time.monotonic() - self._t0) * 1000) % 18500
        self.view.set_position(ms - self.view.offset)   # в превью сдвиг не нужен: оно и так «в такт»

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        g = QLinearGradient(0, 0, self.width(), self.height())
        g.setColorAt(0, QColor("#3b2a6e"))
        g.setColorAt(0.55, QColor("#7a3b5e"))
        g.setColorAt(1, QColor("#c46a2f"))
        p.setBrush(g)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(self.rect(), 16, 16)
