import json
import tempfile
import unittest
from pathlib import Path
from vitaxnative.patchplan import plan

class PatchPlanTests(unittest.TestCase):
    def test_no_identity_never_matches(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            game = root / 'eboot.bin'
            game.write_bytes(b'not-an-elf')
            registry = root / 'patches.json'
            registry.write_text(json.dumps({'schema_version': 1, 'patches': [
                {'title_id': 'PCSA00001', 'version': '01.00', 'kind': 'fps', 'status': 'validated'}
            ]}))
            result = plan(game, registry)
            self.assertEqual(result['validated_registry_matches'], [])
            self.assertEqual(result['patches_applied'], 0)
            self.assertFalse(result['fps_unlocked'])

    def test_invalid_registry_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / 'eboot.bin').write_bytes(b'abc')
            (root / 'registry.json').write_text('{"patches":[]}')
            with self.assertRaises(ValueError):
                plan(root / 'eboot.bin', root / 'registry.json')
