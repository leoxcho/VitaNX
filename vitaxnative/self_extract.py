"""Bounded plaintext Vita SELF extraction. No key handling or decryption.

Layout reference: vitasdk/vita-toolchain src/self.h (MIT).
Only explicit plaintext segment flags are accepted; retail encrypted SELF fails closed.
Reconstructed ELF omits unavailable section headers, preserving program segments.
"""
import hashlib
from pathlib import Path
import struct
import zlib

MAX_SIZE = 128 * 1024 * 1024


class EncryptedSelfError(ValueError):
    """The input still contains encrypted executable segments."""


def _extent(data, offset, size):
    if offset < 0 or size < 0 or offset > len(data) or size > len(data) - offset:
        raise ValueError('SELF extent outside input')
    return data[offset:offset + size]


def _parse_self_layout(path):
    path = Path(path)
    if not 128 <= path.stat().st_size <= MAX_SIZE:
        raise ValueError('SELF input size outside supported bounds')
    data = path.read_bytes()
    if data[:4] != b'SCE\0' or struct.unpack_from('<I', data, 4)[0] != 3:
        raise ValueError('requires Vita SCE SELF version 3')
    if struct.unpack_from('<H', data, 10)[0] != 1:
        raise ValueError('not a SELF executable container')
    header_size = struct.unpack_from('<Q', data, 16)[0]
    if not 128 <= header_size <= len(data):
        raise ValueError('SELF header length outside input')
    elf_size = struct.unpack_from('<Q', data, 24)[0]
    eo, po, si = (struct.unpack_from('<Q', data, o)[0] for o in (64, 72, 88))
    if eo < 128 or eo + 52 > header_size:
        raise ValueError('embedded ELF header outside SELF header')
    header = _extent(data, eo, 52)
    fields = struct.unpack('<16sHHIIIIIHHHHHH', header)
    if header[:7] != b'\x7fELF\x01\x01\x01' or fields[2] != 40 or fields[3] != 1:
        raise ValueError('SELF does not contain ELF32 little-endian ARM version 1')
    phoff, phsize, phnum = fields[5], fields[9], fields[10]
    if not 0 < phnum <= 128 or phsize != 32 or not 52 <= elf_size <= MAX_SIZE:
        raise ValueError('unsupported ELF sizes or program header count')
    if phoff < 52 or phoff + phnum * 32 > elf_size:
        raise ValueError('ELF program header output outside bounds')
    if min(po, si) < 128 or max(po, si) + phnum * 32 > header_size:
        raise ValueError('SELF segment tables outside header')
    table = _extent(data, po, phnum * 32)
    storage = _extent(data, si, phnum * 32)
    segments = []
    spans = [(0, 52), (phoff, phoff + len(table))]
    for i in range(phnum):
        kind, offset, address, _, size, memsize, flags, align = struct.unpack_from('<IIIIIIII', table, i * 32)
        src, length, compression, encryption = struct.unpack_from('<QQQQ', storage, i * 32)
        _extent(data, src, length)
        if length and src < header_size:
            raise ValueError('SELF payload overlaps container header')
        if offset > elf_size or size > elf_size - offset or (kind == 1 and (size > memsize or address + memsize > 0x100000000)):
            raise ValueError('invalid ELF segment output extent')
        if compression not in (1, 2) or encryption not in (1, 2):
            raise ValueError('unknown SELF compression/encryption flag')
        if size:
            if any(offset < end and offset + size > start for start, end in spans):
                raise ValueError('overlapping ELF output extents unsupported')
            spans.append((offset, offset + size))
        segments.append(dict(index=i, type=kind, offset=offset, size=size, source=src,
                             stored_size=length, compression=compression, encryption=encryption))
    return dict(format='Vita_SELF', elf_size=elf_size, arm_machine=40,
                plaintext=all(s['encryption'] == 2 for s in segments), segments=segments,
                _data=data, _header=header, _table=table, _phoff=phoff)


def inspect_self_layout(path):
    """Read-only, JSON-safe container and segment assessment."""
    layout = _parse_self_layout(path)
    return {key: value for key, value in layout.items() if not key.startswith('_')}


def extract_self(path, output):
    """Create a new unpacked ELF; never overwrite output or change input."""
    layout = _parse_self_layout(path)
    if not layout['plaintext']:
        raise EncryptedSelfError('encrypted SELF segments: usable ARM code unavailable; decryption is not implemented')
    result = bytearray(layout['elf_size'])
    header = bytearray(layout['_header'])
    # Section headers are not guaranteed to be preserved by SELF containers.
    struct.pack_into('<I', header, 32, 0)
    struct.pack_into('<HHH', header, 46, 0, 0, 0)
    result[:52] = header
    po = layout['_phoff']
    result[po:po + len(layout['_table'])] = layout['_table']
    for seg in layout['segments']:
        payload = _extent(layout['_data'], seg['source'], seg['stored_size'])
        if seg['compression'] == 2:
            dec = zlib.decompressobj()
            try:
                payload = dec.decompress(payload, seg['size'] + 1)
            except zlib.error as error:
                raise ValueError('invalid compressed SELF segment') from error
            if not dec.eof or dec.unused_data or dec.unconsumed_tail:
                raise ValueError('truncated, trailing, or oversized compressed SELF segment')
        if len(payload) != seg['size']:
            raise ValueError('SELF segment size does not match ELF program header')
        result[seg['offset']:seg['offset'] + seg['size']] = payload
    output = Path(output)
    if output.resolve() == Path(path).resolve():
        raise ValueError('output must differ from source')
    # Exclusive creation prevents replacing an existing installation or source.
    with output.open('xb') as handle:
        handle.write(result)
    return dict(path=str(output), sha256=hashlib.sha256(result).hexdigest(),
                elf_extracted=True, armv7_elf=True, recompiled=False,
                section_headers_preserved=False)
