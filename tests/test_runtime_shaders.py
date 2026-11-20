"""Original runtime bytes, trusted host translation, stable native metadata."""
import ctypes as C
import json
from pathlib import Path
import platform
import struct
import tempfile
import unittest
from vitanx.dynamic import NativeSession
from vitanx.graphics import RuntimeShaderTranslator,_Shader
from vitaxnative.gxp import inspect_gxp
import test_recompiler as support
from test_usse import vertex

class RuntimeShaderParserTests(unittest.TestCase):
    def test_v14_varyings_can_reuse_optional_header_tail(self):
        # Genuine 1.4 layout's varyings begin at152; later headers use156.
        data=vertex();data[5]=4
        data[152:184]=data[156:188]
        struct.pack_into('<I',data,44,152-44)
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'v.gxp';path.write_bytes(data)
            info=inspect_gxp(path)
            self.assertEqual(next(r['offset'] for r in info['regions'] if r['name']=='varyings'),152)
            struct.pack_into('<I',data,44,148-44);path.write_bytes(data)
            with self.assertRaises(ValueError):inspect_gxp(path)

@unittest.skipUnless(platform.system()=='Darwin' and platform.machine()=='arm64','Apple Silicon required')
class RuntimeShaderBridgeTests(unittest.TestCase):
    def test_original_guest_registration_translates_and_rejects_unknown_code(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);elf=root/'x.elf';elf.write_bytes(support.elf([0xe3a0002a,0xe12fff1e]))
            session=NativeSession(elf,root/'media',media=True)
            translator=getattr(session,'runtime_shaders',None) or RuntimeShaderTranslator(session.runtime,session.output)
            rt=session.runtime;rt.vx_runtime_set_memory_base(session.base)
            rt.vn_import.argtypes=[C.c_uint32,C.POINTER(C.c_uint32),C.POINTER(C.c_uint8),C.c_size_t]
            rt.vn_import.restype=C.c_uint32
            start=session.heap_offset;base=session.base+start
            def store(off,data):C.memmove(C.addressof(session.memory)+start+off,data,len(data))
            def word(off):return struct.unpack('<I',bytes(session.memory[start+off:start+off+4]))[0]
            def call(nid,*args):
                r=(C.c_uint32*16)(*args)
                return rt.vn_import(nid,r,session.memory,len(session.memory))
            store(16,struct.pack('<I',0x40000))
            self.assertEqual(call(0xb0f1e4ec,base),0)
            self.assertEqual(call(0x05032658,base+128,base+256),0)
            patcher=word(256);self.assertNotEqual(patcher,0)
            original=bytes(vertex());store(512,original)
            self.assertEqual(call(0x2b528462,patcher,base+512,base+260),0)
            pointer=next(v for v in translator.entries.values() if v)
            metadata=C.cast(pointer,C.POINTER(_Shader)).contents
            self.assertEqual(C.string_at(metadata.gxp,metadata.size),original)
            mutated=bytearray(original);struct.pack_into('<Q',mutated,200,0xffffffffffffffff);store(512,bytes(mutated))
            self.assertEqual(call(0x2b528462,patcher,base+512,base+264),0x805b0009)
            self.assertEqual(call(0x2b528462,patcher,base+512,base+264),0x805b0009)
            self.assertEqual(C.string_at(metadata.gxp,metadata.size),original)
            report=translator.report();self.assertEqual(report['unique_programs'],2)
            self.assertEqual(report['translated'],1);self.assertEqual(report['unsupported'],1)
            self.assertIn('USSE',report['programs'][1]['reason'])
            self.assertEqual(len(json.loads((translator.output/'diagnostics.json').read_text())),2)
            # Disk failures are contained at the C boundary, never unraisable.
            translator._resolve=lambda *_: (_ for _ in ()).throw(OSError('disk full'))
            self.assertIsNone(translator._safe_resolve(None,156))
            session.runtime.vx_runtime_shutdown()
