"""Эквалайзер: 10 полос, пресеты, предусилитель.

Как устроено. Qt-плеер сам по себе звук обрабатывать не умеет, поэтому, когда эквалайзер
включён, звук идёт обходным путём:
    QMediaPlayer → QAudioBufferOutput (готовые сэмплы) → наш фильтр (numpy) → QAudioSink → колонки.
Обычный QAudioOutput в это время отцеплен от плеера, но продолжает хранить громкость и
устройство: звук эквалайзера берёт их оттуда, так что ползунок громкости, затухания и выбор
наушников работают как раньше. Выключили эквалайзер (или все полосы на нуле) — плеер снова
играет напрямую, без обходного пути и без задержки.

Фильтр — линейно-фазовый КИХ из 2047 точек, собранный из АЧХ десяти полосовых фильтров
(низкая и высокая полки по краям, колоколы в середине), свёртка через FFT (overlap-save).
Задержка около 21 мс плюс буфер вывода; на эту задержку большой плеер сдвигает текст песни.

Если на каком-то компьютере сэмплы из плеера не приходят (бывает с редкими драйверами), через
полторы секунды тишины эквалайзер сам выключается и звук идёт напрямую.
"""
import logging
import math
import time

import numpy as np
from PyQt6.QtCore import QObject, QTimer, Qt, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtMultimedia import QAudio, QAudioFormat, QAudioSink, QMediaPlayer
from PyQt6.QtWidgets import (QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QSlider, QVBoxLayout, QWidget)

from .theme import font

log = logging.getLogger("sonar.eq")

BANDS = [31, 62, 125, 250, 500, 1000, 2000, 4000, 8000, 16000]
BAND_LABELS = ["31", "62", "125", "250", "500", "1K", "2K", "4K", "8K", "16K"]
MAX_DB = 12
TAPS = 2047
PRESETS = {
    "flat": ("Ровно", [0] * 10),
    "bass": ("Бас", [7, 6, 5, 3, 1, 0, 0, 0, 0, 0]),
    "bass_max": ("Больше баса", [10, 9, 7, 4, 1, 0, -1, -1, 0, 0]),
    "vocal": ("Вокал", [-2, -2, -1, 1, 3, 4, 4, 3, 1, 0]),
    "night": ("Ночь", [-4, -3, -1, 0, 1, 1, 0, -2, -4, -6]),
    "electro": ("Электроника", [6, 5, 2, 0, -2, 0, 1, 3, 5, 6]),
    "rock": ("Рок", [5, 4, 2, -1, -2, -1, 2, 4, 5, 5]),
    "hiphop": ("Хип-хоп", [6, 5, 3, 2, -1, -1, 1, 0, 2, 3]),
    "acoustic": ("Акустика", [3, 3, 2, 1, 1, 1, 2, 3, 2, 1]),
    "clarity": ("Чёткость", [0, 0, -1, -1, 0, 1, 3, 5, 6, 5]),
}
DEFAULT = {"on": False, "preset": "flat", "gains": [0] * 10, "preamp": 0.0}


# ---------- расчёт фильтра ----------

def _biquad_mag(kind: str, f0: float, gain_db: float, q: float, sr: float, w: np.ndarray) -> np.ndarray:
    """|H| фильтра RBJ (Audio EQ Cookbook) на частотах w (рад/сэмпл)."""
    a = 10 ** (gain_db / 40)
    w0 = 2 * math.pi * f0 / sr
    cw, sw = math.cos(w0), math.sin(w0)
    alpha = sw / (2 * q)
    if kind == "peak":
        b = [1 + alpha * a, -2 * cw, 1 - alpha * a]
        aa = [1 + alpha / a, -2 * cw, 1 - alpha / a]
    else:
        sq = 2 * math.sqrt(a) * alpha
        if kind == "low":
            b = [a * ((a + 1) - (a - 1) * cw + sq), 2 * a * ((a - 1) - (a + 1) * cw), a * ((a + 1) - (a - 1) * cw - sq)]
            aa = [(a + 1) + (a - 1) * cw + sq, -2 * ((a - 1) + (a + 1) * cw), (a + 1) + (a - 1) * cw - sq]
        else:
            b = [a * ((a + 1) + (a - 1) * cw + sq), -2 * a * ((a - 1) + (a + 1) * cw), a * ((a + 1) + (a - 1) * cw - sq)]
            aa = [(a + 1) - (a - 1) * cw + sq, 2 * ((a - 1) - (a + 1) * cw), (a + 1) - (a - 1) * cw - sq]
    z1, z2 = np.exp(-1j * w), np.exp(-2j * w)
    return np.abs((b[0] + b[1] * z1 + b[2] * z2) / (aa[0] + aa[1] * z1 + aa[2] * z2))


def response(gains: list[float], preamp_db: float, sr: float, freqs: np.ndarray) -> np.ndarray:
    """Итоговая АЧХ (в разах) на частотах freqs (Гц)."""
    w = 2 * math.pi * np.clip(freqs, 1, sr / 2 - 1) / sr
    mag = np.full(len(freqs), 10 ** (preamp_db / 20), dtype=np.float64)
    for i, (f0, g) in enumerate(zip(BANDS, gains)):
        if abs(g) < 0.05 or f0 >= sr / 2:
            continue
        kind = "low" if i == 0 else ("high" if i == len(BANDS) - 1 else "peak")
        mag *= _biquad_mag(kind, f0, g, 0.75 if kind != "peak" else 1.1, sr, w)
    return mag


def design(gains: list[float], preamp_db: float, sr: float, taps: int = TAPS) -> np.ndarray:
    """Линейно-фазовый КИХ с нужной АЧХ: частотная выборка + окно Блэкмана."""
    n = 1 << int(math.ceil(math.log2(taps * 4)))
    freqs = np.fft.rfftfreq(n, 1 / sr)
    h = np.fft.irfft(response(gains, preamp_db, sr, freqs), n)
    h = np.roll(h, taps // 2)[:taps] * np.blackman(taps)
    return h.astype(np.float32)


def auto_preamp(gains: list[float]) -> float:
    """Запас по громкости, чтобы подъём полос не давал хрипа."""
    top = max([0.0] + [float(g) for g in gains])
    return -round(top * 0.8, 1)


class Fir:
    """Потоковая свёртка (overlap-save) для нескольких каналов сразу."""

    def __init__(self, h: np.ndarray, channels: int) -> None:
        self.h = h
        self.channels = channels
        self.tail = np.zeros((len(h) - 1, channels), dtype=np.float32)
        self._spec_n = 0
        self._spec = None

    def reset(self) -> None:
        self.tail[:] = 0

    def set_filter(self, h: np.ndarray) -> None:
        self.h = h
        self._spec_n = 0
        if self.tail.shape[0] != len(h) - 1:
            self.tail = np.zeros((len(h) - 1, self.channels), dtype=np.float32)

    def process(self, x: np.ndarray) -> np.ndarray:
        m = len(self.h) - 1
        block = np.concatenate([self.tail, x], axis=0)
        self.tail = block[-m:].copy() if m else self.tail
        n = 1 << int(math.ceil(math.log2(len(block))))
        if n != self._spec_n:
            self._spec = np.fft.rfft(self.h, n)[:, None]
            self._spec_n = n
        y = np.fft.irfft(np.fft.rfft(block, n, axis=0) * self._spec, n, axis=0)
        return y[m:m + len(x)].astype(np.float32)


# ---------- звуковой движок ----------

class Equalizer(QObject):
    """Включает обходной путь звука через фильтр и следит, чтобы он не мешал плееру."""
    changed = pyqtSignal()
    failed = pyqtSignal(str)

    def __init__(self, player, config) -> None:
        super().__init__(player)
        self.player = player
        self.config = config
        data = dict(DEFAULT)
        data.update(config.data.get("eq") or {})
        self.on = bool(data["on"])
        self.preset = data["preset"] if data["preset"] in PRESETS or data["preset"] == "custom" else "flat"
        self.gains = [max(-MAX_DB, min(MAX_DB, float(g))) for g in (list(data["gains"]) + [0] * 10)[:10]]
        self.preamp = float(data["preamp"])
        self.engaged = False
        self._fmt_key = None
        self._fir = None
        self._sink = None
        self._io = None
        self._sr = 0
        self._ch = 0
        self._last_buffer = 0.0
        self._play_since = 0.0
        from .audio_tap import AudioTap
        if getattr(player, "tap", None) is None:
            player.tap = AudioTap(player)
        self.tap = player.tap
        self.tap.listen("eq", self._on_array)
        self._watch = QTimer(self, interval=500)
        self._watch.timeout.connect(self._watchdog)
        out = player.out
        out.volumeChanged.connect(self._sync_volume)
        out.mutedChanged.connect(self._sync_volume)
        player.output_changed.connect(self._device_changed)
        player.mp.playbackStateChanged.connect(self._state)
        player.mp.sourceChanged.connect(lambda *_: self.flush())
        self._wrap_seek()
        self._apply()

    # ---------- настройки ----------

    def save(self) -> None:
        self.config.data["eq"] = {"on": self.on, "preset": self.preset, "gains": [round(g, 1) for g in self.gains],
                                  "preamp": round(self.preamp, 1)}
        self.config.save()

    def set_on(self, on: bool) -> None:
        self.on = on
        self.save()
        self._apply()

    def set_preset(self, key: str) -> None:
        if key not in PRESETS:
            return
        self.preset = key
        self.gains = [float(g) for g in PRESETS[key][1]]
        self.preamp = auto_preamp(self.gains)
        self.save()
        self._apply()

    def set_gain(self, band: int, db: float, save: bool = True) -> None:
        self.gains[band] = max(-MAX_DB, min(MAX_DB, float(db)))
        self.preset = "custom"
        if save:
            self.save()
        self._apply()

    def set_preamp(self, db: float, save: bool = True) -> None:
        self.preamp = max(-MAX_DB, min(6.0, float(db)))
        if save:
            self.save()
        self._apply()

    @property
    def flat(self) -> bool:
        return all(abs(g) < 0.05 for g in self.gains) and abs(self.preamp) < 0.05

    def latency_ms(self) -> int:
        """На сколько звук эквалайзера отстаёт от позиции плеера (для текста песни)."""
        if not self.engaged or not self._sr:
            return 0
        sink_ms = int(self._sink.bufferSize() / max(1, self._sr * self._ch * 4) * 1000 * 0.5) if self._sink else 0
        return int(TAPS / 2 / self._sr * 1000) + sink_ms

    # ---------- включить / выключить обходной путь ----------

    def _apply(self) -> None:
        want = self.on and not self.flat
        if want and not self.engaged:
            self._engage()
        elif not want and self.engaged:
            self._disengage()
        elif want and self._fir is not None:
            self._fir.set_filter(design(self.gains, self.preamp, self._sr))
        self.changed.emit()

    def _engage(self) -> None:
        mp = self.player.mp
        self.tap.need("eq", True)
        mp.setAudioOutput(None)   # плеер теперь звучит только через нас
        self.engaged = True
        self._fmt_key = None
        self._play_since = time.monotonic()
        self._last_buffer = 0.0
        self._watch.start()
        log.info("эквалайзер включён")

    def _disengage(self, reason: str = "") -> None:
        mp = self.player.mp
        self._watch.stop()
        self.tap.need("eq", False)
        mp.setAudioOutput(self.player.out)
        self._stop_sink()
        self.engaged = False
        log.info("эквалайзер выключен%s", f": {reason}" if reason else "")

    def _stop_sink(self) -> None:
        if self._sink is not None:
            self._sink.stop()
            self._sink.deleteLater()
        self._sink = None
        self._io = None
        self._fmt_key = None

    # ---------- звук ----------

    def _open_sink(self, sr: int, ch: int) -> None:
        self._stop_sink()
        fmt = QAudioFormat()
        fmt.setSampleFormat(QAudioFormat.SampleFormat.Float)
        fmt.setChannelCount(ch)
        fmt.setSampleRate(sr)
        self._sink = QAudioSink(self.player.out.device(), fmt, self)
        self._sink.setBufferSize(int(sr * ch * 4 * 0.2))   # 200 мс запаса — без щелчков при нагрузке
        self._io = self._sink.start()
        self._sr, self._ch = sr, ch
        self._fmt_key = (sr, ch)
        self._fir = Fir(design(self.gains, self.preamp, sr), ch)
        self._sync_volume()

    def _on_buffer(self, buf) -> None:
        """Для тестов и старых вызовов: буфер Qt → массив."""
        from .audio_tap import to_array
        got = to_array(buf)
        if got is not None:
            self._on_array(*got)

    def _on_array(self, x: np.ndarray, sr: int) -> None:
        if not self.engaged:
            return
        self._last_buffer = time.monotonic()
        ch = x.shape[1]
        if (sr, ch) != self._fmt_key or self._sink is None:
            self._open_sink(sr, ch)
        y = np.clip(self._fir.process(x), -1.0, 1.0)
        data = y.tobytes()
        free = self._sink.bytesFree()
        if free < len(data):   # вывод не успевает — лучше потерять кусочек, чем копить отставание
            data = data[: free - free % (4 * ch)]
        if data and self._io is not None:
            self._io.write(data)

    def flush(self) -> None:
        """После перемотки и смены трека — без «хвоста» старого звука."""
        if self._fir is not None:
            self._fir.reset()
        if self._sink is not None and self._fmt_key:
            sr, ch = self._fmt_key
            self._open_sink(sr, ch)

    def _wrap_seek(self) -> None:
        original = self.player.seek

        def seek(ms: int) -> None:
            original(ms)
            if self.engaged:
                self.flush()
        self.player.seek = seek

    def _sync_volume(self, *_args) -> None:
        if self._sink is not None:
            out = self.player.out
            self._sink.setVolume(0.0 if out.isMuted() else out.volume())

    def _device_changed(self) -> None:
        if self.engaged and self._fmt_key:
            sr, ch = self._fmt_key
            self._open_sink(sr, ch)

    def _state(self, state) -> None:
        if state == QMediaPlayer.PlaybackState.PlayingState:
            self._play_since = time.monotonic()
            if self._sink is not None and self._sink.state() == QAudio.State.SuspendedState:
                self._sink.resume()
        elif self._sink is not None and state == QMediaPlayer.PlaybackState.PausedState:
            self._sink.suspend()

    def _watchdog(self) -> None:
        """Играем, а сэмплы не приходят — значит, обходной путь тут не работает: звук напрямую."""
        if not self.engaged or self.player.mp.playbackState() != QMediaPlayer.PlaybackState.PlayingState:
            return
        since = time.monotonic() - max(self._last_buffer, self._play_since)
        if since > 1.5:
            self.on = False
            self.save()
            self._disengage("нет звука из плеера")
            self.changed.emit()
            self.failed.emit("Эквалайзер не заработал на этом компьютере и выключен — звук идёт как обычно.")



# ---------- панель ----------

class EqCurve(QWidget):
    """Кривая АЧХ над ползунками — видно, что делает эквалайзер."""

    def __init__(self, eq: Equalizer, parent=None) -> None:
        super().__init__(parent)
        self.eq = eq
        self.setFixedHeight(90)

    def paintEvent(self, _event) -> None:
        from PyQt6.QtGui import QColor, QPainter, QPainterPath, QPen
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        p.setPen(QPen(QColor(255, 255, 255, 30), 1))
        p.drawLine(0, h // 2, w, h // 2)
        freqs = np.geomspace(20, 20000, 160)
        db = 20 * np.log10(np.maximum(response(self.eq.gains, 0.0, 48000, freqs), 1e-6))   # форма, без предусилителя
        path = QPainterPath()
        for i, v in enumerate(db):
            x = i / (len(db) - 1) * w
            y = h / 2 - float(np.clip(v, -14, 14)) / 14 * (h / 2 - 6)
            path.lineTo(x, y) if i else path.moveTo(x, y)
        active = self.eq.on
        p.setPen(QPen(QColor("#ff7a00") if active else QColor(255, 255, 255, 90), 3))
        p.drawPath(path)


class EqPanel(QFrame):
    """Всплывающая панель: вкл/выкл, пресеты, 10 полос, предусилитель."""

    def __init__(self, eq: Equalizer, parent=None) -> None:
        super().__init__(parent, Qt.WindowType.Popup)
        self.setObjectName("flowPanel")
        self.eq = eq
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 16, 18, 16)
        lay.setSpacing(10)

        head = QHBoxLayout()
        title = QLabel("Эквалайзер")
        title.setFont(font(17, QFont.Weight.Bold, display=True))
        head.addWidget(title)
        head.addStretch(1)
        from .widgets import Toggle
        self.toggle = Toggle()
        self.toggle.toggled.connect(self.eq.set_on)
        head.addWidget(self.toggle)
        lay.addLayout(head)

        presets = QGridLayout()
        presets.setHorizontalSpacing(6)
        presets.setVerticalSpacing(6)
        self.preset_buttons = {}
        for i, (key, (name, _g)) in enumerate(PRESETS.items()):
            b = QPushButton(name)
            b.setObjectName("chip")
            b.setCheckable(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _=False, k=key: self._preset(k))
            self.preset_buttons[key] = b
            presets.addWidget(b, i // 5, i % 5)
        lay.addLayout(presets)

        self.curve = EqCurve(eq)
        lay.addWidget(self.curve)

        bands = QHBoxLayout()
        bands.setSpacing(4)
        self.sliders = []
        self.values = []
        for i, label in enumerate(BAND_LABELS + ["Пред."]):
            col = QVBoxLayout()
            col.setSpacing(4)
            value = QLabel("0")
            value.setAlignment(Qt.AlignmentFlag.AlignCenter)
            value.setProperty("role", "muted")
            s = QSlider(Qt.Orientation.Vertical)
            s.setRange(-MAX_DB * 2, (MAX_DB if i < 10 else 6) * 2)   # шаг 0,5 дБ
            s.setFixedHeight(150)
            s.setPageStep(2)
            s.valueChanged.connect(lambda v, idx=i, lbl=value: self._moved(idx, v, lbl))
            s.sliderReleased.connect(self.eq.save)
            s.setToolTip("Предусилитель: общий запас громкости" if i == 10 else f"{label} Гц")
            name = QLabel(label)
            name.setAlignment(Qt.AlignmentFlag.AlignCenter)
            name.setProperty("role", "muted")
            col.addWidget(value)
            col.addWidget(s, 0, Qt.AlignmentFlag.AlignHCenter)
            col.addWidget(name)
            if i == 10:
                bands.addSpacing(10)
            bands.addLayout(col)
            self.sliders.append(s)
            self.values.append(value)
        lay.addLayout(bands)

        row = QHBoxLayout()
        self.note = QLabel()
        self.note.setProperty("role", "muted")
        self.note.setWordWrap(True)
        row.addWidget(self.note, 1)
        reset = QPushButton("Сбросить")
        reset.setObjectName("link")
        reset.setCursor(Qt.CursorShape.PointingHandCursor)
        reset.clicked.connect(lambda: self._preset("flat"))
        row.addWidget(reset)
        lay.addLayout(row)
        eq.changed.connect(self.sync)
        self.sync()

    def _preset(self, key: str) -> None:
        self.eq.set_preset(key)
        if key != "flat" and not self.eq.on:
            self.eq.set_on(True)

    def _moved(self, idx: int, v: int, label: QLabel) -> None:
        db = v / 2
        label.setText(f"{db:+.1f}".replace("+0.0", "0").replace("-0.0", "0"))
        if getattr(self, "_syncing", False):
            return
        dragging = self.sliders[idx].isSliderDown()
        if idx == 10:
            self.eq.set_preamp(db, save=not dragging)
        else:
            self.eq.set_gain(idx, db, save=not dragging)
            if not self.eq.on:
                self.eq.set_on(True)

    def sync(self) -> None:
        self._syncing = True
        self.toggle.blockSignals(True)
        self.toggle.setChecked(self.eq.on)
        self.toggle.blockSignals(False)
        for key, b in self.preset_buttons.items():
            b.setChecked(key == self.eq.preset)
        for i, s in enumerate(self.sliders):
            if not s.isSliderDown():
                s.setValue(int(round((self.eq.preamp if i == 10 else self.eq.gains[i]) * 2)))
        self._syncing = False
        if not self.eq.on:
            self.note.setText("Выключен — звук идёт как есть.")
        elif self.eq.flat:
            self.note.setText("Все полосы на нуле — звук не обрабатывается.")
        else:
            self.note.setText("Включён. Если хрипит на громких местах — опустите «Пред.».")
        self.curve.update()
