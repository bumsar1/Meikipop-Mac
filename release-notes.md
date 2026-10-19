New: **frequency lists and inflections in the popup, like Yomitan**, and a nicer Anki label.

- **Inflections:** under each word, how it was inflected, e.g. 書かれた → 🧩 passive « -た, or 食べられなかった → potential or passive « negative « -た. Hover a tag to read what the form means and how it is built.
- **Frequency lists:** the ranks from your Yomitan frequency dictionaries (JPDB, BCCWJ, ICR, Narou, VN, CC100, …), as name/rank badges.
- **Anki label:** green **＋ Anki**, grey **✓ In Anki**, orange **Anki offline · retry**. The ▶ pronunciation button matches.
- Extra dictionaries (e.g. daijirin) now start on their own line.

Both come from your own Yomitan through the local Yomitan API, fetched together with the lookup (about 25 ms), so the popup is drawn once and doesn't jump. Without Yomitan running, the popup still works and shows Meikipop's own inflection names. Turn them off under Settings → Show Frequency Lists (Yomitan) / Show Inflections.

Also includes the previous release: smaller Anki pictures, game-only reading, couch scanning without mouse moves, and starting Anki automatically.

Download **Meikipop-macOS.dmg**, open it, and drag **Meikipop.app** onto **Applications**. Quit the previous version before replacing it. Permissions from 2.0.5-mac.20261013.2 or later are kept.

The private Anki configuration is retained. Anki, AnkiConnect, Yomitan, and the local Yomitan API component are still required. The app is not Apple-notarized.

The packaged self-test passed. The popup was rendered with real Yomitan data (書かれた, 命じろ, 食べられなかった). Explanations need a mouse hover; they can't be opened with a controller yet. See Meikipop-START-HERE.txt for usage instructions.
