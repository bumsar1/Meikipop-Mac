import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import json
import tempfile
import time
import unittest
from unittest.mock import patch

from meikipop.config.config import config
from meikipop.ocr.interface import BoundingBox, Paragraph
from meikipop.read_log import ReadLog


def para(text, x, y, vertical=False):
    return Paragraph(text, [], BoundingBox(x, y, 0.1, 0.05), vertical)


class ReadLogTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.log = ReadLog(self.tmp.name)
        for key, value in (('log_read_text', True), ('is_enabled', True)):
            p = patch.object(config, key, value)
            p.start()
            self.addCleanup(p.stop)

    def entries(self):
        path = os.path.join(self.tmp.name, time.strftime('%Y-%m-%d') + '.jsonl')
        if not os.path.exists(path):
            return []
        with open(path, encoding='utf-8') as f:
            return [json.loads(line) for line in f]

    def test_format_order_and_consecutive_dedup(self):
        frame = [para('二行目 ', 0.5, 0.6), para('一行目', 0.5, 0.3), para('  ', 0.5, 0.9)]
        self.log.record(frame, window_pid=4242)
        self.log.record(list(frame), window_pid=4242)  # same text again: skipped
        self.log.record([para('次の行', 0.5, 0.3)], window_pid=4242)
        self.log.record(frame, window_pid=4242)  # not consecutive: logged again
        e = self.entries()
        self.assertEqual([x['lines'] for x in e], [['一行目', '二行目'], ['次の行'], ['一行目', '二行目']])
        self.assertEqual(e[0]['pid'], 4242)
        self.assertIsInstance(e[0]['t'], float)
        path = os.path.join(self.tmp.name, time.strftime('%Y-%m-%d') + '.jsonl')
        self.assertIn('一行目', open(path, encoding='utf-8').read())  # not \\u-escaped

    def test_vertical_text_right_to_left(self):
        self.log.record([para('左', 0.2, 0.5, True), para('右', 0.8, 0.5, True)], window_pid=1)
        self.assertEqual(self.entries()[0]['lines'], ['右', '左'])

    def test_frontmost_pid_when_no_window(self):
        with patch('meikipop.read_log.frontmost_pid', return_value=99):
            self.log.record([para('テスト', 0.5, 0.5)], window_pid=None)
        self.assertEqual(self.entries()[0]['pid'], 99)

    def test_off_when_disabled_paused_or_failing(self):
        with patch.object(config, 'log_read_text', False):
            self.log.record([para('一', 0.5, 0.5)], 1)
        with patch.object(config, 'is_enabled', False):
            self.log.record([para('二', 0.5, 0.5)], 1)
        self.assertEqual(self.entries(), [])
        with patch('meikipop.read_log.os.makedirs', side_effect=OSError('disk full')):
            self.log.record([para('三', 0.5, 0.5)], 1)  # must not raise


if __name__ == '__main__':
    unittest.main()
