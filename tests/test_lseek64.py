import ctypes as C
from pathlib import Path
import struct,tempfile,unittest
from vitanx.dynamic import NativeSession
import test_recompiler as support
class Seek64Tests(unittest.TestCase):
    def test_i64_offsets_results_errors_and_readonly_assets(self):
        with tempfile.TemporaryDirectory() as d:
            d=Path(d);source=d/'tiny.elf';source.write_bytes(support.elf([0xe12fff1e]))
            assets=d/'assets';assets.mkdir();file=assets/'data';file.write_bytes(b'0123456789')
            s=NativeSession(source,d/'run');lib=s.runtime
            lib.vx_runtime_mount_app.argtypes=[C.c_char_p]
            self.assertEqual(lib.vx_runtime_mount_app(str(assets).encode()),0)
            lib.vn_import.argtypes=[C.c_uint32,C.POINTER(C.c_uint32),C.POINTER(C.c_uint8),C.c_size_t];lib.vn_import.restype=C.c_uint32
            r=(C.c_uint32*16)();r[0]=0x300;r[1]=1;r[2]=0
            C.memmove(C.addressof(s.memory)+0x300,b'app0:/data\0',11)
            fd=lib.vn_import(0x6c60ac61,r,s.memory,len(s.memory));self.assertLess(fd,0x80000000)
            def seek(offset,origin,descriptor=fd):
                for i in range(16):r[i]=0
                r[0]=descriptor;r[1]=0xdeadbeef;r[2]=offset&0xffffffff;r[3]=(offset>>32)&0xffffffff;r[13]=0x700
                data=struct.pack('<I',origin);C.memmove(C.addressof(s.memory)+0x700,data,4)
                lib.vn_import(0x99ba173e,r,s.memory,len(s.memory))
                return (int(r[1])<<32)|r[0]
            self.assertEqual(seek(0,2),10)
            self.assertEqual(seek((1<<32)+17,0),(1<<32)+17)
            self.assertEqual(seek(-1,1),(1<<32)+16)
            bad=seek(0,99);self.assertEqual(bad>>32,0xffffffff)
            self.assertEqual(seek(0,1),(1<<32)+16)
            self.assertEqual(seek(-1,0)>>32,0xffffffff)
            self.assertEqual(seek(0,0,999)>>32,0xffffffff)
            self.assertEqual(file.read_bytes(),b'0123456789')
            r[0]=fd;lib.vn_import(0xc70b8886,r,s.memory,len(s.memory));lib.vx_runtime_shutdown()
