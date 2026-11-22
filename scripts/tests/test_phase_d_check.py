"""phase_d_check:子序列證明 + § R8.2 因果標記 WARNING(GitHub shuotao/study#1)。"""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import phase_d_check as d  # noqa: E402

BEFORE = "我們先看資料。這次的分享有兩個重點。\n\n第一個是成本。第二個是時程。\n"


class CausalWarning(unittest.TestCase):
    def test_inserted_causal_hook_is_flagged(self):
        after = BEFORE.replace("這次的分享", "會這樣拿出來討論的原因是：這次的分享")
        hits = d.causal_insertions(BEFORE, after)
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0][:2], (1, "原因是"))

    def test_non_causal_hooks_not_flagged(self):
        after = (BEFORE.replace("這次的分享", "這段要先交代的是，這次的分享")
                 .replace("第二個是", "接下來，第二個是"))
        self.assertEqual(d.causal_insertions(BEFORE, after), [])

    def test_causal_word_already_in_source_not_flagged(self):
        before = "因為預算不夠，所以延期。\n"
        after = "也就是說，因為預算不夠，所以延期。\n"
        self.assertEqual(d.causal_insertions(before, after), [])

    def test_inserted_suoyi_in_second_paragraph(self):
        after = BEFORE.replace("第二個是時程", "所以第二個是時程")
        hits = d.causal_insertions(BEFORE, after)
        self.assertEqual([(h[0], h[1]) for h in hits], [(2, "所以")])

    def test_warning_does_not_change_exit_code(self):
        with tempfile.TemporaryDirectory() as t:
            b, a = Path(t, "b.md"), Path(t, "a.md")
            b.write_text(BEFORE, encoding="utf-8")
            a.write_text(BEFORE.replace("第二個是", "因此第二個是"), encoding="utf-8")
            r = subprocess.run([sys.executable, str(ROOT / "scripts/phase_d_check.py"), str(a),
                                "--base", str(b), "--max-growth", "2"],
                               capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stdout)
            self.assertIn("WARNING", r.stdout)
            self.assertIn("因此", r.stdout)

    def test_rewrite_still_fails(self):
        with tempfile.TemporaryDirectory() as t:
            b, a = Path(t, "b.md"), Path(t, "a.md")
            b.write_text(BEFORE, encoding="utf-8")
            a.write_text(BEFORE.replace("成本", "預算"), encoding="utf-8")
            r = subprocess.run([sys.executable, str(ROOT / "scripts/phase_d_check.py"), str(a),
                                "--base", str(b)], capture_output=True, text=True)
            self.assertEqual(r.returncode, 1)


if __name__ == "__main__":
    unittest.main()
