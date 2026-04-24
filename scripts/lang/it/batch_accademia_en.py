#!/usr/bin/env python3
"""
批次轉錄佛羅倫斯學院美術館導覽音檔 (0-15)，英文模式，合併為單一 SRT。
"""

import os, sys, subprocess, requests, time, shutil
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

def transcribe_file(filepath, api_key):
    tmp_mp3 = filepath + ".tmp.mp3"
    subprocess.run(
        ["ffmpeg", "-y", "-i", filepath, "-vn", "-ar", "16000", "-ac", "1", "-b:a", "64k", tmp_mp3],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )

    prompt = (
        "This is an English audio guide for the Galleria dell'Accademia in Florence. "
        "Topics include: Michelangelo, David, Prisoners, non-finito, contrapposto, "
        "Giambologna, Rape of the Sabines, Botticelli, Ghirlandaio, Perugino, "
        "Stradivari, Cristofori, pianoforte, Medici, Carrara marble, Renaissance, "
        "Saint Matthew, plaster models, Bartolini, Gipsoteca, Tribune, "
        "Sala del Colosso, Hall of the Prisoners, musical instruments."
    )

    data = {
        "model": "whisper-large-v3",
        "prompt": prompt[:896],
        "response_format": "verbose_json",
        "language": "en",
        "temperature": "0.0"
    }

    segments = []
    with open(tmp_mp3, "rb") as f:
        files = {"file": (os.path.basename(tmp_mp3), f, "audio/mpeg")}
        resp = requests.post(GROQ_URL, headers={"Authorization": f"Bearer {api_key}"}, data=data, files=files)
    os.remove(tmp_mp3)

    if resp.status_code != 200:
        print(f"  ERROR {resp.status_code}: {resp.text[:300]}", file=sys.stderr)
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
    # Use 3 working keys
    api_keys = [
        os.environ.get("GROQ_API_KEY", ""),
        os.environ.get("GROQ_API_KEY_3", ""),
        os.environ.get("GROQ_API_KEY_4", ""),
    ]
    api_keys = [k for k in api_keys if k]

    base_dir = "/Users/shuotaochiang/Desktop/study"
    prefix = "フィレンツェのアカデミア美術館"

    files = []
    for i in range(16):
        if i == 1:
            path = os.path.join(base_dir, f"{prefix}1.m4a")
        else:
            path = os.path.join(base_dir, f"{prefix} {i}.m4a")
        if os.path.exists(path):
            files.append((i, path))
        else:
            print(f"WARNING: Missing #{i}", file=sys.stderr)

    output_srt = os.path.join(base_dir, "フィレンツェのアカデミア美術館.srt")

    cumulative_offset = 0.0
    all_segments = []

    print(f"[batch-en] Transcribing {len(files)} files in ENGLISH mode...")
    t0 = time.time()

    for idx, (num, path) in enumerate(files):
        key = api_keys[idx % len(api_keys)]
        actual_duration = get_duration(path)
        print(f"[{num:2d}] {os.path.basename(path)} ({actual_duration:.0f}s) key#{idx % len(api_keys)+1}")

        segments, api_dur = transcribe_file(path, key)
        duration = actual_duration if actual_duration > 0 else api_dur

        for s, e, t in segments:
            all_segments.append((s + cumulative_offset, e + cumulative_offset, t))

        print(f"     -> {len(segments)} segments")
        cumulative_offset += duration
        if idx < len(files) - 1:
            time.sleep(0.5)

    with open(output_srt, "w", encoding="utf-8") as f:
        for i, (start, end, text) in enumerate(all_segments, 1):
            f.write(f"{i}\n{fmt(start)} --> {fmt(end)}\n{text}\n\n")

    elapsed = time.time() - t0
    print(f"\n[batch-en] Done! {len(all_segments)} segments in {elapsed:.1f}s")
    print(f"[batch-en] Output: {output_srt}")

if __name__ == "__main__":
    main()
