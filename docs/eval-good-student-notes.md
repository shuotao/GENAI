# good-student-notes skill 評測報告(2026-10-12)

執行者:Claude Opus 5(1M context),於 `/Users/shuotaochiang/Desktop/study`。
工具:`eval-skill` CLI(`bin/eval-skill-darwin-arm64`)。
三軸由使用者指定:**(1) 觸發準確度 (2) 低階模型能否實執 (3) 跨 CLI 分工合理性**。

> **執行模式揭露**(quality-standards 要求):Tier 0/1 走真實 headless CLI
> (`claude -p`,16 題 × 3 次 × 4 workers,per-query timeout 180s)。
> **Tier 2(行為提升/paired baseline)未執行** —— 本輪的「行為證據」改以
> 同一天實跑完整出版管線(台北大洋流場次)時**真實踩到的缺陷**充當,
> 這不是對照實驗,下方凡屬此類一律標明「實跑觀察,非對照實驗」。

---

## Tier 0:靜態 lint —— 3 個發現**全部是 linter 偽陽性**

```
FAIL: frontmatter: unexpected key(s): argument-hint
FAIL: referenced file(s) do not exist: SRT/qaqc_srt.py, scripts/session.py, ...
WARN: file(s) never referenced by SKILL.md: scripts/groq_transcribe.py
```

逐一查證:

| 發現 | 判定 | 證據 |
|---|---|---|
| `argument-hint` 非法 | **偽陽性** | `argument-hint` 是 SKILL.md 正式支援欄位(code.claude.com/docs/en/skills.md 的 frontmatter 表)。eval-skill 的 allowlist(`allowed-tools/description/license/metadata/name`)**比官方 schema 窄**,是過期的 schema |
| 引用檔不存在 | **偽陽性** | 列出的 11 個路徑**全部存在**,只是 repo-root-relative;linter 以 skill 目錄為基準解析 |
| `groq_transcribe.py` 從未被引用 | **偽陽性** | SKILL.md 確實提到它(`grep -c` = 1) |

**結論:Tier 0 對「嵌在 repo 裡、引用 repo 根路徑」的 skill 不可信。**
不要照它的 FAIL 去改一支能正常運作的 skill —— 刪掉 `argument-hint` 會弄壞自動補全提示。

## Tier 1:觸發準確度 —— **16/16 通過**

16 題(8 正例 / 8 near-miss),每題 3 次真實 `claude -p`:

- **recall(正例平均觸發率)= 0.88**,每題皆 ≥ 0.67(門檻)
- **false-trigger(near-miss 平均)= 0.00**,每題皆 ≤ 0.33(門檻)
- 最低的三題(0.67):英文 query、「不要摘要要完整保留」、「錄音+投影片出版」

**沒有偷走任何 sibling skill 的流量**:`transcode-media`(mp4→mp3)、
`youtube-download`、`constructivist-lesson-builder`(5E 教案)、
`knowledge-map-generator`(知識圖譜)四題 near-miss 全部 0.00。

原始資料:`result/good-student-notes/trigger_results.json`;
題庫:`runbooks/good-student-notes-trigger.json`。

## 軸 2:低階模型能否無誤實執(實跑觀察,非對照實驗)

同日跑完整出版管線時**真實踩到**的契約陷阱 —— 這些就是低階模型會卡死的地方:

| # | 實際發生 | 為什麼低階模型會錯 |
|---|---|---|
| 1 | `phase_d_check.py --snapshot` 直接報 `expected one argument` | `--snapshot` 與 `--base` 的方向不直覺(`--snapshot <來源> --base <目的>`),`--help` 沒有範例。我自己第一次也寫錯 |
| 2 | `codex exec -i a -i b "prompt"` → `No prompt provided via stdin.` | `-i/--image` 是**變長參數**,把提示詞吞成第三張圖。靜默失敗,錯誤訊息指向 stdin,完全誤導 |
| 3 | `prepublish_gate.py` 對 build/ 下的裸 md **靜默降級**成 legacy 模式,跳過 Phase C/D 與圖片檢查卻印「✓ 放行出版」 | 看到綠燈就過了,實際上整組閘門沒跑。這是最危險的一種:**失敗看起來像成功** |
| 4 | `publish_qaqc` S6.11 誤報「12 張圖全部無描述條目」 | 查詢路徑不對稱(md 用 basename、notes 存 `images/x.jpg`)。低階模型會去改圖或重跑描述,而不是懷疑查詢邏輯 |
| 5 | `finalize_placement.py` 把非白名單 engine 的 anchor **無聲丟棄** | 沒有任何錯誤輸出,資料就是消失了 |

**已修 1 項之外的 4 項**(見 `docs/model-routing.md` 與當日 commit);
第 1 項屬於 `--help` 文案,列入待辦。

**可執行性守則(寫進 `docs/model-routing.md`)**:
凡是「要自己產一份 JSON、而索引來自另一次呼叫」的步驟(典型:`insert_images.py --apply --anchors`),
**不要交給低階模型單獨完成**。正確分工是給它確定性工具的輸出、讓它只做選擇題
(只複核 `needs_llm_review=true` 的少數),這正是現行 `propose_anchors` + 複核尾巴的設計。

## 軸 3:跨 CLI 分工(實跑)

當日把 `§ S4.5.11` 規劃了一年多、從未實跑的「四角色鏈」真的跑了一次:

- **讀圖** = `agy -p --model gemini-3.8-flash-medium` → 12 張全數成功,15–81s/張
- **找插入位** = `codex exec -m gpt-6.1-sol -i <圖>` 與 **Claude Haiku subagent 雙軌**跑低信心尾巴(3 筆)
- **裁決** = Opus 只處理兩者分歧的 1 筆

結果:2 筆一致(3528→79、3533→82)、1 筆分歧(3530:Haiku 80 / Codex 82)。
Opus 判 80 —— 該圖是「洋流出任務」志工動員,對應 line 80 的「由下而上整理大家的想法」;
Codex 的 82 是「我時間超過太多了」的收尾句,且會讓最後一行疊兩張圖。

**分工評語:合理,但先前不可能落地。** 三支下游工具的 engine 白名單只收
`haiku-reviewed`/`human`,Codex 與 Opus 的標籤會被丟掉或擋下 —— 規劃與實作對不上。
收斂成 `REVIEWED_ENGINES` 常數後才真的跑得通。

`sol` / `luna`:**repo 內零命中**。實測可用的是 `gpt-6.1-sol`(codex 設定檔預設,
ChatGPT OAuth)。`luna` 變體未驗證,**不要憑記憶寫進文件**。

---

## 待辦(未在本輪完成)

1. **Tier 2 行為提升**:需要 paired with-skill / without-skill 對照跑。本輪未做 → skill 的「行為價值」仍無對照證據。
2. `phase_d_check.py` / `describe_images.py` 的 `--help` 補 exit code 語意與範例。
3. eval-skill 的 Tier 0 frontmatter allowlist 過期(`argument-hint` 等),建議回報上游。
4. `build/improvement_queue.jsonl` 342 筆全為 `open`、無人消費。
