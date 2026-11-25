# 打字快時卡一下：先量出慢在哪一段（計畫，尚未實作）

狀態：**只有計畫**。這個分支不合進 main，也不出正式的 alpha。
使用者哪天想查，再從這裡做一個內部測試版；查完之後，計時的程式碼要 revert，
或者只把真的有用的那一小段留下來。

## 為什麼要先量

使用者回報（2026-11-25）：「打字很快的時候似乎還是會卡一下」。

`%APPDATA%\SmartIME\logs\backend.log` 裡，`pime/server.py` 會記下處理超過 30 ms 的請求：

| 時段 | 版本 | 慢的次數 | 樣子 |
|------|------|---------|------|
| 11-24 22–23 點 | alpha.5 | 28 | 零星 |
| 11-25 09:22 前後 | alpha.5 | 62 | **連續幾十個鍵，每個 200–557 ms** |
| 11-25 10:45 之後 | alpha.6 | 3 | 兩次約 40 ms；一次 `filterKeyDown` 1.8 s（開新程式後的第一個鍵） |

模擬器實測（`Session` 直接打一長段中文）：引擎每個鍵 1–2 ms。設 200 個快速詞也一樣，
組字區太長會自動送出，所以也不會越打越慢。**解碼器和快速詞的比對可以排除。**

所以那幾百 ms 是在 `SmartTextService.handle()` 裡、引擎以外的地方。但現在的 log
只記「慢了多少」，沒記「慢在哪一段」，分不出原因，不該用猜的去改。

## 嫌疑

1. **GIL 被面板搶走**：提示列、候選窗在 `ui/overlay.py` 的 `panel-ui` 執行緒用 Python 畫
   （GDI 量字、畫字）。畫的時候拿著 GIL，主執行緒的按鍵處理只能排隊。
   「連續一串都慢」比較像這種，因為每個鍵都觸發重畫。
2. **新程式的第一個鍵**：新的 client 會建一個 `SmartTextService`，第一個鍵還要準備東西
   （找游標、建面板視窗、圖示）。1.8 s 這種一次性的卡比較像這個。
3. **寫詞庫**：送出時 `learn` 會寫 SQLite（WAL）。剛好碰上 checkpoint 或防毒掃描，
   也會讓單一個鍵很慢。
4. **游標位置查詢**：`_caret_known()` 和 overlay 定位會呼叫 `GetGUIThreadInfo`，
   對沒有回應的視窗可能會等。

## 要加的計時（只在內部測試版）

原則：不改任何打字行為，只多記錄；只有「慢」的那一行才寫出來，平常不寫 log。

1. `pime/server.py`：慢的時候，除了總時間，再附上 `handle()` 裡各段的時間：
   - `engine`：`Session.key_down` / `filter_key_down`
   - `view`：`Session.view()`（含 hint／candidate panel 的資料）
   - `panel`：`_show_panel` / `overlay.show` / `overlay.hide`（主執行緒這一側）
   - `caret`：`_caret_known()`
   - `db`：這個鍵裡 `UserDict` 寫入的總時間（在 `learn` / `used_quick_word` 那幾個方法外面包一層）
   - `other`：總時間減掉以上
2. `ui/overlay.py`：`_paint` 花多久；超過 30 ms 也記一行，附上面板種類和大小。
   兩邊的時間戳對得起來，就知道主執行緒慢的時候，面板是不是正在畫。
3. `SmartTextService.__init__` 到第一個鍵回覆之間花多久（新程式第一個鍵那 1.8 s）。
4. 一行的格式，方便 grep：
   `slow onKeyDown 412.3 ms | engine 1.2 view 0.8 panel 3.1 caret 0.2 db 0.0 other 406.9 | paint(hint) 398.5 ms`

做法：用一個小的 context manager（`with _span("engine"):`）把時間記在 thread-local 的 dict 裡，
`server.py` 讀出來。不要到處貼 `perf_counter()`。

## 怎麼用

1. 從這個分支建一個內部測試版（不要用 `set_version.py` 往上加正式的 alpha 號，
   安裝檔名可以加 `-latency` 之類的字樣），給使用者裝。
2. 使用者照平常打字；覺得卡的時候記一下大概幾點。
3. 讀 `backend.log` 那幾分鐘的 `slow` 行，看哪一段最大：
   - `other` 大、`paint` 同時很大 → 嫌疑 1：面板的畫法要改（少重畫、量字快取、
     或把量字搬出 Python）
   - `caret` 大 → 嫌疑 4：查游標要加逾時或快取
   - `db` 大 → 嫌疑 3：寫入改成排隊、批次寫
   - 只有新程式第一個鍵慢 → 嫌疑 2：把那些準備工作提早做或改成懶載入
4. 依結果在 main 上做**真正的修正**（一個主題一個 commit，照平常流程出 alpha）。
   計時的程式碼不跟著進 main。

## 測試

- 單元測試：`_span` 會累計時間；不慢時不寫 log。
- 不能讓計時本身拖慢：每段只有兩次 `perf_counter()`，不寫檔。
- 實機：`tsf_typing_test` 打一段，確認 log 裡出現分段，打出來的字跟沒加計時時一樣。
