import ctypes as C
from pathlib import Path
import struct,subprocess,tempfile,unittest
from vitanx.dynamic import NativeSession
import test_recompiler as support
ROOT=Path(__file__).resolve().parents[1]
class FormatBridgeTests(unittest.TestCase):
    def test_compiled_arm_variadic_registers_stack_and_i64_alignment(self):
        with tempfile.TemporaryDirectory() as d:
            d=Path(d);obj=d/'format.o';source=d/'format.elf'
            subprocess.run(['clang','-target','armv7-none-eabi','-mthumb','-march=armv7-a','-O1','-ffreestanding','-fno-builtin','-fno-unwind-tables','-fno-asynchronous-unwind-tables','-c',str(ROOT/'fixtures/modules/format.c'),'-o',str(obj)],check=True,capture_output=True)
            subprocess.run(['ld.lld','-m','armelf','-T',str(ROOT/'fixtures/homebrew/link.ld'),str(obj),'-o',str(source)],check=True,capture_output=True)
            data=bytearray(source.read_bytes());struct.pack_into('<I',data,32,0);struct.pack_into('<HHH',data,46,0,0,0);source.write_bytes(data)
            report=NativeSession(source,d/'run',imports={0x2000:0x8cba03d5},region_entry=True,partial_regions=True).run()
            self.assertEqual(report['status'],0,report)
            self.assertEqual(report['r'][0],len('key:7FFF8000:1234605616436508552:abc'))
            self.assertEqual(report['runtime_imports'][0]['result'],report['r'][0])

    def test_truncation_zero_size_and_rejected_format_do_not_write(self):
        with tempfile.TemporaryDirectory() as d:
            d=Path(d);source=d/'tiny.elf';source.write_bytes(support.elf([0xe12fff1e]))
            session=NativeSession(source,d/'run');lib=session.runtime
            lib.vn_format_import.argtypes=[C.c_uint32,C.POINTER(C.c_uint32),C.POINTER(C.c_uint8),C.c_size_t,C.c_uint32,C.POINTER(C.c_uint32)]
            r=(C.c_uint32*16)();result=C.c_uint32();r[0]=0x300;r[1]=5;r[2]=0x600;r[3]=0x7fff8000
            C.memmove(C.addressof(session.memory)+0x600,b'SceLibcFileFD:0x%08X\0',21)
            rc=lib.vn_format_import(0x8cba03d5,r,session.memory,len(session.memory),0,C.byref(result))
            self.assertEqual(rc,1);self.assertEqual(result.value,24)
            self.assertEqual(bytes(session.memory[0x300:0x305]),b'SceL\0')
            before=bytes(session.memory[0x300:0x310]);r[0]=0xffffffff;r[1]=0
            self.assertEqual(lib.vn_format_import(0x8cba03d5,r,session.memory,len(session.memory),0,C.byref(result)),1)
            self.assertEqual(result.value,24)
            self.assertEqual(bytes(session.memory[0x300:0x310]),before)
            C.memmove(C.addressof(session.memory)+0x600,b'%f\0',3);r[0]=0x300;r[1]=16
            self.assertEqual(lib.vn_format_import(0x8cba03d5,r,session.memory,len(session.memory),0,C.byref(result)),-1)
            self.assertEqual(bytes(session.memory[0x300:0x310]),before)

    def test_live_unsupported_format_stops_before_caller_continues(self):
        with tempfile.TemporaryDirectory() as d:
            d=Path(d);source=d/'badformat.elf'
            source.write_bytes(support.elf([0xe92d4010,0xe12fff34,0xe3a00063,0xe8bd8010]))
            session=NativeSession(source,d/'run',imports={0x2000:0x8cba03d5})
            session.state.r[0]=0x300;session.state.r[1]=16;session.state.r[2]=0x600;session.state.r[4]=0x2000
            C.memmove(C.addressof(session.memory)+0x600,b'%f\0',3)
            before=bytes(session.memory[0x300:0x310]);report=session.run()
            self.assertEqual(report['status'],-9,report)
            self.assertIn('unsupported snprintf',report['error'])
            self.assertNotEqual(report['r'][0],99)
            self.assertEqual(bytes(session.memory[0x300:0x310]),before)
            self.assertTrue(report['runtime_imports'][-1]['fault'])

    def test_arm_word_sizes_and_first_i64_skip_r3(self):
        with tempfile.TemporaryDirectory() as d:
            d=Path(d);source=d/'wordsize.elf';source.write_bytes(support.elf([0xe12fff1e]))
            s=NativeSession(source,d/'run');lib=s.runtime
            lib.vn_format_import.argtypes=[C.c_uint32,C.POINTER(C.c_uint32),C.POINTER(C.c_uint8),C.c_size_t,C.c_uint32,C.POINTER(C.c_uint32)]
            r=(C.c_uint32*16)();r[0]=0x300;r[1]=64;r[2]=0x600;r[13]=0x700
            result=C.c_uint32()
            for fmt,value,want in [(b'%ld',0xffffffff,b'-1'),(b'%hhd',255,b'-1'),(b'%hhu',255,b'255'),(b'%zu',0xffffffff,b'4294967295')]:
                C.memmove(C.addressof(s.memory)+0x600,fmt+b'\0',len(fmt)+1);r[3]=value
                self.assertEqual(lib.vn_format_import(0x8cba03d5,r,s.memory,len(s.memory),0,C.byref(result)),1)
                self.assertEqual(result.value,len(want))
                self.assertEqual(bytes(s.memory[0x300:0x300+len(want)+1]),want+b'\0')
            C.memmove(C.addressof(s.memory)+0x600,b'%lld\0',5);r[3]=0xdeadbeef
            value=struct.pack('<q',-1234567890123);C.memmove(C.addressof(s.memory)+0x700,value,8)
            self.assertEqual(lib.vn_format_import(0x8cba03d5,r,s.memory,len(s.memory),0,C.byref(result)),1)
            self.assertEqual(bytes(s.memory[0x300:0x30f]),b'-1234567890123\0')
