#!/usr/bin/env python3
"""把 GA4 埋點補進「已經產出」的 goodedunote HTML。

為什麼需要這支:`scripts/lang/en/md_to_html.py` 的 head() 已經帶 GA_SNIPPET,
但那只影響「未來產出」的頁面。既有 16 本書、上百個頁面若要拿到埋點,
唯一的替代方案是把每本書重跑一次 publish —— 那要重過 prepublish_gate、
重壓圖、重 deploy,風險遠高於收益(原則 6:機械步驟用工具)。

本工具是冪等的:頁面裡已有 GA_ID 就跳過,可安全重跑。

用法:
    python3 scripts/inject_ga.py --dry-run
    python3 scripts/inject_ga.py
"""
import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent / "lang" / "en"))
from md_to_html import GA_ID, GA_SNIPPET  # noqa: E402  ← SSoT:片段只寫在一處

PUBLIC = pathlib.Path(__file__).resolve().parent / "publish" / "goodedunote" / "public"

# 後台不埋點:它的瀏覽會以 content_group='admin' 混進文章統計,污染數字。
EXCLUDE_DIRS = {"admin"}


def inject(path: pathlib.Path, dry_run: bool) -> str:
    """回傳 'skip' | 'inject' | 'nohead'。"""
    text = path.read_text(encoding="utf-8")
    if GA_ID in text:
        return "skip"
    if "</head>" not in text:
        return "nohead"
    if not dry_run:
        # 只換第一個 </head>,避免頁面內嵌的範例碼被誤改
        path.write_text(text.replace("</head>", f"{GA_SNIPPET}\n</head>", 1), encoding="utf-8")
    return "inject"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="只印出會改哪些檔,不寫入")
    ap.add_argument("--root", default=str(PUBLIC), help="掃描根目錄(預設 goodedunote/public)")
    args = ap.parse_args()

    root = pathlib.Path(args.root)
    if not root.is_dir():
        print(f"[inject_ga] 找不到目錄:{root}", file=sys.stderr)
        return 1

    tally = {"inject": [], "skip": [], "nohead": []}
    for html in sorted(root.rglob("*.html")):
        rel = html.relative_to(root)
        if set(rel.parts) & EXCLUDE_DIRS:
            continue
        tally[inject(html, args.dry_run)].append(rel)

    verb = "會注入" if args.dry_run else "已注入"
    print(f"[inject_ga] {verb} {len(tally['inject'])} 檔｜已有埋點跳過 {len(tally['skip'])} 檔"
          f"｜無 </head> {len(tally['nohead'])} 檔")
    for rel in tally["inject"]:
        print(f"  + {rel}")
    for rel in tally["nohead"]:
        print(f"  ! 無 </head>,未處理:{rel}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
