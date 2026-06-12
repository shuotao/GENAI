#!/usr/bin/env python3
"""
Gemini Transcribe Tool (Japanese version)
- Uses Gemini 1.5 Flash for audio transcription
- Outputs SRT format
"""

import os
import sys
import time
import json
from pathlib import Path
import google.generativeai as genai

def load_env(start: Path) -> None:
    cur = start.resolve()
    for _ in range(10):
        env_file = cur / ".env"
        if env_file.exists():
            for line in env_file.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip())
            return
        cur = cur.parent

HOST_ENGINE_SIGNALS = ("CLAUDECODE", "GEMINI_CLI", "GITHUB_COPILOT_CLI")


def guard_host_engine(force: bool) -> None:
    """CLAUDE.md 原則 5:CLI host 走 OAuth login token,不打 Gemini API key。
    偵測到 host 信號就拒絕(轉錄請改走 Groq:groq_transcribe_ja.py);--force-api 可硬闖。"""
    if force:
        return
    hits = [k for k in HOST_ENGINE_SIGNALS if os.environ.get(k)]
    if hits:
        print(f"ERROR: host engine signal {hits} detected — 原則 5:CLI host 不打 Gemini API。"
              f"日文轉錄主線是 groq_transcribe_ja.py(Groq 永遠用 API key,合規);"
              f"要硬用 Gemini 轉錄請加 --force-api。", file=sys.stderr)
        sys.exit(2)


def main():
    force = "--force-api" in sys.argv
    if force:
        sys.argv = [a for a in sys.argv if a != "--force-api"]
    guard_host_engine(force)

    if len(sys.argv) < 2:
        print("Usage: python3 gemini_transcribe_ja.py <audio_file> [output_dir] [context_file] [--force-api]")
        sys.exit(1)

    audio_path = Path(sys.argv[1])
    output_dir = Path(sys.argv[2]) if len(sys.argv) > 2 else audio_path.parent
    context_file = Path(sys.argv[3]) if len(sys.argv) > 3 else None

    load_env(Path.cwd())
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("ERROR: GEMINI_API_KEY not found")
        sys.exit(1)

    genai.configure(api_key=api_key)

    context_prompt = ""
    if context_file and context_file.exists():
        context_prompt = context_file.read_text(encoding="utf-8")
    
    print(f"Uploading {audio_path}...")
    audio_file = genai.upload_file(path=str(audio_path))
    
    while audio_file.state.name == "PROCESSING":
        print(".", end="", flush=True)
        time.sleep(5)
        audio_file = genai.get_file(audio_file.name)

    if audio_file.state.name == "FAILED":
        print("\nUpload failed")
        sys.exit(1)
    
    print("\nFile processed. Starting transcription...")

    model = genai.GenerativeModel("models/gemini-flash-latest")
    
    prompt = f"""
あなたはプロの字幕作成者です。提供された日本語の音声を、正確なSRTフォーマットで書き起こしてください。

## 規則
1. 翻訳はせず、オリジナルの日本語を保持してください。
2. タイムコードは正確に作成してください。
3. 句読点を適切に入れ、読みやすくしてください。
4. フィラー（えー、あのー等）は適宜除去してください。
5. 出力はSRTファイルの内容のみとし、説明文などは含めないでください。

## コンテキスト
{context_prompt}
"""

    response = model.generate_content([prompt, audio_file])
    
    srt_content = response.text
    # Remove markdown code blocks if present
    if srt_content.startswith("```"):
        srt_content = re.sub(r"```(srt)?\n", "", srt_content)
        srt_content = re.sub(r"\n```", "", srt_content)

    output_path = output_dir / f"{audio_path.stem}.srt"
    output_path.write_text(srt_content, encoding="utf-8")
    
    print(f"Transcription saved to {output_path}")
    
    # Cleanup file from Gemini API
    genai.delete_file(audio_file.name)

if __name__ == "__main__":
    import re
    main()
