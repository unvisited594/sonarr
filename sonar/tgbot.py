"""Telegram-бот Sonar: «что играет», пауза, дальше, громкость и лайк — из любого места.

У каждого свой бот: токен от @BotFather вписывается в Настройки → Данные. Бот работает
прямо из Sonar (опрос getUpdates), свой сервер не нужен. Слушается только хозяина: в
первый раз нужно отправить боту /start КОД — код показан в настройках. Чужие сообщения бот
игнорирует. Можно указать прокси (socks5://… или http://…), если Telegram недоступен напрямую.
"""
import html
import logging
import re
import secrets
import threading
import time

import requests

log = logging.getLogger("sonar.tgbot")
API = "https://api.telegram.org/bot{token}/{method}"

KEYBOARD = {"inline_keyboard": [
    [{"text": "⏮", "callback_data": "prev"}, {"text": "⏯", "callback_data": "toggle"},
     {"text": "⏭", "callback_data": "next"}],
    [{"text": "🔉", "callback_data": "vol_down"}, {"text": "🔊", "callback_data": "vol_up"},
     {"text": "♥", "callback_data": "like"}, {"text": "🔄", "callback_data": "now"}]]}
HELP = ("Я пульт для Sonar.\n\n"
        "/now — что играет\n/pause — пауза или играть\n/next — дальше\n/prev — назад\n"
        "/vol 50 — громкость в процентах\n/like — лайк текущему треку\n\n"
        "Или просто жмите кнопки под сообщением.")


def _fmt(ms: int) -> str:
    s = max(0, int(ms // 1000))
    return f"{s // 60}:{s % 60:02d}"


def now_text(state: dict) -> str:
    t = state.get("track")
    if not t:
        return "Сейчас ничего не играет."
    mark = "▶️" if state.get("playing") else "⏸"
    pos, dur = state.get("position", 0), state.get("duration", 0)
    if state.get("playing"):
        pos += int((time.time() - state.get("at", time.time())) * 1000)
    lines = [f"{mark} <b>{html.escape(t['title'])}</b>", html.escape(t["artist"] or ""),
             f"{_fmt(min(pos, dur or pos))} / {_fmt(dur)} · громкость {state.get('volume', 0)}%"]
    if t.get("liked"):
        lines.append("♥ в лайках")
    nxt = state.get("next")
    if nxt:
        lines.append(f"\nДальше: {html.escape(nxt['artist'])} — {html.escape(nxt['title'])}")
    return "\n".join(lines)


class TgBot:
    def __init__(self, remote, config, status_cb=None) -> None:
        self.remote = remote
        self.config = config
        self.status_cb = status_cb
        self.status = "выключен"
        self._stop = threading.Event()
        self._thread = None
        self._s = requests.Session()

    # ---------- настройки ----------

    @property
    def token(self) -> str:
        return (self.config.data.get("tg_token") or "").strip()

    @property
    def owner(self) -> int | None:
        return self.config.data.get("tg_owner")

    @property
    def code(self) -> str:
        c = self.config.data.get("tg_code")
        if not c:
            c = f"{secrets.randbelow(900000) + 100000}"
            self.config.data["tg_code"] = c
            self.config.save()
        return c

    def start_link(self) -> str | None:
        name = self.config.data.get("tg_bot_name")
        return f"https://t.me/{name}?start={self.code}" if name else None

    def unlink(self) -> None:
        self.config.data.pop("tg_owner", None)
        self.config.data["tg_code"] = f"{secrets.randbelow(900000) + 100000}"
        self.config.save()
        self._set_status("ждёт хозяина: отправьте боту /start " + self.code)

    def _set_status(self, text: str) -> None:
        self.status = text
        if self.status_cb:
            self.status_cb(text)

    # ---------- запуск ----------

    def start(self) -> None:
        if not self.token or (self._thread and self._thread.is_alive()):
            return
        proxy = (self.config.data.get("tg_proxy") or "").strip()
        self._s.proxies = {"http": proxy, "https": proxy} if proxy else {}
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="tg-bot", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._set_status("выключен")

    def restart(self) -> None:
        self.stop()
        if self._thread:
            self._thread.join(timeout=1)
        self.start()

    # ---------- работа ----------

    def _api(self, method: str, http_timeout: float = 15, **params):
        r = self._s.post(API.format(token=self.token, method=method), json=params, timeout=http_timeout)
        data = r.json()
        if not data.get("ok"):
            raise RuntimeError(data.get("description") or f"ошибка {r.status_code}")
        return data["result"]

    def _loop(self) -> None:
        offset = None
        try:
            me = self._api("getMe")
            self.config.data["tg_bot_name"] = me.get("username", "")
            self._set_status(f"работает: @{me.get('username')}" + ("" if self.owner else
                             f" · ждёт хозяина: отправьте боту /start {self.code}"))
        except Exception as exc:   # неверный токен, нет сети, нужен прокси
            self._set_status(f"не подключился: {exc}")
            return
        errors = 0
        while not self._stop.is_set():
            try:
                updates = self._api("getUpdates", http_timeout=40, offset=offset, timeout=30,
                                    allowed_updates=["message", "callback_query"])
                errors = 0
            except Exception as exc:
                errors += 1
                if "conflict" in str(exc).lower() or "terminated by other getupdates" in str(exc).lower():
                    self._set_status("этот токен уже использует другая программа (другой ваш бот или вторая копия "
                                     "Sonar). Создайте у @BotFather нового бота только для Sonar")
                    self._stop.wait(30)
                    continue
                self._set_status(f"нет связи с Telegram ({exc}), пробую снова")
                self._stop.wait(min(60, 5 * errors))
                continue
            for u in updates:
                offset = u["update_id"] + 1
                try:
                    self._handle(u)
                except Exception as exc:   # одно странное сообщение не роняет бота
                    log.info("бот: не обработал сообщение: %s", exc)

    def _handle(self, u: dict) -> None:
        if "callback_query" in u:
            cq = u["callback_query"]
            chat = cq["message"]["chat"]["id"]
            if chat != self.owner:
                return
            action = cq.get("data", "")
            self._api("answerCallbackQuery", callback_query_id=cq["id"])
            if action != "now":
                self.remote.send(action)
                time.sleep(0.6)
            self._edit(chat, cq["message"]["message_id"])
            return
        msg = u.get("message") or {}
        chat = (msg.get("chat") or {}).get("id")
        text = (msg.get("text") or "").strip()
        if not chat or not text:
            return
        cmd, _, arg = text.partition(" ")
        cmd = cmd.split("@")[0].lower()
        if cmd == "/старт":
            cmd = "/start"
        if self.owner is None:
            digits = re.sub(r"\D", "", text)   # пробелы, дефисы, «/start» — неважно, главное цифры кода
            if digits.endswith(self.code) and len(digits) <= len(self.code) + 2:
                self.config.data["tg_owner"] = chat
                self.config.save()
                self._set_status(f"работает: @{self.config.data.get('tg_bot_name', '')} · хозяин привязан")
                self._send(chat, "Готово! Теперь я слушаюсь только вас.\n\n" + HELP)
                self._now(chat)
            else:
                self._send(chat, "Код не подошёл. Отправьте /start и шесть цифр из Sonar (Настройки → Данные → "
                                 "Telegram-бот) или нажмите там кнопку «Открыть бота».")
            return
        if chat != self.owner:
            return   # чужим — тишина
        simple = {"/pause": "toggle", "/play": "toggle", "/next": "next", "/prev": "prev", "/like": "like"}
        if cmd in ("/start", "/help"):
            self._send(chat, HELP)
        elif cmd == "/now":
            self._now(chat)
        elif cmd in simple:
            self.remote.send(simple[cmd])
            time.sleep(0.6)
            self._now(chat)
        elif cmd == "/vol":
            try:
                self.remote.send("volume", max(0, min(100, int(arg))))
                time.sleep(0.4)
                self._now(chat)
            except ValueError:
                self._send(chat, "Напишите так: /vol 50")
        else:
            self._send(chat, HELP)

    def _send(self, chat: int, text: str) -> None:
        self._api("sendMessage", chat_id=chat, text=text, parse_mode="HTML")

    def _now(self, chat: int) -> None:
        state = self.remote.state()
        cover = ((state.get("track") or {}).get("cover") or "")
        if cover.startswith("https://"):
            try:
                self._api("sendPhoto", chat_id=chat, photo=cover, caption=now_text(state), parse_mode="HTML",
                          reply_markup=KEYBOARD)
                return
            except Exception:
                pass   # Telegram не смог скачать обложку — пришлём текстом
        self._api("sendMessage", chat_id=chat, text=now_text(state), parse_mode="HTML", reply_markup=KEYBOARD)

    def _edit(self, chat: int, message_id: int) -> None:
        state = self.remote.state()
        try:
            self._api("editMessageCaption", chat_id=chat, message_id=message_id, caption=now_text(state),
                      parse_mode="HTML", reply_markup=KEYBOARD)
        except RuntimeError:
            try:
                self._api("editMessageText", chat_id=chat, message_id=message_id, text=now_text(state),
                          parse_mode="HTML", reply_markup=KEYBOARD)
            except RuntimeError:
                pass   # «сообщение не изменилось» — это нормально
