"""Мастерская: наборы оформления («кастомы»), которые можно сохранять, ставить, делиться ими.

Набор — zip-файл .sonarpack:
    pack.json   {"format": 1, "name", "author", "description", "settings": {...}, "images": {...}}
    preview.png превью (необязательно)
    wallpaper.png / icon.png — свои обои и иконка, если они входят в набор

В набор попадают только настройки внешнего вида (тема, цвета, обои, иконка, снег, фон большого
плеера, вид текста песни) — никаких входов в сервисы, путей и прочих личных данных.

Свои наборы лежат в <папка настроек>/workshop/<id>/. Каталог — файл workshop/index.json
в репозитории Sonar на GitHub (его можно поменять ключом workshop_repo в config.json), плюс
встроенные наборы из sonar/assets/workshop.
"""
import io
import json
import logging
import re
import shutil
import time
import zipfile
from pathlib import Path

import requests

from .config import config_dir

log = logging.getLogger("sonar.workshop")

FORMAT = 1
REPO = "unvisited594/sonarr"
BRANCH = "main"
MAX_PACK = 25 * 1024 * 1024
MAX_FILE = 12 * 1024 * 1024

THEME_KEYS = ("theme", "theme_light_from", "theme_dark_from")
LOOK_KEYS = ("accent", "bg_sidebar", "bg_panel", "wallpaper", "wallpaper_visibility", "app_icon", "snow",
             "like_burst")
FLOW_KEYS = ("flow_source", "flow_blur", "flow_speed", "flow_custom", "vinyl")
LYRICS_KEYS = ("lyrics_style", "lyrics_color", "lyrics_sung", "lyrics_halo", "lyrics_font", "lyrics_size",
               "lyrics_bold", "lyrics_align", "lyrics_speed", "lyrics_offset", "lyrics_scroll",
               "lyrics_translate")
ALL_KEYS = THEME_KEYS + LOOK_KEYS + FLOW_KEYS + LYRICS_KEYS
IMAGE_NAMES = {"wallpaper": "wallpaper.png", "icon": "icon.png"}


class WorkshopError(Exception):
    pass


# ---------- проверка ----------

def _clean_value(value):
    """Только простые значения: строка, число, да/нет, пусто или список строк."""
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return value[:200]
    if isinstance(value, list) and len(value) <= 8 and all(isinstance(v, str) for v in value):
        return [v[:32] for v in value]
    raise WorkshopError("в наборе странное значение настройки")


def clean_settings(settings: dict) -> dict:
    if not isinstance(settings, dict):
        raise WorkshopError("в наборе нет настроек")
    return {k: _clean_value(v) for k, v in settings.items() if k in ALL_KEYS}


def clean_meta(data: dict) -> dict:
    def text(key, limit):
        value = data.get(key) or ""
        return re.sub(r"\s+", " ", str(value)).strip()[:limit]
    name = text("name", 60) or "Без названия"
    return {"format": FORMAT, "name": name, "author": text("author", 40),
            "description": text("description", 300), "created": data.get("created") or time.time()}


def slug(name: str) -> str:
    base = re.sub(r"[^\w-]+", "-", name.lower(), flags=re.UNICODE).strip("-")[:40] or "pack"
    return f"{base}-{int(time.time() * 1000) % 10**8}"


# ---------- снимок текущего оформления ----------

def snapshot(config) -> dict:
    """Текущее оформление в виде настроек набора."""
    from .ui.flow_settings import DEFAULTS as FLOW_DEFAULTS
    from .ui.personalize import DEFAULTS as LOOK_DEFAULTS
    data = config.data
    out = {}
    for key in ALL_KEYS:
        if key in data:
            out[key] = data[key]
        elif key in FLOW_DEFAULTS:
            out[key] = FLOW_DEFAULTS[key]
        elif key in LOOK_DEFAULTS:
            out[key] = LOOK_DEFAULTS[key]
    out.setdefault("theme", data.get("theme", "standard"))
    return clean_settings(out)


def snapshot_images(settings: dict) -> dict:
    """Свои обои и иконка, если они выбраны: {вид: путь}."""
    from .ui.personalize import custom_icon_path, custom_wallpaper_path
    images = {}
    if settings.get("wallpaper") == "custom" and custom_wallpaper_path().exists():
        images["wallpaper"] = custom_wallpaper_path()
    if settings.get("app_icon") == "custom" and custom_icon_path().exists():
        images["icon"] = custom_icon_path()
    return images


# ---------- свои наборы ----------

def local_dir() -> Path:
    d = config_dir() / "workshop"
    d.mkdir(parents=True, exist_ok=True)
    return d


class Pack:
    def __init__(self, folder: Path, meta: dict, settings: dict, images: dict) -> None:
        self.folder, self.meta, self.settings, self.images = folder, meta, settings, images

    @property
    def id(self) -> str:
        return self.folder.name

    @property
    def name(self) -> str:
        return self.meta["name"]

    def image_path(self, kind: str) -> Path | None:
        file = self.images.get(kind)
        path = self.folder / file if file else None
        return path if path and path.exists() else None

    @property
    def preview(self) -> Path | None:
        path = self.folder / "preview.png"
        return path if path.exists() else None


def _read_folder(folder: Path) -> Pack | None:
    try:
        data = json.loads((folder / "pack.json").read_text("utf-8"))
        return Pack(folder, clean_meta(data), clean_settings(data.get("settings") or {}),
                    {k: v for k, v in (data.get("images") or {}).items() if k in IMAGE_NAMES})
    except (OSError, ValueError, WorkshopError):
        return None


def local_packs() -> list[Pack]:
    packs = [p for p in (_read_folder(f) for f in local_dir().iterdir() if f.is_dir()) if p]
    return sorted(packs, key=lambda p: -float(p.meta.get("created") or 0))


def _write_folder(folder: Path, meta: dict, settings: dict, images: dict[str, bytes], preview: bytes | None) -> Pack:
    from PyQt6.QtGui import QImage
    folder.mkdir(parents=True, exist_ok=True)
    kept = {}
    for kind, raw in images.items():
        img = QImage.fromData(raw)
        if img.isNull():
            continue   # не картинка — пропускаем, а не доверяем
        img.save(str(folder / IMAGE_NAMES[kind]), "PNG")
        kept[kind] = IMAGE_NAMES[kind]
    if preview:
        img = QImage.fromData(preview)
        if not img.isNull():
            img.save(str(folder / "preview.png"), "PNG")
    (folder / "pack.json").write_text(json.dumps({**meta, "settings": settings, "images": kept},
                                                 ensure_ascii=False, indent=2), "utf-8")
    return Pack(folder, meta, settings, kept)


def save_current(config, name: str, author: str = "", description: str = "", preview: bytes | None = None) -> Pack:
    settings = snapshot(config)
    images = {k: p.read_bytes() for k, p in snapshot_images(settings).items()}
    meta = clean_meta({"name": name, "author": author, "description": description, "created": time.time()})
    return _write_folder(local_dir() / slug(meta["name"]), meta, settings, images, preview)


def delete(pack: Pack) -> None:
    shutil.rmtree(pack.folder, ignore_errors=True)


# ---------- файл .sonarpack ----------

def export(pack: Pack, dest: Path) -> Path:
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("pack.json", json.dumps({**pack.meta, "settings": pack.settings, "images": pack.images},
                                           ensure_ascii=False, indent=2))
        for file in list(pack.images.values()) + ["preview.png"]:
            path = pack.folder / file
            if path.exists():
                z.write(path, file)
    return dest


def import_bytes(raw: bytes) -> Pack:
    """Поставить набор из содержимого .sonarpack (или .zip). Читаем только известные файлы."""
    if len(raw) > MAX_PACK:
        raise WorkshopError("файл набора слишком большой")
    try:
        z = zipfile.ZipFile(io.BytesIO(raw))
    except zipfile.BadZipFile as exc:
        raise WorkshopError("это не файл набора Sonar") from exc

    def read(name: str) -> bytes | None:
        try:
            info = z.getinfo(name)
        except KeyError:
            return None
        if info.file_size > MAX_FILE:
            raise WorkshopError(f"в наборе слишком большой файл {name}")
        return z.read(info)

    head = read("pack.json")
    if head is None:
        raise WorkshopError("в файле нет pack.json — это не набор Sonar")
    try:
        data = json.loads(head.decode("utf-8"))
    except ValueError as exc:
        raise WorkshopError("pack.json повреждён") from exc
    meta = clean_meta(data)
    meta["created"] = time.time()
    settings = clean_settings(data.get("settings") or {})
    images = {}
    for kind, file in IMAGE_NAMES.items():
        if kind in (data.get("images") or {}):
            blob = read(file)
            if blob:
                images[kind] = blob
    return _write_folder(local_dir() / slug(meta["name"]), meta, settings, images, read("preview.png"))


def import_file(path: str | Path) -> Pack:
    return import_bytes(Path(path).read_bytes())


def import_json(data: dict) -> Pack:
    """Набор без картинок, описанный одним JSON (встроенные и простые наборы каталога)."""
    meta = clean_meta(data)
    meta["created"] = time.time()
    return _write_folder(local_dir() / slug(meta["name"]), meta, clean_settings(data.get("settings") or {}), {}, None)


# ---------- применить ----------

def apply(pack: Pack, config) -> None:
    """Записать настройки набора; картинки — на место своих обоев и иконки. Перерисовку окна
    делает главное окно (MainWindow.apply_customization)."""
    from .ui.personalize import custom_icon_path, custom_wallpaper_path
    settings = dict(pack.settings)
    for kind, target in (("wallpaper", custom_wallpaper_path()), ("icon", custom_icon_path())):
        src = pack.image_path(kind)
        if src:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, target)
        elif settings.get("wallpaper" if kind == "wallpaper" else "app_icon") == "custom":
            # набор просит свою картинку, а её в нём нет — оставляем как есть у пользователя
            settings.pop("wallpaper" if kind == "wallpaper" else "app_icon", None)
    for key in ALL_KEYS:
        if key in settings:
            config.data[key] = settings[key]
    config.save()


# ---------- каталог ----------

def repo(config=None) -> str:
    value = (config.data.get("workshop_repo") if config is not None else None) or REPO
    return value.strip().strip("/")


def raw_url(path: str, config=None) -> str:
    return f"https://raw.githubusercontent.com/{repo(config)}/{BRANCH}/workshop/{path.lstrip('/')}"


def builtin_catalog() -> list[dict]:
    folder = Path(__file__).resolve().parent / "assets" / "workshop"
    items = []
    for path in sorted(folder.glob("*.json")):
        try:
            data = json.loads(path.read_text("utf-8"))
        except (OSError, ValueError):
            continue
        items.append({**data, "builtin": True, "id": path.stem})
    return items


def online_catalog(config=None) -> list[dict]:
    """Список наборов из репозитория (блокирующий вызов — через run_async)."""
    r = requests.get(raw_url("index.json", config), timeout=15)
    if r.status_code == 404:
        return []
    r.raise_for_status()
    data = r.json()
    items = data.get("packs") if isinstance(data, dict) else data
    out = []
    for item in items or []:
        if isinstance(item, dict) and (item.get("file") or item.get("settings")):
            out.append({k: item[k] for k in ("id", "name", "author", "description", "file", "settings", "colors")
                        if k in item})
    return out


def install(item: dict, config=None) -> Pack:
    """Поставить набор из каталога (блокирующий вызов — через run_async)."""
    if item.get("settings") and not item.get("file"):
        return import_json(item)
    file = str(item.get("file") or "")
    if not re.fullmatch(r"[\w.\-/]+", file) or ".." in file:
        raise WorkshopError("в каталоге неверное имя файла набора")
    r = requests.get(raw_url(file, config), timeout=30)
    r.raise_for_status()
    if file.endswith(".json"):
        return import_json(r.json())
    return import_bytes(r.content)


def submit_url(pack_name: str, config=None) -> str:
    """Страница «новый issue» в репозитории: прикрепить файл набора — и он попадёт в каталог."""
    from urllib.parse import urlencode
    body = ("Хочу добавить набор в Мастерскую Sonar.\n\n"
            f"Название: {pack_name}\n"
            "Автор (как подписать): \n"
            "Описание: \n\n"
            "Файл набора (.zip) прикреплён ниже — перетащите его в это поле.")
    return f"https://github.com/{repo(config)}/issues/new?" + urlencode(
        {"title": f"Мастерская: {pack_name}", "body": body, "labels": "workshop"})
