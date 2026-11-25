"""Настройки фона большого плеера: цвета, размытие, скорость движения."""
import random

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtGui import QColor

# Готовые палитры: яркие пятна на тёмном фоне. base — цвет «под» пятнами.
PRESETS: dict[str, dict] = {
    "fire":   {"title": "Огонь",  "colors": ["#ff7a00", "#ffd000", "#ff3d00", "#8a2be2"], "base": "#000000"},
    "sunset": {"title": "Закат",  "colors": ["#ff5f6d", "#ffc371", "#c33764", "#ff9a8b"], "base": "#0d0207"},
    "ocean":  {"title": "Океан",  "colors": ["#00c6ff", "#0052ff", "#00e5a8", "#3a0ca3"], "base": "#020611"},
    "aurora": {"title": "Аврора", "colors": ["#00ff9c", "#00b3ff", "#a24bff", "#1de9b6"], "base": "#02040a"},
    "neon":   {"title": "Неон",   "colors": ["#ff00e5", "#00f0ff", "#7c4dff", "#ff2e63"], "base": "#05010d"},
}
COVER, CUSTOM = "cover", "custom"
DEFAULTS = {"flow_source": COVER, "flow_blur": 55, "flow_speed": 50,
            "flow_custom": ["#ff7a00", "#ffd000", "#8a2be2"], "vinyl": False,
            "video_bg": False, "video_transparency": 40,
            "lyrics_on": False, "visualizer": True}
# Текст песни в большом плеере: вид, цвета, шрифт, скорость и сдвиг. Отдельный сброс — reset_lyrics().
LYRICS_DEFAULTS = {"lyrics_style": "dotify", "lyrics_color": "#ffffff", "lyrics_sung": "#000000",
                   "lyrics_halo": True, "lyrics_font": "", "lyrics_size": 30, "lyrics_bold": True,
                   "lyrics_align": "left", "lyrics_speed": 100, "lyrics_offset": 0, "lyrics_scroll": 50,
                   "lyrics_translate": False}
DEFAULTS.update(LYRICS_DEFAULTS)


class FlowSettings(QObject):
    changed = pyqtSignal()

    def __init__(self, config) -> None:
        super().__init__()
        self.config = config

    def get(self, key: str):
        return self.config.data.get(key, DEFAULTS[key])

    def set(self, key: str, value) -> None:
        if self.get(key) == value:
            return
        self.config.data[key] = value
        self.config.save()
        self.changed.emit()

    def reset(self) -> None:
        """«Вернуть как было» для фона: настройки текста песни не трогаем."""
        for key in DEFAULTS:
            if key not in LYRICS_DEFAULTS and key != "lyrics_on":
                self.config.data.pop(key, None)
        self.config.save()
        self.changed.emit()

    def reset_lyrics(self) -> None:
        for key in LYRICS_DEFAULTS:
            self.config.data.pop(key, None)
        self.config.save()
        self.changed.emit()

    @property
    def blur(self) -> float:      # 0..1
        return max(0, min(100, int(self.get("flow_blur")))) / 100

    @property
    def speed(self) -> float:     # множитель скорости движения пятен
        return 0.2 + 1.6 * max(0, min(100, int(self.get("flow_speed")))) / 100

    def palette(self) -> tuple[list[QColor] | None, QColor | None]:
        """(цвета, цвет фона) для выбранного источника; (None, None) — брать из обложки."""
        source = self.get("flow_source")
        if source in PRESETS:
            p = PRESETS[source]
            return [QColor(c) for c in p["colors"]], QColor(p["base"])
        if source == CUSTOM:
            return [QColor(c) for c in self.get("flow_custom")], QColor("#000000")
        return None, None

    def randomize_custom(self) -> None:
        """Случайные, но гармоничные цвета: оттенки разнесены по кругу."""
        h = random.random()
        colors = [QColor.fromHsvF((h + k * random.uniform(0.18, 0.32)) % 1.0,
                                  random.uniform(0.75, 1.0), random.uniform(0.85, 1.0)).name()
                  for k in range(3)]
        self.config.data["flow_custom"] = colors
        self.config.data["flow_source"] = CUSTOM
        self.config.save()
        self.changed.emit()


def normalize(colors: list[QColor], n: int = 4) -> list[QColor]:
    """Ровно n цветов: недостающие — соседние оттенки, чтобы переходы между палитрами были плавными."""
    out = list(colors[:n]) or [QColor("#3b2a6e")]
    i = 0
    while len(out) < n:
        c = out[i % len(out)]
        h = c.hsvHueF() if c.hsvHueF() >= 0 else 0.0
        out.append(QColor.fromHsvF((h + 0.09 * (len(out))) % 1.0, c.hsvSaturationF(), c.valueF()))
        i += 1
    return out


_flow: FlowSettings | None = None


def flow() -> FlowSettings | None:
    return _flow


def set_flow(settings: FlowSettings) -> None:
    global _flow
    _flow = settings
