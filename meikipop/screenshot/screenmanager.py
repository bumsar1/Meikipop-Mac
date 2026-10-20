# meikipop/screenshot/screenmanager.py
import logging
import threading
import time
import sys

from PIL import Image
from .window_capture import FrameParagraphs, capture_window, window_bounds, find_game_window

from meikipop.config.config import config, IS_WAYLAND
from meikipop.gui.region_selector import RegionSelector
from meikipop.gui.window_selector import WindowSelector

if IS_WAYLAND:
    from . import wayland_mss_shim

    mss = wayland_mss_shim.MSSModuleShim()
else:
    import mss

logger = logging.getLogger(__name__)  # Get the logger


# todo doesnt work when monitors change
class ScreenManager(threading.Thread):
    def __init__(self, shared_state, input_loop):
        super().__init__(daemon=True, name="ScreenManager")
        self.shared_state = shared_state
        self.monitor = None
        self.last_ocr_put_time = 0.0
        self.last_screenshot = None
        self.window_frame = None
        self.window_error = ""
        self.last_mouse_pos = None
        self.input_loop = input_loop
        self.capture_window_id = None
        self.capture_window_pid = None
        self.capture_window_label = ""
        self.follow_window = False
        self.game_pid = None  # set when a launcher (VN Library couch mode) hands us the game
        self.showing_engine_text = False  # the hit scanner has engine text (texthook.py), not OCR
        if config.game_pid:
            # Launched for a specific game: no dialogs; the window is found once it exists.
            self.follow_game(config.game_pid)
            return
        if not self.select_capture_window():
            sys.exit(0)
        if config.scan_region == "region":
            self.set_scan_region()
        elif config.scan_region == "window":
            self.set_scan_window()
        else:
            try:
                screen_idx = int(config.scan_region)
                self.set_scan_screen(screen_idx)
            except (ValueError, IndexError):
                logger.warning(f"Invalid screen '{config.scan_region}' in config, defaulting to screen 1.")
                self.set_scan_screen(1)

    def run(self):
        logger.debug("Screenshot thread started.")
        while self.shared_state.running:
            try:
                if config.auto_scan_mode and not config.is_enabled:
                    logger.debug(f"paused while auto mode")
                    self._sleep_and_handle_loop_exit(1)
                    continue
                self.shared_state.screenshot_trigger_event.wait()
                self.shared_state.screenshot_trigger_event.clear()
                if not self.shared_state.running: break
                if self.follow_window:
                    self._follow_capture_window()
                # A hooked engine says what it shows: over its text, look up without OCR.
                frame = self.engine_frame()
                if frame is not None:
                    self.shared_state.hit_scan_queue.put(frame)
                    self.showing_engine_text = True
                    self.last_screenshot = None  # OCR again as soon as the pointer leaves the line
                    self._sleep_and_handle_loop_exit(config.auto_scan_interval_seconds)
                    continue
                engine = getattr(self.shared_state, "engine_text", None)
                if self.showing_engine_text:
                    self.shared_state.hit_scan_queue.put(FrameParagraphs([]))
                    self.showing_engine_text = False
                if (engine is not None and engine.has_text() and config.auto_scan_mode
                        and not getattr(self.input_loop, "hotkey_is_pressed", False)):
                    # The game's lines come from the engine; OCR the rest (menus, choices) only on Shift.
                    self._sleep_and_handle_loop_exit(0.1)
                    continue
                if self.monitor is None:  # still waiting for the game window
                    time.sleep(0.5)
                    self.shared_state.screenshot_trigger_event.set()
                    continue
                logger.debug("Screenshot: Triggered!")

                # prevent multiple ocr runs during auto_scan_interval_seconds
                seconds_since_last_ocr = time.perf_counter() - self.last_ocr_put_time
                if config.auto_scan_mode and seconds_since_last_ocr < config.auto_scan_interval_seconds:
                    logger.debug(
                        f"...{seconds_since_last_ocr:.2f}s since last ocr, sleeping for another {config.auto_scan_interval_seconds - seconds_since_last_ocr:.2f}s")
                    self._sleep_and_handle_loop_exit(config.auto_scan_interval_seconds - seconds_since_last_ocr)
                    continue

                # prevent ocr runs without mouse movements for auto-on-mouse-move mode; not when following a
                # game from couch mode, where the mouse sits still and every new line should still be read
                if config.auto_scan_mode and config.auto_scan_on_mouse_move and not self.game_pid \
                        and self.last_mouse_pos == self.input_loop.get_mouse_pos():
                    continue
                self.last_mouse_pos = self.input_loop.get_mouse_pos()

                logger.debug("screenmanager acquiring lock...")
                with self.shared_state.screen_lock:
                    logger.debug("...successfully acquired lock by screenmanager")
                    start_time = time.perf_counter()
                    img, content = self.take_screenshot()
                logger.debug("...successfully released lock by screenmanager")
                if img is None:  # the followed window is hidden (another Space, minimized): nothing to read
                    self._sleep_and_handle_loop_exit(0.5)
                    continue
                logger.debug(f"Screenshot {img.size} complete in {time.perf_counter() - start_time:.2f}s")

                if self.last_screenshot is not None and self.last_screenshot == content:
                    logger.debug(f"Screen content didnt change... skipping ocr")
                    self._sleep_and_handle_loop_exit(0.1)
                    continue

                self.last_screenshot = content
                self.last_mouse_pos = self.input_loop.get_mouse_pos()
                img.info["mining_window_frame"] = self.window_frame
                img.info["mining_window_error"] = self.window_error
                self.shared_state.ocr_queue.put(img)
                self.last_ocr_put_time = time.perf_counter()
            except:
                logger.exception("An unexpected error occurred in the screenshot loop. Continuing...")
                self._sleep_and_handle_loop_exit(1)
        logger.debug("Screenshot thread stopped.")

    def take_screenshot(self):
        """(image to OCR or None, raw bytes for change detection). Also captures the window for Anki."""
        if self.follow_window:
            self._follow_capture_window()
        self.window_frame = None
        self.window_error = ""
        try:
            self.window_frame = capture_window(self.capture_window_id, self.capture_window_pid)
        except Exception as e:
            # OCR continues, but adding a card reports the missing image.
            self.window_error = str(e)
            logger.debug("Window capture unavailable: %s", e)
        if self.follow_window:
            # Read the window's own pixels: covering windows (and Meikipop's popup) never get read,
            # and a game that is not on screen is not read at all.
            if self.window_frame is None:
                return None, None
            return self.window_frame.pil(), self.window_frame.pixels[0]
        with mss.mss() as sct:
            shot = sct.grab(self.monitor)
        return Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX"), shot.raw

    def engine_frame(self):
        """The hooked engine's text as OCR-style paragraphs when the pointer is on it, else None."""
        engine = getattr(self.shared_state, "engine_text", None)
        if engine is None:
            return None
        frame = engine.frame_at(self.input_loop.get_mouse_pos())
        if frame is None:
            return None
        try:  # the Anki picture, as with OCR
            frame.window_frame = capture_window(self.capture_window_id, self.capture_window_pid)
        except Exception as e:
            frame.window_error = str(e)
        return frame

    def engine_text_changed(self):
        """A new line (or none): replace what the hit scanner has, without OCR."""
        frame = self.engine_frame()
        if frame is not None:
            self.shared_state.hit_scan_queue.put(frame)
            self.showing_engine_text = True
        elif self.showing_engine_text:
            self.shared_state.hit_scan_queue.put(FrameParagraphs([]))
            self.showing_engine_text = False

    def select_capture_window(self):
        # Keep the screenshot thread from changing context while the dialog is open.
        with self.shared_state.screen_lock:
            choice = WindowSelector.choose(self.capture_window_id)
            if choice is None:
                return False
            self.game_pid = None
            self._use_window(choice)
            return True

    def follow_game(self, pid):
        """Track the game started as pid: pick its window as soon as it appears and scan all of it."""
        logger.info("Following game process %s", pid)
        self.game_pid = int(pid)
        self.follow_window = True
        self.capture_window_id = None
        self.monitor = None
        self._follow_capture_window()
        self.force_screenshot_trigger()
        self.shared_state.screenshot_trigger_event.set()

    def _use_window(self, choice):
        self.capture_window_id = choice['id']
        self.capture_window_pid = choice['pid']
        self.capture_window_label = choice['app'] + (' — ' + choice['title'] if choice['title'] else '')
        self.shared_state.capture_window_id = self.capture_window_id
        audio = getattr(self.shared_state, "game_audio", None)
        if audio is not None:
            if config.is_enabled:
                audio.start(self.capture_window_pid, self.capture_window_id)
            else:
                audio.stop()
        self.force_screenshot_trigger()
        self.shared_state.hit_scan_queue.put(None)
        self.shared_state.screenshot_trigger_event.set()
        logger.info('Anki image window: %s (ID %s)', self.capture_window_label, self.capture_window_id)

    def set_scan_window(self):
        """Scan the selected window wherever it is; its position is re-read before every screenshot."""
        logger.info("Set scan area to the selected window")
        self.follow_window = True
        self._follow_capture_window()
        self.force_screenshot_trigger()

    def _follow_capture_window(self):
        bounds = window_bounds(self.capture_window_id) if self.capture_window_id else None
        if bounds is None and self.game_pid:
            # First look, or the game replaced its window (e.g. going full screen).
            found = find_game_window(self.game_pid)
            if found is not None and found['id'] != self.capture_window_id:
                self._use_window(found)
                bounds = window_bounds(found['id'])
        if bounds is None:
            logger.debug("Selected window not on screen; keeping the last scan area")
            return
        x, y, w, h = bounds
        monitor = {"top": y, "left": x, "width": w, "height": h}
        if monitor != self.monitor:
            logger.info(f"Scan area follows window: {monitor}")
            self.monitor = monitor

    def set_scan_region(self):
        self.follow_window = False
        scan_rect = RegionSelector.get_region()
        if scan_rect:
            logger.info(f"Set scan area to region {scan_rect}")
            self.monitor = {"top": scan_rect.y(), "left": scan_rect.x(), "width": scan_rect.width(),
                            "height": scan_rect.height()}
            return True
        else:
            logger.info("Region selection cancelled.")
            return False

    def set_scan_screen(self, screen_index):
        self.follow_window = False
        logger.info(f"Set scan area to screen {screen_index}")
        with mss.mss() as sct:
            if screen_index < len(sct.monitors):
                logger.info(f"Set scan area to screen {screen_index}")
                self.monitor = sct.monitors[screen_index]
            else:
                logger.error(f"Cannot set scan screen: index {screen_index} is out of bounds.")

    def get_scan_geometry(self):
        if not self.monitor:
            return 0, 0, 0, 0
        return self.monitor["left"], self.monitor["top"], self.monitor["width"], self.monitor["height"]

    def force_screenshot_trigger(self):
        self.last_screenshot = None
        self.last_mouse_pos = None

    def _sleep_and_handle_loop_exit(self, interval):
        if config.auto_scan_mode:
            time.sleep(interval)
            self.shared_state.screenshot_trigger_event.set()
        else:
            self.shared_state.hit_scan_queue.trigger()

    @staticmethod
    def get_screens():
        with mss.mss() as sct:
            return sct.monitors