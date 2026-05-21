#!/usr/bin/env python3
"""
srt_to_md.py — Stage 2: 去時間軸、合併、通順的對話稿(cleaned.md)。

Implements CLAUDE.md 「整理」定義 + 零省略原則(Zero Omission):
  - 移除時間軸與序號
  - 合併破碎斷行為完整段落(SRT cue 是依英文斷句切的,中文重組成通順段落)
  - 依場次插入 Markdown 標題(標題是插在段落之間的「導覽」,不取代原文)
  - **絕不**摘要、濃縮、改寫、第三人稱化 —— 每一個 kept cue 的文字都完整出現

輸入(沿用 srt_zhtw.py 的 workdir):
  <workdir>/segments.json   — [{"i","tc","en"}]  (原始順序與分段)
  <workdir>/zh_parts/*.json — {"<i>":"<繁中譯文>"}
  <workdir>/drops.json      — [i,...] 幻覺/雜訊,排除
  <workdir>/headings.json   — {"<i>":"## 標題"} 在該 cue 之前插入標題

用法:
  python3 srt_to_md.py <workdir> <out.md> [--title "標題"] [--subtitle "副標"]
"""
import sys, json, glob, re, argparse
from pathlib import Path

PARA_MIN_CHARS = 300          # 段落達此長度且句尾收束即換段
SENT_END = "。！？”」』）.!?"   # 視為句子結束的字元


def load(workdir):
    segs = json.loads(Path(workdir, "segments.json").read_text(encoding="utf-8"))
    drops = set()
    p = Path(workdir, "drops.json")
    if p.exists():
        drops = set(json.loads(p.read_text(encoding="utf-8")))
    headings = {}
    h = Path(workdir, "headings.json")
    if h.exists():
        headings = {int(k): v for k, v in json.loads(h.read_text(encoding="utf-8")).items()}
    zh = {}
    for pf in sorted(glob.glob(str(Path(workdir, "zh_parts", "*.json")))):
        for k, v in json.loads(Path(pf).read_text(encoding="utf-8")).items():
            zh[int(k)] = v
    return segs, drops, headings, zh


def tidy(text: str) -> str:
    """合併接縫時的輕量清理:去掉標記前後缺口用的前導省略號/破折號,不刪任何實質字。"""
    t = text.strip()
    t = re.sub(r"^[…—\-]+", "", t).strip()   # 去掉開頭的「……」「——」接縫標記
    return t


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("workdir")
    ap.add_argument("out_md")
    ap.add_argument("--title", default="完整演講逐字稿")
    ap.add_argument("--subtitle", default="")
    args = ap.parse_args()

    segs, drops, headings, zh = load(args.workdir)

    out = []
    if args.title:
        out.append(f"# {args.title}\n")
    if args.subtitle:
        out.append(f"*{args.subtitle}*\n")

    para = ""          # 累積中的段落

    def flush():
        nonlocal para
        if para.strip():
            out.append(para.strip() + "\n")
        para = ""

    kept = 0
    src_chars = 0
    for s in segs:
        i = s["i"]
        if i in drops:
            continue
        if i not in zh:
            continue
        # 場次標題:換段、插標題(標題前留空行)
        if i in headings:
            flush()
            out.append(headings[i] + "\n")
        txt = tidy(zh[i])
        if not txt:
            continue
        kept += 1
        src_chars += len(zh[i])
        para += txt
        # 段落收束:夠長且本句以句末標點結尾 → 換段
        if len(para) >= PARA_MIN_CHARS and para[-1] in SENT_END:
            flush()
    flush()

    md = "\n".join(out).rstrip() + "\n"
    Path(args.out_md).write_text(md, encoding="utf-8")

    # 零省略量化檢查:md 正文(去標題行)字數 vs 譯文來源字數
    body = "\n".join(l for l in md.splitlines() if not l.lstrip().startswith("#")
                     and not l.strip().startswith("*"))
    body_chars = len(re.sub(r"\s", "", body))
    src_nospace = src_chars  # zh cue 已是無時間軸文字
    ratio = body_chars / max(1, src_nospace)
    print(f"[md] kept cues       : {kept}")
    print(f"[md] 來源譯文字數     : {src_nospace}")
    print(f"[md] 正文字數(去標題): {body_chars}")
    print(f"[md] 保留率           : {ratio:.3%}  (零省略應 ≈100%+)")
    print(f"[md] 段落數           : {sum(1 for l in md.splitlines() if l and not l.startswith('#') and not l.startswith('*') and not l.startswith('# '))}")
    print(f"[md] 寫出             : {args.out_md}")


if __name__ == "__main__":
    main()
