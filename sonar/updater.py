"""Автообновление: новая версия из релизов на GitHub (того же репозитория, что и Мастерская).

Проверка — GET /repos/<repo>/releases/latest. Если версия новее, Sonar показывает, что нового,
скачивает архив релиза, распаковывает его рядом с данными и запускает маленький .bat:
он ждёт, пока Sonar закроется, копирует новые файлы поверх старых (папки data и downloads
не трогает — там настройки и скачанные треки), запускает Sonar и удаляет себя.
Linux: то же самое, только архив .tar.gz и вместо .bat — .sh.
Запуск из исходников — просто открываем страницу релиза.
"""
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

import requests

from . import paths
from .version import VERSION

log = logging.getLogger("sonar.update")
API = "https://api.github.com/repos/{repo}/releases/latest"
HEADERS = {"Accept": "application/vnd.github+json", "User-Agent": "Sonar-updater"}


def parse(version: str) -> tuple | None:
    m = re.match(r"^v?(\d+)(?:\.(\d+))?(?:\.(\d+))?", (version or "").strip())
    return tuple(int(x or 0) for x in m.groups()) if m else None


def is_newer(remote: str, local: str = VERSION) -> bool:
    r, l = parse(remote), parse(local)
    return bool(r and l and r > l)


def current() -> str:
    return VERSION


def latest(repo: str) -> dict | None:
    """Последний релиз: {version, tag, notes, url, asset_url, asset_name, size} или None."""
    r = requests.get(API.format(repo=repo), headers=HEADERS, timeout=15)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    data = r.json()
    asset = next((a for a in data.get("assets") or [] if _asset_fits(a.get("name", ""))), None)
    tag = data.get("tag_name") or ""
    return {"version": tag.lstrip("vV"), "tag": tag, "notes": (data.get("body") or "").strip(),
            "url": data.get("html_url") or f"https://github.com/{repo}/releases",
            "asset_url": asset.get("browser_download_url") if asset else None,
            "asset_name": asset.get("name") if asset else None, "size": asset.get("size", 0) if asset else 0}


def _asset_fits(name: str) -> bool:
    """Архив для этой системы: Windows — Sonar-….zip без «linux», Linux — Sonar-…-linux….tar.gz."""
    n = name.lower()
    if not n.startswith("sonar"):
        return False
    if sys.platform.startswith("linux"):
        return "linux" in n and n.endswith(".tar.gz")
    return n.endswith(".zip") and "linux" not in n


def exe_name() -> str:
    return "Sonar.exe" if sys.platform == "win32" else "Sonar"


def can_self_update() -> bool:
    return (sys.platform == "win32" or sys.platform.startswith("linux")) and getattr(sys, "frozen", False)


def work_dir() -> Path:
    d = paths.data_dir() / "update"
    d.mkdir(parents=True, exist_ok=True)
    return d


def download(release: dict, progress: dict) -> Path:
    """Скачать архив релиза (блокирующий вызов — через run_async). progress: {'done', 'total'}."""
    dest = work_dir() / (release["asset_name"] or "Sonar-update.zip")
    with requests.get(release["asset_url"], headers={"User-Agent": "Sonar-updater"}, stream=True, timeout=30) as r:
        r.raise_for_status()
        progress["total"] = int(r.headers.get("Content-Length") or release.get("size") or 0)
        progress["done"] = 0
        with open(dest, "wb") as f:
            for chunk in r.iter_content(256 * 1024):
                if progress.get("cancel"):
                    raise RuntimeError("отменено")
                f.write(chunk)
                progress["done"] += len(chunk)
    return dest


def prepare(archive: Path) -> Path:
    """Распаковать и найти папку с программой. Только безопасные пути внутри архива."""
    target = work_dir() / "new"
    shutil.rmtree(target, ignore_errors=True)
    target.mkdir(parents=True)
    if str(archive).endswith(".tar.gz"):
        import tarfile
        with tarfile.open(archive, "r:gz") as tar:
            for member in tar.getmembers():
                name = member.name.replace("\\", "/")
                if name.startswith("/") or ".." in name.split("/"):
                    continue   # чужие пути из архива не распаковываем
                try:
                    tar.extract(member, target, filter="data")   # «data» не пускает ссылки наружу и спецфайлы
                except tarfile.FilterError:
                    continue
    else:
        with zipfile.ZipFile(archive) as z:
            for info in z.infolist():
                name = info.filename.replace("\\", "/")
                if name.startswith("/") or ".." in name.split("/"):
                    continue   # чужие пути из архива не распаковываем
                z.extract(info, target)
    exe = next(iter(sorted((p for p in target.rglob(exe_name()) if p.is_file()), key=lambda p: len(p.parts))), None)
    if exe is None:
        raise RuntimeError(f"в архиве обновления нет {exe_name()}")
    return exe.parent


def launch_installer(new_dir: Path) -> None:
    """Запустить скрипт, который дождётся выхода Sonar, заменит файлы и запустит новую версию."""
    app = paths.app_dir()
    if sys.platform != "win32":
        _launch_sh(new_dir, app)
        return
    bat = Path(tempfile.gettempdir()) / f"sonar-update-{os.getpid()}.bat"
    bat.write_text(
        "@echo off\r\nchcp 65001 >nul\r\n"
        f":wait\r\ntasklist /FI \"PID eq {os.getpid()}\" | find \"{os.getpid()}\" >nul && "
        "(timeout /t 1 /nobreak >nul & goto wait)\r\n"
        f"robocopy \"{new_dir}\" \"{app}\" /E /XD data downloads /R:5 /W:1 /NFL /NDL /NJH /NJS /NP >nul\r\n"
        f"start \"\" \"{app / 'Sonar.exe'}\"\r\n"
        f"rmdir /s /q \"{new_dir.parent}\" 2>nul\r\n"
        "(goto) 2>nul & del \"%~f0\"\r\n", encoding="utf-8")
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "DETACHED_PROCESS", 0)
    subprocess.Popen(["cmd", "/c", str(bat)], creationflags=flags, close_fds=True)
    log.info("обновление: установщик запущен (%s → %s)", new_dir, app)


def _launch_sh(new_dir: Path, app: Path) -> None:
    import shlex
    sh = Path(tempfile.gettempdir()) / f"sonar-update-{os.getpid()}.sh"
    q = shlex.quote
    sh.write_text(
        "#!/bin/sh\n"
        f"while kill -0 {os.getpid()} 2>/dev/null; do sleep 1; done\n"
        f"cd {q(str(new_dir))} || exit 1\n"
        "for item in * .[!.]*; do\n"
        "  [ -e \"$item\" ] || continue\n"
        "  case \"$item\" in data|downloads) continue;; esac\n"
        f"  rm -rf {q(str(app))}/\"$item\"\n"
        f"  cp -a \"$item\" {q(str(app))}/\n"
        "done\n"
        f"chmod +x {q(str(app / 'Sonar'))}\n"
        f"cd {q(str(app))} && nohup ./Sonar >/dev/null 2>&1 &\n"
        f"rm -rf {q(str(new_dir.parent))}\n"
        "rm -f \"$0\"\n", encoding="utf-8")
    sh.chmod(0o755)
    subprocess.Popen(["/bin/sh", str(sh)], start_new_session=True, close_fds=True)
    log.info("обновление: установщик запущен (%s → %s)", new_dir, app)
