"""Screenshot permission and metadata policy, not a fabricated capture service.

Public ABI: VitaSDK psp2/screenshot.h and db/360/SceScreenShot.yml. Vita3K's
module currently leaves these functions unimplemented; no code is copied.
"""
import hashlib
from pathlib import Path
import struct
import threading

LIBRARY = 'f26fc97d'
INVALID_ARGUMENT = 0x80102f01
FILE_NOT_FOUND = 0x80102f03
NOT_SUPPORTED_FORMAT = 0x80102f04
APIS = {0x76e674d1: 'enable', 0x50ae9ff9: 'disable', 0x05db59c7: 'set_param', 0x7061665b: 'set_overlay'}


class OverlayFormatError(ValueError):pass


class ScreenShotPolicy:
    def __init__(self, session):
        self.session = session
        self.lock = threading.RLock()
        # Do not assert the firmware's unspecified default permission.
        self.enabled = None
        self.parameters = None
        self.overlay = None
        self.overlay_pixels = None
        self.trace = []

    def _read(self, address, size):
        offset = address - self.session.base
        if not address or offset < 0 or offset + size > len(self.session.memory):
            raise ValueError('screenshot parameter outside guest memory')
        return bytes(self.session.memory[offset:offset + size])

    def _text(self, address, capacity):
        # Null metadata pointers are retained as unspecified fields; this
        # compatibility policy does not invent titles from host state.
        if not address:
            return None
        if address & 3:
            raise ValueError('unaligned SceWChar32 string')
        points = []
        for index in range(capacity):
            point = struct.unpack('<I', self._read(address + index * 4, 4))[0]
            if not point:
                return ''.join(points)
            if point > 0x10ffff or 0xd800 <= point <= 0xdfff:
                raise ValueError('invalid Unicode scalar')
            points.append(chr(point))
        raise ValueError('unterminated screenshot metadata')

    def _overlay(self, r):
        path_bytes = bytearray()
        for index in range(1024):
            value = self._read(int(r[0])+index, 1)[0]
            if not value:break
            path_bytes.append(value)
        else:raise ValueError('unterminated overlay path')
        path = path_bytes.decode('utf-8')
        if not path.startswith('app0:/') or '\\' in path:
            raise ValueError('overlay path must be read-only app0')
        parts = path[6:].split('/')
        if not parts or any(part in ('', '.', '..') for part in parts):
            raise ValueError('invalid overlay path')
        assets = getattr(self.session, 'assets', None)
        if assets is None:raise FileNotFoundError('app0 unavailable')
        root = Path(assets).resolve()
        target = root.joinpath(*parts)
        if not target.resolve().is_relative_to(root):raise ValueError('overlay escapes app0')
        # Do not follow symlink components even when they resolve inside app0.
        cursor = root
        for part in parts:
            cursor = cursor/part
            if cursor.is_symlink():raise ValueError('overlay symlink unsupported')
        from .screenshot_png import decode_rgba8,MAX_BYTES
        with target.open('rb') as stream:raw = stream.read(MAX_BYTES+1)
        try:width,height,pixels = decode_rgba8(raw)
        except ValueError as error:raise OverlayFormatError(str(error)) from error
        # The public ABI uses signed offsets and does not require the entire
        # image to fit inside the framebuffer. Original startup deliberately
        # chooses positions that extend beyond960x544. Retain offsets; a future
        # capture compositor must clip before indexing pixel storage.
        x,y = (struct.unpack('<i',struct.pack('<I',int(r[index])&0xffffffff))[0] for index in (1,2))
        self.overlay = {'path': path, 'width': width, 'height': height,
                        'offset_x': x, 'offset_y': y,
                        'source_sha256': hashlib.sha256(raw).hexdigest(),
                        'rgba_sha256': hashlib.sha256(pixels).hexdigest()}
        self.overlay_pixels = pixels

    def invoke(self, nid, r):
        with self.lock:
            if nid not in APIS:
                raise ValueError('unsupported SceScreenShot NID')
            result = 0
            if nid == 0x76e674d1:
                self.enabled = True
            elif nid == 0x50ae9ff9:
                self.enabled = False
            elif nid == 0x7061665b:
                try:
                    self._overlay(r)
                except FileNotFoundError:
                    result = FILE_NOT_FOUND
                except OverlayFormatError:
                    result = NOT_SUPPORTED_FORMAT
                except (ValueError, UnicodeError):
                    result = INVALID_ARGUMENT
                except OSError:
                    result = FILE_NOT_FOUND
            else:
                try:
                    address = int(r[0])
                    if address & 3:
                        raise ValueError('unaligned screenshot parameter')
                    photo, game, comment, reserved = struct.unpack('<IIII', self._read(address, 16))
                    if reserved:
                        raise ValueError('screenshot reserved pointer must be null')
                    parameters = {'photo_title': self._text(photo, 64),
                                  'game_title': self._text(game, 64),
                                  'game_comment': self._text(comment, 128)}
                except (ValueError, struct.error):
                    result = INVALID_ARGUMENT
                else:
                    self.parameters = parameters
            self.trace.append({'nid': '%08x' % nid, 'name': APIS[nid], 'result': result})
            self.trace = self.trace[-64:]
            return result

    def report(self):
        with self.lock:
            return {'enabled': self.enabled,
                    'parameters': dict(self.parameters) if self.parameters is not None else None,
                    'overlay': dict(self.overlay) if self.overlay is not None else None,
                    'capture_implemented': False, 'captures_written': 0,
                    'scope': 'guest screenshot permission, metadata and decoded overlay configuration; no capture or notification implementation',
                    'trace': [dict(row) for row in self.trace]}
