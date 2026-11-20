import struct
import tempfile
import unittest
from pathlib import Path
from vitaxnative.elf_segments import inspect_elf_segments


def fixture(offset=84, filesz=4, memsz=8):
    h = bytearray(88)
    h[:7] = b'\x7fELF\x01\x01\x01'
    struct.pack_into('<HHIIIIIHHHHHH', h, 16, 2, 40, 1, 0x1000, 52, 0, 0, 52, 32, 1, 0, 0, 0)
    struct.pack_into('<IIIIIIII', h, 52, 1, offset, 0x1000, 0, filesz, memsz, 5, 4)
    h[84:88] = b'ABCD'
    return h


class ElfSegmentTests(unittest.TestCase):
    def check(self, data):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'eboot.elf'
            p.write_bytes(data)
            return inspect_elf_segments(p)

    def test_valid_arm_segment(self):
        r = self.check(fixture())
        self.assertEqual(r['segments'][0]['file_size'], 4)
        self.assertFalse(r['recompiled'])

    def test_reject_segment_outside_file(self):
        with self.assertRaisesRegex(ValueError, 'segment'):
            self.check(fixture(offset=200))

    def test_reject_mem_smaller_than_file(self):
        with self.assertRaisesRegex(ValueError, 'segment'):
            self.check(fixture(memsz=2))

    def test_reject_self(self):
        with self.assertRaisesRegex(ValueError, 'SCE/SELF'):
            self.check(b'SCE\x00' + bytes(84))

    def test_reject_header_table_outside_file(self):
        b = fixture()
        struct.pack_into('<I', b, 28, 1000)
        with self.assertRaisesRegex(ValueError, 'header table'):
            self.check(b)
