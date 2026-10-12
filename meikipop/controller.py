# meikipop/controller.py
"""Gamepad word navigation: hold a button, step through the OCR text word by word."""
import logging
import threading
import time
import unicodedata
from dataclasses import dataclass
from typing import List, Optional

from PyQt6.QtCore import QObject, QTimer, QRectF, Qt
from PyQt6.QtGui import QColor, QPainter, QPen
from PyQt6.QtWidgets import QWidget

from meikipop.config.config import config, IS_MACOS

logger = logging.getLogger(__name__)

HOLD_BUTTONS = {'LB': 'leftShoulder', 'RB': 'rightShoulder', 'LT': 'leftTrigger', 'RT': 'rightTrigger',
                'L3': 'leftThumbstickButton', 'R3': 'rightThumbstickButton', 'Back': 'buttonOptions'}
REPEAT_DELAY, REPEAT_INTERVAL = 0.4, 0.15


@dataclass(frozen=True)
class Token:
    para: int
    start: int
    length: int
    rect: tuple  # normalized (left, top, right, bottom)

    @property
    def center(self):
        l, t, r, b = self.rect
        return (l + r) / 2, (t + b) / 2


def _skippable(ch: str) -> bool:
    from meikipop.dictionary.lookup import JAPANESE_SEPARATORS
    return ch.isspace() or ch in JAPANESE_SEPARATORS or unicodedata.category(ch)[0] in 'PSZ'


def char_rects(para) -> List[tuple]:
    """One normalized rect per character of para.full_text, split evenly within multi-char words."""
    rects = []
    for word in para.words:
        b = word.box
        l, t = b.center_x - b.width / 2, b.center_y - b.height / 2
        n = max(1, len(word.text))
        for k in range(len(word.text)):
            if para.is_vertical:
                rects.append((l, t + b.height * k / n, l + b.width, t + b.height * (k + 1) / n))
            else:
                rects.append((l + b.width * k / n, t, l + b.width * (k + 1) / n, t + b.height))
        rects.extend([rects[-1] if rects else (l, t, l, t)] * len(word.separator))
    return rects


def tokenize(paragraphs, word_length) -> List[Token]:
    """Greedy longest-dictionary-match segmentation in reading order; punctuation is skipped."""
    order = sorted(range(len(paragraphs)), key=lambda i: (
        (-paragraphs[i].box.center_x, paragraphs[i].box.center_y) if paragraphs[i].is_vertical
        else (paragraphs[i].box.center_y, paragraphs[i].box.center_x)))
    tokens = []
    for p in order:
        para = paragraphs[p]
        text, rects = para.full_text, char_rects(para)
        if len(rects) < len(text):
            rects += [rects[-1] if rects else (0, 0, 0, 0)] * (len(text) - len(rects))
        i = 0
        while i < len(text):
            if _skippable(text[i]):
                i += 1
                continue
            n = max(1, min(word_length(text[i:]), len(text) - i))
            span = rects[i:i + n]
            tokens.append(Token(p, i, n, (min(r[0] for r in span), min(r[1] for r in span),
                                          max(r[2] for r in span), max(r[3] for r in span))))
            i += n
    return tokens


def neighbour(tokens: List[Token], index: int, direction: int, vertical: bool) -> int:
    """Nearest token on the adjacent visual row (horizontal text) or column (vertical text)."""
    cur = tokens[index]
    cx, cy = cur.center
    l, t, r, b = cur.rect
    if vertical:  # columns run right-to-left; "down" means the next column, to the left
        size = r - l
        cands = [(i, tk) for i, tk in enumerate(tokens) if (tk.center[0] < cx - size / 2 if direction > 0 else tk.center[0] > cx + size / 2)]
        if not cands:
            return index
        nearest = min(abs(tk.center[0] - cx) for _, tk in cands)
        row = [(i, tk) for i, tk in cands if abs(tk.center[0] - cx) <= nearest + size / 2]
        return min(row, key=lambda it: abs(it[1].center[1] - cy))[0]
    size = b - t
    cands = [(i, tk) for i, tk in enumerate(tokens) if (tk.center[1] > cy + size / 2 if direction > 0 else tk.center[1] < cy - size / 2)]
    if not cands:
        return index
    nearest = min(abs(tk.center[1] - cy) for _, tk in cands)
    row = [(i, tk) for i, tk in cands if abs(tk.center[1] - cy) <= nearest + size / 2]
    return min(row, key=lambda it: abs(it[1].center[0] - cx))[0]


class ControllerNavigator:
    """Shared between the Qt thread (moves) and the HitScanner thread (fresh OCR, lookups)."""

    def __init__(self, lookup):
        self.lookup = lookup
        self._lock = threading.Lock()
        self.active = False
        self._waiting_for = None  # OCR result that was current when lookup mode started
        self.paragraphs = None
        self.tokens: List[Token] = []
        self.index = 0

    def word_length(self, text: str) -> int:
        from meikipop.dictionary.lookup import DictionaryEntry
        entries = self.lookup._do_lookup(text[:config.max_lookup_length])
        entry = next((e for e in entries if isinstance(e, DictionaryEntry)), None)
        return entry.mining_length if entry else 1

    def begin(self, current_paragraphs):
        with self._lock:
            self.active = True
            self._waiting_for = current_paragraphs
            self.paragraphs, self.tokens, self.index = None, [], 0

    def end(self):
        with self._lock:
            self.active = False
            self.paragraphs, self.tokens = None, []

    def offer(self, paragraphs) -> bool:
        """Called by HitScanner with each OCR result; adopts the first one newer than begin()."""
        with self._lock:
            if not self.active or paragraphs is None or paragraphs is self._waiting_for or paragraphs is self.paragraphs:
                return False
            self._waiting_for = None
        tokens = tokenize(paragraphs, self.word_length)
        with self._lock:
            if not self.active:
                return False
            self.paragraphs, self.tokens, self.index = paragraphs, tokens, 0
        logger.info("Controller: %d words in %d text blocks", len(tokens), len(paragraphs))
        return True

    def move(self, dx: int, dy: int) -> bool:
        with self._lock:
            if not self.tokens:
                return False
            old = self.index
            if dx:
                self.index = max(0, min(len(self.tokens) - 1, self.index + dx))
            if dy:
                vertical = self.paragraphs[self.tokens[self.index].para].is_vertical
                self.index = neighbour(self.tokens, self.index, dy, vertical)
            return self.index != old

    def current(self) -> Optional[Token]:
        with self._lock:
            return self.tokens[self.index] if self.active and self.tokens else None

    def mining_text(self):
        with self._lock:
            if not self.active or not self.tokens:
                return None
            tk, paras = self.tokens[self.index], self.paragraphs
        from meikipop.mining import MiningText
        text = paras[tk.para].full_text
        return MiningText(text[tk.start:], text, tk.start,
                          getattr(paras, "window_frame", None), getattr(paras, "window_error", ""))


class Gamepad:
    """Polls macOS GameController state; background monitoring keeps it working while the game has focus."""

    def __init__(self):
        self.available = False
        try:
            import GameController
            self.gc = GameController
            GameController.GCController.setShouldMonitorBackgroundEvents_(True)
            GameController.GCController.startWirelessControllerDiscoveryWithCompletionHandler_(None)
            self.available = True
        except Exception as e:
            logger.warning("Gamepad support unavailable: %s", e)

    def pad(self):
        if not self.available:
            return None
        for c in self.gc.GCController.controllers() or []:
            pad = c.extendedGamepad()
            if pad is not None:
                return c, pad
        return None

    def name(self) -> str:
        found = self.pad()
        return (found[0].vendorName() or "Controller") if found else ""


class WordHighlight(QWidget):
    """Click-through outline drawn around the selected word."""

    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint |
                            Qt.WindowType.Tool | Qt.WindowType.WindowTransparentForInput |
                            Qt.WindowType.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)

    def show_at(self, x, y, w, h):
        pad = 3
        self.setGeometry(int(x - pad), int(y - pad), int(w + 2 * pad), int(h + 2 * pad))
        if not self.isVisible():
            self.show()
            self._exclude_from_capture()
        self.update()

    def _exclude_from_capture(self):
        from PyQt6.QtGui import QGuiApplication
        if not IS_MACOS or QGuiApplication.platformName() != 'cocoa':
            return
        try:  # keep the outline out of OCR screenshots and Anki images
            import objc
            from AppKit import NSWindowSharingNone
            view = objc.objc_object(c_void_p=int(self.winId()))
            view.window().setSharingType_(NSWindowSharingNone)
        except Exception as e:
            logger.debug("Could not exclude highlight from capture: %s", e)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QPen(QColor(config.color_highlight_word), 2.5))
        p.setBrush(QColor(0, 0, 0, 0))
        p.drawRoundedRect(QRectF(self.rect()).adjusted(1.5, 1.5, -1.5, -1.5), 5, 5)


class ControllerInput(QObject):
    """Reads the gamepad on the Qt thread and drives the navigator, popup and highlight."""

    def __init__(self, shared_state, screen_manager, hit_scanner, popup, navigator):
        super().__init__()
        self.shared_state, self.screen_manager = shared_state, screen_manager
        self.hit_scanner, self.popup, self.navigator = hit_scanner, popup, navigator
        self.gamepad = Gamepad()
        self.highlight = WordHighlight()
        self._prev = {}
        self._repeat = {}
        self._toggled_on = False
        self._game_app = None
        self._shown_token = None
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.poll)
        if self.gamepad.available:
            self.timer.start(16)

    def _pressed(self, pad, name):
        el = getattr(pad, name, None)
        el = el() if el is not None else None
        return bool(el is not None and el.isPressed())

    def _edge(self, key, now_down):
        was = self._prev.get(key, False)
        self._prev[key] = now_down
        return now_down and not was

    def _repeating(self, key, now_down, now):
        """Edge press, then auto-repeat while held."""
        if not now_down:
            self._repeat.pop(key, None)
            return False
        due = self._repeat.get(key)
        if due is None:
            self._repeat[key] = now + REPEAT_DELAY
            return True
        if now >= due:
            self._repeat[key] = now + REPEAT_INTERVAL
            return True
        return False

    def poll(self):
        try:
            self._poll()
        except Exception:
            logger.exception("Controller poll failed")

    def _poll(self):
        found = self.gamepad.pad() if config.controller_enabled and config.is_enabled else None
        if found is None:
            if self.navigator.active:
                self._stop()
            return
        pad = found[1]
        hold = self._pressed(pad, HOLD_BUTTONS.get(config.controller_hold_button, 'leftShoulder'))
        if config.controller_mode == 'toggle':
            if self._edge('hold', hold):
                self._toggled_on = not self._toggled_on
            want = self._toggled_on
        else:
            want = hold
        if want and not self.navigator.active:
            self._start()
        elif not want and self.navigator.active:
            self._stop()
        if not self.navigator.active:
            return

        now = time.monotonic()
        dpad = pad.dpad()
        moved = False
        for key, el, dx, dy in (('left', dpad.left(), -1, 0), ('right', dpad.right(), 1, 0),
                                ('up', dpad.up(), 0, -1), ('down', dpad.down(), 0, 1)):
            if self._repeating(key, el.isPressed(), now):
                moved |= self.navigator.move(dx, dy)
        if moved:
            self.shared_state.hit_scan_queue.trigger()
        if self._edge('a', self._pressed(pad, 'buttonA')):
            self.popup.mine_first_entry()
        if self._edge('x', self._pressed(pad, 'buttonX')):
            self.popup.replay_first_entry()
        if self._edge('b', self._pressed(pad, 'buttonB')) and config.controller_mode == 'toggle':
            self._toggled_on = False
            self._stop()
        self._update_highlight()

    def _start(self):
        logger.info("Controller: lookup mode on")
        self.navigator.begin(self.hit_scanner.last_paragraphs)
        self._shown_token = None
        if config.controller_block_game_input:
            self._take_focus()
        # Fresh OCR of what is on screen right now; the navigator waits for it.
        self.screen_manager.force_screenshot_trigger()
        self.shared_state.screenshot_trigger_event.set()

    def _stop(self):
        logger.info("Controller: lookup mode off")
        self.navigator.end()
        self._repeat.clear()
        self.highlight.hide()
        self._shown_token = None
        self.shared_state.hit_scan_queue.trigger()
        if self._game_app is not None:
            app, self._game_app = self._game_app, None
            # After the popup has hidden (it restores focus on its own hide), hand focus back to the game.
            QTimer.singleShot(80, lambda: self._activate(app))

    def _update_highlight(self):
        tk = self.navigator.current()
        if tk is None:
            self.highlight.hide()
            return
        if tk == self._shown_token and self.highlight.isVisible():
            return
        self._shown_token = tk
        x, y, w, h = self.token_screen_rect(tk)
        self.highlight.show_at(x, y, w, h)

    def token_screen_rect(self, tk: Token):
        left, top, width, height = self.screen_manager.get_scan_geometry()
        l, t, r, b = tk.rect
        return left + l * width, top + t * height, (r - l) * width, (b - t) * height

    def _take_focus(self):
        """Games that read the controller through GameController only get input while frontmost."""
        if not IS_MACOS:
            return
        try:
            from AppKit import NSWorkspace, NSApplication, NSRunningApplication
            front = NSWorkspace.sharedWorkspace().frontmostApplication()
            if front is not None and front.processIdentifier() != NSRunningApplication.currentApplication().processIdentifier():
                self._game_app = front
            NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
        except Exception as e:
            logger.warning("Could not pause game input: %s", e)

    @staticmethod
    def _activate(app):
        try:
            from AppKit import NSApplicationActivateIgnoringOtherApps
            app.activateWithOptions_(NSApplicationActivateIgnoringOtherApps)
        except Exception as e:
            logger.warning("Could not return focus to the game: %s", e)
