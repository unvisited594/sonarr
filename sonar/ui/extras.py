"""Мелочи для удобства: горячие и мультимедийные клавиши, значок в трее, уведомления,
очередь воспроизведения."""
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QAction, QIcon, QKeySequence, QShortcut
from PyQt6.QtWidgets import QMenu, QSystemTrayIcon

SHORTCUTS = [
    ("Пробел", "Пауза / продолжить"),
    ("Ctrl + → / ←", "Следующий / предыдущий трек"),
    ("Ctrl + ↑ / ↓", "Громче / тише"),
    ("Ctrl + L", "Лайк текущего трека"),
    ("Ctrl + F", "Поиск"),
    ("Ctrl + Enter", "Большой плеер"),
    ("Мультимедийные клавиши", "Пауза, следующий, предыдущий"),
]

MEDIA_KEYS = {Qt.Key.Key_MediaPlay, Qt.Key.Key_MediaPause, Qt.Key.Key_MediaTogglePlayPause,
              Qt.Key.Key_MediaNext, Qt.Key.Key_MediaPrevious, Qt.Key.Key_MediaStop}


def install_shortcuts(win) -> None:
    def add(seq, fn):
        sc = QShortcut(QKeySequence(seq), win)
        sc.setContext(Qt.ShortcutContext.ApplicationShortcut)
        sc.activated.connect(fn)

    def volume(step: int) -> None:
        win.bar.volume.setValue(max(0, min(100, win.bar.volume.value() + step)))
        win.show_toast(f"Громкость: {win.bar.volume.value()}%")

    def like() -> None:
        track = win.player.current
        if track is None:
            return
        if win.likes.contains(track):
            win.likes.remove(track)
            win.show_toast("Убрано из моих лайков")
        else:
            win.likes.add(track)
            win.show_toast("Добавлено в мои лайки")

    def search() -> None:
        win.nav.button(0).click()
        win.home.search.setFocus()
        win.home.search.selectAll()

    add("Ctrl+Right", win.player.next)
    add("Ctrl+Left", win.player.prev)
    add("Ctrl+Up", lambda: volume(5))
    add("Ctrl+Down", lambda: volume(-5))
    add("Ctrl+L", like)
    add("Ctrl+F", search)
    add("Ctrl+Return", lambda: win.full_player.close_player() if win.full_player.isVisible()
        else win.open_full_player())


def handle_key(win, event) -> bool:
    """Пробел и мультимедийные клавиши. True — клавиша обработана.
    Пробел в полях ввода и на кнопках им и достаётся: сюда приходит то, что никто не взял."""
    key = event.key()
    if key == Qt.Key.Key_Space and not event.modifiers():
        win.player.toggle()
        return True
    if key in MEDIA_KEYS:
        if key in (Qt.Key.Key_MediaNext,):
            win.player.next()
        elif key in (Qt.Key.Key_MediaPrevious,):
            win.player.prev()
        elif key == Qt.Key.Key_MediaStop:
            if win.player.is_playing:
                win.player.toggle()
        else:
            win.player.toggle()
        return True
    return False


class Tray:
    """Значок в трее: управление плеером, «Показать», «Выход»; уведомления о новом треке."""

    def __init__(self, win, icon: QIcon) -> None:
        self.win = win
        # иконку — до показа: без неё Windows пишет «No Icon set» и значок может не появиться
        self.icon = QSystemTrayIcon(icon, win)
        self.icon.setToolTip("Sonar")
        menu = QMenu()
        self.now = QAction("Ничего не играет", menu)
        self.now.setEnabled(False)
        menu.addAction(self.now)
        menu.addSeparator()
        self.play = menu.addAction("Играть / пауза")
        self.play.triggered.connect(win.player.toggle)
        menu.addAction("Следующий").triggered.connect(win.player.next)
        menu.addAction("Предыдущий").triggered.connect(win.player.prev)
        menu.addSeparator()
        menu.addAction("Показать Sonar").triggered.connect(self.show_window)
        menu.addAction("Выход").triggered.connect(self.quit)
        self.menu = menu   # держим ссылку: меню без владельца иначе уничтожится
        self.icon.setContextMenu(menu)
        self.icon.activated.connect(self._activated)
        self.quitting = False
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.icon.show()

    def set_icon(self, icon: QIcon) -> None:
        self.icon.setIcon(icon)

    def _activated(self, reason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.Trigger:   # одиночный клик — показать/спрятать
            if self.win.isVisible() and not self.win.isMinimized() and self.win.isActiveWindow():
                self.win.hide()
            else:
                self.show_window()

    def show_window(self) -> None:
        self.win.showNormal()
        self.win.raise_()
        self.win.activateWindow()

    def quit(self) -> None:
        self.quitting = True
        self.win.close()

    def on_track(self, track) -> None:
        text = f"{track.title} — {track.artist}" if track.artist else track.title
        self.now.setText(text[:60] + ("…" if len(text) > 60 else ""))
        self.icon.setToolTip(f"Sonar\n{text}"[:120])

    def notify(self, track) -> None:
        if self.icon.isVisible() and self.icon.supportsMessages():
            self.icon.showMessage(track.title, track.artist or "Sonar", self.icon.icon(), 3500)


def queue_menu(win, anchor) -> None:
    """Очередь воспроизведения: текущий трек и ближайшие, клик — перейти."""
    player = win.player
    menu = QMenu(win)
    if not player.queue:
        act = menu.addAction("Очередь пуста")
        act.setEnabled(False)
    else:
        start = max(0, player.index - 3)
        for i in range(start, min(len(player.queue), start + 30)):
            t = player.queue[i]
            label = f"{'▶ ' if i == player.index else '    '}{i + 1}. {t.title} — {t.artist}"
            act = menu.addAction(label[:80])
            if i == player.index:
                f = act.font()
                f.setBold(True)
                act.setFont(f)
            act.setEnabled(t.playable)
            act.triggered.connect(lambda _=False, k=i: player.play_queue(player.queue, k, player.context))
        rest = len(player.queue) - (start + 30)
        if rest > 0:
            menu.addSeparator()
            tail = menu.addAction(f"…и ещё {rest}")
            tail.setEnabled(False)
    menu.exec(anchor.mapToGlobal(anchor.rect().topLeft()))
