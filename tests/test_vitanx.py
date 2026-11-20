import tempfile
import unittest
from pathlib import Path
from vitanx.cli import inspect,convert
from vitanx.fallback import TranslationCache
import test_recompiler as support

class VitanxTests(unittest.TestCase):
    def test_plaintext_preflight_rejects_self_and_wrong_arch(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'x.elf'; p.write_bytes(b'SCE\0'+bytes(100))
            with self.assertRaisesRegex(ValueError,'SELF'): inspect(p)
            data=support.elf([0xe3a0002a,0xe12fff1e]); data[18]=183; p.write_bytes(data)
            with self.assertRaisesRegex(ValueError,'ARM'): inspect(p)
            with self.assertRaises(ValueError): convert(p,Path(d)/'out')
            self.assertFalse((Path(d)/'out').exists())

    def test_fallback_cache_bounds_and_input_mutation(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'x.elf'; p.write_bytes(support.elf([0xe3a0002a,0xe12fff1e]))
            cache=TranslationCache(p,max_blocks=1)
            block=cache.request(0x100)
            self.assertIs(cache.request(0x100),block)
            # Execute the independently generated fallback translation with the
            # existing native harness; live dispatcher integration is still absent.
            support.RecompilerTests().run_code(block,checks='if(r[0]!=42)return 19;')
            with self.assertRaisesRegex(RuntimeError,'budget'): cache.request(0x104)
            p.write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError,'changed'): cache.request(0x100)
