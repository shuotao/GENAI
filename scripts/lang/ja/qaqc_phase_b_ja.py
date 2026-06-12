#!/usr/bin/env python3
"""
qaqc_phase_b_ja.py — Gemini-powered Phase B/Step 3/Step 4 runner (Japanese version)
"""

import os
import re
import sys
import json
import time
import argparse
import urllib.request
import urllib.error
import ssl
from pathlib import Path

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
DEFAULT_MODELS = ["gemini-flash-latest", "gemini-2.0-flash", "gemini-2.5-flash", "gemini-2.5-pro"]
MAX_OUTPUT_TOKENS = 65536

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

def call_gemini(prompt: str, api_key: str, model: str, temperature: float = 0.2) -> str:
    url = GEMINI_URL.format(model=model, key=api_key)
    body = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": temperature, "maxOutputTokens": MAX_OUTPUT_TOKENS},
    }).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
    
    # Create unverified context to bypass SSL issues
    ctx = ssl._create_unverified_context()
    with urllib.request.urlopen(req, timeout=600, context=ctx) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data["candidates"][0]["content"]["parts"][0]["text"]

def call_gemini_with_retry(prompt: str, api_key: str, preferred_model: str | None = None) -> str:
    models = [preferred_model] if preferred_model else []
    for m in DEFAULT_MODELS:
        if m not in models:
            models.append(m)
    last_err: Exception | None = None
    for model in models:
        for attempt in (1, 2):
            try:
                return call_gemini(prompt, api_key, model)
            except Exception as e:
                last_err = e
                time.sleep(5)
                continue
    raise last_err

STRUCTURED_PROMPT_JA = """あなたは逐字録の校正専門家です。以下は日本語の録音を書き起こし、タイムコードに従って分割されたN個のテキスト（JSON配列）です。
各セグメントに対して、内容を正確に反映し、誤字脱字を修正する最小限の校正を行ってください。

### 規則 (タイムコード保護 + 配列不変制約)

1. 句読点を適切に補ってください。
2. 明らかな誤字脱字、変換ミス（特に専門用語）を修正してください。
3. 第一人称、元の文構造を保持してください。**翻訳は絶対にしないでください。日本語のまま出力してください。**
4. 要約、省略、セグメントの結合や分割は厳禁です。入力がN個なら出力も必ずN個にしてください。
5. 出力はJSON配列（文字列の配列）のみとし、説明文や ```json ``` の囲みは含めないでください。

{context_block}

### 入力 (計 {n} セグメント)
{array_json}

### 出力 (JSON配列のみ)
"""

def run_structured(texts: list[str], context: str, api_key: str, model: str | None) -> list[str]:
    context_block = ""
    if context.strip():
        context_block = f"\n### コンテキスト (専門用語の修正リファレンス)\n{context.strip()}\n"
    prompt = STRUCTURED_PROMPT_JA.format(
        context_block=context_block,
        n=len(texts),
        array_json=json.dumps(texts, ensure_ascii=False),
    )
    raw = call_gemini_with_retry(prompt, api_key, preferred_model=model)
    body = raw.strip()
    if body.startswith("```"):
        body = body.split("```", 2)[1]
        if body.lstrip().startswith("json"):
            body = body.lstrip()[4:]
        body = body.rsplit("```", 1)[0]
        body = body.strip()
    try:
        polished = json.loads(body)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"structured: LLM did not return valid JSON: {e}")
    if not isinstance(polished, list) or len(polished) != len(texts):
        raise RuntimeError(f"structured: length mismatch or invalid format (in={len(texts)}, out={len(polished)})")
    return polished

HOST_ENGINE_SIGNALS = ("CLAUDECODE", "GEMINI_CLI", "GITHUB_COPILOT_CLI")


def guard_host_engine(force: bool) -> None:
    """CLAUDE.md 原則 5:CLI host 走 OAuth login token,不打 Gemini API key。
    偵測到 host 信號就拒絕,正確路徑是 marker file 由對話 agent 接手;--force-api 可硬闖。"""
    if force:
        return
    hits = [k for k in HOST_ENGINE_SIGNALS if os.environ.get(k)]
    if hits:
        print(f"ERROR: host engine signal {hits} detected — 原則 5:CLI host 不打 Gemini API。"
              f"要硬打請加 --force-api。", file=sys.stderr)
        sys.exit(2)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["structured"], default="structured")
    ap.add_argument("--context", help="Context string or file path")
    ap.add_argument("--model", help="Preferred Gemini model")
    ap.add_argument("--force-api", action="store_true",
                    help="CLI host 信號下仍強制打 API(原則 5 逃生口)")
    args = ap.parse_args()
    guard_host_engine(args.force_api)
    load_env(Path.cwd())
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        sys.exit(1)
    if args.mode == "structured":
        payload = json.loads(sys.stdin.read())
        texts = payload["texts"]
        ctx = payload.get("context", args.context or "")
        polished = run_structured(texts, ctx, api_key, args.model)
        print(json.dumps({"texts": polished}, ensure_ascii=False))

if __name__ == "__main__":
    main()
