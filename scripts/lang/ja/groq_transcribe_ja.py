#!/usr/bin/env python3
"""
Groq Whisper 逐字稿工具 (日文版)
- 從 .env 讀取 GROQ_API_KEY
- FFmpeg 切片 → Groq Whisper API (language=ja) → SRT 輸出
- 支援 context.txt 背景詞庫
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
    current = Path(start_dir).resolve()
    for _ in range(10):
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

def load_api_keys(start_dir):
    keys = []
    current = Path(start_dir).resolve()
    for _ in range(10):
        env_path = current / ".env"
        if env_path.exists():
            with open(env_path, "r") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        key, val = line.split("=", 1)
                        if key.strip().startswith("GROQ_API_KEY"):
                            keys.append(val.strip())
            break
        current = current.parent
    seen = set()
    unique = []
    for k in keys:
        if k and k not in seen:
            seen.add(k)
            unique.append(k)
    return unique

def truncate_prompt(prompt: str, max_chars: int = 896) -> str:
    if len(prompt) <= max_chars:
        return prompt
    return prompt[:max_chars]

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

def transcribe_chunk(chunk_path, api_keys, key_index, context_prompt):
    base_prompt = "これは技術開発、AI、クラウドコンピューティングに関する会議の日本語録音です。"
    raw_prompt = f"{base_prompt} 内容包含：{context_prompt}。" if context_prompt else base_prompt
    final_prompt = truncate_prompt(raw_prompt, max_chars=896)

    data = {
        "model": "whisper-large-v3",
        "prompt": final_prompt,
        "response_format": "verbose_json",
        "language": "ja",
        "temperature": "0.0"
    }

    rate_limit_attempts = 0
    server_error_attempts_on_current_key = 0
    keys_tried_on_5xx = 0
    keys_tried_on_401 = 0
    max_rate_limit_attempts = len(api_keys) * 2
    max_5xx_per_key = 3
    max_5xx_keys = max(2, len(api_keys))

    while True:
        current_key = api_keys[key_index % len(api_keys)]
        try:
            with open(chunk_path, "rb") as f:
                files = {"file": (os.path.basename(chunk_path), f, "audio/mpeg")}
                response = requests.post(
                    GROQ_URL,
                    headers={
                        "Authorization": f"Bearer {current_key}",
                        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                    },
                    data=data,
                    files=files,
                    timeout=300,
                )
        except requests.exceptions.RequestException as e:
            print(f"  [network error] {e}", file=sys.stderr)
            response = None
            status = -1
        else:
            status = response.status_code

        if status == 200:
            return response.json(), key_index

        if status == 429:
            rate_limit_attempts += 1
            if rate_limit_attempts > max_rate_limit_attempts:
                print(f"ERROR: Rate-limit retries exhausted across {len(api_keys)} keys", file=sys.stderr)
                return None, key_index
            key_index = (key_index + 1) % len(api_keys)
            server_error_attempts_on_current_key = 0
            keys_tried_on_5xx = 0
            wait = min(10 * rate_limit_attempts, 60)
            print(f"  [rate limited] Switching to key #{key_index + 1}/{len(api_keys)}, waiting {wait}s...", file=sys.stderr)
            time.sleep(wait)
            continue

        if status == -1 or 500 <= status < 600:
            err_msg = "network error" if status == -1 else f"HTTP {status}"
            if server_error_attempts_on_current_key < max_5xx_per_key:
                server_error_attempts_on_current_key += 1
                wait = 2 ** server_error_attempts_on_current_key
                preview = (response.text[:200] if response is not None else "")
                print(f"  [server error] {err_msg} on key #{key_index % len(api_keys) + 1}, retry {server_error_attempts_on_current_key}/{max_5xx_per_key} in {wait}s | {preview}", file=sys.stderr)
                time.sleep(wait)
                continue
            keys_tried_on_5xx += 1
            if keys_tried_on_5xx >= max_5xx_keys:
                print(f"ERROR: 5xx persisted across {keys_tried_on_5xx} keys; aborting chunk", file=sys.stderr)
                return None, key_index
            key_index = (key_index + 1) % len(api_keys)
            server_error_attempts_on_current_key = 0
            print(f"  [server error] Rotating to key #{key_index + 1}/{len(api_keys)} (tried {keys_tried_on_5xx}/{max_5xx_keys} keys on 5xx)", file=sys.stderr)
            time.sleep(3)
            continue

        if status == 401:
            keys_tried_on_401 += 1
            body = response.text[:200] if response is not None else ""
            if keys_tried_on_401 >= len(api_keys):
                print(f"ERROR Groq API 401 (fatal): all {len(api_keys)} key(s) invalid | {body}", file=sys.stderr)
                return None, key_index
            key_index = (key_index + 1) % len(api_keys)
            server_error_attempts_on_current_key = 0
            print(f"  [invalid key] key #{(key_index - 1) % len(api_keys) + 1} rejected (401), rotating to key #{key_index + 1}/{len(api_keys)}", file=sys.stderr)
            continue

        body = response.text[:300] if response is not None else ""
        print(f"ERROR Groq API {status} (fatal): {body}", file=sys.stderr)
        return None, key_index

def main():
    if len(sys.argv) < 2:
        print("Usage: python3 groq_transcribe_ja.py <media_file> [output_dir] [context_file]")
        sys.exit(1)

    input_file = sys.argv[1]
    output_dir = sys.argv[2] if len(sys.argv) > 2 else os.path.dirname(os.path.abspath(input_file))
    context_file = sys.argv[3] if len(sys.argv) > 3 else None

    if not os.path.exists(input_file):
        print(f"ERROR: File not found: {input_file}", file=sys.stderr)
        sys.exit(1)

    api_keys = load_api_keys(os.path.dirname(os.path.abspath(input_file)))
    if not api_keys:
        # Try current dir
        api_keys = load_api_keys(os.getcwd())
    
    if not api_keys:
        print("ERROR: No GROQ_API_KEY* found in .env", file=sys.stderr)
        sys.exit(1)

    context_prompt = ""
    if context_file and os.path.exists(context_file):
        with open(context_file, "r", encoding="utf-8") as f:
            context_prompt = f.read().replace("\n", ", ").strip()
    
    if not context_prompt:
        candidate = os.path.join(os.path.dirname(input_file), "context.txt")
        if os.path.exists(candidate):
            with open(candidate, "r", encoding="utf-8") as f:
                context_prompt = f.read().replace("\n", ", ").strip()

    base_name = Path(input_file).stem
    temp_dir = os.path.join(output_dir, f"_temp_{base_name}")
    os.makedirs(temp_dir, exist_ok=True)
    os.makedirs(output_dir, exist_ok=True)

    srt_output = os.path.join(output_dir, f"{base_name}.srt")

    chunks = extract_and_split_audio(input_file, temp_dir)
    global_idx = 1
    key_index = 0
    failed_chunks = []
    with open(srt_output, "w", encoding="utf-8") as srt_file:
        for i, chunk_path in enumerate(chunks):
            time_offset = i * CHUNK_DURATION
            result, key_index = transcribe_chunk(chunk_path, api_keys, key_index, context_prompt)
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
            else:
                failed_chunks.append(i + 1)
            if os.path.exists(chunk_path):
                os.remove(chunk_path)

    if failed_chunks:
        print(f"FATAL: {len(failed_chunks)} chunk(s) failed: {failed_chunks}", file=sys.stderr)
        shutil.rmtree(temp_dir, ignore_errors=True)
        sys.exit(2)

    shutil.rmtree(temp_dir, ignore_errors=True)
    print(f"OUTPUT_SRT={srt_output}")

if __name__ == "__main__":
    main()
