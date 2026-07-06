# 出版 QAQC 規範 (Step 4.5 + Step 6 SSoT)

本檔為**出版前**(Step 4.5)與**出版後**(Step 6)的核心鐵律來源。
- `scripts/publish_qaqc.py` 自動審查腳本 → 從這裡實作規則
- `CLAUDE.md` § Step 4.5 / Step 6 → 從這裡引用條文
- 出版用工具(`scripts/publish_goodedunote.sh`、`scripts/lang/en/md_to_html.py`)
  → 必須與本規範對齊

⚠️ 本檔是「規則條款庫」,不是執行 prompt。Step 4.5 是**人或 agent 在出版前
跑的合規檢查**,Step 6 是**部署後對 deploy 樹的審查**。兩者都應該 100% 機
械化可驗證(checkbox 化)。

> **Single Source of Truth**:出版相關規範只在本檔寫一次。其他工具/文件
> 用引用方式參照(`prompts/publish_qaqc.md § S4.5.x`)。

---

## S4.5 出版前 QAQC(cleaned.md + toc.json → HTML 之前)

### S4.5.0 拆分模式決策(先決定,再出版)

**出版的拆分單元是「講者(人)」,不是主題標題。** 出版前先判斷這場的講者數:

| 情境 | 模式 | 工具 | 產物 |
|---|---|---|---|
| **多位講者**(研討會/多場議程,每場不同人) | 多頁 | `md_to_html.py --multipage` | `index.html`(章節卡)+ 每位講者一頁 `session-N.html` |
| **單一講者的一場分享**(整場只有他一個人) | **單篇連續** | `md_to_html.py --single`(`publish_goodedunote.sh` 於 EXTRA 帶 `--single`) | **只有 `index.html`**,整場一頁到底 |

**鐵律:單一講者 = 一篇連續文章,根本不拆 session。** `##`/`###` 是**文章內的段落
標題**(渲染成 `<h2>`/`<h3>`),不是分頁邊界;讀者從書架點進去就是一頁滾到底,
**不會有「下一個」導覽、不會有章節卡**。把單人一場切成多頁(或每個小標各一頁)是
結構性錯誤 → 由 § S6.8 擋。

判斷依據可看 `data.js` 該書的 `single: true`(單篇)或缺省(多頁)。**單篇模式
不需要 toc.json**(沒有章節卡)。

### S4.5.1 檔案結構

出版單元(workdir)必須包含:
- `cleaned.md` — 出版主稿(Step 2 cleaned.md / Step 3 enhanced.md / Step 4
  notes_<identity>.md 任一終點皆可)
- `toc.json` — 章節索引(見 § S4.5.5)
- (選)cover image — 若用 `--cover`,檔案必須與 cleaned.md 同目錄或在
  IMGSRC 指定處

### S4.5.2 Markdown 支援度(以 `md_to_html.py` 為準)

| 語法 | 支援 | 渲染為 | 備註 |
|---|---|---|---|
| `# Title` | ✅ | 頁面 `<title>` + hero `<h1>` | 只取第一個 H1 |
| `*subtitle*`(緊接 H1 後單行)| ✅ | hero italic 副標 | 必須單行兩端各一個 `*`,只取第一個 |
| `## 章節標題` | ✅ | session 區塊起點 | 每個對應 toc.json 一筆 |
| `### 子標題` | ✅ | 章節內 H3 | |
| `**bold**` | ✅(2026-05-24 加入) | `<strong>` | 段內任意位置 |
| `![alt](file)` | ✅ | 圖片 | 整行單張 → 大圖;同行多張 → 並排 row |
| `![alt](<file with space>)` | ⚠️ | **不渲染** | regex 會把 `<>` 吃進 src;**出版前必須剝除** |
| 段落(空行分隔) | ✅ | `<p>` | |
| body `*italic*` | ❌ | 字面顯示 `*`,不轉斜體 | |
| `[text](url)` | ❌ | 字面顯示 | |
| `> blockquote` | ❌ | 字面顯示 `>` | |
| 列表 `-` / `1.` | ❌ | 字面顯示 | |
| 行內 `` `code` `` | ❌ | 字面顯示 backtick | |
| 區塊 ` ``` ` | ❌ | 字面顯示 | |
| 表格 `|` | ❌ | 字面顯示 | |

### S4.5.3 圖片規則

- **檔案存在性**:每個 `![alt](filename)` 引用的 filename 必須真實存在
  於 IMGSRC 目錄(`publish_goodedunote.sh` 第 4 個 argument,預設為
  cleaned.md 同目錄)
- **檔名可含中文/空白/括號**,但 markdown **不可用 `<filename>`形式
  包覆** — `md_to_html.py` 的 IMG_INLINE regex 是 `\(([^)]+)\)`,會把
  `<>` 一併吃進 src 屬性,導致 HTML 出來是 `src="<檔名>"` 而非 `src="檔名"`
- 合法寫法:`![alt](截圖 2026-05-24 下午1.49.23.png)`
- 不合法寫法:`![alt](<截圖 2026-05-24 下午1.49.23.png>)`
- 出版前若 cleaned.md 來自第三方/編輯器自動加上 `<>`,**合併腳本必須剝除**
- 副檔名:JPG / PNG 皆可。`compress_images.py` 會統一輸出 JPEG 內容但保留
  原副檔名(瀏覽器由 magic bytes 判讀,不會出問題)
- EXIF:手機側拍照不需手動轉正,`compress_images.py` 會依 EXIF 轉正

### S4.5.4 字數承襲

- 本步驟**不重新驗證**字數;字數合規由 Step 2 Phase B 的
  `prompts/qaqc_core_rules.md § R2.3`(95-105%)在出版前已通過

### S4.5.5 toc.json 結構

```json
[
  { "time": "10:00", "talk": "01 講者A — 主題A", "speakers": "講者A · 副標" },
  { "time": "10:30", "talk": "02 講者B — 主題B", "speakers": "講者B · 副標" }
]
```

- 陣列長度 == cleaned.md 內 `## ` 標題的數量,且順序必須一致
- 每筆三個欄位(`time` / `talk` / `speakers`)皆必填;`time` 可為空字串
  但 key 必須存在

### S4.5.6 Slug 命名規則

- ASCII 小寫,連字符分隔(`-`)
- 例:`mcp5-may-2026`、`koshi-cafe`、`bim-revit-mcp-2026-05-23`
- 一旦發布,**slug 不可變更**(URL 永久連結)

### S4.5.7 Slug → 書架對映(必填且必須一致)

| 書架(`SHELVES[].id` in data.js) | shelf id | `--back-anchor` | `--back-label` |
|---|---|---|---|
| 公開活動 | `public` | `shelf-public` | `公開活動書架` |
| 研討會 | `seminar` | `shelf-seminar` | `研討會書架` |
| 讀書會 | `reading` | `shelf-reading` | `讀書會書架` |

每個新出版的 slug 必須:
1. 在 `scripts/publish/goodedunote/public/data.js` 的對應 SHELVES.books 陣列
   **尾端 push**(append)一筆 entry(必填欄位見 § S6.3)。**尾端 = 書架最右**:
   `app.jsx` 以陣列順序 left→right 渲染書脊,新書往右長。**不得插在陣列前面**
   (會跑到最左、破壞「舊左新右」的時間軸)→ 由 § S6.9 擋。
2. 出版時帶上對應的 `--back-anchor` + `--back-label` flag
3. 兩者**書架歸屬必須一致**(資料 vs 連結匹配)

### S4.5.8 出版前最小檢查清單

執行 `publish_goodedunote.sh` 之前的人/agent 須確認:

- [ ] cleaned.md 的 H1 與 *subtitle* 各一行,內容正確
- [ ] `## ` 標題數 == toc.json 長度
- [ ] 所有 `![](...)` 引用的圖檔在 IMGSRC 存在
- [ ] cleaned.md 內**沒有** `<filename>` 形式的圖檔引用
- [ ] 沒有不支援的 markdown 語法(`>`、列表、表格、code block)
- [ ] 已決定 slug,且 slug 在 data.js SHELVES 已建好對應 entry 或預備加入
- [ ] 已決定要傳哪一組 `--back-anchor` + `--back-label`(對照 § S4.5.7)
- [ ] `--cover`(若有)圖檔在 IMGSRC 存在

### S4.5.9 文件家族同步清單(新增一本書 = 同時動多個檔)

**核心思維**:書架描述不該寫「現況快照」,該寫「**這道書架的恆久定位**」。
任何隨書本上線就過期的詞(`預告階段` / `各上線一本` / `即將推出` / `首本` /
`目前僅有`),都該在 Step 4.5 被根除,而不是靠 Step 6 grep 攔截。

每新增一本書(或修書本中繼資料),**publish 前**必須逐項 review:

| 檔案 / 區塊 | 動作 | 何時改 |
|---|---|---|
| `public/data.js` SHELVES[i].books | **必加** entry(slug, title, subtitle, date, venue, duration, words, url, height, width, spineShade, quotes 3-4 筆) | 每次 |
| `public/data.js` SHELVES[i].books 內的 placeholder | 視情況移除 / 改為下一本預告(平移占位)| 每次 |
| `public/data.js` SHELVES[i].description | review,確認新書沒有改變書架的整體定位 | 每次 |
| `public/app.jsx` Shelves SectionHead `title` + `sub` | **應為 count-agnostic** — 若發現寫了「N 本」/「目前」/「即將」必修 | 每次 |
| `public/app.jsx` Hero / Footer / Manifesto | review 是否仍與書架現況不衝突(通常無關) | 每次 |
| `prompts/publish_qaqc.md` § S4.5.7 對映表 | 若新增的是新類型書架(目前已有三類:public/seminar/reading),擴對映表 | 罕見 |
| `CLAUDE.md` § Step 5 / 原則 8 範例指令 | 若示例指令引用的書本變動 | 罕見 |

**書架描述的 timeless test**:寫完讀一遍,問自己「**第 N 本上線後這句話還對嗎?**」
若否,改成 count-agnostic 用法。範例:

| ❌ 會過時 | ✅ Timeless |
|---|---|
| 「目前公開活動、研討會各上線一本逐字稿;讀書會在預告階段」 | 「三道書架都已開張,書脊會隨每場新筆記橫向長出去」 |
| 「首本即將上線」 | 「定期累積中」 |
| 「2026.05 加入第一本」 | (改成只在 book.date 寫具體日期,書架描述不寫日期)|

**S6.7 的 grep audit 是『最後安全網』,不是首道防線**。Audit 抓到紅旗詞代表
S4.5.9 沒做好,應該回頭改文字而不是放任 grep 每次 fail。

### S4.5.11 圖片理解 × 自動插圖(2026-07-05 引入)

啟用:`session.py --images <dir>`;marker 鏈 `phase-d → images → image-insert`。
工具:`describe_images.py`(描述)、`insert_images.py`(插入)、`img_context_score.py`(相關性)。

**引擎**
- 描述:Antigravity CLI headless — `antigravity -p --model "Gemini 3.5 Flash (Medium)"
  --add-dir <session>`(OAuth login;`agy -p` 等效)。送圖前 `exif_transpose`
  到 `.img_norm/` 暫存(原檔不動)。
- 失敗處理:同引擎重試 2 次(退避 5s);連續 3 張失敗即中止整批
  (`--max-consecutive-fails`)。連續失敗先以最小指令(`antigravity -p "hi"`)單測:
  空回應/節流(如日配額用盡,連非 Gemini model 都空)→ 冷卻等待或**改用 Opus
  對話 agent 直接 Read 圖產同 schema 描述**(engine=opus-fallback),補完少數卡住的圖。
- 插圖位置判斷:Claude Haiku subagent;套用與驗證:`insert_images.py`(確定性)。

**描述 prompt 五要求 + 一禁令**
1. `text_in_image`:逐字保留原語言(英/中/日,含頁碼)
2. `layout`:構圖區塊 [{region, content}]
3. `speaker_view` / `audience_view`:雙視角敘述
4. `content_signal`:3-5 個可在逐字稿檢索到的錨點詞(專名/數字)
5. `caption`:12-20 字、含具體實體(地點/產品/主題)
禁:拍攝 meta(顛倒/角度/反光)。

**schema 補充欄位(工具確定性產生)**
`palette_hex`(PIL median-cut top-5)、`deck_page`(投影片內印 `N/M` 頁碼;影片截圖無內印時 fallback 檔名序號 `-NNNN`)、
`needs_review`(deck_page 為 null 時 true)、`anchor{para_index, confidence, engine}`、
`status`(described → inserted;error 不得插入)。

**anchors 產生(2026-07-06 起:確定性工具為主,LLM 只覆核尾巴)**
- **執行者 = Claude Haiku subagent**(本 stage 的規範執行者;不使用更大的模型)。
- 步驟(全部直接呼叫,免語意判斷):
  1. `python3 scripts/propose_anchors.py --session <dir>` — 純 py 文字比對
     (詞彙 containment 分數 + deck_page 單調 DP,零 LLM),輸出
     `anchors_proposed.json`;信心足的直接採用,低信心/無頁碼自動標
     `needs_llm_review`。
  2. Haiku 只複核 `needs_llm_review=true` 的條目(對照描述與候選段落,
     修 after_line 或給 -1),其餘不看。
  3. `insert_images.py --apply --anchors <json>` → `--verify`。
- 實測(0704CC 20 張 ground truth):py 直接採用的 12 張 100% 可接受;
  整體 90%,含 Haiku 複核尾巴後 ≥ 95%(等同全 LLM 判斷,LLM 用量 -60%)。

**anchors 完備性**:每張 described 圖必須出現在 anchors;`after_line=-1` = 此圖
不插入(重複張/封面/無合理位置),apply 跳過並列入報告。

**插圖鐵律(`insert_images.py --apply`)**
原內容行 1:1 不變、CJK 字數不變、每張圖恰插一次、圖檔存在;任一不過 →
rollback + exit 1。deck_page 單調小違序(Haiku 複核後相鄰互換)→ 確定性
clamp 往後對齊;needs_review 清單回報使用者複核。

**相關性計分(gate 與 § S6.11 共用)**
描述全文 vs 插入點 ±1 行,CJK bigram + ASCII 詞 containment。門檻(0704CC
20 張 ground truth 校準):fail < 0.02 硬擋、0.02–0.09 warning 交 agent 複核、
≥ 0.09 healthy。

**驗收標準**
自動 anchors vs 人工 ground truth 同段命中率 ≥ 80%(EXACT + ±1 + 同章節)。
基準:2026-07-05 實測 95%;導入 deck_page/tie-break 後 EXACT 11 → 14(R4,
EXIF 轉正 + content_signal 描述),Opus 覆核成立。

### S4.5.12 重複圖片去重(2026-07-06 引入)

影片截圖抓拍會把同一張投影片拍進多幀。**describe 之後、anchors 之前**跑
`scripts/dedupe_images.py --session <dir> --report`,確認後 `--apply`。
**執行者 = Claude Haiku subagent**;工具為純 py 確定性比對(dHash + 詞彙
Jaccard),直接呼叫、免語意判斷;Haiku 只讀「人工複核」清單做確認。

**判定 = 雙訊號 AND 閘**(缺一不可):
1. 影像指紋:dHash 64-bit Hamming ≤ 6(確定性)
2. 描述一致:image_notes 描述詞彙 Jaccard ≥ 0.5

只有影像近似、描述不同 = **同版型不同內容**(章節卡模板等)→ 列「人工複核」
報告、保留兩張。實證:2026-06-26_1 的「892 天前/603 天前」兩張章節卡 dHash
近似但描述相似僅 0.28,單訊號會誤刪。

**--apply 行為**:每組保留 deck_page 最早一張;其餘自 cleaned.md 移除該圖行
(正文零省略驗證,備份 `.pre-dedupe.bak`)、image_notes 標
`status=duplicate` + `duplicate_of`。**republish 後必須清除部署目錄的孤兒圖檔**
(由 § S6.12 擋)。

### S4.5.10 授權 footer(2026-05-25 引入)

每張出版 HTML(index 與 session-*)的 footer **自動帶授權行**,內容由
`md_to_html.py` baked-in:

> 程式碼 MIT · 站台文案與筆記 [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) · 講者話語著作權歸各場講者個人

對應根目錄三個檔:`LICENSE`(MIT)、`LICENSE-CONTENT`(CC BY 4.0 + 講者
特別說明)、`NOTICE`(雙軌總覽)。

**新增任何引用第三方素材前**(他人簡報截圖、外站圖片、其他 CC 授權內容),
出版者必須:
1. 先查 `NOTICE` 確認該素材屬哪一層
2. 若屬第三方素材且非自己擁有,**必須在引用處單獨標明來源與授權**
3. 不可逕自合併到本站 CC-BY 範圍內(會混淆授權邊界)

---

## S6 出版後 QAQC(deployed HTML)

對 `scripts/publish/goodedunote/public/<slug>/` 的本地副本做檢查
(這份就是 Firebase deploy 的 source of truth)。所有條款應可在
`scripts/publish_qaqc.py` 自動實作。

### S6.1 檔案結構

- `public/<slug>/index.html` **必存**
- **單篇連續模式(`single: true`)**:**只有 `index.html`**,正文在單一
  `<article>` 內(`##`→`<h2>`、`###`→`<h3>`);**無** `session-*.html`、
  **無**章節卡、**無**「下一個」。這是單一講者一場分享的正解(見 § S4.5.0)。
- 多頁模式:有 `session-1.html` ... `session-N.html`,N == toc.json 長度,
  編號連續無跳號
- 單頁 SPA 模式:只有 `index.html`,內含 N 個 `id="session-1"` ~ `session-N"`
  的 `<section>`
- 圖片檔(若有):與 cleaned.md 引用名稱一致存在於 `public/<slug>/`

#### S6.1.b 無孤兒 session 檔(2026-05-30 引入)

`public/<slug>/` 內每個 `session-*.html` 都**必須**被 `index.html` 的某個 `href`
引用。若有檔案存在於目錄但 index 沒指向 → ✗ orphan,代表上次 republish 章節
變少但舊檔案沒被清掉(例如 23 章節 → 2 章節時 session-3.html ~ session-16.html 殘留)。

**Why:** `publish_goodedunote.sh` 的 `rm -f session-*.html` 只清 *本地* 目錄,
但若有人手動編輯後跳過清檔直接 deploy,孤兒檔案會留在 Firebase Hosting 上,
雖然點不到但會在 Firebase 計費與 sitemap 內變雜訊。

#### S6.1.c 無斷裂 session 引用(2026-05-30 引入)

`index.html` 內出現的每個 `href="session-N.html"` 都**必須**對應一個實際存在於
`public/<slug>/` 內的檔案。若 href 指向不存在的檔案 → ✗ dangling reference,
讀者點下去會 404。

**Why:** 防止 toc.json / session-*.html / index.html 三者命名不同步(例如改了
toc.json 但忘記重跑 md_to_html.py,或 md_to_html.py 寫的檔名 pattern 改了)。

### S6.2 Back link(統一書架回連)

- 每個 HTML 在 `<body>` 開頭區塊內(視覺上 viewport 頂端)
  必須包含一個 `<a href="../#shelf-XXX">← 回到XX書架</a>`
- href 的 `shelf-XXX` 必須匹配 data.js 中該 slug 所屬 shelf 的 id
  (`shelf-public` / `shelf-seminar` / `shelf-reading`)
- 連結文字必須符合「← 回到XX書架」格式,中間「XX」必須匹配
  § S4.5.7 對映表的 label

### S6.3 data.js entry 完整性

`public/data.js` 中該 slug 對應的 book object **必須**含以下欄位且非空:

| 欄位 | 型別 | 範例 | 驗證 |
|---|---|---|---|
| `id` | string | `"bim-revit-mcp-2026-05-23"` | 等於 slug |
| `title` | string | `"MCP 五月小聚 · VOL.05"` | 非空 |
| `subtitle` | string | `"分享老師暴增的一個月份"` | 非空 |
| `date` | string | `"2026.05.23"` | 點分式 YYYY.MM.DD |
| `venue` | string | `"小樹屋 + Zoom · hybrid"` | 非空 |
| `duration` | string | `"01h35"` | 非空(可寫 `"—"` 表未知)|
| `words` | number | `18433` | > 0(中文字總計);**且漂移 < 10%**(見 § S6.3.b)|
| `url` | string | `"./bim-revit-mcp-2026-05-23/"` | 形如 `./<slug>/` |
| `height` | number | `340` | 200-400(書脊視覺高度,px)|
| `width` | number | `62` | 40-80(書脊視覺寬度,px)|
| `spineShade` | number | `0` 或 `1` | 配色變體;**0/1 都合法**,不檢查 > 0 |
| `quotes` | string[] | 3-4 筆字面引言 | 長度 3-4 |

#### S6.3.b data.js words 漂移檢查(2026-05-30 引入)

`data.js` 的 `words` 必須在 **deployed `session-*.html` 內所有 `<p>` + `<h3>`
的中文字總和的 ±10% 之內**。漂移 > 10% → ✗,代表有人改了 cleaned.md 但沒更新
data.js(或反過來)。

**閾值選擇:**
- **< 5%** → ✓ healthy
- **5%–10%** → ⚠ warning(可能因刪標題行造成的小漂移,例如 23 H3 → 3 H3 會掉 1-2%)
- **> 10%** → ✗ failure(明顯不同步,要查清楚是哪邊舊了)

**Why:** 我曾在 23 H3 → 3 H3 收斂後忘記同步 data.js 的 words,審查時沒察覺
metadata 跟實際內容已經漂移 2.1%。雖然小,但若改變內容更多(例如 Part II
從整頁變 placeholder),漂移會 > 50%,書脊高度視覺也會變不準。

### S6.4 OG / Twitter meta

**核心(MUST,缺失 = audit fail)**:
- `<meta property="og:title" content="...">`
- `<meta property="og:url" content="...">`
- `<meta name="twitter:card" content="summary_large_image">`

**圖像(SHOULD,建議但不強制)**:
- `<meta property="og:image" content="...">`(該頁第一張圖,無圖則用 cover)
- `<meta name="twitter:image" content="...">`

無圖頁面允許省略 og:image / twitter:image(audit 只印警告不視失敗),
但建議出版時用 `--cover <site-logo>` 提供 fallback 預覽圖,改善社群分享體驗。

### S6.5 圖片預算

- 單一 slug 目錄下所有圖片總和應 **< 10MB**(已壓縮過)
- 單張圖片 > 1MB 時應審視(壓縮失效或圖太大)

### S6.7 Site copy freshness(最後安全網,不是首道防線)

⚠️ **這條規則是 backstop,不是 prevention**。真正的 prevention 是 § S4.5.9
(出版前文件家族同步清單)。S6.7 只是 grep-based safety net,抓到 ✗ 代表
S4.5.9 沒做好,應該回頭把那行文字改成 count-agnostic,而不是把紅旗詞加進
白名單去敷衍 audit。

**動機**:書架區的描述散在三個地方 — `app.jsx` 內的 `SectionHead`(title +
sub)、`data.js` 內三道 shelf 各自的 `description`、書本 hover 卡片內的
quotes。改一邊忘了另一邊,容易導致「一本書已上線、副標還寫『預告階段』」
這類不同步。

**規則**:`app.jsx`、`index.html`、`data.js` 內**禁止出現**以下硬寫狀態/
數量詞,因為它們會隨書本上線而失效:

| 紅旗詞 | 原因 |
|---|---|
| `預告階段` | 書架描述如果硬寫「預告階段」,書本一上線就矛盾 |
| `尚未上線` | 同上(`spine-card` 內的 placeholder fallback 文字除外) |
| `各上線一本` / `各上線 N 本` | 書架本數會增加 |
| `還沒上線` / `即將推出` | 同 placeholder 例外 |
| `首本` / `第一本` | 第二本上線後失效 |

**例外**:`app.jsx` 的 `SpineCard` 內 placeholder books 顯示「逐字稿尚未上線,
先佔個位置」是合法用法(只有未上線的書本看到),audit 會跳過。

**自動偵測**:`scripts/publish_qaqc.py` 會 grep 上述紅旗詞,若出現在非
placeholder 路徑即 ✗ 並要求人工確認。

### S6.6 視覺一致性

- **Dropcap**:`<p class="dropcap">` 不應緊接 `<strong>` 開頭(若有,代表
  該段以 `**bold**` 開頭,規則由 `md_to_html.py` 自動偵測並跳過 dropcap)
- **Spine card**(根頁面 hover 卡片):
  - `.spine-card` 必須有 `max-width: min(320px, 84vw)`(行動裝置 safe area)
  - `.shelf-scroller` 必須有足夠的左右 padding(desktop ≥ 160px / mobile ≥ 48px)
    讓第一本書 hover 不破出畫面
- **Scroll snap**:`.shelf` 必須有 `scroll-snap-align: start` + `scroll-margin-top`
  搭配 fixed nav 高度
- **Hash anchor 跨頁**:根頁面的 React App 必須在 mount 後重新檢查
  `location.hash` 並 scrollIntoView(因為 React-Babel render 比瀏覽器預設
  anchor scroll 慢,沒這層補償會落在 hero)

### S6.8 拆分合理性(2026-07-05 引入)

**拆分單元 = 講者(人),不是主題標題。** 對照 § S4.5.0:

- book 標 `single: true`(單一講者一場分享)→ slug 目錄**必須沒有** `session-*.html`
  (0 個),且 `index.html` 內含 `<article` 連續正文。若單篇書卻出現 `session-*.html`
  → ✗(代表被錯誤拆頁,例:把「開場→志工介紹」這種連續段落切成不同 session、
  中間冒出「下一個」)。
- 未標 `single` 的書維持多頁檢查(§ S6.1 的 N == toc 長度)。

**Why:** 2026-07-05 出 `code-with-claude-tokyo-sharing`(單一講者 Justin)時,
先被切成 16 碎頁、再 3 章,連續敘事被硬切、內容跳接錯亂。根因是沒有「依講者
拆分」的規範與守門 → 補此條 + `md_to_html.py --single` 單篇模式。

### S6.9 書架排序(2026-07-05 引入)

- 每道 shelf 的 `books` 內,**非 placeholder** 的 `book.date`(`YYYY.MM.DD`)必須
  **非遞減**(舊的在左、新的在右)。新書一律 append 到陣列尾端(§ S4.5.7)。
- date 是定寬點分式 → 字串比較即日期比較。任何一本排在更新日期之後卻更早 → ✗。

**Why:** 新書應「往右一次增加過去」。曾把新書 entry 插在 `books` 最前面,書脊
就跑到最左、破壞時間軸。此條把「append 往右」機械化。

### S6.11 圖文相關性(2026-07-05 引入)

部署頁每個 `<figure>` 圖片(cover 除外)必須:
- 在對應 session 的 `image_notes.json` 有條目(status=inserted);
- 描述↔前後 prose 區塊的相關性分數(§ S4.5.11 同一把尺)≥ fail 門檻。

舊書(無 image_notes.json)→ **跳過不 fail**(標註提示)。抓到 fail 代表出版後
md 被手改、或 anchor 判斷漂移 → 修 anchor / 補描述後重出。
**執行者(Haiku)已複核**(anchor.engine=haiku-reviewed/human)卻低分者 → 降**警告**
不擋:多為離題番外投影(產品官網等,與逐字稿零詞彙重疊),放置正確但天生低分。

### S6.12 圖片去重與孤兒(2026-07-06 引入)

- **無孤兒圖**:slug 目錄內每個圖檔(cover.jpg 除外)必須被至少一頁 HTML 的
  `src` 引用。孤兒 = 去重/改版後未清的殘檔 → ✗(浪費流量、S6.5 預算失真)。
- **無完全重複圖**:圖檔 md5 兩兩唯一;重複 → ✗。
- **S6.5 逐頁**:圖片載入成本以「單一 session/index 頁引用的圖總量」計(各頁
  lazy-load 獨立),最大單頁 < 10MB;多場書整本總量大不算違規。
- **近似圖(dHash ≤ 6)只列警告**:同版型模板會誤判,交人工複核(§ S4.5.12
  的雙訊號 AND 閘已在出版前把真重複擋掉,audit 端不重複硬擋)。

### S6.10 後置檢查清單

- [ ] § S6.1 檔案數量正確(單篇:只有 index.html)
- [ ] § S6.8 單篇書無 session-*.html;多頁書 N == toc
- [ ] § S6.9 書架 date 非遞減(新書在最右)
- [ ] § S6.12 無孤兒圖、無 md5 重複圖
- [ ] § S6.1.b 無孤兒 session-*.html
- [ ] § S6.1.c index.html 引用的 session-N.html 全部存在
- [ ] § S6.2 所有 HTML 含正確 back link
- [ ] § S6.3 data.js entry 完整且 shelf 對映一致
- [ ] § S6.3.b data.js words 漂移 < 10%
- [ ] § S6.4 每個 HTML 有完整 OG/Twitter meta
- [ ] § S6.5 圖片總量在預算內
- [ ] § S6.6 視覺一致性(spine-card、scroll snap、hash anchor)無回歸

---

## 違規/失敗時的標準操作

- **S4.5 失敗**(出版前):中斷出版流程,修 cleaned.md / toc.json 後重試
- **S6 失敗**(出版後):
  - 若是 back-link 漏帶 → 重跑出版工具帶上正確 `--back-anchor` + `--back-label`
  - 若是 data.js 不一致 → 修 data.js + 重 deploy(`firebase deploy --only hosting`)
  - 若是視覺一致性回歸 → 檢視 root style.css / app.jsx 是否被改動

## 變更紀錄

- 2026-05-24:首版上線。建立 Step 4.5 / Step 6 框架,對應修 race condition、
  統一書架回連、`publish_qaqc.py` audit。
- 2026-05-30:補 § S6.1.b 孤兒檢測、§ S6.1.c 斷裂引用、§ S6.3.b words 漂移檢測
  三條規則。動機:republish 章節數變動時舊 session 檔可能殘留 / metadata 跟
  cleaned.md 失同步,既有 audit 抓不到。
- 2026-07-05:補 § S4.5.0 拆分模式決策(拆分單元＝講者,單講者用 `--single`
  單篇)、§ S6.8 拆分合理性、§ S6.9 書架排序(新書往右 append)。`md_to_html.py`
  加 `--single` 單篇連續模式、`publish_qaqc.py` 加 S6.8/S6.9 + 單篇 prose 計數。
  動機:單一講者一場分享被錯誤拆成多頁(連續敘事被切、內容跳接);新書 entry
  插在陣列最前面跑到書架最左。兩者都沒規範/守門 → 一次補齊 spec + 工具 + audit。
- 2026-07-05(二):補 § S4.5.11 圖片理解×自動插圖(Antigravity headless 描述、
  Haiku anchors、零省略插圖、相關性計分)與 § S6.11 圖文相關性 audit。新工具:
  describe_images.py / insert_images.py / img_context_score.py / pipeline_autopilot.sh;
  session.py 加 `--images` 與 images/image-insert stages;prepublish_gate 加圖片檢查。
  動機:閉環管線(音檔+圖 → 出版前全自動,deploy 人工)。
- 2026-07-05(三):QC 驗證(0704CC 20 張 ground truth,95% 可接受,Opus 覆核
  成立)結論固化入 § S4.5.11:deck_page 單調鍵、needs_review、tie-break、
  EXIF 轉正、禁拍攝 meta、門檻重校準(fail<0.02/healthy≥0.09)。
- 2026-07-05(四):移除 gemini CLI fallback(個人免費方案遭下架,IneligibleTier
  為帳號級封鎖)改熔斷;§ S4.5.11 全文改指令式,刪 .b/.c 敘事段(歷程留 git)。
- 2026-07-06(二):anchors 產生改「propose_anchors.py 確定性比對為主 +
  Haiku 只複核 needs_llm_review 尾巴」;圖片 stage(去重/插圖)規範執行者
  定為 Claude Haiku。實測 0704CC:py 直採 12 張全對、整體 90%。
- 2026-07-06(四):deck_page 加檔名序號 fallback(影片截圖無內印頁碼時,補
  時序約束,避免 Haiku 無序約束把圖放亂 + clamp 堆疊);antigravity 節流時
  Opus-fallback 補描述。動機:day1 第 7 場實戰。
- 2026-07-06(三):S6.5 改逐頁圖片載入(多場書整本大但每頁不大);S6.11 對
  執行者已複核的低分離題圖降警告;insert_images deck_page 單調小違序改確定性
  clamp;S6.11 多場書合併所有相關 session 的 image_notes。
- 2026-07-06:新增 § S4.5.12 重複圖去重(dedupe_images.py,dHash+描述雙訊號
  AND 閘)與 § S6.12 audit(孤兒圖/md5 重複圖=fail、dHash 近似=警告)。
  動機:genai2026-day1 影片截圖 51 張含 8 組相鄰幀重複;另 892/603 章節卡
  證明單靠影像指紋會誤刪同版型不同內容。
