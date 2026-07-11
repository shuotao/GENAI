#!/usr/bin/env python3
"""finalize_placement.py — 依 deck 順序把 anchors 收斂成「單調 + max-2 + 無 -1」的確定性收尾。

背景(2026-07-09,day2 Happy/李慕約 密集概念 deck):supervisor 反塌陷 DP 在「連續投影片
的可行位置被單調約束擠進 <k 條行」時仍會留 3-stack、且把弱錨點圖判 -1 丟掉。對「已出版、
必須保留所有投影片、且圖序=講者放映序」的 deck,正確模型是**依 deck 序流水放置**:走訪
每張(deck 排序),落點不得早於前一張(單調),該行已滿 max_per_anchor 就往後找第一個未滿的
行。保證:全部放置、無塌陷、無逆位。text-match 佳的位置盡量保留,只在衝突時往後讓位。

用法: finalize_placement.py --session <dir> --md pub_ch.md [--in anchors_sup.json]
       [--out anchors_final.json] [--max-per-anchor 2]
"""
from __future__ import annotations
import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from insert_images import content_lines, line_type  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--session", required=True)
    ap.add_argument("--md", default="pub_ch.md")
    ap.add_argument("--in", dest="inp", default=None)
    ap.add_argument("--out", default=None)
    ap.add_argument("--max-per-anchor", type=int, default=2)
    a = ap.parse_args()
    sdir = Path(a.session).resolve()
    anchors = json.loads(Path(a.inp or sdir / "anchors_sup.json").read_text(encoding="utf-8"))
    notes = {n["file"]: n for n in json.loads((sdir / "image_notes.json").read_text(encoding="utf-8"))}
    lines = [(i, ln) for i, ln in content_lines((sdir / a.md).read_text(encoding="utf-8"))]

    def _build_stripped(ln: str) -> bool:
        """build_genai2026_* 會刪掉的行 → 不可當插入點(否則圖落在其後,build 刪行後黏成塌陷)。"""
        s = ln.strip()
        return (s.startswith("**講者：**") or s.startswith("**講題：**")
                or s == "---" or bool(re.match(r"^#+\s*——.*——\s*$", s)))

    # 可插入行 index(排除 h1/h2 大標題 + build 會刪的行)
    valid = [idx for idx, (_i, ln) in enumerate(lines)
             if line_type(ln) not in ("h1", "h2") and not _build_stripped(ln)]
    valid_set = set(valid)
    max_idx = valid[-1] if valid else 0

    # 依 deck_page 排序(無 deck_page 排最後、保持原相對序)
    def dk(x):
        return (notes.get(x["file"], {}).get("deck_page") is None,
                notes.get(x["file"], {}).get("deck_page") or 0, x["file"])
    anchors.sort(key=dk)

    # 純 deck 順序均勻分佈:第 i 張(deck 排序)落在 valid[round(i·M/N)],
    # 再以「單調下限 + max-2 往後推」修正。結構上保證非遞減(無逆位)、max-2、全放置。
    occ: Counter = Counter()
    floor_pos = 0                  # valid list 內的單調下限(index)
    M, N = len(valid), len(anchors)
    for i, x in enumerate(anchors):
        base_pos = (i * M) // N if N else 0        # 均勻攤在 valid 上
        pos = max(base_pos, floor_pos)
        while pos < M and occ[valid[pos]] >= a.max_per_anchor:
            pos += 1
        if pos >= M:               # 理論上不會(容量 2M ≥ N);保底放最後可插入行
            pos = M - 1
        j = valid[pos]
        x["after_line"] = j
        occ[j] += 1
        floor_pos = pos
        if x.get("engine") not in ("haiku-reviewed", "human"):
            x["engine"] = "deck-flow"

    out = Path(a.out or sdir / "anchors_final.json")
    out.write_text(json.dumps(anchors, ensure_ascii=False, indent=1), encoding="utf-8")
    worst = max(occ.values()) if occ else 0
    placed = sum(1 for x in anchors if x["after_line"] >= 0)
    # 逆位檢查(deck)
    seq = [(notes[x["file"]].get("deck_page") or 0, x["after_line"]) for x in anchors]
    inv = sum(1 for i in range(len(seq) - 1) if seq[i + 1][1] < seq[i][1])
    print(f"[finalize] 放置 {placed}/{len(anchors)} | 落點 {len(occ)} | 最擠 {worst} "
          f"| 逆位 {inv} | → {out.name}")
    return 0 if worst <= a.max_per_anchor and inv == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
