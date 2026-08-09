#!/usr/bin/env python3
"""md_translate_zhtw.py — 將英文 cleaned.md 整檔翻譯為 zh-TW(Gemini Flash)。

用於「時間軸已丟棄」的 cleaned.md 翻譯捷徑(CLAUDE.md Gotcha #6 認可路徑):
零省略以段落 1:1 對齊驗證,不用字數帶。

- 以空行切段(標題行自成一段),每批 BATCH 段送 Gemini,要求回傳同長度 JSON 陣列。
- 每批強制 len(out)==len(in),不符即重試;絕不手動湊數。
- 進度落盤於 <output>.progress.json,可中斷續跑。
- 產品名/指令/UI 英文詞、縮寫保留英文。

引擎(--engine):
  antigravity(預設) — `antigravity -p` OAuth headless 通道(CLAUDE.md 2026-07-05
      引入,不經 API key,可被 Claude Code 指揮)。預設模型 gemini-3.6-flash-medium
      (antigravity models 實機清單確認 2026-08-01)。
  api — generativelanguage API key 通道(GEMINI_API_KEY from .env);受原則 5
      宿主引擎守衛,需 --force-api 明確授權。

領域先驗(--domain):
  本場的領域敘述 + 必須原字串保留的專名清單,可直接給字串或給 .txt 路徑。
  省略時用通用技術演講 prime(DEFAULT_DOMAIN)。
  歷史註記:2026-08-08 以前此 prime 寫死 Autodesk Revit MEP;
  要重現 mechanical-design-cert-prep 需明確帶 --domain(見 README 範例)。

Usage:
  python3 md_translate_zhtw.py IN.md -o OUT.md [--engine antigravity|api]
                               [--model NAME] [--batch 30] [--force-api]
                               [--domain "領域敘述+專名" | --domain path/to/domain.txt]
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
DEFAULT_MODELS = ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-2.5-pro"]
MAX_OUTPUT_TOKENS = 65536
HOST_ENGINE_SIGNALS = ("CLAUDECODE", "GEMINI_CLI", "GITHUB_COPILOT_CLI")


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


def guard_host_engine(force: bool) -> None:
    if force:
        return
    hits = [k for k in HOST_ENGINE_SIGNALS if os.environ.get(k)]
    if hits:
        print(f"ERROR: 偵測到宿主引擎環境 ({', '.join(hits)})。\n"
              f"  原則 5:此環境應由對話 agent 處理判斷步驟,不應重複消費 API。\n"
              f"  若你確定要在此環境用 API key(雙重消費),請加 --force-api。",
              file=sys.stderr)
        sys.exit(3)


def call_gemini(prompt: str, api_key: str, model: str,
                temperature: float = 0.2) -> str:
    url = GEMINI_URL.format(model=model, key=api_key)
    body = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": temperature,
                             "maxOutputTokens": MAX_OUTPUT_TOKENS,
                             "responseMimeType": "application/json"},
    }).encode("utf-8")
    req = urllib.request.Request(
        url, data=body, headers={"Content-Type": "application/json"}, method="POST",
    )
    with urllib.request.urlopen(req, timeout=600) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data["candidates"][0]["content"]["parts"][0]["text"]


def call_gemini_with_retry(prompt: str, api_key: str,
                           preferred_model: str | None = None) -> str:
    models = [preferred_model] if preferred_model else []
    for m in DEFAULT_MODELS:
        if m not in models:
            models.append(m)
    last_err: Exception | None = None
    for model in models:
        for attempt in (1, 2):
            try:
                print(f"[translate] trying {model} (attempt {attempt})...",
                      file=sys.stderr)
                return call_gemini(prompt, api_key, model)
            except urllib.error.HTTPError as e:
                body = e.read().decode("utf-8", errors="replace")[:200]
                last_err = RuntimeError(f"Gemini HTTP {e.code} [{model}]: {body}")
                transient = (e.code == 429) or (500 <= e.code < 600)
                if transient and attempt == 1:
                    wait = 60 if e.code == 503 else 30
                    print(f"[translate] HTTP {e.code} on {model}, sleeping {wait}s...",
                          file=sys.stderr)
                    time.sleep(wait)
                    continue
                if not transient:
                    break
            except Exception as e:  # timeout, connection reset...
                last_err = e
                if attempt == 1:
                    time.sleep(15)
                    continue
    raise RuntimeError(f"all models failed: {last_err}")


def split_blocks(text: str) -> list[str]:
    blocks = [b.strip() for b in re.split(r"\n\s*\n", text)]
    return [b for b in blocks if b]


def strip_fence(text: str) -> str:
    t = text.strip()
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z]*\n", "", t)
        t = re.sub(r"\n```$", "", t.rstrip())
    return t


DEFAULT_DOMAIN = "一般技術演講/教學。產品名、專案名、指令與縮寫一律保留英文原字串。"


def resolve_domain(value: str | None) -> str:
    """--domain 接受「字串」或「.txt 路徑」(比照 session.py 的 --context 語義)。"""
    if not value:
        return DEFAULT_DOMAIN
    p = Path(value)
    if p.exists() and p.is_file():
        return p.read_text(encoding="utf-8").strip()
    return value.strip()


PROMPT = """你是專業繁體中文(台灣)技術譯者。以下是逐段英文文本,
以 JSON 陣列給出,共 {n} 段。請逐段翻譯為繁體中文,回傳「同長度」的 JSON 字串陣列,
第 i 個元素是第 i 段的完整翻譯。

【本場領域與專名】
{domain}

規則:
1. 忠實完整翻譯,零省略、零增添;不可合併或拆分段落。
2. 段落若以 Markdown 標題開頭(#/##/###),保留相同的標題前綴。
3. 產品名、軟體 UI 名稱、指令、參數名、檔案格式、縮寫一律保留英文;
   上方【本場領域與專名】列出的專名,必須原字串輸出,不得音譯或意譯。
4. 使用台灣業界慣用語;標點使用全形。
5. 只輸出 JSON 陣列,不要任何其他文字。

輸入段落:
{payload}"""


def call_antigravity(prompt: str, model: str) -> str:
    r = subprocess.run(
        ["antigravity", "-p", prompt, "--model", model,
         "--dangerously-skip-permissions", "--print-timeout", "10m"],
        capture_output=True, text=True, timeout=660)
    if r.returncode != 0:
        raise RuntimeError(f"antigravity rc={r.returncode}: {r.stderr[:200]}")
    return r.stdout


def extract_json_array(raw: str) -> str:
    """antigravity text 輸出可能夾敘述文字;取第一個 '[' 到最後一個 ']'。"""
    t = strip_fence(raw)
    i, j = t.find("["), t.rfind("]")
    if i == -1 or j == -1 or j <= i:
        raise json.JSONDecodeError("no JSON array found", t[:80], 0)
    return t[i:j + 1]


def translate_batch(blocks: list[str], api_key: str, model: str,
                    engine: str, domain: str = DEFAULT_DOMAIN) -> list[str]:
    payload = json.dumps(blocks, ensure_ascii=False)
    prompt = PROMPT.format(n=len(blocks), payload=payload, domain=domain)
    for attempt in range(1, 4):
        if engine == "antigravity":
            try:
                raw = call_antigravity(prompt, model)
            except Exception as e:
                print(f"[translate] antigravity fail (attempt {attempt}): {e}",
                      file=sys.stderr)
                time.sleep(15)
                continue
        else:
            raw = call_gemini_with_retry(prompt, api_key, model)
        try:
            out = json.loads(extract_json_array(raw))
        except json.JSONDecodeError as e:
            print(f"[translate] batch JSON parse fail (attempt {attempt}): {e}",
                  file=sys.stderr)
            continue
        if isinstance(out, list) and len(out) == len(blocks) and \
                all(isinstance(x, str) and x.strip() for x in out):
            return [x.strip() for x in out]
        got = len(out) if isinstance(out, list) else type(out).__name__
        print(f"[translate] batch misalign: want {len(blocks)} got {got} "
              f"(attempt {attempt}); retrying", file=sys.stderr)
    raise RuntimeError(f"batch failed 3x (size {len(blocks)}) — 段落無法 1:1 對齊")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("input")
    ap.add_argument("-o", "--output", required=True)
    ap.add_argument("--engine", choices=["antigravity", "api"],
                    default="antigravity")
    ap.add_argument("--model", default=None,
                    help="預設: antigravity=gemini-3.6-flash-medium, api=gemini-2.5-flash")
    ap.add_argument("--batch", type=int, default=30)
    ap.add_argument("--domain", default=None,
                    help="本場領域先驗:領域敘述 + 必須保留原文的專名清單。"
                         "可給字串或 .txt 路徑;省略時用通用技術演講 prime。")
    ap.add_argument("--force-api", action="store_true",
                    help="(--engine api 時)明確授權,在宿主引擎環境下仍走 API")
    args = ap.parse_args()

    domain = resolve_domain(args.domain)
    print(f"[translate] domain prime ({len(domain)} chars): {domain[:80]}…",
          file=sys.stderr)

    if args.model is None:
        args.model = ("gemini-3.6-flash-medium" if args.engine == "antigravity"
                      else "gemini-2.5-flash")

    src = Path(args.input)
    out_path = Path(args.output)
    api_key = ""
    if args.engine == "api":
        guard_host_engine(args.force_api)
        load_env(src.parent)
        api_key = os.environ.get("GEMINI_API_KEY", "")
        if not api_key:
            print("ERROR: GEMINI_API_KEY not found in .env", file=sys.stderr)
            sys.exit(1)

    blocks = split_blocks(src.read_text(encoding="utf-8"))
    if not blocks:
        print("ERROR: input has no paragraphs", file=sys.stderr)
        sys.exit(1)

    progress_path = out_path.with_suffix(out_path.suffix + ".progress.json")
    done: dict[str, str] = {}
    if progress_path.exists():
        saved = json.loads(progress_path.read_text(encoding="utf-8"))
        if saved.get("n_blocks") == len(blocks):
            done = saved.get("done", {})
            print(f"[translate] resume: {len(done)}/{len(blocks)} blocks cached",
                  file=sys.stderr)

    for start in range(0, len(blocks), args.batch):
        idxs = list(range(start, min(start + args.batch, len(blocks))))
        pending = [i for i in idxs if str(i) not in done]
        if not pending:
            continue
        result = translate_batch([blocks[i] for i in pending], api_key,
                                 args.model, args.engine, domain)
        for i, zh in zip(pending, result):
            done[str(i)] = zh
        progress_path.write_text(
            json.dumps({"n_blocks": len(blocks), "done": done}, ensure_ascii=False),
            encoding="utf-8")
        print(f"[translate] {len(done)}/{len(blocks)} blocks", file=sys.stderr)

    assert len(done) == len(blocks), "internal: progress incomplete"
    out = "\n\n".join(done[str(i)] for i in range(len(blocks))) + "\n"
    out_path.write_text(out, encoding="utf-8")
    progress_path.unlink(missing_ok=True)
    print(f"OK  {len(blocks)} paragraphs  ->  {out_path}")


if __name__ == "__main__":
    main()
