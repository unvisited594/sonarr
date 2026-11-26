"""Итоги года: слайды в формате сторис (9:16), которые можно сохранить картинками и выложить."""
import time
from pathlib import Path

from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QImage, QLinearGradient, QPainter, QRadialGradient
from PyQt6.QtWidgets import QFileDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from .. import playlog
from .theme import font
from .widgets import muted

PALETTES = [("#3b1d8f", "#ff4d6d"), ("#0f3d5e", "#00e5ff"), ("#5e0f3d", "#ffb703"), ("#1d3b1a", "#b6ff3b"),
            ("#2b1055", "#7597de"), ("#4a0d0d", "#ff7a00"), ("#101820", "#f2aa4c")]
SERVICE_NAMES = {"soundcloud": "SoundCloud", "ytmusic": "YouTube Music", "yandex": "Яндекс Музыка",
                 "deezer": "Deezer", "spotify": "Spotify", "navidrome": "Navidrome"}
MONTHS = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября",
          "ноября", "декабря"]


def _hours_word(n: int) -> str:
    n10, n100 = n % 10, n % 100
    if n10 == 1 and n100 != 11:
        return "час"
    if 2 <= n10 <= 4 and not 12 <= n100 <= 14:
        return "часа"
    return "часов"


def build_slides(s: dict, year: int, name: str) -> list[dict]:
    """Каждый слайд: подпись сверху, крупное слово/число, строки под ним."""
    who = f"{name}, " if name else ""
    slides = [{"kicker": f"Sonar · {year}", "big": "Твои итоги", "lines": [f"{who}вот как звучал твой год"]}]
    hours = s["minutes"] // 60
    slides.append({"kicker": "Ты слушал музыку", "big": f"{s['minutes']:,}".replace(",", " "),
                   "lines": ["минут", f"это {hours} {_hours_word(hours)}" if hours else "и это только начало",
                             f"{s['plays']} прослушиваний · {s['tracks']} треков"]})
    if s["top_artists"]:
        a, m = s["top_artists"][0]
        rest = [f"{i + 2}. {x}" for i, (x, _m) in enumerate(s["top_artists"][1:5])]
        slides.append({"kicker": "Твой исполнитель года", "big": a, "lines": [f"{m} минут вместе"] + rest})
    if s["top_tracks"]:
        t, a, n = s["top_tracks"][0]
        rest = [f"{i + 2}. {x} — {y}" for i, (x, y, _n) in enumerate(s["top_tracks"][1:5])]
        slides.append({"kicker": "Трек года", "big": t, "lines": [f"{a} · {n} раз"] + rest})
    d = time.strptime(s["best_day"], "%Y-%m-%d")
    owl = "Ночная сова" if s["night_share"] >= 15 else ("Жаворонок" if s["hour"] < 11 else "Дневной меломан")
    slides.append({"kicker": "Твой ритм", "big": owl,
                   "lines": [f"Любимый час — {s['hour']}:00", f"Ночью (до 5 утра) — {s['night_share']}% музыки",
                             f"Самый музыкальный день — {d.tm_mday} {MONTHS[d.tm_mon - 1]}: {s['best_day_minutes']} мин"]})
    if s["services"]:
        sid, m = s["services"][0]
        lines = [f"{SERVICE_NAMES.get(x, x)} — {mm} мин" for x, mm in s["services"][:4]]
        slides.append({"kicker": "Больше всего звучал", "big": SERVICE_NAMES.get(sid, sid), "lines": lines})
    if s.get("first", ("", ""))[0]:
        slides.append({"kicker": f"С этого начался твой {year}", "big": s["first"][0], "lines": [s["first"][1]]})
    slides.append({"kicker": "Спасибо, что слушаешь с Sonar", "big": "До встречи в " + str(year + 1),
                   "lines": [f"{s['artists']} исполнителей · {s['tracks']} треков", "Telegram: @sonar081"]})
    return slides


def _longest_word(f: QFont, text: str) -> float:
    from PyQt6.QtGui import QFontMetricsF
    fm = QFontMetricsF(f)
    longest = max((fm.horizontalAdvance(w) for w in text.split()), default=0)   # слово целиком в строку
    return longest


def draw_slide(p: QPainter, w: float, h: float, slide: dict, index: int, total: int) -> None:
    k = w / 1080
    a, b = (QColor(c) for c in PALETTES[index % len(PALETTES)])
    g = QLinearGradient(0, 0, w, h)
    g.setColorAt(0, a)
    g.setColorAt(1, a.darker(170))
    p.fillRect(QRectF(0, 0, w, h), g)
    for cx, cy, r, alpha in ((0.85, 0.18, 0.55, 150), (0.1, 0.75, 0.6, 110), (0.6, 0.95, 0.45, 90)):
        rg = QRadialGradient(cx * w, cy * h, r * w)
        col = QColor(b)
        col.setAlpha(alpha)
        rg.setColorAt(0, col)
        col.setAlpha(0)
        rg.setColorAt(1, col)
        p.fillRect(QRectF(0, 0, w, h), rg)
    # полоски прогресса, как в сторис
    gap, top = 10 * k, 60 * k
    seg = (w - 80 * k - gap * (total - 1)) / total
    for i in range(total):
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 255, 255, 230 if i <= index else 70))
        p.drawRoundedRect(QRectF(40 * k + i * (seg + gap), top, seg, 8 * k), 4 * k, 4 * k)
    margin = 80 * k
    box_w = w - 2 * margin
    p.setPen(QColor(255, 255, 255, 220))
    p.setFont(font(int(46 * k), QFont.Weight.Bold))
    kicker = QRectF(margin, 260 * k, box_w, 200 * k)
    p.drawText(kicker, Qt.TextFlag.TextWordWrap | Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom, slide["kicker"])
    big = slide["big"]
    f = font(int(170 * k), QFont.Weight.Black, display=True)
    size = int(170 * k)
    while size > int(64 * k) and _longest_word(f, big) > box_w:
        size -= int(6 * k) or 1
        f.setPixelSize(size)
    if len(big) > 28:
        f.setPixelSize(min(size, int(96 * k)))
    p.setFont(f)
    p.setPen(QColor("#ffffff"))
    big_rect = p.boundingRect(QRectF(margin, 0, box_w, 2000 * k), Qt.TextFlag.TextWordWrap, big)
    y = 500 * k
    p.drawText(QRectF(margin, y, box_w, big_rect.height()), Qt.TextFlag.TextWordWrap, big)
    y += big_rect.height() + 50 * k
    p.fillRect(QRectF(margin, y, 120 * k, 10 * k), QColor(b))   # акцентная черта
    y += 60 * k
    for i, line in enumerate(slide["lines"]):
        p.setFont(font(int((52 if i == 0 else 40) * k), QFont.Weight.Bold if i == 0 else QFont.Weight.DemiBold))
        p.setPen(QColor(255, 255, 255, 240 if i == 0 else 200))
        r = p.boundingRect(QRectF(margin, y, box_w, 1000 * k), Qt.TextFlag.TextWordWrap, line)
        if y + r.height() > h - 220 * k:
            break
        p.drawText(QRectF(margin, y, box_w, r.height()), Qt.TextFlag.TextWordWrap, line)
        y += r.height() + 22 * k
    p.setFont(font(int(44 * k), QFont.Weight.Black, display=True))
    p.setPen(QColor(255, 255, 255, 235))
    p.drawText(QRectF(margin, h - 170 * k, box_w, 80 * k), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
               "Sonar")


class SlideView(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.slides: list[dict] = []
        self.index = 0
        self.setMinimumSize(270, 480)

    def paintEvent(self, _event) -> None:
        if not self.slides:
            return
        h = self.height()
        w = h * 9 / 16
        if w > self.width():
            w = self.width()
            h = w * 16 / 9
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.translate((self.width() - w) / 2, (self.height() - h) / 2)
        from PyQt6.QtGui import QPainterPath
        clip = QPainterPath()
        clip.addRoundedRect(QRectF(0, 0, w, h), 22, 22)
        p.setClipPath(clip)
        draw_slide(p, w, h, self.slides[self.index], self.index, len(self.slides))

    def mouseReleaseEvent(self, event) -> None:
        if not self.slides:
            return
        step = 1 if event.position().x() > self.width() / 2 else -1
        self.index = max(0, min(len(self.slides) - 1, self.index + step))
        self.update()
        self.parent().sync() if hasattr(self.parent(), "sync") else None


def render_png(slide: dict, index: int, total: int) -> QImage:
    img = QImage(1080, 1920, QImage.Format.Format_ARGB32)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    draw_slide(p, 1080, 1920, slide, index, total)
    p.end()
    return img


class WrappedPage(QWidget):
    def __init__(self, window, history, config, parent=None) -> None:
        super().__init__(parent)
        self.win = window
        self.history = history
        self.config = config
        self.year = time.localtime().tm_year
        lay = QVBoxLayout(self)
        lay.setContentsMargins(36, 28, 36, 20)
        lay.setSpacing(10)
        title = QLabel(f"Итоги {self.year}")
        title.setFont(font(30, QFont.Weight.Black, display=True))
        lay.addWidget(title)
        self.note = muted()
        self.note.setWordWrap(True)
        lay.addWidget(self.note)
        self.view = SlideView(self)
        lay.addWidget(self.view, 1)
        row = QHBoxLayout()
        self.prev = QPushButton("‹ Назад")
        self.next = QPushButton("Дальше ›")
        self.save_one = QPushButton("Сохранить картинку")
        self.save_all = QPushButton("Сохранить все")
        self.save_all.setObjectName("primary")
        for b in (self.prev, self.next, self.save_one, self.save_all):
            b.setCursor(Qt.CursorShape.PointingHandCursor)
        self.prev.clicked.connect(lambda: self._go(-1))
        self.next.clicked.connect(lambda: self._go(1))
        self.save_one.clicked.connect(lambda: self._save(False))
        self.save_all.clicked.connect(lambda: self._save(True))
        row.addStretch(1)
        for b in (self.prev, self.next, self.save_one, self.save_all):
            row.addWidget(b)
        row.addStretch(1)
        lay.addLayout(row)

    def showEvent(self, event) -> None:
        self.refresh()
        super().showEvent(event)

    def refresh(self) -> None:
        events = playlog.load_events(self.year, getattr(self.history, "entries", []))
        s = playlog.summarize(events)
        if s["plays"] < 5:
            self.view.slides = []
            self.note.setText("Итоги соберутся, когда наберётся хоть немного музыки: слушайте — Sonar всё "
                              f"запоминает сам. Пока прослушиваний: {s['plays']}.")
            for b in (self.prev, self.next, self.save_one, self.save_all):
                b.setEnabled(False)
            self.view.update()
            return
        from .. import profile as profiles
        prof = profiles.get(self.config) or {}
        self.view.slides = build_slides(s, self.year, prof.get("name", "") if isinstance(prof, dict) else "")
        self.view.index = min(self.view.index, len(self.view.slides) - 1)
        self.note.setText("Листайте щелчком по картинке (справа — дальше, слева — назад) и сохраняйте для сторис."
                          + (" Часть статистики до этой версии Sonar посчитана примерно, по истории." if s["approx"] else ""))
        self.sync()

    def sync(self) -> None:
        n = len(self.view.slides)
        self.prev.setEnabled(self.view.index > 0)
        self.next.setEnabled(self.view.index < n - 1)
        self.save_one.setEnabled(n > 0)
        self.save_all.setEnabled(n > 0)
        self.view.update()

    def _go(self, step: int) -> None:
        self.view.index = max(0, min(len(self.view.slides) - 1, self.view.index + step))
        self.sync()

    def _save(self, everything: bool) -> None:
        slides = self.view.slides
        if not slides:
            return
        if everything:
            folder = QFileDialog.getExistingDirectory(self, "Куда сохранить итоги", str(Path.home()))
            if not folder:
                return
            for i, sl in enumerate(slides):
                render_png(sl, i, len(slides)).save(str(Path(folder) / f"Sonar-итоги-{self.year}-{i + 1}.png"))
            self.win.show_toast(f"Сохранено картинок: {len(slides)}")
        else:
            i = self.view.index
            path, _ = QFileDialog.getSaveFileName(self, "Сохранить картинку",
                                                  str(Path.home() / f"Sonar-итоги-{self.year}-{i + 1}.png"), "PNG (*.png)")
            if path:
                render_png(slides[i], i, len(slides)).save(path)
                self.win.show_toast("Картинка сохранена")
