New: **controller support**, **visual novel mode**, **extra dictionaries**, and a **scan area that follows the game window**.

- **Controller lookups:** hold **LB** and use the **D-pad** to move word to word and line to line. **A** adds the word to Anki. Settings are in the menu bar under **Controller**.
- **Visual novel mode:** **X** advances text, or picks the outlined dialogue choice while LB is held. The **left stick** moves the mouse, **A/B** left/right-click (right-click usually opens Save/Load), and the **right stick** scrolls.
- **Extra dictionaries:** **Dictionaries…** in the menu bar imports Yomitan `.zip` dictionaries on top of JMdict.
- **Scan Area → Selected Window (Follows It):** no new region needed after moving the window.
- The popup now shows only the matched word (地元, not 地); turn on **Settings → Show Shorter Matches** to get the old list back.
- Fixed: the popup no longer flickers every five seconds while re-checking Anki.

Download **Meikipop-macOS.dmg**, open it, and drag **Meikipop.app** onto **Applications**. Quit the previous version before replacing it. macOS may ask again for Screen Recording and Accessibility permissions; visual novel mode needs Accessibility.

The private Anki configuration is retained. Anki, AnkiConnect, Yomitan, and the local Yomitan API component are still required. The app is not Apple-notarized.

The packaged OCR/dictionary/audio/controller self-test passed. Controller navigation and dialogue choices were confirmed in real use; mouse pointer control was tested with a simulated controller. See Meikipop-START-HERE.txt for usage instructions.
