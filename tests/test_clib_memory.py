import ctypes as C
from pathlib import Path
import tempfile,unittest
from vitanx.dynamic import NativeSession
import test_recompiler as support

class ClibMemoryTests(unittest.TestCase):
    def test_native_primitives_bounds_overlap_and_executable_protection(self):
        with tempfile.TemporaryDirectory() as tmp:
            d=Path(tmp);source=d/'memory.elf';source.write_bytes(support.elf([0xe12fff1e]))
            s=NativeSession(source,d/'run');lib=s.runtime
            lib.vn_memory_import.argtypes=[C.c_uint32,C.POINTER(C.c_uint32),C.POINTER(C.c_uint8),C.c_size_t,C.c_uint32,C.POINTER(C.c_uint32)]
            result=C.c_uint32();r=(C.c_uint32*16)()
            def call(nid,a,b,n):
                r[0]=a;r[1]=b;r[2]=n
                return lib.vn_memory_import(nid,r,s.memory,len(s.memory),0,C.byref(result))
            self.assertEqual(call(0x632980d7,0x300,0x1234,8),1)
            self.assertEqual(result.value,0x300);self.assertEqual(bytes(s.memory[0x300:0x308]),b'4'*8)
            C.memmove(C.addressof(s.memory)+0x300,b'abcdef\0',7)
            self.assertEqual(call(0x736753c8,0x302,0x300,6),1)
            self.assertEqual(bytes(s.memory[0x300:0x308]),b'ababcdef')
            self.assertEqual(call(0x14e9dbd7,0x310,0x300,8),1)
            self.assertEqual(call(0x9cc2bfdf,0x310,0x300,8),1);self.assertEqual(result.value,0)
            self.assertEqual(call(0x407d6153,0x300,ord('c'),8),1);self.assertEqual(result.value,0x304)
            self.assertEqual(call(0xac595e68,0x300,8,0),1);self.assertEqual(result.value,8)
            s.memory[-2]=ord('z');s.memory[-1]=0
            self.assertEqual(call(0xac595e68,len(s.memory)-2,100,0),1);self.assertEqual(result.value,1)
            before=bytes(s.memory[-8:]);self.assertEqual(call(0x632980d7,len(s.memory)-4,0x55,8),-1)
            self.assertEqual(bytes(s.memory[-8:]),before)
            before=bytes(s.memory[0x100:0x104]);self.assertEqual(call(0x632980d7,0x100,0x55,4),-1)
            self.assertEqual(bytes(s.memory[0x100:0x104]),before)
            self.assertEqual(call(0x632980d7,0xffffffff,0x55,0),1);self.assertEqual(result.value,0xffffffff)
    def test_translated_caller_receives_guest_pointer_and_fault_does_not_continue(self):
        with tempfile.TemporaryDirectory() as tmp:
            d=Path(tmp);source=d/'memory.elf';source.write_bytes(support.elf([0xe92d4010,0xe12fff34,0xe8bd8010]))
            s=NativeSession(source,d/'run',imports={0x2000:0x632980d7})
            s.state.r[0]=0x300;s.state.r[1]=0xff;s.state.r[2]=44;s.state.r[4]=0x2000
            report=s.run();self.assertEqual(report['status'],0,report);self.assertEqual(report['r'][0],0x300)
            self.assertEqual(bytes(s.memory[0x300:0x32c]),b'\xff'*44)
            bad=NativeSession(source,d/'bad',imports={0x2000:0x632980d7})
            bad.state.r[0]=0x100;bad.state.r[1]=0xff;bad.state.r[2]=4;bad.state.r[4]=0x2000
            before=bytes(bad.memory[0x100:0x104]);report=bad.run()
            self.assertEqual(report['status'],-9,report);self.assertIn('executable',report['error'])
            self.assertEqual(bytes(bad.memory[0x100:0x104]),before)
