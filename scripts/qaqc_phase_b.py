#!/usr/bin/env python3
"""
qaqc_phase_b.py — Gemini-powered Phase B/Step 3/Step 4 runner (CLI-side)

Four modes (pick one via --mode):

  --mode merged (default)   → Step 2 cleaned.md
    Input  : plain text file (or stdin) containing Phase-A cleaned transcript.
    Output : markdown to stdout (or --output file). Adds punctuation, connectives,
             paragraph merging, ## / ### headings. 95%-105% char-count check.

  --mode structured         → timecode-safe polish for --structured SRT flow
    Input  : JSON on stdin: {"texts": ["seg1", ...], "context": "..."}
    Output : JSON on stdout: {"texts": ["polished1", ...]}  (same length!)
    Used by SRT/qaqc_srt.py --structured. LLM never sees timecodes.

  --mode enhance            → Step 3 enhanced.md (專有名詞補充)
    Input  : cleaned.md (file or stdin).
    Output : markdown with 專業知識補充 blocks inserted after first mention of each term.
    Flags  : --keywords "a,b,c" to pin the term list;
             if omitted, LLM auto-detects terms. Original text is preserved verbatim.

  --mode notes              → Step 4 notes_<立場>.md (立場置入好學生筆記)
    Input  : cleaned.md or enhanced.md (file or stdin).
    Output : markdown with 📝 summary → original text with 🎯 立場視角 blocks → 💡 核心洞察.
    Flags  : --identity "立場" (required, e.g. 建築師 / 國小老師 / 軟體工程師).

All prompts pull their core rules from `prompts/qaqc_core_rules.md` (SSoT).
Reads GEMINI_API_KEY from .env walking up from CWD.

Usage:
    python3 scripts/qaqc_phase_b.py cleaned.txt -o cleaned.md
    python3 scripts/qaqc_phase_b.py --mode structured < payload.json > result.json
    python3 scripts/qaqc_phase_b.py --mode enhance cleaned.md -o enhanced.md \\
        --keywords "RIE,非暴力溝通,依附關係"
    python3 scripts/qaqc_phase_b.py --mode notes enhanced.md -o notes_建築師.md \\
        --identity 建築師
"""

import os
import re
import sys
import json
import time
import argparse
import urllib.request
import urllib.error
from pathlib import Path

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
DEFAULT_MODELS = ["gemini-2.5-flash", "gemini-2.5-pro"]
MAX_OUTPUT_TOKENS = 65536

# SSoT for rules: see prompts/qaqc_core_rules.md
RULES_PATH = Path(__file__).resolve().parent.parent / "prompts" / "qaqc_core_rules.md"


def load_rules() -> str:
    if RULES_PATH.exists():
        return RULES_PATH.read_text(encoding="utf-8")
    return ""  # Fallback: prompts still have their inline minimum rules


def rules_section(marker_start: str, marker_end: str | None = None) -> str:
    """Extract a section of qaqc_core_rules.md between two H2 markers (or to EOF)."""
    rules = load_rules()
    if not rules or marker_start not in rules:
        return ""
    start = rules.index(marker_start)
    if marker_end and marker_end in rules[start:]:
        end = start + rules[start:].index(marker_end)
    else:
        end = len(rules)
    return rules[start:end].strip()


# ─── env ───

def load_env(start: Path) -> None:
    """Walk up from `start`, load first .env we find, populate os.environ."""
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


# ─── Gemini call ───

def call_gemini(prompt: str, api_key: str, model: str,
                temperature: float = 0.2) -> str:
    url = GEMINI_URL.format(model=model, key=api_key)
    body = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": temperature,
                             "maxOutputTokens": MAX_OUTPUT_TOKENS},
    }).encode("utf-8")
    req = urllib.request.Request(
        url, data=body, headers={"Content-Type": "application/json"}, method="POST",
    )
    with urllib.request.urlopen(req, timeout=180) as resp:
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
                print(f"[phase_b] trying {model} (attempt {attempt})...", file=sys.stderr)
                return call_gemini(prompt, api_key, model)
            except urllib.error.HTTPError as e:
                body = e.read().decode("utf-8", errors="replace")[:200]
                last_err = RuntimeError(f"Gemini HTTP {e.code} [{model}]: {body}")
                if e.code == 429 and attempt == 1:
                    print("[phase_b] rate-limited, sleeping 20s...", file=sys.stderr)
                    time.sleep(20)
                    continue
                if e.code == 429:
                    break  # move to next model
                raise last_err
            except Exception as e:  # noqa: BLE001
                last_err = e
                raise
    raise RuntimeError(f"All Gemini models failed. Last error: {last_err}")


# ─── merged mode (paragraphed markdown) ───

MERGED_PROMPT = """你是一位逐字稿校稿專家。請對以下語音轉錄的原始文字進行校稿。

## 規則(來自 prompts/qaqc_core_rules.md § R2)

{r2_rules}
{context_block}
## 原始逐字稿({n_chars} 字)

{text}
"""


def run_merged(in_text: str, context: str, api_key: str, model: str | None) -> tuple[str, dict]:
    context_block = ""
    if context.strip():
        context_block = f"\n## 領域背景(供專名校正參考,不寫入輸出)\n{context.strip()}\n"
    r2 = rules_section("## R2. Phase B 校稿核心鐵律", "## R3.")
    prompt = MERGED_PROMPT.format(
        r2_rules=r2 or "(SSoT 規則庫不可用,使用內嵌最小規則:補標點、接續詞、合併段落、嚴禁摘要、95%-105% 字數)",
        context_block=context_block, n_chars=len(in_text), text=in_text)
    out = call_gemini_with_retry(prompt, api_key, preferred_model=model)
    ratio = len(out) / max(1, len(in_text))
    stats = {"in_chars": len(in_text), "out_chars": len(out), "ratio": round(ratio, 4)}
    return out, stats


# ─── enhance mode (Step 3: 專有名詞補充) ───

ENHANCE_PROMPT = """你是一位專業知識補充專家。請閱讀以下逐字稿,在文中適當位置插入專業知識補充區塊。

## 補充目標
{keyword_instruction}

## 規則(來自 prompts/qaqc_core_rules.md § R4)

{r4_rules}

## 嚴格要求(不可違反)

1. **完整保留原文**:不得修改、刪除、改寫、摘要任何一句原文。輸出必須包含原文每一個字。
2. 補充必須插入在「首次提及該術語的段落之後」,嚴禁統一放在文末
3. 每個術語只在首次出現時補充一次
4. 補充區塊上下各保留一個空行
{context_block}
## 原始逐字稿({n_chars} 字)

{text}
"""


def run_enhance(in_text: str, keywords: list[str], context: str,
                api_key: str, model: str | None) -> tuple[str, dict]:
    if keywords:
        kw_inst = ("請**只針對以下指定的關鍵字**進行補充(不要自行增加其他術語):\n"
                   + "\n".join(f"- {k}" for k in keywords))
    else:
        kw_inst = "請自動找出文中的專業術語和關鍵概念進行補充。"

    context_block = ""
    if context.strip():
        context_block = f"\n## 領域背景(供術語判讀參考)\n{context.strip()}\n"

    r4 = rules_section("## R4. 專有名詞補充", "## R5.")
    prompt = ENHANCE_PROMPT.format(
        keyword_instruction=kw_inst,
        r4_rules=r4 or "(SSoT 規則庫不可用,使用內嵌最小規則)",
        context_block=context_block,
        n_chars=len(in_text),
        text=in_text,
    )
    out = call_gemini_with_retry(prompt, api_key, preferred_model=model)
    ratio = len(out) / max(1, len(in_text))
    stats = {"mode": "enhance", "keywords": keywords,
             "in_chars": len(in_text), "out_chars": len(out),
             "ratio": round(ratio, 4)}
    return out, stats


# ─── notes mode (Step 4: 立場置入好學生筆記) ───

NOTES_PROMPT = """你是一個「好學生筆記」生成系統。請根據以下逐字稿內容,以「{identity}」的立場,生成立場置入的學習筆記。

## 規則(來自 prompts/qaqc_core_rules.md § R3)

{r3_rules}

## 嚴格要求(不可違反)

1. **完整保留原文內容**:每一段原文都必須出現在輸出中,不得省略
2. 字數檢查:輸出(不含新增的框)相對原文應在 95%-105% 區間
3. 類比必須在邏輯上合理且有意義,不可牽強附會
4. 類比區塊上下各保留一個空行

## 你的立場
{identity}

## 必須出現的結構(依順序)

1. 開頭:`> 📝 **學習摘要**` 框
2. 原文內容(逐段出現),在合適位置插入 `> 🎯 **{identity}視角**` 類比區塊
3. 結尾:`> 💡 **核心洞察**` 框
{context_block}
## 逐字稿內容({n_chars} 字)

{text}
"""


def run_notes(in_text: str, identity: str, context: str,
              api_key: str, model: str | None) -> tuple[str, dict]:
    context_block = ""
    if context.strip():
        context_block = f"\n## 領域背景\n{context.strip()}\n"

    r3 = rules_section("## R3. 好學生筆記生成規則", "## R4.")
    prompt = NOTES_PROMPT.format(
        identity=identity,
        r3_rules=r3 or "(SSoT 規則庫不可用,使用內嵌最小規則)",
        context_block=context_block,
        n_chars=len(in_text),
        text=in_text,
    )
    out = call_gemini_with_retry(prompt, api_key, preferred_model=model)
    ratio = len(out) / max(1, len(in_text))
    stats = {"mode": "notes", "identity": identity,
             "in_chars": len(in_text), "out_chars": len(out),
             "ratio": round(ratio, 4)}
    return out, stats


# ─── structured mode (text array in/out) ───

STRUCTURED_PROMPT = """你是逐字稿校稿專家。以下是一支繁體中文錄音轉錄後、依時間軸切分的 N 段文字(JSON 陣列)。
請對**每一段**做最小幅度校稿,輸出完全相同數量的 N 段。

### 規則(時間軸保護 + 陣列不變約束,對應 prompts/qaqc_core_rules.md § R5)

這些規則特定於「結構保留型校稿」,與 R2 合併段落場景不同 — 不可合併相鄰段、
不可拆分、輸入 N 段就回傳 N 段。

1. 補上標點符號。
2. 修正明顯錯字。
3. 保留第一人稱、原句結構 — 嚴禁合併相鄰段、嚴禁拆分、嚴禁摘要。
4. 嚴禁新增或刪除段。輸入 N 段就回傳 N 段。
5. 只輸出一個 JSON 陣列(字串陣列),不要加任何說明文字、不要加 ```json``` 圍欄。
{context_block}
### 輸入(共 {n} 段)
{array_json}

### 輸出(只要 JSON 陣列)
"""


def run_structured(texts: list[str], context: str,
                   api_key: str, model: str | None) -> list[str]:
    context_block = ""
    if context.strip():
        context_block = f"\n### 領域背景(供專名校正參考)\n{context.strip()}\n"
    prompt = STRUCTURED_PROMPT.format(
        context_block=context_block,
        n=len(texts),
        array_json=json.dumps(texts, ensure_ascii=False),
    )
    raw = call_gemini_with_retry(prompt, api_key, preferred_model=model)

    # Strip possible ```json fences
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
        raise RuntimeError(f"structured: LLM did not return valid JSON: {e}\nFirst 300 chars: {body[:300]}")

    if not isinstance(polished, list) or not all(isinstance(x, str) for x in polished):
        raise RuntimeError("structured: LLM output is not a list of strings")

    if len(polished) != len(texts):
        raise RuntimeError(
            f"structured: length mismatch (in={len(texts)}, out={len(polished)}) — "
            "rejecting to preserve timeline integrity"
        )

    return polished


# ─── main ───

def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input", nargs="?", help="Input file. Omit for stdin.")
    ap.add_argument("-o", "--output", help="Output file. Stdout if omitted.")
    ap.add_argument("--mode", choices=["merged", "structured", "enhance", "notes"],
                    default="merged",
                    help="merged=Step2, structured=timecode-safe polish, "
                         "enhance=Step3 術語補充, notes=Step4 立場置入好學生筆記")
    ap.add_argument("--context", help="Context string or file path")
    ap.add_argument("--keywords", help="Comma/newline separated term list (enhance mode). "
                                        "Omit to let LLM auto-detect.")
    ap.add_argument("--identity", help="Required for --mode notes. 立場(e.g. 建築師)")
    ap.add_argument("--model", help="Preferred Gemini model, e.g. gemini-2.5-flash")
    args = ap.parse_args()

    load_env(Path.cwd())
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        print("ERROR: GEMINI_API_KEY not found in .env", file=sys.stderr)
        sys.exit(1)

    # Resolve context
    context = ""
    if args.context:
        p = Path(args.context)
        context = p.read_text(encoding="utf-8") if p.exists() else args.context

    if args.mode == "structured":
        payload = json.loads(sys.stdin.read())
        texts = payload["texts"]
        ctx = payload.get("context", context)
        polished = run_structured(texts, ctx, api_key, args.model)
        print(json.dumps({"texts": polished}, ensure_ascii=False))
        return

    # Read input text for the remaining modes
    if args.input:
        in_text = Path(args.input).read_text(encoding="utf-8")
    else:
        in_text = sys.stdin.read()

    if args.mode == "merged":
        out, stats = run_merged(in_text, context, api_key, args.model)
    elif args.mode == "enhance":
        kws = []
        if args.keywords:
            kws = [k.strip() for k in re.split(r"[,,\n]+", args.keywords) if k.strip()]
        out, stats = run_enhance(in_text, kws, context, api_key, args.model)
    elif args.mode == "notes":
        if not args.identity:
            print("ERROR: --mode notes requires --identity", file=sys.stderr)
            sys.exit(1)
        out, stats = run_notes(in_text, args.identity, context, api_key, args.model)
    else:
        print(f"Unknown mode: {args.mode}", file=sys.stderr)
        sys.exit(1)

    print(f"[phase_b] {args.mode} stats: {stats}", file=sys.stderr)
    if stats.get("ratio") and stats["ratio"] < 0.85:
        print(f"[phase_b] WARNING: output ratio {stats['ratio']} < 0.85, likely omissions",
              file=sys.stderr)

    if args.output:
        Path(args.output).write_text(out, encoding="utf-8")
        print(f"[phase_b] wrote {args.output} ({len(out)} chars)", file=sys.stderr)
    else:
        sys.stdout.write(out)


if __name__ == "__main__":
    main()
