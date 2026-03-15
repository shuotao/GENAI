# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.
It is the **single authoritative specification** for all AI-assisted workflows in this project.

- **Gemini CLI** 使用者請參考 `Gemini.md`（指向本文件）。
- 本文件整合了原 `SRT/Agent.md` 的全部規範（v2.1）。

---

## Project Overview

**"The Physics of Insight"** is a dual-purpose project:

1. **Interactive Web Platform** (`/web`): Static HTML/CSS/JS website + 好學生筆記工作室（client-side AI pipeline）
2. **CLI Workflow** (`.claude/skills/good-student-notes`): Terminal-based transcription + notes generation via Claude Code or Gemini CLI

The project emphasizes "compression vs. expansion" and bridging knowledge silos.

---

## Architecture

### Web Component (`/web`)

- **`index.html`**: Main single-page interface with 13 core sections, Intersection Observer, iframe drawer
- **`studio.html` + `studio.js`**: 好學生筆記工作室 — 4-step client-side AI pipeline
  - Step 1: Upload audio → Groq Whisper transcription → SRT
  - Step 2: QAQC cleanup + Gemini polish (editable preview/edit tabs)
  - Step 3: Keyword-driven knowledge supplement
  - Step 4: Identity-based Good Student Notes generation
- **`config.local.js`**: Local API keys (gitignored), auto-loaded on dev
- **`config.local.example.js`**: Template for other users

### CLI Skill (`.claude/skills/good-student-notes`)

- **`SKILL.md`**: Skill definition, invoked via `/good-student-notes <file> [identity]`
- **`scripts/groq_transcribe.py`**: Groq Whisper transcription (reads `.env` for API key)
- Outputs: `.srt`, `_cleaned.md`, `_good_student_notes.md`

### SRT Component (`/SRT`)

- **`transcribe.py`**: Standalone Python transcription tool (interactive mode)
- **`qaqc_srt.py`**: Quality assurance and cleanup
- **`context.txt`**: Vocabulary context for Whisper accuracy boost

### API Keys

- Stored in project root `.env` (gitignored)
- Format:
  ```
  GROQ_API_KEY=<your-key>
  GEMINI_API_KEY=<your-key>
  ```

---

## Development & Build

### Web Development

```bash
# Simply open in browser (no server needed)
open web/index.html

# Or use local server for full feature testing
cd web && python3 -m http.server 8080
```

**Deployment**: GitHub Pages — `https://shuotao.github.io/GENAI/web/index.html`

### CLI Skill Usage

```bash
# In Claude Code:
/good-student-notes IMG_8384.MOV
/good-student-notes IMG_8384.MOV 建築師

# In Gemini CLI:
# Reference this file and follow the workflow rules below
```

### SRT Standalone Processing

```bash
cd SRT
python3 transcribe.py          # Interactive mode
python3 qaqc_srt.py <file.srt> # Manual QA/QC
```

---

## 核心鐵律 (Critical Rules)

> **以下規範適用於所有 AI 工具（Claude Code、Gemini CLI、Web Studio）處理逐字稿與筆記的場景。**

### 1. 零省略原則 (Zero Omission Policy)

- **嚴禁**對內容進行摘要、總結或改寫
- 原始音訊所轉錄的每一個句子（除了純粹的語助詞外）都必須完整保留
- **禁止**使用「講者介紹了...」、「第一部分提到...」等第三人稱描述性寫法
- 必須保留第一人稱的原話

### 2. 嚴格的「整理」定義

「整理」僅指：
- 移除時間軸與序號
- 移除贅字（呃、嗯、那個——僅作發語詞時）
- 合併破碎斷行
- 加入 Markdown 標題
- 補上標點符號與接續詞

「整理」**絕不包含**：刪減句子、濃縮段落、改變語氣

### 3. QAQC 標準

#### Phase A：自動清理
1. **移除 SRT 元數據**：所有序號與時間軸
2. **移除幻覺段落**：
   - `內容包含：`、`這是一段關於技術開發`、`這是一段繁體中文`
   - `请注意`、`Please note`、`Thank you`、`thanks for`
   - `Subtitles`、`Subscribe`、`字幕由`
3. **過濾亂碼**：中文字比例 < 25% 的段落
4. **常見錯字修正**：剪報→簡報、因該→應該、在來→再來

#### Phase B：AI 校稿
1. 補上標點符號（句號、逗號、問號、驚嘆號、頓號）
2. 在語意斷裂處補上接續詞（然後、接著、也就是說、所以）
3. 合併破碎斷行為完整段落
4. 依語意分段（每 300-500 字或話題轉換時）
5. 插入 Markdown 標題（## 或 ###），標題是插入在段落之間，不能取代原文
6. **字數檢查**：輸出字數必須 ≥ 輸入字數的 95%

### 4. 好學生筆記規範

**前提**：使用者必須指定專業身份，否則不生成筆記

生成規則：
1. **完整保留原文**，每一段都必須出現
2. 在段落或重要概念之後加入專業視角類比區塊：
   ```markdown
   > 🎯 **[身份]視角**
   >
   > - **類比**：[用該專業術語重新詮釋]
   > - **應用**：[在該專業工作中如何應用]
   > - **連結**：[與已知概念的關聯]
   ```
3. 開頭加入學習摘要框（📝）
4. 結尾加入核心洞察（💡）
5. 類比必須在邏輯上合理且有意義
6. 補充區塊上下各保留一個空行

### 5. 錯誤樣態對照表

| 錯誤類型 | ❌ 錯誤 | ✅ 正確 |
|---------|---------|---------|
| 摘要化 | "講者介紹了 Transformer 的架構。" | 保留原話全文 |
| 第三人稱 | "第一部分討論了分析方法。" | 保留第一人稱敘述 |
| 省略細節 | 刪除講者舉例的細節 | 完整保留所有舉例 |
| 過度清洗 | 刪除「我覺得」等語氣詞 | 保留適度語氣詞以維持現場感 |

### 6. 最終檢查清單

- [ ] 所有教學內容與細節已保留？
- [ ] 時間軸與序號已移除？
- [ ] 贅字已適當移除（不影響語意）？
- [ ] 加入了適當的 Markdown 標題？
- [ ] 未將內容轉寫為摘要或文章體裁？
- [ ] 補上了標點符號與接續詞？
- [ ] 輸出字數 ≥ 輸入字數的 95%？

---

## SRT QA/QC 技術規範

### 時間軸修正規則
1. **清理**：提取 `[\d:,]`，過濾髒字符
2. **正規化**：補齊為 `HH:MM:SS,mmm`（毫秒補足3位）
3. **邏輯修復**：
   - `Start Time < End Time`
   - `Next Start >= Previous End`
4. **檔案交付**：另存新檔 `filename_fixed.srt`，不得覆寫原始 SRT

---

## 輸出檔案命名規範

| 用途 | CLI 命名 | Web 命名 |
|------|---------|---------|
| SRT 逐字稿 | `<filename>.srt` | `transcribe.srt` (下載) |
| 合併校稿 | `<filename>_cleaned.md` | `transcript.md` (下載) |
| 知識補充 | N/A (CLI 跳過) | `enhanced.md` (下載) |
| 好學生筆記 | `<filename>_good_student_notes.md` | `good-student-notes.md` (下載) |

所有檔案統一使用 **UTF-8** 編碼。

---

## Key Files & Paths

| Purpose | Path |
|---------|------|
| Main website | `/web/index.html` |
| 好學生筆記工作室 | `/web/studio.html` + `/web/studio.js` |
| CLI Skill | `/.claude/skills/good-student-notes/SKILL.md` |
| Groq 轉錄腳本 | `/.claude/skills/good-student-notes/scripts/groq_transcribe.py` |
| Standalone 轉錄 | `/SRT/transcribe.py` |
| QA/QC 腳本 | `/SRT/qaqc_srt.py` |
| 背景詞庫 | `/SRT/context.txt` |
| API Keys | `/.env` (gitignored) |
| 本文件 | `/CLAUDE.md` (唯一規範) |
| Gemini 指引 | `/Gemini.md` (指向本文件) |

---

## Project Structure Decisions

- **Relative paths throughout**: All web assets use relative paths for flexibility
- **No server required**: Pure static site for web; CLI uses local Python + API calls
- **Single source of truth**: This file (CLAUDE.md) is the only specification. Agent.md content has been fully integrated here.
- **API keys via .env**: Never hardcode keys; `.env` is gitignored
