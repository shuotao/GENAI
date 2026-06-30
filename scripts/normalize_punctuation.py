#!/usr/bin/env python3
"""Phase C 全形化(確定性,非 LLM)— SSoT: prompts/qaqc_core_rules.md § R7.1

把半形 , . ? ! : ; ( ) 在「中文語境」轉成全形 ，。？！：；（）。
中文語境 = 該標點「前或後相鄰字元為 CJK」。兩側皆非 CJK 則保護不轉
(數字小數/版本 9.30、URL、純英文句、檔名 shot-01.png 自然落在保護範圍)。

冒號「位置」不在此工具範圍(§ R7.2 是判斷,由 agent 決定);本工具只正規化
既有標點的「寬度」。Markdown 區塊碼(``` 圍欄)與行內碼(`...`)一律跳過。

用法:
  normalize_punctuation.py IN.md -o OUT.md      # 轉換,寫出
  normalize_punctuation.py IN.md --in-place      # 原地轉換
  normalize_punctuation.py IN.md                 # 轉換,印到 stdout
  normalize_punctuation.py IN.md --check         # 不轉換,只報「CJK 語境殘留半形」數,>0 則 exit 1
"""
from __future__ import annotations
import argparse
import re
import sys
from pathlib import Path

# 半形 → 全形 對映(§ R7.1)
HALF2FULL = {
    ",": "，", ".": "。", "?": "？", "!": "！",
    ":": "：", ";": "；", "(": "（", ")": "）",
}


def is_cjk(ch: str) -> bool:
    """相鄰字元是否屬「中文語境」:Han 表意字 + CJK 標點 + 全形字符。"""
    if not ch:
        return False
    o = ord(ch)
    return (
        0x4E00 <= o <= 0x9FFF      # CJK Unified Ideographs
        or 0x3400 <= o <= 0x4DBF   # Extension A
        or 0xF900 <= o <= 0xFAFF   # Compatibility Ideographs
        or 0x3000 <= o <= 0x303F   # CJK Symbols and Punctuation(、。「」『』等)
        or 0xFF00 <= o <= 0xFFEF   # Fullwidth Forms(，！？：；（）等)
    )


_LINK_RE = re.compile(r"!?\[[^\]]*\]\([^)]*\)")  # markdown 圖片/連結 ![..](..) / [..](..)


def _ascii_alnum(ch: str) -> bool:
    return bool(ch) and ch.isascii() and ch.isalnum()


def has_cjk(s: str) -> bool:
    return any(is_cjk(c) for c in s)


def _spans_to_skip(line: str) -> list[tuple[int, int]]:
    """不轉的字元區間:行內碼 `...`(含反引號)+ markdown 圖片/連結整個 token
    (保護 `](url)` 的括號與檔名/網址,例如 ![alt](shot-01.png) 不被改成全形)。"""
    spans, i, n = [], 0, len(line)
    while i < n:
        if line[i] == "`":
            j = line.find("`", i + 1)
            if j == -1:
                break
            spans.append((i, j + 1))
            i = j + 1
        else:
            i += 1
    for m in _LINK_RE.finditer(line):
        spans.append((m.start(), m.end()))
    return spans


def normalize_line(line: str) -> tuple[str, int]:
    """中文句一律全形(§ R7.1):**只在「含中文的行」**轉換 —— 純英文行(含圖片行)
    原樣保留。轉換時保護 token 內部標點:小數/版本/網域/檔名(英數.英數,如 9.30、
    ai.dev、shot-01.png)、千分位(數字,數字,如 1,000)、網址冒號(`:` 後接 `/`)、
    時間(數字:數字)。連續 2+ 句點 = 省略號「……」。"""
    if not has_cjk(line):
        return line, 0
    skip = _spans_to_skip(line)

    def in_skip(idx: int) -> bool:
        return any(a <= idx < b for a, b in skip)

    out, n, i, ln = [], 0, 0, len(line)
    while i < ln:
        ch = line[i]
        if in_skip(i):
            out.append(ch)
            i += 1
            continue
        prev_ch = line[i - 1] if i > 0 else ""
        next_ch = line[i + 1] if i + 1 < ln else ""
        # 句點:連續 2+ = 省略號;單一 '.' 在英數.英數(小數/網域/檔名/版本)中保留,否則 → 。
        if ch == ".":
            j = i
            while j < ln and line[j] == "." and not in_skip(j):
                j += 1
            run = j - i
            nxt = line[j] if j < ln else ""
            if run >= 2:
                out.append("……"); n += 1; i = j; continue
            if _ascii_alnum(prev_ch) and _ascii_alnum(nxt):
                out.append("."); i = j; continue
            out.append("。"); n += 1; i = j; continue
        if ch == ",":
            if prev_ch.isdigit() and next_ch.isdigit():   # 千分位 1,000
                out.append(","); i += 1; continue
            out.append("，"); n += 1; i += 1; continue
        if ch == ":":
            if next_ch == "/" or (prev_ch.isdigit() and next_ch.isdigit()):  # 網址 / 時間
                out.append(":"); i += 1; continue
            out.append("："); n += 1; i += 1; continue
        if ch in (";", "!", "?", "(", ")"):
            out.append(HALF2FULL[ch]); n += 1; i += 1; continue
        out.append(ch)
        i += 1
    return "".join(out), n


def _normalize_once(text: str) -> tuple[str, int]:
    """單趟:跳過 ``` 圍欄碼區塊,逐行轉換。"""
    lines, out, total, in_fence = text.split("\n"), [], 0, False
    for line in lines:
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            out.append(line)
            continue
        if in_fence:
            out.append(line)
            continue
        new, n = normalize_line(line)
        out.append(new)
        total += n
    return "\n".join(out), total


def normalize_text(text: str) -> tuple[str, int]:
    """回傳 (轉換後文字, 轉換總數)。**跑到定點**:標點相鄰標點(如 `好,)`)需多趟才會
    全部轉到位 —— 後一個標點要等前一個變全形(成為 CJK 語境)後才會被轉。"""
    total = 0
    while True:
        text, n = _normalize_once(text)
        total += n
        if n == 0:
            break
    return text, total


def count_residual(text: str) -> int:
    """CJK 語境中仍是半形的標點數(轉換完應為 0)。給 gate 的 lint 用。"""
    _, n = normalize_text(text)  # 定點總轉換數 = 殘留數
    return n


def main() -> int:
    ap = argparse.ArgumentParser(description="Phase C 全形化(§ R7.1)")
    ap.add_argument("input")
    ap.add_argument("-o", "--output", default=None)
    ap.add_argument("--in-place", action="store_true")
    ap.add_argument("--check", action="store_true",
                    help="不轉換,只報 CJK 語境殘留半形數;>0 則 exit 1")
    a = ap.parse_args()

    text = Path(a.input).read_text(encoding="utf-8")

    if a.check:
        residual = count_residual(text)
        print(f"[2.2 check] {a.input}: CJK 語境殘留半形標點 = {residual}")
        return 1 if residual > 0 else 0

    new, n = normalize_text(text)
    if a.in_place:
        Path(a.input).write_text(new, encoding="utf-8")
        print(f"[2.2] {a.input}: 全形化 {n} 處(原地)")
    elif a.output:
        Path(a.output).write_text(new, encoding="utf-8")
        print(f"[2.2] {a.input} → {a.output}: 全形化 {n} 處")
    else:
        sys.stdout.write(new)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
