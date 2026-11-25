"""Статус в Discord: «Слушает Sonar» — трек, исполнитель, обложка и полоска времени.

Работает через локальный канал Discord-клиента (тот же, что у игр), без логинов и токенов:
Discord должен быть запущен на этом же компьютере. Нет Discord — тихо ждём и пробуем снова.

Нужен Application ID приложения «Sonar» с discord.com/developers/applications: его название
Discord и показывает («Слушает Sonar»). Впишите ID в APP_ID ниже (или ключом discord_app_id
в config.json). Пустой — статус выключен.
"""
import json
import logging
import os
import queue
import socket
import struct
import sys
import threading
import time
import uuid

log = logging.getLogger("sonar.discord")

APP_ID = ""   # ← Application ID приложения «Sonar» из Discord Developer Portal


def app_id(config=None) -> str:
    """ID: из config.json, из этой строки или из файла, который положил сборщик (переменная DISCORD_APP_ID)."""
    if config is not None and (config.data.get("discord_app_id") or "").strip():
        return config.data["discord_app_id"].strip()
    if APP_ID.strip():
        return APP_ID.strip()
    from pathlib import Path
    file = Path(__file__).resolve().parent / "assets" / "discord_app_id.txt"
    try:
        return file.read_text("utf-8").strip() if file.exists() else ""
    except OSError:
        return ""
TELEGRAM = "https://t.me/sonar081"

OP_HANDSHAKE, OP_FRAME, OP_CLOSE = 0, 1, 2
RETRY = 15.0


class _Pipe:
    """Канал до клиента Discord: именованный канал в Windows, сокет в Linux и macOS."""

    def __init__(self) -> None:
        self._f = None
        self._s = None

    def connect(self) -> bool:
        for i in range(10):
            try:
                if sys.platform == "win32":
                    self._f = open(rf"\\?\pipe\discord-ipc-{i}", "r+b", buffering=0)
                else:
                    base = (os.environ.get("XDG_RUNTIME_DIR") or os.environ.get("TMPDIR") or os.environ.get("TMP")
                            or "/tmp")
                    # обычный Discord, из Flatpak и из Snap кладут канал в разные места
                    for sub in ("", "app/com.discordapp.Discord", "snap.discord"):
                        path = os.path.join(base, sub, f"discord-ipc-{i}")
                        if not os.path.exists(path):
                            continue
                        self._s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                        self._s.settimeout(5)
                        try:
                            self._s.connect(path)
                            return True
                        except OSError:
                            self.close()
                    continue
                return True
            except OSError:
                self.close()
        return False

    def send(self, op: int, payload: dict) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        frame = struct.pack("<II", op, len(data)) + data
        if self._f is not None:
            self._f.write(frame)
            self._f.flush()
        else:
            self._s.sendall(frame)

    def recv(self) -> tuple[int, dict]:
        head = self._read(8)
        op, size = struct.unpack("<II", head)
        return op, json.loads(self._read(size).decode("utf-8") or "{}")

    def _read(self, n: int) -> bytes:
        out = b""
        while len(out) < n:
            chunk = self._f.read(n - len(out)) if self._f is not None else self._s.recv(n - len(out))
            if not chunk:
                raise OSError("Discord закрыл канал")
            out += chunk
        return out

    def close(self) -> None:
        for obj in (self._f, self._s):
            try:
                if obj is not None:
                    obj.close()
            except OSError:
                pass
        self._f = self._s = None


def build_activity(track, playing: bool, position_ms: int, releases_url: str) -> dict | None:
    """Что показать в Discord. None — убрать статус."""
    if track is None:
        return None
    title = (getattr(track, "title", "") or "Без названия")[:120]
    artist = (getattr(track, "artist", "") or "")[:120]
    activity = {
        "type": 2,   # «Слушает»
        "details": title if len(title) >= 2 else title + " ",
        "state": (artist if playing else f"На паузе · {artist}")[:128] or "Sonar",
        "assets": {"large_text": "Sonar — музыкальный плеер"},
        "buttons": [{"label": "Скачать Sonar", "url": releases_url}, {"label": "Telegram", "url": TELEGRAM}],
    }
    art = getattr(track, "artwork_url", "") or ""
    if art.startswith("https://") and len(art) <= 256:
        activity["assets"]["large_image"] = art
    else:
        activity["assets"]["large_image"] = "sonar"   # картинка «sonar» из Art Assets приложения, если загружена
    duration = int(getattr(track, "duration_ms", 0) or 0)
    if playing:
        start = int(time.time() * 1000) - max(0, position_ms)
        activity["timestamps"] = {"start": start // 1000}
        if duration > 0:
            activity["timestamps"]["end"] = (start + duration) // 1000
    return activity


class DiscordPresence:
    """Фоновый поток: держит связь с Discord и отправляет последний статус."""

    def __init__(self, app_id: str, releases_url: str) -> None:
        self.app_id = app_id
        self.releases_url = releases_url
        self.enabled = bool(app_id)
        self._q: queue.Queue = queue.Queue()
        self._thread = None
        self.connected = False

    def start(self) -> None:
        if self.enabled and self._thread is None:
            self._thread = threading.Thread(target=self._run, name="discord-presence", daemon=True)
            self._thread.start()

    def update(self, track, playing: bool, position_ms: int = 0) -> None:
        if self.enabled:
            self._q.put(("set", build_activity(track, playing, position_ms, self.releases_url)))

    def clear(self) -> None:
        if self.enabled:
            self._q.put(("set", None))

    def stop(self) -> None:
        if self._thread is not None:
            self._q.put(("stop", None))
            self._thread.join(timeout=2)
            self._thread = None

    def _run(self) -> None:
        pipe = _Pipe()
        latest = ("none", None)
        next_try = 0.0
        while True:
            try:
                kind, activity = self._q.get(timeout=1.0)
                while True:   # копится несколько — важен только последний
                    try:
                        kind, activity = self._q.get_nowait()
                    except queue.Empty:
                        break
                if kind == "stop":
                    if self.connected:
                        try:
                            self._send(pipe, None)
                        except OSError:
                            pass
                    pipe.close()
                    return
                latest = (kind, activity)
                dirty = True
            except queue.Empty:
                dirty = False
            if not self.connected:
                if time.monotonic() < next_try or latest[0] == "none":
                    continue
                if not self._connect(pipe):
                    next_try = time.monotonic() + RETRY
                    continue
                dirty = True
            if dirty:
                try:
                    self._send(pipe, latest[1])
                except (OSError, ValueError, struct.error) as exc:
                    log.info("Discord: связь потеряна (%s)", exc)
                    pipe.close()
                    self.connected = False
                    next_try = time.monotonic() + RETRY

    def _connect(self, pipe: _Pipe) -> bool:
        if not pipe.connect():
            return False
        try:
            pipe.send(OP_HANDSHAKE, {"v": 1, "client_id": self.app_id})
            op, data = pipe.recv()
            if op == OP_CLOSE or data.get("evt") != "READY":
                log.info("Discord не принял подключение: %s", data.get("message") or data)
                pipe.close()
                return False
        except (OSError, ValueError, struct.error):
            pipe.close()
            return False
        self.connected = True
        log.info("Discord: подключено")
        return True

    def _send(self, pipe: _Pipe, activity: dict | None) -> None:
        pipe.send(OP_FRAME, {"cmd": "SET_ACTIVITY", "args": {"pid": os.getpid(), "activity": activity},
                             "nonce": uuid.uuid4().hex})
        op, data = pipe.recv()
        if data.get("evt") == "ERROR":
            log.info("Discord отклонил статус: %s", (data.get("data") or {}).get("message"))
