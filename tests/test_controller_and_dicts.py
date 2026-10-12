import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import json
import tempfile
import unittest
import zipfile
from collections import defaultdict
from unittest.mock import patch

from meikipop.controller import tokenize, neighbour, ControllerNavigator
from meikipop.ocr.interface import BoundingBox, Word, Paragraph
from meikipop.dictionary import user_dicts


def line(text, top, vertical=False):
    """One character per Word, 0.05 wide, laid out like meikiocr output."""
    words = []
    for i, ch in enumerate(text):
        if vertical:
            words.append(Word(ch, '', BoundingBox(top, 0.1 + i * 0.05 + 0.025, 0.05, 0.05)))
        else:
            words.append(Word(ch, '', BoundingBox(0.1 + i * 0.05 + 0.025, top, 0.05, 0.05)))
    n = len(text) * 0.05
    box = BoundingBox(top, 0.1 + n / 2, 0.05, n) if vertical else BoundingBox(0.1 + n / 2, top, n, 0.05)
    return Paragraph(text, words, box, vertical)


KNOWN = {'青空': 2, '見える': 3, 'が': 1, '今日': 2, 'は': 1, '晴れ': 2}


def word_length(text):
    return max((n for w, n in KNOWN.items() if text.startswith(w)), default=1)


class Tokenizing(unittest.TestCase):
    def test_words_and_punctuation(self):
        tokens = tokenize([line('青空が見える。', 0.5)], word_length)
        self.assertEqual([('青空が見える。'[t.start:t.start + t.length]) for t in tokens], ['青空', 'が', '見える'])
        self.assertAlmostEqual(tokens[0].rect[0], 0.1)
        self.assertAlmostEqual(tokens[0].rect[2], 0.2)

    def test_reading_order_top_to_bottom(self):
        tokens = tokenize([line('青空が', 0.6), line('今日は', 0.3)], word_length)
        self.assertEqual(tokens[0].para, 1)  # upper line first

    def test_vertical_columns_right_to_left(self):
        tokens = tokenize([line('青空', 0.3, True), line('今日', 0.7, True)], word_length)
        self.assertEqual(tokens[0].para, 1)

    def test_up_down_keeps_column(self):
        paras = [line('今日は晴れ', 0.3), line('青空が見える', 0.5)]
        tokens = tokenize(paras, word_length)
        texts = [paras[t.para].full_text[t.start:t.start + t.length] for t in tokens]
        start = texts.index('晴れ')
        below = neighbour(tokens, start, 1, False)
        self.assertEqual(texts[below], '見える')
        self.assertEqual(neighbour(tokens, below, -1, False), start)
        self.assertEqual(neighbour(tokens, start, -1, False), start)  # nothing above


class Navigator(unittest.TestCase):
    def test_waits_for_fresh_ocr_and_moves(self):
        nav = ControllerNavigator(lookup=None)
        nav.word_length = word_length
        old = [line('今日は', 0.3)]
        nav.begin(old)
        self.assertFalse(nav.offer(old))  # stale result from before the button press
        self.assertIsNone(nav.mining_text())
        fresh = [line('青空が見える', 0.5)]
        self.assertTrue(nav.offer(fresh))
        self.assertEqual(str(nav.mining_text()), '青空が見える')
        self.assertTrue(nav.move(1, 0))
        text = nav.mining_text()
        self.assertEqual((str(text), text.offset, text.sentence), ('が見える', 2, '青空が見える'))
        nav.move(5, 0)
        self.assertEqual(str(nav.mining_text()), '見える')  # clamped at the last word
        self.assertFalse(nav.move(1, 0))
        nav.end()
        self.assertIsNone(nav.mining_text())


def yomitan_zip(path, title, rows):
    with zipfile.ZipFile(path, 'w') as zf:
        zf.writestr('index.json', json.dumps({'title': title, 'format': 3, 'revision': '1'}))
        zf.writestr('term_bank_1.json', json.dumps(rows, ensure_ascii=False))


class UserDictionaries(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        patcher = patch.object(user_dicts, 'USER_DICT_DIR', os.path.join(self.tmp.name, 'user_dicts'))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.tmp.cleanup)

    def test_import_merge_remove(self):
        z = os.path.join(self.tmp.name, 'mine.zip')
        yomitan_zip(z, 'Mit Ordbog', [['青空', 'あおぞら', '', '', 0, ['blå himmel'], 7, '']])
        self.assertEqual(user_dicts.import_zip(z), 'Mit Ordbog')
        with self.assertRaisesRegex(ValueError, 'already installed'):
            user_dicts.import_zip(z)
        [(path, title, count)] = user_dicts.list_user_dicts()
        self.assertEqual((title, count), ('Mit Ordbog', 1))

        class D:
            entries = {7: [{'glosses': ['blue sky'], 'pos': [], 'tags': []}]}
            lookup_map = defaultdict(list, {'青空': [('青空', 'あおぞら', 100, 7)]})
        d = D()
        user_dicts.merge_into(d)
        refs = d.lookup_map['青空']
        self.assertEqual(len(refs), 2)
        new_id = refs[1][3]
        self.assertGreaterEqual(new_id, user_dicts.USER_ID_BASE)
        self.assertEqual(d.entries[new_id][0]['glosses'], ['blå himmel'])
        self.assertEqual(d.entries[new_id][0]['dict'], 'Mit Ordbog')
        self.assertIn('あおぞら', d.lookup_map)  # kana path added too

        user_dicts.remove(path)
        self.assertEqual(user_dicts.list_user_dicts(), [])

    def test_rejects_non_term_dictionary(self):
        z = os.path.join(self.tmp.name, 'freq.zip')
        with zipfile.ZipFile(z, 'w') as zf:
            zf.writestr('index.json', json.dumps({'title': 'Freq'}))
            zf.writestr('term_meta_bank_1.json', '[]')
        with self.assertRaisesRegex(ValueError, 'no word entries'):
            user_dicts.import_zip(z)


class ShorterMatches(unittest.TestCase):
    def lookup(self):
        from meikipop.dictionary.lookup import Lookup
        from meikipop.dictionary.deconjugator import Form
        lk = Lookup.__new__(Lookup)

        class D:
            entries = {1: [{'glosses': ['hometown'], 'pos': [], 'tags': []}],
                       2: [{'glosses': ['ground'], 'pos': [], 'tags': []}]}
        lk.dictionary = D()
        raw = [(('地元', 'じもと', 100, 1), Form(text='地元'), 2), (('地', 'ち', 100, 2), Form(text='地'), 1)]
        return lk, raw

    def test_hidden_by_default_and_shown_when_enabled(self):
        from meikipop.config.config import config
        lk, raw = self.lookup()
        with patch.object(config, 'show_shorter_matches', False):
            self.assertEqual([e.written_form for e in lk._format_and_sort(raw, '地元')], ['地元'])
        with patch.object(config, 'show_shorter_matches', True):
            self.assertEqual([e.written_form for e in lk._format_and_sort(raw, '地元')], ['地元', '地'])


class FollowWindow(unittest.TestCase):
    def test_scan_area_tracks_window_and_keeps_last_when_hidden(self):
        from meikipop.screenshot import screenmanager
        sm = screenmanager.ScreenManager.__new__(screenmanager.ScreenManager)
        sm.capture_window_id, sm.monitor, sm.follow_window = 42, None, True
        with patch.object(screenmanager, 'window_bounds', return_value=(100, 50, 800, 600)):
            sm._follow_capture_window()
        self.assertEqual(sm.get_scan_geometry(), (100, 50, 800, 600))
        with patch.object(screenmanager, 'window_bounds', return_value=(300, 80, 800, 600)):
            sm._follow_capture_window()
        self.assertEqual(sm.get_scan_geometry(), (300, 80, 800, 600))
        with patch.object(screenmanager, 'window_bounds', return_value=None):  # minimized
            sm._follow_capture_window()
        self.assertEqual(sm.get_scan_geometry(), (300, 80, 800, 600))


class FakeButton:
    def __init__(self, down=False): self.down = down
    def isPressed(self): return self.down


class FakeAxis:
    def __init__(self): self.v = 0.0
    def value(self): return self.v


class FakeStick:
    def __init__(self): self.x, self.y = FakeAxis(), FakeAxis()
    def xAxis(self): return self.x
    def yAxis(self): return self.y


class FakePad:
    def __init__(self):
        self.buttons = {n: FakeButton() for n in ('buttonA', 'buttonB', 'buttonX', 'buttonY', 'leftShoulder')}
        dirs = {d: FakeButton() for d in ('left', 'right', 'up', 'down')}
        self._dpad = type('D', (), {d: (lambda self, b=b: b) for d, b in dirs.items()})()
        self.left_stick, self.right_stick = FakeStick(), FakeStick()
    def leftThumbstick(self): return self.left_stick
    def rightThumbstick(self): return self.right_stick
    def __getattr__(self, name):
        if name in self.__dict__.get('buttons', {}):
            return lambda: self.buttons[name]
        raise AttributeError(name)
    def dpad(self): return self._dpad


class VisualNovelMode(unittest.TestCase):
    def setUp(self):
        from meikipop import controller as c
        for name, value in (('can_post_events', True), ('pointer_position', (500.0, 400.0))):
            patcher = patch.object(c, name, return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = patch.object(c, 'clamp_to_displays', side_effect=lambda x, y: (x, y))
        patcher.start()
        self.addCleanup(patcher.stop)

    def controller(self):
        from PyQt6.QtWidgets import QApplication
        QApplication.instance() or QApplication([])
        from meikipop import controller as c
        from unittest.mock import MagicMock
        sm = MagicMock()
        sm.get_scan_geometry.return_value = (100, 200, 400, 100)
        ctl = c.ControllerInput.__new__(c.ControllerInput)
        c.QObject.__init__(ctl)
        ctl.shared_state, ctl.screen_manager, ctl.hit_scanner, ctl.popup = MagicMock(), sm, MagicMock(), MagicMock()
        ctl.navigator = ControllerNavigator(lookup=None)
        ctl.highlight = MagicMock()
        ctl._prev, ctl._repeat, ctl._toggled_on, ctl._game_app, ctl._shown_token = {}, {}, False, None, None
        pad = FakePad()
        ctl.gamepad = MagicMock()
        ctl.gamepad.pad.return_value = (None, pad)
        return c, ctl, pad

    def test_x_clicks_scan_area_centre_only_in_vn_mode(self):
        from meikipop.config.config import config
        from PyQt6.QtWidgets import QApplication
        c, ctl, pad = self.controller()
        with patch.object(c, 'click_at', return_value=True) as click, \
             patch.object(config, 'vn_mode', True), patch.object(config, 'controller_enabled', True):
            pad.buttons['buttonX'].down = True
            ctl._poll()
            QApplication.processEvents()
            click.assert_called_once_with(300, 250)
            ctl._poll()  # still held: no second click
            QApplication.processEvents()
            self.assertEqual(click.call_count, 1)
        with patch.object(c, 'click_at') as click, \
             patch.object(config, 'vn_mode', False), patch.object(config, 'controller_enabled', True):
            pad.buttons['buttonX'].down = False
            ctl._poll()
            pad.buttons['buttonX'].down = True
            ctl._poll()
            QApplication.processEvents()
            click.assert_not_called()


    def test_x_while_looking_up_clicks_the_selected_word(self):
        from meikipop.config.config import config
        from PyQt6.QtWidgets import QApplication
        c, ctl, pad = self.controller()
        ctl.navigator.word_length = word_length
        ctl.navigator.begin(None)
        ctl.navigator.offer([line('今日は', 0.3), line('青空が', 0.6)])  # two choices
        ctl.navigator.move(0, 1)  # down to the second choice
        with patch.object(c, 'click_at', return_value=True) as click, patch.object(c.QTimer, 'singleShot', lambda ms, f: f()), \
             patch.object(config, 'vn_mode', True), patch.object(config, 'controller_enabled', True), \
             patch.object(config, 'controller_block_game_input', False):
            pad.buttons['leftShoulder'].down = True
            pad.buttons['buttonX'].down = True
            ctl._poll()
        x, y = click.call_args[0]
        self.assertAlmostEqual(x, 100 + 0.15 * 400)  # centre of 青空 (0.1–0.2 of the width)
        self.assertAlmostEqual(y, 200 + 0.6 * 100)


    def test_stick_moves_pointer_and_a_b_click_there(self):
        from meikipop.config.config import config
        c, ctl, pad = self.controller()
        with patch.object(c, 'move_pointer') as move, patch.object(c, 'click_at') as click, patch.object(c, 'scroll') as wheel, \
             patch.object(config, 'vn_mode', True), patch.object(config, 'controller_enabled', True):
            ctl._poll()  # establishes timing
            pad.left_stick.x.v, pad.left_stick.y.v = 1.0, 1.0  # full tilt up-right
            ctl._last_poll -= 0.02
            ctl._poll()
            x, y = move.call_args[0]
            self.assertGreater(x, 500)
            self.assertLess(y, 400)  # up on the stick is up on screen
            pad.left_stick.x.v = pad.left_stick.y.v = 0.0
            pad.buttons['buttonA'].down = True
            ctl._poll()
            click.assert_called_once_with(500.0, 400.0, right=False, restore=False)
            pad.buttons['buttonA'].down = False
            pad.buttons['buttonB'].down = True
            ctl._poll()
            self.assertEqual(click.call_args.kwargs['right'], True)
            pad.right_stick.y.v = -1.0
            ctl._poll()
            wheel.assert_called_once_with(-1)


if __name__ == '__main__':
    unittest.main()
