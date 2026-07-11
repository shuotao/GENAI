#!/usr/bin/env python3
"""placement_supervisor.py — 圖片放置監管 loop 的確定性驅動器(§ S4.5.11)。

背景(2026-07-09):§ S4.5.11 原本缺「把關放置精準度」的那層——propose_anchors 會把
連續截圖塌在同一段落,相關性 gate 逐張看又放行。本工具是那層監管的**確定性核心**,
供 loop agent(建置期 Fable 5 review / Sonnet 測試;運行期對話 agent)反覆呼叫:

  1. 分佈收斂:stack_penalty 從 --penalty-start 升到 --penalty-max,直到沒有任一
     anchor 疊 > --max-per-anchor 張(反塌陷);記錄用到的 penalty。
  2. 相關性分級:對收斂後的每張圖算 img_context_score,分 healthy / warning / fail。
  3. 殘留清單:warning + fail 的圖 = 需**語意複核**(交 Haiku/Sonnet 對照描述與候選段
     落改 after_line),寫進報告的 needs_semantic_review。
  4. 規範缺口:penalty 升到頂仍塌陷、或 fail 收不掉 → 寫 spec_gap（給 Fable 5 / 人
     反向修正 SSoT 門檻或演算法,而不是硬吞)。

輸出:anchors_supervised.json(可直接餵 insert_images --apply)+ supervisor_report.json。
退出碼:0=分佈過關且無 relevance fail;1=仍有需處理項(loop 未收斂)。
"""
from __future__ import annotations
import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from img_context_score import score, verdict, THRESHOLD_FAIL, THRESHOLD_HEALTHY  # noqa: E402
from insert_images import content_lines, line_type  # noqa: E402
from propose_anchors import score_matrix, solve_monotonic  # noqa: E402


def converge_distribution(paged, lines, max_per_anchor, p_start, p_max, p_step):
    """升 stack_penalty 直到 paged 圖的 after_line 分佈沒有塌陷。回傳 (picks, penalty, worst)。"""
    mat = score_matrix(paged, lines)
    penalty = p_start
    picks = solve_monotonic(mat, stack_penalty=penalty)
    while True:
        worst = max(Counter(picks).values()) if picks else 0
        if worst <= max_per_anchor or penalty >= p_max:
            return picks, penalty, worst, mat
        penalty = round(min(penalty + p_step, p_max), 3)
        picks = solve_monotonic(mat, stack_penalty=penalty)


def main() -> int:
    ap = argparse.ArgumentParser(description="圖片放置監管 loop 驅動器(§ S4.5.11)")
    ap.add_argument("--session", required=True)
    ap.add_argument("--md", default="cleaned.md")
    ap.add_argument("--out", default=None, help="anchors 輸出(預設 session/anchors_supervised.json)")
    ap.add_argument("--report", default=None, help="報告輸出(預設 session/supervisor_report.json)")
    ap.add_argument("--max-per-anchor", type=int, default=2)
    ap.add_argument("--penalty-start", type=float, default=0.08)
    ap.add_argument("--penalty-max", type=float, default=0.30)
    ap.add_argument("--penalty-step", type=float, default=0.03)
    a = ap.parse_args()
    if a.penalty_step <= 0:          # F6:防死迴圈(penalty 永遠升不到上限)
        ap.error("--penalty-step 必須 > 0")

    sdir = Path(a.session).resolve()
    notes = json.loads((sdir / "image_notes.json").read_text(encoding="utf-8"))
    usable = [n for n in notes if n.get("status") in ("described", "anchored", "inserted")]
    lines = [ln for _i, ln in content_lines((sdir / a.md).read_text(encoding="utf-8"))]

    paged = sorted([n for n in usable if n.get("deck_page") is not None],
                   key=lambda n: (n["deck_page"], n["file"]))
    unpaged = [n for n in usable if n.get("deck_page") is None]

    anchors: list[dict] = []
    penalty_used = worst = 0
    if paged:
        picks, penalty_used, worst, mat = converge_distribution(
            paged, lines, a.max_per_anchor, a.penalty_start, a.penalty_max, a.penalty_step)
        for idx, (n, j) in enumerate(zip(paged, picks)):
            s = mat[idx][j]
            anchors.append({"file": n["file"], "after_line": (-1 if s <= THRESHOLD_FAIL else j),
                            "confidence": round(max(s, 0), 3), "engine": "supervisor"})
    # unpaged:各自最高分行,避免全撞一行(貪婪讓開已滿的 anchor)
    used = Counter(x["after_line"] for x in anchors if x["after_line"] != -1)
    for n in unpaged:
        ranked = sorted(
            ((score(n, [lines[j]] + ([lines[j + 1]] if j + 1 < len(lines) else [])), j)
             for j, ln in enumerate(lines) if line_type(ln) not in ("h1", "h2")),
            reverse=True)
        pick_j, pick_s = -1, 0.0
        for s, j in ranked:
            if used[j] < a.max_per_anchor:
                pick_j, pick_s = j, s
                break
        ok = pick_s > THRESHOLD_FAIL
        if ok:
            used[pick_j] += 1
        anchors.append({"file": n["file"], "after_line": pick_j if ok else -1,
                        "confidence": round(pick_s, 3), "engine": "supervisor",
                        "needs_llm_review": True})

    # 相關性分級 + 殘留清單
    by_line_ctx = lambda j: [lines[j]] + ([lines[j + 1]] if j + 1 < len(lines) else [])
    graded = {"healthy": [], "warning": [], "fail": []}
    needs_review = []
    for x in anchors:
        if x["after_line"] == -1:
            needs_review.append({**_tag(x), "reason": "not-placed (score≤fail)"})
            continue
        v = verdict(x["confidence"])
        graded[v].append(_tag(x)["tag"])
        if v != "healthy":
            needs_review.append({**_tag(x), "after_line": x["after_line"], "verdict": v})

    dist = Counter(x["after_line"] for x in anchors if x["after_line"] != -1)
    worst_final = max(dist.values()) if dist else 0
    dist_ok = worst_final <= a.max_per_anchor

    spec_gap = []
    if not dist_ok:
        spec_gap.append(f"penalty 升到 {penalty_used}(上限 {a.penalty_max})仍有一行疊 {worst_final} 張 "
                        f"— 反塌陷演算法/上限需調,或該場截圖過密需人工分段(反寫 § S4.5.11)。")
    if graded["fail"]:
        spec_gap.append(f"{len(graded['fail'])} 張 relevance=fail 收不掉 — 可能逐字稿缺對應敘述"
                        f"(demo 只在圖內、口白沒講),文字錨點不足;需評估是否放寬/改用圖內文字錨點"
                        f"(反寫 § S4.5.11 相關性來源)。")

    report = {
        "session": sdir.name, "md": a.md,
        "distribution": {"ok": dist_ok, "penalty_used": penalty_used,
                         "worst_run": worst_final, "max_per_anchor": a.max_per_anchor,
                         "distinct_anchors": len(dist), "placed": sum(dist.values())},
        "relevance": {k: len(v) for k, v in graded.items()},
        "needs_semantic_review": needs_review,
        "spec_gap": spec_gap,
        "converged": dist_ok and not graded["fail"],
    }
    out_path = Path(a.out) if a.out else sdir / "anchors_supervised.json"
    rep_path = Path(a.report) if a.report else sdir / "supervisor_report.json"
    out_path.write_text(json.dumps(anchors, ensure_ascii=False, indent=1), encoding="utf-8")
    rep_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[supervisor] 分佈:{report['distribution']['placed']} 張 / "
          f"{report['distribution']['distinct_anchors']} anchor / 最擠 {worst_final} 張 "
          f"/ penalty={penalty_used} → {'✓' if dist_ok else '✗ 仍塌陷'}")
    print(f"[supervisor] 相關性:healthy {report['relevance']['healthy']} / "
          f"warning {report['relevance']['warning']} / fail {report['relevance']['fail']}")
    print(f"[supervisor] 需語意複核:{len(needs_review)} 張;規範缺口:{len(spec_gap)}")
    for g in spec_gap:
        print(f"  ⚠ spec-gap: {g}")
    print(f"[supervisor] → {out_path.name} / {rep_path.name}")
    return 0 if report["converged"] else 1


def _tag(x: dict) -> dict:
    return {"file": x["file"], "tag": x["file"].split("]-")[-1], "confidence": x["confidence"]}


if __name__ == "__main__":
    sys.exit(main())
