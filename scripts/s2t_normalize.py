#!/usr/bin/env python3
"""簡體漂移正規化 —— 簡體字 → 台灣正體(確定性工具,原則 6)。

**Why:** `GROQ_NO_PROMPT=1` 重轉(Gotcha 7)拿掉 context prompt 的同時,也拿掉了
Whisper 的「繁體中文」語言先驗,輸出會片段性漂移成簡體(2026-08-29 MCP8 場 03:
11,272 CJK 字中 1,059 字為簡體)。這是**確定性**的字元對映,不該勞動 LLM
逐字改(原則 6),也不該混進 Phase B 的語意判斷。

用 OpenCC `s2tw`(簡 → 台灣正體字):
  - **只換字形,不換詞彙** —— 刻意不用 `s2twp`,它會把「軟件→軟體」這類
    用語一起換掉,等於改動講者原話,違反零省略/不改語意。
  - 台灣標準字形:為(非「爲」)、裡(非「裏」)、群(非「羣」)。`s2t` 會誤把
    原本就正確的「群」轉成「羣」,故不可用。
  - 對已是正體的檔案是 no-op,可安全重跑。

原則 1:`transcript.srt` 不可變 —— 本工具**拒絕**處理 transcript.srt。

用法:
    python3 scripts/s2t_normalize.py sessions/<slug>/cleaned.md --in-place
    python3 scripts/s2t_normalize.py sessions/<slug>/cleaned.md          # dry-run
"""

import argparse
import sys
from collections import Counter
from pathlib import Path

try:
    import opencc
except ImportError:
    sys.exit("ERROR: 需要 opencc —— pip install opencc-python-reimplemented")


# 這些字在台灣正體中「本來就是對的」,OpenCC 仍會依簡體讀法轉走 —— 一律保留原字。
# 逐一以 2026-08-29 MCP8 語料核對過(見 § Git 記錄):
#   台 → 臺/檯 :台灣/平台/舞台 是台灣日常標準寫法,臺/檯 是公文書體例。
#   只 → 隻   :「只要/只有」佔絕大多數,隻(量詞)極罕見。
#   了 → 瞭   :ASR 寫「了解」,台灣通用;不改成「瞭解」。
#   面 → 麵   :技術逐字稿的「面」一律是面積/表面/裡面,沒有食物。
# 反之 后→後、里→裡、干→幹、種→种、制→製、系→係 在本語料 100% 轉對,不保護。
KEEP_AS_IS = frozenset("台只了面")


def normalize(text: str) -> str:
    out = opencc.OpenCC("s2tw").convert(text)
    if len(out) != len(text):
        return out  # 交由呼叫端的長度檢查中止
    return "".join(
        src_c if src_c in KEEP_AS_IS else out_c
        for src_c, out_c in zip(text, out)
    )


def main() -> int:
    ap = argparse.ArgumentParser(description="簡體漂移 → 台灣正體(OpenCC s2tw)")
    ap.add_argument("files", nargs="+", type=Path)
    ap.add_argument("--in-place", action="store_true", help="寫回原檔(預設只報告)")
    args = ap.parse_args()

    total_changed = 0
    for path in args.files:
        if path.name == "transcript.srt":
            print(f"[s2t] SKIP {path} —— transcript.srt 不可變(原則 1)", file=sys.stderr)
            continue
        src = path.read_text(encoding="utf-8")
        out = normalize(src)
        if len(src) != len(out):
            # s2tw 是 1:1 字元對映;長度變動代表設定不對,寧可中止也不要偷改內容
            sys.exit(f"ERROR: {path} 長度不一致 ({len(src)} → {len(out)}),中止")
        diff = [(a, b) for a, b in zip(src, out) if a != b]
        total_changed += len(diff)
        top = ", ".join(f"{a}→{b}×{n}" for (a, b), n in Counter(diff).most_common(8))
        print(f"[s2t] {path}: {len(diff)} 字{' (' + top + ')' if diff else ''}")
        if args.in_place and diff:
            path.write_text(out, encoding="utf-8")
            print(f"[s2t]   ↳ written in place")

    if not args.in_place and total_changed:
        print(f"[s2t] dry-run —— 加 --in-place 才會寫回(共 {total_changed} 字)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
