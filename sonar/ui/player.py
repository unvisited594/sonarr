import random

from PyQt6.QtCore import QObject, QSize, Qt, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QFont, QIcon
from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QSlider, QToolButton, QVBoxLayout, QWidget

import logging

from ..logs import host
from .anim import pop
from ..services.base import UnavailableError
from ..workers import run_async
from . import icons
from .theme import C, font
from .widgets import Cover, fmt_time, muted

log = logging.getLogger("sonar.player")
JUMP_SLACK_MS = 2500     # насколько позиция может обогнать реальные часы (буферизация, округления)
MAX_FAILS = 5
MAX_RECOVERIES = 3       # сколько раз за трек переподключаемся после обрыва, прежде чем пропустить
EARLY_END_MS = 4000      # «конец трека» раньше этого запаса до конца — на самом деле обрыв


class Player(QObject):
    track_changed = pyqtSignal(object)
    playing_changed = pyqtSignal(bool)
    position_changed = pyqtSignal(int, int)
    loading_changed = pyqtSignal(bool)
    message = pyqtSignal(str)
    track_unavailable = pyqtSignal(object)
    started = pyqtSignal(object)  # трек реально пошёл в воспроизведение
    repeat_changed = pyqtSignal(bool)
    stopped_after_track = pyqtSignal()   # таймер сна «до конца трека» сработал
    output_changed = pyqtSignal()        # звук пошёл в другое устройство (наушники, колонки)

    def __init__(self, manager, volume: int = 70) -> None:
        super().__init__()
        self.manager = manager
        self.mp = QMediaPlayer(self)
        self.out = QAudioOutput(self)
        self.mp.setAudioOutput(self.out)
        self.out.setVolume(volume / 100)
        # Куда выводить звук: "" — как в системе, иначе описание устройства. Подключили или
        # отключили наушники — переключаемся сами (на выбранные, когда они вернутся).
        self.device_pref = ""
        from PyQt6.QtMultimedia import QMediaDevices
        self._devices = QMediaDevices(self)
        self._devices.audioOutputsChanged.connect(self._apply_output)
        self.user_volume = volume / 100   # громкость с ползунка: к ней возвращаемся после затуханий
        self.queue: list = []
        self.index = -1
        self.context: str | None = None
        self._req = 0
        self._fails = 0
        self.repeat = False
        self._restored_pos = None
        self.stop_after_track = False   # таймер сна «до конца трека»
        self._restored_pos: int | None = None   # позиция из прошлого запуска
        self.fallback_enabled = True     # не играет — искать в других сервисах
        self._fallback_pending = False
        self._last_pos = 0              # где играли перед обрывом
        self._pos_clock = 0.0           # когда запомнили _last_pos (monotonic)
        self._recoveries = 0
        self._handled_error_req = -1    # на один обрыв Qt шлёт пачку ошибок — обрабатываем одну
        self._resume_at: int | None = None
        self.mp.playbackStateChanged.connect(
            lambda s: self.playing_changed.emit(s == QMediaPlayer.PlaybackState.PlayingState))
        self.mp.positionChanged.connect(self._on_position)
        self.mp.mediaStatusChanged.connect(self._on_status)
        self.mp.errorOccurred.connect(self._on_error)

    @property
    def current(self):
        return self.queue[self.index] if 0 <= self.index < len(self.queue) else None

    @property
    def is_playing(self) -> bool:
        return self.mp.playbackState() == QMediaPlayer.PlaybackState.PlayingState

    def duration(self) -> int:
        return self.mp.duration() or (self.current.duration_ms if self.current else 0)

    def play_queue(self, tracks: list, index: int = 0, context: str | None = None) -> None:
        self.queue, self.context, self._fails = list(tracks), context, 0
        self._start(index)

    def _start(self, index: int) -> None:
        if not 0 <= index < len(self.queue):
            return
        self.index = index
        track = self.queue[index]
        self._req += 1
        req = self._req
        self._last_pos = 0
        self._pos_clock = 0.0
        self._recoveries = 0
        self._resume_at = None
        self._fallback_pending = False   # переключились на другой трек — прежний поиск не в счёт
        log.info("▶ трек %s/%s: %s — %s (%s мс, очередь %s/%s, %s)", track.service_id, track.id,
                 track.artist, track.title, track.duration_ms, index + 1, len(self.queue), self.context)
        self.mp.stop()
        self.track_changed.emit(track)
        if not track.playable:
            self._skip(req, f"«{track.title}» недоступен для прослушивания")
            return
        local = self._local_file(track)
        if local:  # скачанный или уже закешированный трек: из файла, без сети
            log.info("источник: файл %s", local.rsplit("/", 1)[-1].rsplit("\\", 1)[-1])
            self.loading_changed.emit(False)
            self.mp.setSource(QUrl.fromLocalFile(local))
            self.mp.play()
            self.started.emit(track)
            self._prefetch_next()
            return
        service = self.manager.get(track.service_id)
        if service is None:
            self._skip(req, "Сервис этого трека отключён")
            return
        self.loading_changed.emit(True)
        resolve = self._resolve_cached if getattr(service, "download_before_play", False) else self._resolve
        run_async(resolve, service, track,
                  on_done=lambda res: self._resolved(req, service, track, res),
                  on_error=lambda err: self._skip(req, f"«{track.title}»: {err}"))

    @staticmethod
    def _local_file(track) -> str | None:
        import os
        from ..downloads import downloads
        from ..stream_cache import cache
        path = track.raw.get("local_file")
        if not path:
            store = downloads()
            if store is not None and track.service_id == "navidrome" and store.has(track.id):
                path = str(store.local_path(track.id))
        if not path and cache().has(track):   # уже скачан во временный кеш
            path = str(cache().path_for(track))
        return path if path and os.path.exists(path) else None

    @staticmethod
    def _resolve_cached(service, track):
        """Скачать трек целиком во временный кеш и играть из файла: обрываться нечему."""
        from ..stream_cache import cache
        try:
            return "ok", QUrl.fromLocalFile(cache().fetch(service, track)).toString()
        except UnavailableError as exc:
            return "unavailable", str(exc)

    def _prefetch_next(self) -> None:
        """Пока играет трек, заранее скачиваем следующий — переход будет мгновенным."""
        from ..stream_cache import cache
        nxt = self.index + 1
        if not 0 <= nxt < len(self.queue):
            return
        track = self.queue[nxt]
        service = self.manager.get(track.service_id)
        if service is None or not getattr(service, "download_before_play", False) or cache().has(track) \
                or not track.playable:
            return
        log.info("подкачиваю следующий: %s/%s", track.service_id, track.id)
        run_async(cache().fetch, service, track,
                  on_error=lambda err: log.warning("подкачка не удалась: %s", err))

    @staticmethod
    def _resolve(service, track):
        """Отличаем «трек недоступен» от сбоя: только первое запоминаем."""
        try:
            return "ok", service.stream_url(track)
        except UnavailableError as exc:
            return "unavailable", str(exc)

    def _resolved(self, req: int, service, track, result) -> None:
        kind, value = result
        if kind == "unavailable":
            service.mark_unavailable(track.id)
            track.playable = False
            self.track_unavailable.emit(track)
            self._skip(req, f"«{track.title}» недоступен: {value}")
            return
        if req != self._req:
            return
        url = value
        log.info("источник: %s", "файл" if url.startswith("file:") else host(url))
        self.loading_changed.emit(False)
        self.mp.setSource(QUrl(url))
        self.mp.play()
        self.started.emit(track)
        self._prefetch_next()

    def _on_position(self, pos: int) -> None:
        # Запоминаем только реальное продвижение. При обрыве Qt может перед «концом» выставить
        # позицию сразу в конец трека — такой скачок не считаем, иначе обрыв выглядит как конец.
        # Мерило — настоящие часы: проигрывание не может продвинуться быстрее, чем прошло времени
        # (так подвисший на пару секунд интерфейс не принимается за скачок).
        import time as _time
        now = _time.monotonic()
        elapsed_ms = (now - self._pos_clock) * 1000 if self._pos_clock else 0
        if self._resume_at is None and pos - self._last_pos <= elapsed_ms + JUMP_SLACK_MS:
            self._last_pos = pos
            self._pos_clock = now
        elif self._resume_at is None:
            log.info("скачок позиции %s → %s мс за %.0f мс не учтён", self._last_pos, pos, elapsed_ms)
        self.position_changed.emit(pos, self.duration())

    def _recover(self) -> bool:
        """Обрыв посреди трека: заново получаем ссылку (у Яндекса они одноразовые) и продолжаем
        с того же места. False — переподключаться больше нельзя, пора пропускать."""
        track = self.current
        if track is None or self._recoveries >= MAX_RECOVERIES or self._last_pos <= 0:
            return False
        self._recoveries += 1
        req = self._req
        resume = self._last_pos
        log.warning("переподключение %s/%s: продолжаю с %s мс", self._recoveries, MAX_RECOVERIES, resume)
        local = self._local_file(track)
        if local:
            self._resume_at = resume
            self.mp.setSource(QUrl.fromLocalFile(local))
            self.mp.play()
            return True
        service = self.manager.get(track.service_id)
        if service is None:
            return False
        self.loading_changed.emit(True)

        def done(result):
            if req != self._req:
                return
            kind, value = result
            if kind != "ok":
                self._skip(req, f"«{track.title}» недоступен: {value}")
                return
            self.loading_changed.emit(False)
            self._resume_at = resume
            self._handled_error_req = -1   # новый источник: его ошибки снова обрабатываем
            self.mp.setSource(QUrl(value))
            self.mp.play()

        run_async(self._resolve, service, track, on_done=done,
                  on_error=lambda err: self._skip(req, f"«{track.title}»: {err}"))
        return True

    def _skip(self, req: int, reason: str) -> None:
        """Трек не играет: сначала ищем его же в других сервисах, и только потом пропускаем."""
        if req != self._req:
            return
        track = self.current
        if (self.fallback_enabled and track is not None and not track.raw.get("fallback_from")
                and not self._fallback_pending):
            from ..services.fallback import find_alternative
            self._fallback_pending = True
            self.loading_changed.emit(True)
            log.info("ищу «%s» в других сервисах (%s)", track.title, reason)
            run_async(find_alternative, self.manager, track,
                      on_done=lambda res: self._fallback_done(req, track, reason, res),
                      on_error=lambda err: self._fallback_done(req, track, reason, None))
            return
        self._skip_now(req, reason)

    def _fallback_done(self, req: int, track, reason: str, result) -> None:
        self._fallback_pending = False
        if req != self._req:
            return
        if not result:
            self._skip_now(req, reason)
            return
        svc, alt = result
        from ..services import AVAILABLE
        alt.raw = {**(alt.raw or {}), "fallback_from": [track.service_id, track.id]}   # без цепочек
        self.queue[self.index] = alt
        from ..services.base import name_from, name_in
        origin = name_in(AVAILABLE[track.service_id]) if track.service_id in AVAILABLE else track.service_id
        self.message.emit(f"«{track.title}» не играет в {origin} — включаю из {name_from(svc)}")
        self._start(self.index)

    def _skip_now(self, req: int, reason: str) -> None:
        if req != self._req:
            return
        log.warning("пропуск трека: %s", reason)
        self.loading_changed.emit(False)
        self._fails += 1
        if self._fails >= MAX_FAILS:
            self.message.emit("Несколько треков подряд не запустились, воспроизведение остановлено")
            return
        self.message.emit(reason)
        QTimer.singleShot(400, lambda: req == self._req and self.next())

    def _on_status(self, status) -> None:
        log.info("статус: %s (позиция %s / %s мс)", status.name, self._last_pos, self.mp.duration())
        if status in (QMediaPlayer.MediaStatus.LoadedMedia, QMediaPlayer.MediaStatus.BufferedMedia) \
                and self._resume_at is not None:
            import time as _time
            pos, self._resume_at = self._resume_at, None
            self.mp.setPosition(pos)   # продолжаем с места обрыва
            self._last_pos = pos
            self._pos_clock = _time.monotonic()
        if status == QMediaPlayer.MediaStatus.BufferedMedia:
            self._fails = 0
        elif status == QMediaPlayer.MediaStatus.EndOfMedia:
            total = max(self.current.duration_ms if self.current else 0, self.mp.duration() or 0)
            if total and self._last_pos < total - EARLY_END_MS and self._recover():
                return   # «конец» раньше времени — это обрыв соединения, а не конец трека
            if self.stop_after_track:
                self.stop_after_track = False
                self.stopped_after_track.emit()
            elif self.repeat and self.current is not None:
                self.mp.setPosition(0)  # тот же трек с начала, очередь не двигается
                self.mp.play()
            else:
                self.next()

    def set_repeat(self, on: bool) -> None:
        if on != self.repeat:
            self.repeat = on
            self.repeat_changed.emit(on)

    def _on_error(self, _error, text: str) -> None:
        if self._handled_error_req == self._req:
            return   # та же поломка: Qt присылает её пачкой
        self._handled_error_req = self._req
        log.warning("ошибка плеера: %s (%s), позиция %s мс", text, _error.name, self._last_pos)
        if self._recover():
            return
        self._skip(self._req, f"Ошибка воспроизведения: {text}")

    def next(self) -> None:
        if self.index + 1 < len(self.queue):
            self._start(self.index + 1)
        elif self.context == "wave" and self.queue:
            random.shuffle(self.queue)  # волна не заканчивается
            self._start(0)

    def prev(self) -> None:
        if self.mp.position() > 3000 or self.index <= 0:
            self.mp.setPosition(0)
        else:
            self._start(self.index - 1)

    # ---------- мягкая пауза ----------
    FADE_MS = 220

    def _volume_anim(self):
        from PyQt6.QtCore import QVariantAnimation
        if getattr(self, "_vanim", None) is None:
            self._vanim = QVariantAnimation(self)
            self._vanim.setDuration(self.FADE_MS)
            self._vanim.valueChanged.connect(lambda v: self.out.setVolume(float(v)))
            self._vanim.finished.connect(self._fade_done)
            self._fade_to_pause = False
        return self._vanim

    def _fade_done(self) -> None:
        if self._fade_to_pause:
            self._fade_to_pause = False
            self.mp.pause()
            self.out.setVolume(self.user_volume)   # громкость — как на ползунке, к следующему старту

    def set_user_volume(self, value: float) -> None:
        """Громкость с ползунка: её и восстанавливаем после затуханий."""
        anim = self._volume_anim()
        self.user_volume = value
        if anim.state() != anim.State.Running:
            self.out.setVolume(value)

    def toggle(self) -> None:
        anim = self._volume_anim()
        if self.is_playing and not self._fade_to_pause:
            # громкость плавно гаснет, пауза — в конце: без щелчка
            now = float(anim.currentValue()) if anim.state() == anim.State.Running else self.user_volume
            self._fade_to_pause = True
            anim.stop()
            anim.setStartValue(now)
            anim.setEndValue(0.0)
            anim.start()
            return
        self._fade_to_pause = False
        anim.stop()
        if self.mp.source().isEmpty():
            if self._restored_pos is not None and self.current is not None:   # «продолжить с места»
                pos, self._restored_pos = self._restored_pos, None
                self._start(max(self.index, 0))
                self._resume_at = pos
            else:
                self._start(max(self.index, 0))
            self.out.setVolume(self.user_volume)
            return
        self.out.setVolume(0.0)
        self.mp.play()
        anim.setStartValue(0.0)
        anim.setEndValue(self.user_volume)
        anim.start()

    # ---------- продолжить с места ----------

    def snapshot(self) -> dict | None:
        """Что сохранить при выходе: очередь (до 200 треков вокруг текущего), трек и позиция."""
        from ..library import track_to_dict
        if self.current is None or not self.queue:
            return None
        start = max(0, self.index - 50)
        part = self.queue[start:start + 200]
        return {"queue": [track_to_dict(t) for t in part], "index": self.index - start,
                "position": int(self.mp.position()), "context": self.context}

    def restore(self, data: dict | None) -> bool:
        """Восстановить очередь без воспроизведения: «играть» продолжит с той же секунды."""
        from ..library import track_from_dict
        if not data or not data.get("queue"):
            return False
        tracks = [track_from_dict(d, self.manager) for d in data["queue"]]
        index = min(max(int(data.get("index", 0)), 0), len(tracks) - 1)
        self.queue, self.index, self.context = tracks, index, data.get("context", "")
        self._restored_pos = int(data.get("position") or 0)
        self.track_changed.emit(tracks[index])
        return True

    def seek(self, ms: int) -> None:
        import time as _time
        self._last_pos = ms   # перемотка пользователем — законный скачок
        self._pos_clock = _time.monotonic()
        self.mp.setPosition(ms)

    # ---------- устройство вывода ----------

    def set_output(self, description: str) -> None:
        self.device_pref = description or ""
        self._apply_output()

    def _apply_output(self) -> None:
        from PyQt6.QtMultimedia import QMediaDevices
        from .audio_devices import find_device
        dev = find_device(self.device_pref) if self.device_pref else None
        if dev is None:   # выбранного сейчас нет — играем туда, куда система
            dev = QMediaDevices.defaultAudioOutput()
        try:
            if self.out.device() != dev:
                self.out.setDevice(dev)
        except AttributeError:
            pass
        self.output_changed.emit()

    def follows_system(self) -> bool:
        return not self.device_pref or not self._pref_present()

    def _pref_present(self) -> bool:
        from .audio_devices import find_device
        return find_device(self.device_pref) is not None

    def output_description(self) -> str:
        try:
            return self.out.device().description()
        except AttributeError:
            return ""

    def set_volume(self, value: int) -> None:
        self.set_user_volume(value / 100)   # с учётом идущего затухания мягкой паузы


class SleepTimer(QObject):
    """Таймер сна: по истечении времени громкость за несколько секунд стихает, плеер встаёт
    на паузу, громкость возвращается. Вариант «до конца трека» — пауза после текущего трека."""
    changed = pyqtSignal()
    fired = pyqtSignal()

    FADE_MS = 8000

    def __init__(self, player: Player) -> None:
        super().__init__()
        self.player = player
        self.deadline = None        # время окончания (monotonic, сек)
        self.until_track_end = False
        self._timer = QTimer(self, singleShot=True)
        self._timer.timeout.connect(self._fade)
        self._fade_timer = QTimer(self, interval=100)
        self._fade_timer.timeout.connect(self._fade_step)
        self._fade_left = 0
        self._volume = 1.0
        player.stopped_after_track.connect(self._finish)

    @property
    def active(self) -> bool:
        return self.deadline is not None or self.until_track_end

    def remaining_minutes(self) -> int | None:
        import time as _t
        if self.deadline is None:
            return None
        return max(0, int((self.deadline - _t.monotonic() + 59) // 60))

    def start(self, minutes: int) -> None:
        import time as _t
        self.cancel(emit=False)
        self.deadline = _t.monotonic() + minutes * 60
        self._timer.start(minutes * 60 * 1000)
        self.changed.emit()

    def start_until_track_end(self) -> None:
        self.cancel(emit=False)
        self.until_track_end = True
        self.player.stop_after_track = True
        self.changed.emit()

    def cancel(self, emit: bool = True) -> None:
        self._timer.stop()
        if self._fade_timer.isActive():
            self._fade_timer.stop()
            self.player.out.setVolume(self._volume)
        self.deadline = None
        self.until_track_end = False
        self.player.stop_after_track = False
        if emit:
            self.changed.emit()

    def _fade(self) -> None:
        self._volume = self.player.user_volume   # с ползунка, а не промежуточная громкость затухания
        self._fade_left = self.FADE_MS
        self._fade_timer.start()

    def _fade_step(self) -> None:
        self._fade_left -= self._fade_timer.interval()
        if self._fade_left <= 0:
            self._fade_timer.stop()
            self._finish()
            return
        self.player.out.setVolume(self._volume * self._fade_left / self.FADE_MS)

    def _finish(self) -> None:
        if self.player.is_playing:
            self.player.mp.pause()
        if self.deadline is not None:      # громкость возвращаем: утром музыка не должна быть тихой
            self.player.out.setVolume(self._volume)
        self.deadline = None
        self.until_track_end = False
        self.changed.emit()
        self.fired.emit()


class PlayerBar(QFrame):
    video_requested = pyqtSignal(object)
    expand_requested = pyqtSignal()

    def __init__(self, player: Player, volume: int, likes=None, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("playerBar")
        self.setFixedHeight(88)
        self.player = player
        self.likes = likes
        self._dragging = False

        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 12, 22, 12)
        lay.setSpacing(16)

        left = QWidget()
        left.setFixedWidth(300)
        ll = QHBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.setSpacing(12)
        self.cover = Cover(56, 10)
        self.cover.setCursor(Qt.CursorShape.PointingHandCursor)
        self.cover.setToolTip("Открыть большой плеер")
        self.cover.clicked.connect(self.expand_requested)
        ll.addWidget(self.cover)
        info = QVBoxLayout()
        info.setSpacing(2)
        info.addStretch(1)
        self.title = QLabel("Ничего не играет")
        self.title.setCursor(Qt.CursorShape.PointingHandCursor)
        self.title.installEventFilter(self)
        self.title.setFont(font(14, QFont.Weight.DemiBold))
        from .widgets import ArtistLabel
        self.artist = ArtistLabel("Выберите трек на главной")
        info.addWidget(self.title)
        info.addWidget(self.artist)
        info.addStretch(1)
        ll.addLayout(info, 1)
        lay.addWidget(left)

        center = QVBoxLayout()
        center.setSpacing(4)
        buttons = QHBoxLayout()
        buttons.setSpacing(14)
        buttons.addStretch(1)
        self.repeat_btn = self._ctrl("repeat", "Повторять трек", lambda: None)
        self.repeat_btn.setCheckable(True)
        self.repeat_btn.toggled.connect(player.set_repeat)
        player.repeat_changed.connect(self._sync_repeat)
        buttons.addWidget(self.repeat_btn)
        self.prev_btn = self._ctrl("prev", "Предыдущий", player.prev)
        self.play_btn = self._ctrl("play", "Играть / пауза", player.toggle, main=True)
        self.play_btn.clicked.connect(lambda _=False, b=self.play_btn: pop(b))
        self.next_btn = self._ctrl("next", "Следующий", player.next)
        for b in (self.prev_btn, self.play_btn, self.next_btn):
            buttons.addWidget(b)
        buttons.addSpacing(32 + 14)  # уравновешиваем «повтор» слева: «играть» по центру ползунка
        buttons.addStretch(1)
        center.addLayout(buttons)
        progress = QHBoxLayout()
        progress.setSpacing(10)
        self.pos_lbl = muted("0:00")
        self.dur_lbl = muted("0:00")
        for lbl in (self.pos_lbl, self.dur_lbl):
            lbl.setFont(font(12))
            lbl.setFixedWidth(40)
        self.pos_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.sliderPressed.connect(lambda: setattr(self, "_dragging", True))
        self.slider.sliderReleased.connect(self._seek)
        progress.addWidget(self.pos_lbl)
        progress.addWidget(self.slider, 1)
        progress.addWidget(self.dur_lbl)
        center.addLayout(progress)
        lay.addLayout(center, 1)

        right = QHBoxLayout()
        right.setSpacing(8)
        self.video_btn = self._ctrl("video", "Смотреть клип",
                                    lambda: self.player.current and self.video_requested.emit(self.player.current))
        self.video_btn.setEnabled(False)
        self.like_btn = self._ctrl("heart", "Добавить в мои лайки", self._toggle_like)
        self.like_btn.clicked.connect(lambda _=False, b=self.like_btn: pop(b))
        self.like_btn.setEnabled(False)
        self.queue_btn = self._ctrl("queue", "Очередь воспроизведения", self._queue_menu)
        right.addWidget(self.queue_btn)
        self.sleep_btn = self._ctrl("moon", "Таймер сна", self._sleep_menu)
        self.sleep_btn.setCheckable(True)
        right.addWidget(self.sleep_btn)
        self.sleep = None   # SleepTimer, задаёт главное окно
        self.playlist_btn = self._ctrl("plus", "Добавить в плейлист", self._playlist_menu)
        self.playlist_btn.setEnabled(False)
        right.addWidget(self.playlist_btn)
        right.addWidget(self.like_btn)
        right.addWidget(self.video_btn)
        right.addSpacing(6)
        self.device_btn = QToolButton()
        self.device_btn.setObjectName("ctrl")
        self.device_btn.setFixedSize(32, 32)
        self.device_btn.setIconSize(QSize(22, 22))
        self.device_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.device_btn.clicked.connect(self._device_panel)
        self.device_btn.hide()   # появится, когда главное окно передаст настройки устройств
        right.addWidget(self.device_btn)
        self.eq_btn = self._ctrl("eq", "Эквалайзер", self._eq_panel)
        self.eq_btn.setCheckable(True)
        self.eq_btn.hide()   # появится, когда главное окно передаст эквалайзер
        right.addWidget(self.eq_btn)
        self._eq = None
        self._device_look = None
        player.output_changed.connect(self.update_device_button)
        vol_icon = QLabel()
        self._vol_icon = vol_icon
        vol_icon.setPixmap(icons.pixmap("volume", C("side_muted"), 20))
        self.volume = QSlider(Qt.Orientation.Horizontal)
        self.volume.setRange(0, 100)
        self.volume.setValue(volume)
        self.volume.setFixedWidth(110)
        self.volume.valueChanged.connect(player.set_volume)
        right.addWidget(vol_icon)
        right.addWidget(self.volume)
        rw = QWidget()
        rw.setLayout(right)
        rw.setFixedWidth(360)
        lay.addWidget(rw)

        player.track_changed.connect(self._on_track)
        player.playing_changed.connect(self._on_playing)
        player.position_changed.connect(self._on_position)
        player.loading_changed.connect(self._on_loading)

    def _on_playing(self, on: bool) -> None:
        self.play_btn.setIcon(icons.icon("pause" if on else "play", C("on_accent")))

    def _sync_repeat(self, on: bool) -> None:
        if self.repeat_btn.isChecked() != on:
            self.repeat_btn.setChecked(on)
        self.repeat_btn.setToolTip("Повтор включён: трек будет играть снова" if on else "Повторять трек")

    def apply_theme(self) -> None:
        self._on_playing(self.player.is_playing)
        for btn, name in ((self.prev_btn, "prev"), (self.next_btn, "next"), (self.video_btn, "video"),
                          (self.playlist_btn, "plus")):
            btn.setIcon(icons.icon(name, C("side_text")))
        self.sleep_btn.setIcon(icons.icon("moon", C("side_muted"), C("side_text")))
        self.queue_btn.setIcon(icons.icon("queue", C("side_text")))
        self.repeat_btn.setIcon(icons.icon("repeat", C("side_muted"), C("side_text")))
        if hasattr(self, "eq_btn"):
            self.eq_btn.setIcon(icons.icon("eq", C("side_muted"), C("side_text")))
        self.update_like()
        self._vol_icon.setPixmap(icons.pixmap("volume", C("side_muted"), 20))

    # ---------- наушники и колонки ----------

    def set_device_look(self, look, config) -> None:
        self._device_look = look
        self._device_config = config
        self.device_btn.show()
        self.update_device_button()

    def update_device_button(self) -> None:
        if self._device_look is None:
            return
        from .audio_devices import KIND_TITLES, device_pixmap
        name = self.player.output_description()
        image = self._device_look.image(name)
        kind = self._device_look.kind(name)
        self.device_btn.setIcon(QIcon(device_pixmap(kind, 22, "#ff7a00", image, card=bool(image))))
        what = "своя картинка" if image else KIND_TITLES.get(kind, "").lower()
        self.device_btn.setToolTip(f"Звук идёт в: {name or 'устройство по умолчанию'}"
                                   f"{f' ({what})' if what else ''}\nНажмите, чтобы сменить наушники")

    def _device_panel(self) -> None:
        from .audio_devices import DevicePanel
        panel = DevicePanel(self.player, self._device_look, self)
        panel.chosen.connect(self._choose_device)
        panel.looks_changed.connect(self.update_device_button)
        panel.adjustSize()
        pos = self.device_btn.mapToGlobal(self.device_btn.rect().topRight())
        panel.move(pos.x() - panel.width(), pos.y() - panel.height() - 8)
        panel.show()

    def _choose_device(self, description: str) -> None:
        self.player.set_output(description)
        self._device_config.data["audio_device"] = description
        self._device_config.save()

    # ---------- эквалайзер ----------

    def set_equalizer(self, eq) -> None:
        self._eq = eq
        self.eq_btn.show()
        eq.changed.connect(self._eq_changed)
        self._eq_changed()

    def _eq_changed(self) -> None:
        on = self._eq is not None and self._eq.on
        self.eq_btn.setChecked(on)
        self.eq_btn.setToolTip("Эквалайзер: включён" if on else "Эквалайзер")

    def _eq_panel(self) -> None:
        from .equalizer import EqPanel
        self._eq_changed()   # кнопка-флажок: состояние показывает эквалайзер, а не щелчок
        panel = EqPanel(self._eq, self)
        panel.adjustSize()
        pos = self.eq_btn.mapToGlobal(self.eq_btn.rect().topRight())
        panel.move(max(0, pos.x() - panel.width()), pos.y() - panel.height() - 8)
        panel.show()

    def _ctrl(self, name, tip, slot, main=False) -> QToolButton:
        b = QToolButton()
        b.setObjectName("ctrlMain" if main else "ctrl")
        b.setFixedSize(40, 40) if main else b.setFixedSize(32, 32)
        b.setIconSize(QSize(20, 20) if main else QSize(18, 18))
        dim = name in ("repeat", "moon", "eq")   # переключатели: приглушены, пока выключены
        b.setIcon(icons.icon(name, C("on_accent") if main else (C("side_muted") if dim else C("side_text")),
                             None if main or not dim else C("side_text")))
        b.setToolTip(tip)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.clicked.connect(slot)
        return b

    def eventFilter(self, obj, event) -> bool:
        if obj is self.title and event.type() == event.Type.MouseButtonRelease:
            self.expand_requested.emit()
        return False

    def _queue_menu(self) -> None:
        from .extras import queue_menu
        queue_menu(self.window(), self.queue_btn)

    def set_sleep_timer(self, sleep) -> None:
        self.sleep = sleep
        sleep.changed.connect(self.update_sleep)
        self._sleep_refresh = QTimer(self, interval=30_000)   # «осталось N мин» в подсказке
        self._sleep_refresh.timeout.connect(self.update_sleep)
        self._sleep_refresh.start()
        self.update_sleep()

    def update_sleep(self) -> None:
        sleep = self.sleep
        on = bool(sleep and sleep.active)
        self.sleep_btn.setChecked(on)
        if not on:
            self.sleep_btn.setToolTip("Таймер сна")
        elif sleep.until_track_end:
            self.sleep_btn.setToolTip("Таймер сна: пауза после этого трека")
        else:
            self.sleep_btn.setToolTip(f"Таймер сна: осталось {sleep.remaining_minutes()} мин")

    def _sleep_menu(self) -> None:
        from PyQt6.QtWidgets import QMenu
        self.update_sleep()  # кнопка checkable: клик переключил её — вернём реальное состояние
        if self.sleep is None:
            return
        menu = QMenu(self)
        if self.sleep.active:
            menu.addAction(self.sleep_btn.toolTip().replace("Таймер сна: ", "Сейчас: ")).setEnabled(False)
            menu.addAction("Выключить таймер").triggered.connect(self.sleep.cancel)
            menu.addSeparator()
        for minutes in (15, 30, 45, 60, 90):
            menu.addAction(f"Через {minutes} мин").triggered.connect(lambda _=False, m=minutes: self.sleep.start(m))
        menu.addAction("После этого трека").triggered.connect(self.sleep.start_until_track_end)
        menu.exec(self.sleep_btn.mapToGlobal(self.sleep_btn.rect().topLeft()))

    def _playlist_menu(self) -> None:
        from PyQt6.QtWidgets import QMenu
        from .widgets import add_to_playlist_menu
        track = self.player.current
        if track is None:
            return
        menu = QMenu(self)
        add_to_playlist_menu(menu, track, self, as_submenu=False)
        menu.exec(self.playlist_btn.mapToGlobal(self.playlist_btn.rect().topLeft()))

    def _toggle_like(self) -> None:
        track = self.player.current
        if track is not None and self.likes is not None:
            self.likes.toggle(track)  # иконку обновит сигнал changed

    def update_like(self) -> None:
        track = self.player.current
        liked = bool(track and self.likes and self.likes.contains(track))
        self.like_btn.setEnabled(track is not None and self.likes is not None)
        self.playlist_btn.setEnabled(track is not None)
        self.like_btn.setIcon(icons.icon("heart_fill" if liked else "heart", C("side_text")))
        self.like_btn.setToolTip("Убрать из моих лайков" if liked else "Добавить в мои лайки")

    def _on_track(self, track) -> None:
        from .widgets import artist_target
        self.artist.set_target(*artist_target(track))
        self.update_like()
        service = self.player.manager.get(track.service_id)
        self.video_btn.setEnabled(bool(service and service.supports_video))
        self.cover.set_url(track.artwork_url)
        self.title.setText(self.title.fontMetrics().elidedText(
            track.title, Qt.TextElideMode.ElideRight, 220))
        self.title.setToolTip(track.title)
        self.artist.setText(self.artist.fontMetrics().elidedText(
            track.artist, Qt.TextElideMode.ElideRight, 220))
        self.slider.setRange(0, max(track.duration_ms, 1))
        self.slider.setValue(0)
        self.pos_lbl.setText("0:00")
        self.dur_lbl.setText(fmt_time(track.duration_ms))

    def _on_loading(self, loading: bool) -> None:
        track = self.player.current
        if loading:
            self.artist.setText("Загрузка…")
        elif track:
            self.artist.setText(self.artist.fontMetrics().elidedText(
                track.artist, Qt.TextElideMode.ElideRight, 220))

    def _on_position(self, pos: int, dur: int) -> None:
        if self._dragging:
            return
        if dur and self.slider.maximum() != dur:
            self.slider.setRange(0, dur)
            self.dur_lbl.setText(fmt_time(dur))
        self.slider.setValue(pos)
        self.pos_lbl.setText(fmt_time(pos))

    def _seek(self) -> None:
        self._dragging = False
        self.player.seek(self.slider.value())
