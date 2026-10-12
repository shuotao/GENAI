#!/usr/bin/env python3
"""文件同步守門(§ 文件同步守則)—— 把「人工記得同步」換成機械斷言。

Why:2026-10-12 盤點發現 23 支 `scripts/` 工具沒有出現在 CLAUDE.md 或 README.md
的任何清單裡(含 2026-09-05 才進 repo 的 retire_list_label.py),而 CLAUDE.md 的
「文件同步守則」要求每次動到 pipeline 階段或公開工具就同步四個地方
(程式 → CLAUDE.md Key Files → CLAUDE.md 散文 → README /scripts 清單)。
一條已經在 23 個檔案上靜默失效的榮譽制規則,應該換成閘門(呼應原則 6:
確定性工作用工具)。

兩條斷言:
  T1 工具清單:每個 scripts/*.py|sh 與 scripts/lang/**/*.py 都要出現在 docs/tools.md
  T2 停點集合:文件寫的 --stop-at 值 == session.py argparse 的 choices

用法:
    python3 scripts/tests/test_docs_sync.py          # 0=通過 1=失敗
    python3 -m pytest scripts/tests/test_docs_sync.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOOLS_DOC = ROOT / "docs" / "tools.md"
SESSION_PY = ROOT / "scripts" / "session.py"
STOPAT_DOCS = (ROOT / "CLAUDE.md", ROOT / "README.md")

# 不是「公開工具」的東西:測試自身、快取、備份
EXCLUDE_PARTS = ("tests", "__pycache__")
EXCLUDE_SUFFIX = (".bak",)


def public_tools() -> list[Path]:
    out: list[Path] = []
    for p in sorted((ROOT / "scripts").glob("*.py")) + sorted((ROOT / "scripts").glob("*.sh")):
        out.append(p)
    out += sorted((ROOT / "scripts" / "lang").rglob("*.py"))
    return [p for p in out
            if not any(part in EXCLUDE_PARTS for part in p.parts)
            and not p.name.endswith(EXCLUDE_SUFFIX)]


def stopat_choices() -> set[str]:
    m = re.search(r"choices=\[([^\]]*?)\]", SESSION_PY.read_text(encoding="utf-8"), re.S)
    assert m, "找不到 session.py 的 --stop-at choices"
    return {c.strip().strip("\"'") for c in m.group(1).split(",") if c.strip()}


def test_every_tool_is_documented() -> list[str]:
    """T1:docs/tools.md 收錄每一支公開工具。"""
    if not TOOLS_DOC.is_file():
        return [f"缺少 {TOOLS_DOC.relative_to(ROOT)}(工具清單的唯一家)"]
    doc = TOOLS_DOC.read_text(encoding="utf-8")
    missing = [str(p.relative_to(ROOT)) for p in public_tools()
               if str(p.relative_to(ROOT)) not in doc]
    if missing:
        return [f"docs/tools.md 未收錄 {len(missing)} 支工具:" + ", ".join(missing)]
    return []


def test_stopat_matches_code() -> list[str]:
    """T2:CLAUDE.md / README.md 寫的停點集合 == session.py 的 choices。"""
    code = stopat_choices()
    fails = []
    for d in STOPAT_DOCS:
        if not d.is_file():
            continue
        t = d.read_text(encoding="utf-8")
        undocumented = sorted(c for c in code if f"`{c}`" not in t)
        if undocumented:
            fails.append(f"{d.name} 未記載 --stop-at 值:{undocumented}(程式有 {len(code)} 個)")
    return fails


def main() -> int:
    fails: list[str] = []
    fails += test_every_tool_is_documented()
    fails += test_stopat_matches_code()
    if fails:
        print("[docs-sync] ✗ 文件與程式不同步:", file=sys.stderr)
        for f in fails:
            print(f"  - {f}", file=sys.stderr)
        return 1
    n = len(public_tools())
    print(f"[docs-sync] ✓ {n} 支公開工具皆收錄於 docs/tools.md;"
          f"--stop-at {len(stopat_choices())} 個值與程式一致")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
