New: **VN Library couch mode picks the game window automatically**, and **permissions now survive updates**.

- **Couch mode:** when VN Library starts a game from couch mode, Meikipop skips the window and region dialogs, finds the game's window by itself (also in full screen) and scans all of it. If Meikipop is already open, it switches to the new game. Normal starts still ask as before.
- **Popup over full-screen games:** the popup and the word outline now show on top of a game in its own full-screen Space.
- **Permissions that stick:** Meikipop is now signed with a stable certificate (the same as VN Library). Older builds looked like a new app to macOS after every update, so permissions shown as on silently stopped working.
- **Permissions…** in the menu bar shows what's missing, opens the right System Settings page, and can quit and reopen Meikipop. It also appears at startup when something is missing (not in couch mode).
- **Guide:** Meikipop-START-HERE.txt now starts with every permission to grant before you play.

**One-time step when updating:** in System Settings → Privacy & Security, remove the old Meikipop entries under **Screen & System Audio Recording** and **Accessibility** with −, then open Meikipop and use **Permissions…** to grant them again. Future updates keep them.

Download **Meikipop-macOS.dmg**, open it, and drag **Meikipop.app** onto **Applications**. Quit the previous version before replacing it.

The private Anki configuration is retained. Anki, AnkiConnect, Yomitan, and the local Yomitan API component are still required. The app is not Apple-notarized.

The packaged self-test passed. Couch mode was tested end to end with a test game started from VN Library (window found in full screen without dialogs, and handoff to a running Meikipop); OCR in full screen was confirmed once. See Meikipop-START-HERE.txt for usage instructions.
