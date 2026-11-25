import os
import sys

from PyQt6.QtCore import QCoreApplication, Qt
from PyQt6.QtWidgets import QApplication

from sonar.config import APP_NAME
from sonar.ui.theme import apply_theme
from sonar.ui.main_window import MainWindow


def main() -> int:
    # Chromium внутри окна входа сыплет в консоль служебными ошибками (WebGPU, отказы
    # TLS к трекерам) — на работу они не влияют, оставляем только фатальные.
    os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--log-level=3")
    # Нужно встроенному браузеру (вход в сервисы) до создания QApplication.
    QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    # Видео (фон плеера, клипы) декодируется процессором, а не видеокартой. Кадры из памяти
    # видеокарты (D3D11) Qt переводит в картинку по отдельному, менее надёжному пути; кадры
    # в обычной памяти проверены, а видео до 720p процессор тянет без заметной нагрузки.
    # На звук не влияет. Переменную можно переопределить в окружении.
    os.environ.setdefault("QT_FFMPEG_DECODING_HW_DEVICE_TYPES", "none")
    from sonar.logs import setup_logging
    setup_logging()  # первым делом: дальше всё, включая FFmpeg, пишется в журнал
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    apply_theme(app)
    try:
        win = MainWindow()
    except Exception as exc:   # не падаем молча: показываем причину и где журнал
        import logging
        import traceback
        from PyQt6.QtWidgets import QMessageBox
        from sonar.logs import log_path
        logging.getLogger("sonar").error("Не удалось запустить Sonar", exc_info=True)
        QMessageBox.critical(None, "Sonar не запустился",
                             f"{exc.__class__.__name__}: {exc}\n\n"
                             f"Подробности в журнале:\n{log_path()}\n\n"
                             + "".join(traceback.format_exception_only(type(exc), exc)).strip())
        return 1
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
