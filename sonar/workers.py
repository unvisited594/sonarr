"""Запуск сетевых операций в фоне, результат приходит в GUI-поток через сигналы."""
from PyQt6.QtCore import QObject, QRunnable, QThreadPool, pyqtSignal

_active: set = set()


class _Signals(QObject):
    done = pyqtSignal(object)
    failed = pyqtSignal(str)


class _Task(QRunnable):
    def __init__(self, fn, args, kwargs):
        super().__init__()
        self.setAutoDelete(False)
        self.fn, self.args, self.kwargs = fn, args, kwargs
        self.signals = _Signals()

    def run(self) -> None:
        try:
            result = self.fn(*self.args, **self.kwargs)
        except Exception as exc:  # показываем пользователю, а не роняем поток
            self._emit("failed", str(exc) or exc.__class__.__name__)
            return
        self._emit("done", result)

    def _emit(self, name: str, value) -> None:
        # Если приложение уже закрывается, получателя нет: результат просто отбрасываем.
        try:
            getattr(self.signals, name).emit(value)
        except RuntimeError:
            pass


def _pool() -> QThreadPool:
    """Почти все фоновые задачи ждут сеть, а не процессор. По умолчанию потоков столько, сколько
    ядер, и на 2–4-ядерном ПК один медленный сервис задерживал загрузку остальных."""
    pool = QThreadPool.globalInstance()
    if pool.maxThreadCount() < 16:
        pool.setMaxThreadCount(16)
    return pool


def run_async(fn, *args, on_done=None, on_error=None, **kwargs):
    task = _Task(fn, args, kwargs)
    _active.add(task)
    if on_done:
        task.signals.done.connect(on_done)
    if on_error:
        task.signals.failed.connect(on_error)
    task.signals.done.connect(lambda _=None: _active.discard(task))
    task.signals.failed.connect(lambda _=None: _active.discard(task))
    _pool().start(task)
    return task
