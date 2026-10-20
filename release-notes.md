**First public release.** Meikipop for macOS is now open to everyone (GPL-3.0, based on [rtr46/meikipop](https://github.com/rtr46/meikipop)).

- **Engine text instead of OCR.** Games started from [VN Library](https://github.com/bumsar1/VNLibrary) 1.64 or later with its Text hook switch on send the text they show to `ws://127.0.0.1:6677`. This covers its bundled Siglus, KiriKiri and BGI engines. Shift over a line looks it up at once, without OCR, and the Anki sentence is the exact line. Menus and choices still use OCR on Shift. Other games work as before, with local OCR.
- **Your own Anki setup.** The app bundles a neutral example. To add cards, copy [mining-settings.example.json](https://github.com/bumsar1/Meikipop-Mac/blob/main/mining-settings.example.json) to `~/Library/Application Support/meikipop/mining-settings.json` and fill in your deck, note type and fields. Until then, adding a card tells you where to put it; lookups work regardless.

Download **Meikipop-macOS.dmg**, open it, and drag **Meikipop.app** onto **Applications**. Quit the previous version before replacing it.

Requirements:
- Apple Silicon Mac.
- For cards and pronunciation: Anki with AnkiConnect, and Yomitan with the separately installed Yomitan API component.

The app is not Apple-notarized: the first time, right-click it → **Open**. Then grant Screen Recording and Accessibility under **Permissions…** in the menu bar menu. The packaged self-test passed. See Meikipop-START-HERE.txt for usage instructions.
