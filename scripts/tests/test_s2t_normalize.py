"""s2t_normalize 只修「簡體漂移」,不得改動正體原文(2026-11-08 審查:整檔 s2tw 會把「干預」改成「幹預」)。"""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import s2t_normalize as n  # noqa: E402


class S2T(unittest.TestCase):
    def test_traditional_text_untouched(self):
        for t in ("干預", "干擾", "後台", "了解", "台灣", "只有一隻", "頭髮", "發展", "皇后", "公里", "制度",
                  "這個面板", "系統", "裡面", "乾淨"):
            self.assertEqual(n.normalize(t), t, t)

    def test_drift_fixed_with_phrase_dictionary(self):
        for src, want in (("干预", "干預"), ("这个面板", "這個面板"), ("头发", "頭髮"), ("系统", "系統"),
                          ("这个数字", "這個數字")):
            self.assertEqual(n.normalize(src), want, src)

    def test_mixed_line_only_changes_simplified_only_positions(self):
        self.assertEqual(n.normalize("这个干預有效"), "這個干預有效")

    def test_dual_use_chars_never_guessed(self):
        # 兩可字本身也是正體字 → 永不自動改(交 Phase B),即使同一行有漂移
        self.assertEqual(n.normalize("后台"), "后台")
        self.assertEqual(n.normalize("数据中心"), "數据中心")
        self.assertEqual(n.normalize("这个头发干"), "這個頭髮干")   # 不猜「乾/幹」
        self.assertEqual(n.normalize("这里面"), "這里面")

    def test_invariant_only_non_traditional_chars_change(self):
        import random
        rnd = random.Random(7)
        pool = list("干預後台了解頭髮發展系統這個面板數據中心皇后公里制度乾淨")
        for _ in range(300):
            t = "".join(rnd.choice(pool) for _ in range(rnd.randint(1, 12))) + rnd.choice(["这", "头", "统", ""])
            out = n.normalize(t)
            for c, o in zip(t, out):
                if c != o:
                    self.assertIn(c, n.SIMPLIFIED_ONLY, (t, out))

    def test_simplified_only_set_shape(self):
        for c in "预这头发统扰":
            self.assertIn(c, n.SIMPLIFIED_ONLY)
        for c in "干后台只了面制系里":
            self.assertNotIn(c, n.SIMPLIFIED_ONLY)

    def test_srt_timeline_and_line_count_unchanged(self):
        srt = "1\n00:00:01,000 --> 00:00:02,000\n这个干預\n\n2\n00:00:03,000 --> 00:00:04,000\n後台管理\n"
        out = n.normalize(srt)
        self.assertEqual(out.split("\n")[1], "00:00:01,000 --> 00:00:02,000")
        self.assertEqual(len(out.split("\n")), len(srt.split("\n")))
        self.assertIn("這個干預", out)
        self.assertIn("後台管理", out)

    def test_cli_refuses_transcript_srt(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "transcript.srt"
            p.write_text("1\n00:00:01,000 --> 00:00:02,000\n这个\n", encoding="utf-8")
            subprocess.run([sys.executable, str(ROOT / "scripts/s2t_normalize.py"), str(p), "--in-place"],
                           capture_output=True, text=True)
            self.assertIn("这个", p.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
