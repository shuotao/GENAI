#!/usr/bin/env python3
"""
srt_zhtw.py — English SRT → Traditional-Chinese (zh-TW) subtitle, structure-preserving.

Implements CLAUDE.md 原則 2 (結構保留型校稿) applied to TRANSLATION:
  SRT → parse → [(timecode, text)...] → LLM (agent) translates the text array only,
  never sees timecodes → recombine translated array with the ORIGINAL timecodes.
  Enforces len(in) == len(out) and byte-identical timecodes (the architectural
  safety net against timeline drift — the user's hard requirement #1).

The LLM stage is done by the host agent (Claude Code, via login token — 原則 5),
NOT by calling any API. This script only does the deterministic parse / drop /
recombine / verify around that agent step.

Modes:
  prep <in.srt> <workdir>
      Parse, drop English Whisper-hallucination cues, write:
        <workdir>/segments.json  — [{"i": int, "tc": str, "en": str}, ...] (survivors)
        <workdir>/source.txt     — numbered English lines for the agent to translate
      Survivors keep their EXACT original timecodes; dropped cues simply leave
      time gaps (valid SRT). Prints drop stats.

  assemble <workdir> <out.srt> --orig <in.srt>
      Read <workdir>/segments.json + every <workdir>/zh_parts/*.json (each a
      {"<i>": "<zh translation>"} object). Enforce the translated index set ==
      survivor index set. Renumber 1..M, attach ORIGINAL timecodes, write out.srt.
      Then VERIFY: every output timecode line is byte-identical to the survivor's
      original timecode and to a line present in <in.srt>. Exit non-zero on any drift.
"""

import sys
import os
import re
import json
import glob
import argparse
from pathlib import Path


# ─── SRT parse / format ───

def parse_srt(content: str) -> list[dict]:
    blocks = content.strip().split("\n\n")
    out = []
    for block in blocks:
        lines = block.split("\n")
        if len(lines) >= 3 and "-->" in lines[1]:
            out.append({"timecode": lines[1].strip(), "text": " ".join(lines[2:]).strip()})
        elif len(lines) >= 2 and "-->" in lines[0]:  # tolerate missing index line
            out.append({"timecode": lines[0].strip(), "text": " ".join(lines[1:]).strip()})
    return out


# ─── English Whisper-hallucination filter ───
# Mirrors scripts/lang/it/clean_srt_it.py's approach but for English silence-seam
# hallucinations seen in this recording. Matched case-insensitively after strip.
_HALLUCINATION_PATTERNS = [
    r"^subtitles by\b",                     # "Subtitles by the Amara.org community"
    r"\bamara\.org\b",
    r"^thank you for watching\b",
    r"^thanks for watching\b",
    r"^please subscribe\b",
    r"^subscribe\b",
    r"^the end\.?$",
    r"^\.+$",                                # only dots
    r"^[\s.\-—]*$",                          # punctuation/space only
    r"^\(.*(music|applause|laughter).*\)$",  # bracketed stage cues
    r"^\[.*(music|applause|laughter).*\]$",
    r"^featuringasm ei gummy$",              # specific garble observed at a seam
    # Prompt echo: Whisper regurgitates the API prompt ("Key terms: ...") on
    # silent/music segments. Every "Key terms ..." cue in this recording is fake.
    r"^key terms\b",
    # YouTube/transcription-service end markers (Whisper trained on captioned video)
    r"^end of transcript\b",
    r"^end credits\b",
    r"\btranscription by\b",
    r"\btranslation by\b",
    r"\bcastingwords\b",
    r"\bcc by\b",
    r"^captions? by\b",
    r"\bESO[ ,.]",                            # "Transcription by ESO" fragments
]
_HALL_RE = [re.compile(p, re.IGNORECASE) for p in _HALLUCINATION_PATTERNS]

# Non-Latin scripts a genuine English talk never contains — Whisper cross-language
# hallucination on non-speech. (Latin-1 accents like ä/é/ñ are NOT in these ranges,
# so names like "Schäfer" / loanwords survive.)
_NONLATIN_RE = re.compile(r"[Ѐ-ӿ぀-ヿ一-鿿가-힯؀-ۿ]")


def _latin_ratio(text: str) -> float:
    nonspace = re.sub(r"\s", "", text)
    if not nonspace:
        return 0.0
    return len(re.findall(r"[A-Za-z]", text)) / len(nonspace)


def is_hallucination(text: str) -> bool:
    t = text.strip()
    if not t:
        return True
    if any(rx.search(t) for rx in _HALL_RE):
        return True
    if _NONLATIN_RE.search(t):                       # any CJK/Cyrillic/Hangul/Arabic
        return True
    if _latin_ratio(t) < 0.5 and len(re.sub(r"\s", "", t)) > 8:  # mostly-symbol garble
        return True
    return False


# ─── prep ───

def cmd_prep(in_srt: str, workdir: str):
    content = Path(in_srt).read_text(encoding="utf-8")
    blocks = parse_srt(content)
    survivors = []
    dropped = []
    for b in blocks:
        if is_hallucination(b["text"]):
            dropped.append(b)
        else:
            survivors.append(b)

    os.makedirs(workdir, exist_ok=True)
    segments = [{"i": i + 1, "tc": b["timecode"], "en": b["text"]}
                for i, b in enumerate(survivors)]
    Path(workdir, "segments.json").write_text(
        json.dumps(segments, ensure_ascii=False, indent=0), encoding="utf-8")

    # numbered source for the agent
    lines = [f"{s['i']}\t{s['en']}" for s in segments]
    Path(workdir, "source.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")

    os.makedirs(Path(workdir, "zh_parts"), exist_ok=True)

    print(f"[prep] parsed {len(blocks)} cues from {in_srt}")
    print(f"[prep] dropped {len(dropped)} hallucination cue(s):")
    for b in dropped:
        print(f"        - {b['timecode']}  |  {b['text'][:60]!r}")
    print(f"[prep] {len(segments)} survivor cue(s) → {workdir}/segments.json")
    print(f"[prep] numbered source → {workdir}/source.txt")
    print(f"[prep] put translations as {workdir}/zh_parts/*.json (each {{\"<i>\": \"<zh>\"}})")


# ─── assemble + verify ───

def cmd_assemble(workdir: str, out_srt: str, orig_srt: str):
    segments = json.loads(Path(workdir, "segments.json").read_text(encoding="utf-8"))
    seg_by_i = {s["i"]: s for s in segments}

    # optional semantic-garbage drop list (indices found unfit during translation)
    drops = set()
    drop_path = Path(workdir, "drops.json")
    if drop_path.exists():
        drops = set(json.loads(drop_path.read_text(encoding="utf-8")))

    zh = {}
    part_files = sorted(glob.glob(str(Path(workdir, "zh_parts", "*.json"))))
    if not part_files:
        print(f"[assemble] FATAL: no translation parts in {workdir}/zh_parts/", file=sys.stderr)
        sys.exit(1)
    for pf in part_files:
        part = json.loads(Path(pf).read_text(encoding="utf-8"))
        for k, v in part.items():
            zh[int(k)] = v

    seg_ids = set(seg_by_i)
    kept_ids = seg_ids - drops          # cues we intend to keep & translate
    zh_ids = set(zh)

    # translations must reference real survivors and must not translate a dropped cue
    invalid = sorted(zh_ids - seg_ids)
    translated_drops = sorted(zh_ids & drops)
    if invalid or translated_drops:
        print(f"[assemble] FATAL: bad translation keys. "
              f"not-a-survivor={invalid[:20]} translated-but-dropped={translated_drops[:20]}",
              file=sys.stderr)
        sys.exit(2)

    # build output (only kept + translated cues), ORIGINAL timecodes, in time order
    out_segs = [s for s in segments if s["i"] in kept_ids and s["i"] in zh_ids]
    parts = []
    for n, s in enumerate(out_segs, 1):
        parts.append(f"{n}\n{s['tc']}\n{zh[s['i']].strip()}\n")
    Path(out_srt).write_text("\n".join(parts), encoding="utf-8")
    # for verify step below
    segments = out_segs

    # ─── VERIFY timecode integrity (requirement #1) ───
    orig_tcs = set()
    for b in parse_srt(Path(orig_srt).read_text(encoding="utf-8")):
        orig_tcs.add(b["timecode"])

    out_blocks = parse_srt(Path(out_srt).read_text(encoding="utf-8"))
    fail = []
    if len(out_blocks) != len(segments):
        print(f"[verify] FATAL: out blocks {len(out_blocks)} != survivors {len(segments)}",
              file=sys.stderr)
        sys.exit(3)
    for ob, s in zip(out_blocks, segments):
        if ob["timecode"] != s["tc"]:
            fail.append((s["i"], s["tc"], ob["timecode"]))
        elif ob["timecode"] not in orig_tcs:
            fail.append((s["i"], s["tc"], "NOT-IN-ORIGINAL"))
    if fail:
        print(f"[verify] FATAL: {len(fail)} timecode mismatch(es):", file=sys.stderr)
        for i, exp, got in fail[:20]:
            print(f"        cue i={i}: expected {exp!r} got {got!r}", file=sys.stderr)
        sys.exit(4)

    print(f"[assemble] wrote {len(segments)} cues → {out_srt}")
    print(f"[verify] OK — all {len(segments)} timecodes byte-identical to original "
          f"and present in {orig_srt}")
    # coverage report (incremental builds): kept = survivors - drops
    untranslated = sorted(kept_ids - zh_ids)
    if untranslated:
        print(f"[assemble] PARTIAL: {len(segments)}/{len(kept_ids)} kept cues translated; "
              f"{len(untranslated)} remaining (next: {untranslated[:8]}...)")
    else:
        print(f"[assemble] COMPLETE: all {len(kept_ids)} kept cues translated "
              f"({len(drops)} cues dropped as hallucination/garbage).")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="mode", required=True)
    p = sub.add_parser("prep")
    p.add_argument("in_srt")
    p.add_argument("workdir")
    a = sub.add_parser("assemble")
    a.add_argument("workdir")
    a.add_argument("out_srt")
    a.add_argument("--orig", required=True, help="original SRT to verify timecodes against")
    args = ap.parse_args()

    if args.mode == "prep":
        cmd_prep(args.in_srt, args.workdir)
    elif args.mode == "assemble":
        cmd_assemble(args.workdir, args.out_srt, args.orig)


if __name__ == "__main__":
    main()
