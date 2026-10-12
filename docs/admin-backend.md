# 營運後台(docs/admin-backend.md)

> 自 `CLAUDE.md` 原則 10 移出(2026-10-12 重構)。原則本身仍列在 CLAUDE.md,
> 細節(四條鐵律、資料表、工具)在本檔。

---

### 原則 10 — 後台是出版層的第三個面,與名冊來源嚴格分離(2026-09-01 引入)

`goodedunote.web.app/admin/` 是**營運後台**:看文章點擊統計、管電子報通訊錄。
它跟 Step 5 出版層共用同一個 Firebase 專案與 hosting,但職責不同。

| | 出版層(`public/<slug>/`) | 後台(`public/admin/`) |
|---|---|---|
| 內容 | 公開的逐字稿 HTML | 個資名冊 + 統計 |
| 保護 | 無(本來就公開) | Firebase Auth Google 登入 + Firestore `admins/` 白名單 |
| 資料 | 靜態檔 | Firestore(`subscribers` / `events` / `stats` / `blockReasons`) |
| 更新 | `publish_goodedunote.sh` | `import_roster.py`、`sync_ga_stats.py`(皆本機執行) |

**鐵律 1 — GWS 唯讀。** 名冊來源是 `~/Desktop/GWS/data/`,那個專案有 BLOCKING scope
guard(禁止在其中引入資料庫/web service)。本專案**只讀不寫**,所有程式寫在
`study/scripts/` 下。正規化語義(`normalize_email` / `load_blacklist` / Round 11
雙形式保留)一律 **import GWS 的 `_common.py`**,絕不自行重寫 —— 重寫必然漂移,
而漂移的後果是「黑名單靜默失效、被封鎖的人重新收到信」。

**鐵律 2 — 個資與憑證不進 git。** `subscribers` 只存在 Firestore;
service account 金鑰在 `.secrets/`、匯出 CSV 在 `exports/`,皆已 gitignore。
`GWS/data/reports/*.md` 有未遮蔽的姓名+email 表格,**不要讀進任何產物**。

**鐵律 3 — 分眾是查詢,不是名單。** 「MCP 歷次/當月」「演講資料」「社群申請」
全部由 `events.category` + `eventDate` 即時算出。新增報名種類 = 在後台新增一筆事件,
**不改程式**;當月沒場次自然為空,零人工維護。這是刻意用來取代 GWS 那種
「每期產一份 `audience_NN.txt`」的做法。

**鐵律 4 — 報名事件與名單軌跡是兩種東西,不可互相偽裝。**
`responses/*.jsonl` 給的是**報名事件**(有姓名、時間、報名選項)→ 進 `registrations` 子集合。
`data/*.txt` 給的是**名單成員身分**(只有 email,無姓名/無日期/無場次)→ 進
`subscriber.lists[]`。把名單成員偽造成一筆 registration 會污染所有以報名為基礎的分眾與統計。
只存在於名單、從未報名過的人(實測 12 位:永久收件人、手動補入、只在黑名單上的位址等)
仍要建成聯絡人 —— 否則封鎖區看不到他們,就無從檢視理由或解封。
`test_audience.txt` 的位址標 `testAddress`,匯出時與封鎖者一併扣除。

**鐵律 5 — 前端不做權限判斷。** 非白名單帳號看到的必須是 Firestore 規則回的
`permission-denied`,不是被 CSS 藏起來的畫面。`admins/` 的 write 在規則中恆為
`false`,只能由本機 `seed_admin.py` 寫入(否則任何登入者都能自我提權)。

---

