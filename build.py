"""Автосборщик Sonar в exe.

    python build.py            — полная сборка: зависимости → иконка → PyInstaller → deno → zip
    python build.py --no-install   не трогать pip (зависимости уже стоят)
    python build.py --no-zip       не упаковывать результат в zip
    python build.py --no-deno      не класть deno.exe рядом с программой
    python build.py --no-portable  данные в профиле Windows (%APPDATA%\\Sonar), а не рядом с программой

Результат: dist/Sonar/Sonar.exe (папка целиком — это программа) и dist/Sonar-ГГГГММДД.zip.
Сборка папкой, а не одним файлом: со встроенным браузером (вход в сервисы) один exe весит
сотни мегабайт и стартует по 10–20 секунд, папкой — запускается сразу.
"""
import argparse
import json
import datetime
import os
import platform
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BUILD, DIST = ROOT / "build", ROOT / "dist"
NAME = "Sonar"


def step(text: str) -> None:
    print(f"\n=== {text} ===", flush=True)


def fail(text: str) -> None:
    print(f"\nОШИБКА: {text}", flush=True)
    sys.exit(1)


def run(cmd: list[str]) -> None:
    print("> " + " ".join(cmd), flush=True)
    if subprocess.call(cmd, cwd=ROOT) != 0:
        fail("команда завершилась с ошибкой (подробности выше)")


def install() -> None:
    step("Зависимости")
    run([sys.executable, "-m", "pip", "install", "--upgrade", "pip"])
    run([sys.executable, "-m", "pip", "install", "-r", "requirements.txt", "pyinstaller>=6.0"])


def make_icon() -> Path:
    step("Иконка")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    sys.path.insert(0, str(ROOT))
    from PyQt6.QtGui import QGuiApplication
    app = QGuiApplication.instance() or QGuiApplication([])  # noqa: F841 — нужен для рисования
    from sonar.ui.personalize import app_icon
    BUILD.mkdir(exist_ok=True)
    app_icon("standard", 256).toImage().save(str(BUILD / "sonar.png"))   # для ярлыка в Linux
    if os.name != "nt":
        return BUILD / "sonar.png"
    ico = BUILD / "sonar.ico"
    if not app_icon("standard", 256).toImage().save(str(ico)):
        png = BUILD / "sonar.png"   # без плагина ICO — PyInstaller сам сконвертирует PNG (нужен Pillow)
        app_icon("standard", 256).toImage().save(str(png))
        ico = png
    print(f"иконка: {ico}")
    return ico


SHARED = "shared_navidrome.json"


def prepare_shared() -> Path | None:
    """Общий Navidrome: shared_navidrome.json в корне проекта → в сборку, с токеном вместо пароля."""
    src = ROOT / SHARED
    if not src.exists():
        return None
    step("Общий сервер Navidrome")
    sys.path.insert(0, str(ROOT))
    from sonar.shared_server import to_token
    data = to_token(json.loads(src.read_text("utf-8")))
    if not (data.get("url") and data.get("user") and data.get("token")):
        fail(f"в {src.name} нужны url, user и password")
    out = ROOT / "sonar" / "assets" / SHARED
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")
    print(f"сервер {data['url']}, пользователь {data['user']} — подключится у всех сам")
    return out


def pyinstaller(icon: Path) -> Path:
    step("PyInstaller")
    sep = os.pathsep
    args = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--windowed", "--onedir",
            "--name", NAME, "--icon", str(icon),
            "--distpath", str(DIST), "--workpath", str(BUILD / "pyinstaller"), "--specpath", str(BUILD),
            "--add-data", f"{ROOT / 'sonar' / 'assets'}{sep}sonar/assets",   # аватарки, иконки сервисов
            "--collect-submodules", "sonar",
            "--collect-data", "ytmusicapi",       # языковые файлы для разбора ответов YouTube Music
            "--collect-submodules", "yandex_music",
            "--hidden-import", "socks",          # прокси для Telegram-бота (requests грузит его на лету)
            "--collect-submodules", "qrcode"]
    try:
        import yt_dlp_ejs  # noqa: F401 — JS-скрипты yt-dlp для YouTube
        args += ["--collect-all", "yt_dlp_ejs"]
    except ImportError:
        print("предупреждение: yt-dlp-ejs не установлен — YouTube в exe может не работать")
    args.append(str(ROOT / "main.py"))
    started = time.monotonic()
    run(args)
    folder = DIST / NAME
    exe = folder / (f"{NAME}.exe" if os.name == "nt" else NAME)
    if not exe.exists():
        fail(f"PyInstaller не создал {exe}")
    print(f"готово за {time.monotonic() - started:.0f} с: {exe}")
    return folder


def add_deno(folder: Path) -> None:
    step("Deno (нужен yt-dlp для YouTube)")
    exe = "deno.exe" if os.name == "nt" else "deno"
    found = shutil.which("deno") or next((str(p) for p in (Path.home() / ".deno" / "bin" / exe,) if p.exists()), None)
    if not found:
        how = "winget install DenoLand.Deno" if os.name == "nt" else "curl -fsSL https://deno.land/install.sh | sh"
        print("Deno не найден: YouTube Music и подбор треков для Spotify/Deezer на ПК без Deno работать не будут.\n"
              f"Установите ({how}) и пересоберите — он положится рядом с программой.")
        return
    shutil.copy2(found, folder / exe)
    print(f"скопирован {found} → {folder / exe}")


PORTABLE_NOTE = """Этот файл включает портативный режим Sonar.

Пока он лежит рядом с Sonar.exe, все данные — настройки, подключённые сервисы, профиль, лайки,
плейлисты, история, журнал и скачанные треки — хранятся в папке data рядом с программой.
Папку Sonar можно переносить куда угодно (другой диск, флешка, другой ПК): данные едут вместе с ней.
Если папки data нет, Sonar создаст новую, как при первом запуске.

Удалите этот файл, чтобы хранить данные в профиле Windows (%APPDATA%\\Sonar).
"""


def make_portable(folder: Path) -> None:
    step("Портативный режим")
    (folder / "portable.txt").write_text(PORTABLE_NOTE, "utf-8")
    stale = folder / "data"   # данные с машины сборщика в архив не попадают
    if stale.exists():
        shutil.rmtree(stale)
    print("данные будут храниться в папке data рядом с Sonar.exe")


LINUX_INSTALL = """#!/bin/sh
# Sonar для Linux: добавить в меню приложений (убрать: ./install.sh --remove).
# Сама программа — эта папка целиком; запуск — ./Sonar
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
APPS="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
FILE="$APPS/sonar.desktop"
if [ "$1" = "--remove" ]; then rm -f "$FILE"; echo "Sonar убран из меню"; exit 0; fi
chmod +x "$DIR/Sonar"
mkdir -p "$APPS"
cat > "$FILE" <<DESKTOP
[Desktop Entry]
Type=Application
Name=Sonar
Comment=Вся музыка в одном плеере
Exec="$DIR/Sonar" %U
Icon=$DIR/sonar.png
Terminal=false
Categories=AudioVideo;Audio;Player;
StartupWMClass=Sonar
DESKTOP
command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$APPS" >/dev/null 2>&1 || true
echo "Готово: Sonar есть в меню приложений."
"""

LINUX_NOTE = """Sonar для Linux

Запуск: ./Sonar (папку можно положить куда угодно, данные — в папке data рядом).
Добавить в меню приложений: ./install.sh   Убрать: ./install.sh --remove

Если не запускается с ошибкой про xcb, поставьте библиотеки Qt (один раз):
  Ubuntu / Debian / Mint:  sudo apt install libxcb-cursor0 libxkbcommon-x11-0 libxcb-icccm4 libxcb-keysyms1
  Fedora:                  sudo dnf install xcb-util-cursor libxkbcommon-x11
  Arch:                    sudo pacman -S xcb-util-cursor libxkbcommon-x11

Медиакнопки клавиатуры, шторка GNOME/KDE и playerctl управляют Sonar сами (MPRIS).
"""


def linux_extras(folder: Path) -> None:
    step("Linux: ярлык и памятка")
    shutil.copy2(BUILD / "sonar.png", folder / "sonar.png")
    script = folder / "install.sh"
    script.write_text(LINUX_INSTALL, "utf-8")
    script.chmod(0o755)
    (folder / "ЧИТАЙ-МЕНЯ.txt").write_text(LINUX_NOTE, "utf-8")
    (folder / NAME).chmod(0o755)
    print("install.sh, sonar.png и памятка положены рядом с программой")


def app_version() -> str:
    """Номер версии: --version, SONAR_VERSION или тег GitHub (v1.2.0 → 1.2.0); иначе dev."""
    raw = os.environ.get("SONAR_VERSION") or os.environ.get("GITHUB_REF_NAME") or ""
    m = re.match(r"^v?(\d+(?:\.\d+){0,2})$", raw.strip())
    return m.group(1) if m else "dev"


def write_version(version: str) -> None:
    (ROOT / "sonar" / "version.py").write_text(
        '"""Версия Sonar. Сборщик (build.py) вписывает сюда номер из тега релиза на GitHub, например 1.2.0.\n'
        '"dev" — сборка без номера: она не предлагает обновиться сама, но «Проверить сейчас» работает."""\n'
        f'VERSION = "{version}"\n', "utf-8")
    print(f"версия: {version}")


def make_zip(folder: Path) -> Path:
    step("Архив")
    version = app_version()
    base = DIST / (f"{NAME}-{version}" if version != "dev" else f"{NAME}-{datetime.date.today():%Y%m%d}")
    if os.name == "nt":
        archive = Path(shutil.make_archive(str(base), "zip", root_dir=DIST, base_dir=folder.name))
    else:   # tar.gz хранит права на запуск, zip — нет
        base = Path(f"{base}-linux-{platform.machine()}")
        archive = Path(shutil.make_archive(str(base), "gztar", root_dir=DIST, base_dir=folder.name))
    print(f"{archive} ({archive.stat().st_size / 1048576:.0f} МБ)")
    return archive


def reexec_in_venv() -> None:
    """Собрать в своём виртуальном окружении .venv рядом с build.py и перезапуститься в нём."""
    venv = ROOT / ".venv"
    py = venv / "bin" / "python"
    if not py.exists():
        step("Окружение Python для сборки (.venv)")
        if subprocess.call([sys.executable, "-m", "venv", str(venv)]) != 0:
            fail("не получилось создать окружение. Установите модуль venv и запустите снова:\n"
                 "  Ubuntu / Debian / Mint: sudo apt install python3-venv\n"
                 "  Fedora: sudo dnf install python3   ·   Arch: уже есть в python")
    print(f"сборка в окружении {venv}")
    os.execv(str(py), [str(py), str(ROOT / "build.py"), *sys.argv[1:]])


def main() -> None:
    parser = argparse.ArgumentParser(description="Сборка Sonar в exe")
    parser.add_argument("--no-install", action="store_true", help="не устанавливать зависимости")
    parser.add_argument("--no-zip", action="store_true", help="не упаковывать в zip")
    parser.add_argument("--no-deno", action="store_true", help="не класть deno рядом с программой")
    parser.add_argument("--no-portable", action="store_true", help="данные в профиле Windows, а не рядом")
    parser.add_argument("--version", help="номер версии, например 1.2.0 (иначе из тега GitHub)")
    opts = parser.parse_args()
    if sys.version_info < (3, 10):
        fail("нужен Python 3.10 или новее")
    if os.name != "nt" and sys.prefix == sys.base_prefix and not opts.no_install:
        reexec_in_venv()   # Ubuntu 23.04+ и другие не дают ставить пакеты в системный Python
    if os.name != "nt":
        print("Сборка для этой системы (не Windows): получится программа Sonar и архив .tar.gz.")
    print(f"Python {platform.python_version()} ({sys.executable})")
    if not opts.no_install:
        install()
    if opts.version:
        os.environ["SONAR_VERSION"] = opts.version
    write_version(app_version())
    if os.environ.get("DISCORD_APP_ID", "").strip():   # ID приложения Discord из переменной сборки
        (ROOT / "sonar" / "assets" / "discord_app_id.txt").write_text(os.environ["DISCORD_APP_ID"].strip(), "utf-8")
        print("Discord: ID приложения встроен")
    icon = make_icon()
    shared = prepare_shared()
    try:
        folder = pyinstaller(icon)
    finally:
        if shared is not None:
            shared.unlink(missing_ok=True)   # токен — только внутри сборки, не в исходниках
    if not opts.no_deno:
        add_deno(folder)
    if not opts.no_portable:
        make_portable(folder)
    if sys.platform.startswith("linux"):
        linux_extras(folder)
    archive = None if opts.no_zip else make_zip(folder)
    step("Готово")
    print(f"Программа: {folder}  (запуск — {NAME + '.exe' if os.name == 'nt' else './' + NAME}; переносите папку целиком)")
    if not opts.no_portable:
        print("Портативная: данные в папке data рядом с exe, папку можно класть куда угодно.")
    if archive:
        print(f"Архив для переноса: {archive}")


if __name__ == "__main__":
    main()
