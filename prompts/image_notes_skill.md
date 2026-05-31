# 好學生筆記 圖像版 — 兩階段工作流程 SSoT

> 把一份 `.md`(通常是 Step 3 的 `enhanced.md`)做成多頁的「視角好學生筆記」圖。
> 視覺/註解規則(6 色語義、視角類比、版面)見 [`image_notes_design.md`](./image_notes_design.md)。

## 設計原則(為什麼是兩階段、無後端自動化)

- **腳本叫不動影像工具**:`scripts/*.py` 無法呼叫 Nano Banana;只有 Antigravity / Gemini CLI 的影像 MCP 工具能生圖。
- 因此**生圖不做後端自動化狀態機**(實測逐頁自動 banana 會重複第 1 頁/跳過/亂 schema)。改成兩個乾淨階段:
  - **確定性的事 → 腳本**:把 md 渲染成 A4 白底底稿、整理逐頁提示。
  - **生圖 → Antigravity/你手動,一次一張**:每頁各自獨立 → 流水號正確、不重複。

## Stage 1 — `/note` 生底稿(與身份無關)

```
python3 scripts/image_notes_session.py note <file.md>
```
- 用 Playwright 把 md 渲染成 `sessions/<slug>/note/base_pNN.png`(A4 白底、真 DOM 文字 → **零遺漏**)+ `meta.json`(含每頁文字)。
- slug = `日期_檔名`。**底稿與身份無關 → 一份底稿可重複給多個職業視角用。**

## Stage 2 — `/好學生筆記` 生圖(指定身份)

```
python3 scripts/image_notes_session.py notes <slug> --identity "<身份>"
```
- 產 `sessions/<slug>/note/banana_prompts_<身份>.md`:每頁拖哪張 `base_pNN.png` + 一段可直接複製的 banana 提示(含該頁內容)。
- 然後**逐頁、各自獨立**生圖(Antigravity 內建 Nano Banana,或 Gemini CLI 的 nanobanana,或你手動):
  - 把該頁的 `base_pNN.png` 拖進 Nano Banana、貼該頁提示 → 疊「<身份>」視角手寫彩色註解、**保留原文一字不改** → 存成同目錄 `pNN.png`。
  - **一次一張、各自獨立** → 每張都是它自己的 `base_pNN`,流水號正確、每頁都有、不會重複第 1 頁、不會互相污染。
- 換職業:同一份底稿,改 `--identity` 再跑一次 Stage 2 即可(底稿不用重產)。

## 疊加提示(Stage 2 每頁通用,身份代入)
```
把這張白底課程筆記頁變成「<身份>」視角的「好學生筆記」:
- 完全保留原始印刷文字一字不改、清晰可辨,只在上面疊手寫風格的彩色註解。
- 6 色:🔵藍 圈關鍵字/底線;🔴紅「!」洞察、「?」疑問;🟠橘/🟢綠 邊欄用「<身份>」生活情境類比+便利貼;🟡黃 螢光重點。
- 底部「💡 核心洞察」手寫框,用「<身份>」的語言總結並連結日常。
```

## 產物
- `sessions/<slug>/note/base_pNN.png`(底稿,與身份無關)
- `sessions/<slug>/note/meta.json`(每頁文字等)
- `sessions/<slug>/note/banana_prompts_<身份>.md`(逐頁提示)
- `sessions/<slug>/note/pNN.png`(各頁成品,由 Nano Banana 手動/逐頁生成)
