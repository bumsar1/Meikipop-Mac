# meikipop/texthook.py
"""Engine text instead of OCR, for games whose engine reports what it shows.

VN Library starts its own engine builds (siglus_engine for now) with VNLIB_TEXTHOOK=1. They then
serve ws://127.0.0.1:6677/json with one JSON event per change:
  {"kind": "name"|"line"|"choice"|"clear"|"view", "text", "screen": {w, h},
   "view": {x, y, w, h},                     # the game image on screen, global top-left points
   "glyph_rects": [{ch, x, y, w, h}, ...]}   # per character, in game-screen pixels
A connecting client first gets the events for the text shown right now.

While a line is shown, its characters become a Paragraph in the same shape OCR produces, so the
hit scanner, popup, Anki mining and the read log work unchanged. Pointing at engine text needs no
screenshot; anything else (menus, choices) still goes through OCR.
"""
import json
import logging
import threading
import time

from meikipop.ocr.interface import BoundingBox, Paragraph, Word

logger = logging.getLogger(__name__)

URL = "ws://127.0.0.1:6677/json"


class EngineText(threading.Thread):
    def __init__(self, shared_state, read_log=None, url=URL):
        super().__init__(daemon=True, name="EngineText")
        self.shared_state = shared_state
        self.read_log = read_log
        self.url = url
        self.connected = False
        self._lock = threading.Lock()
        self._lines = []      # [(text, [(ch, x, y, w, h) in screen points])]
        self._view = None     # (x, y, w, h) in points
        self.on_change = None  # called (from this thread) whenever the shown text changes
        self.pid_source = None  # -> the game's pid, for the read log

    # --- what the rest of Meikipop asks -------------------------------------------------------

    def frame_at(self, point):
        """Paragraphs for the shown engine text if point (global points) is on one of its lines, else None.

        The paragraphs are normalised to the game image; their .geometry is that image's
        (left, top, width, height), which the hit scanner uses instead of the OCR scan area."""
        with self._lock:
            lines, view = list(self._lines), self._view
        if not lines or not view or point is None:
            return None
        px, py = point
        hit = False
        for _, glyphs in lines:
            xs = [g[1] for g in glyphs] + [g[1] + g[3] for g in glyphs]
            ys = [g[2] for g in glyphs] + [g[2] + g[4] for g in glyphs]
            if glyphs and min(xs) - 4 <= px <= max(xs) + 4 and min(ys) - 4 <= py <= max(ys) + 4:
                hit = True
                break
        if not hit:
            return None
        return self._paragraphs(lines, view)

    def has_text(self):
        with self._lock:
            return bool(self._lines)

    # --- connection ---------------------------------------------------------------------------

    def run(self):
        from websockets.sync.client import connect
        while self.shared_state.running:
            try:
                with connect(self.url, open_timeout=2, max_size=4 << 20) as ws:
                    self.connected = True
                    logger.info("Engine text hook connected (%s); OCR is skipped over its lines.", self.url)
                    for message in ws:
                        if not self.shared_state.running:
                            break
                        if isinstance(message, str):
                            self._on_message(message)
            except (OSError, TimeoutError):
                pass  # no hooked game running
            except Exception as e:
                logger.debug("Engine text hook: %s", e)
            if self.connected:
                logger.info("Engine text hook disconnected.")
            self.connected = False
            self._set_lines([])
            time.sleep(2)

    def _on_message(self, message):
        try:
            event = json.loads(message)
        except ValueError:
            return
        kind = event.get("kind")
        view = event.get("view")
        if view:
            with self._lock:
                self._view = (float(view["x"]), float(view["y"]), float(view["w"]), float(view["h"]))
        if kind == "clear":
            self._set_lines([])
        elif kind == "line":
            line = self._to_screen(event)
            if line:
                with self._lock:
                    lines = self._lines + [line]
                self._set_lines(lines)
                self._record(line[0])

    def _to_screen(self, event):
        """(text, glyphs in screen points) for a line event, or None without positions."""
        screen = event.get("screen") or {}
        sw, sh = float(screen.get("w") or 0), float(screen.get("h") or 0)
        with self._lock:
            view = self._view
        rects = event.get("glyph_rects") or []
        if not view or not sw or not sh or not rects:
            return None
        vx, vy, vw, vh = view
        kx, ky = vw / sw, vh / sh
        glyphs = []
        for r in rects:
            ch = r.get("ch") or ""
            if len(ch) != 1 or not (r.get("w") and r.get("h")):
                continue
            glyphs.append((ch, vx + r["x"] * kx, vy + r["y"] * ky, r["w"] * kx, r["h"] * ky))
        if not glyphs:
            return None
        return "".join(g[0] for g in glyphs), glyphs

    def _set_lines(self, lines):
        with self._lock:
            changed = lines != self._lines
            self._lines = lines
        if changed and self.on_change:
            try:
                self.on_change()
            except Exception:
                logger.exception("Engine text change handler failed")

    def _record(self, text):
        """The read log gets each engine line once (the game is the frontmost/followed process)."""
        if self.read_log is None:
            return
        box = BoundingBox(0.5, 0.5, 1.0, 1.0)
        pid = self.pid_source() if self.pid_source else None
        self.read_log.record([Paragraph(text, [], box, False)], pid)

    @staticmethod
    def _paragraphs(lines, view):
        from meikipop.screenshot.window_capture import FrameParagraphs
        vx, vy, vw, vh = view
        out = []
        for text, glyphs in lines:
            words = [Word(ch, "", BoundingBox((x + w / 2 - vx) / vw, (y + h / 2 - vy) / vh, w / vw, h / vh))
                     for ch, x, y, w, h in glyphs]
            left = min(g[1] for g in glyphs)
            top = min(g[2] for g in glyphs)
            right = max(g[1] + g[3] for g in glyphs)
            bottom = max(g[2] + g[4] for g in glyphs)
            box = BoundingBox(((left + right) / 2 - vx) / vw, ((top + bottom) / 2 - vy) / vh,
                              (right - left) / vw, (bottom - top) / vh)
            out.append(Paragraph(text, words, box, False))
        frame = FrameParagraphs(out)
        frame.geometry = (vx, vy, vw, vh)
        frame.from_engine = True
        return frame
