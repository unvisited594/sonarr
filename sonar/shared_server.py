"""Общий сервер Navidrome, который подключается у всех сам, без ввода пароля.

Где Sonar его ищет (первый найденный побеждает):
1. shared_navidrome.json рядом с Sonar.exe — чтобы сменить сервер без пересборки;
2. sonar/assets/shared_navidrome.json внутри сборки — его кладёт build.py из файла
   shared_navidrome.json в корне проекта.

Формат: {"url": "...", "user": "...", "password": "...", "name": "Общий сервер"} или вместо пароля
готовые {"token": "...", "salt": "..."} (так делает build.py, чтобы сам пароль не попал в exe).
Важно: токен даёт тот же доступ, что и пароль, и вытащить его из программы можно. Поэтому для
общего доступа заведите в Navidrome отдельного пользователя без прав администратора.
"""
import hashlib
import json
import logging
import secrets
from pathlib import Path

from . import paths

log = logging.getLogger("sonar.shared")
FILE = "shared_navidrome.json"
DEFAULT_NAME = "Общий сервер"


def _candidates() -> list[Path]:
    return [paths.app_dir() / FILE, Path(__file__).resolve().parent / "assets" / FILE]


def to_token(data: dict) -> dict:
    """{url, user, password} → {url, user, token, salt}: пароль дальше нигде не хранится."""
    out = {k: v for k, v in data.items() if k != "password"}
    if data.get("password") and not (data.get("token") and data.get("salt")):
        salt = secrets.token_hex(8)
        out.update(salt=salt, token=hashlib.md5((data["password"] + salt).encode()).hexdigest())
    return out


def load() -> dict | None:
    """Настройки общего сервера для Navidrome-сервиса или None, если его нет."""
    from .services.navidrome import _normalize_url
    for path in _candidates():
        if not path.exists():
            continue
        try:
            data = to_token(json.loads(path.read_text("utf-8")))
        except (OSError, ValueError) as exc:
            log.warning("общий сервер: не прочитать %s: %s", path, exc)
            continue
        url, user = _normalize_url(data.get("url") or ""), (data.get("user") or "").strip()
        if not (url and user and data.get("token") and data.get("salt")):
            log.warning("общий сервер: в %s нет адреса, имени или пароля", path)
            continue
        name = (data.get("name") or "").strip() or DEFAULT_NAME
        return {"url": url, "user": user, "token": data["token"], "salt": data["salt"],
                "connected": True, "shared": True, "account": {"name": name}}
    return None
