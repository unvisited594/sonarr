from itertools import zip_longest

from ..services.base import name_from
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton, QScrollArea,
                             QVBoxLayout, QWidget)

from ..workers import run_async
from . import icons
from .theme import C, font
from .visibility import is_offline, visible
from .widgets import GroupHeader, Hero, Shelf, TrackRow, clear_layout, muted, show_track_menu

SEARCH_DELAY_MS = 450


class AuthNeeded:
    """Результат загрузки сервиса, отклонившего вход."""
    def __init__(self, message: str) -> None:
        self.message = message
SEARCH_ROWS = 20


class HomePage(QWidget):
    play_requested = pyqtSignal(list, int)
    video_requested = pyqtSignal(object)
    wave_requested = pyqtSignal(list)
    random_requested = pyqtSignal(list)
    sections_updated = pyqtSignal()
    relogin_requested = pyqtSignal(str)   # id сервиса, которому нужно войти заново
    offline_exit = pyqtSignal()
    open_integrations = pyqtSignal()

    def __init__(self, manager, config, parent=None) -> None:
        super().__init__(parent)
        self.manager, self.config = manager, config
        self._gen = 0
        self._sections: dict[str, object] = {}   # id сервиса -> list[Section] | str (ошибка)
        self._wave: dict[str, list] = {}
        self._search_gen = 0
        self._results: dict[str, object] = {}    # id сервиса -> list[Track] | str (ошибка)
        self._query = ""
        self._pending: set[str] = set()

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        content = QWidget()
        lay = QVBoxLayout(content)
        lay.setContentsMargins(28, 8, 28, 28)
        lay.setSpacing(28)

        self.search = QLineEdit()
        self.search.setObjectName("search")
        self.search.setPlaceholderText("Поиск треков")
        self.search.setClearButtonEnabled(True)
        self._search_icon = self.search.addAction(icons.icon("search", C("muted")),
                                                  QLineEdit.ActionPosition.LeadingPosition)
        self._debounce = QTimer(self, singleShot=True, interval=SEARCH_DELAY_MS)
        self._debounce.timeout.connect(lambda: self._start_search(self.search.text()))
        self.search.textChanged.connect(self._on_text)
        self.search.returnPressed.connect(lambda: (self._debounce.stop(),
                                                   self._start_search(self.search.text())))

        self.home_view = QWidget()
        hv = QVBoxLayout(self.home_view)
        hv.setContentsMargins(0, 0, 0, 0)
        hv.setSpacing(36)
        self.hero = Hero()
        self.hero.play_clicked.connect(lambda: self.wave_requested.emit(self.wave_pool()))
        self.hero.random_clicked.connect(lambda: self.random_requested.emit(self.random_pool()))
        hv.addWidget(self.hero)
        self.body = QVBoxLayout()
        self.body.setSpacing(30)
        hv.addLayout(self.body)
        lay.addWidget(self.home_view)

        self.search_view = QWidget()
        self.search_view.hide()
        self.results = QVBoxLayout(self.search_view)
        self.results.setContentsMargins(0, 0, 0, 0)
        self.results.setSpacing(22)
        lay.addWidget(self.search_view)

        lay.addStretch(1)
        scroll.setWidget(content)
        # Поиск вне области прокрутки: он остаётся на месте, пока листается главная.
        bar = QWidget()
        bar_lay = QHBoxLayout(bar)
        bar_lay.setContentsMargins(28, 20, 28, 12)
        bar_lay.addWidget(self.search)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(bar)
        outer.addWidget(scroll, 1)
        self._scroll = scroll

        manager.changed.connect(self.reload)
        self.reload()

    # ---------- общее ----------

    @property
    def hide_unavailable(self) -> bool:
        return bool(self.config.data.get("hide_unavailable"))

    def _visible(self, tracks: list) -> list:
        return visible(tracks, self.config)

    def _downloaded(self) -> list:
        from ..downloads import downloads
        store = downloads()
        return store.tracks() if store is not None else []

    def apply_theme(self) -> None:
        self._search_icon.setIcon(icons.icon("search", C("muted")))
        self.hero.apply_theme()
        self.apply_display()

    def apply_display(self) -> None:
        """Настройки отображения поменялись: перерисовываем из уже загруженного."""
        self._render_home()
        if self._query:
            self._render_search()

    def wave_pool(self) -> list:
        """Перемешивает очереди всех сервисов через один трек."""
        if is_offline(self.config):
            import random
            pool = self._visible(self._downloaded())
            random.shuffle(pool)
            return pool
        rows = zip_longest(*self._wave.values())
        return [t for row in rows for t in row if t and t.playable]

    def random_pool(self, size: int = 50) -> list:
        """Случайная подборка: треки главной всех сервисов, «Мои лайки» и локальные плейлисты."""
        import random
        from ..library import likes, playlists
        pool = [t for state in self._sections.values() if isinstance(state, list)
                for section in state for t in section.tracks]
        store = likes()
        if store is not None:
            pool += store.tracks(self.manager)
        local = playlists()
        if local is not None:
            for pl in local.all():
                pool += local.tracks(pl["id"], self.manager)
        if is_offline(self.config):
            pool = self._downloaded()
        seen, unique = set(), []
        for t in self._visible(pool):
            key = (t.service_id, t.id)
            if t.playable and key not in seen:
                seen.add(key)
                unique.append(t)
        random.shuffle(unique)
        return unique[:size]

    # ---------- главная ----------

    def reload(self, force: bool = False) -> None:
        self._gen += 1
        gen = self._gen
        self._sections.clear()
        self._wave.clear()
        if is_offline(self.config):  # офлайн: никаких запросов в сеть
            self._render_home()
            if self._query:
                self._start_search(self._query)
            return
        self._pending = {svc.id for svc in self.manager.connected()}
        self._featured: dict[str, list] = {}
        for svc in self.manager.connected():
            run_async(svc.featured_playlists,
                      on_done=lambda res, s=svc: self._featured_loaded(gen, s, res),
                      on_error=lambda err: None)
        for svc in self.manager.connected():
            run_async(self._fetch, svc, force,
                      on_done=lambda res, s=svc: self._home_loaded(gen, s, res),
                      on_error=lambda err, s=svc: self._home_loaded(gen, s, err))
        self._render_home()
        if not self._pending:
            self.manager.loading_finished.emit()
        if self._query:  # набор сервисов мог поменяться
            self._start_search(self._query)

    @staticmethod
    def _fetch(svc, force):
        """В фоне. Отклонённый вход возвращаем отдельно: ему нужна кнопка «Войти заново»,
        а не «Повторить» — повтор с тем же токеном ничего не даст."""
        from ..services.base import AuthError
        try:
            return svc.home_sections(force), svc.wave()
        except AuthError as exc:
            return AuthNeeded(str(exc))

    def _home_loaded(self, gen, svc, result) -> None:
        if gen != self._gen:
            return
        if isinstance(result, AuthNeeded):
            self._sections[svc.id] = result
            self.manager.report(svc.id, "auth", result.message)
        elif isinstance(result, str):
            self._sections[svc.id] = result
            self.manager.report(svc.id, "error", result)
        else:
            self._sections[svc.id], self._wave[svc.id] = result
            self.manager.report(svc.id, "ok")
        self._render_home()
        self._pending.discard(svc.id)
        if not self._pending:
            self.manager.loading_finished.emit()

    def _featured_loaded(self, gen, svc, result) -> None:
        if gen == self._gen and result:
            self._featured[svc.id] = result
            self._render_home()

    def _featured_shelf(self) -> QWidget:
        """«Подборки»: случайная подборка Sonar (цветная обложка) и плейлисты самих сервисов."""
        from . import nav
        from .icons import service_icon
        from .widgets import CardShelf, PlaylistCard
        random_card = PlaylistCard("Случайные 50", "Подборка Sonar", None, seed="sonar:random50")
        random_card.clicked.connect(lambda: self.random_requested.emit(self.random_pool()))
        cards = [random_card]
        for svc in self.manager.connected():
            for pl in getattr(self, "_featured", {}).get(svc.id, [])[:12]:
                sub = pl.owner if pl.owner and pl.owner != svc.name else svc.name
                card = PlaylistCard(pl.title, sub, pl.cover_url, service_icon(type(svc), 22),
                                    seed=f"featured:{svc.id}:{pl.id}")
                card.clicked.connect(lambda sid=svc.id, p=pl: nav.open_playlist(sid, p))
                cards.append(card)
        return CardShelf("Подборки", cards)

    def _render_offline(self) -> None:
        banner = QFrame()
        banner.setObjectName("emptyState")
        bl = QHBoxLayout(banner)
        bl.setContentsMargins(18, 12, 14, 12)
        text = QLabel("<b>Офлайн-режим</b>: видны только скачанные треки Navidrome.")
        text.setWordWrap(True)
        bl.addWidget(text, 1)
        back = QPushButton("Вернуться в онлайн")
        back.setProperty("compact", True)
        back.setCursor(Qt.CursorShape.PointingHandCursor)
        back.clicked.connect(self.offline_exit)
        bl.addWidget(back)
        self.body.addWidget(banner)
        from ..services import AVAILABLE
        tracks = self._visible(self._downloaded())
        if tracks:
            shelf = Shelf("Скачанное", tracks, AVAILABLE.get("navidrome"), False)
            shelf.play_requested.connect(self.play_requested)
            self.body.addWidget(shelf)
        else:
            empty = muted("Офлайн-режим: здесь только скачанные треки Navidrome, а их пока нет. "
                          "Скачать трек: правый клик → «Скачать для офлайна» (в онлайн-режиме).")
            empty.setWordWrap(True)
            self.body.addWidget(empty)
        pool = self.wave_pool()
        self.hero.set_preview(pool[:3])
        self.hero.set_subtitle(f"Офлайн: скачанные треки ({len(tracks)})" if tracks
                               else "Офлайн: нет скачанных треков")

    def _render_home(self) -> None:
        clear_layout(self.body)
        self.sections_updated.emit()
        if is_offline(self.config):
            self._render_offline()
            return
        services = self.manager.connected()
        if not services:
            self.body.addWidget(self._empty_state())
            self._update_hero()
            return
        self.body.addWidget(self._featured_shelf())
        for svc in services:
            state = self._sections.get(svc.id)
            if state is None:
                self.body.addWidget(muted(f"Загружаем музыку из {name_from(svc)}…"))
            elif isinstance(state, AuthNeeded):
                self.body.addWidget(self._login_row(svc, state.message))
            elif isinstance(state, str):
                self.body.addWidget(self._error_row(svc, state, lambda: self.reload(force=True)))
            else:
                shown = 0
                for section in state:
                    tracks = self._visible(section.tracks)
                    if not tracks:
                        continue
                    shelf = Shelf(section.title, tracks, type(svc), svc.supports_video)
                    shelf.play_requested.connect(self.play_requested)
                    shelf.video_requested.connect(self.video_requested)
                    self.body.addWidget(shelf)
                    shown += 1
                if not shown:
                    self.body.addWidget(muted(
                        f"В {svc.name} пока нечего показать. Лайкните несколько треков, "
                        "и здесь появится ваша музыка."))
        self._update_hero()

    def _update_hero(self) -> None:
        pool = self.wave_pool()
        self.hero.set_preview(pool[:3])
        services = self.manager.connected()
        if not services:
            self.hero.set_subtitle("Подключите сервис, чтобы волна заработала")
        elif pool:
            names = ", ".join(s.name for s in services if self._wave.get(s.id))
            self.hero.set_subtitle(f"Ваши лайки и рекомендации из {names}")
        elif len(self._sections) < len(services):
            self.hero.set_subtitle("Собираем волну…")
        else:
            self.hero.set_subtitle("Волне пока не из чего собраться")

    def _login_row(self, svc, message: str) -> QWidget:
        row = QFrame()
        row.setObjectName("emptyState")
        lay = QHBoxLayout(row)
        lay.setContentsMargins(18, 14, 14, 14)
        lay.setSpacing(12)
        from .icons import service_icon
        icon = QLabel()
        icon.setPixmap(service_icon(type(svc), 32))
        lay.addWidget(icon)
        text = QLabel(f"<b>{svc.name}</b>: вход устарел, нужно войти заново.")
        text.setWordWrap(True)
        lay.addWidget(text, 1)
        btn = QPushButton("Войти заново")
        btn.setProperty("kind", "primary")
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.clicked.connect(lambda: self.relogin_requested.emit(svc.id))
        lay.addWidget(btn)
        return row

    def _error_row(self, svc, error: str, retry) -> QWidget:
        row = QWidget()
        lay = QHBoxLayout(row)
        lay.setContentsMargins(8, 0, 0, 0)
        text = muted(f"{svc.name}: {error}", role="error")
        text.setWordWrap(True)
        lay.addWidget(text, 1)
        btn = QPushButton("Повторить")
        btn.clicked.connect(retry)
        lay.addWidget(btn)
        return row

    def _empty_state(self) -> QWidget:
        box = QFrame()
        box.setObjectName("emptyState")
        lay = QVBoxLayout(box)
        lay.setContentsMargins(28, 26, 28, 28)
        lay.setSpacing(8)
        title = QLabel("Подключите музыкальный сервис")
        title.setFont(font(22, QFont.Weight.Bold, display=True))
        lay.addWidget(title)
        text = muted("Ваша музыка и рекомендации появятся здесь, как только вы подключите "
                     "сервис в настройках.")
        text.setWordWrap(True)
        lay.addWidget(text)
        lay.addSpacing(10)
        btn = QPushButton("Открыть интеграцию")
        btn.setProperty("kind", "primary")
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.clicked.connect(self.open_integrations)
        lay.addWidget(btn, 0, Qt.AlignmentFlag.AlignLeft)
        return box

    # ---------- поиск ----------

    def _on_text(self, text: str) -> None:
        if not text.strip():
            self._debounce.stop()
            self._search_gen += 1
            self._query = ""
            self.search_view.hide()
            self.home_view.show()
        elif len(text.strip()) >= 2:
            self._debounce.start()

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape and self.search.text():
            self.search.clear()
        else:
            super().keyPressEvent(event)

    def _start_search(self, text: str) -> None:
        query = text.strip()
        if not query:
            return
        self._query = query
        self._search_gen += 1
        gen = self._search_gen
        self._results.clear()
        self.home_view.hide()
        self.search_view.show()
        self._scroll.verticalScrollBar().setValue(0)
        if is_offline(self.config):  # офлайн: ищем по скачанному, без сети
            q = query.casefold()
            self._offline_results = [t for t in self._downloaded()
                                     if q in t.title.casefold() or q in t.artist.casefold()]
            self._render_search()
            return
        for svc in self.manager.connected():
            run_async(svc.search, query,
                      on_done=lambda res, s=svc: self._search_done(gen, s, res),
                      on_error=lambda err, s=svc: self._search_done(gen, s, err))
        self._render_search()

    def _search_done(self, gen, svc, result) -> None:
        if gen != self._search_gen:
            return
        self._results[svc.id] = result
        self._render_search()

    def _render_search(self) -> None:
        clear_layout(self.results)
        title = QLabel(f"Результаты по запросу «{self._query}»")
        title.setFont(font(26, QFont.Weight.Bold, display=True))
        title.setWordWrap(True)
        self.results.addWidget(title)
        if is_offline(self.config):
            tracks = self._visible(getattr(self, "_offline_results", []))
            self.results.addWidget(muted("Офлайн-режим: поиск по скачанным трекам"))
            if not tracks:
                self.results.addWidget(muted("Среди скачанных ничего не нашлось."))
            for i, track in enumerate(tracks):
                row = TrackRow(track)
                row.clicked.connect(lambda i=i, t=tracks: self.play_requested.emit(t, i))
                row.menu_requested.connect(lambda pos, i=i, t=tracks: show_track_menu(
                    self, t, i, pos, False, self.play_requested.emit, self.video_requested.emit))
                self.results.addWidget(row)
            return
        services = self.manager.connected()
        if not services:
            self.results.addWidget(muted("Подключите сервис в Настройках → Интеграция, "
                                         "чтобы искать музыку."))
            return
        collapsed = set(self.config.data.get("search_collapsed", []))
        for svc in services:
            state = self._results.get(svc.id)
            tracks = self._visible(state)[:SEARCH_ROWS] if isinstance(state, list) else []
            count = str(len(tracks)) if isinstance(state, list) else ""
            header = GroupHeader(icons.service_icon(type(svc), 24), svc.name, count,
                                 expanded=svc.id not in collapsed)
            body = QWidget()
            body_lay = QVBoxLayout(body)
            body_lay.setContentsMargins(0, 4, 0, 0)
            body_lay.setSpacing(2)
            body.setVisible(svc.id not in collapsed)
            header.toggled.connect(lambda on, b=body, sid=svc.id: self._set_group(sid, b, on))
            if state is None:
                body_lay.addWidget(muted("Ищем…"))
            elif isinstance(state, str):
                err = muted(state, role="error")
                err.setWordWrap(True)
                body_lay.addWidget(err)
            elif not tracks:
                body_lay.addWidget(muted("Ничего не нашлось."))
            for i, track in enumerate(tracks):
                row = TrackRow(track)
                if track.playable:
                    row.clicked.connect(lambda i=i, t=tracks: self.play_requested.emit(t, i))
                row.menu_requested.connect(
                    lambda pos, i=i, t=tracks, sv=svc: show_track_menu(
                        self, t, i, pos, sv.supports_video,
                        self.play_requested.emit, self.video_requested.emit))
                body_lay.addWidget(row)
            group = QWidget()
            group_lay = QVBoxLayout(group)
            group_lay.setContentsMargins(0, 0, 0, 0)
            group_lay.setSpacing(0)
            group_lay.addWidget(header)
            group_lay.addWidget(body)
            self.results.addWidget(group)

    def _set_group(self, service_id: str, body: QWidget, expanded: bool) -> None:
        body.setVisible(expanded)
        collapsed = set(self.config.data.get("search_collapsed", []))
        if expanded:
            collapsed.discard(service_id)
        else:
            collapsed.add(service_id)
        self.config.data["search_collapsed"] = sorted(collapsed)
        self.config.save()
