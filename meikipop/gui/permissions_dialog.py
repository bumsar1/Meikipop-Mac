# meikipop/gui/permissions_dialog.py
"""Shows which macOS privacy permissions Meikipop has, and opens the right Settings pages."""
import logging
import subprocess
import sys

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QApplication

logger = logging.getLogger(__name__)

SETTINGS = "x-apple.systempreferences:com.apple.preference.security?"

# (key, name in System Settings, what Meikipop needs it for, Settings anchor)
PERMISSIONS = [
    ("screen", "Screen & System Audio Recording",
     "Reading text (OCR), the window picture on Anki cards, and game audio.", "Privacy_ScreenCapture"),
    ("accessibility", "Accessibility",
     "Visual novel mode: X/A/B clicks and moving the mouse with the stick.", "Privacy_Accessibility"),
]


def has_permission(key) -> bool:
    try:
        if key == "screen":
            import Quartz
            return bool(Quartz.CGPreflightScreenCaptureAccess())
        if key == "accessibility":
            from ApplicationServices import AXIsProcessTrusted
            return bool(AXIsProcessTrusted())
    except Exception as e:
        logger.debug("Permission check failed for %s: %s", key, e)
    return False


def missing_permissions():
    return [p for p in PERMISSIONS if not has_permission(p[0])]


def request(key):
    """Ask macOS to add Meikipop to the list (and prompt once), then open the Settings page."""
    try:
        if key == "screen":
            import Quartz
            Quartz.CGRequestScreenCaptureAccess()
        elif key == "accessibility":
            from ApplicationServices import AXIsProcessTrustedWithOptions, kAXTrustedCheckOptionPrompt
            AXIsProcessTrustedWithOptions({kAXTrustedCheckOptionPrompt: True})
    except Exception as e:
        logger.warning("Could not request %s permission: %s", key, e)
    anchor = next(p[3] for p in PERMISSIONS if p[0] == key)
    subprocess.Popen(["/usr/bin/open", SETTINGS + anchor])


def relaunch():
    """Screen Recording only takes effect after a restart."""
    exe = sys.executable
    bundle = exe[:exe.index(".app/") + 4] if ".app/" in exe else None
    if bundle:
        subprocess.Popen(["/bin/zsh", "-c", f'sleep 1; open "{bundle}"'])
    QApplication.quit()


class PermissionsDialog(QDialog):
    def __init__(self, startup=False, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Meikipop Permissions")
        self.setMinimumWidth(520)
        layout = QVBoxLayout(self)
        intro = ("Meikipop needs these macOS permissions. Grant them now so nothing interrupts you in a game."
                 if startup else "Meikipop needs these macOS permissions.")
        label = QLabel(intro + "\n\nIf a permission is switched on but still shows as missing, select Meikipop in "
                       "that list, remove it with −, then click Open Settings here again and switch it on.")
        label.setWordWrap(True)
        layout.addWidget(label)
        self.rows = {}
        for key, name, why, _ in PERMISSIONS:
            row = QHBoxLayout()
            text = QLabel()
            text.setWordWrap(True)
            button = QPushButton("Open Settings")
            button.clicked.connect(lambda _=False, k=key: request(k))
            row.addWidget(text, 1)
            row.addWidget(button)
            layout.addLayout(row)
            self.rows[key] = (text, button, name, why)
        self.note = QLabel("")
        self.note.setWordWrap(True)
        layout.addWidget(self.note)
        buttons = QHBoxLayout()
        self.restart = QPushButton("Quit && Reopen Meikipop")
        self.restart.clicked.connect(relaunch)
        done = QPushButton("Continue" if startup else "Close")
        done.clicked.connect(self.accept)
        buttons.addWidget(self.restart)
        buttons.addStretch()
        buttons.addWidget(done)
        layout.addLayout(buttons)
        self.refresh()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(1000)

    def refresh(self):
        for key, (text, button, name, why) in self.rows.items():
            ok = has_permission(key)
            text.setText(f"{'✓' if ok else '✗'}  <b>{name}</b><br><span style='color:#888'>{why}</span>")
            button.setEnabled(not ok)
        self.note.setText("After switching on Screen & System Audio Recording, macOS only applies it once Meikipop "
                          "restarts: click Quit & Reopen." if not has_permission("screen") else "")


def check_at_startup():
    """Normal starts only: show the dialog when something is missing."""
    missing = missing_permissions()
    if missing:
        logger.info("Missing permissions: %s", ", ".join(p[1] for p in missing))
        PermissionsDialog(startup=True).exec()
