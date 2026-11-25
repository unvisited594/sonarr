"""Настройки приложения: config.json в папке данных (см. sonar/paths.py)."""
import json
import threading
from pathlib import Path

from .paths import APP_NAME, data_dir


def config_dir() -> Path:
    """Папка данных: рядом с программой в портативной сборке, иначе %APPDATA%/Sonar."""
    path = data_dir()
    path.mkdir(parents=True, exist_ok=True)   # папку могли удалить во время работы (сброс)
    return path


class Config:
    def __init__(self) -> None:
        self.path = config_dir() / "config.json"
        self.data: dict = {"services": {}, "volume": 70, "hide_unavailable": False}
        self._lock = threading.Lock()  # сервисы сохраняют токены из фоновых потоков
        self.frozen = False  # после сброса данных: больше ничего не пишем на диск
        self.load()

    def load(self) -> None:
        try:
            self.data.update(json.loads(self.path.read_text("utf-8")))
        except (OSError, ValueError):
            pass
        self.data.setdefault("services", {})

    def save(self) -> None:
        if self.frozen:
            return
        with self._lock:
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), "utf-8")
            tmp.replace(self.path)

    def service(self, service_id: str) -> dict:
        return dict(self.data["services"].get(service_id, {}))

    def set_service(self, service_id: str, values: dict) -> None:
        self.data["services"][service_id] = dict(values)
        self.save()

    def remove_service(self, service_id: str) -> None:
        self.data["services"].pop(service_id, None)
        self.save()
