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
VN_RESCAN_DELAY_MS = 400  # let the game draw the next line before reading it


STICK_DEADZONE, POINTER_SPEED, SCROLL_INTERVAL = 0.2, 1100, 0.12  # speed in points per second


def can_post_events(prompt=True) -> bool:
    """Synthetic mouse input needs Accessibility access; asks macOS to prompt the first time."""
    if not IS_MACOS:
        return False
    from ApplicationServices import AXIsProcessTrustedWithOptions, kAXTrustedCheckOptionPrompt
    if AXIsProcessTrustedWithOptions({kAXTrustedCheckOptionPrompt: prompt}):
        return True
    logger.warning("Visual novel mode needs Accessibility permission to control the mouse")
    return False


def pointer_position():
    import Quartz
    p = Quartz.CGEventGetLocation(Quartz.CGEventCreate(None))
    return p.x, p.y


def click_at(x, y, right=False, restore=True) -> bool:
    """Click at a global point in points, optionally putting the cursor back. False without Accessibility access."""
    if not can_post_events():
        return False
    import Quartz
    back = pointer_position()
    point = Quartz.CGPointMake(x, y)
    button = Quartz.kCGMouseButtonRight if right else Quartz.kCGMouseButtonLeft
    down, up = ((Quartz.kCGEventRightMouseDown, Quartz.kCGEventRightMouseUp) if right
                else (Quartz.kCGEventLeftMouseDown, Quartz.kCGEventLeftMouseUp))
    # Move first: many engines only accept a click on a choice they have seen hovered.
    for kind in (Quartz.kCGEventMouseMoved, down, up):
        event = Quartz.CGEventCreateMouseEvent(None, kind, point, button)
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, event)
        time.sleep(0.05 if kind == Quartz.kCGEventMouseMoved else 0.02)
    if restore:
        Quartz.CGWarpMouseCursorPosition(Quartz.CGPointMake(*back))
        Quartz.CGAssociateMouseAndMouseCursorPosition(True)
    return True


def clamp_to_displays(x, y):
    import Quartz
    err, ids, n = Quartz.CGGetActiveDisplayList(16, None, None)
    rects = [Quartz.CGDisplayBounds(i) for i in (ids or [])[:n]]
    if not rects:
        return x, y
    def dist(r):
        cx = min(max(x, r.origin.x), r.origin.x + r.size.width - 1)
        cy = min(max(y, r.origin.y), r.origin.y + r.size.height - 1)
        return (cx - x) ** 2 + (cy - y) ** 2, cx, cy
    _, cx, cy = min(dist(r) for r in rects)
    return cx, cy


def move_pointer(x, y):
    """Move the real cursor with a mouse-moved event, so games see the hover."""
    import Quartz
    x, y = clamp_to_displays(x, y)
    event = Quartz.CGEventCreateMouseEvent(None, Quartz.kCGEventMouseMoved, Quartz.CGPointMake(x, y), Quartz.kCGMouseButtonLeft)
    Quartz.CGEventPost(Quartz.kCGHIDEventTap, event)


def scroll(lines):
    import Quartz
    event = Quartz.CGEventCreateScrollWheelEvent(None, Quartz.kCGScrollEventUnitLine, 1, int(lines))
    Quartz.CGEventPost(Quartz.kCGHIDEventTap, event)


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
            from meikipop.gui.overlay import float_over_fullscreen
            float_over_fullscreen(self, hide_from_capture=True)
        self.update()

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
        pressed_a = self._edge('a', self._pressed(pad, 'buttonA'))
        pressed_b = self._edge('b', self._pressed(pad, 'buttonB'))
        pressed_x = self._edge('x', self._pressed(pad, 'buttonX'))
        pressed_y = self._edge('y', self._pressed(pad, 'buttonY'))
        if config.vn_mode:
            if pressed_x:
                self.advance_text()
                return
            self._pointer(pad)
            if not self.navigator.active and (pressed_a or pressed_b):
                if can_post_events():
                    click_at(*pointer_position(), right=pressed_b, restore=False)
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
        if pressed_a:
            self.popup.mine_first_entry()
        if pressed_y or (pressed_x and not config.vn_mode):
            self.popup.replay_first_entry()
        if pressed_b and config.controller_mode == 'toggle':
            self._toggled_on = False
            self._stop()
        self._update_highlight()

    def _pointer(self, pad):
        """Left stick moves the mouse pointer; right stick up/down scrolls (e.g. the backlog)."""
        now = time.monotonic()
        dt = min(0.05, now - getattr(self, '_last_poll', now))
        self._last_poll = now
        stick = pad.leftThumbstick()
        sx, sy = stick.xAxis().value(), stick.yAxis().value()
        mag = (sx * sx + sy * sy) ** 0.5
        if mag > STICK_DEADZONE and dt > 0:
            # Squared response: small tilts for precise aiming, full tilt to cross the screen.
            speed = POINTER_SPEED * ((mag - STICK_DEADZONE) / (1 - STICK_DEADZONE)) ** 2 * dt / mag
            if self._pointer_allowed():
                x, y = getattr(self, '_pointer_pos', None) or pointer_position()
                x, y = clamp_to_displays(x + sx * speed, y - sy * speed)  # stick up is +y, screen up is -y
                self._pointer_pos = (x, y)
                move_pointer(x, y)
        else:
            self._pointer_pos = None  # re-read next time, in case the real mouse moved
        ry = pad.rightThumbstick().yAxis().value()
        if abs(ry) > 0.5 and now >= getattr(self, '_next_scroll', 0) and self._pointer_allowed():
            self._next_scroll = now + SCROLL_INTERVAL
            scroll(1 if ry > 0 else -1)

    def _pointer_allowed(self):
        # Checked at most every few seconds (it is polled 60 times a second), so a later grant is picked up.
        now = time.monotonic()
        if now >= getattr(self, '_ax_checked', 0):
            self._ax_ok = can_post_events(prompt=not hasattr(self, '_ax_ok'))
            self._ax_checked = now + (60 if self._ax_ok else 3)
        return self._ax_ok

    def advance_text(self):
        """Visual novel mode: left-click the selected word (e.g. a dialogue choice) while looking up,
        otherwise the middle of the scan area, like clicking the text box."""
        left, top, width, height = self.screen_manager.get_scan_geometry()
        if not width:
            return
        looking_up = self.navigator.active
        token = self.navigator.current() if looking_up else None
        if token is not None:
            x, y, w, h = self.token_screen_rect(token)
            target = (x + w / 2, y + h / 2)
        else:
            target = (left + width / 2, top + height / 2)
        if looking_up:  # get the popup out of the way and wait for the next line
            self.highlight.hide()
            self.popup.hide_popup()
            self.navigator.begin(self.hit_scanner.last_paragraphs)
            self._shown_token = None
        app, self._game_app = self._game_app, None
        if app is not None:
            self._activate(app)  # the click must land in the game, not in Meikipop

        def click():
            if not click_at(*target):
                self.popup.mining_status.setText("Allow Meikipop under Privacy & Security → Accessibility to advance text.")
                return
            if looking_up and self.navigator.active:
                if config.controller_block_game_input:
                    QTimer.singleShot(150, self._take_focus)
                QTimer.singleShot(VN_RESCAN_DELAY_MS, self._rescan)
        QTimer.singleShot(60 if app is not None else 0, click)

    def _rescan(self):
        if self.navigator.active:
            self.screen_manager.force_screenshot_trigger()
            self.shared_state.screenshot_trigger_event.set()

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
