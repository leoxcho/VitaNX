import struct,tempfile,unittest
from pathlib import Path
from test_module_execution import fixture
from vitanx.modules import ModuleSession

class AppUtilExecutionTests(unittest.TestCase):
    def test_translated_arm_initializes_queries_and_shuts_down(self):
        with tempfile.TemporaryDirectory() as tmp:
            d=Path(tmp)
            code=fixture.MAIN.replace(' bl import_a', ''' sub sp,sp,#112
 mov r1,sp
 mov r2,#28
 mov r3,#0
clear_params:
 str r3,[r1],#4
 subs r2,r2,#1
 bne clear_params
 mov r0,sp
 add r1,sp,#64
 bl import_a
 cmp r0,#0
 bne appfail
 mov r0,#1
 add r1,sp,#104
 bl system_int
 cmp r0,#0
 bne appfail
 ldr r0,[sp,#104]
 cmp r0,#1
 bne appfail
 bl shutdown
 cmp r0,#0
 bne appfail
 add sp,sp,#112
 mov r0,#42
 b after_app
appfail:
 add sp,sp,#112
 b failure
after_app:''').replace('state_ptr: .word state', '''.global system_int,shutdown
system_int: bx lr
 nop
shutdown: bx lr
 nop
state_ptr: .word state''')
            main,sym=fixture.build_one(d/'input','main',code)
            raw=bytearray(main.read_bytes());struct.pack_into('<H',raw,0x100+0xa00+6,3)
            struct.pack_into('<I',raw,0x100+0xa10,0x48e01d74)
            struct.pack_into('<II',raw,0x100+0xa1c,0x10c00,0x10c0c)
            struct.pack_into('<IIIIII',raw,0x100+0xc00,0xdaffe671,0x5dfb9ca0,0xb220b00b,sym['import_a'],sym['system_int'],sym['shutdown']);main.write_bytes(raw)
            session=ModuleSession([main],d/'run');sp=session.state.r[13]
            report=session.run()
            self.assertEqual(report['status'],0,report)
            self.assertEqual(report['r'][0],42);self.assertEqual(report['r'][13],sp)
            self.assertEqual(report['f'][0],5)
            self.assertFalse(report['apputil']['initialized'])
            self.assertEqual([x['name'] for x in report['apputil']['trace']],['init','system_int','shutdown'])
            self.assertEqual([x['result'] for x in report['apputil']['trace']],[0,0,0])
