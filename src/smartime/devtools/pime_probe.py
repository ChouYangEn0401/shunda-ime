"""Talk to the running PIMELauncher exactly like PIMETextService.dll does.

This exercises the real chain  launcher -> backend process -> engine  without
an application or the TSF DLL, so an installation can be verified end to end.

    python -m smartime.devtools.pime_probe            # our IME
    python -m smartime.devtools.pime_probe --guid {F80736AA-...}   # any PIME IME

Protocol (PIME 1.3, PIMEClient.cpp): message-mode named pipe
``\\\\.\\pipe\\<user>\\PIME\\Launcher``; each call is one TransactNamedPipe
with a JSON request carrying "method" and "seqNum"; the reply echoes seqNum.
"""

from __future__ import annotations

import argparse
import ctypes
import getpass
import json
import sys
import threading
from ctypes import wintypes

GUID = "{61AA71DB-BB8C-4C7D-9BD7-C324464DF341}"

GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
OPEN_EXISTING = 3
PIPE_READMODE_MESSAGE = 0x2
ERROR_MORE_DATA = 234
INVALID_HANDLE_VALUE = wintypes.HANDLE(-1).value

k32 = ctypes.WinDLL("kernel32", use_last_error=True)
k32.WaitNamedPipeW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD]
k32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
                            wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
k32.CreateFileW.restype = wintypes.HANDLE
k32.SetNamedPipeHandleState.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD), wintypes.LPVOID,
                                        wintypes.LPVOID]
k32.TransactNamedPipe.argtypes = [wintypes.HANDLE, wintypes.LPVOID, wintypes.DWORD, wintypes.LPVOID,
                                  wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), wintypes.LPVOID]
k32.ReadFile.argtypes = [wintypes.HANDLE, wintypes.LPVOID, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD),
                         wintypes.LPVOID]
k32.CloseHandle.argtypes = [wintypes.HANDLE]
k32.OpenThread.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
k32.OpenThread.restype = wintypes.HANDLE
k32.CancelSynchronousIo.argtypes = [wintypes.HANDLE]
THREAD_TERMINATE = 0x0001


class LauncherClient:
    def __init__(self, timeout_ms: int = 5000):
        name = rf"\\.\pipe\{getpass.getuser()}\PIME\Launcher"
        if not k32.WaitNamedPipeW(name, timeout_ms):
            raise ConnectionError(f"PIMELauncher pipe not available: {name} (error {ctypes.get_last_error()})")
        h = k32.CreateFileW(name, GENERIC_READ | GENERIC_WRITE, 0, None, OPEN_EXISTING, 0, None)
        if h == INVALID_HANDLE_VALUE:
            raise ConnectionError(f"cannot open {name} (error {ctypes.get_last_error()})")
        mode = wintypes.DWORD(PIPE_READMODE_MESSAGE)
        if not k32.SetNamedPipeHandleState(h, ctypes.byref(mode), None, None):
            raise ConnectionError(f"SetNamedPipeHandleState failed ({ctypes.get_last_error()})")
        self.handle = h
        self.seq = 0

    def call(self, method: str, timeout: float = 10.0, **fields) -> dict:
        """Send one request. PIMELauncher never answers an init for an unknown
        GUID, so the blocking pipe call runs in a worker thread with a timeout."""
        result: dict = {}

        def work() -> None:
            result["tid"] = threading.get_native_id()
            try:
                result["reply"] = self._call(method, **fields)
            except Exception as e:  # noqa: BLE001 - re-raised in the caller
                result["error"] = e

        t = threading.Thread(target=work, daemon=True)
        t.start()
        t.join(timeout)
        if t.is_alive():
            # Unblock the synchronous pipe call; otherwise CloseHandle would wait for it.
            th = k32.OpenThread(THREAD_TERMINATE, False, result.get("tid", 0))
            if th:
                k32.CancelSynchronousIo(th)
                k32.CloseHandle(th)
            t.join(2.0)
            raise TimeoutError(f"{method}: no reply from PIMELauncher within {timeout:.0f}s")
        if "error" in result:
            raise result["error"]
        return result["reply"]

    def _call(self, method: str, **fields) -> dict:
        self.seq += 1
        req = {"method": method, "seqNum": self.seq, **fields}
        data = json.dumps(req, ensure_ascii=False).encode("utf-8")
        buf = ctypes.create_string_buffer(4096)
        n = wintypes.DWORD()
        out = b""
        ok = k32.TransactNamedPipe(self.handle, data, len(data), buf, len(buf), ctypes.byref(n), None)
        out += buf.raw[: n.value]
        while not ok:
            if ctypes.get_last_error() != ERROR_MORE_DATA:
                raise ConnectionError(f"{method}: pipe error {ctypes.get_last_error()}")
            ok = k32.ReadFile(self.handle, buf, len(buf), ctypes.byref(n), None)
            out += buf.raw[: n.value]
        reply = json.loads(out.decode("utf-8"))
        if reply.get("seqNum") != self.seq:
            raise ValueError(f"{method}: seqNum mismatch in {reply}")
        return reply

    def close(self) -> None:
        k32.CloseHandle(self.handle)


def key_fields(ch: str) -> dict:
    return {"charCode": ord(ch), "keyCode": ord(ch.upper()) if ch.isalnum() else 0, "repeatCount": 1,
            "scanCode": 0, "isExtended": False, "keyStates": [0] * 256}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--guid", default=GUID)
    ap.add_argument("--keys", default="ji3ap7", help="characters to type after activation")
    ap.add_argument("--require-conversion", action="store_true",
                    help="fail unless the final composition contains non-ASCII text (i.e. Chinese)")
    args = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    try:
        c = LauncherClient()
    except ConnectionError as e:
        print("FAIL:", e)
        return 1
    try:
        # PIMELauncher maps lower-case GUIDs (PipeServer::initInputMethods)
        r = c.call("init", id=args.guid.lower(), isWindows8Above=True, isMetroApp=False, isUiLess=False,
                   isConsole=False)
        print("init       ->", r)
        if not r.get("success"):
            print("FAIL: backend rejected init")
            return 1
        r = c.call("onActivate", isKeyboardOpen=True)
        print("onActivate ->", r)
        if not r.get("success"):
            print("FAIL: onActivate")
            return 1
        last: dict = {}
        for ch in args.keys:
            f = c.call("filterKeyDown", **key_fields(ch))
            last = c.call("onKeyDown", **key_fields(ch)) if f.get("return") else f
            print(f"key {ch!r:5} ->", {k: v for k, v in last.items() if k not in ("success", "seqNum")})
            if not last.get("success"):
                print(f"FAIL: key {ch!r}")
                return 1
        c.call("onDeactivate")
        composition = last.get("compositionString", "")
        if args.require_conversion and (not composition or composition.isascii()):
            print(f"FAIL: expected converted Chinese text, got {composition!r}")
            return 1
        print("PASS")
        return 0
    except (TimeoutError, ConnectionError, ValueError) as e:
        print("FAIL:", e)
        return 1
    finally:
        c.close()


if __name__ == "__main__":
    sys.exit(main())
