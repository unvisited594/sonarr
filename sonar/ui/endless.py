"""Бесконечная волна и перенос плейлистов.

Бесконечная волна: очередь подходит к концу — Sonar сам дописывает похожие треки (радио
YouTube Music по текущему треку, иначе «Моя волна» того же сервиса, иначе другие треки
исполнителя) и музыка не останавливается.

Перенос плейлиста: для каждого трека ищем его в выбранном сервисе (тем же строгим
сравнением, что и запасной поиск: название, исполнитель, длительность) и собираем
новый плейлист Sonar из найденного.
"""
import logging
import random

from PyQt6 import sip
from PyQt6.QtCore import QObject, QTimer, Qt
from PyQt6.QtWidgets import QMenu, QMessageBox, QProgressDialog

from ..services.base import AuthError, ServiceError
from ..services.fallback import best_match
from ..workers import run_async

log = logging.getLogger("sonar.endless")


def _key(t) -> tuple:
    return ((t.title or "").strip().lower(), (t.artist or "").split(",")[0].strip().lower())


def similar(manager, track, seen: set) -> list:
    """В фоне: похожие треки, которых ещё не было в очереди."""
    found = []
    yt = manager.get("ytmusic")
    if yt is not None and hasattr(yt, "_radio"):
        try:
            seed = track if track.service_id == "ytmusic" else best_match(track, yt.search(f"{track.artist} {track.title}"))
            if seed is not None:
                found = yt._radio(seed)
        except (AuthError, ServiceError) as exc:
            log.info("радио YouTube Music не вышло: %s", exc)
    svc = manager.get(track.service_id)
    if len(found) < 5 and svc is not None:
        try:
            found += svc.wave() or []
        except (AuthError, ServiceError, NotImplementedError) as exc:
            log.info("волна %s не вышла: %s", track.service_id, exc)
    if len(found) < 5 and svc is not None and track.artist:
        try:
            found += svc.search(track.artist.split(",")[0])
        except (AuthError, ServiceError) as exc:
            log.info("поиск по исполнителю не вышел: %s", exc)
    out = []
    for t in found:
        k = _key(t)
        if t.playable and k not in seen:
            seen.add(k)
            out.append(t)
    head, tail = out[:5], out[5:]   # самые похожие — первыми, остальное вперемешку
    random.shuffle(tail)
    return (head + tail)[:25]


class Endless(QObject):
    def __init__(self, player, manager, config, toast) -> None:
        super().__init__(player)
        self.player, self.manager, self.config, self.toast = player, manager, config, toast
        self._busy = False
        player.started.connect(self._check)

    @property
    def on(self) -> bool:
        return bool(self.config.data.get("endless", True))

    def set_on(self, on: bool) -> None:
        self.config.data["endless"] = on
        self.config.save()

    def _check(self, track) -> None:
        p = self.player
        if (not self.on or self._busy or p.context in ("wave", "radio", "alarm") or track is None
                or track.service_id == "radio" or p.index < len(p.queue) - 2):
            return
        self._busy = True
        seen = {_key(t) for t in p.queue}

        def done(tracks):
            self._busy = False
            if sip.isdeleted(self) or not tracks:
                return
            p.queue.extend(tracks)
            self.toast(f"Волна продолжается: +{len(tracks)} похожих")

        def failed(_msg):
            self._busy = False
        run_async(similar, self.manager, track, seen, on_done=done, on_error=failed)


def transfer(manager, tracks: list, service_id: str, progress: dict) -> tuple[list, list]:
    """В фоне: (найденные, не найденные)."""
    svc = manager.get(service_id)
    found, missing = [], []
    progress["total"] = len(tracks)
    for i, t in enumerate(tracks):
        if progress.get("cancel"):
            break
        progress["done"] = i
        if t.service_id == service_id and t.playable:
            found.append(t)
            continue
        try:
            match = best_match(t, svc.search(f"{(t.artist or '').split(',')[0]} {t.title}".strip()))
        except (AuthError, ServiceError):
            match = None
        (found if match is not None else missing).append(match or t)
    progress["done"] = len(tracks)
    return found, missing


def offer_transfer(page, anchor, title: str, tracks: list, local_store, on_created) -> None:
    """Меню «Собрать в другом сервисе» → прогресс → новый плейлист Sonar."""
    from ..services.base import name_in
    services = [s for s in page.manager.connected()]
    if not services or not tracks:
        QMessageBox.information(page, "Перенос плейлиста", "Нужен хотя бы один подключённый сервис и треки в плейлисте.")
        return
    menu = QMenu(page)
    for svc in services:
        menu.addAction(f"Собрать {name_in(svc)}", lambda s=svc: _run(page, title, tracks, s, local_store, on_created))
    menu.exec(anchor.mapToGlobal(anchor.rect().bottomLeft()))


def _run(page, title, tracks, svc, local_store, on_created) -> None:
    from ..services.base import name_from
    tracks = tracks[:300]
    progress = {"done": 0, "total": len(tracks)}
    dlg = QProgressDialog(f"Ищу треки {name_from(svc)}…", "Отмена", 0, max(1, len(tracks)), page)
    dlg.setWindowTitle("Перенос плейлиста")
    dlg.setWindowModality(Qt.WindowModality.WindowModal)
    dlg.setMinimumDuration(0)
    tick = QTimer(dlg, interval=200)
    tick.timeout.connect(lambda: (dlg.setValue(progress["done"]), progress.__setitem__("cancel", dlg.wasCanceled())))
    tick.start()

    def done(result):
        tick.stop()
        dlg.close()
        found, missing = result
        if not found:
            QMessageBox.information(page, "Перенос плейлиста", "Ни один трек не нашёлся в этом сервисе.")
            return
        pid = local_store.create(f"{title} · {svc.name}")
        for t in found:
            local_store.add(pid, t)
        text = f"Нашлось {len(found)} из {len(tracks)}."
        if missing:
            names = "\n".join(f"• {m.artist} — {m.title}" for m in missing[:12])
            text += f"\n\nНе нашлись ({len(missing)}):\n{names}" + ("\n…" if len(missing) > 12 else "")
        QMessageBox.information(page, "Плейлист собран", text)
        on_created(pid)

    def failed(msg):
        tick.stop()
        dlg.close()
        QMessageBox.warning(page, "Перенос плейлиста", f"Не получилось: {msg}")
    run_async(transfer, page.manager, tracks, svc.id, progress, on_done=done, on_error=failed)
