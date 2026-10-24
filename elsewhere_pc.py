#!/usr/bin/env python3
"""
Elsewhere PC - iPhone helyszin-szimulalo (USB, Windows/Mac/Linux)

Mukodes:
  - a pymobiledevice3 "tunneld" szolgaltatasa USB-n at alagutat nyit az iPhone-hoz
  - ez a program egy tartosan nyitott DVT (Instruments) munkamenetet tart fenn
  - a helyi weboldalon (http://127.0.0.1:8765) terkepre kattintva teleportalsz

Fontos: a szimulalt hely addig el, amig ez a program fut es a telefon be van dugva.
Futtatas:  python elsewhere_pc.py          (valodi telefonnal)
           python elsewhere_pc.py --demo   (telefon nelkul, csak a felulet kiprobalasa)
"""
import asyncio
import json
import sys
import threading
import webbrowser
from contextlib import AsyncExitStack, suppress
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = 8765
DEMO = "--demo" in sys.argv
WATCHDOG_SECONDS = 20

if not DEMO:
    from pymobiledevice3.services.dvt.instruments.dvt_provider import DvtProvider
    from pymobiledevice3.services.dvt.instruments.location_simulation import LocationSimulation
    from pymobiledevice3.tunneld.api import get_tunneld_devices


class Spoofer:
    """Egy hatterszalon futo asyncio ciklus, ami tartja a telefonnal a kapcsolatot."""

    def __init__(self):
        self.loop = asyncio.new_event_loop()
        threading.Thread(target=self.loop.run_forever, daemon=True).start()
        self.stack = None
        self.rsd = None
        self.loc = None
        self.target = None  # (lat, lon) amit tartani kell
        self.message = "Meg nincs beallitott hely."
        self.device = ""
        self.lock = None
        self.call(self._init())
        asyncio.run_coroutine_threadsafe(self._watchdog(), self.loop)

    def call(self, coro, timeout=60):
        return asyncio.run_coroutine_threadsafe(coro, self.loop).result(timeout)

    async def _init(self):
        self.lock = asyncio.Lock()

    # ---- kapcsolat ----
    async def _disconnect(self):
        if self.stack is not None:
            with suppress(Exception):
                await self.stack.aclose()
        if self.rsd is not None:
            with suppress(Exception):
                await self.rsd.close()
        self.stack = self.rsd = self.loc = None

    async def _connect(self):
        await self._disconnect()
        if DEMO:
            self.loc = object()
            self.device = "DEMO (nincs valodi telefon)"
            return
        try:
            rsds = await get_tunneld_devices()
        except Exception as e:
            raise RuntimeError(
                "A tunneld nem elerheto. Inditsd el rendszergazdakent: "
                "python -m pymobiledevice3 remote tunneld  (" + type(e).__name__ + ")"
            ) from e
        if not rsds:
            raise RuntimeError(
                "Nem talalok iPhone-t. Dugd be kabellel, oldd fel, "
                "koppints a Trust (Megbizom) gombra, es varj par masodpercet."
            )
        rsd = rsds[0]
        for extra in rsds[1:]:
            with suppress(Exception):
                await extra.close()
        stack = AsyncExitStack()
        try:
            dvt = await stack.enter_async_context(DvtProvider(rsd))
            loc = await stack.enter_async_context(LocationSimulation(dvt))
        except BaseException:
            with suppress(Exception):
                await stack.aclose()
            with suppress(Exception):
                await rsd.close()
            raise
        self.stack, self.rsd, self.loc = stack, rsd, loc
        self.device = str(getattr(rsd, "udid", "iPhone"))

    async def _apply(self, lat, lon):
        if DEMO:
            return
        await self.loc.set(lat, lon)

    # ---- publikus muveletek ----
    async def set_location(self, lat, lon):
        async with self.lock:
            try:
                if self.loc is None:
                    await self._connect()
                await self._apply(lat, lon)
            except Exception:
                # egyszer ujracsatlakozunk, mielott feladnank
                await self._connect()
                await self._apply(lat, lon)
            self.target = (lat, lon)
            self.message = f"Hely beallitva: {lat:.6f}, {lon:.6f}"

    async def clear(self):
        async with self.lock:
            self.target = None
            if self.loc is not None and not DEMO:
                with suppress(Exception):
                    await self.loc.clear()
            await self._disconnect()
            self.message = "Valodi GPS visszaallitva."

    async def status(self):
        return {
            "connected": self.loc is not None,
            "device": self.device,
            "target": self.target,
            "message": self.message,
            "demo": DEMO,
        }

    async def _watchdog(self):
        """Idonkent ujra elkuldi a helyet; ha a kapcsolat megszakadt, ujracsatlakozik."""
        while True:
            await asyncio.sleep(WATCHDOG_SECONDS)
            if self.target is None:
                continue
            async with self.lock:
                try:
                    if self.loc is None:
                        await self._connect()
                    await self._apply(*self.target)
                except Exception as e:
                    await self._disconnect()
                    self.message = f"Kapcsolat megszakadt, ujraprobalom... ({e})"


SPOOFER = None

PAGE = r"""<!doctype html>
<html lang="hu">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Elsewhere PC</title>
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.css">
<style>
  :root { --bg:#fff; --fg:#1b1d21; --muted:#6b7280; --card:#f4f5f7; --line:#d9dce1; --accent:#ff5a2c; --ok:#16a34a; --err:#dc2626; }
  @media (prefers-color-scheme: dark) {
    :root { --bg:#14161a; --fg:#eceef2; --muted:#9aa1ad; --card:#1d2026; --line:#2e333b; }
  }
  * { box-sizing: border-box; }
  html, body { height:100%; margin:0; }
  body { font:15px/1.4 system-ui, -apple-system, Segoe UI, sans-serif; background:var(--bg); color:var(--fg); display:flex; flex-direction:column; }
  header { padding:10px 14px; background:var(--card); border-bottom:1px solid var(--line); display:flex; flex-wrap:wrap; gap:8px; align-items:center; }
  header h1 { font-size:16px; margin:0 10px 0 0; }
  input, button { font:inherit; padding:8px 10px; border-radius:8px; border:1px solid var(--line); background:var(--bg); color:var(--fg); }
  input.search { flex:1 1 220px; min-width:160px; }
  input.num { width:120px; }
  button { cursor:pointer; }
  button.primary { background:var(--accent); border-color:var(--accent); color:#111; font-weight:600; }
  button:disabled { opacity:.5; cursor:default; }
  #map { flex:1; min-height:300px; }
  footer { padding:8px 14px; background:var(--card); border-top:1px solid var(--line); display:flex; gap:10px; align-items:center; }
  #dot { width:10px; height:10px; border-radius:50%; background:var(--muted); flex:none; }
  #dot.on { background:var(--ok); } #dot.bad { background:var(--err); }
  #msg { overflow-wrap:anywhere; }
  .results { position:absolute; z-index:1000; top:56px; left:14px; right:14px; max-width:520px; background:var(--card); border:1px solid var(--line); border-radius:8px; display:none; }
  .results div { padding:8px 10px; cursor:pointer; border-bottom:1px solid var(--line); }
  .results div:last-child { border-bottom:0; }
  .results div:hover { background:var(--line); }
</style>
</head>
<body>
<header>
  <h1>Elsewhere PC</h1>
  <input id="q" class="search" placeholder="Keress helyet (pl. Eiffel-torony, Budapest)" autocomplete="off">
  <button id="go">Keres</button>
  <input id="lat" class="num" placeholder="Szelesseg">
  <input id="lon" class="num" placeholder="Hosszusag">
  <button id="tp" class="primary">Teleport ide</button>
  <button id="real">Valodi GPS</button>
</header>
<div id="results" class="results"></div>
<div id="map"></div>
<footer><span id="dot"></span><span id="msg">Kattints a terkepre egy hely kivalasztasahoz.</span></footer>

<script src="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.js"></script>
<script>
const $ = id => document.getElementById(id);
const map = L.map('map').setView([47.4979, 19.0402], 12);
L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
  maxZoom: 19, attribution: '&copy; OpenStreetMap'
}).addTo(map);
let pick = null, active = null;

function setPick(lat, lon, pan) {
  if (pick) pick.setLatLng([lat, lon]); else pick = L.marker([lat, lon]).addTo(map);
  $('lat').value = lat.toFixed(6); $('lon').value = lon.toFixed(6);
  if (pan) map.setView([lat, lon], Math.max(map.getZoom(), 15));
}
map.on('click', e => setPick(e.latlng.lat, e.latlng.lng, false));

function say(text, state) {
  $('msg').textContent = text;
  $('dot').className = state || '';
}

async function api(path, body) {
  const r = await fetch(path, body ? {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)} : {});
  const j = await r.json();
  if (!r.ok) throw new Error(j.error || r.statusText);
  return j;
}

$('tp').onclick = async () => {
  const lat = parseFloat($('lat').value), lon = parseFloat($('lon').value);
  if (isNaN(lat) || isNaN(lon)) { say('Valassz ki helyet a terkepen, vagy irj be koordinatakat.', 'bad'); return; }
  $('tp').disabled = true; say('Teleportalas...', '');
  try {
    const s = await api('/api/set', {lat, lon});
    say(s.message, 'on');
    if (active) active.setLatLng([lat, lon]);
    else active = L.circleMarker([lat, lon], {radius:9, color:'#16a34a', fillOpacity:.6}).addTo(map);
  } catch (e) { say(e.message, 'bad'); }
  $('tp').disabled = false;
};

$('real').onclick = async () => {
  try {
    const s = await api('/api/clear', {});
    say(s.message, '');
    if (active) { map.removeLayer(active); active = null; }
  } catch (e) { say(e.message, 'bad'); }
};

async function search() {
  const q = $('q').value.trim();
  if (!q) return;
  const box = $('results'); box.innerHTML = ''; box.style.display = 'none';
  try {
    const r = await fetch('https://nominatim.openstreetmap.org/search?format=json&limit=5&q=' + encodeURIComponent(q));
    const list = await r.json();
    if (!list.length) { say('Nincs talalat.', 'bad'); return; }
    list.forEach(p => {
      const d = document.createElement('div');
      d.textContent = p.display_name;
      d.onclick = () => { setPick(parseFloat(p.lat), parseFloat(p.lon), true); box.style.display = 'none'; };
      box.appendChild(d);
    });
    box.style.display = 'block';
  } catch (e) { say('A kereses nem sikerult: ' + e.message, 'bad'); }
}
$('go').onclick = search;
$('q').addEventListener('keydown', e => { if (e.key === 'Enter') search(); });

async function poll() {
  try {
    const s = await api('/api/status');
    $('dot').className = s.target ? 'on' : '';
    if (s.target && !active) active = L.circleMarker(s.target, {radius:9, color:'#16a34a', fillOpacity:.6}).addTo(map);
    if (!s.target && active) { map.removeLayer(active); active = null; }
    if (s.demo && !$('msg').dataset.demo) { $('msg').dataset.demo = 1; say('DEMO mod: nincs valodi telefon.', ''); }
  } catch (e) { say('A program nem elerheto. Fut az elsewhere_pc.py?', 'bad'); }
}
setInterval(poll, 5000); poll();
</script>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _send(self, code, payload, ctype="application/json; charset=utf-8"):
        data = payload if isinstance(payload, bytes) else json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}")

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            self._send(200, PAGE.encode("utf-8"), "text/html; charset=utf-8")
        elif self.path == "/api/status":
            self._send(200, SPOOFER.call(SPOOFER.status()))
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        try:
            if self.path == "/api/set":
                b = self._body()
                lat, lon = float(b["lat"]), float(b["lon"])
                if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                    raise ValueError("A koordinata ervenytelen.")
                SPOOFER.call(SPOOFER.set_location(lat, lon))
                self._send(200, SPOOFER.call(SPOOFER.status()))
            elif self.path == "/api/clear":
                SPOOFER.call(SPOOFER.clear())
                self._send(200, SPOOFER.call(SPOOFER.status()))
            else:
                self._send(404, {"error": "not found"})
        except Exception as e:  # a hibauzenet megjelenik a weboldalon
            self._send(500, {"error": f"{type(e).__name__}: {e}" if not str(e) else str(e)})


def main():
    global SPOOFER
    SPOOFER = Spoofer()
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    url = f"http://127.0.0.1:{PORT}"
    print(f"Elsewhere PC fut: {url}" + ("  [DEMO mod]" if DEMO else ""))
    print("Hagyd nyitva ezt az ablakot: amig fut, a hely tartva marad. Kilepes: Ctrl+C")
    threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nKilepes, valodi GPS visszaallitasa...")
        with suppress(Exception):
            SPOOFER.call(SPOOFER.clear(), timeout=15)
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
