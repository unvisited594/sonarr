"""Анимации управления: смена страниц и вкладок, уведомления, «подпрыгивание» кнопок.

Все — на снимках и прозрачности, без пересчёта раскладок: анимации сами не должны тормозить.
"""
import math

from PyQt6.QtCore import QEasingCurve, QPoint, QPropertyAnimation, QSize, Qt, QVariantAnimation
from PyQt6.QtWidgets import QGraphicsOpacityEffect, QLabel, QStackedWidget

FADE_MS = 220


class _Ghost(QLabel):
    """Снимок прежнего содержимого, который растворяется поверх нового."""

    def __init__(self, parent) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self._effect)
        self._anim = QPropertyAnimation(self._effect, b"opacity", self)
        self._anim.setDuration(FADE_MS)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.finished.connect(self.hide)
        self.hide()

    def fade(self, pixmap, rect) -> None:
        if pixmap is None or pixmap.isNull():
            return
        self._anim.stop()
        self.setPixmap(pixmap)
        self.setGeometry(rect)
        self._effect.setOpacity(1.0)
        self.show()
        self.raise_()
        self._anim.setStartValue(1.0)
        self._anim.setEndValue(0.0)
        self._anim.start()


class FadeStack(QStackedWidget):
    """Стек страниц с плавной сменой: прежняя страница растворяется поверх новой."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._ghost = _Ghost(self)
        self.animate = True

    def _switch(self, apply) -> None:
        old = self.currentWidget()
        snapshot = old.grab() if (self.animate and old is not None and self.isVisible()) else None
        apply()
        if snapshot is not None and self.currentWidget() is not old:
            self._ghost.fade(snapshot, self.rect())

    def setCurrentIndex(self, index: int) -> None:
        if index != self.currentIndex():
            self._switch(lambda: QStackedWidget.setCurrentIndex(self, index))

    def setCurrentWidget(self, widget) -> None:
        if widget is not self.currentWidget():
            self._switch(lambda: QStackedWidget.setCurrentWidget(self, widget))


def attach_tab_fade(tabs) -> None:
    """Плавная смена вкладок QTabWidget: снимок берётся до переключения (tabBarClicked)."""
    ghost = _Ghost(tabs)
    state = {"shot": None}

    def before(index: int) -> None:
        current = tabs.currentWidget()
        if index != tabs.currentIndex() and current is not None and tabs.isVisible():
            state["shot"] = (current.grab(), current.geometry())

    def after(_index: int) -> None:
        if state["shot"] is not None:
            pixmap, rect = state["shot"]
            state["shot"] = None
            ghost.fade(pixmap, rect)
    tabs.tabBarClicked.connect(before)
    tabs.currentChanged.connect(after)


def pop(button, scale: float = 0.32, duration: int = 280) -> None:
    """Кнопка «подпрыгивает»: иконка на миг увеличивается и возвращается."""
    base = getattr(button, "_pop_base", None) or button.iconSize()
    button._pop_base = QSize(base)
    anim = getattr(button, "_pop_anim", None)
    if anim is None:
        anim = QVariantAnimation(button)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setDuration(duration)

        def step(t, b=button):
            k = 1 + scale * math.sin(math.pi * float(t))
            b.setIconSize(QSize(round(b._pop_base.width() * k), round(b._pop_base.height() * k)))
        anim.valueChanged.connect(step)
        anim.finished.connect(lambda b=button: b.setIconSize(b._pop_base))
        button._pop_anim = anim
    anim.stop()
    anim.start()


class ToastAnimator:
    """Уведомление выезжает снизу и проявляется; уходит — растворяясь."""

    def __init__(self, toast) -> None:
        self.toast = toast
        self.effect = QGraphicsOpacityEffect(toast)
        toast.setGraphicsEffect(self.effect)
        self.fade = QPropertyAnimation(self.effect, b"opacity", toast)
        self.fade.setDuration(200)
        self.slide = QPropertyAnimation(toast, b"pos", toast)
        self.slide.setDuration(240)
        self.slide.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._hiding = False
        self.fade.finished.connect(self._fade_done)

    def show_at(self, pos: QPoint) -> None:
        self._hiding = False
        self.fade.stop()
        self.slide.stop()
        if not self.toast.isVisible() or self.effect.opacity() < 0.99:
            self.slide.setStartValue(pos + QPoint(0, 14))
            self.slide.setEndValue(pos)
            self.toast.move(pos + QPoint(0, 14))
            self.toast.show()
            self.slide.start()
            self.fade.setStartValue(self.effect.opacity() if self.toast.isVisible() else 0.0)
            self.fade.setEndValue(1.0)
            self.fade.start()
        else:
            self.toast.move(pos)

    def hide(self) -> None:
        if not self.toast.isVisible():
            return
        self._hiding = True
        self.fade.stop()
        self.fade.setStartValue(self.effect.opacity())
        self.fade.setEndValue(0.0)
        self.fade.start()

    def _fade_done(self) -> None:
        if self._hiding:
            self._hiding = False
            self.toast.hide()
