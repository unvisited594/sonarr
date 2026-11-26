"""Мастерская: свои наборы оформления, каталог, достижения и приколюхи."""
import math
import random
import webbrowser
from pathlib import Path

from PyQt6 import sip
from PyQt6.QtCore import QPointF, QRectF, Qt, QTimer
from PyQt6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap, QRadialGradient
from PyQt6.QtWidgets import (QFileDialog, QFrame, QGridLayout, QHBoxLayout, QInputDialog, QLabel, QMessageBox,
                             QPushButton, QScrollArea, QTabWidget, QVBoxLayout, QWidget)

from .. import workshop
from ..achievements import ACHIEVEMENTS
from ..workers import run_async
from .theme import font
from .widgets import muted

CARD_W = 300


# ---------- превью набора ----------

def _flow_colors(settings: dict) -> list[str]:
    from .flow_settings import PRESETS
    source = settings.get("flow_source", "cover")
    if source in PRESETS:
        return PRESETS[source]["colors"]
    if source == "custom" and settings.get("flow_custom"):
        return list(settings["flow_custom"])
    return ["#7c4dff", "#ff5f6d", "#3b2a6e"]


def render_preview(settings: dict, w: int = CARD_W, h: int = 168) -> QPixmap:
    """Картинка набора: фон большого плеера его цветами, полоска темы, акцент и строка текста."""
    ratio = 2
    pm = QPixmap(w * ratio, h * ratio)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.scale(ratio, ratio)
    clip = QPainterPath()
    clip.addRoundedRect(QRectF(0, 0, w, h), 14, 14)
    p.setClipPath(clip)
    p.fillRect(QRectF(0, 0, w, h), QColor("#0b0b12"))
    colors = _flow_colors(settings)
    spots = [(0.2, 0.3), (0.8, 0.35), (0.5, 0.85), (0.1, 0.9)]
    for i, c in enumerate(colors[:4]):
        cx, cy = spots[i]
        g = QRadialGradient(QPointF(cx * w, cy * h), w * 0.55)
        col = QColor(c)
        g.setColorAt(0, col)
        col.setAlpha(0)
        g.setColorAt(1, col)
        p.fillRect(QRectF(0, 0, w, h), g)
    # тема: светлая или тёмная полоска «интерфейса» слева
    light = settings.get("theme") == "light"
    p.fillRect(QRectF(0, 0, w * 0.16, h), QColor(255, 255, 255, 215) if light else QColor(10, 10, 14, 200))
    accent = QColor(settings.get("accent") or ("#141416" if light else "#f2f2f2"))
    for i in range(4):
        p.setBrush(accent if i == 0 else (QColor(0, 0, 0, 60) if light else QColor(255, 255, 255, 50)))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(QRectF(w * 0.04, 16 + i * 26, w * 0.08, w * 0.08), 4, 4)
    # пластинка, если включена
    if settings.get("vinyl"):
        p.setBrush(QColor("#111114"))
        p.drawEllipse(QPointF(w * 0.58, h * 0.4), h * 0.26, h * 0.26)
        p.setBrush(QColor(colors[0]))
        p.drawEllipse(QPointF(w * 0.58, h * 0.4), h * 0.08, h * 0.08)
    else:
        p.setBrush(QColor(255, 255, 255, 40))
        p.drawRoundedRect(QRectF(w * 0.46, h * 0.16, h * 0.46, h * 0.46), 10, 10)
    # строка «текста песни» в цветах набора
    f = QFont(settings.get("lyrics_font") or "Segoe UI")
    f.setPixelSize(17)
    f.setWeight(QFont.Weight.Black if settings.get("lyrics_bold", True) else QFont.Weight.Medium)
    text = "Sonar поёт ♪"
    path = QPainterPath()
    path.addText(QPointF(w * 0.24, h * 0.86), f, text)
    sung = QColor(settings.get("lyrics_sung") or "#000000")
    plain = QColor(settings.get("lyrics_color") or "#ffffff")
    if settings.get("lyrics_halo", True):
        halo = QColor(255, 255, 255, 150) if sung.lightnessF() < 0.5 else QColor(0, 0, 0, 120)
        pen = QPen(halo, 2.4)
        p.save()
        p.setClipRect(QRectF(0, 0, w * 0.5, h))
        p.strokePath(path, pen)
        p.restore()
    p.fillPath(path, plain)
    p.save()
    p.setClipRect(QRectF(0, 0, w * 0.5, h))
    p.fillPath(path, sung)
    p.restore()
    if settings.get("snow"):
        rnd = random.Random(7)
        p.setBrush(QColor(255, 255, 255, 190))
        for _ in range(26):
            p.drawEllipse(QPointF(rnd.random() * w, rnd.random() * h), 1.6, 1.6)
    p.end()
    pm.setDevicePixelRatio(ratio)
    return pm


def preview_bytes(settings: dict) -> bytes:
    from PyQt6.QtCore import QBuffer, QIODevice
    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    render_preview(settings).toImage().save(buf, "PNG")
    return bytes(buf.data())


# ---------- конфетти ----------

class Confetti(QWidget):
    """Конфетти сыплется сверху на всё окно и тает. Прозрачно для мыши."""
    DURATION = 2600

    def __init__(self, window: QWidget, count: int = 140) -> None:
        super().__init__(window)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setGeometry(window.rect())
        rnd = random.Random()
        palette = ["#ff4d6d", "#ffd23f", "#00e5ff", "#7c4dff", "#3ddc84", "#ff7a00"]
        self._bits = [(rnd.random(), rnd.uniform(-0.35, 0), rnd.uniform(0.35, 0.7), rnd.uniform(6, 12),
                       rnd.uniform(0, 360), rnd.uniform(-540, 540), QColor(rnd.choice(palette)), rnd.random() * 6.28)
                      for _ in range(count)]   # x, старт, скорость, размер, угол, вращение, цвет, фаза
        self._t = 0
        self._timer = QTimer(self, interval=16)
        self._timer.timeout.connect(self._tick)
        self.show()
        self.raise_()
        self._timer.start()

    def _tick(self) -> None:
        self._t += 16
        if self._t >= self.DURATION:
            self._timer.stop()
            self.deleteLater()
            return
        self.update()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        k = self._t / 1000
        fade = min(1.0, (self.DURATION - self._t) / 600)
        for x, y0, v, size, ang, spin, color, ph in self._bits:
            y = (y0 + v * k) * self.height()
            xx = x * self.width() + 30 * math.sin(k * 3 + ph)
            p.save()
            p.translate(xx, y)
            p.rotate(ang + spin * k)
            c = QColor(color)
            c.setAlphaF(max(0.0, fade))
            p.setBrush(c)
            p.setPen(Qt.PenStyle.NoPen)
            p.drawRect(QRectF(-size / 2, -size / 4 * abs(math.cos(k * 6 + ph)) - 1, size, size / 2 * abs(math.cos(k * 6 + ph)) + 2))
            p.restore()


# ---------- карточки ----------

def _card() -> tuple[QFrame, QVBoxLayout]:
    card = QFrame()
    card.setObjectName("card")
    card.setFixedWidth(CARD_W + 28)
    lay = QVBoxLayout(card)
    lay.setContentsMargins(14, 14, 14, 14)
    lay.setSpacing(6)
    return card, lay


def _btn(text: str, primary: bool = False) -> QPushButton:
    b = QPushButton(text)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    b.setProperty("compact", True)
    if primary:
        b.setObjectName("primary")
    return b


def _grid_page() -> tuple[QScrollArea, QVBoxLayout, QGridLayout]:
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    inner = QWidget()
    outer = QVBoxLayout(inner)
    outer.setContentsMargins(4, 12, 12, 24)
    outer.setSpacing(12)
    grid = QGridLayout()
    grid.setHorizontalSpacing(14)
    grid.setVerticalSpacing(14)
    grid.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
    scroll.setWidget(inner)
    return scroll, outer, grid


def _plain(label: QLabel) -> QLabel:
    """Тексты из чужих наборов — только как текст: никакой разметки и картинок по ссылкам."""
    label.setTextFormat(Qt.TextFormat.PlainText)
    return label


def _clear(layout) -> None:
    """Убрать всё из раскладки, включая вложенные раскладки (иначе старые карточки остаются)."""
    while layout.count():
        item = layout.takeAt(0)
        if item.widget() is not None:
            item.widget().hide()
            item.widget().deleteLater()
        elif item.layout() is not None:
            _clear(item.layout())
            item.layout().deleteLater()


def _medal(symbol: str, done: bool, size: int = 64) -> QPixmap:
    ratio = 2
    pm = QPixmap(size * ratio, size * ratio)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.scale(ratio, ratio)
    r = QRectF(4, 4, size - 8, size - 8)
    g = QLinearGradient(r.topLeft(), r.bottomRight())
    if done:
        g.setColorAt(0, QColor("#ffe082"))
        g.setColorAt(1, QColor("#f59e0b"))
    else:
        g.setColorAt(0, QColor("#5b5b63"))
        g.setColorAt(1, QColor("#35353b"))
    p.setPen(QPen(QColor(255, 255, 255, 120 if done else 40), 2))
    p.setBrush(g)
    p.drawEllipse(r)
    f = QFont()
    f.setPixelSize(int(size * (0.34 if len(symbol) < 3 else 0.26)))
    f.setWeight(QFont.Weight.Black)
    p.setFont(f)
    p.setPen(QColor("#4a2a00") if done else QColor(255, 255, 255, 110))
    p.drawText(r, Qt.AlignmentFlag.AlignCenter, symbol)
    p.end()
    pm.setDevicePixelRatio(ratio)
    return pm


# ---------- страница ----------

class WorkshopPage(QWidget):
    def __init__(self, window, config, achievements, flow, parent=None) -> None:
        super().__init__(parent)
        self.win = window
        self.config = config
        self.ach = achievements
        self.flow = flow
        self._catalog: list[dict] | None = None
        self._party_timer = QTimer(self, interval=3500)
        self._party_timer.timeout.connect(self._party_step)
        self._party_saved = None

        lay = QVBoxLayout(self)
        lay.setContentsMargins(36, 28, 24, 0)
        lay.setSpacing(4)
        title = QLabel("Мастерская")
        title.setFont(font(30, QFont.Weight.Black, display=True))
        lay.addWidget(title)
        lay.addWidget(muted("Наборы оформления: тема, цвета, обои, иконка, фон плеера и вид текста песни. "
                            "Сохраняйте свои, делитесь файлом, ставьте из каталога."))
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        lay.addWidget(self.tabs, 1)

        mine, self.mine_outer, self.mine_grid = _grid_page()
        self.tabs.addTab(mine, "Мои наборы")
        cat, self.cat_outer, self.cat_grid = _grid_page()
        self.tabs.addTab(cat, "Каталог")
        ach, self.ach_outer, self.ach_grid = _grid_page()
        self.tabs.addTab(ach, "Достижения")
        fun = self._fun_tab()
        self.tabs.addTab(fun, "Приколюхи")
        self.tabs.currentChanged.connect(self._tab_changed)

        self._build_mine_header()
        self.ach.changed.connect(self._fill_achievements)
        self.refresh_mine()
        self._fill_achievements()

    # ---------- мои наборы ----------

    def _build_mine_header(self) -> None:
        row = QHBoxLayout()
        save = _btn("Сохранить текущее оформление", primary=True)
        save.clicked.connect(self._save_current)
        imp = _btn("Открыть файл набора…")
        imp.clicked.connect(self._import)
        row.addWidget(save)
        row.addWidget(imp)
        row.addStretch(1)
        self.mine_outer.addLayout(row)
        self.mine_empty = muted("Здесь пока пусто. Настройте Sonar под себя (тема, обои, фон плеера, текст "
                                "песни) и нажмите «Сохранить текущее оформление».")
        self.mine_empty.setWordWrap(True)
        self.mine_outer.addWidget(self.mine_empty)
        self.mine_outer.addLayout(self.mine_grid)
        self.mine_outer.addStretch(1)

    def refresh_mine(self) -> None:
        _clear(self.mine_grid)
        packs = workshop.local_packs()
        self.mine_empty.setVisible(not packs)
        for i, pack in enumerate(packs):
            self.mine_grid.addWidget(self._pack_card(pack), i // 3, i % 3)

    def _pack_card(self, pack) -> QFrame:
        card, lay = _card()
        pic = QLabel()
        pic.setPixmap(QPixmap(str(pack.preview)).scaled(CARD_W, 168, Qt.AspectRatioMode.KeepAspectRatio,
                                                         Qt.TransformationMode.SmoothTransformation)
                      if pack.preview else render_preview(pack.settings))
        lay.addWidget(pic)
        name = _plain(QLabel(pack.name))
        name.setFont(font(15, QFont.Weight.Bold))
        lay.addWidget(name)
        if pack.meta.get("author"):
            lay.addWidget(_plain(muted(f"автор: {pack.meta['author']}")))
        if pack.meta.get("description"):
            d = _plain(muted(pack.meta["description"]))
            d.setWordWrap(True)
            lay.addWidget(d)
        row = QHBoxLayout()
        use = _btn("Применить", primary=True)
        use.clicked.connect(lambda: self._apply(pack))
        share = _btn("Поделиться")
        share.clicked.connect(lambda: self._share(pack))
        remove = _btn("Удалить")
        remove.clicked.connect(lambda: self._delete(pack))
        row.addWidget(use)
        row.addWidget(share)
        row.addWidget(remove)
        lay.addLayout(row)
        return card

    def _save_current(self) -> None:
        name, ok = QInputDialog.getText(self, "Сохранить набор", "Как назвать набор?")
        if not ok or not name.strip():
            return
        author = (self.config.data.get("profile") or {}).get("name", "") if isinstance(
            self.config.data.get("profile"), dict) else ""
        settings = workshop.snapshot(self.config)
        workshop.save_current(self.config, name.strip(), author, preview=preview_bytes(settings))
        self.ach.bump("saved")
        self.refresh_mine()
        self.win.show_toast(f"Набор «{name.strip()}» сохранён")

    def _apply(self, pack) -> None:
        workshop.apply(pack, self.config)
        self.win.apply_customization()
        self.win.show_toast(f"Оформление «{pack.name}» применено")

    def _share(self, pack) -> None:
        box = QMessageBox(self)
        box.setWindowTitle("Поделиться набором")
        box.setText(f"Набор «{pack.name}» можно сохранить файлом и отправить кому угодно — его откроют "
                    "кнопкой «Открыть файл набора…».\n\nЧтобы набор попал в общий каталог, сохраните файл "
                    "и прикрепите его к заявке на GitHub (откроется страница) или пришлите в Telegram @sonar081.")
        save = box.addButton("Сохранить файл…", QMessageBox.ButtonRole.AcceptRole)
        submit = box.addButton("Сохранить и отправить в каталог", QMessageBox.ButtonRole.ActionRole)
        box.addButton("Отмена", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() not in (save, submit):
            return
        safe = "".join(ch for ch in pack.name if ch.isalnum() or ch in " -_").strip() or "Sonar"
        ext = ".zip" if box.clickedButton() is submit else ".sonarpack"
        path, _ = QFileDialog.getSaveFileName(self, "Сохранить набор", str(Path.home() / f"{safe}{ext}"),
                                              "Набор Sonar (*.sonarpack *.zip)")
        if not path:
            return
        workshop.export(pack, Path(path))
        self.win.show_toast("Файл набора сохранён")
        if box.clickedButton() is submit:
            webbrowser.open(workshop.submit_url(pack.name, self.config))

    def _delete(self, pack) -> None:
        if QMessageBox.question(self, "Удалить набор", f"Удалить «{pack.name}»?") == QMessageBox.StandardButton.Yes:
            workshop.delete(pack)
            self.refresh_mine()

    def _import(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Набор Sonar", str(Path.home()), "Набор Sonar (*.sonarpack *.zip)")
        if not path:
            return
        try:
            pack = workshop.import_file(path)
        except (workshop.WorkshopError, OSError) as exc:
            QMessageBox.warning(self, "Не получилось", str(exc))
            return
        self.refresh_mine()
        self.tabs.setCurrentIndex(0)
        self.win.show_toast(f"Набор «{pack.name}» добавлен — нажмите «Применить»")

    # ---------- каталог ----------

    def _tab_changed(self, index: int) -> None:
        if index == 1 and self._catalog is None:
            self.load_catalog()

    def load_catalog(self) -> None:
        _clear(self.cat_outer)
        self._catalog = []
        head = QHBoxLayout()
        head.addWidget(muted("Наборы от автора Sonar и пользователей. Свой можно предложить кнопкой "
                             "«Поделиться» в «Моих наборах»."), 1)
        again = _btn("Обновить")
        again.clicked.connect(self.load_catalog)
        head.addWidget(again)
        self.cat_outer.addLayout(head)
        self._cat_status = muted("Загружаю каталог…")
        self.cat_outer.addWidget(self._cat_status)
        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(14)
        grid.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.cat_grid = grid
        self.cat_outer.addLayout(grid)
        self.cat_outer.addStretch(1)
        self._show_catalog(workshop.builtin_catalog())

        def done(items):
            if sip.isdeleted(self):
                return
            self._cat_status.setText("" if items else "В онлайн-каталоге пока ничего нет — ниже встроенные наборы.")
            self._cat_status.setVisible(not items)
            self._show_catalog(items)

        def failed(_msg):
            if not sip.isdeleted(self):
                self._cat_status.setText("Онлайн-каталог сейчас недоступен — показаны встроенные наборы.")
        run_async(workshop.online_catalog, self.config, on_done=done, on_error=failed)

    def _show_catalog(self, items: list[dict]) -> None:
        names = {i.get("name") for i in self._catalog}
        for item in items:
            if item.get("name") in names:
                continue
            self._catalog.append(item)
            n = len(self._catalog) - 1
            self.cat_grid.addWidget(self._catalog_card(item), n // 3, n % 3)

    def _catalog_card(self, item: dict) -> QFrame:
        card, lay = _card()
        pic = QLabel()
        settings = item.get("settings") or {}
        if not settings and item.get("colors"):
            settings = {"flow_source": "custom", "flow_custom": list(item["colors"])[:4]}
        pic.setPixmap(render_preview(settings))
        lay.addWidget(pic)
        name = _plain(QLabel(str(item.get("name") or "Набор")[:60]))
        name.setFont(font(15, QFont.Weight.Bold))
        lay.addWidget(name)
        who = "встроенный" if item.get("builtin") else (f"автор: {str(item['author'])[:40]}" if item.get("author") else "")
        if who:
            lay.addWidget(_plain(muted(who)))
        if item.get("description"):
            d = _plain(muted(str(item["description"])[:300]))
            d.setWordWrap(True)
            lay.addWidget(d)
        get = _btn("Поставить", primary=True)
        get.clicked.connect(lambda: self._install(item, get))
        lay.addWidget(get, 0, Qt.AlignmentFlag.AlignLeft)
        return card

    def _install(self, item: dict, button: QPushButton) -> None:
        button.setEnabled(False)
        button.setText("Ставлю…")

        def done(pack):
            if sip.isdeleted(self):
                return
            button.setText("Поставлено")
            self.ach.bump("installed")
            self.refresh_mine()
            answer = QMessageBox.question(self, "Набор поставлен", f"«{pack.name}» в ваших наборах. Применить сейчас?")
            if answer == QMessageBox.StandardButton.Yes:
                self._apply(pack)

        def failed(msg):
            if not sip.isdeleted(self):
                button.setEnabled(True)
                button.setText("Поставить")
                QMessageBox.warning(self, "Не получилось", f"Набор не скачался: {msg}")
        if item.get("builtin"):
            try:
                done(workshop.import_json(item))
            except workshop.WorkshopError as exc:
                failed(str(exc))
            return
        run_async(workshop.install, item, self.config, on_done=done, on_error=failed)

    # ---------- достижения ----------

    def _fill_achievements(self) -> None:
        _clear(self.ach_outer)
        got, total = self.ach.progress()
        head = QLabel(f"Открыто {got} из {total}")
        head.setFont(font(17, QFont.Weight.Bold, display=True))
        self.ach_outer.addWidget(head)
        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(14)
        grid.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        for i, (aid, title, how, symbol, _test) in enumerate(ACHIEVEMENTS):
            done = aid in self.ach.done
            card = QFrame()
            card.setObjectName("card")
            card.setFixedWidth(300)
            row = QHBoxLayout(card)
            row.setContentsMargins(12, 12, 12, 12)
            pic = QLabel()
            pic.setPixmap(_medal(symbol, done))
            row.addWidget(pic)
            text = QVBoxLayout()
            name = QLabel(title)
            name.setFont(font(14, QFont.Weight.Bold))
            if not done:
                name.setProperty("role", "muted")
            text.addWidget(name)
            hint = muted(how if done or aid != "egg" else "Секрет. Подсказка: имя этой программы…")
            hint.setWordWrap(True)
            text.addWidget(hint)
            row.addLayout(text, 1)
            grid.addWidget(card, i // 3, i % 3)
        self.ach_outer.addLayout(grid)
        self.ach_outer.addStretch(1)

    # ---------- приколюхи ----------

    def _fun_tab(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QWidget()
        lay = QVBoxLayout(inner)
        lay.setContentsMargins(4, 16, 12, 24)
        lay.setSpacing(10)

        def item(title: str, text: str, button: str, slot) -> QPushButton:
            card = QFrame()
            card.setObjectName("card")
            card.setMaximumWidth(720)
            row = QHBoxLayout(card)
            row.setContentsMargins(16, 14, 16, 14)
            col = QVBoxLayout()
            t = QLabel(title)
            t.setFont(font(15, QFont.Weight.Bold))
            col.addWidget(t)
            d = muted(text)
            d.setWordWrap(True)
            col.addWidget(d)
            row.addLayout(col, 1)
            b = _btn(button, primary=True)
            b.clicked.connect(slot)
            row.addWidget(b)
            lay.addWidget(card)
            return b

        item("Конфетти", "Просто так. Потому что можно.", "Бахнуть", lambda: Confetti(self.win))
        self.party_btn = item("Режим вечеринки", "Фон большого плеера каждые несколько секунд меняет цвета "
                              "и быстрее движется. Выключите — всё вернётся как было.", "Включить", self._toggle_party)
        item("Удиви меня", "Случайное оформление: цвета фона плеера, акцент и вид текста песни. "
             "Понравится — сохраните в «Моих наборах».", "Перемешать", self._surprise)
        item("Пасхалка", "Где-то в Sonar спрятан секрет. Подсказка в «Достижениях».", "Ок", lambda: None)
        lay.addStretch(1)
        scroll.setWidget(inner)
        return scroll

    def _toggle_party(self) -> None:
        if self._party_timer.isActive():
            self._party_timer.stop()
            if self._party_saved is not None:
                for key, value in self._party_saved.items():
                    self.flow.config.data[key] = value
                self.flow.config.save()
                self.flow.changed.emit()
            self._party_saved = None
            self.party_btn.setText("Включить")
            self.win.show_toast("Вечеринка окончена")
            return
        self._party_saved = {k: self.flow.get(k) for k in ("flow_source", "flow_custom", "flow_speed")}
        self.flow.config.data["flow_speed"] = 100
        self._party_step()
        self._party_timer.start()
        self.party_btn.setText("Выключить")
        Confetti(self.win)
        self.ach.bump("party")
        self.win.show_toast("Вечеринка! Откройте большой плеер")

    def _party_step(self) -> None:
        self.flow.randomize_custom()

    def _surprise(self) -> None:
        from .lyrics_controls import COLOR_PRESETS
        rnd = random.Random()
        self.flow.randomize_custom()
        data = self.config.data
        hue = rnd.random()
        data["accent"] = QColor.fromHsvF(hue, 0.65, 1.0).name()
        _title, text, sung = rnd.choice(COLOR_PRESETS)
        data["lyrics_color"], data["lyrics_sung"] = text, sung
        data["lyrics_style"] = rnd.choice(["dotify", "karaoke"])
        data["vinyl"] = rnd.random() < 0.5
        self.config.save()
        self.win.apply_customization()
        self.win.show_toast("Готово! Не нравится — жмите ещё раз")

    def stop_party(self) -> None:
        if self._party_timer.isActive():
            self._toggle_party()


