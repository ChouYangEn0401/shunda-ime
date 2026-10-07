"""順打輸入法 (Shunda IME): zhuyin/English mixed input without mode switching.

The Python package, the data folder (%APPDATA%\\SmartIME) and the PIME
backend folder keep the original code name "smartime", so a rename never
loses anyone's settings or memory.
"""

__version__ = "0.7.0"

# Product naming lives here only, so a rename touches one place (the IME
# manifest backend/input_methods/smartime/ime.json must match PRODUCT_NAME;
# tests/test_backend_files.py checks it).
PRODUCT_NAME = "順打輸入法"
PRODUCT_NAME_EN = "Shunda IME"
