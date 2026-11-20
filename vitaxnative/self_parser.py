"""Read-only SCE container header diagnostics; not a decryptor or ELF extractor."""
import struct
from pathlib import Path

HEADER_SIZE = 0x80


def parse_self_header(data: bytes, file_size: int) -> dict:
    if len(data) < HEADER_SIZE or data[:4] != b'SCE\x00':
        raise ValueError('not a complete SCE header')
    if file_size < HEADER_SIZE:
        raise ValueError('SCE file is truncated')
    # Common SCE header fields; avoid interpreting container lengths as file offsets.
    version = struct.unpack_from('<I', data, 4)[0]
    sdk_type, header_type = struct.unpack_from('<HH', data, 8)
    metadata_offset = struct.unpack_from('<I', data, 12)[0]
    header_length, data_length = struct.unpack_from('<QQ', data, 16)
    warnings = []
    if header_length < HEADER_SIZE or header_length > file_size:
        warnings.append('Declared header length is outside the file bounds')
    if metadata_offset >= file_size:
        warnings.append('Metadata offset is outside the file bounds')
    if data_length > file_size:
        warnings.append('Declared data length exceeds physical file size; this is not proof of corruption')
    return {
        'format': 'SCE_container', 'version': version,
        'sdk_type_raw': sdk_type, 'header_type_raw': header_type,
        'metadata_offset_raw': metadata_offset,
        'header_length': header_length, 'data_length': data_length,
        'file_size': file_size, 'encryption_status': 'undetermined',
        'elf_extracted': False, 'armv7_elf': False, 'warnings': warnings,
    }


def inspect_self(path: Path) -> dict:
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(path)
    with path.open('rb') as handle:
        header = handle.read(HEADER_SIZE)
    return {'path': str(path), **parse_self_header(header, path.stat().st_size)}
