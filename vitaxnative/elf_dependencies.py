"""Read-only bounded ELF32 ARM section, relocation and import inventory.

No instruction recompilation, decryption, or runtime linking is performed.
"""
import struct
from pathlib import Path

MAX_FILE = 512 * 1024 * 1024
MAX_SECTIONS = 4096
MAX_ENTRIES = 200000
SHT_SYMTAB, SHT_STRTAB, SHT_RELA, SHT_REL, SHT_DYNSYM = 2, 3, 4, 9, 11


def inspect_elf_dependencies(path: Path) -> dict:
    path = Path(path)
    size = path.stat().st_size
    if not 52 <= size <= MAX_FILE:
        raise ValueError('ELF size outside inspection limits')
    with path.open('rb') as f:
        data = f.read()
    if data[:4] == b'SCE\x00':
        raise ValueError('SCE/SELF input: an unpacked authorized ELF is required')
    if data[:7] != b'\x7fELF\x01\x01\x01':
        raise ValueError('requires little-endian ELF32')
    (etype, machine, version, entry, phoff, shoff, flags, ehsize,
     phentsize, phnum, shentsize, shnum, shstrndx) = struct.unpack_from('<HHIIIIIHHHHHH', data, 16)
    if machine != 40 or version != 1 or ehsize < 52:
        raise ValueError('requires ARM ELF32')
    if shnum == 0:
        return {'path': str(path), 'section_count': 0, 'undefined_symbols': [], 'relocations': [], 'recompiled': False,
                'warnings': ['No section header table; imports and relocations cannot be inventoried']}
    if shnum > MAX_SECTIONS or shentsize < 40 or shoff > size or shnum * shentsize > size - shoff:
        raise ValueError('section header table outside file bounds')
    sections = []
    for i in range(shnum):
        vals = struct.unpack_from('<IIIIIIIIII', data, shoff + i * shentsize)
        name, typ, flags, addr, off, length, link, info, align, entsize = vals
        if typ != 8 and (off > size or length > size - off):
            raise ValueError(f'section {i} outside file bounds')
        sections.append({'type': typ, 'offset': off, 'size': length, 'link': link,
                         'info': info, 'entsize': entsize, 'flags': flags, 'address': addr})

    def string_at(sec_idx, off):
        if sec_idx >= len(sections) or sections[sec_idx]['type'] != SHT_STRTAB:
            raise ValueError('invalid string table link')
        sec = sections[sec_idx]
        if off >= sec['size']:
            raise ValueError('string offset outside table')
        start = sec['offset'] + off
        end = data.find(b'\0', start, sec['offset'] + sec['size'])
        if end < 0:
            raise ValueError('unterminated symbol string')
        return data[start:end].decode('utf-8', errors='replace')

    symbols_by_section = {}
    symbols = []
    for i, sec in enumerate(sections):
        if sec['type'] not in (SHT_SYMTAB, SHT_DYNSYM):
            continue
        if sec['entsize'] < 16 or sec['size'] % sec['entsize']:
            raise ValueError('invalid symbol entry size')
        count = sec['size'] // sec['entsize']
        if count > MAX_ENTRIES:
            raise ValueError('too many symbols')
        entries = []
        for j in range(count):
            name, value, sym_size, info, other, shndx = struct.unpack_from('<IIIBBH', data, sec['offset'] + j * sec['entsize'])
            symbol = {'name': string_at(sec['link'], name), 'value': value,
                      'size': sym_size, 'binding': info >> 4, 'type': info & 15,
                      'section_index': shndx, 'undefined': shndx == 0}
            entries.append(symbol)
            if symbol['name'] and symbol['undefined']:
                symbols.append(symbol)
        symbols_by_section[i] = entries
    # ARM ELF mapping symbols distinguish code state from inline literal/table data.
    code_ranges = []
    function_entries = set()
    mappings = {}
    function_ends = {}
    for entries in symbols_by_section.values():
        for symbol in entries:
            idx = symbol['section_index']
            if not 0 < idx < len(sections) or not sections[idx]['flags'] & 4:
                continue
            sec = sections[idx]
            value = symbol['value']
            if not sec['address'] <= (value & ~1) <= sec['address'] + sec['size']:
                raise ValueError('code symbol outside executable section')
            name = symbol['name'].split('.')[0]
            if name in ('$a', '$t', '$d'):
                if (name == '$t' and value & 1) or (name == '$a' and value & 3):
                    raise ValueError('misaligned ARM mapping symbol')
                key = (idx, value)
                if key in mappings and mappings[key] != name:
                    raise ValueError('conflicting ARM mapping symbols')
                mappings[key] = name
            elif symbol['type'] == 2 and not symbol['undefined']:
                function_entries.add(value)
                if symbol['size']:
                    function_ends[idx] = max(function_ends.get(idx, 0), (value & ~1) + symbol['size'])
    for idx in sorted({key[0] for key in mappings}):
        points = sorted((address, mode) for (section, address), mode in mappings.items() if section == idx)
        for i, (start, mode) in enumerate(points):
            end = points[i+1][0] if i+1 < len(points) else sections[idx]['address'] + sections[idx]['size']
            # Linkers can merge trailing .rodata into .text without a new
            # mapping symbol. Sized functions bound that final code interval.
            if i+1 == len(points) and function_ends.get(idx, 0) > start:
                end = min(end, function_ends[idx])
            if mode != '$d' and start < end:
                code_ranges.append({'start': start, 'end': end, 'thumb': mode == '$t'})
    relocations = []
    for i, sec in enumerate(sections):
        if sec['type'] not in (SHT_REL, SHT_RELA):
            continue
        minimum = 8 if sec['type'] == SHT_REL else 12
        if sec['entsize'] < minimum or sec['size'] % sec['entsize']:
            raise ValueError('invalid relocation entry size')
        count = sec['size'] // sec['entsize']
        if count > MAX_ENTRIES or len(relocations) + count > MAX_ENTRIES:
            raise ValueError('too many relocations')
        symtab = symbols_by_section.get(sec['link'])
        if symtab is None:
            raise ValueError('relocation links to invalid symbol table')
        for j in range(count):
            off, info = struct.unpack_from('<II', data, sec['offset'] + j * sec['entsize'])
            sym_index = info >> 8
            if sym_index >= len(symtab):
                raise ValueError('relocation symbol index outside table')
            item = {'section_index': i, 'offset': off, 'type': info & 255,
                    'symbol': symtab[sym_index]['name']}
            if sec['type'] == SHT_RELA:
                item['addend'] = struct.unpack_from('<i', data, sec['offset'] + j * sec['entsize'] + 8)[0]
            relocations.append(item)
    return {'path': str(path), 'section_count': shnum, 'undefined_symbols': symbols,
            'relocations': relocations, 'code_ranges': code_ranges,
            'function_entries': sorted(function_entries), 'recompiled': False,
            'warnings': ['Inventory only; Vita NID resolution and runtime are not implemented']}
