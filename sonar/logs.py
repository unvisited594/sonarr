"""Журнал работы: %APPDATA%/Sonar/logs/sonar.log (текущий запуск) и sonar.prev.log (прошлый).

В один файл попадают:
  * события Sonar (модуль logging, логгер "sonar");
  * сообщения Qt (qt.multimedia.*, qt.network.* и т. п.);
  * вывод FFmpeg — он пишет прямо в поток ошибок процесса, мимо Python, поэтому сам дескриптор 2
    перенаправляется в файл;
  * необработанные исключения Python (с трассировкой) — они больше не роняют программу молча.
"""
import faulthandler
import logging
import os
import platform
import sys
from pathlib import Path

from .config import APP_NAME, config_dir

log = logging.getLogger("sonar")
_file = None


def log_dir() -> Path:
    path = config_dir() / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def log_path() -> Path:
    return log_dir() / "sonar.log"


def setup_logging() -> Path:
    global _file
    path = log_path()
    prev = log_dir() / "sonar.prev.log"
    try:
        if path.exists():
            path.replace(prev)   # прошлый запуск сохраняем рядом
    except OSError:
        pass
    _file = open(path, "a", encoding="utf-8", buffering=1, errors="replace")
    try:  # FFmpeg и прочий C-код пишут в дескриптор 2 — направляем его в файл
        sys.stderr.flush() if sys.stderr else None
        os.dup2(_file.fileno(), 2)
    except OSError:
        pass
    sys.stderr = _file
    faulthandler.enable(_file)   # даже при аварийном падении в журнале останется трассировка

    logging.basicConfig(level=logging.INFO, stream=_file, force=True,
                        format="%(asctime)s.%(msecs)03d %(levelname)-7s %(name)s: %(message)s",
                        datefmt="%H:%M:%S")
    for noisy in ("urllib3", "yandex_music", "ytmusicapi", "PIL"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    from PyQt6.QtCore import QtMsgType, qInstallMessageHandler
    levels = {QtMsgType.QtDebugMsg: logging.DEBUG, QtMsgType.QtInfoMsg: logging.INFO,
              QtMsgType.QtWarningMsg: logging.WARNING, QtMsgType.QtCriticalMsg: logging.ERROR,
              QtMsgType.QtFatalMsg: logging.CRITICAL}
    qt_log = logging.getLogger("qt")

    def qt_handler(kind, context, message):
        qt_log.log(levels.get(kind, logging.INFO), "%s%s", f"[{context.category}] " if context.category
                   and context.category != "default" else "", message)
    qInstallMessageHandler(qt_handler)

    def excepthook(exc_type, exc, tb):
        # PyQt роняет программу на необработанном исключении в слоте; с этим хуком — пишем и живём
        log.error("Необработанная ошибка", exc_info=(exc_type, exc, tb))
    sys.excepthook = excepthook

    from PyQt6.QtCore import PYQT_VERSION_STR, QT_VERSION_STR
    log.info("=== %s запущен: Python %s, PyQt %s, Qt %s, %s, %s ===", APP_NAME, platform.python_version(),
             PYQT_VERSION_STR, QT_VERSION_STR, platform.platform(),
             "exe" if getattr(sys, "frozen", False) else "из исходников")
    return path


def host(url: str) -> str:
    """Для журнала: только сервер, без пути и параметров (в них бывают токены)."""
    from urllib.parse import urlparse
    try:
        return urlparse(url).netloc or url[:40]
    except ValueError:
        return "?"
