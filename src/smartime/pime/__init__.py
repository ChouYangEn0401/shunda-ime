"""PIME backend: speaks PIME's line-based JSON protocol over stdin/stdout.

PIME (https://github.com/EasyIME/PIME) provides the Windows TSF text service
(C++ DLL) and a launcher that spawns backends listed in ``backends.json``.
We register our own backend so the engine runs on our own Python runtime.
"""
