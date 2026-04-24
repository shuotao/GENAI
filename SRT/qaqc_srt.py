#!/usr/bin/env python3
"""
qaqc_srt.py — SRT 的 QAQC 清理

模式:
  (default) 文字清理模式
    讀 SRT,對每一段 text 套用錯字字典、丟棄幻覺段落,輸出**標準 SRT**(時間軸原樣保留,
    僅 text 被替換;若整段被丟棄,序號會重編)。不動時間軸、不合併段落。

  --structured 結構保留型校稿(P1 關鍵功能)
    將 SRT 拆為 [(timecode, text)...],把 text 陣列丟給 LLM(只能看到文字、看不到時間
    軸),要求 LLM 回傳**等長**的校稿後陣列,再用原時間戳重組回 SRT。若長度不符即
    fallback 到純文字清理模式(不嘗試任何猜測重組)。
    → 呼叫 scripts/qaqc_phase_b.py 做 LLM 階段。

詞典:
  --domain <name>   疊加 dict/typo_dict.<name>.json
  --dict  <path>    指定單一字典檔(完整取代,不疊加)
  預設只用 dict/typo_dict.json。

用法:
    python3 SRT/qaqc_srt.py <in.srt>                           # in-place 清理
    python3 SRT/qaqc_srt.py <in.srt> -o <out.srt>              # 寫到別處
    python3 SRT/qaqc_srt.py <in.srt> --domain parenting
    python3 SRT/qaqc_srt.py <in.srt> --structured              # 需要 GEMINI_API_KEY
"""

import sys
import os
import re
import json
import argparse
import subprocess
from pathlib import Path

# Allow `dict.load` import regardless of CWD
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
from dict.load import load_typo_dict, load_hallucination_prefixes  # noqa: E402


# ─── SRT parsing ───

def parse_srt(content: str) -> list[dict]:
    """Parse SRT into [{'timecode': '00:00:00,000 --> 00:00:05,500', 'text': '...'}, ...]"""
    blocks = content.strip().split("\n\n")
    out = []
    for block in blocks:
        lines = block.split("\n")
        if len(lines) >= 3:
            out.append({"timecode": lines[1], "text": "\n".join(lines[2:])})
    return out


def format_srt(blocks: list[dict]) -> str:
    parts = []
    for i, b in enumerate(blocks, 1):
        parts.append(f"{i}\n{b['timecode']}\n{b['text']}\n")
    return "\n".join(parts)


# ─── Phase A: deterministic cleanup (same for default and structured modes) ───

# Regex patterns for garbled-text detection. Rules defined in prompts/qaqc_core_rules.md § R1.2.
# Ported from web/studio.js:isGarbled() to keep CLI/Web behavior identical.
_CJK_RE = re.compile(
    r"[一-鿿㐀-䶿豈-﫿　-〿＀-￯"
    r"，。！?、;:「」『』(()《》〈〉—…·~]"
)
_NOISE_RE = re.compile(r"[┌┐└┘├┤┬┴┼│─⊇◡◬Ⓓ჏ს⓪①②③④⑤⑥⑦⑧⑨]")
_EXOTIC_RE = re.compile(r"[Ⴀ-ჿ؀-ۿЀ-ӿ฀-๿ऀ-ॿ]")
_LONG_LATIN_RE = re.compile(r"(?:[a-zA-Z]{2,}\s+){5,}")


def is_garbled(text: str) -> bool:
    """Return True if the segment is likely Whisper garbage (see R1.2 in
    prompts/qaqc_core_rules.md). Any single rule matching flags the text.

    Note: we do NOT flag single-character texts as garbled. 1-char Chinese
    replies ("對"/"嗯"/"好"/"對啊") are common and valid in dialogue transcripts.
    The original Web `isGarbled` had `length < 2 → true` which silently dropped
    legitimate content; fixed here and in `web/studio.js` to align.
    """
    if not text:
        return True
    cjk_count = len(_CJK_RE.findall(text))
    non_space = len(re.sub(r"\s", "", text))
    if non_space == 0:
        return True
    cjk_ratio = cjk_count / non_space
    if cjk_ratio < 0.25 and non_space > 10:
        return True
    if "�" in text:
        return True
    if len(_NOISE_RE.findall(text)) > 1:
        return True
    if _EXOTIC_RE.search(text):
        return True
    if _LONG_LATIN_RE.search(text) and cjk_ratio < 0.5:
        return True
    return False


def phase_a_clean(blocks: list[dict], typo_map: dict[str, str],
                  hallucination_prefixes: list[str]) -> tuple[list[dict], dict]:
    """Apply deterministic cleanup in-place. Returns (surviving_blocks, stats).

    Rules are defined in `prompts/qaqc_core_rules.md § R1`. This function is the
    Python implementation; `web/studio.js:runPhaseA` is the JS mirror. Keep them
    aligned — if you add a rule here, add it there too.
    """
    stats = {"original": len(blocks), "dropped_empty": 0, "dropped_hallucination": 0,
             "dropped_garbled": 0, "typo_hits": 0}
    out = []
    for b in blocks:
        text = b["text"].strip()
        text = re.sub(r" {2,}", " ", text)

        # typo replacement, count hits
        for wrong, correct in typo_map.items():
            if wrong in text:
                stats["typo_hits"] += text.count(wrong)
                text = text.replace(wrong, correct)

        if not text:
            stats["dropped_empty"] += 1
            continue
        if any(text.startswith(p) for p in hallucination_prefixes):
            stats["dropped_hallucination"] += 1
            continue
        if is_garbled(text):
            stats["dropped_garbled"] += 1
            continue

        out.append({"timecode": b["timecode"], "text": text})
    stats["surviving"] = len(out)
    return out, stats


# ─── Structured-preserving polish (LLM sees text array only) ───

def phase_b_structured(blocks: list[dict], context: str | None = None) -> list[dict]:
    """Send only the text array to the Phase B polisher (scripts/qaqc_phase_b.py).

    Enforces len(input) == len(output). On any mismatch, returns the input unchanged
    (NEVER attempts to rebuild the timeline; that's the architectural safety net).
    """
    texts = [b["text"] for b in blocks]
    # Call the external polish script via stdin/stdout JSON contract
    phase_b = PROJECT_ROOT / "scripts" / "qaqc_phase_b.py"
    if not phase_b.exists():
        print(f"[qaqc] Phase B script not found: {phase_b} — skipping --structured",
              file=sys.stderr)
        return blocks

    payload = {"texts": texts, "context": context or ""}
    try:
        proc = subprocess.run(
            ["python3", str(phase_b), "--mode", "structured"],
            input=json.dumps(payload, ensure_ascii=False),
            capture_output=True, text=True, check=True,
        )
        result = json.loads(proc.stdout)
        polished = result["texts"]
    except (subprocess.CalledProcessError, json.JSONDecodeError, KeyError) as e:
        print(f"[qaqc] Phase B failed: {e} — returning unchanged", file=sys.stderr)
        return blocks

    if len(polished) != len(blocks):
        print(f"[qaqc] Phase B length mismatch: in={len(blocks)} out={len(polished)} — "
              "rejecting polished output (timecode safety)", file=sys.stderr)
        return blocks

    return [{"timecode": b["timecode"], "text": t} for b, t in zip(blocks, polished)]


# ─── Main ───

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input", help="Path to input .srt")
    ap.add_argument("-o", "--output", help="Output path (default: overwrite input)")
    ap.add_argument("--domain", help="Domain overlay, e.g. 'parenting'")
    ap.add_argument("--dict", dest="dict_path",
                    help="Use a single custom dict file (overrides base + domain)")
    ap.add_argument("--structured", action="store_true",
                    help="Also run Phase B structured polish via scripts/qaqc_phase_b.py")
    ap.add_argument("--context", help="Context string or file path to pass to Phase B")
    args = ap.parse_args()

    in_path = Path(args.input)
    out_path = Path(args.output) if args.output else in_path
    if not in_path.exists():
        print(f"Not found: {in_path}", file=sys.stderr)
        sys.exit(1)

    # Build typo map
    if args.dict_path:
        with open(args.dict_path, "r", encoding="utf-8") as f:
            typo_map = json.load(f).get("corrections", {})
        print(f"[qaqc] Using custom dict: {args.dict_path} ({len(typo_map)} entries)")
    else:
        typo_map = load_typo_dict(domain=args.domain)
        print(f"[qaqc] Loaded dict: base"
              + (f" + {args.domain}" if args.domain else "")
              + f" ({len(typo_map)} entries)")

    hallucination_prefixes = load_hallucination_prefixes()

    # Read + Phase A
    content = in_path.read_text(encoding="utf-8")
    blocks = parse_srt(content)
    blocks, stats = phase_a_clean(blocks, typo_map, hallucination_prefixes)

    print(f"[qaqc] Phase A: {stats['original']} → {stats['surviving']} blocks "
          f"(dropped {stats['dropped_empty']} empty, "
          f"{stats['dropped_hallucination']} hallucination, "
          f"{stats['dropped_garbled']} garbled; "
          f"{stats['typo_hits']} typo fixes)")

    # Phase B (optional)
    if args.structured:
        ctx = ""
        if args.context:
            p = Path(args.context)
            ctx = p.read_text(encoding="utf-8") if p.exists() else args.context
        blocks = phase_b_structured(blocks, context=ctx)
        print(f"[qaqc] Phase B (structured) complete: {len(blocks)} blocks (timecode untouched)")

    # Write
    out_path.write_text(format_srt(blocks), encoding="utf-8")
    print(f"[qaqc] Wrote: {out_path}")


if __name__ == "__main__":
    main()
