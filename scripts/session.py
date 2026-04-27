#!/usr/bin/env python3
"""
scripts/session.py — 統籌一次音訊轉筆記處理的整條 pipeline

Session 容器把所有產物與輸入都綁在 sessions/<slug>/,避免汙染專案根目錄。

用法:
    python3 scripts/session.py new <audio_file> \\
        [--context "<data-or-file>"] \\
        [--domain <name>] \\
        [--identity "<身份>"] \\
        [--skip-phase-b]     # 僅跑到 Phase A,產出 cleaned.srt 不產 cleaned.md
        [--structured-srt]   # 另外產一份 transcript.cleaned.srt(結構保留型校稿)

Flow:
    1. Build slug YYYY-MM-DD_<sanitized-filename>, mkdir sessions/<slug>/
    2. symlink audio → source.<ext>; write context.txt (and metadata.json skeleton)
    3. groq_transcribe.py → transcript.srt  (IMMUTABLE)
    4. qaqc_srt.py --domain <name> → cleaned.srt  (Phase A only)
    5. phase B merged → cleaned.md
    6. (optional) qaqc_srt.py --structured → transcript.cleaned.srt  (timecode-safe)
    7. (optional) identity-based notes_<identity>.md
    8. Write final metadata.json (ratios, timings, typo hits, etc.)
"""

import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SESSIONS_DIR = PROJECT_ROOT / "sessions"
GROQ_SCRIPT = PROJECT_ROOT / ".claude/skills/good-student-notes/scripts/groq_transcribe.py"
QAQC_SCRIPT = PROJECT_ROOT / "SRT/qaqc_srt.py"
PHASE_B_SCRIPT = PROJECT_ROOT / "scripts/qaqc_phase_b.py"


# ─── Engine routing(誰在叫我?)──────────────────────────────────────
# 規則:CLI host(Claude Code、Gemini CLI 等)用 OAuth login token 計費,絕不打
# LLM API key,Phase B/Step 3/Step 4 由對話 agent 接手。純 shell/cron 才走 API。
# 詳見 CLAUDE.md「Engine Routing」章節 + memory feedback_auth_model_split.md。

ENGINE_CHOICES = ("auto", "claude", "gemini", "copilot", "api", "none")

# host detection signals → engine。第一個命中就贏。
ENGINE_ENV_SIGNALS = (
    ("claude",  ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "CLAUDE_CODE_EXECPATH")),
    ("gemini",  ("GEMINI_CLI", "GEMINI_CLI_SESSION", "GOOGLE_GEMINI_CLI")),
    ("copilot", ("GITHUB_COPILOT_CLI", "GH_COPILOT_AGENT", "COPILOT_AGENT_SESSION")),
)


def detect_engine(explicit: str | None = None) -> tuple[str, str]:
    """Return (engine, reason). Explicit non-auto value short-circuits detection."""
    if explicit and explicit != "auto":
        return explicit, f"--engine={explicit}"
    for engine, env_keys in ENGINE_ENV_SIGNALS:
        for k in env_keys:
            if os.environ.get(k):
                return engine, f"detected ${k}"
    return "unknown", "no host signal found"


def resolve_engine(args) -> str:
    """Print the routing decision and return the chosen engine.
    `unknown` defaults to refusing API calls — the user must opt in via --engine api."""
    engine, reason = detect_engine(args.engine)
    if engine == "unknown":
        print(f"[session] engine=unknown ({reason}); Phase B / Step 3 / Step 4 will be "
              f"SKIPPED to avoid burning API quotas. Pass --engine api to opt into "
              f"calling Gemini API explicitly.", file=sys.stderr)
        return "none"
    host_label = os.environ.get("AI_AGENT", "agent CLI" if engine != "api" else "Web/cron")
    print(f"[session] engine={engine} ({reason}, host={host_label})")
    return engine


# ─── Slug ───

def _slugify(name: str) -> str:
    """Convert audio filename stem into a filesystem-friendly slug."""
    s = re.sub(r"[^\w.\- ]", "", name, flags=re.UNICODE)
    s = re.sub(r"\s+", "-", s.strip())
    return s


def build_slug(audio_path: Path, today: dt.date | None = None) -> str:
    today = today or dt.date.today()
    return f"{today.isoformat()}_{_slugify(audio_path.stem)}"


# ─── Context writer ───

def resolve_context(ctx: str | None) -> str:
    """Accept a path, a raw string, or None. Return content (possibly empty)."""
    if not ctx:
        return ""
    p = Path(ctx)
    if p.exists() and p.is_file():
        return p.read_text(encoding="utf-8")
    return ctx


# ─── Char metrics ───

def count_chars(text: str) -> dict:
    no_space = re.sub(r"\s+", "", text)
    chinese = re.findall(r"[一-鿿]", text)
    return {"no_space": len(no_space), "chinese": len(chinese)}


# ─── Srt parsing for metrics ───

def srt_effective_chars(srt_path: Path) -> dict:
    """Return char counts for SRT text portion only (excluding timecodes/indices)."""
    content = srt_path.read_text(encoding="utf-8")
    # Strip index lines (digits only) and timecode lines
    lines = []
    for line in content.splitlines():
        s = line.strip()
        if not s:
            continue
        if re.fullmatch(r"\d+", s):
            continue
        if "-->" in s:
            continue
        lines.append(s)
    joined = " ".join(lines)
    return count_chars(joined)


# ─── Pipeline steps ───

def run(cmd: list[str], cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess:
    print(f"\n$ {' '.join(cmd)}", file=sys.stderr)
    return subprocess.run(cmd, cwd=str(cwd or PROJECT_ROOT), check=check,
                          capture_output=False)


def new_session(args):
    # 0. Engine routing — 第一件事:確認誰在叫我,印出 routing 決策
    engine = resolve_engine(args)
    if getattr(args, "dry_run", False):
        print(f"[session] --dry-run: engine={engine}, exiting without doing work.")
        return

    audio = Path(args.audio).resolve()
    if not audio.exists():
        print(f"Audio not found: {audio}", file=sys.stderr)
        sys.exit(1)

    SESSIONS_DIR.mkdir(exist_ok=True)
    slug = build_slug(audio)
    sdir = SESSIONS_DIR / slug
    if sdir.exists():
        # If the session already exists, we do NOT overwrite its products; bail.
        print(f"Session already exists: {sdir}", file=sys.stderr)
        print("Remove it first or pick a different date.", file=sys.stderr)
        sys.exit(2)
    sdir.mkdir()

    print(f"[session] created: {sdir}")

    # 1. symlink audio
    ext = audio.suffix
    src_link = sdir / f"source{ext}"
    try:
        os.symlink(audio, src_link)
    except OSError:
        # Fallback to copy on filesystems that can't symlink
        import shutil
        shutil.copy2(audio, src_link)

    # 2. context.txt
    ctx_text = resolve_context(args.context)
    ctx_path = sdir / "context.txt"
    ctx_path.write_text(ctx_text, encoding="utf-8")
    print(f"[session] context.txt: {len(ctx_text)} chars / "
          f"{len(ctx_text.encode('utf-8'))} bytes")

    # 3. Metadata skeleton
    meta = {
        "session_id": slug,
        "source_audio": audio.name,
        "source_size_bytes": audio.stat().st_size,
        "created_at": dt.date.today().isoformat(),
        "domain_candidate": args.domain,
        "identity": args.identity,
    }

    # 4. Groq transcription
    t0 = time.time()
    transcript = sdir / "transcript.srt"
    # groq_transcribe.py signature: <media> [output_dir] [context_file]
    # We want output to be named transcript.srt (not <stem>.srt), so we handle rename.
    run(["python3", str(GROQ_SCRIPT), str(src_link), str(sdir), str(ctx_path)])
    # groq script outputs <stem>.srt — since we symlinked to source.<ext>, stem = "source"
    groq_out = sdir / "source.srt"
    if groq_out.exists():
        groq_out.rename(transcript)
    if not transcript.exists():
        print(f"[session] ERROR: Groq did not produce transcript.srt", file=sys.stderr)
        meta["error"] = "groq_transcription_failed"
        (sdir / "metadata.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2),
                                            encoding="utf-8")
        sys.exit(3)
    groq_secs = round(time.time() - t0, 1)
    print(f"[session] transcript.srt saved ({transcript.stat().st_size} bytes, "
          f"{groq_secs}s)")

    original_metrics = srt_effective_chars(transcript)

    # 5. Phase A cleanup → cleaned.srt
    cleaned_srt = sdir / "cleaned.srt"
    cmd = ["python3", str(QAQC_SCRIPT), str(transcript), "-o", str(cleaned_srt)]
    if args.domain:
        cmd += ["--domain", args.domain]
    run(cmd)

    phase_a_metrics = srt_effective_chars(cleaned_srt)

    # 6. Structured-preserving polish → transcript.cleaned.srt (optional)
    transcript_cleaned_srt = None
    if args.structured_srt:
        transcript_cleaned_srt = sdir / "transcript.cleaned.srt"
        cmd = ["python3", str(QAQC_SCRIPT), str(transcript),
               "-o", str(transcript_cleaned_srt),
               "--structured"]
        if args.domain:
            cmd += ["--domain", args.domain]
        if ctx_text:
            cmd += ["--context", str(ctx_path)]
        try:
            run(cmd)
        except subprocess.CalledProcessError as e:
            print(f"[session] structured polish failed: {e}", file=sys.stderr)
            transcript_cleaned_srt = None

    # 7. Phase B merged → cleaned.md
    # (skipped if --stop-at transcribe/phase-a OR --skip-phase-b)
    cleaned_md = sdir / "cleaned.md"
    phase_b_stats = None
    do_phase_b = (not args.skip_phase_b
                  and args.stop_at not in ("transcribe", "phase-a"))
    if do_phase_b:
        plain = _srt_to_plain(cleaned_srt)
        in_m = count_chars(plain)

        if engine in ("claude", "gemini", "copilot"):
            # Agent CLI 模式:寫 Phase A 純文字到 cleaned.md + 放 marker,等對話 agent 接手
            cleaned_md.write_text(plain, encoding="utf-8")
            target_lo = int(in_m["chinese"] * 0.95)
            target_hi = int(in_m["chinese"] * 1.05)
            marker_path = sdir / ".phase_b_pending.json"
            marker = {
                "stage": "phase-b",
                "engine": engine,
                "input_file": str(cleaned_md.relative_to(PROJECT_ROOT)),
                "rules_ref": "CLAUDE.md § 核心鐵律 + § QAQC 標準",
                "ssot_rules": "prompts/qaqc_core_rules.md",
                "input_chinese_chars": in_m["chinese"],
                "target_chinese_chars_min": target_lo,
                "target_chinese_chars_max": target_hi,
                "context_file": str(ctx_path.relative_to(PROJECT_ROOT)),
                "instructions": (
                    f"Phase B 待 {engine} agent 接手。讀 {cleaned_md.name} 純文字版,套 "
                    "CLAUDE.md 的 Phase B 規則(零省略、合併斷行、加標點接續詞、加 ## 標題、"
                    f"中文字數落在 {target_lo}-{target_hi} 區間),寫回 {cleaned_md.name}。"
                    "完成後刪本 marker。"
                ),
                "created_at": dt.datetime.now().isoformat(timespec="seconds"),
            }
            marker_path.write_text(
                json.dumps(marker, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"[session] Phase B 待 {engine} agent 接手:")
            print(f"  marker: {marker_path.relative_to(PROJECT_ROOT)}")
            print(f"  input:  {cleaned_md.relative_to(PROJECT_ROOT)} "
                  f"({in_m['chinese']:,} 中文字)")
            print(f"  target: {target_lo:,}-{target_hi:,} 中文字 (95-105%)")
            phase_b_stats = {
                "engine": engine,
                "status": "pending_agent_handoff",
                "marker_file": marker_path.name,
                "in_chinese_chars": in_m["chinese"],
                "target_min": target_lo,
                "target_max": target_hi,
            }

        elif engine == "api":
            # 純 shell/cron 路徑:打 Gemini API
            tmp_in = sdir / ".phase_b_input.txt"
            tmp_in.write_text(plain, encoding="utf-8")
            try:
                cmd = ["python3", str(PHASE_B_SCRIPT), str(tmp_in),
                       "-o", str(cleaned_md), "--mode", "merged"]
                if ctx_text:
                    cmd += ["--context", str(ctx_path)]
                run(cmd)
                out_m = count_chars(cleaned_md.read_text(encoding="utf-8"))
                phase_b_stats = {
                    "engine": "api",
                    "in_chars_no_space": in_m["no_space"],
                    "out_chars_no_space": out_m["no_space"],
                    "ratio_no_space": round(out_m["no_space"] / max(1, in_m["no_space"]), 4),
                    "ratio_chinese": round(out_m["chinese"] / max(1, in_m["chinese"]), 4),
                }
            except subprocess.CalledProcessError as e:
                print(f"[session] Phase B (API) failed: {e} — falling back to Phase A plaintext",
                      file=sys.stderr)
                cleaned_md.write_text(plain, encoding="utf-8")
                phase_b_stats = {"engine": "api", "fallback": "phase_a_plaintext",
                                 "error": str(e)}
            finally:
                if tmp_in.exists():
                    tmp_in.unlink()

        else:  # engine == "none"
            cleaned_md.write_text(plain, encoding="utf-8")
            print(f"[session] engine=none: Phase B skipped, cleaned.md = Phase A plaintext")
            phase_b_stats = {"engine": "none", "status": "skipped"}

    # 7.5 Step 3: 專有名詞補充 → enhanced.md
    # Runs if --keywords given OR --enhance flag OR stop-at in {enhance, notes}.
    enhanced_md = None
    enhance_stats = None
    do_enhance = (cleaned_md.exists()
                  and args.stop_at not in ("transcribe", "phase-a", "phase-b")
                  and (args.keywords or args.enhance
                       or (args.identity and args.stop_at == "notes")))
    if do_enhance:
        enhanced_md = sdir / "enhanced.md"

        if engine in ("claude", "gemini", "copilot"):
            # Agent CLI 模式:寫 marker,等對話 agent 接手(在 Phase B 處理完 cleaned.md 之後)
            marker_path = sdir / ".step_3_pending.json"
            marker = {
                "stage": "step-3-enhance",
                "engine": engine,
                "input_file": str(cleaned_md.relative_to(PROJECT_ROOT)),
                "output_file": str(enhanced_md.relative_to(PROJECT_ROOT)),
                "rules_ref": "CLAUDE.md § Step 3 + prompts/qaqc_core_rules.md",
                "keywords_explicit": args.keywords or None,
                "context_file": str(ctx_path.relative_to(PROJECT_ROOT)),
                "depends_on": "phase-b 完成(cleaned.md 已校稿,不是純文字版)",
                "instructions": (
                    f"Step 3 待 {engine} agent 接手。先確認 cleaned.md 已完成 Phase B "
                    "(如果 .phase_b_pending.json 還在,先處理它)。然後讀 cleaned.md,"
                    "標出專有名詞並補充說明,輸出 enhanced.md。完成後刪本 marker。"
                ),
                "created_at": dt.datetime.now().isoformat(timespec="seconds"),
            }
            marker_path.write_text(
                json.dumps(marker, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"[session] Step 3 待 {engine} agent 接手: "
                  f"{marker_path.relative_to(PROJECT_ROOT)}")
            enhance_stats = {"engine": engine, "status": "pending_agent_handoff",
                             "marker_file": marker_path.name}
            enhanced_md = None  # 不要把不存在的檔當 source for Step 4

        elif engine == "api":
            try:
                cmd = ["python3", str(PHASE_B_SCRIPT), str(cleaned_md),
                       "-o", str(enhanced_md), "--mode", "enhance"]
                if args.keywords:
                    cmd += ["--keywords", args.keywords]
                if ctx_text:
                    cmd += ["--context", str(ctx_path)]
                run(cmd)
                in_m = count_chars(cleaned_md.read_text(encoding="utf-8"))
                out_m = count_chars(enhanced_md.read_text(encoding="utf-8"))
                enhance_stats = {
                    "engine": "api",
                    "in_chars_no_space": in_m["no_space"],
                    "out_chars_no_space": out_m["no_space"],
                    "ratio_no_space": round(out_m["no_space"] / max(1, in_m["no_space"]), 4),
                    "keywords_explicit": bool(args.keywords),
                }
            except subprocess.CalledProcessError as e:
                print(f"[session] Step 3 enhance (API) failed: {e}", file=sys.stderr)
                enhanced_md = None
                enhance_stats = {"engine": "api", "error": str(e)}

        else:  # none
            print("[session] engine=none: Step 3 skipped")
            enhanced_md = None
            enhance_stats = {"engine": "none", "status": "skipped"}

    # 7.6 Step 4: 立場置入好學生筆記 → notes_<identity>.md
    notes_md = None
    notes_stats = None
    do_notes = (args.identity and args.stop_at == "notes" and cleaned_md.exists())
    if do_notes:
        notes_md = sdir / f"notes_{args.identity}.md"
        source_md = enhanced_md if (enhanced_md and enhanced_md.exists()) else cleaned_md

        if engine in ("claude", "gemini", "copilot"):
            marker_path = sdir / ".step_4_pending.json"
            marker = {
                "stage": "step-4-notes",
                "engine": engine,
                "identity": args.identity,
                "input_file": str(source_md.relative_to(PROJECT_ROOT)),
                "output_file": str(notes_md.relative_to(PROJECT_ROOT)),
                "rules_ref": "CLAUDE.md § 好學生筆記規範 + prompts/qaqc_core_rules.md",
                "context_file": str(ctx_path.relative_to(PROJECT_ROOT)),
                "depends_on": ("step-3-enhance 完成(若有);否則 phase-b 完成"),
                "instructions": (
                    f"Step 4 待 {engine} agent 接手。讀 {source_md.name},以「{args.identity}」"
                    "立場插入專業視角類比區塊(類比/應用/連結),完整保留原文,字數比 95-105%,"
                    f"輸出 {notes_md.name}。完成後刪本 marker。"
                ),
                "created_at": dt.datetime.now().isoformat(timespec="seconds"),
            }
            marker_path.write_text(
                json.dumps(marker, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"[session] Step 4 待 {engine} agent 接手: "
                  f"{marker_path.relative_to(PROJECT_ROOT)}")
            notes_stats = {"engine": engine, "status": "pending_agent_handoff",
                           "marker_file": marker_path.name, "identity": args.identity}
            notes_md = None

        elif engine == "api":
            try:
                cmd = ["python3", str(PHASE_B_SCRIPT), str(source_md),
                       "-o", str(notes_md), "--mode", "notes",
                       "--identity", args.identity]
                if ctx_text:
                    cmd += ["--context", str(ctx_path)]
                run(cmd)
                in_m = count_chars(source_md.read_text(encoding="utf-8"))
                out_m = count_chars(notes_md.read_text(encoding="utf-8"))
                notes_stats = {
                    "engine": "api",
                    "source": source_md.name,
                    "in_chars_no_space": in_m["no_space"],
                    "out_chars_no_space": out_m["no_space"],
                    "ratio_no_space": round(out_m["no_space"] / max(1, in_m["no_space"]), 4),
                }
            except subprocess.CalledProcessError as e:
                print(f"[session] Step 4 notes (API) failed: {e}", file=sys.stderr)
                notes_md = None
                notes_stats = {"engine": "api", "error": str(e)}

        else:  # none
            print("[session] engine=none: Step 4 skipped")
            notes_md = None
            notes_stats = {"engine": "none", "status": "skipped"}

    # 8. Write metadata.json
    meta.update({
        "stop_at": args.stop_at,
        "transcription": {
            "engine": "Groq Whisper large-v3",
            "duration_secs": groq_secs,
            "context_bytes": len(ctx_text.encode("utf-8")),
            "original_chars_no_space": original_metrics["no_space"],
            "original_chinese_chars": original_metrics["chinese"],
        },
        "qaqc": {
            "phase_a_chars_no_space": phase_a_metrics["no_space"],
            "phase_a_chinese_chars": phase_a_metrics["chinese"],
            "phase_b": phase_b_stats,
            "enhance": enhance_stats,
            "notes": notes_stats,
            "structured_srt_produced": transcript_cleaned_srt is not None,
        },
        "artifacts": {
            "source": src_link.name,
            "context": ctx_path.name,
            "transcript_srt": transcript.name,
            "cleaned_srt": cleaned_srt.name,
            "cleaned_md": cleaned_md.name if cleaned_md.exists() else None,
            "enhanced_md": enhanced_md.name if (enhanced_md and enhanced_md.exists()) else None,
            "notes_md": notes_md.name if (notes_md and notes_md.exists()) else None,
            "transcript_cleaned_srt": (transcript_cleaned_srt.name
                                       if transcript_cleaned_srt else None),
        },
    })
    (sdir / "metadata.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n[session] ✅ complete: {sdir}")
    if phase_b_stats:
        print(f"  Phase B ratio_chinese = {phase_b_stats.get('ratio_chinese', 'N/A')}")
    if enhanced_md:
        print(f"  Step 3 enhanced.md produced")
    if notes_md:
        print(f"  Step 4 notes_{args.identity}.md produced")
    print(f"  stopped at: {args.stop_at}")


def _srt_to_plain(srt_path: Path) -> str:
    """Strip SRT indices + timecodes, return concatenated text with newlines between segments."""
    out_lines = []
    for block in srt_path.read_text(encoding="utf-8").strip().split("\n\n"):
        lines = block.split("\n")
        if len(lines) >= 3:
            out_lines.append("\n".join(lines[2:]))
    return "\n".join(out_lines)


# ─── Main ───

def main():
    ap = argparse.ArgumentParser(
        description="好學生筆記 pipeline 統籌器 — sessions/<slug>/ 容器化所有產物",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = ap.add_subparsers(dest="cmd", required=True)

    new = sub.add_parser("new", help="Create & run a new session")
    new.add_argument("audio", help="Path to audio/video file")
    new.add_argument("--context", help="Context: a string OR a path to a .txt file")
    new.add_argument("--domain", help="Typo dict domain overlay, e.g. parenting")
    new.add_argument("--identity",
                     help="Step 4 立場 for 好學生筆記 (e.g. 建築師);"
                          " requires --stop-at notes")
    new.add_argument("--keywords",
                     help="Step 3 comma-separated keyword list for 專有名詞補充;"
                          " omit + --enhance to let LLM auto-detect")
    new.add_argument("--enhance", action="store_true",
                     help="Run Step 3 (專有名詞補充) with auto-detected terms")
    new.add_argument("--stop-at",
                     choices=["transcribe", "phase-a", "phase-b", "enhance", "notes"],
                     default="phase-b",
                     help="Stopping point (default: phase-b = cleaned.md). "
                          "Step 2 is the most common終點 for users who just want the "
                          "合併 cleaned.md — don't always run to notes.")
    new.add_argument("--skip-phase-b", action="store_true",
                     help="(Legacy alias of --stop-at phase-a) Skip Phase B; produce cleaned.srt only")
    new.add_argument("--structured-srt", action="store_true",
                     help="Also produce transcript.cleaned.srt via --structured mode")
    new.add_argument("--engine",
                     choices=ENGINE_CHOICES,
                     default="auto",
                     help="Phase B / Step 3 / Step 4 routing. "
                          "auto: detect host via env (CLAUDECODE/GEMINI_CLI/...); "
                          "claude|gemini|copilot: agent接手, 不打 API; "
                          "api: 走 Gemini API (純 shell/cron 用); "
                          "none: 跳過所有 LLM 步驟,只到 Phase A")
    new.add_argument("--dry-run", action="store_true",
                     help="Just print engine routing decision and exit (no Groq/no API)")

    args = ap.parse_args()
    if args.cmd == "new":
        new_session(args)


if __name__ == "__main__":
    main()
