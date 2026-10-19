New: **reliable Anki cards, reading only the game, and couch mode that counts every line**.

- **Anki cards no longer fail on the picture:** the Picture field is now a WebP scaled to at most 1600 px (about 100 KB) instead of a 5–7 MB full-resolution PNG. The large uploads timed out, and a third of card additions failed.
- **Lighter scanning:** the card picture is only encoded when you add a card, not on every scan.
- **Only the game is read:** with Scan Area → Selected Window, and always in couch mode, Meikipop reads the game window's own picture instead of the screen. Windows on top of the game are never read, and a game hidden on another desktop isn't read at all. This also keeps VN Library's characters-read count clean.
- **Couch mode reads every line:** scanning continues without mouse movement; unchanged frames are skipped.
- **Anki starts by itself:** if Anki is closed when you add a card, Meikipop opens it in the background (a full-screen game keeps the screen) and adds the card once AnkiConnect answers.
- Fixed: error spam while waiting for the game window, and a startup race in reading the mouse position (now correct on every display).

Download **Meikipop-macOS.dmg**, open it, and drag **Meikipop.app** onto **Applications**. Quit the previous version before replacing it. Permissions from 2.0.5-mac.20261013.2 or later are kept; when updating from an older version, see the permissions section in Meikipop-START-HERE.txt.

The private Anki configuration is retained. Anki, AnkiConnect, Yomitan, and the local Yomitan API component are still required. The app is not Apple-notarized.

The packaged self-test passed, including WebP card pictures. Window-only reading and scanning without mouse movement were tested with a covered test game whose text changed while the mouse stood still. Card adding with the smaller picture was tested in unit tests, not yet with a real card. See Meikipop-START-HERE.txt for usage instructions.
