# 專案架構與開發指令(docs/architecture.md)

> 自 `CLAUDE.md` 移出(2026-10-12 重構)。CLAUDE.md 是專案憲法,
> 只留原則與索引;本檔是它指向的參考資料。

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
- **`lang/`**: 多語系轉錄/清理腳本(見 `scripts/lang/README.md`)。目前有 `it/`(義大利文,歷史參考)、`en/`(英文)、`ja/`(日文);跨語系格式工具(`srt_clean_md.py`、`vtt_to_txt.py`)放 `lang/` 根

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

