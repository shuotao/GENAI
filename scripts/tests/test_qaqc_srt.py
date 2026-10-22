"""R1.2 exemptions and the short-reply rule (prompts/qaqc_core_rules.md § R1), CLI side.
The Web mirror (web/studio.js isGarbled) was checked for parity on 1,966 real cues (0 disagreements, 2026-10-22)."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "SRT"))
sys.path.insert(0, str(ROOT))
from qaqc_srt import is_garbled, phase_a_clean  # noqa: E402


class R12(unittest.TestCase):
    def test_speech_is_kept(self):
        for s in ("domain knowledge", "Writing is rewriting", "Yes, of course", "我用 Google 的 Gemini Flash", "對", "好"):
            self.assertFalse(is_garbled(s), s)

    def test_garble_is_dropped(self):
        for s in ("", "這個 ┌┐└┘├┤ 符號", "Привет мир", "@@@ ### $$$ %%% ^^^ &&&",
                  "Thank you for watching and please subscribe to the channel"):
            self.assertTrue(is_garbled(s), s)

    def test_short_replies_survive_phase_a(self):
        blocks = [{"timecode": f"00:00:0{i},000 --> 00:00:0{i},900", "text": t} for i, t in enumerate(["對", "好", "主題是,好"])]
        out, st = phase_a_clean(blocks, {}, [], ["主題是,"])
        self.assertEqual([b["text"] for b in out], ["對", "好"])     # wrapper remainder < 3 is still dropped


if __name__ == "__main__":
    unittest.main()
