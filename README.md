# The Physics of Insight

**兩件事共存的專案**:
1. **好學生筆記工具** — 音訊/影片 → 逐字稿 → 合併校稿 → 專有名詞補充 → 立場置入的好學生筆記。CLI pipeline + Web Studio 雙軌。**本 README 下半部是工具的執行用法。**
2. **Physics of Insight 視覺網頁** — 結合 Jack Butcher (Visualize Value) 設計風格與松尾研 LLM 課程學習心得的互動網頁,本專案的「前身作」,保留在 `/web/index.html` 主站。

> 為什麼兩件事在同一個 repo?網頁部分是專案緣起(見 [`docs/origin-story.md`](./docs/origin-story.md) Zeabur 創辦人分享),
> 啟發了這套好學生筆記工具的誕生 — 也就是現在的主戰場。

> ⚠️ **本 README 是「非規範」的上手說明;一切規範以 [`CLAUDE.md`](./CLAUDE.md) 為準。**
> pipeline 階段或核心原則變動時,必須同步更新本檔(見 CLAUDE.md § Project Structure Decisions 的文件同步守則)。

---

## 🚀 快速上手(好學生筆記工具)

### 1. 環境需求
- **Python ≥ 3.10**(scripts 用了 PEP 604 `str | None` 語法)
- **ffmpeg**:`brew install ffmpeg` / `apt install ffmpeg`
- **Python packages**:`pip install requests`
- **API Keys**:
  - Groq(轉錄):[console.groq.com/keys](https://console.groq.com/keys)(免費)
  - Gemini(校稿 + 筆記):[aistudio.google.com/apikey](https://aistudio.google.com/apikey)(免費)

### 2. 設定 API Key

CLI 使用者:
```bash
# 在專案根建立 .env
echo "GROQ_API_KEY=你的Groq_key" > .env
echo "GEMINI_API_KEY=你的Gemini_key" >> .env
```

Web Studio 使用者:直接在瀏覽器 UI 輸入框貼上(只存在你的瀏覽器,不會上傳)。

### 3. 跑一個音檔

```bash
# 最常用:產出去時間軸、合併通順的 cleaned.md(大宗使用者終點)
python3 scripts/session.py new <audio_file> --context "背景關鍵字,人名,專名"

# 範例:處理一支育兒諮詢錄音
python3 scripts/session.py new "諮詢錄音.m4a" \
    --context "RIE 教養, 語嫣, 糖果家好好睡, 安全依附關係" \
    --domain parenting
```

產物全部落在 `sessions/<YYYY-MM-DD_slug>/`。

---

## 🎯 Scenario-based 使用(依你想要的產物選指令)

每一步都是合法終點 — **不要預設每次都跑到底**:

| 你想要什麼 | `--stop-at` | 產物 | 適用情境 |
|------------|-------------|------|---------|
| 帶時間軸的 SRT | `transcribe` | `transcript.srt` | 做字幕、影片編輯索引 |
| 時間軸保留但錯字修正過 | `phase-a` | `cleaned.srt` | 專業字幕稿 |
| **去時間軸、合併、通順的對話稿** | `phase-b` ⭐(預設) | `cleaned.md` | **大宗使用者的終點** |
| 標點正規化(全形 + 預告語冒號) | `phase-c` | (精修 cleaned.md) | cleaned.md **出版前強制門**(§ R7) |
| 通順 / hook(內容指涉型承接) | `phase-d` | (精修 cleaned.md) | cleaned.md **出版前強制門**(§ R8) |
| 加專有名詞百科補充 | `enhance` | `enhanced.md` | 主題陌生的讀者 |
| 以某立場(身份/角色)置入的好學生筆記 | `notes` | `notes_<立場>.md` | 學習者自用 |
| 出版成可分享網頁 | (獨立指令 `publish_goodedunote.sh`,非 `--stop-at`) | `<slug>.html` + 線上網址 | 把筆記做成網頁分享(Step 5) |

> **Phase C / Phase D(原 Step 2.2/2.5)= cleaned.md 出版前的強制門**(CLAUDE.md 原則 9):
> 產出 cleaned.md 後,標點正規化(`scripts/normalize_punctuation.py`,§ R7)與通順/hook(§ R8)必須完成,
> `scripts/prepublish_gate.py`(由 `publish_goodedunote.sh` 開頭呼叫)會擋下未過 Phase C/D 的出版。
> 與 Phase A/B 同樣操作同一份 cleaned.md;Step 3+ 才換產物。

> **Step 5(出版)是獨立的一層**:把任一 md 產物轉成分頁式 HTML,deploy 到 Firebase 的 **`goodedunote`** 專案
> (`https://goodedunote.web.app/<slug>/`,每篇一個子路徑)。
> 工具:`scripts/lang/en/md_to_html.py`(md→HTML)+ `scripts/publish_goodedunote.sh`(同步圖 + `deploy --only hosting`)。
> **它與 GENAI 的 `/web` 站(GitHub Pages)是不同層級,出版筆記時不會、也不該動到 `/web`**(見 CLAUDE.md 原則 7)。

### 典型指令

```bash
# 只要 SRT 字幕
python3 scripts/session.py new audio.m4a --stop-at transcribe

# 要 cleaned.md(不需要好學生筆記)— 最常見
python3 scripts/session.py new audio.m4a --context "專名詞"

# 全套:跑到 Step 4 好學生筆記,以「建築師」立場置入
python3 scripts/session.py new audio.m4a \
    --context "專名詞" --domain parenting \
    --stop-at notes --identity 建築師

# 想自動偵測文中的專業術語做補充
python3 scripts/session.py new audio.m4a --stop-at enhance --enhance

# 也可以在 Claude Code 裡直接用 slash command
/good-student-notes audio.m4a 建築師 --context "..." --domain parenting
```

**Step 5 出版(轉 HTML + 部署到 goodedunote):**

```bash
# 把一篇筆記的 cleaned.md(+ 含 toc.json 的 workdir)轉「多頁」HTML 並上線
# 多頁 = index(封面 hero + 章節卡片)+ 每場一頁,每頁各自 OG 社群預覽圖(該場第一張圖,無圖用封面)
# 圖片自動壓縮 + EXIF 轉正後才上傳(省 Firebase 流量)
scripts/publish_goodedunote.sh <cleaned.md> <workdir> <slug> [圖片來源目錄] [--cover IMG.jpg] [--tagline "…"]
# → https://goodedunote.web.app/<slug>/(只動 goodedunote 的 hosting,不碰 /web)
```

---

## 🌐 何時用 Web Studio(`web/studio.html`)

Web 與 CLI 做同一件事,但 Web 有獨家優勢:

- **每一步後隨時可匯出 Session ZIP**(解壓縮後結構與 CLI session 目錄同構,可直接塞進 `sessions/`)
- **即時貼 context** — 對話中臨時補充背景資料,不用重跑整個 pipeline
- **步驟 Preview/Edit**,每一步的 md 可直接在瀏覽器裡手動微調後再進下一步
- **圖像版好學生筆記**:兩階段流程已實作(`/note` 生 A4 白底底稿 → `/好學生筆記` 逐頁疊視角手寫註解;見 `prompts/image_notes_skill.md` / `image_notes_design.md`)。**只能在 Web(自帶 key)/ Antigravity / Gemini CLI 驅動**,CLI 走 OAuth login token 無影像通道(原則 5 + Auth 雙軌表)

開啟方式:
```bash
# 本機 HTTP server(需要 HTTP 才能 fetch dict/ 共用詞典)
python3 -m http.server 8080
# 瀏覽器開 http://localhost:8080/web/studio.html
```

GitHub Pages 部署版:`https://shuotao.github.io/GENAI/web/studio.html`

---

## 🔄 CLI ↔ Web 對齊機制

兩條路徑共用:
- **同一份錯字詞典**(`dict/typo_dict*.json`,Web 用 dict-loader.js fetch)
- **同一份 Phase B 規則**(`prompts/qaqc_core_rules.md` SSoT)
- **同構的 session 產物結構**(Web ZIP 解壓 = CLI 目錄)

使用者累積的錯字校正推進 `dict/typo_dict.<domain>.json` 後 **`git push`**,
下次 Web 使用者頁面 reload 會自動拿到最新字典(`dict-loader.js` 用版本戳 cache busting)。

---

## 📂 專案架構與目錄說明

本專案採用靜態網頁架構，結構清晰，便於本機閱覽與部署。

### 1. `/web` - 核心網頁內容
這是專案的最主要目錄，包含了所有的呈現邏輯：
- **`index.html`**: 主頁面。採用單頁式捲動設計，包含 13 個核心章節，展示學習哲學與方法論。
- **`style.css`**: 定義了全域的視覺風格，包含黑白極簡風、毛玻璃效果、以及抽屜式互動動畫。
- **`script.js`**: 處理滾動偵測（Intersection Observer）、導覽列狀態切換以及側邊抽屜（Drawer）的動態加載。
- **`tech-01.html` 到 `tech-10.html`**: 詳細技術頁面。當點擊主頁上的「⦿」按鈕時，這些頁面會以 **3/4 寬度抽屜** 的形式從右側推出來。
- **`easter-egg.html`**: 隱藏彩蛋頁面。展示了實際的開發工作流程與「好學生筆記」的生成範例。

### 2. `/assets` - 視覺資產
存放所有圖片與圖示：
- `physics_of_insight/`: 核心觀念的視覺化圖表。
- 包含頭像照片與專用的 UI 圖示（如 `jack_diamond_icon.png`）。

### 3. `/SRT` - 原始工具 & 規格
- **`qaqc_srt.py`**: Phase A 清理 + `--structured` 結構保留型校稿
- **`transcribe.py`**: 獨立互動式轉錄工具
- **`context.example.txt`**: Context 格式範例(不會自動載入)
- **`SRT_QA_QC_檢查清單.md`**: QAQC 檢查清單(歷史文件,現況以 CLAUDE.md 為準)

> 「圖像視角好學生筆記」的完整設計已從本目錄移至 **`prompts/image_notes_design.md`**(P3 設計 SSoT;僅 Web+Antigravity 可驅動)。

### 4. `/scripts` - 共用腳本層(2026-04 新增)
- **`session.py`**: Pipeline 統籌器,一行命令跑完 Groq 轉錄 → Phase A → Phase B → Phase C → Phase D →(選)Step 3 補名詞 →(選)Step 4 筆記;偵測 host engine 決定打 API 或寫 marker 交對話 agent(原則 5)
- **`qaqc_phase_b.py`**: Gemini-powered 校稿(merged / polish〔Phase C 冒號+Phase D hook〕/ enhance / notes / structured 模式)
- **`normalize_punctuation.py`**: Phase C 全形化確定性工具(§ R7.1;中文句一律全形,保護小數/網址/網域/檔名/碼/markdown 連結)
- **`prepublish_gate.py`**: 出版前強制門(原則 9)— 檢查 Phase C/D 完成戳記 + 無殘留 marker + 全形 lint
- **`publish_goodedunote.sh`** + **`publish_qaqc.py`**: Step 5 出版(md→HTML→壓圖→deploy;拆分依講者數:單一講者一場用 `--single` 單篇連續、多講者用 `--multipage`,見 CLAUDE.md 原則 8)與 Step 6 出版後 audit
- **`describe_images.py`** + **`dedupe_images.py`** + **`insert_images.py`** + **`pipeline_autopilot.sh`**: 圖片理解(Antigravity headless)→ Haiku 自動插圖 → 閉環入口(`session.py --images <dir>`,見 prompts/publish_qaqc.md § S4.5.11)
- **`compress_images.py`**: 出版前圖片壓縮 + EXIF 轉正
- **`image_notes_session.py`** + **`md_to_a4_png.py`**: 好學生筆記**圖像版**兩階段工具(`/note` 生 A4 底稿 → `/好學生筆記` 逐頁生圖;僅 Web/Antigravity/Gemini CLI 可驅動)
- **`lang/`**: 多語系轉錄/清理腳本(目前有 `it/` 義大利文、`en/` 英文、`ja/` 日文)

### 5. `/dict` - 共用詞典(2026-04 新增)
CLI 與 Web 使用同一份字典:
- **`typo_dict.json`** + **`typo_dict.<domain>.json`**: 錯字修正(可疊加領域詞典)
- **`hallucination_prefixes.json`**: Whisper 幻覺前綴
- **`load.py`**: Python 載入器

### 6. `/sessions` - Session 容器(2026-04 新增)
每個音檔處理產生一個 `sessions/<YYYY-MM-DD_slug>/` 目錄,裡面有:
- `source.<ext>` (symlink)、`context.txt`、`transcript.srt`
- `cleaned.srt`、`cleaned.md`、`notes_<identity>.md`(選)
- `corrections.json`、`metadata.json`

### 7. `/docs` - 專案敘事
- **[`docs/origin-story.md`](./docs/origin-story.md)** — 專案緣起。Zeabur 創辦人關於 Claude Code 的深度實踐分享好學生筆記,本工具(好學生筆記工作室 + CLI Skill)的設計藍本。

### 8. 根目錄文件
- **`CLAUDE.md`**: 所有 AI 工具(Claude Code、Gemini CLI、Web Studio)的唯一規範文件
- **`GEMINI.md`**: Gemini CLI 入口(10 bytes 純指路檔 → `CLAUDE.md`)
- **`AGENTS.md`**: OpenAI Codex / 其他 AGENTS.md 相容工具入口(10 bytes 純指路檔 → `CLAUDE.md`)
- **`index.html`**: 專案入口點,自動引導至 `web/index.html`
- **`README.md`**: 本專案說明文件

---

## 📑 頁面重點與設計想法(Physics of Insight 網頁部分)

### 主頁面 (Main Stream)
*   **想法**: 致敬設計 Jack Butcher 的 "The Physics of Value"，用極簡的幾何圖形與強烈的對比（黑/白/灰）來降低認知摩擦。
*   **重點**: 強調「壓縮 vs. 還原」、「孤島 vs. 連結」等核心對立概念，呈現學習 LLM 不只是技術累積，更是思維模型的改變。

### 技術抽屜 (Technical Drawers)
*   **想法**: 使用 **Iframe 抽屜互動**，讓讀者在不離開主視覺脈絡的情況下，能深入閱讀技術細節。
*   **重點**: 每個細節頁面（tech-xx）都包含具體的技術手段（HOW）與對應的 Prompt 技術（Technique），讓內容不僅是哲學，更是可執行的 SOP。

### 隱藏彩蛋 (The Hidden Gem)
*   **想法**: 在結語處放入一個微小的鑽石圖示。
*   **重點**: 揭露這個網頁背後是如何利用 Gemini CLI 工具自動化處理 SRT、翻譯、與架構生成的過程，達成「人機共舞」的實踐。

---

## 💻 本機閱覽指南(Physics of Insight 網頁部分)

以下內容僅適用於 `/web/index.html` 主站(Physics of Insight 視覺設計網頁),不是好學生筆記工具。

Physics of Insight 網頁支持離線閱覽,不需要 server。直接進入 `web/` 雙擊 `index.html` 即可(`file://` 協議)。
**但** Web Studio(`web/studio.html`)需要 HTTP server 才能 fetch `/dict/` 共用詞典,否則會 fallback 到硬寫的 3 組通用字典。

### 字型與瀏覽器
- 建議 Chrome / Edge / Safari 最新版(毛玻璃效果)
- 字型優先 Google Fonts「Noto Sans TC」,無網路時 fallback 到系統黑體

---

## 🔧 Troubleshooting

| 症狀 | 原因與解法 |
|------|-----------|
| `scripts/session.py` 跑到一半出 400 error 且 context 很長 | Groq Whisper prompt 有 **896 字元上限**(characters,非 bytes)。腳本已自動裁切;若仍過長請縮短 `--context` |
| Web Studio 的 domain 下拉選單空白 | 用 `file://` 開啟時 fetch 被擋。改用 `python3 -m http.server 8080` |
| CLI 跑出 `ffmpeg: command not found` | 裝 ffmpeg:`brew install ffmpeg` 或 `apt install ffmpeg` |
| Python syntax error on `str \| None` | 需要 Python ≥ 3.10。檢查 `python3 --version` |
| 產出的 `cleaned.md` 字數遠低於原文 | Phase B 違反 95%-105% 量化檢查。檢查 metadata.json 的 `ratio_chinese`,若 < 0.95 建議重跑 |
| 好學生筆記圖像版生不出圖 | 影像生成只能在 Web(自帶 key)/ Antigravity / Gemini CLI 驅動;Claude Code / 純 CLI 走 OAuth login token,無影像通道(原則 5)。流程見 `prompts/image_notes_skill.md` |

更多規範細節見 [`CLAUDE.md`](./CLAUDE.md) 第 § Common Gotchas 章節。

---

**"The Physics of Insight - 讓我們用放大來放大你學習的機會和潛力。"**
