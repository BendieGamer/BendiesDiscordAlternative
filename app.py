"""
Chord — Desktop Client  (app.py)
=================================
Python desktop application powered by pywebview.

New in v2:
  • Server switcher UI — connect to any Chord backend (localhost or remote)
  • Real 1-on-1 WebRTC calling with ring/accept/reject flow
  • OS-level desktop notifications for DMs, calls, and friend requests
  • Call overlay with accept / hang-up buttons
  • Notification permission requested on startup
  • Saved server list in localStorage (persists across sessions)

Install:
    pip install pywebview

Run:
    python app.py

Build to EXE:
    pip install pyinstaller
    pyinstaller chord.spec
"""

import sys
import os
import time
import threading
import subprocess
import urllib.request

# ── PyInstaller resource helper ───────────────────────────────────────────────
def resource_path(rel: str) -> str:
    base = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, rel)

# ── Local backend management ──────────────────────────────────────────────────
LOCAL_PORT    = 3000
LOCAL_API     = f"http://localhost:{LOCAL_PORT}"
_backend_proc = None

def _find_node():
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

def start_local_backend():
    global _backend_proc
    server_js = resource_path('server.js')
    if not os.path.exists(server_js):
        return False
    node = _find_node()
    try:
        kw = {}
        if sys.platform == 'win32':
            kw['creationflags'] = subprocess.CREATE_NO_WINDOW
        _backend_proc = subprocess.Popen(
            [node, server_js],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            cwd=os.path.dirname(server_js), **kw
        )
        def _log(pipe):
            for line in iter(pipe.readline, b''):
                print('[backend]', line.decode(errors='replace').rstrip())
        threading.Thread(target=_log, args=(_backend_proc.stdout,), daemon=True).start()
        threading.Thread(target=_log, args=(_backend_proc.stderr,), daemon=True).start()
    except FileNotFoundError:
        print(f'[chord] node not found at: {node}')
        return False
    # Wait up to 12 s
    deadline = time.time() + 12
    while time.time() < deadline:
        try:
            urllib.request.urlopen(f'{LOCAL_API}/health', timeout=1)
            print('[chord] Local backend up ✅')
            return True
        except Exception:
            time.sleep(0.3)
    return False

def stop_local_backend():
    global _backend_proc
    if _backend_proc and _backend_proc.poll() is None:
        _backend_proc.terminate()
        try: _backend_proc.wait(timeout=5)
        except subprocess.TimeoutExpired: _backend_proc.kill()
        _backend_proc = None

# ── HTML frontend ─────────────────────────────────────────────────────────────
def build_html(default_api: str, default_ws: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Chord</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:ital,wght@0,300;0,400;0,500;0,600;0,700;1,400&family=DM+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
:root{{
  --bg:#0d0e10;--bg2:#141618;--bg3:#1a1c1f;--bg4:#222528;--sidebar:#111315;
  --accent:#5865f2;--accent2:#4752c4;--green:#3ba55c;--red:#ed4245;--yellow:#faa61a;
  --text:#dcddde;--text2:#8e9297;--text3:#72767d;--border:#2a2c2f;
  --hover:rgba(255,255,255,.06);--sel:rgba(88,101,242,.3);
  --r:8px;--f:'DM Sans',sans-serif;--mono:'DM Mono',monospace;
}}
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:var(--f);background:var(--bg);color:var(--text);height:100vh;overflow:hidden;display:flex;flex-direction:column}}
button{{font-family:var(--f);cursor:pointer;border:none;outline:none}}
input,textarea{{font-family:var(--f);outline:none;border:none}}
::-webkit-scrollbar{{width:4px}}::-webkit-scrollbar-thumb{{background:var(--bg4);border-radius:2px}}

/* ── Titlebar ── */
#titlebar{{
  -webkit-app-region:drag;height:38px;background:var(--sidebar);
  display:flex;align-items:center;padding:0 14px;gap:12px;flex-shrink:0;
  border-bottom:1px solid var(--border);
}}
#titlebar .logo{{font-size:15px;font-weight:800;letter-spacing:-.5px;color:#fff}}
#titlebar .server-badge{{
  font-size:11px;color:var(--text2);background:var(--bg3);padding:3px 8px;
  border-radius:12px;border:1px solid var(--border);max-width:200px;
  overflow:hidden;text-overflow:ellipsis;white-space:nowrap;
}}
#titlebar .no-drag{{-webkit-app-region:no-drag;display:flex;gap:6px;margin-left:auto;align-items:center}}

/* ── Buttons ── */
.btn{{display:inline-flex;align-items:center;justify-content:center;gap:6px;padding:9px 16px;border-radius:var(--r);font-size:13px;font-weight:600;transition:.15s;cursor:pointer}}
.btn-primary{{background:var(--accent);color:#fff}}.btn-primary:hover{{background:var(--accent2)}}
.btn-ghost{{background:transparent;color:var(--text2);border:1px solid var(--border)}}.btn-ghost:hover{{background:var(--hover);color:var(--text)}}
.btn-green{{background:var(--green);color:#fff}}.btn-green:hover{{background:#2e9450}}
.btn-red{{background:var(--red);color:#fff}}.btn-red:hover{{background:#c0392b}}
.btn-sm{{padding:5px 12px;font-size:12px}}
.btn-xs{{padding:4px 8px;font-size:11px}}
.err{{color:var(--red);font-size:12px;margin-top:8px}}

/* ── Server switcher screen ── */
#switcher-screen{{
  position:fixed;inset:0;top:38px;display:flex;align-items:center;justify-content:center;
  background:radial-gradient(ellipse at 20% 60%, #0f123a 0%, var(--bg) 65%);z-index:900;
}}
.sw-box{{background:var(--bg2);border:1px solid var(--border);border-radius:16px;padding:36px;width:480px;max-width:94vw}}
.sw-box h2{{font-size:24px;font-weight:800;margin-bottom:4px;
  background:linear-gradient(135deg,#fff 40%,var(--accent));-webkit-background-clip:text;-webkit-text-fill-color:transparent}}
.sw-box p{{color:var(--text2);font-size:13px;margin-bottom:24px}}
.sw-row{{display:flex;gap:8px;margin-bottom:10px}}
.sw-row input{{flex:1;padding:10px 12px;background:var(--bg3);color:var(--text);border:1px solid var(--border);border-radius:var(--r);font-size:14px;transition:.15s}}
.sw-row input:focus{{border-color:var(--accent)}}
.saved-list{{max-height:180px;overflow-y:auto;margin-bottom:16px}}
.saved-item{{
  display:flex;align-items:center;gap:10px;padding:9px 12px;border-radius:8px;
  background:var(--bg3);margin-bottom:6px;cursor:pointer;transition:.15s;
}}
.saved-item:hover{{background:var(--bg4)}}
.saved-item .dot{{width:8px;height:8px;border-radius:50%;background:var(--text3);flex-shrink:0}}
.saved-item .dot.online{{background:var(--green)}}
.saved-item .url{{flex:1;font-size:13px;font-family:var(--mono)}}
.saved-item .name{{font-size:12px;color:var(--text2)}}
.sw-divider{{display:flex;align-items:center;gap:10px;margin:16px 0;color:var(--text3);font-size:12px}}
.sw-divider::before,.sw-divider::after{{content:'';flex:1;height:1px;background:var(--border)}}

/* ── Auth screen ── */
#auth-screen{{
  position:fixed;inset:0;top:38px;display:flex;align-items:center;justify-content:center;
  background:radial-gradient(ellipse at 30% 40%,#1a1f5e 0%,var(--bg) 60%);z-index:800;
}}
.auth-box{{background:var(--bg2);border:1px solid var(--border);border-radius:16px;padding:36px;width:400px;max-width:94vw}}
.auth-box h1{{font-size:26px;font-weight:800;margin-bottom:4px;
  background:linear-gradient(135deg,#fff,var(--accent));-webkit-background-clip:text;-webkit-text-fill-color:transparent}}
.auth-box small{{color:var(--text2);font-size:12px;display:block;margin-bottom:24px}}
.auth-box label{{display:block;font-size:11px;font-weight:700;color:var(--text2);text-transform:uppercase;letter-spacing:.06em;margin:14px 0 5px}}
.auth-box input{{width:100%;padding:9px 12px;background:var(--bg3);color:var(--text);border:1px solid var(--border);border-radius:var(--r);font-size:14px;transition:.15s}}
.auth-box input:focus{{border-color:var(--accent)}}
.auth-actions{{margin-top:20px;display:flex;gap:8px;align-items:center}}
.auth-switch{{font-size:12px;color:var(--text2);cursor:pointer}}.auth-switch span{{color:var(--accent);font-weight:600}}
.back-btn{{font-size:12px;color:var(--text3);cursor:pointer;display:flex;align-items:center;gap:4px;margin-bottom:16px}}
.back-btn:hover{{color:var(--text)}}

/* ── App shell ── */
#app{{display:flex;flex:1;overflow:hidden}}
#server-list{{width:68px;background:var(--sidebar);display:flex;flex-direction:column;align-items:center;padding:10px 0;gap:6px;overflow-y:auto;flex-shrink:0}}
.s-icon{{width:46px;height:46px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:17px;font-weight:700;cursor:pointer;transition:.2s;color:#fff;position:relative;flex-shrink:0}}
.s-icon:hover{{border-radius:14px}}.s-icon.active{{border-radius:14px}}
.s-icon::before{{content:'';position:absolute;left:-8px;top:50%;transform:translateY(-50%);width:4px;border-radius:0 4px 4px 0;background:var(--accent);transition:.2s;height:0}}
.s-icon.active::before{{height:70%}}.s-icon:hover::before{{height:35%}}
.s-div{{width:30px;height:1px;background:var(--border);margin:2px 0}}
.s-add{{width:46px;height:46px;border-radius:50%;background:var(--bg3);display:flex;align-items:center;justify-content:center;cursor:pointer;color:var(--green);font-size:22px;transition:.2s;flex-shrink:0}}
.s-add:hover{{background:var(--green);color:#fff;border-radius:14px}}

#ch-sidebar{{width:232px;background:var(--bg2);display:flex;flex-direction:column;flex-shrink:0}}
.srv-header{{height:46px;padding:0 14px;display:flex;align-items:center;justify-content:space-between;border-bottom:1px solid var(--border);font-weight:700;font-size:14px;cursor:pointer;flex-shrink:0}}
.srv-header:hover{{background:var(--hover)}}
.ch-section{{padding:14px 6px 2px;font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.07em;color:var(--text3);display:flex;justify-content:space-between;align-items:center}}
.ch-section span{{cursor:pointer;font-size:16px}}
.ch-item{{display:flex;align-items:center;gap:7px;padding:7px 8px;margin:0 6px;border-radius:6px;cursor:pointer;color:var(--text2);font-size:14px;transition:.13s}}
.ch-item:hover{{background:var(--hover);color:var(--text)}}.ch-item.active{{background:var(--sel);color:#fff}}
.ch-hash{{font-size:17px;color:var(--text3)}}
.vc-member-row{{padding:2px 6px 2px 34px;display:flex;align-items:center;gap:6px;font-size:11px;color:var(--text2)}}
.vc-member-row .dot{{width:7px;height:7px;border-radius:50%;background:var(--green)}}

#user-panel{{height:50px;background:var(--bg3);display:flex;align-items:center;gap:8px;padding:0 8px;margin-top:auto;flex-shrink:0}}
.uav{{width:30px;height:30px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:12px;font-weight:700;color:#fff;flex-shrink:0}}
.upname{{font-size:13px;font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;flex:1}}
.uptag{{font-size:11px;color:var(--text3);font-family:var(--mono)}}

#dm-sidebar{{width:232px;background:var(--bg2);display:flex;flex-direction:column;flex-shrink:0}}
.dm-hdr{{height:46px;padding:0 14px;display:flex;align-items:center;border-bottom:1px solid var(--border);font-weight:700;font-size:14px}}
.dm-item{{display:flex;align-items:center;gap:9px;padding:7px 10px;margin:3px 6px;border-radius:6px;cursor:pointer;color:var(--text2);transition:.13s}}
.dm-item:hover{{background:var(--hover);color:var(--text)}}.dm-item.active{{background:var(--sel);color:#fff}}
.dm-item .call-btn{{margin-left:auto;opacity:0;transition:.15s;color:var(--green);font-size:15px;padding:2px 4px}}
.dm-item:hover .call-btn{{opacity:1}}

#main{{flex:1;display:flex;flex-direction:column;overflow:hidden;position:relative}}
.ch-hdr{{height:46px;padding:0 14px;display:flex;align-items:center;gap:8px;border-bottom:1px solid var(--border);font-weight:700;font-size:14px;flex-shrink:0}}
.ch-hdr .hash{{color:var(--text2);font-size:18px}}.hsep{{width:1px;height:18px;background:var(--border)}}
.htopic{{color:var(--text2);font-size:13px;font-weight:400}}

#msgs{{flex:1;overflow-y:auto;padding:12px 0}}
.mg{{display:flex;gap:14px;padding:3px 14px;transition:.1s}}.mg:hover{{background:rgba(255,255,255,.02)}}
.mav{{width:38px;height:38px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:15px;font-weight:700;color:#fff;flex-shrink:0;margin-top:2px}}
.mb{{flex:1;min-width:0}}.mm{{display:flex;align-items:baseline;gap:7px;margin-bottom:1px}}
.mauth{{font-weight:600;font-size:14px}}.mtime{{font-size:10px;color:var(--text3);font-family:var(--mono)}}
.mc{{font-size:14px;line-height:1.5;word-break:break-word}}

#input-area{{padding:0 14px 20px;flex-shrink:0}}
.input-box{{background:var(--bg4);border-radius:var(--r);display:flex;align-items:center;padding:0 12px;gap:8px}}
.input-box input{{flex:1;background:transparent;color:var(--text);font-size:14px;padding:13px 0}}
.input-box input::placeholder{{color:var(--text3)}}
.send-btn{{background:transparent;color:var(--accent);font-size:19px;padding:4px 8px;border-radius:6px;transition:.15s}}
.send-btn:hover{{background:var(--accent);color:#fff}}

#members-panel{{width:230px;background:var(--bg2);padding:14px 6px;overflow-y:auto;flex-shrink:0}}
#members-panel h3{{font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.07em;color:var(--text3);padding:0 8px;margin-bottom:8px}}
.mem-row{{display:flex;align-items:center;gap:9px;padding:5px 8px;border-radius:6px;cursor:pointer;transition:.13s}}
.mem-row:hover{{background:var(--hover)}}.mem-name{{font-size:14px;color:var(--text2)}}
.online-dot{{width:9px;height:9px;border-radius:50%;background:var(--green);flex-shrink:0;margin-left:auto}}

/* ── Voice panel ── */
#voice-panel{{flex:1;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:20px}}
.vc-room{{background:var(--bg2);border-radius:16px;padding:28px 44px;text-align:center;min-width:320px;border:1px solid var(--border)}}
.vc-room h2{{font-size:20px;font-weight:700;margin-bottom:3px}}
.vc-room .sub{{color:var(--text2);font-size:13px;margin-bottom:20px}}
.vc-parts{{display:flex;flex-wrap:wrap;gap:14px;justify-content:center;margin-bottom:20px;min-height:72px}}
.vc-part{{display:flex;flex-direction:column;align-items:center;gap:6px}}
.vc-av{{width:64px;height:64px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:22px;font-weight:700;color:#fff;transition:.25s;position:relative}}
.vc-av.speaking{{box-shadow:0 0 0 3px var(--green)}}
.vc-av.muted::after{{content:'🔇';position:absolute;bottom:-2px;right:-2px;font-size:13px}}
.vc-name{{font-size:12px;color:var(--text2);font-weight:600}}
.vc-ctrls{{display:flex;gap:10px}}
.vc-btn{{width:44px;height:44px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:18px;cursor:pointer;transition:.2s;border:none}}
.vc-btn.def{{background:var(--bg4);color:var(--text)}}.vc-btn.def:hover{{background:var(--hover)}}
.vc-btn.muted{{background:var(--red);color:#fff}}
.vc-btn.leave{{background:var(--red);color:#fff}}.vc-btn.leave:hover{{background:#c0392b}}
#vc-status{{margin-top:10px;font-size:12px;color:var(--text2)}}

/* ── Friends panel ── */
#friends-panel{{flex:1;display:flex;flex-direction:column;overflow:hidden}}
.ftabs{{height:46px;padding:0 14px;display:flex;align-items:center;gap:3px;border-bottom:1px solid var(--border)}}
.ftab{{padding:5px 11px;border-radius:6px;font-size:13px;font-weight:600;cursor:pointer;color:var(--text2);background:transparent;transition:.13s}}
.ftab.active{{background:var(--sel);color:#fff}}.ftab:hover:not(.active){{background:var(--hover)}}
#fcontent{{flex:1;overflow-y:auto;padding:14px}}
.fr-row{{display:flex;align-items:center;gap:10px;padding:10px;border-radius:8px;background:var(--bg3);margin-bottom:7px;transition:.13s}}
.fr-row:hover{{background:var(--bg4)}}.fr-info{{flex:1}}.fr-name{{font-weight:600;font-size:14px}}.fr-status{{font-size:12px;color:var(--text2)}}
.fr-acts{{display:flex;gap:5px}}
.add-form{{display:flex;gap:8px;margin-bottom:18px}}
.add-form input{{flex:1;padding:9px 12px;background:var(--bg3);color:var(--text);border:1px solid var(--border);border-radius:var(--r);font-size:13px}}
.add-form input:focus{{border-color:var(--accent)}}

/* ── Welcome ── */
#welcome{{flex:1;display:flex;align-items:center;justify-content:center;flex-direction:column;gap:10px;color:var(--text2)}}

/* ── CALLING OVERLAY ── */
#call-overlay{{
  position:fixed;bottom:24px;right:24px;z-index:800;
  background:var(--bg2);border:1px solid var(--border);border-radius:14px;
  padding:18px 20px;width:280px;box-shadow:0 16px 48px rgba(0,0,0,.6);
  display:none;
}}
#call-overlay.show{{display:block;animation:popIn .2s ease}}
@keyframes popIn{{from{{transform:scale(.9);opacity:0}}to{{transform:scale(1);opacity:1}}}}
.co-tag{{font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.07em;color:var(--text2);margin-bottom:8px}}
.co-tag.ringing{{color:var(--green)}}.co-tag.outgoing{{color:var(--yellow)}}
.co-user{{display:flex;align-items:center;gap:10px;margin-bottom:14px}}
.co-user .av{{width:44px;height:44px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:18px;font-weight:700;color:#fff}}
.co-user .info .name{{font-weight:700;font-size:15px}}.co-user .info .sub{{font-size:12px;color:var(--text2)}}
.co-btns{{display:flex;gap:8px}}
.co-ring{{animation:pulse 1.5s infinite}}
@keyframes pulse{{0%,100%{{box-shadow:0 0 0 0 rgba(59,165,92,.4)}}50%{{box-shadow:0 0 0 8px rgba(59,165,92,0)}}}}
.co-timer{{font-size:13px;color:var(--text2);text-align:center;margin-top:8px;font-family:var(--mono)}}

/* ── Active call bar ── */
#call-bar{{
  position:fixed;bottom:0;left:68px;right:0;height:44px;
  background:linear-gradient(90deg,#1d5c31,#1a4d29);
  display:none;align-items:center;padding:0 16px;gap:12px;
  border-top:1px solid #2a7a40;z-index:700;
}}
#call-bar.show{{display:flex}}
#call-bar .cname{{font-weight:600;font-size:13px;flex:1}}
#call-bar .cdur{{font-size:12px;color:rgba(255,255,255,.7);font-family:var(--mono)}}

/* ── Toast ── */
#toasts{{position:fixed;bottom:70px;right:24px;display:flex;flex-direction:column;gap:7px;z-index:1000}}
.toast{{background:var(--bg3);border:1px solid var(--border);border-radius:8px;padding:10px 14px;font-size:13px;max-width:280px;animation:tsIn .2s;box-shadow:0 6px 20px rgba(0,0,0,.4)}}
.toast.ok{{border-color:var(--green);color:var(--green)}}.toast.err{{border-color:var(--red);color:var(--red)}}.toast.info{{border-color:var(--accent);color:var(--accent)}}
@keyframes tsIn{{from{{transform:translateX(30px);opacity:0}}to{{transform:translateX(0);opacity:1}}}}

/* ── Modal ── */
.modal-ov{{position:fixed;inset:0;background:rgba(0,0,0,.55);display:flex;align-items:center;justify-content:center;z-index:600}}
.modal{{background:var(--bg2);border-radius:12px;padding:24px;width:360px;max-width:94vw;border:1px solid var(--border)}}
.modal h2{{font-size:18px;font-weight:700;margin-bottom:14px}}
.modal label{{display:block;font-size:11px;font-weight:700;color:var(--text2);text-transform:uppercase;letter-spacing:.06em;margin:12px 0 5px}}
.modal input,.modal select{{width:100%;padding:9px 12px;background:var(--bg3);color:var(--text);border:1px solid var(--border);border-radius:var(--r);font-size:13px;font-family:var(--f)}}
.modal input:focus,.modal select:focus{{border-color:var(--accent)}}
.m-acts{{display:flex;gap:8px;justify-content:flex-end;margin-top:18px}}

.hidden{{display:none!important}}
</style>
</head>
<body>

<!-- Titlebar -->
<div id="titlebar">
  <span class="logo">⚡ Chord</span>
  <span class="server-badge" id="tb-server">Connecting…</span>
  <div class="no-drag">
    <button class="btn btn-ghost btn-sm" onclick="showSwitcher()" title="Switch server">🌐 Servers</button>
    <button class="btn btn-ghost btn-sm" onclick="logout()">↩ Logout</button>
  </div>
</div>

<!-- Server switcher -->
<div id="switcher-screen">
  <div class="sw-box">
    <h2>Connect to a Chord Server</h2>
    <p>Enter the address of a Chord backend, or pick a saved one below. You can host your own!</p>

    <div class="sw-row">
      <input id="sw-url" placeholder="http://localhost:3000  or  https://mychord.example.com" type="url"
             onkeydown="if(event.key==='Enter') swConnect()" />
      <button class="btn btn-primary" onclick="swConnect()">Connect</button>
    </div>
    <div id="sw-err" class="err"></div>

    <div id="saved-list" class="saved-list"></div>

    <div class="sw-divider">or</div>
    <button class="btn btn-ghost" style="width:100%" onclick="swLocal()">
      🖥️ Use local server (localhost:3000)
    </button>
    <div style="margin-top:8px;font-size:11px;color:var(--text3)">
      Demo accounts on any fresh server: alice / bob / charlie &nbsp;(password: password123)
    </div>
  </div>
</div>

<!-- Auth screen -->
<div id="auth-screen" class="hidden">
  <div class="auth-box">
    <div class="back-btn" onclick="showSwitcher()">← Change server</div>
    <h1 id="auth-title">Welcome back</h1>
    <small id="auth-srv"></small>
    <div id="reg-wrap" class="hidden">
      <label>Display Name</label>
      <input id="reg-name" placeholder="Your Name" />
    </div>
    <label>Username</label>
    <input id="auth-un" placeholder="username" autocomplete="username" />
    <label>Password</label>
    <input id="auth-pw" type="password" placeholder="••••••••" autocomplete="current-password"
           onkeydown="if(event.key==='Enter') doAuth()" />
    <div id="auth-err" class="err"></div>
    <div class="auth-actions">
      <button class="btn btn-primary" onclick="doAuth()" id="auth-btn">Log In</button>
      <span class="auth-switch" onclick="toggleReg()">Need an account? <span>Register</span></span>
    </div>
  </div>
</div>

<!-- App -->
<div id="app" class="hidden">
  <!-- Server rail -->
  <div id="server-list">
    <div class="s-icon" id="dm-icon" title="DMs & Friends" onclick="showDMs()" style="background:var(--accent);font-size:20px">💬</div>
    <div class="s-div"></div>
    <div id="s-icons"></div>
    <div class="s-add" title="Create Server" onclick="showCreateServer()">+</div>
  </div>

  <!-- Channel sidebar -->
  <div id="ch-sidebar">
    <div class="srv-header" id="srv-hdr">Select a server</div>
    <div id="ch-list" style="flex:1;overflow-y:auto;padding-bottom:8px"></div>
    <div id="user-panel">
      <div class="uav" id="pan-av"></div>
      <div style="flex:1;min-width:0">
        <div class="upname" id="pan-name"></div>
        <div class="uptag" id="pan-tag"></div>
      </div>
    </div>
  </div>

  <!-- DM sidebar -->
  <div id="dm-sidebar" class="hidden">
    <div class="dm-hdr">Direct Messages</div>
    <div id="dm-list" style="flex:1;overflow-y:auto;padding:6px 0"></div>
    <div id="user-panel-dm" style="height:50px;background:var(--bg3);display:flex;align-items:center;gap:8px;padding:0 8px">
      <div class="uav" id="pan-av-dm"></div>
      <div style="flex:1;min-width:0">
        <div class="upname" id="pan-name-dm"></div>
        <div class="uptag" id="pan-tag-dm"></div>
      </div>
    </div>
  </div>

  <!-- Main -->
  <div id="main">
    <!-- Channel view -->
    <div id="ch-view" class="hidden" style="display:flex;flex-direction:column;flex:1;overflow:hidden">
      <div class="ch-hdr">
        <span class="hash" id="ch-hash">#</span>
        <span id="ch-name-h">general</span>
        <div class="hsep"></div>
        <span class="htopic" id="ch-topic"></span>
        <div style="margin-left:auto;display:flex;gap:6px">
          <button class="btn btn-ghost btn-sm" id="call-hdr-btn" style="display:none" onclick="callCurrentDmUser()">📞 Call</button>
          <button class="btn btn-ghost btn-sm" onclick="toggleMembers()">👥</button>
        </div>
      </div>
      <div id="msgs"></div>
      <div id="input-area">
        <div class="input-box">
          <input id="msg-in" placeholder="Message…" onkeydown="handleKey(event)" />
          <button class="send-btn" onclick="send()">➤</button>
        </div>
      </div>
    </div>

    <!-- Voice panel -->
    <div id="voice-panel" class="hidden" style="display:flex">
      <div class="vc-room">
        <h2 id="vc-name">Voice Channel</h2>
        <div class="sub">Real-time voice · WebRTC</div>
        <div class="vc-parts" id="vc-parts"></div>
        <div class="vc-ctrls">
          <button class="vc-btn def" id="vc-mute" onclick="toggleMute()" title="Mute">🎤</button>
          <button class="vc-btn def" id="vc-deaf" onclick="toggleDeafen()" title="Deafen">🔊</button>
          <button class="vc-btn leave" onclick="leaveVC()" title="Leave">📞</button>
        </div>
        <div id="vc-status"></div>
      </div>
    </div>

    <!-- Friends panel -->
    <div id="friends-panel" class="hidden" style="display:flex">
      <div class="ftabs">
        <button class="ftab active" onclick="fTab('all',this)">All Friends</button>
        <button class="ftab" onclick="fTab('pending',this)">Pending</button>
        <button class="ftab" onclick="fTab('add',this)">Add Friend</button>
      </div>
      <div id="fcontent"></div>
    </div>

    <!-- Welcome -->
    <div id="welcome">
      <div style="font-size:56px">⚡</div>
      <div style="font-size:20px;font-weight:700;color:var(--text)">Pick a channel to start</div>
      <div style="font-size:14px">Or open a DM and call a friend</div>
    </div>
  </div>

  <!-- Members panel -->
  <div id="members-panel" class="hidden">
    <h3>Members</h3>
    <div id="mem-list"></div>
  </div>
</div>

<!-- Incoming / Outgoing call overlay -->
<div id="call-overlay">
  <div class="co-tag" id="co-tag">Incoming Call</div>
  <div class="co-user">
    <div class="av" id="co-av" style="background:var(--accent)">?</div>
    <div class="info">
      <div class="name" id="co-name">Unknown</div>
      <div class="sub" id="co-sub">is calling you…</div>
    </div>
  </div>
  <div class="co-btns" id="co-btns"></div>
  <div class="co-timer" id="co-timer"></div>
</div>

<!-- Active call bar -->
<div id="call-bar">
  <span style="font-size:16px">📞</span>
  <span class="cname" id="cb-name">Call</span>
  <span class="cdur" id="cb-dur">00:00</span>
  <button class="btn btn-red btn-sm" onclick="hangup()">Hang Up</button>
  <button class="btn btn-ghost btn-sm" id="cb-mute" onclick="toggleCallMute()">🎤 Mute</button>
</div>

<!-- Toasts -->
<div id="toasts"></div>

<!-- Modal -->
<div id="modal-ov" class="modal-ov hidden" onclick="if(event.target===this)closeModal()">
  <div class="modal">
    <h2 id="m-title"></h2>
    <div id="m-body"></div>
    <div class="m-acts" id="m-acts"></div>
  </div>
</div>

<audio id="ring-audio" loop>
  <source src="data:audio/wav;base64,UklGRnoGAABXQVZFZm10IBAAAA..." type="audio/wav">
</audio>

<script>
// ═══════════════════════════════════════════════════════════
// STATE
// ═══════════════════════════════════════════════════════════
let API_BASE = '{default_api}';
let WS_BASE  = '{default_ws}';

const S = {{
  token:null, user:null, servers:[], curSrv:null, channels:[],
  curCh:null, curDmId:null, curDmUser:null, members:[], dms:[],
  view:'welcome',
  chWs:null, userWs:null, vcWs:null, callWs:null,
  // VC
  vcCh:null, localStream:null, vcPeers:{{}}, muted:false, deafened:false, vcParts:{{}},
  // Calls
  callId:null, callRole:null, callPeerId:null,
  callStream:null, callPeers:{{}}, callMuted:false, callActive:false,
  callTimer:null, callStartTime:null, callTimerEl:null,
  // Ring timeout
  ringTimeout:null,
}};

// ═══════════════════════════════════════════════════════════
// UTILITIES
// ═══════════════════════════════════════════════════════════
async function api(method, path, body) {{
  const r = await fetch(API_BASE + path, {{
    method,
    headers:{{'Content-Type':'application/json', ...(S.token?{{'Authorization':'Bearer '+S.token}}:{{}}) }},
    body: body ? JSON.stringify(body) : undefined,
  }});
  if (!r.ok) {{ const e=await r.json().catch(()=>({{error:'Error'}})); throw new Error(e.error||'Request failed'); }}
  return r.json();
}}

function toast(msg, type='info', dur=3500) {{
  const el = document.createElement('div');
  el.className = `toast ${{type}}`;
  el.textContent = msg;
  document.getElementById('toasts').appendChild(el);
  setTimeout(()=>el.remove(), dur);
}}

function esc(t) {{ return String(t).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }}
function av(l,c,sz=38,fs=14){{ return `<div style="width:${{sz}}px;height:${{sz}}px;border-radius:50%;background:${{c}};display:flex;align-items:center;justify-content:center;font-size:${{fs}}px;font-weight:700;color:#fff;flex-shrink:0">${{esc(l)}}</div>`; }}
function tfmt(ts) {{ return new Date(ts*1000).toLocaleTimeString([],{{hour:'2-digit',minute:'2-digit'}}); }}
function secFmt(s) {{ const m=Math.floor(s/60); return `${{String(m).padStart(2,'0')}}:${{String(s%60).padStart(2,'0')}}`; }}

// Desktop notifications
function requestNotifPerm() {{
  if ('Notification' in window && Notification.permission==='default') Notification.requestPermission();
}}

function notify(title, body, icon='⚡') {{
  if (!('Notification' in window) || Notification.permission!=='granted') return;
  try {{ new Notification(title, {{ body, icon:'data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 100 100%22><text y=%22.9em%22 font-size=%2290%22>${{icon}}</text></svg>' }}); }} catch {{}}
}}

// Ringtone (generated beep via Web Audio)
let _ringCtx=null, _ringNodes=[];
function startRing() {{
  stopRing();
  try {{
    _ringCtx = new (window.AudioContext||window.webkitAudioContext)();
    function beep() {{
      if (!_ringCtx) return;
      const o=_ringCtx.createOscillator(), g=_ringCtx.createGain();
      o.connect(g); g.connect(_ringCtx.destination);
      o.frequency.value=880; g.gain.setValueAtTime(.3,_ringCtx.currentTime);
      g.gain.exponentialRampToValueAtTime(.001,_ringCtx.currentTime+.5);
      o.start(_ringCtx.currentTime); o.stop(_ringCtx.currentTime+.5);
    }}
    beep();
    const id = setInterval(beep, 1500);
    _ringNodes.push(id);
  }} catch {{}}
}}
function stopRing() {{
  for (const id of _ringNodes) clearInterval(id);
  _ringNodes=[];
  if (_ringCtx) {{ _ringCtx.close().catch(()=>{{}}); _ringCtx=null; }}
}}

// ═══════════════════════════════════════════════════════════
// SERVER SWITCHER
// ═══════════════════════════════════════════════════════════
const SAVED_KEY = 'chord_saved_servers';

function getSaved() {{ try {{ return JSON.parse(localStorage.getItem(SAVED_KEY)||'[]'); }} catch {{ return []; }} }}
function saveServer(url, name) {{
  const list = getSaved().filter(s=>s.url!==url);
  list.unshift({{ url, name, ts:Date.now() }});
  localStorage.setItem(SAVED_KEY, JSON.stringify(list.slice(0,10)));
}}
function removeSaved(url) {{
  localStorage.setItem(SAVED_KEY, JSON.stringify(getSaved().filter(s=>s.url!==url)));
  renderSaved();
}}

function renderSaved() {{
  const el = document.getElementById('saved-list');
  const list = getSaved();
  if (!list.length) {{ el.innerHTML='<div style="color:var(--text3);font-size:12px;padding:8px 0">No saved servers yet.</div>'; return; }}
  el.innerHTML = list.map(s=>`
    <div class="saved-item" onclick="swSelect('${{esc(s.url)}}')">
      <div class="dot" id="dot-${{btoa(s.url).replace(/[^a-z0-9]/gi,'')}}"></div>
      <div style="flex:1;min-width:0">
        <div class="url">${{esc(s.url)}}</div>
        ${{s.name?`<div class="name">${{esc(s.name)}}</div>`:''}}
      </div>
      <button class="btn btn-ghost btn-xs" onclick="event.stopPropagation();removeSaved('${{esc(s.url)}}')" title="Remove">✕</button>
    </div>
  `).join('');
  // Ping each saved server
  for (const s of list) {{
    fetch(s.url+'/health', {{signal:AbortSignal.timeout(2000)}})
      .then(r=>r.ok?'online':'offline').catch(()=>'offline')
      .then(status=>{{
        const dot = document.getElementById('dot-'+btoa(s.url).replace(/[^a-z0-9]/gi,''));
        if (dot) dot.className = 'dot '+(status==='online'?'online':'');
      }});
  }}
}}

async function swConnect(url) {{
  const input = document.getElementById('sw-url');
  url = (url || input.value).trim().replace(/\\/+$/,'');
  if (!url) {{ document.getElementById('sw-err').textContent='Enter a server URL'; return; }}
  if (!url.startsWith('http')) url = 'http://'+url;
  document.getElementById('sw-err').textContent='Checking…';
  try {{
    const r = await fetch(url+'/health', {{signal:AbortSignal.timeout(5000)}});
    if (!r.ok) throw new Error('Bad response');
    const data = await r.json();
    document.getElementById('sw-err').textContent='';
    setServer(url, data.server||url);
    saveServer(url, data.server||'');
    showAuth();
  }} catch(e) {{
    document.getElementById('sw-err').textContent = '❌ Could not connect: '+e.message;
  }}
}}

async function swLocal() {{ await swConnect('http://localhost:{LOCAL_PORT}'); }}
async function swSelect(url) {{ await swConnect(url); }}

function setServer(httpUrl, name) {{
  API_BASE = httpUrl + '/api';
  WS_BASE  = httpUrl.replace(/^http/,'ws');
  document.getElementById('tb-server').textContent = name || httpUrl;
  // Clear any stale auth for different server
  const storedSrv = localStorage.getItem('chord_server');
  if (storedSrv !== httpUrl) {{
    localStorage.removeItem('chord_token');
    S.token = null;
  }}
  localStorage.setItem('chord_server', httpUrl);
}}

function showSwitcher() {{
  document.getElementById('switcher-screen').style.display='flex';
  document.getElementById('auth-screen').classList.add('hidden');
  document.getElementById('app').classList.add('hidden');
  renderSaved();
}}

// ═══════════════════════════════════════════════════════════
// AUTH
// ═══════════════════════════════════════════════════════════
let isReg = false;
function showAuth() {{
  document.getElementById('switcher-screen').style.display='none';
  document.getElementById('auth-screen').classList.remove('hidden');
  document.getElementById('auth-srv').textContent = 'Connected to: '+API_BASE.replace('/api','');
  // Check saved token
  const saved = localStorage.getItem('chord_token');
  if (saved) {{ S.token=saved; tryAutoLogin(); }}
}}
async function tryAutoLogin() {{
  try {{ S.user = await api('GET','/me'); showApp(); }} catch {{ S.token=null; localStorage.removeItem('chord_token'); }}
}}
function toggleReg() {{
  isReg=!isReg;
  document.getElementById('auth-title').textContent = isReg?'Create account':'Welcome back';
  document.getElementById('auth-btn').textContent   = isReg?'Register':'Log In';
  document.getElementById('reg-wrap').classList.toggle('hidden',!isReg);
  document.querySelector('.auth-switch').innerHTML   = isReg?'Have an account? <span>Log In</span>':'Need an account? <span>Register</span>';
  document.getElementById('auth-err').textContent   = '';
}}
async function doAuth() {{
  const un=document.getElementById('auth-un').value.trim();
  const pw=document.getElementById('auth-pw').value;
  const err=document.getElementById('auth-err');
  if (!un||!pw) {{ err.textContent='Fill in all fields'; return; }}
  try {{
    let d;
    if (isReg) {{
      const dn=document.getElementById('reg-name').value.trim()||un;
      d=await api('POST','/register',{{username:un,display_name:dn,password:pw}});
    }} else {{ d=await api('POST','/login',{{username:un,password:pw}}); }}
    S.token=d.token; S.user=d.user;
    localStorage.setItem('chord_token',d.token);
    showApp();
  }} catch(e) {{ err.textContent=e.message; }}
}}
function logout() {{
  localStorage.removeItem('chord_token');
  S.token=null; S.user=null;
  if (S.userWs) S.userWs.close();
  showSwitcher();
}}

// ═══════════════════════════════════════════════════════════
// APP INIT
// ═══════════════════════════════════════════════════════════
async function showApp() {{
  if (!S.user) {{ try{{ S.user=await api('GET','/me'); }}catch{{ return showSwitcher(); }} }}
  document.getElementById('switcher-screen').style.display='none';
  document.getElementById('auth-screen').classList.add('hidden');
  document.getElementById('app').classList.remove('hidden');
  const u=S.user, l=(u.display_name||u.username)[0].toUpperCase();
  for (const id of ['pan-av','pan-av-dm']) {{
    const el=document.getElementById(id); el.style.background=u.avatar_color; el.textContent=l;
  }}
  for (const id of ['pan-name','pan-name-dm']) document.getElementById(id).textContent=u.display_name;
  for (const id of ['pan-tag','pan-tag-dm'])   document.getElementById(id).textContent='@'+u.username;
  await loadServers();
  connectUserWs();
  requestNotifPerm();
  showView('welcome');
}}

// ═══════════════════════════════════════════════════════════
// USER WEBSOCKET (notifications + call events)
// ═══════════════════════════════════════════════════════════
function connectUserWs() {{
  if (S.userWs) S.userWs.close();
  const ws = new WebSocket(`${{WS_BASE}}/ws/user/${{S.user.id}}?token=${{S.token}}`);
  ws.onmessage = e => handleUserWsMsg(JSON.parse(e.data));
  ws.onclose = () => setTimeout(()=>{{ if(S.token) connectUserWs(); }}, 3000);
  S.userWs = ws;
}}

function handleUserWsMsg(msg) {{
  switch(msg.type) {{
    case 'new_dm':
      if (S.curDmId!==msg.dm_id) {{
        toast(`💬 ${{msg.message.display_name}}: ${{msg.message.content.slice(0,50)}}`, 'info');
        notify('New message from '+msg.message.display_name, msg.message.content.slice(0,100), '💬');
      }} else {{
        appendMsg(msg.message);
      }}
      loadDMs();
      break;

    case 'friend_request':
      toast(`👋 Friend request from ${{msg.from}}`, 'info');
      notify('Friend request', msg.from+' wants to be friends', '👋');
      break;

    // ── Incoming call ──
    case 'call_ring':
      S.callId   = msg.callId;
      S.callRole = 'callee';
      showCallOverlay('incoming', msg.caller);
      startRing();
      notify('📞 Incoming call', msg.caller.display_name+' is calling you…', '📞');
      // Auto-reject after 45s
      S.ringTimeout = setTimeout(()=>{{ if(S.callId===msg.callId) rejectCall(); }}, 45000);
      break;

    // ── Caller: callee's phone is ringing ──
    case 'call_ringing':
      S.callId   = msg.callId;
      S.callRole = 'caller';
      showCallOverlay('outgoing', msg.callee);
      break;

    // ── Callee accepted ──
    case 'call_accepted':
      clearTimeout(S.ringTimeout);
      stopRing();
      hideCallOverlay();
      startActiveCall(msg.callId, msg.callee||S.curDmUser);
      break;

    // ── Various ending events ──
    case 'call_rejected':
    case 'call_cancelled':
    case 'call_ended':
    case 'call_missed':
      clearTimeout(S.ringTimeout);
      stopRing();
      hideCallOverlay();
      endActiveCall();
      toast(msg.type==='call_rejected'?'📵 Call rejected':msg.type==='call_missed'?'📵 Missed call':'📞 Call ended', 'info');
      break;

    case 'call_busy':
      toast(`📵 ${{msg.callee}} is busy`, 'err');
      break;
  }}
}}

// ═══════════════════════════════════════════════════════════
// SERVERS
// ═══════════════════════════════════════════════════════════
async function loadServers() {{
  S.servers = await api('GET','/servers');
  renderServerIcons();
}}

function renderServerIcons() {{
  const el=document.getElementById('s-icons'); el.innerHTML='';
  for (const s of S.servers) {{
    const d=document.createElement('div');
    d.className='s-icon'+(S.curSrv?.id===s.id?' active':'');
    d.style.background=s.icon_color; d.title=s.name; d.textContent=s.name[0].toUpperCase();
    d.onclick=()=>selectServer(s);
    el.appendChild(d);
  }}
}}

async function selectServer(srv) {{
  S.curSrv=srv; S.curDmId=null; S.curDmUser=null;
  document.getElementById('ch-sidebar').style.display='flex';
  document.getElementById('dm-sidebar').classList.add('hidden');
  document.getElementById('srv-hdr').textContent=srv.name;
  renderServerIcons();
  await loadChannels(); await loadMembers();
  showView('welcome');
}}

// ═══════════════════════════════════════════════════════════
// CHANNELS
// ═══════════════════════════════════════════════════════════
async function loadChannels() {{
  S.channels = await api('GET',`/servers/${{S.curSrv.id}}/channels`);
  renderChannels();
}}

function renderChannels() {{
  const el=document.getElementById('ch-list'); el.innerHTML='';
  const txt=S.channels.filter(c=>c.type==='text');
  const vc =S.channels.filter(c=>c.type==='voice');
  if (txt.length) {{
    el.innerHTML+=`<div class="ch-section">Text <span onclick="showCreateCh('text')">+</span></div>`;
    for (const c of txt)
      el.innerHTML+=`<div class="ch-item${{S.curCh?.id===c.id?' active':''}}" onclick="selectCh(${{c.id}})"><span class="ch-hash">#</span>${{esc(c.name)}}</div>`;
  }}
  if (vc.length) {{
    el.innerHTML+=`<div class="ch-section">Voice <span onclick="showCreateCh('voice')">+</span></div>`;
    for (const c of vc) {{
      const vm=c.voice_members||[];
      el.innerHTML+=`<div class="ch-item${{S.vcCh?.id===c.id?' active':''}}" onclick="joinVC(${{c.id}},'${{esc(c.name)}}')">🔊 ${{esc(c.name)}}${{vm.length?` <span style="font-size:11px;color:var(--green);margin-left:auto">${{vm.length}}</span>`:''}}</div>`;
    }}
  }}
}}

async function loadMembers() {{
  S.members = await api('GET',`/servers/${{S.curSrv.id}}/members`);
  const el=document.getElementById('mem-list'); el.innerHTML='';
  for (const m of S.members)
    el.innerHTML+=`<div class="mem-row">${{av(m.display_name[0].toUpperCase(),m.avatar_color,32,12)}}<span class="mem-name">${{esc(m.display_name)}}</span><div class="online-dot"></div></div>`;
}}

function toggleMembers() {{
  const p=document.getElementById('members-panel');
  p.classList.toggle('hidden');
}}

// ═══════════════════════════════════════════════════════════
// TEXT CHANNELS
// ═══════════════════════════════════════════════════════════
async function selectCh(id) {{
  const ch=S.channels.find(c=>c.id===id); if(!ch||ch.type==='voice') return;
  S.curCh=ch; S.curDmId=null; S.curDmUser=null;
  document.getElementById('ch-name-h').textContent=ch.name;
  document.getElementById('ch-hash').textContent='#';
  document.getElementById('ch-topic').textContent='#'+ch.name;
  document.getElementById('msg-in').placeholder='Message #'+ch.name;
  document.getElementById('call-hdr-btn').style.display='none';
  showView('channel'); renderChannels();
  if (S.chWs) S.chWs.close();
  const ws=new WebSocket(`${{WS_BASE}}/ws/channel/${{ch.id}}?token=${{S.token}}`);
  ws.onmessage=e=>{{ const d=JSON.parse(e.data); if(d.type==='new_message') appendMsg(d.message); }};
  S.chWs=ws;
  const msgs=await api('GET',`/channels/${{ch.id}}/messages`);
  const c=document.getElementById('msgs'); c.innerHTML='';
  for (const m of msgs) appendMsg(m,false);
  c.scrollTop=c.scrollHeight;
}}

function appendMsg(msg, scroll=true) {{
  const c=document.getElementById('msgs');
  const d=document.createElement('div'); d.className='mg';
  d.innerHTML=`${{av(msg.display_name[0].toUpperCase(),msg.avatar_color)}}<div class="mb"><div class="mm"><span class="mauth" style="color:${{msg.avatar_color}}">${{esc(msg.display_name)}}</span><span class="mtime">${{tfmt(msg.created_at)}}</span></div><div class="mc">${{esc(msg.content)}}</div></div>`;
  c.appendChild(d);
  if (scroll) c.scrollTop=c.scrollHeight;
}}

async function send() {{
  const inp=document.getElementById('msg-in');
  const content=inp.value.trim(); if(!content) return;
  inp.value='';
  try {{
    if (S.curDmId) {{
      await api('POST',`/dms/${{S.curDmId}}/messages`,{{content}});
      const msgs=await api('GET',`/dms/${{S.curDmId}}/messages`);
      const c=document.getElementById('msgs'); c.innerHTML='';
      for(const m of msgs) appendMsg(m,false); c.scrollTop=c.scrollHeight;
    }} else if (S.curCh) {{
      await api('POST',`/channels/${{S.curCh.id}}/messages`,{{content}});
    }}
  }} catch(e) {{ toast(e.message,'err'); inp.value=content; }}
}}

function handleKey(e) {{ if(e.key==='Enter'&&!e.shiftKey){{ e.preventDefault(); send(); }} }}

// ═══════════════════════════════════════════════════════════
// DIRECT MESSAGES
// ═══════════════════════════════════════════════════════════
async function showDMs() {{
  document.getElementById('ch-sidebar').style.display='none';
  document.getElementById('dm-sidebar').classList.remove('hidden');
  S.curSrv=null; renderServerIcons();
  await loadDMs();
  showView('friends'); renderFriends('all');
}}

async function loadDMs() {{
  S.dms=await api('GET','/dms');
  const el=document.getElementById('dm-list'); el.innerHTML='';
  for (const dm of S.dms) {{
    const o=dm.other_user;
    const d=document.createElement('div');
    d.className='dm-item'+(S.curDmId===dm.id?' active':'');
    d.innerHTML=`${{av(o.display_name[0].toUpperCase(),o.avatar_color,32,12)}}
      <span style="font-size:13px;font-weight:600;flex:1">${{esc(o.display_name)}}</span>
      <span class="call-btn" title="Call ${{esc(o.display_name)}}" onclick="event.stopPropagation();callUser('${{esc(o.username)}}')">📞</span>`;
    d.onclick=()=>openDm(dm.id,o);
    el.appendChild(d);
  }}
}}

async function openDm(dmId, other) {{
  S.curDmId=dmId; S.curCh=null; S.curDmUser=other;
  document.getElementById('ch-name-h').textContent=other.display_name;
  document.getElementById('ch-hash').textContent='@';
  document.getElementById('ch-topic').textContent='Direct message';
  document.getElementById('msg-in').placeholder='Message '+other.display_name;
  document.getElementById('call-hdr-btn').style.display='flex';
  showView('channel'); await loadDMs();
  const msgs=await api('GET',`/dms/${{dmId}}/messages`);
  const c=document.getElementById('msgs'); c.innerHTML='';
  for(const m of msgs) appendMsg(m,false); c.scrollTop=c.scrollHeight;
}}

function callCurrentDmUser() {{
  if (S.curDmUser) callUser(S.curDmUser.username);
}}

// ═══════════════════════════════════════════════════════════
// FRIENDS
// ═══════════════════════════════════════════════════════════
async function renderFriends(tab='all') {{
  const friends=await api('GET','/friends');
  const el=document.getElementById('fcontent'); el.innerHTML='';
  if (tab==='add') {{
    el.innerHTML=`<h3 style="margin-bottom:12px;font-weight:700">Add Friend</h3>
      <div class="add-form"><input id="fadd-un" placeholder="Username" onkeydown="if(event.key==='Enter')addFriend()"/><button class="btn btn-primary btn-sm" onclick="addFriend()">Send Request</button></div>
      <div id="fadd-st" style="font-size:12px"></div>`; return;
  }}
  const list = tab==='pending' ? friends.filter(f=>f.status==='pending') : friends.filter(f=>f.status==='accepted');
  if (!list.length) {{ el.innerHTML=`<div style="color:var(--text3);text-align:center;padding:32px 0;font-size:14px">${{tab==='pending'?'No pending requests':'No friends yet'}}</div>`; return; }}
  for (const f of list) {{
    const o=f.other; const d=document.createElement('div'); d.className='fr-row';
    let acts='';
    if (f.status==='pending'&&!f.is_requester)
      acts=`<button class="btn btn-green btn-xs" onclick="acceptFriend(${{f.id}})">Accept</button><button class="btn btn-red btn-xs" onclick="removeFriend(${{f.id}})">Decline</button>`;
    else if (f.status==='accepted')
      acts=`<button class="btn btn-ghost btn-xs" onclick="openDmByUser('${{esc(o.username)}}')">💬</button><button class="btn btn-green btn-xs" onclick="callUser('${{esc(o.username)}}')">📞</button><button class="btn btn-red btn-xs" onclick="removeFriend(${{f.id}})">✕</button>`;
    else
      acts=`<span style="color:var(--text3);font-size:11px">Pending…</span>`;
    d.innerHTML=`${{av(o.display_name[0].toUpperCase(),o.avatar_color)}}<div class="fr-info"><div class="fr-name">${{esc(o.display_name)}}</div><div class="fr-status">${{f.status==='pending'?(f.is_requester?'Outgoing':'Incoming'):'Online'}}</div></div><div class="fr-acts">${{acts}}</div>`;
    el.appendChild(d);
  }}
}}

function fTab(tab,btn) {{
  document.querySelectorAll('.ftab').forEach(b=>b.classList.remove('active'));
  btn.classList.add('active'); renderFriends(tab);
}}

async function addFriend() {{
  const un=document.getElementById('fadd-un').value.trim();
  const st=document.getElementById('fadd-st'); if(!un) return;
  try{{ await api('POST','/friends/request',{{username:un}}); st.style.color='var(--green)'; st.textContent='Request sent!'; document.getElementById('fadd-un').value=''; }}
  catch(e){{ st.style.color='var(--red)'; st.textContent=e.message; }}
}}
async function acceptFriend(id){{ await api('POST',`/friends/${{id}}/accept`); renderFriends('pending'); }}
async function removeFriend(id){{ await api('DELETE',`/friends/${{id}}`); renderFriends('all'); }}
async function openDmByUser(un) {{
  const d=await api('POST','/dms/open',{{username:un}});
  await showDMs(); await loadDMs();
  const dm=S.dms.find(x=>x.id===d.dm_id);
  if (dm) openDm(dm.id, dm.other_user);
}}

// ═══════════════════════════════════════════════════════════
// GROUP VOICE CHANNELS
// ═══════════════════════════════════════════════════════════
const ICE={{iceServers:[{{urls:'stun:stun.l.google.com:19302'}},{{urls:'stun:stun1.l.google.com:19302'}}]}};

async function joinVC(chId, name) {{
  if (S.vcCh?.id===chId) return;
  if (S.vcCh) leaveVC();
  S.vcCh=S.channels.find(c=>c.id===chId);
  document.getElementById('vc-name').textContent=name;
  document.getElementById('vc-status').textContent='Connecting…';
  showView('voice'); renderChannels();
  try{{ S.localStream=await navigator.mediaDevices.getUserMedia({{audio:true,video:false}}); }}
  catch{{ S.localStream=null; document.getElementById('vc-status').textContent='⚠️ Mic denied'; }}
  S.vcParts={{}};
  S.vcParts[S.user.id]={{id:S.user.id,display_name:S.user.display_name,avatar_color:S.user.avatar_color,muted:S.muted}};
  renderVCParts();
  const ws=new WebSocket(`${{WS_BASE}}/ws/voice/${{chId}}?token=${{S.token}}`);
  ws.onopen=()=>document.getElementById('vc-status').textContent='✅ Connected';
  ws.onmessage=async e=>{{
    const msg=JSON.parse(e.data);
    if(msg.type==='voice_peer_exists'){{ S.vcParts[msg.userId]=msg.userInfo; renderVCParts(); await vcOffer(msg.userId); }}
    else if(msg.type==='voice_user_joined'){{ S.vcParts[msg.userId]=msg.userInfo; renderVCParts(); }}
    else if(msg.type==='voice_user_left'){{ delete S.vcParts[msg.userId]; if(S.vcPeers[msg.userId]){{S.vcPeers[msg.userId].close();delete S.vcPeers[msg.userId];}} renderVCParts(); }}
    else if(msg.type==='voice_signal') await vcSignal(msg.fromUserId,msg.signal);
  }};
  ws.onclose=()=>document.getElementById('vc-status').textContent='Disconnected';
  S.vcWs=ws;
}}

async function vcOffer(pid) {{
  const pc=vcPC(pid); const o=await pc.createOffer(); await pc.setLocalDescription(o);
  S.vcWs?.send(JSON.stringify({{type:'voice_signal',toUserId:pid,signal:{{type:'offer',sdp:o.sdp}}}}));
}}
function vcPC(pid) {{
  if(S.vcPeers[pid]) S.vcPeers[pid].close();
  const pc=new RTCPeerConnection(ICE); S.vcPeers[pid]=pc;
  if(S.localStream) for(const t of S.localStream.getTracks()) pc.addTrack(t,S.localStream);
  pc.onicecandidate=e=>{{ if(e.candidate) S.vcWs?.send(JSON.stringify({{type:'voice_signal',toUserId:pid,signal:{{type:'candidate',candidate:e.candidate}}}})); }};
  pc.ontrack=e=>{{ const a=new Audio(); a.srcObject=e.streams[0]; if(!S.deafened) a.play().catch(()=>{{}}); }};
  return pc;
}}
async function vcSignal(from, sig) {{
  if(sig.type==='offer'){{ const pc=vcPC(from); await pc.setRemoteDescription({{type:'offer',sdp:sig.sdp}}); const ans=await pc.createAnswer(); await pc.setLocalDescription(ans); S.vcWs?.send(JSON.stringify({{type:'voice_signal',toUserId:from,signal:{{type:'answer',sdp:ans.sdp}}}})); }}
  else if(sig.type==='answer'){{ const pc=S.vcPeers[from]; if(pc) await pc.setRemoteDescription({{type:'answer',sdp:sig.sdp}}); }}
  else if(sig.type==='candidate'){{ const pc=S.vcPeers[from]; if(pc) await pc.addIceCandidate(sig.candidate).catch(()=>{{}}); }}
}}
function leaveVC() {{
  if(S.vcWs){{S.vcWs.close();S.vcWs=null;}}
  if(S.localStream){{S.localStream.getTracks().forEach(t=>t.stop());S.localStream=null;}}
  for(const pc of Object.values(S.vcPeers)) pc.close(); S.vcPeers={{}};
  S.vcParts={{}}; S.vcCh=null; renderChannels(); showView('welcome');
}}
function toggleMute() {{
  S.muted=!S.muted;
  if(S.localStream) S.localStream.getAudioTracks().forEach(t=>t.enabled=!S.muted);
  const btn=document.getElementById('vc-mute');
  btn.textContent=S.muted?'🔇':'🎤'; btn.className=S.muted?'vc-btn muted':'vc-btn def';
  if(S.vcParts[S.user.id]) S.vcParts[S.user.id].muted=S.muted;
  renderVCParts();
}}
function toggleDeafen() {{
  S.deafened=!S.deafened;
  const btn=document.getElementById('vc-deaf');
  btn.textContent=S.deafened?'🔇':'🔊'; btn.className=S.deafened?'vc-btn muted':'vc-btn def';
}}
function renderVCParts() {{
  const el=document.getElementById('vc-parts'); el.innerHTML='';
  for(const[,p] of Object.entries(S.vcParts))
    el.innerHTML+=`<div class="vc-part"><div class="vc-av${{p.muted?' muted':''}}" style="background:${{p.avatar_color}}">${{p.display_name[0].toUpperCase()}}</div><div class="vc-name">${{esc(p.display_name)}}</div></div>`;
}}

// ═══════════════════════════════════════════════════════════
// DIRECT CALLING  (1-on-1 WebRTC)
// ═══════════════════════════════════════════════════════════
async function callUser(username) {{
  if (S.callActive) {{ toast('Already in a call','err'); return; }}
  try {{
    const r=await api('POST','/call/ring',{{username}});
    S.callId=r.callId; S.callRole='caller';
    // Overlay is shown via the WS event 'call_ringing' that server sends back
  }} catch(e) {{ toast(e.message,'err'); }}
}}

async function acceptCall() {{
  if (!S.callId) return;
  clearTimeout(S.ringTimeout); stopRing();
  try {{
    await api('POST',`/call/accept/${{S.callId}}`);
    hideCallOverlay();
    startActiveCall(S.callId, null);
  }} catch(e) {{ toast(e.message,'err'); }}
}}

async function rejectCall() {{
  if (!S.callId) return;
  clearTimeout(S.ringTimeout); stopRing();
  try {{ await api('POST',`/call/reject/${{S.callId}}`); }} catch {{}}
  hideCallOverlay();
  S.callId=null; S.callRole=null;
}}

async function hangup() {{
  if (!S.callId) return;
  try {{ await api('POST',`/call/reject/${{S.callId}}`); }} catch {{}}
  endActiveCall();
}}

async function startActiveCall(callId, otherUser) {{
  S.callActive=true; S.callId=callId;
  // Acquire mic
  try {{
    S.callStream=await navigator.mediaDevices.getUserMedia({{audio:true,video:false}});
  }} catch {{
    S.callStream=null; toast('⚠️ Mic access denied','err');
  }}
  // Connect to call WS relay
  const ws=new WebSocket(`${{WS_BASE}}/ws/call/${{callId}}?token=${{S.token}}`);
  S.callWs=ws;
  ws.onopen=()=>console.log('[call] WS open');
  ws.onmessage=async e=>{{
    const msg=JSON.parse(e.data);
    if(msg.type==='call_peer_ready'){{
      S.callPeerId=msg.peerId;
      if(S.callRole==='caller') await callOffer(msg.peerId);
    }}
    if(msg.type==='call_signal') await callSignal(msg.fromUserId,msg.signal);
    if(msg.type==='call_ended'){{ endActiveCall(); toast('📞 Call ended','info'); }}
  }};
  ws.onclose=()=>{{
    if(S.callActive){{ endActiveCall(); toast('📞 Call ended','info'); }}
  }};

  // Show green call bar
  const bar=document.getElementById('call-bar');
  const name=otherUser?.display_name || (S.callRole==='callee' ? 'Caller' : 'Callee');
  document.getElementById('cb-name').textContent='In call with '+name;
  bar.classList.add('show');
  // Timer
  S.callStartTime=Date.now();
  S.callTimer=setInterval(()=>{{
    const sec=Math.floor((Date.now()-S.callStartTime)/1000);
    document.getElementById('cb-dur').textContent=secFmt(sec);
  }},1000);
}}

function endActiveCall() {{
  if (S.callWs) {{ S.callWs.close(); S.callWs=null; }}
  if (S.callStream) {{ S.callStream.getTracks().forEach(t=>t.stop()); S.callStream=null; }}
  for(const pc of Object.values(S.callPeers)) pc.close(); S.callPeers={{}};
  clearInterval(S.callTimer); S.callTimer=null;
  document.getElementById('call-bar').classList.remove('show');
  S.callActive=false; S.callId=null; S.callRole=null; S.callPeerId=null;
}}

async function callOffer(pid) {{
  const pc=callPC(pid); const o=await pc.createOffer(); await pc.setLocalDescription(o);
  S.callWs?.send(JSON.stringify({{type:'call_signal',signal:{{type:'offer',sdp:o.sdp}}}}));
}}
function callPC(pid) {{
  if(S.callPeers[pid]) S.callPeers[pid].close();
  const pc=new RTCPeerConnection(ICE); S.callPeers[pid]=pc;
  if(S.callStream) for(const t of S.callStream.getTracks()) pc.addTrack(t,S.callStream);
  pc.onicecandidate=e=>{{ if(e.candidate) S.callWs?.send(JSON.stringify({{type:'call_signal',signal:{{type:'candidate',candidate:e.candidate}}}})); }};
  pc.ontrack=e=>{{ const a=new Audio(); a.srcObject=e.streams[0]; a.play().catch(()=>{{}}); }};
  return pc;
}}
async function callSignal(fromId, sig) {{
  if(!S.callPeers[fromId] && sig.type==='offer') {{
    const pc=callPC(fromId); await pc.setRemoteDescription({{type:'offer',sdp:sig.sdp}});
    const ans=await pc.createAnswer(); await pc.setLocalDescription(ans);
    S.callWs?.send(JSON.stringify({{type:'call_signal',signal:{{type:'answer',sdp:ans.sdp}}}}));
  }} else if(sig.type==='answer'){{
    const pc=Object.values(S.callPeers)[0]; if(pc) await pc.setRemoteDescription({{type:'answer',sdp:sig.sdp}});
  }} else if(sig.type==='candidate'){{
    const pc=Object.values(S.callPeers)[0]; if(pc) await pc.addIceCandidate(sig.candidate).catch(()=>{{}});
  }}
}}
function toggleCallMute() {{
  S.callMuted=!S.callMuted;
  if(S.callStream) S.callStream.getAudioTracks().forEach(t=>t.enabled=!S.callMuted);
  document.getElementById('cb-mute').textContent=S.callMuted?'🔇 Unmute':'🎤 Mute';
}}

// ═══════════════════════════════════════════════════════════
// CALL OVERLAY
// ═══════════════════════════════════════════════════════════
function showCallOverlay(dir, user) {{
  const ov=document.getElementById('call-overlay');
  document.getElementById('co-av').style.background = user.avatar_color||'var(--accent)';
  document.getElementById('co-av').textContent = (user.display_name||'?')[0].toUpperCase();
  document.getElementById('co-name').textContent = user.display_name||user.username;
  const tag=document.getElementById('co-tag');
  const sub=document.getElementById('co-sub');
  const btns=document.getElementById('co-btns');
  if (dir==='incoming') {{
    tag.textContent='Incoming Call'; tag.className='co-tag ringing';
    sub.textContent='is calling you…';
    btns.innerHTML=`<button class="btn btn-green co-ring" style="flex:1" onclick="acceptCall()">📞 Accept</button><button class="btn btn-red" style="flex:1" onclick="rejectCall()">📵 Decline</button>`;
    // Ring countdown
    let t=45;
    document.getElementById('co-timer').textContent=`Ringing… ${{t}}s`;
    const iv=setInterval(()=>{{
      if(!S.callId){{clearInterval(iv);return;}}
      t--; document.getElementById('co-timer').textContent=`Ringing… ${{t}}s`;
      if(t<=0) clearInterval(iv);
    }},1000);
  }} else {{
    tag.textContent='Calling…'; tag.className='co-tag outgoing';
    sub.textContent='Waiting for answer…';
    btns.innerHTML=`<button class="btn btn-red" style="flex:1" onclick="rejectCall()">📵 Cancel</button>`;
    document.getElementById('co-timer').textContent='';
  }}
  ov.classList.add('show');
}}

function hideCallOverlay() {{
  document.getElementById('call-overlay').classList.remove('show');
}}

// ═══════════════════════════════════════════════════════════
// VIEWS
// ═══════════════════════════════════════════════════════════
function showView(v) {{
  S.view=v;
  document.getElementById('welcome').style.display      = v==='welcome'?'flex':'none';
  document.getElementById('ch-view').style.display      = v==='channel'?'flex':'none';
  document.getElementById('voice-panel').style.display  = v==='voice'?'flex':'none';
  document.getElementById('friends-panel').style.display= v==='friends'?'flex':'none';
  if(v==='friends') renderFriends('all');
}}

// ═══════════════════════════════════════════════════════════
// MODALS
// ═══════════════════════════════════════════════════════════
function showModal(title, bodyHtml, actions) {{
  document.getElementById('m-title').textContent=title;
  document.getElementById('m-body').innerHTML=bodyHtml;
  const el=document.getElementById('m-acts'); el.innerHTML='';
  for(const a of actions){{
    const b=document.createElement('button'); b.className=`btn ${{a.cls||'btn-primary'}} btn-sm`;
    b.textContent=a.label; b.onclick=a.fn; el.appendChild(b);
  }}
  document.getElementById('modal-ov').classList.remove('hidden');
}}
function closeModal(){{ document.getElementById('modal-ov').classList.add('hidden'); }}

function showCreateServer(){{
  showModal('Create Server','<label>Server Name</label><input id="ns-name" placeholder="My Server" style="width:100%;padding:9px 12px;background:var(--bg3);color:var(--text);border:1px solid var(--border);border-radius:8px;font-size:13px;font-family:var(--f);margin-top:6px">',[
    {{label:'Cancel',cls:'btn-ghost',fn:closeModal}},
    {{label:'Create',fn:async()=>{{const n=document.getElementById('ns-name').value.trim();if(!n) return;const s=await api('POST','/servers',{{name:n}});closeModal();await loadServers();selectServer(s);}}}},
  ]);
}}

function showCreateCh(type){{
  showModal(`Create ${{type==='text'?'Text':'Voice'}} Channel`,'<label>Channel Name</label><input id="nc-name" placeholder="'+(type==='text'?'new-channel':'New VC')+'" style="width:100%;padding:9px 12px;background:var(--bg3);color:var(--text);border:1px solid var(--border);border-radius:8px;font-size:13px;font-family:var(--f);margin-top:6px">',[
    {{label:'Cancel',cls:'btn-ghost',fn:closeModal}},
    {{label:'Create',fn:async()=>{{const n=document.getElementById('nc-name').value.trim();if(!n) return;await api('POST',`/servers/${{S.curSrv.id}}/channels`,{{name:n,type}});closeModal();await loadChannels();}}}},
  ]);
}}

// ═══════════════════════════════════════════════════════════
// BOOT
// ═══════════════════════════════════════════════════════════
document.addEventListener('keydown',e=>{{if(e.key==='Escape')closeModal();}});

// Restore saved server on startup
(function boot() {{
  const savedSrv = localStorage.getItem('chord_server');
  if (savedSrv) {{
    fetch(savedSrv+'/health', {{signal:AbortSignal.timeout(3000)}})
      .then(r=>r.json()).then(data=>{{
        setServer(savedSrv, data.server||savedSrv);
        S.token=localStorage.getItem('chord_token');
        if (S.token) tryAutoLogin();
        else showAuth();
      }}).catch(()=>showSwitcher());
  }} else {{
    showSwitcher();
  }}
}})();
</script>
</body>
</html>"""

# ── pywebview window ──────────────────────────────────────────────────────────
def run_app():
    try:
        import webview
    except ImportError:
        print("\n❌  pywebview not installed.  Run:  pip install pywebview\n")
        sys.exit(1)

    default_api = f"http://localhost:{LOCAL_PORT}/api"
    default_ws  = f"ws://localhost:{LOCAL_PORT}"
    html        = build_html(default_api, default_ws)

    class JsAPI:
        """Exposed to JS via window.pywebview.api.*"""
        def get_version(self):
            return "2.0.0"

        def open_url(self, url):
            import webbrowser
            webbrowser.open(url)

        def show_notification(self, title, body):
            """Fallback for platforms where Web Notifications don't work."""
            # On Windows we can try a system tray toast via plyer (optional dep)
            try:
                from plyer import notification  # type: ignore
                notification.notify(title=title, message=body, app_name='Chord', timeout=5)
            except Exception:
                pass  # silent fallback — web notification already attempted in JS

    webview.create_window(
        title            = "Chord",
        html             = html,
        width            = 1300,
        height           = 820,
        min_size         = (960, 640),
        resizable        = True,
        frameless        = False,
        easy_drag        = False,
        js_api           = JsAPI(),
        background_color = '#0d0e10',
    )
    webview.start(debug=False)
    stop_local_backend()

# ── Entry point ───────────────────────────────────────────────────────────────
def main():
    print("=" * 52)
    print("  ⚡ Chord v2 — Desktop Client")
    print("=" * 52)

    # Try to start the local backend (optional — user can connect to remote)
    server_js = resource_path('server.js')
    if os.path.exists(server_js):
        print(f"[chord] Found server.js — attempting local backend start…")
        ok = start_local_backend()
        if not ok:
            print("[chord] Local backend not started — user can pick a remote server.")
    else:
        print("[chord] No server.js found — server-switcher only mode.")

    run_app()


if __name__ == '__main__':
    main()
