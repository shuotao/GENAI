# 多模型角色分工 SSoT(docs/model-routing.md)

> 建立於 2026-10-12。**本檔是「哪個 model / CLI 負責哪一段」的唯一真實來源。**
> 在此之前,角色分配散落在 `CLAUDE.md` 原則 5/6、`prompts/publish_qaqc.md § S4.5.11`
> 與各腳本的註解裡,而且**規劃與實作對不上**(見下方「規劃 vs 實跑」)。
>
> 鐵則:**本檔只記錄「實測確認過」的事。** 沒跑過的寫在「規劃」區,不混進 live 表。

---

## 1. 實測可用模型(2026-10-12 於本機驗證)

### Antigravity CLI(`antigravity` / 別名 `agy`,v1.2.14)
`antigravity models` 實際回傳:

| 家族 | id |
|---|---|
| Gemini Flash **3.8** | `gemini-3.8-flash-{high,medium,low}` |
| Gemini Flash 3.7 | `gemini-3.7-flash-{high,medium,low}` |
| Gemini Flash 3.6 | `gemini-3.6-flash-{high,medium,low}` |
| Gemini **Pro** 3.1 | `gemini-3.1-pro-{high,low}` |
| Claude | `claude-opus-5-5-{low,medium,high}`、`claude-sonnet-5-5-{low,medium,high}` |
| 開源 | `gpt-oss-120b-medium` |

Auth:Antigravity 自己的 OAuth login(`antigravity -p`)。**不是 API key 通道**,
所以不受「腳本禁打 Gemini API」守門限制(CLAUDE.md 原則 5)。

> **2026-10-12 修正**:`describe_images.py` 的 `MODEL_PREFERENCE` 原本停在 3.6/3.7,
> 3.8 上線後永遠不會被選到 → 長期跑在舊模型上。已改為新→舊排序並把預設提到
> `gemini-3.8-flash-medium`。新世代上線時往前插一格即可。

### Codex CLI(`codex`,v0.161.0)
- 設定檔 `~/.codex/config.toml`:`model = "gpt-6.1-sol"`、`model_reasoning_effort = "medium"`
- Auth:**ChatGPT OAuth**(`auth mode = chatgpt`),非 API key → 同樣合乎原則 5
- `codex exec` 支援 `-m/--model` 與 **`-i/--image <FILE>...`(可讀圖)**
- 沙箱:`-s read-only | workspace-write | danger-full-access`

> **⚠️ 低階模型地雷(2026-10-12 實際踩到)**:`-i/--image` 是**變長參數**。
> 寫成 `codex exec -i a.jpg -i b.jpg "提示詞"`,最後那個提示詞會被當成**第三個圖片檔**
> 吞掉,然後 codex 轉去讀 stdin、報 `No prompt provided via stdin.`。
> **正解:提示詞走 stdin**(`codex exec -i a.jpg -i b.jpg < prompt.txt`),
> 或把提示詞放在所有 `-i` 之前。

### Claude Code(本 repo 的主 host)
Auth:OAuth login token。**無影像生成通道**(讀圖可以,生圖不行)。

---

## 2. Live 分工表(實際在跑的)

| 階段 | 執行者 | 為什麼是它 |
|---|---|---|
| Step 1 轉錄 | **Groq Whisper large-v3**(API key,`.env` 支援多把輪替) | 確定性工具,非判斷(原則 6) |
| Phase A 清理 | `SRT/qaqc_srt.py`(純 Python,零 LLM) | 確定性 |
| Phase B 校稿 | **對話 agent**(本 repo 預設 = Claude Code) | 判斷:語意幻覺、專名校正、分段 |
| Phase C 標點 | `normalize_punctuation.py` + agent 補全形冒號 | 機械 + 少量判斷 |
| Phase D hook | agent,`phase_d_check.py` 機械證明只插不改 | 判斷,但有子序列證明把關 |
| **圖片理解** | **Antigravity headless** `agy -p --model gemini-3.8-flash-medium`(`describe_images.py`) | 單一引擎 + 熔斷;Claude Code 這端只負責指揮 |
| 錨點提案 | `propose_anchors.py`(DP,零 LLM) | 確定性 |
| **低信心尾巴複核** | **Claude Haiku subagent**(現行)+ **Codex `gpt-6.1-sol`**(2026-10-12 起實跑) | 判斷;兩者分歧才升級 |
| 分歧裁決 | **Opus**(對話 agent) | 只處理分歧,不是每筆都看 |
| 插入 / 去重 / 驗證 | `insert_images.py` / `dedupe_images.py` / `placement_check.py` | **LLM 絕不放 bytes**(原則 6) |
| Step 4.5 / 5 / 6 | 全部確定性腳本 | 分類、收斂、出版、audit |

### 複核者標籤(engine)
下游三支工具用 `anchor.engine` 判斷「這個放置是否已被複核」:

```
REVIEWED_ENGINES = ("haiku-reviewed", "human", "codex-reviewed", "opus-reviewed")
```

定義於 `finalize_placement.py` / `prepublish_gate.py` / `publish_qaqc.py`。

> **2026-10-12 修正**:三處原本各自硬寫 `("haiku-reviewed","human")`。
> 後果:四角色鏈規劃要讓 Codex 找插入位、Opus 驗證,但那些標籤
> **會被 `finalize_placement.py` 無聲丟棄**,或被另外兩支當成「未複核」擋下 ——
> 規劃根本不可能落地。收斂成單一常數後才真的跑得起來。
> 新增複核者 = 只動這一行。

---

## 3. 規劃 vs 實跑(誠實對照)

`prompts/publish_qaqc.md § S4.5.11` 的「四角色鏈」自 2026-07-19 起標註「規劃,尚未實跑」。
2026-10-12 盤點結果:

| 角色 | 規劃 | 2026-10-12 之前 | 現在 |
|---|---|---|---|
| 讀簡報 | Antigravity | ✅ 已實跑 | ✅ |
| 找插入位 | **Codex** | ❌ 從未實作(`grep -i codex` 在所有 `.py/.sh/.js/.toml` **零命中**) | ✅ 實跑(`codex exec -m gpt-6.1-sol -i …`) |
| 驅動插入 | Haiku | ✅ 已實跑 | ✅ |
| 驗證 | **Opus** | ❌ 無程式路徑,且產出的標籤會被白名單丟掉 | ⚠️ 部分:Opus 只裁決分歧,不做全量語意驗證 |

**`sol` / `luna` 在 repo 內零命中。** `gpt-6.1-sol` 只存在於 `~/.codex/config.toml`,
本檔是它第一次被寫進專案文件。若要用 luna 變體,請先 `codex exec -m <id> "say OK"` 實測,
確認可用再寫進本表 —— 不要憑記憶寫 model id。

---

## 4. 低階模型可執行性(哪些工具不能交給小模型)

盤點時標出的高危工具,共通點是「CLI 契約藏在文件裡,不在 `--help` 裡」:

| 工具 | 危險點 |
|---|---|
| `describe_images.py` | 三種 exit code(0 乾淨 / **1 有圖失敗但仍寫檔** / 2 熔斷)。只檢查「有沒有 crash」會把 1 當成功 |
| `insert_images.py --apply` | `--anchors` 無預設,且那份 JSON 的 `after_line` 索引來自**另一次 `--plan`**;`-1` = 不插入。全管線最易錯的一步 |
| `propose_anchors.py` | 六個調校浮點數,預設值是對一組 ground truth 校出來的;輸出是**提案**,工具本身不強制你複核 |
| `finalize_placement.py` | engine 不在白名單 → **靜默丟資料**(已於 2026-10-12 收斂成共用常數,但仍是靜默) |
| `dedupe_images.py --apply` | 會改寫 `cleaned.md`,旗標名看不出破壞性 |
| `qaqc_phase_b.py` | host 守門長得像 bug,`--force-api` 是誘餌 —— 繞過就重演雙重計費事故(原則 5) |
| `session.py` | `--stop-at` 預設 `phase-b`;到 Step 4 要**同時**給 `--stop-at notes` 與 `--identity`,少一個就靜默跳過 |
| `codex exec -i` | 變長參數吞掉提示詞(見上) |

**結論:凡是「要自己產一份 JSON、索引來自另一次呼叫」的步驟,不要交給低階模型單獨完成。**
給它確定性工具的輸出當輸入、讓它只做選擇題(複核 `needs_llm_review=true` 的少數),
才是安全的分工 —— 這正是現行 propose_anchors + 複核尾巴的設計。
