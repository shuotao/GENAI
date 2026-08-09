#!/usr/bin/env python3
"""para_len_check.py — Phase B 段落長度量測(§ R2.1:目標每段 60~120 CJK 字,寧短勿長)。

確定性量測工具:只回報「哪幾段超出帶寬、超多少」,**不自動切段**——
切在哪裡是語意判斷(一個論點/一個舉例/一段引用=一段),留給對話 agent(原則 6)。

實證出處:2026-07-11 day2 手改 corpus,使用者手改版段均長 68~93 CJK 字;
40/84 條人工修正屬「段落拆分」。詳 prompts/qaqc_core_rules.md § R2.1。

判準刻意**不對稱**,因為 § R2.1 寫的是「寧短勿長」:
  - 硬條件(fail):中位數落在 [min, max] 之外、超長段(>max)比例 > --over、
    或出現極長段(> max × 2)。
  - 軟提醒(不 fail):過短段(<min)只列出供人工判斷是否該與鄰段合併。
早期版本把過短與超長等重罰,反而懲罰了規範鼓勵的方向,已修正。

Usage:
  python3 scripts/para_len_check.py <md> [<md> ...] [--min 60] [--max 120]
                                    [--over 0.20] [--quiet]

Exit code: 0 = 通過;1 = 未達標;2 = usage/IO 錯誤。
"""

import argparse
import re
import statistics
import sys
from pathlib import Path

CJK = re.compile(r"[一-鿿]")
# 極長段:超過 max 的 2 倍,無論達標率如何一律 fail(閱讀節奏已崩)
HARD_FACTOR = 2.0


def paragraphs(text: str) -> list[str]:
    """空行切段;標題行(#)與圖片行不計入段落統計。"""
    out = []
    for p in re.split(r"\n\s*\n", text):
        p = p.strip()
        if not p or p.startswith("#"):
            continue
        if re.fullmatch(r"!\[[^\]]*\]\([^)]*\)", p):
            continue
        out.append(p)
    return out


def check(path: Path, lo: int, hi: int, over_max: float, quiet: bool) -> bool:
    text = path.read_text(encoding="utf-8")
    ps = paragraphs(text)
    if not ps:
        print(f"[para] {path}: 沒有正文段落", file=sys.stderr)
        return False
    lens = [len(CJK.findall(p)) for p in ps]
    hard = int(hi * HARD_FACTOR)
    med = statistics.median(lens)
    longs = [n for n in lens if n > hi]
    shorts = [n for n in lens if n < lo]
    over_hard = [(i, n) for i, n in enumerate(lens) if n > hard]
    over_ratio = len(longs) / len(lens)

    reasons = []
    if not (lo <= med <= hi):
        reasons.append(f"中位 {med:.0f} 不在 {lo}-{hi}")
    if over_ratio > over_max:
        reasons.append(f"超長段占比 {over_ratio:.0%} > {over_max:.0%}")
    if over_hard:
        reasons.append(f"極長段 {len(over_hard)} 段 > {hard} 字")
    ok = not reasons

    print(f"[para] {path}")
    print(f"       段落 {len(lens)}｜平均 {round(statistics.mean(lens))}｜中位 {med:.0f}"
          f"｜超長(>{hi}) {len(longs)}｜過短(<{lo}) {len(shorts)}｜"
          f"{lo}-{hi} 內 {len(lens) - len(longs) - len(shorts)}/{len(lens)}")
    if not quiet:
        for i, n in enumerate(lens):
            if n > hi:
                head = re.sub(r"\s+", " ", ps[i])[:38]
                print(f"       #{i + 1:<3} {n:>4} 字 超長{' ‼極長' if n > hard else ''}  {head}…")
        for i, n in enumerate(lens):
            if n < lo:
                head = re.sub(r"\s+", " ", ps[i])[:38]
                print(f"       #{i + 1:<3} {n:>4} 字 (短,僅提醒)  {head}…")
    print(f"       → {'✓ 通過' if ok else '✗ 未達標:' + '；'.join(reasons)}")
    return ok


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("md", nargs="+")
    ap.add_argument("--min", type=int, default=60, dest="lo")
    ap.add_argument("--max", type=int, default=120, dest="hi")
    ap.add_argument("--over", type=float, default=0.20, dest="over_max",
                    help="超長段(>max)可容忍的比例上限(預設 0.20)")
    ap.add_argument("--quiet", action="store_true", help="只印摘要,不列出個別超標段")
    a = ap.parse_args()

    all_ok = True
    for m in a.md:
        p = Path(m)
        if not p.is_file():
            print(f"[para] 找不到 {p}", file=sys.stderr)
            return 2
        all_ok &= check(p, a.lo, a.hi, a.over_max, a.quiet)
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
