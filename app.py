"""
Chord Desktop Client  —  app.py
================================
Architecture: Python spins up a tiny local HTTP server that serves the
frontend HTML. pywebview loads it as a real http:// URL, so localStorage,
WebSockets, fetch, Notification API, and every other browser API work
exactly as they do in a normal browser. No pywebview JS bridge needed.

Run:
    pip install pywebview
    python app.py

Build to EXE:
    pip install pyinstaller
    pyinstaller --onefile --windowed --name Chord app.py
"""

import sys
import os
import time
import json
import threading
import subprocess
import urllib.request
import http.server
import socketserver
import socket

# ── helpers ───────────────────────────────────────────────────────────────────
def resource_path(rel):
    base = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, rel)

def find_free_port():
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]

# ── settings (simple JSON file next to the exe) ───────────────────────────────
SETTINGS_FILE = os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), 'chord_settings.json')

def load_settings():
    try:
        with open(SETTINGS_FILE, 'r') as f:
            return json.load(f)
    except Exception:
        return {}

def save_settings(data):
    try:
        with open(SETTINGS_FILE, 'w') as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass

# ── Chord backend (Node.js) ───────────────────────────────────────────────────
BACKEND_PORT = 3000
_backend_proc = None

def find_node():
    candidates = ['node', 'node.exe']
    if sys.platform == 'win32':
        candidates += [
            r'C:\Program Files\nodejs\node.exe',
            r'C:\Program Files (x86)\nodejs\node.exe',
            os.path.expanduser(r'~\AppData\Roaming\nvm\current\node.exe'),
        ]
    for c in candidates:
        try:
            subprocess.run([c, '--version'], capture_output=True, check=True, timeout=3)
            return c
        except Exception:
            pass
    return 'node'

def start_backend():
    global _backend_proc
    server_js = resource_path('server.js')
    if not os.path.exists(server_js):
        return False
    node = find_node()
    try:
        kw = {}
        if sys.platform == 'win32':
            kw['creationflags'] = subprocess.CREATE_NO_WINDOW
        _backend_proc = subprocess.Popen(
            [node, server_js],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            cwd=os.path.dirname(server_js), **kw
        )
        def _log(p):
            for line in iter(p.readline, b''):
                print('[backend]', line.decode(errors='replace').rstrip())
        for pipe in [_backend_proc.stdout, _backend_proc.stderr]:
            threading.Thread(target=_log, args=(pipe,), daemon=True).start()
    except FileNotFoundError:
        print('[chord] node not found')
        return False

    deadline = time.time() + 15
    while time.time() < deadline:
        try:
            urllib.request.urlopen(f'http://localhost:{BACKEND_PORT}/health', timeout=1)
            print('[chord] Chord backend ready ✅')
            return True
        except Exception:
            time.sleep(0.4)
    print('[chord] Backend did not start in time')
    return False

def stop_backend():
    global _backend_proc
    if _backend_proc and _backend_proc.poll() is None:
        _backend_proc.terminate()
        try:
            _backend_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _backend_proc.kill()
        _backend_proc = None

# ── Tiny HTTP server that serves the frontend HTML ────────────────────────────
# By serving over real HTTP, every browser API works perfectly.
# localStorage works. fetch() works. WebSockets work. No hacks needed.

FRONTEND_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Chord</title>
<style>
:root {
  --bg: #0d0e10; --bg2: #141618; --bg3: #1a1c1f; --bg4: #222528;
  --sidebar: #111315; --accent: #5865f2; --accent2: #4752c4;
  --green: #3ba55c; --red: #ed4245; --yellow: #faa61a;
  --text: #dcddde; --text2: #8e9297; --text3: #72767d;
  --border: #2a2c2f; --hover: rgba(255,255,255,.06);
  --sel: rgba(88,101,242,.3);
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: 'Segoe UI', system-ui, sans-serif; background: var(--bg); color: var(--text); height: 100vh; overflow: hidden; display: flex; flex-direction: column; font-size: 14px; }
button { font-family: inherit; cursor: pointer; border: none; outline: none; }
input, textarea { font-family: inherit; outline: none; border: none; color: var(--text); background: transparent; }
::-webkit-scrollbar { width: 4px; }
::-webkit-scrollbar-thumb { background: var(--bg4); border-radius: 2px; }

/* ── Buttons ── */
.btn { display: inline-flex; align-items: center; justify-content: center; gap: 6px; padding: 9px 18px; border-radius: 6px; font-size: 14px; font-weight: 600; transition: .15s; cursor: pointer; }
.btn-primary { background: var(--accent); color: #fff; }
.btn-primary:hover { background: var(--accent2); }
.btn-ghost { background: transparent; color: var(--text2); border: 1px solid var(--border); }
.btn-ghost:hover { background: var(--hover); color: var(--text); }
.btn-green { background: var(--green); color: #fff; }
.btn-green:hover { filter: brightness(1.1); }
.btn-red { background: var(--red); color: #fff; }
.btn-red:hover { filter: brightness(1.1); }
.btn-sm { padding: 5px 12px; font-size: 12px; border-radius: 5px; }
.btn-xs { padding: 3px 8px; font-size: 11px; border-radius: 4px; }

/* ── Input ── */
.inp { width: 100%; padding: 9px 12px; background: var(--bg3); border: 1px solid var(--border); border-radius: 6px; font-size: 14px; color: var(--text); transition: .15s; font-family: inherit; }
.inp:focus { border-color: var(--accent); }
.lbl { display: block; font-size: 11px; font-weight: 700; color: var(--text2); text-transform: uppercase; letter-spacing: .06em; margin: 12px 0 5px; }
.err { color: var(--red); font-size: 12px; margin-top: 6px; min-height: 16px; }
.ok  { color: var(--green); font-size: 12px; margin-top: 6px; }

/* ── Screens (switcher / auth) ── */
.screen { position: fixed; inset: 0; display: flex; align-items: center; justify-content: center; z-index: 100; }
#sw-screen { background: radial-gradient(ellipse at 25% 50%, #0d1235 0%, var(--bg) 70%); }
#auth-screen { background: radial-gradient(ellipse at 30% 40%, #121852 0%, var(--bg) 70%); }

.sw-box, .auth-box {
  background: var(--bg2); border: 1px solid var(--border);
  border-radius: 16px; padding: 36px; width: 460px; max-width: 94vw;
}
.sw-box h2, .auth-box h1 {
  font-size: 24px; font-weight: 800; margin-bottom: 6px;
  background: linear-gradient(135deg, #fff 30%, var(--accent));
  -webkit-background-clip: text; -webkit-text-fill-color: transparent;
}
.sw-box p, .auth-box small { color: var(--text2); font-size: 13px; display: block; margin-bottom: 20px; }
.sw-row { display: flex; gap: 8px; margin-bottom: 8px; }
.sw-row .inp { flex: 1; }
.saved-list { max-height: 180px; overflow-y: auto; margin: 10px 0 14px; }
.saved-item { display: flex; align-items: center; gap: 10px; padding: 9px 12px; border-radius: 8px; background: var(--bg3); margin-bottom: 5px; cursor: pointer; transition: .15s; }
.saved-item:hover { background: var(--bg4); }
.s-dot { width: 8px; height: 8px; border-radius: 50%; background: var(--text3); flex-shrink: 0; }
.s-dot.live { background: var(--green); }
.s-url { flex: 1; font-size: 12px; font-family: monospace; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--text); }
.sw-or { display: flex; align-items: center; gap: 10px; margin: 14px 0; color: var(--text3); font-size: 12px; }
.sw-or::before, .sw-or::after { content: ''; flex: 1; height: 1px; background: var(--border); }
.back-link { font-size: 12px; color: var(--text3); cursor: pointer; margin-bottom: 14px; display: inline-block; }
.back-link:hover { color: var(--text); }
.auth-toggle { font-size: 12px; color: var(--text2); cursor: pointer; margin-left: 10px; }
.auth-toggle b { color: var(--accent); }
.join-card { background: var(--bg3); border-radius: 8px; padding: 12px; margin: 10px 0; display: flex; align-items: center; gap: 12px; }
.join-icon { width: 46px; height: 46px; border-radius: 10px; display: flex; align-items: center; justify-content: center; font-size: 20px; font-weight: 800; color: #fff; flex-shrink: 0; }

/* ── App layout ── */
#app { display: flex; flex: 1; overflow: hidden; }

/* Server rail */
#rail { width: 68px; background: var(--sidebar); display: flex; flex-direction: column; align-items: center; padding: 10px 0; gap: 6px; overflow-y: auto; flex-shrink: 0; }
.rail-icon { width: 46px; height: 46px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 18px; font-weight: 700; color: #fff; cursor: pointer; transition: .2s; position: relative; flex-shrink: 0; user-select: none; }
.rail-icon:hover, .rail-icon.active { border-radius: 14px; }
.rail-icon::before { content: ''; position: absolute; left: -8px; top: 50%; transform: translateY(-50%); width: 4px; border-radius: 0 4px 4px 0; background: var(--accent); transition: .2s; height: 0; }
.rail-icon.active::before { height: 70%; }
.rail-icon:hover::before { height: 40%; }
.rail-div { width: 30px; height: 1px; background: var(--border); flex-shrink: 0; }
.rail-add { width: 46px; height: 46px; border-radius: 50%; background: var(--bg3); display: flex; align-items: center; justify-content: center; cursor: pointer; color: var(--green); font-size: 24px; transition: .2s; flex-shrink: 0; }
.rail-add:hover { background: var(--green); color: #fff; border-radius: 14px; }

/* Channel sidebar */
#ch-side { width: 232px; background: var(--bg2); display: flex; flex-direction: column; flex-shrink: 0; }
.side-header { height: 46px; padding: 0 14px; display: flex; align-items: center; gap: 8px; border-bottom: 1px solid var(--border); font-weight: 700; font-size: 14px; cursor: pointer; flex-shrink: 0; user-select: none; }
.side-header:hover { background: var(--hover); }
.side-header-name { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.ch-section { padding: 14px 8px 2px; font-size: 10px; font-weight: 700; text-transform: uppercase; letter-spacing: .07em; color: var(--text3); display: flex; justify-content: space-between; align-items: center; }
.ch-add-btn { cursor: pointer; font-size: 16px; padding: 0 4px; border-radius: 3px; color: var(--text2); }
.ch-add-btn:hover { background: var(--hover); color: var(--text); }
.ch-item { display: flex; align-items: center; gap: 8px; padding: 7px 8px; margin: 1px 6px; border-radius: 6px; cursor: pointer; color: var(--text2); transition: .12s; user-select: none; }
.ch-item:hover { background: var(--hover); color: var(--text); }
.ch-item.active { background: var(--sel); color: #fff; }
.ch-icon { font-size: 16px; width: 20px; text-align: center; flex-shrink: 0; }
.ch-name { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 14px; }
.vc-count { font-size: 11px; color: var(--green); font-weight: 600; }

/* User panel */
#user-panel { height: 50px; background: var(--bg3); display: flex; align-items: center; gap: 8px; padding: 0 8px; margin-top: auto; flex-shrink: 0; }
.u-av { width: 30px; height: 30px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 12px; font-weight: 700; color: #fff; flex-shrink: 0; cursor: pointer; }
.u-name { font-size: 13px; font-weight: 600; flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; cursor: pointer; }
.u-tag { font-size: 10px; color: var(--text3); font-family: monospace; }
.panel-btn { width: 28px; height: 28px; display: flex; align-items: center; justify-content: center; border-radius: 5px; cursor: pointer; color: var(--text2); font-size: 15px; transition: .12s; flex-shrink: 0; }
.panel-btn:hover { background: var(--hover); color: var(--text); }

/* DM sidebar */
#dm-side { width: 232px; background: var(--bg2); display: flex; flex-direction: column; flex-shrink: 0; }
.dm-search { padding: 8px 10px; flex-shrink: 0; }
.dm-search .inp { padding: 7px 10px; font-size: 13px; }
#dm-list { flex: 1; overflow-y: auto; padding: 4px 0; }
.dm-item { display: flex; align-items: center; gap: 9px; padding: 7px 10px; margin: 2px 6px; border-radius: 6px; cursor: pointer; color: var(--text2); transition: .12s; position: relative; }
.dm-item:hover { background: var(--hover); color: var(--text); }
.dm-item.active { background: var(--sel); color: #fff; }
.dm-av-wrap { position: relative; flex-shrink: 0; }
.dm-av { width: 34px; height: 34px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 13px; font-weight: 700; color: #fff; }
.dm-status { position: absolute; bottom: 0; right: 0; width: 10px; height: 10px; border-radius: 50%; border: 2px solid var(--bg2); }
.dm-status.online { background: var(--green); }
.dm-status.offline { background: var(--text3); }
.dm-info { flex: 1; min-width: 0; }
.dm-name { font-size: 13px; font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.dm-prev { font-size: 11px; color: var(--text3); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; margin-top: 1px; }
.dm-call-btn { opacity: 0; transition: .12s; font-size: 15px; padding: 2px 4px; border-radius: 4px; color: var(--green); }
.dm-item:hover .dm-call-btn { opacity: 1; }
.dm-call-btn:hover { background: rgba(59,165,92,.2); }
.dm-lower { height: 50px; background: var(--bg3); display: flex; align-items: center; gap: 8px; padding: 0 8px; flex-shrink: 0; }

/* Main content */
#main { flex: 1; display: flex; flex-direction: column; overflow: hidden; min-width: 0; }
.ch-header { height: 46px; padding: 0 14px; display: flex; align-items: center; gap: 8px; border-bottom: 1px solid var(--border); font-weight: 700; font-size: 15px; flex-shrink: 0; }
.ch-header-icon { color: var(--text2); font-size: 18px; flex-shrink: 0; }
.ch-sep { width: 1px; height: 18px; background: var(--border); flex-shrink: 0; }
.ch-topic { color: var(--text2); font-size: 13px; font-weight: 400; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

/* Messages */
#msgs { flex: 1; overflow-y: auto; padding: 8px 0; }
.day-div { display: flex; align-items: center; gap: 10px; padding: 12px 14px; font-size: 11px; color: var(--text3); }
.day-div::before, .day-div::after { content: ''; flex: 1; height: 1px; background: var(--border); }
.msg { display: flex; gap: 12px; padding: 3px 14px; transition: .1s; position: relative; }
.msg:hover { background: rgba(255,255,255,.02); }
.msg-av { width: 38px; height: 38px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 15px; font-weight: 700; color: #fff; flex-shrink: 0; margin-top: 2px; cursor: pointer; }
.msg-body { flex: 1; min-width: 0; }
.msg-meta { display: flex; align-items: baseline; gap: 8px; margin-bottom: 2px; }
.msg-author { font-weight: 600; font-size: 14px; cursor: pointer; }
.msg-author:hover { text-decoration: underline; }
.msg-time { font-size: 10px; color: var(--text3); font-family: monospace; }
.msg-content { font-size: 14px; line-height: 1.5; word-break: break-word; }
.msg-del { position: absolute; right: 14px; top: 50%; transform: translateY(-50%); opacity: 0; cursor: pointer; color: var(--red); font-size: 13px; background: var(--bg3); border-radius: 4px; padding: 2px 6px; border: 1px solid var(--border); transition: .1s; }
.msg:hover .msg-del { opacity: 1; }

/* Input area */
#input-area { padding: 0 14px 16px; flex-shrink: 0; }
.msg-box { background: var(--bg4); border-radius: 8px; display: flex; align-items: center; padding: 0 12px; gap: 8px; border: 1px solid transparent; transition: .15s; }
.msg-box:focus-within { border-color: var(--border); }
.msg-inp { flex: 1; background: transparent; font-size: 14px; padding: 12px 0; font-family: inherit; color: var(--text); }
.msg-inp::placeholder { color: var(--text3); }
.send-btn { background: transparent; color: var(--accent); font-size: 18px; padding: 4px 8px; border-radius: 5px; transition: .12s; flex-shrink: 0; cursor: pointer; border: none; }
.send-btn:hover { background: var(--accent); color: #fff; }

/* Members panel */
#mem-panel { width: 228px; background: var(--bg2); overflow-y: auto; flex-shrink: 0; padding: 14px 6px; }
.mem-section { font-size: 10px; font-weight: 700; text-transform: uppercase; color: var(--text3); padding: 8px 8px 4px; letter-spacing: .06em; }
.mem-row { display: flex; align-items: center; gap: 9px; padding: 5px 8px; border-radius: 6px; cursor: pointer; transition: .12s; }
.mem-row:hover { background: var(--hover); }
.mem-av-wrap { position: relative; flex-shrink: 0; }
.mem-av { width: 30px; height: 30px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 12px; font-weight: 700; color: #fff; }
.mem-online { position: absolute; bottom: 0; right: 0; width: 9px; height: 9px; border-radius: 50%; border: 2px solid var(--bg2); background: var(--green); }
.mem-name { font-size: 13px; color: var(--text2); flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.mem-role { font-size: 10px; color: var(--accent); font-weight: 600; }

/* VC panel */
#vc-view { flex: 1; display: flex; align-items: center; justify-content: center; }
.vc-card { background: var(--bg2); border: 1px solid var(--border); border-radius: 16px; padding: 32px 48px; text-align: center; min-width: 320px; }
.vc-card h2 { font-size: 20px; font-weight: 700; margin-bottom: 4px; }
.vc-sub { color: var(--text2); font-size: 13px; margin-bottom: 20px; }
.vc-parts { display: flex; flex-wrap: wrap; gap: 16px; justify-content: center; margin-bottom: 20px; min-height: 80px; }
.vc-part { display: flex; flex-direction: column; align-items: center; gap: 6px; }
.vc-pav { width: 64px; height: 64px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 24px; font-weight: 700; color: #fff; position: relative; transition: .25s; }
.vc-pav.muted::after { content: '🔇'; position: absolute; bottom: -2px; right: -2px; font-size: 13px; }
.vc-pname { font-size: 12px; color: var(--text2); font-weight: 600; }
.vc-ctrls { display: flex; gap: 10px; justify-content: center; }
.vc-btn { width: 46px; height: 46px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 18px; cursor: pointer; border: none; transition: .2s; font-family: inherit; }
.vc-btn.normal { background: var(--bg4); color: var(--text); }
.vc-btn.normal:hover { background: var(--hover); }
.vc-btn.active { background: var(--red); color: #fff; }
#vc-status { margin-top: 12px; font-size: 12px; color: var(--text2); }

/* Friends panel */
#friends-view { flex: 1; display: flex; flex-direction: column; overflow: hidden; }
.fp-tabs { height: 46px; padding: 0 14px; display: flex; align-items: center; gap: 4px; border-bottom: 1px solid var(--border); flex-shrink: 0; }
.fp-tab { padding: 5px 12px; border-radius: 6px; font-size: 13px; font-weight: 600; cursor: pointer; color: var(--text2); background: transparent; border: none; font-family: inherit; position: relative; transition: .12s; }
.fp-tab.active { background: var(--sel); color: #fff; }
.fp-tab:hover:not(.active) { background: var(--hover); }
.fp-badge { position: absolute; top: -3px; right: -3px; background: var(--red); color: #fff; font-size: 9px; font-weight: 700; min-width: 14px; height: 14px; border-radius: 7px; display: flex; align-items: center; justify-content: center; padding: 0 2px; }
#fp-body { flex: 1; overflow-y: auto; padding: 14px; }
.fr-row { display: flex; align-items: center; gap: 10px; padding: 10px 12px; border-radius: 8px; background: var(--bg3); margin-bottom: 7px; }
.fr-row:hover { background: var(--bg4); }
.fr-av { width: 38px; height: 38px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 14px; font-weight: 700; color: #fff; flex-shrink: 0; position: relative; }
.fr-info { flex: 1; min-width: 0; }
.fr-name { font-weight: 600; font-size: 14px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.fr-sub { font-size: 12px; color: var(--text2); }
.fr-acts { display: flex; gap: 5px; flex-shrink: 0; }
.add-box { background: var(--bg3); border-radius: 10px; padding: 16px; margin-bottom: 16px; }
.add-box h3 { font-size: 14px; font-weight: 700; margin-bottom: 4px; }
.add-box p { font-size: 12px; color: var(--text2); margin-bottom: 12px; }
.search-results { margin-top: 10px; display: flex; flex-direction: column; gap: 6px; }
.sr-row { display: flex; align-items: center; gap: 10px; padding: 8px 10px; border-radius: 8px; background: var(--bg4); }
.sr-av { width: 34px; height: 34px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 13px; font-weight: 700; color: #fff; flex-shrink: 0; }
.sr-info { flex: 1; min-width: 0; }
.sr-name { font-size: 13px; font-weight: 600; }
.sr-un { font-size: 11px; color: var(--text2); font-family: monospace; }

/* Welcome screen */
#welcome-view { flex: 1; display: flex; align-items: center; justify-content: center; flex-direction: column; gap: 12px; color: var(--text2); }

/* Call overlay */
#call-overlay { position: fixed; bottom: 24px; right: 24px; z-index: 500; background: var(--bg2); border: 1px solid var(--border); border-radius: 14px; padding: 18px 20px; width: 280px; box-shadow: 0 16px 48px rgba(0,0,0,.7); display: none; }
#call-overlay.show { display: block; animation: popIn .2s ease; }
@keyframes popIn { from { transform: scale(.9); opacity: 0; } to { transform: scale(1); opacity: 1; } }
.co-type { font-size: 10px; font-weight: 700; text-transform: uppercase; letter-spacing: .07em; margin-bottom: 8px; }
.co-type.incoming { color: var(--green); }
.co-type.outgoing { color: var(--yellow); }
.co-user { display: flex; align-items: center; gap: 10px; margin-bottom: 14px; }
.co-av { width: 44px; height: 44px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 18px; font-weight: 700; color: #fff; flex-shrink: 0; }
.co-name { font-weight: 700; font-size: 15px; }
.co-sub { font-size: 12px; color: var(--text2); }
.co-btns { display: flex; gap: 8px; }
.ring-anim { animation: ring 1.5s infinite; }
@keyframes ring { 0%,100% { box-shadow: 0 0 0 0 rgba(59,165,92,.4); } 50% { box-shadow: 0 0 0 8px rgba(59,165,92,0); } }
.co-timer { font-size: 12px; color: var(--text2); text-align: center; margin-top: 8px; font-family: monospace; }

/* Active call bar */
#call-bar { position: fixed; bottom: 0; left: 68px; right: 0; height: 44px; background: linear-gradient(90deg, #1d5c31, #194d27); display: none; align-items: center; padding: 0 16px; gap: 12px; border-top: 1px solid #2a7a40; z-index: 400; }
#call-bar.show { display: flex; }
.cb-name { font-weight: 600; font-size: 13px; flex: 1; }
.cb-dur { font-size: 12px; color: rgba(255,255,255,.7); font-family: monospace; }

/* Profile pop */
#prof-pop { position: fixed; z-index: 400; background: var(--bg2); border: 1px solid var(--border); border-radius: 12px; width: 260px; box-shadow: 0 16px 48px rgba(0,0,0,.7); overflow: hidden; display: none; }
#prof-pop.show { display: block; animation: popIn .15s ease; }
.pp-banner { height: 60px; }
.pp-body { padding: 8px 14px 14px; }
.pp-av { width: 56px; height: 56px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 22px; font-weight: 700; color: #fff; margin: -28px 0 0 12px; border: 4px solid var(--bg2); position: relative; z-index: 1; }
.pp-name { font-size: 16px; font-weight: 700; margin-top: 10px; }
.pp-un { font-size: 12px; color: var(--text2); font-family: monospace; }
.pp-bio { font-size: 12px; color: var(--text2); margin: 8px 0; line-height: 1.4; }
.pp-line { height: 1px; background: var(--border); margin: 10px 0; }
.pp-acts { display: flex; flex-direction: column; gap: 5px; }

/* Toast */
#toasts { position: fixed; bottom: 60px; right: 24px; display: flex; flex-direction: column; gap: 7px; z-index: 600; pointer-events: none; }
.toast { background: var(--bg3); border: 1px solid var(--border); border-radius: 8px; padding: 10px 14px; font-size: 13px; max-width: 300px; box-shadow: 0 6px 20px rgba(0,0,0,.5); animation: toastIn .2s; }
.toast.ok { border-color: var(--green); }
.toast.err { border-color: var(--red); }
.toast.info { border-color: var(--accent); }
@keyframes toastIn { from { transform: translateX(30px); opacity: 0; } to { transform: translateX(0); opacity: 1; } }

/* Modal */
.modal-bg { position: fixed; inset: 0; background: rgba(0,0,0,.6); display: flex; align-items: center; justify-content: center; z-index: 300; }
.modal { background: var(--bg2); border-radius: 12px; padding: 24px; width: 400px; max-width: 94vw; border: 1px solid var(--border); }
.modal h2 { font-size: 18px; font-weight: 700; margin-bottom: 14px; }
.modal-acts { display: flex; gap: 8px; justify-content: flex-end; margin-top: 18px; }

/* DM sidebar tabs */
.dm-side-tab { flex: 1; padding: 12px 8px; font-size: 13px; font-weight: 600; color: var(--text2); background: transparent; border: none; border-bottom: 2px solid transparent; cursor: pointer; font-family: inherit; transition: .12s; position: relative; }
.dm-side-tab:hover { color: var(--text); background: var(--hover); }
.dm-side-tab.active { color: var(--text); border-bottom-color: var(--accent); }

/* Friends in DM sidebar */
.fr-dm-item { display: flex; align-items: center; gap: 9px; padding: 8px 10px; margin: 2px 6px; border-radius: 6px; cursor: pointer; color: var(--text2); transition: .12s; }
.fr-dm-item:hover { background: var(--hover); color: var(--text); }
.fr-dm-name { font-size: 13px; font-weight: 600; flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.fr-dm-status { font-size: 11px; color: var(--text3); }
.fr-dm-acts { display: flex; gap: 3px; flex-shrink: 0; }
.pending-item { display: flex; align-items: center; gap: 9px; padding: 9px 10px; margin: 2px 6px; border-radius: 6px; background: rgba(88,101,242,.08); border: 1px solid rgba(88,101,242,.2); }
.pending-name { font-size: 13px; font-weight: 600; flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

/* Add Friend modal */
.add-friend-modal { text-align: center; padding: 8px 0; }
.add-friend-modal .big-icon { font-size: 48px; margin-bottom: 12px; }
.add-friend-modal h3 { font-size: 18px; font-weight: 700; margin-bottom: 6px; }
.add-friend-modal p { color: var(--text2); font-size: 13px; margin-bottom: 20px; }
.friend-search-result { display: flex; align-items: center; gap: 10px; padding: 10px 12px; border-radius: 8px; background: var(--bg3); margin-bottom: 6px; transition: .12s; }
.friend-search-result:hover { background: var(--bg4); }

.invite-box { display: flex; align-items: center; gap: 8px; background: var(--bg3); border-radius: 8px; padding: 10px 12px; margin: 10px 0; }
.invite-code { flex: 1; font-family: monospace; font-size: 18px; font-weight: 700; letter-spacing: 3px; color: var(--text); }

/* Ctx menu */
.ctx { position: fixed; background: var(--bg2); border: 1px solid var(--border); border-radius: 8px; padding: 4px; z-index: 700; min-width: 150px; box-shadow: 0 8px 24px rgba(0,0,0,.5); }
.ctx-item { padding: 7px 12px; border-radius: 5px; cursor: pointer; font-size: 13px; font-weight: 500; transition: .1s; color: var(--text); }
.ctx-item:hover { background: var(--hover); }
.ctx-item.danger { color: var(--red); }

/* Notif panel */
#notif-panel { position: fixed; top: 8px; right: 14px; z-index: 500; background: var(--bg2); border: 1px solid var(--border); border-radius: 12px; width: 300px; box-shadow: 0 16px 48px rgba(0,0,0,.6); display: none; max-height: 420px; overflow: hidden; flex-direction: column; }
#notif-panel.show { display: flex; animation: popIn .15s ease; }
.np-head { padding: 12px 14px; border-bottom: 1px solid var(--border); font-weight: 700; font-size: 14px; display: flex; align-items: center; justify-content: space-between; }
.np-body { overflow-y: auto; flex: 1; }
.np-item { padding: 10px 14px; border-bottom: 1px solid var(--border); cursor: pointer; transition: .1s; }
.np-item:hover { background: var(--hover); }
.np-item.unread { background: rgba(88,101,242,.08); }
.np-label { font-size: 10px; font-weight: 700; text-transform: uppercase; color: var(--text3); margin-bottom: 3px; }
.np-text { font-size: 13px; }
.np-time { font-size: 10px; color: var(--text3); margin-top: 2px; font-family: monospace; }
.np-empty { padding: 24px; text-align: center; color: var(--text3); font-size: 13px; }

.hidden { display: none !important; }
.badge { display: inline-flex; align-items: center; justify-content: center; background: var(--red); color: #fff; font-size: 9px; font-weight: 700; min-width: 16px; height: 16px; border-radius: 8px; padding: 0 3px; position: absolute; top: -3px; right: -3px; }
</style>
</head>
<body>

<!-- ── Server Switcher ── -->
<div id="sw-screen" class="screen">
  <div class="sw-box">
    <h2>Connect to Chord</h2>
    <p>Enter a backend URL to connect, or join a server with an invite code.</p>
    <div class="sw-row">
      <input id="sw-url" class="inp" type="url" placeholder="http://localhost:3000"
             onkeydown="if(event.key==='Enter')swConnect()">
      <button class="btn btn-primary" onclick="swConnect()">Connect</button>
    </div>
    <div class="err" id="sw-err"></div>
    <div class="saved-list" id="saved-list"></div>
    <div class="sw-or">or</div>
    <button class="btn btn-ghost" style="width:100%;margin-bottom:6px;" onclick="swConnect('https://thl2lsbc-3000.use.devtunnels.ms')">
      🌐 Default server (thl2lsbc-3000.use.devtunnels.ms)
    </button>
    <button class="btn btn-ghost" style="width:100%" onclick="swLocal()">
      🖥️ Local server (localhost:3000)
    </button>
    <div style="margin-top:20px; border-top:1px solid var(--border); padding-top:16px;">
      <div style="font-size:12px;color:var(--text2);margin-bottom:8px;">Join with invite code (after connecting)</div>
      <div class="sw-row">
        <input id="sw-code" class="inp" placeholder="Invite code e.g. ab12cd34"
               onkeydown="if(event.key==='Enter')previewInvite()">
        <button class="btn btn-ghost" onclick="previewInvite()">Preview</button>
      </div>
      <div id="join-preview"></div>
    </div>
    <div style="margin-top:12px;font-size:11px;color:var(--text3);text-align:center;">
      Demo: alice / bob / charlie &nbsp;·&nbsp; password: password123
    </div>
  </div>
</div>

<!-- ── Auth Screen ── -->
<div id="auth-screen" class="screen hidden">
  <div class="auth-box">
    <div class="back-link" onclick="showSwitcher()">← Back to server list</div>
    <h1 id="auth-title">Welcome back</h1>
    <small id="auth-srv"></small>
    <div id="reg-name-row" class="hidden">
      <label class="lbl">Display Name</label>
      <input id="reg-name" class="inp" placeholder="Your name">
    </div>
    <label class="lbl">Username</label>
    <input id="auth-un" class="inp" placeholder="username" autocomplete="username">
    <label class="lbl">Password</label>
    <input id="auth-pw" class="inp" type="password" placeholder="••••••••"
           autocomplete="current-password" onkeydown="if(event.key==='Enter')doAuth()">
    <div class="err" id="auth-err"></div>
    <div style="margin-top:16px;display:flex;align-items:center;gap:8px;">
      <button class="btn btn-primary" id="auth-btn" onclick="doAuth()">Log In</button>
      <span class="auth-toggle" onclick="toggleAuthMode()">
        Need an account? <b>Register</b>
      </span>
    </div>
  </div>
</div>

<!-- ── Main App ── -->
<div id="app" class="hidden">

  <!-- Server rail -->
  <div id="rail">
    <div class="rail-icon" id="dms-btn" title="Direct Messages"
         style="background:#5865f2;font-size:20px;position:relative"
         onclick="showDMs()">
      💬
      <span class="badge hidden" id="dm-badge" style="font-size:9px;"></span>
    </div>
    <div class="rail-icon" id="friends-btn" title="Friends"
         style="background:#3ba55c;font-size:20px;position:relative"
         onclick="showFriendsView()">
      👥
      <span class="badge hidden" id="fr-badge" style="font-size:9px;"></span>
    </div>
    <div class="rail-div"></div>
    <div id="server-icons"></div>
    <div class="rail-add" title="Add Server" onclick="showAddServer()">+</div>
  </div>

  <!-- Channel sidebar -->
  <div id="ch-side">
    <div class="side-header" onclick="showServerMenu()">
      <span class="side-header-name" id="srv-name">Select a server</span>
      <span style="color:var(--text2);font-size:11px">▼</span>
    </div>
    <div id="ch-list" style="flex:1;overflow-y:auto;padding-bottom:8px;"></div>
    <div id="user-panel">
      <div class="u-av" id="pan-av" onclick="showMyProfile(event)"></div>
      <div style="flex:1;min-width:0;" onclick="showMyProfile(event)">
        <div class="u-name" id="pan-name"></div>
        <div class="u-tag" id="pan-tag"></div>
      </div>
      <div class="panel-btn" title="Edit profile" onclick="showEditProfile()">⚙️</div>
    </div>
  </div>

  <!-- DM sidebar -->
  <div id="dm-side" class="hidden">
    <div style="display:flex;border-bottom:1px solid var(--border);flex-shrink:0;">
      <button id="dm-tab-msgs" class="dm-side-tab active" onclick="dmSideTab('msgs',this)">Messages</button>
      <button id="dm-tab-friends" class="dm-side-tab" onclick="dmSideTab('friends',this)" style="position:relative;">
        Friends
        <span class="badge hidden" id="fr-badge2" style="font-size:9px;top:-2px;right:-2px;"></span>
      </button>
    </div>
    <!-- Messages pane -->
    <div id="dm-msgs-pane" style="display:flex;flex-direction:column;flex:1;overflow:hidden;">
      <div class="dm-search">
        <input id="dm-search" class="inp" placeholder="🔍 Search conversations" oninput="filterDMs(this.value)">
      </div>
      <div id="dm-list" style="flex:1;overflow-y:auto;"></div>
      <button class="btn btn-ghost btn-sm" onclick="showNewDM()" style="margin:8px;justify-content:center;">✏️ New Message</button>
    </div>
    <!-- Friends pane -->
    <div id="dm-friends-pane" style="display:none;flex-direction:column;flex:1;overflow:hidden;">
      <div style="padding:8px 10px;flex-shrink:0;display:flex;gap:6px;">
        <button class="btn btn-primary btn-sm" style="flex:1;justify-content:center;" onclick="showAddFriendModal()">➕ Add Friend</button>
      </div>
      <div id="dm-fr-list" style="flex:1;overflow-y:auto;padding:4px 0;"></div>
    </div>
    <div class="dm-lower">
      <div class="u-av" id="pan-av2" style="width:30px;height:30px;font-size:12px;"></div>
      <div style="flex:1;min-width:0;margin-left:8px;">
        <div class="u-name" id="pan-name2" style="font-size:13px;"></div>
        <div class="u-tag" id="pan-tag2" style="font-size:10px;"></div>
      </div>
    </div>
  </div>

  <!-- Main area -->
  <div id="main">
    <!-- Welcome -->
    <div id="welcome-view">
      <div style="font-size:52px;">⚡</div>
      <div style="font-size:20px;font-weight:700;color:var(--text);">Pick a channel to start chatting</div>
      <div>Or open a DM and call a friend</div>
    </div>

    <!-- Chat view -->
    <div id="chat-view" class="hidden" style="display:flex;flex-direction:column;flex:1;overflow:hidden;">
      <div class="ch-header">
        <span class="ch-header-icon" id="chat-icon">#</span>
        <span id="chat-name" style="font-size:15px;font-weight:700;"></span>
        <div class="ch-sep"></div>
        <span class="ch-topic" id="chat-topic"></span>
        <div style="margin-left:auto;display:flex;gap:6px;flex-shrink:0;">
          <button class="btn btn-ghost btn-sm" id="call-hdr-btn" style="display:none" onclick="callDMUser()">📞 Call</button>
          <button class="btn btn-ghost btn-sm" onclick="toggleMembers()">👥</button>
        </div>
      </div>
      <div id="msgs"></div>
      <div id="input-area">
        <div class="msg-box">
          <input id="msg-inp" class="msg-inp" placeholder="Message…" onkeydown="onMsgKey(event)">
          <button class="send-btn" onclick="sendMsg()">➤</button>
        </div>
      </div>
    </div>

    <!-- Voice view -->
    <div id="vc-view" class="hidden" style="display:flex;">
      <div class="vc-card">
        <h2 id="vc-ch-name">Voice Channel</h2>
        <div class="vc-sub">Real-time audio · WebRTC</div>
        <div class="vc-parts" id="vc-parts"></div>
        <div class="vc-ctrls">
          <button class="vc-btn normal" id="vc-mute" onclick="toggleMute()">🎤</button>
          <button class="vc-btn normal" id="vc-deaf" onclick="toggleDeafen()">🔊</button>
          <button class="vc-btn active" onclick="leaveVC()">📞</button>
        </div>
        <div id="vc-status"></div>
      </div>
    </div>

    <!-- Friends view -->
    <div id="friends-view" class="hidden" style="display:flex;">
      <div class="fp-tabs">
        <button class="fp-tab active" id="fp-tab-all"     onclick="fpTab('all',this)">Friends</button>
        <button class="fp-tab"        id="fp-tab-pending" onclick="fpTab('pending',this)">Pending</button>
        <button class="fp-tab"        id="fp-tab-add"     onclick="fpTab('add',this)">➕ Add</button>
      </div>
      <div id="fp-body"></div>
    </div>
  </div>

  <!-- Members panel -->
  <div id="mem-panel" class="hidden">
    <div style="font-size:11px;font-weight:700;text-transform:uppercase;color:var(--text3);padding:14px 8px 8px;letter-spacing:.07em;">Members</div>
    <div id="mem-list"></div>
  </div>
</div>

<!-- ── Overlays ── -->

<!-- Incoming friend request popup -->
<div id="fr-popup" style="display:none;position:fixed;bottom:24px;left:50%;transform:translateX(-50%);z-index:800;
     background:var(--bg2);border:1px solid var(--green);border-radius:14px;
     padding:16px 20px;min-width:320px;max-width:400px;box-shadow:0 16px 48px rgba(0,0,0,.7);
     animation:popIn .2s ease;">
  <div style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.07em;color:var(--green);margin-bottom:10px;">👋 Friend Request</div>
  <div style="display:flex;align-items:center;gap:12px;margin-bottom:14px;">
    <div id="frp-av" style="width:44px;height:44px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:18px;font-weight:700;color:#fff;flex-shrink:0;"></div>
    <div>
      <div id="frp-name" style="font-weight:700;font-size:15px;"></div>
      <div style="font-size:12px;color:var(--text2);">wants to be your friend</div>
    </div>
  </div>
  <div style="display:flex;gap:8px;">
    <button class="btn btn-green" style="flex:1;" onclick="frpAccept()">✓ Accept</button>
    <button class="btn btn-ghost" style="flex:1;" onclick="frpDecline()">✕ Decline</button>
    <button class="btn btn-ghost btn-sm" onclick="frpDismiss()">Later</button>
  </div>
</div>

<!-- Call overlay (incoming/outgoing) -->
<div id="call-overlay">
  <div class="co-type" id="co-type">Incoming Call</div>
  <div class="co-user">
    <div class="co-av" id="co-av">?</div>
    <div>
      <div class="co-name" id="co-name"></div>
      <div class="co-sub" id="co-sub"></div>
    </div>
  </div>
  <div class="co-btns" id="co-btns"></div>
  <div class="co-timer" id="co-timer"></div>
</div>

<!-- Active call bar -->
<div id="call-bar">
  <span>📞</span>
  <span class="cb-name" id="cb-name">In call</span>
  <span class="cb-dur" id="cb-dur">00:00</span>
  <button class="btn btn-red btn-sm" onclick="hangup()">Hang Up</button>
  <button class="btn btn-ghost btn-sm" id="cb-mute-btn" onclick="toggleCallMute()">🎤 Mute</button>
</div>

<!-- Profile popover -->
<div id="prof-pop">
  <div class="pp-banner" id="pp-banner"></div>
  <div class="pp-body">
    <div class="pp-av" id="pp-av"></div>
    <div class="pp-name" id="pp-name"></div>
    <div class="pp-un" id="pp-un"></div>
    <div class="pp-bio" id="pp-bio"></div>
    <div class="pp-line"></div>
    <div class="pp-acts" id="pp-acts"></div>
  </div>
</div>

<!-- Notification panel -->
<div id="notif-panel">
  <div class="np-head">
    Notifications
    <button class="btn btn-ghost btn-sm" onclick="markAllRead()">Mark read</button>
  </div>
  <div class="np-body" id="np-body"></div>
</div>

<!-- Toasts -->
<div id="toasts"></div>

<!-- Modal (re-used for all dialogs) -->
<div id="modal-bg" class="modal-bg hidden" onclick="if(event.target===this)closeModal()">
  <div class="modal">
    <h2 id="modal-title"></h2>
    <div id="modal-body"></div>
    <div class="modal-acts" id="modal-acts"></div>
  </div>
</div>

<script>
// ════════════════════════════════════════════════════════════════════
//  Everything is served over real HTTP so localStorage / fetch /
//  WebSocket all work exactly like a normal web page.  No pywebview
//  JS bridge is used at all.
// ════════════════════════════════════════════════════════════════════

// ── Storage (plain localStorage - works fine over HTTP) ───────────────────────
const LS = {
  get: k => { try { return JSON.parse(localStorage.getItem(k)); } catch { return null; } },
  set: (k, v) => { try { localStorage.setItem(k, JSON.stringify(v)); } catch {} },
  del: k => { try { localStorage.removeItem(k); } catch {} },
};

// ── State ─────────────────────────────────────────────────────────────────────
let API = '', WS = '';
const S = {
  token: null, user: null,
  servers: [], curSrv: null, channels: [], curCh: null,
  curDmId: null, curDmUser: null,
  members: [], allDms: [], friends: [],
  chWs: null, userWs: null,
  vcCh: null, localStream: null, vcPeers: {}, muted: false, deafened: false, vcParts: {},
  callId: null, callRole: null, callPeers: {}, callStream: null,
  callMuted: false, callActive: false, callTimer: null, callStart: null, ringTO: null,
  pendingCount: 0, dmUnread: 0,
  view: 'welcome',
};

// ── Utilities ─────────────────────────────────────────────────────────────────
async function apiFetch(method, path, body) {
  const r = await fetch(API + path, {
    method,
    headers: {
      'Content-Type': 'application/json',
      ...(S.token ? { 'Authorization': 'Bearer ' + S.token } : {}),
    },
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await r.json();
  if (!r.ok) throw new Error(data.error || 'Request failed');
  return data;
}

async function ping(url) {
  const c = new AbortController();
  const t = setTimeout(() => c.abort(), 4000);
  try {
    const r = await fetch(url, { signal: c.signal });
    clearTimeout(t);
    return r.ok ? await r.json() : null;
  } catch { clearTimeout(t); return null; }
}

function toast(msg, type = 'info', dur = 3500) {
  const el = document.createElement('div');
  el.className = `toast ${type}`;
  el.textContent = msg;
  document.getElementById('toasts').appendChild(el);
  setTimeout(() => el.remove(), dur);
}

function esc(s) {
  return String(s)
    .replace(/&/g,'&amp;')
    .replace(/</g,'&lt;')
    .replace(/>/g,'&gt;')
    .replace(/"/g,'&quot;');
}

function avatarEl(letter, color, size = 38, fontSize = 14) {
  return `<div style="width:${size}px;height:${size}px;border-radius:50%;background:${color};`+
    `display:flex;align-items:center;justify-content:center;font-size:${fontSize}px;`+
    `font-weight:700;color:#fff;flex-shrink:0;">${esc(letter)}</div>`;
}

function fmtTime(ts) {
  return new Date(ts * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}
function fmtDate(ts) {
  return new Date(ts * 1000).toLocaleDateString([], { weekday: 'long', month: 'long', day: 'numeric' });
}
function fmtRelative(ts) {
  const s = Math.floor((Date.now() - ts * 1000) / 1000);
  if (s < 60) return 'just now';
  if (s < 3600) return Math.floor(s / 60) + 'm ago';
  if (s < 86400) return Math.floor(s / 3600) + 'h ago';
  return new Date(ts * 1000).toLocaleDateString([], { month: 'short', day: 'numeric' });
}
function secFmt(s) {
  return String(Math.floor(s / 60)).padStart(2, '0') + ':' + String(s % 60).padStart(2, '0');
}

function notify(title, body) {
  if (typeof Notification !== 'undefined' && Notification.permission === 'granted') {
    try { new Notification(title, { body }); } catch {}
  }
}
function askNotifPerm() {
  if (typeof Notification !== 'undefined' && Notification.permission === 'default') {
    Notification.requestPermission();
  }
}

// Ring tone
let _rCtx = null, _rIv = null;
function startRing() {
  stopRing();
  try {
    _rCtx = new (window.AudioContext || window.webkitAudioContext)();
    function beep() {
      if (!_rCtx) return;
      const o = _rCtx.createOscillator(), g = _rCtx.createGain();
      o.connect(g); g.connect(_rCtx.destination);
      o.frequency.value = 880;
      g.gain.setValueAtTime(0.25, _rCtx.currentTime);
      g.gain.exponentialRampToValueAtTime(0.001, _rCtx.currentTime + 0.5);
      o.start(_rCtx.currentTime); o.stop(_rCtx.currentTime + 0.5);
    }
    beep(); _rIv = setInterval(beep, 1600);
  } catch {}
}
function stopRing() {
  clearInterval(_rIv); _rIv = null;
  if (_rCtx) { try { _rCtx.close(); } catch {} _rCtx = null; }
}

// ── Modal ─────────────────────────────────────────────────────────────────────
function showModal(title, bodyHtml, buttons) {
  document.getElementById('modal-title').textContent = title;
  document.getElementById('modal-body').innerHTML = bodyHtml;
  const acts = document.getElementById('modal-acts');
  acts.innerHTML = '';
  (buttons || []).forEach(b => {
    const btn = document.createElement('button');
    btn.className = `btn btn-sm ${b.cls || 'btn-primary'}`;
    btn.textContent = b.label;
    btn.onclick = b.fn;
    acts.appendChild(btn);
  });
  document.getElementById('modal-bg').classList.remove('hidden');
}
function closeModal() { document.getElementById('modal-bg').classList.add('hidden'); }

// ── Server Switcher ───────────────────────────────────────────────────────────
function savedServers() { return LS.get('chord_servers') || []; }

function saveSrv(url, name) {
  const list = savedServers().filter(s => s.url !== url);
  list.unshift({ url, name });
  LS.set('chord_servers', list.slice(0, 10));
}

function removeSrv(url) {
  LS.set('chord_servers', savedServers().filter(s => s.url !== url));
  renderSaved();
}

function renderSaved() {
  const el = document.getElementById('saved-list');
  const list = savedServers();
  if (!list.length) {
    el.innerHTML = '<div style="color:var(--text3);font-size:12px;padding:6px 0">No saved servers yet.</div>';
    return;
  }
  el.innerHTML = list.map((s, i) =>
    `<div class="saved-item" onclick="swConnect('${esc(s.url)}')">` +
    `<div class="s-dot" id="sdot-${i}"></div>` +
    `<div class="s-url">${esc(s.url)}</div>` +
    `<button class="btn-xs btn-ghost" style="background:transparent;border:none;color:var(--text3);cursor:pointer;padding:2px 6px;" onclick="event.stopPropagation();removeSrv('${esc(s.url)}')">✕</button>` +
    `</div>`
  ).join('');
  // Ping each server
  list.forEach((s, i) => {
    ping(s.url + '/health').then(d => {
      const dot = document.getElementById('sdot-' + i);
      if (dot) dot.className = 's-dot' + (d ? ' live' : '');
    });
  });
}

async function swConnect(rawUrl) {
  const inp = document.getElementById('sw-url');
  let url = (rawUrl || inp.value || '').trim().replace(/\/+$/, '');
  if (!url) { document.getElementById('sw-err').textContent = 'Enter a server URL'; return; }
  if (!url.startsWith('http')) url = 'http://' + url;
  document.getElementById('sw-err').textContent = 'Connecting…';
  const data = await ping(url + '/health');
  if (!data || !data.ok) {
    document.getElementById('sw-err').textContent = '❌ Could not connect to ' + url;
    return;
  }
  document.getElementById('sw-err').textContent = '';
  setBackend(url, data.server || url);
  saveSrv(url, data.server || '');
  showAuth();
}

function swLocal() { swConnect('http://localhost:3000'); }

function setBackend(httpUrl, name) {
  API = httpUrl + '/api';
  WS  = httpUrl.replace(/^http/, 'ws');
  document.getElementById('sw-err').textContent = '';
  // If switching servers, clear old token
  if (LS.get('chord_server') !== httpUrl) {
    LS.del('chord_token');
    S.token = null;
  }
  LS.set('chord_server', httpUrl);
  LS.set('chord_server_name', name || httpUrl);
}

async function previewInvite() {
  const code = (document.getElementById('sw-code').value || '').trim().replace(/.*\//, '');
  const el = document.getElementById('join-preview');
  if (!code) return;
  if (!API) { el.innerHTML = '<div class="err">Connect to a server first.</div>'; return; }
  el.innerHTML = '<div style="color:var(--text2);font-size:13px;margin-top:8px;">Checking…</div>';
  try {
    const srv = await apiFetch('GET', '/servers/invite/' + code);
    el.innerHTML = `
      <div class="join-card" style="margin-top:8px;">
        <div class="join-icon" style="background:${srv.icon_color}">${esc(srv.icon_emoji || srv.name[0])}</div>
        <div>
          <div style="font-weight:700;font-size:15px;">${esc(srv.name)}</div>
          <div style="font-size:12px;color:var(--text2);">${srv.member_count} members · ${esc(srv.description || 'No description')}</div>
        </div>
      </div>
      ${srv.already_member
        ? '<div class="ok" style="margin-top:6px;">✓ Already a member</div>'
        : `<button class="btn btn-primary btn-sm" style="margin-top:8px;" onclick="joinCode('${esc(code)}')">Join Server</button>`}`;
  } catch(e) {
    el.innerHTML = `<div class="err" style="margin-top:6px;">${esc(e.message)}</div>`;
  }
}

async function joinCode(code) {
  try {
    const srv = await apiFetch('POST', '/servers/invite/' + code + '/join');
    toast('Joined ' + srv.name, 'ok');
    document.getElementById('join-preview').innerHTML = '';
    await loadServers();
    showSwitcher();
    document.getElementById('sw-screen').classList.add('hidden');
    document.getElementById('app').classList.remove('hidden');
    selectServer(srv);
  } catch(e) { toast(e.message, 'err'); }
}

function showSwitcher() {
  document.getElementById('sw-screen').classList.remove('hidden');
  document.getElementById('auth-screen').classList.add('hidden');
  document.getElementById('app').classList.add('hidden');
  document.getElementById('sw-code').value = '';
  document.getElementById('join-preview').innerHTML = '';
  renderSaved();
}

// ── Auth ──────────────────────────────────────────────────────────────────────
let isRegMode = false;

function showAuth() {
  document.getElementById('sw-screen').classList.add('hidden');
  document.getElementById('auth-screen').classList.remove('hidden');
  document.getElementById('auth-srv').textContent = 'Server: ' + API.replace('/api', '');
}

function toggleAuthMode() {
  isRegMode = !isRegMode;
  document.getElementById('auth-title').textContent = isRegMode ? 'Create Account' : 'Welcome Back';
  document.getElementById('auth-btn').textContent = isRegMode ? 'Register' : 'Log In';
  document.getElementById('reg-name-row').classList.toggle('hidden', !isRegMode);
  document.querySelector('.auth-toggle').innerHTML = isRegMode
    ? 'Already have one? <b>Log In</b>'
    : 'Need an account? <b>Register</b>';
  document.getElementById('auth-err').textContent = '';
}

async function doAuth() {
  const un  = document.getElementById('auth-un').value.trim();
  const pw  = document.getElementById('auth-pw').value;
  const err = document.getElementById('auth-err');
  if (!un || !pw) { err.textContent = 'Fill in all fields.'; return; }
  try {
    let data;
    if (isRegMode) {
      const dn = document.getElementById('reg-name').value.trim() || un;
      data = await apiFetch('POST', '/register', { username: un, display_name: dn, password: pw });
    } else {
      data = await apiFetch('POST', '/login', { username: un, password: pw });
    }
    S.token = data.token;
    S.user  = data.user;
    LS.set('chord_token', data.token);
    bootApp();
  } catch(e) { err.textContent = e.message; }
}

function logout() {
  LS.del('chord_token'); S.token = null; S.user = null;
  if (S.userWs) S.userWs.close();
  endCall();
  document.getElementById('app').classList.add('hidden');
  showSwitcher();
}

// ── Boot ──────────────────────────────────────────────────────────────────────
async function bootApp() {
  if (!S.user) {
    try { S.user = await apiFetch('GET', '/me'); }
    catch { LS.del('chord_token'); S.token = null; showAuth(); return; }
  }
  document.getElementById('sw-screen').classList.add('hidden');
  document.getElementById('auth-screen').classList.add('hidden');
  document.getElementById('app').classList.remove('hidden');
  // Set user panels
  const u = S.user;
  const L = (u.display_name || u.username)[0].toUpperCase();
  ['pan-av','pan-av2'].forEach(id => {
    const el = document.getElementById(id);
    if (el) { el.style.background = u.avatar_color; el.textContent = L; }
  });
  ['pan-name','pan-name2'].forEach(id => {
    const el = document.getElementById(id); if (el) el.textContent = u.display_name;
  });
  ['pan-tag','pan-tag2'].forEach(id => {
    const el = document.getElementById(id); if (el) el.textContent = '@' + u.username;
  });
  await loadServers();
  connectUserWs();
  askNotifPerm();
  loadNotifs();
  loadFriendsSidebar();
  setView('welcome');
}

// ── User WebSocket ─────────────────────────────────────────────────────────────
function connectUserWs() {
  if (S.userWs) S.userWs.close();
  const ws = new WebSocket(`${WS}/ws/user/${S.user.id}?token=${S.token}`);
  ws.onmessage = e => handlePush(JSON.parse(e.data));
  ws.onclose = () => setTimeout(() => { if (S.token) connectUserWs(); }, 3000);
  S.userWs = ws;
}

function handlePush(msg) {
  switch (msg.type) {
    case 'new_dm':
      loadDMs();
      if (S.curDmId === msg.dm_id) appendMsg(msg.message);
      else {
        S.dmUnread++;
        updateDmBadge();
        toast('💬 ' + msg.message.display_name + ': ' + msg.message.content.slice(0, 50), 'info');
        notify('New message from ' + msg.message.display_name, msg.message.content.slice(0, 100));
      }
      break;
    case 'friend_request':
      S.pendingCount++;
      updatePendingBadge();
      loadNotifs();
      // Show inline popup with Accept/Decline
      showFriendRequestPopup(msg.from);
      notify('Friend Request', msg.from.display_name + ' wants to be friends');
      break;
    case 'friend_accepted':
      toast('✅ ' + msg.by.display_name + ' accepted your friend request', 'ok');
      loadFriendsSidebar();
      break;
    case 'call_ring':
      S.callId = msg.callId; S.callRole = 'callee';
      showCallOverlay('incoming', msg.caller);
      startRing();
      notify('📞 Incoming Call', msg.caller.display_name + ' is calling you…');
      S.ringTO = setTimeout(() => { if (S.callId === msg.callId) rejectCall(); }, 45000);
      break;
    case 'call_ringing':
      S.callId = msg.callId; S.callRole = 'caller';
      showCallOverlay('outgoing', msg.callee);
      break;
    case 'call_accepted':
      clearTimeout(S.ringTO); stopRing(); hideCallOverlay();
      startActiveCall(msg.callId, msg.callee);
      break;
    case 'call_rejected': case 'call_cancelled': case 'call_ended': case 'call_missed':
      clearTimeout(S.ringTO); stopRing(); hideCallOverlay(); endCall();
      toast(msg.type === 'call_missed' ? '📵 Missed call' : '📞 Call ended', 'info');
      break;
    case 'call_busy':
      toast('📵 User is busy', 'err'); break;
    case 'message_deleted':
      document.getElementById('msg-' + msg.message_id)?.remove(); break;
  }
}

function updateDmBadge() {
  const b = document.getElementById('dm-badge');
  if (!b) return;
  if (S.dmUnread > 0) { b.textContent = S.dmUnread > 9 ? '9+' : S.dmUnread; b.classList.remove('hidden'); }
  else b.classList.add('hidden');
}
function updatePendingBadge() {
  // Rail badge on Friends button
  const rb = document.getElementById('fr-badge');
  if (rb) {
    if (S.pendingCount > 0) { rb.textContent = S.pendingCount > 9 ? '9+' : S.pendingCount; rb.classList.remove('hidden'); }
    else rb.classList.add('hidden');
  }
  // Sidebar tab badge
  const sb = document.getElementById('fr-badge2');
  if (sb) {
    if (S.pendingCount > 0) { sb.textContent = S.pendingCount > 9 ? '9+' : S.pendingCount; sb.classList.remove('hidden'); }
    else sb.classList.add('hidden');
  }
  // Old pending tab badge
  const tab = document.getElementById('fp-tab-pending'); if (!tab) return;
  let b = tab.querySelector('.fp-badge');
  if (S.pendingCount > 0) {
    if (!b) { b = document.createElement('span'); b.className = 'fp-badge'; tab.appendChild(b); }
    b.textContent = S.pendingCount;
  } else { b?.remove(); }
}

// ── Notifications panel ───────────────────────────────────────────────────────
async function loadNotifs() {
  try {
    const notifs = await apiFetch('GET', '/notifications');
    const unread = notifs.filter(n => !n.read).length;
    S.pendingCount = notifs.filter(n => n.type === 'friend_request' && !n.read).length;
    updatePendingBadge();
    const el = document.getElementById('np-body');
    if (!notifs.length) { el.innerHTML = '<div class="np-empty">No notifications</div>'; return; }
    el.innerHTML = notifs.map(n => {
      const d = n.data || {};
      const body = n.type === 'friend_request' ? `<b>${esc(d.from_dn)}</b> sent you a friend request`
                 : n.type === 'friend_accepted' ? `<b>${esc(d.from_dn || '?')}</b> accepted your request`
                 : JSON.stringify(d);
      return `<div class="np-item${n.read ? '' : ' unread'}" onclick='handleNotifClick(${JSON.stringify(JSON.stringify(n))})'>
        <div class="np-label">${n.type.replace(/_/g,' ')}</div>
        <div class="np-text">${body}</div>
        <div class="np-time">${fmtRelative(n.created_at)}</div>
      </div>`;
    }).join('');
  } catch {}
}
async function markAllRead() { await apiFetch('POST', '/notifications/read'); loadNotifs(); }
function handleNotifClick(jsonStr) {
  const n = JSON.parse(jsonStr);
  closeNotifPanel();
  if (n.type === 'friend_request') { showDMs(); fpTab('pending', document.getElementById('fp-tab-pending')); }
}
function toggleNotifPanel() { document.getElementById('notif-panel').classList.toggle('show'); if (document.getElementById('notif-panel').classList.contains('show')) loadNotifs(); }
function closeNotifPanel() { document.getElementById('notif-panel').classList.remove('show'); }

// ── Servers ───────────────────────────────────────────────────────────────────
async function loadServers() {
  S.servers = await apiFetch('GET', '/servers');
  renderServerIcons();
}

function renderServerIcons() {
  const el = document.getElementById('server-icons');
  el.innerHTML = '';
  S.servers.forEach(srv => {
    const d = document.createElement('div');
    d.className = 'rail-icon' + (S.curSrv?.id === srv.id ? ' active' : '');
    d.style.background = srv.icon_color;
    d.title = srv.name;
    d.textContent = srv.icon_emoji || srv.name[0].toUpperCase();
    d.onclick = () => selectServer(srv);
    d.oncontextmenu = e => { e.preventDefault(); showSrvCtx(srv, e.clientX, e.clientY); };
    el.appendChild(d);
  });
}

async function selectServer(srv) {
  S.curSrv = srv; S.curDmId = null; S.curDmUser = null;
  document.getElementById('ch-side').style.display = 'flex';
  document.getElementById('dm-side').classList.add('hidden');
  document.getElementById('srv-name').textContent = srv.name;
  renderServerIcons();
  await Promise.all([loadChannels(), loadMembers()]);
  setView('welcome');
}

function showServerMenu() {
  if (!S.curSrv) return;
  apiFetch('GET', '/servers/' + S.curSrv.id).then(srv => {
    const link = API.replace('/api', '') + '/invite/' + srv.invite_code;
    const isOwner = S.curSrv.owner_id === S.user.id;
    showModal(srv.name, `
      <p style="color:var(--text2);font-size:13px;margin-bottom:12px;">${esc(srv.description || 'No description')} · ${srv.member_count} members</p>
      <div style="font-size:11px;font-weight:700;color:var(--text3);text-transform:uppercase;margin-bottom:6px;">Invite Code</div>
      <div class="invite-box">
        <span class="invite-code">${esc(srv.invite_code)}</span>
        <button class="btn btn-primary btn-sm" onclick="copyText('${esc(srv.invite_code)}',this)">Copy</button>
      </div>
      <div style="font-size:11px;color:var(--text2);margin-bottom:6px;word-break:break-all;">${esc(link)}</div>
      <button class="btn btn-ghost btn-sm" onclick="copyText('${esc(link)}',this)">📋 Copy Link</button>
      ${isOwner ? `<div style="margin-top:12px;"><button class="btn btn-ghost btn-sm" onclick="resetInvite()">🔄 Reset Code</button></div>` : ''}
    `, [{ label: 'Close', cls: 'btn-ghost', fn: closeModal }]);
  }).catch(e => toast(e.message, 'err'));
}

async function resetInvite() {
  try { await apiFetch('POST', '/servers/' + S.curSrv.id + '/invite/reset'); toast('Invite code reset', 'ok'); closeModal(); showServerMenu(); }
  catch(e) { toast(e.message, 'err'); }
}

function copyText(text, btn) {
  navigator.clipboard.writeText(text).then(() => {
    if (btn) { const o = btn.textContent; btn.textContent = 'Copied!'; setTimeout(() => btn.textContent = o, 1500); }
  }).catch(() => toast('Copy failed', 'err'));
}

function showSrvCtx(srv, x, y) {
  document.getElementById('ctx-el')?.remove();
  const el = document.createElement('div');
  el.id = 'ctx-el'; el.className = 'ctx';
  el.style.cssText = `left:${x}px;top:${y}px;`;
  el.innerHTML = `<div class="ctx-item" onclick="showServerMenu();document.getElementById('ctx-el')?.remove()">🔗 Invite People</div>` +
    (srv.owner_id === S.user.id
      ? `<div class="ctx-item danger" onclick="deleteServer(${srv.id})">🗑️ Delete Server</div>`
      : `<div class="ctx-item danger" onclick="leaveServer(${srv.id})">🚪 Leave Server</div>`);
  document.body.appendChild(el);
  setTimeout(() => document.addEventListener('click', function h() { el.remove(); document.removeEventListener('click', h); }), 0);
}

async function deleteServer(id) {
  document.getElementById('ctx-el')?.remove();
  if (!confirm('Delete server? This cannot be undone.')) return;
  try { await apiFetch('DELETE', '/servers/' + id); S.curSrv = null; await loadServers(); setView('welcome'); document.getElementById('srv-name').textContent = 'Select a server'; }
  catch(e) { toast(e.message, 'err'); }
}
async function leaveServer(id) {
  document.getElementById('ctx-el')?.remove();
  try { await apiFetch('DELETE', '/servers/' + id + '/leave'); S.curSrv = null; await loadServers(); setView('welcome'); }
  catch(e) { toast(e.message, 'err'); }
}

function showAddServer() {
  showModal('Add a Server', `
    <button class="btn btn-primary" style="width:100%;margin-bottom:8px;" onclick="closeModal();showCreateServer()">🏗️ Create a Server</button>
    <button class="btn btn-ghost" style="width:100%;" onclick="closeModal();showJoinServer()">🔗 Join with Invite Code</button>
  `, [{ label: 'Cancel', cls: 'btn-ghost', fn: closeModal }]);
}

function showCreateServer() {
  showModal('Create Server', `
    <label class="lbl">Server Name *</label>
    <input id="ns-name" class="inp" placeholder="My Server" style="margin-top:4px;">
    <label class="lbl">Description</label>
    <input id="ns-desc" class="inp" placeholder="What's this server about?" style="margin-top:4px;">
    <label class="lbl">Icon Emoji</label>
    <input id="ns-emoji" class="inp" placeholder="🎮" style="margin-top:4px;">
  `, [
    { label: 'Cancel', cls: 'btn-ghost', fn: closeModal },
    { label: 'Create', fn: async () => {
      const name = document.getElementById('ns-name').value.trim(); if (!name) return;
      try {
        const srv = await apiFetch('POST', '/servers', {
          name, description: document.getElementById('ns-desc').value.trim(),
          icon_emoji: document.getElementById('ns-emoji').value.trim(),
        });
        closeModal(); await loadServers(); selectServer(srv);
      } catch(e) { toast(e.message, 'err'); }
    }},
  ]);
}

function showJoinServer() {
  showModal('Join a Server', `
    <label class="lbl">Invite Code or Link</label>
    <input id="jc-code" class="inp" placeholder="ab12cd34" style="margin-top:4px;">
    <div id="jc-preview" style="margin-top:10px;"></div>
  `, [
    { label: 'Cancel', cls: 'btn-ghost', fn: closeModal },
    { label: 'Preview & Join', fn: async () => {
      let code = (document.getElementById('jc-code').value || '').trim().replace(/.*\//, '');
      const el = document.getElementById('jc-preview');
      el.innerHTML = '<div style="color:var(--text2);font-size:13px;">Checking…</div>';
      try {
        const srv = await apiFetch('GET', '/servers/invite/' + code);
        if (srv.already_member) { toast('Already a member!', 'ok'); closeModal(); return; }
        await apiFetch('POST', '/servers/invite/' + code + '/join');
        toast('Joined ' + srv.name, 'ok'); closeModal(); await loadServers(); selectServer(srv);
      } catch(e) { el.innerHTML = `<div class="err">${esc(e.message)}</div>`; }
    }},
  ]);
}

// ── Channels ──────────────────────────────────────────────────────────────────
async function loadChannels() {
  S.channels = await apiFetch('GET', '/servers/' + S.curSrv.id + '/channels');
  renderChannels();
}

function renderChannels() {
  const el = document.getElementById('ch-list'); el.innerHTML = '';
  const text  = S.channels.filter(c => c.type === 'text');
  const voice = S.channels.filter(c => c.type === 'voice');
  if (text.length) {
    el.innerHTML += `<div class="ch-section">Text <span class="ch-add-btn" onclick="showCreateChannel('text')">+</span></div>`;
    text.forEach(c => {
      el.innerHTML += `<div class="ch-item${S.curCh?.id===c.id?' active':''}" onclick="selectChannel(${c.id})" title="${esc(c.topic||'')}">
        <span class="ch-icon">#</span><span class="ch-name">${esc(c.name)}</span>
      </div>`;
    });
  }
  if (voice.length) {
    el.innerHTML += `<div class="ch-section">Voice <span class="ch-add-btn" onclick="showCreateChannel('voice')">+</span></div>`;
    voice.forEach(c => {
      const vm = c.voice_members || [];
      el.innerHTML += `<div class="ch-item${S.vcCh?.id===c.id?' active':''}" onclick="joinVC(${c.id},'${esc(c.name)}')">
        <span class="ch-icon">🔊</span><span class="ch-name">${esc(c.name)}</span>
        ${vm.length ? `<span class="vc-count">${vm.length}</span>` : ''}
      </div>`;
    });
  }
}

async function loadMembers() {
  S.members = await apiFetch('GET', '/servers/' + S.curSrv.id + '/members');
  const el = document.getElementById('mem-list'); el.innerHTML = '';
  const owners  = S.members.filter(m => m.role === 'owner');
  const regular = S.members.filter(m => m.role !== 'owner');
  if (owners.length) {
    el.innerHTML += '<div class="mem-section">Owner</div>';
    owners.forEach(m => el.innerHTML += memberRow(m));
  }
  if (regular.length) {
    el.innerHTML += `<div class="mem-section">Members — ${regular.length}</div>`;
    regular.forEach(m => el.innerHTML += memberRow(m));
  }
}

function memberRow(m) {
  return `<div class="mem-row" onclick="showProfile('${esc(m.username)}',event)">
    <div class="mem-av-wrap">
      <div class="mem-av" style="background:${m.avatar_color};">${m.display_name[0].toUpperCase()}</div>
      <div class="mem-online"></div>
    </div>
    <span class="mem-name">${esc(m.display_name)}</span>
    ${m.role==='owner' ? '<span class="mem-role">👑</span>' : ''}
  </div>`;
}

function toggleMembers() { document.getElementById('mem-panel').classList.toggle('hidden'); }

function showCreateChannel(type) {
  showModal(`New ${type==='text'?'Text':'Voice'} Channel`, `
    <label class="lbl">Channel Name *</label>
    <input id="nc-name" class="inp" placeholder="${type==='text'?'general':'Chill VC'}" style="margin-top:4px;">
    ${type==='text' ? '<label class="lbl">Topic</label><input id="nc-topic" class="inp" placeholder="What is this channel about?" style="margin-top:4px;">' : ''}
  `, [
    { label: 'Cancel', cls: 'btn-ghost', fn: closeModal },
    { label: 'Create', fn: async () => {
      const name = (document.getElementById('nc-name').value || '').trim(); if (!name) return;
      const topic = (document.getElementById('nc-topic')?.value || '').trim();
      try { await apiFetch('POST', '/servers/' + S.curSrv.id + '/channels', { name, type, topic }); closeModal(); await loadChannels(); }
      catch(e) { toast(e.message, 'err'); }
    }},
  ]);
}

// ── Messages ──────────────────────────────────────────────────────────────────
let _lastDateStr = '';

async function selectChannel(id) {
  const ch = S.channels.find(c => c.id === id); if (!ch || ch.type === 'voice') return;
  S.curCh = ch; S.curDmId = null; S.curDmUser = null;
  document.getElementById('chat-icon').textContent = '#';
  document.getElementById('chat-name').textContent = ch.name;
  document.getElementById('chat-topic').textContent = ch.topic || '';
  document.getElementById('msg-inp').placeholder = 'Message #' + ch.name;
  document.getElementById('call-hdr-btn').style.display = 'none';
  setView('chat'); renderChannels();
  if (S.chWs) S.chWs.close();
  const ws = new WebSocket(`${WS}/ws/channel/${ch.id}?token=${S.token}`);
  ws.onmessage = e => {
    const d = JSON.parse(e.data);
    if (d.type === 'new_message') appendMsg(d.message);
    if (d.type === 'message_deleted') document.getElementById('msg-' + d.message_id)?.remove();
  };
  S.chWs = ws;
  const msgs = await apiFetch('GET', '/channels/' + ch.id + '/messages');
  const c = document.getElementById('msgs'); c.innerHTML = ''; _lastDateStr = '';
  msgs.forEach(m => appendMsg(m, false));
  c.scrollTop = c.scrollHeight;
}

function appendMsg(msg, scroll = true) {
  const c = document.getElementById('msgs');
  const dateStr = new Date(msg.created_at * 1000).toDateString();
  if (dateStr !== _lastDateStr) {
    _lastDateStr = dateStr;
    const sep = document.createElement('div'); sep.className = 'day-div'; sep.textContent = fmtDate(msg.created_at);
    c.appendChild(sep);
  }
  const div = document.createElement('div'); div.className = 'msg'; div.id = 'msg-' + msg.id;
  const mine = msg.author_id === S.user?.id;
  div.innerHTML = `
    <div class="msg-av" style="background:${msg.avatar_color};" onclick="showProfile('${esc(msg.username)}',event)">${msg.display_name[0].toUpperCase()}</div>
    <div class="msg-body">
      <div class="msg-meta">
        <span class="msg-author" style="color:${msg.avatar_color};" onclick="showProfile('${esc(msg.username)}',event)">${esc(msg.display_name)}</span>
        <span class="msg-time">${fmtTime(msg.created_at)}</span>
      </div>
      <div class="msg-content">${esc(msg.content)}</div>
    </div>
    ${mine ? `<div class="msg-del" onclick="deleteMsg(${msg.id})" title="Delete">🗑️</div>` : ''}
  `;
  c.appendChild(div);
  if (scroll) c.scrollTop = c.scrollHeight;
}

async function deleteMsg(id) {
  try { await apiFetch('DELETE', '/messages/' + id); document.getElementById('msg-' + id)?.remove(); }
  catch(e) { toast(e.message, 'err'); }
}

async function sendMsg() {
  const inp = document.getElementById('msg-inp');
  const content = inp.value.trim(); if (!content) return;
  inp.value = ''; _lastDateStr = '';
  try {
    if (S.curDmId) {
      await apiFetch('POST', '/dms/' + S.curDmId + '/messages', { content });
      const msgs = await apiFetch('GET', '/dms/' + S.curDmId + '/messages');
      const c = document.getElementById('msgs'); c.innerHTML = ''; _lastDateStr = '';
      msgs.forEach(m => appendMsg(m, false)); c.scrollTop = c.scrollHeight;
    } else if (S.curCh) {
      await apiFetch('POST', '/channels/' + S.curCh.id + '/messages', { content });
    }
  } catch(e) { toast(e.message, 'err'); inp.value = content; }
}

function onMsgKey(e) { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMsg(); } }

// ── DMs ───────────────────────────────────────────────────────────────────────
async function showDMs() {
  document.getElementById('ch-side').style.display = 'none';
  document.getElementById('dm-side').classList.remove('hidden');
  S.curSrv = null; renderServerIcons();
  S.dmUnread = 0; updateDmBadge();
  dmSideTab('msgs', document.getElementById('dm-tab-msgs'));
  await loadDMs();
  setView('friends');
  fpTab('all', document.getElementById('fp-tab-all'));
}

async function loadDMs() {
  S.allDms = await apiFetch('GET', '/dms');
  renderDMList(S.allDms);
}

function renderDMList(dms) {
  const el = document.getElementById('dm-list'); el.innerHTML = '';
  if (!dms.length) {
    el.innerHTML = '<div style="color:var(--text3);font-size:13px;text-align:center;padding:20px;">No conversations yet.<br>Add friends to start chatting!</div>';
    return;
  }
  dms.forEach(dm => {
    const o = dm.other_user;
    const div = document.createElement('div');
    div.className = 'dm-item' + (S.curDmId === dm.id ? ' active' : '');
    div.innerHTML = `
      <div class="dm-av-wrap">
        <div class="dm-av" style="background:${o.avatar_color};">${o.display_name[0].toUpperCase()}</div>
        <div class="dm-status ${o.status==='online'?'online':'offline'}"></div>
      </div>
      <div class="dm-info">
        <div class="dm-name">${esc(o.display_name)}</div>
        <div class="dm-prev">${dm.last_msg ? esc(dm.last_msg.slice(0,40)) : 'Start a conversation'}</div>
      </div>
      <div class="dm-call-btn" onclick="event.stopPropagation();callUser(${o.id})" title="Call">📞</div>
    `;
    div.onclick = () => openDM(dm.id, o);
    el.appendChild(div);
  });
}

function filterDMs(q) {
  if (!q) { renderDMList(S.allDms); return; }
  const lq = q.toLowerCase();
  renderDMList(S.allDms.filter(dm => dm.other_user.display_name.toLowerCase().includes(lq) || dm.other_user.username.toLowerCase().includes(lq)));
}

async function openDM(dmId, other) {
  S.curDmId = dmId; S.curCh = null; S.curDmUser = other;
  document.getElementById('chat-icon').textContent = '@';
  document.getElementById('chat-name').textContent = other.display_name;
  document.getElementById('chat-topic').textContent = other.username;
  document.getElementById('msg-inp').placeholder = 'Message ' + other.display_name + '…';
  document.getElementById('call-hdr-btn').style.display = 'flex';
  setView('chat'); await loadDMs(); _lastDateStr = '';
  const msgs = await apiFetch('GET', '/dms/' + dmId + '/messages');
  const c = document.getElementById('msgs'); c.innerHTML = ''; _lastDateStr = '';
  msgs.forEach(m => appendMsg(m, false)); c.scrollTop = c.scrollHeight;
}

function callDMUser() { if (S.curDmUser) callUser(S.curDmUser.id); }

function showNewDM() {
  showModal('New Message', `
    <label class="lbl">Username</label>
    <input id="ndm-un" class="inp" placeholder="e.g. alice" style="margin-top:4px;" oninput="searchNewDM(this.value)">
    <div id="ndm-results" class="search-results" style="margin-top:10px;"></div>
  `, [
    { label: 'Cancel', cls: 'btn-ghost', fn: closeModal },
    { label: 'Open Chat', fn: async () => {
      const un = (document.getElementById('ndm-un').value || '').trim(); if (!un) return;
      try {
        const r = await apiFetch('POST', '/dms/open', { username: un });
        closeModal(); await loadDMs();
        const dm = S.allDms.find(d => d.id === r.dm_id);
        if (dm) openDM(dm.id, dm.other_user);
      } catch(e) { toast(e.message, 'err'); }
    }},
  ]);
}

let _searchTO = null;
function searchNewDM(q) {
  clearTimeout(_searchTO);
  const el = document.getElementById('ndm-results'); if (!el) return;
  if (q.length < 2) { el.innerHTML = ''; return; }
  _searchTO = setTimeout(async () => {
    try {
      const users = await apiFetch('GET', '/users/search?q=' + encodeURIComponent(q));
      el.innerHTML = users.length
        ? users.map(u => `<div class="sr-row">
            ${avatarEl(u.display_name[0].toUpperCase(), u.avatar_color, 34, 13)}
            <div class="sr-info"><div class="sr-name">${esc(u.display_name)}</div><div class="sr-un">@${esc(u.username)}</div></div>
            <button class="btn btn-ghost btn-xs" onclick="document.getElementById('ndm-un').value='${esc(u.username)}'">Select</button>
          </div>`).join('')
        : '<div style="color:var(--text3);font-size:13px;">No users found</div>';
    } catch {}
  }, 300);
}

// ── Friends ───────────────────────────────────────────────────────────────────
async function renderFriends(tab = 'all') {
  const friends = await apiFetch('GET', '/friends');
  S.friends = friends;
  const pending = friends.filter(f => f.status === 'pending' && !f.is_requester);
  S.pendingCount = pending.length; updatePendingBadge();
  const el = document.getElementById('fp-body'); el.innerHTML = '';

  if (tab === 'add') {
    el.innerHTML = `
      <div class="add-box">
        <h3>Add Friend</h3>
        <p>Search by username and send a friend request.</p>
        <div style="display:flex;gap:8px;">
          <input id="fadd-un" class="inp" placeholder="Search username…" oninput="searchFriendAdd(this.value)" style="flex:1;">
          <button class="btn btn-primary btn-sm" onclick="sendFriendReqInput()">Send</button>
        </div>
        <div class="err" id="fadd-err"></div>
        <div class="ok" id="fadd-ok"></div>
        <div class="search-results" id="fadd-results" style="margin-top:10px;"></div>
      </div>`;
    return;
  }

  if (tab === 'pending') {
    const inc = friends.filter(f => f.status === 'pending' && !f.is_requester);
    const out = friends.filter(f => f.status === 'pending' && f.is_requester);
    if (!inc.length && !out.length) { el.innerHTML = '<div style="color:var(--text3);text-align:center;padding:32px 0;">No pending requests</div>'; return; }
    if (inc.length) {
      el.innerHTML += `<div style="font-size:11px;font-weight:700;color:var(--text3);text-transform:uppercase;margin-bottom:8px;">Incoming — ${inc.length}</div>`;
      inc.forEach(f => el.innerHTML += friendRow(f, 'incoming'));
    }
    if (out.length) {
      el.innerHTML += `<div style="font-size:11px;font-weight:700;color:var(--text3);text-transform:uppercase;margin:12px 0 8px;">Sent</div>`;
      out.forEach(f => el.innerHTML += friendRow(f, 'outgoing'));
    }
    return;
  }

  // All friends
  const accepted = friends.filter(f => f.status === 'accepted');
  if (!accepted.length) {
    el.innerHTML = `<div style="color:var(--text3);text-align:center;padding:32px 0;">No friends yet.<br><br>
      <button class="btn btn-primary btn-sm" onclick="fpTab('add',document.getElementById('fp-tab-add'))">➕ Add Friends</button></div>`;
    return;
  }
  el.innerHTML = `<div style="font-size:11px;font-weight:700;color:var(--text3);text-transform:uppercase;margin-bottom:8px;">All Friends — ${accepted.length}</div>`;
  accepted.forEach(f => el.innerHTML += friendRow(f, 'accepted'));
}

function friendRow(f, type) {
  const o = f.other;
  let acts = '';
  if (type === 'incoming') {
    acts = `<button class="btn btn-green btn-xs" onclick="acceptFriend(${f.id})">✓ Accept</button>
            <button class="btn btn-ghost btn-xs" onclick="declineFriend(${f.id})">✕</button>`;
  } else if (type === 'outgoing') {
    acts = `<span style="color:var(--text3);font-size:11px;">Pending…</span>
            <button class="btn btn-ghost btn-xs" onclick="cancelFriend(${f.id})">Cancel</button>`;
  } else {
    acts = `<button class="btn btn-ghost btn-xs" onclick="dmUser('${esc(o.username)}')">💬</button>
            <button class="btn btn-ghost btn-xs" onclick="callUser(${o.id})">📞</button>
            <button class="btn btn-ghost btn-xs" onclick="removeFriend(${f.id})" style="color:var(--red);">✕</button>`;
  }
  const statusDot = `<div style="position:absolute;bottom:0;right:0;width:10px;height:10px;border-radius:50%;border:2px solid var(--bg3);background:${o.status==='online'?'var(--green)':'var(--text3)'}"></div>`;
  return `<div class="fr-row">
    <div class="fr-av" style="background:${o.avatar_color};">${o.display_name[0].toUpperCase()}${statusDot}</div>
    <div class="fr-info">
      <div class="fr-name">${esc(o.display_name)}</div>
      <div class="fr-sub">${o.status === 'online' ? '🟢 Online' : '⚫ Offline'}</div>
    </div>
    <div class="fr-acts">${acts}</div>
  </div>`;
}

function fpTab(tab, btn) {
  document.querySelectorAll('.fp-tab').forEach(b => b.classList.remove('active'));
  if (btn) btn.classList.add('active');
  renderFriends(tab);
}

let _friendSearchTO = null;
function searchFriendAdd(q) {
  clearTimeout(_friendSearchTO);
  const el = document.getElementById('fadd-results'); if (!el) return;
  if (q.length < 2) { el.innerHTML = ''; return; }
  _friendSearchTO = setTimeout(async () => {
    try {
      const users = await apiFetch('GET', '/users/search?q=' + encodeURIComponent(q));
      if (!users.length) { el.innerHTML = '<div style="color:var(--text3);font-size:13px;">No users found</div>'; return; }
      el.innerHTML = users.map(u => {
        const fr = S.friends.find(f => f.other.id === u.id);
        const btn = !fr ? `<button class="btn btn-primary btn-xs" onclick="quickAddFriend(${u.id},this)">Add</button>`
                  : fr.status === 'accepted' ? `<span style="color:var(--green);font-size:11px;">✓ Friends</span>`
                  : `<span style="color:var(--text3);font-size:11px;">Pending</span>`;
        return `<div class="sr-row">
          ${avatarEl(u.display_name[0].toUpperCase(), u.avatar_color, 34, 13)}
          <div class="sr-info"><div class="sr-name">${esc(u.display_name)}</div><div class="sr-un">@${esc(u.username)}</div></div>
          ${btn}
        </div>`;
      }).join('');
    } catch {}
  }, 300);
}

async function sendFriendReqInput() {
  const un = (document.getElementById('fadd-un')?.value || '').trim();
  const err = document.getElementById('fadd-err'), ok = document.getElementById('fadd-ok');
  if (!un || !err || !ok) return;
  err.textContent = ''; ok.textContent = '';
  try {
    await apiFetch('POST', '/friends/request', { username: un });
    ok.textContent = '✓ Request sent to ' + un + '!';
    document.getElementById('fadd-un').value = '';
    document.getElementById('fadd-results').innerHTML = '';
    loadFriendsSidebar();
  } catch(e) { err.textContent = e.message; }
}

async function quickAddFriend(userId, btn) {
  try {
    await fetch(API + '/friends/request', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + S.token },
      body: JSON.stringify({ user_id: userId }),
    });
    btn.textContent = 'Sent!'; btn.disabled = true;
  } catch(e) { toast(e.message, 'err'); }
}

async function acceptFriend(id)  { await apiFetch('POST', '/friends/' + id + '/accept');  loadFriendsSidebar(); renderFriends('pending'); }
async function declineFriend(id) { await apiFetch('POST', '/friends/' + id + '/decline'); loadFriendsSidebar(); renderFriends('pending'); }
async function cancelFriend(id)  { await apiFetch('DELETE', '/friends/' + id);            loadFriendsSidebar(); renderFriends('pending'); }
async function removeFriend(id)  { if (!confirm('Remove friend?')) return; await apiFetch('DELETE', '/friends/' + id); loadFriendsSidebar(); renderFriends('all'); }

async function dmUser(username) {
  const r = await apiFetch('POST', '/dms/open', { username });
  await showDMs(); await loadDMs();
  const dm = S.allDms.find(d => d.id === r.dm_id);
  if (dm) openDM(dm.id, dm.other_user);
}

// ── Profile popover ───────────────────────────────────────────────────────────
let _popTarget = null;

async function showProfile(username, event) {
  event?.stopPropagation();
  if (_popTarget === username) { closeProfile(); return; }
  _popTarget = username;
  const pop = document.getElementById('prof-pop');
  const x = event?.clientX || 200, y = event?.clientY || 200;
  pop.style.left = Math.min(x + 12, window.innerWidth - 280) + 'px';
  pop.style.top  = Math.min(y, window.innerHeight - 340) + 'px';
  pop.classList.add('show');
  document.getElementById('pp-name').textContent = 'Loading…';
  document.getElementById('pp-un').textContent = '';
  document.getElementById('pp-bio').textContent = '';
  document.getElementById('pp-acts').innerHTML = '';
  try {
    const u = await apiFetch('GET', '/users/' + encodeURIComponent(username));
    document.getElementById('pp-banner').style.background = `linear-gradient(135deg, ${u.avatar_color}, ${u.avatar_color}66)`;
    const av = document.getElementById('pp-av');
    av.style.background = u.avatar_color; av.textContent = u.display_name[0].toUpperCase();
    document.getElementById('pp-name').textContent = u.display_name;
    document.getElementById('pp-un').textContent = '@' + u.username;
    document.getElementById('pp-bio').textContent = u.bio || 'No bio set.';
    const isSelf = u.id === S.user?.id;
    const fr = u.friendship;
    let acts = '';
    if (!isSelf) {
      if (!fr) acts = `<button class="btn btn-primary btn-sm" onclick="sendFriendByUn('${esc(u.username)}')">➕ Add Friend</button>`;
      else if (fr.status === 'accepted') {
        acts = `<button class="btn btn-ghost btn-sm" onclick="dmUser('${esc(u.username)}');closeProfile()">💬 Message</button>
                <button class="btn btn-ghost btn-sm" onclick="callUser(${u.id});closeProfile()">📞 Call</button>`;
      } else acts = `<span style="color:var(--text3);font-size:12px;">Request pending…</span>`;
    } else {
      acts = `<button class="btn btn-ghost btn-sm" onclick="showEditProfile();closeProfile()">✏️ Edit Profile</button>`;
    }
    document.getElementById('pp-acts').innerHTML = acts;
  } catch(e) { document.getElementById('pp-name').textContent = 'Error: ' + e.message; }
}

async function sendFriendByUn(username) {
  try { await apiFetch('POST', '/friends/request', { username }); toast('Friend request sent!', 'ok'); closeProfile(); }
  catch(e) { toast(e.message, 'err'); }
}
function closeProfile() { document.getElementById('prof-pop').classList.remove('show'); _popTarget = null; }
function showMyProfile(event) { if (S.user) showProfile(S.user.username, event); }

function showEditProfile() {
  showModal('Edit Profile', `
    <label class="lbl">Display Name</label>
    <input id="ep-name" class="inp" value="${esc(S.user?.display_name || '')}" style="margin-top:4px;">
    <label class="lbl">Bio</label>
    <input id="ep-bio" class="inp" value="${esc(S.user?.bio || '')}" placeholder="Tell people about yourself" style="margin-top:4px;">
  `, [
    { label: 'Cancel', cls: 'btn-ghost', fn: closeModal },
    { label: 'Save', fn: async () => {
      try {
        const u = await apiFetch('PATCH', '/me', {
          display_name: document.getElementById('ep-name').value.trim(),
          bio: document.getElementById('ep-bio').value.trim(),
        });
        S.user = u;
        ['pan-name','pan-name2'].forEach(id => { const el=document.getElementById(id); if(el) el.textContent=u.display_name; });
        closeModal(); toast('Profile updated', 'ok');
      } catch(e) { toast(e.message, 'err'); }
    }},
  ]);
}

// ── Voice ─────────────────────────────────────────────────────────────────────
const ICE_CFG = { iceServers: [{ urls: 'stun:stun.l.google.com:19302' }, { urls: 'stun:stun1.l.google.com:19302' }] };

async function joinVC(chId, name) {
  if (S.vcCh?.id === chId) return;
  if (S.vcCh) leaveVC();
  S.vcCh = S.channels.find(c => c.id === chId);
  document.getElementById('vc-ch-name').textContent = name;
  document.getElementById('vc-status').textContent = 'Connecting…';
  setView('voice'); renderChannels();
  try { S.localStream = await navigator.mediaDevices.getUserMedia({ audio: true, video: false }); }
  catch { S.localStream = null; document.getElementById('vc-status').textContent = '⚠️ Mic denied — you can still listen'; }
  S.vcParts = { [S.user.id]: { id: S.user.id, display_name: S.user.display_name, avatar_color: S.user.avatar_color, muted: S.muted } };
  renderVCParts();
  const ws = new WebSocket(`${WS}/ws/voice/${chId}?token=${S.token}`);
  ws.onopen = () => document.getElementById('vc-status').textContent = '✅ Connected';
  ws.onmessage = async e => {
    const msg = JSON.parse(e.data);
    if (msg.type === 'voice_peer_exists') { S.vcParts[msg.userId] = msg.userInfo; renderVCParts(); await vcOffer(msg.userId); }
    else if (msg.type === 'voice_user_joined') { S.vcParts[msg.userId] = msg.userInfo; renderVCParts(); }
    else if (msg.type === 'voice_user_left') {
      delete S.vcParts[msg.userId];
      if (S.vcPeers[msg.userId]) { S.vcPeers[msg.userId].close(); delete S.vcPeers[msg.userId]; }
      renderVCParts();
    }
    else if (msg.type === 'voice_signal') await vcSignal(msg.fromUserId, msg.signal);
  };
  ws.onclose = () => document.getElementById('vc-status').textContent = 'Disconnected';
  S.vcWs = ws;
}

async function vcOffer(pid) {
  const pc = vcPC(pid);
  const offer = await pc.createOffer();
  await pc.setLocalDescription(offer);
  S.vcWs?.send(JSON.stringify({ type: 'voice_signal', toUserId: pid, signal: { type: 'offer', sdp: offer.sdp } }));
}

function vcPC(pid) {
  if (S.vcPeers[pid]) S.vcPeers[pid].close();
  const pc = new RTCPeerConnection(ICE_CFG); S.vcPeers[pid] = pc;
  if (S.localStream) S.localStream.getTracks().forEach(t => pc.addTrack(t, S.localStream));
  pc.onicecandidate = e => { if (e.candidate) S.vcWs?.send(JSON.stringify({ type: 'voice_signal', toUserId: pid, signal: { type: 'candidate', candidate: e.candidate } })); };
  pc.ontrack = e => { const a = new Audio(); a.srcObject = e.streams[0]; if (!S.deafened) a.play().catch(() => {}); };
  return pc;
}

async function vcSignal(from, sig) {
  if (sig.type === 'offer') {
    const pc = vcPC(from);
    await pc.setRemoteDescription({ type: 'offer', sdp: sig.sdp });
    const ans = await pc.createAnswer(); await pc.setLocalDescription(ans);
    S.vcWs?.send(JSON.stringify({ type: 'voice_signal', toUserId: from, signal: { type: 'answer', sdp: ans.sdp } }));
  } else if (sig.type === 'answer') {
    if (S.vcPeers[from]) await S.vcPeers[from].setRemoteDescription({ type: 'answer', sdp: sig.sdp });
  } else if (sig.type === 'candidate') {
    if (S.vcPeers[from]) await S.vcPeers[from].addIceCandidate(sig.candidate).catch(() => {});
  }
}

function leaveVC() {
  if (S.vcWs) { S.vcWs.close(); S.vcWs = null; }
  if (S.localStream) { S.localStream.getTracks().forEach(t => t.stop()); S.localStream = null; }
  Object.values(S.vcPeers).forEach(pc => pc.close()); S.vcPeers = {};
  S.vcParts = {}; S.vcCh = null; renderChannels(); setView('welcome');
}

function toggleMute() {
  S.muted = !S.muted;
  if (S.localStream) S.localStream.getAudioTracks().forEach(t => t.enabled = !S.muted);
  const btn = document.getElementById('vc-mute');
  btn.textContent = S.muted ? '🔇' : '🎤'; btn.className = S.muted ? 'vc-btn active' : 'vc-btn normal';
  if (S.vcParts[S.user.id]) S.vcParts[S.user.id].muted = S.muted;
  renderVCParts();
}
function toggleDeafen() {
  S.deafened = !S.deafened;
  const btn = document.getElementById('vc-deaf');
  btn.textContent = S.deafened ? '🔇' : '🔊'; btn.className = S.deafened ? 'vc-btn active' : 'vc-btn normal';
}
function renderVCParts() {
  const el = document.getElementById('vc-parts'); el.innerHTML = '';
  Object.values(S.vcParts).forEach(p => {
    el.innerHTML += `<div class="vc-part">
      <div class="vc-pav${p.muted?' muted':''}" style="background:${p.avatar_color};">${p.display_name[0].toUpperCase()}</div>
      <div class="vc-pname">${esc(p.display_name)}</div>
    </div>`;
  });
}

// ── Direct Calls ──────────────────────────────────────────────────────────────
async function callUser(userId) {
  if (S.callActive) { toast('Already in a call', 'err'); return; }
  try { await apiFetch('POST', '/call/ring', { user_id: userId }); }
  catch(e) { toast(e.message, 'err'); }
}

async function acceptCall() {
  clearTimeout(S.ringTO); stopRing();
  try { await apiFetch('POST', '/call/accept/' + S.callId); hideCallOverlay(); startActiveCall(S.callId, null); }
  catch(e) { toast(e.message, 'err'); }
}

async function rejectCall() {
  clearTimeout(S.ringTO); stopRing();
  try { await apiFetch('POST', '/call/reject/' + S.callId); } catch {}
  hideCallOverlay(); S.callId = null; S.callRole = null;
}

async function hangup() {
  if (!S.callId) return;
  try { await apiFetch('POST', '/call/reject/' + S.callId); } catch {}
  endCall();
}

async function startActiveCall(callId, other) {
  S.callActive = true; S.callId = callId;
  try { S.callStream = await navigator.mediaDevices.getUserMedia({ audio: true, video: false }); }
  catch { S.callStream = null; }
  const ws = new WebSocket(`${WS}/ws/call/${callId}?token=${S.token}`);
  S.callWs = ws;
  ws.onmessage = async e => {
    const msg = JSON.parse(e.data);
    if (msg.type === 'call_peer_ready') { if (S.callRole === 'caller') await callOffer(msg.peerId); }
    if (msg.type === 'call_signal') await callSignal(msg.fromUserId, msg.signal);
    if (msg.type === 'call_ended') { endCall(); toast('📞 Call ended', 'info'); }
  };
  ws.onclose = () => { if (S.callActive) { endCall(); toast('📞 Call ended', 'info'); } };
  const name = other?.display_name || S.curDmUser?.display_name || 'Call';
  document.getElementById('cb-name').textContent = 'In call with ' + name;
  document.getElementById('call-bar').classList.add('show');
  S.callStart = Date.now();
  S.callTimer = setInterval(() => {
    const sec = Math.floor((Date.now() - S.callStart) / 1000);
    document.getElementById('cb-dur').textContent = secFmt(sec);
  }, 1000);
}

function endCall() {
  if (S.callWs) { S.callWs.close(); S.callWs = null; }
  if (S.callStream) { S.callStream.getTracks().forEach(t => t.stop()); S.callStream = null; }
  Object.values(S.callPeers).forEach(pc => pc.close()); S.callPeers = {};
  clearInterval(S.callTimer); S.callTimer = null;
  document.getElementById('call-bar').classList.remove('show');
  S.callActive = false; S.callId = null; S.callRole = null;
}

async function callOffer(pid) {
  const pc = callPC(pid); const o = await pc.createOffer(); await pc.setLocalDescription(o);
  S.callWs?.send(JSON.stringify({ type: 'call_signal', signal: { type: 'offer', sdp: o.sdp } }));
}
function callPC(pid) {
  if (S.callPeers[pid]) S.callPeers[pid].close();
  const pc = new RTCPeerConnection(ICE_CFG); S.callPeers[pid] = pc;
  if (S.callStream) S.callStream.getTracks().forEach(t => pc.addTrack(t, S.callStream));
  pc.onicecandidate = e => { if (e.candidate) S.callWs?.send(JSON.stringify({ type: 'call_signal', signal: { type: 'candidate', candidate: e.candidate } })); };
  pc.ontrack = e => { const a = new Audio(); a.srcObject = e.streams[0]; a.play().catch(() => {}); };
  return pc;
}
async function callSignal(fromId, sig) {
  const pcs = Object.values(S.callPeers);
  if (!S.callPeers[fromId] && sig.type === 'offer') {
    const pc = callPC(fromId);
    await pc.setRemoteDescription({ type: 'offer', sdp: sig.sdp });
    const ans = await pc.createAnswer(); await pc.setLocalDescription(ans);
    S.callWs?.send(JSON.stringify({ type: 'call_signal', signal: { type: 'answer', sdp: ans.sdp } }));
  } else if (sig.type === 'answer' && pcs.length) {
    await pcs[0].setRemoteDescription({ type: 'answer', sdp: sig.sdp });
  } else if (sig.type === 'candidate' && pcs.length) {
    await pcs[0].addIceCandidate(sig.candidate).catch(() => {});
  }
}
function toggleCallMute() {
  S.callMuted = !S.callMuted;
  if (S.callStream) S.callStream.getAudioTracks().forEach(t => t.enabled = !S.callMuted);
  document.getElementById('cb-mute-btn').textContent = S.callMuted ? '🔇 Unmute' : '🎤 Mute';
}

function showCallOverlay(dir, user) {
  const ov = document.getElementById('call-overlay');
  document.getElementById('co-av').style.background = user.avatar_color || '#5865f2';
  document.getElementById('co-av').textContent = (user.display_name || '?')[0].toUpperCase();
  document.getElementById('co-name').textContent = user.display_name || user.username;
  if (dir === 'incoming') {
    document.getElementById('co-type').textContent = 'Incoming Call'; document.getElementById('co-type').className = 'co-type incoming';
    document.getElementById('co-sub').textContent = 'is calling you…';
    document.getElementById('co-btns').innerHTML = `<button class="btn btn-green ring-anim" style="flex:1;" onclick="acceptCall()">📞 Accept</button><button class="btn btn-red" style="flex:1;" onclick="rejectCall()">📵 Decline</button>`;
    let t = 45; document.getElementById('co-timer').textContent = 'Ringing… ' + t + 's';
    const iv = setInterval(() => { if (!S.callId) { clearInterval(iv); return; } document.getElementById('co-timer').textContent = 'Ringing… ' + (--t) + 's'; if (t <= 0) clearInterval(iv); }, 1000);
  } else {
    document.getElementById('co-type').textContent = 'Calling…'; document.getElementById('co-type').className = 'co-type outgoing';
    document.getElementById('co-sub').textContent = 'Waiting for answer…';
    document.getElementById('co-btns').innerHTML = `<button class="btn btn-red" style="flex:1;" onclick="rejectCall()">📵 Cancel</button>`;
    document.getElementById('co-timer').textContent = '';
  }
  ov.classList.add('show');
}
function hideCallOverlay() { document.getElementById('call-overlay').classList.remove('show'); }

// ── Views ─────────────────────────────────────────────────────────────────────
function setView(v) {
  S.view = v;
  document.getElementById('welcome-view').style.display = v === 'welcome' ? 'flex' : 'none';
  document.getElementById('chat-view').style.display    = v === 'chat'    ? 'flex' : 'none';
  document.getElementById('vc-view').style.display      = v === 'voice'   ? 'flex' : 'none';
  document.getElementById('friends-view').style.display = v === 'friends' ? 'flex' : 'none';
}

// ── Global events ─────────────────────────────────────────────────────────────
document.addEventListener('click', e => {
  if (!e.target.closest('#prof-pop') && !e.target.closest('.msg-av') &&
      !e.target.closest('.msg-author') && !e.target.closest('.mem-row') &&
      !e.target.closest('.u-av') && !e.target.closest('.pp-av') &&
      !e.target.closest('.fr-av') && !e.target.closest('.dm-av')) closeProfile();
  if (!e.target.closest('#notif-panel') && !e.target.closest('#notif-btn')) closeNotifPanel();
});
document.addEventListener('keydown', e => {
  if (e.key === 'Escape') { closeModal(); closeProfile(); closeNotifPanel(); }
});

// ── Friend Request Popup ──────────────────────────────────────────────────────
let _frpData = null; // { friendshipId, from }

function showFriendRequestPopup(fromUser) {
  _frpData = { from: fromUser };
  const pop = document.getElementById('fr-popup');
  const av  = document.getElementById('frp-av');
  av.style.background = fromUser.avatar_color || '#5865f2';
  av.textContent = (fromUser.display_name || '?')[0].toUpperCase();
  document.getElementById('frp-name').textContent = fromUser.display_name || fromUser.username;
  pop.style.display = 'block';
  // Auto-dismiss after 30s
  clearTimeout(_frpTimer);
  _frpTimer = setTimeout(frpDismiss, 30000);
}
let _frpTimer = null;

async function frpAccept() {
  if (!_frpData) return;
  try {
    // Find the pending friendship ID
    const friends = await apiFetch('GET', '/friends');
    const fr = friends.find(f => f.other.id === _frpData.from.id && f.status === 'pending' && !f.is_requester);
    if (fr) {
      await apiFetch('POST', '/friends/' + fr.id + '/accept');
      toast('✅ Now friends with ' + _frpData.from.display_name, 'ok');
      loadFriendsSidebar();
    }
  } catch(e) { toast(e.message, 'err'); }
  frpDismiss();
}

async function frpDecline() {
  if (!_frpData) return;
  try {
    const friends = await apiFetch('GET', '/friends');
    const fr = friends.find(f => f.other.id === _frpData.from.id && f.status === 'pending' && !f.is_requester);
    if (fr) await apiFetch('POST', '/friends/' + fr.id + '/decline');
    toast('Request from ' + _frpData.from.display_name + ' declined', 'info');
    S.pendingCount = Math.max(0, S.pendingCount - 1);
    updatePendingBadge();
  } catch(e) { toast(e.message, 'err'); }
  frpDismiss();
}

function frpDismiss() {
  clearTimeout(_frpTimer);
  document.getElementById('fr-popup').style.display = 'none';
  _frpData = null;
}

// ── Friends View (dedicated) ──────────────────────────────────────────────────
function showFriendsView() {
  // Open DM sidebar on the Friends tab
  document.getElementById('ch-side').style.display = 'none';
  document.getElementById('dm-side').classList.remove('hidden');
  S.curSrv = null; renderServerIcons();
  dmSideTab('friends', document.getElementById('dm-tab-friends'));
  setView('friends');
  fpTab('all', document.getElementById('fp-tab-all'));
  // Also update the sidebar friend list
  loadFriendsSidebar();
}

function dmSideTab(tab, btn) {
  document.querySelectorAll('.dm-side-tab').forEach(b => b.classList.remove('active'));
  if (btn) btn.classList.add('active');
  document.getElementById('dm-msgs-pane').style.display    = tab === 'msgs'    ? 'flex' : 'none';
  document.getElementById('dm-friends-pane').style.display = tab === 'friends' ? 'flex' : 'none';
  if (tab === 'friends') loadFriendsSidebar();
}

async function loadFriendsSidebar() {
  try {
    const friends = await apiFetch('GET', '/friends');
    S.friends = friends;
    const pending  = friends.filter(f => f.status === 'pending' && !f.is_requester);
    const accepted = friends.filter(f => f.status === 'accepted');
    S.pendingCount = pending.length;
    updatePendingBadge();

    const el = document.getElementById('dm-fr-list');
    if (!el) return;
    el.innerHTML = '';

    // Pending requests section
    if (pending.length) {
      el.innerHTML += `<div style="font-size:10px;font-weight:700;text-transform:uppercase;color:var(--red);padding:8px 14px 4px;letter-spacing:.06em;">
        Pending — ${pending.length}
      </div>`;
      pending.forEach(f => {
        const o = f.other;
        el.innerHTML += `<div class="pending-item">
          <div style="width:34px;height:34px;border-radius:50%;background:${o.avatar_color};display:flex;align-items:center;justify-content:center;font-size:13px;font-weight:700;color:#fff;flex-shrink:0;">${o.display_name[0].toUpperCase()}</div>
          <div style="flex:1;min-width:0;">
            <div class="pending-name">${esc(o.display_name)}</div>
            <div style="font-size:11px;color:var(--text3);">wants to be friends</div>
          </div>
          <div style="display:flex;gap:4px;">
            <button class="btn btn-green btn-xs" onclick="acceptFriendSidebar(${f.id})">✓</button>
            <button class="btn btn-ghost btn-xs" onclick="declineFriendSidebar(${f.id})">✕</button>
          </div>
        </div>`;
      });
    }

    // Online/offline friends
    if (accepted.length) {
      const online  = accepted.filter(f => f.other.status === 'online');
      const offline = accepted.filter(f => f.other.status !== 'online');

      if (online.length) {
        el.innerHTML += `<div style="font-size:10px;font-weight:700;text-transform:uppercase;color:var(--text3);padding:10px 14px 4px;letter-spacing:.06em;">Online — ${online.length}</div>`;
        online.forEach(f => el.innerHTML += friendSidebarRow(f));
      }
      if (offline.length) {
        el.innerHTML += `<div style="font-size:10px;font-weight:700;text-transform:uppercase;color:var(--text3);padding:10px 14px 4px;letter-spacing:.06em;">Offline — ${offline.length}</div>`;
        offline.forEach(f => el.innerHTML += friendSidebarRow(f));
      }
    }

    if (!pending.length && !accepted.length) {
      el.innerHTML = `<div style="text-align:center;padding:32px 14px;color:var(--text3);font-size:13px;">
        No friends yet.<br><br>
        <button class="btn btn-primary btn-sm" onclick="showAddFriendModal()">➕ Add Your First Friend</button>
      </div>`;
    }
  } catch(e) { console.error('loadFriendsSidebar:', e); }
}

function friendSidebarRow(f) {
  const o = f.other;
  const onlineDot = `<div style="position:absolute;bottom:0;right:0;width:10px;height:10px;border-radius:50%;border:2px solid var(--bg2);background:${o.status==='online'?'var(--green)':'var(--text3)'}"></div>`;
  return `<div class="fr-dm-item">
    <div style="position:relative;flex-shrink:0;">
      <div style="width:34px;height:34px;border-radius:50%;background:${o.avatar_color};display:flex;align-items:center;justify-content:center;font-size:13px;font-weight:700;color:#fff;">${o.display_name[0].toUpperCase()}</div>
      ${onlineDot}
    </div>
    <div style="flex:1;min-width:0;">
      <div class="fr-dm-name">${esc(o.display_name)}</div>
      <div class="fr-dm-status">${o.status === 'online' ? '🟢 Online' : '⚫ Offline'}</div>
    </div>
    <div class="fr-dm-acts">
      <button class="btn btn-ghost btn-xs" title="Message" onclick="dmUser('${esc(o.username)}')">💬</button>
      <button class="btn btn-ghost btn-xs" title="Call" onclick="callUser(${o.id})">📞</button>
    </div>
  </div>`;
}

async function acceptFriendSidebar(id) {
  try { await apiFetch('POST', '/friends/' + id + '/accept'); toast('Friend accepted!', 'ok'); loadFriendsSidebar(); }
  catch(e) { toast(e.message, 'err'); }
}
async function declineFriendSidebar(id) {
  try { await apiFetch('POST', '/friends/' + id + '/decline'); loadFriendsSidebar(); }
  catch(e) { toast(e.message, 'err'); }
}

// ── Add Friend Modal ──────────────────────────────────────────────────────────
function showAddFriendModal() {
  showModal('Add a Friend', `
    <div class="add-friend-modal">
      <div class="big-icon">👋</div>
      <h3>Find your friends</h3>
      <p>Search by username to send them a friend request.</p>
    </div>
    <div style="display:flex;gap:8px;margin-bottom:8px;">
      <input id="afm-un" class="inp" placeholder="Enter username…" oninput="afmSearch(this.value)"
             onkeydown="if(event.key==='Enter')afmSend()" style="flex:1;">
      <button class="btn btn-primary" onclick="afmSend()">Send Request</button>
    </div>
    <div class="err" id="afm-err"></div>
    <div class="ok" id="afm-ok"></div>
    <div id="afm-results" style="margin-top:10px;"></div>
  `, [{ label: 'Close', cls: 'btn-ghost', fn: closeModal }]);
}

let _afmTO = null;
function afmSearch(q) {
  clearTimeout(_afmTO);
  const el = document.getElementById('afm-results'); if (!el) return;
  if (q.length < 2) { el.innerHTML = ''; return; }
  _afmTO = setTimeout(async () => {
    try {
      const users = await apiFetch('GET', '/users/search?q=' + encodeURIComponent(q));
      if (!users.length) { el.innerHTML = '<div style="color:var(--text3);font-size:13px;text-align:center;padding:12px;">No users found</div>'; return; }
      el.innerHTML = users.map(u => {
        const fr = S.friends.find(f => f.other.id === u.id);
        let action = '';
        if (u.id === S.user?.id) action = '<span style="color:var(--text3);font-size:12px;">That\'s you!</span>';
        else if (!fr) action = `<button class="btn btn-primary btn-sm" onclick="afmSendTo('${esc(u.username)}',this)">➕ Add</button>`;
        else if (fr.status === 'accepted') action = '<span style="color:var(--green);font-size:12px;font-weight:600;">✓ Friends</span>';
        else if (fr.is_requester) action = '<span style="color:var(--text3);font-size:12px;">Request sent</span>';
        else action = `<button class="btn btn-green btn-sm" onclick="afmAcceptFrom(${fr.id},this)">✓ Accept</button>`;
        return `<div class="friend-search-result">
          <div style="width:38px;height:38px;border-radius:50%;background:${u.avatar_color};display:flex;align-items:center;justify-content:center;font-size:15px;font-weight:700;color:#fff;flex-shrink:0;">${u.display_name[0].toUpperCase()}</div>
          <div style="flex:1;min-width:0;">
            <div style="font-weight:600;font-size:14px;">${esc(u.display_name)}</div>
            <div style="font-size:12px;color:var(--text2);font-family:monospace;">@${esc(u.username)}</div>
          </div>
          ${action}
        </div>`;
      }).join('');
    } catch(e) { el.innerHTML = `<div class="err">${esc(e.message)}</div>`; }
  }, 300);
}

async function afmSend() {
  const inp = document.getElementById('afm-un');
  const un  = (inp?.value || '').trim();
  const err = document.getElementById('afm-err');
  const ok  = document.getElementById('afm-ok');
  if (!un || !err || !ok) return;
  err.textContent = ''; ok.textContent = '';
  try {
    await apiFetch('POST', '/friends/request', { username: un });
    ok.textContent = '✓ Friend request sent to ' + un + '!';
    if (inp) inp.value = '';
    document.getElementById('afm-results').innerHTML = '';
    loadFriendsSidebar();
  } catch(e) { err.textContent = e.message; }
}

async function afmSendTo(username, btn) {
  try {
    await apiFetch('POST', '/friends/request', { username });
    btn.textContent = 'Sent!'; btn.disabled = true; btn.className = 'btn btn-ghost btn-sm';
    toast('Friend request sent to ' + username, 'ok');
    loadFriendsSidebar();
  } catch(e) { toast(e.message, 'err'); }
}

async function afmAcceptFrom(id, btn) {
  try {
    await apiFetch('POST', '/friends/' + id + '/accept');
    btn.textContent = 'Accepted!'; btn.disabled = true; btn.className = 'btn btn-ghost btn-sm';
    toast('Friend accepted!', 'ok');
    loadFriendsSidebar();
  } catch(e) { toast(e.message, 'err'); }
}

const DEFAULT_SERVER = 'https://thl2lsbc-3000.use.devtunnels.ms';

(function init() {
  const srv   = LS.get('chord_server');
  const token = LS.get('chord_token');
  const name  = LS.get('chord_server_name');

  if (srv) {
    setBackend(srv, name || srv);
    if (token) {
      S.token = token;
      apiFetch('GET', '/me')
        .then(u => { S.user = u; bootApp(); })
        .catch(() => { S.token = null; LS.del('chord_token'); showAuth(); });
      return;
    }
    showAuth(); return;
  }

  // First launch — pre-fill the default server and auto-connect
  document.getElementById('sw-url').value = DEFAULT_SERVER;
  swConnect(DEFAULT_SERVER);
})();
</script>
</body>
</html>"""


class FrontendHandler(http.server.BaseHTTPRequestHandler):
    """Serves the frontend HTML for any GET request."""
    def do_GET(self):
        content = FRONTEND_HTML.encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def log_message(self, fmt, *args):
        pass  # suppress request logs


def start_frontend_server():
    """Start a local HTTP server for the frontend on a random free port."""
    port = find_free_port()
    httpd = socketserver.TCPServer(('127.0.0.1', port), FrontendHandler)
    httpd.allow_reuse_address = True
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    print(f'[chord] Frontend server on http://127.0.0.1:{port}')
    return port


def run():
    print('=' * 52)
    print('  ⚡ Chord — Desktop Client')
    print('=' * 52)

    # Try to start the local Chord backend
    js = resource_path('server.js')
    if os.path.exists(js):
        print('[chord] Starting local backend…')
        ok = start_backend()
        if not ok:
            print('[chord] Local backend unavailable — user can connect to a remote server.')
    else:
        print('[chord] No server.js found — remote-only mode.')

    # Start frontend HTTP server
    fe_port = start_frontend_server()
    frontend_url = f'http://127.0.0.1:{fe_port}'

    try:
        import webview
    except ImportError:
        print('\n❌  pywebview not installed.  Run:  pip install pywebview\n')
        # Fallback: just open in the system browser
        import webbrowser
        webbrowser.open(frontend_url)
        input('Press Enter to exit…')
        stop_backend()
        return

    webview.create_window(
        title='Chord',
        url=frontend_url,           # ← real HTTP URL, not inline HTML
        width=1340, height=840,
        min_size=(960, 640),
        resizable=True,
        background_color='#0d0e10',
    )
    webview.start(debug=False)
    stop_backend()


if __name__ == '__main__':
    run()