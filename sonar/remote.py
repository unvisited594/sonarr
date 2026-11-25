"""Управление Sonar извне: пульт с телефона (страница в браузере по Wi-Fi) и Telegram-бот.

Remote живёт в главном потоке Qt: раз в полсекунды кладёт «что сейчас играет» в снимок под
замком, а команды из чужих потоков (веб-сервер, бот) принимает сигналом — Qt сам переносит их
в главный поток. Так сеть никогда не трогает плеер напрямую.

Пульт: маленький HTTP-сервер на свободном порту 8765–8775 в локальной сети. Каждый запрос
должен нести ключ (?k=…) из QR-кода — без него 403. Ключ можно сменить, тогда старые ссылки
перестанут работать.
"""
import json
import logging
import secrets
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from PyQt6.QtCore import QObject, QTimer, pyqtSignal

log = logging.getLogger("sonar.remote")
PORTS = range(8765, 8776)
ACTIONS = {"raise", "toggle", "play", "pause", "next", "prev", "like", "seek", "volume", "vol_up", "vol_down"}


class Remote(QObject):
    """Мост между сетью и плеером."""
    command = pyqtSignal(str, object)   # из любого потока; выполняется в главном

    def __init__(self, window) -> None:
        super().__init__(window)
        self.win = window
        self._lock = threading.Lock()
        self._state: dict = {"track": None, "playing": False}
        self.command.connect(self._run)
        self._timer = QTimer(self, interval=500)
        self._timer.timeout.connect(self._snapshot)
        self._timer.start()
        self._snapshot()

    # ---------- снимок (главный поток) ----------

    def _snapshot(self) -> None:
        p = self.win.player
        t = p.current
        likes = getattr(self.win, "likes", None)
        state = {
            "playing": bool(p.is_playing),
            "position": int(p.mp.position()),
            "duration": int(p.mp.duration() or (t.duration_ms if t else 0) or 0),
            "volume": int(self.win.bar.volume.value()),
            "at": time.time(),
            "track": None,
        }
        if t is not None:
            state["track"] = {"title": t.title, "artist": t.artist, "cover": t.artwork_url or "",
                              "service": t.service_id, "liked": bool(likes and likes.contains(t))}
            nxt = p.queue[p.index + 1] if 0 <= p.index + 1 < len(p.queue) else None
            state["next"] = {"title": nxt.title, "artist": nxt.artist} if nxt else None
        with self._lock:
            self._state = state

    def state(self) -> dict:
        """Снимок для чужих потоков."""
        with self._lock:
            return dict(self._state)

    # ---------- команды (главный поток) ----------

    def _run(self, action: str, arg) -> None:
        p, bar = self.win.player, self.win.bar
        if action == "toggle":
            p.toggle()
        elif action == "play" and not p.is_playing:
            p.toggle()
        elif action == "pause" and p.is_playing:
            p.toggle()
        elif action == "next":
            p.next()
        elif action == "prev":
            p.prev()
        elif action == "like":
            bar._toggle_like()
        elif action == "seek" and arg is not None:
            p.seek(max(0, int(arg)))
        elif action == "volume" and arg is not None:
            bar.volume.setValue(max(0, min(100, int(arg))))
        elif action == "raise":
            self.win.showNormal()
            self.win.raise_()
            self.win.activateWindow()
        elif action in ("vol_up", "vol_down"):
            bar.volume.setValue(max(0, min(100, bar.volume.value() + (10 if action == "vol_up" else -10))))
        QTimer.singleShot(150, self._snapshot)

    def send(self, action: str, arg=None) -> bool:
        """Из любого потока."""
        if action not in ACTIONS:
            return False
        self.command.emit(action, arg)
        return True


def lan_addresses() -> list[str]:
    """Адреса этого компьютера в локальной сети (основной — первым)."""
    found = []
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))   # пакет никуда не уходит, просто узнаём свой адрес
        found.append(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if ip not in found and not ip.startswith("127."):
                found.append(ip)
    except OSError:
        pass
    return found or ["127.0.0.1"]


class PhoneRemote:
    """HTTP-сервер пульта. start()/stop() из главного потока."""

    def __init__(self, remote: Remote, config) -> None:
        self.remote = remote
        self.config = config
        self.httpd = None
        self.thread = None
        self.port = 0

    @property
    def key(self) -> str:
        k = self.config.data.get("remote_key")
        if not k:
            k = secrets.token_urlsafe(12)
            self.config.data["remote_key"] = k
            self.config.save()
        return k

    def new_key(self) -> None:
        self.config.data["remote_key"] = secrets.token_urlsafe(12)
        self.config.save()

    @property
    def running(self) -> bool:
        return self.httpd is not None

    def url(self) -> str:
        return f"http://{lan_addresses()[0]}:{self.port}/?k={self.key}"

    def start(self) -> bool:
        if self.httpd is not None:
            return True
        handler = _make_handler(self)
        for port in PORTS:
            try:
                self.httpd = ThreadingHTTPServer(("0.0.0.0", port), handler)
                self.port = port
                break
            except OSError:
                continue
        if self.httpd is None:
            log.warning("пульт: все порты %s–%s заняты", PORTS.start, PORTS.stop - 1)
            return False
        self.httpd.daemon_threads = True
        self.thread = threading.Thread(target=self.httpd.serve_forever, name="phone-remote", daemon=True)
        self.thread.start()
        log.info("пульт с телефона: порт %s", self.port)
        return True

    def stop(self) -> None:
        if self.httpd is not None:
            self.httpd.shutdown()
            self.httpd.server_close()
        self.httpd = None
        self.thread = None


def _make_handler(owner: PhoneRemote):
    class Handler(BaseHTTPRequestHandler):
        server_version = "Sonar"

        def log_message(self, *_args) -> None:   # без шума в журнале
            pass

        def _authorized(self, query: dict) -> bool:
            given = (query.get("k") or [""])[0] or self.headers.get("X-Sonar-Key", "")
            return bool(given) and secrets.compare_digest(given, owner.key)

        def _send(self, code: int, body: bytes, kind: str = "application/json; charset=utf-8") -> None:
            self.send_response(code)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            u = urlparse(self.path)
            q = parse_qs(u.query)
            if not self._authorized(q):
                self._send(403, "Нужна ссылка из QR-кода в Sonar".encode("utf-8"), "text/plain; charset=utf-8")
                return
            if u.path == "/":
                self._send(200, PAGE.encode("utf-8"), "text/html; charset=utf-8")
            elif u.path == "/api/state":
                self._send(200, json.dumps(owner.remote.state(), ensure_ascii=False).encode("utf-8"))
            else:
                self._send(404, b"{}")

        def do_POST(self) -> None:
            u = urlparse(self.path)
            if u.path != "/api/cmd" or not self._authorized(parse_qs(u.query)):
                self._send(403, b"{}")
                return
            try:
                size = min(int(self.headers.get("Content-Length") or 0), 1024)
                data = json.loads(self.rfile.read(size) or b"{}")
            except (ValueError, OSError):
                self._send(400, b"{}")
                return
            ok = owner.remote.send(str(data.get("action", "")), data.get("value"))
            self._send(200 if ok else 400, json.dumps({"ok": ok}).encode())
    return Handler


PAGE = """<!doctype html>
<html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="theme-color" content="#0b0b12"><title>Sonar — пульт</title>
<style>
:root{--bg:#0b0b12;--fg:#f2f2f7;--dim:#9a9aa8;--acc:#7c4dff;--acc2:#00e5ff}
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
html,body{margin:0;height:100%;background:var(--bg);color:var(--fg);font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
body{display:flex;flex-direction:column;align-items:center;padding:calc(env(safe-area-inset-top,0px) + 18px) 22px calc(env(safe-area-inset-bottom,0px) + 22px)}
#bg{position:fixed;inset:0;z-index:-1;background:radial-gradient(80% 50% at 30% 10%,#3b2a8f88,transparent),radial-gradient(70% 50% at 80% 90%,#00e5ff33,transparent)}
header{width:100%;max-width:520px;display:flex;justify-content:space-between;align-items:center;font-weight:800;letter-spacing:.06em;font-size:14px;color:var(--dim)}
#dot{width:9px;height:9px;border-radius:50%;background:#555;display:inline-block;margin-right:8px}
#cover{width:min(78vw,420px);aspect-ratio:1;border-radius:22px;margin:22px 0 18px;background:#1c1c26 center/cover no-repeat;box-shadow:0 30px 80px #0009}
#title{font-size:24px;font-weight:800;text-align:center;max-width:520px}
#artist{font-size:17px;color:var(--dim);margin-top:6px;text-align:center}
#bar{width:100%;max-width:520px;height:8px;border-radius:4px;background:#ffffff22;margin:26px 0 8px;position:relative}
#fill{position:absolute;left:0;top:0;bottom:0;border-radius:4px;background:var(--fg);width:0}
#times{width:100%;max-width:520px;display:flex;justify-content:space-between;color:var(--dim);font-size:13px;font-variant-numeric:tabular-nums}
#ctl{display:flex;align-items:center;gap:26px;margin:20px 0}
button{border:0;background:#ffffff14;color:var(--fg);border-radius:50%;width:64px;height:64px;font-size:24px;cursor:pointer}
button:active{transform:scale(.94)}
#play{width:86px;height:86px;background:var(--fg);color:var(--bg);font-size:32px}
#like.on{color:#ff4d6d}
#vol{width:100%;max-width:520px;display:flex;gap:12px;align-items:center;color:var(--dim)}
input[type=range]{flex:1;accent-color:var(--acc)}
#next{color:var(--dim);font-size:14px;margin-top:18px;text-align:center}
#err{display:none;color:#ff7a7a;margin-top:14px;text-align:center}
</style></head><body><div id="bg"></div>
<header><span><span id="dot"></span>SONAR · ПУЛЬТ</span><span id="svc"></span></header>
<div id="cover"></div><div id="title">Ничего не играет</div><div id="artist">Включите трек в Sonar</div>
<div id="bar"><div id="fill"></div></div><div id="times"><span id="pos">0:00</span><span id="dur">0:00</span></div>
<div id="ctl"><button id="like" aria-label="Лайк">♥</button><button id="prev" aria-label="Назад">⏮</button>
<button id="play" aria-label="Пауза или играть">▶</button><button id="nextb" aria-label="Дальше">⏭</button><button id="vdown" aria-label="Тише">−</button></div>
<div id="vol"><span>🔈</span><input id="v" type="range" min="0" max="100"><span id="vn">0</span></div>
<div id="next"></div><div id="err">Sonar не отвечает. Тот же Wi-Fi? Sonar открыт?</div>
<script>
const K=new URLSearchParams(location.search).get('k')||'';let S=null,got=0,dragV=false;
const $=id=>document.getElementById(id);
const fmt=ms=>{ms=Math.max(0,ms|0);const s=Math.floor(ms/1000);return Math.floor(s/60)+':'+String(s%60).padStart(2,'0')};
async function cmd(action,value){try{await fetch('/api/cmd?k='+encodeURIComponent(K),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action,value})});setTimeout(poll,200)}catch(e){}}
async function poll(){try{const r=await fetch('/api/state?k='+encodeURIComponent(K),{cache:'no-store'});if(!r.ok)throw 0;S=await r.json();got=performance.now();$('err').style.display='none';$('dot').style.background='#3ddc84';draw()}catch(e){$('err').style.display='block';$('dot').style.background='#ff4d6d'}}
function draw(){if(!S)return;const t=S.track;
 $('title').textContent=t?t.title:'Ничего не играет';$('artist').textContent=t?t.artist:'Включите трек в Sonar';
 $('svc').textContent=t?t.service:'';$('cover').style.backgroundImage=t&&t.cover?'url("'+t.cover.replace(/"/g,'')+'")':'none';
 $('play').textContent=S.playing?'❚❚':'▶';$('like').classList.toggle('on',!!(t&&t.liked));
 if(!dragV){$('v').value=S.volume;$('vn').textContent=S.volume}
 $('next').textContent=S.next?'Дальше: '+S.next.artist+' — '+S.next.title:'';tick()}
function tick(){if(!S)return;const pos=S.position+(S.playing?performance.now()-got:0),d=S.duration||1;
 $('fill').style.width=Math.min(100,pos/d*100)+'%';$('pos').textContent=fmt(Math.min(pos,d));$('dur').textContent=fmt(S.duration)}
$('play').onclick=()=>cmd('toggle');$('nextb').onclick=()=>cmd('next');$('prev').onclick=()=>cmd('prev');$('like').onclick=()=>cmd('like');
$('vdown').onclick=()=>cmd('vol_down');
$('v').oninput=e=>{dragV=true;$('vn').textContent=e.target.value};$('v').onchange=e=>{dragV=false;cmd('volume',+e.target.value)};
$('bar').onclick=e=>{if(!S||!S.duration)return;const r=$('bar').getBoundingClientRect();cmd('seek',Math.round((e.clientX-r.left)/r.width*S.duration))};
setInterval(poll,1000);setInterval(tick,250);poll();
</script></body></html>"""
