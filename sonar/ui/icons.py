"""Иконки рисуются кодом, чтобы не таскать файлы и не зависеть от шрифтов."""
import math
from pathlib import Path

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QIcon, QPainter, QPainterPath, QPen, QPixmap, QPolygonF


def _poly(p, s, pts):
    p.drawPolygon(QPolygonF([QPointF(x * s, y * s) for x, y in pts]))


def _play(p, s, c):
    p.setBrush(c); p.setPen(Qt.PenStyle.NoPen)
    _poly(p, s, [(0.32, 0.2), (0.32, 0.8), (0.82, 0.5)])


def _pause(p, s, c):
    p.setBrush(c); p.setPen(Qt.PenStyle.NoPen)
    for x in (0.27, 0.57):
        p.drawRoundedRect(QRectF(x * s, 0.22 * s, 0.16 * s, 0.56 * s), 0.04 * s, 0.04 * s)


def _next(p, s, c):
    p.setBrush(c); p.setPen(Qt.PenStyle.NoPen)
    _poly(p, s, [(0.22, 0.24), (0.22, 0.76), (0.62, 0.5)])
    p.drawRoundedRect(QRectF(0.65 * s, 0.24 * s, 0.11 * s, 0.52 * s), 0.03 * s, 0.03 * s)


def _prev(p, s, c):
    p.translate(s, 0); p.scale(-1, 1)
    _next(p, s, c)


def _stroke(p, s, c, width=0.075):
    pen = QPen(c, width * s)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap); pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen); p.setBrush(Qt.BrushStyle.NoBrush)


def _home(p, s, c):
    """Домик: крыша со свесами, стены, дверь."""
    _stroke(p, s, c, 0.075)
    roof = QPainterPath(QPointF(0.1 * s, 0.5 * s))
    roof.lineTo(0.5 * s, 0.15 * s)
    roof.lineTo(0.9 * s, 0.5 * s)
    p.drawPath(roof)
    walls = QPainterPath(QPointF(0.23 * s, 0.4 * s))
    walls.lineTo(0.23 * s, 0.84 * s)
    walls.lineTo(0.77 * s, 0.84 * s)
    walls.lineTo(0.77 * s, 0.4 * s)
    p.drawPath(walls)
    door = QPainterPath(QPointF(0.42 * s, 0.84 * s))
    door.lineTo(0.42 * s, 0.62 * s)
    door.lineTo(0.58 * s, 0.62 * s)
    door.lineTo(0.58 * s, 0.84 * s)
    p.drawPath(door)


def _wave(p, s, c):
    """Звуковая волна: столбики разной высоты."""
    _stroke(p, s, c, 0.085)
    heights = (0.18, 0.42, 0.66, 0.38, 0.56, 0.26, 0.12)
    step = 0.7 / (len(heights) - 1)
    for i, h in enumerate(heights):
        x = (0.15 + i * step) * s
        p.drawLine(QPointF(x, (0.5 - h / 2) * s), QPointF(x, (0.5 + h / 2) * s))


def _chevron(p, s, c):
    _stroke(p, s, c, 0.1)
    path = QPainterPath(QPointF(0.28 * s, 0.4 * s))
    path.lineTo(0.5 * s, 0.62 * s)
    path.lineTo(0.72 * s, 0.4 * s)
    p.drawPath(path)


def _heart_path(s) -> QPainterPath:
    path = QPainterPath(QPointF(0.5 * s, 0.84 * s))
    path.cubicTo(0.12 * s, 0.6 * s, 0.08 * s, 0.32 * s, 0.24 * s, 0.22 * s)
    path.cubicTo(0.36 * s, 0.14 * s, 0.47 * s, 0.22 * s, 0.5 * s, 0.32 * s)
    path.cubicTo(0.53 * s, 0.22 * s, 0.64 * s, 0.14 * s, 0.76 * s, 0.22 * s)
    path.cubicTo(0.92 * s, 0.32 * s, 0.88 * s, 0.6 * s, 0.5 * s, 0.84 * s)
    return path


def _heart(p, s, c):
    _stroke(p, s, c, 0.08)
    p.drawPath(_heart_path(s))


def _heart_fill(p, s, c):
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(c)
    p.drawPath(_heart_path(s))


def _grid(p, s, c):
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(c)
    for x in (0.18, 0.54):
        for y in (0.18, 0.54):
            p.drawRoundedRect(QRectF(x * s, y * s, 0.28 * s, 0.28 * s), 0.06 * s, 0.06 * s)


def _list(p, s, c):
    _stroke(p, s, c, 0.08)
    for y in (0.28, 0.5, 0.72):
        p.drawLine(QPointF(0.34 * s, y * s), QPointF(0.82 * s, y * s))
        p.drawPoint(QPointF(0.18 * s, y * s))


def _playlist(p, s, c):
    _stroke(p, s, c, 0.08)
    for y, x2 in ((0.24, 0.8), (0.44, 0.8), (0.64, 0.5)):
        p.drawLine(QPointF(0.16 * s, y * s), QPointF(x2 * s, y * s))
    p.setBrush(c)
    p.drawEllipse(QPointF(0.66 * s, 0.76 * s), 0.08 * s, 0.07 * s)
    p.drawLine(QPointF(0.74 * s, 0.76 * s), QPointF(0.74 * s, 0.5 * s))


def _plus(p, s, c):
    _stroke(p, s, c, 0.09)
    p.drawLine(QPointF(0.5 * s, 0.2 * s), QPointF(0.5 * s, 0.8 * s))
    p.drawLine(QPointF(0.2 * s, 0.5 * s), QPointF(0.8 * s, 0.5 * s))


def _shuffle(p, s, c):
    _stroke(p, s, c, 0.075)
    a = QPainterPath(QPointF(0.14 * s, 0.3 * s))
    a.cubicTo(0.45 * s, 0.3 * s, 0.5 * s, 0.7 * s, 0.84 * s, 0.7 * s)
    b = QPainterPath(QPointF(0.14 * s, 0.7 * s))
    b.cubicTo(0.45 * s, 0.7 * s, 0.5 * s, 0.3 * s, 0.84 * s, 0.3 * s)
    p.drawPath(a)
    p.drawPath(b)
    for y in (0.3, 0.7):
        p.drawLine(QPointF(0.84 * s, y * s), QPointF(0.72 * s, (y - 0.1) * s))
        p.drawLine(QPointF(0.84 * s, y * s), QPointF(0.72 * s, (y + 0.1) * s))


def _arrowhead(p, s, tip: QPointF, angle_deg: float, length: float = 0.13) -> None:
    for spread in (-35, 35):
        a = math.radians(angle_deg + 180 + spread)
        p.drawLine(tip, QPointF(tip.x() + length * s * math.cos(a), tip.y() + length * s * math.sin(a)))


def _repeat(p, s, c):
    """Повтор: две встречные стрелки по прямоугольному кругу."""
    _stroke(p, s, c, 0.075)
    top = QPainterPath(QPointF(0.2 * s, 0.56 * s))
    top.lineTo(0.2 * s, 0.4 * s)
    top.quadTo(0.2 * s, 0.28 * s, 0.32 * s, 0.28 * s)
    top.lineTo(0.8 * s, 0.28 * s)
    p.drawPath(top)
    _arrowhead(p, s, QPointF(0.8 * s, 0.28 * s), 0)
    bottom = QPainterPath(QPointF(0.8 * s, 0.44 * s))
    bottom.lineTo(0.8 * s, 0.6 * s)
    bottom.quadTo(0.8 * s, 0.72 * s, 0.68 * s, 0.72 * s)
    bottom.lineTo(0.2 * s, 0.72 * s)
    p.drawPath(bottom)
    _arrowhead(p, s, QPointF(0.2 * s, 0.72 * s), 180)


def _refresh(p, s, c):
    """Обновить: круговая стрелка."""
    _stroke(p, s, c, 0.08)
    rect = QRectF(0.2 * s, 0.2 * s, 0.6 * s, 0.6 * s)
    p.drawArc(rect, 60 * 16, 290 * 16)
    tip = QPointF(0.5 * s + 0.3 * s * math.cos(math.radians(60)), 0.5 * s - 0.3 * s * math.sin(math.radians(60)))
    _arrowhead(p, s, tip, -30 + 180 - 90, 0.15)


def _expand(p, s, c):
    _stroke(p, s, c, 0.08)
    p.drawLine(QPointF(0.3 * s, 0.7 * s), QPointF(0.72 * s, 0.28 * s))
    p.drawLine(QPointF(0.42 * s, 0.28 * s), QPointF(0.72 * s, 0.28 * s))
    p.drawLine(QPointF(0.72 * s, 0.28 * s), QPointF(0.72 * s, 0.58 * s))


def _close(p, s, c):
    _stroke(p, s, c, 0.08)
    p.drawLine(QPointF(0.28 * s, 0.28 * s), QPointF(0.72 * s, 0.72 * s))
    p.drawLine(QPointF(0.72 * s, 0.28 * s), QPointF(0.28 * s, 0.72 * s))


def _queue(p, s, c):
    """Очередь: три строки и треугольник «играет»."""
    _stroke(p, s, c, 0.075)
    for y in (0.3, 0.5, 0.7):
        p.drawLine(QPointF(0.38 * s, y * s), QPointF(0.84 * s, y * s))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(c)
    tri = QPainterPath(QPointF(0.14 * s, 0.22 * s))
    tri.lineTo(0.28 * s, 0.3 * s)
    tri.lineTo(0.14 * s, 0.38 * s)
    tri.closeSubpath()
    p.drawPath(tri)


def _mic(p, s, c):
    """Микрофон — исполнители."""
    _stroke(p, s, c, 0.075)
    p.drawRoundedRect(QRectF(0.38 * s, 0.14 * s, 0.24 * s, 0.4 * s), 0.12 * s, 0.12 * s)
    p.drawArc(QRectF(0.26 * s, 0.3 * s, 0.48 * s, 0.38 * s), 200 * 16, 140 * 16)
    p.drawLine(QPointF(0.5 * s, 0.68 * s), QPointF(0.5 * s, 0.84 * s))
    p.drawLine(QPointF(0.36 * s, 0.84 * s), QPointF(0.64 * s, 0.84 * s))


def _disc(p, s, c):
    """Пластинка — альбомы."""
    _stroke(p, s, c, 0.075)
    p.drawEllipse(QPointF(0.5 * s, 0.5 * s), 0.33 * s, 0.33 * s)
    p.drawEllipse(QPointF(0.5 * s, 0.5 * s), 0.09 * s, 0.09 * s)
    p.drawArc(QRectF(0.27 * s, 0.27 * s, 0.46 * s, 0.46 * s), 110 * 16, 60 * 16)


def _moon(p, s, c):
    """Полумесяц: круг минус смещённый круг."""
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(c)
    full = QPainterPath()
    full.addEllipse(QPointF(0.48 * s, 0.52 * s), 0.3 * s, 0.3 * s)
    bite = QPainterPath()
    bite.addEllipse(QPointF(0.64 * s, 0.4 * s), 0.25 * s, 0.25 * s)
    p.drawPath(full.subtracted(bite))


def _palette(p, s, c):
    """Палитра художника: овал с вырезом и тремя красками."""
    _stroke(p, s, c, 0.07)
    path = QPainterPath()
    path.addEllipse(QRectF(0.14 * s, 0.18 * s, 0.72 * s, 0.64 * s))
    hole = QPainterPath()
    hole.addEllipse(QPointF(0.62 * s, 0.66 * s), 0.08 * s, 0.08 * s)
    p.drawPath(path)
    p.drawPath(hole)
    p.setBrush(c)
    p.setPen(Qt.PenStyle.NoPen)
    for x, y in ((0.34, 0.38), (0.52, 0.32), (0.32, 0.58)):
        p.drawEllipse(QPointF(x * s, y * s), 0.055 * s, 0.055 * s)


def _globe(p, s, c):
    _stroke(p, s, c, 0.07)
    p.drawEllipse(QPointF(0.5 * s, 0.5 * s), 0.32 * s, 0.32 * s)
    p.drawEllipse(QPointF(0.5 * s, 0.5 * s), 0.13 * s, 0.32 * s)
    p.drawLine(QPointF(0.18 * s, 0.5 * s), QPointF(0.82 * s, 0.5 * s))
    for y in (0.34, 0.66):
        half = 0.32 * math.sqrt(1 - ((y - 0.5) / 0.32) ** 2) * 0.92
        p.drawLine(QPointF((0.5 - half) * s, y * s), QPointF((0.5 + half) * s, y * s))


def _globe_off(p, s, c):
    """Офлайн: планета, перечёркнутая по диагонали."""
    _globe(p, s, c)
    pen = QPen(QColor(0, 0, 0, 0), 0.2 * s)
    p.save()
    p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    p.setPen(pen)
    p.drawLine(QPointF(0.16 * s, 0.16 * s), QPointF(0.84 * s, 0.84 * s))
    p.restore()
    _stroke(p, s, c, 0.08)
    p.drawLine(QPointF(0.16 * s, 0.16 * s), QPointF(0.84 * s, 0.84 * s))


def _chevron_left(p, s, c):
    p.translate(s, 0)
    p.rotate(90)
    _chevron(p, s, c)


def _chevron_right(p, s, c):
    p.translate(0, s)
    p.rotate(-90)
    _chevron(p, s, c)


def _settings(p, s, c):
    p.setBrush(c); p.setPen(Qt.PenStyle.NoPen)
    path = QPainterPath()
    pts, cx = [], 0.5 * s
    for k in range(8):
        a = k * 45
        for da, r in ((-10, 0.39), (10, 0.39), (17, 0.29), (28, 0.29)):
            rad = math.radians(a + da)
            pts.append(QPointF(cx + r * s * math.cos(rad), cx + r * s * math.sin(rad)))
    path.addPolygon(QPolygonF(pts)); path.closeSubpath()
    path.addEllipse(QPointF(cx, cx), 0.13 * s, 0.13 * s)
    path.setFillRule(Qt.FillRule.OddEvenFill)
    p.drawPath(path)


def _volume(p, s, c):
    p.setBrush(c); p.setPen(Qt.PenStyle.NoPen)
    _poly(p, s, [(0.14, 0.4), (0.3, 0.4), (0.5, 0.22), (0.5, 0.78), (0.3, 0.6), (0.14, 0.6)])
    _stroke(p, s, c, 0.06)
    for r in (0.14, 0.26):
        p.drawArc(QRectF((0.5 - r) * s, (0.5 - r) * s, 2 * r * s, 2 * r * s), -45 * 16, 90 * 16)


def _logo(p, s, c):
    p.setBrush(c); p.setPen(Qt.PenStyle.NoPen)
    p.drawEllipse(QRectF(0.06 * s, 0.06 * s, 0.88 * s, 0.88 * s))
    clip = QPainterPath(); clip.addEllipse(QRectF(0.06 * s, 0.06 * s, 0.88 * s, 0.88 * s))
    p.setClipPath(clip)
    # линии контрастны кругу: тёмные на светлом логотипе, светлые на тёмном
    _stroke(p, s, QColor("#070707") if c.lightness() > 128 else QColor("#ffffff"), 0.05)
    for i in range(5):
        y0 = (0.26 + i * 0.12) * s
        path = QPainterPath(QPointF(0, y0))
        for x in range(0, s + 1, 2):
            path.lineTo(x, y0 + 0.035 * s * math.sin(x / s * 2 * math.pi + i * 0.9))
        p.drawPath(path)


def _video(p, s, c):
    _stroke(p, s, c, 0.07)
    p.drawRoundedRect(QRectF(0.12 * s, 0.28 * s, 0.5 * s, 0.44 * s), 0.08 * s, 0.08 * s)
    p.setBrush(c); p.setPen(Qt.PenStyle.NoPen)
    _poly(p, s, [(0.68, 0.43), (0.9, 0.3), (0.9, 0.7), (0.68, 0.57)])


def _spark(p, s, c):
    """Итоги: большая четырёхлучевая звезда и маленькая рядом."""
    from PyQt6.QtGui import QPainterPath
    def star(cx, cy, r):
        path = QPainterPath()
        path.moveTo(cx, cy - r)
        path.quadTo(cx, cy, cx + r, cy)
        path.quadTo(cx, cy, cx, cy + r)
        path.quadTo(cx, cy, cx - r, cy)
        path.quadTo(cx, cy, cx, cy - r)
        return path
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(c)
    p.drawPath(star(0.42 * s, 0.56 * s, 0.36 * s))
    p.drawPath(star(0.8 * s, 0.2 * s, 0.15 * s))


def _eq(p, s, c):
    """Эквалайзер: три ползунка с ручками на разной высоте."""
    _stroke(p, s, c, 0.08)
    for x, y in ((0.22, 0.62), (0.5, 0.32), (0.78, 0.55)):
        p.drawLine(QPointF(x * s, 0.14 * s), QPointF(x * s, 0.86 * s))
    p.setBrush(c)
    for x, y in ((0.22, 0.62), (0.5, 0.32), (0.78, 0.55)):
        p.drawEllipse(QPointF(x * s, y * s), 0.1 * s, 0.1 * s)


def _lyrics(p, s, c):
    """Текст песни: строки разной длины и нота."""
    _stroke(p, s, c, 0.075)
    for y, x2 in ((0.26, 0.84), (0.44, 0.62), (0.62, 0.5), (0.8, 0.42)):
        p.drawLine(QPointF(0.14 * s, y * s), QPointF(x2 * s, y * s))
    p.drawLine(QPointF(0.78 * s, 0.44 * s), QPointF(0.78 * s, 0.78 * s))
    p.drawLine(QPointF(0.78 * s, 0.44 * s), QPointF(0.9 * s, 0.5 * s))
    p.setBrush(c); p.setPen(Qt.PenStyle.NoPen)
    p.drawEllipse(QPointF(0.7 * s, 0.8 * s), 0.09 * s, 0.07 * s)


def _search(p, s, c):
    _stroke(p, s, c, 0.08)
    p.drawEllipse(QRectF(0.18 * s, 0.18 * s, 0.46 * s, 0.46 * s))
    p.drawLine(QPointF(0.57 * s, 0.57 * s), QPointF(0.8 * s, 0.8 * s))


DRAW = {"queue": _queue, "mic": _mic, "disc": _disc, "moon": _moon, "palette": _palette, "globe": _globe, "globe_off": _globe_off, "repeat": _repeat, "refresh": _refresh, "expand": _expand, "close": _close, "grid": _grid, "list": _list, "playlist": _playlist, "plus": _plus, "shuffle": _shuffle, "heart": _heart, "heart_fill": _heart_fill, "chevron_left": _chevron_left, "wave": _wave, "chevron": _chevron, "chevron_right": _chevron_right, "search": _search, "lyrics": _lyrics, "eq": _eq, "spark": _spark, "video": _video, "play": _play, "pause": _pause, "next": _next, "prev": _prev, "home": _home,
        "settings": _settings, "volume": _volume, "logo": _logo}


def pixmap(name: str, color: str = "#f2f2f2", size: int = 48) -> QPixmap:
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    DRAW[name](p, size, QColor(color))
    p.end()
    return pm


def icon(name: str, color: str = "#f2f2f2", active: str | None = None) -> QIcon:
    ico = QIcon()
    ico.addPixmap(pixmap(name, color), QIcon.Mode.Normal, QIcon.State.Off)
    ico.addPixmap(pixmap(name, active or color), QIcon.Mode.Normal, QIcon.State.On)
    dim = pixmap(name, "#444444" if QColor(color).lightness() > 128 else "#8a8a8a")
    ico.addPixmap(dim, QIcon.Mode.Disabled, QIcon.State.Off)
    ico.addPixmap(dim, QIcon.Mode.Disabled, QIcon.State.On)
    return ico


ASSETS = Path(__file__).resolve().parents[1] / "assets"


def service_icon(service_cls, size: int = 40) -> QPixmap:
    """assets/<id>.png, если он есть; иначе плитка с монограммой сервиса."""
    ratio = 2  # рисуем с запасом для экранов с масштабированием
    px = size * ratio
    pm = QPixmap(px, px)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform
                     | QPainter.RenderHint.TextAntialiasing)
    radius = px * 0.28
    clip = QPainterPath()
    clip.addRoundedRect(QRectF(0, 0, px, px), radius, radius)
    p.setClipPath(clip)
    custom = QPixmap(str(ASSETS / f"{service_cls.id}.png"))
    if not custom.isNull():
        p.drawPixmap(0, 0, custom.scaled(px, px, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                         Qt.TransformationMode.SmoothTransformation))
    else:
        p.fillRect(QRectF(0, 0, px, px), QColor(service_cls.icon_color))
        f = QFont(["Segoe UI Variable Display", "Segoe UI", "Inter", "Arial"])
        f.setPixelSize(int(px * 0.38))
        f.setWeight(QFont.Weight.Black)
        p.setFont(f)
        p.setPen(QColor("#ffffff"))
        p.drawText(QRectF(0, 0, px, px), Qt.AlignmentFlag.AlignCenter,
                   service_cls.icon_letters or service_cls.name[:1])
    p.end()
    pm.setDevicePixelRatio(ratio)
    return pm


def circle_avatar(path, size: int, ring: str | None = None, ring_width: float = 0) -> QPixmap:
    """Круглая аватарка из файла; ring — цвет обводки (для выбранной)."""
    ratio = 2
    px = size * ratio
    pm = QPixmap(px, px)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform)
    inset = ring_width * ratio
    area = QRectF(inset, inset, px - 2 * inset, px - 2 * inset)
    clip = QPainterPath()
    clip.addEllipse(area)
    p.save()
    p.setClipPath(clip)
    src = QPixmap(str(path)) if path else QPixmap()
    if src.isNull():
        p.fillRect(area, QColor("#3a3a3a"))
    else:
        p.drawPixmap(area.toRect(), src.scaled(int(area.width()), int(area.height()),
                                                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                                Qt.TransformationMode.SmoothTransformation))
    p.restore()
    if ring and ring_width:
        pen = QPen(QColor(ring), ring_width * ratio)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        half = ring_width * ratio / 2
        p.drawEllipse(QRectF(half, half, px - 2 * half, px - 2 * half))
    p.end()
    pm.setDevicePixelRatio(ratio)
    return pm
