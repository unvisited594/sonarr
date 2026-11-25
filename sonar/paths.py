"""Где Sonar хранит данные. Единственное место, где вычисляются пути.

Портативный режим (сборка build.py по умолчанию): рядом с Sonar.exe лежит файл portable.txt,
и все данные — настройки, лайки, плейлисты, история, журнал, скачанные треки — хранятся в папке
data рядом с программой. Папку программы можно переносить куда угодно: данные едут вместе с ней.
Нет папки data — создаётся новая, как при первом запуске.

Обычный режим (запуск из исходников или без portable.txt): данные в профиле пользователя,
%APPDATA%\\Sonar.

Если выбранная папка недоступна для записи (чужой профиль, Program Files, флешка только для
чтения), берётся следующая в списке — Sonar не падает, а запоминает причину в fallback_reason.
"""
import os
import sys
import tempfile
import uuid
from pathlib import Path

APP_NAME = "Sonar"
MARKER = "portable.txt"

_data_dir: Path | None = None
fallback_reason = ""   # почему пришлось взять не ту папку, что хотели (для уведомления и журнала)


def app_dir() -> Path:
    """Папка программы: рядом с Sonar.exe у сборки, корень проекта у исходников."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def is_portable() -> bool:
    return (app_dir() / MARKER).exists()


def _user_dir() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home() / ".config")
    return Path(base) / APP_NAME


def _writable(path: Path) -> bool:
    """Можно ли создать папку и записать в неё файл (права проверяем делом, а не по атрибутам)."""
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / f".write-test-{uuid.uuid4().hex[:8]}"
        probe.write_text("ok", "utf-8")
        probe.unlink()
        return True
    except OSError:
        return False


def data_dir() -> Path:
    global _data_dir, fallback_reason
    if _data_dir is not None:
        return _data_dir
    candidates = []
    if is_portable():
        candidates.append(app_dir() / "data")
    candidates += [_user_dir(), Path(tempfile.gettempdir()) / APP_NAME]
    for i, path in enumerate(candidates):
        if _writable(path):
            if i > 0 and is_portable():
                fallback_reason = (f"В папку программы нельзя записывать ({app_dir()}), поэтому данные "
                                   f"хранятся в {path}. Перенесите Sonar туда, где у вас есть права "
                                   f"на запись, чтобы данные лежали рядом с программой.")
            elif i > 0:
                fallback_reason = f"Папка данных по умолчанию недоступна, используется {path}."
            _data_dir = path
            return path
    # совсем никуда нельзя писать — работаем во временной папке, пусть и без сохранения
    _data_dir = Path(tempfile.mkdtemp(prefix="sonar-"))
    fallback_reason = "Не нашлось папки, куда можно записывать: настройки не сохранятся после выхода."
    return _data_dir


def downloads_dir() -> Path:
    """Скачанные треки: в портативном режиме — data/downloads рядом с программой."""
    if is_portable():
        target = data_dir() / "downloads"
        old = app_dir() / "downloads"   # прежние сборки клали загрузки прямо рядом с exe — переносим
        if old.is_dir() and not target.exists():
            try:
                old.rename(target)
            except OSError:
                pass
    elif getattr(sys, "frozen", False):
        target = data_dir() / "downloads"
    else:
        target = app_dir() / "downloads"   # из исходников — как раньше, в папке проекта
    if not _writable(target):
        target = data_dir() / "downloads"
        target.mkdir(parents=True, exist_ok=True)
    return target


def reset_cache() -> None:
    """Для тестов: заново определить папку данных."""
    global _data_dir, fallback_reason
    _data_dir, fallback_reason = None, ""
