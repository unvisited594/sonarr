"""Кроссфейд: конец трека плавно перетекает в начало следующего.

Плеер у Sonar один, поэтому за несколько секунд до конца уходящий трек «пересаживается» во
второй, временный плеер (с того же места) и там затихает, а основной плеер уже берёт следующий
трек и плавно набирает громкость. Если временный плеер не завёлся за 2 секунды (бывает с
одноразовыми ссылками), кроссфейда не будет: трек просто доиграет как обычно.
Не работает при повторе трека и при таймере сна «до конца трека».
"""
import logging

from PyQt6.QtCore import QObject, QTimer, QVariantAnimation
from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer

log = logging.getLogger("sonar.crossfade")
MAX_SEC = 12


class Crossfader(QObject):
    def __init__(self, player, config) -> None:
        super().__init__(player)
        self.player = player
        self.config = config
        self.active = False
        self._ghost = None
        self._gout = None
        self._fade_in_pending = False
        self._anims = []
        player.mp.positionChanged.connect(self._on_position)
        player.started.connect(self._on_started)
        player.playing_changed.connect(self._on_playing)

    @property
    def seconds(self) -> int:
        return max(0, min(MAX_SEC, int(self.config.data.get("crossfade", 0) or 0)))

    def set_seconds(self, sec: int) -> None:
        self.config.data["crossfade"] = max(0, min(MAX_SEC, int(sec)))
        self.config.save()

    def _has_next(self) -> bool:
        p = self.player
        return p.index + 1 < len(p.queue) or (p.context == "wave" and bool(p.queue))

    def _on_position(self, pos: int) -> None:
        sec = self.seconds
        p = self.player
        if not sec or self.active or not p.is_playing or p.repeat or p.stop_after_track or not self._has_next():
            return
        dur = p.mp.duration() or (p.current.duration_ms if p.current else 0)
        if dur < sec * 2000 + 5000:
            return   # короткий трек — пусть доиграет целиком
        if dur - pos <= sec * 1000:
            self._begin(pos, sec)

    def _begin(self, pos: int, sec: int) -> None:
        p = self.player
        self.active = True
        self._ghost = QMediaPlayer(self)
        self._gout = QAudioOutput(self)
        try:
            self._gout.setDevice(p.out.device())
        except AttributeError:
            pass
        self._gout.setVolume(p.out.volume())
        self._ghost.setAudioOutput(self._gout)
        self._ghost.setSource(p.mp.source())
        self._ghost.setPosition(pos + 120)
        self._sec = sec
        self._handed = False
        self._ghost.positionChanged.connect(self._ghost_moving)
        self._ghost.play()
        QTimer.singleShot(2000, self._give_up)
        log.info("кроссфейд %s с: начинаю с %s мс", sec, pos)

    def _ghost_moving(self, pos: int) -> None:
        if self._handed or self._ghost is None or pos <= 0:
            return
        self._handed = True   # уходящий трек звучит из временного плеера — основной берёт следующий
        self._fade_in_pending = True
        self.player.out.setVolume(0.0)
        self.player.next()
        self._animate(self._gout, self._gout.volume(), 0.0, self._sec * 1000, self._finish_ghost)

    def _give_up(self) -> None:
        if self.active and not self._handed:
            log.info("кроссфейд: временный плеер не завёлся — трек доиграет как обычно")
            self._finish_ghost()

    def _on_started(self, _track) -> None:
        if self._fade_in_pending:
            self._fade_in_pending = False
            self._animate(self.player.out, 0.0, self.player.user_volume, self._sec * 1000)

    def _on_playing(self, on: bool) -> None:
        if not on and self._ghost is not None and self._handed and not self._fade_in_pending:
            self._finish_ghost()   # пауза посреди перехода — тишина сразу

    def _animate(self, out, start: float, end: float, ms: int, done=None) -> None:
        anim = QVariantAnimation(self)
        anim.setStartValue(float(start))
        anim.setEndValue(float(end))
        anim.setDuration(max(200, ms))
        anim.valueChanged.connect(lambda v, o=out: o.setVolume(float(v)))
        anim.finished.connect(lambda a=anim: self._anims.remove(a) if a in self._anims else None)
        if done:
            anim.finished.connect(done)
        self._anims.append(anim)
        anim.start()

    def _finish_ghost(self) -> None:
        if self._ghost is not None:
            self._ghost.stop()
            self._ghost.deleteLater()
            self._gout.deleteLater()
        self._ghost = self._gout = None
        self.active = False
        if self._fade_in_pending and not self._handed:
            self._fade_in_pending = False
