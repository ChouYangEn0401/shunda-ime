"""Screenshot the settings page with sample data, in headless Edge, and
report JavaScript errors (for checking UI changes without touching the
user's own settings or memory).

    python -m smartime.devtools.settings_shot out_dir [--view dict] [--dark] [--width 1280]

Runs the real settings server on a throwaway data folder.
"""

from __future__ import annotations

import argparse
import os
import secrets
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

EDGE = [Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Microsoft/Edge/Application/msedge.exe",
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Microsoft/Edge/Application/msedge.exe"]


def sample_data(app) -> None:
    u = app.user
    for phrase, reading, origin, n in [("逗號", "ㄉㄡˋ-ㄏㄠˋ", "fix", 1), ("我們", "ㄨㄛˇ-ㄇㄣ˙", "pick", 5),
                                       ("的時候", "ㄉㄜ˙-ㄕˊ-ㄏㄡˋ", "tab", 2), ("候選", "ㄏㄡˋ-ㄒㄩㄢˇ", "fix", 3)]:
        for _ in range(n):
            u.learn(phrase, reading, "zh", origin)
    u.learn("deadline", "", "en", "pick")
    u.add("陳怡君", "ㄔㄣˊ-ㄧˊ-ㄐㄩㄣ", "zh", "朋友")
    u.add("順打輸入法", "ㄕㄨㄣˋ-ㄉㄚˇ-ㄕㄨ-ㄖㄨˋ-ㄈㄚˇ", "zh", "專案術語")
    u.block("鬥號", "ㄉㄡˋ-ㄏㄠˋ")
    u.add_snippet("範例市範例區示範路 100 號\n（請寄到這裡，謝謝）", "我的地址", "addr", "地址")
    u.add_snippet("感謝您的來信！我們已經收到，會在兩個工作天內回覆您。", "", "thanks", "客服")
    # enough to show how the list holds up when it gets long (分類, usage,
    # a keyword two snippets share)
    more = [
        ("公司地址", "addr", "地址", "範例市信義區示範大道 5 號 12 樓\n範例科技股份有限公司"),
        ("退貨流程", "return", "客服", "您好，退貨請在收到商品 7 天內申請：\n1. 登入會員中心\n2. 選擇訂單並按「申請退貨」"),
        ("出貨時間", "ship", "客服", "訂單成立後 1–2 個工作天出貨，出貨後會再寄通知信給您。"),
        ("營業時間", "hours", "客服", "客服時間：週一至週五 9:00–18:00（國定假日休息）。"),
        ("", "sorry", "客服", "很抱歉造成您的不便，我們會儘快為您處理。"),
        ("Email 簽名", "sig", "簽名", "陳怡君\n產品設計部 · 範例科技\n(02) 1234-5678"),
        ("英文簽名", "sigen", "簽名", "Best regards,\nYi-Chun Chen"),
        ("", "meet", "工作", "我們約下週二下午兩點開會可以嗎？會議連結稍後寄給您。"),
        ("週報開頭", "weekly", "工作", "本週進度：\n- 完成：\n- 進行中：\n- 卡住的事："),
        ("", "ok", "", "好的，沒問題！"),
        ("", "brb", "", "我先離開一下，馬上回來。"),
        ("匯款帳號", "bank", "", "範例銀行（代碼 000）帳號 0000-000-000000"),
    ]
    for title, keyword, category, body in more:
        u.add_snippet(body, title, keyword, category)
    for i in range(1, 25):
        u.add_snippet(f"範例片語第 {i} 則：常用的一段話放在這裡。", "", f"t{i:02d}", "範例" if i % 3 else "")
    rows = u.snippets()
    for r, n in zip(rows, [6, 14, 0, 3, 9, 1, 0, 22, 0, 2, 0, 5, 1]):
        for _ in range(n):
            u.used_snippet(r["id"])
    u.add_custom_symbols("(=^・ω・^=)\n( ͡° ͜ʖ ͡°)\n★\n♥")


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("out")
    ap.add_argument("--view", default="dict")
    ap.add_argument("--dark", action="store_true")
    ap.add_argument("--width", type=int, default=1280)
    ap.add_argument("--height", type=int, default=1100)
    ap.add_argument("--set", action="append", default=[], metavar="KEY=VALUE",
                    help="a setting for the screenshot (JSON value), e.g. --set punct_style=\"fullwidth\"")
    args = ap.parse_args()
    edge = next((p for p in EDGE if p.exists()), None)
    if edge is None:
        print("Edge not found")
        return 2
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["SMARTIME_USER_DIR"] = str(Path(tmp) / "user")
        from ..settings.api import SettingsApp, SettingsServer
        from ..voice import launch as voice_launch

        # --set voice_enabled=true started the real voice service (a global
        # keyboard hook, the model on the GPU) on the throwaway folder
        voice_launch.start = lambda: True
        app = SettingsApp()
        sample_data(app)
        if args.set:
            import json

            patch = {}
            for item in args.set:
                key, _, value = item.partition("=")
                try:
                    patch[key] = json.loads(value)
                except ValueError:
                    patch[key] = value
            app.save_config(patch)
        token = secrets.token_urlsafe(16)
        srv = SettingsServer(app, token)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        url = f"http://127.0.0.1:{srv.port}/?t={token}#{args.view}"
        shot = out / f"settings-{args.view}{'-dark' if args.dark else ''}.png"
        cmd = [str(edge), "--headless=new", "--disable-gpu", "--hide-scrollbars", f"--screenshot={shot}",
               f"--window-size={args.width},{args.height}", "--virtual-time-budget=5000",
               f"--user-data-dir={Path(tmp) / 'edge'}", "--enable-logging=stderr", "--v=0",
               "--no-first-run", "--disable-extensions",
               "--force-prefers-reduced-motion"]  # no half-finished switch animations in the shot
        if args.dark:
            cmd.append("--force-dark-mode")
            cmd.append("--blink-settings=preferredColorScheme=0")
        cmd.append(url)
        t0 = time.monotonic()
        proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=90)
        errors = [line for line in proc.stderr.splitlines()
                  if "CONSOLE" in line and ("Error" in line or "error" in line or "Uncaught" in line)]
        srv.shutdown()
        app.close()
        print(shot, f"({time.monotonic() - t0:.1f}s)")
        for line in errors:
            print("JS:", line)
        return 1 if errors or not shot.exists() else 0


if __name__ == "__main__":
    sys.exit(main())
