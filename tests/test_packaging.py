import plistlib
import struct
import tempfile
import unittest
from pathlib import Path
from vitaxnative.packaging import package_native

class PackagingTests(unittest.TestCase):
    def test_rejects_vita_elf(self):
        with tempfile.TemporaryDirectory() as d:
            f=Path(d)/'eboot.bin'; f.write_bytes(b'\x7fELF'+b'\0'*64)
            with self.assertRaises(ValueError): package_native(f, Path(d), 'Vita Game', 'org.example.vita')
    def test_packages_arm64_header_and_prevents_overwrite(self):
        with tempfile.TemporaryDirectory() as d:
            f=Path(d)/'native'; f.write_bytes(struct.pack('<III', 0xfeedfacf, 0x0100000c, 0)+b'\0'*64)
            app=package_native(f, Path(d), 'Native Test', 'org.example.native')
            with (app/'Contents'/'Info.plist').open('rb') as h: info=plistlib.load(h)
            self.assertEqual(info['CFBundleExecutable'], 'Game')
            self.assertTrue((app/'Contents'/'MacOS'/'Game').exists())
            with self.assertRaises(FileExistsError): package_native(f, Path(d), 'Native Test', 'org.example.native')
    def test_invalid_name(self):
        with tempfile.TemporaryDirectory() as d:
            f=Path(d)/'native'; f.write_bytes(struct.pack('<III', 0xfeedfacf, 0x0100000c, 0)+b'\0'*64)
            with self.assertRaises(ValueError): package_native(f, Path(d), '../bad', 'org.example.bad')
if __name__ == '__main__': unittest.main()
