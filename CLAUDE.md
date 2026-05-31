# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.
It is the **single authoritative specification** for all AI-assisted workflows in this project.

> **專案憲法**:本檔是所有 AI 引擎的唯一規範來源。
> 專案根的 `GEMINI.md`、`AGENTS.md` 皆為 **10 bytes 純指路檔**,內容只有一行 `CLAUDE.md`。
> 任何 AI 工具(Claude Code、Gemini CLI、OpenAI Codex、其他 AGENTS.md 相容工具)啟動時
> 讀到對應入口檔,會被引導至本檔。借鑑自 REVIT_MCP_study 專案的極簡憲法邏輯。

本文件整合了原 `SRT/Agent.md` 的全部規範(v2.2 — 2026-04 架構性升級版)。

---

## Project Overview

**"The Physics of Insight"** is a dual-purpose project:

1. **Interactive Web Platform** (`/web`): Static HTML/CSS/JS website + 好學生筆記工作室(client-side AI pipeline)
2. **CLI Workflow** (`/.claude/skills/good-student-notes` + `/scripts/`): Terminal-based transcription + notes generation,由 `scripts/session.py` 統籌,Claude Code 或 Gemini CLI 呼叫

專案緣起:[`docs/origin-story.md`](./docs/origin-story.md) — Zeabur 創辦人關於 Claude Code 的深度實踐分享,是本工具的設計藍本。

---

## Quick Start(三行版)

```bash
# 處理一個音檔,產出去時間軸、合併、通順的 cleaned.md(大宗使用者終點)
python3 scripts/session.py new <audio_file> --context "領域專名詞"

# 要好學生筆記?加 --stop-at notes --identity "<立場>"
# 要互動校稿 + 即時貼 context?開 web/studio.html
```

詳細選項見 § Development & Build;規則見 § 核心鐵律;架構原則見下一節。

---

## 核心架構原則(2026-04 升級引入)

以下四條原則**優先於**所有其他規範。違反任何一條必須先修正架構,不得靠「叮嚀 LLM」繞過。

### 原則 1 — SRT 不可變(Immutability)
Groq 轉錄產出的 `transcript.srt` 是原始證據,任何後續校稿**不得回寫**原檔。
- 要合併/加標題/分段 → 產物是 `cleaned.md`(時間軸刻意丟棄)
- 要保留時間軸的校稿版 → 產物是 `transcript.cleaned.srt`(見原則 2)

### 原則 2 — 結構保留型校稿(LLM 看不到時間軸)
透過 `scripts/qaqc_phase_b.py --mode structured`:
```
SRT → Python parse → [(tc_1, text_1), ..., (tc_N, text_N)]
                          ↓
              LLM 只看 text 陣列(無時間軸,JSON)
                          ↓
              output 陣列 + 原 timecode 重組 → cleaned.srt
```
- 強制 `len(input) == len(output)`,不符即拒絕(fallback 回原文字)
- LLM 永遠看不到 `00:00:12,000 --> 00:00:17,000`,不可能改到
- 這是**架構性保護**,不是 prompt 叮嚀

### 原則 3 — Context 綁 Session,不綁專案
- 專案根層**禁止**長駐 `context.txt`
- 每次處理前,使用者提供「本次背景資料」(貼文字 / 指定 .txt 路徑)
- `scripts/session.py` 自動寫入 `sessions/<slug>/context.txt`
- Groq 轉錄只從 session 目錄讀 context(`groq_transcribe.py:129-136`),**不再 fallback 到 `SRT/context.*`**
- 範例檔位於 `SRT/context.example.txt`(僅供參考,不會被自動載入)

### 原則 4 — Session 容器
每次音檔 = 一個 session 目錄:
```
sessions/
  2026-04-24_No-84-Changping-St-33/
    source.m4a              # 原音檔 symlink(不複製,省空間)
    context.txt             # 本次 context
    transcript.srt          # Groq 輸出 — IMMUTABLE
    cleaned.srt             # Phase A 清理後 SRT(時間軸保留,僅錯字替換)
    cleaned.md              # Phase A+B 合併校稿 markdown
    transcript.cleaned.srt  # (選)結構保留型校稿 SRT
    notes_<identity>.md     # (選)好學生筆記
    corrections.json        # 本 session 手動校正紀錄(待人工推送至 dict/)
    metadata.json           # 字數比率、耗時、統計
    .phase_b_pending.json   # (CLI engine 模式)Phase B 待 agent 接手的 marker
    .step_3_pending.json    # (CLI engine 模式)Step 3 待 agent 接手的 marker
    .step_4_pending.json    # (CLI engine 模式)Step 4 待 agent 接手的 marker
```

### 原則 5 — Engine Routing(誰開的就由誰執行)
Pipeline 任何需要 LLM 的階段(Phase B 校稿、Step 3 補名詞、Step 4 立場筆記)都
**先確認 host engine 才決定怎麼執行**,不再無腦打 Gemini API。

`scripts/session.py` 啟動時偵測 host:

| 偵測信號 | engine | 行為 |
|---|---|---|
| `$CLAUDECODE` 設定 | `claude` | 寫 marker,**不打任何 API**,等 Claude Code 對話 agent 接手 |
| `$GEMINI_CLI` 設定 | `gemini` | 寫 marker,**不打任何 API**,等 Gemini CLI 對話 agent 接手 |
| `$GITHUB_COPILOT_CLI` 設定 | `copilot` | 同上,等 Copilot CLI 接手 |
| 無信號 + `--engine api` | `api` | 走 `qaqc_phase_b.py` 打 Gemini API(純 shell/cron 用) |
| 無信號 + 沒指定 | `none` | 跳過 Phase B/Step 3/Step 4,印 warning(防呆) |

**Why:** 2026-04-27 跑 0425.mp4 時,session.py 在 Claude Code 環境下盲目打 Gemini API,
SSL → 503 → 429 quota 連環掛,1 小時白做。CLI host 用 OAuth login token 計費,
打 API key 是雙重消費 + 燒錯 quota。詳 memory `feedback_auth_model_split.md`。

**Auth 雙軌總表(本專案的核心 auth 設計):**

| 入口 | LLM Auth | Groq Auth |
|------|----------|-----------|
| Claude Code CLI | OAuth login token(免 API key) | API key |
| Gemini CLI | OAuth login token(免 API key) | API key |
| GitHub Copilot CLI | OAuth login token(免 API key) | API key |
| 純 shell / cron | 用 .env 的 `GEMINI_API_KEY` | API key |
| Web (studio.html) | 使用者貼 user-supplied API key | 使用者貼 user-supplied API key |

Web 為什麼保留 Gemini API key 欄位是 **刻意的普及策略**:Gemini key 取得門檻最低
(Google AI Studio 一鍵免費發 key),不要因為 CLI 不需要就拿掉 Web 欄位。

**Marker file 契約**(agent 接手協議):

當 agent(Claude/Gemini/Copilot)在 session 目錄看到任一 `.<stage>_pending.json`:

1. 讀 marker 取得 `input_file`、`output_file`、`rules_ref`、字數區間、`instructions`
2. 套對應規則(Phase B → § QAQC 標準;Step 3 → § Step 3;Step 4 → § 好學生筆記規範)
3. 中文字數驗證落在 `target_chinese_chars_min`–`max` 之間
4. 寫回輸出檔
5. **刪除 marker**(代表已完成)
6. 更新 `metadata.json` 的對應 stats 區塊,`actor` 改成 agent 自己

Marker file 之間有依賴順序:`phase-b → step-3 → step-4`。處理時依序進行,
若使用者只跑到 phase-b,不會有後兩個 marker;只跑到 step-3 不會有 step-4。

### 原則 6 — 算力分工:確定性工作用工具,LLM 只做判斷(2026-05 引入)

**語言模型是拿來「處理事情(判斷)」的,不是拿來做自動化的。** 凡是確定性、機械性的步驟,
**一律寫成/呼叫腳本工具**,不要用 LLM 逐字硬幹;LLM(對話 agent)只保留給真正需要判斷的環節。

| 該用工具(確定性) | 該用 LLM(判斷) |
|---|---|
| Groq 轉錄、SRT parse、去時間軸、套字典、丟幻覺/空段、合併段落、md→HTML、Firebase 部署、字數 QAQC | 翻譯、語意幻覺(文法通順但內容虛構)的辨識、專名/人名校正、風格決策 |

**Why:** 2026-05 處理 Koshi Cafe 四檔時,使用者明確要求「以省 LLM 算力為目標、善用工具、用完一個再做下一個」。
照此把轉錄/清理/合併/出版全交給腳本,LLM 只做翻譯與名稱判斷,又快又省。

**做法守則:**
- 多檔批次**一個做完再做下一個**(sequential),不要平行燒算力。
- 一個階段 = 一支可重用工具(`scripts/lang/`、`scripts/`),需要重跑時是「一行指令」,不是重新請 LLM 做一遍。
- 發現自己在「用 LLM 重複做某件機械事」→ 停下來,改寫成腳本。

---

## Architecture

### Web Component (`/web`)

- **`index.html`**: Main single-page interface with 13 core sections, Intersection Observer, iframe drawer
- **`studio.html` + `studio.js`**: 好學生筆記工作室 — 4-step client-side AI pipeline
  - Step 1: Upload audio → Groq Whisper transcription → SRT
  - Step 2: QAQC cleanup + Gemini polish (editable preview/edit tabs)
  - Step 3: Keyword-driven knowledge supplement
  - Step 4: Identity-based Good Student Notes generation
- **`dict-loader.js`**: 從 `/dict/*.json` fetch 共用字典(CLI/Web 對齊)
- **`config.local.js`**: Local API keys (gitignored), auto-loaded on dev
- **`config.local.example.js`**: Template for other users
- Step 4 末端支援 **匯出 Session ZIP**,解壓後結構與 CLI 的 `sessions/<slug>/` 同構

### CLI Skill (`/.claude/skills/good-student-notes`)

- **`SKILL.md`**: Skill 定義,使用者透過 `/good-student-notes` 呼叫
- **`scripts/groq_transcribe.py`**: Groq Whisper 單檔轉錄(從 `.env` 讀 key,只從輸入檔同目錄讀 context.txt)

### Shared Scripts (`/scripts`)

- **`session.py`**: Pipeline 統籌器 — `python3 scripts/session.py new <audio> [--context] [--domain] [--identity]`
- **`qaqc_phase_b.py`**: Gemini-powered Phase B(支援 merged 與 structured 兩模式)
- **`lang/`**: 多語系轉錄/清理腳本(見 `scripts/lang/README.md`)。目前有 `it/`(義大利文),未來可擴充 `ja/`、`en/` 等

### SRT Component (`/SRT`)

- **`transcribe.py`**: Standalone Python transcription tool (interactive mode)
- **`qaqc_srt.py`**: Phase A 清理 + `--structured` 模式的結構保留型校稿排程器
- **`context.example.txt`**: Context 格式範例(僅供參考,不會自動載入)

### Shared Dictionaries (`/dict`)

CLI 與 Web 共用同一份資料來源:

- **`typo_dict.json`**: 通用錯字(目前 3 組)
- **`typo_dict.<domain>.json`**: 領域字典(目前有 `parenting`,19 組)
- **`hallucination_prefixes.json`**: Whisper 幻覺段落前綴(11 組,統一基準)
- **`load.py`**: Python 載入器(`load_typo_dict(domain=...)`)
- **`_manifest.json`**: Web 端查可用 domain 的清單

### Sessions (`/sessions`)

所有處理過的音檔產物容器(見原則 4)。CLI 產出與 Web ZIP 匯出同構。

### Docs (`/docs`)

- **`origin-story.md`**: 專案緣起的好學生筆記,本工具的設計藍本

### API Keys

- Stored in project root `.env` (gitignored)
- Format:
  ```
  GROQ_API_KEY=<your-key>
  GEMINI_API_KEY=<your-key>
  ```

### Runtime Dependencies

- **Python ≥ 3.10**(scripts 用了 PEP 604 `str | None` 語法)
- **ffmpeg**(Groq 轉錄前切段所需):`brew install ffmpeg` 或 `apt install ffmpeg`
- **Python packages**:標準庫 + `requests`(`pip install requests`)。核心腳本刻意用 `urllib` 呼叫 Gemini、`requests` 呼叫 Groq,避免 Gemini/Groq SDK 依賴
- **網路連線**:呼叫 Groq(`api.groq.com`)與 Gemini(`generativelanguage.googleapis.com`)API

---

## Development & Build

### Web Development

```bash
# Simply open in browser (no server needed)
open web/index.html

# 或 serve on HTTP(dict-loader.js 需要 HTTP 才能 fetch /dict/*.json;
# file:// 協議下會 fallback 到硬寫字典)
cd web && python3 -m http.server 8080
# 或從專案根:  python3 -m http.server 8080  → http://localhost:8080/web/studio.html
```

**Deployment**: GitHub Pages — `https://shuotao.github.io/GENAI/web/index.html`

### CLI Skill Usage

```bash
# In Claude Code (推薦):
/good-student-notes <audio_file>
/good-student-notes <audio_file> 建築師
/good-student-notes <audio_file> 建築師 --context "糖果家好好睡, 語嫣, RIE 教養" --domain parenting

# 直接呼叫統籌器(同等效果):
python3 scripts/session.py new <audio_file> \
    --context "領域專名詞" \
    --domain parenting \
    --identity 建築師

# 單純做 Phase A(不校稿):
python3 SRT/qaqc_srt.py <in.srt> -o <out.srt> --domain parenting

# 結構保留型校稿(時間軸零變動):
python3 SRT/qaqc_srt.py <in.srt> -o <out.srt> --structured --domain parenting
```

### SRT Standalone Processing

```bash
cd SRT
python3 transcribe.py          # Interactive mode(既有互動模式)
```

---

## 五步驟產物定位(R6)

| Step | 產物 | 本質 | 誰需要 |
|------|------|------|--------|
| Step 1 | `transcript.srt` | 帶時間軸的原始逐字稿 | 字幕、影片編輯索引、法律證據 |
| Step 2 | `cleaned.md` | **去時間軸、合併、通順的串接稿** | **大宗使用者的終點** |
| Step 3 | `enhanced.md` | 專有名詞補充後的稿(非身份置入) | 對內容陌生、需要術語百科 |
| Step 4 | `notes_<立場>.md` | 立場置入的好學生筆記 | 想用自己視角吸收內容 |
| **Step 4.5** | (檢查報告) | **出版前 QAQC**:確認 cleaned.md/toc.json 結構合規(SSoT: [`prompts/publish_qaqc.md § S4.5`](./prompts/publish_qaqc.md)) | 出版前驗收,避免 markdown 不支援的語法、圖檔 `<>` 包覆、漏 toc 等問題 |
| Step 5 | `<slug>.html` + 線上網址 | **分頁式 HTML 出版稿,deploy 到 Firebase `goodedunote` 專案** | 要把筆記做成可分享的網頁 |
| **Step 6** | (審查報告) | **出版後 QAQC**:自動 audit 三本書是否一致(`python3 scripts/publish_qaqc.py`) | 統一書架回連、data.js 完整、OG meta、視覺一致性 |

Web 的差異化定位(未來):Gemini 圖像生成能力(banana pro / gemini-2.5-flash-image)
產出**圖文並茂**的好學生筆記。目前尚未實作,列為 P3 範圍;實作前 Web/CLI 的 Step 4 輸出應文字面一致。

### 原則 7 — Step 5 出版層與 GENAI Web 端是兩個不同層級(2026-05 引入)

Step 5(把任一 markdown 產物轉 HTML 並上線)是**「筆記出版層」**,它的部署目標是 Firebase 的 **`goodedunote`** 專案
(`https://goodedunote.web.app/<slug>/`,每篇筆記一個子路徑)。

**它與 `/web` 的 GENAI Web 端是兩件事,不得混為一談:**

| | Step 5 出版層 | GENAI Web 端(`/web`) |
|---|---|---|
| 內容 | 每一篇處理過的筆記(逐字稿/翻譯/好學生筆記)的 HTML | Physics of Insight 主站 + 好學生筆記工作室 studio |
| 部署 | Firebase `goodedunote` 專案,`--only hosting` | GitHub Pages(`shuotao.github.io/GENAI/web/…`) |
| 工具 | `scripts/lang/en/md_to_html.py`(md→分頁 HTML)+ `scripts/publish_goodedunote.sh`(同步 + deploy) | 既有 `web/` 靜態站 |
| 觸發 | 處理完一篇筆記、要對外分享時 | 改網站本身時 |

**鐵律:跑 Step 5 出版一篇筆記時,絕不去動 `/web` 或 GENAI 的 GitHub Pages 部署。** 兩者層級不同、生命週期不同。
Step 5 只在 `goodedunote` 專案的 hosting 上新增/更新該篇 `<slug>/`,不碰其他專案、不碰 firestore/storage 規則。

### 原則 8 — Step 4.5 + Step 6 出版 QAQC(2026-05-24 引入)

出版流程的「合規關卡」拆成出版前與出版後兩段,規範皆在 SSoT 檔
**`prompts/publish_qaqc.md`**,跟 `prompts/qaqc_core_rules.md` 同一個 SSoT
模式。

| | Step 4.5 出版前 | Step 6 出版後 |
|---|---|---|
| 觸發 | 跑 `publish_goodedunote.sh` 之前 | deploy 後 |
| 形式 | 人/agent 對照 checklist 核對 cleaned.md + toc.json | `python3 scripts/publish_qaqc.py` 自動審 |
| 重點 | Markdown 支援度、圖檔不能用 `<file>` 包覆、slug→shelf 對映表 | 統一書架 back-link、data.js 完整、OG meta、視覺一致性 |
| 失敗時 | 中斷出版,修檔重試 | 修 data.js / 重出版 / 重 deploy |

**Slug → 書架對映表**(出版時必須一致,見 SSoT § S4.5.7):

| 書架 | shelf id | `--back-anchor` | `--back-label` |
|---|---|---|---|
| 公開活動 | `public` | `shelf-public` | `公開活動書架` |
| 研討會 | `seminar` | `shelf-seminar` | `研討會書架` |
| 讀書會 | `reading` | `shelf-reading` | `讀書會書架` |

出版指令必須:
1. 在 `scripts/publish/goodedunote/public/data.js` 的對應 shelf.books 加 entry
   (book.id 必須等於 slug,book.url 用 `./<slug>/` 相對路徑)
2. 跑 `publish_goodedunote.sh` / `md_to_html.py` 時帶上對應的 `--back-anchor`
   + `--back-label`
3. Deploy 後跑 `python3 scripts/publish_qaqc.py` 驗 audit 全綠

---

## 核心鐵律 (Critical Rules)

> **以下規範適用於所有 AI 工具(Claude Code、Gemini CLI、Web Studio)處理逐字稿與筆記的場景。**
>
> **SSoT**: `prompts/qaqc_core_rules.md` 是 Phase A / Phase B / Step 3 / Step 4 規則的**單一真實來源**,
> CLI 與 Web 的 prompt 都從那裡引用。本節為使用者導覽性概述,詳細規則條款請見 SSoT 檔。

### 1. 零省略原則 (Zero Omission Policy)

- **嚴禁**對內容進行摘要、總結或改寫
- 原始音訊所轉錄的每一個句子(除了純粹的語助詞外)都必須完整保留
- **禁止**使用「講者介紹了...」、「第一部分提到...」等第三人稱描述性寫法
- 必須保留第一人稱的原話

### 2. 嚴格的「整理」定義

「整理」僅指:
- 移除時間軸與序號(**僅在產 markdown 時**;產 SRT 時不動時間軸)
- 移除贅字(呃、嗯、那個——僅作發語詞時)
- 合併破碎斷行
- 加入 Markdown 標題
- 補上標點符號與接續詞

「整理」**絕不包含**:刪減句子、濃縮段落、改變語氣

### 3. QAQC 標準

#### Phase A:自動清理(確定性,Python 實作)
1. **移除幻覺段落**:以 `dict/hallucination_prefixes.json` 前綴開頭者整段丟棄
2. **過濾亂碼**:中文字比例 < 25% 的段落(Web 端;CLI 待補)
3. **錯字修正**:套用 `dict/typo_dict.json` + `dict/typo_dict.<domain>.json`(疊加)
4. **不動時間軸**:僅替換 text,時間戳原樣保留

#### 幻覺清理是「兩層」的(2026-05,跨語系實戰補充)

Whisper 的幻覺集中在**靜音/音樂/掌聲/休息/開場墊場**等非語音段。處理分兩層:

**第 1 層 — 確定性過濾(腳本做,抓大宗)**,常見樣態:
- **prompt 回放**:Whisper 把我們給的 prompt 吐回來(中文「內容包含…」、英文 `Key terms…`)→ 整句丟。
- **影片字幕殘留幻覺**:`The END`、`Subtitles by the Amara.org community`、`Thank you for watching`、`END OF TRANSCRIPT`、`Transcription by …`、`CC by …`。
- **跨語系亂碼**:英文場冒出韓/西里爾/CJK、中文場冒出韓/泰/拉丁重音字 → 多 script 混雜即丟(但 Latin-1 重音如 ä/é/ñ 屬正常人名,勿誤殺)。
- **低資訊**:純標點/空白、結尾一串全大寫拉丁(如 `MING PAO TORONTO`)、極短雜訊。
- 工具:中文 `SRT/qaqc_srt.py`(`is_garbled` + 前綴);跨語系/英文用 `scripts/lang/srt_clean_md.py`、`scripts/lang/en/srt_zhtw.py` 的幻覺樣式表。

**第 2 層 — 語意幻覺(LLM/agent 判斷,腳本抓不到)**:
- 「**文法通順但內容虛構**」的段落(例:技術演講開場音樂處冒出「marine oil / 某某海灘 / coffee shop」這種與主題無關的流暢句),charset/前綴都過不了,只能靠 agent 讀內容、對照議程判斷後**列入 drop 清單**再由腳本剔除。
- 原則:第 1 層能抓的絕不勞動 LLM(見原則 6);第 2 層只挑「機器判不出」的少數送 agent。

#### 名稱與專名校正(F1,2026-05 引入)

**ASR 對人名/專名錯得最離譜,一律以權威來源為準,不信 ASR、也別只信手寫筆記。**
- 人名/單位:以**官方報名表、議程、講者官網**為準(實例:`Michi`→**Nicci**、`子榮`↔**芷瑢**、`Ligora`→**Legora**、`Drlib`→**Doctolib**、`Windsor`→**Windsurf**)。
- 英文技術演講的系統性誤聽:**「Claude」常被聽成「Cloud / quad」**(→ Claude Code / Claude API / Claude Platform);可進英文場校正字典。
- 能確定的對應就寫進字典/glossary 做**確定性替換**;名單不齊時**先問使用者要官方資料**,不要猜。

#### Phase B:AI 校稿(強化量化校驗,Gemini 2.5 Flash 實作)
1. 補上標點符號(句號、逗號、問號、驚嘆號、頓號)
2. 在語意斷裂處補上接續詞(然後、接著、也就是說、所以)
3. 合併破碎斷行為完整段落
4. 依語意分段(每 300-500 字或話題轉換時)
5. 插入 Markdown 標題(## 或 ###),標題是插入在段落之間,不能取代原文
6. **量化檢查(Quantitative Validation)**:
   - **字數指標**:輸出字數(MD)必須落在原始有效字數(SRT 去除時間戳)的 **95% - 105%** 之間
   - **分段處理**:長文本以 50-100 行為一組逐段對齊校稿(Claude 手動時),自動 pipeline 一次送給 Gemini(context window 夠)
   - **禁令**:嚴禁使用摘要式詞彙(如「講者介紹了」、「接著討論」等)
7. **結構保留選項(`--structured`)**:若需產出保留時間軸的校稿 SRT,強制以 JSON 陣列往返 LLM,`len(in) == len(out)` 不符即拒絕

### 4. 好學生筆記規範

**前提**:使用者必須指定專業身份,否則不生成筆記

生成規則:
1. **完整保留原文**,每一段都必須出現,**字數檢查標準同 QAQC Phase B**
2. 在段落或重要概念之後加入專業視角類比區塊:
   ```markdown
   > 🎯 **[身份]視角**
   >
   > - **類比**:[用該專業術語重新詮釋]
   > - **應用**:[在該專業工作中如何應用]
   > - **連結**:[與已知概念的關聯]
   ```
3. 開頭加入學習摘要框(📝)
4. 結尾加入核心洞察(💡)
5. 類比必須在邏輯上合理且有意義
6. 補充區塊上下各保留一個空行

### 5. 錯誤樣態對照表

| 錯誤類型 | ❌ 錯誤 | ✅ 正確 |
|---------|---------|---------|
| 摘要化 | "講者介紹了 Transformer 的架構。" | 保留原話全文 |
| 第三人稱 | "第一部分討論了分析方法。" | 保留第一人稱敘述 |
| 省略細節 | 刪除講者舉例的細節 | 完整保留所有舉例 |
| 過度清洗 | 刪除「我覺得」等語氣詞 | 保留適度語氣詞以維持現場感 |
| 壓縮產出 | 字數低於原文 95% | 字數維持在 95% - 105% 區間 |
| 時間軸被重組 | LLM 直接讀 SRT 產 cleaned.srt | 用 `--structured` 讓 LLM 只看 text 陣列 |

### 6. 最終檢查清單 (強制執行)

- [ ] 所有教學內容與細節已保留?
- [ ] 產物正確歸位在 `sessions/<slug>/`(不在 root)?
- [ ] `transcript.srt` 完全未被修改?
- [ ] 贅字已適當移除(不影響語意)?
- [ ] 加入了適當的 Markdown 標題?
- [ ] 未將內容轉寫為摘要或文章體裁?
- [ ] 補上了標點符號與接續詞?
- [ ] **字數校驗:輸出字數是否落在原始有效字數的 95% - 105% 之間?**
   - **(E1)同口徑比對**:來源與產物要用「相同方式」算(都去空白、都排除圖片語法 `![..](..)`),否則會出現假性落差。曾因「來源含空格、正文去空格」誤報 95% 虛驚。
- [ ] **是否排除了所有「講者提到」、「本段討論」等第三人稱摘要詞?**
   - **(E2)分清「誰在摘要」**:禁的是**我方(整理者)**寫的第三人稱摘要;若是**講者本人原話**裡說「另一個講者提到…」,那是第一人稱原話,**必須保留**,不是違規(掃描禁詞時別誤判)。
- [ ] **(E3)翻譯類產物:原文段落數 == 譯文段落數(1:1 對齊)** 作為零省略的對齊檢查。
- [ ] **(E4)字數/cue 校驗要對照「原始全部 cue」,不是「清理後存活的 cue」。** 否則**清理階段的誤刪**永遠抓不到。實例:2026-05 zh 清理器把雙語場的英文句整段當亂碼丟,因為當時只比對「存活集」對「合併稿」(100%),漏看了「原始 SRT → 存活集」這一段的流失。**保留率要從 Step 1 原始 cue 一路追到最終產物。**
- [ ] 若有新發現的錯字,是否寫入 `sessions/<slug>/corrections.json`(而非直接改 `dict/`)?

---

## Context 生命週期

- **寫入**:由使用者在呼叫 CLI 時透過 `--context` 提供,或 Web 端 Step 1 textarea 填寫
- **儲存**:`sessions/<slug>/context.txt`(本 session 專屬)
- **讀取**:Groq 轉錄時作為 Whisper prompt(注意 896 **字元**上限,見 Common Gotchas #1);Phase B 時作為專名校正參考
- **生命週期結束**:session 結束,context 就封存在該 session 目錄內,**絕不被下一個 session 自動沿用**

**過去問題案例**:`SRT/context.txt` 長駐專案,是上個 PicCollage meetup 的殘留,卻在處理育兒主題音檔時被自動當 prompt,汙染辨識。升級後此 fallback 已移除(`groq_transcribe.py:129-136`)。

---

## Session 生命週期

1. `python3 scripts/session.py new <audio>` → 建立 `sessions/<slug>/`
2. 執行:symlink audio → 寫 context → Groq 轉錄 → Phase A → Phase B(選)→ Step 3(選)→ Step 4(選)→ Step 5 出版(選)
3. 使用 `--stop-at` 控制終止點:`transcribe`、`phase-a`、`phase-b`(預設)、`enhance`、`notes`(Step 1–4)。**Step 5 出版不是 session.py 的 stop-at**,而是獨立指令 `scripts/publish_goodedunote.sh`(見原則 7)
4. 使用者檢視 `cleaned.md`,若發現錯字,寫入 `corrections.json`(**不直接改 `dict/`**)
5. 數個 session 累積同樣誤判後,人工審閱把 `corrections.json` 條目 merge 進 `dict/typo_dict.<domain>.json`
6. Session 完成後不應修改 `transcript.srt`(原則 1);可重跑 `--structured` 產額外的 `transcript.cleaned.srt`

### 停點原則(R6.2)

五個步驟的產物都是**合法終點**。不要預設每次都要跑到 Step 4/5 —— 大宗使用者在 Step 2
(cleaned.md,去時間軸、合併、通順)就已滿足。設計上:

- CLI:`--stop-at phase-b` 是預設;指定 `notes` 才會跑到 Step 4
- Step 5(出版)是**獨立、可選**的最後一層,以 `scripts/publish_goodedunote.sh` 執行(非 session.py 的 stop-at):把任一 md 產物轉 HTML 並 deploy 到 `goodedunote`(見原則 7),**不會、也不該觸發 GENAI `/web` 的更新**
- Web:每一步後按「📦 匯出 Session ZIP」即可終止。ZIP 的 `metadata.json.stop_at` 反映實際完成的深度

---

## Common Gotchas(實戰踩過的坑)

這幾個是本專案實際開發時踩過的坑,寫下來避免重蹈:

1. **Groq Whisper prompt 有 896 字元上限**(characters,**不是 bytes**)
   - 2026-05 實測 400 訊息:`prompt length must be 896 characters or fewer, but provided prompt contains 931 characters` → Groq 數的是**字元數**
   - **歷史更正**:本條原寫「896 bytes / ≤290 中文字」,是 2026-04 第一次踩錯時的誤判。byte 上限只是字元上限的更嚴格子集 → 舊的 byte 裁切**不會 400**,但會把中文 context 砍到只剩 ~290 字,白白浪費 ⅔ 容量、減少送進 Whisper 的領域詞、降低辨識品質
   - 解法:送 Groq 前確認整段 prompt(base + 內容包含 + context + 。)**≤ 896 字元**(中文用 `wc -m`,不是 `wc -c`)。CLI `groq_transcribe.py:truncate_prompt` 與 Web `studio.js:callGroqWhisper` 已統一按字元裁切

2. **macOS APFS 是 case-insensitive filesystem**
   - `Gemini.md` 與 `GEMINI.md` 視為同一 inode
   - 要改檔名大小寫時:`mv Gemini.md _tmp.md && mv _tmp.md GEMINI.md` 兩步走,避免誤操作
   - 2026-04-24 把 Gemini.md 重整為 GEMINI.md 時踩到

3. **`dict-loader.js` 需要 HTTP 協議才能 fetch `/dict/*.json`**
   - `file://` 下瀏覽器安全政策擋 fetch,會 fallback 到 studio.js 硬寫的 3 組通用字典
   - 用 `cd web && python3 -m http.server 8080` 才能看到完整 22 組 parenting 詞典
   - GitHub Pages 部署下路徑會是 `/GENAI/dict/`,`dict-loader.js` 用 `../dict/` 相對路徑正確解析

4. **Gemini LLM 讀 SRT 會動時間軸** — 這是架構原則 2 的起源
   - 產「保留時間軸的校稿 SRT」務必走 `--structured`:Python 拆結構、LLM 只看 text 陣列、Python 重組
   - 不要讓 LLM 直接讀 SRT 產 SRT,必失敗

---

## Git-as-Knowledge-Base 機制

Web 沒有後台、不能自己累積校正資料,但可以透過 **git 版控當作分發管道**:

```
CLI session 發現錯字 → sessions/<slug>/corrections.json   [本地]
         ↓ 人工審閱、多 session 交叉驗證
         ↓ 推進 dict/typo_dict.<domain>.json
git commit + push                                         [共享]
         ↓
Web 使用者 git pull(或瀏覽器下次 reload)
  dict-loader.js 抓 dict/_manifest.json(讀 version)
         ↓
  以 `?v=<version>` 做 cache-bust 抓 typo_dict*.json       [生效]
```

**關鍵機制**:
- `dict/_manifest.json` 的 `version` 欄位是 cache busting 信號。**新增字典條目後務必 bump version**
- `dict-loader.js` 每次 fetch 都帶 `?v=<version>`,確保 GitHub Pages / CDN 不會送舊檔
- 使用者不需要 hard-reload,只要 git pull 或頁面 reload,Web 端就同步最新字典
- **這是 Web 的「後台替代品」** — 不需要 backend service,git push 即分發

### 貢獻新字典條目的 SOP

1. 處理多個同領域 session,觀察 corrections.json 中**反覆出現**的同組誤判
2. 把這組誤判加入 `dict/typo_dict.<domain>.json`(若是通用錯字則加 `typo_dict.json`)
3. bump `dict/_manifest.json` 的 `version`(例:`2026-04-24.1` → `2026-04-24.2` 或 `2026-05-01.1`)
4. 新增 domain 時,同步更新 `_manifest.json` 的 `domains` 陣列
5. git commit + push,下次 Web 使用者自動拿到

---

## 多語系腳本慣例

- 中文版是主線,由 `scripts/session.py` → `.claude/skills/good-student-notes/scripts/groq_transcribe.py`
- 其他語言的實作放 `scripts/lang/<ISO639-1>/`(目前有 `it/`)
- 若日後抽象化,建議把共用骨架抽到 `scripts/lang/core.py`,各語言作為 adapter
- 詳見 [`scripts/lang/README.md`](./scripts/lang/README.md)

---

## 輸出檔案命名規範

| 用途 | 位置 |
|------|------|
| 原音檔 symlink | `sessions/<slug>/source.<ext>` |
| 本次 context | `sessions/<slug>/context.txt` |
| Groq 轉錄(不可變) | `sessions/<slug>/transcript.srt` |
| Phase A 清理後 SRT | `sessions/<slug>/cleaned.srt` |
| Phase A+B 合併校稿 | `sessions/<slug>/cleaned.md` |
| 結構保留型校稿 SRT(選) | `sessions/<slug>/transcript.cleaned.srt` |
| 好學生筆記(選) | `sessions/<slug>/notes_<identity>.md` |
| 手動校正紀錄 | `sessions/<slug>/corrections.json` |
| 統計與 metadata | `sessions/<slug>/metadata.json` |
| Web 匯出 ZIP | `<slug>.zip`(內含同結構) |

所有檔案統一使用 **UTF-8** 編碼。

---

## Key Files & Paths

| Purpose | Path |
|---------|------|
| Main website | `/web/index.html` |
| 好學生筆記工作室 | `/web/studio.html` + `/web/studio.js` |
| Web 字典載入器 | `/web/dict-loader.js` |
| CLI Skill 定義 | `/.claude/skills/good-student-notes/SKILL.md` |
| Groq 轉錄腳本 | `/.claude/skills/good-student-notes/scripts/groq_transcribe.py` |
| Pipeline 統籌器 | `/scripts/session.py` |
| Gemini Phase B | `/scripts/qaqc_phase_b.py` |
| 多語系腳本 | `/scripts/lang/` |
| 英文轉錄(Groq, language=en) | `/scripts/lang/en/groq_transcribe_en.py` |
| 結構保留型翻譯(EN→zh-TW;原則 2) | `/scripts/lang/en/srt_zhtw.py`(prep/assemble + 時間軸 byte 驗證) |
| SRT → cleaned.md(翻譯版,讀 zh_parts) | `/scripts/lang/en/srt_to_md.py` |
| SRT → cleaned.md(直接清理合併,zh/en) | `/scripts/lang/srt_clean_md.py` |
| **Step 5** md → HTML | `/scripts/lang/en/md_to_html.py`(單頁 SPA 或 `--multipage` 每場一頁;`--cover` 封面 hero + OG 預覽圖;`--base-url` 給 OG 絕對網址;圖片大圖/並排/佔位 alt 抑制;字數 QAQC)。**hash `#fragment` 無法做各章節各自社群預覽 → 多頁模式每場獨立網址 + 各自 `og:image`(該場第一張圖,無圖用封面)** |
| **Step 5** 圖片壓縮 + EXIF 轉正 | `/scripts/compress_images.py`(出版前壓縮省流量、把手機側拍照轉正) |
| **Step 5** 出版到 Firebase goodedunote | `/scripts/publish_goodedunote.sh`(多頁 HTML + 壓圖 + `deploy --only hosting`;自動帶 `--base-url`) |
| **Step 5** goodedunote 部署根(累積所有筆記) | `/scripts/publish/goodedunote/`(每篇 `public/<slug>/`) |
| Standalone 轉錄 | `/SRT/transcribe.py` |
| QA/QC 腳本 | `/SRT/qaqc_srt.py` |
| Context 範例檔 | `/SRT/context.example.txt` |
| 共用字典 | `/dict/typo_dict*.json`、`/dict/hallucination_prefixes.json`、`/dict/_manifest.json` |
| 字典載入器 | `/dict/load.py`(Python)、`/web/dict-loader.js`(Web,cache busting 版) |
| **SSoT 規則文件** | `/prompts/qaqc_core_rules.md`(Phase A/B、Step 3/4 的核心鐵律) |
| Session 容器 | `/sessions/<slug>/` |
| 專案敘事起源 | `/docs/origin-story.md` |
| API Keys | `/.env` (gitignored) |
| 本文件 | `/CLAUDE.md` (唯一規範) |
| Gemini CLI 入口 | `/GEMINI.md` (10 bytes 指路檔,內容 `CLAUDE.md`) |
| Codex/AGENTS 入口 | `/AGENTS.md` (10 bytes 指路檔,內容 `CLAUDE.md`) |

---

## Project Structure Decisions

- **Session 容器化**:每個音檔處理 = `sessions/<slug>/` 單一目錄,完整、可攜、可獨立歸檔
- **Single Source of Truth (字典)**:`dict/` 是 CLI 與 Web 共用的唯一字典來源,`dict/load.py` 與 `web/dict-loader.js` 分別為兩端的 adapter
- **Relative paths throughout**: All web assets use relative paths for flexibility
- **No server required (mostly)**: Pure static site for web;但 `dict-loader.js` 需 HTTP 才能 fetch(file:// 下會 fallback 到硬寫字典)
- **Single source of truth (規範)**: CLAUDE.md 是唯一規範。Agent.md、SRT_QA_QC_檢查清單.md 等為歷史參考
- **API keys via .env**: Never hardcode keys; `.env` is gitignored
- **多語系擴展**:新增語言在 `scripts/lang/<ISO639-1>/`,不需改主線
- **雙軌授權**:程式碼 MIT(`LICENSE`)+ 內容 CC BY 4.0(`LICENSE-CONTENT`)
  + 講者話語講者保留(`NOTICE`)。所有出版頁 footer 自動套授權行,
  root index 也壓在最底。**新增任何引用第三方內容前**,先看 `NOTICE` 確認層級。
