"""Groq 轉錄 2026-11-08 修正的守門測試(docs/gotchas.md #1、#8):
  1. prompt 上限 896 以 UTF-8 bytes 計 → truncate_prompt 按 bytes 裁、不切壞多位元組字
  2. 主轉錄預設不送 prompt;覆蓋率可疑才帶 prompt 轉一次當「診斷對照」,只回報、不換版
  3. prompted(舊)模式:以時間區間差集決定是否換成無 prompt 版
  4. 快取驗證 / 第二次轉錄失敗 / 時長未知 / 收尾警告 的控制流程
CLI(groq_transcribe.py)與 Web(web/studio.js)同門檻同語義,Parity 用 node 對照。"""
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / ".claude/skills/good-student-notes/scripts"))
import groq_transcribe as gt  # noqa: E402


def segs(spans, text="這是一句測試用的完整語音內容"):
    """每個 span 切成 ≤5 秒的句子(真實 Whisper 句長),避免誤觸稀疏規則。"""
    out = []
    for a, e in spans:
        t = a
        while t < e:
            out.append({"start": t, "end": min(t + 5, e), "text": text})
            t += 5
    return out


# 實際形狀(2026 AI FORUM 場,有 prompt 的 600s 段):每 ~150s 出現一次 20s 空白
DROPPY = segs([(0, 3)] + [(21 + 10 * k, 30 + 10 * k) for k in range(13)]
              + [(175, 184), (204, 300), (320, 450), (474, 500), (526, 600)])
DENSE = segs([(16 + 5 * k, 21 + 5 * k) for k in range(116)])          # 段首 16s 靜音
PAUSE16 = segs([(0, 3)] + [(19 + 5 * k, 24 + 5 * k) for k in range(116)])  # 寒暄後停 16s
GAP_A = segs([(0, 100), (120, 600)])        # 漏 100–120
GAP_B = segs([(0, 300), (320, 600)])        # 漏 300–320(與 GAP_A 互補)
SPARSE = [{"start": 0, "end": 600, "text": "嗯"}]                     # 吐一句然後沉默
EMOJI = [{"start": 0, "end": 5, "text": "😀😀 好　的 "}]
FIXTURES = {"droppy": (DROPPY, 600.0), "dense": (DENSE, 600.0), "pause16": (PAUSE16, 600.0),
            "gap_a": (GAP_A, 600.0), "gap_b": (GAP_B, 600.0), "sparse": (SPARSE, 600.0),
            "empty": ([], 300.0), "unknown_dur": (DENSE, None), "emoji": (EMOJI, 5.0),
            "bad_ts": ([{"start": 5, "end": 2, "text": "壞"}, {"start": "x", "end": 9, "text": "壞"}] + DENSE, 600.0)}


class TruncatePrompt(unittest.TestCase):
    def test_short_prompt_untouched(self):
        self.assertEqual(gt.truncate_prompt("短 prompt kW"), "短 prompt kW")

    def test_cjk_capped_by_bytes(self):
        self.assertEqual(gt.truncate_prompt("中" * 900), "中" * 298)          # 896 // 3

    def test_never_splits_multibyte_char(self):
        for n in range(1, 4):
            out = gt.truncate_prompt("a" * n + "中" * 400)
            self.assertLessEqual(len(out.encode("utf-8")), 896)

    def test_build_prompt_fits(self):
        self.assertLessEqual(len(gt.build_prompt("算力中心、液冷 CDU、kW/Rack、" * 40).encode()), 896)


class Coverage(unittest.TestCase):
    def cov(self, k):
        return gt.chunk_coverage(*FIXTURES[k])

    def test_droppy_is_suspicious(self):
        c = self.cov("droppy")
        self.assertIn("interior_gap", c["reasons"])
        self.assertIn("gap_ratio", c["reasons"])

    def test_dense_with_leading_silence_is_clean(self):
        self.assertEqual(self.cov("dense")["reasons"], [])

    def test_pause_after_greeting_is_flagged(self):          # 誤報只多一次對照呼叫
        self.assertEqual(self.cov("pause16")["reasons"], ["interior_gap"])

    def test_sparse_segment(self):
        self.assertIn("sparse_segment", self.cov("sparse")["reasons"])

    def test_unknown_duration_and_empty(self):
        self.assertIn("duration_unknown", self.cov("unknown_dur")["reasons"])
        self.assertIn("no_text", self.cov("empty")["reasons"])
        for bad in (0, -1, float("nan"), float("inf"), "abc"):
            self.assertIsNone(gt.valid_duration(bad))

    def test_invalid_timestamps_reported_not_hidden(self):
        c = self.cov("bad_ts")
        self.assertEqual(c["invalid_segments"], 2)
        self.assertIn("invalid_timestamps", c["reasons"])

    def test_text_len_code_points(self):
        self.assertEqual(self.cov("emoji")["text_chars"], 4)              # 😀😀好的;全形空白不計

    def test_interval_diff(self):
        self.assertEqual(gt.interval_diff([[0, 10]], [[2, 3], [5, 6]]), [[0, 2], [3, 5], [6, 10]])
        self.assertEqual(gt.interval_diff([[0, 10]], [[0, 10]]), [])


class PickAndDecide(unittest.TestCase):
    def test_prompted_mode_switches_only_on_clear_gain(self):
        p, q = gt.chunk_coverage(*FIXTURES["droppy"]), gt.chunk_coverage(*FIXTURES["pause16"])
        self.assertEqual(gt.pick_better(p, q), "second")

    def test_complementary_gaps_do_not_switch_and_are_reported(self):
        a, b = {"segments": GAP_A}, {"segments": GAP_B}
        sel, entry = gt.decide("prompted", a, b, "plain", 600.0, 0, "done")
        self.assertIs(sel, a)                                     # loss 20s > 1s → 不換
        self.assertEqual([(r["start"], r["end"]) for r in entry["review_ranges"]], [(100.0, 120.0)])
        self.assertIn("other_version_has_extra_ranges", entry["unresolved_reasons"])

    def test_plain_mode_never_switches_to_prompted(self):
        plain, prompted = {"segments": DROPPY}, {"segments": DENSE + segs([(1, 2)], "內容包含:算力中心")}
        sel, entry = gt.decide("plain", plain, prompted, "prompted", 600.0, 600, "done")
        self.assertIs(sel, plain)
        self.assertTrue(entry["review_ranges"])
        self.assertTrue(all(r["source"] == "prompted" and r["start"] >= 600 for r in entry["review_ranges"]))

    def test_second_read_failure_is_unresolved(self):
        _, entry = gt.decide("plain", {"segments": DROPPY}, None, "prompted", 600.0, 0, "failed", "HTTP 429")
        self.assertIn("second_read_failed", entry["unresolved_reasons"])
        self.assertEqual(entry["second_error"], "HTTP 429")

    def test_clean_chunk_resolved(self):
        _, entry = gt.decide("plain", {"segments": DENSE}, None, "prompted", 600.0, 0, "not_needed")
        self.assertEqual(entry["unresolved_reasons"], [])


class ProcessChunkFlow(unittest.TestCase):
    """mock API / ffprobe / hash,驗快取、續跑、第二次轉錄失敗、key 索引傳遞。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.chunk = str(Path(self.tmp) / "src_chunk_000.mp3")
        Path(self.chunk).write_bytes(b"fake")
        self._saved = (gt.media_duration, gt._file_sha256, gt.PROMPT_MODE, gt.COVERAGE_FALLBACK)
        gt.media_duration = lambda p: 600.0
        gt._file_sha256 = lambda p: "audio-1"
        gt.PROMPT_MODE, gt.COVERAGE_FALLBACK = "plain", True
        self.calls = []

    def tearDown(self):
        gt.media_duration, gt._file_sha256, gt.PROMPT_MODE, gt.COVERAGE_FALLBACK = self._saved
        shutil.rmtree(self.tmp, ignore_errors=True)

    def fake(self, plain_segs, prompted_segs=None, fail_prompted=False):
        def transcribe(path, keys, idx, ctx, use_prompt=None):
            self.calls.append("prompted" if use_prompt else "plain")
            if use_prompt and fail_prompted:
                gt.LAST_ERROR["msg"] = "HTTP 429"
                return None, idx + 2                       # 輪過兩把 key 後放棄
            return {"segments": prompted_segs if use_prompt else plain_segs, "duration": 600.0}, idx + 1
        return transcribe

    def run_chunk(self, transcribe, key_index=0):
        return gt.process_chunk(self.chunk, ["k1", "k2", "k3"], key_index, "context", 0, transcribe=transcribe)

    def test_clean_chunk_single_call(self):
        sel, idx, entry = self.run_chunk(self.fake(DENSE))
        self.assertEqual(self.calls, ["plain"])
        self.assertEqual((idx, entry["second_status"]), (1, "not_needed"))

    def test_suspicious_plain_gets_diagnostic_second_read(self):
        sel, idx, entry = self.run_chunk(self.fake(DROPPY, DENSE))
        self.assertEqual(self.calls, ["plain", "prompted"])
        self.assertEqual(sel["segments"], DROPPY)            # 不換版
        self.assertEqual(idx, 2)                             # key 索引沿用第二次呼叫後的值
        self.assertTrue(entry["review_ranges"])

    def test_second_read_failure_then_resume_retries_only_second(self):
        sel, idx, entry = self.run_chunk(self.fake(DROPPY, fail_prompted=True))
        self.assertEqual((entry["second_status"], entry["second_error"]), ("failed", "HTTP 429"))
        self.assertEqual(idx, 3)
        self.calls.clear()
        sel, idx, entry = self.run_chunk(self.fake(DROPPY, DENSE))
        self.assertEqual(self.calls, ["prompted"])           # 主轉錄來自快取
        self.assertEqual(entry["second_status"], "done")

    def test_completed_cache_makes_no_calls(self):
        self.run_chunk(self.fake(DROPPY, DENSE))
        self.calls.clear()
        self.run_chunk(self.fake(DROPPY, DENSE))
        self.assertEqual(self.calls, [])

    def test_cache_invalidated_by_new_audio_or_mode(self):
        self.run_chunk(self.fake(DENSE))
        gt._file_sha256 = lambda p: "audio-2"
        self.calls.clear()
        self.run_chunk(self.fake(DENSE))
        self.assertEqual(self.calls, ["plain"])
        gt.PROMPT_MODE = "prompted"
        self.calls.clear()
        self.run_chunk(self.fake(DENSE, DENSE))
        self.assertEqual(self.calls, ["prompted"])

    def test_old_or_corrupt_cache_is_ignored(self):
        cache = Path(self.chunk).with_suffix(".json")
        for content in ('{"segments": []}', "not json"):
            cache.write_text(content)
            self.calls.clear()
            self.run_chunk(self.fake(DENSE))
            self.assertEqual(self.calls, ["plain"])

    def test_fallback_disabled_marks_unresolved(self):
        gt.COVERAGE_FALLBACK = False
        _, _, entry = self.run_chunk(self.fake(DROPPY))
        self.assertEqual(self.calls, ["plain"])
        self.assertIn("second_read_disabled", entry["unresolved_reasons"])

    def test_disabling_second_read_ignores_cached_second(self):
        gt.PROMPT_MODE = "prompted"
        sel, _, entry = self.run_chunk(self.fake(PAUSE16, DROPPY))       # prompted 主轉錄 = DROPPY
        self.assertEqual(entry["selected"], "plain")                     # 有對照 → 換版
        gt.COVERAGE_FALLBACK = False
        self.calls.clear()
        sel, _, entry = self.run_chunk(self.fake(PAUSE16, DROPPY))
        self.assertEqual(self.calls, [])
        self.assertEqual((entry["selected"], entry["second_status"]), ("prompted", "disabled"))
        self.assertIn("second_read_disabled", entry["unresolved_reasons"])
        gt.COVERAGE_FALLBACK = True                                       # 重新開啟:快取的第二版仍在
        sel, _, entry = self.run_chunk(self.fake(PAUSE16, DROPPY))
        self.assertEqual(self.calls, [])
        self.assertEqual(entry["selected"], "plain")

    def test_primary_failure_returns_none(self):
        def boom(*a, **k):
            return None, 5
        self.assertEqual(self.run_chunk(boom), (None, 5, None))

    def test_write_segments_offsets_once_and_numbers_continuously(self):
        out = Path(self.tmp) / "o.srt"
        with open(out, "w", encoding="utf-8") as f:
            n = gt.write_segments(f, [{"start": 1, "end": 2, "text": "甲"}, {"start": 3, "end": 4, "text": " "}], 0, 1)
            n = gt.write_segments(f, [{"start": 1, "end": 2, "text": "乙"}], 600, n)
        t = out.read_text(encoding="utf-8")
        self.assertEqual(n, 3)
        self.assertIn("2\n00:10:01,000 --> 00:10:02,000\n乙", t)


BAD_TS = [{"start": 1, "end": 2, "text": "甲"}, {"start": None, "end": 3, "text": "乙"},
          {"start": "x", "text": "丙"}, {"start": 9, "end": 4, "text": "丁"},
          {"start": float("inf"), "end": 1, "text": "戊"}, {"start": 3, "end": 4, "text": "  "},
          {"start": True, "end": 5, "text": "己"}, {"start": " ", "end": 6, "text": "庚"},
          {"start": "7", "end": "8", "text": "辛"}, {"start": 8.0001, "end": 8.0004, "text": "壬"},
          {"start": 9, "end": 999, "text": "癸"}]


ORDER_TS = [{"start": 10, "end": 11, "text": "一"}, {"start": 2, "end": 3, "text": "二"},
            {"start": None, "end": None, "text": "三"}, {"start": 599.9999, "end": 600.1, "text": "四"},
            {"start": 595, "end": 600.4, "text": "五"}, {"start": 20, "end": 700, "text": "六"}]


class RepairTimes(unittest.TestCase):
    def test_terra_repro_cases(self):
        rows, adj = gt.repair_times(ORDER_TS[:3], 600.0)
        self.assertEqual([r[:2] for r in rows], [(10, 11), (11, 12), (12, 13)])      # 倒退與無效都緊接上一句
        self.assertEqual([a["reason"] for a in adj], [["out_of_order"], ["invalid"]])
        self.assertEqual(adj[0]["original"], [2, 3])
        self.assertTrue(gt.timing_unresolved(adj))

    def test_clamp_and_min_length_stay_inside_chunk(self):
        rows, adj = gt.repair_times([ORDER_TS[3]], 600.0)
        a, e, _ = rows[0]
        self.assertLessEqual(e, 600.0)
        self.assertGreaterEqual(e - a, 0.001 - 1e-9)
        self.assertEqual(adj[0]["original"], [599.9999, 600.1])
        self.assertIn("min_length", adj[0]["reason"])

    def test_minor_overshoot_recorded_not_flagged(self):
        rows, adj = gt.repair_times([ORDER_TS[4]], 600.0)
        self.assertEqual(adj[0]["reason"], ["clamp_end_minor"])
        self.assertFalse(gt.timing_unresolved(adj))
        rows, adj = gt.repair_times([ORDER_TS[5]], 600.0)                           # 超出 100s
        self.assertEqual(adj[0]["reason"], ["clamp_end"])
        self.assertTrue(gt.timing_unresolved(adj))

    def test_decide_reports_adjustments(self):
        _, entry = gt.decide("plain", {"segments": ORDER_TS[:3]}, None, "prompted", 600.0, 0, "not_needed")
        self.assertIn("timestamps_adjusted", entry["unresolved_reasons"])
        self.assertEqual(len(entry["timestamp_adjustments"]), 2)

    def test_chains_from_previous_cue_not_running_max(self):
        rows, adj = gt.repair_times([{"start": 10, "end": 20, "text": "一"}, {"start": 11, "end": 12, "text": "二"},
                                     {"start": None, "end": None, "text": "三"}], 600.0)
        self.assertEqual(rows[2][:2], (12.0, 13.0))

    def test_report_written_equals_srt_text(self):
        import io
        cases = ORDER_TS + BAD_TS + [{"start": 1, "end": 1.0001, "text": "極短"}]
        rows, adj = gt.repair_times(cases, 600.0)
        buf = io.StringIO()
        gt.write_segments(buf, cases, 0, 1, 600.0)
        cues = [b.split("\n")[1] for b in buf.getvalue().strip().split("\n\n")]
        kept = [i for i, sg in enumerate(cases) if (sg.get("text") or "").strip()]
        for x in adj:
            line = cues[kept.index(x["index"])]
            self.assertEqual(line, f"{gt.format_srt_time(x['written'][0])} --> {gt.format_srt_time(x['written'][1])}")
        for line in cues:
            a, e = line.split(" --> ")
            self.assertLess(a, e, line)                      # 沒有零長度 cue
        rows, adj = gt.repair_times([{"start": 1, "end": 1.0001, "text": "極短"}], 600.0)
        self.assertEqual((adj[0]["written"], adj[0]["reason"]), ([1.0, 1.001], ["min_length"]))

    def test_format_srt_time_rounds_to_ms(self):
        self.assertEqual(gt.format_srt_time(1.001), "00:00:01,001")
        self.assertEqual(gt.format_srt_time(3599.9996), "01:00:00,000")

    def test_clean_whisper_output_has_no_adjustments(self):
        self.assertEqual(gt.repair_times(DENSE, 600.0)[1], [])


class SafeTimes(unittest.TestCase):
    def test_bool_and_blank_rejected(self):
        for v in (True, False, " ", "", None, "nan", float("nan")):
            self.assertIsNone(gt._finite(v), v)
        self.assertEqual(gt._finite("7"), 7.0)

    def test_text_kept_times_monotonic(self):
        out = gt.safe_times(BAD_TS, 20.0)
        self.assertEqual([t for _, _, t in out], list("甲乙丙丁戊己庚辛壬癸"))
        self.assertEqual(out[7][:2], (7.0, 8.0))                     # 數字字串照用
        self.assertEqual(out[-1][1], 20.0)                           # 超出段長裁切
        self.assertNotEqual(gt.format_srt_time(out[8][0]), gt.format_srt_time(out[8][1]))  # 毫秒後非零長
        for a, e, _ in out:
            self.assertLess(a, e)
        starts = [a for a, _, _ in out]
        self.assertEqual(starts, sorted(starts))

    def test_write_segments_survives_bad_timestamps(self):
        import io
        buf = io.StringIO()
        self.assertEqual(gt.write_segments(buf, BAD_TS, 600, 1, 20.0), 11)
        self.assertNotIn("nan", buf.getvalue().lower())


@unittest.skipUnless(shutil.which("node"), "node not installed")
class Parity(unittest.TestCase):
    """web/studio.js 對同一組 fixture 要給出相同結論;並跑 Web 的非同步流程(mock API)。"""

    def node(self, body):
        src = (ROOT / "web/studio.js").read_text(encoding="utf-8")
        lib = src[src.index("const GROQ_PROMPT_MAX_BYTES"):src.index("async function callGroqWhisper")]
        f0 = src.index("function formatSrtTime(sec)")
        fmt = src[f0:src.index("\n}\n", f0) + 3]
        js = "const GROQ_CHUNK_RETRIES = 3; const sleep = () => Promise.resolve();\n" + fmt + lib + body
        r = subprocess.run(["node", "-e", js], capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)

    def test_coverage_matches_python(self):
        cases = {k: {"segments": s, "duration": d} for k, (s, d) in FIXTURES.items()}
        bad = json.dumps([{k: (None if isinstance(v, float) and v == float("inf") else v) for k, v in d.items()}
                          for d in BAD_TS], ensure_ascii=False)
        order = json.dumps(ORDER_TS, ensure_ascii=False)
        got = self.node(f"""
const BAD_TS = {bad}; BAD_TS[4].start = Infinity;
const cases = {json.dumps(cases, ensure_ascii=False)}; const out = {{}};
for (const [k, c] of Object.entries(cases)) {{
  const v = chunkCoverage(c.segments, c.duration);
  out[k] = {{reasons: v.reasons, covered: v.covered, gap: v.gapTotal, chars: v.textChars, iv: v.intervals}};
}}
out.diff = intervalDiff([[0,10]], [[2,3],[5,6]]);
out.safe = covSafeTimes(BAD_TS, 20).map(x => [x.start, x.end, x.text]);
out.badCov = chunkCoverage(BAD_TS, 20).invalidSegments;
const ORDER_TS = %s;
out.order = covRepairTimes(ORDER_TS, 600);
out.fmt = [1.001, 3599.9996, 0.0005, 12.345].map(formatSrtTime);
out.trunc = new TextEncoder().encode(buildGroqPrompt('zh', '中'.repeat(900))).length;
out.truncAuto = truncateUtf8('a' + '中'.repeat(400), 896).length;
console.log(JSON.stringify(out));""".replace("%s", order))
        for k, (s, d) in FIXTURES.items():
            c = gt.chunk_coverage(s, d)
            self.assertEqual(got[k]["reasons"], c["reasons"], k)
            self.assertAlmostEqual(got[k]["covered"], c["covered"], places=6, msg=k)
            self.assertAlmostEqual(got[k]["gap"], c["gap_total"], places=6, msg=k)
            self.assertEqual(got[k]["chars"], c["text_chars"], k)
            self.assertEqual(got[k]["iv"], c["intervals"], k)
        self.assertEqual(got["diff"], gt.interval_diff([[0, 10]], [[2, 3], [5, 6]]))
        self.assertEqual(len(got["safe"]), len(gt.safe_times(BAD_TS, 20.0)))
        for js_row, py_row in zip(got["safe"], gt.safe_times(BAD_TS, 20.0)):
            self.assertAlmostEqual(js_row[0], py_row[0], places=9)
            self.assertAlmostEqual(js_row[1], py_row[1], places=9)
            self.assertEqual(js_row[2], py_row[2])
        self.assertEqual(got["badCov"], gt.chunk_coverage(BAD_TS, 20.0)["invalid_segments"])
        self.assertEqual(got["fmt"], [gt.format_srt_time(x) for x in (1.001, 3599.9996, 0.0005, 12.345)])
        py_rows, py_adj = gt.repair_times(ORDER_TS, 600.0)
        self.assertEqual(got["order"]["adj"], py_adj)
        for j, (a, e, t) in zip(got["order"]["rows"], py_rows):
            self.assertAlmostEqual(j["start"], a, places=9)
            self.assertAlmostEqual(j["end"], e, places=9)
        self.assertLessEqual(got["trunc"], 896)
        self.assertEqual(got["truncAuto"], len(gt.truncate_prompt("a" + "中" * 400)))

    def test_web_flow(self):
        got = self.node(f"""
const DROPPY = {json.dumps(DROPPY, ensure_ascii=False)}, DENSE = {json.dumps(DENSE, ensure_ascii=False)};
let calls = [], failPrompted = 0;
async function callGroqWhisper(blob, key, ctx, fn, lang, opts) {{
  const prompted = !(opts && opts.noPrompt); calls.push(prompted ? 'prompted' : 'plain');
  if (prompted && failPrompted-- > 0) throw new Error('Groq API 429: rate');
  if (blob === 'bad4xx' && prompted) throw new Error('Groq API 400: bad');
  return {{ segments: blob === 'clean' ? DENSE : (prompted ? DENSE : DROPPY), duration: 600 }};
}}
(async () => {{
  const out = {{}};
  let r = await transcribeWithCoverage('clean', 'k', 'ctx', 'a', 'zh', 600, 0); out.clean = [calls, r.report.unresolved_reasons]; calls = [];
  r = await transcribeWithCoverage('x', 'k', 'ctx', 'a', 'zh', 600, 600);
  out.diag = [calls, r.result.segments.length, r.report.review_ranges.length, r.report.review_ranges[0].start]; calls = [];
  failPrompted = 2; r = await transcribeWithCoverage('x', 'k', 'ctx', 'a', 'zh', 600, 0);
  out.retry = [calls, r.report.second_status]; calls = [];
  r = await transcribeWithCoverage('bad4xx', 'k', 'ctx', 'a', 'zh', 600, 0);
  out.fail = [calls, r.report.second_status, r.report.unresolved_reasons.includes('second_read_failed'), r.result.segments.length]; calls = [];
  r = await transcribeWithCoverage('x', 'k', '', 'a', 'auto', null, 0);
  out.noPrompt = [calls, r.report.second_status];
  console.log(JSON.stringify(out));
}})();""")
        self.assertEqual(got["clean"], [["plain"], []])
        self.assertEqual(got["diag"][0], ["plain", "prompted"])
        self.assertEqual(got["diag"][1], len(DROPPY))                       # 不換版
        self.assertGreater(got["diag"][2], 0)
        self.assertGreaterEqual(got["diag"][3], 600)                        # offset 加上
        self.assertEqual(got["retry"], [["plain", "prompted", "prompted", "prompted"], "done"])  # 主轉錄只一次
        self.assertEqual(got["fail"], [["plain", "prompted"], "failed", True, len(DROPPY)])
        self.assertEqual(got["noPrompt"], [["plain"], "disabled"])


@unittest.skipUnless(shutil.which("node"), "node not installed")
class WebRunTranscribe(unittest.TestCase):
    """跑真正的 runTranscribe()(DOM 與 Groq 以 stub 取代):逐字稿與報告成組提交、空結果算失敗、
    中途例外不污染上一份稿、換稿清掉下游產物。"""

    def test_state_transitions(self):
        src = (ROOT / "web/studio.js").read_text(encoding="utf-8")
        lib = src[src.index("const GROQ_PROMPT_MAX_BYTES"):src.index("async function callGroqWhisper")]
        a = src.index("let transcribeReport = [];")
        state = src[a:src.index("function sleep(ms)", a)]
        r0 = src.index("async function runTranscribe()")
        run = src[r0:src.index("\n}\n", r0) + 3]
        js = """
let srtContent = '', rawCleaned = '', cleanedMd = '', enhancedMd = '', notesMd = '', imageNotesPngs = [];
const GROQ_CHUNK_RETRIES = 3, CHUNK_DURATION = 600; let GROQ_MAX_DIRECT_BYTES = 1e9;
async function fileToMp3Segments() { return { jobs: [{ blob: 'c1', timeOffset: 0, duration: 30, filename: 'a.mp3', bytes: 1 },
  { blob: 'c2', timeOffset: 30, duration: 30, filename: 'a.mp3', bytes: 1 }], duration: 60 }; }
const sleep = () => Promise.resolve();
const els = {}; const $ = id => (els[id] = els[id] || { value: '', disabled: false, textContent: '', files: [],
  classList: { add() {}, remove() {} }, children: [], appendChild(c) { this.children.push(c); } });
const document = { createElement: () => ({ addEventListener() {}, textContent: '' }) };
const downloadFile = () => {};
const log = []; const addProgressLine = (n, m) => log.push(m);
const showProgress = () => {}, setProgressBar = () => {}, showResult = () => {};
const formatSrtTime = t => String(t); const alert = m => log.push('ALERT ' + m);
let mode = 'ok';
async function callGroqWhisper(blob, key, ctx, fn, lang, opts) {
  if (mode === 'throw' || (mode === 'partial' && blob === 'c2')) throw new Error('Groq API 400: boom');
  if (mode === 'empty') return { segments: [], duration: 30 };
  return { segments: [{ start: 0, end: 30, text: mode === 'ok' ? '第一份稿' : '第二份稿' }], duration: 30 };
}
""" + lib + state + run + """
(async () => {
  const out = {};
  $('file-input').files = [{ size: 10, name: 'a.m4a' }]; $('groq-key').value = 'k';
  await runTranscribe(); cleanedMd = 'A 的校稿';
  out.a = [srtContent.includes('第一份稿'), transcribeReport.length, transcribeFailed, cleanedMd];
  mode = 'throw'; await runTranscribe();
  out.midFail = [srtContent.includes('第一份稿'), transcribeReport.length, cleanedMd, $('btn-paste-next').disabled,
                 $('prog-1-lines').children.length];
  mode = 'partial'; GROQ_MAX_DIRECT_BYTES = 0; $('prog-1-lines').children = [];
  await runTranscribe();
  out.partial = [srtContent.includes('第一份稿'), transcribeReport.length, cleanedMd, $('prog-1-lines').children.length];
  GROQ_MAX_DIRECT_BYTES = 1e9; $('prog-1-lines').children = [];
  mode = 'empty'; await runTranscribe();
  out.empty = [srtContent, transcribeReport.length, transcribeFailed, cleanedMd,
               transcribeReport[0].unresolved_reasons.includes('no_text'), $('prog-1-lines').children.length];
  console.log(JSON.stringify(out));
})();
"""
        r = subprocess.run(["node", "-e", js], capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        got = json.loads(r.stdout)
        self.assertEqual(got["a"], [True, 1, False, "A 的校稿"])
        # 例外(主轉錄第一段就失敗 → 本次無報告):A 整組保留、貼上鈕恢復、沒有診斷鈕
        self.assertEqual(got["midFail"], [True, 1, "A 的校稿", False, 0])
        # 第 2 段失敗:A 整組保留,第 1 段的本次報告以診斷鈕另外提供
        self.assertEqual(got["partial"], [True, 1, "A 的校稿", 1])
        # 空結果:失敗、A 的下游清掉、出現本次診斷下載鈕
        self.assertEqual(got["empty"], ["", 1, True, "", True, 1])


if __name__ == "__main__":
    unittest.main()
