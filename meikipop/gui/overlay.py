# meikipop/gui/overlay.py
"""macOS window tweaks for Meikipop's floating windows (popup, word outline)."""
import logging

from meikipop.config.config import IS_MACOS

logger = logging.getLogger(__name__)


def ns_window(widget):
    from PyQt6.QtGui import QGuiApplication
    if not IS_MACOS or QGuiApplication.platformName() != 'cocoa':
        return None
    import objc
    return objc.objc_object(c_void_p=int(widget.winId())).window()


def float_over_fullscreen(widget, hide_from_capture=False):
    """Show on every Space, including a game's full-screen Space, instead of only the desktop."""
    try:
        window = ns_window(widget)
        if window is None:
            return
        from AppKit import (NSWindowCollectionBehaviorCanJoinAllSpaces, NSWindowCollectionBehaviorFullScreenAuxiliary,
                            NSWindowCollectionBehaviorStationary, NSWindowCollectionBehaviorIgnoresCycle,
                            NSStatusWindowLevel, NSWindowSharingNone)
        window.setCollectionBehavior_(NSWindowCollectionBehaviorCanJoinAllSpaces | NSWindowCollectionBehaviorFullScreenAuxiliary |
                                      NSWindowCollectionBehaviorStationary | NSWindowCollectionBehaviorIgnoresCycle)
        window.setLevel_(NSStatusWindowLevel)
        window.setHidesOnDeactivate_(False)
        if hide_from_capture:  # keep it out of OCR screenshots and Anki images
            window.setSharingType_(NSWindowSharingNone)
    except Exception as e:
        logger.debug("Could not configure overlay window: %s", e)
