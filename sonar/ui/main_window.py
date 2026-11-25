import logging
import sys

from PyQt6.QtCore import QSize, Qt, QTimer
from PyQt6.QtGui import QColor, QIcon
from PyQt6.QtWidgets import (QApplication, QButtonGroup, QHBoxLayout, QLabel, QMainWindow,
                             QToolButton, QVBoxLayout, QWidget)

from ..config import APP_NAME, Config
from ..history import History
from ..downloads import Downloads, set_downloads
from ..library import Likes, LocalPlaylists, set_likes, set_playlists
from ..services import AVAILABLE

AVAILABLE_NAMES = {sid: cls.name for sid, cls in AVAILABLE.items()}
from ..services import ServiceManager
from . import icons
from . import theme as themes
from .decor import SantaHat, SnowOverlay, ThemedPanel
from .full_player import FullPlayer
from .history_page import HistoryPage
from .mini_player import MiniPlayer
from .onboarding import Onboarding
from .. import profile as profiles
from .service_page import ServicePage
from .home import HomePage
from .likes_page import LikesPage
from .playlists_page import PlaylistsPage
from .player import Player, PlayerBar
from .settings import SettingsPage
from .video import VideoWindow


WORKSHOP_PAGE = 10   # индекс страницы Мастерской в стеке (после 0–9)
WRAPPED_PAGE = 11    # «Итоги года»
RADIO_PAGE = 12      # «Радио»


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(QIcon(icons.pixmap("logo", "#f2f2f2", 64)))
        self.resize(1300, 840)
        self.setMinimumSize(980, 640)

        self.config = Config()
        themes.set_accent(self.config.data.get("accent"))
        themes.set_backgrounds(self.config.data.get("bg_sidebar"), self.config.data.get("bg_panel"))
        themes.apply_theme(QApplication.instance(), themes.effective_theme(self.config.data))
        self.manager = ServiceManager(self.config)
        self.history = History()
        self.likes = Likes()
        set_likes(self.likes)
        self.playlists = LocalPlaylists()
        set_playlists(self.playlists)
        from ..library import UnavailableTracks, set_unavailable
        self.unavailable = UnavailableTracks()
        set_unavailable(self.unavailable)
        self.downloads = Downloads(self.manager)
        set_downloads(self.downloads)
        volume = int(self.config.data.get("volume", 70))
        self.player = Player(self.manager, volume)

        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        h = QHBoxLayout(root)
        h.setContentsMargins(0, 0, 10, 0)
        h.setSpacing(0)
        h.addWidget(self._sidebar())

        right = QVBoxLayout()
        right.setContentsMargins(0, 10, 0, 0)
        right.setSpacing(0)
        self.panel = ThemedPanel()
        self.panel.setObjectName("panel")
        pl = QVBoxLayout(self.panel)
        pl.setContentsMargins(0, 0, 0, 0)
        from .anim import FadeStack
        self.stack = FadeStack()
        pl.addWidget(self.stack)
        right.addWidget(self.panel, 1)
        self.bar = PlayerBar(self.player, volume, self.likes)
        right.addWidget(self.bar)
        h.addLayout(right, 1)

        self.home = HomePage(self.manager, self.config)
        self.settings = SettingsPage(self.manager, self.config)
        self.history_page = HistoryPage(self.history, self.manager, self.config)
        self.likes_page = LikesPage(self.likes, self.manager, self.config)
        self.playlists_page = PlaylistsPage(self.playlists, self.manager, self.config)
        # Индексы страниц = id кнопок меню: 0 главная, 1 настройки, 2 прослушанное, 3 мои лайки,
        # 4 плейлисты
        self.stack.addWidget(self.home)
        self.stack.addWidget(self.settings)
        self.stack.addWidget(self.history_page)
        self.stack.addWidget(self.likes_page)
        self.stack.addWidget(self.playlists_page)
        self.service_page = ServicePage(self.home, self.manager, self.config)
        self.stack.addWidget(self.service_page)   # 5: страница сервиса из левого меню
        from .library_pages import AlbumPage, AlbumsPage, ArtistPage, ArtistsPage
        self.artists_page = ArtistsPage(self.manager, self.config, self.likes)
        self.albums_page = AlbumsPage(self.manager, self.config)
        self.artist_page = ArtistPage(self.manager, self.config, self.go_back)
        self.album_page = AlbumPage(self.manager, self.config, self.go_back)
        for page in (self.artists_page, self.albums_page, self.artist_page, self.album_page):
            self.stack.addWidget(page)   # 6 исполнители, 7 альбомы, 8 исполнитель, 9 альбом
        for page in (self.artist_page, self.album_page):
            page.play_requested.connect(lambda tracks, i: self.player.play_queue(tracks, i, "artist"))
            page.video_requested.connect(self.open_video)
        self._history: list = []   # откуда пришли на страницу исполнителя/альбома — для «Назад»
        from . import nav
        nav.set_handlers(artist=self.open_artist, album=self.open_album, playlist=self.open_service_playlist,
                         toast=self.show_toast)

        from .flow_settings import FlowSettings, set_flow
        self.flow = FlowSettings(self.config)
        set_flow(self.flow)
        from .player import SleepTimer
        self.sleep = SleepTimer(self.player)
        self.bar.set_sleep_timer(self.sleep)
        # Наушники и колонки: куда играет звук и как выглядит устройство
        from .audio_devices import DeviceLook
        self.player.set_output(self.config.data.get("audio_device") or "")
        self.bar.set_device_look(DeviceLook(self.config), self.config)
        from .equalizer import Equalizer
        self.player.eq = Equalizer(self.player, self.config)
        self.player.eq.failed.connect(self.show_toast)
        from .crossfade import Crossfader
        self.crossfade = Crossfader(self.player, self.config)
        from .endless import Endless
        self.endless = Endless(self.player, self.manager, self.config, self.show_toast)
        from .hotkeys import Hotkeys
        self.hotkeys = Hotkeys(self, self.config)
        self.hotkeys.triggered.connect(self._hotkey)
        self.player.playing_changed.connect(self.hotkeys.set_playing)   # медиакнопки — только пока играем

        self.bar.set_equalizer(self.player.eq)
        self.sleep.fired.connect(lambda: self.show_toast("Таймер сна: музыка на паузе. Спокойной ночи"))
        self.sleep.changed.connect(self._sleep_toast)
        self.full_player = FullPlayer(self, self.player, self.likes, self.bar.volume)
        self.flow.changed.connect(self.full_player.apply_flow)
        self.full_player.apply_flow()
        self.settings.add_player_tab(self.flow, lambda: self.full_player._cover_colors)
        lay = getattr(self.settings, "player_tab_lay", None)
        if lay is not None:   # «Горячие клавиши» — в конец вкладки «Плеер», перед растяжкой
            from .hotkeys import HotkeysSection
            item = lay.takeAt(lay.count() - 1)
            self._hotkeys_section = HotkeysSection(self.hotkeys, lay)
            if item is not None and item.spacerItem() is not None:
                lay.addStretch(1)
        from .personalize import Personalization, set_personalization
        self.pers = Personalization(self.config)
        set_personalization(self.pers)
        self.pers.changed.connect(self._apply_look)
        self._setup_workshop()
        self._setup_extras()
        self.settings.add_look_tab(self.pers)
        self.settings.add_behaviour(self.pers)
        self._apply_look()
        self.player.set_repeat(bool(self.config.data.get("repeat")))
        self.mini = MiniPlayer(self.player, self.config, self.restore_from_mini, self.bar.volume)
        self._was_maximized = False
        self.player.repeat_changed.connect(self._save_repeat)
        self.full_player.video_requested.connect(self.open_video)
        self.bar.expand_requested.connect(self.open_full_player)
        self.snow = SnowOverlay(self)
        self.hats = [SantaHat(self.home.hero.play, 0.8), SantaHat(self.bar.play_btn, 0.72, lift=0.32)]

        self.toast = QLabel(self)
        self.toast.setObjectName("toast")
        self.toast.hide()
        from .anim import ToastAnimator
        self._toast_anim = ToastAnimator(self.toast)
        self._toast_timer = QTimer(self, singleShot=True, interval=4000)
        self._toast_timer.timeout.connect(self._toast_anim.hide)

        self.home.play_requested.connect(lambda tracks, i: self.player.play_queue(tracks, i, "shelf"))
        self.home.wave_requested.connect(self._wave)
        self.history_page.play_requested.connect(
            lambda tracks, i: self.player.play_queue(tracks, i, "history"))
        self.history_page.video_requested.connect(self.open_video)
        self.likes_page.play_requested.connect(
            lambda tracks, i: self.player.play_queue(tracks, i, "likes"))
        self.likes_page.video_requested.connect(self.open_video)
        self.likes.changed.connect(self.bar.update_like)
        self.likes.liked.connect(self._like_burst)
        self.playlists_page.play_requested.connect(
            lambda tracks, i: self.player.play_queue(tracks, i, "playlist"))
        self.playlists_page.video_requested.connect(self.open_video)
        self.home.random_requested.connect(self._random)
        self.home.relogin_requested.connect(self.relogin)
        self.manager.loading_finished.connect(self._home_loaded)
        self.service_page.play_requested.connect(
            lambda tracks, i: self.player.play_queue(tracks, i, "service"))
        self.service_page.video_requested.connect(self.open_video)

        self.downloads.finished.connect(lambda title: self.show_toast(f"Скачано для офлайна: {title}"))
        self.downloads.failed.connect(lambda title, err: self.show_toast(f"Не удалось скачать «{title}»: {err}"))
        self.downloads.changed.connect(self._downloads_changed)

        self.player.started.connect(self.history.add)
        self.player.started.connect(self._on_track_started_minimized)
        self.home.video_requested.connect(self.open_video)
        self.bar.video_requested.connect(self.open_video)
        self.video_window = None
        self.home.open_integrations.connect(self._open_integrations)
        self.settings.refresh_requested.connect(lambda: self.home.reload(force=True))
        self.settings.display_changed.connect(self.home.apply_display)
        self.settings.display_changed.connect(self.history_page.refresh)
        self.settings.display_changed.connect(self.likes_page.refresh)
        self.settings.display_changed.connect(self.playlists_page.refresh)
        self.settings.theme_changed.connect(self.apply_theme)
        self.settings.theme_reapply.connect(lambda t: self.apply_theme(t, force=True))
        self.settings.data_tab.set_stores(self.history, self.likes, self.playlists, self.downloads,
                                          self.unavailable, self.manager, self.config)
        self.settings.data_tab.offline_changed.connect(self.set_offline)
        self.home.offline_exit.connect(lambda: self.set_offline(False))
        self.player.track_unavailable.connect(lambda t: self.unavailable.note(t, "Не запустился в сервисе"))
        self.player.started.connect(self.unavailable.discard)
        self.settings.data_tab.reset_requested.connect(self.reset_all)
        self.player.message.connect(self.show_toast)
        self.player.track_unavailable.connect(lambda _t: (self.home.apply_display(),
                                                          self.history_page.refresh(),
                                                          self.likes_page.refresh(),
                                                          self.playlists_page.refresh()))
        self.player.playing_changed.connect(
            lambda on: self.home.hero.set_playing(on and self.player.context == "wave"))

        self._dark_title_bar()
        self._apply_decorations()
        from .busy import BusyOverlay
        self.busy_overlay = BusyOverlay(self)
        self._busy_depth = 0
        from .extras import Tray, install_shortcuts
        install_shortcuts(self)
        self.tray = Tray(self, self.windowIcon())
        self.player.track_changed.connect(self.tray.on_track)
        self.player.started.connect(self._notify_track)
        geometry = self.config.data.get("window_geometry")
        if geometry:   # размер, положение и «на весь экран» — как в прошлый раз
            from PyQt6.QtCore import QByteArray
            self.restoreGeometry(QByteArray.fromBase64(geometry.encode("ascii")))
        if self.player.restore(self.config.data.get("session")):
            self.bar.update_like()
        from .. import paths
        if paths.fallback_reason:   # папка программы недоступна для записи — объясняем, где данные
            logging.getLogger("sonar").warning("Папка данных: %s", paths.fallback_reason)
            QTimer.singleShot(1500, lambda: self.show_toast("Данные хранятся не рядом с программой — "
                                                            "подробности в Настройки → Данные"))
        # Знакомство: при первом запуске (или если имя ещё не указано)
        self.onboarding = Onboarding(self, self.config)
        self.onboarding.finished.connect(self._profile_saved)
        if profiles.get(self.config) is None:
            QTimer.singleShot(0, lambda: (self.onboarding.open(edit=False), self._raise_decor()))
        # «Авто»: раз в 30 секунд проверяем, не пора ли сменить светлую и тёмную
        self._theme_clock = QTimer(self, interval=30_000)
        self._theme_clock.timeout.connect(self._check_theme_time)
        self._theme_clock.start()

    def _sidebar(self) -> QWidget:
        side = QWidget()
        side.setObjectName("sidebar")
        side.setFixedWidth(72)
        v = QVBoxLayout(side)
        v.setContentsMargins(12, 16, 12, 18)
        v.setSpacing(10)
        self.profile_btn = QToolButton()   # аватарка профиля; пока профиля нет — логотип
        self.profile_btn.setObjectName("profileBtn")
        self.profile_btn.setFixedSize(48, 48)
        self.profile_btn.setIconSize(QSize(40, 40))
        self.profile_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.profile_btn.clicked.connect(self.edit_profile)
        self._update_profile_btn()
        v.addWidget(self.profile_btn, 0, Qt.AlignmentFlag.AlignHCenter)
        v.addSpacing(6)
        self.nav = QButtonGroup(self)
        self._nav_icons: list = []
        self.nav.setExclusive(True)
        home = self._nav_button("home", "Главная", 0)
        listened = self._nav_button("wave", "Прослушанное", 2)
        liked = self._nav_button("heart", "Мои лайки", 3)
        lists = self._nav_button("playlist", "Плейлисты", 4)
        artists = self._nav_button("mic", "Исполнители", 6)
        albums = self._nav_button("disc", "Альбомы", 7)
        workshop = self._nav_button("palette", "Мастерская: наборы оформления, достижения, приколюхи", WORKSHOP_PAGE)
        wrapped = self._nav_button("spark", "Итоги года", WRAPPED_PAGE)
        radio_btn = self._nav_button("globe", "Радио", RADIO_PAGE)
        settings = self._nav_button("settings", "Настройки", 1)
        home.setChecked(True)
        v.addWidget(home)
        v.addWidget(listened)
        v.addWidget(liked)
        v.addWidget(lists)
        v.addWidget(artists)
        v.addWidget(albums)
        v.addWidget(workshop)
        v.addWidget(wrapped)
        v.addWidget(radio_btn)
        v.addSpacing(8)
        self._service_buttons: dict = {}   # сервисов в меню больше нет; словарь — для совместимости
        v.addStretch(1)
        self.refresh_btn = QToolButton()
        self.refresh_btn.setObjectName("nav")
        self.refresh_btn.setFixedSize(48, 48)
        self.refresh_btn.setIconSize(QSize(24, 24))
        self.refresh_btn.setIcon(icons.icon("refresh", themes.C("side_muted")))
        self.refresh_btn.setToolTip("Обновить главную")
        self.refresh_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.refresh_btn.clicked.connect(self.refresh_home)
        from .widgets import Spinner
        self._refresh_spinner = Spinner(self.refresh_btn, "refresh", "side_muted", 24)
        v.addWidget(self.refresh_btn)
        v.addWidget(settings)  # в самом низу
        return side

    def _apply_look(self) -> None:
        """Иконка окна и панели задач, обои панели, акцентный цвет."""
        self.player.fallback_enabled = bool(self.pers.get("fallback_services"))
        look = (self.pers.get("accent"), self.pers.get("bg_sidebar"), self.pers.get("bg_panel"))
        if look != getattr(self, "_look_applied", "unset"):
            first = not hasattr(self, "_look_applied")
            self._look_applied = look
            themes.set_accent(look[0])
            themes.set_backgrounds(look[1], look[2])
            if not first:  # при запуске тема уже применена с этими цветами
                self.apply_theme(themes.current_id(), force=True)
        from .personalize import app_icon
        icon = QIcon(app_icon(self.pers.get("app_icon"), 128))
        self.setWindowIcon(icon)
        if getattr(self, "tray", None) is not None:
            self.tray.set_icon(icon)
        QApplication.instance().setWindowIcon(icon)
        if getattr(self, "video_window", None) is not None:
            self.video_window.setWindowIcon(icon)
        self._update_profile_btn()
        self.panel.update()
        if hasattr(self, "snow"):
            self._apply_decorations()   # переключатель «Снежинки»

    def _update_profile_btn(self) -> None:
        p = profiles.get(self.config)
        if p:
            self.profile_btn.setIcon(QIcon(icons.circle_avatar(profiles.avatar_path(p.get("avatar")), 40)))
            self.profile_btn.setToolTip(f"{p.get('name', '')} — изменить имя или аву")
        else:
            from .personalize import app_icon, personalization
            pers = personalization()
            kind = pers.get("app_icon") if pers else "standard"
            self.profile_btn.setIcon(QIcon(app_icon(kind, 40) if kind != "standard"
                                           else icons.pixmap("logo", themes.C("text"), 40)))
            self.profile_btn.setToolTip("Профиль")

    def edit_profile(self) -> None:
        self.onboarding.open(edit=profiles.get(self.config) is not None)
        self._raise_decor()

    def _profile_saved(self, profile: dict) -> None:
        self._update_profile_btn()
        self.show_toast(f"Привет, {profile['name']}!")

    def _raise_decor(self) -> None:
        if self.snow.isVisible():
            self.snow.raise_()
        self.toast.raise_()

    def _push_page(self, page) -> None:
        current = self.stack.currentWidget()
        if current is not page:
            self._history.append(current)
            del self._history[:-20]
        if self.full_player.isVisible():
            self.full_player.close_player()
        self.nav.setExclusive(False)   # страница вне меню: ни одна кнопка не подсвечена
        for b in self.nav.buttons():
            b.setChecked(False)
        self.nav.setExclusive(True)
        self.stack.setCurrentWidget(page)

    def open_artist(self, service_id: str, artist_id: str, name: str = "") -> None:
        self._push_page(self.artist_page)
        self.artist_page.show_artist(service_id, artist_id, name)

    def open_album(self, album) -> None:
        self._push_page(self.album_page)
        self.album_page.show_album(album)

    def open_service_playlist(self, service_id: str, playlist) -> None:
        svc = self.manager.get(service_id)
        if svc is None:
            return
        self.nav.button(4).setChecked(True)
        self.stack.setCurrentWidget(self.playlists_page)
        self.playlists_page.open_service(svc, playlist)

    def go_back(self) -> None:
        page = self._history.pop() if self._history else self.home
        self.stack.setCurrentWidget(page)
        button = self.nav.button(self.stack.indexOf(page))
        if button is not None:
            button.setChecked(True)

    def open_service(self, service_id: str) -> None:
        self.service_page.show_service(service_id)
        self.stack.setCurrentWidget(self.service_page)
        if service_id in self._service_buttons:
            self._service_buttons[service_id].setChecked(True)

    def set_offline(self, on: bool) -> None:
        if bool(self.config.data.get("offline")) == on:
            return
        self.config.data["offline"] = on
        self.config.save()
        toggle = self.settings.data_tab.offline   # переключатель в «Данных» — сразу, даже если вкладка скрыта
        toggle.blockSignals(True)
        toggle.setChecked(on)
        toggle.blockSignals(False)
        self.home.reload()
        self.history_page.refresh()
        self.likes_page.refresh()
        self.playlists_page._remote.clear()
        self.playlists_page.refresh()
        if not on and self.playlists_page.isVisible():
            self.playlists_page._load_remote()
        self.service_page.refresh()
        count = len(self.downloads.entries)
        self.show_toast(f"Офлайн-режим: скачанных треков — {count}" if on else "Снова онлайн")

    def _check_theme_time(self) -> None:
        wanted = themes.effective_theme(self.config.data)
        if wanted != themes.current_id():
            self.apply_theme(wanted)
            self.settings.update_theme_controls()

    def busy(self, fn, text: str = "Применяю настройки"):
        """Тяжёлое применение оформления — под размытым снимком окна с надписью.
        Вложенные вызовы (тема включила снег и т. п.) показывают слой один раз."""
        if getattr(self, "_busy_depth", 0) or not hasattr(self, "busy_overlay") or not self.isVisible():
            return fn()
        self._busy_depth += 1
        self.busy_overlay.cover(text)
        try:
            return fn()
        finally:
            self._busy_depth -= 1
            QTimer.singleShot(80, self.busy_overlay.release)   # дать новой теме нарисоваться

    def apply_theme(self, theme_id: str, force: bool = False) -> None:
        if theme_id == themes.current_id() and not force:
            return
        self.busy(lambda: self._apply_theme_now(theme_id))

    def _apply_theme_now(self, theme_id: str) -> None:
        if hasattr(self, "pers"):   # свои цвета — из настроек на момент применения (выбор темы их сбрасывает)
            look = (self.pers.get("accent"), self.pers.get("bg_sidebar"), self.pers.get("bg_panel"))
            themes.set_accent(look[0])
            themes.set_backgrounds(look[1], look[2])
            self._look_applied = look   # чтобы следом не применить ту же тему второй раз
        themes.apply_theme(QApplication.instance(), theme_id)
        self._update_profile_btn()
        self._dark_title_bar()
        for button, name in self._nav_icons:
            button.setIcon(icons.icon(name, themes.C("side_muted"), themes.C("side_text")))
        self._refresh_spinner.stop()   # иконка в цвете новой темы
        self.home.apply_theme()
        self.bar.apply_theme()
        self.full_player.apply_theme()
        self.mini.apply_theme()
        self.history_page.refresh()
        self.likes_page.refresh()
        self.playlists_page.refresh()
        for card in self.settings.cards:
            card.rebuild()
        self._apply_decorations()
        self.update()

    def _apply_decorations(self) -> None:
        t = themes.current()
        pers = getattr(self, "pers", None)
        snow = pers.snow_on() if pers is not None else t["snow"]
        if snow:
            self.snow.start()
        else:
            self.snow.stop()
        for hat in self.hats:
            hat.set_enabled(t["hats"])
        self.toast.raise_()
        self.panel.update()

    def _nav_button(self, name: str, tip: str, page: int) -> QToolButton:
        b = QToolButton()
        b.setObjectName("nav")
        b.setCheckable(True)
        b.setFixedSize(48, 48)
        b.setIconSize(QSize(26, 26))
        b.setIcon(icons.icon(name, themes.C("side_muted"), themes.C("side_text")))
        self._nav_icons.append((b, name))
        b.setToolTip(tip)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.clicked.connect(lambda: (self._history.clear(), self.stack.setCurrentIndex(page)))
        self.nav.addButton(b, page)
        return b

    def _open_integrations(self) -> None:
        self.nav.button(1).setChecked(True)
        self.stack.setCurrentIndex(1)
        self.settings.show_integrations()

    def _wave(self, pool: list) -> None:
        if self.player.context == "wave" and self.player.queue:
            self.player.toggle()
        elif pool:
            self.player.play_queue(pool, 0, "wave")
        elif not self.manager.connected():
            self.show_toast("Подключите сервис: Настройки → Интеграция")
        else:
            self.show_toast("Волна ещё собирается, попробуйте через пару секунд")

    def open_video(self, track) -> None:
        current = self.player.current
        same = current is not None and current.id == track.id
        start = self.player.mp.position() if same else 0
        if self.player.is_playing:
            self.player.mp.pause()  # звук идёт из клипа, песню ставим на паузу
        if self.video_window is None:
            self.video_window = VideoWindow(self.manager)
            self.video_window.setWindowIcon(self.windowIcon())
        self.video_window.open(track, start, self.bar.volume.value() / 100)

    def _downloads_changed(self) -> None:
        if self.config.data.get("offline"):  # в офлайне от загрузок зависит, что видно
            self.home.reload()
            self.service_page.refresh()
            self.likes_page.refresh()
            self.history_page.refresh()
            self.playlists_page.refresh()

    def changeEvent(self, event) -> None:
        super().changeEvent(event)
        if event.type() == event.Type.WindowStateChange:
            if self.isMinimized():
                self._was_maximized = bool(event.oldState() & Qt.WindowState.WindowMaximized)
                self.mini.dismissed = False
                self.mini.show_mini()
            else:
                self.mini.hide()

    def restore_from_mini(self) -> None:
        self.mini.hide()
        if self._was_maximized:
            self.showMaximized()
        else:
            self.showNormal()
        self.raise_()
        self.activateWindow()

    def _on_track_started_minimized(self, _track) -> None:
        # Окно свёрнуто, а мини-плеера не было (ничего не играло): показываем его
        if self.isMinimized() and not self.mini.isVisible():
            self.mini.show_mini()

    def _save_repeat(self, on: bool) -> None:
        self.config.data["repeat"] = on
        self.config.save()

    def _notify_track(self, track) -> None:
        """Уведомление о новом треке — только если окно не перед глазами."""
        if not self.pers.get("notify_track"):
            return
        if self.isActiveWindow() and self.isVisible() and not self.isMinimized():
            return
        self.tray.notify(track)

    def _sleep_toast(self) -> None:
        if self.sleep.until_track_end:
            self.show_toast("Таймер сна: пауза после этого трека")
        elif self.sleep.deadline is not None:
            self.show_toast(f"Таймер сна: через {self.sleep.remaining_minutes()} мин")

    def _like_burst(self, track) -> None:
        """Сердечки из кнопки лайка — той, что сейчас на экране."""
        from .decor import HeartBurst
        if not self.pers.get("like_burst"):
            return
        btn = self.full_player.like_btn if self.full_player.isVisible() else self.bar.like_btn
        if not btn.isVisible():
            return
        center = btn.mapTo(self, btn.rect().center())
        HeartBurst(self, center, QColor("#ff4d6d"))
        if self.snow.isVisible():
            self.snow.raise_()

    def refresh_home(self) -> None:
        if not self.manager.connected():
            self.show_toast("Подключите сервис в Настройках → Интеграция")
            return
        if self._refresh_spinner.spinning:
            return   # уже обновляем
        self._refresh_spinner.start()   # иконка крутится, пока не догрузятся все сервисы
        self._refresh_requested_by_user = True
        self.home.reload(force=True)  # мимо кеша сервисов: заново лайки, рекомендации, полки
        self.show_toast("Обновляем главную…")

    def _home_loaded(self) -> None:
        if self._refresh_spinner.spinning:
            self._refresh_spinner.stop()
        if getattr(self, "_refresh_requested_by_user", False):
            self._refresh_requested_by_user = False
            stale = [AVAILABLE_NAMES.get(sid, sid) for sid in self.manager.needs_login]
            self.show_toast(f"Нужно войти заново: {', '.join(stale)}" if stale else "Главная обновлена ✓")

    def relogin(self, service_id: str) -> None:
        self.nav.button(1).setChecked(True)
        self.stack.setCurrentIndex(1)
        self.settings.relogin(service_id)

    def open_full_player(self) -> None:
        if self.player.current is None:
            self.show_toast("Включите трек, чтобы открыть большой плеер")
            return
        self.full_player.open_player()
        if self.snow.isVisible():
            self.snow.raise_()  # снег идёт и над большим плеером
        self.toast.raise_()

    def _random(self, pool: list) -> None:
        if not pool:
            self.show_toast("Пока не из чего собрать подборку: подключите сервис или лайкните треки")
            return
        self.player.play_queue(pool, 0, "random")
        from .widgets import tracks_word
        self.show_toast(f"Случайная подборка: {tracks_word(len(pool))}")

    # ---------- Мастерская, достижения, пасхалка ----------

    def _setup_workshop(self) -> None:
        from PyQt6.QtWidgets import QApplication
        from ..achievements import Achievements
        from .workshop_page import WorkshopPage
        self.achievements = Achievements(self.config)
        self.workshop_page = WorkshopPage(self, self.config, self.achievements, self.flow)
        index = self.stack.addWidget(self.workshop_page)
        assert index == WORKSHOP_PAGE, index
        from ..playlog import PlayLog
        from .wrapped_page import WrappedPage
        self.playlog = PlayLog(self.player)
        self.wrapped_page = WrappedPage(self, self.history, self.config)
        assert self.stack.addWidget(self.wrapped_page) == WRAPPED_PAGE
        from .radio_page import RadioPage
        self.radio_page = RadioPage(self.config)
        assert self.stack.addWidget(self.radio_page) == RADIO_PAGE
        self.radio_page.play_requested.connect(lambda tracks, i: self.player.play_queue(tracks, i, "radio"))
        self.playlists_page.smart_sources = (self.likes, self.history)
        # Выравнивание громкости, оверлей поверх игр, будильник
        from .alarm import Alarm, AlarmSection
        from .loudness import Loudness
        from .overlay import GameOverlay
        self.loudness = Loudness(self.player, self.config)
        self.overlay = GameOverlay(self.player, self.config)
        self.alarm = Alarm(self, self.config)
        lay = getattr(self.settings, "player_tab_lay", None)
        if lay is not None:
            item = lay.takeAt(lay.count() - 1)
            self._extra_player_settings(lay)
            self._alarm_section = AlarmSection(self.alarm, lay, self)
            if item is not None and item.spacerItem() is not None:
                lay.addStretch(1)
        self.achievements.unlocked.connect(self._on_achievement)
        self.player.started.connect(self.achievements.track_started)
        self.likes.liked.connect(lambda _t: self.achievements.set_value("likes", len(self.likes.entries)))
        self.full_player.lyrics_btn.toggled.connect(lambda on: on and self.achievements.bump("lyrics"))
        self._typed = ""
        QApplication.instance().installEventFilter(self)

    # ---------- Discord и обновления ----------

    def _setup_extras(self) -> None:
        from .. import discord_presence, workshop
        from .extras_section import ExtrasSection, Updates
        repo = workshop.repo(self.config)
        app_id = discord_presence.app_id(self.config)
        self.presence = discord_presence.DiscordPresence(app_id, f"https://github.com/{repo}/releases")
        if self.config.data.get("discord_on", True):
            self.presence.start()
        p = self.player
        p.started.connect(lambda track: self._presence_push())
        p.playing_changed.connect(lambda _on: self._presence_push())
        original = p.seek

        def seek(ms: int) -> None:   # перемотали — полоска времени в Discord тоже
            original(ms)
            QTimer.singleShot(300, self._presence_push)
        p.seek = seek
        self.updates = Updates(self, self.config, repo)
        self.extras = ExtrasSection(self.config, self.presence, self.updates, self._discord_toggle, self)
        lay = self.settings.data_tab.widget().layout()
        for i, card in enumerate(self.extras.cards):
            lay.insertWidget(i, card)
        # Пульт с телефона и Telegram-бот
        from ..remote import PhoneRemote, Remote
        from ..tgbot import TgBot
        from .remote_section import RemoteSection
        self.remote = Remote(self)
        self.phone_remote = PhoneRemote(self.remote, self.config)
        if self.config.data.get("remote_on"):
            self.phone_remote.start()
        self.tgbot = TgBot(self.remote, self.config)
        from ..mpris import Mpris
        self.mpris = Mpris(self.remote)   # Linux: медиакнопки и шторка системы
        self.mpris.start()
        self.remote_section = RemoteSection(self.config, self.phone_remote, self.tgbot, self)
        base = len(self.extras.cards)
        for i, card in enumerate(self.remote_section.cards):
            lay.insertWidget(base + i, card)
        if self.tgbot.token:
            self.tgbot.start()

    def _presence_push(self) -> None:
        if not self.config.data.get("discord_on", True):
            return
        p = self.player
        track = p.current
        playing = p.mp.playbackState() == p.mp.PlaybackState.PlayingState
        self.presence.update(track, playing, p.mp.position())

    def _discord_toggle(self, on: bool) -> None:
        self.config.data["discord_on"] = on
        self.config.save()
        if on:
            self.presence.start()
            self._presence_push()
        else:
            self.presence.clear()

    def _extra_player_settings(self, lay) -> None:
        """Вкладка «Плеер»: выравнивание громкости и оверлей поверх игр."""
        from PyQt6.QtGui import QFont
        from PyQt6.QtWidgets import QComboBox, QHBoxLayout, QLabel
        from .overlay import CORNERS, MODES
        from .theme import font
        from .widgets import Toggle, muted
        head = QLabel("Громкость и оверлей")
        head.setFont(font(17, QFont.Weight.Bold, display=True))
        lay.addSpacing(22)
        lay.addWidget(head)
        row = QHBoxLayout()
        note = muted("Выравнивание громкости: тихие треки чуть громче, громкие чуть тише — не нужно "
                     "дёргать ползунок между треками из разных сервисов.")
        note.setWordWrap(True)
        note.setFixedWidth(560)
        row.addWidget(note)
        row.addSpacing(20)
        loud = Toggle()
        loud.setChecked(self.loudness.on)
        loud.toggled.connect(self.loudness.set_on)
        row.addWidget(loud)
        row.addStretch(1)
        lay.addLayout(row)
        note = muted("Оверлей поверх игр: плашка с треком в углу экрана. Не мешает мыши и игре; горячая "
                     "клавиша — Ctrl+Alt+O. Виден в оконном и «полноэкранном оконном» режиме игры.")
        note.setWordWrap(True)
        note.setMaximumWidth(640)
        lay.addSpacing(10)
        lay.addWidget(note)
        row = QHBoxLayout()
        mode = QComboBox()
        for key, title in MODES:
            mode.addItem(title, key)
        mode.setCurrentIndex(max(0, mode.findData(self.overlay.mode)))
        mode.currentIndexChanged.connect(lambda _i: self.overlay.set_mode(mode.currentData()))
        corner = QComboBox()
        for key, title in CORNERS:
            corner.addItem(title, key)
        corner.setCurrentIndex(max(0, corner.findData(self.overlay.corner)))
        corner.currentIndexChanged.connect(lambda _i: (self.overlay.set_corner(corner.currentData()), self.overlay.flash()))
        row.addWidget(mode)
        row.addWidget(corner)
        row.addStretch(1)
        lay.addLayout(row)

    def _hotkey(self, action: str) -> None:
        p = self.player
        if action == "toggle":
            p.toggle()
        elif action == "next":
            p.next()
        elif action == "prev":
            p.prev()
        elif action in ("vol_up", "vol_down"):
            v = self.bar.volume.value() + (5 if action == "vol_up" else -5)
            self.bar.volume.setValue(max(0, min(100, v)))
            self.show_toast(f"Громкость {self.bar.volume.value()}%") if not self.isActiveWindow() else None
        elif action == "like":
            self.bar._toggle_like()
        elif action == "overlay":
            self.overlay.toggle()

    def quit_app(self) -> None:
        """Закрыться совсем (а не в трей) — нужно для обновления."""
        tray = getattr(self, "tray", None)
        if tray is not None:
            tray.quitting = True
        self.close()
        from PyQt6.QtWidgets import QApplication
        QApplication.quit()

    def _on_achievement(self, aid: str) -> None:
        from ..achievements import BY_ID
        from .workshop_page import Confetti
        self.show_toast(f"Достижение: {BY_ID[aid][1]}!")
        Confetti(self, 70)

    def apply_customization(self) -> None:
        """Настройки внешнего вида поменялись разом (набор из Мастерской): перерисовать всё."""
        self.flow.changed.emit()
        self.pers.changed.emit()
        self.apply_theme(themes.effective_theme(self.config.data), force=True)
        self.settings.update_theme_controls()

    def eventFilter(self, obj, event) -> bool:
        # Пасхалка: набрать «sonar» (или «сонар») где угодно, кроме полей ввода
        if event.type() == event.Type.KeyPress and hasattr(self, "achievements"):
            from PyQt6.QtWidgets import QAbstractSpinBox, QApplication, QLineEdit, QPlainTextEdit, QTextEdit
            focus = QApplication.focusWidget()
            text = event.text().lower()
            typing = isinstance(focus, (QLineEdit, QTextEdit, QPlainTextEdit, QAbstractSpinBox))
            target = obj is focus if focus is not None else obj is self   # каждое нажатие — один раз
            if text and target and not typing:
                self._typed = (self._typed + text)[-8:]
                if self._typed.endswith(("sonar", "сонар", "ыщтфк")):
                    self._typed = ""
                    from .workshop_page import Confetti
                    Confetti(self, 220)
                    self.show_toast("Ты нашёл пасхалку! Sonar любит тебя")
                    self.achievements.bump("egg")
        return super().eventFilter(obj, event)

    def show_toast(self, text: str) -> None:
        self.toast.setText(text)
        self.toast.adjustSize()
        self.toast.raise_()
        self._toast_anim.show_at(self._toast_pos())
        self._toast_timer.start()

    def _toast_pos(self):
        from PyQt6.QtCore import QPoint
        x = 72 + (self.width() - 72 - self.toast.width()) // 2
        y = self.height() - self.bar.height() - self.toast.height() - 18
        return QPoint(x, y)

    def _place_toast(self) -> None:
        self.toast.move(self._toast_pos())

    def keyPressEvent(self, event) -> None:
        from .extras import handle_key
        if not handle_key(self, event):
            super().keyPressEvent(event)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self.toast.isVisible():
            self._place_toast()

    def reset_all(self, with_downloads: bool) -> None:
        """Удаляет данные и перезапускает Sonar с чистого листа."""
        import shutil
        from PyQt6.QtCore import QProcess
        from ..config import config_dir
        # Ничего не должно записаться обратно: ни при закрытии, ни из таймеров, ни из фоновых
        # потоков, обновляющих токены сервисов.
        for store in (self.config, self.history, self.likes, self.playlists, self.unavailable):
            store.frozen = True
        self.player.mp.stop()
        data = config_dir()
        keep = None if with_downloads else self.downloads.dir.resolve()
        # В портативной сборке загрузки лежат внутри data — без галочки их не трогаем
        for item in data.iterdir() if data.exists() else []:
            if keep is not None and item.resolve() == keep:
                continue
            if item.is_dir():
                shutil.rmtree(item, ignore_errors=True)
            else:
                item.unlink(missing_ok=True)
        if with_downloads:
            shutil.rmtree(self.downloads.dir, ignore_errors=True)
        args = sys.argv[1:] if getattr(sys, "frozen", False) else sys.argv
        QProcess.startDetached(sys.executable, args)
        QApplication.instance().quit()

    def closeEvent(self, event) -> None:
        tray = getattr(self, "tray", None)
        if (tray is not None and self.pers.get("close_to_tray") and not tray.quitting
                and tray.icon.isVisible()):
            event.ignore()   # «Сворачивать в трей при закрытии»: прячемся, музыка играет дальше
            self.hide()
            if not self.config.data.get("tray_hint_shown"):
                self.config.data["tray_hint_shown"] = True
                tray.icon.showMessage("Sonar работает в трее", "Музыка играет дальше. Выход — в меню значка.",
                                      tray.icon.icon(), 4000)
            return
        if tray is not None:
            tray.icon.hide()
        self.config.data["volume"] = self.bar.volume.value()
        self.config.data["window_geometry"] = bytes(self.saveGeometry().toBase64()).decode("ascii")
        session = self.player.snapshot()   # «продолжить с места» при следующем запуске
        if session:
            self.config.data["session"] = session
        self.config.save()   # после сброса хранилища «заморожены»: save() ничего не пишет
        self.history.save()
        self.likes.save()
        self.playlists.save()
        self.unavailable.save()
        self.mini.close()
        if getattr(self, "presence", None) is not None:
            self.presence.stop()   # убрать статус из Discord
        if getattr(self, "playlog", None) is not None:
            self.playlog.flush()
        if getattr(self, "loudness", None) is not None:
            self.loudness.flush()
        if getattr(self, "overlay", None) is not None:
            self.overlay.close()
        for name in ("phone_remote", "tgbot", "mpris"):
            obj = getattr(self, name, None)
            if obj is not None:
                obj.stop()
        if self.video_window is not None:
            self.video_window.close()
        super().closeEvent(event)

    def _dark_title_bar(self) -> None:
        if sys.platform != "win32":
            return
        try:
            import ctypes
            value = ctypes.c_int(1 if themes.current().get("dark", True) else 0)
            for attr in (20, 19):  # DWMWA_USE_IMMERSIVE_DARK_MODE (новые и старые сборки Win10)
                if ctypes.windll.dwmapi.DwmSetWindowAttribute(
                        int(self.winId()), attr, ctypes.byref(value), ctypes.sizeof(value)) == 0:
                    break
        except Exception:
            pass
