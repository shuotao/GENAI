#!/usr/bin/env python3
"""Step 4.5→5 一致性編排(dry-run,不 deploy)。SSoT: prompts/publish_qaqc.md § S4.5.13。

把既有工具依序串起、**遇非零即停**,證明 State A(拆檔)與 State B(一檔多講者)收斂後
在 Step 5 產出的結構完全一致(session-*.html 數 == toc == count(^## )),而且全程不 deploy。

流程(只排序 + 一道 pre-deploy 結構檢查,不重造既有檢查):
  1. classify_session.classify  → 印狀態(原則9:需人工先跑 init 補好 book.json)
  2. build_book_master build     → build/<slug>/{publish.md,toc.json} + self-assert
  3. prepublish_gate.py          → 阻擋 gate(全形/marker/圖分佈,原封不動)
  4. md_to_html.py → 丟棄式 outdir(mode 由 book.recommended_mode 決定,back-anchor 由 shelf 推導)
  5. pre-deploy 結構檢查:multipage → N(session-*.html)==len(toc)==count(^## );single → 0 session + <article
  6. 印 CONVERGENCE OK

注意:Step 6 的 publish_qaqc.py 是「出版後」稽核(逐 data.js 書 audit),dry-run 階段書尚未進
data.js,故不在此呼叫;真正 deploy 後再跑 publish_qaqc.py(見 § S4.5.13 收斂 loop)。

用法:
  python3 scripts/step45_converge.py --book build/<slug>/book.json [--keep]
"""
from __future__ import annotations
import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = sys.executable

# § S4.5.7 slug→書架 back-link 對映(單一來源,不手打)
SHELF_BACK = {
    "public":  ("shelf-public",  "公開活動書架"),
    "seminar": ("shelf-seminar", "研討會書架"),
    "reading": ("shelf-reading", "讀書會書架"),
}


def _run(cmd: list[str], label: str) -> None:
    print(f"\n[converge] ▶ {label}: {' '.join(str(c) for c in cmd)}")
    r = subprocess.run(cmd)
    if r.returncode != 0:
        sys.exit(f"[converge] ✗ {label} 退出碼 {r.returncode} — 收斂中止(不 deploy)")


def main() -> int:
    ap = argparse.ArgumentParser(description="Step 4.5→5 一致性 dry-run 編排")
    ap.add_argument("--book", required=True, help="build/<slug>/book.json")
    ap.add_argument("--keep", action="store_true", help="保留 dry-run outdir")
    a = ap.parse_args()

    book = json.loads(Path(a.book).read_text(encoding="utf-8"))
    slug = book["slug"]
    shelf = book.get("shelf", "public")
    wd = ROOT / "build" / slug
    md = wd / "publish.md"
    mode = book.get("recommended_mode", "multipage")

    # 1) classify(印狀態;原則9 由人工在 init 階段已確認)
    _run([PY, str(ROOT / "scripts/classify_session.py"), *[
          str(ROOT / "sessions" / s if not Path(s).exists() else s) for s in book["sources"]]],
         "1/5 classify")

    # 2) build master + self-assert
    _run([PY, str(ROOT / "scripts/build_book_master.py"), "build", "--book", a.book],
         "2/5 build_book_master")
    if not md.is_file():
        sys.exit(f"[converge] ✗ 找不到 {md}(State C 不建 master?dry-run 只驗多場書)")

    # 3) 出版前阻擋 gate(原封不動)
    _run([PY, str(ROOT / "scripts/prepublish_gate.py"), str(md)], "3/5 prepublish_gate")

    # 4) md → HTML 到丟棄式 outdir(back-anchor 由 shelf 推導,非手打)
    outdir = wd / "_dryout"
    if outdir.exists():
        shutil.rmtree(outdir)
    outdir.mkdir(parents=True)
    back_anchor, back_label = SHELF_BACK.get(shelf, SHELF_BACK["public"])
    cmd = [PY, str(ROOT / "scripts/lang/en/md_to_html.py"), str(md), str(wd), str(outdir),
           "--base-url", f"https://goodedunote.web.app/{slug}/",
           "--back-anchor", back_anchor, "--back-label", back_label]
    cmd += ["--single"] if mode == "single" else ["--multipage"]
    _run(cmd, "4/5 md_to_html(dry-run outdir)")

    # 5) pre-deploy 結構一致性檢查(A≡B 的保證點)
    n_hh = sum(1 for l in md.read_text(encoding="utf-8").splitlines() if re.match(r"^## (?!#)", l))
    n_toc = len(json.loads((wd / "toc.json").read_text(encoding="utf-8")))
    sess = sorted(outdir.glob("session-*.html"))
    idx = outdir / "index.html"
    print(f"\n[converge] 結構:count(^## )={n_hh}  len(toc)={n_toc}  session-*.html={len(sess)}  mode={mode}")
    errs = []
    if mode == "single":
        if sess:
            errs.append(f"single 模式卻有 {len(sess)} 個 session-*.html(應 0)")
        if idx.is_file() and "<article" not in idx.read_text(encoding="utf-8"):
            errs.append("single 模式 index.html 缺 <article>")
    else:
        if not (len(sess) == n_toc == n_hh):
            errs.append(f"multipage 不一致:session={len(sess)}, toc={n_toc}, ##={n_hh}(三者須相等)")
    if errs:
        sys.exit("[converge] ✗ 結構檢查失敗:\n  - " + "\n  - ".join(errs))

    print(f"\n[converge] ✅ CONVERGENCE OK — {slug}({book.get('state','?')}態)收斂一致,"
          f"可安心跑 publish_goodedunote.sh(本輪 dry-run 未 deploy)。")
    if not a.keep:
        shutil.rmtree(outdir)
    else:
        print(f"[converge] outdir 保留於 {outdir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
