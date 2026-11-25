"""«Применяю настройки»: размытый снимок окна поверх него, пока Qt применяет тему.

Применение таблицы стилей занимает доли секунды и блокирует интерфейс — это ограничение Qt,
его не вынести в фон. Поэтому перед применением окно «замораживается» размытым снимком с
надписью: вместо зависшего интерфейса человек видит понятное действие, затем слой растворяется.
"""
from PyQt6.QtCore import QEasingCurve, QPropertyAnimation, QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QPainter, QPainterPath, QPixmap
from PyQt6.QtWidgets import QGraphicsOpacityEffect, QWidget

from .theme import font


def blurred(pm: QPixmap, strength: int = 12) -> QPixmap:
    """Быстрое размытие: уменьшить в strength раз и растянуть обратно со сглаживанием (дважды)."""
    if pm.isNull():
        return pm
    img = pm.toImage()
    w, h = img.width(), img.height()
    for _ in range(2):
        small = img.scaled(max(1, w // strength), max(1, h // strength),
                           Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
        img = small.scaled(w, h, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
    out = QPixmap.fromImage(img)
    out.setDevicePixelRatio(pm.devicePixelRatio())
    return out


class BusyOverlay(QWidget):
    def __init__(self, window: QWidget) -> None:
        super().__init__(window)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
        self._shot = QPixmap()
        self._text = ""
        self._effect = QGraphicsOpacityEffect(self)
        self._effect.setOpacity(1.0)
        self.setGraphicsEffect(self._effect)
        self._anim = QPropertyAnimation(self._effect, b"opacity", self)
        self._anim.setDuration(260)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.finished.connect(self._done)
        self.hide()

    def cover(self, text: str = "Применяю настройки") -> None:
        """Показать размытый снимок окна с надписью — и сразу нарисовать, до тяжёлой работы."""
        window = self.parentWidget()
        self._anim.stop()
        self._effect.setOpacity(1.0)
        self._shot = blurred(window.grab())
        self._text = text
        self.setGeometry(window.rect())
        self.show()
        self.raise_()
        self.repaint()   # синхронно: следующая операция надолго займёт поток интерфейса

    def release(self) -> None:
        if not self.isVisible():
            return
        self._anim.setStartValue(1.0)
        self._anim.setEndValue(0.0)
        self._anim.start()

    def _done(self) -> None:
        if self._effect.opacity() < 0.05:
            self.hide()
            self._shot = QPixmap()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if not self._shot.isNull():
            p.drawPixmap(self.rect(), self._shot)
        p.fillRect(self.rect(), QColor(0, 0, 0, 90))
        if not self._text:
            return
        f = font(18, QFont.Weight.Bold)
        p.setFont(f)
        tw = p.fontMetrics().horizontalAdvance(self._text)
        box = QRectF(0, 0, tw + 64, 58)
        box.moveCenter(QRectF(self.rect()).center())
        path = QPainterPath()
        path.addRoundedRect(box, 18, 18)
        p.fillPath(path, QColor(18, 18, 20, 215))
        p.setPen(QColor("#ffffff"))
        p.drawText(box, Qt.AlignmentFlag.AlignCenter, self._text)
