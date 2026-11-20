"""Read-only Vita3K installed title inventory and bounded PARAM.SFO parsing.

No decryption, ROM extraction, conversion, filesystem writes or launches.
"""
from pathlib import Path
import os
import re
import struct

# Override with --app-root or VITANX_APP_ROOT; never embed a developer's private drive path.
DEFAULT_APP_ROOT = Path(os.environ.get('VITANX_APP_ROOT',
    str(Path.home() / 'Library' / 'Application Support' / 'Vita3K' / 'ux0' / 'app'))).expanduser()
TITLE_ID = re.compile(r'^[A-Z]{4}[0-9]{5}$')
_MAX_SFO_BYTES = 2 * 1024 * 1024
_MAX_SFO_ENTRIES = 256


def read_param_sfo(path):
    """Return selected strings from a bounded, non-symlink Vita PARAM.SFO file."""
    path = Path(path)
    if path.is_symlink() or path.parent.is_symlink() or not path.is_file():
        raise ValueError('PARAM.SFO must be a regular non-symlink file')
    size = path.stat().st_size
    if size < 20 or size > _MAX_SFO_BYTES:
        raise ValueError('PARAM.SFO size outside supported bounds')
    raw = path.read_bytes()
    if len(raw) != size:
        raise ValueError('PARAM.SFO changed during read')
    magic, version, key_start, value_start, count = struct.unpack_from('<4sIIII', raw)
    if magic != b'\x00PSF' or version > 0x101 or count > _MAX_SFO_ENTRIES:
        raise ValueError('invalid PARAM.SFO header')
    entry_end = 20 + 16 * count
    if not entry_end <= key_start <= value_start <= size:
        raise ValueError('invalid PARAM.SFO table offsets')
    out = {}
    for i in range(count):
        key_offset, fmt, value_len, value_max, value_offset = struct.unpack_from('<HHIII', raw, 20 + i * 16)
        ks = key_start + key_offset
        vs = value_start + value_offset
        if ks >= value_start or value_len > value_max or vs > size or value_max > size - vs:
            raise ValueError('PARAM.SFO entry outside table bounds')
        terminator = raw.find(b'\x00', ks, value_start)
        if terminator == -1:
            raise ValueError('unterminated PARAM.SFO key')
        try:
            key = raw[ks:terminator].decode('ascii')
        except UnicodeDecodeError as error:
            raise ValueError('non-ASCII PARAM.SFO key') from error
        if not key or key in out:
            raise ValueError('duplicate or empty PARAM.SFO key')
        if fmt in (0x0004, 0x0204):
            out[key] = raw[vs:vs + value_len].split(b'\x00', 1)[0].decode('utf-8', errors='replace')
        elif fmt == 0x0404 and value_len == 4:
            out[key] = struct.unpack_from('<I', raw, vs)[0]
        else:
            continue
    return out


def _no_symlink_dir(path):
    return path.is_dir() and not path.is_symlink()


def list_installed_games(app_root=DEFAULT_APP_ROOT):
    """Inventory a Vita3K ux0/app root; never open symlinked title directories."""
    app_root = Path(app_root).expanduser()
    if not _no_symlink_dir(app_root):
        raise ValueError('Vita3K app root must be an existing, non-symlink directory')
    ux0 = app_root.parent
    patch_root, dlc_root = ux0 / 'patch', ux0 / 'addcont'
    titles = []
    for game in sorted(app_root.iterdir(), key=lambda p:p.name):
        if not TITLE_ID.fullmatch(game.name) or not _no_symlink_dir(game):
            continue
        sfo = game / 'sce_sys' / 'param.sfo'
        metadata = {}
        error = None
        try:
            metadata = read_param_sfo(sfo)
            declared = metadata.get('TITLE_ID')
            if declared and declared != game.name:
                raise ValueError(f'TITLE_ID mismatch: {declared}')
        except (OSError, ValueError) as exc:
            error = str(exc)
        patch = patch_root / game.name
        patch_metadata = {}
        patch_error = None
        if _no_symlink_dir(patch):
            try:
                patch_metadata = read_param_sfo(patch / 'sce_sys' / 'param.sfo')
                declared = patch_metadata.get('TITLE_ID')
                if declared and declared != game.name:
                    raise ValueError(f'patch TITLE_ID mismatch: {declared}')
            except (OSError, ValueError) as exc:
                patch_error = str(exc)
        dlc = dlc_root / game.name
        dlc_names = sorted(p.name for p in dlc.iterdir() if _no_symlink_dir(p)) if _no_symlink_dir(dlc) else []
        titles.append({'title_id':game.name, 'title':metadata.get('TITLE', game.name),
                       'version':metadata.get('APP_VER'), 'game_path':str(game),
                       'base_metadata_error':error,
                       'patch_path':str(patch) if _no_symlink_dir(patch) else None,
                       'patch_version':patch_metadata.get('APP_VER'),
                       'patch_metadata_error':patch_error,
                       'dlc_count':len(dlc_names), 'dlc_content_ids':dlc_names})
    return {'app_root':str(app_root),'patch_root':str(patch_root),
            'dlc_root':str(dlc_root),'count':len(titles), 'games':titles,
            'read_only':True,'gameplay_verified':False}
