"""Standalone desktop entry; --self-test performs no capture or Anki writes."""
import os
import sys
from pathlib import Path
import traceback

bundle = Path(getattr(sys, '_MEIPASS', Path(__file__).parent))
self_test = '--self-test' in sys.argv
if self_test:
    os.environ['QT_QPA_PLATFORM'] = 'offscreen'
else:
    logs = Path.home() / 'Library/Logs/Meikipop'
    logs.mkdir(parents=True, exist_ok=True)
    log = logs / 'app.log'
    if log.exists() and log.stat().st_size > 2_000_000:
        log.replace(log.with_suffix('.previous.log'))
    sys.stdout = sys.stderr = log.open('a', buffering=1)

try:
    import meikiocr.ocr as engine
    def bundled_model(repo_id, filename):
        path = bundle / 'models' / filename
        if not path.is_file():
            raise RuntimeError(f'The OCR model is missing from the app: {filename}')
        return str(path)
    engine._get_model_path = bundled_model
    from meikipop.utils.paths import paths
    if not Path(paths.dictionary_path).exists():
        import shutil
        shutil.copy2(bundle / 'dictionary.pkl', paths.dictionary_path)
    if self_test:
        import json
        from PyQt6.QtWidgets import QApplication
        from PyQt6.QtMultimedia import QMediaPlayer
        from PIL import Image, ImageDraw, ImageFont
        from meikipop.main import SharedState
        from meikipop.dictionary.lookup import Lookup
        from meikipop.ocr.ocr import OcrProcessor
        app = QApplication([])
        from meikipop.config.config import config
        config.save = lambda: None  # Self-test must not change user settings.
        state = SharedState()
        from meikipop.dictionary.customdict import Dictionary
        packaged_dictionary = Dictionary()
        assert packaged_dictionary.load_dictionary(str(bundle / 'dictionary.pkl'))
        lookup = Lookup(state, None)
        assert lookup.lookup('青空'), 'Dictionary lookup failed'
        providers = OcrProcessor._discover_providers(object())
        assert 'meikiocr (local)' in providers, providers
        ocr = providers['meikiocr (local)']()
        assert ocr.ocr_client is not None
        pic = Image.new('RGB', (800, 150), 'white')
        font = ImageFont.truetype('/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc', 48)
        ImageDraw.Draw(pic).text((30,30), '青空が見える。', font=font, fill='black')
        result = ocr.scan(pic)
        assert result, 'OCR returned no paragraphs'
        from meikipop.mining import Miner
        miner = Miner()
        assert miner.settings['profile'] == 'Bilingual'
        from meikipop.screenshot.window_capture import encode_png
        import Quartz
        import pynput.mouse._darwin
        assert Quartz.CGWindowListCreateImage
        from meikipop.controller import Gamepad
        assert Gamepad().available, 'Controller support missing'
        from ApplicationServices import AXIsProcessTrustedWithOptions
        player = QMediaPlayer()
        import subprocess, struct
        from meikipop.game_audio import AudioRing
        assert not state.game_audio.enabled
        packet = subprocess.check_output([str(bundle / 'native/GameAudio'), '--self-test'])
        size, = struct.unpack('<I', packet[:4])
        assert size == len(packet) - 4
        ring = AudioRing(); ring.append(packet[4:])
        assert ring.wav(15).startswith(b'RIFF')
        report = {'success':True,'frozen':bool(getattr(sys,'frozen',False)), 'providers':list(providers), 'ocr_paragraphs':len(result), 'profile':miner.settings['profile']}
        target = Path(sys.argv[sys.argv.index('--self-test')+1])
        target.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        from meikipop.main import main
        main()
except Exception:
    traceback.print_exc()
    if not self_test:
        from PyQt6.QtWidgets import QApplication, QMessageBox
        app = QApplication.instance() or QApplication([])
        QMessageBox.critical(None, 'Meikipop could not start', f'An error occurred. The log file is here:\n{log}\n\n{traceback.format_exc()[-1200:]}')
    raise
