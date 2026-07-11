#!/usr/bin/env python3
"""propose_anchors.py — 插圖 anchor 確定性比對器(純 py 文字比對,零 LLM)。

SSoT: prompts/publish_qaqc.md § S4.5.11。設計(原則 6):
- 比對訊號 = image_notes 描述詞彙(img_context_score.terms:CJK bigram +
  ASCII 詞 + 數字)對每個內容行的 containment 分數(行 + 下一行為上下文)。
- 有 deck_page 的圖:**單調 DP** — 在「anchor 隨頁碼非遞減」約束下最大化總分
  (確定性,全域最優)。
- 無 deck_page(needs_review)的圖:獨立取最高分行;低於 --min-score 給 -1。
- 輸出 anchors JSON(直接餵 insert_images.py --apply);confidence = 原始分數,
  低於 --review-below 的條目標 needs_llm_review=true,由執行者(Claude Haiku)
  複核,其餘直接採用 —— LLM 只看低信心尾巴,不做全量語意判斷。

用法:
    python3 scripts/propose_anchors.py --session sessions/<slug> \
        [--md cleaned.md] [--out anchors.json] [--min-score 0.02] [--review-below 0.06]
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from img_context_score import score  # noqa: E402
from insert_images import content_lines, line_type  # noqa: E402

NEG_INF = float("-inf")


def score_matrix(notes: list[dict], lines: list[str]) -> list[list[float]]:
    """s[i][j] = 圖 i 描述 vs 行 j(+下一行)的 containment 分數。標題行不作插入點。"""
    mat = []
    for n in notes:
        row = []
        for j, ln in enumerate(lines):
            if line_type(ln) in ("h1", "h2"):
                row.append(NEG_INF)  # 不插在大標題後
                continue
            ctx = [ln] + ([lines[j + 1]] if j + 1 < len(lines) else [])
            row.append(score(n, ctx))
        mat.append(row)
    return mat


def solve_monotonic(mat: list[list[float]], stack_penalty: float = 0.0) -> list[int]:
    """DP:每張圖選一行,行序非遞減(可同行),最大化總分。回傳每張圖的行 index。

    反塌陷(2026-07-09,§ S4.5.11):把「連續投影片疊在同一行」變成有成本。
    轉移分兩種:前一張在 *嚴格更前* 的行 k<j(無懲罰)或 *同一行* j(扣 stack_penalty)。
    → 一行疊 t 張的總成本 = (t-1)·stack_penalty;唯有該行分數夠高、勝過次佳*不同*行
      至少 stack_penalty 才會疊。stack_penalty=0 時退化回原本可無限疊的行為。
    """
    n, m = len(mat), len(mat[0])
    dp = [[NEG_INF] * m for _ in range(n)]
    choice = [[0] * m for _ in range(n)]  # choice[i][j] = 第 i-1 張選的行 k
    for j in range(m):
        dp[0][j] = mat[0][j]
    for i in range(1, n):
        run = NEG_INF   # max dp[i-1][k] for k < j(嚴格更前,無懲罰)
        argrun = 0
        for j in range(m):
            best_val, best_k = run, argrun
            same = (dp[i - 1][j] - stack_penalty) if dp[i - 1][j] > NEG_INF else NEG_INF
            if same > best_val:            # 疊同一行(付懲罰)
                best_val, best_k = same, j
            dp[i][j] = (mat[i][j] + best_val) if (mat[i][j] > NEG_INF and best_val > NEG_INF) else NEG_INF
            choice[i][j] = best_k
            if dp[i - 1][j] > run:          # 納入 k=j,供之後 j'>j 用(維持嚴格更前)
                run, argrun = dp[i - 1][j], j
    # 回溯
    out = [0] * n
    j = max(range(m), key=lambda k: dp[n - 1][k])
    out[n - 1] = j
    for i in range(n - 1, 0, -1):
        j = choice[i][out[i]]
        out[i - 1] = j
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="確定性 anchor 比對(§ S4.5.11)")
    ap.add_argument("--session", required=True)
    ap.add_argument("--md", default="cleaned.md")
    ap.add_argument("--out", default=None, help="anchors JSON 輸出路徑(預設 session 內 anchors_proposed.json)")
    ap.add_argument("--min-score", type=float, default=0.02, help="低於此分 → -1 不插入")
    ap.add_argument("--review-below", type=float, default=0.06,
                    help="低於此分標 needs_llm_review(Haiku 複核)")
    ap.add_argument("--stack-penalty", type=float, default=0.08,
                    help="反塌陷:連續圖疊同一行的每張懲罰(0=關閉;§ S4.5.11)")
    ap.add_argument("--max-per-anchor", type=int, default=2,
                    help="unpaged 圖貪婪讓位門檻:單行已達此數就換次佳行(F5)")
    a = ap.parse_args()

    sdir = Path(a.session).resolve()
    notes = json.loads((sdir / "image_notes.json").read_text(encoding="utf-8"))
    usable = [n for n in notes if n.get("status") in ("described", "anchored")]
    md_text = (sdir / a.md).read_text(encoding="utf-8")
    lines = [ln for _i, ln in content_lines(md_text)]

    paged = sorted([n for n in usable if n.get("deck_page") is not None],
                   key=lambda n: (n["deck_page"], n["file"]))
    unpaged = [n for n in usable if n.get("deck_page") is None]

    from collections import Counter
    used: Counter = Counter()   # 各行已放幾張(unpaged 貪婪讓位用,F5)
    anchors = []
    review_ct = skip_ct = 0
    if paged:
        mat = score_matrix(paged, lines)
        picks = solve_monotonic(mat, stack_penalty=a.stack_penalty)
        for i, (n, j) in enumerate(zip(paged, picks)):   # F7:enumerate,不用 paged.index
            s = mat[i][j]
            if s > a.min_score:
                used[j] += 1
            if s <= a.min_score:
                anchors.append({"file": n["file"], "after_line": -1, "confidence": round(max(s, 0), 3),
                                "engine": "py-textmatch", "needs_llm_review": True})
                skip_ct += 1
                review_ct += 1
            else:
                need = s < a.review_below
                anchors.append({"file": n["file"], "after_line": j, "confidence": round(s, 3),
                                "engine": "py-textmatch",
                                **({"needs_llm_review": True} if need else {})})
                review_ct += 1 if need else 0
    for n in unpaged:
        # F5:無頁碼圖也套「讓開已滿行」的貪婪,避免全撞同一行造成塌陷。
        ranked = sorted(
            ((score(n, [ln] + ([lines[j + 1]] if j + 1 < len(lines) else [])), j)
             for j, ln in enumerate(lines) if line_type(ln) not in ("h1", "h2")),
            reverse=True)
        best_j, best_s = -1, 0.0
        for s, j in ranked:
            if used[j] < a.max_per_anchor:
                best_j, best_s = j, s
                break
        ok = best_s > a.min_score
        if ok:
            used[best_j] += 1
        anchors.append({"file": n["file"], "after_line": best_j if ok else -1,
                        "confidence": round(best_s, 3), "engine": "py-textmatch",
                        "needs_llm_review": True})  # 無頁碼一律複核(§ S4.5.11)
        review_ct += 1
        skip_ct += 0 if ok else 1

    out_path = Path(a.out) if a.out else sdir / "anchors_proposed.json"
    out_path.write_text(json.dumps(anchors, ensure_ascii=False, indent=1), encoding="utf-8")
    placed = sum(1 for x in anchors if x["after_line"] != -1)
    from collections import Counter
    dist = Counter(x["after_line"] for x in anchors if x["after_line"] != -1)
    distinct = len(dist)
    worst_line, worst_ct = (dist.most_common(1)[0] if dist else (None, 0))
    print(f"[anchors] {len(anchors)} 張:插入 {placed} / 不插 {skip_ct} / 需 Haiku 複核 {review_ct}")
    print(f"[anchors] 分佈:{placed} 張落在 {distinct} 個不同插入點;最擠一行 {worst_ct} 張(stack_penalty={a.stack_penalty})")
    print(f"[anchors] → {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
