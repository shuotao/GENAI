#!/usr/bin/env python3
"""img_context_score.py — 圖文相關性計分(確定性,gate 與 Step 6 audit 共用)。

SSoT: prompts/publish_qaqc.md § S4.5.11 / § S6.11。
計分:圖片描述文字(text_in_image + speaker/audience_view + caption)與插入點
±1 內容行的詞彙重疊 containment 分數:

    score = |desc_terms ∩ ctx_terms| / max(1, min(|desc_terms|, |ctx_terms|))

詞彙 = CJK bigram + 小寫 ASCII 詞(len≥2)。

門檻(2026-07-05 以 0704CC 20 張人工 ground truth 實測校準):
- 正樣本(人工位置)分數 0.030-0.220(median 0.064);
- 負樣本(遠離 ≥10 行,n=75)0.000-0.088(median 0.036);57% 負樣本高於正樣本下限
  → **鑑別度只夠當粗網,不夠當精準判官**。
- 故:fail < 0.02(幾乎確定無關,硬擋);0.02-0.09 warning(列給 agent 語意複核,
  不擋);healthy ≥ 0.09。語意相關性的精準判斷屬 LLM(原則 6),本模組只抓大錯。
"""
from __future__ import annotations
import re

CJK = re.compile(r"[一-鿿㐀-䶿]")
ASCII_WORD = re.compile(r"[A-Za-z][A-Za-z0-9.+-]{1,}")
NUMBER = re.compile(r"\d{2,}")  # 純數字是強錨點(頁碼/年份/天數,如 892、2024)

THRESHOLD_FAIL = 0.02
THRESHOLD_HEALTHY = 0.09


def terms(text: str) -> set[str]:
    out: set[str] = set()
    cjk_runs = re.findall(r"[一-鿿㐀-䶿]+", text)
    for run in cjk_runs:
        out.update(run[i : i + 2] for i in range(len(run) - 1))
        if len(run) == 1:
            out.add(run)
    out.update(w.lower() for w in ASCII_WORD.findall(text))
    out.update(NUMBER.findall(text))
    return out


def desc_text(note: dict) -> str:
    parts = [note.get("text_in_image", ""), note.get("speaker_view", ""),
             note.get("audience_view", ""), note.get("caption", "")]
    for blk in note.get("layout") or []:
        parts.append(blk.get("content", ""))
    return " ".join(p for p in parts if p)


def score(note: dict, context_lines: list[str]) -> float:
    d = terms(desc_text(note))
    c = terms(" ".join(context_lines))
    if not d or not c:
        return 0.0
    inter = len(d & c)
    return inter / max(1, min(len(d), len(c)))


def verdict(s: float) -> str:
    if s >= THRESHOLD_HEALTHY:
        return "healthy"
    if s >= THRESHOLD_FAIL:
        return "warning"
    return "fail"
