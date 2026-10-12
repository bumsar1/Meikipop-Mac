# meikipop/screenshot/screenmanager.py
import logging
import threading
import time
import sys

from PIL import Image
from .window_capture import capture_window, window_bounds

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
        self.last_window_digest = None
        self.window_frame = None
        self.window_error = ""
        self.last_mouse_pos = None
        self.input_loop = input_loop
        self.capture_window_id = None
        self.capture_window_pid = None
        self.capture_window_label = ""
        self.follow_window = False
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
                logger.debug("Screenshot: Triggered!")

                # prevent multiple ocr runs during auto_scan_interval_seconds
                seconds_since_last_ocr = time.perf_counter() - self.last_ocr_put_time
                if config.auto_scan_mode and seconds_since_last_ocr < config.auto_scan_interval_seconds:
                    logger.debug(
                        f"...{seconds_since_last_ocr:.2f}s since last ocr, sleeping for another {config.auto_scan_interval_seconds - seconds_since_last_ocr:.2f}s")
                    self._sleep_and_handle_loop_exit(config.auto_scan_interval_seconds - seconds_since_last_ocr)
                    continue

                # prevent ocr runs without mouse movements for auto-on-mouse-move mode
                if config.auto_scan_mode and config.auto_scan_on_mouse_move and self.last_mouse_pos == self.input_loop.get_mouse_pos():
                    continue
                self.last_mouse_pos = self.input_loop.get_mouse_pos()

                logger.debug("screenmanager acquiring lock...")
                with self.shared_state.screen_lock:
                    logger.debug("...successfully acquired lock by screenmanager")
                    start_time = time.perf_counter()
                    screenshot = self.take_screenshot()
                logger.debug("...successfully released lock by screenmanager")
                processing_duration = time.perf_counter() - start_time
                logger.debug(f"Screenshot {screenshot.size} complete in {processing_duration:.2f}s")

                window_digest = self.window_frame.digest if self.window_frame else self.window_error
                if self.last_screenshot and self.last_screenshot.raw == screenshot.raw and window_digest == self.last_window_digest:
                    logger.debug(f"Screen content didnt change... skipping ocr")
                    self._sleep_and_handle_loop_exit(0.1)
                    continue

                self.last_window_digest = window_digest
                self.last_screenshot = screenshot
                self.last_mouse_pos = self.input_loop.get_mouse_pos()
                img = Image.frombytes("RGB", screenshot.size, screenshot.bgra, "raw", "BGRX")
                img.info["mining_window_frame"] = self.window_frame
                img.info["mining_window_error"] = self.window_error
                self.shared_state.ocr_queue.put(img)
                self.last_ocr_put_time = time.perf_counter()
            except:
                logger.exception("An unexpected error occurred in the screenshot loop. Continuing...")
                self._sleep_and_handle_loop_exit(1)
        logger.debug("Screenshot thread stopped.")

    def take_screenshot(self):
        if self.follow_window:
            self._follow_capture_window()
        with mss.mss() as sct:
            sct_img = sct.grab(self.monitor)
            self.window_frame = None
            self.window_error = ""
            try:
                self.window_frame = capture_window(self.capture_window_id, self.capture_window_pid)
            except Exception as e:
                # OCR continues, but adding a card reports the missing image.
                self.window_error = str(e)
                logger.debug("Window capture unavailable: %s", e)
            return sct_img

    def select_capture_window(self):
        # Keep the screenshot thread from changing context while the dialog is open.
        with self.shared_state.screen_lock:
            choice = WindowSelector.choose(self.capture_window_id)
            if choice is None:
                return False
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
            return True

    def set_scan_window(self):
        """Scan the selected window wherever it is; its position is re-read before every screenshot."""
        logger.info("Set scan area to the selected window")
        self.follow_window = True
        self._follow_capture_window()
        self.force_screenshot_trigger()

    def _follow_capture_window(self):
        bounds = window_bounds(self.capture_window_id) if self.capture_window_id else None
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