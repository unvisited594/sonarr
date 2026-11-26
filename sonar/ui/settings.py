from PyQt6 import sip
from PyQt6.QtCore import QSize, QTime, QTimer, Qt, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QPushButton, QTimeEdit, QToolButton,
                             QScrollArea, QTabWidget, QVBoxLayout, QWidget)

from ..services import AVAILABLE
from ..services.base import ServiceError
from ..workers import run_async
from .theme import font
from . import browser_login
from .icons import service_icon
from . import theme as themes
from .data_tab import DataTab
from .decor import AutoPreview, ThemePreview
from .widgets import Toggle, clear_layout, muted


def _small(text: str, primary: bool = False) -> QPushButton:
    b = QPushButton(text)
    b.setProperty("compact", True)
    if primary:
        b.setProperty("kind", "primary")
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    return b


class ServiceCard(QFrame):
    """Компактная строка сервиса: иконка, имя, статус, действия.
    Форма ручного ввода раскрывается под строкой."""

    refresh_requested = pyqtSignal()
    INDENT = 54  # иконка 40 + отступ 14: форма выравнивается по тексту

    def __init__(self, cls, manager, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("serviceCard")
        self.cls, self.manager = cls, manager
        self.edits: dict = {}
        self.browser_btn = self.connect_btn = None
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(14, 12, 14, 12)
        self.lay.setSpacing(0)
        self.rebuild()

    def rebuild(self) -> None:
        clear_layout(self.lay)
        self.edits.clear()
        self.browser_btn = self.connect_btn = None
        self._manual_panel = None
        service = self.manager.get(self.cls.id)

        row = QHBoxLayout()
        row.setSpacing(14)
        icon = QLabel()
        icon.setPixmap(service_icon(self.cls, 40))
        icon.setFixedSize(40, 40)
        row.addWidget(icon)
        text = QVBoxLayout()
        text.setSpacing(1)
        name = QLabel(self.cls.name)
        name.setFont(font(15, QFont.Weight.DemiBold))
        relogin = service is not None and self.cls.id in self.manager.needs_login
        if relogin:
            status = muted("Вход устарел — нужно войти заново", role="error")
        else:
            shared = service is not None and self.manager.is_shared(self.cls.id)
            if shared:
                status = muted(f"Подключено: {service.account_name} — общий сервер, вход не нужен")
            else:
                status = muted(f"Подключено: {service.account_name}" if service else self.cls.description)
        status.setFont(font(13))
        self.status_label = status
        text.addWidget(name)
        text.addWidget(status)
        row.addLayout(text, 1)

        manual_toggle = None
        self.refresh_btn = None
        if service and not relogin:
            from .widgets import Spinner
            refresh = _small("Обновить")
            refresh.setToolTip("Заново загрузить музыку сервиса и проверить вход")
            refresh.setIconSize(QSize(14, 14))
            self.refresh_btn = refresh
            self._spinner = Spinner(refresh, "refresh", "text", 14)
            self._spinner.stop()   # ставит неподвижную иконку
            refresh.clicked.connect(self._refresh)
            off = _small("Отключить")
            off.clicked.connect(self._disconnect)
            row.addWidget(refresh)
            if self.manager.is_shared(self.cls.id):
                own = QPushButton("Свой сервер")
                own.setObjectName("link")
                own.setCursor(Qt.CursorShape.PointingHandCursor)
                own.setToolTip("Подключить свой Navidrome вместо общего")
                own.clicked.connect(lambda: self.manager.disconnect(self.cls.id))
                row.addWidget(own)
            row.addWidget(off)
        elif relogin:
            # Вход отклонён: «Обновить» с тем же токеном бесполезно — предлагаем войти заново
            can_browse = (bool(self.cls.browser_login) or self.cls.login_needs_fields) \
                and browser_login.AVAILABLE
            manual_toggle = QPushButton("Вручную")
            manual_toggle.setObjectName("link")
            manual_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
            row.addWidget(manual_toggle)
            if can_browse:
                self.browser_btn = _small("Войти заново", primary=True)
                self.browser_btn.clicked.connect(self._browser_login)
                row.addWidget(self.browser_btn)
            off = _small("Отключить")
            off.clicked.connect(self._disconnect)
            row.addWidget(off)
        else:
            can_browse = (bool(self.cls.browser_login) or self.cls.login_needs_fields) \
                and browser_login.AVAILABLE
            if can_browse:
                manual_toggle = QPushButton("Настроить" if self.cls.login_needs_fields else "Вручную")
                manual_toggle.setObjectName("link")
                manual_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
                self.browser_btn = _small("Войти", primary=True)
                self.browser_btn.setToolTip("Войти в аккаунт во встроенном окне браузера")
                self.browser_btn.clicked.connect(self._browser_login)
                row.addWidget(manual_toggle)
                row.addWidget(self.browser_btn)
            else:
                if self.cls.id == "navidrome" and self.manager.shared_available():
                    shared_btn = QPushButton("Общий сервер")
                    shared_btn.setObjectName("link")
                    shared_btn.setCursor(Qt.CursorShape.PointingHandCursor)
                    shared_btn.setToolTip("Подключить общий сервер Sonar — без пароля")
                    shared_btn.clicked.connect(self.manager.use_shared)
                    row.addWidget(shared_btn)
                manual_toggle = _small("Подключить", primary=True)
                row.addWidget(manual_toggle)
        self.lay.addLayout(row)

        self.error = muted(role="error")
        self.error.setWordWrap(True)
        self.error.setContentsMargins(self.INDENT, 8, 0, 0)
        self.error.hide()

        if manual_toggle is not None:
            panel = QWidget()
            panel.hide()
            self._manual_panel = panel
            manual_toggle.clicked.connect(lambda: panel.setVisible(not panel.isVisible()))
            self.lay.addWidget(panel)
            self._build_manual(panel)
        self.lay.addWidget(self.error)

    def _build_manual(self, panel: QWidget) -> None:
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(self.INDENT, 14, 0, 4)
        lay.setSpacing(8)
        if (self.cls.browser_login or self.cls.login_needs_fields) and not browser_login.AVAILABLE:
            note = muted("Чтобы входить через браузер, установите пакет PyQt6-WebEngine.")
            note.setWordWrap(True)
            lay.addWidget(note)
        if self.cls.help_text:
            help_lbl = QLabel(self.cls.help_text)
            help_lbl.setWordWrap(True)
            help_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            help_lbl.setProperty("role", "help")
            help_lbl.setFont(font(13))
            lay.addWidget(help_lbl)
        for f in self.cls.credential_fields:
            label = QLabel(f.label)
            label.setFont(font(13, QFont.Weight.DemiBold))
            lay.addWidget(label)
            if f.multiline:
                edit = QPlainTextEdit()
                edit.setPlaceholderText(f.placeholder)
                edit.setFixedHeight(110)
            else:
                edit = QLineEdit()
                edit.setPlaceholderText(f.placeholder)
                if f.secret:
                    edit.setEchoMode(QLineEdit.EchoMode.Password)
                edit.returnPressed.connect(self._browser_login if self.cls.login_needs_fields
                                           and browser_login.AVAILABLE else self._manual_connect)
                # повторный вход: подставляем то, что уже знаем (Client ID, адрес, логин), но не секреты
                existing = self.manager.get(self.cls.id)
                if existing is not None and not f.secret and existing.settings.get(f.key):
                    edit.setText(str(existing.settings[f.key]))
            self.edits[f.key] = edit
            lay.addWidget(edit)
        if self.cls.login_needs_fields and browser_login.AVAILABLE:
            self.connect_btn = _small("Войти", primary=True)
            self.connect_btn.clicked.connect(self._browser_login)
        else:
            self.connect_btn = _small("Подключить", primary=self.browser_btn is None)
            self.connect_btn.clicked.connect(self._manual_connect)
        lay.addSpacing(2)
        lay.addWidget(self.connect_btn, 0, Qt.AlignmentFlag.AlignLeft)

    def _refresh(self) -> None:
        """Перезагрузка сервиса с видимым откликом: иконка крутится до итога."""
        if self._spinner.spinning:
            return
        self._spinner.start()
        self.refresh_btn.setText("Обновляем…")
        self.error.hide()
        self.refresh_requested.emit()

    def on_status(self, service_id: str, state: str, message: str) -> None:
        if service_id != self.cls.id:
            return
        if state == "auth":
            self.rebuild()   # покажет «Войти заново»
            return
        if self.refresh_btn is None or sip.isdeleted(self.refresh_btn) or not self._spinner.spinning:
            return
        self._spinner.stop()
        if state == "ok":
            self.refresh_btn.setText("Обновлено ✓")
            QTimer.singleShot(2000, lambda b=self.refresh_btn: None if sip.isdeleted(b) else b.setText("Обновить"))
        else:
            self.refresh_btn.setText("Обновить")
            self._show_error(message)

    def _buttons(self):
        return [b for b in (self.browser_btn, self.connect_btn)
                if b is not None and not sip.isdeleted(b)]

    def _set_busy(self, busy: bool) -> None:
        for b in self._buttons():
            b.setEnabled(not busy)
        if self.browser_btn is not None and not sip.isdeleted(self.browser_btn):
            self.browser_btn.setText("Подключаем…" if busy else "Войти")
        if busy:
            self.error.hide()

    def _show_error(self, text: str) -> None:
        if sip.isdeleted(self.error):
            return
        self.error.setText(text)
        self.error.show()
        self._set_busy(False)

    def _values(self) -> dict:
        return {key: (w.toPlainText() if isinstance(w, QPlainTextEdit) else w.text()).strip()
                for key, w in self.edits.items()}

    def _manual_connect(self) -> None:
        creds = self._values()
        for f in self.cls.credential_fields:
            if f.required and not creds.get(f.key):
                self._show_error(f"Заполните поле «{f.label}».")
                return
        self._connect(creds)

    def _browser_login(self) -> None:
        creds = self._values()
        try:
            spec = self.cls({}).prepare_login(creds)
        except ServiceError as exc:
            if self._manual_panel is not None:
                self._manual_panel.show()  # там поле, которое нужно заполнить
            self._show_error(str(exc))
            return
        self.error.hide()
        dialog = browser_login.BrowserLoginDialog(spec, self.cls.name, self.window())
        dialog.exec()
        token = dialog.token
        dialog.deleteLater()
        if not token:
            return  # пользователь закрыл окно, это не ошибка
        creds.update(spec.extra)
        creds[spec.field] = token
        self._connect(creds)

    def _connect(self, creds: dict) -> None:
        self._set_busy(True)
        service = self.cls({})
        run_async(service.connect, creds,
                  on_done=lambda _: self.manager.register(service),
                  on_error=self._show_error)

    def _disconnect(self) -> None:
        if self.manager.is_shared(self.cls.id):
            text = (f"Отключить общий сервер {self.cls.name}? Его музыка пропадёт с главной. "
                    "Вернуть его можно кнопкой «Общий сервер» здесь же.")
        else:
            text = (f"Отключить {self.cls.name}? Данные входа будут удалены с этого компьютера, "
                    "музыка сервиса пропадёт с главной.")
        answer = QMessageBox.question(self, "Отключить сервис", text)
        if answer == QMessageBox.StandardButton.Yes:
            self.manager.disconnect(self.cls.id)


class SettingRow(QFrame):
    """Строка настройки: название, пояснение и переключатель."""

    def __init__(self, title: str, description: str, checked: bool, on_change, parent=None,
                 icon=None) -> None:
        super().__init__(parent)
        self.setObjectName("serviceCard")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(18, 14, 18, 14)
        lay.setSpacing(16)
        if icon is not None:
            pic = QLabel()
            pic.setPixmap(icon)
            lay.addWidget(pic)
        text = QVBoxLayout()
        text.setSpacing(2)
        name = QLabel(title)
        name.setFont(font(15, QFont.Weight.DemiBold))
        desc = muted(description)
        desc.setFont(font(13))
        desc.setWordWrap(True)
        text.addWidget(name)
        text.addWidget(desc)
        lay.addLayout(text, 1)
        self.toggle = Toggle()
        self.toggle.setChecked(checked)
        self.toggle.toggled.connect(on_change)
        name.setBuddy(self.toggle)
        lay.addWidget(self.toggle, 0, Qt.AlignmentFlag.AlignVCenter)

    def mouseReleaseEvent(self, event) -> None:  # клик по всей строке переключает
        if event.button() == Qt.MouseButton.LeftButton:
            self.toggle.toggle()
        super().mouseReleaseEvent(event)


class ThemeCard(QFrame):
    """Карточка темы: превью, название, описание. Клик выбирает тему."""
    chosen = pyqtSignal(str)

    def __init__(self, theme_id: str, parent=None) -> None:
        super().__init__(parent)
        self.theme_id = theme_id
        self.setObjectName("themeCard")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        if theme_id == themes.AUTO_ID:
            data = {"title": "Авто", "description": "Светлая днём, тёмная вечером"}
            preview = AutoPreview(themes.THEMES[themes.DARK_ID], themes.THEMES[themes.LIGHT_ID])
        else:
            data = themes.THEMES[theme_id]
            preview = ThemePreview(data)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 12, 12, 14)
        lay.setSpacing(4)
        lay.addWidget(preview)
        lay.addSpacing(6)
        name = QLabel(data["title"])
        name.setFont(font(15, QFont.Weight.DemiBold))
        lay.addWidget(name)
        desc = muted(data["description"])
        desc.setFont(font(13))
        lay.addWidget(desc)

    def set_selected(self, on: bool) -> None:
        self.setProperty("selected", on)
        self.style().unpolish(self)
        self.style().polish(self)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.chosen.emit(self.theme_id)
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key.Key_Space, Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.chosen.emit(self.theme_id)
        else:
            super().keyPressEvent(event)


BACKGROUNDS = ("#0b1020", "#1a1033", "#0f2a1f", "#2a0f14", "#232323", "#f4efe6", "#e8f1fb", "#fde8ef")
ACCENTS = ("#ff4d6d", "#ff8a00", "#ffd60a", "#2ecc71", "#00c2c7", "#3a86ff", "#8e5cff", "#ff4ecd")


class OptionTile(QFrame):
    """Плитка выбора: картинка-превью и подпись. Без превью — плюс «добавить свою»."""
    clicked = pyqtSignal()

    def __init__(self, title: str, preview=None, round_: bool = False, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("themeCard")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._round = round_
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(6)
        self.pic = QLabel()
        self.pic.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.pic.setFixedSize(*((72, 72) if round_ else (160, 100)))
        lay.addWidget(self.pic, 0, Qt.AlignmentFlag.AlignHCenter)
        label = QLabel(title)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setFont(font(13, QFont.Weight.DemiBold))
        lay.addWidget(label)
        self.set_preview(preview)

    def set_preview(self, preview) -> None:
        if preview is None:  # «своя»: пока не выбрана — значок «добавить»
            from . import icons as _icons
            from .theme import C
            self.pic.setPixmap(_icons.pixmap("plus", C("muted"), 36))
            self.pic.setStyleSheet(f"border: 2px dashed {C('muted')}; border-radius: "
                                   f"{36 if self._round else 12}px;")
        else:
            self.pic.setStyleSheet("")
            self.pic.setPixmap(preview)

    def set_selected(self, on: bool) -> None:
        self.setProperty("selected", on)
        self.style().unpolish(self)
        self.style().polish(self)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key.Key_Space, Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.clicked.emit()
        else:
            super().keyPressEvent(event)


class SettingsPage(QWidget):
    refresh_requested = pyqtSignal()
    display_changed = pyqtSignal()
    theme_changed = pyqtSignal(str)
    theme_reapply = pyqtSignal(str)   # та же тема, но свои цвета сброшены — применить заново

    def __init__(self, manager, config, parent=None) -> None:
        super().__init__(parent)
        self.manager, self.config = manager, config
        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 32, 28, 0)
        outer.setSpacing(18)
        title = QLabel("Настройки")
        title.setFont(font(40, QFont.Weight.Black, display=True))
        outer.addWidget(title)

        self.tabs = QTabWidget()
        self.tabs.tabBar().setDrawBase(False)
        self.tabs.addTab(self._integrations_tab(), "Интеграция")
        self.tabs.addTab(self._display_tab(), "Визуальное отображение")
        self.tabs.addTab(self._themes_tab(), "Темы и оформление")
        from .anim import attach_tab_fade
        attach_tab_fade(self.tabs)
        self.data_tab = DataTab()
        self.tabs.addTab(self.data_tab, "Данные")
        outer.addWidget(self.tabs, 1)

        manager.changed.connect(self._rebuild_cards)
        manager.status.connect(lambda sid, st, msg: [c.on_status(sid, st, msg) for c in self.cards])

    @staticmethod
    def _page() -> tuple[QScrollArea, QVBoxLayout]:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        lay = QVBoxLayout(content)
        lay.setContentsMargins(0, 18, 8, 28)
        lay.setSpacing(8)
        scroll.setWidget(content)
        from .widgets import FitHeight
        scroll._fit = FitHeight(scroll)   # ничего не сплющивается на неполноэкранном окне
        return scroll, lay

    def _integrations_tab(self) -> QWidget:
        scroll, lay = self._page()
        intro = muted("Подключённые сервисы наполняют главную: ваша музыка, рекомендации "
                      "и «Моя волна».")
        intro.setWordWrap(True)
        lay.addWidget(intro)
        lay.addSpacing(8)
        self.cards = []
        for cls in AVAILABLE.values():
            card = ServiceCard(cls, self.manager)
            card.setMaximumWidth(640)
            card.refresh_requested.connect(self.refresh_requested)
            self.cards.append(card)
            lay.addWidget(card)
        lay.addStretch(1)
        return scroll

    def _display_tab(self) -> QWidget:
        scroll, lay = self._page()
        row = SettingRow(
            "Скрывать недоступные треки",
            "Треки, которые нельзя послушать (ограничения региона, подписки или правообладателя), "
            "не будут показываться на главной и в поиске.",
            bool(self.config.data.get("hide_unavailable")),
            self._set_hide_unavailable)
        row.setMaximumWidth(640)
        lay.addWidget(row)
        self._behaviour_lay = lay   # сюда add_behaviour допишет трей, уведомления и клавиши
        return scroll

    def add_behaviour(self, pers) -> None:
        """Трей, уведомления и список горячих клавиш — во «Визуальном отображении»."""
        from .extras import SHORTCUTS
        lay = self._behaviour_lay
        lay.addSpacing(18)
        for title, desc, key in (
                ("Сворачивать в трей при закрытии", "Крестик прячет окно, музыка играет дальше. Выход — "
                                                    "в меню значка в трее.", "close_to_tray"),
                ("Уведомлять о новом треке", "Всплывающее уведомление, когда окно свёрнуто или в фоне.",
                 "notify_track"),
                ("Искать трек в других сервисах", "Если трек не играет (подписка, регион, сбой), Sonar найдёт "
                 "его же в другом подключённом сервисе, включит оттуда и сообщит об этом.", "fallback_services")):
            row = SettingRow(title, desc, bool(pers.get(key)), lambda on, k=key: pers.set(k, on))
            row.setMaximumWidth(640)
            lay.addWidget(row)
        lay.addSpacing(18)
        head = QLabel("Горячие клавиши")
        head.setFont(font(17, QFont.Weight.Bold, display=True))
        lay.addWidget(head)
        card = QFrame()
        card.setObjectName("serviceCard")
        card.setMaximumWidth(640)
        grid = QGridLayout(card)
        grid.setContentsMargins(18, 12, 18, 12)
        grid.setHorizontalSpacing(24)
        grid.setVerticalSpacing(6)
        for i, (keys, what) in enumerate(SHORTCUTS):
            k = QLabel(keys)
            k.setFont(font(13, QFont.Weight.Bold))
            grid.addWidget(k, i, 0)
            grid.addWidget(muted(what), i, 1)
        lay.addWidget(card)
        lay.addStretch(1)

    def _themes_tab(self) -> QWidget:
        scroll, lay = self._page()
        self._looks_lay = lay   # сюда же add_look_tab допишет раздел «Оформление»
        head = QLabel("Темы")
        head.setFont(font(24, QFont.Weight.Black, display=True))
        lay.addWidget(head)
        lay.addSpacing(4)
        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(14)
        self.theme_cards = []
        for i, theme_id in enumerate(themes.CHOICES):
            card = ThemeCard(theme_id)
            card.chosen.connect(self._choose_theme)
            self.theme_cards.append(card)
            grid.addWidget(card, i // 2, i % 2)
        grid.setColumnStretch(2, 1)
        lay.addLayout(grid)
        lay.addSpacing(16)

        head = QLabel("Время переключения для «Авто»")
        head.setFont(font(17, QFont.Weight.Bold, display=True))
        lay.addWidget(head)
        times = QFrame()
        times.setObjectName("serviceCard")
        times.setMaximumWidth(600)
        t_lay = QHBoxLayout(times)
        t_lay.setContentsMargins(18, 12, 18, 12)
        t_lay.setSpacing(10)
        self.time_edits = {}
        for key, label, default in (("theme_light_from", "Светлая с", themes.DEFAULT_LIGHT_FROM),
                                    ("theme_dark_from", "Тёмная с", themes.DEFAULT_DARK_FROM)):
            t_lay.addWidget(QLabel(label))
            edit = QTimeEdit()
            edit.setDisplayFormat("HH:mm")
            edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
            edit.setFixedWidth(84)
            edit.setTime(QTime.fromString(self.config.data.get(key, default), "HH:mm"))
            edit.timeChanged.connect(lambda value, k=key: self._set_time(k, value))
            self.time_edits[key] = edit
            t_lay.addWidget(edit)
            t_lay.addSpacing(18)
        t_lay.addStretch(1)
        lay.addWidget(times)
        self.theme_status = muted()
        self.theme_status.setWordWrap(True)
        self.theme_status.setContentsMargins(4, 4, 0, 0)
        lay.addWidget(self.theme_status)
        self.update_theme_controls()
        return scroll

    def update_theme_controls(self) -> None:
        """Отмечает выбранный вариант и поясняет, какая тема сейчас показана."""
        data = self.config.data
        chosen = data.get("theme", themes.DARK_ID)
        for card in self.theme_cards:
            card.set_selected(card.theme_id == chosen)
        auto = chosen == themes.AUTO_ID
        for edit in self.time_edits.values():
            edit.setEnabled(auto)
        if auto:
            light = themes.effective_theme(data) == themes.LIGHT_ID
            until = data.get("theme_dark_from" if light else "theme_light_from",
                             themes.DEFAULT_DARK_FROM if light else themes.DEFAULT_LIGHT_FROM)
            self.theme_status.setText(f"Сейчас {'светлая' if light else 'тёмная'} тема, до {until}.")
        else:
            self.theme_status.setText("Время учитывается, только когда выбрано «Авто». "
                                      "Новогодняя тема от времени не зависит.")

    def _changed(self) -> None:
        self.config.save()
        self.theme_changed.emit(themes.effective_theme(self.config.data))
        self.update_theme_controls()

    COLOR_KEYS = ("accent", "bg_sidebar", "bg_panel")

    def _choose_theme(self, theme_id: str) -> None:
        """Выбор темы сбрасывает свои цвета (акцент, фон меню и панели) — тема как задумана.
        Повторный клик по текущей теме — способ вернуть её цвета. Сброс «тихий»: тема
        применяется один раз уже без своих цветов, а не дважды подряд."""
        previous = self.config.data.get("theme", themes.DARK_ID)
        customized = any(self.config.data.get(k) for k in self.COLOR_KEYS)
        if theme_id == previous and not customized:
            return
        for key in self.COLOR_KEYS:
            self.config.data[key] = None
        self.config.data["theme"] = theme_id
        if theme_id == previous:   # та же тема со своими цветами — переприменяем без них
            self.config.save()
            self.theme_reapply.emit(themes.effective_theme(self.config.data))
            self._after_theme(previous, theme_id)
            return
        self._changed()
        self._after_theme(previous, theme_id)

    def _after_theme(self, previous: str, theme_id: str) -> None:
        pers = getattr(self, "_pers", None)
        if pers is None:
            return
        if (theme_id in themes.SPECIAL_IDS) != (previous in themes.SPECIAL_IDS):
            pers.set("snow", theme_id in themes.SPECIAL_IDS)
        self._sync_look()   # кружки цветов в «Оформлении» — в «Как в теме»

    def _set_time(self, key: str, value: QTime) -> None:
        self.config.data[key] = value.toString("HH:mm")
        self._changed()

    def _set_hide_unavailable(self, on: bool) -> None:
        self.config.data["hide_unavailable"] = on
        self.config.save()
        self.display_changed.emit()

    def _rebuild_cards(self) -> None:
        for card in self.cards:
            card.rebuild()

    def add_player_tab(self, flow, cover_colors) -> None:
        """Вкладка «Плеер»: фон большого плеера. Добавляется, когда плеер уже создан."""
        from .flow_controls import FlowControls, FlowPreview
        scroll, lay = self._page()
        self.player_tab_lay = lay   # сюда главное окно добавит «Горячие клавиши»
        # Переходы между треками: кроссфейд
        head = QLabel("Переходы между треками")
        head.setFont(font(17, QFont.Weight.Bold, display=True))
        lay.addWidget(head)
        note = muted("Кроссфейд: конец трека плавно перетекает в начало следующего, без тишины между ними. "
                     "0 — выключен.")
        note.setWordWrap(True)
        note.setMaximumWidth(640)
        lay.addWidget(note)
        from PyQt6.QtWidgets import QSlider
        row = QHBoxLayout()
        cf = QSlider(Qt.Orientation.Horizontal)
        cf.setRange(0, 12)
        cf.setMinimumWidth(320)
        cf.setMaximumWidth(420)
        cf.setValue(int(self.config.data.get("crossfade", 0) or 0))
        cf_label = muted()
        def show(v):
            cf_label.setText("выключен" if v == 0 else f"{v} с")
        show(cf.value())
        cf.valueChanged.connect(show)
        cf.valueChanged.connect(lambda v: (self.config.data.__setitem__("crossfade", v), self.config.save()))
        row.addWidget(cf)
        row.addWidget(cf_label)
        row.addStretch(1)
        lay.addLayout(row)
        from .widgets import Toggle
        row = QHBoxLayout()
        wave_note = muted("Бесконечная волна: когда очередь заканчивается, Sonar сам добавляет похожие треки, "
                          "и музыка не останавливается.")
        wave_note.setWordWrap(True)
        wave_note.setFixedWidth(560)
        row.addWidget(wave_note)
        row.addSpacing(20)
        endless = Toggle()
        endless.setChecked(bool(self.config.data.get("endless", True)))
        endless.toggled.connect(lambda on: (self.config.data.__setitem__("endless", on), self.config.save()))
        row.addWidget(endless)
        row.addStretch(1)
        lay.addSpacing(8)
        lay.addLayout(row)
        lay.addSpacing(22)
        head = QLabel("Фон большого плеера")
        head.setFont(font(17, QFont.Weight.Bold, display=True))
        lay.addWidget(head)
        note = muted("Разноцветные пятна плывут и перетекают друг в друга. Выберите цвета, "
                     "размытие и скорость — превью меняется сразу. То же есть в самом плеере: "
                     "кнопка с палитрой вверху справа.")
        note.setWordWrap(True)
        note.setMaximumWidth(640)
        lay.addWidget(note)
        lay.addSpacing(6)
        preview = FlowPreview(flow, cover_colors)
        preview.setMaximumWidth(640)
        lay.addWidget(preview)
        lay.addSpacing(8)
        controls = FlowControls(flow)
        controls.setMaximumWidth(640)
        lay.addWidget(controls)
        # Текст песни: вид, цвета, шрифт, скорость — с живым превью
        from .lyrics_controls import LyricsControls, LyricsPreview
        lay.addSpacing(26)
        head = QLabel("Текст песни")
        head.setFont(font(17, QFont.Weight.Bold, display=True))
        lay.addWidget(head)
        note = muted("Как выглядит текст в большом плеере: «Как в Dotify» подсвечивает строку целиком, "
                     "«Караоке» — по буквам. То же есть в самом плеере: кнопка с шестерёнкой вверху справа, "
                     "когда открыт текст.")
        note.setWordWrap(True)
        note.setMaximumWidth(640)
        lay.addWidget(note)
        lay.addSpacing(6)
        lyrics_preview = LyricsPreview(flow)
        lyrics_preview.setMaximumWidth(640)
        lay.addWidget(lyrics_preview)
        lay.addSpacing(8)
        lyrics_controls = LyricsControls(flow)
        lyrics_controls.setMaximumWidth(640)
        lay.addWidget(lyrics_controls)
        lay.addStretch(1)
        self.tabs.insertTab(self.tabs.indexOf(self.data_tab), scroll, "Плеер")

    def add_look_tab(self, pers) -> None:
        """Раздел «Оформление» внутри вкладки «Темы и оформление»: иконка, обои, акцент, снег."""
        from PyQt6.QtWidgets import QFileDialog, QSlider
        from .personalize import APP_ICONS, WALLPAPERS, app_icon, wallpaper_preview
        lay = self._looks_lay
        lay.addSpacing(26)
        head = QLabel("Оформление")
        head.setFont(font(24, QFont.Weight.Black, display=True))
        lay.addWidget(head)
        lay.addSpacing(4)
        self._pers = pers
        self._icon_tiles, self._wall_tiles = {}, {}

        def section(title: str, hint: str) -> None:
            head = QLabel(title)
            head.setFont(font(17, QFont.Weight.Bold, display=True))
            lay.addWidget(head)
            note = muted(hint)
            note.setWordWrap(True)
            note.setMaximumWidth(640)
            lay.addWidget(note)

        def pick(kind: str) -> None:
            path, _ = QFileDialog.getOpenFileName(self, "Выберите картинку", "",
                                                  "Изображения (*.png *.jpg *.jpeg *.webp *.bmp *.gif)")
            if path and not pers.import_image(path, kind):
                QMessageBox.warning(self, "Не получилось", "Этот файл не похож на картинку.")

        section("Иконка приложения", "Видна в панели задач и в заголовке окна. «Своя…» — любая ваша "
                                     "картинка: её центр станет круглой иконкой.")
        row = QHBoxLayout()
        row.setSpacing(12)
        for key, title in APP_ICONS:
            tile = OptionTile(title, app_icon(key, 72) if key != "custom" else None, round_=True)
            tile.clicked.connect(lambda k=key: pick("icon") if k == "custom" else pers.set("app_icon", k))
            self._icon_tiles[key] = tile
            row.addWidget(tile)
        row.addStretch(1)
        lay.addLayout(row)
        lay.addSpacing(18)

        section("Обои", "Фон главной панели. «Свои…» — любая ваша картинка. "
                        "Видимость регулирует, насколько обои проступают сквозь интерфейс.")
        row = QHBoxLayout()
        row.setSpacing(12)
        for key, title in WALLPAPERS:
            tile = OptionTile(title, wallpaper_preview(key) if key != "custom" else None)
            tile.clicked.connect(lambda k=key: pick("wallpaper") if k == "custom" else pers.set("wallpaper", k))
            self._wall_tiles[key] = tile
            row.addWidget(tile)
        row.addStretch(1)
        lay.addLayout(row)
        vis_head = QHBoxLayout()
        vis_head.addWidget(QLabel("Видимость обоев"))
        vis_head.addStretch(1)
        self._vis_value = muted()
        vis_head.addWidget(self._vis_value)
        holder = QWidget()
        holder.setMaximumWidth(640)
        hl = QVBoxLayout(holder)
        hl.setContentsMargins(0, 8, 0, 0)
        hl.addLayout(vis_head)
        self._vis = QSlider(Qt.Orientation.Horizontal)
        self._vis.setRange(10, 90)
        self._vis.setValue(int(pers.get("wallpaper_visibility")))
        self._vis.valueChanged.connect(lambda v: self._vis_value.setText(f"{v}%"))
        self._vis.sliderReleased.connect(lambda: pers.set("wallpaper_visibility", self._vis.value()))
        self._vis.valueChanged.connect(lambda v: None if self._vis.isSliderDown() else pers.set("wallpaper_visibility", v))
        hl.addWidget(self._vis)
        lay.addWidget(holder)
        lay.addSpacing(14)

        sub = QLabel("Или выбрать цвет заднего фона?")
        sub.setFont(font(15, QFont.Weight.Bold))
        lay.addWidget(sub)
        hint = muted("Свой цвет для левого меню с плеером и для основной панели — страниц и настроек. "
                     "Текст сам станет тёмным или светлым, чтобы читаться. Цвет панели заменяет обои.")
        hint.setWordWrap(True)
        hint.setMaximumWidth(640)
        lay.addWidget(hint)
        self._bg_btns: dict = {}
        for key, label in (("bg_sidebar", "Левое меню и плеер"), ("bg_panel", "Основная панель")):
            row = QHBoxLayout()
            row.setSpacing(10)
            name = QLabel(label)
            name.setFixedWidth(170)
            row.addWidget(name)
            self._bg_btns[key] = {}
            for color in (None, *BACKGROUNDS):
                b = QToolButton()
                b.setObjectName("colorSwatch")
                b.setCheckable(True)
                b.setFixedSize(34, 34)
                b.setIconSize(QSize(26, 26))
                b.setCursor(Qt.CursorShape.PointingHandCursor)
                b.setToolTip("Как в теме" if color is None else color)
                b.clicked.connect(lambda _=False, k=key, c=color: self._set_background(k, c))
                self._bg_btns[key][color] = b
                row.addWidget(b)
            own = QToolButton()
            own.setObjectName("colorSwatch")
            own.setFixedSize(34, 34)
            own.setIconSize(QSize(18, 18))
            own.setCursor(Qt.CursorShape.PointingHandCursor)
            own.setToolTip("Свой цвет…")
            own.clicked.connect(lambda _=False, k=key: self._pick_background(k))
            self._bg_btns[key]["own"] = own
            row.addWidget(own)
            row.addStretch(1)
            lay.addLayout(row)
        lay.addSpacing(18)

        section("Акцентный цвет", "Цвет кнопок воспроизведения, ползунков, переключателей и выбранных "
                                  "вариантов. «Как в теме» — цвет выбранной темы.")
        row = QHBoxLayout()
        row.setSpacing(10)
        self._accent_btns = {}
        for color in (None, *ACCENTS):
            b = QToolButton()
            b.setObjectName("colorSwatch")
            b.setCheckable(True)
            b.setFixedSize(38, 38)
            b.setIconSize(QSize(30, 30))
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setToolTip("Как в теме" if color is None else color)
            b.clicked.connect(lambda _=False, c=color: pers.set("accent", c))
            self._accent_btns[color] = b
            row.addWidget(b)
        own = QToolButton()
        own.setObjectName("colorSwatch")
        own.setFixedSize(38, 38)
        own.setIconSize(QSize(20, 20))
        own.setCursor(Qt.CursorShape.PointingHandCursor)
        own.setToolTip("Свой цвет…")
        own.clicked.connect(self._pick_accent)
        self._accent_own = own
        row.addWidget(own)
        row.addStretch(1)
        lay.addLayout(row)
        lay.addSpacing(18)
        burst = SettingRow("Сердечки при лайке", "Когда лайкаете трек, из кнопки разлетаются сердечки.",
                           bool(pers.get("like_burst")), lambda on: pers.set("like_burst", on))
        burst.setMaximumWidth(640)
        lay.addWidget(burst)
        self.snow_row = SettingRow("Снежинки", "Снег поверх окна. Включается сам вместе с новогодней темой, "
                                   "но его можно выключить — или включить в любой другой теме.",
                                   pers.snow_on(), lambda on: pers.set("snow", on))
        self.snow_row.setMaximumWidth(640)
        lay.addWidget(self.snow_row)
        lay.addStretch(1)
        pers.changed.connect(self._sync_look)
        self._sync_look()

    def _set_background(self, key: str, color) -> None:
        self._pers.set(key, color)
        if key == "bg_panel" and color and self._pers.get("wallpaper") != "none":
            self._pers.set("wallpaper", "none")   # «или»: цвет панели вместо обоев

    def _pick_background(self, key: str) -> None:
        from PyQt6.QtGui import QColor
        from PyQt6.QtWidgets import QColorDialog
        current = self._pers.get(key) or "#1a1033"
        chosen = QColorDialog.getColor(QColor(current), self, "Цвет фона")
        if chosen.isValid():
            self._set_background(key, chosen.name())

    def _pick_accent(self) -> None:
        from PyQt6.QtGui import QColor
        from PyQt6.QtWidgets import QColorDialog
        current = self._pers.get("accent") or "#ff4d6d"
        chosen = QColorDialog.getColor(QColor(current), self, "Акцентный цвет")
        if chosen.isValid():
            self._pers.set("accent", chosen.name())

    def _sync_look(self) -> None:
        from PyQt6.QtGui import QIcon
        from .flow_controls import swatch
        from . import icons as _icons
        from .theme import C, THEMES, current_id
        accent = self._pers.get("accent")
        for color, b in self._accent_btns.items():
            base = color or THEMES[current_id()]["accent"]
            b.setIcon(QIcon(swatch([base, base], 30)))
            b.setChecked(color == accent or (color is None and not accent))
        self._accent_own.setIcon(_icons.icon("plus", C("muted")))
        for key, buttons in getattr(self, "_bg_btns", {}).items():
            chosen = self._pers.get(key)
            for color, b in buttons.items():
                if color == "own":
                    b.setIcon(QIcon(swatch([chosen, chosen], 18)) if chosen and chosen not in BACKGROUNDS
                              else _icons.icon("plus", C("muted")))
                    continue
                base = color or THEMES[current_id()]["panel" if key == "bg_panel" else "bg"]
                b.setIcon(QIcon(swatch([base, base], 26)))
                b.setChecked(color == chosen or (color is None and not chosen))
        if hasattr(self, "snow_row"):   # снег мог включиться сам — вместе с новогодней темой
            self.snow_row.toggle.blockSignals(True)
            self.snow_row.toggle.setChecked(self._pers.snow_on())
            self.snow_row.toggle.blockSignals(False)
        self._accent_own.setProperty("custom", bool(accent and accent not in ACCENTS))
        from .personalize import app_icon, custom_icon_path, custom_wallpaper_path, wallpaper_preview
        pers = self._pers
        for key, tile in self._icon_tiles.items():
            tile.set_selected(key == pers.get("app_icon"))
        if custom_icon_path().exists():
            self._icon_tiles["custom"].set_preview(app_icon("custom", 72))
        for key, tile in self._wall_tiles.items():
            tile.set_selected(key == pers.get("wallpaper"))
        if custom_wallpaper_path().exists():
            self._wall_tiles["custom"].set_preview(wallpaper_preview("custom"))
        self._vis_value.setText(f"{self._vis.value()}%")

    def show_integrations(self) -> None:
        self.tabs.setCurrentIndex(0)

    def relogin(self, service_id: str) -> None:
        """С главной «Войти заново»: открываем карточку и сразу окно входа."""
        self.show_integrations()
        for card in self.cards:
            if card.cls.id == service_id:
                card.rebuild()
                if card.browser_btn is not None and browser_login.AVAILABLE:
                    QTimer.singleShot(150, card._browser_login)
                elif card._manual_panel is not None:
                    card._manual_panel.show()
