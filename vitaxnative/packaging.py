"""Safe standalone packaging for *already native* macOS executables.

This does not recompile Vita games. It is a downstream component of that pipeline.
"""
import hashlib
import json
import os
import plistlib
import re
import shutil
import struct
import tempfile
from pathlib import Path

MACHO_ARM64 = (0xFEEDFACF, 0x0100000C)


def require_arm64_macho(path: Path) -> None:
    with Path(path).open('rb') as f:
        header = f.read(12)
    if len(header) < 12:
        raise ValueError('executable too short')
    magic, cpu, subtype = struct.unpack('<III', header)
    if (magic, cpu) != MACHO_ARM64:
        raise ValueError('requires a thin ARM64 macOS Mach-O executable (not a Vita eboot)')


def package_native(executable: Path, output_dir: Path, name: str, bundle_id: str) -> Path:
    """Atomically create a .app from an existing ARM64 Mach-O, never overwrite."""
    executable, output_dir = Path(executable), Path(output_dir)
    require_arm64_macho(executable)
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9 ._()-]{0,99}', name) or name in ('.', '..'):
        raise ValueError('invalid application name')
    if not re.fullmatch(r'[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+', bundle_id):
        raise ValueError('invalid bundle identifier')
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / (name + '.app')
    if target.exists() or target.is_symlink():
        raise FileExistsError(target)
    temp = Path(tempfile.mkdtemp(prefix='.vitaxnative-', dir=output_dir))
    try:
        app = temp / target.name
        macos = app / 'Contents' / 'MacOS'
        macos.mkdir(parents=True)
        dest = macos / 'Game'
        shutil.copyfile(executable, dest)
        dest.chmod(0o755)
        info = {'CFBundleExecutable': 'Game', 'CFBundleIdentifier': bundle_id,
                'CFBundleName': name, 'CFBundleDisplayName': name,
                'CFBundlePackageType': 'APPL', 'CFBundleVersion': '1',
                'CFBundleShortVersionString': '0.1.0', 'LSMinimumSystemVersion': '12.0'}
        with (app / 'Contents' / 'Info.plist').open('wb') as f:
            plistlib.dump(info, f)
        digest = hashlib.sha256(dest.read_bytes()).hexdigest()
        (app / 'Contents' / 'Resources').mkdir()
        (app / 'Contents' / 'Resources' / 'build-manifest.json').write_text(json.dumps({
            'origin': 'already-native-arm64-macho', 'sha256': digest,
            'vita_recompiled': False, 'fps_unlocked': False,
            'resolution_enhanced': False}, indent=2))
        os.rename(app, target)
        return target
    finally:
        shutil.rmtree(temp)
