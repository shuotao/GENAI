#!/usr/bin/env python3
"""Retry failed files (3, 7, 11, 15) and patch into the merged SRT."""

import os, sys, subprocess, requests, time, re
from pathlib import Path

GROQ_URL = "https://api.groq.com/openai/v1/audio/transcriptions"

def load_env():
    env_path = Path(__file__).resolve().parent / ".env"
    if env_path.exists():
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip())

def fmt(seconds):
    h = int(seconds) // 3600
    m = (int(seconds) % 3600) // 60
    s = int(seconds) % 60
    ms = int((seconds - int(seconds)) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

def get_duration(path):
    cmd = ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
           "-of", "default=noprint_wrappers=1:nokey=1", path]
    r = subprocess.run(cmd, capture_output=True, text=True)
    return float(r.stdout.strip()) if r.stdout.strip() else 0

def transcribe_file(filepath, api_key, context_prompt):
    tmp_mp3 = filepath + ".tmp.mp3"
    subprocess.run(
        ["ffmpeg", "-y", "-i", filepath, "-vn", "-ar", "16000", "-ac", "1", "-b:a", "64k", tmp_mp3],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    prompt = f"這是一段關於佛羅倫斯學院美術館（Galleria dell'Accademia）的繁體中文導覽錄音。內容包含：{context_prompt}"
    data = {
        "model": "whisper-large-v3",
        "prompt": prompt[:896],
        "response_format": "verbose_json",
        "language": "zh",
        "temperature": "0.0"
    }
    segments = []
    with open(tmp_mp3, "rb") as f:
        files = {"file": (os.path.basename(tmp_mp3), f, "audio/mpeg")}
        resp = requests.post(GROQ_URL, headers={"Authorization": f"Bearer {api_key}"}, data=data, files=files)
    os.remove(tmp_mp3)
    if resp.status_code != 200:
        print(f"  ERROR {resp.status_code}: {resp.text[:200]}", file=sys.stderr)
        return segments
    result = resp.json()
    for seg in result.get("segments", []):
        text = seg.get("text", "").strip()
        if text:
            segments.append((seg["start"], seg["end"], text))
    return segments

def main():
    load_env()
    # Use only working keys (rotate between 3)
    api_keys = [
        os.environ.get("GROQ_API_KEY", ""),
        os.environ.get("GROQ_API_KEY_3", ""),
        os.environ.get("GROQ_API_KEY_4", ""),
    ]
    api_keys = [k for k in api_keys if k]

    base_dir = "/Users/shuotaochiang/Desktop/study"
    prefix = "フィレンツェのアカデミア美術館"
    context = (
        "米開朗基羅, 大衛像, 囚奴, 未完成雕塑, non-finito, contrapposto, "
        "Giambologna, 劫奪薩賓婦女, Botticelli, Ghirlandaio, Stradivari, "
        "Cristofori, 鋼琴, Medici, 卡拉拉大理石, 佛羅倫斯, 文藝復興, "
        "聖馬太, 石膏模型, Bartolini, 樂器廳, 巨人廳, 囚奴廊"
    )

    # First, read existing SRT to get all segments and compute cumulative offsets
    # We need durations of ALL 16 files to compute correct offsets
    all_durations = []
    for i in range(16):
        if i == 1:
            path = os.path.join(base_dir, f"{prefix}1.m4a")
        else:
            path = os.path.join(base_dir, f"{prefix} {i}.m4a")
        d = get_duration(path)
        all_durations.append(d)
        print(f"File #{i}: duration={d:.1f}s")

    # Compute cumulative offsets
    offsets = [0.0]
    for d in all_durations[:-1]:
        offsets.append(offsets[-1] + d)

    # Read existing SRT
    srt_path = os.path.join(base_dir, "フィレンツェのアカデミア美術館.srt")
    with open(srt_path, "r", encoding="utf-8") as f:
        existing_content = f.read()

    # Parse existing SRT into segments
    existing_segments = []
    blocks = existing_content.strip().split("\n\n")
    for block in blocks:
        lines = block.strip().split("\n")
        if len(lines) >= 3:
            time_line = lines[1]
            text = "\n".join(lines[2:])
            m = re.match(r"(\d+:\d+:\d+,\d+)\s*-->\s*(\d+:\d+:\d+,\d+)", time_line)
            if m:
                def parse_time(t):
                    parts = t.replace(",", ".").split(":")
                    return float(parts[0])*3600 + float(parts[1])*60 + float(parts[2])
                start = parse_time(m.group(1))
                end = parse_time(m.group(2))
                existing_segments.append((start, end, text))

    # Transcribe the 4 failed files
    failed_nums = [3, 7, 11, 15]
    new_segments_map = {}  # num -> list of (abs_start, abs_end, text)

    for idx, num in enumerate(failed_nums):
        if num == 1:
            path = os.path.join(base_dir, f"{prefix}1.m4a")
        else:
            path = os.path.join(base_dir, f"{prefix} {num}.m4a")

        key = api_keys[idx % len(api_keys)]
        print(f"\n[retry] #{num}: {os.path.basename(path)}")
        segments = transcribe_file(path, key, context)
        offset = offsets[num]
        abs_segs = [(s + offset, e + offset, t) for s, e, t in segments]
        new_segments_map[num] = abs_segs
        print(f"  -> {len(segments)} segments, offset={offset:.1f}s")
        if idx < len(failed_nums) - 1:
            time.sleep(1)

    # Merge: insert new segments at correct positions
    # For each failed file, its segments should go between offset[num] and offset[num] + duration[num]
    all_segments = list(existing_segments)
    for num, segs in new_segments_map.items():
        all_segments.extend(segs)

    # Sort by start time
    all_segments.sort(key=lambda x: x[0])

    # Write merged SRT
    with open(srt_path, "w", encoding="utf-8") as f:
        for i, (start, end, text) in enumerate(all_segments, 1):
            f.write(f"{i}\n{fmt(start)} --> {fmt(end)}\n{text}\n\n")

    print(f"\n[retry] 完成！總共 {len(all_segments)} 段")
    print(f"[retry] 輸出: {srt_path}")

if __name__ == "__main__":
    main()
