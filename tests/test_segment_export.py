import json
import tempfile
import unittest
from pathlib import Path
from test_elf_segments import fixture
from vitaxnative.segment_export import export_segments

class SegmentExportTests(unittest.TestCase):
    def test_exports_and_manifest(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            src = root / 'test.elf'
            src.write_bytes(fixture())
            output = root / 'export'
            result = export_segments(src, output)
            self.assertEqual(result['segments'], 1)
            self.assertEqual((output / 'segment-000.bin').read_bytes(), b'ABCD')
            self.assertFalse(json.loads((output / 'manifest.json').read_text())['recompiled'])
            with self.assertRaises(FileExistsError):
                export_segments(src, output)

    def test_self_rejected_without_output(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            src = root / 'eboot.bin'
            src.write_bytes(b'SCE\0' + bytes(100))
            with self.assertRaisesRegex(ValueError, 'SCE/SELF'):
                export_segments(src, root / 'export')
            self.assertFalse((root / 'export').exists())
