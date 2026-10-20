New: **engine text instead of OCR** for games with a text hook.

- Games started from VN Library with its **Text hook** switch on send the text they show to `ws://127.0.0.1:6677`, with each character's position on screen. This covers KiriKiri Player 0.3.15 and BGI Player 0.1.9 (bundled with VN Library 1.63), and siglus_engine builds that include the hook. Meikipop connects to it on its own.
- **Shift over a line looks it up at once.** There is no screenshot and no OCR, so there are no misread characters. The Anki sentence is the exact line.
- **Menus and choices** are still read with OCR when you hold Shift over them. Games without the hook work exactly as before.
- **Read log:** while a game is hooked, only the engine's lines are logged, once each and with the game's own process id. OCR misreads of menus and notices (such as クイックセーブしました) no longer count as text read in VN Library.

Also includes the previous release: frequency lists and inflections in the popup, and the nicer Anki label.

Download **Meikipop-macOS.dmg**, open it, and drag **Meikipop.app** onto **Applications**. Quit the previous version before replacing it. Permissions from 2.0.5-mac.20261013.2 or later are kept.

The private Anki configuration is retained. Anki, AnkiConnect, Yomitan, and the local Yomitan API component are still required. The app is not Apple-notarized.

Tested:
- The packaged self-test passed, and the packaged app connected to the hook of a running game.
- A unit test and a run against Summer Pockets checked that a point on a character's box returns that character and the exact sentence.

Not tested: holding Shift with a real mouse over a hooked game. See Meikipop-START-HERE.txt for usage instructions.
