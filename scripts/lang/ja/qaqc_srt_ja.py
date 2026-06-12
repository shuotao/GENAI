#!/usr/bin/env python3
"""
qaqc_srt_ja.py — SRT 的 QAQC 清理 (Japanese version)
"""

import sys
import os
import re
import json
import argparse
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Updated regex for Japanese
_CJK_RE = re.compile(
    r"["
    r"\u4E00-\u9FFF"  # Kanji
    r"\u3040-\u309F"  # Hiragana
    r"\u30A0-\u30FF"  # Katakana
    r"\uFF00-\uFFEF"  # Full-width forms
    r"，。！?、;:「」『』(()《》〈〉—…·~"
    r"]"
)

def parse_srt(content: str) -> list[dict]:
    # More robust split that handles \r\n and multiple newlines
    raw_blocks = re.split(r'\n\s*\n', content.strip())
    out = []
    for block in raw_blocks:
        lines = block.strip().split("\n")
        if len(lines) >= 3:
            # First line is index, second is timecode, rest is text
            out.append({"timecode": lines[1], "text": "\n".join(lines[2:])})
    print(f"[qaqc_ja] Parsed {len(out)} blocks from SRT.", file=sys.stderr)
    return out

def format_srt(blocks: list[dict]) -> str:
    parts = []
    for i, b in enumerate(blocks, 1):
        parts.append(f"{i}\n{b['timecode']}\n{b['text']}\n")
    return "\n".join(parts)

def phase_a_clean(blocks: list[dict]) -> list[dict]:
    out = []
    for b in blocks:
        text = b["text"].strip()
        if not text:
            continue
        # For now, minimal cleanup for Japanese
        out.append({"timecode": b["timecode"], "text": text})
    return out

def phase_b_structured(blocks: list[dict], context: str | None = None) -> list[dict]:
    CHUNK_SIZE = 100
    out_blocks = []
    
    for i in range(0, len(blocks), CHUNK_SIZE):
        chunk = blocks[i : i + CHUNK_SIZE]
        texts = [b["text"] for b in chunk]
        phase_b = Path(__file__).resolve().parent / "qaqc_phase_b_ja.py"
        payload = {"texts": texts, "context": context or ""}
        
        print(f"[qaqc_ja] Processing blocks {i+1} to {min(i + CHUNK_SIZE, len(blocks))}...", file=sys.stderr)
        
        try:
            proc = subprocess.run(
                ["python3", str(phase_b), "--mode", "structured"],
                input=json.dumps(payload, ensure_ascii=False),
                capture_output=True, text=True, check=True,
            )
            result = json.loads(proc.stdout)
            polished = result["texts"]
            
            if len(polished) != len(chunk):
                print(f"[qaqc_ja] Warning: length mismatch in chunk {i//CHUNK_SIZE + 1}. Fallback to original.", file=sys.stderr)
                out_blocks.extend(chunk)
            else:
                for b, t in zip(chunk, polished):
                    out_blocks.append({"timecode": b["timecode"], "text": t})
                    
        except subprocess.CalledProcessError as e:
            print(f"[qaqc_ja] Phase B failed with stderr in chunk {i//CHUNK_SIZE + 1}:\n{e.stderr}", file=sys.stderr)
            out_blocks.extend(chunk)
        except Exception as e:
            print(f"[qaqc_ja] Phase B failed in chunk {i//CHUNK_SIZE + 1}: {e}", file=sys.stderr)
            out_blocks.extend(chunk)
            
    return out_blocks

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input")
    ap.add_argument("-o", "--output")
    ap.add_argument("--structured", action="store_true")
    ap.add_argument("--context")
    args = ap.parse_args()

    in_path = Path(args.input)
    out_path = Path(args.output) if args.output else in_path
    
    content = in_path.read_text(encoding="utf-8")
    blocks = parse_srt(content)
    blocks = phase_a_clean(blocks)

    if args.structured:
        ctx = ""
        if args.context:
            p = Path(args.context)
            ctx = p.read_text(encoding="utf-8") if p.exists() else args.context
        blocks = phase_b_structured(blocks, context=ctx)

    out_path.write_text(format_srt(blocks), encoding="utf-8")

if __name__ == "__main__":
    main()
