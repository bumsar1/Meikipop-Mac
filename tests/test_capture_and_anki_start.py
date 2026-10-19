import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import io
import unittest
from unittest.mock import patch, MagicMock

import requests
from PIL import Image

from meikipop.mining import Miner, MiningError
from meikipop.screenshot.window_capture import WindowFrame


def cgimage(width, height, rgb):
    """A real CGImage in the same layout CGWindowListCreateImage returns (BGRA, premultiplied first)."""
    import Quartz
    space = Quartz.CGColorSpaceCreateDeviceRGB()
    ctx = Quartz.CGBitmapContextCreate(None, width, height, 8, 0, space,
                                       Quartz.kCGImageAlphaPremultipliedFirst | Quartz.kCGBitmapByteOrder32Little)
    Quartz.CGContextSetRGBFillColor(ctx, rgb[0] / 255, rgb[1] / 255, rgb[2] / 255, 1)
    Quartz.CGContextFillRect(ctx, Quartz.CGRectMake(0, 0, width, height))
    return Quartz.CGBitmapContextCreateImage(ctx)


class WindowFrames(unittest.TestCase):
    def test_pixels_keep_their_colours(self):
        frame = WindowFrame(cgimage(40, 20, (200, 30, 90)), 5)
        img = frame.pil()
        self.assertEqual(img.size, (40, 20))
        r, g, b = img.getpixel((10, 10))
        self.assertTrue(abs(r - 200) <= 2 and abs(g - 30) <= 2 and abs(b - 90) <= 2, (r, g, b))

    def test_card_image_is_small_webp(self):
        frame = WindowFrame(cgimage(3600, 2260, (40, 120, 200)), 5)
        data, ext = frame.card_image()
        self.assertEqual(ext, 'webp')
        img = Image.open(io.BytesIO(data))
        self.assertEqual(img.format, 'WEBP')
        self.assertLessEqual(max(img.size), 1600)
        self.assertEqual(img.size, (1600, 1004))  # aspect ratio kept

    def test_each_capture_has_its_own_identity(self):
        a, b = WindowFrame(cgimage(4, 4, (0, 0, 0)), 9), WindowFrame(cgimage(4, 4, (0, 0, 0)), 9)
        self.assertNotEqual(a.digest, b.digest)


class FollowedWindowScans(unittest.TestCase):
    def manager(self):
        from meikipop.screenshot import screenmanager
        sm = screenmanager.ScreenManager.__new__(screenmanager.ScreenManager)
        sm.follow_window, sm.game_pid, sm.capture_window_id, sm.capture_window_pid = True, None, 3, 4
        sm.monitor = {"top": 0, "left": 0, "width": 40, "height": 20}
        sm._follow_capture_window = lambda: None
        return screenmanager, sm

    def test_reads_the_window_itself_not_the_screen(self):
        screenmanager, sm = self.manager()
        with patch.object(screenmanager, 'capture_window', return_value=WindowFrame(cgimage(40, 20, (1, 2, 3)), 3)), \
             patch.object(screenmanager.mss, 'mss') as screen:
            img, content = sm.take_screenshot()
        screen.assert_not_called()
        self.assertEqual(img.size, (40, 20))
        self.assertTrue(content)

    def test_hidden_window_is_not_read(self):
        screenmanager, sm = self.manager()
        with patch.object(screenmanager, 'capture_window', side_effect=RuntimeError('on another desktop')), \
             patch.object(screenmanager.mss, 'mss') as screen:
            self.assertEqual(sm.take_screenshot(), (None, None))
        screen.assert_not_called()
        self.assertIn('another desktop', sm.window_error)


class HitScanWithoutArea(unittest.TestCase):
    def test_no_division_by_zero_before_the_game_window_exists(self):
        from meikipop.ocr.hit_scan import HitScanner
        from meikipop.ocr.interface import BoundingBox, Paragraph
        hs = HitScanner.__new__(HitScanner)
        hs.input_loop = MagicMock()
        hs.input_loop.get_mouse_pos.return_value = (10, 10)
        hs.screen_manager = MagicMock()
        hs.screen_manager.get_scan_geometry.return_value = (0, 0, 0, 0)
        self.assertIsNone(hs.hit_scan([Paragraph('テスト', [], BoundingBox(0.5, 0.5, 1, 1), False)]))


class AnkiStart(unittest.TestCase):
    def miner(self, answers):
        m = Miner.__new__(Miner)
        calls = iter(answers)

        def anki(action, **params):
            outcome = next(calls)
            if outcome == 'down':
                try:
                    raise requests.ConnectionError('refused')
                except requests.ConnectionError as e:
                    raise MiningError('Cannot connect.') from e
            return 6
        m.anki = anki
        return m

    def test_running_anki_is_left_alone(self):
        with patch('subprocess.run') as run:
            self.miner(['up']).ensure_anki()
        run.assert_not_called()

    def test_closed_anki_is_started_in_the_background(self):
        messages = []
        with patch('subprocess.run', return_value=MagicMock(returncode=0)) as run, patch('meikipop.mining.time.sleep'):
            self.miner(['down', 'down', 'up']).ensure_anki(messages.append)
        self.assertEqual(run.call_args[0][0], ['/usr/bin/open', '-g', '-b', 'net.ankiweb.dtop'])
        self.assertEqual(messages, ['Anki was closed. Starting Anki…', 'Anki started. Adding the card…'])

    def test_gives_up_with_a_clear_message(self):
        m = self.miner(['down'] + ['down'] * 100)
        m.ANKI_START_TIMEOUT = 0
        with patch('subprocess.run', return_value=MagicMock(returncode=0)):
            with self.assertRaisesRegex(MiningError, 'AnkiConnect did not answer'):
                m.ensure_anki()

    def test_other_anki_errors_are_not_hidden(self):
        m = Miner.__new__(Miner)
        m.anki = MagicMock(side_effect=MiningError('Anki: collection is not available'))
        with patch('subprocess.run') as run, self.assertRaisesRegex(MiningError, 'collection'):
            m.ensure_anki()
        run.assert_not_called()


if __name__ == '__main__':
    unittest.main()
