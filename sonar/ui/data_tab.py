"""Настройки → Данные: где что лежит, скачанные треки, сброс."""
from pathlib import Path

from PyQt6.QtCore import Qt, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices, QFont
from PyQt6.QtWidgets import (QCheckBox, QFrame, QHBoxLayout, QLabel, QMessageBox, QPushButton, QScrollArea,
                             QVBoxLayout, QWidget)

from ..config import config_dir
from .theme import font
from .widgets import muted, tracks_word


def folder_size(path: Path) -> int:
    try:
        return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
    except OSError:
        return 0


def human_size(n: int) -> str:
    for unit in ("Б", "КБ", "МБ", "ГБ"):
        if n < 1024 or unit == "ГБ":
            return f"{n:.0f} {unit}" if unit in ("Б", "КБ") else f"{n:.1f} {unit}".replace(".", ",")
        n /= 1024
    return f"{n} Б"


def _button(text: str, danger: bool = False) -> QPushButton:
    b = QPushButton(text)
    b.setProperty("compact", True)
    if danger:
        b.setObjectName("danger")
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    return b


PAGE = 100


class DataTab(QScrollArea):
    reset_requested = pyqtSignal(bool)   # True — удалить и скачанные треки
    offline_changed = pyqtSignal(bool)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.stores = None  # (history, likes, playlists, downloads) — передаёт главное окно
        content = QWidget()
        lay = QVBoxLayout(content)
        lay.setContentsMargins(0, 18, 8, 28)
        lay.setSpacing(12)
        self.setWidget(content)
        from .widgets import FitHeight
        self._fit = FitHeight(self)

        # --- скачанные треки ---
        self.dl_card, dl = self._card(lay, "Скачанные треки")
        self.dl_stats = QLabel()
        self.dl_stats.setFont(font(15, QFont.Weight.DemiBold))
        dl.addWidget(self.dl_stats)
        self.dl_path = self._path_label(dl)
        row = QHBoxLayout()
        self.open_dl = _button("Открыть папку загрузок")
        self.open_dl.clicked.connect(lambda: self._open(self._downloads_dir()))
        self.clear_dl = _button("Удалить все загрузки", danger=True)
        self.clear_dl.clicked.connect(self._clear_downloads)
        row.addWidget(self.open_dl)
        row.addWidget(self.clear_dl)
        row.addStretch(1)
        dl.addLayout(row)
        from .widgets import Toggle
        off_row = QHBoxLayout()
        off_text = QVBoxLayout()
        off_text.setSpacing(2)
        off_title = QLabel("Офлайн-режим")
        off_title.setFont(font(15, QFont.Weight.DemiBold))
        off_text.addWidget(off_title)
        off_hint = muted("Везде видны только скачанные треки Navidrome, Sonar не ходит в сеть.")
        off_hint.setWordWrap(True)
        off_text.addWidget(off_hint)
        off_row.addLayout(off_text, 1)
        self.offline = Toggle()
        self.offline.toggled.connect(self.offline_changed)
        off_row.addWidget(self.offline, 0, Qt.AlignmentFlag.AlignVCenter)
        dl.addSpacing(6)
        dl.addLayout(off_row)

        # --- недоступные треки ---
        self.un_card, un = self._card(lay, "Недоступные треки")
        self.un_stats = muted()
        self.un_stats.setWordWrap(True)
        un.addWidget(self.un_stats)
        self.un_rows = QVBoxLayout()
        self.un_rows.setSpacing(2)
        un.addLayout(self.un_rows)
        pager = QHBoxLayout()
        pager.setSpacing(6)
        self.un_prev = _button("‹ Назад")
        self.un_prev.clicked.connect(lambda: self._page(-1))
        self.un_pages = QHBoxLayout()
        self.un_pages.setSpacing(4)
        self.un_next = _button("Вперёд ›")
        self.un_next.clicked.connect(lambda: self._page(1))
        self.un_clear = _button("Очистить список", danger=True)
        self.un_clear.clicked.connect(self._clear_unavailable)
        pager.addWidget(self.un_prev)
        pager.addLayout(self.un_pages)
        pager.addWidget(self.un_next)
        pager.addStretch(1)
        pager.addWidget(self.un_clear)
        un.addLayout(pager)
        self._un_page = 0
        from PyQt6.QtCore import QTimer
        self._un_timer = QTimer(self, singleShot=True, interval=250)
        self._un_timer.timeout.connect(self._render_unavailable)

        # --- данные Sonar ---
        self.data_card, data = self._card(lay, "Данные Sonar")
        self.data_stats = muted()
        self.data_stats.setWordWrap(True)
        data.addWidget(self.data_stats)
        self.data_path = self._path_label(data)
        self.data_note = muted()
        self.data_note.setWordWrap(True)
        data.addWidget(self.data_note)
        row = QHBoxLayout()
        open_data = _button("Открыть папку данных")
        open_data.clicked.connect(lambda: self._open(config_dir()))
        row.addWidget(open_data)
        row.addStretch(1)
        data.addLayout(row)

        # --- журнал ---
        self.log_card, lg = self._card(lay, "Журнал работы")
        self.log_stats = muted()
        lg.addWidget(self.log_stats)
        self.log_path = self._path_label(lg)
        note = muted("Сюда пишутся события плеера, ошибки и сообщения Qt и FFmpeg — пригодится, если "
                     "что-то работает не так. В журнале бывают адреса потоков (у Navidrome в них токен "
                     "входа), поэтому пересылайте его только тому, кому доверяете.")
        note.setWordWrap(True)
        lg.addWidget(note)
        row = QHBoxLayout()
        open_log = _button("Открыть журнал")
        open_log.clicked.connect(self._open_log)
        save_log = _button("Сохранить журнал…")
        save_log.clicked.connect(self._save_log)
        row.addWidget(open_log)
        row.addWidget(save_log)
        row.addStretch(1)
        lg.addLayout(row)

        # --- сброс ---
        self.reset_card, reset = self._card(lay, "Сброс")
        text = muted("Удаляет все данные Sonar: подключения к сервисам, профиль, лайки, плейлисты, "
                     "историю и настройки. Sonar перезапустится, как при первом запуске. "
                     "Отменить это нельзя.")
        text.setWordWrap(True)
        reset.addWidget(text)
        self.with_downloads = QCheckBox("Удалить и скачанные треки")
        reset.addWidget(self.with_downloads)
        row = QHBoxLayout()
        self.reset_btn = _button("Сбросить всё", danger=True)
        self.reset_btn.clicked.connect(self._reset)
        row.addWidget(self.reset_btn)
        row.addStretch(1)
        reset.addLayout(row)
        lay.addStretch(1)

    # ---------- построение ----------

    @staticmethod
    def _card(parent_lay, title: str):
        card = QFrame()
        card.setObjectName("serviceCard")
        card.setMaximumWidth(640)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(18, 14, 18, 16)
        lay.setSpacing(8)
        head = QLabel(title)
        head.setFont(font(17, QFont.Weight.Bold, display=True))
        lay.addWidget(head)
        parent_lay.addWidget(card)
        return card, lay

    @staticmethod
    def _path_label(lay) -> QLabel:
        label = muted()
        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)  # путь можно скопировать
        label.setWordWrap(True)
        lay.addWidget(label)
        return label

    # ---------- данные ----------

    def set_stores(self, history, likes, playlists, downloads, unavailable=None, manager=None, config=None) -> None:
        self.stores = (history, likes, playlists, downloads)
        self.unavailable, self.manager, self.config = unavailable, manager, config
        downloads.changed.connect(self.refresh)
        if unavailable is not None:
            unavailable.changed.connect(self._unavailable_changed)

    def _unavailable_changed(self) -> None:
        # Треки попадают в список пачками (десятки за одну отрисовку главной): перерисовываем один
        # раз после пачки, а не на каждый трек — иначе 100 строк пересоздаются сотни раз подряд.
        if self.isVisible():
            self._un_timer.start()

    def _page(self, step: int) -> None:
        self._un_page += step
        self._render_unavailable()
        self.ensureWidgetVisible(self.un_card, 0, 0)

    def _goto(self, page: int) -> None:
        self._un_page = page
        self._render_unavailable()
        self.ensureWidgetVisible(self.un_card, 0, 0)

    def _render_unavailable(self) -> None:
        from .widgets import TrackRow, clear_layout
        from ..services import AVAILABLE
        from .icons import service_icon
        clear_layout(self.un_rows)
        clear_layout(self.un_pages)
        store = self.unavailable
        items = store.tracks(self.manager) if store is not None and self.manager is not None else []
        total = len(items)
        pages = max(1, (total + PAGE - 1) // PAGE)
        self._un_page = max(0, min(self._un_page, pages - 1))
        hidden = bool(self.config and self.config.data.get("hide_unavailable"))
        self.un_stats.setText(
            (f"{tracks_word(total)} — {'сейчас скрыты' if hidden else 'будут скрыты'} при «Скрывать "
             f"недоступные треки». Хранится до {store.LIMIT}, при переполнении удаляются самые старые."
             ) if total else "Недоступных треков пока не встречалось.")
        icons_cache = {sid: service_icon(cls, 18) for sid, cls in AVAILABLE.items()}
        for track, reason in items[self._un_page * PAGE:(self._un_page + 1) * PAGE]:
            row = TrackRow(track, icons_cache.get(track.service_id))
            if reason:
                row.setToolTip(reason)
            self.un_rows.addWidget(row)
        for b in (self.un_prev, self.un_next, self.un_clear):
            b.setVisible(total > 0)
        self.un_prev.setEnabled(self._un_page > 0)
        self.un_next.setEnabled(self._un_page < pages - 1)
        if pages > 1:   # номера страниц; при многих — окно вокруг текущей
            show = sorted({0, pages - 1, *range(max(0, self._un_page - 2), min(pages, self._un_page + 3))})
            prev_n = -1
            for n in show:
                if prev_n >= 0 and n - prev_n > 1:
                    self.un_pages.addWidget(muted("…"))
                b = _button(str(n + 1))
                b.setCheckable(True)
                b.setChecked(n == self._un_page)
                b.setObjectName("chip")
                b.clicked.connect(lambda _=False, k=n: self._goto(k))
                self.un_pages.addWidget(b)
                prev_n = n

    def _clear_unavailable(self) -> None:
        answer = QMessageBox.question(self, "Очистить список",
                                      "Очистить список недоступных треков? Сами треки и пометки сервисов "
                                      "не меняются: список заполнится снова, когда такие треки встретятся.")
        if answer == QMessageBox.StandardButton.Yes and self.unavailable is not None:
            self._un_page = 0
            self.unavailable.clear()

    def _downloads_dir(self) -> Path:
        return self.stores[3].dir

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.refresh()

    def refresh(self) -> None:
        if self.stores is None or not self.isVisible():
            return
        history, likes, playlists, downloads = self.stores
        n = len(downloads.entries)
        size = folder_size(downloads.dir)
        pending = len(downloads.pending)
        stats = f"{tracks_word(n)}, {human_size(size)}" if n else "Пока ничего не скачано"
        if pending:
            stats += f"  (скачивается ещё {pending})"
        self.dl_stats.setText(stats)
        self.dl_path.setText(str(downloads.dir))
        self.clear_dl.setEnabled(n > 0)
        if self.config is not None:
            self.offline.blockSignals(True)
            self.offline.setChecked(bool(self.config.data.get("offline")))
            self.offline.blockSignals(False)
        self._render_unavailable()

        folder = config_dir()
        local_tracks = sum(len(p["tracks"]) for p in playlists.all())
        self.data_stats.setText(
            f"Лайков: {len(likes.entries)}  ·  плейлистов: {len(playlists.all())} ({tracks_word(local_tracks)})"
            f"  ·  в истории: {len(history.entries)}  ·  занимает {human_size(folder_size(folder))}")
        self.data_path.setText(str(folder))
        from .. import paths
        where = ("Портативный режим: данные лежат в папке data рядом с программой и переезжают вместе "
                 "с ней. Нет папки — Sonar создаст новую, как при первом запуске."
                 if paths.is_portable() and not paths.fallback_reason
                 else "Данные хранятся в профиле Windows и не удаляются вместе с программой.")
        if paths.fallback_reason:
            where = paths.fallback_reason
        self.data_note.setText(f"{where} Здесь настройки, сервисы с токенами входа, профиль, лайки, "
                               "плейлисты и история. Токены лежат открытым текстом — не передавайте "
                               "эти файлы другим.")
        from ..logs import log_path
        lp = log_path()
        self.log_stats.setText(f"Текущий запуск: {human_size(lp.stat().st_size) if lp.exists() else 'пусто'}")
        self.log_path.setText(str(lp))

    def _open_log(self) -> None:
        from ..logs import log_path
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(log_path())))

    def _save_log(self) -> None:
        """Копия журнала (текущий и прошлый запуск в одном файле) туда, куда скажут."""
        import datetime
        from PyQt6.QtWidgets import QFileDialog
        from ..logs import log_dir
        default = str(Path.home() / "Desktop" / f"sonar-log-{datetime.datetime.now():%Y%m%d-%H%M}.txt")
        target, _ = QFileDialog.getSaveFileName(self, "Сохранить журнал", default, "Текст (*.txt)")
        if not target:
            return
        parts = []
        for name, title in (("sonar.prev.log", "ПРОШЛЫЙ ЗАПУСК"), ("sonar.log", "ТЕКУЩИЙ ЗАПУСК")):
            f = log_dir() / name
            if f.exists():
                parts.append(f"===== {title} =====\n" + f.read_text("utf-8", errors="replace"))
        Path(target).write_text("\n\n".join(parts) or "Журнал пуст.", "utf-8")
        QMessageBox.information(self, "Журнал сохранён", f"Сохранено в\n{target}")

    @staticmethod
    def _open(path: Path) -> None:
        path.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def _clear_downloads(self) -> None:
        downloads = self.stores[3]
        n = len(downloads.entries)
        answer = QMessageBox.question(self, "Удалить загрузки",
                                      f"Удалить все скачанные треки ({tracks_word(n)})? "
                                      "В офлайн-режиме слушать будет нечего.")
        if answer == QMessageBox.StandardButton.Yes:
            for track_id in list(downloads.entries):
                downloads.remove(track_id)

    def _reset(self) -> None:
        extra = " и скачанные треки" if self.with_downloads.isChecked() else ""
        answer = QMessageBox.warning(
            self, "Сбросить всё",
            f"Удалить все данные Sonar{extra}? Подключения, профиль, лайки, плейлисты и история "
            "пропадут, Sonar перезапустится. Это нельзя отменить.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel)
        if answer == QMessageBox.StandardButton.Yes:
            self.reset_requested.emit(self.with_downloads.isChecked())
