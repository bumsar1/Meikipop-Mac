New: existing-word indicators in the popup. Words already in the configured Anki deck show **✓ Already in Anki** and cannot be added from the popup. Checks run in the background, successful additions update immediately, and unavailable Anki connections are shown explicitly. A fresh check also runs before adding.

Private backup of Meikipop for Apple Silicon Macs.

Download **Meikipop-macOS.zip**, extract it, and move **Meikipop.app** to Applications. The app runs in the menu bar; choose **Quit** to exit. See **Meikipop-START-HERE.txt** for setup and usage instructions.

Includes Shift lookups, Yomitan pronunciation, Anki field mapping, window screenshots, and an optional 5–30 second game audio buffer. Game audio is off at launch. Enable it in the game audio submenu to fill `SentenceAudio`; Yomitan's word pronunciation remains in `ExpressionAudio`.

The release retains the existing private Anki configuration. Anki, AnkiConnect, Yomitan, and the local Yomitan API component are still required. The app interface, messages, and permission descriptions are in English. The app is not Apple-notarized.

The packaged self-test and synthetic audio tests passed. Recording from a real game with macOS permissions still needs testing on your Mac.
