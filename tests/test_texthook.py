import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import json
import types
import unittest

from meikipop.ocr.hit_scan import HitScanner
from meikipop.texthook import EngineText

LINE = {"engine": "siglus", "kind": "line", "text": "「ねぇ」", "screen": {"w": 1920, "h": 1080},
        "view": {"x": 420, "y": 211, "w": 960, "h": 540},
        "glyph_rects": [{"ch": c, "x": 369 + 38 * i, "y": 851, "w": 38, "h": 38} for i, c in enumerate("「ねぇ」")]}


class EngineTextTest(unittest.TestCase):
    def setUp(self):
        self.engine = EngineText(types.SimpleNamespace(running=True))
        self.engine._on_message(json.dumps(LINE))

    def test_lookup_at_the_character_under_the_pointer(self):
        point = (420 + (369 + 38 + 19) / 2, 211 + (851 + 19) / 2)  # middle of ね, in screen points
        frame = self.engine.frame_at(point)
        self.assertIsNotNone(frame)
        scanner = HitScanner(types.SimpleNamespace(running=True),
                             types.SimpleNamespace(get_mouse_pos=lambda: point),
                             types.SimpleNamespace(get_scan_geometry=lambda: (0, 0, 0, 0)))
        result = scanner.hit_scan(frame)
        self.assertEqual(str(result), "ねぇ」")
        self.assertEqual(result.sentence, "「ねぇ」")

    def test_no_engine_text_off_the_line_or_after_clear(self):
        self.assertIsNone(self.engine.frame_at((430, 230)))
        self.engine._on_message(json.dumps({"kind": "clear", "screen": LINE["screen"]}))
        self.assertFalse(self.engine.has_text())


if __name__ == '__main__':
    unittest.main()
