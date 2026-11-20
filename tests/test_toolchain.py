import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from vitaxnative.toolchain import diagnose, smoke_test

class ToolchainTests(unittest.TestCase):
    def test_diagnostics_disclose_missing_backends(self):
        with patch('vitaxnative.toolchain.platform.system', return_value='Darwin'), \
             patch('vitaxnative.toolchain.platform.machine', return_value='arm64'), \
             patch('vitaxnative.toolchain.shutil.which', return_value=None):
            data = diagnose()
        self.assertFalse(data['native_arm64_build_supported'])
        self.assertFalse(data['vita_recompiler'])
        self.assertFalse(data['metal_backend'])

    def test_smoke_test_rejects_unsupported_host(self):
        with tempfile.TemporaryDirectory() as tmp, patch('vitaxnative.toolchain.diagnose', return_value={'native_arm64_build_supported': False}):
            with self.assertRaisesRegex(RuntimeError, 'Apple Silicon Mac'):
                smoke_test(Path(tmp))
            self.assertEqual(list(Path(tmp).iterdir()), [])

if __name__ == '__main__': unittest.main()
