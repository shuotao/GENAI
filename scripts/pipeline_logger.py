#!/usr/bin/env python3
"""pipeline_logger.py — 「log → check → return-and-improvement」自動化迴圈的基座。

純標準庫,零依賴。所有 Step1~6 的工具在跑完一個 stage 後呼叫 log_stage() 落一筆
JSON line;檢查類工具(prepublish_gate.py、publish_qaqc.py 等)發現失敗項時呼叫
enqueue_improvement() 把問題丟進待改善佇列,供之後的迴圈消化。

落點:
    sessions/<slug>/pipeline_log.jsonl   — 該 session 自己的 log(session 綁定)
    build/pipeline_runs.jsonl            — 全域彙總 log(跨 session 統計用)
    build/improvement_queue.jsonl        — 待改善佇列(open/closed)

設計原則:
    - 純 append-only JSON Lines,不做並發鎖(本專案是 sequential pipeline,原則 6/9)
    - import 失敗或寫檔失敗都不該讓呼叫端的主流程掛掉 → 呼叫端一律 try/except 包
    - CLI 介面供 shell 腳本(non-Python)呼叫:
        python3 scripts/pipeline_logger.py --log <session> <stage> <tool> <status> [detail]
        python3 scripts/pipeline_logger.py --list-open
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BUILD_DIR = PROJECT_ROOT / "build"
SESSIONS_DIR = PROJECT_ROOT / "sessions"
GLOBAL_LOG = BUILD_DIR / "pipeline_runs.jsonl"
IMPROVEMENT_QUEUE = BUILD_DIR / "improvement_queue.jsonl"

VALID_STATUS = ("pass", "fail", "warn")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _append_jsonl(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def _session_log_path(session) -> Path:
    """session 可以是 slug 字串,也可以是 session 目錄的 Path。"""
    if isinstance(session, Path):
        sdir = session
    else:
        s = str(session)
        p = Path(s)
        # 傳進來的若已是一個存在的目錄路徑(絕對或相對),直接用;否則當作 slug 拼 sessions/<slug>
        sdir = p if p.is_dir() else SESSIONS_DIR / s
    return sdir / "pipeline_log.jsonl"


def _session_name(session) -> str:
    if isinstance(session, Path):
        return session.name
    s = str(session)
    p = Path(s)
    return p.name if p.is_dir() or "/" in s else s


def log_stage(session_dir, stage: str, tool: str, status: str,
              metrics: dict | None = None, detail: str = "") -> dict:
    """記一筆 stage 執行結果,同時 append 到 session log 與全域 log。

    Args:
        session_dir: session 目錄路徑(Path 或字串),或 slug 字串;也接受
            None/""(找不到 session 時只寫全域 log,session 欄位標 "(none)")。
        stage: 例如 "S4.5-gate"、"S6-audit"、"S4.5-insert"
        tool: 呼叫的腳本名,例如 "prepublish_gate.py"
        status: "pass" | "fail" | "warn"
        metrics: 任意數值統計 dict(可 None)
        detail: 人類可讀的補充說明

    Returns:
        寫入的 record dict。
    """
    if status not in VALID_STATUS:
        raise ValueError(f"status 必須是 {VALID_STATUS} 之一,收到 {status!r}")

    session_name = _session_name(session_dir) if session_dir else "(none)"
    record = {
        "ts": _now_iso(),
        "session": session_name,
        "stage": stage,
        "tool": tool,
        "status": status,
        "metrics": metrics or {},
        "detail": detail,
    }

    _append_jsonl(GLOBAL_LOG, record)
    if session_dir:
        _append_jsonl(_session_log_path(session_dir), record)

    return record


def enqueue_improvement(source: str, session: str, issue: str, suggestion: str = "") -> dict:
    """把一個待改善項目 append 到 build/improvement_queue.jsonl。

    Args:
        source: 哪個 check 發現的,例如 "S4.5-gate"、"S6-audit"
        session: session slug(或 "(none)")
        issue: 問題描述
        suggestion: 建議修法(可空)

    Returns:
        寫入的 record dict。
    """
    record = {
        "ts": _now_iso(),
        "source": source,
        "session": session,
        "issue": issue,
        "suggestion": suggestion,
        "status": "open",
    }
    _append_jsonl(IMPROVEMENT_QUEUE, record)
    return record


def list_open() -> list[dict]:
    """讀 improvement_queue.jsonl,回傳 status == 'open' 的項目(依 ts 順序)。"""
    if not IMPROVEMENT_QUEUE.is_file():
        return []
    out = []
    for line in IMPROVEMENT_QUEUE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if rec.get("status") == "open":
            out.append(rec)
    return out


def close_improvement(match_fn) -> int:
    """把 improvement_queue.jsonl 中符合 match_fn(record) -> bool 的項目改成 status='closed'。

    因為是 append-only jsonl,「改狀態」的做法是:重寫整份檔案,對符合的項目
    加上 closed_ts 並把 status 改成 closed(其餘保持不動;不合併重複行)。

    Returns:
        改動的筆數。
    """
    if not IMPROVEMENT_QUEUE.is_file():
        return 0
    lines = IMPROVEMENT_QUEUE.read_text(encoding="utf-8").splitlines()
    out_lines = []
    changed = 0
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            out_lines.append(line)
            continue
        if rec.get("status") == "open" and match_fn(rec):
            rec["status"] = "closed"
            rec["closed_ts"] = _now_iso()
            changed += 1
        out_lines.append(json.dumps(rec, ensure_ascii=False))
    if changed:
        IMPROVEMENT_QUEUE.write_text("\n".join(out_lines) + "\n", encoding="utf-8")
    return changed


def _cli_list_open() -> int:
    items = list_open()
    if not items:
        print("[pipeline_logger] improvement queue 無 open 項目。")
        return 0
    print(f"[pipeline_logger] {len(items)} 筆 open:")
    for it in items:
        print(f"  - [{it['ts']}] ({it['source']}/{it['session']}) {it['issue']}"
              + (f" — 建議:{it['suggestion']}" if it.get("suggestion") else ""))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Pipeline log/improvement queue CLI")
    ap.add_argument("--list-open", action="store_true", help="列出 improvement queue 的 open 項目")
    ap.add_argument("--log", nargs="+", metavar="ARG",
                    help="--log <session> <stage> <tool> <status> [detail]")
    a = ap.parse_args()

    if a.list_open:
        return _cli_list_open()

    if a.log:
        if len(a.log) < 4:
            print("--log 需要至少 4 個參數: <session> <stage> <tool> <status> [detail]",
                  file=sys.stderr)
            return 2
        session, stage, tool, status = a.log[0], a.log[1], a.log[2], a.log[3]
        detail = " ".join(a.log[4:]) if len(a.log) > 4 else ""
        try:
            rec = log_stage(session, stage, tool, status, detail=detail)
        except ValueError as e:
            print(f"[pipeline_logger] ✗ {e}", file=sys.stderr)
            return 2
        print(f"[pipeline_logger] ✓ logged: {rec['session']}/{rec['stage']} status={rec['status']}")
        return 0

    ap.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
