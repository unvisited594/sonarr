"""MPRIS для Linux: Sonar в системных медиа-виджетах (шторка GNOME/KDE, экран блокировки),
медиакнопки клавиатуры и playerctl — всё через стандартный D-Bus-интерфейс плееров.

Работает в отдельном потоке на jeepney (чистый Python). Команды уходят в плеер через Remote
(сигналом в главный поток), а состояние берётся из его потокобезопасного снимка. Нет D-Bus
(не Linux, нет сессии) — модуль просто ничего не делает.
"""
import logging
import sys
import threading
import time

log = logging.getLogger("sonar.mpris")

BUS_NAME = "org.mpris.MediaPlayer2.sonar"
PATH = "/org/mpris/MediaPlayer2"
ROOT_IF = "org.mpris.MediaPlayer2"
PLAYER_IF = "org.mpris.MediaPlayer2.Player"
PROPS_IF = "org.freedesktop.DBus.Properties"
INTRO_IF = "org.freedesktop.DBus.Introspectable"

INTROSPECT = """<!DOCTYPE node PUBLIC "-//freedesktop//DTD D-BUS Object Introspection 1.0//EN"
 "http://www.freedesktop.org/standards/dbus/1.0/introspect.dtd">
<node>
 <interface name="org.freedesktop.DBus.Introspectable"><method name="Introspect"><arg direction="out" type="s"/></method></interface>
 <interface name="org.freedesktop.DBus.Properties">
  <method name="Get"><arg direction="in" type="s"/><arg direction="in" type="s"/><arg direction="out" type="v"/></method>
  <method name="GetAll"><arg direction="in" type="s"/><arg direction="out" type="a{sv}"/></method>
  <method name="Set"><arg direction="in" type="s"/><arg direction="in" type="s"/><arg direction="in" type="v"/></method>
  <signal name="PropertiesChanged"><arg type="s"/><arg type="a{sv}"/><arg type="as"/></signal>
 </interface>
 <interface name="org.mpris.MediaPlayer2">
  <method name="Raise"/><method name="Quit"/>
  <property name="CanQuit" type="b" access="read"/><property name="CanRaise" type="b" access="read"/>
  <property name="HasTrackList" type="b" access="read"/><property name="Identity" type="s" access="read"/>
  <property name="DesktopEntry" type="s" access="read"/>
  <property name="SupportedUriSchemes" type="as" access="read"/><property name="SupportedMimeTypes" type="as" access="read"/>
 </interface>
 <interface name="org.mpris.MediaPlayer2.Player">
  <method name="Next"/><method name="Previous"/><method name="Pause"/><method name="PlayPause"/>
  <method name="Stop"/><method name="Play"/>
  <method name="Seek"><arg direction="in" type="x"/></method>
  <method name="SetPosition"><arg direction="in" type="o"/><arg direction="in" type="x"/></method>
  <signal name="Seeked"><arg type="x"/></signal>
  <property name="PlaybackStatus" type="s" access="read"/><property name="Rate" type="d" access="readwrite"/>
  <property name="Metadata" type="a{sv}" access="read"/><property name="Volume" type="d" access="readwrite"/>
  <property name="Position" type="x" access="read"/>
  <property name="MinimumRate" type="d" access="read"/><property name="MaximumRate" type="d" access="read"/>
  <property name="CanGoNext" type="b" access="read"/><property name="CanGoPrevious" type="b" access="read"/>
  <property name="CanPlay" type="b" access="read"/><property name="CanPause" type="b" access="read"/>
  <property name="CanSeek" type="b" access="read"/><property name="CanControl" type="b" access="read"/>
 </interface>
</node>"""


class Mpris:
    def __init__(self, remote) -> None:
        self.remote = remote
        self._thread = None
        self._stop = threading.Event()
        self._last = None

    def start(self) -> None:
        if not sys.platform.startswith("linux") or self._thread is not None:
            return
        try:
            import jeepney  # noqa: F401
        except ImportError:
            log.info("MPRIS: нет jeepney — медиаклавиши Linux через систему не работают")
            return
        self._thread = threading.Thread(target=self._run, name="mpris", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    # ---------- свойства ----------

    def _state(self) -> dict:
        return self.remote.state()

    def _position_us(self, st: dict) -> int:
        pos = st.get("position", 0)
        if st.get("playing"):
            pos += int((time.time() - st.get("at", time.time())) * 1000)
        return int(max(0, pos) * 1000)

    def _metadata(self, st: dict) -> dict:
        t = st.get("track")
        if not t:
            return {"mpris:trackid": ("o", "/org/mpris/MediaPlayer2/TrackList/NoTrack")}
        tid = "/sonar/track/" + str(abs(hash((t["title"], t["artist"]))) % 10**12)
        md = {"mpris:trackid": ("o", tid), "xesam:title": ("s", t["title"] or ""),
              "xesam:artist": ("as", [a.strip() for a in (t["artist"] or "").split(",") if a.strip()] or [""]),
              "mpris:length": ("x", int(st.get("duration", 0)) * 1000)}
        if t.get("cover"):
            md["mpris:artUrl"] = ("s", t["cover"])
        return md

    def _player_props(self, st: dict) -> dict:
        has = st.get("track") is not None
        return {
            "PlaybackStatus": ("s", "Playing" if st.get("playing") else ("Paused" if has else "Stopped")),
            "Rate": ("d", 1.0), "MinimumRate": ("d", 1.0), "MaximumRate": ("d", 1.0),
            "Metadata": ("a{sv}", self._metadata(st)), "Volume": ("d", st.get("volume", 0) / 100),
            "Position": ("x", self._position_us(st)),
            "CanGoNext": ("b", True), "CanGoPrevious": ("b", True), "CanPlay": ("b", True), "CanPause": ("b", True),
            "CanSeek": ("b", has), "CanControl": ("b", True),
        }

    @staticmethod
    def _root_props() -> dict:
        return {"CanQuit": ("b", False), "CanRaise": ("b", True), "HasTrackList": ("b", False),
                "Identity": ("s", "Sonar"), "DesktopEntry": ("s", "sonar"),
                "SupportedUriSchemes": ("as", []), "SupportedMimeTypes": ("as", [])}

    # ---------- поток D-Bus ----------

    def _run(self) -> None:
        from jeepney import DBusAddress, MessageType, new_error, new_method_return, new_signal
        from jeepney.bus_messages import message_bus
        from jeepney.io.blocking import open_dbus_connection
        try:
            conn = open_dbus_connection(bus="SESSION")
            reply = conn.send_and_get_reply(message_bus.RequestName(BUS_NAME, 4))   # 4 = не ставить в очередь
            if reply.body[0] not in (1, 4):
                log.info("MPRIS: имя %s занято", BUS_NAME)
        except Exception as exc:   # нет сессионной шины
            log.info("MPRIS недоступен: %s", exc)
            return
        log.info("MPRIS: Sonar виден системе как %s", BUS_NAME)
        emitter = DBusAddress(PATH, interface=PROPS_IF)
        last_send = 0.0
        while not self._stop.is_set():
            try:
                msg = conn.receive(timeout=0.5)
            except TimeoutError:
                msg = None
            except Exception as exc:
                log.info("MPRIS: шина закрылась: %s", exc)
                return
            if msg is not None and msg.header.message_type == MessageType.method_call:
                try:
                    out = self._call(msg, new_method_return, new_error)
                    if out is not None:
                        conn.send(out)
                except Exception as exc:
                    log.info("MPRIS: ошибка вызова: %s", exc)
            # сообщить системе об изменениях (раз в полсекунды, только если что-то поменялось)
            if time.monotonic() - last_send > 0.5:
                last_send = time.monotonic()
                st = self._state()
                key = (st.get("playing"), (st.get("track") or {}).get("title"), (st.get("track") or {}).get("artist"),
                       st.get("volume"), (st.get("track") or {}).get("cover"))
                if key != self._last:
                    self._last = key
                    props = self._player_props(st)
                    changed = {k: props[k] for k in ("PlaybackStatus", "Metadata", "Volume", "CanSeek")}
                    try:
                        conn.send(new_signal(emitter, "PropertiesChanged", "sa{sv}as", (PLAYER_IF, changed, [])))
                    except Exception:
                        pass

    def _call(self, msg, new_method_return, new_error):
        from jeepney import HeaderFields
        h = msg.header.fields
        iface, member = h.get(HeaderFields.interface), h.get(HeaderFields.member)
        if h.get(HeaderFields.path) != PATH:
            return new_error(msg, "org.freedesktop.DBus.Error.UnknownObject")
        if iface == INTRO_IF and member == "Introspect":
            return new_method_return(msg, "s", (INTROSPECT,))
        if iface == PROPS_IF:
            st = self._state()
            all_props = {ROOT_IF: self._root_props(), PLAYER_IF: self._player_props(st)}
            if member == "GetAll":
                return new_method_return(msg, "a{sv}", (all_props.get(msg.body[0], {}),))
            if member == "Get":
                group, name = msg.body
                if name in all_props.get(group, {}):
                    return new_method_return(msg, "v", (all_props[group][name],))
                return new_error(msg, "org.freedesktop.DBus.Error.InvalidArgs")
            if member == "Set":
                group, name, (sig, value) = msg.body
                if group == PLAYER_IF and name == "Volume":
                    self.remote.send("volume", int(max(0.0, min(1.0, float(value))) * 100))
                return new_method_return(msg)
        if iface == ROOT_IF:
            if member == "Raise":
                self.remote.send("raise")
            return new_method_return(msg)
        if iface == PLAYER_IF:
            st = self._state()
            simple = {"Next": "next", "Previous": "prev", "PlayPause": "toggle", "Play": "play", "Pause": "pause",
                      "Stop": "pause"}
            if member in simple:
                self.remote.send(simple[member])
            elif member == "Seek":
                self.remote.send("seek", max(0, (self._position_us(st) + int(msg.body[0])) // 1000))
            elif member == "SetPosition":
                self.remote.send("seek", max(0, int(msg.body[1]) // 1000))
            return new_method_return(msg)
        return new_error(msg, "org.freedesktop.DBus.Error.UnknownMethod")
