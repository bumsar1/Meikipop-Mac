New: **a read log for VN Library**, and **the popup stays out of OCR**.

- **Characters read in VN Library:** Meikipop now saves the text it recognises to `read-log/` in its data folder, so VN Library can count how many characters you've read per game and session. Turn it off under Settings → "Log recognised text for VN Library".
- **Popup kept out of OCR:** the dictionary popup is now invisible to Meikipop's own screenshots, like the word outline already was. Before, when the popup covered the game, its dictionary entries could be read as game text and ended up in the read log. The popup also no longer shows up in Anki screenshots or screen recordings.
- **Exit crash:** a crash when quitting is fixed.

Download **Meikipop-macOS.dmg**, open it, and drag **Meikipop.app** onto **Applications**. Quit the previous version before replacing it. Permissions carry over from the previous release.

The private Anki configuration is retained. Anki, AnkiConnect, Yomitan, and the local Yomitan API component are still required. The app is not Apple-notarized.

The packaged self-test and the unit tests passed. A test window with the new setting was confirmed to be left out of screen captures on macOS 27.
