r"""Open the 順打輸入法 settings window.

Started by the tray menu (設定…), by Windows' language settings (選項, via
ime.json "configTool"), and by the Start-menu shortcut, normally as
``<PIME>\smartime\runtime\pythonw.exe settings.py`` (no console window).
Same source lookup as server.py.
"""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

for root in (HERE / "app", HERE.parent):
    if (root / "src" / "smartime" / "__init__.py").is_file():
        sys.path.insert(0, str(root / "src"))
        break
else:
    sys.stderr.write("smartime: cannot find the application sources\n")
    sys.exit(2)

from smartime.settings.__main__ import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
