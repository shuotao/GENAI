#!/usr/bin/env python3
"""出版前強制門(原則 9 / CLAUDE.md)— 由 publish_goodedunote.sh 開頭呼叫。

確保「產出 cleaned.md 後,必須先跑過 Phase C 與 Phase D,才能進入 Step 5/6 部署」。
檢查三件事(任何一項不過 → exit 1,中止部署):

  1. 完成戳記:session 的 metadata.json 內 qaqc.phase_c.status == "done"
     且 qaqc.phase_d.status == "done"(相容舊 key step_2_2/step_2_5)。
  2. 無殘留 marker:session 根沒有 .phase_c_pending.json / .phase_d_pending.json
     (也擋舊名 .step_2_2_pending.json / .step_2_5_pending.json)。
  3. 全形 lint:被出版的 md($MD)正文「CJK 語境殘留半形標點」== 0(§ R7.1)。

從 md 路徑往上層走找含 metadata.json 的 session 根。找不到(legacy 裸 md 出版)
→ 印 warning 放行;`--require-session` 可強制要求一定要有 session。
"""
from __future__ import annotations
import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from normalize_punctuation import count_residual  # noqa: E402

# 新名 + 舊名(相容):任一存在即視為該階段未完成
PENDING_MARKERS = (".phase_c_pending.json", ".phase_d_pending.json",
                   ".step_2_2_pending.json", ".step_2_5_pending.json")
# (新 key, 舊相容 key)
STATUS_KEYS = (("phase_c", "step_2_2"), ("phase_d", "step_2_5"))


def find_session_root(md_path: Path) -> Path | None:
    """從 md 的所在目錄往上找第一個含 metadata.json 的目錄。"""
    for d in [md_path.parent, *md_path.parents]:
        if (d / "metadata.json").is_file():
            return d
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description="Step 5 出版前強制門(§ R7/§ R8 + 原則 9)")
    ap.add_argument("md", help="要出版的 markdown(通常是 _build/source.md)")
    ap.add_argument("--require-session", action="store_true",
                    help="找不到 session(metadata.json)時也視為失敗")
    a = ap.parse_args()

    md_path = Path(a.md).resolve()
    if not md_path.is_file():
        print(f"[gate] ✗ 找不到 md:{md_path}", file=sys.stderr)
        return 1

    fails: list[str] = []

    # (3) 全形 lint — 直接驗被出版的 md
    md_text_all = md_path.read_text(encoding="utf-8")
    residual = count_residual(md_text_all)
    if residual > 0:
        fails.append(f"全形 lint:{md_path.name} 仍有 {residual} 處 CJK 語境半形標點未轉"
                     f"(跑 `python3 scripts/normalize_punctuation.py {md_path.name} --in-place`)")

    # (3b) 分佈塌陷 — 無條件驗(不依賴 session;master-centric/legacy 裸 md 也擋)。
    # 這是「連續投影片倒同一段」的硬門,與 § S6.11.b 事後 audit 同口徑。
    from placement_check import overstacked, order_inversions  # noqa: E402
    # 人工確認可連放的圖(image_notes.human_grouped)→ 分佈檢核放行(§ S4.5.11 人工覆寫)
    approved: set[str] = set()
    _sessions = Path(__file__).resolve().parent.parent / "sessions"
    for np in (_sessions.glob("*/image_notes.json") if _sessions.is_dir() else []):
        try:
            for n in json.loads(np.read_text(encoding="utf-8")):
                if n.get("human_grouped"):
                    approved.add(n["file"].split("/")[-1])
        except Exception:
            pass
    # 聚合多場書:各場投影片獨立編號 → 分佈/順序必須「分章」跑,不得跨 `## 章` 比對
    # (否則第 N 場末圖 vs 第 N+1 場首圖會誤判逆位)。以 `^## ` 切章;無 `## ` 則整份為一段。
    chapters = re.split(r"(?m)^(?=## )", md_text_all) if re.search(r"(?m)^## ", md_text_all) else [md_text_all]
    for ch in chapters:
        for anchor, refs in overstacked(ch, approved=approved):
            tags = [r.split("-")[-1] for r in refs]
            fails.append(f"圖片分佈塌陷:「{anchor[:30]}…」後一口氣掛 {len(refs)} 張 {tags}"
                         f"(連續投影片未攤到對應段落;跑 placement_supervisor.py 收斂;§ S4.5.11)")
        for a_ref, a_seq, b_ref, b_seq in order_inversions(ch):
            fails.append(f"圖片順序逆位:{a_ref.split('-')[-1]}(序{a_seq})排在 "
                         f"{b_ref.split('-')[-1]}(序{b_seq})之前 — 與原始截圖順序錯位(§ S4.5.11)")

    # (1)(2) 完成戳記 + marker
    root = find_session_root(md_path)
    if root is None:
        msg = f"[gate] ⚠️ 找不到 session(往上無 metadata.json):{md_path}"
        if a.require_session:
            print(msg + " — --require-session 視為失敗", file=sys.stderr)
            fails.append("找不到 session metadata.json")
        else:
            print(msg + " — legacy 裸 md 出版,跳過戳記檢查,只做全形 lint。")
    else:
        leftover = [m for m in PENDING_MARKERS if (root / m).exists()]
        if leftover:
            fails.append(f"殘留 marker:{', '.join(leftover)}(Phase C/D 尚未完成)")
        meta = json.loads((root / "metadata.json").read_text(encoding="utf-8"))
        qaqc = meta.get("qaqc") or {}
        for new_key, old_key in STATUS_KEYS:
            entry = qaqc.get(new_key) or qaqc.get(old_key) or {}
            st = entry.get("status")
            if st != "done":
                shown = new_key if qaqc.get(new_key) is not None else f"{new_key}(/{old_key})"
                fails.append(f"metadata qaqc.{shown}.status = {st!r}(需 'done')")

        # (4) 圖片流程(§ S4.5.11)— 只在 session 有啟用圖片 stage 時檢查
        if (root / "images").is_dir() or (root / "image_notes.json").exists():
            for m in (".images_pending.json", ".image_insert_pending.json"):
                if (root / m).exists():
                    fails.append(f"殘留 marker:{m}(圖片理解/插圖尚未完成)")
            import re as _re
            notes_p = root / "image_notes.json"
            notes = json.loads(notes_p.read_text(encoding="utf-8")) if notes_p.exists() else []
            by_file = {n["file"]: n for n in notes}
            md_text = md_path.read_text(encoding="utf-8")
            refs = [m for m in _re.findall(r"!\[[^\]]*\]\(([^)]+)\)", md_text)
                    if not m.startswith("http") and m != "cover.jpg"]
            # (4a) md 每張圖要有 inserted 條目
            for ref in refs:
                n = by_file.get(ref) or by_file.get(Path(ref).name)
                if not n:
                    fails.append(f"圖片 {ref}:image_notes.json 無條目(§ S4.5.11)")
                elif n.get("status") not in ("inserted",):
                    fails.append(f"圖片 {ref}:status={n.get('status')!r}(需 'inserted')")
            # (4b) 圖文相關性(確定性計分,與 S6.11 共用)
            sys.path.insert(0, str(Path(__file__).resolve().parent))
            from img_context_score import score, verdict, THRESHOLD_FAIL  # noqa: E402
            lines = [ln for ln in md_text.splitlines() if ln.strip()]
            for i, ln in enumerate(lines):
                m = _re.match(r"^!\[[^\]]*\]\(([^)]+)\)\s*$", ln)
                if not m or m.group(1).startswith("http") or m.group(1) == "cover.jpg":
                    continue
                n = by_file.get(m.group(1)) or by_file.get(Path(m.group(1)).name)
                if not n:
                    continue  # 已在 4a 報過
                # 上下文 = 前後各自最近的正文行(向外跳過連續圖片行)
                ctx = []
                for step in (-1, 1):
                    j = i + step
                    while 0 <= j < len(lines) and lines[j].startswith("!["):
                        j += step
                    if 0 <= j < len(lines):
                        ctx.append(lines[j])
                s = score(n, ctx)
                if verdict(s) == "fail":
                    fails.append(f"圖文相關性:{m.group(1)} score={s:.3f} < {THRESHOLD_FAIL}"
                                 f"(描述與上下文不相關,複核 anchor;§ S4.5.11)")
            # (分佈塌陷已由上方 (3b) 無條件檢核涵蓋,此處不重複)

    session_id = root.name if root else md_path.stem

    if fails:
        print("[gate] ✗ 出版被擋(原則 9 — 每步須獨立完成驗證後才能往下):", file=sys.stderr)
        for f in fails:
            print(f"        - {f}", file=sys.stderr)
        try:
            sys.path.insert(0, str(Path(__file__).resolve().parent))
            from pipeline_logger import log_stage, enqueue_improvement  # noqa: E402
            log_stage(root, "S4.5-gate", "prepublish_gate.py", "fail",
                      metrics={"fails": len(fails)}, detail="; ".join(fails[:5]))
            for f in fails:
                enqueue_improvement("S4.5-gate", session_id, f)
        except Exception:  # noqa: BLE001 — logger 缺席不影響 gate 判斷
            pass
        return 1

    where = root.name if root else "(legacy 無 session)"
    print(f"[gate] ✓ Phase C/D 通過,放行出版({where},全形殘留=0)。")
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from pipeline_logger import log_stage  # noqa: E402
        log_stage(root, "S4.5-gate", "prepublish_gate.py", "pass",
                  metrics={"fails": 0}, detail=f"where={where}")
    except Exception:  # noqa: BLE001
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
