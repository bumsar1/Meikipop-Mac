Bug fix release: **Meikipop no longer crashes when you open its menu bar menu** on macOS 27.

- Fixed: clicking the Meikipop icon in the menu bar could quit the app. This was a Qt bug on macOS 27 (Qt reads the click count of an event that is no longer a mouse click); the affected callback is now disabled.
- Fixed: opening the menu bar menu no longer pauses or resumes Meikipop by itself.
- Fixed: a rare crash when quitting, caused by ONNX Runtime's telemetry thread. Telemetry is now turned off.

Includes everything from the previous release: controller lookups, visual novel mode, extra Yomitan dictionaries and the scan area that follows the game window.

Download **Meikipop-macOS.dmg**, open it, and drag **Meikipop.app** onto **Applications**. Quit the previous version before replacing it. macOS may ask again for Screen Recording and Accessibility permissions.

The private Anki configuration is retained. Anki, AnkiConnect, Yomitan, and the local Yomitan API component are still required. The app is not Apple-notarized.

The packaged OCR/dictionary/audio/controller self-test passed. The crash cause was confirmed against the crash reports; the fix was tested in isolation, not by clicking the real menu bar. See Meikipop-START-HERE.txt for usage instructions.
