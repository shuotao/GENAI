# The Physics of Insight - 松尾研 LLM 學習旅程

這是一個結合了 **Jack Butcher (Visualize Value)** 視覺設計風格與 **松尾研 LLM 課程** 學習心得的高度互動式網頁專案。本專案旨在透過「知識轉譯」與「視覺錨點」，將複雜的 LLM 技術概念轉化為直覺且可留存的學習資產。

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
- **`好學生筆記.md`**: AI 角色設定與 Prompt 規範參考
- **`SRT_QA_QC_檢查清單.md`**: QAQC 檢查清單(歷史文件,現況以 CLAUDE.md 為準)

### 4. `/scripts` - 共用腳本層(2026-04 新增)
- **`session.py`**: Pipeline 統籌器,一行命令跑完 Groq 轉錄 → Phase A → Phase B → 好學生筆記
- **`qaqc_phase_b.py`**: Gemini-powered Phase B 校稿(CLI/Web 共用)
- **`lang/`**: 多語系轉錄/清理腳本(目前有 `it/`,未來可擴充日文、英文等)

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

## 🛠 好學生筆記工作流程(CLI)

```bash
# 一行命令跑完整條 pipeline
python3 scripts/session.py new <audio_file> \
    --context "領域專名詞,逗號隔開" \
    --domain parenting \
    --identity 建築師

# 或在 Claude Code 中用 skill
/good-student-notes <audio_file> 建築師 --context "..." --domain parenting
```

所有產物會歸位在 `sessions/<YYYY-MM-DD_slug>/`。詳見 [`CLAUDE.md`](./CLAUDE.md)。

---

## 📑 頁面重點與設計想法

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

## 💻 本機閱覽指南 (Offline Viewing)

本專案完全支持離線閱覽，不需要配置網頁伺服器（Server）即可運作。

### 1. 直接開啟
您可以直接進入 `web/` 資料夾，雙擊 **`index.html`** 文件。瀏覽器會以 `file://` 協議開啟。

### 2. 關於路徑的說明
*   **相對路徑**: 所有的連結、圖片、CSS 與 JS 引用均使用「相對路徑」（如 `../assets/` 或 `./style.css`）。這確保了無論您將整個專案資料夾放在家目錄、桌面或隨身碟，所有資源都能正確載入。
*   **抽屜顯示**: 抽屜內容是透過 Javascript 動態將相對的 HTML 路徑（如 `tech-01.html`）填入 Iframe 的 `src` 屬性。

### 3. 最佳體驗建議
*   **瀏覽器**: 建議使用 Chrome, Edge 或 Safari 的最新版本，以獲得最佳的滾動偵測與毛玻璃背景效果。
*   **字型**: 專案會優先嘗試從 Google Fonts 抓取「Noto Sans TC」，若在無網路環境下，則會回退到系統預設的黑體字，不影響閱讀。

---

**"The Physics of Insight - 讓我們用放大來放大你學習的機會和潛力。"**
