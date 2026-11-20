import tempfile
import unittest
import zipfile
from pathlib import Path
from vitaxnative.__main__ import inspect, scan

class InspectorTests(unittest.TestCase):
    def test_archive(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'demo.vpk'
            with zipfile.ZipFile(p, 'w') as z:
                z.writestr('eboot.bin', b'fake')
                z.writestr('sce_sys/param.sfo', b'fake')
            r = inspect(p)
            self.assertTrue(r['has_eboot'])
            self.assertTrue(r['has_sfo'])
            self.assertFalse(r['native_build_available'])
    def test_scan(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / 'sample.elf').write_bytes(b'ELF')
            self.assertEqual(len(list(scan(Path(d)))), 1)
    def test_missing(self):
        with self.assertRaises(FileNotFoundError):
            inspect(Path('/missing-vitaxnative-test'))

if __name__ == '__main__': unittest.main()
