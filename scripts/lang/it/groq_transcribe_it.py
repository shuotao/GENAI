#!/usr/bin/env python3
"""
Groq Whisper transcription for Italian audio.
Splits audio into chunks, transcribes via Groq API with language=it.
Rotates API keys on rate limit errors.
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

# Context prompt with key terms from the Florence Duomo tour
CONTEXT_PROMPT = (
    "Cattedrale di Santa Maria del Fiore, Brunelleschi, cupola, Vasari, Zuccari, "
    "Giotto, campanile, Arnolfo di Cambio, Donatello, Lorenzo Ghiberti, "
    "Paolo Uccello, John Hawkwood, Cosimo de' Medici, prospettiva, "
    "affresco, buon fresco, Giudizio Universale, battistero, "
    "Santa Reparata, Porta dei Cornacchini, Firenze, Toscana, "
    "Carrara, Prato, Maremma, opus sectile, gnomon, Toscanelli, "
    "Luca della Robbia, hora italica, navata, abside, tribune, "
    "herringbone, spina di pesce, lanterna, costoloni, "
    "Federico Zuccari, Vincenzo Borghini, intarsia"
)


def load_api_keys(start_dir):
    """Load all GROQ_API_KEY variants from .env"""
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
    # Deduplicate while preserving order
    seen = set()
    unique = []
    for k in keys:
        if k not in seen:
            seen.add(k)
            unique.append(k)
    return unique


def format_srt_time(seconds):
    total_seconds = int(seconds)
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


def transcribe_chunk(chunk_path, api_keys, key_index):
    """Try transcribing with key rotation on rate limit."""
    data = {
        "model": "whisper-large-v3",
        "prompt": CONTEXT_PROMPT,
        "response_format": "verbose_json",
        "language": "it",
        "temperature": "0.0"
    }

    attempts = 0
    max_attempts = len(api_keys) * 2  # Try each key up to 2 times

    while attempts < max_attempts:
        current_key = api_keys[key_index % len(api_keys)]
        with open(chunk_path, "rb") as f:
            files = {"file": (os.path.basename(chunk_path), f, "audio/mpeg")}
            response = requests.post(
                GROQ_URL,
                headers={"Authorization": f"Bearer {current_key}"},
                data=data,
                files=files
            )

        if response.status_code == 200:
            return response.json(), key_index

        if response.status_code == 429:
            attempts += 1
            key_index = (key_index + 1) % len(api_keys)
            wait = min(10 * attempts, 60)
            print(f"  [rate limited] Switching to key #{key_index + 1}, waiting {wait}s...", file=sys.stderr)
            time.sleep(wait)
            continue

        print(f"ERROR Groq API {response.status_code}: {response.text[:300]}", file=sys.stderr)
        return None, key_index

    print("ERROR: All API keys exhausted / rate limited.", file=sys.stderr)
    return None, key_index


def main():
    input_file = sys.argv[1] if len(sys.argv) > 1 else None
    if not input_file or not os.path.exists(input_file):
        print(f"Usage: python3 {sys.argv[0]} <media_file>")
        sys.exit(1)

    output_dir = os.path.dirname(os.path.abspath(input_file))
    api_keys = load_api_keys(output_dir)
    if not api_keys:
        print("ERROR: No GROQ_API_KEY found in .env", file=sys.stderr)
        sys.exit(1)
    print(f"[groq-it] Loaded {len(api_keys)} API key(s)")

    base_name = Path(input_file).stem
    temp_dir = os.path.join(output_dir, f"_temp_{base_name}")
    os.makedirs(temp_dir, exist_ok=True)
    srt_output = os.path.join(output_dir, f"{base_name}.srt")

    print(f"[groq-it] Input: {input_file}")
    print(f"[groq-it] Splitting into {CHUNK_DURATION}s chunks...")
    start_time = time.time()
    chunks = extract_and_split_audio(input_file, temp_dir)
    print(f"[groq-it] {len(chunks)} chunks created")

    global_idx = 1
    key_index = 0
    with open(srt_output, "w", encoding="utf-8") as srt_file:
        for i, chunk_path in enumerate(chunks):
            print(f"[groq-it] Transcribing chunk {i+1}/{len(chunks)}...")
            time_offset = i * CHUNK_DURATION
            result, key_index = transcribe_chunk(chunk_path, api_keys, key_index)
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
            elif result is None:
                print(f"  [FAILED] chunk {i+1} - will be missing from output", file=sys.stderr)
            os.remove(chunk_path)

    shutil.rmtree(temp_dir, ignore_errors=True)
    elapsed = time.time() - start_time
    print(f"[groq-it] SRT saved: {srt_output}")
    print(f"[groq-it] Total time: {elapsed:.1f}s")
    print(f"[groq-it] Total segments: {global_idx - 1}")


if __name__ == "__main__":
    main()
