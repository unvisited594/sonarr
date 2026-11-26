"""Видео на фоне большого плеера: тот же трек на YouTube, беззвучно, в такт музыке."""
import logging

from PyQt6.QtCore import QObject, Qt, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QImage
from PyQt6.QtMultimedia import QMediaPlayer, QVideoFrame, QVideoSink

from ..services.base import ServiceError
from ..workers import run_async

log = logging.getLogger("sonar.videobg")
# Только видеодорожка не выше 720p: звук играет основной плеер, а фону хватает и этого.
# H.264 (avc1) — в первую очередь: его декодирует любая видеокарта, а AV1, который YouTube всё
# чаще кладёт в mp4, встроенный в Qt FFmpeg понимает не везде — фон остался бы пустым.
BG_FORMAT = ("bestvideo[height<=720][vcodec^=avc1]/bestvideo[height<=720][ext=mp4]"
             "/bestvideo[height<=720]/best[height<=720]/best")
SYNC_DRIFT_MS = 2500
_url_cache: dict = {}


def find_youtube_video(manager, track) -> str:
    """id ролика на YouTube для трека любого сервиса; официальный клип, если он есть."""
    from ..services import youtube_match
    svc = manager.get(track.service_id)
    if track.service_id == "ytmusic" and svc is not None:
        try:
            return svc._video_id(track)
        except ServiceError:
            return track.id
    raw = track.raw or {}
    isrc = (raw.get("external_ids") or {}).get("isrc") or raw.get("isrc")
    artist = ((raw.get("artists") or [{}])[0].get("name") if raw.get("artists") else None) \
        or track.artist.split(",")[0].strip()
    return youtube_match.find_music_video(track.title, artist, track.duration_ms, isrc)


def resolve_video_url(manager, track) -> str:
    """В фоне: ссылка на видеопоток. Найденное кешируется на сессию."""
    from ..services.youtube_music import extract_stream
    key = (track.service_id, track.id)
    if key not in _url_cache:
        vid = find_youtube_video(manager, track)
        _url_cache[key] = extract_stream(f"https://www.youtube.com/watch?v={vid}", BG_FORMAT)
        log.info("видео для %s/%s: youtube %s", track.service_id, track.id, vid)
    return _url_cache[key]


class VideoBackground(QObject):
    frame_ready = pyqtSignal()

    def __init__(self, manager, parent=None) -> None:
        super().__init__(parent)
        self.manager = manager
        self.mp = QMediaPlayer(self)      # без аудиовыхода — играет беззвучно
        self.sink = QVideoSink(self)
        self.mp.setVideoSink(self.sink)
        self.sink.videoFrameChanged.connect(self._on_frame)
        self.mp.mediaStatusChanged.connect(self._on_status)
        self.mp.errorOccurred.connect(self._on_error)
        self._frame = None
        self._image: QImage | None = None
        self._dirty = False
        self._req = 0
        self._key = None
        self._resume_at = 0
        self._track = None
        self._retried = False

    def _on_error(self, _error, text: str) -> None:
        """Ссылки YouTube живут несколько часов: протухшую сбрасываем и пробуем один раз заново."""
        log.warning("видео на фоне: %s", text)
        if self._track is not None and not self._retried:
            self._retried = True
            _url_cache.pop((self._track.service_id, self._track.id), None)
            track, pos, self._key = self._track, self.mp.position(), None
            # менять источник прямо внутри сигнала ошибки этого же плеера — небезопасно для Qt
            QTimer.singleShot(0, lambda: self.start(track, pos, retry=True))

    @property
    def active(self) -> bool:
        return self._key is not None

    def start(self, track, position_ms: int = 0, retry: bool = False) -> None:
        key = (track.service_id, track.id)
        if key == self._key:
            return
        self.stop()
        self._key = key
        self._track = track
        if not retry:
            self._retried = False
        self._req += 1
        req = self._req
        run_async(resolve_video_url, self.manager, track,
                  on_done=lambda url: self._resolved(req, url, position_ms),
                  on_error=lambda err: req == self._req and log.info("видео не найдено: %s", err))

    def _resolved(self, req: int, url: str, position_ms: int) -> None:
        if req != self._req:
            return
        self._resume_at = position_ms
        self.mp.setSource(QUrl(url))
        self.mp.play()

    def _on_status(self, status) -> None:
        if status == QMediaPlayer.MediaStatus.LoadedMedia and self._resume_at:
            dur = self.mp.duration()
            self.mp.setPosition(self._resume_at % dur if dur else self._resume_at)
            self._resume_at = 0
        elif status == QMediaPlayer.MediaStatus.EndOfMedia:   # ролик короче трека — по кругу
            QTimer.singleShot(0, self._loop)

    def _loop(self) -> None:
        if self._key is not None:
            self.mp.setPosition(0)
            self.mp.play()

    def stop(self) -> None:
        self._req += 1
        self._key = None
        self._track = None
        self.mp.stop()
        self.mp.setSource(QUrl())
        self._frame, self._image = None, None

    def set_playing(self, on: bool) -> None:
        if self._key is None:
            return
        if on:
            self.mp.play()
        else:
            self.mp.pause()

    def sync(self, position_ms: int) -> None:
        """Подтягиваем видео к музыке, если разошлись (буферизация, перемотка)."""
        dur = self.mp.duration()
        if self._key is None or not dur or self.mp.playbackState() != QMediaPlayer.PlaybackState.PlayingState:
            return
        target = position_ms % dur
        if abs(self.mp.position() - target) > SYNC_DRIFT_MS:
            self.mp.setPosition(target)

    def _on_frame(self, frame) -> None:
        # Кадр приходит из потока декодера ссылкой на временный объект, который удаляется сразу
        # после сигнала. Храним собственную копию: QVideoFrame копируется дёшево (счётчик ссылок),
        # а обращение к удалённому кадру при отрисовке роняло программу.
        self._frame = QVideoFrame(frame)
        self._dirty = True

    def image(self, width: int, height: int) -> QImage | None:
        """Последний кадр, отмасштабированный «на всю площадь». Пересчёт — только при новом кадре."""
        if self._dirty and self._frame is not None and self._frame.isValid():
            img = self._frame.toImage()
            if not img.isNull():
                self._image = img.scaled(width, height, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                         Qt.TransformationMode.FastTransformation)
            self._dirty = False
        return self._image
