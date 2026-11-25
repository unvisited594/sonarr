"""Вход через встроенный браузер: пользователь логинится на сайте сервиса,
приложение забирает cookie с токеном и закрывает окно.

Нужен пакет PyQt6-WebEngine. Без него остаётся ручной ввод токена.
"""
from PyQt6.QtCore import QTimer, QUrl
from PyQt6.QtWidgets import QApplication, QDialog, QVBoxLayout

from .widgets import muted

try:
    from PyQt6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile
    from PyQt6.QtWebEngineWidgets import QWebEngineView
    AVAILABLE = True
except ImportError:
    AVAILABLE = False

if AVAILABLE:
    class _RedirectCatcher(QWebEnginePage):
        """Перехватывает переход на redirect_uri OAuth: сервер на 127.0.0.1 не нужен."""

        def __init__(self, profile, parent, prefix: str, on_redirect) -> None:
            super().__init__(profile, parent)
            self._prefix, self._on_redirect = prefix, on_redirect

        def acceptNavigationRequest(self, url, nav_type, is_main_frame) -> bool:
            if url.toString().startswith(self._prefix):
                self._on_redirect(url.toString())
                return False
            return super().acceptNavigationRequest(url, nav_type, is_main_frame)


UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0 Safari/537.36")
_profile = None


def _shared_profile():
    """Профиль без имени живёт только в памяти: на диске сессия не остаётся."""
    global _profile
    if _profile is None:
        _profile = QWebEngineProfile(QApplication.instance())
        _profile.setHttpUserAgent(UA)
    return _profile


class BrowserLoginDialog(QDialog):
    def __init__(self, spec, service_name: str, parent=None) -> None:
        super().__init__(parent)
        self.spec = spec
        self.token: str | None = None
        self._cookies: dict[str, str] = {}
        self._armed = False
        self.setWindowTitle(f"Вход в {service_name}")
        self.resize(560, 760)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 12, 0, 0)
        lay.setSpacing(10)
        hint = muted(f"Войдите в аккаунт {service_name}. Окно закроется само, "
                     "как только вход завершится.")
        hint.setWordWrap(True)
        hint.setContentsMargins(16, 0, 16, 0)
        lay.addWidget(hint)

        profile = _shared_profile()
        profile.setHttpUserAgent(spec.user_agent or UA)
        self.store = profile.cookieStore()
        self.store.deleteAllCookies()  # начинаем с чистого листа, в т.ч. после «Отключить»
        self.store.cookieAdded.connect(self._on_cookie)
        self.view = QWebEngineView(self)
        if spec.redirect_prefix:
            page = _RedirectCatcher(profile, self.view, spec.redirect_prefix, self._on_redirect)
        else:
            page = QWebEnginePage(profile, self.view)
        self.view.setPage(page)
        lay.addWidget(self.view, 1)
        self.view.load(QUrl(spec.url))

    def _on_redirect(self, url: str) -> None:
        if not self.token:
            self.token = url
            QTimer.singleShot(0, self.accept)

    def _on_cookie(self, cookie) -> None:
        if self.spec.redirect_prefix:
            return
        domain = cookie.domain().lstrip(".")
        if domain != self.spec.domain and not domain.endswith("." + self.spec.domain):
            return
        name = cookie.name().data().decode(errors="ignore")
        value = cookie.value().data().decode(errors="ignore").strip()
        if not value:
            return
        self._cookies[name] = value
        if name == self.spec.cookie and not self._armed:
            self._armed = True
            # после входа сайт ставит ещё пачку cookie: даём им прийти
            QTimer.singleShot(1500 if self.spec.collect_all else 0, self._finish)

    def _finish(self) -> None:
        if self.spec.collect_all:
            self.token = "; ".join(f"{k}={v}" for k, v in self._cookies.items())
        else:
            self.token = self._cookies.get(self.spec.cookie)
        self.accept()

    def done(self, result: int) -> None:
        try:
            self.store.cookieAdded.disconnect(self._on_cookie)
        except TypeError:
            pass
        self.view.stop()
        super().done(result)
