"""Горячие клавиши, которые работают, даже когда Sonar свёрнут или вы в игре.

Windows: RegisterHotKey + WM_HOTKEY из очереди сообщений Qt. Медиакнопки клавиатуры
(Play/Pause, Next, Prev) Sonar занимает, только пока сам играет музыку: на паузе и когда
ничего не играет, они достаются другим плеерам (Spotify, браузеру и т. д.).
Другие системы: те же сочетания работают, пока окно Sonar активно.
Настройки — config.data["hotkeys"] = {действие: "Ctrl+Alt+Right"}, "media_keys": bool.
"""
import ctypes
import logging
import sys

from PyQt6.QtCore import QAbstractNativeEventFilter, QObject, pyqtSignal
from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtCore import Qt

log = logging.getLogger("sonar.hotkeys")

ACTIONS = [("toggle", "Пауза / играть", "Ctrl+Alt+Space"), ("next", "Следующий трек", "Ctrl+Alt+Right"),
           ("prev", "Предыдущий трек", "Ctrl+Alt+Left"), ("vol_up", "Громче", "Ctrl+Alt+Up"),
           ("vol_down", "Тише", "Ctrl+Alt+Down"), ("like", "Лайк текущему треку", "Ctrl+Alt+L"),
           ("overlay", "Показать трек поверх игр", "Ctrl+Alt+O")]
MEDIA = {"toggle": 0xB3, "next": 0xB0, "prev": 0xB1}
WM_HOTKEY = 0x0312
MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN, MOD_NOREPEAT = 0x1, 0x2, 0x4, 0x8, 0x4000

_SPECIAL = {Qt.Key.Key_Space: 0x20, Qt.Key.Key_Left: 0x25, Qt.Key.Key_Up: 0x26, Qt.Key.Key_Right: 0x27,
            Qt.Key.Key_Down: 0x28, Qt.Key.Key_Home: 0x24, Qt.Key.Key_End: 0x23, Qt.Key.Key_PageUp: 0x21,
            Qt.Key.Key_PageDown: 0x22, Qt.Key.Key_Insert: 0x2D, Qt.Key.Key_Delete: 0x2E,
            Qt.Key.Key_Comma: 0xBC, Qt.Key.Key_Period: 0xBE, Qt.Key.Key_Minus: 0xBD, Qt.Key.Key_Equal: 0xBB}


def to_native(seq_text: str) -> tuple[int, int] | None:
    """«Ctrl+Alt+Right» → (модификаторы Windows, виртуальный код клавиши)."""
    seq = QKeySequence(seq_text)
    if seq.isEmpty():
        return None
    combo = seq[0]
    key, mods = combo.key(), combo.keyboardModifiers()
    m = MOD_NOREPEAT
    if mods & Qt.KeyboardModifier.ControlModifier:
        m |= MOD_CONTROL
    if mods & Qt.KeyboardModifier.AltModifier:
        m |= MOD_ALT
    if mods & Qt.KeyboardModifier.ShiftModifier:
        m |= MOD_SHIFT
    if mods & Qt.KeyboardModifier.MetaModifier:
        m |= MOD_WIN
    k = int(key.value) if hasattr(key, "value") else int(key)
    if key in _SPECIAL:
        vk = _SPECIAL[key]
    elif 0x30 <= k <= 0x39 or 0x41 <= k <= 0x5A:
        vk = k
    elif Qt.Key.Key_F1.value <= k <= Qt.Key.Key_F24.value:
        vk = 0x70 + (k - Qt.Key.Key_F1.value)
    else:
        return None
    if m == MOD_NOREPEAT:
        return None   # без модификатора глобально не перехватываем: сломаем набор текста
    return m, vk


class _Filter(QAbstractNativeEventFilter):
    def __init__(self, owner) -> None:
        super().__init__()
        self.owner = owner

    def nativeEventFilter(self, event_type, message):
        if sys.platform == "win32" and event_type == b"windows_generic_MSG":
            from ctypes import wintypes
            msg = wintypes.MSG.from_address(int(message))
            if msg.message == WM_HOTKEY:
                self.owner._fire(int(msg.wParam))
                return True, 0
        return False, 0


class Hotkeys(QObject):
    triggered = pyqtSignal(str)
    problems = pyqtSignal(list)   # какие сочетания не удалось занять (уже заняты другой программой)

    def __init__(self, window, config) -> None:
        super().__init__(window)
        self.win = window
        self.config = config
        self._ids: dict[int, str] = {}
        self._shortcuts: list = []
        self._filter = None
        self.failed: list[str] = []
        self._media_ids: dict[int, str] = {}
        self.playing = False
        self.apply()

    def set_playing(self, on: bool) -> None:
        """Медиакнопки — только пока Sonar играет, иначе они нужны другим программам."""
        self.playing = on
        if sys.platform == "win32":
            self._media_windows()

    def keys(self) -> dict:
        saved = self.config.data.get("hotkeys") or {}
        return {aid: saved.get(aid, default) for aid, _t, default in ACTIONS}

    @property
    def media(self) -> bool:
        return bool(self.config.data.get("media_keys", True))

    def set_key(self, aid: str, text: str) -> None:
        self.config.data.setdefault("hotkeys", {})[aid] = text
        self.config.save()
        self.apply()

    def set_media(self, on: bool) -> None:
        self.config.data["media_keys"] = on
        self.config.save()
        self.apply()

    def reset(self) -> None:
        self.config.data.pop("hotkeys", None)
        self.config.save()
        self.apply()

    def _fire(self, hid: int) -> None:
        aid = self._ids.get(hid)
        if aid:
            self.triggered.emit(aid)

    def apply(self) -> None:
        self.clear()
        self.failed = []
        if sys.platform == "win32":
            self._apply_windows()
        else:
            for aid, text in self.keys().items():
                if text:
                    sc = QShortcut(QKeySequence(text), self.win)
                    sc.setContext(Qt.ShortcutContext.ApplicationShortcut)
                    sc.activated.connect(lambda a=aid: self.triggered.emit(a))
                    self._shortcuts.append(sc)
        # медиакнопки, пока окно активно, ловит и сам Qt — на всех системах
        if self.media:
            for key, aid in ((Qt.Key.Key_MediaPlay, "toggle"), (Qt.Key.Key_MediaTogglePlayPause, "toggle"),
                             (Qt.Key.Key_MediaNext, "next"), (Qt.Key.Key_MediaPrevious, "prev")):
                sc = QShortcut(QKeySequence(key), self.win)
                sc.setContext(Qt.ShortcutContext.ApplicationShortcut)
                sc.activated.connect(lambda a=aid: self.triggered.emit(a))
                self._shortcuts.append(sc)
        self.problems.emit(self.failed)

    def _apply_windows(self) -> None:
        from PyQt6.QtCore import QCoreApplication
        user32 = ctypes.windll.user32
        if self._filter is None:
            self._filter = _Filter(self)
            QCoreApplication.instance().installNativeEventFilter(self._filter)
        hid = 0xB000
        items = [(aid, to_native(text), text) for aid, text in self.keys().items() if text]
        for aid, native, text in items:
            if native is None:
                self.failed.append(text)
                continue
            hid += 1
            if user32.RegisterHotKey(None, hid, native[0], native[1]):
                self._ids[hid] = aid
            else:
                self.failed.append(text)
        if self.failed:
            log.info("горячие клавиши заняты другими программами: %s", ", ".join(self.failed))
        self._media_windows()

    def _media_windows(self) -> None:
        user32 = ctypes.windll.user32
        for hid in list(self._media_ids):
            user32.UnregisterHotKey(None, hid)
            self._ids.pop(hid, None)
        self._media_ids.clear()
        if not (self.media and self.playing):
            return
        for n, (aid, vk) in enumerate(MEDIA.items()):
            hid = 0xBF00 + n
            if user32.RegisterHotKey(None, hid, MOD_NOREPEAT, vk):
                self._ids[hid] = aid
                self._media_ids[hid] = aid

    def clear(self) -> None:
        if sys.platform == "win32":
            for hid in list(self._ids):
                ctypes.windll.user32.UnregisterHotKey(None, hid)
        self._ids.clear()
        self._media_ids.clear()
        for sc in self._shortcuts:
            sc.setEnabled(False)
            sc.deleteLater()
        self._shortcuts.clear()


class HotkeysSection(QObject):
    """Блок «Горячие клавиши» для вкладки «Плеер»."""

    def __init__(self, hotkeys: Hotkeys, lay) -> None:
        super().__init__(hotkeys)
        from PyQt6.QtGui import QFont
        from PyQt6.QtWidgets import QGridLayout, QHBoxLayout, QKeySequenceEdit, QLabel, QPushButton
        from .theme import font
        from .widgets import Toggle, muted
        self.hk = hotkeys
        head = QLabel("Горячие клавиши")
        head.setFont(font(17, QFont.Weight.Bold, display=True))
        lay.addSpacing(22)
        lay.addWidget(head)
        note = muted(("Работают везде: даже когда Sonar свёрнут или вы в игре. " if sys.platform == "win32" else
                      "В Linux сочетания работают, пока окно Sonar активно, а медиакнопки клавиатуры и шторка "
                      "системы управляют Sonar всегда (через MPRIS). ") +
                     "Щёлкните по полю и нажмите новое сочетание (с Ctrl, Alt или Shift).")
        note.setWordWrap(True)
        note.setMaximumWidth(640)
        lay.addWidget(note)
        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(8)
        self.edits = {}
        keys = hotkeys.keys()
        for row, (aid, title, _d) in enumerate(ACTIONS):
            grid.addWidget(QLabel(title), row, 0)
            edit = QKeySequenceEdit(QKeySequence(keys[aid]))
            edit.setMaximumSequenceLength(1)
            edit.setMaximumWidth(220)
            edit.editingFinished.connect(lambda a=aid, e=edit: self.hk.set_key(a, e.keySequence().toString()))
            grid.addWidget(edit, row, 1)
            self.edits[aid] = edit
        lay.addLayout(grid)
        row = QHBoxLayout()
        row.addWidget(QLabel("Медиакнопки клавиатуры (▶❚❚, ⏭, ⏮), пока играет Sonar"))
        row.addStretch(1)
        media = Toggle()
        media.setChecked(hotkeys.media)
        media.toggled.connect(hotkeys.set_media)
        row.addWidget(media)
        wrap = QHBoxLayout()
        wrap.addLayout(row)
        lay.addLayout(wrap)
        self.warn = muted()
        self.warn.setWordWrap(True)
        self.warn.setMaximumWidth(640)
        lay.addWidget(self.warn)
        reset = QPushButton("Сбросить сочетания")
        reset.setObjectName("link")
        reset.setCursor(Qt.CursorShape.PointingHandCursor)
        reset.clicked.connect(self._reset)
        lay.addWidget(reset, 0, Qt.AlignmentFlag.AlignLeft)
        hotkeys.problems.connect(self._show_problems)
        self._show_problems(hotkeys.failed)

    def _reset(self) -> None:
        self.hk.reset()
        keys = self.hk.keys()
        for aid, edit in self.edits.items():
            edit.setKeySequence(QKeySequence(keys[aid]))

    def _show_problems(self, failed: list) -> None:
        self.warn.setText("" if not failed else "Не получилось занять: " + ", ".join(failed) +
                          ". Их уже использует другая программа (например, другой плеер) — выберите другое сочетание.")
