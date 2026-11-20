import struct
import tempfile
from pathlib import Path
import unittest
import zlib
from vitaxnative.self_extract import extract_self, inspect_self_layout
from vitaxnative.elf_segments import inspect_elf_segments


def fixture(compressed=False, encryption=2):
    payload = b'\x01\x00\xa0\xe3\x1e\xff\x2f\xe1'
    stored = zlib.compress(payload) if compressed else payload
    data = bytearray(4096 + len(stored))
    struct.pack_into('<4sIHHIQQQ', data, 0, b'SCE\0', 3, 0xC0, 1, 0, 4096, 264, len(data))
    struct.pack_into('<QQQ', data, 64, 160, 224, 0)
    struct.pack_into('<Q', data, 88, 256)
    ident = b'\x7fELF\x01\x01\x01' + bytes(9)
    struct.pack_into('<16sHHIIIIIHHHHHH', data, 160, ident, 2, 40, 1, 0x81000000, 52, 0, 0, 52, 32, 1, 0, 0, 0)
    struct.pack_into('<IIIIIIII', data, 224, 1, 256, 0x81000000, 0, 8, 8, 5, 4)
    struct.pack_into('<QQQQ', data, 256, 4096, len(stored), 2 if compressed else 1, encryption)
    data[4096:] = stored
    return data


class ExtractionTests(unittest.TestCase):
    def test_plain_and_zlib_roundtrip(self):
        for compressed in (False, True):
            with self.subTest(compressed=compressed), tempfile.TemporaryDirectory() as tmp:
                src, out = Path(tmp)/'eboot.bin', Path(tmp)/'out.elf'
                original = fixture(compressed)
                src.write_bytes(original)
                result = extract_self(src, out)
                self.assertTrue(result['elf_extracted'])
                manifest = inspect_elf_segments(out)
                self.assertEqual(manifest['segments'][0]['file_size'], 8)
                self.assertEqual(out.read_bytes()[256:], b'\x01\x00\xa0\xe3\x1e\xff\x2f\xe1')
                self.assertEqual(src.read_bytes(), original)
                with self.assertRaises(FileExistsError): extract_self(src, out)

    def test_reject_encrypted_even_if_payload_is_plain(self):
        with tempfile.TemporaryDirectory() as tmp:
            src, out = Path(tmp)/'in', Path(tmp)/'out'
            src.write_bytes(fixture(encryption=1))
            with self.assertRaisesRegex(ValueError, 'encrypted SELF'): extract_self(src, out)
            self.assertFalse(out.exists())

    def test_bounds_and_corrupt_compression(self):
        for mutate in ('bounds', 'zlib', 'overlap', 'unknown'):
            with self.subTest(mutate=mutate), tempfile.TemporaryDirectory() as tmp:
                data = fixture(True)
                if mutate == 'bounds': struct.pack_into('<Q', data, 256, len(data)+1)
                if mutate == 'zlib': data[4096:] = bytes(len(data)-4096)
                if mutate == 'overlap': struct.pack_into('<I', data, 228, 52)
                if mutate == 'unknown': struct.pack_into('<Q', data, 280, 3)
                src, out = Path(tmp)/'in', Path(tmp)/'out'
                src.write_bytes(data)
                with self.assertRaises(ValueError): extract_self(src, out)
                self.assertFalse(out.exists())
