# Meikipop for macOS

A private backup of a customized Meikipop 2.0.5 for Apple Silicon, with Japanese OCR, Shift lookups, Yomitan/Anki integration, window screenshots, and optional game audio.

## Download

Download **Meikipop-macOS.dmg** from [Releases](https://github.com/bumsar1/Meikipop-Mac/releases/latest), open it, and drag **Meikipop.app** onto the **Applications** shortcut. Eject the disk image and launch Meikipop from Applications. Quit the previous version before replacing it.

The app runs in the menu bar. Choose **Quit** to exit or **Pause meikipop** to pause scanning and audio capture. macOS may request screen/audio recording and Accessibility permissions.

The release includes Python, local OCR models, a dictionary, and the existing personal Anki field mapping. It is a private backup for the original Mac setup, not a general-purpose installer. Keep Anki with AnkiConnect and the browser with Yomitan API open. The separately installed Yomitan API component still uses the existing Python installation; this app does not install that component.

## Usage

1. Select the game window, check the screenshot preview, and select the text region.
2. Hold **Shift** over a word to look it up and hear its pronunciation.
3. Keep holding Shift and click the word or **+ Anki** to add a card.
4. Optional: open the game audio submenu in the menu bar and enable sentence audio. Select 5, 10, 15, or 30 seconds. Wait for the spoken line to finish before adding the word.

The app interface is in English. See [USAGE.txt](USAGE.txt) for additional details.

Game audio is off at every launch. It captures audio from the selected game's application, including music and effects; it does not automatically detect sentence boundaries. The microphone is not used. The buffer stays in memory and is cleared when capture stops, the app pauses, or the selected window changes. Added clips go into `SentenceAudio`; Yomitan's word pronunciation stays in `ExpressionAudio`.

## Controller lookups

Connect a controller (Xbox, PlayStation, Switch Pro or other MFi pad) and hold **LB**. Meikipop scans the text region, outlines the first word, and shows its popup.

- **D-pad left/right** moves word to word; **up/down** moves to the line above or below. Holding repeats.
- **A** adds the top entry to Anki; **X** replays the pronunciation.
- Release **LB** to close.

The menu bar **Controller** submenu changes the button (LB, RB, LT, RT, L3, R3, Back), switches between hold and press-on/press-off (then **B** also closes), and shows the connected controller. **Pause Game Input While Looking Up** briefly brings Meikipop to the front, so games that read the controller through macOS stop reacting while you navigate. The game still sees the lookup button press itself.

**Visual Novel Mode** (Controller submenu) makes **X** left-click the middle of the scan area, like clicking the text box, so you can advance text in games without controller support. It works with or without the lookup button held; while looking up, the popup closes and the new line is read automatically. For dialogue choices, hold the lookup button, move the outline onto the choice and press **X**: it clicks the outlined word instead. The scan area must cover the choices, so use **Scan Area → Selected Window**. Pronunciation replay moves to **Y**. The **left stick** moves the mouse pointer (further tilt is faster), **A** left-clicks and **B** right-clicks where it points (in most visual novels a right-click opens the Save/Load menu), and the **right stick** scrolls up/down, e.g. in the backlog. macOS asks for Accessibility permission the first time.

Words are split by the longest dictionary match, the same way Shift lookups pick a word.

## Extra dictionaries

Choose **Dictionaries…** in the menu bar and add Yomitan dictionary `.zip` files (for example a monolingual or name dictionary). They are added on top of the built-in JMdict and are labelled with their name in the popup. Kanji and frequency-only dictionaries are not supported. Installed dictionaries live in `~/Library/Application Support/meikipop/user_dicts`.

## Starting from VN Library couch mode

When VN Library starts a game from couch mode, it starts Meikipop with `--game-pid <pid>` (or, if Meikipop is already running, sends it the game). Meikipop then skips the window and region dialogs, waits for that game's window, including one in its own full-screen Space, and scans the whole window. Nothing is saved to your settings; a normal start still asks as before.

## Scan area that follows the game

Choose **Scan Area → Selected Window (Follows It)** in the menu bar. Meikipop then scans the window picked under **Select Window for Anki Screenshots…** and re-reads its position before every scan, so moving or resizing the window needs no new region. If the window is minimized, the last position is kept.

## Shorter matches

By default the popup lists only the word that was matched (地元), plus the kanji card. Turn on **Settings → Show Shorter Matches** to also list shorter words such as 地.

## Pronunciation volume

Choose **Pronunciation Volume…** from the menu bar to adjust word pronunciation from 0% (muted) to 100%. The default is 50%, increased from the previous fixed 10%. Changes apply immediately and are saved when the dialog closes. This adjusts playback in Meikipop; it does not rewrite audio attached to Anki cards or change the game audio buffer.

## Existing words in Anki

Each word shows **Checking Anki…**, **✓ Already in Anki**, or **＋ Anki**. Existing words have no add link, while pronunciation playback remains available. The check matches the complete expression in the configured deck (including subdecks), using the dictionary headword for inflected text. It does not search the whole sentence or compare readings.

Checks run in the background and are cached for up to five seconds. A successful addition updates the indicator immediately. **Anki unavailable · retry** means the status could not be verified. A fresh check before adding, plus Anki's existing duplicate validation, prevents stale status from being the only protection. Keep Anki and AnkiConnect running.

## Source and building

The source does not include the personal configuration. Copy `mining-settings.example.json` to `mining-settings.json` and adapt it to your Yomitan export. The card format name, type, deck, model, and fields must match the active profile exactly; the example values are placeholders. Some app messages still reference the original Bilingual profile.

Install `requirements.txt` with Python 3.13 on an Apple Silicon Mac and follow [app-build/BUILD.txt](app-build/BUILD.txt). Xcode Command Line Tools are required to compile the Swift audio helper. Building requires an existing local Meikipop dictionary and downloaded MeikiOCR models. These and the local configuration are included in the resulting app.

The app is locally ad hoc-signed, not Apple-notarized. Log file: `~/Library/Logs/Meikipop/app.log`.

## Validation

The packaged OCR/dictionary test, the audio helper's synthetic PCM test, buffer limits, menu controls, and simulated Anki media uploads passed. Recording from a real game with the app's macOS permissions still needs to be tested. No test cards were created in Anki.

## Credits and license

Based on [rtr46/meikipop](https://github.com/rtr46/meikipop), version 2.0.5, under GPL-3.0; see [LICENSE](LICENSE). This variant is not an official upstream release. Third-party licenses are also included in the app under `Contents/Resources/licenses`. [Yomitan API](https://github.com/yomidevs/yomitan-api) provides the local integration.

Customizations include Yomitan/Anki fields and media, Shift behavior, pronunciation playback, explicit window selection, macOS packaging, and a ScreenCaptureKit audio buffer.
