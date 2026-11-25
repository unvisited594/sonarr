"""Отвод звука из плеера: готовые сэмплы для эквалайзера и визуализатора.

Один QAudioBufferOutput на всех. Подключается к плееру, только пока он кому-то нужен
(need("eq", True) / need("viz", True)), и отключается, когда не нужен никому, — без лишней работы.
Слушатели получают numpy-массив float32 размером (кадры, каналы) и частоту дискретизации.
"""
import time

import numpy as np
from PyQt6.QtCore import QObject
from PyQt6.QtMultimedia import QAudioBufferOutput, QAudioFormat


def to_array(buf) -> tuple[np.ndarray, int] | None:
    fmt = buf.format()
    sr, ch = fmt.sampleRate(), fmt.channelCount()
    if not sr or not ch or buf.byteCount() <= 0:
        return None
    try:
        raw = buf.constData().asstring(buf.byteCount())
    except AttributeError:
        raw = bytes(buf.data())
    kind = fmt.sampleFormat()
    if kind == QAudioFormat.SampleFormat.Int16:
        x = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    elif kind == QAudioFormat.SampleFormat.Int32:
        x = np.frombuffer(raw, dtype=np.int32).astype(np.float32) / 2147483648.0
    elif kind == QAudioFormat.SampleFormat.UInt8:
        x = (np.frombuffer(raw, dtype=np.uint8).astype(np.float32) - 128) / 128.0
    else:
        x = np.frombuffer(raw, dtype=np.float32)
    x = x[: len(x) - len(x) % ch].reshape(-1, ch)
    return x, sr


class AudioTap(QObject):
    def __init__(self, player) -> None:
        super().__init__(player)
        self.player = player
        self._needs: set[str] = set()
        self._listeners: dict[str, callable] = {}
        self._out = None
        self.last_buffer = 0.0

    def listen(self, key: str, fn) -> None:
        self._listeners[key] = fn

    def need(self, key: str, on: bool) -> None:
        (self._needs.add if on else self._needs.discard)(key)
        if self._needs and self._out is None:
            fmt = QAudioFormat()
            fmt.setSampleFormat(QAudioFormat.SampleFormat.Float)
            fmt.setChannelCount(2)
            fmt.setSampleRate(48000)
            self._out = QAudioBufferOutput(fmt, self)
            self._out.audioBufferReceived.connect(self._on_buffer)
            self.player.mp.setAudioBufferOutput(self._out)
        elif not self._needs and self._out is not None:
            self.player.mp.setAudioBufferOutput(None)
            self._out.deleteLater()
            self._out = None

    @property
    def attached(self) -> bool:
        return self._out is not None

    def _on_buffer(self, buf) -> None:
        got = to_array(buf)
        if got is None:
            return
        self.last_buffer = time.monotonic()
        x, sr = got
        for key in list(self._needs):
            fn = self._listeners.get(key)
            if fn is not None:
                fn(x, sr)


class Analyzer:
    """Спектр для визуализатора: 24 полосы (логарифмически) и «удар баса», сглаженные."""
    BANDS = 24

    def __init__(self) -> None:
        self.levels = np.zeros(self.BANDS, dtype=np.float32)
        self.bass = 0.0
        self._peak = 1e-3
        self.updated = 0.0

    def feed(self, x: np.ndarray, sr: int) -> None:
        mono = x.mean(axis=1) if x.ndim == 2 else x
        if len(mono) < 256:
            return
        self._ring = np.concatenate([getattr(self, "_ring", np.zeros(0, np.float32)), mono])[-4096:]
        n = 4096
        seg = np.pad(self._ring, (n - len(self._ring), 0)) if len(self._ring) < n else self._ring
        spec = np.abs(np.fft.rfft(seg * np.hanning(n))) / (n / 4)   # полная громкость синуса ≈ 1
        freqs = np.fft.rfftfreq(n, 1 / sr)
        edges = np.geomspace(40, min(16000, sr / 2 - 1), self.BANDS + 1)
        bands = []
        for a, b in zip(edges[:-1], edges[1:]):
            sel = spec[(freqs >= a) & (freqs < b)]
            # в узкой низкой полосе может не оказаться ни одного отсчёта — берём ближайший
            bands.append(sel.max() if sel.size else spec[int(np.argmin(np.abs(freqs - (a * b) ** 0.5)))])
        bands = np.array(bands, dtype=np.float32)
        db = 20 * np.log10(bands + 1e-6)
        norm = np.clip((db + 60) / 60, 0, 1)    # −60 дБ и тише → 0, полная громкость → 1
        self.levels = np.maximum(norm, self.levels * 0.82)   # быстро вверх, плавно вниз
        bass = float(spec[(freqs >= 35) & (freqs < 140)].mean())
        self._peak = max(self._peak * 0.995, bass)
        self.bass = max(bass / self._peak if self._peak > 0 else 0.0, self.bass * 0.85)
        self.updated = time.monotonic()

    def decay(self) -> None:
        """Нет свежего звука (пауза) — всё плавно опускается."""
        if time.monotonic() - self.updated > 0.15:
            self.levels *= 0.85
            self.bass *= 0.85
