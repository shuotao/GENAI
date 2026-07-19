#!/usr/bin/env python3
"""Step 4.5 書本 master 收斂器(取代寫死的 build_genai2026_day1/day2.py)。

把 State A(拆檔)與 State B(一檔多講者)都**正規化成同一個 canonical master**
(build/<slug>/publish.md + toc.json),讓 Step 5(md_to_html.py)與 Step 6(publish_qaqc.py)
一視同仁 —— 這是「發布一致性」的樞紐。SSoT: prompts/publish_qaqc.md § S4.5.13。

收斂不變式(emit_canonical 是唯一寫 bytes 的地方 → A 與 B 輸出骨架位元等價):
  第 1 行  : `# <書名>`
  第 2 行  : `*<副標>*`(可選)
  逐章     : `## 第 N 場 · <類別>｜<講者短名>` + 章內 blocks(只含 `### `+段落+`![]()`)
  其餘     : 零 `#`、無 `#### `/`>`/list/table/`---`
  且 count(^## ) == len(toc.json) == 場數

兩個子命令(對齊原則 9 分類後停、人工確認再往下):
  init  : 依 classify 結果產 build/<slug>/book.json 範本(講者/類別 stub 待人工補),不建 master
  build : 讀 book.json → publish.md + toc.json + self-assert

用法:
  python3 scripts/build_book_master.py init  --dirs <dir>... --slug <slug> [--title T] [--shelf public]
  python3 scripts/build_book_master.py build --dirs <dir>... --book build/<slug>/book.json
"""
from __future__ import annotations
import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from classify_session import classify, H1_RE, H2_RE          # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
IMG_RE = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")
BARE_PNG_RE = re.compile(r"(!\[[^\]]*\]\()([^)/]+\.(?:png|jpg|jpeg|webp))(\))", re.I)


@dataclass
class Chapter:
    index: int          # 0 = 開場, 1..N = 講者場
    category: str       # 類別:企業案例 / 教學 / AI AGENT / 對談 / 開場 …
    name: str           # 講者短名(進 ## 標題):小馮 / 主持人
    full: str           # 講者全名(進 toc.speakers):小馮 · 薩泰爾娛樂 全端工程師
    talk: str           # 講題(進 toc.talk)
    blocks: list = field(default_factory=list)   # 已正規化:只含 ### / 段落 / ![]()


# ---------- 共用:把一段 cleaned 內文正規化成 blocks(## → ###,剝不支援語法) ----------
def _normalize_body(lines: list[str], img_prefix: str | None) -> list[str]:
    out = []
    for ln in lines:
        s = ln.rstrip()
        if not s.strip():
            out.append("")
            continue
        if s.strip() == "---":
            continue
        if s.startswith("#### "):
            s = "###" + s[4:]
        elif H2_RE.match(s):                    # ## 小節 → ### 子標
            s = "#" + s
        elif s.startswith("**講者") or s.startswith("**講題"):
            continue
        elif s.startswith(">"):                 # 引言標記剝除,保留內容(零省略)
            body = s[1:].strip()
            if not body:
                continue
            s = body
        if img_prefix:                          # 跨 deck 圖名加前綴,避免合併撞名
            s = BARE_PNG_RE.sub(lambda m: f"{m.group(1)}{img_prefix}-{m.group(2)}{m.group(3)}", s)
        out.append(s)
    # 收斂連續空行
    collapsed, prev_blank = [], False
    for s in out:
        blank = (s == "")
        if blank and prev_blank:
            continue
        collapsed.append(s)
        prev_blank = blank
    return collapsed


def _first_h1_text(lines: list[str]) -> str:
    for ln in lines:
        if H1_RE.match(ln):
            return ln[2:].strip()
    return ""


# ---------- State A:concat-demote ----------
def parse_state_a(dirs: list[Path], speakers: list[dict]) -> list[Chapter]:
    chapters = []
    for k, d in enumerate(dirs, start=1):
        lines = (d / "cleaned.md").read_text(encoding="utf-8").splitlines()
        # 丟掉那一個 # 講題行(改由 ## 第N場 承載),其餘正規化
        body = [ln for ln in lines if not H1_RE.match(ln)]
        blocks = _normalize_body(body, img_prefix=f"s{k}")
        sp = speakers[k - 1]
        chapters.append(Chapter(
            index=k, category=sp.get("category", ""),
            name=sp.get("name", ""), full=sp.get("full", sp.get("name", "")),
            talk=sp.get("talk") or _first_h1_text(lines), blocks=blocks))
    return chapters


# ---------- State B:split-promote ----------
def parse_state_b(one_dir: Path, speakers: list[dict]) -> list[Chapter]:
    lines = (one_dir / "cleaned.md").read_text(encoding="utf-8").splitlines()
    # 依頂層 # 切段;首個 # 前的內容 = 開場段
    segs = []                       # [(h1_text_or_None, [body lines])]
    cur_title, cur_body = None, []
    for ln in lines:
        if H1_RE.match(ln):
            segs.append((cur_title, cur_body))
            cur_title, cur_body = ln[2:].strip(), []
        else:
            cur_body.append(ln)
    segs.append((cur_title, cur_body))

    chapters, sp_i = [], 0
    for seg_i, (title, body) in enumerate(segs):
        if seg_i == 0:
            if not any(s.strip() for s in body):
                continue            # 首個 # 前沒內容 → 無開場場
            idx = 0
        else:
            idx = seg_i
        blocks = _normalize_body(body, img_prefix=None)     # 單 deck,不改圖名
        sp = speakers[sp_i]; sp_i += 1
        chapters.append(Chapter(
            index=idx, category=sp.get("category", ""),
            name=sp.get("name", ""), full=sp.get("full", sp.get("name", "")),
            talk=sp.get("talk") or (title or ""), blocks=blocks))
    return chapters


# ---------- 唯一 bytes 出處:位元等價保證在這裡 ----------
def emit_canonical(chapters: list[Chapter], title: str, subtitle: str) -> tuple[str, list[dict]]:
    lines = [f"# {title}"]
    if subtitle:
        lines.append(f"*{subtitle}*")
    toc = []
    for ch in chapters:
        lines.append("")
        lines.append(f"## 第 {ch.index} 場 · {ch.category}｜{ch.name}")
        # 章內 blocks 開頭去除多餘空行
        body = ch.blocks
        while body and body[0] == "":
            body = body[1:]
        lines.extend(body)
        toc.append({"time": ch.category, "talk": ch.talk, "speakers": ch.full})
    md = "\n".join(lines).strip() + "\n"
    return md, toc


# ---------- self-assert(唯一一處,不複製進 gate) ----------
def _cjk(s: str) -> int:
    return len(re.findall(r"[一-鿿]", s))


def self_assert(md: str, toc: list[dict], expected: int, sources: list[Path]) -> None:
    lines = md.splitlines()
    n_chapters = sum(1 for l in lines if H2_RE.match(l))
    n_h1 = sum(1 for l in lines if H1_RE.match(l))
    errs = []
    if not (n_chapters == len(toc) == expected):
        errs.append(f"章數/toc/場數不一致: ##={n_chapters}, toc={len(toc)}, 期望={expected}")
    if n_h1 != 1:
        errs.append(f"頂層 # 應恰 1 個,實得 {n_h1}")
    for pat, label in [(r"^#### ", "H4"), (r"^> ", "blockquote"), (r"^- ", "bullet"),
                       (r"^\|", "table"), (r"^---$", "hr"), (r"!\[[^\]]*\]\(<", "圖檔<>包覆")]:
        c = sum(1 for l in lines if re.search(pat, l))
        if c:
            errs.append(f"殘留不支援語法 {label}: {c}")
    src_cjk = sum(_cjk((d / "cleaned.md").read_text(encoding="utf-8")) for d in sources)
    out_cjk = _cjk(md)
    if src_cjk and out_cjk < src_cjk * 0.995:
        errs.append(f"零省略失守: publish.md CJK={out_cjk} < 來源 {src_cjk}*0.995={src_cjk*0.995:.0f}")
    if errs:
        sys.exit("[build] self-assert 失敗:\n  - " + "\n  - ".join(errs))
    print(f"[build] self-assert ✓  章數={n_chapters}==toc=={len(toc)}==場數={expected};"
          f" 頂層#=1;CJK={out_cjk}(來源{src_cjk})")


# ---------- init:產 book.json 範本(講者/類別 stub 待人工補) ----------
def _speaker_stub_a(d: Path) -> dict:
    ctx = (d / "context.txt")
    name = full = ""
    if ctx.is_file():
        m = re.search(r"講者[:：]\s*([^。\n]+)", ctx.read_text(encoding="utf-8"))
        if m:
            full = m.group(1).strip().rstrip("。")
            name = re.split(r"[,,·]", full)[0].strip()
    lines = (d / "cleaned.md").read_text(encoding="utf-8").splitlines()
    return {"category": "", "name": name, "full": full or name, "talk": _first_h1_text(lines)}


def _speaker_stub_b(title: str, is_opening: bool) -> dict:
    if is_opening:
        return {"category": "開場", "name": "主持人", "full": "主持人", "talk": "開場"}
    # 「第一位老師:Revit API…」→ name=第一位老師, talk=Revit API…
    name, _, talk = title.partition("：")
    if not talk:
        name, _, talk = title.partition(":")
    return {"category": "", "name": name.strip() or title, "full": name.strip() or title,
            "talk": (talk or title).strip()}


def cmd_init(a) -> int:
    dirs = [Path(x) for x in a.dirs]
    c = classify(dirs)
    slug = a.slug or c.book_slug or "book"
    speakers = []
    if c.state == "A":
        speakers = [_speaker_stub_a(d) for d in dirs]
    elif c.state == "B":
        lines = (dirs[0] / "cleaned.md").read_text(encoding="utf-8").splitlines()
        titles = [ln[2:].strip() for ln in lines if H1_RE.match(ln)]
        has_open = c.chapter_boundaries and c.chapter_boundaries[0].get("kind") == "opening"
        if has_open:
            speakers.append(_speaker_stub_b("", True))
        speakers += [_speaker_stub_b(t, False) for t in titles]
    else:
        speakers = [_speaker_stub_a(dirs[0])]
    book = {"slug": slug, "title": a.title or slug, "subtitle": a.subtitle or "",
            "shelf": a.shelf, "state": c.state, "recommended_mode": c.recommended_mode,
            "sources": [d.name for d in dirs], "speakers": speakers}
    wd = ROOT / "build" / slug
    wd.mkdir(parents=True, exist_ok=True)
    (wd / "book.json").write_text(json.dumps(book, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[init] 已寫 {wd/'book.json'}(state={c.state}, {len(speakers)} 場)")
    print("[init] ⚠ 原則9:請人工補齊每場的 category/name/full/talk,再跑 build。")
    return 0


def cmd_build(a) -> int:
    book = json.loads(Path(a.book).read_text(encoding="utf-8"))
    dirs = [Path("sessions") / s if not Path(s).exists() else Path(s) for s in book["sources"]]
    dirs = [d if d.exists() else (ROOT / "sessions" / Path(s).name)
            for d, s in zip(dirs, book["sources"])]
    c = classify(dirs)
    speakers = book["speakers"]
    if c.state == "A":
        chapters = parse_state_a(dirs, speakers)
    elif c.state == "B":
        chapters = parse_state_b(dirs[0], speakers)
    else:
        print("[build] State C → 不建 master(--single 直接吃 cleaned.md);寫 .single 意圖。")
        wd = ROOT / "build" / book["slug"]; wd.mkdir(parents=True, exist_ok=True)
        (wd / ".single").write_text(book["sources"][0] + "\n", encoding="utf-8")
        return 0
    if len(speakers) != c.speaker_count:
        sys.exit(f"[build] book.json speakers={len(speakers)} 與分類場數={c.speaker_count} 不符")
    md, toc = emit_canonical(chapters, book["title"], book.get("subtitle", ""))
    self_assert(md, toc, c.speaker_count, dirs)
    wd = ROOT / "build" / book["slug"]; wd.mkdir(parents=True, exist_ok=True)
    (wd / "publish.md").write_text(md, encoding="utf-8")
    (wd / "toc.json").write_text(json.dumps(toc, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[build] 已寫 {wd/'publish.md'} + toc.json({len(toc)} 章);mode={c.recommended_mode}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Step 4.5 書本 master 收斂器")
    sub = ap.add_subparsers(dest="cmd", required=True)
    pi = sub.add_parser("init"); pi.add_argument("--dirs", nargs="+", required=True)
    pi.add_argument("--slug"); pi.add_argument("--title"); pi.add_argument("--subtitle")
    pi.add_argument("--shelf", default="public", choices=["public", "seminar", "reading"])
    pi.set_defaults(fn=cmd_init)
    pb = sub.add_parser("build"); pb.add_argument("--dirs", nargs="+")
    pb.add_argument("--book", required=True); pb.set_defaults(fn=cmd_build)
    a = ap.parse_args()
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
