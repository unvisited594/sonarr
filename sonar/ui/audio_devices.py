"""Наушники и колонки: куда играет звук и как выглядит устройство.

Устройство вывода выбирается в плеере (кнопка с наушниками рядом с громкостью). Для каждого
устройства показывается картинка: вид угадывается по названию (вкладыши, полноразмерные,
гарнитура, колонки…), а пользователь может выбрать другой вид или свою картинку.

Настройки в config.data:
  audio_device  — описание выбранного устройства ("" — как в системе);
  device_kinds  — {описание: вид};
  device_images — {описание: имя файла своей картинки в папке настроек}.
"""
import hashlib
import math
import shutil

from PyQt6.QtCore import QPointF, QRectF, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QIcon, QImage, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap
from PyQt6.QtMultimedia import QMediaDevices
from PyQt6.QtWidgets import (QFileDialog, QFrame, QHBoxLayout, QLabel, QMenu, QMessageBox, QPushButton,
                             QSizePolicy, QToolButton, QVBoxLayout, QWidget)

from ..config import config_dir
from .theme import font

KINDS = [("over_ear", "Полноразмерные наушники"), ("earbuds", "Беспроводные вкладыши"),
         ("in_ear", "Проводные внутриканальные"), ("headset", "Игровая гарнитура"),
         ("speakers", "Колонки"), ("laptop", "Динамики ноутбука"), ("monitor", "Монитор или телевизор")]
KIND_TITLES = dict(KINDS)

# Подсказки по названию устройства: первое совпадение решает
_GUESS = [
    ("earbuds", ("airpods", "buds", "tws", "earbud", "freebuds", "pods", "вкладыш")),
    ("headset", ("headset", "гарнитур", "hyperx", "steelseries", "razer", "logitech g", "arctis", "kraken",
                 "hands-free", "handsfree")),
    ("in_ear", ("in-ear", "внутриканал", "earphone")),
    ("monitor", ("hdmi", "displayport", "monitor", "монитор", "nvidia high definition", "tv", "телевизор")),
    ("laptop", ("realtek", "динамики", "speakers (", "internal", "встроен")),
    ("speakers", ("speaker", "колонк", "jbl", "soundbar", "саундбар", "marshall", "яндекс станция", "станция")),
    ("over_ear", ("headphone", "наушник", "wh-", "xm", "beats", "bose", "sennheiser", "audio-technica", "ath-")),
]


def guess_kind(name: str) -> str:
    low = name.lower()
    for kind, words in _GUESS:
        if any(w in low for w in words):
            return kind
    return "over_ear"


# ---------- рисунки ----------

def _pen(c: QColor, w: float) -> QPen:
    pen = QPen(c, w)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    return pen


def draw_device(p: QPainter, kind: str, r: QRectF, accent: QColor) -> None:
    """Обобщённый рисунок устройства этого вида в прямоугольнике r (без марок и логотипов)."""
    s = min(r.width(), r.height())
    cx, cy = r.center().x(), r.center().y()
    body = QColor("#2b2b31")
    shine = QColor(255, 255, 255, 60)
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing)

    def grad(top: QColor, bottom: QColor, rect: QRectF) -> QLinearGradient:
        g = QLinearGradient(rect.topLeft(), rect.bottomLeft())
        g.setColorAt(0, top)
        g.setColorAt(1, bottom)
        return g

    if kind in ("over_ear", "headset"):
        # оголовье — дуга, чашки по бокам
        p.setPen(_pen(body, s * 0.07))
        p.setBrush(Qt.BrushStyle.NoBrush)
        arc = QRectF(cx - s * 0.34, cy - s * 0.4, s * 0.68, s * 0.66)
        p.drawArc(arc, 10 * 16, 160 * 16)
        p.setPen(_pen(accent, s * 0.03))
        p.drawArc(arc.adjusted(s * 0.05, s * 0.05, -s * 0.05, -s * 0.05), 30 * 16, 120 * 16)
        for side in (-1, 1):
            cup = QRectF(cx + side * s * 0.33 - s * 0.12, cy - s * 0.05, s * 0.24, s * 0.36)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(grad(QColor("#45454d"), body, cup))
            p.drawRoundedRect(cup, s * 0.1, s * 0.1)
            p.setBrush(accent)
            p.drawRoundedRect(QRectF(cup.center().x() - s * 0.03 * side - s * 0.025, cup.top() + s * 0.06,
                                     s * 0.05, cup.height() - s * 0.12), s * 0.025, s * 0.025)
            p.setBrush(shine)
            p.drawEllipse(QRectF(cup.left() + s * 0.04, cup.top() + s * 0.04, s * 0.06, s * 0.08))
        if kind == "headset":   # микрофон на гибкой штанге
            p.setPen(_pen(body, s * 0.035))
            p.setBrush(Qt.BrushStyle.NoBrush)
            path = QPainterPath(QPointF(cx - s * 0.3, cy + s * 0.25))
            path.cubicTo(QPointF(cx - s * 0.3, cy + s * 0.42), QPointF(cx - s * 0.12, cy + s * 0.44),
                         QPointF(cx - s * 0.04, cy + s * 0.4))
            p.drawPath(path)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(accent)
            p.drawEllipse(QPointF(cx - s * 0.03, cy + s * 0.4), s * 0.045, s * 0.045)
    elif kind == "earbuds":
        # открытый кейс и два вкладыша
        case = QRectF(cx - s * 0.3, cy - s * 0.02, s * 0.6, s * 0.36)
        edge = _pen(QColor("#8e8e98"), max(1.0, s * 0.018))   # белое на светлом — нужен контур
        p.setPen(edge)
        p.setBrush(grad(QColor("#fafafa"), QColor("#d9d9de"), case))
        p.drawRoundedRect(case, s * 0.16, s * 0.16)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 60))
        p.drawRect(QRectF(case.left() + s * 0.02, case.top() + s * 0.1, case.width() - s * 0.04, s * 0.014))
        p.setBrush(accent)
        p.drawEllipse(QPointF(cx, case.top() + s * 0.2), s * 0.022, s * 0.022)
        p.setPen(edge)
        for side in (-1, 1):
            bx = cx + side * s * 0.16
            p.setBrush(grad(QColor("#ffffff"), QColor("#dedee4"), QRectF(bx - s * 0.08, cy - s * 0.4, s * 0.16, s * 0.4)))
            p.drawEllipse(QPointF(bx, cy - s * 0.27), s * 0.085, s * 0.075)
            stem = QRectF(bx - s * 0.03 + side * s * 0.02, cy - s * 0.26, s * 0.06, s * 0.22)
            p.drawRoundedRect(stem, s * 0.03, s * 0.03)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor("#3a3a42"))
            p.drawEllipse(QPointF(bx - side * s * 0.035, cy - s * 0.28), s * 0.028, s * 0.024)
            p.setBrush(accent)
            p.drawEllipse(QPointF(stem.center().x(), stem.bottom() - s * 0.02), s * 0.014, s * 0.014)
            p.setPen(edge)
    elif kind == "in_ear":
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(_pen(QColor("#3a3a42"), s * 0.025))
        for side in (-1, 1):
            path = QPainterPath(QPointF(cx + side * s * 0.18, cy - s * 0.12))
            path.cubicTo(QPointF(cx + side * s * 0.2, cy + s * 0.1), QPointF(cx + side * s * 0.04, cy + s * 0.12),
                         QPointF(cx, cy + s * 0.2))
            p.drawPath(path)
        p.drawLine(QPointF(cx, cy + s * 0.2), QPointF(cx, cy + s * 0.38))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(accent)
        p.drawRoundedRect(QRectF(cx - s * 0.025, cy + s * 0.14, s * 0.05, s * 0.09), s * 0.02, s * 0.02)
        p.setBrush(QColor("#3a3a42"))
        p.drawRoundedRect(QRectF(cx - s * 0.03, cy + s * 0.36, s * 0.06, s * 0.08), s * 0.015, s * 0.015)
        for side in (-1, 1):
            bx = cx + side * s * 0.18
            p.setBrush(grad(QColor("#4a4a52"), QColor("#26262c"), QRectF(bx - s * 0.08, cy - s * 0.32, s * 0.16, s * 0.22)))
            p.drawEllipse(QPointF(bx, cy - s * 0.2), s * 0.08, s * 0.09)
            p.setBrush(accent)
            p.drawEllipse(QPointF(bx - side * s * 0.07, cy - s * 0.27), s * 0.045, s * 0.04)
            p.setBrush(shine)
            p.drawEllipse(QPointF(bx - s * 0.03, cy - s * 0.24), s * 0.02, s * 0.025)
    elif kind == "speakers":
        for side in (-1, 1):
            box = QRectF(cx + side * s * 0.21 - s * 0.16, cy - s * 0.36, s * 0.32, s * 0.72)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(grad(QColor("#45454d"), body, box))
            p.drawRoundedRect(box, s * 0.05, s * 0.05)
            p.setBrush(QColor("#16161a"))
            p.drawEllipse(QPointF(box.center().x(), box.top() + s * 0.16), s * 0.07, s * 0.07)
            p.drawEllipse(QPointF(box.center().x(), box.bottom() - s * 0.2), s * 0.12, s * 0.12)
            p.setBrush(accent)
            p.drawEllipse(QPointF(box.center().x(), box.bottom() - s * 0.2), s * 0.04, s * 0.04)
            p.setBrush(shine)
            p.drawEllipse(QPointF(box.center().x() - s * 0.03, box.top() + s * 0.14), s * 0.02, s * 0.02)
    elif kind == "laptop":
        screen = QRectF(cx - s * 0.32, cy - s * 0.34, s * 0.64, s * 0.42)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(body)
        p.drawRoundedRect(screen, s * 0.03, s * 0.03)
        p.setBrush(grad(accent.lighter(130), accent.darker(160), screen))
        p.drawRect(screen.adjusted(s * 0.03, s * 0.03, -s * 0.03, -s * 0.03))
        base = QPainterPath()
        base.moveTo(cx - s * 0.4, cy + s * 0.16)
        base.lineTo(cx + s * 0.4, cy + s * 0.16)
        base.lineTo(cx + s * 0.36, cy + s * 0.08)
        base.lineTo(cx - s * 0.36, cy + s * 0.08)
        base.closeSubpath()
        p.setBrush(QColor("#55555e"))
        p.drawPath(base)
        p.setPen(_pen(QColor(255, 255, 255, 200), s * 0.025))
        for i in range(3):   # волны звука
            rr = s * (0.06 + i * 0.06)
            p.drawArc(QRectF(cx + s * 0.02 - rr, cy - s * 0.13 - rr, 2 * rr, 2 * rr), -40 * 16, 80 * 16)
    else:   # monitor
        screen = QRectF(cx - s * 0.38, cy - s * 0.32, s * 0.76, s * 0.46)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(body)
        p.drawRoundedRect(screen, s * 0.03, s * 0.03)
        p.setBrush(grad(accent.lighter(130), accent.darker(170), screen))
        p.drawRect(screen.adjusted(s * 0.025, s * 0.025, -s * 0.025, -s * 0.025))
        p.setBrush(QColor("#55555e"))
        p.drawRect(QRectF(cx - s * 0.03, screen.bottom(), s * 0.06, s * 0.12))
        p.drawRoundedRect(QRectF(cx - s * 0.16, screen.bottom() + s * 0.11, s * 0.32, s * 0.04), s * 0.02, s * 0.02)
    p.restore()


def device_pixmap(kind: str, size: int, accent: str = "#ff7a00", image: str | None = None,
                  card: bool = False) -> QPixmap:
    """Картинка устройства. card=True — на светлой подложке со скруглением (для списка и карточки)."""
    ratio = 2
    pm = QPixmap(size * ratio, size * ratio)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.scale(ratio, ratio)
    r = QRectF(0, 0, size, size)
    if card:
        g = QLinearGradient(0, 0, 0, size)
        g.setColorAt(0, QColor("#f4f4f7"))
        g.setColorAt(1, QColor("#d9d9e0"))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(g)
        p.drawRoundedRect(r, size * 0.22, size * 0.22)
    if image:
        img = QImage(image)
        if not img.isNull():
            clip = QPainterPath()
            clip.addRoundedRect(r, size * 0.22, size * 0.22)
            p.setClipPath(clip)
            scaled = img.scaled(size * ratio, size * ratio, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                Qt.TransformationMode.SmoothTransformation)
            p.drawImage(QRectF(0, 0, size, size), scaled,
                        QRectF((scaled.width() - size * ratio) / 2, (scaled.height() - size * ratio) / 2,
                               size * ratio, size * ratio))
            p.end()
            pm.setDevicePixelRatio(ratio)
            return pm
    draw_device(p, kind, r.adjusted(size * 0.08, size * 0.08, -size * 0.08, -size * 0.08) if card else r,
                QColor(accent))
    p.end()
    pm.setDevicePixelRatio(ratio)
    return pm


# ---------- настройки устройства ----------

class DeviceLook:
    """Вид и своя картинка для каждого устройства (по его названию)."""

    def __init__(self, config) -> None:
        self.config = config

    def kind(self, name: str) -> str:
        return (self.config.data.get("device_kinds") or {}).get(name) or guess_kind(name)

    def image(self, name: str) -> str | None:
        file = (self.config.data.get("device_images") or {}).get(name)
        if file and (config_dir() / file).exists():
            return str(config_dir() / file)
        return None

    def set_kind(self, name: str, kind: str) -> None:
        self.config.data.setdefault("device_kinds", {})[name] = kind
        images = self.config.data.get("device_images") or {}
        file = images.pop(name, None)
        if file:
            (config_dir() / file).unlink(missing_ok=True)
        self.config.save()

    def set_image(self, name: str, path: str) -> bool:
        if QImage(path).isNull():
            return False
        file = "device_" + hashlib.sha1(name.encode()).hexdigest()[:12] + ".png"
        dest = config_dir() / file
        dest.parent.mkdir(parents=True, exist_ok=True)
        img = QImage(path)
        if max(img.width(), img.height()) > 512:   # хватит и такого размера, файл маленький
            img = img.scaled(512, 512, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        if not img.save(str(dest), "PNG"):
            shutil.copyfile(path, dest)
        self.config.data.setdefault("device_images", {})[name] = file
        self.config.save()
        return True

    def pixmap(self, name: str, size: int, accent: str, card: bool = True) -> QPixmap:
        return device_pixmap(self.kind(name), size, accent, self.image(name), card)


def find_device(description: str):
    """Устройство по описанию или None (если его сейчас нет)."""
    for dev in QMediaDevices.audioOutputs():
        if dev.description() == description:
            return dev
    return None


# ---------- панель выбора ----------

class DevicePanel(QFrame):
    """Всплывающая панель: что сейчас играет, большая картинка, список устройств."""
    chosen = pyqtSignal(str)   # описание устройства, "" — как в системе

    def __init__(self, player, look: DeviceLook, parent=None) -> None:
        super().__init__(parent, Qt.WindowType.Popup)
        self.setObjectName("flowPanel")
        self.player = player
        self.look = look
        self.setMinimumWidth(360)
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(16, 16, 16, 14)
        self.lay.setSpacing(8)
        self.rebuild()

    def rebuild(self) -> None:
        while self.lay.count():
            item = self.lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        current = self.player.output_description()
        head = QLabel("Сейчас играет в")
        head.setProperty("role", "muted")
        self.lay.addWidget(head)
        hero = QHBoxLayout()
        hero.setSpacing(14)
        pic = QLabel()
        pic.setPixmap(self.look.pixmap(current, 112, _accent()))
        pic.setFixedSize(112, 112)
        hero.addWidget(pic)
        info = QVBoxLayout()
        info.setSpacing(4)
        name = QLabel(current or "Устройство по умолчанию")
        name.setFont(font(16, QFont.Weight.Bold))
        name.setWordWrap(True)
        info.addWidget(name)
        kind = QLabel(KIND_TITLES.get(self.look.kind(current), "") if not self.look.image(current) else "Своя картинка")
        kind.setProperty("role", "muted")
        info.addWidget(kind)
        change = QPushButton("Мои наушники другие…")
        change.setObjectName("link")
        change.setCursor(Qt.CursorShape.PointingHandCursor)
        change.clicked.connect(lambda: self._kind_menu(current, change))
        info.addWidget(change, 0, Qt.AlignmentFlag.AlignLeft)
        info.addStretch(1)
        hero.addLayout(info, 1)
        self.lay.addLayout(hero)
        self.lay.addSpacing(6)
        title = QLabel("Куда выводить звук")
        title.setFont(font(14, QFont.Weight.Bold))
        self.lay.addWidget(title)
        follow = self.player.follows_system()
        default = QMediaDevices.defaultAudioOutput()
        self.lay.addWidget(self._row("Как в системе", f"сейчас: {default.description()}" if not default.isNull() else "",
                                     None, follow, ""))
        for dev in QMediaDevices.audioOutputs():
            desc = dev.description()
            self.lay.addWidget(self._row(desc, KIND_TITLES.get(self.look.kind(desc), ""), desc,
                                         not follow and desc == current, desc))

    def _row(self, title: str, sub: str, device: str | None, selected: bool, value: str) -> QWidget:
        b = QToolButton()
        b.setObjectName("deviceRow")
        b.setCheckable(True)
        b.setChecked(selected)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        b.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        b.setMinimumHeight(54)
        if device is not None:
            b.setIcon(QIcon(self.look.pixmap(device, 40, _accent())))
        else:
            b.setIcon(QIcon(_system_icon(40)))
        b.setIconSize(QSize(40, 40))
        b.setText(f"{title}\n{sub}" if sub else title)
        b.clicked.connect(lambda _=False, v=value: self._choose(v))
        return b

    def _choose(self, value: str) -> None:
        self.chosen.emit(value)
        self.rebuild()

    def _kind_menu(self, name: str, anchor: QWidget) -> None:
        menu = QMenu(self)
        current = self.look.kind(name)
        for kind, title in KINDS:
            act = menu.addAction(QIcon(device_pixmap(kind, 28, _accent(), card=True)), title)
            act.setCheckable(True)
            act.setChecked(kind == current and not self.look.image(name))
            act.triggered.connect(lambda _=False, k=kind: (self.look.set_kind(name, k), self._refresh()))
        menu.addSeparator()
        menu.addAction("Своя картинка… (фото ваших наушников)", lambda: self._pick_image(name))
        menu.exec(anchor.mapToGlobal(anchor.rect().bottomLeft()))

    def _pick_image(self, name: str) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Фото ваших наушников", "",
                                              "Изображения (*.png *.jpg *.jpeg *.webp *.bmp)")
        if path and not self.look.set_image(name, path):
            QMessageBox.warning(self, "Не получилось", "Этот файл не похож на картинку.")
        self._refresh()

    looks_changed = pyqtSignal()

    def _refresh(self) -> None:
        self.rebuild()
        self.looks_changed.emit()   # картинка поменялась — обновить кнопку в плеере


def _accent() -> str:
    return "#ff7a00"


def _system_icon(size: int) -> QPixmap:
    """Значок «как в системе»: шестерёнка-круг с волнами."""
    ratio = 2
    pm = QPixmap(size * ratio, size * ratio)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.scale(ratio, ratio)
    g = QLinearGradient(0, 0, 0, size)
    g.setColorAt(0, QColor("#f4f4f7"))
    g.setColorAt(1, QColor("#d9d9e0"))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(g)
    p.drawRoundedRect(QRectF(0, 0, size, size), size * 0.22, size * 0.22)
    c = QPointF(size / 2, size / 2)
    p.setPen(_pen(QColor("#2b2b31"), size * 0.06))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawEllipse(c, size * 0.14, size * 0.14)
    for i in range(8):
        a = i * math.pi / 4
        p.drawLine(QPointF(c.x() + math.cos(a) * size * 0.2, c.y() + math.sin(a) * size * 0.2),
                   QPointF(c.x() + math.cos(a) * size * 0.27, c.y() + math.sin(a) * size * 0.27))
    p.end()
    pm.setDevicePixelRatio(ratio)
    return pm
