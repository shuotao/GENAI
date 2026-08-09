#!/usr/bin/env python3
"""scripts/dialogue_check.py — 多講者座談對談歸屬與順序檢核(§ S4.5.14)

純 stdlib、確定性、不打 LLM。SSoT: prompts/publish_qaqc.md § S4.5.14 + § S6.13,
qaqc_core_rules.md § R2.1 多講者專則 / § R8.2。

三檢:
  D1 歸屬覆蓋(硬)— cleaned.md 每個 prose 段落開頭是否有合法的 `名字：` 標籤。
  D2 順序 + 筆記覆蓋(硬)— reference_notes.md 逐條抽罕見 anchor 定位到 cleaned.md
     段落,比對覆蓋率與 LIS 順序率。
  D3 跨講者混併(警告)— note 講者與其落點段歸屬講者不一致的比例。

用法:
    python3 scripts/dialogue_check.py --session sessions/<slug> \
        [--md cleaned.md] [--notes reference_notes.md] \
        [--book build/<slug>/book.json] \
        [--speakers 慕約,小馮,Jackle] [--host 慕約] \
        [--report dialogue_report.json] [--label-only]

Exit code: 0 = skip(不適用)或收斂;1 = 適用但未收斂;2 = usage/IO/格式錯誤。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from collections import defaultdict
from datetime import datetime
from pathlib import Path

# ── 常數(SSoT: prompts/publish_qaqc.md § S4.5.14) ──────────────────────
ALLOWED_EXTRA = {"觀眾", "現場提問", "主持人", "全場", "Discord"}

LABEL_RE = re.compile(r"^([^\s：]{1,12})：")
HEADING_RE = re.compile(r"^#{1,6}\s")
IMAGE_RE = re.compile(r"^!\[")

ASCII_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9./_-]{2,}")
DIGIT_UNIT_RE = re.compile(r"\d+[億萬千百年月日集機台%]")
CJK_RUN_RE = re.compile(r"[一-鿿㐀-䶿]+")

D2_COVERAGE_MIN = 0.70
D2_ORDER_MIN = 0.85
D2_MIN_ANCHORS = 10
D3_WARN_RATIO = 0.10


# ── 正規化 ───────────────────────────────────────────────────────────────
def normalize(s: str) -> str:
    """strip whitespace, 全形 alnum → 半形, lowercase(NFKC 涵蓋全半形轉換)。"""
    s = unicodedata.normalize("NFKC", s)
    s = s.strip()
    return s.lower()


# ── prose 段落解析(D1 與 D2 共用;cleaned.md 或 publish.md 章節文字皆可餵) ──
def prose_paragraphs(text: str) -> list[tuple[int, str]]:
    """回 [(idx, block_text), ...],排除標題行、圖片行、空段;idx = 檔案順序。"""
    blocks = re.split(r"\n\s*\n", text)
    out = []
    idx = 0
    in_editorial = False  # 編註/延伸參考/附錄 = 編輯性附錄,非講者對談,排除於 D1/D2
    for raw in blocks:
        block = raw.strip("\n")
        stripped = block.strip()
        if not stripped:
            continue
        if HEADING_RE.match(stripped):
            in_editorial = bool(re.search(r"延伸參考|編註|附錄", stripped))
            continue
        if in_editorial:
            continue
        if IMAGE_RE.match(stripped):
            continue
        out.append((idx, block))
        idx += 1
    return out


def _compute_d1(paragraphs: list[tuple[int, str]], roster: set[str]) -> dict:
    unlabeled: list[int] = []
    unknown_labels: list[str] = []
    turns_per_speaker: dict[str, int] = defaultdict(int)
    para_speaker: dict[int, str] = {}

    for idx, block in paragraphs:
        m = LABEL_RE.match(block.strip())
        if not m:
            unlabeled.append(idx)
            continue
        label = m.group(1)
        if label in roster:
            turns_per_speaker[label] += 1
            para_speaker[idx] = label
        elif label in ALLOWED_EXTRA:
            para_speaker[idx] = label
        else:
            unknown_labels.append(label)

    prose_total = len(paragraphs)
    labeled = prose_total - len(unlabeled)
    coverage = (labeled / prose_total) if prose_total else 0.0

    d1a = len(unlabeled) == 0
    d1b = len(unknown_labels) == 0
    d1c = all(turns_per_speaker.get(name, 0) >= 1 for name in roster)
    d1d = len(turns_per_speaker) >= 2
    ok = d1a and d1b and d1c and d1d

    return {
        "ok": ok,
        "prose_paragraphs": prose_total,
        "labeled": labeled,
        "coverage": round(coverage, 4),
        "unlabeled": unlabeled,
        "unknown_labels": unknown_labels,
        "turns_per_speaker": dict(turns_per_speaker),
        "para_speaker": para_speaker,
        "_d1a": d1a, "_d1b": d1b, "_d1c": d1c, "_d1d": d1d,
    }


def check_labels(text: str, roster: set[str], host: str | None) -> tuple[bool, str]:
    """D1 core,純函式、可被 prepublish_gate.py 直接 import。

    roster: 該場/該章的講者名單(不含 ALLOWED_EXTRA);host 若給定會併入 roster
    (若呼叫端尚未把 host 併入 roster)。
    """
    full_roster = set(roster)
    if host:
        full_roster.add(host)
    paragraphs = prose_paragraphs(text)
    d1 = _compute_d1(paragraphs, full_roster)
    detail = (
        f"labeled={d1['labeled']}/{d1['prose_paragraphs']} "
        f"unlabeled={len(d1['unlabeled'])} unknown_labels={d1['unknown_labels'][:5]} "
        f"turns={d1['turns_per_speaker']}"
    )
    return d1["ok"], detail


# ── reference_notes.md 解析(接受兩種格式) ──────────────────────────────
def parse_reference_notes(text: str, roster: set[str]) -> list[dict]:
    """回 [{"note_speaker": str, "note_text": str}, ...],依檔案行序(=時序)。

    Format A: `## X`(X ∈ roster)設定 current_speaker,後續 `- bullet` 或
              非空文字行 = 一則筆記。
    Format B: 任一行 `^(X)：...`(X ∈ roster ∪ ALLOWED_EXTRA)= 一則筆記
              (THIS IS WHAT THE EXISTING FILES USE)。
    忽略:`# ` 標題行、`> ` 註解行、`---`、非 roster 的 `## ` 標頭(僅重置
    current_speaker,不影響 Format B 判斷 — 同一節內文字仍可自帶標籤)。
    """
    notes: list[dict] = []
    current_speaker: str | None = None
    allowed = roster | ALLOWED_EXTRA
    for raw_line in text.splitlines():
        line = raw_line.rstrip("\n")
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("# ") or stripped == "---":
            continue
        if stripped.startswith("> "):
            continue
        m_head = re.match(r"^#{2,6}\s+(.+)$", stripped)
        if m_head:
            name = m_head.group(1).strip()
            current_speaker = name if name in roster else None
            continue
        m_b = LABEL_RE.match(stripped)
        if m_b and m_b.group(1) in allowed:
            note_text = stripped[m_b.end():].strip()
            if note_text:
                notes.append({"note_speaker": m_b.group(1), "note_text": note_text})
            continue
        if current_speaker:
            m_bullet = re.match(r"^-\s+(.*)$", stripped)
            body = m_bullet.group(1).strip() if m_bullet else stripped
            if body:
                notes.append({"note_speaker": current_speaker, "note_text": body})
    return notes


# ── D2 anchor 索引(cleaned.md 段落 → ASCII/digit/CJK n-gram 文檔頻率表) ──
class AnchorIndex:
    def __init__(self, paragraphs: list[tuple[int, str]]):
        self.ascii_paras: dict[str, list[int]] = defaultdict(list)
        self.digit_paras: dict[str, list[int]] = defaultdict(list)
        self.gram_paras: dict[str, list[int]] = defaultdict(list)
        for idx, raw in paragraphs:
            norm = normalize(raw)
            for w in {m.group(0) for m in ASCII_WORD_RE.finditer(norm)}:
                self.ascii_paras[w].append(idx)
            for w in {m.group(0) for m in DIGIT_UNIT_RE.finditer(norm)}:
                self.digit_paras[w].append(idx)
            seen: set[str] = set()
            for run in CJK_RUN_RE.finditer(norm):
                t = run.group(0)
                for n in range(3, 7):
                    for i in range(len(t) - n + 1):
                        g = t[i:i + n]
                        if g not in seen:
                            seen.add(g)
                            self.gram_paras[g].append(idx)

    def candidate_paragraphs(self, note_text: str) -> dict[int, str]:
        """回 {para_idx: anchor_text, ...} — 該 note 所有合格 anchor 命中段落的聯集。

        取代舊版 best_anchor() 的「單一最低 df anchor → 首次出現段」邏輯:
        recurring anchor(人名/產品名/常見詞)會在多段出現,只挑第一段會讓
        greedy forward pass 失去後續候選,錯判為 misordered。這裡改成蒐集
        「該 note 所有 anchor 的所有出現段」聯集,交給呼叫端做 forward 挑選。
        """
        norm = normalize(note_text)
        cands: dict[int, str] = {}

        for m in ASCII_WORD_RE.finditer(norm):
            w = m.group(0)
            for p in self.ascii_paras.get(w, []):
                cands.setdefault(p, w)

        for m in DIGIT_UNIT_RE.finditer(norm):
            w = m.group(0)
            for p in self.digit_paras.get(w, []):
                cands.setdefault(p, w)

        for run in CJK_RUN_RE.finditer(norm):
            t = run.group(0)
            for n in range(3, 7):
                for i in range(len(t) - n + 1):
                    g = t[i:i + n]
                    lst = self.gram_paras.get(g)
                    if lst and 1 <= len(lst) <= 2:
                        for p in lst:
                            cands.setdefault(p, g)

        return cands


# ── roster 解析 ──────────────────────────────────────────────────────────
def resolve_roster(args, session_dir: Path) -> tuple[set[str] | None, str | None]:
    if args.speakers:
        names = [s.strip() for s in args.speakers.split(",") if s.strip()]
        roster = set(names)
        host = args.host.strip() if args.host else None
        if host:
            roster.add(host)
        return roster, host

    if args.book:
        book_path = Path(args.book)
        if not book_path.is_file():
            return None, None
        try:
            book = json.loads(book_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None, None
        sources = book.get("sources", [])
        speakers = book.get("speakers", [])
        slug = session_dir.name
        if slug not in sources:
            return None, None
        i = sources.index(slug)
        if i >= len(speakers):
            return None, None
        full = (speakers[i] or {}).get("full", "")
        items = [p.strip() for p in full.split("×") if p.strip()]
        roster: set[str] = set()
        host: str | None = None
        for it in items:
            if it.endswith("（主持）"):
                name = it[: -len("（主持）")].strip()
                host = name
                roster.add(name)
            else:
                roster.add(it)
        return roster, host

    return None, None


# ── main ─────────────────────────────────────────────────────────────────
def _log(session_dir: Path | None, status: str, metrics: dict, detail: str) -> None:
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from pipeline_logger import log_stage  # noqa: E402
        log_stage(session_dir, "S4.5-dialogue", "dialogue_check.py", status,
                  metrics=metrics, detail=detail)
    except Exception:  # noqa: BLE001 — logger 缺席不影響判斷
        pass


def _enqueue(slug: str, issue: str, suggestion: str = "") -> None:
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from pipeline_logger import enqueue_improvement  # noqa: E402
        enqueue_improvement("S4.5-dialogue", slug, issue, suggestion)
    except Exception:  # noqa: BLE001
        pass


def main() -> int:
    ap = argparse.ArgumentParser(description="§ S4.5.14 多講者座談對談歸屬與順序檢核")
    ap.add_argument("--session", required=True, help="sessions/<slug> 目錄")
    ap.add_argument("--md", default="cleaned.md")
    ap.add_argument("--notes", default="reference_notes.md")
    ap.add_argument("--book", help="build/<slug>/book.json(roster 來源之一)")
    ap.add_argument("--speakers", help="逗號分隔講者名單(優先於 --book)")
    ap.add_argument("--host", help="主持人姓名(需配合 --speakers)")
    ap.add_argument("--report", default="dialogue_report.json")
    ap.add_argument("--label-only", action="store_true", help="只跑 D1")
    args = ap.parse_args()

    session_dir = Path(args.session)
    if not session_dir.is_dir():
        print(f"[dialogue_check] ✗ 找不到 session 目錄:{session_dir}", file=sys.stderr)
        return 2

    slug = session_dir.name
    md_path = session_dir / args.md
    notes_path = session_dir / args.notes
    report_path = session_dir / args.report

    # ── 適用性判定 ──
    applicable = notes_path.is_file() or (
        bool(args.speakers) and len([s for s in args.speakers.split(",") if s.strip()]) >= 2
    )
    if not applicable:
        print(f"[dialogue_check] skip:{slug} 無 reference_notes.md 且未給 --speakers(≥2),"
              f"非多講者座談,不適用 § S4.5.14。")
        report = {
            "applicable": False,
            "session": slug,
            "generated_at": datetime.now().astimezone().isoformat(),
        }
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        return 0

    if not md_path.is_file():
        print(f"[dialogue_check] ✗ 找不到 md:{md_path}", file=sys.stderr)
        return 2

    roster, host = resolve_roster(args, session_dir)
    if not roster or len(roster) < 2:
        print("[dialogue_check] ✗ 無法解析 roster(給 --speakers 或有效的 --book)。",
              file=sys.stderr)
        return 2

    md_text = md_path.read_text(encoding="utf-8")
    paragraphs = prose_paragraphs(md_text)
    d1 = _compute_d1(paragraphs, roster)

    thresholds = {
        "d1_unlabeled": 0,
        "d2_coverage": D2_COVERAGE_MIN,
        "d2_order": D2_ORDER_MIN,
        "d2_min_anchors": D2_MIN_ANCHORS,
        "d3_warn_ratio": D3_WARN_RATIO,
    }

    checks: dict = {
        "D1": {
            "ok": d1["ok"],
            "prose_paragraphs": d1["prose_paragraphs"],
            "labeled": d1["labeled"],
            "coverage": d1["coverage"],
            "unlabeled": d1["unlabeled"],
            "unknown_labels": d1["unknown_labels"],
            "turns_per_speaker": d1["turns_per_speaker"],
        }
    }

    if args.label_only:
        converged = d1["ok"]
        report = {
            "applicable": True,
            "session": slug,
            "md": args.md,
            "notes": args.notes,
            "roster": sorted(roster),
            "host": host,
            "thresholds": thresholds,
            "checks": checks,
            "converged": converged,
            "generated_at": datetime.now().astimezone().isoformat(),
        }
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        if converged:
            print(f"[dialogue_check] ✓ {slug} D1(label-only)通過。")
            _log(session_dir, "pass", {"d1_ok": True}, "label-only")
            return 0
        print(f"[dialogue_check] ✗ {slug} D1(label-only)未過。", file=sys.stderr)
        _log(session_dir, "fail", {"d1_ok": False}, "label-only")
        _enqueue(slug, f"D1 歸屬覆蓋未過(label-only):{checks['D1']}")
        return 1

    # ── D2(需要 reference_notes.md) ──
    if not notes_path.is_file():
        print(f"[dialogue_check] ✗ 找不到 {notes_path}(--speakers 模式仍需要 reference_notes.md "
              f"才能跑 D2)。", file=sys.stderr)
        return 2

    notes_text = notes_path.read_text(encoding="utf-8")
    note_items = parse_reference_notes(notes_text, roster)
    if len(note_items) == 0:
        print(f"[dialogue_check] ✗ {notes_path.name} 無可辨識的筆記條目(格式錯誤,不猜)。",
              file=sys.stderr)
        return 2

    index = AnchorIndex(paragraphs)
    matched: list[dict] = []
    unmatched_notes: list[dict] = []
    for note in note_items:
        cands = index.candidate_paragraphs(note["note_text"])
        if not cands:
            unmatched_notes.append(note)
            continue
        matched.append({
            "note_speaker": note["note_speaker"],
            "note_text": note["note_text"],
            "candidates": sorted(cands.keys()),
            "cand_anchor": cands,
        })

    total_notes = len(note_items)
    coverage = (len(matched) / total_notes) if total_notes else 0.0

    # ── LIS(longest non-decreasing chain,at most one pick per note)────────
    # 取代舊版 greedy forward pass:greedy 用一根 running 指標,一旦某則 note
    # 因內容缺失只命中弱/常見 anchor 而誤配到高 para_idx,running 會被推高,
    # 之後幾乎所有真正在後面的 note 都會被判 misordered(單一早期誤配拖垮
    # 全體)。改用標準 DP 求「跨所有 (note_index, candidate_para) pair、
    # 每則 note 至多選一個、para 非遞減」的最長鏈 —— 誤配的雜訊 pair 若無法
    # 融入單調鏈,自然不會被選中,不會像 greedy 那樣連坐拖垮後續 note。
    nodes: list[dict] = []
    for note_pos, m in enumerate(matched):
        for p in m["candidates"]:
            nodes.append({"note_pos": note_pos, "para": p})

    n_nodes = len(nodes)
    chain_len = [1] * n_nodes
    back = [-1] * n_nodes
    for k in range(n_nodes):
        node = nodes[k]
        best_prev_len = 0
        best_prev_idx = -1
        for j in range(k):
            prev = nodes[j]
            if prev["note_pos"] < node["note_pos"] and prev["para"] <= node["para"]:
                if chain_len[j] > best_prev_len:
                    best_prev_len = chain_len[j]
                    best_prev_idx = j
        if best_prev_idx >= 0:
            chain_len[k] = best_prev_len + 1
            back[k] = best_prev_idx

    order_len = 0
    chain_end = -1
    for k in range(n_nodes):
        if chain_len[k] > order_len:
            order_len = chain_len[k]
            chain_end = k

    on_chain_note_pos: dict[int, int] = {}  # note_pos -> chosen para(on optimal chain)
    k = chain_end
    while k != -1:
        node = nodes[k]
        on_chain_note_pos[node["note_pos"]] = node["para"]
        k = back[k]

    in_order_count = len(on_chain_note_pos)
    misordered: list[dict] = []
    for note_pos, m in enumerate(matched):
        cands = m["candidates"]
        if note_pos in on_chain_note_pos:
            m["para_idx"] = on_chain_note_pos[note_pos]
            m["in_order"] = True
        else:
            m["para_idx"] = cands[0]
            m["in_order"] = False
            misordered.append(m)
        m["anchor"] = m["cand_anchor"].get(m["para_idx"], "")

    order_ratio = (order_len / len(matched)) if matched else 0.0

    d2_a = coverage >= D2_COVERAGE_MIN
    d2_b = order_ratio >= D2_ORDER_MIN
    d2_c = len(matched) >= D2_MIN_ANCHORS
    d2_ok = d2_a and d2_b and d2_c

    checks["D2"] = {
        "ok": d2_ok,
        "notes_total": total_notes,
        "matched": len(matched),
        "coverage": round(coverage, 4),
        "order_ratio": round(order_ratio, 4),
        "in_order": in_order_count,
        "misordered": [
            {"note_speaker": m["note_speaker"], "note_text": m["note_text"], "para_idx": m["para_idx"]}
            for m in misordered
        ],
        "unmatched_notes": [
            {"note_speaker": n["note_speaker"], "note_text": n["note_text"]}
            for n in unmatched_notes
        ],
    }

    # ── D3(warn only) ──
    para_speaker = d1["para_speaker"]
    mismatches = [
        m for m in matched
        if para_speaker.get(m["para_idx"]) != m["note_speaker"]
    ]
    mismatch_ratio = (len(mismatches) / len(matched)) if matched else 0.0
    d3_warn = mismatch_ratio > D3_WARN_RATIO
    checks["D3"] = {
        "level": "warn" if d3_warn else "ok",
        "ok": not d3_warn,
        "mismatch_ratio": round(mismatch_ratio, 4),
        "mismatches": [
            {
                "note_speaker": m["note_speaker"],
                "note_text": m["note_text"],
                "para_idx": m["para_idx"],
                "para_speaker": para_speaker.get(m["para_idx"]),
            }
            for m in mismatches
        ],
    }

    converged = d1["ok"] and d2_ok

    report = {
        "applicable": True,
        "session": slug,
        "md": args.md,
        "notes": args.notes,
        "roster": sorted(roster),
        "host": host,
        "thresholds": thresholds,
        "checks": checks,
        "converged": converged,
        "generated_at": datetime.now().astimezone().isoformat(),
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[dialogue_check] {slug}: D1 {'✓' if d1['ok'] else '✗'} "
          f"(labeled {d1['labeled']}/{d1['prose_paragraphs']}, unknown={len(d1['unknown_labels'])}) "
          f"D2 {'✓' if d2_ok else '✗'} "
          f"(coverage={coverage:.2f} order={order_ratio:.2f} matched={len(matched)}) "
          f"D3 {'warn' if d3_warn else 'ok'}(mismatch_ratio={mismatch_ratio:.2f})")

    if not d1["ok"]:
        print(f"        - D1 未過:unlabeled={len(d1['unlabeled'])} "
              f"unknown_labels={d1['unknown_labels'][:5]}", file=sys.stderr)
    if not d2_ok:
        reasons = []
        if not d2_a:
            reasons.append(f"coverage {coverage:.2f} < {D2_COVERAGE_MIN}")
        if not d2_b:
            reasons.append(f"order_ratio {order_ratio:.2f} < {D2_ORDER_MIN}")
        if not d2_c:
            reasons.append(f"matched {len(matched)} < {D2_MIN_ANCHORS}(reference_notes 需補具體專名/產品名再重跑)")
        print(f"        - D2 未過:{'; '.join(reasons)}", file=sys.stderr)

    if converged:
        status = "warn" if d3_warn else "pass"
    else:
        status = "fail"
    _log(session_dir, status,
         {"d1_ok": d1["ok"], "d2_ok": d2_ok, "d3_mismatch_ratio": round(mismatch_ratio, 4)},
         f"coverage={coverage:.2f} order_ratio={order_ratio:.2f}")

    if not converged:
        if not d1["ok"]:
            _enqueue(slug, f"D1 歸屬覆蓋未過:unlabeled={len(d1['unlabeled'])} "
                           f"unknown_labels={d1['unknown_labels'][:5]}",
                     "補上 `名字：` 段首標籤(§ R2.1 多講者專則)")
        if not d2_ok:
            _enqueue(slug, f"D2 順序/覆蓋未過:coverage={coverage:.2f} order_ratio={order_ratio:.2f} "
                           f"matched={len(matched)}",
                     "對照 reference_notes.md 修正段落順序/補漏,或補具體專名再重跑")
    if d3_warn:
        for m in mismatches[:10]:
            _enqueue(slug, f"D3 跨講者混併:note(講者={m['note_speaker']}) 落點段講者="
                           f"{para_speaker.get(m['para_idx'])} para_idx={m['para_idx']}",
                     "人工複核歸屬(引述他人話語屬正常情形,非必然錯誤)")

    return 0 if converged else 1


if __name__ == "__main__":
    raise SystemExit(main())
