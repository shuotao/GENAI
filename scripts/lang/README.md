# `scripts/lang/` — 多語系轉錄與清理腳本

這個目錄集中放置**各語言版本**的轉錄、清理、批次處理腳本。中文版的主線是核心工具
(`.claude/skills/good-student-notes/scripts/groq_transcribe.py`),本目錄放其他語言
的並行實作或歷史參考。

## 目錄慣例

子目錄以 [ISO 639-1 語言代碼](https://en.wikipedia.org/wiki/List_of_ISO_639-1_codes) 命名:

```
scripts/lang/
├── it/             # Italian  (義大利文,歷史參考)
├── ja/             # Japanese (日文)
├── en/             # English  (英文)
├── srt_clean_md.py # 跨語系:SRT → cleaned.md(直接清理合併,zh/en)
├── vtt_to_txt.py   # 跨語系:YouTube VTT → 純文字(去重、去標籤,確定性工具)
└── README.md
```

語言特定工具放 `<ISO639-1>/` 子目錄;**不綁語言的格式轉換/清理工具**(如
`srt_clean_md.py`、`vtt_to_txt.py`)放本目錄根。

## 目前內容

### `it/` — 義大利文

2026 年 4 月上旬處理「義大利 Accademia」系列音檔時的批次腳本。當時目標是把連續多支
音檔一次轉完並做 QAQC,因此開發了批次/重試/清理專用工具:

| 檔案 | 作用 |
|------|------|
| `groq_transcribe_it.py` | Groq Whisper 義大利文單檔轉錄(language=it) |
| `batch_accademia.py` | 批次處理 Accademia 系列 — 義大利文路徑 |
| `batch_accademia_en.py` | 批次處理 — 英文路徑(同系列英文講者) |
| `batch_qaqc.py` | 對批次產出的 SRT 做 QAQC 清理 |
| `clean_srt_it.py` | 義大利文 SRT 特定清理(義文語尾、標點) |
| `retry_accademia.py` | 針對失敗 chunk 做重試 |

這些腳本是**歷史參考**而非現役主線 —— 未來若重新處理義大利文音檔,可直接重跑或做為
重構範本。

### `en/` — 英文

| 檔案 | 作用 |
|------|------|
| `groq_transcribe_en.py` | Groq Whisper 英文單檔轉錄(language=en) |
| `srt_zhtw.py` | 結構保留型翻譯 EN→zh-TW(prep/assemble + 時間軸 byte 驗證,原則 2) |
| `srt_to_md.py` | SRT → cleaned.md(翻譯版,讀 zh_parts) |
| `md_to_html.py` | Step 5 出版:md → 分頁 HTML(見 CLAUDE.md 原則 7) |

### `ja/` — 日文

2026 年 6 月引入的日文轉錄與 QAQC 工具集:

| 檔案 | 作用 |
|------|------|
| `groq_transcribe_ja.py` | Groq Whisper 日文單檔轉錄(language=ja)— **轉錄主線** |
| `gemini_transcribe_ja.py` | Gemini 音訊轉錄(替代方案;有原則 5 engine 守門,CLI host 下拒絕,`--force-api` 可硬闖) |
| `qaqc_srt_ja.py` | Phase A 清理(日文字符感知:漢字/平假名/片假名) |
| `qaqc_phase_b_ja.py` | Gemini Phase B structured 校稿(日文 prompt;同樣有原則 5 守門) |

Auth 與主線相同:從 `.env` 讀 `GROQ_API_KEY` / `GEMINI_API_KEY`;打 Gemini API 的兩支
僅限純 shell/cron 環境使用(CLI host 環境會被守門擋下,改由對話 agent 接手)。

## 與主線(中文)的關係

中文處理走 `scripts/session.py`(P1 完成後)→ 呼叫 `.claude/skills/good-student-notes/scripts/groq_transcribe.py`。
多語系腳本若未來要統一介面,建議抽出共用的 `lang/core.py` 放本目錄下,各語言實作成為 plugin。
目前暫不做抽象化 —— en/、ja/ 已是正式使用的第二、三語言,但各自工具仍小而獨立,
等出現第三份重複的 load_env / call_gemini 樣板時再抽 core.py。
