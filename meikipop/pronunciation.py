"""Asynchronous pronunciation from the user's live Yomitan audio sources."""
import base64
import threading
from collections import OrderedDict
from PyQt6.QtCore import QObject, pyqtSignal, QBuffer, QByteArray, QIODevice, QUrl
from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer
from meikipop.mining import Miner, MiningError
from meikipop.config.config import config


def fetch_pronunciation(expression, reading):
    payload = Miner().yomitan('ankiFields', text=expression, type='term',
                             markers=['expression', 'reading', 'audio'],
                             maxEntries=32, includeMedia=True)
    for item in payload.get('audioMedia', []):
        if item.get('term') == expression and item.get('reading', '') == (reading or expression):
            return base64.b64decode(item['content'], validate=True), item['ankiFilename']
    raise MiningError('No pronunciation found in your Yomitan audio sources.')


class Pronunciation(QObject):
    ready = pyqtSignal(int, object, str)
    failed = pyqtSignal(int, str)
    message = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.output = QAudioOutput(self)
        self.set_volume(config.pronunciation_volume)
        self.player = QMediaPlayer(self)
        self.player.setAudioOutput(self.output)
        self.player.errorOccurred.connect(lambda *args: self.message.emit('Could not play audio: ' + self.player.errorString()))
        self.buffer = None
        self.generation = 0
        self.cache = OrderedDict()
        self.pending = None
        self.loading = False
        self.ready.connect(self._ready)
        self.failed.connect(self._failed)

    def set_volume(self, percent):
        self.volume_percent = max(0, min(100, int(percent)))
        config.pronunciation_volume = self.volume_percent
        self.output.setVolume(self.volume_percent / 100.0)

    def stop(self):
        self.generation += 1
        self.pending = None
        self.player.stop()

    def play(self, entry):
        self.stop()
        key = (entry.written_form, entry.reading)
        if key in self.cache:
            self.cache.move_to_end(key)
            self._play_bytes(*self.cache[key])
            return
        self.pending = (self.generation, key)
        self._start_pending()

    def _start_pending(self):
        if self.loading or self.pending is None:
            return
        generation, key = self.pending
        self.pending = None
        self.loading = True
        def work():
            try:
                data, name = fetch_pronunciation(*key)
                self.ready.emit(generation, (key, data), name)
            except Exception as e:
                self.failed.emit(generation, str(e))
        threading.Thread(target=work, name='YomitanPronunciation', daemon=True).start()

    def _ready(self, generation, payload, name):
        self.loading = False
        key, data = payload
        self.cache[key] = (data, name)
        while len(self.cache) > 64:
            self.cache.popitem(last=False)
        if generation == self.generation:
            self._play_bytes(data, name)
        self._start_pending()

    def _failed(self, generation, message):
        self.loading = False
        if generation == self.generation:
            self.message.emit('Pronunciation: ' + message)
        self._start_pending()

    def _play_bytes(self, data, name):
        self.player.stop()
        self.player.setSource(QUrl())
        if self.buffer is not None:
            self.buffer.close()
            self.buffer.deleteLater()
        self.buffer = QBuffer(self)
        self.buffer.setData(QByteArray(data))
        self.buffer.open(QIODevice.OpenModeFlag.ReadOnly)
        self.player.setSourceDevice(self.buffer, QUrl(name))
        self.player.play()
