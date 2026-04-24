#!/usr/bin/env python3
"""Clean Italian SRT: remove metadata, hallucinated segments, merge text."""

import re
import sys

def parse_srt(text):
    """Parse SRT into list of (index, start_sec, text) tuples."""
    blocks = re.split(r'\n\n+', text.strip())
    segments = []
    for block in blocks:
        lines = block.strip().split('\n')
        if len(lines) < 3:
            continue
        try:
            idx = int(lines[0])
        except ValueError:
            continue
        # Parse timestamp
        ts_match = re.match(r'(\d{2}:\d{2}:\d{2},\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2},\d{3})', lines[1])
        if not ts_match:
            continue
        text = ' '.join(lines[2:]).strip()
        segments.append((idx, ts_match.group(1), text))
    return segments

# Hallucination patterns for Italian Whisper
HALLUCINATION_PATTERNS = [
    r'^\.{2,}$',                          # Just dots
    r'^Grazie\s*$',                       # Standalone "Grazie"
    r'^Grazie a tutti\s*$',               # Standalone "Grazie a tutti"
    r'^Grazie per la visione\s*$',        # YouTube-style hallucination
    r'^Grazie mille\s*$',                 # End filler
    r'la citt[àa] di San Paolo',         # Hallucination
    r'la citt[àa] di San Marco.*Dante',  # Hallucination block
    r'la citt[àa] di San Francesco',     # Hallucination
    r'la citt[àa] di San Lorenzo',       # Hallucination
    r'^Sottotitoli\s',                     # Subtitles
    r'^Subscribe',
    r'^Thank you',
    r'^Please note',
]

def is_hallucination(text):
    for pat in HALLUCINATION_PATTERNS:
        if re.search(pat, text.strip(), re.IGNORECASE):
            return True
    # Very short meaningless segments
    clean = re.sub(r'[^\w]', '', text)
    if len(clean) < 3:
        return True
    return False

def main():
    with open(sys.argv[1], 'r', encoding='utf-8') as f:
        content = f.read()

    segments = parse_srt(content)
    print(f"Total segments: {len(segments)}", file=sys.stderr)

    kept = []
    removed = []
    for idx, ts, text in segments:
        if is_hallucination(text):
            removed.append((idx, text[:60]))
        else:
            kept.append(text)

    print(f"Kept: {len(kept)}, Removed: {len(removed)}", file=sys.stderr)
    for idx, preview in removed:
        print(f"  [removed #{idx}] {preview}", file=sys.stderr)

    # Join all kept text
    full_text = '\n\n'.join(kept)
    print(full_text)

if __name__ == '__main__':
    main()
