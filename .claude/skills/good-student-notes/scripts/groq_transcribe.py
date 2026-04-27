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


def load_api_keys(start_dir):
    """從 .env 讀取所有 GROQ_API_KEY* 變體並去重(保序)"""
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


def truncate_prompt_utf8(prompt: str, max_bytes: int = 896) -> str:
    """Groq Whisper prompt 有 896 bytes UTF-8 上限,超過會 400 error。
    從尾端逐字截斷直到 fit(中文字 3 bytes/字)。"""
    encoded = prompt.encode("utf-8")
    if len(encoded) <= max_bytes:
        return prompt
    # 二分法找最大可保留的 char 數
    lo, hi = 0, len(prompt)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if len(prompt[:mid].encode("utf-8")) <= max_bytes:
            lo = mid
        else:
            hi = mid - 1
    return prompt[:lo]


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
    """以多 key 輪替 + 重試轉錄。
    - 200: 成功
    - 429 (rate limit): 切下一把 key,線性退避
    - 5xx (server error): 同 key 指數退避重試;耗盡後輪替 key 再試
    - 其他 4xx: 視為致命,直接放棄
    回傳 (result_dict_or_None, updated_key_index)。
    """
    base_prompt = "這是一段關於技術開發與會議簡報內容的繁體中文錄音。"
    raw_prompt = f"{base_prompt} 內容包含：{context_prompt}。" if context_prompt else base_prompt
    final_prompt = truncate_prompt_utf8(raw_prompt, max_bytes=896)

    data = {
        "model": "whisper-large-v3",
        "prompt": final_prompt,
        "response_format": "verbose_json",
        "language": "zh",
        "temperature": "0.0"
    }

    rate_limit_attempts = 0
    server_error_attempts_on_current_key = 0
    keys_tried_on_5xx = 0
    max_rate_limit_attempts = len(api_keys) * 2
    max_5xx_per_key = 3
    max_5xx_keys = max(2, len(api_keys))  # 5xx 時最多輪過幾把 key

    while True:
        current_key = api_keys[key_index % len(api_keys)]
        try:
            with open(chunk_path, "rb") as f:
                files = {"file": (os.path.basename(chunk_path), f, "audio/mpeg")}
                response = requests.post(
                    GROQ_URL,
                    headers={"Authorization": f"Bearer {current_key}"},
                    data=data,
                    files=files,
                    timeout=300,
                )
        except requests.exceptions.RequestException as e:
            # 網路層異常視同 5xx 處理
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
                print(f"ERROR: Rate-limit retries exhausted across {len(api_keys)} keys",
                      file=sys.stderr)
                return None, key_index
            key_index = (key_index + 1) % len(api_keys)
            server_error_attempts_on_current_key = 0  # reset
            keys_tried_on_5xx = 0
            wait = min(10 * rate_limit_attempts, 60)
            print(f"  [rate limited] Switching to key #{key_index + 1}/{len(api_keys)}, "
                  f"waiting {wait}s...", file=sys.stderr)
            time.sleep(wait)
            continue

        # 5xx 或網路異常:同 key 指數退避重試;耗盡再輪 key
        if status == -1 or 500 <= status < 600:
            err_msg = f"network error" if status == -1 else f"HTTP {status}"
            if server_error_attempts_on_current_key < max_5xx_per_key:
                server_error_attempts_on_current_key += 1
                wait = 2 ** server_error_attempts_on_current_key  # 2, 4, 8s
                preview = (response.text[:200] if response is not None else "")
                print(f"  [server error] {err_msg} on key #{key_index % len(api_keys) + 1}, "
                      f"retry {server_error_attempts_on_current_key}/{max_5xx_per_key} "
                      f"in {wait}s | {preview}", file=sys.stderr)
                time.sleep(wait)
                continue
            # 同 key 試 3 次都掛 → 換下一把
            keys_tried_on_5xx += 1
            if keys_tried_on_5xx >= max_5xx_keys:
                print(f"ERROR: 5xx persisted across {keys_tried_on_5xx} keys; aborting chunk",
                      file=sys.stderr)
                return None, key_index
            key_index = (key_index + 1) % len(api_keys)
            server_error_attempts_on_current_key = 0
            print(f"  [server error] Rotating to key #{key_index + 1}/{len(api_keys)} "
                  f"(tried {keys_tried_on_5xx}/{max_5xx_keys} keys on 5xx)", file=sys.stderr)
            time.sleep(3)
            continue

        # 其他 4xx 致命錯誤(401 認證、400 格式、413 太大等)
        body = response.text[:300] if response is not None else ""
        print(f"ERROR Groq API {status} (fatal): {body}", file=sys.stderr)
        return None, key_index


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

    # Load all GROQ_API_KEY* variants from .env (rotate on rate limit)
    env_path = load_env(os.path.dirname(os.path.abspath(input_file)))
    api_keys = load_api_keys(os.path.dirname(os.path.abspath(input_file)))
    if not api_keys:
        print("ERROR: No GROQ_API_KEY* found in .env", file=sys.stderr)
        sys.exit(1)

    print(f"[groq] .env loaded from: {env_path}")
    print(f"[groq] {len(api_keys)} unique API key(s) available for rotation")
    print(f"[groq] Input: {input_file}")

    # Load context
    context_prompt = ""
    if context_file and os.path.exists(context_file):
        with open(context_file, "r", encoding="utf-8") as f:
            context_prompt = f.read().replace("\n", ", ").strip()
        print(f"[groq] Context loaded: {context_file}")

    # Auto-detect context.txt ONLY in the same directory as the input file.
    # This is intentional: context is session-scoped (lives in sessions/<id>/context.txt
    # alongside the audio), never project-scoped. We deliberately do NOT fall back to
    # SRT/context.txt or any other shared location — that past behavior caused cross-
    # session contamination (see CLAUDE.md "Context 生命週期").
    if not context_prompt:
        candidate = os.path.join(os.path.dirname(input_file), "context.txt")
        if os.path.exists(candidate):
            with open(candidate, "r", encoding="utf-8") as f:
                context_prompt = f.read().replace("\n", ", ").strip()
            print(f"[groq] Context auto-detected: {candidate}")

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
    key_index = 0
    failed_chunks = []
    with open(srt_output, "w", encoding="utf-8") as srt_file:
        for i, chunk_path in enumerate(chunks):
            print(f"[groq] Transcribing chunk {i+1}/{len(chunks)} "
                  f"(using key #{key_index % len(api_keys) + 1}/{len(api_keys)})...")
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
            os.remove(chunk_path)

    if failed_chunks:
        # 不要靜默產生有 10 分鐘空洞的 SRT。讓 session.py 失敗,讓使用者知道。
        print(f"[groq] FATAL: {len(failed_chunks)} chunk(s) failed: {failed_chunks}",
              file=sys.stderr)
        print(f"[groq] Partial SRT written to {srt_output} (with gaps);"
              f" pipeline aborted to avoid silent corruption.", file=sys.stderr)
        shutil.rmtree(temp_dir, ignore_errors=True)
        sys.exit(2)

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
