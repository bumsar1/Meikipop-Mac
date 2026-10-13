# meikipop/read_log.py
"""Appends recognised text to a daily JSON-lines file that VN Library reads to count characters read.

One line per OCR frame: {"t": unix time, "pid": game pid or null, "lines": [paragraph text, ...]}.
Consecutive identical frames are skipped; VN Library does all other de-duplication.
"""
import json
import logging
import os
import time

from meikipop.config.config import config
from meikipop.utils.paths import paths

logger = logging.getLogger(__name__)

LOG_DIR = os.path.join(paths.data_dir, 'read-log')


def reading_order(paragraphs):
    """Vertical text right-to-left, horizontal text top-to-bottom (the order the controller steps through)."""
    return sorted(paragraphs, key=lambda p: (-p.box.center_x, p.box.center_y) if p.is_vertical
                  else (p.box.center_y, p.box.center_x))


def frontmost_pid():
    try:
        from AppKit import NSWorkspace
        app = NSWorkspace.sharedWorkspace().frontmostApplication()
        return int(app.processIdentifier()) if app is not None else None
    except Exception:
        return None


class ReadLog:
    def __init__(self, directory=LOG_DIR):
        self.directory = directory
        self._last_lines = None

    def record(self, paragraphs, window_pid=None):
        """Never raises: a logging problem must not break OCR."""
        try:
            if not config.log_read_text or not config.is_enabled or not paragraphs:
                return
            lines = [t for t in (p.full_text.strip() for p in reading_order(paragraphs)) if t]
            if not lines or lines == self._last_lines:
                return
            self._last_lines = lines
            now = time.time()
            entry = {"t": now, "pid": window_pid if window_pid else frontmost_pid(), "lines": lines}
            os.makedirs(self.directory, exist_ok=True)
            path = os.path.join(self.directory, time.strftime('%Y-%m-%d', time.localtime(now)) + '.jsonl')
            with open(path, 'a', encoding='utf-8') as f:
                f.write(json.dumps(entry, ensure_ascii=False) + '\n')
        except Exception as e:
            logger.warning("Could not write the read log: %s", e)
