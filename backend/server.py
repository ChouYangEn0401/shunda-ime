r"""PIME backend entry point for 順打輸入法 (Shunda IME).

PIMELauncher runs ``<PIME>\smartime\runtime\python.exe server.py`` with this
folder as the working directory. In development this folder is reached through
a directory junction, so resolve the real path before locating the sources.

Layouts supported:
  dev:      <repo>/backend/server.py   + <repo>/src/smartime
  deployed: <backend>/server.py        + <backend>/app/src/smartime
"""

import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
# Icons are handed to the TSF DLL inside every application, so keep the
# unresolved path (under Program Files) rather than the junction target.
ICON_DIR = Path(os.path.abspath(__file__)).parent / "input_methods" / "smartime" / "icons"

for root in (HERE / "app", HERE.parent):
    if (root / "src" / "smartime" / "__init__.py").is_file():
        sys.path.insert(0, str(root / "src"))
        break
else:
    sys.stderr.write("smartime: cannot find the application sources\n")
    sys.exit(2)

from smartime.pime.server import main  # noqa: E402

if __name__ == "__main__":
    main(icon_dir=ICON_DIR)
