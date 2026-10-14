# 上游同步之後要補跑的事

`origin/main` 有 **100 個 commit**（`bd15cad..08069a4`，另有新 tag `v0.6.0`）還沒落到本機 `main`。
這一格**沒有**把它們合併進來：`git merge` 不在這個 session 的允許指令裡，所以同步要由人完成。

> **先把上游合併進來，再照下面逐項跑。** 本機 `main` 零個獨有 commit、`origin/main` 一百個，
> 所以 `main` 本身可以直接快轉（`git merge --ff-only origin/main`）。

> **這一輪最重要的一件事：`uv` 已經被上游移除。** `uv.lock` 被刪掉（-971 行），
> 新增 `requirements.txt` 與 `requirements-voice.txt`，上游 `CONTRIBUTING.md` 明文寫
> 「**不要用 uv 或其他套件管理器**」。所以下面一律用 `.venv\Scripts\python`，
> 不要再跑 `uv sync` / `uv run`。

---

## 1. 重建開發環境（一定要先做這個）

```powershell
py -3.13 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
```

**預期看到**：pip 跑完沒有紅字；`.venv\Scripts\python --version` 顯示 `Python 3.13.x`。

**為什麼需要**：`pyproject.toml` 改了 25 行、`uv.lock` 整個被刪、新增 `requirements.txt`（33 行）
與 `requirements-voice.txt`（46 行）。套件來源和安裝方式都換了，舊的 `.venv` 或 uv 環境不算數。
語音輸入要用才裝 `requirements-voice.txt`（很大，選用）。

## 2. 重建詞庫

```powershell
.venv\Scripts\python tools\build_data.py
```

**預期看到**：產生 `data\generated\smartime.db`，大約 30 MB，沒有 traceback。

**為什麼需要**：`tools/build_data.py` 改了，而且這一批新增了整個「更多符號」符號庫——
`data/extra/symbols_extra.json`（+12675 行）、`tools/build_symbols_extra.py`（新檔）、
`src/smartime/engine/symbols_extra.py`（新檔）。不重建的話新符號庫不會進 db。

## 3. 跑測試

```powershell
.venv\Scripts\python -m pytest
```

**預期看到**：全綠。

**為什麼需要**：一百個 commit 動到 `src/**` 幾乎每一個模組（`engine/session.py` 一個檔就 758 行變動），
並新增約十五個測試檔。特別留意這幾個，紅了最可能是真的行為變了而不是測試太嚴：

- `tests/test_typing_corpus.py` — 使用者真實鍵盤紀錄配上本來想打的字，解碼器權重被它釘住
- `tests/test_golden.py` + `tests/golden/*.json` — 這一批新加的黃金測試（候選窗 4161 行、解碼 402 行）
- `tests/test_correction_scenarios.py`、`tests/test_installer_files.py`、`tests/test_symbols_extra.py` — 都是新檔

**注意：我沒有跑過這一行。** 這一格的 session 不被允許跑測試，而且分支上還沒有上游的程式碼，
跑了也是在測舊版。測試結果目前是未知，不是通過。

## 4. 重新載入開發模式的輸入法

```powershell
powershell -ExecutionPolicy Bypass -File scripts\dev-reload.ps1 -Rebuild
```

**預期看到**：PIMELauncher 被停掉、做完事再由 `explorer.exe` 重新啟動；
之後切到順打輸入法，打 `ji3` 看得到候選窗、打 `k27` 出得來「的」。

**為什麼需要**：`backend/input_methods/smartime/ime.json`、`src/smartime/pime/text_service.py`（116 行）、
`src/smartime/engine/**`（session、decoder、correction、panel、userdict、symbols 全都動過）都改了。
開發模式的輸入法不重新載入就還是跑舊程式。這裡用 `-Rebuild` 是因為第 2 項的詞庫也要一起重建。

## 5. 打開設定頁看一眼

```powershell
.venv\Scripts\python -m smartime.settings
```

**預期看到**：一個沒有網址列的 Edge app 視窗；打字、選字、詞庫、片語、關於各頁都打得開，
主控台沒有 JS 錯誤。這一批新加的東西要特別點一下：**我的片語**的搜尋／排序／分類／勾選批次處理、
**關於**頁的「檢查更新」與版本籤。

**為什麼需要**：`src/smartime/settings/api.py`（157 行）、`ui/app.js`（629 行）、
`ui/index.html`（129 行）、`ui/style.css`（45 行）都大改，而且新增了 `src/smartime/update.py`（168 行）。
設定頁是 JS，壞掉不會讓 pytest 紅，只能自己開起來看。

## 6. 安裝檔流程有變（**現在不用跑**，下次出版前要跑）

**為什麼要記這一條**：`installer/smartime.iss`（270 行）、`installer/pending-deletes.ps1`（新檔）、
`tools/build_installer.py`（73 行）、`tools/set_version.py`（39 行）、`tools/test_installer.ps1`（214 行）
全都改了，而且上游改成「只帶 PIME 核心、只註冊順打，不再執行 PIME 官方安裝檔」。

下次要出版的時候再跑：

```powershell
.venv\Scripts\python tools\build_installer.py
tools\test_installer.ps1 -Setup dist\ShundaIME-Setup-<版本>.exe -RestoreDev
```

**預期看到**：產生 `dist\ShundaIME-Setup-<版本>.exe`（需要 Inno Setup 6）；
安裝測試涵蓋乾淨安裝、takeover、移除後未重開機重裝三種情況。需要系統管理員，會跳一次 UAC。

---

## 這一批上游改動的版本脈絡

版本從 `0.6.0` 一路走到 `0.8.0-alpha.10`（中間 `0.8.0-rc.1` 被撤回）。
新 tag 只有 `v0.6.0` 一個。`CHANGELOG.md`（278 行）、`README.md`（272 行）、
`CONTRIBUTING.md`（新檔）、`docs/index.html`（新檔）、`docs/keys.md`、`docs/install.md`
都重寫過，要知道這一批到底改了什麼使用者看得到的行為，看 `CHANGELOG.md` 最快。
