#!/usr/bin/env python3
"""
dedup_to_srt.py — 把 vtt_to_txt.py 產出的去滾動文字(`[hh:mm:ss] text` 每行一段)
合併成「句子級」SRT cue,時間軸直接沿用來源時間戳(原則 1/2 的精神:時間軸是證據,
這裡只做確定性合併、不改字)。

輸入每行格式: `[HH:MM:SS] 一段文字`
做法:
  - 累積片段直到遇到句末標點(. ! ? 。!?)或達到 max_chars,輸出成一個 cue。
  - cue start = 該句第一個片段的時間;end = 下一句第一個片段的時間
    (最後一句 end = start + tail_sec)。
  - 同時套用 name-corrections(JSON: {錯:對}),做確定性字串替換。

用法:
  python3 dedup_to_srt.py <dedup.txt> -o <out.srt> [--names name_corrections.json]
                          [--max-chars 200] [--tail-sec 4]
時間軸是秒級(來源就是秒級),輸出 SRT 用 ,000 毫秒。
"""

import sys
import re
import json
import argparse
from pathlib import Path

LINE_RE = re.compile(r"^\[(\d{1,2}):(\d{2}):(\d{2})\]\s*(.*)$")
SENT_END_RE = re.compile(r"[.!?。!?]['\"”’)]?\s*$")


def parse(path):
    rows = []
    for raw in Path(path).read_text(encoding="utf-8").splitlines():
        m = LINE_RE.match(raw.strip())
        if not m:
            continue
        h, mi, s, text = m.groups()
        secs = int(h) * 3600 + int(mi) * 60 + int(s)
        text = text.strip()
        if text:
            rows.append((secs, text))
    return rows


def fmt_tc(secs):
    h = secs // 3600
    m = (secs % 3600) // 60
    s = secs % 60
    return f"{h:02d}:{m:02d}:{s:02d},000"


def apply_names(text, names):
    for bad, good in names.items():
        text = text.replace(bad, good)
    return text


def merge(rows, max_chars, tail_sec, names):
    cues = []          # (start_secs, text)
    buf, start = [], None
    for secs, text in rows:
        if start is None:
            start = secs
        buf.append(text)
        joined = " ".join(buf)
        if SENT_END_RE.search(text) or len(joined) >= max_chars:
            cues.append((start, joined.strip()))
            buf, start = [], None
    if buf:
        cues.append((start, " ".join(buf).strip()))

    out = []
    for i, (start, text) in enumerate(cues):
        end = cues[i + 1][0] if i + 1 < len(cues) else start + tail_sec
        if end <= start:                 # 同秒起訖 → 至少給 1 秒,維持合法 SRT
            end = start + 1
        if names:
            text = apply_names(text, names)
        out.append((start, end, text))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("dedup")
    ap.add_argument("-o", "--output", required=True)
    ap.add_argument("--names", help="name-corrections JSON {bad: good}")
    ap.add_argument("--max-chars", type=int, default=200)
    ap.add_argument("--tail-sec", type=int, default=4)
    args = ap.parse_args()

    names = {}
    if args.names:
        names = json.loads(Path(args.names).read_text(encoding="utf-8"))

    rows = parse(args.dedup)
    cues = merge(rows, args.max_chars, args.tail_sec, names)

    parts = []
    for n, (start, end, text) in enumerate(cues, 1):
        parts.append(f"{n}\n{fmt_tc(start)} --> {fmt_tc(end)}\n{text}\n")
    Path(args.output).write_text("\n".join(parts), encoding="utf-8")
    print(f"[dedup_to_srt] {len(rows)} fragments → {len(cues)} sentence cues → {args.output}")


if __name__ == "__main__":
    main()
