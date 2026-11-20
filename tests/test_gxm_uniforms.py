"""Native GXM metadata bridge and default-uniform memory ownership checks."""
import ctypes
from pathlib import Path
import platform
import shutil
import struct
import subprocess
import tempfile
import unittest
from test_usse import vertex

ROOT=Path(__file__).resolve().parents[1]


@unittest.skipUnless(platform.system()=='Darwin' and shutil.which('clang'),'macOS Clang required')
class GxmUniformTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        directory=tempfile.TemporaryDirectory();cls.addClassCleanup(directory.cleanup)
        library=Path(directory.name)/'gxm.dylib'
        subprocess.run(['clang','-dynamiclib','-Wall','-Wextra','-Werror','-fobjc-arc','-DVX_ENABLE_GXM',
                        '-I',str(ROOT/'runtime'),str(ROOT/'runtime/vita_runtime.c'),str(ROOT/'runtime/vita_gxm.c'),
                        str(ROOT/'runtime/vita_metal.m'),'-framework','Foundation','-framework','Metal','-o',str(library)],
                       check=True,capture_output=True)
        cls.library=ctypes.CDLL(str(library));cls.call_native=cls.library.vx_gxm_import
        cls.call_native.argtypes=[ctypes.c_uint32,ctypes.POINTER(ctypes.c_uint32),ctypes.POINTER(ctypes.c_uint8),
                                  ctypes.c_size_t,ctypes.c_uint32,ctypes.POINTER(ctypes.c_uint32)]
        cls.call_native.restype=ctypes.c_int

    def setUp(self):
        self.base=0x81000000;self.mem=(ctypes.c_uint8*16384)()
        data=vertex();ctypes.memmove(ctypes.addressof(self.mem)+1024,bytes(data),len(data))

    def call(self,nid,*args):
        regs=(ctypes.c_uint32*16)();regs[13]=self.base+256
        for i,value in enumerate(args):
            if i<4:regs[i]=value
            else:struct.pack_into('<I',self.mem,256+(i-4)*4,value)
        out=ctypes.c_uint32(0xfeed)
        self.assertEqual(self.call_native(nid,regs,self.mem,len(self.mem),self.base,ctypes.byref(out)),1)
        return out.value

    def test_lookup_reflection_and_v15_runtime_registration(self):
        ctypes.memmove(ctypes.addressof(self.mem)+2048,b'gvColor\0',8)
        self.assertEqual(self.call(0xed8b6c69,self.base+1024),0)
        p=self.call(0x277794c4,self.base+1024,self.base+2048)
        self.assertEqual(p,self.base+1024+248)
        self.assertEqual(self.call(0x06ff9151,self.base+1024,1),p)
        self.assertEqual(self.call(0x06ff9151,self.base+1024,2),0)
        self.assertEqual(self.call(0x6e61ddf5,self.base+1024,p),1)
        self.assertEqual(self.call(0x6e61ddf5,self.base+1024,p+1),0xffffffff)
        for nid,expected in ((0x1997dc17,1),(0x7b9023c3,0),(0xbd2998d1,4),
                             (0xdba8d061,1),(0xbb58267d,14),(0x5c79d59a,0)):
            self.assertEqual(self.call(nid,p),expected)
        self.assertEqual(self.call(0x6af88a5d,p),self.base+1024+270)
        self.assertEqual(self.call(0x633caa54,self.base+1024,11,0),self.base+1024+232)

    def test_uniform_writes_are_partial_bounded_and_atomic_on_fault(self):
        p=self.base+1024+248;buffer=self.base+4096;source=self.base+8192
        struct.pack_into('<8I',self.mem,4096,*([0xdeadbeef]*8))
        struct.pack_into('<2I',self.mem,8192,0x80000000,0x7fc01234)
        self.assertEqual(self.call(0x65dd0c84,buffer,p,1,2,source),0)
        self.assertEqual(struct.unpack_from('<4I',self.mem,4096),(0xdeadbeef,0x80000000,0x7fc01234,0xdeadbeef))
        before=bytes(self.mem)
        self.assertEqual(self.call(0x65dd0c84,buffer,p,3,2,source),0x805b0003)
        self.assertEqual(self.call(0x65dd0c84,buffer,p,0,4,self.base+len(self.mem)-4),0x805b0004)
        self.assertEqual(self.call(0x65dd0c84,buffer,p,0,4,source+1),0x805b0004)
        # Exclude the ABI argument stack from the mutation comparison.
        self.assertEqual(bytes(self.mem)[1024:],before[1024:])

    def test_float3_array_padding_cross_element_and_source_overlap(self):
        parameter=1024+248;self.mem[parameter+5]=0xe3
        struct.pack_into('<I',self.mem,parameter+8,2)
        struct.pack_into('<8I',self.mem,4096,*([0xdeadbeef]*8))
        struct.pack_into('<4I',self.mem,8192,1,2,3,4)
        self.assertEqual(self.call(0x65dd0c84,self.base+4096,self.base+parameter,2,4,self.base+8192),0)
        self.assertEqual(struct.unpack_from('<8I',self.mem,4096),(0xdeadbeef,0xdeadbeef,1,0xdeadbeef,2,3,4,0xdeadbeef))
        # Snapshot the entire source before writing overlapping/strided output.
        self.assertEqual(self.call(0x65dd0c84,self.base+4096,self.base+parameter,0,4,self.base+4096+8),0)
        self.assertEqual(struct.unpack_from('<6I',self.mem,4096),(1,0xdeadbeef,2,0xdeadbeef,3,3))

    def test_strided_destination_fault_preserves_entire_buffer(self):
        parameter=1024+248;self.mem[parameter+5]=0xe3
        struct.pack_into('<I',self.mem,parameter+8,2)
        struct.pack_into('<4I',self.mem,8192,1,2,3,4)
        before=bytes(self.mem)[1024:]
        # First write fits, second element crosses guest memory: neither writes.
        self.assertEqual(self.call(0x65dd0c84,self.base+len(self.mem)-12,
                                  self.base+parameter,2,4,self.base+8192),0x805b0004)
        self.assertEqual(bytes(self.mem)[1024:],before)
