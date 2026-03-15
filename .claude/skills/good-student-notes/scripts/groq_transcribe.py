#!/usr/bin/env python3
"""
Groq Whisper 逐字稿工具 (CLI 版)
- 從 .env 讀取 GROQ_API_KEY
- FFmpeg 切片 → Groq Whisper API → SRT 輸出
- 支援 context.txt 背景詞庫

Usage:
    python3 groq_transcribe.py <media_file> [output_dir] [context_file]
"""

import os
import sys
import subprocess
import requests
import shutil
import time
from datetime import timedelta
from pathlib import Path

CHUNK_DURATION = 600  # 10 minutes per chunk
GROQ_URL = "https://api.groq.com/openai/v1/audio/transcriptions"


def load_env(start_dir):
    """從 start_dir 往上尋找 .env 並載入 GROQ_API_KEY"""
    current = Path(start_dir).resolve()
    for _ in range(10):  # 最多往上找 10 層
        env_path = current / ".env"
        if env_path.exists():
            with open(env_path, "r") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        key, val = line.split("=", 1)
                        os.environ.setdefault(key.strip(), val.strip())
            return str(env_path)
        current = current.parent
    return None


def format_srt_time(seconds):
    td = timedelta(seconds=seconds)
    total_seconds = int(td.total_seconds())
    h = total_seconds // 3600
    m = (total_seconds % 3600) // 60
    s = total_seconds % 60
    ms = int((seconds - total_seconds) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def extract_and_split_audio(input_file, temp_dir):
    base_name = Path(input_file).stem
    output_pattern = os.path.join(temp_dir, f"{base_name}_chunk_%03d.mp3")

    command = [
        "ffmpeg", "-y", "-i", input_file,
        "-vn", "-ar", "16000", "-ac", "1", "-b:a", "64k",
        "-f", "segment", "-segment_time", str(CHUNK_DURATION),
        output_pattern
    ]
    subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    chunks = sorted([
        os.path.join(temp_dir, f)
        for f in os.listdir(temp_dir)
        if f.startswith(f"{base_name}_chunk_")
    ])
    return chunks


def transcribe_chunk(chunk_path, api_key, context_prompt):
    base_prompt = "這是一段關於技術開發與會議簡報內容的繁體中文錄音。"
    final_prompt = f"{base_prompt} 內容包含：{context_prompt}。" if context_prompt else base_prompt

    data = {
        "model": "whisper-large-v3",
        "prompt": final_prompt,
        "response_format": "verbose_json",
        "language": "zh",
        "temperature": "0.0"
    }

    with open(chunk_path, "rb") as f:
        files = {"file": (os.path.basename(chunk_path), f, "audio/mpeg")}
        response = requests.post(
            GROQ_URL,
            headers={"Authorization": f"Bearer {api_key}"},
            data=data,
            files=files
        )

    if response.status_code != 200:
        print(f"ERROR Groq API {response.status_code}: {response.text[:200]}", file=sys.stderr)
        return None
    return response.json()


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 groq_transcribe.py <media_file> [output_dir] [context_file]")
        sys.exit(1)

    input_file = sys.argv[1]
    output_dir = sys.argv[2] if len(sys.argv) > 2 else os.path.dirname(os.path.abspath(input_file))
    context_file = sys.argv[3] if len(sys.argv) > 3 else None

    if not os.path.exists(input_file):
        print(f"ERROR: File not found: {input_file}", file=sys.stderr)
        sys.exit(1)

    # Load API key from .env
    env_path = load_env(os.path.dirname(os.path.abspath(input_file)))
    api_key = os.environ.get("GROQ_API_KEY", "")
    if not api_key:
        print("ERROR: GROQ_API_KEY not found in .env", file=sys.stderr)
        sys.exit(1)

    print(f"[groq] .env loaded from: {env_path}")
    print(f"[groq] Input: {input_file}")

    # Load context
    context_prompt = ""
    if context_file and os.path.exists(context_file):
        with open(context_file, "r", encoding="utf-8") as f:
            context_prompt = f.read().replace("\n", ", ").strip()
        print(f"[groq] Context loaded: {context_file}")

    # Auto-search for context.txt near the input file
    if not context_prompt:
        for candidate in [
            os.path.join(os.path.dirname(input_file), "context.txt"),
            os.path.join(os.path.dirname(input_file), "SRT", "context.txt"),
        ]:
            if os.path.exists(candidate):
                with open(candidate, "r", encoding="utf-8") as f:
                    context_prompt = f.read().replace("\n", ", ").strip()
                print(f"[groq] Context auto-detected: {candidate}")
                break

    # Prepare temp directory
    base_name = Path(input_file).stem
    temp_dir = os.path.join(output_dir, f"_temp_{base_name}")
    os.makedirs(temp_dir, exist_ok=True)
    os.makedirs(output_dir, exist_ok=True)

    srt_output = os.path.join(output_dir, f"{base_name}.srt")

    # Extract and split audio
    print(f"[groq] Extracting audio and splitting into {CHUNK_DURATION}s chunks...")
    start_time = time.time()
    chunks = extract_and_split_audio(input_file, temp_dir)
    print(f"[groq] {len(chunks)} chunks created")

    # Transcribe each chunk
    global_idx = 1
    with open(srt_output, "w", encoding="utf-8") as srt_file:
        for i, chunk_path in enumerate(chunks):
            print(f"[groq] Transcribing chunk {i+1}/{len(chunks)}...")
            time_offset = i * CHUNK_DURATION
            result = transcribe_chunk(chunk_path, api_key, context_prompt)
            if result:
                segments = result.get("segments", [])
                for seg in segments:
                    text = seg.get("text", "").strip()
                    if not text:
                        continue
                    actual_start = seg["start"] + time_offset
                    actual_end = seg["end"] + time_offset
                    srt_file.write(f"{global_idx}\n")
                    srt_file.write(f"{format_srt_time(actual_start)} --> {format_srt_time(actual_end)}\n")
                    srt_file.write(f"{text}\n\n")
                    global_idx += 1
            os.remove(chunk_path)

    # Cleanup
    shutil.rmtree(temp_dir, ignore_errors=True)

    elapsed = time.time() - start_time
    print(f"[groq] SRT saved: {srt_output}")
    print(f"[groq] Total time: {elapsed:.1f}s")
    print(f"[groq] Total segments: {global_idx - 1}")

    # Output the SRT path for the caller
    print(f"OUTPUT_SRT={srt_output}")


if __name__ == "__main__":
    main()
