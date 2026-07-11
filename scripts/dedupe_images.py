#!/usr/bin/env python3
"""dedupe_images.py — 重複圖片檢測與去重(§ S4.5.12 / § S6.12)。

影片截圖抓拍常把同一張投影片拍進多幀。本工具以**雙訊號 AND 閘**判定重複:
1. **影像指紋**:dHash 64-bit(PIL 灰階 9x8 梯度),Hamming ≤ 門檻(確定性)。
2. **描述一致性**:image_notes 描述詞彙 Jaccard ≥ DESC_FLOOR。
兩者同時成立才視為重複(自動移除);只有指紋相似、描述不同 = 同版型不同內容
(如同一套章節卡模板),列入「人工複核」報告、不移除。
實證:2026-06-26_1 的 892/603 天前兩張章節卡,dHash 距離 ≤6 但描述相似僅 0.28
—— 單靠影像指紋會誤刪。

模式:
  --report            列出重複組 + 統計(不改任何檔)
  --apply             每組保留 deck_page 最小(演講最早)一張,其餘:
                      - 從 cleaned.md 移除該圖行(正文零省略驗證)
                      - image_notes 標 status=duplicate、duplicate_of=<保留檔>

用法:
  python3 scripts/dedupe_images.py --session sessions/<slug> [--report|--apply]
  [--hash-threshold 6](64-bit Hamming;≤6 視為同一張投影片)
"""
from __future__ import annotations
import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from img_context_score import terms  # noqa: E402

HASH_THRESHOLD = 6   # 64-bit dHash Hamming 距離;≤6 = 影像近似(含輕微轉場/游標差異)
DESC_FLOOR = 0.5     # 描述 Jaccard ≥ 0.5 才確認為同內容(擋同版型不同內容的誤判)
MAX_DUP_GAP = 4      # deck_page 間距 ≤ 此值才算「連拍幀重複」自動移除;超過 = 講者回頭
                     # 放同一張(非連續重複)→ 兩張都留、列複核(§ S4.5.12,2026-07-09)


def dhash(img_path: Path) -> int:
    from PIL import Image
    im = Image.open(img_path).convert("L").resize((9, 8), Image.Resampling.LANCZOS)
    px = list(im.getdata())
    bits = 0
    for row in range(8):
        for col in range(8):
            bits = (bits << 1) | (1 if px[row * 9 + col] > px[row * 9 + col + 1] else 0)
    return bits


def hamming(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


def desc_jaccard(n1: dict, n2: dict) -> float:
    t1 = terms(" ".join([n1.get("text_in_image", ""), n1.get("caption", "")]))
    t2 = terms(" ".join([n2.get("text_in_image", ""), n2.get("caption", "")]))
    if not t1 or not t2:
        return 0.0
    return len(t1 & t2) / len(t1 | t2)


def find_groups(notes: list[dict], sdir: Path, threshold: int, desc_floor: float,
                max_gap: int = MAX_DUP_GAP
                ) -> tuple[list[list[dict]], list[tuple[dict, dict, float]]]:
    """回 (重複組, 人工複核清單)。
    重複組:dHash ≤ threshold **且** 描述 Jaccard ≥ desc_floor **且** deck_page 間距 ≤ max_gap
    (三閘 AND,union-find)。
    人工複核:僅影像相似描述不足、**或影像+描述都像但 deck_page 遠距**(講者回頭放同一張,
    非連續重複)→ (n1, n2, jaccard),不移除、兩張都留。"""
    items = []
    for n in notes:
        p = sdir / n["file"]
        if p.exists() and n.get("status") in ("described", "inserted", "anchored"):
            items.append((n, dhash(p)))
    parent = list(range(len(items)))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    review = []
    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            if hamming(items[i][1], items[j][1]) <= threshold:
                sim = desc_jaccard(items[i][0], items[j][0])
                dp_i, dp_j = items[i][0].get("deck_page"), items[j][0].get("deck_page")
                gap = abs(dp_i - dp_j) if (dp_i is not None and dp_j is not None) else 0
                if sim >= desc_floor and gap <= max_gap:
                    parent[find(i)] = find(j)               # 近距連拍幀 → 真重複,移除
                elif sim >= desc_floor and gap > max_gap:
                    review.append((items[i][0], items[j][0], sim))  # 遠距回頭 → 兩張都留
                else:
                    review.append((items[i][0], items[j][0], sim))  # 描述不足 → 兩張都留
    groups: dict[int, list[dict]] = {}
    for i, (n, _h) in enumerate(items):
        groups.setdefault(find(i), []).append(n)
    out = [sorted(g, key=lambda n: (n.get("deck_page") or 0, n["file"]))
           for g in groups.values() if len(g) > 1]
    return sorted(out, key=lambda g: g[0].get("deck_page") or 0), review


IMG_LINE_TPL = "]({file})"


def main() -> int:
    ap = argparse.ArgumentParser(description="重複圖片檢測/去重(§ S4.5.12)")
    ap.add_argument("--session", required=True)
    ap.add_argument("--md", default="cleaned.md")
    ap.add_argument("--hash-threshold", type=int, default=HASH_THRESHOLD)
    ap.add_argument("--desc-floor", type=float, default=DESC_FLOOR)
    ap.add_argument("--max-dup-gap", type=int, default=MAX_DUP_GAP,
                    help="deck_page 間距 ≤ 此值才算連拍重複自動移除;超過=講者回頭放同一張,兩張都留")
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--report", action="store_true")
    mode.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    sdir = Path(a.session).resolve()
    notes_path = sdir / "image_notes.json"
    notes = json.loads(notes_path.read_text(encoding="utf-8"))
    groups, review = find_groups(notes, sdir, a.hash_threshold, a.desc_floor, a.max_dup_gap)

    total_dupes = sum(len(g) - 1 for g in groups)
    print(f"[dedupe] 檢查 {len(notes)} 張 | 重複組 {len(groups)} 組(多餘 {total_dupes} 張)"
          f" | 人工複核 {len(review)} 對(dHash ≤ {a.hash_threshold} AND 描述 ≥ {a.desc_floor})")
    for gi, g in enumerate(groups, 1):
        keep = g[0]
        print(f"  組 {gi}(保留 → {keep['file'][-12:]} p{keep.get('deck_page')}):")
        for n in g:
            mark = "★保留" if n is keep else "✂移除"
            sim = desc_jaccard(keep, n) if n is not keep else 1.0
            print(f"    {mark} {n['file'][-12:]} p{n.get('deck_page')} "
                  f"| 描述相似 {sim:.2f} | {n.get('caption','')[:24]}")
    for n1, n2, sim in review:
        print(f"  ⚠ 複核(同版型?): {n1['file'][-12:]} vs {n2['file'][-12:]} "
              f"| 描述相似 {sim:.2f} → 保留兩張,人工確認")
    if a.report or not groups:
        return 0

    # --apply:每組保留第一張,其餘移除
    md_path = sdir / a.md
    md_text = md_path.read_text(encoding="utf-8")
    removed = []
    for g in groups:
        for n in g[1:]:
            pattern = re.compile(r"^!\[[^\]]*\]\(" + re.escape(n["file"]) + r"\)\s*\n?",
                                 re.MULTILINE)
            md_text, cnt = pattern.subn("", md_text)
            n["status"] = "duplicate"
            n["duplicate_of"] = g[0]["file"]
            removed.append((n["file"], cnt))
    # 零省略驗證:正文(非圖行)完全不變
    def prose(t):
        return [l for l in t.splitlines() if l.strip() and not re.match(r"^!\[[^\]]*\]\([^)]+\)\s*$", l)]
    old_prose = prose(md_path.read_text(encoding="utf-8"))
    if prose(md_text) != old_prose:
        print("[dedupe] ✗ 正文行改變,rollback(不落盤)", file=sys.stderr)
        return 1
    bak = md_path.with_suffix(".md.pre-dedupe.bak")
    bak.write_text(md_path.read_text(encoding="utf-8"), encoding="utf-8")
    md_path.write_text(md_text, encoding="utf-8")
    notes_path.write_text(json.dumps(notes, ensure_ascii=False, indent=2), encoding="utf-8")
    not_found = [f for f, c in removed if c == 0]
    print(f"[dedupe] ✓ 移除 {sum(c for _f, c in removed)} 行(備份 {bak.name})"
          + (f";不在 md 內(僅標記): {len(not_found)}" if not_found else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
