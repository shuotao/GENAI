#!/usr/bin/env python3
"""Batch QAQC Phase A: auto-clean all SRT files to raw text."""
import re
import sys

HALLUCINATION_PREFIXES = [
    "內容包含：", "這是一段關於技術開發", "這是一段繁體中文",
    "请注意", "Please note", "Thank you", "thanks for",
    "Subtitles", "Subscribe", "字幕由",
]

TYPO_MAP = {
    "剪報": "簡報", "因該": "應該", "在來": "再來",
}

def chinese_ratio(text):
    if not text.strip():
        return 0
    chinese = len(re.findall(r'[\u4e00-\u9fff]', text))
    total = len(text.strip())
    return chinese / total if total > 0 else 0

def is_hallucination(text):
    t = text.strip()
    for prefix in HALLUCINATION_PREFIXES:
        if t.startswith(prefix):
            return True
    return False

def clean_srt(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    blocks = content.strip().split('\n\n')
    lines = []
    removed = 0

    for block in blocks:
        block_lines = block.strip().split('\n')
        # Extract text lines (skip index and timecode)
        text_lines = []
        for line in block_lines:
            line = line.strip()
            if not line:
                continue
            if re.match(r'^\d+$', line):
                continue
            if re.match(r'\d{2}:\d{2}:\d{2}', line):
                continue
            text_lines.append(line)

        text = ' '.join(text_lines).strip()
        if not text:
            removed += 1
            continue

        # Filter hallucinations
        if is_hallucination(text):
            removed += 1
            continue

        # Filter garbled text (< 25% Chinese, but allow pure English proper nouns)
        ratio = chinese_ratio(text)
        if ratio < 0.25 and len(text) > 5:
            removed += 1
            continue

        # Fix common typos
        for wrong, correct in TYPO_MAP.items():
            text = text.replace(wrong, correct)

        # Remove repeated emoji markers
        text = re.sub(r'[✅✸✦⏩○≅⏭]+\s*', '', text)

        lines.append(text)

    return lines, removed

def main():
    for i in range(1, 7):
        srt_file = f"{i}.srt"
        out_file = f"{i}_raw.txt"

        lines, removed = clean_srt(srt_file)

        with open(out_file, 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines))

        char_count = sum(len(l) for l in lines)
        print(f"{srt_file}: {len(lines)} lines kept, {removed} removed, {char_count} chars -> {out_file}")

if __name__ == '__main__':
    main()
