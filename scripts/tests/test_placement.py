#!/usr/bin/env python3
"""test_placement.py — 圖片放置監管三支模組的驗證測試(propose_anchors / placement_check /
placement_supervisor)。目標:證明反塌陷 DP 真的擋得住「連續投影片塌在同一段落」,
且不破壞既有保證(單調性、penalty=0 退化為舊行為的最優解)。

跑法:
    python3 scripts/tests/test_placement.py
或:
    python3 -m unittest scripts.tests.test_placement -v   (需在 scripts/ 有 __init__.py,本專案沒有,故用直接執行法)
"""
from __future__ import annotations

import random
import subprocess
import sys
import unittest
from collections import Counter
from itertools import product
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = SCRIPTS_DIR.parent
sys.path.insert(0, str(SCRIPTS_DIR))

from propose_anchors import solve_monotonic  # noqa: E402
from placement_check import anchor_runs, overstacked, distribution_report  # noqa: E402

NEG_INF = float("-inf")

SESSION_DIR = REPO_ROOT / "sessions" / "2026-06-27_公務人力發展學院福華國際文教會館-10"


# ---------------------------------------------------------------------------
# 共用工具:窮舉暴力解(獨立於待測 DP 的第二套實作),用來交叉驗證 solve_monotonic
# 是否真的求出「全域最優」而非某個滾動 max 維護錯誤下的次優解。
# ---------------------------------------------------------------------------

def brute_force_best(mat: list[list[float]], stack_penalty: float) -> float:
    """窮舉所有合法(行序非遞減)指派,回傳最大總分(含疊同一行的懲罰)。"""
    n, m = len(mat), len(mat[0])
    best = NEG_INF

    def rec(i: int, prev_j: int, val: float) -> None:
        nonlocal best
        if val == NEG_INF:
            return
        if i == n:
            best = max(best, val)
            return
        for j in range(prev_j, m):
            s = mat[i][j]
            if s == NEG_INF:
                continue
            penalty = stack_penalty if (i > 0 and j == prev_j) else 0.0
            rec(i + 1, j, val + s - penalty)

    rec(0, 0, 0.0)
    return best


def sequence_value(mat: list[list[float]], seq: list[int], stack_penalty: float) -> float:
    """依 solve_monotonic 回傳的 seq,依同一套規則重算總分,供交叉驗證。"""
    val = 0.0
    for i, j in enumerate(seq):
        s = mat[i][j]
        if s == NEG_INF:
            return NEG_INF
        if i > 0 and j == seq[i - 1]:
            val += s - stack_penalty
        else:
            val += s
    return val


def random_matrix(n: int, m: int, neg_prob: float = 0.0, seed: int | None = None) -> list[list[float]]:
    rng = random.Random(seed)
    mat = []
    for _ in range(n):
        row = []
        for _ in range(m):
            if rng.random() < neg_prob:
                row.append(NEG_INF)
            else:
                row.append(round(rng.uniform(0.0, 1.0), 3))
        mat.append(row)
    return mat


# ---------------------------------------------------------------------------
# 1. 反塌陷有效性:單一行對所有圖都是最高分時,penalty 拉高應能把疊圖攤開。
# ---------------------------------------------------------------------------

class TestAntiCollapse(unittest.TestCase):
    def _make_peaked_matrix(self, n: int, m: int, peak: int, peak_score=1.0, other_score=0.95):
        mat = []
        for _i in range(n):
            row = [other_score] * m
            row[peak] = peak_score
            mat.append(row)
        return mat

    def test_zero_penalty_collapses_to_peak_column(self):
        mat = self._make_peaked_matrix(n=6, m=6, peak=3)
        picks = solve_monotonic(mat, stack_penalty=0.0)
        worst = max(Counter(picks).values())
        # 沒有懲罰時,所有圖分數在同一欄最高 → 全部塌陷在該欄
        self.assertEqual(worst, len(mat), f"預期 0-penalty 全塌陷在同一欄,實際分佈={picks}")
        self.assertTrue(all(j == 3 for j in picks))

    def test_large_penalty_spreads_out(self):
        mat = self._make_peaked_matrix(n=6, m=6, peak=3)
        picks = solve_monotonic(mat, stack_penalty=1.0)  # 遠大於分數差 0.05
        worst = max(Counter(picks).values())
        self.assertLessEqual(worst, 2, f"大 penalty 後仍過度堆疊:picks={picks}")

    def test_worst_run_non_increasing_as_penalty_rises(self):
        mat = self._make_peaked_matrix(n=8, m=8, peak=4)
        penalties = [0.0, 0.02, 0.06, 0.1, 0.3, 1.0]
        worst_runs = []
        for p in penalties:
            picks = solve_monotonic(mat, stack_penalty=p)
            worst_runs.append(max(Counter(picks).values()))
        for a, b in zip(worst_runs, worst_runs[1:]):
            self.assertLessEqual(b, a,
                f"penalty 上升時最擠欄位張數應非遞增:{list(zip(penalties, worst_runs))}")
        self.assertLess(worst_runs[-1], worst_runs[0],
            f"最大 penalty 應明顯優於 0-penalty:{list(zip(penalties, worst_runs))}")

    def test_realistic_deck_collapse_scenario(self):
        """模擬 day2 第8場 12 張擠一行的實例:12 張圖對同一段落分數都最高。

        校準重點:懲罰要「贏過」堆疊分數與次佳欄位分數的差距,才會真的攤開
        (演算法定義:t 張疊同一欄的邊際成本是每多疊一張扣 stack_penalty;
        只要 penalty < peak-other 分數差,疊起來仍然划算,這是正確、非 bug 的行為)。
        故此處分數差刻意設小(0.05),用 penalty=0.5 遠大於差距來驗證攤開。
        """
        n = 12
        mat = self._make_peaked_matrix(n=n, m=n, peak=5, peak_score=0.5, other_score=0.45)
        picks_flat = solve_monotonic(mat, stack_penalty=0.0)
        picks_fixed = solve_monotonic(mat, stack_penalty=0.5)
        self.assertEqual(max(Counter(picks_flat).values()), n)
        self.assertLessEqual(max(Counter(picks_fixed).values()), 3)


# ---------------------------------------------------------------------------
# 2. 單調不變性:任意 penalty、任意(可行的)隨機矩陣,輸出序列必為非遞減。
# ---------------------------------------------------------------------------

class TestMonotonicity(unittest.TestCase):
    def test_monotonic_on_random_matrices(self):
        for seed in range(20):
            n = random.Random(seed).randint(2, 10)
            m = random.Random(seed + 1000).randint(2, 10)
            mat = random_matrix(n, m, neg_prob=0.1, seed=seed)
            # 確保每列至少一個有限值,否則整體不可行(此案例交給 edge-case 測試處理)
            for row in mat:
                if all(v == NEG_INF for v in row):
                    row[0] = 0.01
            for penalty in (0.0, 0.05, 0.2, 0.5):
                picks = solve_monotonic(mat, stack_penalty=penalty)
                self.assertEqual(len(picks), n)
                for a, b in zip(picks, picks[1:]):
                    self.assertLessEqual(a, b,
                        f"seed={seed} penalty={penalty} 非單調:{picks}\nmat={mat}")

    def test_monotonic_and_optimal_against_brute_force_small(self):
        """小矩陣(n,m<=4)窮舉驗證 DP 既單調、又真的是全域最優(不是滾動 max 記錯的次優解)。"""
        for seed in range(15):
            n = random.Random(seed).randint(1, 4)
            m = random.Random(seed + 500).randint(1, 4)
            mat = random_matrix(n, m, neg_prob=0.15, seed=seed + 9999)
            for row in mat:
                if all(v == NEG_INF for v in row):
                    row[0] = 0.01
            for penalty in (0.0, 0.1, 0.3):
                picks = solve_monotonic(mat, stack_penalty=penalty)
                for a, b in zip(picks, picks[1:]):
                    self.assertLessEqual(a, b)
                dp_value = sequence_value(mat, picks, penalty)
                brute_value = brute_force_best(mat, penalty)
                self.assertAlmostEqual(dp_value, brute_value, places=6,
                    msg=f"seed={seed} penalty={penalty} DP 非全域最優:"
                        f"dp={dp_value} brute={brute_value} mat={mat}")


# ---------------------------------------------------------------------------
# 3. penalty=0 等價舊行為(單純總分最大化,無反塌陷懲罰)。
# ---------------------------------------------------------------------------

class TestZeroPenaltyEquivalence(unittest.TestCase):
    def test_zero_penalty_matches_plain_max_score_dp(self):
        """獨立實作一支「無懲罰版」DP(只求 sum(mat[i][pick_i]) 最大、行序非遞減),
        比較其最優值與 solve_monotonic(mat, 0) 的結果值是否一致。"""
        def plain_max(mat):
            n, m = len(mat), len(mat[0])
            dp = [[NEG_INF] * m for _ in range(n)]
            for j in range(m):
                dp[0][j] = mat[0][j]
            for i in range(1, n):
                run = NEG_INF
                for j in range(m):
                    if dp[i - 1][j] > run:
                        run = dp[i - 1][j]
                    dp[i][j] = (mat[i][j] + run) if (mat[i][j] > NEG_INF and run > NEG_INF) else NEG_INF
            return max(dp[n - 1])

        for seed in range(10):
            n = random.Random(seed).randint(2, 7)
            m = random.Random(seed + 300).randint(2, 7)
            mat = random_matrix(n, m, neg_prob=0.1, seed=seed + 7777)
            for row in mat:
                if all(v == NEG_INF for v in row):
                    row[0] = 0.01
            picks = solve_monotonic(mat, stack_penalty=0.0)
            dp_value = sequence_value(mat, picks, 0.0)
            plain_value = plain_max(mat)
            self.assertAlmostEqual(dp_value, plain_value, places=6,
                msg=f"seed={seed} penalty=0 應等價無懲罰版最大總分:"
                    f"dp={dp_value} plain={plain_value}")


# ---------------------------------------------------------------------------
# 4. overstacked / anchor_runs 判定
# ---------------------------------------------------------------------------

class TestPlacementCheck(unittest.TestCase):
    def test_three_consecutive_images_is_overstacked(self):
        md = (
            "## 標題\n"
            "這是一段正文。\n"
            "![a](img1.png)\n"
            "![b](img2.png)\n"
            "![c](img3.png)\n"
            "後面又有一段正文。\n"
        )
        over = overstacked(md, max_per_anchor=2)
        self.assertEqual(len(over), 1)
        anchor_text, refs = over[0]
        self.assertEqual(anchor_text, "這是一段正文。")
        self.assertEqual(refs, ["img1.png", "img2.png", "img3.png"])

    def test_two_consecutive_images_not_overstacked(self):
        md = (
            "這是一段正文。\n"
            "![a](img1.png)\n"
            "![b](img2.png)\n"
            "後面又有一段正文。\n"
        )
        self.assertEqual(overstacked(md, max_per_anchor=2), [])
        runs = anchor_runs(md)
        self.assertEqual(len(runs), 1)
        self.assertEqual(len(runs[0][1]), 2)

    def test_images_separated_by_body_line_not_collapsed(self):
        md = (
            "這是一段正文。\n"
            "![a](img1.png)\n"
            "中間插了一句正文。\n"
            "![b](img2.png)\n"
            "![c](img3.png)\n"
        )
        # 三張圖被正文行隔成 (1 張) + (2 張) 兩個 anchor,任一組都未過門檻
        self.assertEqual(overstacked(md, max_per_anchor=2), [])
        runs = anchor_runs(md)
        self.assertEqual([len(r) for _a, r in runs], [1, 2])

    def test_http_images_and_cover_excluded(self):
        md = (
            "這是一段正文。\n"
            "![x](http://example.com/a.png)\n"
            "![y](http://example.com/b.png)\n"
            "![z](http://example.com/c.png)\n"
            "![cover](cover.jpg)\n"
            "另一段正文。\n"
        )
        # http 圖與 cover.jpg 都不被視為本地圖片行,不參與 anchor_runs 計數
        self.assertEqual(anchor_runs(md), [])
        self.assertEqual(overstacked(md, max_per_anchor=1), [])

    def test_blank_lines_between_images_still_same_run(self):
        # anchor_runs 只保留非空行,故空白行本身不會打斷 run;
        # 真正打斷的只有「非圖片的非空正文行」
        md = (
            "正文開頭。\n"
            "![a](img1.png)\n"
            "\n"
            "![b](img2.png)\n"
            "\n"
            "![c](img3.png)\n"
        )
        runs = anchor_runs(md)
        self.assertEqual(len(runs), 1)
        self.assertEqual(len(runs[0][1]), 3)
        self.assertEqual(len(overstacked(md, max_per_anchor=2)), 1)

    def test_distribution_report_shape(self):
        md = (
            "正文一。\n"
            "![a](img1.png)\n"
            "![b](img2.png)\n"
            "![c](img3.png)\n"
            "正文二。\n"
            "![d](img4.png)\n"
        )
        rep = distribution_report(md, max_per_anchor=2)
        self.assertFalse(rep["ok"])
        self.assertEqual(rep["total_imgs"], 4)
        self.assertEqual(rep["distinct_anchors"], 2)
        self.assertEqual(rep["worst_run"], 3)
        self.assertEqual(len(rep["overstacked"]), 1)
        self.assertEqual(rep["overstacked"][0]["count"], 3)


# ---------------------------------------------------------------------------
# 5. 端到端:真實 session 跑 placement_supervisor.py
# ---------------------------------------------------------------------------

@unittest.skipUnless(SESSION_DIR.exists() and (SESSION_DIR / "image_notes.json").exists(),
                      f"測試用 session 不存在:{SESSION_DIR}")
class TestEndToEndSupervisor(unittest.TestCase):
    def test_real_session_converges_and_report_shape(self):
        import json
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            out_path = Path(tmp) / "anchors_supervised.json"
            report_path = Path(tmp) / "supervisor_report.json"
            cmd = [
                sys.executable, str(SCRIPTS_DIR / "placement_supervisor.py"),
                "--session", str(SESSION_DIR),
                "--md", "pub_ch8_test.md",
                "--out", str(out_path),
                "--report", str(report_path),
            ]
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            self.assertIn(proc.returncode, (0, 1),
                f"非預期退出碼 {proc.returncode}\nstdout={proc.stdout}\nstderr={proc.stderr}")
            self.assertTrue(report_path.exists(), f"未產出報告\nstdout={proc.stdout}\nstderr={proc.stderr}")
            report = json.loads(report_path.read_text(encoding="utf-8"))

            dist = report["distribution"]
            self.assertLessEqual(dist["worst_run"], 2,
                f"端到端最擠 anchor 應 <= 2(反塌陷應生效),實際={dist['worst_run']}")
            # exit code 語意:converged 時應為 0,否則為 1
            self.assertEqual(proc.returncode, 0 if report["converged"] else 1)
            self.assertGreater(dist["placed"], 0)

            anchors = json.loads(out_path.read_text(encoding="utf-8"))
            self.assertGreater(len(anchors), 0)
            for a in anchors:
                self.assertIn("file", a)
                self.assertIn("after_line", a)
                self.assertIn("confidence", a)


# ---------------------------------------------------------------------------
# 6. 邊界案例:單張圖、全 NEG_INF 一列、全同分,不得崩潰、輸出需合法。
# ---------------------------------------------------------------------------

class TestEdgeCases(unittest.TestCase):
    def test_single_image(self):
        picks = solve_monotonic([[0.1, 0.5, 0.2]], stack_penalty=0.1)
        self.assertEqual(len(picks), 1)
        self.assertEqual(picks[0], 1)  # 應選分數最高的欄

    def test_all_scores_equal_no_crash_and_valid(self):
        mat = [[0.5] * 4 for _ in range(5)]
        picks = solve_monotonic(mat, stack_penalty=0.1)
        self.assertEqual(len(picks), 5)
        for j in picks:
            self.assertTrue(0 <= j < 4)
        for a, b in zip(picks, picks[1:]):
            self.assertLessEqual(a, b)

    def test_entire_row_neg_inf_does_not_crash(self):
        """某一列(圖)全部欄位皆不可插入(理論上不該發生於實際資料,
        但介面上是合法輸入,函式不得丟例外)。"""
        mat = [
            [NEG_INF, NEG_INF, NEG_INF],
            [0.1, 0.2, 0.3],
            [0.4, 0.1, 0.2],
        ]
        try:
            picks = solve_monotonic(mat, stack_penalty=0.1)
        except Exception as e:  # noqa: BLE001
            self.fail(f"entire-row-NEG_INF 輸入不應丟例外,實際:{e!r}")
        self.assertEqual(len(picks), 3)
        for j in picks:
            self.assertTrue(0 <= j < 3, f"index 越界:{picks}")

    def test_single_column_all_neg_inf_still_monotonic(self):
        """某一欄(對應 h1/h2 標題行)全不可插,其餘欄正常。"""
        mat = [
            [0.1, NEG_INF, 0.3],
            [0.2, NEG_INF, 0.4],
            [0.3, NEG_INF, 0.1],
        ]
        picks = solve_monotonic(mat, stack_penalty=0.1)
        self.assertEqual(len(picks), 3)
        self.assertTrue(all(j != 1 for j in picks), f"不應選中全 NEG_INF 的欄位:{picks}")
        for a, b in zip(picks, picks[1:]):
            self.assertLessEqual(a, b)

    def test_overstacked_empty_md(self):
        self.assertEqual(anchor_runs(""), [])
        self.assertEqual(overstacked(""), [])
        rep = distribution_report("")
        self.assertTrue(rep["ok"])
        self.assertEqual(rep["total_imgs"], 0)

    def test_overstacked_only_images_no_body_line(self):
        """圖片在檔案最開頭、之前沒有任何正文行(anchor 文字為空字串)。"""
        md = "![a](img1.png)\n![b](img2.png)\n![c](img3.png)\n"
        over = overstacked(md, max_per_anchor=2)
        self.assertEqual(len(over), 1)
        self.assertEqual(over[0][0], "")
        self.assertEqual(len(over[0][1]), 3)


if __name__ == "__main__":
    unittest.main(verbosity=2)
