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
    residual = count_residual(md_path.read_text(encoding="utf-8"))
    if residual > 0:
        fails.append(f"全形 lint:{md_path.name} 仍有 {residual} 處 CJK 語境半形標點未轉"
                     f"(跑 `python3 scripts/normalize_punctuation.py {md_path.name} --in-place`)")

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

    if fails:
        print("[gate] ✗ 出版被擋(原則 9 — 每步須獨立完成驗證後才能往下):", file=sys.stderr)
        for f in fails:
            print(f"        - {f}", file=sys.stderr)
        return 1

    where = root.name if root else "(legacy 無 session)"
    print(f"[gate] ✓ Phase C/D 通過,放行出版({where},全形殘留=0)。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
