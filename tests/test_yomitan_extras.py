import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import unittest
from unittest.mock import patch

from meikipop.config.config import config
from meikipop.dictionary.lookup import DictionaryEntry
from meikipop.yomitan_extras import YomitanExtras, parse_term_entries

# Trimmed from a real /termEntries answer for 書かれた
PAYLOAD = {'dictionaryEntries': [
    {'headwords': [{'term': '書く', 'reading': 'かく'}],
     'inflectionRuleChainCandidates': [
         {'source': 'algorithm', 'inflectionRules': [{'name': 'passive', 'description': '1. Indicates an action received.'},
                                                     {'name': '-た', 'description': '1. Past.'}]},
         {'source': 'algorithm', 'inflectionRules': [{'name': 'passive', 'description': '1. Indicates an action received.'},
                                                     {'name': '-た', 'description': '1. Past.'}]}],
     'frequencies': [{'headwordIndex': 0, 'dictionary': 'JPDBv2㋕', 'frequency': 263, 'displayValue': '263'},
                     {'headwordIndex': 0, 'dictionary': 'BCCWJ', 'frequency': 148, 'displayValue': None},
                     {'headwordIndex': 0, 'dictionary': 'Narou', 'frequency': 426, 'displayValue': None},
                     {'headwordIndex': 0, 'dictionary': 'Narou', 'frequency': 8929, 'displayValue': None}]},
    {'headwords': [{'term': 'かく', 'reading': 'かく'}],
     'inflectionRuleChainCandidates': [{'source': 'algorithm', 'inflectionRules': []}], 'frequencies': []},
]}


def entry(written, reading):
    return DictionaryEntry(id=1, written_form=written, reading=reading, senses=[], freq=1, deconjugation_process=())


class Parsing(unittest.TestCase):
    def test_frequencies_and_inflections_per_headword(self):
        parsed = parse_term_entries(PAYLOAD)
        kaku = parsed[('書く', 'かく')]
        self.assertEqual(kaku['frequencies'], [('JPDBv2㋕', '263'), ('BCCWJ', '148'), ('Narou', '426, 8929')])
        self.assertEqual(kaku['inflections'], [[('passive', '1. Indicates an action received.'), ('-た', '1. Past.')]])
        self.assertEqual(parsed[('かく', 'かく')], {'frequencies': [], 'inflections': []})

    def test_empty_or_odd_answers(self):
        self.assertEqual(parse_term_entries({}), {})
        self.assertEqual(parse_term_entries(None), {})


class Attaching(unittest.TestCase):
    def setUp(self):
        for key in ('show_frequency_lists', 'show_inflections'):
            p = patch.object(config, key, True)
            p.start()
            self.addCleanup(p.stop)

    def test_matches_by_word_and_reading(self):
        extras = YomitanExtras()
        kaku, kana = entry('書く', 'かく'), entry('かく', '')
        with patch.object(extras, '_session_post', return_value=PAYLOAD) as post:
            extras.attach([kaku, kana], '書かれた文字')
            extras.attach([entry('書く', 'かく')], '書かれた文字')  # second time from the cache
        self.assertEqual(post.call_count, 1)
        self.assertEqual(kaku.yomitan_frequencies[0], ('JPDBv2㋕', '263'))
        self.assertEqual([n for n, _ in kaku.yomitan_inflections[0]], ['passive', '-た'])
        self.assertEqual(kana.yomitan_frequencies, [])  # kana-only entries match reading == word

    def test_yomitan_down_is_skipped_for_a_while(self):
        extras = YomitanExtras()
        with patch.object(extras, '_session_post', side_effect=ConnectionError('refused')) as post:
            first = entry('書く', 'かく')
            extras.attach([first], 'a')
            extras.attach([entry('書く', 'かく')], 'b')  # no second wait for a dead server
        self.assertEqual(post.call_count, 1)
        self.assertFalse(hasattr(first, 'yomitan_frequencies'))

    def test_nothing_fetched_when_both_settings_are_off(self):
        extras = YomitanExtras()
        with patch.object(config, 'show_frequency_lists', False), patch.object(config, 'show_inflections', False), \
             patch.object(extras, '_session_post') as post:
            extras.attach([entry('書く', 'かく')], 'x')
        post.assert_not_called()


class Rendering(unittest.TestCase):
    def test_popup_shows_chips_tags_and_tooltips(self):
        from PyQt6.QtWidgets import QApplication
        QApplication.instance() or QApplication([])
        from meikipop.main import SharedState
        from meikipop.gui.popup import Popup

        class Input:
            def is_virtual_hotkey_down(self): return False
        popup = Popup(SharedState(), Input())
        popup.timer.stop(); popup.anki_timer.stop()
        popup.anki_status.state = lambda w: 'absent'
        popup._calibrate_empirically()
        e = entry('書く', 'かく')
        e.senses = [{'glosses': ['to write'], 'pos': [], 'tags': []}]
        e.yomitan_frequencies = [('JPDBv2㋕', '263')]
        e.yomitan_inflections = [[('passive', 'Indicates an action received.'), ('-た', '')]]
        with patch.object(config, 'show_inflections', True), patch.object(config, 'show_frequency_lists', True):
            html_text, _ = popup._calculate_content_and_size_char_count([e])
        self.assertIn('href="mine:0"', html_text)
        self.assertIn('＋ Anki', html_text)
        self.assertIn('JPDBv2㋕', html_text)
        self.assertIn('passive', html_text)
        self.assertIn('Indicates an action received.', popup._link_tips['infl:0'])
        self.assertEqual(popup._link_tips['infl:1'], '')  # no description: no tooltip
        self.assertLess(html_text.index('JPDBv2'), html_text.index('to write'))


if __name__ == '__main__':
    unittest.main()
