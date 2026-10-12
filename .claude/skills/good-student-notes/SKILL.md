---
name: good-student-notes
description: 將音訊/影片檔案轉為逐字稿，經 QAQC 清理與 AI 校稿後，生成好學生筆記。Use when user provides a media file and asks for transcription, notes, or 好學生筆記.
argument-hint: <media_file> [identity] [--context <data-or-file>] [--domain <name>] [--images <dir>]
allowed-tools: Bash, Read, Write, Glob, Grep, Edit
---

# 好學生筆記 CLI 工作流程

你是一個好學生筆記生成系統。當使用者提供媒體檔案時，嚴格按照以下步驟執行。

**所有作業規範請遵循本專案的 `CLAUDE.md`。**

---

## 輸入解析

使用者會以下列方式呼叫：
```
/good-student-notes <media_file> [identity] [--context <data-or-file>] [--domain <name>]
```

- `<media_file>`:媒體檔案路徑(必要)
- `[identity]`:使用者身份/專業背景(選填,例如:建築師、軟體工程師)
- `--context <data-or-file>`:本次錄音的背景資料(選填)
  - 可以是一段文字(以引號包起)
  - 可以是一個 `.txt` 檔路徑
  - 可以是「剛才使用者貼在對話裡的資料」— 若對話中有補充內容,你應該先把它寫入 `/tmp/context_<session>.txt` 再傳入
- `--domain <name>`:領域詞典(選填,例如:parenting, tech)— 對應 `dict/typo_dict.<name>.json`
- 如果未提供 identity,跳過好學生筆記生成(只產 SRT 和合併校稿)

---

## 核心架構原則(必須遵循)

1. **SRT 不可變**:`transcript.srt` 是原始證據,絕不回寫。
2. **時間軸保護**:Phase B 的 LLM 校稿永遠**看不到時間戳**(由 `scripts/qaqc_phase_b.py --mode structured` 保證)。
3. **Context 綁 Session**:使用者提供的 context 綁在 `sessions/<id>/context.txt`,不汙染專案。
4. **Session 容器**:所有產物歸位在 `sessions/<id>/`。

---

## 執行步驟(一行命令)

整個流程已封裝為 `scripts/session.py`,你只需呼叫:

```bash
python3 scripts/session.py new "<media_file>" \
  [--context "<data-or-file>"] \
  [--domain <name>] \
  [--images <dir>] \            # 啟用圖片理解 + 自動插圖(marker 鏈多兩關)
  [--stop-at {transcribe|phase-a|phase-b|phase-c|phase-d|images|image-insert|enhance|notes}]  # default: phase-b
  [--keywords "term1,term2"] \   # 觸發 Step 3
  [--enhance] \                  # 觸發 Step 3(自動辨識術語)
  [--identity "<立場>"]          # 觸發 Step 4(需 --stop-at notes)
```

### 停點原則(R6.2)

**不要預設每次跑完 Step 4**。大宗使用者在 Step 2(cleaned.md)就已滿足。依使用者
意圖選擇停點:

| 使用者意圖 | `--stop-at` |
|-----------|-------------|
| 只要 SRT 字幕檔 | `transcribe` |
| 要時間軸保留的錯字修正版 | `phase-a`(同 `--skip-phase-b`) |
| 要去時間軸、合併、通順的稿 | `phase-b`(預設) |
| 標點正規化(出版前強制門,§ R7) | `phase-c` |
| 通順 / hook(出版前強制門,§ R8) | `phase-d` |
| 圖片理解(產圖片內容矩陣) | `images`(需 `--images <dir>`) |
| 自動插圖 | `image-insert`(需 `--images <dir>`) |
| 外加專有名詞補充 | `enhance` 並提供 `--keywords` 或 `--enhance` |
| 一路到好學生筆記 | `notes` 並提供 `--identity` |

> ⚠️ `--stop-at` 共 **9** 個值,以 `scripts/session.py` 的 argparse `choices` 為準
> (由 `scripts/tests/test_docs_sync.py` T2 機械守門)。

### 腳本自動完成

1. 計算 session slug:`YYYY-MM-DD_<sanitized-filename>`,建立 `sessions/<slug>/`
2. symlink 音檔為 `source.<ext>`,寫入 `context.txt`、`metadata.json` 骨架
3. 呼叫 Groq Whisper → `transcript.srt`(時間軸保留、以 context.txt 作 prompt)
4. 呼叫 `SRT/qaqc_srt.py --domain <name>` → Phase A(錯字、幻覺、亂碼過濾)
5. (若未 `--stop-at` 早於 phase-b)呼叫 `scripts/qaqc_phase_b.py --mode merged` → `cleaned.md`
6. (若 `--stop-at enhance|notes` 且有 keywords/enhance 旗標)→ `enhanced.md`
7. (若 `--stop-at notes` 且有 `--identity`)→ `notes_<立場>.md`
8. 寫入 `metadata.json` 的字數比率、耗時、錯字命中數、stop_at 等

---

## 你(Claude)的角色

腳本跑完後,你要做的是**檢視與回報**,不要再逐字校稿:

1. `ls sessions/<slug>/` 確認所有產物齊全:
   - `source.<ext>`(symlink)
   - `context.txt`
   - `transcript.srt`
   - `cleaned.md`
   - `metadata.json`
   - (若有 identity)`notes_<identity>.md`
2. 讀 `metadata.json`,檢查:
   - `qaqc.ratio_chinese` 是否在 [0.95, 1.05] 區間
   - `summary_words_check` 是否為 0
3. 讀 `cleaned.md`,若發現明顯錯字或專名錯誤,寫入 `sessions/<slug>/corrections.json`:
   ```json
   {"_meta": {"session": "<slug>", "domain_candidate": "<name>"},
    "corrections": {"錯字": "正字", ...}}
   ```
   這份 `corrections.json` **不會**自動合進 `dict/typo_dict.<domain>.json`,
   需要使用者手動審閱後推送(避免單 session 的偶發誤判污染共用詞典)。
4. 若 Phase B 的字數比率 < 0.95,或 `structured` 長度檢查失敗,**不要**嘗試
   自己補救;在回報中明確標示,讓使用者決定是否重跑或手動修。

---

## 完成報告

```
✅ 好學生筆記工作流程完成

📁 Session:sessions/<slug>/
  - source.<ext>             (symlink, N MB)
  - context.txt              (N bytes)
  - transcript.srt           (N segments)
  - cleaned.md               (N chars, ratio 0.XX)
  - notes_<identity>.md      (若有)
  - metadata.json

📊 統計:
  - Groq 耗時:N.N 秒
  - Phase A 命中:M 組錯字、K 個幻覺段
  - Phase B 字數比率:0.XX (target [0.95, 1.05])
  - 領域詞典:base + <domain>(N 組)

⚠  待人工確認:(若有)
  - corrections.json 候選條目:K 組(尚未推送至 dict/)
```

---

## Marker 鏈:腳本停在哪、你要接手什麼(原則 5 + 原則 9)

在 Claude Code / Gemini CLI / Copilot CLI 底下,`session.py` 偵測到 host 就
**只寫 marker、不打任何 API**。腳本跑完後 session 目錄會留下待辦 marker,**由你接手**。

依賴順序(逐一清除,**清一個、驗一個**,不得打包):

```
.phase_b_pending.json  → .phase_c_pending.json → .phase_d_pending.json
   →(.images_pending.json → .image_insert_pending.json,帶 --images 時)
   → .step_3_pending.json → .step_4_pending.json
```

每個 marker 的處理協議:
1. 讀 marker 的 `input_file` / `output_file` / `rules_ref` / 中文字數區間 / `instructions`
2. 套對應規則(SSoT:`prompts/qaqc_core_rules.md`、`prompts/publish_qaqc.md`)
3. **跑該關的驗證器**,綠了才算完成:

   | marker | 驗證器 |
   |---|---|
   | phase-b | 字數落在 `target_chinese_chars_min`–`max`;`scripts/para_len_check.py` |
   | phase-c | `scripts/normalize_punctuation.py <md> --check` 殘留 = 0 |
   | phase-d | `scripts/phase_d_check.py <md> --base <快照>`(**動手前先 `--snapshot <md> --base <快照>` 存檔**) |
   | images | `image_notes.json` 全數 `described`;**注意 exit 1 = 有圖失敗但仍寫檔,不是成功** |
   | image-insert | `insert_images.py --verify`;分佈「最擠一行 ≤ 2 張」 |

4. 寫回輸出檔 → **刪 marker** → 更新 `metadata.json` 對應區塊的 `status` 與 `actor`

> `scripts/prepublish_gate.py` 會擋下「phase_c/phase_d 未 done、marker 殘留、
> 正文仍有 CJK 語境半形標點」的出版,所以漏清 marker 一定會在 Step 5 被攔下。

---

## 不要做的事

- ❌ 不要自己從 `.srt` 做 Phase B 校稿 — 永遠呼叫 `scripts/qaqc_phase_b.py`
- ❌ 不要在根目錄寫產出檔 — 一律寫到 `sessions/<slug>/`
- ❌ 不要用 `SRT/context.example.txt` 當 context — 這是範例檔
- ❌ 不要自動把 `corrections.json` 合進 `dict/typo_dict.*.json` — 需人工審閱
- ❌ 不要在輸出中使用第三人稱描述(「講者提到...」「本段討論...」等)

---

## 降級路徑(若腳本不可用)

若 `scripts/session.py` 或 `scripts/qaqc_phase_b.py` 出錯,可手動執行:

```bash
# Step 1: 轉錄
python3 .claude/skills/good-student-notes/scripts/groq_transcribe.py \
  "<audio>" "<output_dir>" "<context_file>"

# Step 2: Phase A 清理
python3 SRT/qaqc_srt.py "<srt>" --domain <name> -o "<cleaned.srt>"

# Step 3: Phase B 校稿
python3 scripts/qaqc_phase_b.py --mode merged --context "<ctx>" \
  "<cleaned_text>" -o "<cleaned.md>"
```

但正常情況下一律走 `scripts/session.py new`。
