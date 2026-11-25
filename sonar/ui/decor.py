"""Декорации тем: фон панели с оленями, снег поверх окна, шапочки на кнопках."""
import math
import random

from PyQt6.QtCore import QEvent, QPointF, QRect, QRectF, Qt, QTimer
from PyQt6.QtGui import (QColor, QLinearGradient, QPainter, QPainterPath, QPainterPathStroker,
                         QPixmap, QRegion, QTransform)
from PyQt6.QtWidgets import QFrame, QWidget

from .theme import C, current


# ---------- олени ----------

def _reindeer_path() -> QPainterPath:
    """Силуэт оленя одной фигурой в единичных координатах (корпус длиной 1, морда вправо).
    Одна фигура важна для полупрозрачной заливки: иначе стыки частей светлее."""
    shape = QPainterPath()
    shape.addEllipse(QPointF(0, 0), 0.5, 0.2)                      # корпус
    neck = QPainterPath(QPointF(0.24, -0.12))
    neck.lineTo(0.43, -0.44)
    neck.lineTo(0.58, -0.42)
    neck.lineTo(0.48, 0.04)
    neck.closeSubpath()
    head = QPainterPath()
    head.addEllipse(QPointF(0.57, -0.47), 0.1, 0.07)
    head.addEllipse(QPointF(0.68, -0.43), 0.075, 0.05)            # морда
    ear = QPainterPath(QPointF(0.49, -0.52))
    ear.lineTo(0.41, -0.62)
    ear.lineTo(0.54, -0.55)
    ear.closeSubpath()
    tail = QPainterPath()
    tail.addEllipse(QPointF(-0.5, -0.12), 0.06, 0.04)
    # united() переводит кривые в ломаные с допуском в единицах координат:
    # в масштабе 1 эллипсы стали бы многоугольниками, поэтому объединяем в масштабе x100.
    big = QTransform.fromScale(100, 100)
    shape = big.map(shape)
    for part in (neck, head, ear, tail):
        shape = shape.united(big.map(part))

    lines = QPainterPath()
    for (x1, y1), (x2, y2) in (((-0.34, 0.1), (-0.39, 0.6)), ((-0.2, 0.13), (-0.16, 0.6)),
                               ((0.24, 0.13), (0.21, 0.6)), ((0.36, 0.08), (0.41, 0.6))):
        lines.moveTo(x1, y1)
        lines.lineTo(x2, y2)
    legs = QPainterPathStroker()
    legs.setWidth(6)
    legs.setCapStyle(Qt.PenCapStyle.RoundCap)
    shape = shape.united(legs.createStroke(big.map(lines)))

    antlers = QPainterPath()
    for dx in (0.0, 0.07):  # два рога, второй чуть сдвинут
        antlers.moveTo(0.54 + dx, -0.52)
        antlers.lineTo(0.47 + dx, -0.78)
        antlers.lineTo(0.34 + dx, -0.96)
        antlers.moveTo(0.505 + dx, -0.66)
        antlers.lineTo(0.6 + dx, -0.8)
        antlers.moveTo(0.44 + dx, -0.82)
        antlers.lineTo(0.5 + dx, -0.97)
    horns = QPainterPathStroker()
    horns.setWidth(3.5)
    horns.setCapStyle(Qt.PenCapStyle.RoundCap)
    horns.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    return shape.united(horns.createStroke(big.map(antlers))).simplified()


_REINDEER = None


def draw_reindeer(p: QPainter, x: float, y: float, size: float, color: QColor,
                  facing: int = 1) -> None:
    """(x, y) — середина корпуса, size — длина корпуса в пикселях, facing=-1 — морда влево."""
    global _REINDEER
    if _REINDEER is None:
        _REINDEER = _reindeer_path()
    p.save()
    p.translate(x, y)
    p.scale(size * facing / 100, size / 100)  # фигура построена в масштабе x100
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(color)
    p.drawPath(_REINDEER)
    p.restore()


class ThemedPanel(QFrame):
    """Основная панель: фон темы и, в новогодней, сугроб с оленями внизу.
    Фон рисуется один раз в картинку: снег перерисовывает панель кусочками много раз в секунду."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._cache: QPixmap | None = None
        self._cache_key = None

    def _background(self) -> QPixmap:
        from .personalize import custom_wallpaper_path, paint_wallpaper, personalization
        pers = personalization()
        kind = pers.get("wallpaper") if pers else "none"
        visibility = (pers.get("wallpaper_visibility") if pers else 45) / 100
        custom = custom_wallpaper_path()
        stamp = custom.stat().st_mtime if kind == "custom" and custom.exists() else 0
        ratio = self.devicePixelRatioF()
        key = (self.width(), self.height(), ratio, tuple(sorted(current().items())), kind, visibility, stamp)
        if self._cache is not None and self._cache_key == key:
            return self._cache
        pm = QPixmap(int(self.width() * ratio), int(self.height() * ratio))
        pm.setDevicePixelRatio(ratio)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(0, 0, self.width(), self.height())
        clip = QPainterPath()
        clip.addRoundedRect(r, 14, 14)
        p.setClipPath(clip)
        p.fillRect(r, QColor(C("panel")))
        if kind != "none":
            # обои под цветом панели: «видимость» — насколько они проступают, текст остаётся читаемым
            p.setOpacity(visibility)
            paint_wallpaper(p, r.width(), r.height(), kind)
            p.setOpacity(1.0)
        if current()["reindeer"]:
            self._paint_winter(p, r.width(), r.height())
        p.end()
        self._cache, self._cache_key = pm, key
        return pm

    @staticmethod
    def _paint_winter(p: QPainter, w: float, h: float) -> None:
        glow = QLinearGradient(0, h * 0.55, 0, h)
        glow.setColorAt(0, QColor(255, 255, 255, 0))
        glow.setColorAt(1, QColor(255, 255, 255, 18))
        p.fillRect(QRectF(0, 0, w, h), glow)
        drift = QPainterPath(QPointF(0, h))
        drift.lineTo(0, h - 46)
        for i in range(0, int(w) + 40, 40):
            drift.quadTo(i + 20, h - 62 - 10 * math.sin(i / 90), i + 40, h - 46)
        drift.lineTo(w, h)
        drift.closeSubpath()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 255, 255, 26))
        p.drawPath(drift)
        deer = QColor(255, 255, 255, 34)
        base = h - 74
        for i, (dx, size) in enumerate(((-90, 120), (-250, 104), (-395, 92))):
            draw_reindeer(p, w + dx, base + (120 - size) * 0.35 - 8 * (i % 2), size, deer, facing=-1)

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        r = event.rect()
        p.drawPixmap(r, self._background(), self._source(r))

    def _source(self, r: QRect) -> QRect:
        ratio = self.devicePixelRatioF()
        return QRect(int(r.x() * ratio), int(r.y() * ratio), int(r.width() * ratio), int(r.height() * ratio))


# ---------- снег ----------

class SnowOverlay(QWidget):
    """Снег поверх окна. Не перехватывает мышь; обновляет только участки вокруг снежинок."""

    COUNT = 70
    FPS_MS = 40

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._flakes: list[list[float]] = []
        self._t = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(self.FPS_MS)
        self._timer.timeout.connect(self._tick)
        parent.installEventFilter(self)
        self.hide()

    def eventFilter(self, obj, event) -> bool:
        if obj is self.parent() and event.type() == QEvent.Type.Resize:
            self.setGeometry(self.parent().rect())
            self._seed(keep=True)
        return False

    def _seed(self, keep: bool = False) -> None:
        w, h = max(self.width(), 1), max(self.height(), 1)
        if keep and self._flakes:
            for f in self._flakes:
                f[0] %= w
            return
        self._flakes = [[random.uniform(0, w), random.uniform(0, h), random.uniform(1.2, 3.4),
                         random.uniform(0.6, 1.8), random.uniform(0, math.tau)]
                        for _ in range(self.COUNT)]

    def start(self) -> None:
        self.setGeometry(self.parent().rect())
        self._seed()
        self.show()
        self.raise_()
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()
        self.hide()

    @staticmethod
    def _rect(f) -> QRect:
        r = int(f[2]) + 2
        return QRect(int(f[0]) - r, int(f[1]) - r, 2 * r, 2 * r)

    def _tick(self) -> None:
        self._t += 0.04
        w, h = self.width(), self.height()
        dirty = QRegion()
        for f in self._flakes:
            dirty += self._rect(f)
            f[1] += f[3]
            f[0] += 0.45 * math.sin(self._t + f[4])
            if f[1] > h + 5:
                f[1] = -5
                f[0] = random.uniform(0, w)
            dirty += self._rect(f)
        self.update(dirty)

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        area = event.rect()
        for f in self._flakes:
            if area.intersects(self._rect(f)):
                p.setBrush(QColor(255, 255, 255, int(120 + 35 * f[2])))
                p.drawEllipse(QPointF(f[0], f[1]), f[2], f[2])


# ---------- шапочка ----------

def draw_hat(p: QPainter, rect: QRectF) -> None:
    """Новогодний колпак в прямоугольнике rect, кончик свисает вправо."""
    p.save()
    p.translate(rect.x(), rect.y())
    p.scale(rect.width(), rect.height())
    p.setPen(Qt.PenStyle.NoPen)
    cone = QPainterPath(QPointF(0.1, 0.72))
    cone.cubicTo(0.18, 0.3, 0.42, 0.06, 0.74, 0.1)
    cone.cubicTo(0.92, 0.13, 0.98, 0.3, 0.9, 0.5)
    cone.lineTo(0.8, 0.46)
    cone.cubicTo(0.84, 0.32, 0.76, 0.26, 0.66, 0.3)
    cone.cubicTo(0.74, 0.44, 0.8, 0.58, 0.84, 0.72)
    cone.closeSubpath()
    grad = QLinearGradient(0, 0, 1, 1)
    grad.setColorAt(0, QColor("#e8243c"))
    grad.setColorAt(1, QColor("#a30d22"))
    p.setBrush(grad)
    p.drawPath(cone)
    p.setBrush(QColor("#ffffff"))
    p.drawRoundedRect(QRectF(0.02, 0.66, 0.9, 0.2), 0.1, 0.1)
    p.drawEllipse(QPointF(0.9, 0.52), 0.1, 0.1)
    p.restore()


class SantaHat(QWidget):
    """Шапочка поверх кнопки: живёт в родителе кнопки и следует за ней."""

    def __init__(self, button: QWidget, scale: float = 0.78, lift: float = 0.5) -> None:
        super().__init__(button.parentWidget())
        self._button, self._scale, self._lift = button, scale, lift
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        button.installEventFilter(self)
        self.hide()

    def eventFilter(self, obj, event) -> bool:
        kind = event.type()
        if kind in (QEvent.Type.Move, QEvent.Type.Resize):
            self._place()
        elif kind == QEvent.Type.Show:
            self._sync()
        elif kind == QEvent.Type.Hide:
            self.hide()
        return False

    def set_enabled(self, on: bool) -> None:
        self._on = on
        self._sync()

    def _sync(self) -> None:
        """Видна, только если тема с шапками и сама кнопка сейчас на экране."""
        if getattr(self, "_on", False) and self._button.isVisible():
            self._place()
            self.show()
            self.raise_()
        else:
            self.hide()

    def _place(self) -> None:
        b = self._button.geometry()
        size = int(b.width() * self._scale)
        top = max(0, b.y() - int(size * self._lift))  # не вылезать за верх родителя
        self.setGeometry(b.x() - int(size * 0.18), top, size, size)
        if getattr(self, "_on", False):
            self.raise_()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.translate(self.width() / 2, self.height() / 2)
        p.rotate(-18)
        p.translate(-self.width() / 2, -self.height() / 2)
        draw_hat(p, QRectF(0, 0, self.width(), self.height()))


# ---------- превью темы для настроек ----------

class AutoPreview(QWidget):
    """Превью «Авто»: левая половина тёмная, правая светлая, по диагонали."""

    def __init__(self, dark: dict, light: dict, parent=None) -> None:
        super().__init__(parent)
        self.setFixedSize(260, 150)
        self._dark, self._light = ThemePreview(dark), ThemePreview(light)

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        dark_img, light_img = self._dark.grab(), self._light.grab()
        p.drawPixmap(0, 0, dark_img)
        cut = QPainterPath(QPointF(150, 0))
        cut.lineTo(260, 0)
        cut.lineTo(260, 150)
        cut.lineTo(110, 150)
        cut.closeSubpath()
        p.setClipPath(cut)
        p.drawPixmap(0, 0, light_img)


class ThemePreview(QWidget):
    def __init__(self, theme: dict, parent=None) -> None:
        super().__init__(parent)
        self.theme = theme
        self.setFixedSize(260, 150)
        rnd = random.Random(7)
        self._flakes = [(rnd.uniform(0, 260), rnd.uniform(0, 150), rnd.uniform(1, 2.2)) for _ in range(26)]

    def paintEvent(self, _event) -> None:
        t = self.theme
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        clip = QPainterPath()
        clip.addRoundedRect(QRectF(self.rect()), 12, 12)
        p.setClipPath(clip)
        p.fillRect(self.rect(), QColor(t["bg"]))
        panel = QRectF(22, 8, 230, 134)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(t["panel"]))
        p.drawRoundedRect(panel, 8, 8)
        for i in range(3):  # пункты меню
            p.setBrush(QColor(t["muted"]))
            p.drawEllipse(QPointF(11, 22 + i * 16), 3, 3)
        grad = QLinearGradient(32, 18, 72, 58)
        grad.setColorAt(0, QColor(t["wave_from"]))
        grad.setColorAt(1, QColor(t["wave_to"]))
        p.setBrush(grad)
        p.drawRoundedRect(QRectF(32, 18, 40, 40), 7, 7)
        p.setBrush(QColor(t["text"]))
        p.drawRoundedRect(QRectF(80, 24, 70, 9), 4, 4)
        p.drawRoundedRect(QRectF(80, 38, 50, 9), 4, 4)
        p.setBrush(QColor(t["accent"]))
        p.drawEllipse(QPointF(222, 38), 14, 14)
        p.setBrush(QColor(t["on_accent"]))
        p.drawPolygon([QPointF(218, 31), QPointF(218, 45), QPointF(229, 38)])
        for i in range(5):
            p.setBrush(QColor(t["cover"]))
            p.drawRoundedRect(QRectF(32 + i * 42, 72, 36, 36), 5, 5)
            p.setBrush(QColor(t["muted"]))
            p.drawRoundedRect(QRectF(32 + i * 42, 113, 26, 5), 2, 2)
        if t["reindeer"]:
            draw_reindeer(p, 222, 128, 26, QColor(255, 255, 255, 60), facing=-1)
            draw_reindeer(p, 190, 129, 22, QColor(255, 255, 255, 60), facing=-1)
        if t["hats"]:
            p.save()
            p.translate(210, 16)
            p.rotate(-18)
            draw_hat(p, QRectF(-4, -6, 22, 22))
            p.restore()
        if t["snow"]:
            for x, y, r in self._flakes:
                p.setBrush(QColor(255, 255, 255, 190))
                p.drawEllipse(QPointF(x, y), r, r)


class HeartBurst(QWidget):
    """Сердечки разлетаются из точки и тают. Прозрачен для мыши, живёт меньше секунды."""

    DURATION = 900

    def __init__(self, window: QWidget, origin, color: QColor) -> None:
        super().__init__(window)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setGeometry(window.rect())
        self._origin = QPointF(origin)
        self._color = color
        rnd = random.Random()
        self._hearts = [(rnd.uniform(-160, -20), rnd.uniform(60, 190), rnd.uniform(7, 15),
                         rnd.uniform(-40, 40)) for _ in range(14)]  # угол, скорость, размер, вращение
        self._t = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._tick)
        self.show()
        self.raise_()
        self._timer.start()

    def _tick(self) -> None:
        self._t += self._timer.interval()
        if self._t >= self.DURATION:
            self._timer.stop()
            self.deleteLater()
            return
        self.update()

    def paintEvent(self, _event) -> None:
        from .icons import _heart_path
        k = self._t / self.DURATION
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        for angle, speed, size, spin in self._hearts:
            a = math.radians(angle)
            dist = speed * (1 - (1 - k) ** 3)          # быстрый вылет, плавное торможение
            x = self._origin.x() + math.cos(a) * dist
            y = self._origin.y() + math.sin(a) * dist + 60 * k * k  # лёгкая «гравитация»
            c = QColor(self._color)
            c.setAlpha(int(255 * (1 - k)))
            p.save()
            p.translate(x, y)
            p.rotate(spin * k)
            p.scale(1 + 0.3 * k, 1 + 0.3 * k)
            p.translate(-size / 2, -size / 2)
            p.setBrush(c)
            p.drawPath(_heart_path(size))
            p.restore()
