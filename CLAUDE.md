# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.
It is the **single authoritative specification** for all AI-assisted workflows in this project.

> **專案憲法**:本檔是所有 AI 引擎的唯一規範來源。
> 專案根的 `GEMINI.md`、`AGENTS.md` 皆為 **10 bytes 純指路檔**,內容只有一行 `CLAUDE.md`。
> 任何 AI 工具(Claude Code、Gemini CLI、OpenAI Codex、其他 AGENTS.md 相容工具)啟動時
> 讀到對應入口檔,會被引導至本檔。借鑑自 REVIT_MCP_study 專案的極簡憲法邏輯。

本文件整合了原 `SRT/Agent.md` 的全部規範(v2.2 — 2026-04 架構性升級版)。

---

## 文件索引(2026-10-12 重構)

CLAUDE.md 只留**原則、鐵律與索引**;細節在下列參考檔。每個 session 都會載入本檔,
所以參考資料搬出去是為了讓開場成本對得起它的用處。

| 檔案 | 內容 | 什麼時候讀 |
|---|---|---|
| [`docs/tools.md`](./docs/tools.md) | **60 支 `scripts/` 工具的唯一清單**(有閘門) | 要找某支工具、或新增工具時 |
| [`docs/architecture.md`](./docs/architecture.md) | Web/CLI 元件、目錄職責、Runtime 依賴、開發指令 | 改架構或要跑起來時 |
| [`docs/gotchas.md`](./docs/gotchas.md) | 實戰事故紀錄(append-only) | **動 Groq/轉錄/字典/圖片 EXIF 之前必讀** |
| [`docs/model-routing.md`](./docs/model-routing.md) | 哪個 model/CLI 負責哪一段、實測模型清單、低階模型地雷 | 要派工給別的 CLI/模型時 |
| [`docs/admin-backend.md`](./docs/admin-backend.md) | 營運後台(原則 10 的細節) | 碰 admin/ 或名冊時 |
| [`docs/eval-good-student-notes.md`](./docs/eval-good-student-notes.md) | skill 評測報告(Tier 0/1 + 實跑觀察) | 要改 SKILL.md 或評測時 |
| [`prompts/qaqc_core_rules.md`](./prompts/qaqc_core_rules.md) | **SSoT**:Phase A/B、Step 3/4 規則(§ R1–R8) | 校稿時 |
| [`prompts/publish_qaqc.md`](./prompts/publish_qaqc.md) | **SSoT**(781 行,最大):Step 4.5 + Step 6(§ S4.5.x / § S6.x) | 出版時 |
| [`prompts/image_notes_design.md`](./prompts/image_notes_design.md) · [`image_notes_skill.md`](./prompts/image_notes_skill.md) | 圖像視角筆記設計與流程 | 做圖像版時 |

**提交前跑一次 `python3 scripts/tests/test_docs_sync.py`** —— 它斷言工具清單與
`--stop-at` 集合跟程式一致,紅燈不得合併(§ 文件同步守則)。

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
# 閉環(音檔+圖片 → 出版前全自動,deploy 人工按):
scripts/pipeline_autopilot.sh <audio> --images <dir> --context "…"
```

詳細選項見 § Development & Build;規則見 § 核心鐵律;架構原則見下一節。

---

## 三軌分工總表(2026-05-31)— 三個獨立作業面,共用 SSoT、分工不互擾

| 軌 | 介面 | 範圍 | 入口 | 產物落點 |
|---|---|---|---|---|
| **A. CLI 1–6 步** | 終端機 / Claude Code / Gemini CLI | 音檔→逐字稿→清理→補充→筆記→出版 | `python3 scripts/session.py new <audio>`(+ Step 5 `publish_goodedunote.sh`) | `sessions/<slug>/` 根(transcript.srt / cleaned.md / …) |
| **B. Web 工作室** | 瀏覽器 `studio.html` | Step 1–4 客戶端管線 + Step 4 圖文版(CSS 疊加) | 開 `web/studio.html`(使用者自帶 key) | 瀏覽器內 + 匯出 Session ZIP(**不寫 repo**) |
| **C. 圖像版生圖** | Antigravity / Gemini CLI | `/note` 生底稿 → `/好學生筆記` 逐頁 banana 生圖 | `python3 scripts/image_notes_session.py note/notes` | `sessions/<slug>/note/`(base_pNN.png / pNN.png) |

**共用(SSoT,三軌一致):** QAQC 文字鐵律 `prompts/qaqc_core_rules.md`(A、B);圖像視覺規則 6 色/視角 `prompts/image_notes_design.md`(B 圖文版、C);字典 `dict/`(A、B);本檔(全部)。

**分工不互擾(已驗證):**
- **落點不碰撞**:A 寫 `sessions/<slug>/` 根、C 寫 `sessions/<slug>/note/` 子目錄 → 同源材料可共存、無檔案衝突;B 不寫 repo。
- **「好學生筆記」三種產物各有其面、不混淆**:A=文字 `notes_<id>.md`;B=瀏覽器 Step 4(文字 + 可選 CSS 圖文版);C=banana 影像 `pNN.png`。
- **影像 auth 各走各的**(原則 5 + Auth 雙軌表):A 的 CLI 走 login token、**不生圖**;B 用使用者自帶 key 的 CSS 疊加;C 用 Antigravity/Gemini CLI 的影像工具。

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
    .phase_b_pending.json      # (CLI engine 模式)Phase B 待 agent 接手的 marker
    .phase_c_pending.json      # Phase C 標點正規化(§ R7)
    .phase_d_pending.json      # Phase D 通順/hook(§ R8)
    .images_pending.json       # (--images 時)圖片理解,describe_images.py 完成後自刪
    .image_insert_pending.json # (--images 時)自動插圖(§ S4.5.11)
    .step_3_pending.json       # (選)Step 3 待 agent 接手的 marker
    .step_4_pending.json       # (選)Step 4 待 agent 接手的 marker
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

**架構性守門(2026-06-12 引入):** 所有會打 Gemini API 的腳本入口
(`scripts/qaqc_phase_b.py`、`scripts/lang/ja/qaqc_phase_b_ja.py`、
`scripts/lang/ja/gemini_transcribe_ja.py`)在啟動時自查 host 信號
(`$CLAUDECODE` / `$GEMINI_CLI` / `$GITHUB_COPILOT_CLI`),偵測到即拒絕執行並指回
marker 流程;`--force-api` 是唯一逃生口(session.py 在 engine=api 路徑會自帶,
因為統籌器層已做過路由決策)。這堵住了繞過 session.py 直打的路徑
(例:在 Claude Code 裡直接跑 `SRT/qaqc_srt.py --structured`),
與原則 2 同樣是架構性保護而非 prompt 叮嚀。

**Auth 雙軌總表(本專案的核心 auth 設計):**

| 入口 | LLM Auth | Groq Auth |
|------|----------|-----------|
| Claude Code CLI | OAuth login token(免 API key) | API key |
| Gemini CLI | OAuth login token(免 API key) | API key |
| GitHub Copilot CLI | OAuth login token(免 API key) | API key |
| 純 shell / cron | 用 .env 的 `GEMINI_API_KEY` | API key |
| Web (studio.html) | 使用者貼 user-supplied API key | 使用者貼 user-supplied API key |
| **Antigravity CLI headless(被 Claude Code 指揮)** | **自帶 OAuth login(`antigravity -p`)** | —(不經 Groq) |

**Antigravity headless 通道(2026-07-05 引入):** `antigravity -p`(別名 `agy -p`)走
Antigravity 自己的 OAuth login,屬合法 CLI 授權通道;「腳本禁打 Gemini API」守門
只擋 API key 通道。`describe_images.py` 以此通道做圖片理解,單引擎 + 熔斷
(規則見 prompts/publish_qaqc.md § S4.5.11)。

Web 為什麼保留 Gemini API key 欄位是 **刻意的普及策略**:Gemini key 取得門檻最低
(Google AI Studio 一鍵免費發 key),不要因為 CLI 不需要就拿掉 Web 欄位。

**Auth 雙軌的直接後果 — 影像功能的可用性**:好學生筆記的**圖像版**(設計見
[`prompts/image_notes_design.md`](./prompts/image_notes_design.md))需要**影像生成工具**,
能驅動的 host 取決於它有沒有影像通道:

| Host | 影像可用? | 影像通道 |
|------|-----------|---------|
| **Web (studio)** | ✅ | 使用者自帶 Gemini key → `gemini-2.5-flash-image`(Step 4 圖文版,目前走確定性 CSS 疊加;banana 封面 best-effort) |
| **Antigravity** | ✅ | 內建 Nano Banana Pro via MCP |
| **Gemini CLI** | ✅(需裝 extension) | `gemini extensions install …/nanobanana`(`/edit` 吃輸入圖、自動存檔) |
| **Claude Code / Copilot / 純 shell** | ❌ | 走 OAuth login token,無影像工具 |

**好學生筆記圖像版 = 兩階段、無後端自動化**(流程 SSoT
[`prompts/image_notes_skill.md`](./prompts/image_notes_skill.md))。關鍵事實:**腳本叫不動影像工具**(只有 Antigravity / Gemini CLI 的影像 MCP 能生圖),故不做逐頁自動 banana(實測會重複第 1 頁);改成:
- **Stage 1 `/note`**(`image_notes_session.py note <md>`):`md_to_a4_png.py` 用 Playwright 把 md 渲染成 A4 白底底稿 `base_pNN.png`(原文真 DOM、零遺漏)。**底稿與身份無關 → 一份可重複給多職業用。**
- **Stage 2 `/好學生筆記`**(`notes <slug> --identity`):產逐頁提示清單 `banana_prompts_<身份>.md`,然後**逐頁、各自獨立**把 `base_pNN.png` 拖進 Nano Banana 疊視角手寫註解 → `pNN.png`。一次一張 → 流水號正確、不重複(這是避免「多頁都變第 1 頁」的正解)。
(2026-05-31 教訓:逐頁自動 banana 連兩次失敗;結論=工具只做確定性底稿,生圖由 Antigravity/手動一張張做。)

**Marker file 契約**(agent 接手協議):

當 agent(Claude/Gemini/Copilot)在 session 目錄看到任一 `.<stage>_pending.json`:

1. 讀 marker 取得 `input_file`、`output_file`、`rules_ref`、字數區間、`instructions`
2. 套對應規則(Phase B → § QAQC 標準;Step 3 → § Step 3;Step 4 → § 好學生筆記規範)
3. 中文字數驗證落在 `target_chinese_chars_min`–`max` 之間
4. 寫回輸出檔
5. **刪除 marker**(代表已完成)
6. 更新 `metadata.json` 的對應 stats 區塊,`actor` 改成 agent 自己

Marker file 之間有依賴順序:`phase-b → phase-c → phase-d →(images → image-insert,--images 啟用時)→ step-3 → step-4`。處理時**依序進行、逐一清除、清一個驗一個**(原則 9);
Phase A/B/C/D 都在精修同一份 cleaned.md(A/B 產出、C/D 出版前強制精修),Step 3+ 才換產物。
若使用者只跑到 phase-b,仍會連帶產生 `.phase_c_pending.json` / `.phase_d_pending.json`(cleaned.md 出版前強制門);
`--stop-at phase-c` 只產到 Phase C、不產 Phase D;只跑到 step-3 不會有 step-4。

- `.phase_c_pending.json`(stage `phase-c`,SSoT § R7):先跑確定性工具 `scripts/normalize_punctuation.py --in-place`(全形化),再依 § R7.2 補全形冒號;完成後刪 marker、`metadata.json` 的 `qaqc.phase_c.status` 改 `done`。
- `.phase_d_pending.json`(stage `phase-d`,SSoT § R8):依 § R8 補內容指涉型 hook,零省略 1:1;完成後刪 marker、`qaqc.phase_d.status` 改 `done`。
- **出版閘**:`scripts/prepublish_gate.py`(由 `publish_goodedunote.sh` 開頭呼叫)會擋下「2.2/2.5 未 done、marker 殘留、正文仍有 CJK 語境半形標點,或出現 `[文字](網址)` 連結語法(§ S6.14 — 本管線只支援裸網址自動連結)」的出版。

### 原則 6 — 算力分工:確定性工作用工具,LLM 只做判斷(2026-05 引入)

**語言模型是拿來「處理事情(判斷)」的,不是拿來做自動化的。** 凡是確定性、機械性的步驟,
**一律寫成/呼叫腳本工具**,不要用 LLM 逐字硬幹;LLM(對話 agent)只保留給真正需要判斷的環節。

| 該用工具(確定性) | 該用 LLM(判斷) |
|---|---|
| Groq 轉錄、SRT parse、去時間軸、套字典、丟幻覺/空段、合併段落、md→HTML、Firebase 部署、字數 QAQC | 翻譯、語意幻覺(文法通順但內容虛構)的辨識、專名/人名校正、風格決策 |

**Why:** 2026-05 處理 Koshi Cafe 四檔時,使用者明確要求「以省 LLM 算力為目標、善用工具、用完一個再做下一個」。
照此把轉錄/清理/合併/出版全交給腳本,LLM 只做翻譯與名稱判斷,又快又省。

**影像四角色鏈範例(規劃,SSoT § S4.5.11):** Antigravity 讀簡報 → **Codex** 找插入位(只補
`propose_anchors.py` 標低信心的 tail)→ **Haiku** 驅動 `insert_images.py --apply` → **Opus** 驗證。
**插入/去重/驗證永遠留在確定性工具,LLM 絕不放 bytes**——這正是本原則:找位置是判斷(LLM),把圖放進去是機械(工具)。

**做法守則:**
- 多檔批次**一個做完再做下一個**(sequential),不要平行燒算力。
- 一個階段 = 一支可重用工具(`scripts/lang/`、`scripts/`),需要重跑時是「一行指令」,不是重新請 LLM 做一遍。
- 發現自己在「用 LLM 重複做某件機械事」→ 停下來,改寫成腳本。

---

> **架構與開發指令**(Web/CLI 各元件、目錄職責、Runtime 依賴、本機開發與 build 指令)
> 已移出至 [`docs/architecture.md`](./docs/architecture.md)。

## 五步驟產物定位(R6)

| Step | 產物 | 本質 | 誰需要 |
|------|------|------|--------|
| Step 1 | `transcript.srt` | 帶時間軸的原始逐字稿 | 字幕、影片編輯索引、法律證據 |
| Step 2 | `cleaned.md` | **去時間軸、合併、通順的串接稿** | **大宗使用者的終點** |
| **Phase C**(Step 2 內) | (精修 cleaned.md) | **標點正規化**:半形→全形(確定性工具)+ 預告語後改全形冒號「：」(判斷)。SSoT: [`prompts/qaqc_core_rules.md § R7`](./prompts/qaqc_core_rules.md) | cleaned.md 出版前的**強制門**(見原則 9) |
| **Phase D**(Step 2 內) | (精修 cleaned.md) | **通順 / hook**:除接續詞外,補「內容指涉型 hook」(回指/框架/轉折/列點/過場/復述/收束)做前後句承接,零省略。SSoT: [`§ R8`](./prompts/qaqc_core_rules.md) | cleaned.md 出版前的**強制門**(見原則 9) |
| Step 3 | `enhanced.md` | 專有名詞補充後的稿(非身份置入) | 對內容陌生、需要術語百科 |
| Step 4 | `notes_<立場>.md` | 立場置入的好學生筆記 | 想用自己視角吸收內容 |
| **Step 4.5** | (檢查報告 + `build/<slug>/publish.md`) | **出版前 QAQC + 場次狀態收斂**:先 `classify_session.py` 判 A/B/C(分類後停等確認),`build_book_master.py` 把拆檔/一檔多講者都收斂成同一 canonical master,`step45_converge.py` dry-run 驗 `session==toc==##`(SSoT: [`§ S4.5` / `§ S4.5.13`](./prompts/publish_qaqc.md)) | 出版前驗收 + 確保拆檔與一檔多講者出版一致;避免 markdown 不支援語法、圖檔 `<>` 包覆、漏 toc |
| Step 5 | `<slug>.html` + 線上網址 | **分頁式 HTML 出版稿,deploy 到 Firebase `goodedunote` 專案** | 要把筆記做成可分享的網頁 |
| **Step 6** | (審查報告) | **出版後 QAQC**:自動 audit 三本書是否一致(`python3 scripts/publish_qaqc.py`) | 統一書架回連、data.js 完整、OG meta、視覺一致性 |

Web 的差異化定位(未來):**圖像視角好學生筆記** —— 用影像把既有筆記內容**不破壞地**
疊上專業視角(建築師/醫學/會計/工程)的手寫風格註解,讓學習者在原文上「墊高角度」做知識串聯。
**完整設計 SSoT 見 [`prompts/image_notes_design.md`](./prompts/image_notes_design.md)**
(兩階段生成法、4 視角類比庫、prompt 模板、6 色語義系統)。

**狀態(2026-10-12 更正):CLI 兩階段流程已實作** —— `scripts/image_notes_session.py`(note/notes)
+ `scripts/md_to_a4_png.py`(Playwright 產 A4 底稿)+ `.agent/workflows/`、`.gemini/commands/` 入口
+ 流程 SSoT `prompts/image_notes_skill.md` 皆在 repo 內。先前標註「P3,未實作」與事實不符。
未實作的只剩「Web studio 內的圖像版」。**重要:生圖這一段只能在
Web(使用者自帶 API key)+ Antigravity(IDE 可呼叫 Gemini 影像)驅動,CLI 因走 OAuth login token
無法驅動影像 API(見原則 5 + Auth 雙軌表)**。影像引擎:主走 Gemini `gemini-2.5-flash-image`
(banana pro),Web 另規劃 OpenAI/Codex image(gpt-image,使用者自帶 OpenAI key 才出現)選項。

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
1. 在 `scripts/publish/goodedunote/public/data.js` 的對應 shelf.books **尾端 append**
   一筆 entry(book.id 必須等於 slug,book.url 用 `./<slug>/` 相對路徑)。
   **新書一律 append 到陣列尾端 = 書架最右**(舊左新右,`app.jsx` 以陣列序 left→right
   渲染);**不得插在最前面**(會跑到最左)。由 SSoT § S6.9 擋。
2. 跑 `publish_goodedunote.sh` / `md_to_html.py` 時帶上對應的 `--back-anchor`
   + `--back-label`
3. Deploy 後跑 `python3 scripts/publish_qaqc.py` 驗 audit 全綠

**出版拆分單元 = 講者(人),不是主題標題(2026-07-05 引入,SSoT § S4.5.0 / § S6.8):**
- **單一講者的一場分享 = 一篇連續文章,根本不拆 session**:出版帶 `--single`
  (`publish_goodedunote.sh … --single`),`md_to_html.py` 產**單一 `index.html``,
  `##`/`###` 是文章內段落標題(`<h2>`/`<h3>`),**無章節卡、無「下一個」、無 toc.json 需求**;
  data.js 該書標 `single: true`。
- **多位講者的活動** 才用多頁(`--multipage`,每位講者一頁 `session-N.html`,toc 對齊)。
- **Why:** 2026-07-05 把單一講者一場心得硬切成 16 碎頁 / 3 章,連續敘事被切、內容跳接。
  拆分依「講者數」而非主題標題,單人一場就是一整篇。違反由 § S6.8(單篇不得有 session 檔)擋。

**補述層(2026-08-31 引入,SSoT § S4.5.15):** 逐字稿之外可疊一層**補述層** —— 原文一字不改,
在講到某項技術的句子後插入 `>` 引用框標注它對應到哪張看板卡/domain/skill/檔案,另附清單附錄
(先例:`bim-mcp-8` 場 01)。`md_to_html` 已原生渲染 blockquote/表格/清單/`---`;
`insert_images` 的**錨點行空間會排除補述層**,圖只插在講者段落後(零省略驗證仍涵蓋補述框)。
**段落模型仍是「一段落 = 一行」**:`md_to_html.parse()` 會丟掉空行,非 blockquote 的軟斷行
無從判斷段界,跨行 `**粗體**` 也會配不起來 → 由 `prepublish_gate` (3c) 擋下,來源要把軟斷行併掉
(blockquote 內則由 render_blocks 併行處理,不受此限)。
**每個 session 檔仍只能有一個 `#`**(講題行)—— `#` 數是 `classify_session` 判 State A/B 的訊號,
補述層與附錄的標題一律從 `##` 起。

**Step 4.5 場次狀態分類與收斂(2026-07-19 引入,SSoT § S4.5.13):** 錄音來源有兩型態,`cleaned.md`
heading 形狀不同,若直接出版會不一致:
- **State A 拆檔**(N 目錄、每檔 1 個 `#`)/ **State B 一檔多講者**(單檔多個 `#` + 首個 `#` 前的
  `##` 開場 run)/ **State C 單一講者**(1 個 `#`)。由 `scripts/classify_session.py` 確定性判別,
  **分類後停、人工確認場數再往下**(原則 9)。
- A 與 B **都先經 `scripts/build_book_master.py` 收斂成同一 canonical master**(檔頂恰一個 `#`、
  一串 `## 第 N 場 · 類別｜講者`、子標 `###`、`count(##)==toc==場數`),走同一 `emit_canonical` →
  骨架位元等價,Step 5/6 一視同仁。取代寫死的 `build_genai2026_day1/day2.py`。**主持人開場 = 第 0 場**
  (否則被 `md_to_html.parse()` 當 front-matter 靜默丟)。
- `scripts/step45_converge.py --book build/<slug>/book.json` 做 dry-run 收斂 loop(`classify → build →
  prepublish_gate → md_to_html → 結構檢查 session==toc==##`),遇非零即停、**不 deploy**;
  `publish_goodedunote.sh` 加 `DRY_RUN=1` 停在部署前。
- **Why:** 一檔多講者(BIM_MCP_7)直接 `--multipage` 會吞講者 `#`、爆成小節頁、丟開場;收斂到同一
  master 才一致。

### 原則 9 — 逐步獨立執行、不得打包(2026-06-30 引入)

**每個要求的 step 必須「獨立完成且驗證」後,才能進下一步。嚴禁幻覺式自行打包、一口氣把多步跑完。**
必須一步一步驅動出「該用的工具、該走的流程、該套的規範」,以確保輸出一致、可重跑、可稽核,並避免濫用 token。

- **機械步驟一律走工具**(呼應原則 6),**判斷步驟走 marker 交對話 agent**(呼應原則 5);發現自己在用 LLM 重複做機械事 → 停下改用工具。
- **marker 依賴鏈逐一清除**:`phase-b → phase-c → phase-d →(images → image-insert,帶 `--images` 時)→ step-3 → step-4`,
  清一個、驗一個(字數/全形/段落數/圖片分佈等),再清下一個。
- **Phase C / Phase D 是 cleaned.md 出版前的強制門**(原 Step 2.2/2.5;與 Phase A/B 同屬 Step 2 內部、精修同一份 cleaned.md):SSoT [`§ R7`](./prompts/qaqc_core_rules.md) / [`§ R8`](./prompts/qaqc_core_rules.md);由 `scripts/prepublish_gate.py` 在 `publish_goodedunote.sh` 開頭把關,未過不得進 Step 5/6。
- **Why**:2026-06 多場校稿出版時確認,批次打包、一次跑完多步會造成品質崩壞與 token 濫用;拆成獨立可驗收的 step、各自用對工具,結果才一致。

---

### 原則 10 — 後台是出版層的第三個面,與名冊來源嚴格分離(2026-09-01 引入)

`goodedunote.web.app/admin/` 是**營運後台**(文章點擊統計 + 電子報通訊錄),
與 Step 5 出版層共用同一個 Firebase 專案與 hosting,但職責不同。四條鐵律:

1. **GWS 唯讀** —— 名冊來源 `~/Desktop/GWS/data/` 只讀不寫;正規化語義一律 import GWS 的 `_common.py`,絕不自行重寫(重寫必漂移,漂移 = 黑名單靜默失效)。
2. **個資與憑證不進 git** —— `subscribers` 只存 Firestore;金鑰在 `.secrets/`、匯出在 `exports/`,皆 gitignore。
3. **分眾是查詢,不是名單** —— 由 `events.category` + `eventDate` 即時算出;新增報名種類 = 後台新增事件,**不改程式**。
4. **報名事件與名單軌跡不可互相偽裝**;**前端不做權限判斷**(非白名單必須拿到 Firestore `permission-denied`,不是被 CSS 藏起來)。

> 完整說明(資料表對照、三支工具、firestore.rules 設計)見 [`docs/admin-backend.md`](./docs/admin-backend.md)。

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
4. 依語意分段,目標每段 60~120 CJK 字、寧短勿長,一個語意單元(論點/舉例/對話)= 一段(實證:2026-07-11 day2 corpus,詳見 `prompts/qaqc_core_rules.md § R2.1`)
5. 代名詞指涉不清且上下文可確定對象時具體化(它/他→具名),不改語意、不增刪資訊
6. 插入 Markdown 標題(## 或 ###),標題是插入在段落之間,不能取代原文
7. **量化檢查(Quantitative Validation)**:
   - **字數指標**:輸出字數(MD)必須落在原始有效字數(SRT 去除時間戳)的 **95% - 105%** 之間
   - **分段處理**:長文本以 50-100 行為一組逐段對齊校稿(Claude 手動時),自動 pipeline 一次送給 Gemini(context window 夠)
   - **禁令**:嚴禁使用摘要式詞彙(如「講者介紹了」、「接著討論」等)
8. **結構保留選項(`--structured`)**:若需產出保留時間軸的校稿 SRT,強制以 JSON 陣列往返 LLM,`len(in) == len(out)` 不符即拒絕

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

> **圖像視角版(CLI 兩階段已實作;Web 版未實作)**:以上是**文字版**好學生筆記規範。另有「圖像視角版」——
> 把內容**不破壞地**疊上專業視角的手寫風格註解**影像**,完整設計見
> [`prompts/image_notes_design.md`](./prompts/image_notes_design.md)。它只在 Web + Antigravity
> 可驅動(見原則 5 + Auth 雙軌表),目前 Step 4 實作仍為文字版。

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
  - **活動/年會場次的 context 必須包含每位講者人名、公司/產品名、講題核心專名**(ASR 對專名最不可靠,見核心鐵律 F1;實證 2026-07-11:day2 四場 28 條誤聽全是 context 沒涵蓋的專名)。
- **儲存**:`sessions/<slug>/context.txt`(本 session 專屬)
- **讀取**:Groq 轉錄時作為 Whisper prompt(注意 896 **字元**上限,見 Common Gotchas #1);Phase B 時作為專名校正參考
- **生命週期結束**:session 結束,context 就封存在該 session 目錄內,**絕不被下一個 session 自動沿用**

**過去問題案例**:`SRT/context.txt` 長駐專案,是上個 PicCollage meetup 的殘留,卻在處理育兒主題音檔時被自動當 prompt,汙染辨識。升級後此 fallback 已移除(`groq_transcribe.py:129-136`)。

---

## Session 生命週期

1. `python3 scripts/session.py new <audio>` → 建立 `sessions/<slug>/`
2. 執行:symlink audio → 寫 context → Groq 轉錄 → Phase A → Phase B(選)→ Step 3(選)→ Step 4(選)→ Step 5 出版(選)
3. 使用 `--stop-at` 控制終止點(9 個值,以 `scripts/session.py` 的 argparse `choices` 為準):
   `transcribe`、`phase-a`、`phase-b`(預設)、`phase-c`、`phase-d`、`images`、`image-insert`、`enhance`、`notes`。
   其中 `images`／`image-insert` 只在有帶 `--images <dir>` 時才有意義。**Step 5 出版不是 session.py 的 stop-at**,而是獨立指令 `scripts/publish_goodedunote.sh`(見原則 7)
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

> **Common Gotchas(實戰事故紀錄,append-only)** 已移出至 [`docs/gotchas.md`](./docs/gotchas.md)。
> 內含:Groq 896 字元上限、APFS 大小寫、dict-loader 需 HTTP、LLM 讀 SRT 會動時間軸、
> EXIF 轉正、轉錄語言不要硬指定、**吵雜場地的 prompt-echo 幻覺與兩層偵測**。
> 動手前若涉及上述任一主題,先讀該檔。

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
- 其他語言的實作放 `scripts/lang/<ISO639-1>/`(目前有 `it/`、`en/`、`ja/`)
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

> **`scripts/` 工具已移出本表** → 唯一清單在 [`docs/tools.md`](./docs/tools.md)
> (60 支,由 `scripts/tests/test_docs_sync.py` 機械守門)。本表只留**非工具**的關鍵路徑。


| Purpose | Path |
|---------|------|
| Main website | `/web/index.html` |
| 好學生筆記工作室 | `/web/studio.html` + `/web/studio.js` |
| Web 字典載入器 | `/web/dict-loader.js` |
| CLI Skill 定義 | `/.claude/skills/good-student-notes/SKILL.md` |
| 多語系腳本 | `/scripts/lang/` |
| **Step 5** goodedunote 部署根(累積所有筆記) | `/scripts/publish/goodedunote/`(每篇 `public/<slug>/`) |
| **後台** 前端 | `/scripts/publish/goodedunote/public/admin/`(React UMD + Babel standalone,共用主站 `style.css` tokens) |
| **後台** Firestore 規則 / 索引 | `/scripts/publish/goodedunote/firestore.rules`、`firestore.indexes.json` |
| Standalone 轉錄 | `/SRT/transcribe.py` |
| QA/QC 腳本 | `/SRT/qaqc_srt.py` |
| Context 範例檔 | `/SRT/context.example.txt` |
| 共用字典 | `/dict/typo_dict*.json`、`/dict/hallucination_prefixes.json`、`/dict/_manifest.json` |
| 字典載入器 | `/dict/load.py`(Python)、`/web/dict-loader.js`(Web,cache busting 版) |
| **工具清單(唯一家,有閘門)** | `/docs/tools.md`(60 支公開工具一行說明;由 `scripts/tests/test_docs_sync.py` 守門) |
| **多模型角色分工 SSoT** | `/docs/model-routing.md`(哪個 model/CLI 負責哪一段、哪些 live 哪些仍是規劃) |
| **SSoT 規則文件** | `/prompts/qaqc_core_rules.md`(Phase A/B、Step 3/4 的核心鐵律) |
| **出版 QAQC SSoT**(最大一份,781 行) | `/prompts/publish_qaqc.md`(Step 4.5 出版前 + Step 6 出版後;§ S4.5.x / § S6.x) |
| **圖像視角筆記設計 SSoT** | `/prompts/image_notes_design.md`(Step 4 圖像版:兩階段生成、4 視角類比庫、prompt 模板、6 色系統) |
| **連續圖說 skill 流程 SSoT** | `/prompts/image_notes_skill.md`(`/好學生筆記` 多頁連續圖說的 agent 流程:參考圖鎖風格、斷點續存、僅 Antigravity/Gemini CLI) |
| Antigravity 入口 | `/.agent/workflows/note.md`(/note 生底稿)、`/.agent/workflows/好學生筆記.md`(/好學生筆記 生圖) |
| Gemini CLI 入口 | `/.gemini/commands/note.toml`、`/.gemini/commands/好學生筆記.toml`(後者生圖需 nanobanana extension) |
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
- **文件同步守則(2026-10-12 改為閘門制)**:`README.md` 是**非規範**的上手說明,**權威以 CLAUDE.md 為準**;規範不複製進 README,要寫就用指向(`見 CLAUDE.md § …` / `§ Rn`)。
  - **工具清單只有一個家:[`docs/tools.md`](./docs/tools.md)。** 新增/刪除 `scripts/` 公開工具時改那一處即可,不必同時維護 CLAUDE.md Key Files 與 README 的 `/scripts` 清單。
  - **由 `scripts/tests/test_docs_sync.py` 機械守門**(呼應原則 6):T1 每支 `scripts/*.py|sh` 與 `scripts/lang/**/*.py` 都要在 `docs/tools.md`;T2 文件寫的 `--stop-at` 集合必須等於 `session.py` argparse 的 `choices`。**提交前跑一次,紅燈不得合併。**
  - 變動 pipeline 階段、核心原則時,仍須同步 README 的相關段落(stop-at 表由 T2 守,其餘靠人)。
  - **Why**:2026-10-12 盤點發現 23 支工具沒出現在任何文件清單裡(含 2026-09-05 才進 repo 的 `retire_list_label.py`),`--stop-at` 更在 CLAUDE.md 內部自相矛盾(:623 寫 5 個、:184 承認有 phase-c/d、程式實際 9 個)。一條已在 23 個檔案上靜默失效的榮譽制規則,應該換成閘門。
  - 其餘非規範文件(Agent.md、SRT_QA_QC_檢查清單.md 等)為歷史參考,允許過時、不在此同步義務內。
- **API keys via .env**: Never hardcode keys; `.env` is gitignored
- **多語系擴展**:新增語言在 `scripts/lang/<ISO639-1>/`,不需改主線
- **雙軌授權**:程式碼 MIT(`LICENSE`)+ 內容 CC BY 4.0(`LICENSE-CONTENT`)
  + 講者話語講者保留(`NOTICE`)。所有出版頁 footer 自動套授權行,
  root index 也壓在最底。**新增任何引用第三方內容前**,先看 `NOTICE` 確認層級。

---

## 部署完成的定義(2026-07-16 依 /insights 報告新增;附加條款,不取代上述任何原則)

> 本節是原則 7/8/9 的**收尾補強**,不改變任何既有步驟或關卡;
> 逐步獨立執行(原則 9)、prepublish gate、Step 4.5/6 QAQC 照常全部執行。

1. **commit 之後必 push**。本專案有兩個部署層(原則 7):Step 5 筆記出版層
   (Firebase `goodedunote`)與 GENAI Web 端(GitHub Pages,吃 git push 生效)。
   歷史摩擦:多次 commit 沒 push,GitHub Pages / 字典分發(Git-as-Knowledge-Base
   機制靠 push 分發)停在舊版,線上看起來「還是壞的」。
2. **宣告完成前,實際打開線上網址驗證**:
   - Step 5 出版 → 開 `https://goodedunote.web.app/<slug>/` 確認新頁可見、
     無亂碼(mojibake)、書架 back-link 正確(Step 6 audit 之外再加一眼人工確認)。
   - 改 `/web` → push 後開 GitHub Pages 網址確認生效。
3. **兩層部署不互相觸發(原則 7 鐵律)但各自都要收尾**:動了哪一層,就把該層
   deploy/push + 線上驗證做完;若同一次工作兩層都動了,兩層都要收尾,不得只做一半。
4. 長逐字稿/翻譯的產出**分段寫檔**,不要一次性輸出到對話(避免輸出 token 上限);
   拆分只影響輸出方式,零省略 95–105% 字數帶照常適用。
