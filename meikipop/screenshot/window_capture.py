"""Capture the explicitly selected window, independently of keyboard focus."""
from functools import cached_property
import hashlib
import io
import itertools
import os

CARD_IMAGE_MAX_SIDE = 1600   # pixels; a Retina full-screen capture is ~3600 wide
CARD_IMAGE_QUALITY = 80      # WebP: ~100 KB per card instead of a 5–7 MB PNG

_serials = itertools.count(1)


class WindowFrame:
    """One capture of the selected window, kept as the raw CGImage. Encoding is deferred
    until something needs it (a new card, the selector preview), since it is costly and
    most captures are never used."""

    def __init__(self, image, window_id):
        self.image = image
        self.window_id = int(window_id)
        self.digest = f"{self.window_id}-{next(_serials)}"  # identifies this capture, not its content

    @cached_property
    def pixels(self):
        """(raw BGRA bytes, width, height, bytes per row)."""
        import Quartz
        data = Quartz.CGDataProviderCopyData(Quartz.CGImageGetDataProvider(self.image))
        return (bytes(data), Quartz.CGImageGetWidth(self.image), Quartz.CGImageGetHeight(self.image),
                Quartz.CGImageGetBytesPerRow(self.image))

    def pil(self):
        from PIL import Image
        raw, w, h, stride = self.pixels
        # CGWindowListCreateImage gives 32-bit little-endian premultiplied-first pixels: B, G, R, A in memory.
        return Image.frombuffer('RGBA', (w, h), raw, 'raw', 'BGRA', stride, 1).convert('RGB')

    @cached_property
    def png(self):
        return encode_png(self.image)

    def card_image(self):
        """(bytes, file extension) for the Anki Picture field: scaled down and WebP-compressed."""
        image = self.pil()
        image.thumbnail((CARD_IMAGE_MAX_SIDE, CARD_IMAGE_MAX_SIDE))
        out = io.BytesIO()
        image.save(out, 'WEBP', quality=CARD_IMAGE_QUALITY, method=4)
        return out.getvalue(), 'webp'


class FrameParagraphs(list):
    def __init__(self, paragraphs, frame=None, error=''):
        super().__init__(paragraphs or [])
        self.window_frame = frame
        self.window_error = error


def choose_window(windows, pid, region, own_pid=None):
    """CG lists windows front-to-back; reject other apps and unrelated regions."""
    if pid == (own_pid if own_pid is not None else os.getpid()):
        raise RuntimeError('Activate the game window before looking up a word.')
    x,y,w,h = (region[k] for k in ('left','top','width','height'))
    for window in windows:
        if window.get('kCGWindowOwnerPID') != pid or window.get('kCGWindowLayer') != 0:
            continue
        bounds = window.get('kCGWindowBounds', {})
        bx,by,bw,bh = (bounds.get(k,0) for k in ('X','Y','Width','Height'))
        if bw <= 1 or bh <= 1 or window.get('kCGWindowAlpha',1) <= 0:
            continue
        overlap = max(0,min(x+w,bx+bw)-max(x,bx)) * max(0,min(y+h,by+bh)-max(y,by))
        if overlap >= 0.9*w*h:
            return window['kCGWindowNumber']
    raise RuntimeError('The OCR region is outside the active window. Activate the game or select the scanning region again.')


def encode_png(image):
    import Quartz
    from Foundation import NSMutableData
    data = NSMutableData.data()
    dest = Quartz.CGImageDestinationCreateWithData(data, 'public.png', 1, None)
    if dest is None:
        raise RuntimeError('Could not prepare the window screenshot.')
    Quartz.CGImageDestinationAddImage(dest, image, None)
    if not Quartz.CGImageDestinationFinalize(dest):
        raise RuntimeError('Could not save the window screenshot as PNG.')
    return bytes(data)


def list_windows():
    import Quartz
    windows = Quartz.CGWindowListCopyWindowInfo(
        Quartz.kCGWindowListOptionOnScreenOnly | Quartz.kCGWindowListExcludeDesktopElements,
        Quartz.kCGNullWindowID)
    result = []
    for window in windows or []:
        bounds = window.get('kCGWindowBounds', {})
        if (window.get('kCGWindowOwnerPID') == os.getpid() or
                window.get('kCGWindowLayer') != 0 or
                bounds.get('Width', 0) < 100 or bounds.get('Height', 0) < 60 or
                window.get('kCGWindowAlpha', 1) <= 0):
            continue
        result.append({'id': int(window['kCGWindowNumber']),
                       'pid': int(window['kCGWindowOwnerPID']),
                       'app': str(window.get('kCGWindowOwnerName', 'Program')),
                       'title': str(window.get('kCGWindowName', '')),
                       'bounds': dict(bounds)})
    return result


def process_tree(pid):
    """pid plus all its descendants (a launcher shell -> wine -> the game)."""
    import subprocess
    pids, todo = [], [int(pid)]
    while todo:
        p = todo.pop()
        pids.append(p)
        try:
            out = subprocess.run(['/usr/bin/pgrep', '-P', str(p)], capture_output=True, text=True, timeout=2).stdout
        except Exception:
            out = ''
        todo.extend(int(c) for c in out.split() if c.isdigit() and int(c) not in pids)
    return pids


def find_game_window(pid):
    """The largest normal window owned by pid or its children, on any desktop (including a
    full-screen Space that is not currently shown). Returns a list_windows()-style dict or None."""
    import Quartz
    pids = set(process_tree(pid))
    windows = Quartz.CGWindowListCopyWindowInfo(Quartz.kCGWindowListOptionAll, Quartz.kCGNullWindowID)
    best = None
    for window in windows or []:
        bounds = window.get('kCGWindowBounds', {})
        w, h = bounds.get('Width', 0), bounds.get('Height', 0)
        if (window.get('kCGWindowOwnerPID') not in pids or window.get('kCGWindowLayer') != 0 or
                w < 200 or h < 150 or window.get('kCGWindowAlpha', 1) <= 0):
            continue
        if best is None or w * h > best[0]:
            best = (w * h, {'id': int(window['kCGWindowNumber']),
                            'pid': int(window['kCGWindowOwnerPID']),
                            'app': str(window.get('kCGWindowOwnerName', 'Game')),
                            'title': str(window.get('kCGWindowName', '')),
                            'bounds': dict(bounds)})
    return best[1] if best else None


def window_bounds(window_id):
    """Global (left, top, width, height) of the window in points; None if it is not on screen."""
    import Quartz
    windows = Quartz.CGWindowListCopyWindowInfo(
        Quartz.kCGWindowListOptionIncludingWindow, int(window_id))
    match = next((w for w in windows or [] if int(w.get('kCGWindowNumber', -1)) == int(window_id)), None)
    if match is None or not match.get('kCGWindowIsOnscreen', True):
        return None
    b = match.get('kCGWindowBounds', {})
    x, y, w, h = (int(b.get(k, 0)) for k in ('X', 'Y', 'Width', 'Height'))
    return (x, y, w, h) if w >= 10 and h >= 10 else None


def capture_window(window_id, expected_pid=None):
    import Quartz
    if window_id is None:
        raise RuntimeError('Select a window from the menu bar → Select Window for Anki Screenshots.')
    windows = Quartz.CGWindowListCopyWindowInfo(
        Quartz.kCGWindowListOptionIncludingWindow, int(window_id))
    match = next((w for w in windows or [] if int(w.get('kCGWindowNumber', -1)) == int(window_id)), None)
    if match is None or (expected_pid is not None and match.get('kCGWindowOwnerPID') != expected_pid):
        raise RuntimeError('The selected window is closed. Select the game window again from the menu bar.')
    if not match.get('kCGWindowIsOnscreen', True):
        raise RuntimeError('The selected window is minimized or on another desktop. Show it and try again.')
    image = Quartz.CGWindowListCreateImage(
        Quartz.CGRectNull, Quartz.kCGWindowListOptionIncludingWindow, int(window_id),
        Quartz.kCGWindowImageBoundsIgnoreFraming | Quartz.kCGWindowImageBestResolution)
    if image is None or Quartz.CGImageGetWidth(image) == 0:
        raise RuntimeError('macOS could not capture the window. Check Screen Recording permission for Meikipop (or Terminal when using the script), then restart Meikipop.')
    return WindowFrame(image, window_id)
