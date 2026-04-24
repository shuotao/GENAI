#!/usr/bin/env python3
"""
批次轉錄佛羅倫斯學院美術館導覽音檔 (0-15)，合併為單一 SRT。
"""

import os
import sys
import subprocess
import requests
import time
import shutil
from datetime import timedelta
from pathlib import Path

GROQ_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
CHUNK_DURATION = 600

# 載入 .env
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
    """Get audio duration in seconds using ffprobe."""
    cmd = ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
           "-of", "default=noprint_wrappers=1:nokey=1", path]
    r = subprocess.run(cmd, capture_output=True, text=True)
    return float(r.stdout.strip()) if r.stdout.strip() else 0

def transcribe_file(filepath, api_key, context_prompt):
    """Transcribe a single audio file, return list of (start, end, text)."""
    # Convert to mp3 first for Groq
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
        resp = requests.post(
            GROQ_URL,
            headers={"Authorization": f"Bearer {api_key}"},
            data=data,
            files=files
        )

    os.remove(tmp_mp3)

    if resp.status_code != 200:
        print(f"  ERROR {resp.status_code}: {resp.text[:200]}", file=sys.stderr)
        return segments, 0

    result = resp.json()
    duration = result.get("duration", 0)
    for seg in result.get("segments", []):
        text = seg.get("text", "").strip()
        if text:
            segments.append((seg["start"], seg["end"], text))

    return segments, duration


def main():
    load_env()
    api_key = os.environ.get("GROQ_API_KEY", "")
    if not api_key:
        print("ERROR: No GROQ_API_KEY", file=sys.stderr)
        sys.exit(1)

    base_dir = "/Users/shuotaochiang/Desktop/study"
    prefix = "フィレンツェのアカデミア美術館"

    # Build ordered file list: 0, 1, 2, ..., 15
    files = []
    for i in range(16):
        if i == 1:
            # 檔名是 "フィレンツェのアカデミア美術館1.m4a" (no space)
            path = os.path.join(base_dir, f"{prefix}1.m4a")
        else:
            path = os.path.join(base_dir, f"{prefix} {i}.m4a")
        if os.path.exists(path):
            files.append((i, path))
        else:
            print(f"WARNING: Missing file #{i}: {path}", file=sys.stderr)

    context = (
        "米開朗基羅, 大衛像, 囚奴, 未完成雕塑, non-finito, contrapposto, "
        "Giambologna, 劫奪薩賓婦女, Botticelli, Ghirlandaio, Stradivari, "
        "Cristofori, 鋼琴, Medici, 卡拉拉大理石, 佛羅倫斯, 文藝復興, "
        "聖馬太, 石膏模型, Bartolini, 樂器廳, 巨人廳, 囚奴廊"
    )

    output_srt = os.path.join(base_dir, "フィレンツェのアカデミア美術館.srt")

    global_idx = 1
    cumulative_offset = 0.0
    all_segments = []

    print(f"[batch] 開始轉錄 {len(files)} 個檔案...")
    t0 = time.time()

    # Use multiple API keys to avoid rate limits
    api_keys = [
        os.environ.get("GROQ_API_KEY", ""),
        os.environ.get("GROQ_API_KEY_3", ""),
        os.environ.get("GROQ_API_KEY_4", ""),
        os.environ.get("GROQ_API_KEY_ORIGINAL", ""),
    ]
    api_keys = [k for k in api_keys if k]

    for idx, (num, path) in enumerate(files):
        key = api_keys[idx % len(api_keys)]
        print(f"[batch] #{num}: {os.path.basename(path)} (key #{idx % len(api_keys) + 1})")

        # Get actual duration for offset calculation
        actual_duration = get_duration(path)

        segments, api_duration = transcribe_file(path, key, context)
        duration = actual_duration if actual_duration > 0 else api_duration

        for start, end, text in segments:
            all_segments.append((start + cumulative_offset, end + cumulative_offset, text))

        print(f"  -> {len(segments)} segments, duration={duration:.1f}s")
        cumulative_offset += duration

        # Small delay to avoid rate limiting
        if idx < len(files) - 1:
            time.sleep(0.5)

    # Write merged SRT
    with open(output_srt, "w", encoding="utf-8") as f:
        for i, (start, end, text) in enumerate(all_segments, 1):
            f.write(f"{i}\n{fmt(start)} --> {fmt(end)}\n{text}\n\n")

    elapsed = time.time() - t0
    print(f"\n[batch] 完成！共 {len(all_segments)} 段，耗時 {elapsed:.1f}s")
    print(f"[batch] 輸出: {output_srt}")


if __name__ == "__main__":
    main()
