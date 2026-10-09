"""Opt-in, application-filtered game audio. Bounded memory; no continuous disk recording."""
from collections import deque
from pathlib import Path
import hashlib
import io
import struct
import subprocess
import sys
import threading
import time
import wave

RATE = 24000

class AudioRing:
    def __init__(self):
        self.chunks = deque()
        self.size = 0
        self.last = 0.0
        self.lock = threading.Lock()

    def append(self, pcm):
        with self.lock:
            self.chunks.append(pcm)
            self.size += len(pcm)
            self.last = time.monotonic()
            limit = RATE * 2 * 30
            while self.size > limit:
                first = self.chunks.popleft()
                excess = self.size - limit
                if len(first) > excess:
                    self.chunks.appendleft(first[excess:])
                    self.size -= excess
                else:
                    self.size -= len(first)

    def wav(self, seconds):
        with self.lock:
            if time.monotonic() - self.last > 2:
                raise RuntimeError('No recent game audio. Check the window and audio permission, or disable game audio.')
            pcm = b''.join(self.chunks)[-int(seconds * RATE * 2):]
        if len(pcm) < RATE:
            raise RuntimeError('The audio buffer is not ready. Let the game play the line first.')
        if max((abs(x[0]) for x in struct.iter_unpack('<h', pcm)), default=0) < 50:
            raise RuntimeError('The audio buffer is silent. Play the line in the game, or disable game audio.')
        target = io.BytesIO()
        with wave.open(target, 'wb') as f:
            f.setnchannels(1); f.setsampwidth(2); f.setframerate(RATE); f.writeframes(pcm)
        return target.getvalue()

class GameAudio:
    def __init__(self):
        self.enabled = False  # Always requires opt-in after launching.
        self.seconds = 15
        self.process = None
        self.ring = AudioRing()
        self.target = None
        self.error = ''

    def stop(self):
        process, self.process = self.process, None
        if process is not None:
            process.terminate()
            try: process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                process.kill(); process.wait()
        self.ring = AudioRing()
        self.target = None

    def start(self, pid, window):
        self.stop()
        self.error = ''
        if not self.enabled:
            return
        root = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent.parent))
        helper = root / 'native' / 'GameAudio'
        try:
            process = subprocess.Popen([str(helper), str(pid), str(window)], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        except OSError as e:
            self.error = 'Could not start game audio: ' + str(e)
            return
        self.process = process
        self.target = (pid, window)
        ring = self.ring
        def read_exact(n):
            data = bytearray()
            while len(data) < n:
                part = process.stdout.read(n - len(data))
                if not part: raise EOFError()
                data.extend(part)
            return bytes(data)
        def read():
            try:
                while True:
                    size, = struct.unpack('<I', read_exact(4))
                    if size == 0 or size > RATE * 2 * 5 or size % 2:
                        raise RuntimeError('Invalid audio format')
                    ring.append(read_exact(size))
            except EOFError:
                pass
            except Exception as e:
                if self.process is process: self.error = str(e)
                if process.poll() is None: process.terminate()
            finally:
                process.stdout.close()
        def errors():
            message = process.stderr.read(8192).decode('utf-8', errors='replace').strip()
            if self.process is process and message:
                self.error = 'Game audio: ' + message
            process.stderr.close()
        threading.Thread(target=read, daemon=True, name='GameAudioBuffer').start()
        threading.Thread(target=errors, daemon=True, name='GameAudioErrors').start()

    def snapshot(self, window):
        if not self.enabled: return None
        if self.error: raise RuntimeError(self.error)
        if not self.process or self.process.poll() is not None:
            raise RuntimeError('Game audio has stopped. Toggle it off and on, and check the macOS audio permission.')
        if not self.target or self.target[1] != window:
            raise RuntimeError('The audio source window has changed. Look up the word again.')
        return self.ring.wav(self.seconds)

    def status(self):
        if not self.enabled: return 'Off'
        if self.error: return self.error[:160]
        if not self.process or self.process.poll() is not None: return 'Not recording – toggle off and on to retry'
        if time.monotonic() - self.ring.last > 2: return 'Waiting for audio / macOS permission…'
        return f'Buffer: {min(self.seconds, self.ring.size / (RATE * 2)):.1f} sec · selected game only'
