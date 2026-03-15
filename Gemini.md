# Gemini.md

本文件為 Gemini CLI 使用者的快速入口。**所有作業規範請參考 `CLAUDE.md`。**

---

## 指向

> **完整規範文件：[CLAUDE.md](./CLAUDE.md)**
>
> 本專案的唯一指導規範文件為 `CLAUDE.md`，涵蓋：
> - 零省略原則 (Zero Omission Policy)
> - QAQC 清理與校稿標準
> - 好學生筆記生成規則
> - 輸出檔案命名規範
> - 錯誤樣態對照表
>
> 無論使用 Claude Code 或 Gemini CLI，均須遵守 `CLAUDE.md` 中的所有規範。

---

## Gemini CLI 快速開始

### 好學生筆記工作流程

在 Gemini CLI 中，透過 `@` 指令指定媒體檔案，並參照 `CLAUDE.md` 的規範執行：

```bash
# 步驟一：轉錄（需要 Groq API Key，存放於 .env）
# 使用 Python 腳本處理音訊轉錄
python3 .claude/skills/good-student-notes/scripts/groq_transcribe.py <media_file>

# 步驟二：QAQC + 校稿
# 在 Gemini CLI 對話中，@cleaned_file 並指示：
# "請根據 CLAUDE.md 的 QAQC 標準與校稿規則，對這份逐字稿進行 Phase A + Phase B 處理"

# 步驟三：好學生筆記（需指定身份）
# "請根據 CLAUDE.md 的好學生筆記規範，以「建築師」的視角生成好學生筆記"
```

### 核心提醒

1. **Groq 轉錄**需透過 Python 腳本執行（Gemini CLI 無法直接上傳音檔至 Groq）
2. **校稿與筆記生成**可直接在 Gemini CLI 對話中完成
3. 所有規範與鐵律請查閱 **CLAUDE.md**
