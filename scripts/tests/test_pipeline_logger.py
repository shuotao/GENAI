#!/usr/bin/env python3
"""test_pipeline_logger.py — scripts/pipeline_logger.py 的驗證測試。

覆蓋:log_stage 寫入格式(session log + 全域 log)、enqueue_improvement/list_open、
close_improvement、CLI --log/--list-open、jsonl 多筆 append 不互毀。

跑法:
    python3 scripts/tests/test_pipeline_logger.py
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = SCRIPTS_DIR.parent
sys.path.insert(0, str(SCRIPTS_DIR))

import pipeline_logger as pl  # noqa: E402


def _read_jsonl(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    return [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]


class TestPipelineLogger(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="pipeline_logger_test_"))
        # Monkeypatch module-level paths to isolate from real build/sessions dirs
        self._orig_build = pl.BUILD_DIR
        self._orig_sessions = pl.SESSIONS_DIR
        self._orig_global = pl.GLOBAL_LOG
        self._orig_queue = pl.IMPROVEMENT_QUEUE
        pl.BUILD_DIR = self.tmp / "build"
        pl.SESSIONS_DIR = self.tmp / "sessions"
        pl.GLOBAL_LOG = pl.BUILD_DIR / "pipeline_runs.jsonl"
        pl.IMPROVEMENT_QUEUE = pl.BUILD_DIR / "improvement_queue.jsonl"

    def tearDown(self):
        pl.BUILD_DIR = self._orig_build
        pl.SESSIONS_DIR = self._orig_sessions
        pl.GLOBAL_LOG = self._orig_global
        pl.IMPROVEMENT_QUEUE = self._orig_queue
        shutil.rmtree(self.tmp, ignore_errors=True)

    # ------------------------------------------------------------------
    # log_stage
    # ------------------------------------------------------------------
    def test_log_stage_writes_global_and_session_log(self):
        sdir = self.tmp / "sessions" / "my-slug"
        sdir.mkdir(parents=True)
        rec = pl.log_stage(sdir, "S4.5-gate", "prepublish_gate.py", "pass",
                            metrics={"fails": 0}, detail="ok")
        self.assertEqual(rec["session"], "my-slug")
        self.assertEqual(rec["stage"], "S4.5-gate")
        self.assertEqual(rec["status"], "pass")

        global_recs = _read_jsonl(pl.GLOBAL_LOG)
        self.assertEqual(len(global_recs), 1)
        self.assertEqual(global_recs[0]["session"], "my-slug")

        session_recs = _read_jsonl(sdir / "pipeline_log.jsonl")
        self.assertEqual(len(session_recs), 1)
        self.assertEqual(session_recs[0]["tool"], "prepublish_gate.py")

        # required fields present
        for field in ("ts", "session", "stage", "tool", "status", "metrics", "detail"):
            self.assertIn(field, global_recs[0])

    def test_log_stage_accepts_slug_string(self):
        rec = pl.log_stage("some-slug", "S6-audit", "publish_qaqc.py", "fail")
        self.assertEqual(rec["session"], "some-slug")
        session_log = pl.SESSIONS_DIR / "some-slug" / "pipeline_log.jsonl"
        self.assertTrue(session_log.is_file())

    def test_log_stage_none_session_only_global(self):
        rec = pl.log_stage(None, "S6-audit", "publish_qaqc.py", "pass")
        self.assertEqual(rec["session"], "(none)")
        global_recs = _read_jsonl(pl.GLOBAL_LOG)
        self.assertEqual(len(global_recs), 1)
        # no session dir should have been created
        self.assertFalse((pl.SESSIONS_DIR / "(none)").exists())

    def test_log_stage_invalid_status_raises(self):
        with self.assertRaises(ValueError):
            pl.log_stage(None, "stage", "tool", "bogus")

    def test_log_stage_multiple_appends_dont_corrupt(self):
        sdir = self.tmp / "sessions" / "multi"
        sdir.mkdir(parents=True)
        for i in range(20):
            pl.log_stage(sdir, f"stage-{i}", "tool.py", "pass" if i % 2 == 0 else "fail",
                         metrics={"i": i})
        global_recs = _read_jsonl(pl.GLOBAL_LOG)
        session_recs = _read_jsonl(sdir / "pipeline_log.jsonl")
        self.assertEqual(len(global_recs), 20)
        self.assertEqual(len(session_recs), 20)
        # order and content preserved
        for i, rec in enumerate(session_recs):
            self.assertEqual(rec["stage"], f"stage-{i}")
            self.assertEqual(rec["metrics"]["i"], i)

    # ------------------------------------------------------------------
    # improvement queue
    # ------------------------------------------------------------------
    def test_enqueue_and_list_open(self):
        pl.enqueue_improvement("S4.5-gate", "slug-a", "issue A", "fix A")
        pl.enqueue_improvement("S6-audit", "slug-b", "issue B")
        open_items = pl.list_open()
        self.assertEqual(len(open_items), 2)
        self.assertEqual(open_items[0]["issue"], "issue A")
        self.assertEqual(open_items[0]["suggestion"], "fix A")
        self.assertEqual(open_items[0]["status"], "open")
        self.assertEqual(open_items[1]["suggestion"], "")

    def test_list_open_empty_when_no_queue_file(self):
        self.assertEqual(pl.list_open(), [])

    def test_close_improvement(self):
        pl.enqueue_improvement("S4.5-gate", "slug-a", "issue A")
        pl.enqueue_improvement("S4.5-gate", "slug-b", "issue B")
        changed = pl.close_improvement(lambda rec: rec["session"] == "slug-a")
        self.assertEqual(changed, 1)
        open_items = pl.list_open()
        self.assertEqual(len(open_items), 1)
        self.assertEqual(open_items[0]["session"], "slug-b")

        all_recs = _read_jsonl(pl.IMPROVEMENT_QUEUE)
        self.assertEqual(len(all_recs), 2)
        closed = [r for r in all_recs if r["session"] == "slug-a"]
        self.assertEqual(closed[0]["status"], "closed")
        self.assertIn("closed_ts", closed[0])

    def test_queue_multiple_appends_dont_corrupt(self):
        for i in range(15):
            pl.enqueue_improvement("source", f"slug-{i}", f"issue {i}")
        recs = _read_jsonl(pl.IMPROVEMENT_QUEUE)
        self.assertEqual(len(recs), 15)
        for i, rec in enumerate(recs):
            self.assertEqual(rec["issue"], f"issue {i}")


class TestPipelineLoggerCLI(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="pipeline_logger_cli_test_"))
        self.env_build = self.tmp / "build"
        self.env_sessions = self.tmp / "sessions"

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _run_cli(self, *args):
        # Run the script with cwd set so PROJECT_ROOT-relative build/ lands in tmp.
        # pipeline_logger.py derives PROJECT_ROOT from __file__, not cwd, so instead
        # we invoke via -c to override module globals before calling main().
        code = (
            "import sys; from pathlib import Path; "
            "sys.path.insert(0, %r); import pipeline_logger as pl; "
            "pl.BUILD_DIR = Path(%r); pl.SESSIONS_DIR = Path(%r); "
            "pl.GLOBAL_LOG = pl.BUILD_DIR / 'pipeline_runs.jsonl'; "
            "pl.IMPROVEMENT_QUEUE = pl.BUILD_DIR / 'improvement_queue.jsonl'; "
            "sys.argv = ['pipeline_logger.py'] + %r; "
            "sys.exit(pl.main())"
        ) % (str(SCRIPTS_DIR), str(self.env_build), str(self.env_sessions), list(args))
        return subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)

    def test_cli_log_and_list_open(self):
        result = self._run_cli("--log", "cli-slug", "S4.5-gate", "prepublish_gate.py", "fail",
                                "something broke")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("logged", result.stdout)

        global_recs = _read_jsonl(self.env_build / "pipeline_runs.jsonl")
        self.assertEqual(len(global_recs), 1)
        self.assertEqual(global_recs[0]["session"], "cli-slug")
        self.assertEqual(global_recs[0]["status"], "fail")
        self.assertEqual(global_recs[0]["detail"], "something broke")

    def test_cli_log_invalid_status(self):
        result = self._run_cli("--log", "cli-slug", "stage", "tool", "notarealstatus")
        self.assertNotEqual(result.returncode, 0)

    def test_cli_list_open_no_queue(self):
        result = self._run_cli("--list-open")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("無 open", result.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
