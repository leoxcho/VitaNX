"""Exact native dispatch index, including tagged Thumb PCs and import hooks."""
import ctypes as C
import tempfile,unittest
from pathlib import Path
from vitanx.dynamic import NativeSession
from vitaxnative.recompiler import translate_elf
import test_recompiler as support

class RegionDispatchTests(unittest.TestCase):
    def test_index_matches_native_validator_and_preserves_cached_code(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);elf=p/'x.elf';elf.write_bytes(support.elf([0xe3a0002a,0xe12fff1e]))
            session=NativeSession(elf,p/'run')
            translation=session.initial
            self.assertEqual(translation['dispatch_addresses'],[0x100,0x104])
            for pc in range(0xfc,0x10b):
                self.assertEqual(int(pc in session.region_by_pc),session.active_validator(pc))
            report=session.run();self.assertEqual(report['r'][0],42)
            cached=NativeSession(elf,p/'cached',native_cache=p/'run')
            self.assertTrue(cached.build_events[0]['cache_hit'])
            self.assertEqual(cached.run()['r'][0],42)
