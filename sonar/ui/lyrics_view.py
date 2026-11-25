"""Текст песни в большом плеере. Два вида:
- «Как в Dotify» — подсвечивается вся текущая строка, спетые строки в цвете «спетого»,
  будущие приглушены;
- «Караоке» — буквы по одной (с плавной заливкой внутри буквы) меняют цвет, когда их поют.
Цвета, шрифт, размер, выравнивание, скорость заливки, сдвиг по времени и плавность прокрутки
берутся из настроек (flow_settings, ключи lyrics_*). Колёсиком текст можно прокрутить,
щелчок по строке перематывает к ней."""
import time

from PyQt6.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QFontMetricsF, QImage, QLinearGradient, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QWidget

from .theme import font

MANUAL_HOLD = 3.0                    # после ручной прокрутки столько секунд не крутим сами


def halo_for(color: QColor) -> QColor:
    """Обводка, контрастная к цвету букв: светлая вокруг тёмных, тёмная вокруг светлых."""
    return QColor(255, 255, 255, 150) if color.lightnessF() < 0.5 else QColor(0, 0, 0, 120)


def char_progress(line, ms: int) -> float:
    """Сколько символов строки уже спето (дробное: буква закрашивается плавно)."""
    n = len(line.text)
    if ms <= line.start:
        return 0.0
    if ms >= line.end:
        return float(n)
    if line.words:   # пословные метки: между ними идём равномерно
        marks = [(line.start, 0)] + [(t, i) for t, i in line.words if i <= n] + [(line.end, n)]
        marks.sort()
        for (t0, i0), (t1, i1) in zip(marks, marks[1:]):
            if t0 <= ms < t1:
                return i0 + (i1 - i0) * (ms - t0) / max(t1 - t0, 1)
        return float(n)
    return n * (ms - line.start) / max(line.end - line.start, 1)


class LyricsView(QWidget):
    seek_requested = pyqtSignal(int)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMouseTracking(True)
        self._lyrics = None
        self._state = "none"      # loading | none | ok
        self._ms = 0
        self._scroll = 0.0        # смещение содержимого (px)
        self._manual_until = 0.0
        self._rows = []           # [(line_index, text, char_offset, y, перевод?)]
        self.translations = None  # перевод строк (или None)
        self._line_y = []         # [(y_top, y_bottom)] для каждой строки
        self._height = 0.0
        self._laid_width = -1
        self._hover = -1
        self._small = font(14, QFont.Weight.DemiBold)
        self.scale = 1.0          # превью в настройках рисует мельче
        self.style = "dotify"
        self.unsung, self.sung = QColor("#ffffff"), QColor("#000000")
        self.halo = True
        self.align = "left"
        self.char_ms = 110.0
        self.offset = 0
        self.ease = 0.18
        self._font = font(30, QFont.Weight.Black, display=True)

    def apply_settings(self, fs) -> None:
        """Перечитать настройки текста (вызывается при каждом изменении)."""
        if fs is None:
            return
        self.style = fs.get("lyrics_style")
        self.unsung, self.sung = QColor(fs.get("lyrics_color")), QColor(fs.get("lyrics_sung"))
        self.halo = bool(fs.get("lyrics_halo"))
        self.align = fs.get("lyrics_align")
        speed = max(25, min(300, int(fs.get("lyrics_speed"))))
        char_ms = 110.0 * 100 / speed
        if char_ms != self.char_ms and self._lyrics and self._lyrics.synced:
            self._lyrics.finish(char_ms=char_ms)
        self.char_ms = char_ms
        self.offset = int(fs.get("lyrics_offset"))
        self.ease = 0.05 + 0.35 * max(0, min(100, int(fs.get("lyrics_scroll")))) / 100
        size = max(14, int(int(fs.get("lyrics_size")) * self.scale))
        weight = QFont.Weight.Black if fs.get("lyrics_bold") else QFont.Weight.Medium
        family = fs.get("lyrics_font")
        if family:
            f = QFont(family)
            f.setPixelSize(size)
            f.setWeight(weight)
        else:
            f = font(size, weight, display=True)
        self._font = f
        self._laid_width = -1
        self.update()

    # ---------- данные ----------

    def set_loading(self) -> None:
        self._lyrics, self._state = None, "loading"
        self._laid_width = -1
        self.update()

    def set_lyrics(self, lyrics) -> None:
        if lyrics and lyrics.synced and self.char_ms != 110.0:
            lyrics.finish(char_ms=self.char_ms)
        self._lyrics = lyrics
        self.translations = None
        self._state = "ok" if lyrics and lyrics.lines else "none"
        self._laid_width = -1
        self._scroll = 0.0
        self._manual_until = 0.0
        self.update()

    @property
    def synced(self) -> bool:
        return bool(self._lyrics and self._lyrics.synced)

    def set_position(self, ms: int) -> None:
        """Вызывается на каждом кадре большого плеера."""
        self._ms = ms + self.offset   # сдвиг: плюс — текст раньше, минус — позже
        if self._state != "ok":
            return
        self._layout()
        if time.monotonic() >= self._manual_until and self.synced:
            target = self._target_scroll()
            delta = target - self._scroll
            self._scroll += delta * self.ease if abs(delta) > 0.5 else delta
        self.update()

    # ---------- раскладка ----------

    def _layout(self) -> None:
        width = self._wrap_width()
        if width == self._laid_width or not self._lyrics:
            return
        self._laid_width = width
        fm = QFontMetricsF(self._font)
        lh = fm.height() * 1.12
        gap = fm.height() * 0.55
        y = 0.0
        self._rows, self._line_y = [], []
        for i, line in enumerate(self._lyrics.lines):
            top = y
            for text, offset in self._wrap(line.text, fm, width):
                self._rows.append((i, text, offset, y, False))
                y += lh
            tr = self.translations[i] if self.translations and i < len(self.translations) else ""
            if tr and tr.strip().lower() != line.text.strip().lower():
                tfm = QFontMetricsF(self._tr_font())
                for text, _off in self._wrap(tr, tfm, width):
                    self._rows.append((i, text, 0, y + lh * 0.05, True))
                    y += tfm.height() * 1.1
            self._line_y.append((top, y))
            y += gap
        self._height = y

    def _tr_font(self) -> QFont:
        f = QFont(self._font)
        f.setPixelSize(max(12, int(self._font.pixelSize() * 0.52)))
        f.setWeight(QFont.Weight.DemiBold)
        return f

    def set_translations(self, lines) -> None:
        self.translations = lines
        self._laid_width = -1
        self.update()

    def _wrap_width(self) -> float:
        return self.width() * 0.86

    @staticmethod
    def _wrap(text: str, fm: QFontMetricsF, width: float) -> list[tuple[str, int]]:
        """Перенос по словам; offset — с какого символа строки начинается ряд."""
        rows, start, current = [], 0, ""
        pos = 0
        for word in text.split(" "):
            candidate = f"{current} {word}" if current else word
            if current and fm.horizontalAdvance(candidate) > width:
                rows.append((current, start))
                start = pos
                current = word
            else:
                current = candidate
            pos += len(word) + 1
        rows.append((current, start))
        return rows

    def _target_scroll(self) -> float:
        idx = max(self._lyrics.index_at(self._ms) if self._lyrics else 0, 0)   # до первой строки — она по центру
        if idx >= len(self._line_y):
            return 0.0
        top, bottom = self._line_y[idx]
        return (top + bottom) / 2 - self.height() * 0.42

    def _clamp(self, value: float) -> float:
        return max(-self.height() * 0.42, min(value, self._height - self.height() * 0.42))

    # ---------- мышь ----------

    def wheelEvent(self, event) -> None:
        if self._state != "ok":
            return
        self._layout()
        self._scroll = self._clamp(self._scroll - event.angleDelta().y() * 0.6)
        self._manual_until = time.monotonic() + MANUAL_HOLD
        self.update()

    def _line_at(self, y: float) -> int:
        y += self._scroll
        for i, (top, bottom) in enumerate(self._line_y):
            if top - 6 <= y <= bottom + 6:
                return i
        return -1

    def mouseMoveEvent(self, event) -> None:
        hover = self._line_at(event.position().y()) if self.synced else -1
        if hover != self._hover:
            self._hover = hover
            self.setCursor(Qt.CursorShape.PointingHandCursor if hover >= 0 else Qt.CursorShape.ArrowCursor)
            self.update()

    def leaveEvent(self, _event) -> None:
        self._hover = -1
        self.update()

    def mouseReleaseEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton or not self.synced:
            return
        i = self._line_at(event.position().y())
        if i >= 0:
            self._manual_until = 0.0
            self.seek_requested.emit(max(0, self._lyrics.lines[i].start))

    # ---------- рисование ----------

    def paintEvent(self, _event) -> None:
        # Рисуем в отдельный слой и гасим его края: строка, уходящая за верх или низ,
        # плавно растворяется, а не обрезается.
        ratio = self.devicePixelRatioF()
        layer = QImage(int(self.width() * ratio), int(self.height() * ratio), QImage.Format.Format_ARGB32_Premultiplied)
        layer.setDevicePixelRatio(ratio)
        layer.fill(Qt.GlobalColor.transparent)
        p = QPainter(layer)
        self._paint_text(p)
        p.resetTransform()
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
        fade = QLinearGradient(0, 0, 0, self.height())
        edge = min(0.14, 60 / max(self.height(), 1))
        fade.setColorAt(0, QColor(0, 0, 0, 0))
        fade.setColorAt(edge, QColor(0, 0, 0, 255))
        fade.setColorAt(1 - edge, QColor(0, 0, 0, 255))
        fade.setColorAt(1, QColor(0, 0, 0, 0))
        p.fillRect(QRectF(0, 0, self.width(), self.height()), fade)
        p.end()
        out = QPainter(self)
        out.drawImage(0, 0, layer)

    def _paint_text(self, p: QPainter) -> None:
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        if self._state != "ok":
            p.setFont(font(20, QFont.Weight.DemiBold))
            p.setPen(QColor(255, 255, 255, 200))
            text = "Ищу текст песни…" if self._state == "loading" else "Текст этой песни не найден"
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, text)
            return
        self._layout()
        fm = QFontMetricsF(self._font)
        ascent = fm.ascent()
        current = self._lyrics.index_at(self._ms) if self.synced else -1
        if not self.synced:
            p.setFont(self._small)
            p.setPen(QColor(255, 255, 255, 150))
            p.drawText(QRectF(0, 0, self.width(), 22), Qt.AlignmentFlag.AlignCenter,
                       "Текст без разметки по времени — прокручивайте колёсиком")
        p.translate(0, -self._scroll + (26 if not self.synced else 0))
        visible_top, visible_bottom = self._scroll - 80, self._scroll + self.height() + 80
        left = (self.width() - self._wrap_width()) / 2
        karaoke = self.style == "karaoke"
        for idx, text, offset, y, is_tr in self._rows:
            if is_tr:   # перевод: мелко и приглушённо, под своей строкой
                tf = self._tr_font()
                tfm = QFontMetricsF(tf)
                tx = left if self.align == "left" else (self.width() - tfm.horizontalAdvance(text)) / 2
                c = QColor(self.unsung)
                c.setAlphaF(0.55 if idx != current else 0.8)
                p.setFont(tf)
                p.setPen(c)
                p.drawText(QPointF(tx, y + tfm.ascent()), text)
                continue
            if y + fm.height() < visible_top or y > visible_bottom:
                continue
            line = self._lyrics.lines[idx]
            if self.align == "left":
                x = left
            else:
                x = (self.width() - fm.horizontalAdvance(text)) / 2
            path = QPainterPath()
            path.addText(QPointF(x, y + ascent), self._font, text)
            far = abs(idx - current) if current >= 0 else (0 if not self.synced else 2)
            hover = idx == self._hover
            if not self.synced:
                self._fill(p, path, self.unsung, 1.0)
                continue
            if not karaoke:
                # Как в Dotify: строка целиком — спетая, текущая или будущая
                if idx < current or (idx == current and self._ms >= line.end and current == len(self._lyrics.lines) - 1):
                    self._fill(p, path, self.sung, 1.0 if hover else 0.85, halo=self.halo)
                elif idx == current:
                    self._fill(p, path, self.unsung, 1.0)
                else:
                    self._fill(p, path, self.unsung, 0.85 if hover else (0.55 if far == 1 else 0.4))
                continue
            done = max(0.0, min(char_progress(line, self._ms) - offset, float(len(text))))
            # Караоке: дальние от текущей строки — тише, внимание на том, что поют сейчас
            alpha = 1.0 if far == 0 or hover else (0.75 if far == 1 else 0.5)
            if done < len(text):
                self._fill(p, path, self.unsung, alpha)
            if done > 0:
                k = int(done)
                edge = fm.horizontalAdvance(text[:k])
                if k < len(text):   # текущая буква закрашивается плавно, слева направо
                    edge += fm.horizontalAdvance(text[k]) * (done - k)
                p.save()
                p.setClipRect(QRectF(x - 6, y - 6, edge + 6 if done < len(text) else 1e5, fm.height() + 12))
                self._fill(p, path, self.sung, alpha, halo=self.halo)
                p.restore()

    @staticmethod
    def _fill(p: QPainter, path: QPainterPath, color: QColor, alpha: float, halo: bool = False) -> None:
        if halo:
            base = halo_for(color)
            h = QColor(base)
            h.setAlphaF(base.alphaF() * alpha)
            pen = QPen(h, 3.2)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            p.strokePath(path, pen)
        c = QColor(color)
        c.setAlphaF(alpha)
        p.fillPath(path, c)
