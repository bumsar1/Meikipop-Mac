# Meikipop til Mac

Privat backup af en tilpasset Meikipop 2.0.5 til Apple Silicon: japansk OCR, Shift-opslag, Yomitan/Anki, vinduesbilleder og valgfri spillyd.

## Hent appen

Hent **Meikipop-Mac-med-spillyd.zip** fra [Releases](https://github.com/bumsar1/Meikipop-Mac/releases/latest), pak den ud, og flyt Meikipop.app til Programmer. Afslut den gamle app før udskiftning.

Appen kører i menulinjen. Vælg **Quit** for at afslutte eller **Pause meikipop** for at stoppe scanning og lyd midlertidigt. macOS kan bede om tilladelse til skærm-/lydoptagelse og Tilgængelighed.

Release-appen indeholder Python, lokale OCR-modeller, ordbog og den eksisterende personlige Anki-feltmapping. Den er en privat backup til den oprindelige Mac-opsætning, ikke en generel installer. Anki med AnkiConnect og browseren med Yomitan API skal stadig være åbne. Den separat installerede Yomitan API-komponent bruger den eksisterende Python-installation; den installeres ikke af appen.

## Brug

1. Vælg spilvinduet, kontrollér prøvebilledet, og markér tekstområdet.
2. Hold Shift over et ord for opslag og udtale.
3. Hold fortsat Shift, og klik på ordet eller **+ Anki** for at tilføje.
4. Valgfrit: aktivér **Spillyd til Anki → Medtag spillyd i SentenceAudio**. Vælg 5, 10, 15 eller 30 sekunder. Lad replikken afslutte, før du tilføjer ordet.

Spillyd er slået fra ved hver opstart. Bufferen omfatter programmets lyd, også musik og effekter; der er ingen automatisk sætningsafgrænsning. Mikrofonen bruges ikke. Bufferen holdes i hukommelsen og tømmes ved stop, pause og vinduesskift. Ved tilføjelse gemmes klippet i `SentenceAudio`; Yomitans ordudtale bliver i `ExpressionAudio`.

## Kilde og bygning

Kildekoden indeholder ikke den personlige konfiguration. Kopiér `mining-settings.example.json` til `mining-settings.json`, og tilpas den til Yomitan-eksporten. Kortformatets navn, type, deck, model og felter skal svare præcis til den aktive profil; eksempelværdierne er ikke en færdig opsætning. Nogle brugerbeskeder nævner fortsat den oprindelige Bilingual-profil.

Installer `requirements.txt` i Python 3.13 på en Apple Silicon-Mac, og følg `app-build/BUILD.txt`. Xcode Command Line Tools kræves for Swift-lydhjælperen. Bygningen kræver en lokal Meikipop-ordbog og downloadede MeikiOCR-modeller. Bygningen medtager disse og den lokale konfiguration i appen.

Appen er lokalt ad hoc-signeret, ikke Apple-notariseret. Fejllog: `~/Library/Logs/Meikipop/app.log`.

## Validering

Pakket OCR-/ordbogstest, lydhjælperens syntetiske PCM-test, buffergrænser, menubetjening og simuleret Anki-medietilføjelse er bestået. Optagelsen fra et rigtigt spil med appens macOS-tilladelser skal stadig afprøves. Ingen testkort blev oprettet i Anki.

## Oprindelse og licens

Baseret på [rtr46/meikipop](https://github.com/rtr46/meikipop), version 2.0.5, GPL-3.0; se [LICENSE](LICENSE). Denne variant er ikke en officiel upstream-release. Tredjepartslicenser findes også i appens `Contents/Resources/licenses`. Yomitan API: https://github.com/yomidevs/yomitan-api.

Tilpasninger: Yomitan/Anki-felter og medier, Shift-adfærd, udtale, eksplicit vinduesvalg, macOS-appbygning og ScreenCaptureKit-lydbuffer.
