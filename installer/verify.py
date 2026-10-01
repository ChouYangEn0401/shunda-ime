"""Post-install check, run by the installer as the signed-in user.

Talks to PIMELauncher exactly like an application's input method DLL does
and types a few keys; succeeds only if the SmartIME backend answers and
converts zhuyin to Chinese. The launcher may still be starting, so retry.
"""

import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent  # <PIME>\smartime\installer
sys.path.insert(0, str(HERE.parent / "app" / "src"))

from smartime.devtools.pime_probe import main  # noqa: E402

rc = 1
for attempt in range(6):
    rc = main(["--keys", "ji3ap7", "--require-conversion"])
    if rc == 0:
        break
    time.sleep(1.5)
sys.exit(rc)
