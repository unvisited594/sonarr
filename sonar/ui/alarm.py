"""Будильник: в нужное время Sonar сам включает музыку и плавно поднимает громкость.

config.data["alarm"] = {"on", "time": "07:30", "days": [0..6] (пн=0), "source": "likes" | "wave" |
"radio" | "playlist:<id>", "ramp": секунды}. Работает, пока Sonar запущен (можно свернуть в трей).
"""
import logging
import random
import time

from PyQt6.QtCore import QObject, QTime, QTimer, Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QPushButton, QSlider, QTimeEdit

log = logging.getLogger("sonar.alarm")
DAYS = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
DEFAULT = {"on": False, "time": "07:30", "days": [0, 1, 2, 3, 4], "source": "likes", "ramp": 90}


class Alarm(QObject):
    def __init__(self, window, config) -> None:
        super().__init__(window)
        self.win, self.config = window, config
        self._fired = ""
        self._ramp = None
        self._timer = QTimer(self, interval=15000)
        self._timer.timeout.connect(self._check)
        self._timer.start()

    @property
    def data(self) -> dict:
        d = dict(DEFAULT)
        d.update(self.config.data.get("alarm") or {})
        return d

    def update(self, **changes) -> None:
        d = self.data
        d.update(changes)
        self.config.data["alarm"] = d
        self.config.save()

    def next_ring(self) -> str:
        d = self.data
        if not d["on"] or not d["days"]:
            return "выключен"
        h, m = map(int, d["time"].split(":"))
        now = time.localtime()
        for add in range(8):
            t = time.localtime(time.time() + add * 86400)
            if t.tm_wday in d["days"] and (add > 0 or (h, m) > (now.tm_hour, now.tm_min)):
                when = "сегодня" if add == 0 else ("завтра" if add == 1 else DAYS[t.tm_wday].lower())
                return f"зазвонит {when} в {d['time']}"
        return "выключен"

    def _check(self) -> None:
        d = self.data
        if not d["on"]:
            return
        now = time.localtime()
        stamp = time.strftime("%Y-%m-%d %H:%M", now)
        if now.tm_wday in d["days"] and time.strftime("%H:%M", now) == d["time"] and self._fired != stamp:
            self._fired = stamp
            self.ring()

    def tracks(self, source: str) -> list:
        mgr = self.win.manager
        if source == "likes":
            tracks = self.win.likes.tracks(mgr)
            random.shuffle(tracks)
            return tracks
        if source == "radio":
            favs = self.win.radio_page.favorites() if hasattr(self.win, "radio_page") else []
            return favs[:1]
        if source.startswith("playlist:"):
            return self.win.playlists_page.local.tracks(source.split(":", 1)[1], mgr)
        for svc in mgr.connected():   # «волна»: первый сервис, где она есть
            try:
                found = svc.wave()
                if found:
                    return found
            except Exception:
                continue
        return []

    def ring(self) -> None:
        d = self.data
        tracks = [t for t in self.tracks(d["source"]) if t.playable] or [t for t in self.tracks("likes") if t.playable]
        if not tracks:
            self.win.show_toast("Будильник: нечего включить — добавьте лайки или выберите плейлист")
            return
        log.info("будильник: %s, %s треков", d["source"], len(tracks))
        bar = self.win.bar
        target = max(20, bar.volume.value())
        bar.volume.setValue(5)
        self.win.player.play_queue(tracks, 0, "alarm")
        self.win.showNormal()
        self.win.raise_()
        self.win.show_toast("Доброе утро! Будильник Sonar")
        steps = max(1, int(d["ramp"]))
        start = time.monotonic()
        if self._ramp is not None:
            self._ramp.stop()
        self._ramp = QTimer(self, interval=1000)

        def up():
            k = min(1.0, (time.monotonic() - start) / steps)
            bar.volume.setValue(int(5 + (target - 5) * k))
            if k >= 1:
                self._ramp.stop()
        self._ramp.timeout.connect(up)
        self._ramp.start()


class AlarmSection(QObject):
    """Блок «Будильник» для вкладки «Плеер»."""

    def __init__(self, alarm: Alarm, lay, window) -> None:
        super().__init__(alarm)
        from .theme import font
        from .widgets import Toggle, muted
        self.alarm = alarm
        d = alarm.data
        head = QLabel("Будильник")
        head.setFont(font(17, QFont.Weight.Bold, display=True))
        lay.addSpacing(22)
        lay.addWidget(head)
        note = muted("Утром Sonar сам включит музыку и плавно поднимет громкость. Работает, пока Sonar открыт "
                     "(можно свернуть в трей).")
        note.setWordWrap(True)
        note.setMaximumWidth(640)
        lay.addWidget(note)
        row = QHBoxLayout()
        self.toggle = Toggle()
        self.toggle.setChecked(d["on"])
        self.toggle.toggled.connect(lambda on: self._set(on=on))
        row.addWidget(self.toggle)
        self.time = QTimeEdit(QTime.fromString(d["time"], "HH:mm"))
        self.time.setDisplayFormat("HH:mm")
        self.time.timeChanged.connect(lambda t: self._set(time=t.toString("HH:mm")))
        row.addWidget(self.time)
        self.days = []
        for i, name in enumerate(DAYS):
            b = QPushButton(name)
            b.setObjectName("chip")
            b.setCheckable(True)
            b.setChecked(i in d["days"])
            b.setFixedWidth(46)
            b.toggled.connect(lambda _on: self._set(days=[k for k, x in enumerate(self.days) if x.isChecked()]))
            self.days.append(b)
            row.addWidget(b)
        row.addStretch(1)
        lay.addLayout(row)
        row = QHBoxLayout()
        row.addWidget(QLabel("Что играть:"))
        self.source = QComboBox()
        self.source.addItem("Мои лайки (вперемешку)", "likes")
        self.source.addItem("Моя волна", "wave")
        self.source.addItem("Радио (первая станция из избранного)", "radio")
        for pl in window.playlists_page.local.all():
            if not pl.get("smart"):
                self.source.addItem(f"Плейлист: {pl['title']}", f"playlist:{pl['id']}")
        i = self.source.findData(d["source"])
        self.source.setCurrentIndex(max(0, i))
        self.source.currentIndexChanged.connect(lambda _i: self._set(source=self.source.currentData()))
        self.source.setMaximumWidth(440)
        row.addWidget(self.source)
        row.addStretch(1)
        lay.addLayout(row)
        row = QHBoxLayout()
        row.addWidget(QLabel("Громкость нарастает:"))
        self.ramp = QSlider(Qt.Orientation.Horizontal)
        self.ramp.setRange(10, 300)
        self.ramp.setValue(int(d["ramp"]))
        self.ramp.setMaximumWidth(260)
        self.ramp_label = muted()
        self.ramp.valueChanged.connect(lambda v: (self.ramp_label.setText(f"{v} с"), self._set(ramp=v)))
        self.ramp_label.setText(f"{d['ramp']} с")
        row.addWidget(self.ramp)
        row.addWidget(self.ramp_label)
        test = QPushButton("Проверить сейчас")
        test.setCursor(Qt.CursorShape.PointingHandCursor)
        test.clicked.connect(alarm.ring)
        row.addWidget(test)
        row.addStretch(1)
        lay.addLayout(row)
        self.status = muted()
        lay.addWidget(self.status)
        self._show()

    def _set(self, **kw) -> None:
        self.alarm.update(**kw)
        self._show()

    def _show(self) -> None:
        self.status.setText("Будильник " + self.alarm.next_ring())
