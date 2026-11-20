"""Opt-in live GXM backend integration; no device or game launch required."""
import ctypes as C
import json
from pathlib import Path
import platform
import tempfile
import unittest
from vitanx.dynamic import NativeSession
from vitanx.graphics import media_bindings
import test_recompiler as support

@unittest.skipUnless(platform.system()=='Darwin' and platform.machine()=='arm64','Apple Silicon required')
class MediaRuntimeTests(unittest.TestCase):
    def test_gxm_shared_memory_and_feature_cache_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);elf=root/'x.elf';elf.write_bytes(support.elf([0xe3a0002a,0xe12fff1e]))
            plain=NativeSession(elf,root/'plain')
            enabled=NativeSession(elf,root/'media',media=True,native_cache=root/'plain')
            self.assertFalse(enabled.cache_runtime_ok)
            self.assertTrue(enabled.cache_abi_ok)
            self.assertTrue(all(e['cache_hit'] for e in enabled.build_events))
            self.assertEqual(json.loads((root/'media/runtime-build.json').read_text()),{'media':True,'schema':1})
            runtime=enabled.runtime
            runtime.vn_import.argtypes=[C.c_uint32,C.POINTER(C.c_uint32),C.POINTER(C.c_uint8),C.c_size_t]
            runtime.vn_import.restype=C.c_uint32
            runtime.vx_runtime_set_memory_base(enabled.base)
            offset=enabled.heap_offset;pointer=enabled.base+offset
            # GXM initializer consumes original guest bytes through shared backing.
            C.memmove(C.addressof(enabled.memory)+offset+16,(C.c_uint32*1)(0x40000),4)
            regs=(C.c_uint32*16)();regs[0]=pointer
            self.assertEqual(runtime.vn_import(0xb0f1e4ec,regs,enabled.memory,len(enabled.memory)),0)
            regs[0]=0
            self.assertEqual(runtime.vn_import(0x45229c39,regs,enabled.memory,len(enabled.memory)),0)
            report=enabled.run();self.assertEqual(report['r'][0],42)
            self.assertEqual(report['media']['gxm']['draws'],0)
            self.assertEqual(report['media']['audio']['ports_opened'],0)
            self.assertEqual(report['media']['display']['frames_presented'],0)
            cached=NativeSession(elf,root/'cached',media=True,native_cache=root/'media')
            self.assertTrue(cached.cache_runtime_ok)
            self.assertEqual(cached.run()['r'][0],42)
            plain.runtime.vx_runtime_shutdown()

    def test_all_media_exports_have_exact_library_identity(self):
        bindings=media_bindings()
        self.assertEqual(len(bindings),102)
        self.assertEqual(bindings[('f76b66bd','b0f1e4ec')],0xb0f1e4ec)
        self.assertNotIn(('00000000','b0f1e4ec'),bindings)
