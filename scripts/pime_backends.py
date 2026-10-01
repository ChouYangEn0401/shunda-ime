"""Add or remove the 順打輸入法 entry in PIME's backends.json.

Run with any Python (the installer uses the bundled runtime):
    python pime_backends.py add    "C:\\Program Files (x86)\\PIME"
    python pime_backends.py remove "C:\\Program Files (x86)\\PIME"

PIME reads this file with jsoncpp, so it is written as UTF-8 *without* BOM.
A one-time backup (backends.json.smartime-backup) is kept next to it.
"""

import json
import shutil
import sys
from pathlib import Path

ENTRY = {
    "name": "smartime",
    "command": "smartime\\runtime\\python.exe",
    "workingDir": "smartime",
    "params": "server.py",
}


def main() -> int:
    if len(sys.argv) != 3 or sys.argv[1] not in ("add", "remove"):
        print(__doc__)
        return 2
    action, pime_dir = sys.argv[1], Path(sys.argv[2])
    path = pime_dir / "backends.json"
    backup = path.with_name("backends.json.smartime-backup")
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, list):
        print(f"unexpected format in {path}")
        return 1
    if not backup.exists():
        shutil.copy2(path, backup)
    data = [b for b in data if b.get("name") != ENTRY["name"]]
    if action == "add":
        data.append(ENTRY)
    path.write_text(json.dumps(data, indent=4, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"{action}: {path} now lists {[b.get('name') for b in data]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
