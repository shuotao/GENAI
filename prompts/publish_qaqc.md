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
   尾端 push 一筆 entry(必填欄位見 § S6.3)
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
- 多頁模式:有 `session-1.html` ... `session-N.html`,N == toc.json 長度,
  編號連續無跳號
- 單頁模式:只有 `index.html`,內含 N 個 `id="session-1"` ~ `session-N"`
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

### S6.7 後置檢查清單

- [ ] § S6.1 檔案數量正確
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
