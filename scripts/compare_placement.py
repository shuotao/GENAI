#!/usr/bin/env python3
"""比對一組放置(anchors: deck→after_ci)與 ground-truth,算語意相符率。

用於 Step 4.5 影像放置調校迴圈(§ S4.5.11):把 Haiku/演算法的放置對照使用者手排,
tolerance=±N content-line 內視為「語意同區、相符」。輸出 %相符 + 逐 deck 差異。

用法:
  python3 scripts/compare_placement.py --gt gt_placement.json --pred anchors.json [--tol 1]
  pred 格式:[{"deck":1,"after_ci":141}, ...] 或 [{"file":"...","after_line":N}](自動抓 deck)
"""
import argparse, json, re, sys
from pathlib import Path


def load_deck_map(path, gt=None):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    out = {}
    for x in data:
        deck = x.get("deck")
        if deck is None:  # 從檔名時間序推 deck(對 pred 用 gt 的檔名→deck)
            fn = x.get("file", "")
            if gt:
                deck = gt.get(fn)
        ci = x.get("after_ci", x.get("after_line"))
        if deck is not None and ci is not None:
            out[deck] = ci
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gt", required=True)
    ap.add_argument("--pred", required=True)
    ap.add_argument("--tol", type=int, default=1, help="±N content-line 內算相符")
    ap.add_argument("--paras", default=None, help="seg_paras.json(印錨點段落文字)")
    a = ap.parse_args()

    gt_raw = json.loads(Path(a.gt).read_text(encoding="utf-8"))
    gt = {g["deck"]: g["after_ci"] for g in gt_raw}
    fn2deck = {g["file"]: g["deck"] for g in gt_raw}
    pred = load_deck_map(a.pred, fn2deck)
    paras = {}
    if a.paras:
        paras = {p["ci"]: p["text"] for p in json.loads(Path(a.paras).read_text(encoding="utf-8"))}

    match = 0
    rows = []
    for deck in sorted(gt):
        g = gt[deck]
        p = pred.get(deck)
        ok = p is not None and abs(p - g) <= a.tol
        if ok:
            match += 1
        rows.append((deck, g, p, ok))
    pct = match / len(gt) * 100
    print(f"相符率: {match}/{len(gt)} = {pct:.1f}%  (tol=±{a.tol})")
    print("deck | GT_ci | pred_ci | 相符 | GT 錨點段落")
    for deck, g, p, ok in rows:
        mark = "✓" if ok else "✗"
        ptxt = str(p) if p is not None else "—"
        anchor = paras.get(g, "")[:40]
        print(f"  {deck:>2} | {g:>5} | {ptxt:>7} | {mark} | {anchor}")
    # 給下游判斷用
    print(f"\nSUMMARY pct={pct:.1f} miss={[d for d,_,_,ok in rows if not ok]}")
    return 0 if pct >= 90 else 1


if __name__ == "__main__":
    sys.exit(main())
