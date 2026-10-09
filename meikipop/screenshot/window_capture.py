"""Capture the explicitly selected window, independently of keyboard focus."""
from dataclasses import dataclass
import hashlib
import os


@dataclass(frozen=True)
class WindowFrame:
    png: bytes
    digest: str
    window_id: int


class FrameParagraphs(list):
    def __init__(self, paragraphs, frame=None, error=''):
        super().__init__(paragraphs or [])
        self.window_frame = frame
        self.window_error = error


def choose_window(windows, pid, region, own_pid=None):
    """CG lists windows front-to-back; reject other apps and unrelated regions."""
    if pid == (own_pid if own_pid is not None else os.getpid()):
        raise RuntimeError('Aktivér spilvinduet før opslaget.')
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
    raise RuntimeError('OCR-området ligger ikke i det aktive vindue. Aktivér spillet eller vælg scanningsområdet igen.')


def encode_png(image):
    import Quartz
    from Foundation import NSMutableData
    data = NSMutableData.data()
    dest = Quartz.CGImageDestinationCreateWithData(data, 'public.png', 1, None)
    if dest is None:
        raise RuntimeError('Kunne ikke klargøre vinduesbilledet.')
    Quartz.CGImageDestinationAddImage(dest, image, None)
    if not Quartz.CGImageDestinationFinalize(dest):
        raise RuntimeError('Kunne ikke gemme vinduesbilledet som PNG.')
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


def capture_window(window_id, expected_pid=None):
    import Quartz
    if window_id is None:
        raise RuntimeError('Vælg et vindue via menulinjen → Vælg vindue til Anki-billeder.')
    windows = Quartz.CGWindowListCopyWindowInfo(
        Quartz.kCGWindowListOptionIncludingWindow, int(window_id))
    match = next((w for w in windows or [] if int(w.get('kCGWindowNumber', -1)) == int(window_id)), None)
    if match is None or (expected_pid is not None and match.get('kCGWindowOwnerPID') != expected_pid):
        raise RuntimeError('Det valgte vindue er lukket. Vælg spilvinduet igen via menulinjen.')
    if not match.get('kCGWindowIsOnscreen', True):
        raise RuntimeError('Det valgte vindue er minimeret eller på et andet skrivebord. Vis det, og prøv igen.')
    image = Quartz.CGWindowListCreateImage(
        Quartz.CGRectNull, Quartz.kCGWindowListOptionIncludingWindow, int(window_id),
        Quartz.kCGWindowImageBoundsIgnoreFraming | Quartz.kCGWindowImageBestResolution)
    if image is None or Quartz.CGImageGetWidth(image) == 0:
        raise RuntimeError('macOS kunne ikke tage vinduesbilledet. Kontrollér skærmoptagelsestilladelsen til Terminal, og genstart Meikipop.')
    png = encode_png(image)
    return WindowFrame(png, hashlib.sha256(png).hexdigest(), int(window_id))
