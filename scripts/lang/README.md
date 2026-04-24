# `scripts/lang/` — 多語系轉錄與清理腳本

這個目錄集中放置**各語言版本**的轉錄、清理、批次處理腳本。中文版的主線是核心工具
(`.claude/skills/good-student-notes/scripts/groq_transcribe.py`),本目錄放其他語言
的並行實作或歷史參考。

## 目錄慣例

子目錄以 [ISO 639-1 語言代碼](https://en.wikipedia.org/wiki/List_of_ISO_639-1_codes) 命名:

```
scripts/lang/
├── it/          # Italian  (義大利文)
├── ja/          # Japanese (日文,預留)
├── en/          # English  (英文,預留)
└── README.md
```

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
重構範本。後續新增語言(日文、英文)時,請在此建立 `ja/`、`en/` 等子目錄並仿照結構。

## 與主線(中文)的關係

中文處理走 `scripts/session.py`(P1 完成後)→ 呼叫 `.claude/skills/good-student-notes/scripts/groq_transcribe.py`。
多語系腳本若未來要統一介面,建議抽出共用的 `lang/core.py` 放本目錄下,各語言實作成為 plugin。
目前暫不做抽象化 —— 等第二個語言正式使用時再評估(見 plan scope guard)。
