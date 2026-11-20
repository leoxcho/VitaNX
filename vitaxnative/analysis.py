"""Read-only, bounded Vita package metadata and executable analysis."""
import hashlib
import json
import struct
import zipfile
from pathlib import Path

MAX_SFO = 2 * 1024 * 1024
MAX_ARCHIVE_ENTRIES = 100000
MAX_ENTRY_SIZE = 4 * 1024**3


def parse_sfo(data: bytes) -> dict:
    if len(data) < 20 or len(data) > MAX_SFO or data[:4] != b'\x00PSF':
        raise ValueError('invalid or oversized PARAM.SFO')
    _, version, keys_start, values_start, count = struct.unpack_from('<4sIIII', data)
    if count > 4096 or 20 + count * 16 > len(data):
        raise ValueError('invalid SFO entry count')
    result = {}
    for i in range(count):
        key_offset, fmt, size, maximum, value_offset = struct.unpack_from('<HHIII', data, 20 + 16*i)
        k = keys_start + key_offset
        v = values_start + value_offset
        if k >= len(data) or v > len(data) or size > maximum or size > len(data) - v:
            raise ValueError('invalid SFO offsets')
        end = data.find(b'\x00', k)
        if end == -1 or end >= values_start:
            raise ValueError('unterminated SFO key')
        key = data[k:end].decode('utf-8', errors='replace')
        raw = data[v:v+size]
        if fmt == 0x0404 and size == 4:
            result[key] = struct.unpack('<I', raw)[0]
        elif fmt in (0x0004, 0x0204):
            result[key] = raw.split(b'\x00', 1)[0].decode('utf-8', errors='replace')
    return result


def elf_info(data: bytes) -> dict:
    if len(data) < 52 or data[:4] != b'\x7fELF':
        return {'format': 'unknown_or_container', 'armv7_elf': False}
    elf_class, endian = data[4], data[5]
    if endian not in (1, 2) or elf_class not in (1, 2):
        return {'format': 'invalid_elf', 'armv7_elf': False}
    byteorder = '<' if endian == 1 else '>'
    machine = struct.unpack_from(byteorder + 'H', data, 18)[0]
    return {'format': 'ELF', 'class': 32 if elf_class == 1 else 64,
            'endianness': 'little' if endian == 1 else 'big',
            'machine': machine, 'armv7_elf': elf_class == 1 and machine == 40}


def safe_archive_members(z: zipfile.ZipFile):
    entries = z.infolist()
    if len(entries) > MAX_ARCHIVE_ENTRIES:
        raise ValueError('archive has too many entries')
    seen = set()
    for entry in entries:
        name = entry.filename.replace('\\', '/')
        parts = name.split('/')
        if name.startswith('/') or any(p in ('..', '') for p in parts[:-1]) or '..' in parts or ':' in parts[0]:
            raise ValueError('unsafe archive path')
        if entry.file_size > MAX_ENTRY_SIZE:
            raise ValueError('oversized archive entry')
        if name.casefold() in seen:
            raise ValueError('duplicate archive entry')
        seen.add(name.casefold())
    return entries


def analyze(path: Path) -> dict:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(path)
    result = {'path': str(path), 'kind': 'directory' if path.is_dir() else path.suffix.lower(),
              'title': None, 'title_id': None, 'version': None, 'has_eboot': False,
              'has_sfo': False, 'native_build_available': False,
              'status': 'preflight_only', 'warnings': []}
    sfo = exe = None
    exe_size = None
    if path.is_dir():
        sfo_path, exe_path = path / 'sce_sys' / 'param.sfo', path / 'eboot.bin'
        if sfo_path.is_file():
            if sfo_path.stat().st_size > MAX_SFO: raise ValueError('oversized PARAM.SFO')
            sfo = sfo_path.read_bytes()
        if exe_path.is_file():
            with exe_path.open('rb') as f: exe = f.read(128)
            exe_size = exe_path.stat().st_size
    elif path.suffix.lower() in ('.vpk', '.zip'):
        with zipfile.ZipFile(path) as z:
            entries = safe_archive_members(z)
            result['entries'] = len(entries)
            names = {e.filename.casefold(): e for e in entries}
            if 'sce_sys/param.sfo' in names:
                entry = names['sce_sys/param.sfo']
                if entry.file_size > MAX_SFO: raise ValueError('oversized PARAM.SFO')
                sfo = z.read(entry)
            if 'eboot.bin' in names:
                with z.open(names['eboot.bin']) as f: exe = f.read(128)
                exe_size = names['eboot.bin'].file_size
    elif path.is_file():
        with path.open('rb') as f: exe = f.read(128)
        exe_size = path.stat().st_size
    result['has_sfo'] = sfo is not None
    result['has_eboot'] = exe is not None
    if sfo is not None:
        try:
            metadata = parse_sfo(sfo)
            result.update(title=metadata.get('TITLE'), title_id=metadata.get('TITLE_ID'),
                          version=metadata.get('APP_VER') or metadata.get('VERSION'))
        except ValueError as err:
            result['warnings'].append(f'SFO parse failed: {err}')
    if exe is not None:
        result['executable'] = elf_info(exe)
        if exe[:4] == b'SCE\x00':
            from .self_parser import parse_self_header
            result['executable'] = parse_self_header(exe, exe_size)
        if not result['executable']['armv7_elf']:
            result['warnings'].append('Executable is not a directly recognized ARMv7 ELF; may require SELF decryption or extraction.')
    result['warnings'].append('Metadata inspection only; use compatibility for bounded translation and runtime support checks.')
    return result


def load_patch_registry(path: Path) -> dict:
    """Validate patch metadata. Never executes patches or mutates game data."""
    registry = json.loads(Path(path).read_text(encoding='utf-8'))
    if not isinstance(registry, dict) or registry.get('schema_version') != 1 or not isinstance(registry.get('patches'), list):
        raise ValueError('invalid patch registry')
    for patch in registry['patches']:
        if not isinstance(patch, dict) or not all(isinstance(patch.get(k), str) and patch[k] for k in ('title_id', 'version', 'kind', 'status')):
            raise ValueError('invalid patch entry')
        if patch['status'] not in ('candidate', 'validated', 'rejected'):
            raise ValueError('invalid patch status')
        if patch['kind'] not in ('fps', 'resolution', 'compatibility'):
            raise ValueError('invalid patch kind')
    return registry
