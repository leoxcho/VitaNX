import struct
import tempfile
import unittest
from pathlib import Path
from vitaxnative.elf_dependencies import inspect_elf_dependencies


def fixture():
    data = bytearray(320)
    data[:7] = b'\x7fELF\x01\x01\x01'
    struct.pack_into('<HHIIIIIHHHHHH', data, 16, 2, 40, 1, 0, 0, 52, 0, 52, 0, 0, 40, 4, 0)
    # null, string table, symbol table, REL section
    struct.pack_into('<IIIIIIIIII', data, 92, 0, 3, 0, 0, 240, 12, 0, 0, 1, 0)
    struct.pack_into('<IIIIIIIIII', data, 132, 0, 2, 0, 0, 256, 32, 1, 0, 4, 16)
    struct.pack_into('<IIIIIIIIII', data, 172, 0, 9, 0, 0, 288, 8, 2, 0, 4, 8)
    data[288:296] = struct.pack('<II', 0x1000, (1 << 8) | 28)
    data[240:252] = b'\x00sceTest\x00xxx'
    struct.pack_into('<IIIBBH', data, 272, 1, 0, 0, 0x12, 0, 0)
    return data


class DependencyTests(unittest.TestCase):
    def check(self, data):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'test.elf'
            p.write_bytes(data)
            return inspect_elf_dependencies(p)

    def test_reject_self(self):
        with self.assertRaisesRegex(ValueError, 'SELF'):
            self.check(b'SCE\x00' + bytes(100))

    def test_no_sections(self):
        b = bytearray(52)
        b[:7] = b'\x7fELF\x01\x01\x01'
        struct.pack_into('<HHIIIIIHHHHHH', b, 16, 2, 40, 1, 0, 0, 0, 0, 52, 0, 0, 0, 0, 0)
        self.assertEqual(self.check(b)['section_count'], 0)

    def test_invalid_section_bounds(self):
        b = fixture()
        struct.pack_into('<I', b, 32, 250)
        with self.assertRaisesRegex(ValueError, 'section header'):
            self.check(b)

    def test_undefined_symbol_and_relocation(self):
        b = fixture()
        result = self.check(b)
        self.assertEqual(result['undefined_symbols'][0]['name'], 'sceTest')
        self.assertEqual(result['relocations'][0]['type'], 28)
        self.assertEqual(result['relocations'][0]['symbol'], 'sceTest')
