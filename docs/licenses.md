# 第三方資料與元件授權

本專案程式碼的授權尚未決定（見 Phase 2 決議：推廣前再決定）。為了保留開源與閉源兩種選擇，引擎程式碼**不直接併入 copyleft 程式碼**。

| 元件 | 用途 | 授權 | 散布方式 |
|------|------|------|----------|
| [McBopomofo](https://github.com/openvanilla/McBopomofo) `Source/Data` @ `be6564a` | 中文詞庫、讀音、詞頻；建置時執行其 curation pipeline | MIT | 建置時下載，衍生的 `smartime.db` 隨安裝散布；授權檔存於 `data/vendor/.../LICENSE.txt` |
| [wordfreq](https://github.com/rspeer/wordfreq) | 英文詞頻（前 80,000 詞） | 程式 Apache-2.0；**資料 CC BY-SA 4.0** | 僅建置時使用；衍生的英文詞頻表（`smartime.db` 的 `en` 資料表）須標示出處並以 CC BY-SA 4.0 授權 |
| [PIME](https://github.com/EasyIME/PIME) 1.3.0 | Windows TSF 前端與 Launcher | LGPL-2.1 | **不隨本專案散布**；安裝腳本會從官方 GitHub 下載官方安裝檔 |
| Python embeddable 3.13 | 後端執行環境 | PSF License | 安裝腳本從 python.org 下載 |
| Microsoft JhengHei（微軟正黑體） | 只在 `tools/make_icons.py` 繪製圖示時使用 | Windows 字型 | 圖示為點陣輸出，不散布字型檔 |

日後若改用或新增資料（例如 libchewing / RIME 詞庫為 LGPL），須在此更新並確認與授權決策相容。
