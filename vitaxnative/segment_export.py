"""Export validated, *already unpacked* ARM ELF load segments for offline analysis.

This is not SELF decryption, recompilation, or a runnable macOS port.
"""
import json
import os
import tempfile
from pathlib import Path
from .elf_segments import inspect_elf_segments


def export_segments(source: Path, destination: Path) -> dict:
    source, destination = Path(source), Path(destination)
    report = inspect_elf_segments(source)
    if not report['segments']:
        raise ValueError('ELF has no PT_LOAD segments')
    if destination.exists():
        raise FileExistsError(f'output already exists: {destination}')
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.vitaxnative-', dir=destination.parent) as temp:
        staging = Path(temp) / 'segments'
        staging.mkdir()
        with source.open('rb') as inp:
            for seg in report['segments']:
                name = f"segment-{seg['index']:03d}.bin"
                with (staging / name).open('xb') as out:
                    inp.seek(seg['file_offset'])
                    remaining = seg['file_size']
                    while remaining:
                        chunk = inp.read(min(1024 * 1024, remaining))
                        if not chunk:
                            raise ValueError('source changed while exporting')
                        out.write(chunk)
                        remaining -= len(chunk)
                import hashlib
                if hashlib.sha256((staging / name).read_bytes()).hexdigest() != seg['sha256']:
                    raise ValueError('source changed during export')
                seg['export_file'] = name
        (staging / 'manifest.json').write_text(json.dumps(report, indent=2) + '\n')
        os.rename(staging, destination)
    return {'output': str(destination), 'segments': len(report['segments']), 'recompiled': False}
