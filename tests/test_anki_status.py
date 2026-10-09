import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import time
import unittest
from unittest.mock import patch, Mock
from PyQt6.QtWidgets import QApplication
from meikipop.anki_status import AnkiStatus
from meikipop.mining import Miner, MiningError
from meikipop.dictionary.lookup import DictionaryEntry
from meikipop.main import SharedState
from meikipop.gui.popup import Popup

app = QApplication.instance() or QApplication([])

class Tests(unittest.TestCase):
    def miner(self):
        miner = Miner.__new__(Miner)
        miner.settings = {'formatName':'Expression'}
        miner.anki_config = {'cardFormats':[{'name':'Expression', 'deck':'Japanese', 'fields':{'Expression':{'value':'{expression}'}}}]}
        miner.anki = Mock(return_value=[])
        return miner

    def test_exact_field_and_deck_search(self):
        m = self.miner()
        self.assertFalse(m.word_exists('食べる'))
        m.anki.assert_called_with('findNotes', query='"deck:Japanese" "Expression:食べる"')
        m.anki.return_value = [12]
        self.assertTrue(m.word_exists('食べる'))

    def test_query_escapes_special_characters(self):
        m = self.miner()
        m.word_exists('a*"_\\')
        query = m.anki.call_args.kwargs['query']
        self.assertIn(r'\*', query); self.assertIn(r'\"', query)
        self.assertIn(r'\_', query); self.assertIn(r'\\', query)

    def test_existing_word_stops_before_preparing_or_uploading(self):
        m = self.miner(); m.anki.return_value = [12]; m.prepare = Mock()
        with self.assertRaisesRegex(MiningError, 'Already'):
            m.add(Mock(written_form='食べる', reading='たべる'))
        m.prepare.assert_not_called()
        self.assertEqual(m.anki.call_count, 1)

    def test_error_is_not_absence(self):
        m = self.miner(); m.anki.side_effect = MiningError('Offline')
        with self.assertRaises(MiningError): m.word_exists('食べる')

    def test_late_result_cannot_undo_success(self):
        status = AnkiStatus()
        status.mark_added('食べる')
        status._completed(({'食べる':'absent'}, {'食べる':0}))
        self.assertEqual(status.state('食べる'), 'present')
        status.cache['食べる'] = ('present', time.monotonic()-1)
        self.assertEqual(status.state('食べる'), 'checking')

    def test_async_error_and_deduplication(self):
        status = AnkiStatus()
        with patch('meikipop.anki_status.Miner') as cls:
            cls.return_value.word_exists.side_effect = MiningError('Offline')
            status.request(['食べる','食べる'])
            deadline = time.monotonic()+2
            while status.busy and time.monotonic()<deadline:
                app.processEvents(); time.sleep(0.005)
            self.assertFalse(status.busy)
            self.assertEqual(status.state('食べる'), 'unknown')
            cls.return_value.word_exists.assert_called_once()

    def test_known_word_has_no_add_link_but_keeps_audio(self):
        popup = Popup(SharedState(), Mock())
        popup.timer.stop(); popup.anki_timer.stop()
        popup._calibrate_empirically()
        entry = DictionaryEntry(1,'食べる','たべる',[{'glosses':['eat']}],1,())
        popup._mining_entries = [entry]
        popup.anki_status.mark_added('食べる')
        markup, _ = popup._calculate_content_and_size_char_count([entry])
        self.assertIn('Already in Anki',markup)
        self.assertNotIn('href="mine:0"',markup)
        self.assertIn('href="audio:0"',markup)
        with patch('meikipop.mining.Miner.add') as add:
            popup._mine_clicked('mine:0'); add.assert_not_called()
        popup.anki_status.cache['食べる'] = ('absent', time.monotonic()+5)
        markup, _ = popup._calculate_content_and_size_char_count([entry])
        self.assertIn('href="mine:0"',markup)
        popup.close()

if __name__ == '__main__': unittest.main()
