# 第三方資料與元件授權

本專案程式碼的授權尚未決定（見 Phase 2 決議：推廣前再決定）。為了保留開源與閉源兩種選擇，引擎程式碼**不直接併入 copyleft 程式碼**。

| 元件 | 用途 | 授權 | 散布方式 |
|------|------|------|----------|
| [McBopomofo](https://github.com/openvanilla/McBopomofo) `Source/Data` @ `be6564a` | 中文詞庫、讀音、詞頻；建置時執行其 curation pipeline | MIT | 建置時下載，衍生的 `smartime.db` 隨安裝散布；授權檔存於 `data/vendor/.../LICENSE.txt` |
| [wordfreq](https://github.com/rspeer/wordfreq) | 英文詞頻（前 80,000 詞） | 程式 Apache-2.0；**資料 CC BY-SA 4.0** | 僅建置時使用；衍生的英文詞頻表（`smartime.db` 的 `en` 資料表）須標示出處並以 CC BY-SA 4.0 授權 |
| [PIME](https://github.com/EasyIME/PIME) 1.3.0 | Windows TSF 前端與 Launcher | LGPL-2.1 | 安裝檔內附**未修改的官方安裝檔** `PIME-1.3.0-stable-setup.exe`（SHA-256 固定），電腦上沒有 PIME 時才安裝；原始碼連結寫在安裝目錄的 `THIRD-PARTY-NOTICES.txt`。開發用的 `scripts/install.ps1` 則從官方 GitHub 下載 |
| Python embeddable 3.13 | 後端執行環境 | PSF License | 隨安裝檔散布（建置時驗證 SHA-256 與 PSF 簽章），授權檔在 `runtime\LICENSE.txt` |
| [Inno Setup](https://jrsoftware.org/isinfo.php) 6 | 產生安裝檔；繁中訊息檔取自官方 issrc 的非官方翻譯 | Inno Setup License（允許商業使用） | 安裝程式本身含 Inno Setup 執行元件；不散布 Inno Setup 編譯器 |
| Microsoft JhengHei（微軟正黑體） | 只在 `tools/make_icons.py` 繪製圖示時使用 | Windows 字型 | 圖示為點陣輸出，不散布字型檔 |

倚天鍵盤的按鍵對照（`engine/layouts.py`）是業界標準配置，對照 libchewing 的 `et.rs` 逐鍵核對過，只引用對照關係這項事實，沒有複製程式碼。

日後若改用或新增資料（例如 libchewing / RIME 詞庫為 LGPL），須在此更新並確認與授權決策相容。
