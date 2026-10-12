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


if __name__ == '__main__':
    unittest.main()
