"""Original ARM media imports through the exact-qualified module linker.

Invalid audio parameters avoid opening a device. Input before display creation
must write neutral samples into the same guest memory used by native regions.
"""
import importlib.util
from pathlib import Path
import platform
import shutil
import struct
import tempfile
import unittest
from vitanx.modules import ModuleSession
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('media_module_fixture',ROOT/'fixtures/modules/build.py')
fixture=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixture)
SOURCE=r'''
.syntax unified
.arch armv7-a
.fpu neon
.arm
.global _start,state,state_ptr,import_a,import_ctrl
.text
_start:
 push {r4,lr}
 ldr r4,state_ptr
 mov r0,#3
 bl import_a
 str r0,[r4]
 mov r0,#0
 add r1,r4,#64
 mov r2,#1
 bl import_ctrl
 str r0,[r4,#4]
 mov r0,#42
 pop {r4,pc}
import_a: bx lr
 nop
 nop
 nop
import_ctrl: bx lr
 nop
 nop
 nop
state_ptr: .word state
.data
state: .space 128
'''
def build(folder):
    path,symbols=fixture.build_one(folder,'media_devices',SOURCE)
    data=bytearray(path.read_bytes())
    # Two public import descriptors use independently qualified libraries.
    struct.pack_into('<I',data,0x100+0x800+0x30,0xa68)
    for index,(library,nid,symbol) in enumerate(((0x438bb957,0x5bc341e4,'import_a'),(0xd197e3c7,0xa9c3ced6,'import_ctrl'))):
        descriptor=0x100+0xa00+index*0x34;table=0xc00+index*8
        struct.pack_into('<BBHHHHH',data,descriptor,0x34,0,1,0,1,0,0)
        struct.pack_into('<II',data,descriptor+0x10,library,0)
        struct.pack_into('<II',data,descriptor+0x1c,0x10000+table,0x10000+table+4)
        struct.pack_into('<II',data,0x100+table,nid,symbols[symbol])
    path.write_bytes(data)
    return path

@unittest.skipUnless(platform.system()=='Darwin' and shutil.which('ld.lld'),'Apple media frameworks and LLD required')
class MediaDeviceIntegrationTests(unittest.TestCase):
    def test_exact_imports_native_guest_memory_and_registers(self):
        with tempfile.TemporaryDirectory() as d:
            d=Path(d);path=build(d/'input')
            session=ModuleSession([path],d/'enabled',media=True)
            session.state.r[8]=0x12345678;session.state.f[63]=0x7fc12345
            report=session.run()
            self.assertEqual(report['status'],0,report)
            self.assertEqual(report['r'][0],42)
            self.assertEqual(report['r'][8],0x12345678)
            self.assertEqual(report['f'][63],0x7fc12345)
            offset=session.process.modules[0].new_base+0x1000-session.base
            memory=bytes(session.memory[offset:offset+96])
            self.assertEqual(struct.unpack_from('<II',memory),(0x8026000a,1))
            self.assertEqual(memory[72:76],bytes(4)) # no buttons
            self.assertEqual(memory[76:80],bytes([128])*4) # neutral sticks
            self.assertEqual(memory[80:96],bytes(16))
            self.assertEqual(report['media']['audio']['ports_opened'],0)
            # Without optional media bindings, an identical exact import traps.
            disabled=ModuleSession([path],d/'disabled',media=False,allow_unresolved=True)
            stopped=disabled.run()
            self.assertEqual(stopped['status'],-9,stopped)
            self.assertEqual(stopped['fault_context']['library_nid'],'438bb957')
            self.assertEqual(stopped['fault_context']['function_nid'],'5bc341e4')
