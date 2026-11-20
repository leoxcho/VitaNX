import struct
import tempfile
import unittest
from pathlib import Path
from vitaxnative.self_parser import parse_self_header, inspect_self
from vitaxnative.analysis import analyze

class SelfParserTests(unittest.TestCase):
    def sample(self):
        h = bytearray(128)
        h[:4] = b'SCE\x00'
        struct.pack_into('<IHHIQQ', h, 4, 3, 0x140, 1, 0x600, 0x1000, 0x5ab949)
        return h

    def test_gravity_rush_style_header(self):
        result = parse_self_header(self.sample(), 2936784)
        self.assertEqual(result['version'], 3)
        self.assertEqual(result['header_length'], 4096)
        self.assertEqual(result['encryption_status'], 'undetermined')
        self.assertFalse(result['elf_extracted'])

    def test_reject_truncated_header(self):
        with self.assertRaises(ValueError): parse_self_header(b'SCE\x00', 4)

    def test_directory_analysis_detects_self(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root/'eboot.bin').write_bytes(self.sample() + bytes(5000))
            result = analyze(root)
            self.assertEqual(result['executable']['format'], 'SCE_container')
            self.assertFalse(result['native_build_available'])
            self.assertEqual(inspect_self(root/'eboot.bin')['version'], 3)

if __name__ == '__main__': unittest.main()
