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
  - **只動「僅簡體字」**(本身不是任何正體字的字),且只在含這類字的行內動;正體原文
    (含「干預」「後台」等兩可字)一律不變 → 可安全地對整份檔案自動跑(session.py 在 Phase A 後自動執行)。

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


def _load_dict(name):
    """OpenCC 套件自帶字典:每行 `來源\t目標1 目標2 …`。"""
    d = {}
    path = Path(opencc.__file__).resolve().parent / "dictionary" / name
    for line in path.read_text(encoding="utf-8").splitlines():
        if "\t" in line:
            src, tgt = line.split("\t", 1)
            d[src] = tgt.split()
    return d


def _simplified_only():
    """「僅簡體字」:簡→繁字典的來源字,且本身不是任何正體字(不在繁→簡的來源、也不在簡→繁的目標)。
    例:预/这/头/发/统 在內;干/后/台/只/了/面/制/系 不在(它們本身也是合法正體字)。"""
    st, ts = _load_dict("STCharacters.txt"), _load_dict("TSCharacters.txt")
    trad = set(ts) | {t for targets in st.values() for t in targets}
    return frozenset(s for s, t in st.items() if s not in trad and t != [s])


SIMPLIFIED_ONLY = _simplified_only()
_CONVERTER = opencc.OpenCC("s2tw")


def normalize_unit(text: str) -> str:
    """一個 cue / 一行。只有含「僅簡體字」才轉(證明它漂移了);且只接受「原字 ∈ 僅簡體字」那些位置的
    變更 —— 正體原文裡的「干預」「後台」「了解」永遠不會被動到(2026-11-08 審查:整檔 s2tw 會把
    正體「干預」改成「幹預」)。轉換仍用 s2tw 的詞組字典,所以「干预」→「干預」、「头发」→「頭髮」正確。"""
    if not any(c in SIMPLIFIED_ONLY for c in text):
        return text
    out = _CONVERTER.convert(text)
    if len(out) != len(text):
        return out  # 交由呼叫端的長度檢查中止
    # 不變式:只改「本身不是任何正體字」的字 → 正確的正體原文永遠不會被改壞。
    # 兩可字(据/干/后/里…)一律不動,即使在漂移行內(「数据」→「數据」、「头发干」的「干」不猜乾/幹),
    # 交 Phase B 依語意改(§ R2.1)。2026-11-08 第三輪審查:用鄰字推斷兩可字會把「头发干」改成「頭髮幹」。
    return "".join(o if (c in SIMPLIFIED_ONLY and c not in KEEP_AS_IS) else c for c, o in zip(text, out))


def normalize(text: str) -> str:
    """逐行處理(SRT 每個 cue 的文字是一行;md 每段一行)。行數與每行長度不變 → 時間軸不受影響。"""
    return "\n".join(normalize_unit(line) for line in text.split("\n"))


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
