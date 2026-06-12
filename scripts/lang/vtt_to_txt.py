#!/usr/bin/env python3
"""YouTube 自動字幕 VTT → 去重純文字(確定性,原則 6)。

YouTube 滾動式 VTT 的特徵:每個 cue 重複前一行字幕,新內容在含
<00:00:00.000><c> 逐字標記的那一行。本工具:
  1. 解析 cue,只取含 <c> 標記的「新內容行」(或無標記 cue 的全文)
  2. 剝除所有 inline tag,連續去重
  3. 輸出 [hh:mm:ss] text 一行一句(供後續斷段/分場次用)

用法:
  python3 scripts/lang/vtt_to_txt.py in.vtt -o out.txt
"""
import argparse
import re
import sys

TS_RE = re.compile(r"(\d{2}:\d{2}:\d{2})\.\d{3}\s+-->")
TAG_RE = re.compile(r"<[^>]+>")


def parse(path: str):
    lines = open(path, encoding="utf-8").read().splitlines()
    out = []  # (timestamp, text)
    cur_ts = None
    cue_lines = []

    def flush():
        nonlocal cue_lines
        if cur_ts is None:
            cue_lines = []
            return
        tagged = [l for l in cue_lines if "<c>" in l or re.search(r"<\d", l)]
        picked = tagged if tagged else cue_lines
        for l in picked:
            text = TAG_RE.sub("", l).strip()
            if not text:
                continue
            if out and out[-1][1] == text:
                continue
            out.append((cur_ts, text))
        cue_lines = []

    for line in lines:
        m = TS_RE.match(line.strip())
        if m:
            flush()
            cur_ts = m.group(1)
            continue
        if line.startswith(("WEBVTT", "Kind:", "Language:")) or not line.strip():
            continue
        if cur_ts is not None:
            cue_lines.append(line)
    flush()

    # 二次去重:YouTube 會把「上一行」原樣放進下一 cue 當第一行
    deduped = []
    for ts, text in out:
        if deduped and deduped[-1][1] == text:
            continue
        deduped.append((ts, text))
    return deduped


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input")
    ap.add_argument("-o", "--output", required=True)
    args = ap.parse_args()
    rows = parse(args.input)
    with open(args.output, "w", encoding="utf-8") as f:
        for ts, text in rows:
            f.write(f"[{ts}] {text}\n")
    print(f"{len(rows)} lines -> {args.output}", file=sys.stderr)


if __name__ == "__main__":
    main()
