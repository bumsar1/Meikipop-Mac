"""Non-blocking Anki presence checks, with a bounded, short-lived cache."""
from collections import OrderedDict
import threading
import time
from PyQt6.QtCore import QObject, pyqtSignal
from meikipop.mining import Miner

class AnkiStatus(QObject):
    updated = pyqtSignal()
    completed = pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.cache = OrderedDict()
        self.revisions = {}
        self.busy = False
        self.completed.connect(self._completed)

    def state(self, word):
        item = self.cache.get(word)
        if item is None or item[1] < time.monotonic():
            return 'checking'
        return item[0]

    def request(self, words):
        if self.busy:
            return
        pending = list(dict.fromkeys(w for w in words if w and self.state(w) == 'checking'))
        if not pending:
            return
        self.busy = True
        versions = {w: self.revisions.get(w, 0) for w in pending}
        def work():
            results = {}
            try:
                miner = Miner()
                miner.timeout = (1, 3)
                for word in pending:
                    results[word] = 'present' if miner.word_exists(word) else 'absent'
            except Exception:
                for word in pending:
                    results.setdefault(word, 'unknown')
            self.completed.emit((results, versions))
        threading.Thread(target=work, name='AnkiPresence', daemon=True).start()

    def _completed(self, payload):
        results, versions = payload
        self.busy = False
        for word, state in results.items():
            if versions[word] != self.revisions.get(word, 0):
                continue  # A successful addition supersedes an older lookup.
            self.cache[word] = (state, time.monotonic() + (3 if state == 'unknown' else 5))
            self.cache.move_to_end(word)
        while len(self.cache) > 256:
            word, _ = self.cache.popitem(last=False)
            self.revisions.pop(word, None)
        self.updated.emit()

    def mark_added(self, word):
        self.revisions[word] = self.revisions.get(word, 0) + 1
        self.cache[word] = ('present', time.monotonic() + 5)
        self.updated.emit()
