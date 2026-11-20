"""Bounded VitaSDK VELF module-entry and function-import discovery.

Format references (MIT): vitasdk/vita-toolchain src/sce-elf-defs.h and
src/vita-elf-create/sce-elf.c. Metadata is read at the ELF's declared addresses;
this module does not apply relocation records or claim arbitrary module linking.
"""
from pathlib import Path
import struct
from .elf_segments import inspect_elf_segments

ET_SCE_EXEC = 0xfe00
ET_SCE_RELEXEC = 0xfe04
PT_SCE_RELA = 0x60000000
MAX_IMPORTS = 65536
MAX_TABLE_BYTES = 4 * 1024 * 1024


def reconcile_imports(discovered, explicit=None):
    """Metadata is authoritative; explicit entries are optional assertions.

    Accept mappings or pairs, preserving duplicate assertions for validation.
    Never infer identifiers from names or silently replace a metadata NID.
    """
    result = dict(sorted(discovered.items()))
    pairs = explicit.items() if hasattr(explicit, 'items') else explicit or ()
    seen = {}
    for address, nid in pairs:
        if type(address) is not int or type(nid) is not int or not 0 <= address <= 0xffffffff or not 0 <= nid <= 0xffffffff:
            raise ValueError('invalid explicit import mapping')
        if address in seen and seen[address] != nid:
            raise ValueError(f'conflicting duplicate explicit import at {address:#010x}')
        seen[address] = nid
    for address, nid in sorted(seen.items()):
        if address not in result:
            raise ValueError(f'explicit import {address:#010x} absent from Vita module metadata')
        if result[address] != nid:
            raise ValueError(f'explicit import conflict at {address:#010x}: explicit NID {nid:#010x}, metadata NID {result[address]:#010x}')
    return result


def inspect_vita_module(path):
    """Discover entry and import hooks in a fixed-address VitaSDK SCE ELF.

    Return integer ``entry`` and ``imports`` (stub-address -> NID) plus library,
    module and relocation inventories. Variable/TLS imports are explicitly
    rejected. Relocation presence is reported, never silently treated as applied.
    """
    path = Path(path)
    elf = inspect_elf_segments(path)
    if elf['elf_type'] not in (ET_SCE_EXEC, ET_SCE_RELEXEC):
        raise ValueError('requires Vita SCE EXEC/RELEXEC ELF; ordinary ELF has no SCE module entry')
    data = path.read_bytes()
    segments = elf['segments']
    if not segments or len(segments) > 16:
        raise ValueError('unsupported Vita load-segment count')
    spans = []
    for segment in segments:
        lo = segment['virtual_address']
        hi = lo + segment['memory_size']
        if hi > 0x100000000 or any(lo < end and start < hi for start, end in spans):
            raise ValueError('invalid or overlapping Vita load segments')
        spans.append((lo, hi))

    def mapped(address, size, executable=False):
        if not 0 <= address <= 0xffffffff or size < 0 or size > MAX_TABLE_BYTES:
            raise ValueError('Vita metadata address/size outside supported bounds')
        for segment in segments:
            offset = address - segment['virtual_address']
            if 0 <= offset <= segment['file_size'] and size <= segment['file_size'] - offset:
                if executable and not segment['flags'] & 1:
                    break
                return segment['file_offset'] + offset
        raise ValueError('Vita metadata outside mapped file bytes')

    def u32(address):
        return struct.unpack_from('<I', data, mapped(address, 4))[0]

    def words(address, count):
        if not 0 <= count <= MAX_IMPORTS:
            raise ValueError('Vita function table count exceeds limit')
        if not count:
            return []
        return list(struct.unpack_from('<' + 'I' * count, data, mapped(address, 4 * count)))

    def library_string(address):
        if not address:return None
        value=bytearray()
        for index in range(256):
            character=data[mapped(address+index,1)]
            if not character:return value.decode('utf-8',errors='replace')
            value.append(character)
        raise ValueError('unterminated Vita library name')

    encoded_entry = elf['entry_point']
    module_segment_index = encoded_entry >> 30
    module_offset = encoded_entry & 0x3fffffff
    candidates = [segment for segment in segments if segment['index'] == module_segment_index]
    if len(candidates) != 1:
        raise ValueError('Vita module-info entry references absent load segment')
    module_segment = candidates[0]
    base = module_segment['virtual_address']
    module_address = base + module_offset
    module_file = mapped(module_address, 0x5c)
    attributes, version = struct.unpack_from('<HH', data, module_file)
    raw_name = data[module_file + 4:module_file + 31]
    if b'\0' not in raw_name:
        raise ValueError('unterminated Vita module name')
    name = raw_name.split(b'\0', 1)[0].decode('utf-8', errors='replace')
    export_top, export_end, import_top, import_end = struct.unpack_from('<IIII', data, module_file + 0x24)
    module_nid, tls_start, tls_filesz, tls_memsz, start_offset, stop_offset = struct.unpack_from('<IIIIII', data, module_file + 0x34)
    if start_offset == 0xffffffff:
        raise ValueError('Vita module has no startup entry')
    entry = base + start_offset
    mapped(entry & ~1, 2 if entry & 1 else 4, executable=True)
    if not entry & 1 and entry & 3:
        raise ValueError('unaligned ARM module entry')
    if tls_memsz or tls_filesz:
        raise ValueError('Vita TLS module initialization unsupported')

    def table_extent(top, end):
        if end < top or end - top > MAX_TABLE_BYTES:
            raise ValueError('invalid Vita module table extent')
        if end != top:
            mapped(base + top, end - top)
        return base + top, base + end

    cursor,table_end=table_extent(export_top,export_end)
    exports=[]
    export_count=0
    # Official vita-toolchain sce_module_exports, fixed 0x20-byte layout.
    while cursor<table_end:
        offset=mapped(cursor,4)
        size,reserved,library_version=struct.unpack_from('<BBH',data,offset)
        if size!=0x20 or reserved or size>table_end-cursor:
            raise ValueError('unsupported or truncated Vita export structure')
        offset=mapped(cursor,size)
        flags,functions,variables,tls_variables,library_nid,library_name,nid_address,entry_address=struct.unpack_from('<HHIIIIII',data,offset+4)
        if tls_variables:raise ValueError('Vita TLS exports require unsupported linking')
        total=functions+variables
        export_count+=total
        if export_count>MAX_IMPORTS:raise ValueError('too many Vita exports')
        nids=words(nid_address,total);addresses=words(entry_address,total)
        if len(set(nids))!=len(nids):raise ValueError('duplicate Vita export NID in library')
        function_exports={};variable_exports={}
        for index,(nid,address) in enumerate(zip(nids,addresses)):
            if index<functions:
                if not address&1 and address&3:raise ValueError('unaligned Vita function export')
                mapped(address&~1,2 if address&1 else 4,executable=True)
                function_exports[nid]=address
            else:
                mapped(address,1);variable_exports[nid]=address
        exports.append({'name':library_string(library_name),'nid':library_nid,
                        'version':library_version,'flags':flags,
                        'functions':function_exports,'variables':variable_exports})
        cursor+=size
    cursor, table_end = table_extent(import_top, import_end)
    hooks = {}
    libraries = []
    while cursor < table_end:
        offset = mapped(cursor, 4)
        size, reserved, library_version = struct.unpack_from('<BBH', data, offset)
        if size not in (0x24, 0x34) or size > table_end - cursor:
            raise ValueError('unsupported or truncated Vita import structure')
        offset = mapped(cursor, size)
        flags, functions, variables, tls_variables = struct.unpack_from('<HHHH', data, offset + 4)
        if variables or tls_variables:
            raise ValueError('Vita variable/TLS imports require unsupported linking')
        if len(hooks) + functions > MAX_IMPORTS:
            raise ValueError('too many Vita function imports')
        if size == 0x34:
            library_nid, library_name = struct.unpack_from('<II', data, offset + 0x10)
            nid_address, stub_address = struct.unpack_from('<II', data, offset + 0x1c)
        else:
            library_nid, library_name, nid_address, stub_address = struct.unpack_from('<IIII', data, offset + 0xc)
        library_label = library_string(library_name)
        nids = words(nid_address, functions)
        stubs = words(stub_address, functions)
        for stub, nid in zip(stubs, nids):
            # Rewritten VitaSDK stubs are ARM, though Thumb callers may BLX them.
            if stub & 3:
                raise ValueError('unaligned Vita import stub')
            mapped(stub, 12, executable=True)
            if stub in hooks:
                raise ValueError('duplicate Vita import stub')
            hooks[stub] = nid
        libraries.append({'name': library_label, 'nid': library_nid,
                          'version': library_version, 'flags': flags,
                          'function_count': functions})
        cursor += size

    phoff = struct.unpack_from('<I', data, 28)[0]
    phentsize, phnum = struct.unpack_from('<HH', data, 42)
    relocations = []
    for index in range(phnum):
        typ, offset, _, _, length = struct.unpack_from('<IIIII', data, phoff + index * phentsize)
        if typ != PT_SCE_RELA:
            continue
        if offset > len(data) or length > len(data) - offset or length > MAX_TABLE_BYTES:
            raise ValueError('Vita relocation program header outside bounds')
        cursor = offset
        end = offset + length
        counts = {}
        while cursor < end:
            if end - cursor < 8:
                raise ValueError('truncated Vita relocation')
            first = struct.unpack_from('<I', data, cursor)[0]
            form = first & 15
            width = 12 if form == 0 else 8 if form == 1 else 0
            if not width or width > end - cursor:
                raise ValueError('unsupported/truncated Vita relocation record')
            if form == 0 and first >> 20:
                raise ValueError('paired Vita relocations unsupported')
            code = (first >> 8) & 255
            counts[code] = counts.get(code, 0) + 1
            cursor += width
        relocations.append({'program_header': index, 'file_offset': offset,
                            'size': length, 'types': counts, 'applied': False})

    return {'path': str(path), 'format': 'VitaSDK_SCE_ELF',
            'elf_type': elf['elf_type'], 'module_name': name,
            'module_nid': module_nid, 'module_attributes': attributes,
            'module_version': version, 'module_info_address': module_address,
            'module_segment_base': base, 'entry': entry, 'imports': hooks,
            'libraries': libraries, 'exports':exports, 'relocations': relocations,
            'relocations_applied': False,
            'limitations': ['declared virtual addresses only; no rebasing',
                            'variable/TLS imports and TLS initialization unsupported']}


def inspect_vitasdk_elf(path, *, allow_missing=False):
    """Read official 16-byte .vitalink.fstubs records in linked ET_EXEC input.

    This is the GCC ELF before vita-elf-create rewrites stubs into executable
    instructions. Returned hooks prevent executing metadata words as ARM code.
    This does not itself prove which compiler produced a file.
    """
    path = Path(path)
    elf = inspect_elf_segments(path)
    if elf['elf_type'] in (ET_SCE_EXEC, ET_SCE_RELEXEC):
        return inspect_vita_module(path)
    if elf['elf_type'] != 2:
        raise ValueError('VitaSDK linked ELF inspection requires ET_EXEC')
    data = path.read_bytes()
    shoff = struct.unpack_from('<I', data, 32)[0]
    shentsize, shnum, shstrndx = struct.unpack_from('<HHH', data, 46)
    if allow_missing and not shoff and not shnum:
        return None
    if not 0 < shnum <= 4096 or shentsize < 40 or shoff > len(data) or shnum * shentsize > len(data) - shoff or shstrndx >= shnum:
        raise ValueError('invalid VitaSDK ELF section headers')
    sections = [struct.unpack_from('<IIIIIIIIII', data, shoff + i * shentsize) for i in range(shnum)]
    string_section = sections[shstrndx]
    _, kind, _, _, string_offset, string_size, *_ = string_section
    if kind != 3 or string_offset > len(data) or string_size > len(data) - string_offset:
        raise ValueError('invalid VitaSDK ELF section string table')
    strings = data[string_offset:string_offset + string_size]
    hooks = {}
    libraries = []
    for section in sections:
        name_index, kind, flags, address, offset, length, _, _, _, _ = section
        if name_index >= len(strings):
            raise ValueError('section name outside VitaSDK string table')
        end = strings.find(b'\0', name_index)
        if end < 0:
            raise ValueError('unterminated VitaSDK section name')
        name = strings[name_index:end].decode('utf-8', errors='replace')
        if name.startswith('.vitalink.vstubs') and length:
            raise ValueError('VitaSDK variable imports require unsupported linking')
        if not name.startswith('.vitalink.fstubs'):
            continue
        if kind != 1 or length % 16 or address & 3 or offset > len(data) or length > len(data) - offset:
            raise ValueError('invalid VitaSDK function stub section')
        if len(hooks) + length // 16 > MAX_IMPORTS:
            raise ValueError('too many VitaSDK function stubs')
        # A section must be fully mapped with the same file/virtual relationship.
        if not any(segment['flags'] & 1 and
                   segment['virtual_address'] <= address and
                   address + length <= segment['virtual_address'] + segment['file_size'] and
                   offset - segment['file_offset'] == address - segment['virtual_address']
                   for segment in elf['segments']):
            raise ValueError('VitaSDK stubs outside executable mapped bytes')
        for relative in range(0, length, 16):
            stub_flags, library_nid, nid, _ = struct.unpack_from('<IIII', data, offset + relative)
            stub = address + relative
            if stub in hooks:
                raise ValueError('duplicate VitaSDK import stub')
            hooks[stub] = nid
            libraries.append({'name': name.rsplit('.', 1)[-1],
                              'nid': library_nid, 'flags': stub_flags,
                              'function_nid': nid, 'stub': stub})
    if not hooks:
        if allow_missing:return None
        raise ValueError('no official VitaSDK function stub sections found')
    entry = elf['entry_point']
    address, width = entry & ~1, 2 if entry & 1 else 4
    if (not entry & 1 and address & 3) or not any(
            segment['flags'] & 1 and segment['virtual_address'] <= address and
            address + width <= segment['virtual_address'] + segment['file_size']
            for segment in elf['segments']):
        raise ValueError('VitaSDK entry outside executable mapped bytes')
    return {'path': str(path), 'format': 'VitaSDK_linked_ELF',
            'elf_type': 2, 'entry': entry, 'imports': hooks,
            'libraries': libraries, 'relocations_applied': False,
            'limitations': ['linked ET_EXEC addresses; no rebasing',
                            'variable imports unsupported',
                            'stub metadata is not compiler provenance proof']}


def validate_identity_relocations(path):
    """Validate SDK long-form SCE relocations at their original linked addresses.

    No image rebasing is performed and no source bytes are changed. Every record
    must reproduce the existing encoded value; otherwise conversion must stop.
    This is narrower than a dynamic SCE linker and deliberately rejects paired,
    compressed and variable-import relocation encodings.
    """
    path = Path(path)
    elf = inspect_elf_segments(path)
    if elf['elf_type'] not in (ET_SCE_EXEC, ET_SCE_RELEXEC):
        raise ValueError('identity SCE relocation validation requires SCE ELF')
    data = path.read_bytes()
    segments = elf['segments']
    phoff = struct.unpack_from('<I', data, 28)[0]
    phentsize, phnum = struct.unpack_from('<HH', data, 42)
    count = 0
    types = {}
    for index in range(phnum):
        typ, offset, _, _, length = struct.unpack_from('<IIIII', data, phoff + index * phentsize)
        if typ != PT_SCE_RELA:
            continue
        if offset > len(data) or length > len(data)-offset or length > MAX_TABLE_BYTES or length % 12:
            raise ValueError('invalid long-form SCE relocation extent')
        for position in range(offset, offset+length, 12):
            first, addend, site_offset = struct.unpack_from('<III', data, position)
            if first & 15 or first >> 20:
                raise ValueError('only unpaired long-form SCE relocations supported')
            symbol_index, code, data_index = (first >> 4)&15, (first >> 8)&255, (first >> 16)&15
            if symbol_index >= len(segments) or data_index >= len(segments):
                raise ValueError('SCE relocation references missing segment')
            symbol_segment, site_segment = segments[symbol_index], segments[data_index]
            if site_offset > site_segment['file_size'] or 4 > site_segment['file_size']-site_offset:
                raise ValueError('SCE relocation site outside file-backed segment')
            site_address=site_segment['virtual_address']+site_offset
            if site_address > 0xffffffff:
                raise ValueError('SCE relocation site address overflow')
            file_offset=site_segment['file_offset']+site_offset
            word=struct.unpack_from('<I',data,file_offset)[0]
            target=(symbol_segment['virtual_address']+addend)&0xffffffff
            relative=(target-site_address)&0xffffffff
            if code in (2,38):  # ABS32 / TARGET1
                actual,expected=word,target
            elif code in (3,41):  # REL32 / TARGET2
                actual,expected=word,relative
            elif code==42:  # PREL31: top bit belongs to unwind descriptor
                actual,expected=word&0x7fffffff,relative&0x7fffffff
            elif code in (43,44):  # ARM MOVW/MOVT absolute
                instruction=word&0x0ff00000
                if instruction != (0x03000000 if code==43 else 0x03400000):
                    raise ValueError('SCE ARM MOV relocation opcode mismatch')
                actual=((word>>4)&0xf000)|(word&0xfff)
                expected=(target if code==43 else target>>16)&0xffff
            elif code in (47,48):  # Thumb MOVW/MOVT absolute
                first_half,second_half=word&0xffff,word>>16
                if first_half&0xfbf0 != (0xf240 if code==47 else 0xf2c0) or second_half&0x8000:
                    raise ValueError('SCE Thumb MOV relocation opcode mismatch')
                actual=((first_half&15)<<12)|(((first_half>>10)&1)<<11)|(((second_half>>12)&7)<<8)|(second_half&255)
                expected=(target if code==47 else target>>16)&0xffff
            elif code in (28,29):  # ARM CALL / JUMP24
                blx = word & 0xfe000000 == 0xfa000000
                if word&0x0e000000 != 0x0a000000 or (word>>28==15 and not (blx and code==28)):
                    raise ValueError('SCE ARM branch relocation opcode unsupported')
                if blx:
                    actual = ((word&0xffffff)<<2)|((word>>23)&2)
                    expected = relative&0x3ffffff
                else:
                    actual,expected=word&0xffffff,(relative>>2)&0xffffff
                signed=relative if relative<0x80000000 else relative-0x100000000
                if relative&(1 if blx else 3) or not -(1<<25)<=signed<(1<<25):
                    raise ValueError('SCE ARM branch relocation out of range')
            elif code==10:  # THM_CALL BL / BLX immediate
                upper,lower=word&0xffff,word>>16
                thumb=lower&0xd000==0xd000
                blx=lower&0xd001==0xc000
                if upper&0xf800 != 0xf000 or not (thumb or blx):
                    raise ValueError('SCE Thumb branch relocation opcode unsupported')
                sign=(upper>>10)&1
                bit1=1^((lower>>13)&1)^sign
                bit2=1^((lower>>11)&1)^sign
                actual=(sign<<24)|(bit1<<23)|(bit2<<22)|((upper&1023)<<12)|((lower&2047)<<1)
                expected=relative&0x1fffffe
                signed=relative if relative<0x80000000 else relative-0x100000000
                if (not thumb and relative&3) or not -(1<<24)<=signed<(1<<24):
                    raise ValueError('SCE Thumb branch relocation out of range')
            else:
                raise ValueError(f'unsupported identity SCE relocation type {code}')
            if actual!=expected:
                raise ValueError(f'SCE relocation type {code} at {site_address:#x} requires unsupported rebasing: encoded {actual:#x}, expected {expected:#x}')
            count+=1
            types[code]=types.get(code,0)+1
    return {'identity_load_validated':True, 'relocation_count':count,
            'types':types, 'image_modified':False,
            'policy':'every SCE relocation matches existing bytes at declared segment virtual addresses'}
