#!/usr/bin/env python3
"""
Groq Whisper 逐字稿工具 (CLI 版)
- 從 .env 讀取 GROQ_API_KEY
- FFmpeg 切片 → Groq Whisper API → SRT 輸出
- 支援 context.txt 背景詞庫

Usage:
    python3 groq_transcribe.py <media_file> [output_dir] [context_file]

環境變數:
    GROQ_PROMPT_MODE=plain     (預設)主轉錄**不送 prompt**;覆蓋率可疑的段落再帶 prompt 轉一次當
                               「診斷對照」,對照版多出來的區間寫進 review_ranges,**不自動換版**
                               (prompt 版在靜音處可能是 prompt-echo 幻覺,交 Phase B agent 判斷)。
    GROQ_PROMPT_MODE=prompted  舊行為:主轉錄帶 prompt;可疑時無 prompt 重轉,區間差集明顯較好才換版。
    GROQ_PROMPT_MODE=off       只轉一次、不送 prompt、不做對照(= 舊的 GROQ_NO_PROMPT=1,仍相容)。
    GROQ_COVERAGE_FALLBACK=0   關閉第二次轉錄(可疑段只記 unresolved)。
    GROQ_CHUNK_SECONDS=300     覆寫切段長度(預設 600)。

為什麼預設不送 prompt(2026-11-08,見 docs/gotchas.md #8):
    帶 prompt 的 Whisper 會**靜默跳過整段語音**(SRT 出現 20 秒級空白、無錯誤)。同一 16.5 分鐘音檔:
    context prompt 2,279 中文字、只送一句 base prompt 2,657 字、不送 prompt 3,545 字;切段長度無關。
    漏掉的語音校稿救不回來;專名錯誤 Phase B 可以校(核心鐵律 F1)。不送 prompt 的副作用是
    片段性簡體漂移,由 session.py 在 Phase A 後自動跑 s2t_normalize.py。

覆蓋率閘門:每段量「有語音的時間區間」(相鄰句間隔 ≤6s 視為連續);段內空白 ≥12s、空白總長 >10%、
    時長未知、無文字、時間戳不合法、或單句 ≥30s 但 <0.5 字/秒 → 可疑。只能找疑點,不能證明零省略。
    每段決策寫入 <stem>.transcribe_report.json(session.py 併入 metadata.json)。
"""

import hashlib
import json
import math
import os
import re
import sys
import subprocess
import requests
import shutil
import time
from datetime import timedelta
from pathlib import Path

CHUNK_DURATION = int(os.environ.get("GROQ_CHUNK_SECONDS") or 600)  # seconds per chunk
_FALSY = ("", "0", "false", "False")
NO_PROMPT = os.environ.get("GROQ_NO_PROMPT", "") not in _FALSY          # 舊旗標 = mode off
_MODE = (os.environ.get("GROQ_PROMPT_MODE") or "plain").strip().lower()
PROMPT_MODE = "off" if NO_PROMPT else (_MODE if _MODE in ("plain", "prompted", "off") else "plain")
COVERAGE_FALLBACK = os.environ.get("GROQ_COVERAGE_FALLBACK", "1") not in _FALSY
MODEL = "whisper-large-v3"
LANGUAGE = "zh"
GATE_VERSION = 2

# 覆蓋率閘門門檻(web/studio.js COVERAGE_* 同值,改一邊要改另一邊;test_groq_coverage 對照)
GAP_SEC = 6.0              # 相鄰句間隔 ≤ 此值視為連續語音
SUSPECT_GAP_SEC = 12.0     # 段內(非段首)空白 ≥ 此值 → 可疑
SUSPECT_GAP_RATIO = 0.10   # 空白總長 > 段長 10% → 可疑
SPARSE_SEG_SEC = 30.0      # 單句 ≥ 30s
SPARSE_DENSITY = 0.5       #   且 < 0.5 字/秒 → 可疑(吐一句然後整段沉默)
SWITCH_GAIN_SEC = 5.0      # prompted 模式:無 prompt 版多覆蓋 ≥ 5s
SWITCH_MAX_LOSS_SEC = 1.0  #   且少覆蓋 ≤ 1s 才換版
REVIEW_MIN_SEC = 1.0       # 非選中版獨有的區間 > 1s → 列入 review_ranges
# 空白字元集合(與 JS 完全相同,不用 \s 以免兩端定義不同)
_WS_RE = re.compile("[ \t\n\r\f\v\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff]+")
LAST_ERROR = {"msg": None}
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


def truncate_prompt(prompt: str, max_bytes: int = 896) -> str:
    """Groq Whisper prompt 上限 896 —— **以 UTF-8 bytes 計**(2026-11-08 實測)。

    實測(同一把 key、3 秒音檔):'a'*900 → 報 900;'中'*300 → 報 900;'中'*900 → 報 2700;
    473 字元的中英混合 prompt → 報 989(= 其 UTF-8 byte 數)。故中文約 298 字即滿。
    歷史:2026-05 曾實測為「字元」並改成按字元裁(見 docs/gotchas.md #1),Groq 之後改了口徑;
    按 bytes 裁在兩種口徑下都不會 400(bytes ≥ 字元),所以永遠按 bytes 裁。
    在字元邊界截斷,不切壞多位元組字。"""
    data = prompt.encode("utf-8")
    if len(data) <= max_bytes:
        return prompt
    return data[:max_bytes].decode("utf-8", errors="ignore")


def _finite(x):
    """有限數值;接受 int/float 與非空白的數字字串,拒絕 bool/None/空白/NaN/Infinity(JS covFinite 同規則)。"""
    if isinstance(x, bool) or x is None:
        return None
    if isinstance(x, str):
        if not x.strip():
            return None
    elif not isinstance(x, (int, float)):
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def seg_times(sg, dur):
    """單句時間戳驗證(覆蓋率與輸出共用):合法 → (start, end),end 裁到段長;不合法 → None。"""
    a, e = _finite(sg.get("start")), _finite(sg.get("end"))
    if a is None or e is None or a < 0 or e <= a or (dur is not None and a >= dur):
        return None
    if dur is not None:
        e = min(e, dur)
    return a, e


def _json_safe(x):
    """原始時間值寫進報告用(JS covRaw 同規則):None/bool/str/有限數值原樣;非有限數值 → "NaN"/"Infinity"。"""
    if x is None or isinstance(x, (bool, str)):
        return x
    if isinstance(x, (int, float)):
        if math.isfinite(x):
            return x
        return "NaN" if math.isnan(x) else ("Infinity" if x > 0 else "-Infinity")
    return repr(x)


def valid_duration(*candidates):
    """第一個有限正數;都沒有 → None(未知長度不可當 0 或當完整覆蓋)。"""
    for c in candidates:
        v = _finite(c)
        if v is not None and v > 0:
            return v
    return None


def text_len(t):
    """非空白字元數,以 code point 計(JS 端用 Array.from 同口徑)。"""
    return len(_WS_RE.sub("", t or ""))


def _total(iv):
    return sum(e - a for a, e in iv)


def interval_diff(A, B):
    """A − B;兩者皆為已排序、不重疊的 [a, e] 清單。"""
    out = []
    for a, e in A:
        cur = a
        for b, f in B:
            if f <= cur or b >= e:
                continue
            if b > cur:
                out.append([cur, b])
            cur = max(cur, f)
            if cur >= e:
                break
        if cur < e:
            out.append([cur, e])
    return out


def chunk_coverage(segments, duration):
    """量一段轉錄的覆蓋率。duration 為已知段長(None = 未知)。比較皆用原值,不四捨五入。"""
    dur = valid_duration(duration)
    spans, invalid, chars, sparse, invalid_details = [], 0, 0, [], []
    for idx, sg in enumerate(segments or []):
        n = text_len(sg.get("text"))
        if n == 0:
            continue
        t = seg_times(sg, dur)
        if t is None:
            invalid += 1
            invalid_details.append({"index": idx, "start": _json_safe(sg.get("start")),
                                    "end": _json_safe(sg.get("end")), "text": (sg.get("text") or "").strip()})
            continue
        a, e = t
        chars += n
        spans.append((a, e))
        if e - a >= SPARSE_SEG_SEC and n / (e - a) < SPARSE_DENSITY:
            sparse.append([a, e])
    spans.sort()
    iv = []
    for a, e in spans:
        if iv and a - iv[-1][1] <= GAP_SEC:
            iv[-1][1] = max(iv[-1][1], e)
        else:
            iv.append([a, e])
    if iv and iv[0][0] <= GAP_SEC:
        iv[0][0] = 0.0
    if iv and dur is not None and dur - iv[-1][1] <= GAP_SEC:
        iv[-1][1] = dur
    gaps, cursor = [], 0.0
    for i, (a, e) in enumerate(iv):
        if a > cursor:
            gaps.append([cursor, a, "lead" if i == 0 else "interior"])
        cursor = e
    if dur is not None and dur > cursor:
        gaps.append([cursor, dur, "tail"])
    gap_total = sum(g[1] - g[0] for g in gaps)
    interior = [g[1] - g[0] for g in gaps if g[2] == "interior"]
    max_interior = max(interior) if interior else 0.0
    reasons = []
    if dur is None:
        reasons.append("duration_unknown")
    if chars == 0:
        reasons.append("no_text")
    if invalid:
        reasons.append("invalid_timestamps")
    if max_interior >= SUSPECT_GAP_SEC:
        reasons.append("interior_gap")
    if dur is not None and gap_total > SUSPECT_GAP_RATIO * dur:
        reasons.append("gap_ratio")
    if sparse:
        reasons.append("sparse_segment")
    return {"duration": dur, "segments": len(spans), "invalid_segments": invalid, "text_chars": chars,
            "intervals": iv, "gaps": gaps, "gap_total": gap_total, "max_interior_gap": max_interior,
            "covered": _total(iv), "sparse_segments": sparse, "invalid_details": invalid_details,
            "reasons": reasons}


def coverage_suspicious(cov):
    return bool(cov["reasons"])


def pick_better(cov_primary, cov_second):
    """prompted 模式用:回傳 'second'(換成無 prompt 版)或 'primary'。
    只看時間區間差集 —— 字數多不代表內容多(可能是幻覺灌字)。"""
    if "no_text" in cov_second["reasons"] or "duration_unknown" in cov_second["reasons"]:
        return "primary"
    gain = _total(interval_diff(cov_second["intervals"], cov_primary["intervals"]))
    loss = _total(interval_diff(cov_primary["intervals"], cov_second["intervals"]))
    return "second" if gain >= SWITCH_GAIN_SEC and loss <= SWITCH_MAX_LOSS_SEC else "primary"


def review_ranges(cov_selected, cov_other, other_segments, offset, other_mode):
    """非選中版有語音、選中版沒有的區間(>1s),附該區間內非選中版的原文供 agent 判斷。"""
    out = []
    for a, e in interval_diff(cov_other["intervals"], cov_selected["intervals"]):
        if e - a <= REVIEW_MIN_SEC:
            continue
        texts = [(sg.get("text") or "").strip() for sg in other_segments or []
                 if (_finite(sg.get("end")) or 0) > a and (_finite(sg.get("start")) or 0) < e
                 and text_len(sg.get("text"))]
        out.append({"start": round(a + offset, 2), "end": round(e + offset, 2), "source": other_mode,
                    "text": "".join(texts)})
    return out


def build_prompt(context_prompt):
    base_prompt = "這是一段關於技術開發與會議簡報內容的繁體中文錄音。"
    raw = f"{base_prompt} 內容包含：{context_prompt}。" if context_prompt else base_prompt
    return truncate_prompt(raw, max_bytes=896)


def media_duration(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
                       capture_output=True, text=True)
    return _finite(r.stdout.strip())


def _file_sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def cache_key(chunk_path, context_prompt):
    """快取只在「同音訊、同請求設定、同閘門版本」時有效。"""
    parts = [str(GATE_VERSION), _file_sha256(chunk_path), MODEL, LANGUAGE, PROMPT_MODE, str(CHUNK_DURATION),
             hashlib.sha256(build_prompt(context_prompt).encode("utf-8")).hexdigest()]
    return hashlib.sha256("|".join(parts).encode()).hexdigest()


def decide(primary_mode, primary, second, second_mode, duration, offset, second_status, second_error=None):
    """確定性決策:由原始 API 結果算覆蓋率、選版、review_ranges、unresolved。可由快取重算。"""
    pcov = chunk_coverage(primary.get("segments"), duration)
    entry = {"offset": offset, "duration": duration, "primary_mode": primary_mode, "selected": primary_mode,
             "second_mode": second_mode, "second_status": second_status, "second_error": second_error,
             "primary": _cov_summary(pcov), "second": None, "review_ranges": [], "unresolved_reasons": []}
    selected, scov_sel = primary, pcov
    if second is not None:
        scov = chunk_coverage(second.get("segments"), duration)
        entry["second"] = _cov_summary(scov)
        if primary_mode == "prompted" and pick_better(pcov, scov) == "second":
            selected, scov_sel = second, scov
            entry["selected"] = second_mode
        other, ocov, omode = ((second, scov, second_mode) if selected is primary
                              else (primary, pcov, primary_mode))
        entry["review_ranges"] = review_ranges(scov_sel, ocov, other.get("segments"), offset, omode)
    reasons = list(scov_sel["reasons"])
    if second_status in ("failed", "disabled"):
        reasons.append(f"second_read_{second_status}")
    if entry["review_ranges"]:
        reasons.append("other_version_has_extra_ranges")
    entry["gaps"] = [[round(a + offset, 2), round(e + offset, 2), k] for a, e, k in scov_sel["gaps"]]
    # 時間戳調整(不合法/倒退/裁切/補長):文字照樣輸出,原始值與寫出值留在報告供核對
    entry["invalid_segments"] = scov_sel["invalid_details"]
    _, adjustments = repair_times(selected.get("segments"), duration)
    entry["timestamp_adjustments"] = adjustments
    if timing_unresolved(adjustments):
        reasons.append("timestamps_adjusted")
    entry["unresolved_reasons"] = reasons
    return selected, entry


def _cov_summary(c):
    return {k: (round(v, 2) if isinstance(v, float) else v) for k, v in c.items()
            if k not in ("intervals", "gaps", "invalid_details")}


def process_chunk(chunk_path, api_keys, key_index, context_prompt, offset, transcribe=None):
    """轉一段(含快取、閘門、第二次轉錄)。回傳 (selected_result | None, key_index, entry | None)。
    transcribe 參數供測試注入假 API。"""
    transcribe = transcribe or transcribe_chunk
    duration = valid_duration(media_duration(chunk_path))
    key = cache_key(chunk_path, context_prompt)
    cache_path = os.path.splitext(chunk_path)[0] + ".json"
    primary_mode = "prompted" if PROMPT_MODE == "prompted" else "plain"
    second_mode = "plain" if primary_mode == "prompted" else "prompted"

    cached = None
    if os.path.exists(cache_path):
        try:
            with open(cache_path, encoding="utf-8") as cf:
                cached = json.load(cf)
        except (OSError, ValueError):
            cached = None
        if not (isinstance(cached, dict) and cached.get("cache_key") == key and cached.get("primary")):
            print("  [resume] cache stale/unverifiable → re-transcribe")
            cached = None

    if cached:
        primary = cached["primary"]
        print("  [resume] primary reused from cache")
    else:
        primary, key_index = transcribe(chunk_path, api_keys, key_index, context_prompt,
                                        use_prompt=(primary_mode == "prompted"))
        if not primary:
            return None, key_index, None
    duration = valid_duration(duration, primary.get("duration"))

    second, second_status, second_error = None, "not_needed", None
    second_allowed = PROMPT_MODE != "off" and COVERAGE_FALLBACK
    # 快取事實(之前轉過的第二版)與本次有效狀態分開:關閉對照時本次不用它,但保留在快取,重新開啟可重用
    cached_second = cached.get("second") if cached and cached.get("second_status") == "done" else None
    if second_allowed and cached_second is not None:
        second, second_status = cached_second, "done"
    pcov = chunk_coverage(primary.get("segments"), duration)
    if second is None and coverage_suspicious(pcov):
        if not second_allowed:
            second_status = "disabled"
        else:
            print(f"  [coverage] suspicious {pcov['reasons']} (gaps {pcov['gap_total']:.0f}s) "
                  f"→ second read ({second_mode})")
            LAST_ERROR["msg"] = None
            second, key_index = transcribe(chunk_path, api_keys, key_index, context_prompt,
                                           use_prompt=(second_mode == "prompted"))
            if second:
                second_status = "done"
            else:
                second_status, second_error = "failed", LAST_ERROR["msg"] or "unknown error"
                print(f"  [coverage] second read failed: {second_error}", file=sys.stderr)

    selected, entry = decide(primary_mode, primary, second, second_mode, duration, offset,
                             second_status, second_error)
    with open(cache_path, "w", encoding="utf-8") as cf:
        keep = second if second is not None else cached_second
        json.dump({"cache_key": key, "gate_version": GATE_VERSION, "primary": primary,
                   "second": keep, "second_status": "done" if keep is not None else second_status},
                  cf, ensure_ascii=False)
    if second is not None:
        print(f"  [coverage] {primary_mode} {entry['primary']['covered']:.0f}s vs {second_mode} "
              f"{entry['second']['covered']:.0f}s → selected {entry['selected']}"
              + (f"; {len(entry['review_ranges'])} review range(s)" if entry["review_ranges"] else ""))
    return selected, key_index, entry


def format_srt_time(seconds):
    """先四捨五入到整數毫秒再格式化(舊版用浮點截斷,1.001 可能寫成 1,000)。"""
    total_ms = max(0, _ms(seconds))
    h, rem = divmod(total_ms, 3_600_000)
    m, rem = divmod(rem, 60_000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

def _has_audio(path):
    """True when ffprobe reports a duration of at least 0.05 s (empty tail segments report none)."""
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
                       capture_output=True, text=True)
    try:
        return float(r.stdout.strip()) >= 0.05
    except ValueError:
        return False


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
        if f.startswith(f"{base_name}_chunk_") and f.endswith(".mp3")   # .json = cached results (resume)
        # A recording whose length is ~ a multiple of CHUNK_DURATION leaves an empty last segment (header only);
        # Groq rejects it (400 audio_too_short) and the whole run used to fail. Skip segments with no audio.
        and _has_audio(os.path.join(temp_dir, f))
    ])
    return chunks


def transcribe_chunk(chunk_path, api_keys, key_index, context_prompt, use_prompt=None):
    """以多 key 輪替 + 重試轉錄。
    - 200: 成功
    - 429 (rate limit): 切下一把 key,線性退避
    - 5xx (server error): 同 key 指數退避重試;耗盡後輪替 key 再試
    - 401 (invalid key): 跳過這把 key 輪下一把;全部 key 都 401 才放棄
    - 其他 4xx: 視為致命,直接放棄
    回傳 (result_dict_or_None, updated_key_index)。
    """
    data = {
        "model": MODEL,
        "response_format": "verbose_json",
        "language": LANGUAGE,
        "temperature": "0.0"
    }
    if use_prompt is None:
        use_prompt = PROMPT_MODE == "prompted"
    if use_prompt:
        data["prompt"] = build_prompt(context_prompt)

    rate_limit_attempts = 0
    server_error_attempts_on_current_key = 0
    keys_tried_on_5xx = 0
    keys_tried_on_401 = 0
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
                LAST_ERROR["msg"] = f"HTTP {status}" if status != -1 else "network error"
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
                LAST_ERROR["msg"] = f"HTTP {status}" if status != -1 else "network error"
                return None, key_index
            key_index = (key_index + 1) % len(api_keys)
            server_error_attempts_on_current_key = 0
            print(f"  [server error] Rotating to key #{key_index + 1}/{len(api_keys)} "
                  f"(tried {keys_tried_on_5xx}/{max_5xx_keys} keys on 5xx)", file=sys.stderr)
            time.sleep(3)
            continue

        # 401 認證失敗:這把 key 死了,但其他 key 可能有效 → 跳過、輪下一把
        # (多 key 場景下,單把失效 key 不該中止整個 chunk;全部試完才放棄)
        if status == 401:
            keys_tried_on_401 += 1
            body = response.text[:200] if response is not None else ""
            if keys_tried_on_401 >= len(api_keys):
                print(f"ERROR Groq API 401 (fatal): all {len(api_keys)} key(s) invalid | {body}",
                      file=sys.stderr)
                LAST_ERROR["msg"] = f"HTTP {status}" if status != -1 else "network error"
                return None, key_index
            key_index = (key_index + 1) % len(api_keys)
            server_error_attempts_on_current_key = 0
            print(f"  [invalid key] key #{(key_index - 1) % len(api_keys) + 1} rejected (401), "
                  f"rotating to key #{key_index + 1}/{len(api_keys)}", file=sys.stderr)
            continue

        # 其他 4xx 致命錯誤(400 格式、413 太大等)
        body = response.text[:300] if response is not None else ""
        print(f"ERROR Groq API {status} (fatal): {body}", file=sys.stderr)
        LAST_ERROR["msg"] = f"HTTP {status}" if status != -1 else "network error"
        return None, key_index


MINOR_OVERSHOOT_MS = 1000  # 句尾超出段長 ≤ 1s 是 Whisper 常態,只記錄、不列 unresolved


def _ms(x):
    """四捨五入到整數毫秒,半數進位(= JS Math.round;Python round() 是銀行家捨入,兩端會差 1ms)。"""
    return math.floor(x * 1000 + 0.5)


def repair_times(segments, duration=None):
    """輸出用時間戳,**以整數毫秒運算**(報告的 written 與 SRT 寫出值逐毫秒一致)。文字一律保留(零省略);
    回傳 (rows[(start_s, end_s, text)], adjustments)。規則(依序):
      不合法 → 緊接上一句、長 1s;開始早於上一句開始 → out_of_order、緊接上一句、保留原長;
      結尾超出段長 → 裁切;長度 < 1ms → 補到 1ms(段尾放不下就往前挪)。
    「上一句」= 上一個寫出的 cue(不是歷史最大結尾)。除「句尾小幅超出段長」外,調整都讓該段列 unresolved。"""
    dur = valid_duration(duration)
    dur_ms = _ms(dur) if dur is not None else None
    rows, adj = [], []
    prev_start, prev_end = 0, 0
    for idx, seg in enumerate(segments or []):
        text = (seg.get("text") or "").strip()
        if not text:
            continue
        raw_a, raw_e = _finite(seg.get("start")), _finite(seg.get("end"))
        reasons = []
        if raw_a is None or raw_e is None or raw_a < 0 or raw_e <= raw_a or (dur is not None and raw_a >= dur):
            a, e = prev_end, prev_end + 1000
            reasons.append("invalid")
        else:
            a, e = _ms(raw_a), _ms(raw_e)
            if rows and a < prev_start:
                length = e - a
                a, e = prev_end, prev_end + length
                reasons.append("out_of_order")
        if dur_ms is not None and e > dur_ms:
            reasons.append("clamp_end_minor" if not reasons and e - dur_ms <= MINOR_OVERSHOOT_MS else "clamp_end")
            e = dur_ms
        if e - a < 1:
            e = a + 1
            if dur_ms is not None and e > dur_ms:
                e, a = dur_ms, max(0, dur_ms - 1)
            reasons.append("min_length")
        if reasons:
            adj.append({"index": idx, "text": text, "original": [_json_safe(seg.get("start")),
                        _json_safe(seg.get("end"))], "written": [a / 1000, e / 1000], "reason": reasons})
        rows.append((a / 1000, e / 1000, text))
        prev_start, prev_end = a, e
    return rows, adj


def timing_unresolved(adjustments):
    return any(set(x["reason"]) - {"clamp_end_minor"} for x in adjustments)


def safe_times(segments, duration=None):
    return repair_times(segments, duration)[0]


def write_segments(srt_file, segments, time_offset, global_idx, duration=None):
    for a, e, text in safe_times(segments, duration):
        srt_file.write(f"{global_idx}\n")
        srt_file.write(f"{format_srt_time(a + time_offset)} --> {format_srt_time(e + time_offset)}\n")
        srt_file.write(f"{text}\n\n")
        global_idx += 1
    return global_idx


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
    report = []
    print(f"[groq] prompt mode: {PROMPT_MODE}; coverage second read: {'on' if COVERAGE_FALLBACK else 'off'}")
    with open(srt_output, "w", encoding="utf-8") as srt_file:
        for i, chunk_path in enumerate(chunks):
            print(f"[groq] Transcribing chunk {i+1}/{len(chunks)} "
                  f"(using key #{key_index % len(api_keys) + 1}/{len(api_keys)})...")
            time_offset = i * CHUNK_DURATION
            result, key_index, entry = process_chunk(chunk_path, api_keys, key_index, context_prompt, time_offset)
            if result:
                entry["chunk"] = i + 1
                report.append(entry)
                global_idx = write_segments(srt_file, result.get("segments", []), time_offset, global_idx,
                                            entry.get("duration"))
            else:
                failed_chunks.append(i + 1)
            os.remove(chunk_path)

    unresolved = [{"chunk": e["chunk"], "reasons": e["unresolved_reasons"], "gaps": e["gaps"],
                   "review_ranges": e["review_ranges"], "invalid_segments": e["invalid_segments"],
                   "timestamp_adjustments": e["timestamp_adjustments"]}
                  for e in report if e["unresolved_reasons"]]
    report_path = os.path.join(output_dir, f"{base_name}.transcribe_report.json")
    with open(report_path, "w", encoding="utf-8") as rf:
        json.dump({"gate_version": GATE_VERSION, "prompt_mode": PROMPT_MODE,
                   "coverage_fallback": COVERAGE_FALLBACK, "chunk_seconds": CHUNK_DURATION,
                   "note": "閘門只能找疑點,不能證明零省略(gotchas #8)",
                   "failed_chunks": failed_chunks, "chunks": report, "unresolved": unresolved},
                  rf, ensure_ascii=False, indent=2)

    if failed_chunks:
        # 不要靜默產生有 10 分鐘空洞的 SRT。讓 session.py 失敗,讓使用者知道。
        print(f"[groq] FATAL: {len(failed_chunks)} chunk(s) failed: {failed_chunks}",
              file=sys.stderr)
        print(f"[groq] Partial SRT written to {srt_output} (with gaps);"
              f" pipeline aborted to avoid silent corruption.", file=sys.stderr)
        print(f"[groq] Finished chunks cached in {temp_dir} — re-run the same command to resume.",
              file=sys.stderr)
        sys.exit(2)
    if global_idx == 1:
        print("[groq] FATAL: no text in any chunk — check the audio (pure silence? wrong file?)",
              file=sys.stderr)
        sys.exit(2)
    if unresolved:
        print(f"[groq] WARNING: {len(unresolved)} chunk(s) need a look — see {report_path} "
              f"(gaps may be real silence / video playback; review_ranges hold the other version's text)",
              file=sys.stderr)

    # Keep the cache when a second read failed so a re-run only retries that call.
    if any(e["second_status"] == "failed" for e in report):
        print(f"[groq] second read failed on some chunk(s); cache kept in {temp_dir} — re-run to retry.",
              file=sys.stderr)
    else:
        shutil.rmtree(temp_dir, ignore_errors=True)

    elapsed = time.time() - start_time
    print(f"[groq] SRT saved: {srt_output}")
    print(f"[groq] Total time: {elapsed:.1f}s")
    print(f"[groq] Total segments: {global_idx - 1}")

    # Output the SRT path for the caller
    print(f"OUTPUT_SRT={srt_output}")


if __name__ == "__main__":
    main()
