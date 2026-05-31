---
description: /note 生底稿(Stage 1)。把一份 .md(預設 web/enhanced.md)渲染成 A4 白底底稿 base_pNN.png,原文真 DOM 渲染、零遺漏。底稿與身份無關,可重複給多個職業視角用。下一步用 /好學生筆記 在底稿上生圖。
---

# /note — 生底稿(Stage 1)

把逐字稿/筆記 .md 變成乾淨的 A4 白底「底稿」圖,供之後生圖用。**底稿與身份無關**,一份可重複用。
詳見 [`prompts/image_notes_skill.md`](../../prompts/image_notes_skill.md)。前提:Playwright。

## 步驟
1. 確認要處理的 `.md`(預設 `web/enhanced.md`)。
2. 執行:
   ```bash
   python3 scripts/image_notes_session.py note <file.md>
   ```
   → 產出 `sessions/<slug>/note/base_pNN.png` + `meta.json`(slug = 日期_檔名)。
3. 告訴使用者底稿位置與 **slug**,並提示下一步:
   `/好學生筆記 <slug> <身份>`(例:`/好學生筆記 2026-05-31_enhanced 鋼琴老師`)。
