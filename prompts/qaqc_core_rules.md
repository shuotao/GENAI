# QAQC 核心規則 (Single Source of Truth)

本檔為所有 Phase A / Phase B / 好學生筆記 / 知識補充流程的**核心鐵律**。
CLI(`scripts/qaqc_phase_b.py`)與 Web(`web/studio.js`)的 prompt 組合器都從這裡
引用規則文字。**任何規則修改只改這個檔**,兩端下次執行自動生效(Web 需 git pull 或
cache-bust fetch)。

⚠️ **本檔不是 prompt 本身**,而是 prompt 的「規則條款庫」。Prompt 的場景化包裝(如 Web
使用者當下貼 context、CLI 自動從 session 讀)由兩端各自組合 — 本檔只提供共用鐵律。

---

## R1. Phase A 清理規則(確定性,Python/JS 實作)

1. **R1.1 幻覺段落移除**:以 `dict/hallucination_prefixes.json` 列出的任一前綴開頭者,整段丟棄
2. **R1.2 亂碼過濾**:任一條件成立即丟棄
   - 中文字(CJK)占非空白字元比例 < 25%,且該段 > 10 字
   - 出現 `�` 取代字元
   - noise 符號(`┌┐└┘├┤┬┴┼│─⊇◡◬Ⓓ჏ს⓪①②③④⑤⑥⑦⑧⑨`)出現 ≥ 2 次
   - 出現非 CJK 稀有字集(喬治亞、阿拉伯、西里爾、泰、印地等)
   - 連續 5+ 個英文單字且 CJK 比例 < 50%
3. **R1.3 錯字修正**:套用 `dict/typo_dict.json` + `dict/typo_dict.<domain>.json`(疊加)
4. **R1.4 空白正規化**:多個連續空格縮為一個
5. **R1.5 不動時間軸**:SRT 的 timecode 欄位原樣保留,僅改 text

## R2. Phase B 校稿核心鐵律(LLM-side,必須出現在每個 Phase B prompt)

### R2.1 必須做的事
- 補上標點符號(句號、逗號、問號、驚嘆號、頓號)
- 在語意斷裂處補上最小量接續詞(然後、接著、也就是說、所以)
- 合併破碎斷行為完整段落
- 依語意分段(每 300-500 字或話題轉換時),段落間空一行
- 在段落之間插入 Markdown 標題(## 或 ###),標題**不取代**原文

### R2.2 絕對禁令(鐵律,違反即失敗)
- 嚴禁刪減任何句子
- 嚴禁濃縮或摘要
- 嚴禁改變原意或語氣
- 嚴禁使用第三人稱描述(「講者提到了...」「第一部分討論」「本段論述」等)
- 嚴禁省略講者舉例的細節
- 嚴禁動到時間軸(若輸入包含時間戳結構)

### R2.3 量化檢查
- 輸出字數必須落在輸入字數的 **95% - 105%** 之間
- 輸出 < 95% 視為失敗,視情況 fallback 原文或重跑
- 結構保留型(--structured)模式另加:輸出段數必須 == 輸入段數

## R3. 好學生筆記生成規則(Step 4,立場置入)

**前提**:使用者必須指定**立場**(通常是一種專業身份,如「建築師」「小學老師」「軟體工程師」;
也可以是角色/身份/處境)。否則跳過本步驟。

「立場置入」的意義:以該立場的視角,將原文的核心概念**翻譯**為該立場熟悉的類比、
場景、工作流,讓學習者以自己熟悉的語言重新理解內容。

1. **R3.1 完整保留原文**:每一段原文都必須出現(字數檢查同 R2.3)
2. **R3.2 插入立場視角類比區塊**(上下各空一行):
   ```markdown
   > 🎯 **[立場]視角**
   >
   > - **類比**:[用該立場的術語/日常經驗重新詮釋這個概念]
   > - **應用**:[這個概念在該立場的工作或生活中如何應用]
   > - **連結**:[與該立場已知概念的關聯]
   ```
3. **R3.3 開頭學習摘要框**:
   ```markdown
   > 📝 **學習摘要**
   > - 核心主題:[一句話]
   > - [立場]視角的關鍵收穫:[2-3 點]
   ```
4. **R3.4 結尾核心洞察框**:
   ```markdown
   > 💡 **核心洞察**
   > [用該立場的語言,一段話總結最重要的學習]
   ```
5. **R3.5 類比品質**:必須在邏輯上合理且有意義,不可牽強附會

## R4. 專有名詞補充(Step 3,非身份置入)

使用者提供關鍵字(或由 LLM 自動識別專業術語),對 cleaned.md 中**首次出現該術語
的段落之後**附加名詞釋義區塊。本步驟不置入立場,只做術語百科補充。

1. **R4.1 就地補充,不改原文**:原段落一字不改,補充**加**在段落後
2. **R4.2 補充區塊格式**:
   ```markdown
   > **專業知識補充:[術語名稱]**
   >
   > [用淺顯易懂的方式說明,約 2-4 句,涵蓋定義、應用、常見誤解或延伸方向]
   ```
3. **R4.3 只補首次出現**:每個術語補充一次,之後再出現不重複
4. **R4.4 補充區塊上下各保留一個空行**

## R5. 時間軸保護(架構性,非 prompt 層)

- Phase B 若要產「保留時間軸的校稿 SRT」,**必須**走 structured 管道:Python 拆 SRT
  → LLM 只看 text 陣列 → Python 以原 timecode 重組 → cleaned.srt
- LLM 永遠看不到 `00:00:12,000 --> ...`,不可能改到
- 若 LLM 回傳陣列長度 != 輸入長度 → 拒絕合併,fallback 原文
- 詳見 `CLAUDE.md § 核心架構原則 2`

## R6. 四步驟產物定位與停點原則

### R6.1 四個步驟的本質產物
| Step | 產物 | 本質 | 誰需要 |
|------|------|------|--------|
| Step 1 | `transcript.srt` | **帶時間軸的原始逐字稿** | 做字幕、法律證據、影片編輯時的索引 |
| Step 2 | `cleaned.md` | **去時間軸、合併、通順的串接稿** | **大宗使用者的終點**(想讀完整內容,不看時間戳) |
| Step 3 | `enhanced.md` | **專有名詞補充後的稿**(非身份置入) | 對內容陌生、希望有術語百科的讀者 |
| Step 4 | `notes_<立場>.md` | **立場置入的好學生筆記** | 想以自己的視角重新吸收內容的學習者 |

### R6.2 停點原則
每個步驟的產物都是**合法終點**,使用者可以任意停在任一步驟:

- CLI:`scripts/session.py new <audio> --stop-at {transcribe|phase-a|phase-b|enhance|notes}`
- Web:每一步後按「下載」或「匯出 Session ZIP」即可終止;不需要一路跑到 Step 4
- 不要把「跑完四步驟」當成成功的唯一定義。Step 2 滿足使用者的比例可能最高。

### R6.3 Web 的差異化(未來方向,尚未實作)
Web Studio 的獨特優勢目標是能驅動 **Gemini 圖像生成**(banana pro / gemini-2.5-flash-image)
為好學生筆記產出**圖文並茂**的最終版本。這是文字管線之外的附加層,目前尚未實作,
列為 P3 範圍。在實作前,Web 與 CLI 的 Step 4 輸出應保持文字面一致。

---

## 引用方式

### Python(`scripts/qaqc_phase_b.py`)

```python
from pathlib import Path
RULES_PATH = Path(__file__).parent.parent / "prompts" / "qaqc_core_rules.md"
CORE_RULES = RULES_PATH.read_text(encoding="utf-8")

# 組合 prompt:
prompt = f"...\n{extract_section(CORE_RULES, 'R2')}\n...具體任務..."
```

### JavaScript(`web/studio.js`)

```javascript
const rulesResp = await fetch('../prompts/qaqc_core_rules.md');
const CORE_RULES = await rulesResp.text();
// 組合 prompt,套入 R2 區塊
```

實務上兩端的 prompt 組合模板不同(CLI 走自動化、Web 走互動式),但**規則文字本身
來自同一份檔案**,維持 SSoT。

---

## 維護守則

- **只改這一個檔**,不要在 qaqc_phase_b.py / studio.js / CLAUDE.md 中複製規則文字
- CLAUDE.md 有條件式重述時,以 `見 prompts/qaqc_core_rules.md § R2` 指向本檔
- 規則變更請 commit 時寫清楚 why,因為 CLI 與 Web 行為都會同步改變
