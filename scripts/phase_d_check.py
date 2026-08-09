#!/usr/bin/env python3
"""phase_d_check.py — Phase D「只插入、不改寫」的機械證明(§ R8.2)。

§ R8 規定 hook 只能**插在句間**,不得改寫或刪原句,且段落數 1:1 不變。
這兩件事都是確定性可驗的,不該靠人眼複查(原則 6):

  - **段落數不變**:len(before paragraphs) == len(after paragraphs)。
  - **子序列證明**:若真的只做插入,則 before 的字元序列必為 after 的
    **子序列**(subsequence)。任何刪字、改字、換序都會使子序列比對失敗,
    並可回報第一個對不上的位置。標點寬度差異先正規化再比,避免誤報。
  - **成長率**:hook 是少量插入,CJK 成長率應落在 [1.00, --max-growth]。

用法(先在 Phase D 之前留一份 base 快照):

  python3 scripts/phase_d_check.py --snapshot sessions/<slug>/cleaned.md \\
      --base build/_phase_d_base/<slug>.md          # Phase D 前:存快照
  python3 scripts/phase_d_check.py sessions/<slug>/cleaned.md \\
      --base build/_phase_d_base/<slug>.md          # Phase D 後:驗證

Exit code: 0 = 通過;1 = 未通過;2 = usage/IO 錯誤。
"""

import argparse
import re
import shutil
import sys
from pathlib import Path

CJK = re.compile(r"[一-鿿]")
# 半形→全形對照,避免 Phase C 之後的寬度差異造成假性不符
WIDTH = str.maketrans(",.?!:;()", "，。？！：；（）")


def norm(text: str) -> str:
    """比對用正規化:去空白、統一標點寬度。內容字元本身不動。"""
    return re.sub(r"\s+", "", text).translate(WIDTH)


def paragraphs(text: str) -> list[str]:
    return [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]


def is_subsequence(small: str, big: str) -> tuple[bool, int]:
    """small 是否為 big 的子序列;回傳 (結果, 第一個對不上的 small 索引)。"""
    it = iter(big)
    for i, ch in enumerate(small):
        for c in it:
            if c == ch:
                break
        else:
            return False, i
    return True, -1


def check(after_path: Path, base_path: Path, max_growth: float) -> bool:
    before = base_path.read_text(encoding="utf-8")
    after = after_path.read_text(encoding="utf-8")
    pb, pa = paragraphs(before), paragraphs(after)

    reasons = []
    if len(pb) != len(pa):
        reasons.append(f"段落數 {len(pb)} → {len(pa)}(§ R8.2 要求 1:1 不變)")

    ok_sub, bad_i = is_subsequence(norm(before), norm(after))
    if not ok_sub:
        ctx = norm(before)[max(0, bad_i - 30):bad_i + 30]
        reasons.append(f"子序列比對失敗 @ 原文第 {bad_i} 字:有內容被刪改 → …{ctx}…")

    nb, na = len(CJK.findall(before)), len(CJK.findall(after))
    growth = na / nb if nb else 0
    if growth < 1.0:
        reasons.append(f"CJK 減少 {nb} → {na}(hook 只該增加)")
    elif growth > max_growth:
        reasons.append(f"CJK 成長 {growth:.3f} > {max_growth}(插入過量,恐已改寫)")

    print(f"[phase-d] {after_path}")
    print(f"          段落 {len(pb)} → {len(pa)}｜CJK {nb} → {na}(×{growth:.3f})"
          f"｜子序列 {'✓' if ok_sub else '✗'}")
    print(f"          → {'✓ 通過' if not reasons else '✗ 未通過：' + '；'.join(reasons)}")
    return not reasons


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("md", nargs="?", help="Phase D 後的 cleaned.md(驗證模式)")
    ap.add_argument("--base", required=True, help="Phase D 前的快照路徑")
    ap.add_argument("--snapshot", help="改為存快照模式:把這個檔複製成 --base")
    ap.add_argument("--max-growth", type=float, default=1.12,
                    help="CJK 成長率上限(預設 1.12;hook 是少量插入)")
    a = ap.parse_args()

    base = Path(a.base)
    if a.snapshot:
        src = Path(a.snapshot)
        if not src.is_file():
            print(f"[phase-d] 找不到 {src}", file=sys.stderr)
            return 2
        base.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, base)
        print(f"[phase-d] 快照已存:{src} → {base}")
        return 0

    if not a.md:
        print("[phase-d] 驗證模式需要給 md 路徑", file=sys.stderr)
        return 2
    after = Path(a.md)
    if not after.is_file() or not base.is_file():
        print(f"[phase-d] 找不到 {after if not after.is_file() else base}", file=sys.stderr)
        return 2
    return 0 if check(after, base, a.max_growth) else 1


if __name__ == "__main__":
    sys.exit(main())
