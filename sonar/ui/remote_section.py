"""Настройки → Данные: «Пульт с телефона» и «Telegram-бот»."""
import webbrowser

from PyQt6 import sip
from PyQt6.QtCore import QObject, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPainter
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget

from .theme import font


class QrCode(QWidget):
    """QR-код ссылки пульта (пакет qrcode: только матрица, рисуем сами)."""

    def __init__(self, size: int = 200, parent=None) -> None:
        super().__init__(parent)
        self.setFixedSize(size, size)
        self._matrix = []

    def set_text(self, text: str) -> None:
        try:
            import qrcode
            qr = qrcode.QRCode(border=2, error_correction=qrcode.constants.ERROR_CORRECT_M)
            qr.add_data(text)
            qr.make(fit=True)
            self._matrix = qr.get_matrix()
        except ImportError:
            self._matrix = []
        self.update()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#ffffff"))
        if not self._matrix:
            p.setPen(QColor("#555"))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "QR недоступен")
            return
        n = len(self._matrix)
        cell = self.width() / n
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#000000"))
        for y, row in enumerate(self._matrix):
            for x, on in enumerate(row):
                if on:
                    p.drawRect(QRectF(x * cell, y * cell, cell + 0.5, cell + 0.5))


class _Relay(QObject):
    text = pyqtSignal(str)   # из потока бота — в главный поток


def _card(title: str) -> tuple[QFrame, QVBoxLayout]:
    card = QFrame()
    card.setObjectName("serviceCard")
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


class RemoteSection(QObject):
    def __init__(self, config, phone, bot, parent=None) -> None:
        super().__init__(parent)
        from .widgets import Toggle
        self.config, self.phone, self.bot = config, phone, bot
        self.cards = []

        # ---------- пульт ----------
        card, c = _card("Пульт с телефона")
        row = QHBoxLayout()
        row.addWidget(_muted("Управляйте Sonar с телефона: наведите камеру на QR-код. Телефон должен быть "
                             "в той же Wi-Fi сети, что и компьютер. Ничего ставить не нужно."), 1)
        self.phone_toggle = Toggle()
        self.phone_toggle.setChecked(phone.running)
        self.phone_toggle.toggled.connect(self._phone_on)
        row.addWidget(self.phone_toggle)
        c.addLayout(row)
        body = QHBoxLayout()
        self.qr = QrCode(190)
        body.addWidget(self.qr)
        info = QVBoxLayout()
        self.url = QLabel()
        self.url.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.url.setWordWrap(True)
        self.url.setTextFormat(Qt.TextFormat.PlainText)
        info.addWidget(self.url)
        info.addWidget(_muted("Первый раз Windows спросит про доступ к сети — разрешите для частных сетей. "
                              "Ссылка с ключом: без неё пульт не откроется."))
        new = QPushButton("Новая ссылка")
        new.setToolTip("Старые ссылки и QR-коды перестанут работать")
        new.setCursor(Qt.CursorShape.PointingHandCursor)
        new.clicked.connect(self._new_key)
        info.addWidget(new, 0, Qt.AlignmentFlag.AlignLeft)
        info.addStretch(1)
        body.addLayout(info, 1)
        self.phone_body = QWidget()
        self.phone_body.setLayout(body)
        c.addWidget(self.phone_body)
        self.cards.append(card)
        self._sync_phone()

        # ---------- бот ----------
        card, c = _card("Telegram-бот")
        c.addWidget(_muted("Свой бот-пульт: «что играет», пауза, дальше, громкость и лайк — из любого места. "
                           "Создайте бота у @BotFather (команда /newbot) и вставьте его токен сюда."))
        self.token = QLineEdit(config.data.get("tg_token", ""))
        self.token.setPlaceholderText("Токен бота, например 123456:ABC-DEF…")
        self.token.setEchoMode(QLineEdit.EchoMode.Password)
        c.addWidget(self.token)
        self.proxy = QLineEdit(config.data.get("tg_proxy", ""))
        self.proxy.setPlaceholderText("Прокси, если Telegram не открывается напрямую: socks5://127.0.0.1:1080 (необязательно)")
        c.addWidget(self.proxy)
        row = QHBoxLayout()
        save = QPushButton("Сохранить и запустить")
        save.setObjectName("primary")
        save.setCursor(Qt.CursorShape.PointingHandCursor)
        save.clicked.connect(self._save_bot)
        father = QPushButton("Открыть @BotFather")
        father.setCursor(Qt.CursorShape.PointingHandCursor)
        father.clicked.connect(lambda: webbrowser.open("https://t.me/BotFather"))
        self.open_bot = QPushButton("Открыть бота")
        self.open_bot.setToolTip("Откроет вашего бота в Telegram и сам отправит код привязки — останется нажать «Старт»")
        self.open_bot.setCursor(Qt.CursorShape.PointingHandCursor)
        self.open_bot.clicked.connect(self._open_bot)
        unlink = QPushButton("Отвязать хозяина")
        unlink.setObjectName("link")
        unlink.setCursor(Qt.CursorShape.PointingHandCursor)
        unlink.clicked.connect(self._unlink)
        for b in (save, self.open_bot, father, unlink):
            row.addWidget(b)
        row.addStretch(1)
        c.addLayout(row)
        self.bot_status = _muted()
        c.addWidget(self.bot_status)
        self.cards.append(card)
        self._relay = _Relay()
        self._relay.text.connect(self._show_bot_status)
        bot.status_cb = self._relay.text.emit
        self._show_bot_status(bot.status if bot.token else "не настроен: вставьте токен")

    # ---------- пульт ----------

    def _phone_on(self, on: bool) -> None:
        self.config.data["remote_on"] = on
        self.config.save()
        if on and not self.phone.start():
            self.url.setText("Не получилось открыть порт 8765–8775: все заняты другими программами.")
        if not on:
            self.phone.stop()
        self._sync_phone()

    def _new_key(self) -> None:
        self.phone.new_key()
        self._sync_phone()

    def _sync_phone(self) -> None:
        on = self.phone.running
        self.phone_body.setVisible(on)
        if on:
            link = self.phone.url()
            self.url.setText(link)
            self.qr.set_text(link)

    # ---------- бот ----------

    def _save_bot(self) -> None:
        self.config.data["tg_token"] = self.token.text().strip()
        self.config.data["tg_proxy"] = self.proxy.text().strip()
        self.config.save()
        if not self.bot.token:
            self.bot.stop()
            self._show_bot_status("не настроен: вставьте токен")
            return
        self._show_bot_status("подключаюсь…")
        self.bot.restart()

    def _open_bot(self) -> None:
        link = self.bot.start_link()
        if link:
            webbrowser.open(link)

    def _unlink(self) -> None:
        self.bot.unlink()

    def _show_bot_status(self, text: str) -> None:
        if sip.isdeleted(self.bot_status):
            return
        extra = ""
        if self.bot.token and self.bot.owner is None and "ждёт хозяина" not in text:
            extra = f"\nКод привязки: отправьте боту /start {self.bot.code}"
        self.bot_status.setText("Статус: " + text + extra)
        self.open_bot.setVisible(bool(self.bot.start_link()) and self.bot.owner is None)
