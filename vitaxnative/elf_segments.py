"""Bounded, read-only ELF32 ARM load-segment validation and manifest generation.

Does not translate instructions, decrypt SELF, or execute untrusted code.
"""
import hashlib
import struct
from pathlib import Path

MAX_PROGRAM_HEADERS = 512
MAX_INPUT_SIZE = 512 * 1024 * 1024


def inspect_elf_segments(path: Path) -> dict:
    path = Path(path)
    size = path.stat().st_size
    if size < 52 or size > MAX_INPUT_SIZE:
        raise ValueError('ELF size outside supported inspection bounds')
    with path.open('rb') as f:
        header = f.read(52)
        if header[:4] != b'\x7fELF':
            if header[:4] == b'SCE\x00':
                raise ValueError('SCE/SELF container: provide an authorized, unpacked ELF; no decryptor is integrated')
            raise ValueError('not an ELF executable')
        if header[4] != 1 or header[5] != 1 or header[6] != 1:
            raise ValueError('requires ELF32 little-endian version 1')
        fields = struct.unpack_from('<HHIIIIIHHHHHH', header, 16)
        e_type, machine, version, entry, phoff, shoff, flags, ehsize, phentsize, phnum, shentsize, shnum, shstrndx = fields
        if machine != 40 or version != 1 or ehsize < 52:
            raise ValueError('requires a valid ARM ELF32 header')
        if phnum > MAX_PROGRAM_HEADERS or (phnum and (phentsize < 32 or phoff > size or phnum * phentsize > size - phoff)):
            raise ValueError('invalid program header table bounds')
        segments = []
        for i in range(phnum):
            f.seek(phoff + i * phentsize)
            raw = f.read(32)
            p_type, offset, vaddr, paddr, filesz, memsz, pflags, align = struct.unpack('<IIIIIIII', raw)
            if p_type != 1:
                continue
            if filesz > memsz or offset > size or filesz > size - offset:
                raise ValueError(f'PT_LOAD segment {i} outside file or memory bounds')
            f.seek(offset)
            digest = hashlib.sha256()
            remaining = filesz
            while remaining:
                chunk = f.read(min(1024 * 1024, remaining))
                if not chunk:
                    raise ValueError('truncated segment')
                digest.update(chunk)
                remaining -= len(chunk)
            segments.append({'index': i, 'file_offset': offset, 'file_size': filesz,
                             'virtual_address': vaddr, 'memory_size': memsz,
                             'flags': pflags, 'sha256': digest.hexdigest()})
    return {'path': str(path), 'format': 'ELF32_ARM', 'entry_point': entry,
            'elf_type': e_type, 'segments': segments,
            'recompiled': False, 'native_app_created': False,
            'warning': 'Structural analysis only; no ARM translation or Vita runtime available'}
