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
```

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

## 四步驟產物定位(R6)

| Step | 產物 | 本質 | 誰需要 |
|------|------|------|--------|
| Step 1 | `transcript.srt` | 帶時間軸的原始逐字稿 | 字幕、影片編輯索引、法律證據 |
| Step 2 | `cleaned.md` | **去時間軸、合併、通順的串接稿** | **大宗使用者的終點** |
| Step 3 | `enhanced.md` | 專有名詞補充後的稿(非身份置入) | 對內容陌生、需要術語百科 |
| Step 4 | `notes_<立場>.md` | 立場置入的好學生筆記 | 想用自己視角吸收內容 |

Web 的差異化定位(未來):Gemini 圖像生成能力(banana pro / gemini-2.5-flash-image)
產出**圖文並茂**的好學生筆記。目前尚未實作,列為 P3 範圍;實作前 Web/CLI 的 Step 4 輸出應文字面一致。

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
- [ ] **是否排除了所有「講者提到」、「本段討論」等第三人稱摘要詞?**
- [ ] 若有新發現的錯字,是否寫入 `sessions/<slug>/corrections.json`(而非直接改 `dict/`)?

---

## Context 生命週期

- **寫入**:由使用者在呼叫 CLI 時透過 `--context` 提供,或 Web 端 Step 1 textarea 填寫
- **儲存**:`sessions/<slug>/context.txt`(本 session 專屬)
- **讀取**:Groq 轉錄時作為 Whisper prompt(注意 896 bytes UTF-8 上限);Phase B 時作為專名校正參考
- **生命週期結束**:session 結束,context 就封存在該 session 目錄內,**絕不被下一個 session 自動沿用**

**過去問題案例**:`SRT/context.txt` 長駐專案,是上個 PicCollage meetup 的殘留,卻在處理育兒主題音檔時被自動當 prompt,汙染辨識。升級後此 fallback 已移除(`groq_transcribe.py:129-136`)。

---

## Session 生命週期

1. `python3 scripts/session.py new <audio>` → 建立 `sessions/<slug>/`
2. 執行:symlink audio → 寫 context → Groq 轉錄 → Phase A → Phase B(選)→ Step 3(選)→ Step 4(選)
3. 使用 `--stop-at` 控制終止點:`transcribe`、`phase-a`、`phase-b`(預設)、`enhance`、`notes`
4. 使用者檢視 `cleaned.md`,若發現錯字,寫入 `corrections.json`(**不直接改 `dict/`**)
5. 數個 session 累積同樣誤判後,人工審閱把 `corrections.json` 條目 merge 進 `dict/typo_dict.<domain>.json`
6. Session 完成後不應修改 `transcript.srt`(原則 1);可重跑 `--structured` 產額外的 `transcript.cleaned.srt`

### 停點原則(R6.2)

四個步驟的產物都是**合法終點**。不要預設每次都要跑到 Step 4 —— 大宗使用者在 Step 2
(cleaned.md,去時間軸、合併、通順)就已滿足。設計上:

- CLI:`--stop-at phase-b` 是預設;指定 `notes` 才會跑完整條 pipeline
- Web:每一步後按「📦 匯出 Session ZIP」即可終止。ZIP 的 `metadata.json.stop_at` 反映實際完成的深度

---

## Common Gotchas(實戰踩過的坑)

這幾個是本專案實際開發時踩過的坑,寫下來避免重蹈:

1. **Groq Whisper prompt 有 896 bytes UTF-8 上限**(不是字元數)
   - 中文字 UTF-8 是 3 bytes/字 → context 實際 ≤ 約 290 中文字
   - 2026-04-24 第一次處理育兒音檔時就是這個錯,試了 3 次才過
   - 解法:送 Groq 前用 `wc -c` 確認 base prompt + context ≤ 896 bytes

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
