"""Real typing test in Chromium text fields (Edge), like the input boxes of
VS Code, LINE, Teams, ChatGPT or claude.ai (all Chromium/Electron).

A local page with several kinds of fields is opened in an isolated Edge
window (temporary profile; the user's browser is not touched). The page
reports its field contents back to this script. Keys are sent with
SendInput, exactly like tsf_typing_test, with the same protections: waits
for 5 s of keyboard/mouse idle, stops at the first real key or click, backs
up and restores the user's memory and settings.

Fields
  ta      plain <textarea>
  ce      contenteditable <div> (rich chat editors)
  react   <textarea> whose script rewrites its value on every input event
          (framework-controlled inputs)
  cancel  contenteditable that interrupts the composition (blur + focus)
          once it is longer than 10 characters, like editors that re-render
          mid-composition — reproduces "the app ended the composition"

    python -m smartime.devtools.browser_typing_test
"""

from __future__ import annotations

import ctypes
import json
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from ctypes import wintypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import tsf_typing_test as tt
from ..settings.__main__ import _browser

TITLE = "SmartIME browser test"
TF_IPPMF_FORSESSION = 0x20000000
user32 = tt.user32

PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>""" + TITLE + """</title>
<style>
 body{font:20px "Microsoft JhengHei UI",sans-serif;margin:12px;background:#f5f6f8}
 #cap{font-size:15px;color:#333;white-space:pre-wrap;margin-bottom:8px}
 .f{display:block;width:96%;min-height:44px;margin:6px 0;padding:6px;border:2px solid #bbb;background:#fff;font:22px "Microsoft JhengHei UI"}
 .on{border-color:#2563eb}
 label{font-size:13px;color:#666}
</style></head><body>
<div id="cap">waiting</div>
<label>ta</label><textarea id="ta" class="f"></textarea>
<label>ce</label><div id="ce" class="f" contenteditable="true"></div>
<label>react</label><textarea id="react" class="f"></textarea>
<label>cancel</label><div id="cancel" class="f" contenteditable="true"></div>
<label>cancel_ta</label><textarea id="cancel_ta" class="f"></textarea>
<label>chat (Ctrl+Enter sends)</label><textarea id="chat" class="f"></textarea>
<script>
const ids = ["ta","ce","react","cancel","cancel_ta","chat"];
let sent = [];
const ev = [];
let target = "ta", interrupted = false;
function val(id){ const el=document.getElementById(id); return el.value!==undefined && el.tagName==="TEXTAREA" ? el.value : el.innerText.replace(/\\n$/,""); }
function report(){ const values={}, rects={}; ids.forEach(i=>{values[i]=val(i); const r=document.getElementById(i).getBoundingClientRect(); rects[i]=[r.left,r.top,r.width,r.height];});
  fetch("/report",{method:"POST",body:JSON.stringify({values,rects,dpr:devicePixelRatio,sent,events:ev.slice(-40),target})}).catch(()=>{}); }
document.getElementById("chat").addEventListener("keydown",e=>{
  if(e.key==="Enter" && e.ctrlKey){ e.preventDefault(); sent.push(e.target.value); e.target.value=""; ev.push("chat:sent"); report(); }});
ids.forEach(id=>{ const el=document.getElementById(id);
  ["compositionstart","compositionend"].forEach(t=>el.addEventListener(t,e=>{ev.push(id+":"+t+":"+(e.data||""));report();}));
  el.addEventListener("input",e=>{ if(id==="react"){ const v=el.value; el.value=v; }
    if(id.startsWith("cancel")) ev.push(id+":input:"+e.inputType+":"+(e.data||"")+" => "+val(id)); report(); });
  el.addEventListener("compositionupdate",e=>{
    if(id.startsWith("cancel") && !interrupted && (e.data||"").length>10){ interrupted=true; ev.push(id+":interrupt at «"+e.data+"»");
      el.blur(); setTimeout(()=>{ ev.push(id+":after-blur => "+val(id)); el.focus(); report(); },0); }
  });
});
async function poll(){
  try{ const r=await fetch("/cmd"); const c=await r.json();
    if(c.cmd==="prepare"){ target=c.target; interrupted=false; ev.length=0; sent=[];
      ids.forEach(i=>{const el=document.getElementById(i); if(el.tagName==="TEXTAREA") el.value=""; else el.innerHTML=""; el.classList.toggle("on", i===target);});
      document.getElementById("cap").textContent=c.caption; const el=document.getElementById(target); el.focus();
      fetch("/ack",{method:"POST",body:String(c.n)}); report(); }
  }catch(e){}
  setTimeout(poll,60);
}
poll(); report();
</script></body></html>"""


class _State:
    def __init__(self) -> None:
        self.cmd: dict = {}
        self.ack = -1
        self.report: dict = {}
        self.lock = threading.Lock()


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # quiet
        pass

    def _reply(self, body: bytes, ctype: str = "application/json") -> None:
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        st: _State = self.server.state
        if self.path.startswith("/cmd"):
            with st.lock:
                cmd, st.cmd = st.cmd, {}
            self._reply(json.dumps(cmd).encode())
        else:
            self._reply(PAGE.encode("utf-8"), "text/html; charset=utf-8")

    def do_POST(self):  # noqa: N802
        st: _State = self.server.state
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        with st.lock:
            if self.path == "/report":
                st.report = json.loads(body.decode("utf-8"))
            elif self.path == "/ack":
                st.ack = int(body)
        self._reply(b"{}")


def _find_window(title: str, timeout: float = 15.0) -> int:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        found = []

        @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        def cb(hwnd, _):
            buf = ctypes.create_unicode_buffer(256)
            user32.GetWindowTextW(hwnd, buf, 256)
            if buf.value.startswith(title) and user32.IsWindowVisible(hwnd):
                found.append(hwnd)
            return True

        user32.EnumWindows(cb, 0)
        if found:
            return found[0]
        time.sleep(0.3)
    return 0


def _title(hwnd: int) -> str:
    buf = ctypes.create_unicode_buffer(256)
    user32.GetWindowTextW(hwnd, buf, 256)
    return buf.value


def _focus(hwnd: int) -> bool:
    """Bring the page to the front. Windows' foreground lock only lets the
    process that produced the latest input switch windows, so if the plain
    attempt fails, inject F24 (a key no application uses) and try again."""
    for attempt in range(4):
        if _focus_once(hwnd):
            return True
        for up in (False, True):
            inp = tt.INPUT(type=tt.INPUT_KEYBOARD)
            inp.u.ki = tt.KEYBDINPUT(wVk=0x87, wScan=0, dwFlags=tt.KEYEVENTF_KEYUP if up else 0,  # VK_F24
                                     dwExtraInfo=tt.INJECTED_TAG)
            user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(tt.INPUT))
        tt.pump(0.2)
    return False


def _focus_once(hwnd: int) -> bool:
    fg = user32.GetForegroundWindow()
    fg_thread = user32.GetWindowThreadProcessId(fg, None)
    me = tt.kernel32.GetCurrentThreadId()
    attached = fg_thread and fg_thread != me and user32.AttachThreadInput(fg_thread, me, True)
    user32.ShowWindow(hwnd, 9)  # SW_RESTORE
    user32.BringWindowToTop(hwnd)
    user32.SetForegroundWindow(hwnd)
    if attached:
        user32.AttachThreadInput(fg_thread, me, False)
    tt.pump(0.3)
    return user32.GetForegroundWindow() == hwnd


def _render_widget(hwnd: int) -> int:
    """The child window that shows the page (its client origin = CSS 0,0)."""
    found = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(child, _):
        buf = ctypes.create_unicode_buffer(128)
        user32.GetClassNameW(child, buf, 128)
        if buf.value == "Chrome_RenderWidgetHostHWND":
            found.append(child)
        return True

    user32.EnumChildWindows(hwnd, cb, 0)
    return found[0] if found else hwnd


def _click(hwnd: int, css_x: float, css_y: float, dpr: float) -> None:
    pt = wintypes.POINT(int(css_x * dpr), int(css_y * dpr))
    user32.ClientToScreen(_render_widget(hwnd), ctypes.byref(pt))
    user32.SetCursorPos(pt.x, pt.y)
    for flag in (0x0002, 0x0004):  # MOUSEEVENTF_LEFTDOWN, LEFTUP
        inp = tt.INPUT(type=0)  # INPUT_MOUSE
        inp.u.mi = tt.MOUSEINPUT(dx=0, dy=0, mouseData=0, dwFlags=flag, time=0, dwExtraInfo=tt.INJECTED_TAG)
        user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(tt.INPUT))
    tt.pump(0.3)


# (field, script, expected or None = what the engine simulator produces)
SCENARIOS_PER_FIELD = [
    "ji3ap7{ENTER}",
    "su3cl3<",
    "ji3m/4python vu,3{ENTER}",
    "ji3a87{LEFT}{UP}2{ENTER}",
    "ao6u.3{TAB}{ENTER}",
    "ji3a87{ESC}j{ENTER}",
    # the user's report: long text, edits in the middle, then back to the end
    "b06c.4283tj x96k27y4b/6b06j6z83fm4u/ jp6k27jp4wu6{LEFT}{LEFT}{BS}{RIGHT}{RIGHT}ru.4cjo4y94vscodexu3ua04{ENTER}",
    # longer than 30 characters: automatic partial commit
    "b06c.4283tj x96k27y4b/6b06j6z83fm4u/ jp6k27jp4wu6ru.4cjo4y94vscodexu3ua04yjo4284k27t8 u4{ENTER}",
]
FIELDS = ["ta", "ce", "react"]


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    browser = _browser()
    if not browser:
        print("ABORT: Edge/Chrome not found")
        return 2
    only_interrupt = "--interrupt-only" in sys.argv[1:]
    cases = [] if only_interrupt else [(f, s, tt.expected_text(s)) for f in FIELDS for s in SCENARIOS_PER_FIELD]
    print("waiting until keyboard/mouse have been idle for 5 s ...")
    if not tt.wait_until_idle():
        print("ABORT: the computer is in use; try again later (no keys were sent)")
        return 2

    state = _State()
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    server.state = state
    threading.Thread(target=server.serve_forever, daemon=True).start()
    profile = tempfile.mkdtemp(prefix="smartime-edge-")
    url = f"http://127.0.0.1:{server.server_address[1]}/"
    proc = subprocess.Popen(browser + [f"--app={url}", f"--user-data-dir={profile}", "--no-first-run",
                                       "--no-default-browser-check", "--window-position=40,40",
                                       "--window-size=1150,760"])
    memory = tt.MemoryGuard()
    tt.ole32.CoInitializeEx(None, 0x2)
    mgr = tt.ProfileMgr()
    previous = mgr.active()
    tt.GUARD = tt.UserGuard()
    failures = 0
    hwnd = 0
    try:
        hwnd = _find_window(TITLE)
        if not hwnd or not _focus(hwnd):
            print("ABORT: could not bring the test page to the foreground; no keys were sent")
            return 2
        # --ms: compare with Microsoft Bopomofo (same keys, its own behaviour)
        clsid, prof = tt.PIME_CLSID, tt.PROFILE_GUID
        if "--ms" in sys.argv[1:]:
            clsid, prof = "{B115690A-EA02-48D5-A231-E3578D2FDF80}", "{B2F9C502-1742-11D4-9790-0080C882687E}"
        hr = mgr.activate(tt.TF_PROFILETYPE_INPUTPROCESSOR, 0x0404, tt.guid(clsid),
                          tt.guid(prof), None,
                          TF_IPPMF_FORSESSION | tt.TF_IPPMF_DONTCARECURRENTINPUTLANGUAGE)
        if hr != 0:
            print(f"FAIL: ActivateProfile returned {hr & 0xFFFFFFFF:#x}")
            return 1
        tt.pump(1.0)
        # switching the input method may flash Windows' input indicator,
        # which takes the foreground for a moment: bring the page back
        if not _focus(hwnd):
            print(f"ABORT: could not get the foreground back from {_title(user32.GetForegroundWindow())!r}")
            return 2

        def send(vk: int, up: bool) -> None:
            if tt.GUARD.user_input:
                raise tt.Aborted("you used the keyboard/mouse; stopped so we don't type over you")
            if user32.GetForegroundWindow() != hwnd:
                raise tt.Aborted("the test page lost the foreground to "
                                 f"{_title(user32.GetForegroundWindow())!r}; stopped sending keys")
            inp = tt.INPUT(type=tt.INPUT_KEYBOARD)
            flags = (tt.KEYEVENTF_KEYUP if up else 0) | (tt.KEYEVENTF_EXTENDEDKEY if vk in (0xA3, 0xA5) else 0)
            inp.u.ki = tt.KEYBDINPUT(wVk=vk, wScan=user32.MapVirtualKeyW(vk, 0), dwFlags=flags,
                                     dwExtraInfo=tt.INJECTED_TAG)
            user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(tt.INPUT))

        def tap(vk, shift=False, ctrl=False, alt=False):
            tt.tap_keys(send, vk, shift, ctrl, alt)

        def prepare(n: int, field: str, caption: str) -> None:
            with state.lock:
                state.cmd = {"cmd": "prepare", "n": n, "target": field, "caption": caption}
            end = time.monotonic() + 5
            while state.ack != n and time.monotonic() < end:
                tt.pump(0.05)
            tt.pump(0.2)

        for n, (field, script, expected) in enumerate(cases, 1):
            memory.rewind()
            prepare(n, field, f"{n}/{len(cases)}  [{field}]  keys: {script}\nexpected: {expected}\n"
                              "（智慧輸入法自動測試：碰鍵盤或滑鼠會立即停止）")
            tt.type_script(tap, script)
            tt.pump(0.5)
            got = state.report.get("values", {}).get(field, "")
            ok = got == expected
            failures += not ok
            label = script if len(script) <= 34 else script[:31] + "..."
            print(f"{'PASS' if ok else 'FAIL'}  {field:6} {label!r:36} -> {got!r}"
                  + ("" if ok else f"  (expected {expected!r})"))

        # The user ends the composition: the text must appear exactly once.
        n0 = len(cases) + 10
        if not only_interrupt:
            prepare(n0, "ta", "mouse click while composing: 我們 | click at the start | 你")
            tt.type_script(tap, "ji3ap7")
            tt.pump(0.3)
            rep = state.report
            x, y, w, h = rep["rects"]["ta"]
            _click(hwnd, x + 6, y + h / 2, rep.get("dpr", 1.0))
            tt.type_script(tap, "su3{ENTER}")
            tt.pump(0.5)
            got = state.report["values"]["ta"]
            ok = got.count("我們") == 1 and got.count("你") == 1
            failures += not ok
            print(f"{'PASS' if ok else 'FAIL'}  click  {'ji3ap7 <click> su3':36} -> {got!r}")

            prepare(n0 + 1, "chat", "Ctrl+Enter sends while composing: 我們 | Ctrl+Enter | 你")
            tt.type_script(tap, "ji3ap7{C-ENTER}su3{ENTER}")
            tt.pump(0.5)
            rep = state.report
            got, sent = rep["values"]["chat"], rep.get("sent", [])
            ok = got == "你" and sent == ["我們"]
            failures += not ok
            print(f"{'PASS' if ok else 'FAIL'}  chat   {'ji3ap7 Ctrl+Enter su3':36} -> field {got!r}, sent {sent!r}")

        # An editor that interrupts the composition: what stays in the field?
        script = "ji3ap7rup wu0dk3u3283b/6dj94k27vu jp6"
        for k, field in enumerate(("cancel", "cancel_ta")):
            prepare(len(cases) + 1 + k, field, f"interrupt test [{field}]  keys: {script}")
            tt.type_script(tap, script + "{ENTER}")
            tt.pump(0.6)
            rep = state.report
            print(f"INFO  {field} after an app interruption: {rep.get('values', {}).get(field, '')!r}")
            for e in rep.get("events", []):
                if e.startswith(field + ":"):
                    print("      ", e)
        return 1 if failures else 0
    except tt.Aborted as e:
        print("ABORT:", e)
        return 2
    finally:
        mgr.activate(previous.dwProfileType, previous.langid, previous.clsid, previous.guidProfile,
                     previous.hkl, TF_IPPMF_FORSESSION | tt.TF_IPPMF_DONTCARECURRENTINPUTLANGUAGE)
        tt.GUARD.close()
        memory.restore()
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True)
        server.shutdown()
        time.sleep(0.5)
        shutil.rmtree(profile, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
