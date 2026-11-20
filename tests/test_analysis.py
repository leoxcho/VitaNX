import json
import struct
import tempfile
import unittest
import zipfile
from pathlib import Path
from vitaxnative.analysis import analyze, elf_info, parse_sfo, load_patch_registry

class AnalysisTests(unittest.TestCase):
    def test_elf(self):
        header = bytearray(52); header[:6] = b'\x7fELF\x01\x01'; struct.pack_into('<H', header, 18, 40)
        self.assertTrue(elf_info(header)['armv7_elf'])
    def test_sfo(self):
        key = b'TITLE\x00'; val = b'Demo\x00'
        data = struct.pack('<4sIIII', b'\x00PSF', 0x101, 36, 36+len(key), 1)
        data += struct.pack('<HHIII', 0, 0x0204, len(val), len(val), 0) + key + val
        self.assertEqual(parse_sfo(data)['TITLE'], 'Demo')
    def test_sfo_bad_offset(self):
        with self.assertRaises(ValueError): parse_sfo(b'not-a-valid-sfo')
    def test_traversal_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)/'bad.vpk'
            with zipfile.ZipFile(p, 'w') as z: z.writestr('../escape', 'bad')
            with self.assertRaises(ValueError): analyze(p)
    def test_patch_registry(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'patches.json'; p.write_text(json.dumps({'schema_version':1,'patches':[]}))
            self.assertEqual(load_patch_registry(p)['patches'], [])
    def test_no_false_build_claim(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'demo.vpk'
            with zipfile.ZipFile(p, 'w') as z: z.writestr('eboot.bin', b'not an ELF')
            self.assertFalse(analyze(p)['native_build_available'])

if __name__ == '__main__': unittest.main()
