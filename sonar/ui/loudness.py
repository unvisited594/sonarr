"""Выравнивание громкости: тихие треки чуть громче, громкие чуть тише — без дёрганья ползунка.

Через отвод звука (AudioTap) меряем громкость трека (среднеквадратичную, с подавлением тишины)
и подстраиваем коэффициент к целевому уровню, плавно и в пределах ±8 дБ. Коэффициент
умножается на громкость, которую выставляет плеер (ползунок, затухания), — сам ползунок не
двигается. Запомненный коэффициент трека применяется сразу при следующем прослушивании.
"""
import json
import math

import numpy as np
from PyQt6.QtCore import QObject, QTimer

from ..config import config_dir

TARGET_DB = -16.0    # целевой уровень (≈ «громкость стримингов»)
MAX_DB = 8.0
MAX_CACHE = 3000


class Loudness(QObject):
    def __init__(self, player, config) -> None:
        super().__init__(player)
        self.player = player
        self.config = config
        self.gain = 1.0
        self._target = 1.0
        self._sum = 0.0
        self._n = 0
        self._key = None
        self._path = config_dir() / "loudness.json"
        try:
            self._cache = json.loads(self._path.read_text("utf-8"))
        except (OSError, ValueError):
            self._cache = {}
        out = player.out
        self._raw_set = out.setVolume
        self._raw_volume = 1.0
        out.setVolume = self._set_volume          # все, кто ставит громкость, проходят через нас
        tap = getattr(player, "tap", None)
        if tap is None:
            from .audio_tap import AudioTap
            tap = player.tap = AudioTap(player)
        self.tap = tap
        tap.listen("loud", self._feed)
        player.started.connect(self._started)
        self._ease = QTimer(self, interval=100)
        self._ease.timeout.connect(self._step)
        self._ease.start()
        self.apply_setting()

    @property
    def on(self) -> bool:
        return bool(self.config.data.get("loudness", True))

    def set_on(self, on: bool) -> None:
        self.config.data["loudness"] = on
        self.config.save()
        self.apply_setting()

    def apply_setting(self) -> None:
        self.tap.need("loud", self.on)
        if not self.on:
            self._target = 1.0

    def _set_volume(self, v: float) -> None:
        self._raw_volume = float(v)
        self._raw_set(min(1.0, self._raw_volume * self.gain))

    def _started(self, track) -> None:
        self._save_current()
        self._key = f"{track.service_id}:{track.id}" if track is not None else None
        self._sum, self._n = 0.0, 0
        db = self._cache.get(self._key) if self._key else None
        self._target = self._gain_for(db) if (db is not None and self.on) else self._target

    def _gain_for(self, measured_db: float) -> float:
        diff = max(-MAX_DB, min(MAX_DB, TARGET_DB - measured_db))
        return 10 ** (diff / 20)

    def _feed(self, x: np.ndarray, _sr: int) -> None:
        if not self.on:
            return
        mono = x.mean(axis=1) if x.ndim == 2 else x
        ms = float(np.mean(mono * mono))
        if ms < 1e-6:   # тишина и паузы не в счёт
            return
        self._sum += ms
        self._n += 1
        if self._n % 20 == 0:
            db = 10 * math.log10(self._sum / self._n)
            self._target = self._gain_for(db)

    def _step(self) -> None:
        target = self._target if self.on else 1.0
        if abs(target - self.gain) < 0.002:
            return
        self.gain += (target - self.gain) * 0.08      # мягко, за пару секунд
        self._raw_set(min(1.0, self._raw_volume * self.gain))

    def _save_current(self) -> None:
        if self._key and self._n >= 40:
            self._cache[self._key] = round(10 * math.log10(self._sum / self._n), 2)
            if len(self._cache) > MAX_CACHE:
                for k in list(self._cache)[: len(self._cache) - MAX_CACHE]:
                    self._cache.pop(k, None)
            try:
                self._path.write_text(json.dumps(self._cache), "utf-8")
            except OSError:
                pass

    def flush(self) -> None:
        self._save_current()
