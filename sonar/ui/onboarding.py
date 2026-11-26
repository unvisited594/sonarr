"""Экран знакомства: имя и аватарка. Фон — живой градиент из цветов выбранной авы."""
import random

from PyQt6.QtCore import QEasingCurve, QPoint, QPropertyAnimation, QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QImage
from PyQt6.QtWidgets import (QGraphicsOpacityEffect, QHBoxLayout, QLabel, QLineEdit, QPushButton, QToolButton,
                             QVBoxLayout, QWidget)

from .. import profile as profiles
from .full_player import DEFAULT_COLORS, FRAME_MS, _mix, _text_color, paint_flow, palette_from
from .icons import circle_avatar
from .theme import font

AVATAR_SIZE = 112


class _SideAvatar(QLabel):
    """Боковая аватарка карусели: меньше и приглушена, клик — перейти к ней."""
    clicked = pyqtSignal()

    def __init__(self, size: int) -> None:
        super().__init__()
        self.setFixedSize(size, size)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._effect = QGraphicsOpacityEffect(self)
        self._effect.setOpacity(0.55)
        self.setGraphicsEffect(self._effect)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()


class AvatarCarousel(QWidget):
    """Выбор авы каруселью: по центру — выбранная (крупнее, с обводкой), по бокам —
    предыдущая и следующая. Стрелки по краям, клик по боковой и ← → на клавиатуре.
    Карусель закольцована."""
    changed = pyqtSignal(str)

    CENTER, SIDE = 156, 96

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.ids = [aid for aid, _t, _f in profiles.AVATARS]
        self.titles = {aid: title for aid, title, _f in profiles.AVATARS}
        self.index = 0
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)
        row = QHBoxLayout()
        row.setSpacing(22)
        row.addStretch(1)
        self.prev_btn = self._arrow("chevron_left", "Предыдущая", lambda: self.step(-1))
        self.left = _SideAvatar(self.SIDE)
        self.left.clicked.connect(lambda: self.step(-1))
        self.center = QLabel()
        self.center.setFixedSize(self.CENTER, self.CENTER)
        self._center_fx = QGraphicsOpacityEffect(self.center)
        self.center.setGraphicsEffect(self._center_fx)
        self._fade = QPropertyAnimation(self._center_fx, b"opacity", self)
        self._fade.setDuration(220)
        self._fade.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.right = _SideAvatar(self.SIDE)
        self.right.clicked.connect(lambda: self.step(1))
        self.next_btn = self._arrow("chevron_right", "Следующая", lambda: self.step(1))
        for wdg in (self.prev_btn, self.left, self.center, self.right, self.next_btn):
            row.addWidget(wdg, 0, Qt.AlignmentFlag.AlignVCenter)
        row.addStretch(1)
        lay.addLayout(row)
        self.name = QLabel()
        self.name.setFont(font(17, QFont.Weight.Bold))
        self.name.setAlignment(Qt.AlignmentFlag.AlignCenter)
        _text_color(self.name, "#ffffff")
        lay.addWidget(self.name)
        self.counter = QLabel()
        self.counter.setFont(font(12, QFont.Weight.DemiBold))
        self.counter.setAlignment(Qt.AlignmentFlag.AlignCenter)
        _text_color(self.counter, "rgba(255,255,255,0.6)")
        lay.addWidget(self.counter)
        self._show(animate=False)

    def _arrow(self, icon_name: str, tip: str, fn) -> QToolButton:
        from . import icons
        b = QToolButton()
        b.setObjectName("carouselArrow")
        b.setIcon(icons.icon(icon_name, "#ffffff"))
        b.setIconSize(QSize(26, 26))
        b.setFixedSize(48, 48)
        b.setToolTip(tip)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.setFocusPolicy(Qt.FocusPolicy.NoFocus)   # стрелки ← → остаются у карусели
        b.clicked.connect(fn)
        return b

    @property
    def current(self) -> str:
        return self.ids[self.index]

    def set_current(self, avatar_id: str) -> None:
        if avatar_id in self.ids:
            self.index = self.ids.index(avatar_id)
            self._show(animate=False)

    def step(self, delta: int) -> None:
        self.index = (self.index + delta) % len(self.ids)
        self._show(animate=True)
        self.changed.emit(self.current)

    def _show(self, animate: bool) -> None:
        n = len(self.ids)
        cur, prev, nxt = self.ids[self.index], self.ids[(self.index - 1) % n], self.ids[(self.index + 1) % n]
        self.center.setPixmap(circle_avatar(profiles.avatar_path(cur), self.CENTER, "#ffffff", 4))
        self.left.setPixmap(circle_avatar(profiles.avatar_path(prev), self.SIDE))
        self.right.setPixmap(circle_avatar(profiles.avatar_path(nxt), self.SIDE))
        self.left.setToolTip(self.titles[prev])
        self.right.setToolTip(self.titles[nxt])
        self.name.setText(self.titles[cur])
        self.counter.setText(f"{self.index + 1} из {n}")
        if animate:   # выбранная «проявляется»
            self._fade.stop()
            self._fade.setStartValue(0.35)
            self._fade.setEndValue(1.0)
            self._fade.start()


class Onboarding(QWidget):
    finished = pyqtSignal(dict)

    def __init__(self, window, config) -> None:
        super().__init__(window)
        self.config = config
        # Фон закрашивается целиком: Qt не нужно перерисовывать то, что под нами, на каждом кадре
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._edit = False
        self._avatar = profiles.AVATARS[0][0]
        self._t = 0.0
        self._from = list(DEFAULT_COLORS)
        self._to = list(DEFAULT_COLORS)
        self._blend = 1.0
        self._palettes: dict[str, list[QColor]] = {}
        self._anim = None
        self._timer = QTimer(self)
        self._timer.setInterval(FRAME_MS)
        self._timer.timeout.connect(self._tick)
        self.hide()

        lay = QVBoxLayout(self)
        lay.setContentsMargins(40, 40, 40, 40)
        lay.setSpacing(0)
        lay.addStretch(2)
        self.title = QLabel("Как тебя звать?")
        self.title.setFont(font(46, QFont.Weight.Black, display=True))
        self.title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        _text_color(self.title, "#ffffff")
        lay.addWidget(self.title)
        lay.addSpacing(6)
        self.subtitle = QLabel("Выбери аву и введи имя")
        self.subtitle.setFont(font(19, QFont.Weight.DemiBold))
        self.subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        _text_color(self.subtitle, "rgba(255,255,255,0.8)")
        lay.addWidget(self.subtitle)
        lay.addSpacing(40)

        self.carousel = AvatarCarousel()
        self.carousel.changed.connect(self.select_avatar)
        lay.addWidget(self.carousel)
        lay.addSpacing(30)

        self.name = QLineEdit()
        self.name.setObjectName("onboardName")
        self.name.setPlaceholderText("Твоё имя")
        self.name.setMaxLength(40)
        self.name.setFixedWidth(380)
        self.name.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.name.setFont(font(18, QFont.Weight.DemiBold))
        pal = self.name.palette()  # подсказка в поле: светлая поверх цветного фона при любой теме
        pal.setColor(pal.ColorRole.PlaceholderText, QColor(255, 255, 255, 150))
        pal.setColor(pal.ColorRole.Text, QColor("#ffffff"))
        self.name.setPalette(pal)
        self.name.textChanged.connect(self._update_done)
        self.name.returnPressed.connect(self._done)
        lay.addWidget(self.name, 0, Qt.AlignmentFlag.AlignHCenter)
        lay.addSpacing(22)

        self.done_btn = QPushButton("Готово")
        self.done_btn.setObjectName("onboardDone")
        self.done_btn.setFixedWidth(220)
        self.done_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.done_btn.clicked.connect(self._done)
        lay.addWidget(self.done_btn, 0, Qt.AlignmentFlag.AlignHCenter)
        lay.addSpacing(10)
        self.skip_btn = QPushButton("Пропустить")
        self.skip_btn.setObjectName("onboardSkip")
        self.skip_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.skip_btn.clicked.connect(self._skip)
        lay.addWidget(self.skip_btn, 0, Qt.AlignmentFlag.AlignHCenter)
        lay.addStretch(3)

        window.installEventFilter(self)
        self.select_avatar(self._avatar)
        self._update_done()

    # ---------- показ ----------

    def open(self, edit: bool = False) -> None:
        """edit=False — первое знакомство; edit=True — смена имени и авы из меню."""
        self._edit = edit
        current = profiles.get(self.config) or {}
        self.title.setText("Профиль" if edit else "Как тебя звать?")
        self.subtitle.setText("Смени аву или имя" if edit else "Выбери аву и введи имя")
        self.done_btn.setText("Сохранить" if edit else "Готово")
        self.skip_btn.setText("Отмена" if edit else "Пропустить")
        self.name.setText(current.get("name", "") if edit else "")
        self.select_avatar(current.get("avatar") or profiles.AVATARS[0][0])
        parent = self.parent()
        self.setGeometry(parent.rect())
        self.show()
        self.raise_()
        # Пустое поле с выравниванием по центру Qt не подписывает, пока оно в фокусе,
        # поэтому при знакомстве фокус на экране, а не в поле — подсказка «Твоё имя» видна.
        (self.name if self.name.text() else self).setFocus()
        self._timer.start()
        if edit:
            self._slide(QPoint(0, parent.height()), QPoint(0, 0))

    def _close(self) -> None:
        self._slide(self.pos(), QPoint(0, self.parent().height()), on_done=self._hide_now)

    def _hide_now(self) -> None:
        self._timer.stop()
        self.hide()

    def _slide(self, start, end, on_done=None) -> None:
        if self._anim is not None:
            self._anim.stop()
        self._anim = QPropertyAnimation(self, b"pos", self)
        self._anim.setDuration(300)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.setStartValue(start)
        self._anim.setEndValue(end)
        if on_done:
            self._anim.finished.connect(on_done)
        self._anim.start()

    def eventFilter(self, obj, event) -> bool:
        if obj is self.parent() and event.type() == event.Type.Resize and self.isVisible():
            self.setGeometry(self.parent().rect())
        return False

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key.Key_Left, Qt.Key.Key_Right) and not self.name.hasFocus():
            self.carousel.step(-1 if event.key() == Qt.Key.Key_Left else 1)
        elif event.key() == Qt.Key.Key_Escape and self._edit:
            self._close()
        elif event.text().strip() and event.text().isprintable():
            # фокус на экране, но печатать можно сразу: буква уходит в поле имени
            self.name.setFocus()
            self.name.insert(event.text())
        else:
            super().keyPressEvent(event)

    # ---------- выбор ----------

    def select_avatar(self, avatar_id: str) -> None:
        self._avatar = avatar_id
        if self.carousel.current != avatar_id:
            self.carousel.set_current(avatar_id)
        if avatar_id not in self._palettes:
            path = profiles.avatar_path(avatar_id)
            image = QImage(str(path)) if path else QImage()
            self._palettes[avatar_id] = palette_from(image) if not image.isNull() else list(DEFAULT_COLORS)
        k = min(self._blend, 1.0)
        self._from = [_mix(a, b, k) for a, b in zip(self._from, self._to)]
        self._to = self._palettes[avatar_id]
        self._blend = 0.0

    def _update_done(self) -> None:
        self.done_btn.setEnabled(bool(self.name.text().strip()))

    def _done(self) -> None:
        name = self.name.text().strip()
        if not name:
            self.name.setFocus()
            return
        self.finished.emit(profiles.save(self.config, name, self._avatar))
        self._close()

    def _skip(self) -> None:
        if self._edit:  # «Отмена»: ничего не меняем
            self._close()
            return
        avatar = random.choice(profiles.AVATARS)[0]
        self.finished.emit(profiles.save(self.config, profiles.random_name(), avatar))
        self._close()

    # ---------- фон ----------

    def _tick(self) -> None:
        self._t += FRAME_MS / 1000 * 1.1
        if self._blend < 1.0:
            self._blend = min(1.0, self._blend + FRAME_MS / 900)
        self.update()

    def paintEvent(self, _event) -> None:
        from PyQt6.QtGui import QPainter
        k = min(self._blend, 1.0)
        colors = [_mix(a, b, k) for a, b in zip(self._from, self._to)]
        painter = QPainter(self)
        paint_flow(painter, self.rect(), colors, self._t, 0.8)
