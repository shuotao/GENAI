#!/usr/bin/env python3
"""Step 4.5 場次狀態分類器（確定性,無 LLM — 見 CLAUDE.md 原則 6 / prompts/publish_qaqc.md § S4.5.13）。

判別一個 session(或一組 sibling session)的「場次狀態」,決定 Step 5 出版模式與 build_book_master.py
要做的正規化動作。只讀 cleaned.md 的 heading 行首 + 檔案系統形狀,**不讀正文、不猜門檻、不打 LLM**。

三態(SSoT: prompts/publish_qaqc.md § S4.5.13):
  A 拆檔錄音     : N 個目錄,每檔恰 1 個 `#` + 多個 `##`         → concat-demote / multipage
  B 一檔多講者   : 1 個目錄,多個 `#`(講者)+ 首個 # 前的 ## run  → split-promote / multipage
  C 單一講者     : 1 個目錄,恰 1 個 `#` + 多個 `##`              → passthrough    / single

用法:
  python3 scripts/classify_session.py <session_dir> [<session_dir> ...] [--marker] [--json]

**原則 9 確認關卡**:本工具只輸出「判定」。判定後請人工確認 state 與 speaker_count 正確,
再交給 build_book_master.py;不自動往下建 master。
"""
from __future__ import annotations
import argparse
import json
import re
import sys
from dataclasses import dataclass, asdict
from pathlib import Path

H1_RE = re.compile(r"^# (?!#)")        # `# ` 但非 `## `
H2_RE = re.compile(r"^## (?!#)")       # `## ` 但非 `### `
_SLICE_RE = re.compile(r"[/_-](\d{1,3})\.[A-Za-z0-9]+$")   # source symlink 指向分段檔(…/GENAI2026_1/7.m4a)


@dataclass
class Classification:
    state: str                       # "A" | "B" | "C"
    speaker_count: int
    chapter_boundaries: list         # A: [{dir,line}]; B: [{line,kind}]; C: [{dir,line}]
    recommended_mode: str            # "multipage" | "single"
    normalization_action: str        # "concat-demote" | "split-promote" | "passthrough"
    signals: dict                    # 逐目錄原始計數(可稽核)
    book_slug: str | None            # 建議 slug(A 無法自動推 → None;B/C 由目錄名)


def _slugify(name: str) -> str:
    s = re.sub(r"^\d{4}-\d{2}-\d{2}[_-]?", "", name)      # 去日期前綴
    s = re.sub(r"[^0-9A-Za-z]+", "-", s).strip("-").lower()
    return s or name.lower()


def _scan(cleaned: Path) -> dict:
    """回傳單一 cleaned.md 的 heading 訊號。"""
    if not cleaned.is_file():
        raise FileNotFoundError(f"缺 cleaned.md: {cleaned}")
    lines = cleaned.read_text(encoding="utf-8").splitlines()
    h1_lines, h2_lines = [], []
    seen_h1 = False
    leading_h2_run = 0
    for i, ln in enumerate(lines, 1):
        if H1_RE.match(ln):
            h1_lines.append(i)
            seen_h1 = True
        elif H2_RE.match(ln):
            h2_lines.append(i)
            if not seen_h1:
                leading_h2_run += 1
    return {
        "n_h1": len(h1_lines),
        "n_h2": len(h2_lines),
        "h1_lines": h1_lines,
        "leading_h2_run": leading_h2_run,
    }


def _sibling_group(dirs: list[Path]) -> bool:
    """≥2 目錄且共享日期前綴 + 數字尾 → 視為同一活動的拆檔。"""
    if len(dirs) < 2:
        return False
    prefixes = set()
    for d in dirs:
        m = re.match(r"(\d{4}-\d{2}-\d{2}).*?[_-](\d{1,3})$", d.name)
        if not m:
            return False
        prefixes.add(m.group(1))
    return len(prefixes) == 1


def _sliced_source(d: Path) -> bool:
    for src in d.glob("source.*"):
        try:
            tgt = src.resolve()
        except OSError:
            continue
        if _SLICE_RE.search(str(tgt)):
            return True
    return False


def classify(paths: list[Path]) -> Classification:
    dirs = [Path(p) for p in paths]
    per = {d.name: _scan(d / "cleaned.md") for d in dirs}
    sig = {
        "dirs": per,
        "sibling_group": _sibling_group(dirs),
        "sliced_source": {d.name: _sliced_source(d) for d in dirs},
    }

    # ---- 決策表(純函式,不猜門檻)----
    if len(dirs) >= 2:
        if all(per[d.name]["n_h1"] == 1 for d in dirs):
            boundaries = [{"dir": d.name, "line": per[d.name]["h1_lines"][0]} for d in dirs]
            return Classification("A", len(dirs), boundaries, "multipage",
                                  "concat-demote", sig, None)
        bad = [d.name for d in dirs if per[d.name]["n_h1"] != 1]
        sys.exit(f"[classify] 錯誤:多目錄群組(疑 State A)但這些檔的 # 數不是 1:{bad}。"
                 f"State A 每檔須恰一個 # 講題。請人工確認。")

    d = dirs[0]
    s = per[d.name]
    if s["n_h1"] >= 2:
        opening = 1 if s["leading_h2_run"] > 0 else 0
        boundaries = ([{"line": 1, "kind": "opening"}] if opening else []) + \
                     [{"line": ln, "kind": "talk"} for ln in s["h1_lines"]]
        return Classification("B", s["n_h1"] + opening, boundaries, "multipage",
                              "split-promote", sig, _slugify(d.name))
    if s["n_h1"] == 1:
        return Classification("C", 1, [{"dir": d.name, "line": s["h1_lines"][0]}],
                              "single", "passthrough", sig, _slugify(d.name))

    sys.exit(f"[classify] 錯誤:{d.name} 的 cleaned.md 沒有任何頂層 #(n_h1=0)。"
             f"無法判定場次狀態,請先確認 Phase B 是否插入了 #/## 標題。絕不臆測。")


def main() -> int:
    ap = argparse.ArgumentParser(description="Step 4.5 場次狀態分類器(A/B/C)")
    ap.add_argument("dirs", nargs="+", help="一或多個 session 目錄")
    ap.add_argument("--marker", action="store_true", help="寫 <dir>/.session_state.json")
    ap.add_argument("--json", action="store_true", help="只印 JSON(供編排腳本擷取)")
    a = ap.parse_args()

    dirs = [Path(x) for x in a.dirs]
    for d in dirs:
        if not d.is_dir():
            sys.exit(f"[classify] 不是目錄:{d}")

    c = classify(dirs)
    payload = asdict(c)

    if a.json:
        print(json.dumps(payload, ensure_ascii=False))
    else:
        print(f"[classify] state = {c.state}  ({c.normalization_action} / {c.recommended_mode})")
        print(f"[classify] 場次數(含開場) = {c.speaker_count}")
        print(f"[classify] book_slug 建議 = {c.book_slug}")
        print(f"[classify] chapter_boundaries = {c.chapter_boundaries}")
        print(f"[classify] 訊號 = {json.dumps(c.signals, ensure_ascii=False)}")
        print("[classify] ⚠ 原則9:請人工確認 state 與場次數,再跑 build_book_master.py。")

    if a.marker:
        for d in dirs:
            (d / ".session_state.json").write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[classify] marker 已寫入 {len(dirs)} 個目錄的 .session_state.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
