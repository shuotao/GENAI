#!/usr/bin/env python3
"""
scripts/image_notes_session.py — 好學生筆記「圖像版」兩階段工具。
**無後端自動化狀態機**:腳本只做確定性的事(渲染底稿、整理逐頁提示);
真正的生圖(Nano Banana)由 Antigravity / 你手動逐頁完成(腳本叫不動影像工具)。

兩階段(對應兩個 slash 指令):
  /note         → `note` 子指令:把 .md 渲染成 A4 白底「底稿」base_pNN.png(原文保真)。
                  底稿**與身份無關** → 一份底稿可重複給多個職業視角用。
  /好學生筆記    → `notes` 子指令:對某份底稿 + 指定身份,產出「逐頁 banana 提示清單」。
                  把每頁 base_pNN.png 拖進 Nano Banana、貼提示 → 該頁好學生筆記。
                  **一次一張、各自獨立 → 沒有連續/重複問題。**

依賴:Playwright(pip install playwright && playwright install chromium)。

用法:
    python3 scripts/image_notes_session.py note  <input.md> [--slug <slug>]
    python3 scripts/image_notes_session.py notes <slug> --identity "<身份>"
"""

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SESSIONS_DIR = PROJECT_ROOT / "sessions"


def _slugify(name: str) -> str:
    return re.sub(r"\s+", "-", re.sub(r"[^\w.\- ]", "", name, flags=re.UNICODE).strip())


def _rel(p: Path) -> str:
    return str(p.relative_to(PROJECT_ROOT)) if p.is_relative_to(PROJECT_ROOT) else str(p)


def _note_dir(slug: str) -> Path:
    return SESSIONS_DIR / slug / "note"


# ─── /note:生底稿(Stage 1,與身份無關)───────────────────────────────
def cmd_note(args) -> None:
    md_path = Path(args.input_md).resolve()
    if not md_path.exists():
        sys.exit(f"[note] 來源不存在:{md_path}")
    slug = args.slug or f"{dt.date.today().isoformat()}_{_slugify(md_path.stem)}"
    out_dir = _note_dir(slug)

    sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
    from md_to_a4_png import render_md_to_a4
    print("[note] 渲染 A4 白底底稿中(原文真 DOM 渲染、零遺漏)...")
    base_files, page_texts = render_md_to_a4(md_path, out_dir, prefix="base", collect_text=True)

    meta = {
        "slug": slug,
        "source_md": _rel(md_path),
        "created_at": dt.datetime.now().isoformat(timespec="seconds"),
        "pages": [{"n": i + 1, "base_png": f.name,
                   "page_text": (page_texts[i] if page_texts and i < len(page_texts) else "")}
                  for i, f in enumerate(base_files)],
    }
    (out_dir / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[note] ✓ 底稿 {len(base_files)} 頁就緒於 {out_dir.relative_to(PROJECT_ROOT)}/(base_pNN.png)")
    print("[note] 底稿與身份無關,可重複用。下一步開始生圖:")
    print(f'       python3 scripts/image_notes_session.py notes {slug} --identity "<身份>"')


# ─── /好學生筆記:生圖提示(Stage 2,指定身份)──────────────────────────
def cmd_notes(args) -> None:
    out_dir = _note_dir(args.slug)
    meta_p = out_dir / "meta.json"
    if not meta_p.exists():
        sys.exit(f"[好學生筆記] 找不到底稿:{meta_p}\n           請先 `/note` 產底稿(python3 scripts/image_notes_session.py note <md>)。")
    meta = json.loads(meta_p.read_text(encoding="utf-8"))
    ident = args.identity

    lines = [
        f"# 好學生筆記 · 逐頁 banana 提示(身份:{ident})",
        f"底稿:{meta['source_md']} · 共 {len(meta['pages'])} 頁",
        "",
        "做法:把每頁的 `base_pNN.png` **拖進 Antigravity(Nano Banana)**,貼下面的提示 → 該頁好學生筆記。",
        "**一次一張、各自獨立 → 沒有連續/重複問題。** 成品自己另存(例如同目錄 pNN.png)。",
        "",
        "## 通用提示(每頁都可用,直接複製)",
        f"> 把這張白底課程筆記頁變成「{ident}」視角的「好學生筆記」:",
        "> - 完全保留原始印刷文字(位置、內容一字不改、清晰可辨),只在上面疊手寫風格的彩色註解。",
        f"> - 6 色語義:🔵藍 圈關鍵字/底線重點;🔴紅「!」洞察、「?」疑問;🟠橘/🟢綠 邊欄用「{ident}」的生活情境做類比+便利貼;🟡黃 螢光筆標重點。",
        f"> - 底部加「💡 核心洞察」手寫框,用「{ident}」的語言總結並連結其日常。",
        "",
        "---",
        "",
    ]
    for pg in meta["pages"]:
        txt = (pg.get("page_text") or "").strip().replace("\n", " ")
        lines += [
            f"## 第 {pg['n']} 頁 → 拖入 `{pg['base_png']}`",
            "本頁內容(供你確認 banana 沒看錯、別與他頁混淆):",
            f"> {txt[:180]}{'…' if len(txt) > 180 else ''}",
            "",
        ]
    prompt_path = out_dir / f"banana_prompts_{_slugify(ident)}.md"
    prompt_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"[好學生筆記] ✓ 逐頁提示清單就緒:{_rel(prompt_path)}")
    print(f"[好學生筆記] 在 Antigravity:逐張把 {out_dir.relative_to(PROJECT_ROOT)}/base_pNN.png 拖進 Nano Banana、")
    print("            貼上對應頁的提示即可(一次一張,沒有連續/重複問題)。腳本不代呼叫影像工具。")


def main():
    ap = argparse.ArgumentParser(description="好學生筆記 圖像版:兩階段(note 生底稿 / notes 生圖提示)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    n = sub.add_parser("note", help="(/note)把 .md 渲染成 A4 白底底稿 base_pNN.png(與身份無關)")
    n.add_argument("input_md")
    n.add_argument("--slug", default=None)
    n.set_defaults(func=cmd_note)

    s = sub.add_parser("notes", help="(/好學生筆記)對底稿 + 身份產逐頁 banana 提示清單")
    s.add_argument("slug")
    s.add_argument("--identity", required=True, help="視角身份,例如『鋼琴老師』『律師』")
    s.set_defaults(func=cmd_notes)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
