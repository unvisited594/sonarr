"""Достижения — приколюхи за то, как человек слушает музыку в Sonar.

Счётчики живут в config.data["fun_stats"], открытые достижения — в config.data["achievements"]
({id: время}). Всё считается только на этом компьютере и никуда не отправляется.
"""
import time

from PyQt6.QtCore import QObject, pyqtSignal

# id, название, как получить, значок (символ на медали), проверка по счётчикам
ACHIEVEMENTS = [
    ("first", "Первый трек", "Включить что-нибудь в Sonar", "1", lambda s: s.get("plays", 0) >= 1),
    ("plays50", "Разогрев", "Послушать 50 треков", "50", lambda s: s.get("plays", 0) >= 50),
    ("plays500", "Меломан", "Послушать 500 треков", "500", lambda s: s.get("plays", 0) >= 500),
    ("plays2000", "Живу в наушниках", "Послушать 2000 треков", "2K", lambda s: s.get("plays", 0) >= 2000),
    ("night", "Ночная сова", "Слушать музыку между часом и пятью ночи", "☾", lambda s: s.get("night", 0) >= 1),
    ("morning", "Ранняя пташка", "Включить музыку до семи утра", "☀", lambda s: s.get("morning", 0) >= 1),
    ("services3", "Всеядный", "Слушать треки из трёх разных сервисов", "3", lambda s: len(s.get("services", [])) >= 3),
    ("likes10", "Сердечко", "Поставить 10 лайков", "♥", lambda s: s.get("likes", 0) >= 10),
    ("likes100", "Влюбчивый", "Поставить 100 лайков", "♥♥", lambda s: s.get("likes", 0) >= 100),
    ("lyrics", "Подпеваю", "Открыть текст песни в большом плеере", "♪", lambda s: s.get("lyrics", 0) >= 1),
    ("custom", "Дизайнер", "Сохранить свой набор в Мастерской", "✎", lambda s: s.get("saved", 0) >= 1),
    ("installer", "Коллекционер", "Поставить 3 набора из каталога", "★", lambda s: s.get("installed", 0) >= 3),
    ("party", "Вечеринка", "Включить режим вечеринки", "✦", lambda s: s.get("party", 0) >= 1),
    ("egg", "Пасхалка", "Найти секрет: набрать на клавиатуре одно слово…", "?", lambda s: s.get("egg", 0) >= 1),
    ("marathon", "Марафон", "Слушать без перерыва больше часа", "∞", lambda s: s.get("streak_max", 0) >= 3600),
]
BY_ID = {a[0]: a for a in ACHIEVEMENTS}


class Achievements(QObject):
    unlocked = pyqtSignal(str)   # id нового достижения
    changed = pyqtSignal()

    def __init__(self, config) -> None:
        super().__init__()
        self.config = config
        self._last_play = 0.0

    @property
    def stats(self) -> dict:
        return self.config.data.setdefault("fun_stats", {})

    @property
    def done(self) -> dict:
        return self.config.data.setdefault("achievements", {})

    def bump(self, key: str, by: int = 1) -> None:
        self.stats[key] = int(self.stats.get(key, 0)) + by
        self._check()

    def set_value(self, key: str, value) -> None:
        self.stats[key] = value
        self._check()

    def track_started(self, track) -> None:
        s = self.stats
        now = time.time()
        s["plays"] = int(s.get("plays", 0)) + 1
        hour = time.localtime(now).tm_hour
        if 1 <= hour < 5:
            s["night"] = int(s.get("night", 0)) + 1
        if 5 <= hour < 7:
            s["morning"] = int(s.get("morning", 0)) + 1
        services = set(s.get("services", []))
        if getattr(track, "service_id", None):
            services.add(track.service_id)
        s["services"] = sorted(services)
        # непрерывное прослушивание: следующий трек начался не позже чем через 10 минут
        if self._last_play and now - self._last_play < 600:
            s["streak"] = float(s.get("streak", 0)) + (now - self._last_play)
        else:
            s["streak"] = 0.0
        s["streak_max"] = max(float(s.get("streak_max", 0)), s["streak"])
        self._last_play = now
        self._check()

    def _check(self) -> None:
        new = [aid for aid, *_rest, test in ACHIEVEMENTS if aid not in self.done and test(self.stats)]
        for aid in new:
            self.done[aid] = time.time()
        self.config.save()
        for aid in new:
            self.unlocked.emit(aid)
        self.changed.emit()

    def progress(self) -> tuple[int, int]:
        return len([a for a in ACHIEVEMENTS if a[0] in self.done]), len(ACHIEVEMENTS)
