"""Оформление: иконка приложения и обои главной панели. Всё рисуется кодом;
своя картинка копируется в папку данных и не зависит от исходного файла."""
import math
import random
from pathlib import Path

from PyQt6.QtCore import QObject, QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import (QColor, QImage, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap,
                         QRadialGradient)

from ..config import config_dir

APP_ICONS = [("standard", "Стандартная"), ("newyear", "Новогодняя"), ("sea", "Морская"),
             ("space", "Космическая"), ("custom", "Своя…")]
WALLPAPERS = [("none", "Без обоев"), ("newyear", "Новогодние"), ("sea", "Морские"),
              ("space", "Космос"), ("custom", "Свои…")]
DEFAULTS = {"app_icon": "standard", "wallpaper": "none", "wallpaper_visibility": 45,
            "accent": None, "like_burst": True, "snow": None, "bg_sidebar": None, "bg_panel": None,
            "close_to_tray": False, "notify_track": True, "fallback_services": True}


def custom_icon_path() -> Path:
    return config_dir() / "custom_icon.png"


def custom_wallpaper_path() -> Path:
    return config_dir() / "custom_wallpaper.png"


class Personalization(QObject):
    changed = pyqtSignal()

    def __init__(self, config) -> None:
        super().__init__()
        self.config = config

    def get(self, key: str):
        return self.config.data.get(key, DEFAULTS[key])

    def snow_on(self) -> bool:
        """Снег: явный выбор пользователя, а если его не было — как у темы (новогодняя — со снегом)."""
        value = self.config.data.get("snow")
        if value is None:
            return self.config.data.get("theme") == "newyear"
        return bool(value)

    def set(self, key: str, value) -> None:
        self.config.data[key] = value
        self.config.save()
        self.changed.emit()

    def import_image(self, source: str, kind: str) -> bool:
        """Своя картинка: проверяем, что это изображение, и кладём копию в папку данных."""
        image = QImage(source)
        if image.isNull():
            return False
        if kind == "icon":
            side = min(image.width(), image.height())  # квадрат по центру
            image = image.copy((image.width() - side) // 2, (image.height() - side) // 2, side, side)
            image.scaled(512, 512, Qt.AspectRatioMode.KeepAspectRatio,
                         Qt.TransformationMode.SmoothTransformation).save(str(custom_icon_path()))
            self.set("app_icon", "custom")
        else:
            if image.width() > 3840:
                image = image.scaledToWidth(3840, Qt.TransformationMode.SmoothTransformation)
            image.save(str(custom_wallpaper_path()))
            self.set("wallpaper", "custom")
        return True


# ---------- иконки приложения ----------

def _snowflake(p: QPainter, c: QPointF, r: float, width: float, color: QColor) -> None:
    pen = QPen(color, width)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    p.setPen(pen)
    for k in range(6):
        a = math.radians(k * 60 + 90)
        end = QPointF(c.x() + r * math.cos(a), c.y() - r * math.sin(a))
        p.drawLine(c, end)
        for frac in (0.55,):
            mid = QPointF(c.x() + r * frac * math.cos(a), c.y() - r * frac * math.sin(a))
            for side in (-35, 35):
                b = a + math.radians(side)
                p.drawLine(mid, QPointF(mid.x() + r * 0.3 * math.cos(b), mid.y() - r * 0.3 * math.sin(b)))


def app_icon(kind: str, size: int = 128) -> QPixmap:
    from .icons import circle_avatar, pixmap
    if kind == "custom" and custom_icon_path().exists():
        return circle_avatar(custom_icon_path(), size)
    if kind not in ("newyear", "sea", "space"):
        return pixmap("logo", "#f2f2f2", size)
    ratio = 2
    s = size * ratio
    pm = QPixmap(s, s)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    circle = QPainterPath()
    circle.addEllipse(QRectF(s * 0.04, s * 0.04, s * 0.92, s * 0.92))
    p.setClipPath(circle)
    center = QPointF(s / 2, s / 2)
    if kind == "newyear":
        g = QRadialGradient(QPointF(s * 0.4, s * 0.35), s * 0.7)
        g.setColorAt(0, QColor("#e8243c"))
        g.setColorAt(1, QColor("#8f0b1e"))
        p.fillRect(QRectF(0, 0, s, s), g)
        _snowflake(p, center, s * 0.3, s * 0.045, QColor("#ffffff"))
    elif kind == "sea":
        g = QLinearGradient(0, 0, 0, s)
        g.setColorAt(0, QColor("#48cae4"))
        g.setColorAt(1, QColor("#023e8a"))
        p.fillRect(QRectF(0, 0, s, s), g)
        p.setBrush(QColor(255, 236, 160))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QPointF(s * 0.68, s * 0.3), s * 0.1, s * 0.1)
        pen = QPen(QColor("#ffffff"), s * 0.05)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        for row, y0 in enumerate((0.52, 0.66, 0.8)):
            wave = QPainterPath(QPointF(s * 0.1, s * y0))
            for x in range(0, 41):
                xx = s * (0.1 + 0.8 * x / 40)
                wave.lineTo(xx, s * y0 + s * 0.035 * math.sin(x / 40 * math.tau * 1.5 + row))
            p.drawPath(wave)
    else:  # космос
        g = QRadialGradient(QPointF(s * 0.3, s * 0.3), s * 0.9)
        g.setColorAt(0, QColor("#3a1c71"))
        g.setColorAt(1, QColor("#05010d"))
        p.fillRect(QRectF(0, 0, s, s), g)
        rnd = random.Random(4)
        p.setPen(Qt.PenStyle.NoPen)
        for _ in range(26):
            p.setBrush(QColor(255, 255, 255, rnd.randint(120, 255)))
            p.drawEllipse(QPointF(rnd.uniform(0, s), rnd.uniform(0, s)), s * 0.008 * rnd.uniform(1, 2.2),
                          s * 0.008 * rnd.uniform(1, 2.2))
        planet = QRadialGradient(QPointF(s * 0.45, s * 0.45), s * 0.26)
        planet.setColorAt(0, QColor("#ffb347"))
        planet.setColorAt(1, QColor("#d9480f"))
        p.setBrush(planet)
        p.drawEllipse(center, s * 0.2, s * 0.2)
        p.save()
        p.translate(center)
        p.rotate(-20)
        p.setPen(QPen(QColor(255, 255, 255, 220), s * 0.035))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QPointF(0, 0), s * 0.36, s * 0.1)
        p.restore()
    p.end()
    pm.setDevicePixelRatio(ratio)
    return pm


# ---------- обои ----------

def paint_wallpaper(p: QPainter, w: float, h: float, kind: str) -> None:
    """Рисует обои на всю панель. Видимость (прозрачность) задаёт вызывающий."""
    rnd = random.Random(11)  # одинаковая раскладка при каждой перерисовке
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    if kind == "custom" and custom_wallpaper_path().exists():
        img = QImage(str(custom_wallpaper_path()))
        scaled = img.scaled(int(w), int(h), Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                            Qt.TransformationMode.SmoothTransformation)
        p.drawImage(QPointF((w - scaled.width()) / 2, (h - scaled.height()) / 2), scaled)
        return
    if kind == "newyear":
        g = QLinearGradient(0, 0, 0, h)
        g.setColorAt(0, QColor("#0b1a3a"))
        g.setColorAt(1, QColor("#1d3b6e"))
        p.fillRect(QRectF(0, 0, w, h), g)
        moon = QRadialGradient(QPointF(w * 0.82, h * 0.16), h * 0.12)
        moon.setColorAt(0, QColor(255, 250, 220, 255))
        moon.setColorAt(0.45, QColor(255, 250, 220, 230))
        moon.setColorAt(1, QColor(255, 250, 220, 0))
        p.fillRect(QRectF(0, 0, w, h), moon)
        for _ in range(int(w * h / 9000)):
            _snowflake(p, QPointF(rnd.uniform(0, w), rnd.uniform(0, h * 0.85)), rnd.uniform(3, 9), 1.2,
                       QColor(255, 255, 255, rnd.randint(90, 200)))
        p.setPen(Qt.PenStyle.NoPen)
        x = -20.0
        while x < w + 40:  # ёлки по нижнему краю
            th = rnd.uniform(0.18, 0.32) * h
            tw = th * 0.55
            p.setBrush(QColor("#0f3b2e"))
            for tier in range(3):
                top = h - th + tier * th * 0.26
                half = tw * (0.45 + tier * 0.2)
                tri = QPainterPath(QPointF(x, top))
                tri.lineTo(x + half, top + th * 0.38)
                tri.lineTo(x - half, top + th * 0.38)
                tri.closeSubpath()
                p.drawPath(tri)
            for _ in range(5):  # огоньки гирлянды
                p.setBrush(QColor(rnd.choice(["#ff4d4d", "#ffd23f", "#4dd2ff", "#ffffff"])))
                p.drawEllipse(QPointF(x + rnd.uniform(-tw * 0.35, tw * 0.35), h - th * rnd.uniform(0.1, 0.75)), 2.6, 2.6)
            x += tw * rnd.uniform(0.9, 1.4)
    elif kind == "sea":
        g = QLinearGradient(0, 0, 0, h)
        g.setColorAt(0, QColor("#48cae4"))
        g.setColorAt(0.5, QColor("#0077b6"))
        g.setColorAt(1, QColor("#03045e"))
        p.fillRect(QRectF(0, 0, w, h), g)
        p.setPen(Qt.PenStyle.NoPen)
        for _ in range(6):  # лучи света сверху
            x0 = rnd.uniform(0, w)
            ray = QPainterPath(QPointF(x0, 0))
            ray.lineTo(x0 + w * 0.05, 0)
            ray.lineTo(x0 + w * 0.2, h)
            ray.lineTo(x0 + w * 0.08, h)
            ray.closeSubpath()
            p.setBrush(QColor(255, 255, 255, 18))
            p.drawPath(ray)
        p.setBrush(Qt.BrushStyle.NoBrush)
        for _ in range(int(w * h / 14000)):  # пузырьки
            r = rnd.uniform(2, 9)
            p.setPen(QPen(QColor(255, 255, 255, rnd.randint(60, 150)), 1.4))
            p.drawEllipse(QPointF(rnd.uniform(0, w), rnd.uniform(h * 0.15, h)), r, r)
        for k in range(int(w / 70)):  # водоросли
            x0 = rnd.uniform(0, w)
            pen = QPen(QColor(10, 90, 70, 200), rnd.uniform(5, 9))
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            weed = QPainterPath(QPointF(x0, h))
            height = rnd.uniform(0.15, 0.35) * h
            for step in range(1, 11):
                weed.lineTo(x0 + 10 * math.sin(step * 0.9 + k), h - height * step / 10)
            p.drawPath(weed)
    elif kind == "space":
        g = QLinearGradient(0, 0, w, h)
        g.setColorAt(0, QColor("#05010d"))
        g.setColorAt(1, QColor("#140a33"))
        p.fillRect(QRectF(0, 0, w, h), g)
        for cx, cy, rr, col in ((0.25, 0.3, 0.45, "#7b2cbf"), (0.7, 0.65, 0.5, "#3a86ff"), (0.55, 0.2, 0.3, "#ff4d9d")):
            neb = QRadialGradient(QPointF(w * cx, h * cy), max(w, h) * rr)
            c = QColor(col)
            neb.setColorAt(0, QColor(c.red(), c.green(), c.blue(), 110))
            neb.setColorAt(1, QColor(c.red(), c.green(), c.blue(), 0))
            p.fillRect(QRectF(0, 0, w, h), neb)
        p.setPen(Qt.PenStyle.NoPen)
        for _ in range(int(w * h / 1800)):
            p.setBrush(QColor(255, 255, 255, rnd.randint(60, 255)))
            r = rnd.choice([0.6, 0.8, 1.0, 1.4, 2.0])
            p.drawEllipse(QPointF(rnd.uniform(0, w), rnd.uniform(0, h)), r, r)
        planet = QRadialGradient(QPointF(w * 0.8, h * 0.72), h * 0.2)
        planet.setColorAt(0, QColor("#ffb347"))
        planet.setColorAt(1, QColor("#7a2a0a"))
        p.setBrush(planet)
        p.drawEllipse(QPointF(w * 0.84, h * 0.76), h * 0.16, h * 0.16)
        p.save()
        p.translate(w * 0.84, h * 0.76)
        p.rotate(-18)
        p.setPen(QPen(QColor(255, 230, 200, 170), 4))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QPointF(0, 0), h * 0.3, h * 0.07)
        p.restore()


def wallpaper_preview(kind: str, w: int = 160, h: int = 100) -> QPixmap:
    ratio = 2
    pm = QPixmap(w * ratio, h * ratio)
    pm.fill(QColor("#2a2a2a"))
    p = QPainter(pm)
    clip = QPainterPath()
    clip.addRoundedRect(QRectF(0, 0, w * ratio, h * ratio), 12 * ratio, 12 * ratio)
    p.setClipPath(clip)
    if kind == "none":
        from .theme import C
        p.fillRect(QRectF(0, 0, w * ratio, h * ratio), QColor(C("panel")))
    else:
        paint_wallpaper(p, w * ratio, h * ratio, kind)
    p.end()
    pm.setDevicePixelRatio(ratio)
    return pm


_pers: Personalization | None = None


def personalization() -> Personalization | None:
    return _pers


def set_personalization(obj: Personalization) -> None:
    global _pers
    _pers = obj
