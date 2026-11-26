import math

from PyQt6 import sip
from PyQt6.QtCore import QObject, QPointF, QRectF, QSize, Qt, QTimer, QUrl, pyqtProperty, QPropertyAnimation, QEasingCurve, pyqtSignal
from PyQt6.QtGui import QColor, QDesktopServices, QFont, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap
from PyQt6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PyQt6.QtWidgets import (QAbstractButton, QFrame, QGridLayout, QHBoxLayout, QLabel, QMenu, QScrollArea, QSizePolicy, QToolButton,
                             QVBoxLayout, QWidget)

from . import icons
from .theme import C, font


def clear_layout(layout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        if item.widget():
            # deleteLater удаляет лишь на следующем такте — до этого старый виджет виден поверх нового
            item.widget().hide()
            item.widget().deleteLater()
        elif item.layout():
            clear_layout(item.layout())


def muted(text: str = "", role: str = "muted") -> QLabel:
    lbl = QLabel(text)
    lbl.setProperty("role", role)
    return lbl


def fmt_time(ms: int) -> str:
    s = max(0, int(ms // 1000))
    return f"{s // 60}:{s % 60:02d}"


class ImageLoader(QObject):
    """Загрузка обложек: очередь, HTTP/1.1 и повторы.

    На главной разом появляются десятки карточек. По HTTP/2 Qt шлёт все запросы одновременно в одно
    соединение, и CDN отклоняет потоки сверх своего лимита («Server refused a stream») — такие
    обложки не грузились вовсе. Поэтому: не больше MAX_PARALLEL загрузок сразу, HTTP/2 выключен,
    временные сбои повторяются."""
    _instance = None
    MAX_PARALLEL = 6
    RETRIES = 2
    UA = b"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
    # повторять имеет смысл только то, что может пройти со второй попытки
    TRANSIENT = {
        QNetworkReply.NetworkError.RemoteHostClosedError, QNetworkReply.NetworkError.TimeoutError,
        QNetworkReply.NetworkError.TemporaryNetworkFailureError, QNetworkReply.NetworkError.NetworkSessionFailedError,
        QNetworkReply.NetworkError.ProxyTimeoutError, QNetworkReply.NetworkError.UnknownNetworkError,
        QNetworkReply.NetworkError.ServiceUnavailableError, QNetworkReply.NetworkError.InternalServerError,
        QNetworkReply.NetworkError.UnknownServerError, QNetworkReply.NetworkError.ProtocolFailure,
        QNetworkReply.NetworkError.OperationCanceledError,
    }

    @classmethod
    def instance(cls) -> "ImageLoader":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self) -> None:
        super().__init__()
        self.nam = QNetworkAccessManager(self)
        self.nam.setTransferTimeout(20000)
        self.cache: dict[str, QPixmap] = {}
        self.pending: dict[str, list] = {}
        self.failed: set[str] = set()     # окончательно не загрузились (404 и т. п.): не долбим сервер
        self._queue: list[tuple[str, int]] = []
        self._active = 0

    def load(self, url: str, callback) -> None:
        if url in self.cache:
            callback(self.cache[url])
            return
        if url in self.failed:
            return
        if url in self.pending:
            self.pending[url].append(callback)
            return
        self.pending[url] = [callback]
        self._queue.append((url, 0))
        self._pump()

    def _pump(self) -> None:
        while self._queue and self._active < self.MAX_PARALLEL:
            url, attempt = self._queue.pop(0)
            if url not in self.pending:   # все, кому была нужна картинка, уже не ждут
                continue
            req = QNetworkRequest(QUrl(url))
            req.setAttribute(QNetworkRequest.Attribute.Http2AllowedAttribute, False)
            req.setRawHeader(b"User-Agent", self.UA)
            self._active += 1
            reply = self.nam.get(req)
            reply.finished.connect(lambda r=reply, u=url, a=attempt: self._done(r, u, a))

    def _done(self, reply: QNetworkReply, url: str, attempt: int) -> None:
        self._active -= 1
        error = reply.error()
        status = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute) or 0
        pm = QPixmap()
        if error == QNetworkReply.NetworkError.NoError:
            pm.loadFromData(reply.readAll())
        reply.deleteLater()
        transient = error in self.TRANSIENT or status in (429, 500, 502, 503, 504)
        if pm.isNull() and transient and attempt < self.RETRIES:
            # повтор с паузой: даём серверу передохнуть, остальные загрузки идут своим чередом
            QTimer.singleShot(600 * (attempt + 1), lambda: (self._queue.append((url, attempt + 1)), self._pump()))
            self._pump()
            return
        callbacks = self.pending.pop(url, [])
        if pm.isNull():
            if not transient:
                self.failed.add(url)
        else:
            self.cache[url] = pm
            for cb in callbacks:
                cb(pm)
        self._pump()


class Cover(QWidget):
    """Квадратная обложка со скруглёнными углами, грузится асинхронно."""
    clicked = pyqtSignal()

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit()
        super().mouseReleaseEvent(event)

    def __init__(self, size: int, radius: int = 10, parent=None) -> None:
        super().__init__(parent)
        self.setFixedSize(size, size)
        self._radius = radius
        self._pm: QPixmap | None = None
        self._url: str | None = None
        self._unavailable = False
        self._badge: QPixmap | None = None
        self._vinyl = False
        self.angle = 0.0  # поворот пластинки, градусы

    def set_vinyl(self, on: bool) -> None:
        """Обложка-пластинка: чёрный диск с бороздками, обложка — круглая наклейка в центре."""
        self._vinyl = on
        self.update()

    def _paint_vinyl(self, p: QPainter, rect: QRectF) -> None:
        c = rect.center()
        r = rect.width() / 2
        p.translate(c)
        p.rotate(self.angle)
        p.translate(-c)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#111111"))
        p.drawEllipse(c, r, r)
        for k in range(14):  # бороздки
            rr = r * (0.42 + 0.04 * k)
            p.setPen(QPen(QColor(255, 255, 255, 10 + (k % 3) * 6), 1))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(c, rr, rr)
        glare = QPainterPath()  # блик: из-за вращения пластинка «играет» светом
        glare.moveTo(c)
        glare.arcTo(QRectF(c.x() - r, c.y() - r, 2 * r, 2 * r), 30, 28)
        glare.closeSubpath()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 255, 255, 18))
        p.drawPath(glare)
        label = QPainterPath()
        label.addEllipse(c, r * 0.38, r * 0.38)
        p.save()
        p.setClipPath(label)
        if self._pm:
            scaled = self._pm.scaled(int(r * 0.76) + 2, int(r * 0.76) + 2,
                                     Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                     Qt.TransformationMode.SmoothTransformation)
            p.drawPixmap(int(c.x() - scaled.width() / 2), int(c.y() - scaled.height() / 2), scaled)
        else:
            p.fillRect(rect, QColor(C("cover")))
        p.restore()
        p.setBrush(QColor("#111111"))
        p.drawEllipse(c, r * 0.035, r * 0.035)  # отверстие

    def set_badge(self, pm: QPixmap | None) -> None:
        """Иконка сервиса в правом нижнем углу обложки."""
        self._badge = pm
        self.update()

    def set_unavailable(self, on: bool) -> None:
        self._unavailable = on
        self.update()

    def set_pixmap(self, pm: QPixmap | None) -> None:
        """Готовая картинка вместо загрузки по адресу (сгенерированные обложки)."""
        self._url, self._pm = None, pm
        self.update()

    def set_url(self, url: str | None) -> None:
        self._url, self._pm = url, None
        self.update()
        if url:
            ImageLoader.instance().load(url, self._callback(url))

    def _callback(self, url):
        def apply(pm):
            if sip.isdeleted(self) or self._url != url:
                return
            self._pm = pm
            self.update()
        return apply

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform)
        rect = QRectF(self.rect())
        if self._vinyl:
            self._paint_vinyl(p, rect)
            return
        path = QPainterPath()
        path.addRoundedRect(rect, self._radius, self._radius)
        p.setClipPath(path)
        if self._pm:
            scaled = self._pm.scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                     Qt.TransformationMode.SmoothTransformation)
            p.drawPixmap((self.width() - scaled.width()) // 2,
                         (self.height() - scaled.height()) // 2, scaled)
        else:
            p.fillRect(rect, QColor(C("cover")))
            p.setPen(QPen(QColor(C("cover_ring")), max(2, self.width() // 40)))
            r = self.width() * 0.16
            p.drawEllipse(rect.center(), r, r)
        if self._badge is not None:
            size = self._badge.width() / self._badge.devicePixelRatio()
            spot = QRectF(rect.right() - size - 8, rect.bottom() - size - 8, size, size)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(0, 0, 0, 90))  # лёгкая тень, чтобы значок читался на любой обложке
            p.drawRoundedRect(spot.adjusted(-2, -2, 2, 2), size * 0.32, size * 0.32)
            p.drawPixmap(spot.toRect(), self._badge)
        if self._unavailable:
            p.fillRect(rect, QColor(0, 0, 0, 165))
            if self.width() >= 96:  # на мелких обложках плашка не влезет: хватит затемнения
                f = font(12, QFont.Weight.Bold)
                p.setFont(f)
                text = "Недоступно"
                tw = p.fontMetrics().horizontalAdvance(text)
                pill = QRectF(8, 8, tw + 18, 24)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(242, 242, 242, 235))
                p.drawRoundedRect(pill, 12, 12)
                p.setPen(QColor("#111111"))
                p.drawText(pill, Qt.AlignmentFlag.AlignCenter, text)


def generated_cover(seed: str, title: str = "", size: int = 320, round_: bool = False) -> QPixmap:
    """Обложка для того, что придумал сам Sonar: случайные, но постоянные для seed цвета."""
    import hashlib
    h = int(hashlib.md5(seed.encode("utf-8")).hexdigest()[:8], 16)
    hue1 = (h % 360) / 360
    hue2 = (hue1 + 0.12 + ((h >> 9) % 25) / 100) % 1.0
    c1 = QColor.fromHsvF(hue1, 0.72, 0.95)
    c2 = QColor.fromHsvF(hue2, 0.85, 0.55)
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    clip = QPainterPath()
    if round_:
        clip.addEllipse(QRectF(0, 0, size, size))
    else:
        clip.addRect(QRectF(0, 0, size, size))
    p.setClipPath(clip)
    grad = QLinearGradient(0, 0, size, size)
    grad.setColorAt(0, c1)
    grad.setColorAt(1, c2)
    p.fillRect(QRectF(0, 0, size, size), grad)
    glow = QColor(255, 255, 255, 40)   # мягкий блик, чтобы не было плоско
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(glow)
    p.drawEllipse(QPointF(size * (0.2 + (h >> 4) % 50 / 100), size * 0.25), size * 0.45, size * 0.45)
    letter = (title.strip()[:1] or "♪").upper()
    f = font(int(size * 0.42), QFont.Weight.Black, display=True)
    p.setFont(f)
    p.setPen(QColor(255, 255, 255, 230))
    p.drawText(QRectF(0, 0, size, size), Qt.AlignmentFlag.AlignCenter, letter)
    p.end()
    return pm


class ArtistLabel(QLabel):
    """Имя исполнителя, по клику — его профиль. Подчёркивается при наведении."""

    def __init__(self, text: str = "", parent=None) -> None:
        super().__init__(text, parent)
        self.setProperty("role", "muted")
        self._target = None   # (service_id, artist_id, name)

    def set_target(self, service_id: str | None, artist_id: str | None, name: str = "") -> None:
        self._target = (service_id, artist_id, name) if service_id and artist_id else None
        self.setCursor(Qt.CursorShape.PointingHandCursor if self._target else Qt.CursorShape.ArrowCursor)
        self.setToolTip(f"Открыть исполнителя {name}" if self._target else "")

    def enterEvent(self, event) -> None:
        if self._target:
            f = self.font()
            f.setUnderline(True)
            self.setFont(f)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        f = self.font()
        f.setUnderline(False)
        self.setFont(f)
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:
        if self._target and event.button() == Qt.MouseButton.LeftButton:
            event.accept()   # клик по имени не должен запускать трек под ним
        else:
            super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if self._target and event.button() == Qt.MouseButton.LeftButton:
            from . import nav
            event.accept()
            nav.open_artist(*self._target)
        else:
            super().mouseReleaseEvent(event)


def artist_target(track) -> tuple:
    return track.service_id, (track.raw or {}).get("artist_id"), (track.artist or "").split(",")[0].strip()


class TrackCard(QFrame):
    clicked = pyqtSignal()
    menu_requested = pyqtSignal(object)  # глобальная позиция курсора

    COVER = 160

    def __init__(self, track, badge=None, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("card")
        self.setFixedWidth(self.COVER + 16)
        if track.playable:
            self.setCursor(Qt.CursorShape.PointingHandCursor)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 10)
        lay.setSpacing(3)
        cover = Cover(self.COVER, 10)
        cover.set_url(track.artwork_url)
        cover.set_unavailable(not track.playable)
        if badge is not None:
            cover.set_badge(badge)
        lay.addWidget(cover)
        lay.addSpacing(6)
        title = QLabel()
        title.setFont(font(14, QFont.Weight.DemiBold))
        title.setText(title.fontMetrics().elidedText(track.title, Qt.TextElideMode.ElideRight, self.COVER))
        title.setToolTip(track.title)
        sub = ArtistLabel()
        sub.setText(sub.fontMetrics().elidedText(track.artist, Qt.TextElideMode.ElideRight, self.COVER))
        sub.set_target(*artist_target(track))
        if not track.playable:
            title.setProperty("role", "dim")
            sub.setProperty("role", "dim")
        lay.addWidget(title)
        lay.addWidget(sub)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit()
        super().mouseReleaseEvent(event)

    def contextMenuEvent(self, event) -> None:
        self.menu_requested.emit(event.globalPos())


def add_to_playlist_menu(menu: QMenu, track, parent, as_submenu: bool = True) -> None:
    """Подменю «Добавить в плейлист»: локальные плейлисты и создание нового."""
    from PyQt6.QtWidgets import QInputDialog
    from ..library import playlists
    store = playlists()
    if store is None:
        return
    sub = menu.addMenu("Добавить в плейлист") if as_submenu else menu
    for pl in store.all():
        if pl.get("smart"):
            continue   # умные плейлисты собираются сами
        act = sub.addAction(pl["title"])
        if store.contains(pl["id"], track):
            act.setText(f"{pl['title']}  ✓")
            act.setEnabled(False)  # уже там: дубли не добавляем
        else:
            act.triggered.connect(lambda _=False, pid=pl["id"]: store.add(pid, track))
    if store.all():
        sub.addSeparator()

    def create() -> None:
        title, ok = QInputDialog.getText(parent, "Новый плейлист", "Название плейлиста:")
        if ok and title.strip():
            store.add(store.create(title), track)

    sub.addAction("Новый плейлист…").triggered.connect(create)


def show_track_menu(parent, tracks: list, index: int, pos, supports_video: bool,
                    play, video, extra=()) -> None:
    """Контекстное меню трека: общее для карточек и строк поиска."""
    track = tracks[index]
    menu = QMenu(parent)
    act = menu.addAction("Слушать")
    act.setEnabled(track.playable)
    act.triggered.connect(lambda: play(tracks, index))
    if supports_video:
        menu.addAction("Смотреть клип").triggered.connect(lambda: video(track))
    from ..library import likes
    store = likes()
    if store is not None:
        if store.contains(track):
            menu.addAction("Убрать из моих лайков").triggered.connect(lambda: store.remove(track))
        else:
            menu.addAction("Добавить в мои лайки").triggered.connect(lambda: store.add(track))
    add_to_playlist_menu(menu, track, parent)
    if track.permalink:
        def copy_link(url=track.permalink):
            from PyQt6.QtGui import QGuiApplication
            from . import nav
            QGuiApplication.clipboard().setText(url)
            nav.toast("Ссылка на трек скопирована")
        menu.addAction("Скопировать ссылку").triggered.connect(copy_link)
    from ..downloads import SERVICE_ID, downloads
    dl = downloads()
    if dl is not None and track.service_id == SERVICE_ID:
        if dl.has(track.id):
            menu.addAction("Удалить загрузку").triggered.connect(lambda: dl.remove(track.id))
        elif track.id in dl.pending:
            menu.addAction("Скачивается…").setEnabled(False)
        else:
            menu.addAction("Скачать для офлайна").triggered.connect(lambda: dl.start(track))
    for text, action in extra:  # действия конкретного места, например «Убрать из плейлиста»
        menu.addAction(text).triggered.connect(action)
    if track.permalink:
        menu.addAction("Открыть в браузере").triggered.connect(
            lambda: QDesktopServices.openUrl(QUrl(track.permalink)))
    menu.exec(pos)


class TrackRow(QFrame):
    """Строка трека для результатов поиска."""
    clicked = pyqtSignal()
    menu_requested = pyqtSignal(object)

    def __init__(self, track, service_icon_pm=None, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("card")
        if track.playable:
            self.setCursor(Qt.CursorShape.PointingHandCursor)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 6, 14, 6)
        lay.setSpacing(12)
        cover = Cover(44, 8)
        cover.set_url(track.artwork_url)
        cover.set_unavailable(not track.playable)
        lay.addWidget(cover)
        text = QVBoxLayout()
        text.setSpacing(0)
        title = QLabel(track.title)
        title.setFont(font(14, QFont.Weight.DemiBold))
        sub = ArtistLabel(track.artist)
        sub.set_target(*artist_target(track))
        if not track.playable:
            title.setProperty("role", "dim")
            sub.setProperty("role", "dim")
        text.addWidget(title)
        text.addWidget(sub)
        lay.addLayout(text, 1)
        if not track.playable:
            lay.addWidget(muted("Недоступно"))
        if service_icon_pm is not None:
            icon = QLabel()
            icon.setPixmap(service_icon_pm)
            icon.setToolTip("Источник трека")
            lay.addWidget(icon)
        dur = muted(fmt_time(track.duration_ms) if track.duration_ms else "")
        dur.setFixedWidth(44)
        dur.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        lay.addWidget(dur)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit()
        super().mouseReleaseEvent(event)

    def contextMenuEvent(self, event) -> None:
        self.menu_requested.emit(event.globalPos())


class CardGrid(QWidget):
    """Сетка карточек: число колонок подстраивается под ширину."""

    def __init__(self, step: int, parent=None) -> None:
        super().__init__(parent)
        self._step = step
        self._cards: list = []
        self._columns = 0
        self.grid = QGridLayout(self)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setHorizontalSpacing(4)
        self.grid.setVerticalSpacing(10)
        self.grid.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)

    def set_cards(self, cards: list) -> None:
        for card in self._cards:
            card.deleteLater()
        self._cards = list(cards)
        self._columns = 0
        self._relayout()

    def _relayout(self) -> None:
        columns = max(1, self.width() // self._step) if self.width() > 0 else 6
        if columns == self._columns and self.grid.count() == len(self._cards):
            return
        self._columns = columns
        while self.grid.count():
            self.grid.takeAt(0)
        for i, card in enumerate(self._cards):
            self.grid.addWidget(card, i // columns, i % columns)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._relayout()


class PlaylistCard(QFrame):
    clicked = pyqtSignal()
    COVER = 160

    def __init__(self, title: str, subtitle: str, cover_url: str | None, badge=None,
                 parent=None, seed: str | None = None, round_: bool = False) -> None:
        super().__init__(parent)
        self.setObjectName("card")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedWidth(self.COVER + 16)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 10)
        lay.setSpacing(3)
        cover = Cover(self.COVER, self.COVER // 2 if round_ else 10)
        if cover_url:
            cover.set_url(cover_url)
        elif seed is not None:   # своя обложка Sonar: случайные постоянные цвета
            cover.set_pixmap(generated_cover(seed, title, self.COVER * 2, round_))
        if badge is not None:
            cover.set_badge(badge)
        lay.addWidget(cover)
        lay.addSpacing(6)
        name = QLabel()
        name.setFont(font(14, QFont.Weight.DemiBold))
        name.setText(name.fontMetrics().elidedText(title, Qt.TextElideMode.ElideRight, self.COVER))
        name.setToolTip(title)
        lay.addWidget(name)
        lay.addWidget(muted(subtitle))

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit()
        super().mouseReleaseEvent(event)


class CardShelf(QWidget):
    """Горизонтальная полка готовых карточек (плейлисты, альбомы) со стрелками, как у треков."""

    def __init__(self, title: str, cards: list, tag_cls=None, parent=None) -> None:
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        head = QHBoxLayout()
        head.setContentsMargins(8, 0, 0, 0)
        lbl = QLabel(title)
        lbl.setFont(font(22, QFont.Weight.Bold, display=True))
        head.addWidget(lbl)
        if tag_cls is not None:
            from .icons import service_icon
            icon = QLabel()
            icon.setPixmap(service_icon(tag_cls, 18))
            head.addSpacing(6)
            head.addWidget(icon)
            head.addWidget(muted(tag_cls.name))
        head.addStretch(1)
        lay.addLayout(head)
        scroll = _HScroll()
        scroll.setWidgetResizable(True)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        row_widget = QWidget()
        row = QHBoxLayout(row_widget)
        row.setContentsMargins(0, 0, 0, 6)
        row.setSpacing(4)
        for card in cards:
            row.addWidget(card)
        row.addStretch(1)
        scroll.setWidget(row_widget)
        scroll.setFixedHeight(row_widget.sizeHint().height() + 12)
        lay.addWidget(scroll)


def tracks_word(n: int) -> str:
    if n % 10 == 1 and n % 100 != 11:
        return f"{n} трек"
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return f"{n} трека"
    return f"{n} треков"


class GroupHeader(QFrame):
    """Заголовок сворачиваемой группы: шеврон, иконка, название, счётчик."""
    toggled = pyqtSignal(bool)

    def __init__(self, icon_pm, title: str, count: str = "", expanded: bool = True,
                 parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("groupHeader")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._expanded = expanded
        lay = QHBoxLayout(self)
        lay.setContentsMargins(6, 6, 12, 6)
        lay.setSpacing(10)
        self.chevron = QLabel()
        lay.addWidget(self.chevron)
        icon = QLabel()
        icon.setPixmap(icon_pm)
        lay.addWidget(icon)
        name = QLabel(title)
        name.setFont(font(17, QFont.Weight.Bold, display=True))
        lay.addWidget(name)
        if count:
            lay.addWidget(muted(count), 0, Qt.AlignmentFlag.AlignBottom)
        lay.addStretch(1)
        self._update()

    def _update(self) -> None:
        from . import icons
        self.chevron.setPixmap(icons.pixmap("chevron" if self._expanded else "chevron_right",
                                            C("muted"), 18))
        self.setToolTip("Свернуть" if self._expanded else "Развернуть")

    def toggle(self) -> None:
        self._expanded = not self._expanded
        self._update()
        self.toggled.emit(self._expanded)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.position().toPoint()):
            self.toggle()
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key.Key_Space, Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.toggle()
        else:
            super().keyPressEvent(event)


class Spinner(QObject):
    """Крутит иконку на кнопке, пока идёт работа: видно, что нажатие сработало."""

    def __init__(self, button, icon_name: str, color_key: str = "text", size: int = 18) -> None:
        super().__init__(button)
        self.button, self.icon_name, self.color_key, self.size = button, icon_name, color_key, size
        self._angle = 0
        self._timer = QTimer(self)
        self._timer.setInterval(30)
        self._timer.timeout.connect(self._tick)

    def _pixmap(self, angle: float) -> QPixmap:
        from . import icons
        base = icons.pixmap(self.icon_name, C(self.color_key), self.size * 2)
        out = QPixmap(base.size())
        out.fill(Qt.GlobalColor.transparent)
        p = QPainter(out)
        p.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform)
        p.translate(out.width() / 2, out.height() / 2)
        p.rotate(angle)
        p.translate(-out.width() / 2, -out.height() / 2)
        p.drawPixmap(0, 0, base)
        p.end()
        out.setDevicePixelRatio(2)
        return out

    @property
    def spinning(self) -> bool:
        return self._timer.isActive()

    def start(self) -> None:
        self._angle = 0
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()
        from PyQt6.QtGui import QIcon
        self.button.setIcon(QIcon(self._pixmap(0)))

    def _tick(self) -> None:
        if sip.isdeleted(self.button):
            self._timer.stop()
            return
        from PyQt6.QtGui import QIcon
        self._angle = (self._angle + 12) % 360
        self.button.setIcon(QIcon(self._pixmap(self._angle)))


class Toggle(QAbstractButton):
    """Переключатель: дорожка с бегунком, анимация по нажатию."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(44, 24)
        self._pos = 0.0
        self._anim = QPropertyAnimation(self, b"knob", self)
        self._anim.setDuration(140)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.toggled.connect(self._animate)

    def _get_knob(self) -> float:
        return self._pos

    def _set_knob(self, value: float) -> None:
        self._pos = value
        self.update()

    knob = pyqtProperty(float, _get_knob, _set_knob)

    def setChecked(self, on: bool) -> None:  # без анимации при начальной установке
        super().setChecked(on)
        self._anim.stop()
        self._set_knob(1.0 if on else 0.0)

    def _animate(self, on: bool) -> None:
        self._anim.stop()
        self._anim.setStartValue(self._pos)
        self._anim.setEndValue(1.0 if on else 0.0)
        self._anim.start()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        on_col, off_col = QColor(C("accent")), QColor(C("toggle_off"))
        track = QColor(
            int(off_col.red() + (on_col.red() - off_col.red()) * self._pos),
            int(off_col.green() + (on_col.green() - off_col.green()) * self._pos),
            int(off_col.blue() + (on_col.blue() - off_col.blue()) * self._pos))
        p.setBrush(track)
        p.drawRoundedRect(QRectF(0, 0, self.width(), self.height()), 12, 12)
        d = self.height() - 6
        x = 3 + (self.width() - d - 6) * self._pos
        p.setBrush(QColor(C("on_accent")) if self._pos > 0.5 else QColor(C("toggle_knob_off")))
        p.drawEllipse(QRectF(x, 3, d, d))
        if self.hasFocus():
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(QColor(C("muted")), 1))
            p.drawRoundedRect(QRectF(0.5, 0.5, self.width() - 1, self.height() - 1), 12, 12)

    def sizeHint(self) -> QSize:
        return QSize(44, 24)


class _HScroll(QScrollArea):
    """Горизонтальная лента: колесо без Shift прокручивает страницу, а не ленту."""

    def wheelEvent(self, event) -> None:
        horizontal = event.angleDelta().x()
        if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            horizontal = horizontal or event.angleDelta().y()
        if horizontal:
            bar = self.horizontalScrollBar()
            bar.setValue(bar.value() - horizontal)
            event.accept()
        else:
            event.ignore()


class Shelf(QWidget):
    play_requested = pyqtSignal(list, int)
    video_requested = pyqtSignal(object)

    def __init__(self, title: str, tracks: list, service_cls=None,
                 supports_video: bool = False, parent=None) -> None:
        super().__init__(parent)
        self._supports_video = supports_video
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        head = QHBoxLayout()
        head.setContentsMargins(8, 0, 0, 0)
        head.setSpacing(10)
        lbl = QLabel(title)
        lbl.setFont(font(22, QFont.Weight.Bold, display=True))
        head.addWidget(lbl)
        if service_cls is not None:  # откуда эта полка: иконка и название сервиса
            from .icons import service_icon
            source = QHBoxLayout()
            source.setSpacing(6)
            source.setContentsMargins(4, 0, 0, 3)
            icon = QLabel()
            icon.setPixmap(service_icon(service_cls, 18))
            source.addWidget(icon)
            source.addWidget(muted(service_cls.name))
            head.addLayout(source)
            head.setAlignment(source, Qt.AlignmentFlag.AlignBottom)
        head.addStretch(1)
        self.prev_btn = self._arrow("chevron_left", "Назад", -1)
        self.next_btn = self._arrow("chevron_right", "Вперёд", 1)
        head.addWidget(self.prev_btn)
        head.addWidget(self.next_btn)
        lay.addLayout(head)

        scroll = _HScroll()
        self._scroll = scroll
        self._anim = None
        scroll.setWidgetResizable(True)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        row_widget = QWidget()
        row = QHBoxLayout(row_widget)
        row.setContentsMargins(0, 0, 0, 6)
        row.setSpacing(4)
        for i, track in enumerate(tracks):
            card = TrackCard(track)
            if track.playable:
                card.clicked.connect(lambda i=i: self.play_requested.emit(tracks, i))
            card.menu_requested.connect(lambda pos, i=i: self._menu(tracks, i, pos))
            row.addWidget(card)
        row.addStretch(1)
        scroll.setWidget(row_widget)
        scroll.setFixedHeight(row_widget.sizeHint().height() + 12)
        lay.addWidget(scroll)
        bar = scroll.horizontalScrollBar()
        bar.valueChanged.connect(self._update_arrows)
        bar.rangeChanged.connect(self._update_arrows)
        self._update_arrows()

    def _arrow(self, icon_name: str, tip: str, direction: int) -> QToolButton:
        from . import icons
        b = QToolButton()
        b.setObjectName("shelfArrow")
        b.setFixedSize(32, 32)
        b.setIconSize(QSize(18, 18))
        b.setIcon(icons.icon(icon_name, C("text")))
        b.setToolTip(tip)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.clicked.connect(lambda: self._page(direction))
        return b

    def _page(self, direction: int) -> None:
        """Листаем на ширину видимой части минус одна карточка, чтобы не терять место."""
        bar = self._scroll.horizontalScrollBar()
        step = max(TrackCard.COVER, self._scroll.viewport().width() - TrackCard.COVER)
        target = max(bar.minimum(), min(bar.maximum(), bar.value() + direction * step))
        if self._anim is not None:
            self._anim.stop()
        self._anim = QPropertyAnimation(bar, b"value", self)
        self._anim.setDuration(260)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.setStartValue(bar.value())
        self._anim.setEndValue(target)
        self._anim.start()

    def _update_arrows(self, *_args) -> None:
        bar = self._scroll.horizontalScrollBar()
        scrollable = bar.maximum() > bar.minimum()
        self.prev_btn.setVisible(scrollable)
        self.next_btn.setVisible(scrollable)
        self.prev_btn.setEnabled(bar.value() > bar.minimum())
        self.next_btn.setEnabled(bar.value() < bar.maximum())


    def _menu(self, tracks: list, index: int, pos) -> None:
        show_track_menu(self, tracks, index, pos, self._supports_video,
                        self.play_requested.emit, self.video_requested.emit)


class WaveArt(QWidget):
    """Обложка «Моей волны»: линии, которые плывут, пока волна играет."""

    def __init__(self, size: int = 176, parent=None) -> None:
        super().__init__(parent)
        self.setFixedSize(size, size)
        self._phase = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(33)
        self._timer.timeout.connect(self._tick)

    def set_playing(self, on: bool) -> None:
        if on:
            self._timer.start()
        else:
            self._timer.stop()

    def _tick(self) -> None:
        self._phase += 0.05
        self.update()

    def paintEvent(self, _event) -> None:
        w, h = self.width(), self.height()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        clip = QPainterPath()
        clip.addRoundedRect(QRectF(0, 0, w, h), 22, 22)
        p.setClipPath(clip)
        grad = QLinearGradient(0, 0, w, h)
        grad.setColorAt(0, QColor(C("wave_from")))
        grad.setColorAt(1, QColor(C("wave_to")))
        p.fillRect(self.rect(), grad)
        for i in range(7):
            y0 = h * (0.2 + i * 0.1)
            amp = h * (0.018 + 0.04 * (0.5 + 0.5 * math.sin(self._phase * 0.6 + i * 0.8)))
            line = QColor(C("wave_line"))
            line.setAlpha(50 + i * 28)
            pen = QPen(line, 2.2)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            path = QPainterPath(QPointF(0, y0 + amp * math.sin(self._phase + i * 0.55)))
            for x in range(4, w + 4, 4):
                path.lineTo(x, y0 + amp * math.sin(x / w * 2.4 * math.pi + self._phase + i * 0.55))
            p.drawPath(path)


class Hero(QWidget):
    play_clicked = pyqtSignal()
    random_clicked = pyqtSignal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(28)
        self.art = WaveArt(176)
        self.random_btn = QToolButton(self.art)
        self.random_btn.setObjectName("artPlay")
        self.random_btn.setFixedSize(48, 48)
        self.random_btn.setIconSize(QSize(22, 22))
        self.random_btn.move(176 - 48 - 12, 176 - 48 - 12)
        self.random_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.random_btn.setToolTip("Случайные 50 треков из всех сервисов")
        self.random_btn.clicked.connect(self.random_clicked)
        lay.addWidget(self.art, 0, Qt.AlignmentFlag.AlignTop)

        col = QVBoxLayout()
        col.setSpacing(10)
        title = QLabel('<div style="line-height:86%">Моя<br>волна</div>')
        title.setFont(font(56, QFont.Weight.Black, display=True))
        col.addWidget(title)
        self.subtitle = muted()
        self.subtitle.setFont(font(14, QFont.Weight.DemiBold))
        col.addWidget(self.subtitle)
        col.addStretch(1)
        lay.addLayout(col, 1)

        box = QWidget()
        box.setFixedSize(190, 176)
        box.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.previews = []
        for x, y in ((112, 4), (24, 62), (118, 108)):
            c = Cover(64, 14, box)
            c.move(x, y)
            c.hide()
            self.previews.append(c)
        lay.addWidget(box)

        self.play = QToolButton()
        self.play.setObjectName("heroPlay")
        self.play.setFixedSize(80, 80)
        self.play.setIconSize(QSize(34, 34))
        self._playing = False
        self.play.setIcon(icons.icon("play", C("on_accent")))
        self.random_btn.setIcon(icons.icon("play", C("on_accent")))
        self.play.setCursor(Qt.CursorShape.PointingHandCursor)
        self.play.setToolTip("Слушать «Мою волну»")
        self.play.clicked.connect(self.play_clicked)
        lay.addWidget(self.play, 0, Qt.AlignmentFlag.AlignVCenter)

    def set_preview(self, tracks: list) -> None:
        for i, cover in enumerate(self.previews):
            if i < len(tracks):
                cover.set_url(tracks[i].artwork_url)
                cover.show()
            else:
                cover.hide()

    def set_subtitle(self, text: str) -> None:
        self.subtitle.setText(text)

    def set_playing(self, on: bool) -> None:
        self._playing = on
        self.play.setIcon(icons.icon("pause" if on else "play", C("on_accent")))
        self.art.set_playing(on)

    def apply_theme(self) -> None:
        self.set_playing(self._playing)
        self.random_btn.setIcon(icons.icon("play", C("on_accent")))
        self.art.update()


class FitHeight(QObject):
    """Чтобы в прокрутке ничего не сплющивалось на неполноэкранном окне.

    Подписи с переносом строк на узком окне занимают больше строк, чем Qt закладывает при
    расчёте размера содержимого, и недостающее отнимается у соседей — кнопок, карточек.
    Расчёт Qt «высота по ширине» здесь занижен, поэтому к нему прибавляется поправка: после
    раскладки ищем виджет, получивший меньше своего минимума, и увеличиваем поправку на нехватку.

    Без дрожания: размер содержимого выставляет сама прокрутка — здесь задаётся только минимум;
    поправка при той же ширине лишь растёт (сбрасывается при смене ширины), а минимум меняется,
    только если значение действительно другое. Прежний вариант каждый раз пересчитывал с нуля,
    и содержимое прыгало между двумя высотами несколько раз в секунду."""

    def __init__(self, scroll) -> None:
        super().__init__(scroll)
        self.scroll = scroll
        scroll.viewport().installEventFilter(self)
        if scroll.widget() is not None:
            scroll.widget().installEventFilter(self)
        self._width = -1
        self._extra = 0   # поправка к расчёту Qt при текущей ширине
        self._timer = QTimer(self, singleShot=True, interval=0)   # пачка событий — один пересчёт
        self._timer.timeout.connect(self.fit)

    def eventFilter(self, obj, event) -> bool:
        from PyQt6.QtCore import QEvent
        if event.type() in (QEvent.Type.Resize, QEvent.Type.LayoutRequest, QEvent.Type.Show):
            self._timer.start()
        return False

    @staticmethod
    def _deficit(root) -> int:
        """Насколько не хватает самому сжатому видимому виджету (0 — всем хватает)."""
        worst = 0
        for ch in root.findChildren(QWidget):
            if ch.isVisibleTo(root):
                need = ch.minimumSizeHint().height()
                if need > 0:
                    worst = max(worst, need - ch.height())
        return worst

    def fit(self) -> None:
        content = self.scroll.widget()
        lay = content.layout() if content is not None else None
        if lay is None or not self.scroll.isVisible():
            return
        width = self.scroll.viewport().width()
        if width != self._width:   # другая ширина — переносы другие, поправку считаем заново
            self._width, self._extra = width, 0
        base = lay.totalMinimumSize().height()
        if lay.hasHeightForWidth():
            base = max(base, lay.totalHeightForWidth(width))
        # раскладка уже применена прокруткой: если кому-то не хватило — поправка растёт
        if content.minimumHeight() == base + self._extra and content.height() >= base:
            missing = self._deficit(content)
            if missing > 1:
                self._extra += missing
        target = base + self._extra
        if content.minimumHeight() != target:
            content.setMinimumHeight(target)   # дальше прокрутка сама растянет содержимое


