"""Настройки → Данные: «Статус в Discord» и «Обновления». Плюс сама проверка обновлений."""
import time
import webbrowser

from PyQt6 import sip
from PyQt6.QtCore import QObject, Qt, QTimer
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QMessageBox, QProgressDialog, QPushButton, QVBoxLayout

from .. import updater
from ..workers import run_async
from .theme import font

CHECK_EVERY = 6 * 3600 * 1000


def _card(title: str) -> tuple[QFrame, QVBoxLayout]:
    card = QFrame()
    card.setObjectName("serviceCard")   # как остальные карточки вкладки «Данные»
    card.setMaximumWidth(640)
    lay = QVBoxLayout(card)
    lay.setContentsMargins(18, 14, 18, 16)
    lay.setSpacing(8)
    t = QLabel(title)
    t.setFont(font(17, QFont.Weight.Bold, display=True))
    lay.addWidget(t)
    return card, lay


def _muted(text: str = "") -> QLabel:
    label = QLabel(text)
    label.setProperty("role", "muted")
    label.setWordWrap(True)
    label.setTextFormat(Qt.TextFormat.PlainText)
    return label


class Updates(QObject):
    """Проверяет релизы: при запуске (через 8 с) и раз в 6 часов, если включено."""

    def __init__(self, window, config, repo: str) -> None:
        super().__init__(window)
        self.win = window
        self.config = config
        self.repo = repo
        self.status = "Ещё не проверяли"
        self.on_status = None   # колбэк для карточки в настройках
        self._busy = False
        self._timer = QTimer(self, interval=CHECK_EVERY)
        self._timer.timeout.connect(lambda: self.check(manual=False))
        if self.auto:
            QTimer.singleShot(8000, lambda: self.check(manual=False))
            self._timer.start()

    @property
    def auto(self) -> bool:
        return bool(self.config.data.get("update_auto", True))

    def set_auto(self, on: bool) -> None:
        self.config.data["update_auto"] = on
        self.config.save()
        self._timer.start() if on else self._timer.stop()

    def _set_status(self, text: str) -> None:
        self.status = text
        if self.on_status:
            self.on_status(text)

    def check(self, manual: bool = True) -> None:
        if self._busy:
            return
        if not manual and updater.current() == "dev":
            return   # сборка без номера версии — сама не пристаёт
        self._busy = True
        self._set_status("Проверяю…")

        def done(release):
            self._busy = False
            if sip.isdeleted(self):
                return
            stamp = time.strftime("%H:%M")
            if not release:
                self._set_status(f"Релизов пока нет (проверено в {stamp})")
                return
            newer = updater.is_newer(release["version"])
            if not newer:
                if updater.current() == "dev":
                    self._set_status(f"Последний релиз — {release['version'] or release['tag']}; у вас сборка без номера "
                                     f"(проверено в {stamp})")
                else:
                    self._set_status(f"У вас последняя версия {updater.current()} (проверено в {stamp})")
                if manual and updater.current() == "dev":
                    self._offer(release, dev=True)
                return
            self._set_status(f"Доступна версия {release['version']}")
            if manual or self.config.data.get("update_skip") != release["version"]:
                self._offer(release)

        def failed(msg):
            self._busy = False
            if not sip.isdeleted(self):
                self._set_status(f"Не получилось проверить: {msg}")
        run_async(updater.latest, self.repo, on_done=done, on_error=failed)

    def _offer(self, release: dict, dev: bool = False) -> None:
        box = QMessageBox(self.win)
        box.setWindowTitle("Обновление Sonar")
        box.setTextFormat(Qt.TextFormat.PlainText)
        notes = release["notes"][:1200] + ("…" if len(release["notes"]) > 1200 else "")
        head = (f"Последний релиз — {release['version'] or release['tag']}. У вас сборка без номера версии."
                if dev else f"Вышла новая версия Sonar: {release['version']} (у вас {updater.current()}).")
        box.setText(head + ("\n\nЧто нового:\n" + notes if notes else ""))
        can = updater.can_self_update() and release.get("asset_url")
        go = box.addButton("Обновить сейчас" if can else "Открыть страницу релиза", QMessageBox.ButtonRole.AcceptRole)
        later = box.addButton("Позже", QMessageBox.ButtonRole.RejectRole)
        skip = None if dev else box.addButton("Пропустить эту версию", QMessageBox.ButtonRole.DestructiveRole)
        box.exec()
        clicked = box.clickedButton()
        if clicked is skip and skip is not None:
            self.config.data["update_skip"] = release["version"]
            self.config.save()
        elif clicked is go:
            if can:
                self._install(release)
            else:
                webbrowser.open(release["url"])
        del later

    def _install(self, release: dict) -> None:
        progress = {"done": 0, "total": 0}
        dlg = QProgressDialog("Скачиваю обновление…", "Отмена", 0, 100, self.win)
        dlg.setWindowTitle("Обновление Sonar")
        dlg.setWindowModality(Qt.WindowModality.WindowModal)
        dlg.setMinimumDuration(0)
        dlg.setValue(0)
        tick = QTimer(dlg, interval=150)

        def update_bar():
            total = progress.get("total") or 0
            if total:
                dlg.setValue(min(99, int(progress["done"] * 100 / total)))
                dlg.setLabelText(f"Скачиваю обновление… {progress['done'] / 1048576:.0f} из {total / 1048576:.0f} МБ")
            if dlg.wasCanceled():
                progress["cancel"] = True
        tick.timeout.connect(update_bar)
        tick.start()

        def downloaded(path):
            tick.stop()
            if progress.get("cancel"):
                dlg.close()
                return
            dlg.setLabelText("Распаковываю…")
            dlg.setValue(99)

            def ready(new_dir):
                dlg.close()
                answer = QMessageBox.question(self.win, "Обновление Sonar",
                                              "Всё готово. Sonar закроется на несколько секунд и откроется уже новым. "
                                              "Настройки и скачанные треки останутся на месте. Обновить сейчас?")
                if answer == QMessageBox.StandardButton.Yes:
                    updater.launch_installer(new_dir)
                    self.win.quit_app() if hasattr(self.win, "quit_app") else self.win.close()

            def bad(msg):
                dlg.close()
                QMessageBox.warning(self.win, "Обновление Sonar", f"Архив обновления не распаковался: {msg}")
            run_async(updater.prepare, path, on_done=ready, on_error=bad)

        def failed(msg):
            tick.stop()
            dlg.close()
            if not progress.get("cancel"):
                QMessageBox.warning(self.win, "Обновление Sonar",
                                    f"Не получилось скачать обновление: {msg}\nМожно скачать вручную со страницы релиза.")
        run_async(updater.download, release, progress, on_done=downloaded, on_error=failed)


class ExtrasSection(QObject):
    """Две карточки для вкладки «Данные»: self.cards — их вставляет главное окно."""

    def __init__(self, config, presence, updates: Updates, on_discord_toggle, parent=None) -> None:
        super().__init__(parent)
        from .widgets import Toggle
        self.config = config
        self.cards = []

        card, c = _card("Статус в Discord")
        row = QHBoxLayout()
        row.addWidget(_muted("Показывать друзьям в Discord, что вы слушаете: трек, исполнитель, обложка и время. "
                             "Нужен запущенный Discord на этом компьютере."), 1)
        self.discord = Toggle()
        self.discord.setChecked(bool(config.data.get("discord_on", True)))
        self.discord.toggled.connect(on_discord_toggle)
        row.addWidget(self.discord)
        c.addLayout(row)
        if not presence.app_id:
            c.addWidget(_muted("Статус пока не настроен в этой сборке (нет Application ID)."))
        self.cards.append(card)

        card, c = _card("Обновления")
        c.addWidget(_muted(f"Версия: {updater.current()}"))
        row = QHBoxLayout()
        row.addWidget(_muted("Проверять новые версии сами и предлагать обновиться. Настройки и скачанные "
                             "треки при обновлении не трогаются."), 1)
        auto = Toggle()
        auto.setChecked(updates.auto)
        auto.toggled.connect(updates.set_auto)
        row.addWidget(auto)
        c.addLayout(row)
        self.status = _muted(updates.status)
        c.addWidget(self.status)
        row = QHBoxLayout()
        check = QPushButton("Проверить сейчас")
        check.setCursor(Qt.CursorShape.PointingHandCursor)
        check.clicked.connect(lambda: updates.check(manual=True))
        row.addWidget(check)
        row.addStretch(1)
        c.addLayout(row)
        updates.on_status = lambda text: None if sip.isdeleted(self.status) else self.status.setText(text)
        self.cards.append(card)
