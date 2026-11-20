"""Guest-originated system module loading; original assembled ARM/Thumb inputs."""
import ctypes as C
import struct,tempfile,unittest
from pathlib import Path
from test_module_execution import fixture
from vitanx.modules import ModuleSession,SYSMODULE_FATAL,SYSMODULE_UNLOADED,SYSMODULE_INVALID

class SystemModuleTests(unittest.TestCase):
    def test_guest_load_initializes_once_then_calls_thumb_export(self):
        with tempfile.TemporaryDirectory() as tmp:
            d=Path(tmp)
            code=fixture.MAIN.replace(' bl import_a', ''' mov r0,#15
 bl sysquery
 ldr r1,unloaded
 cmp r0,r1
 bne failure
 mov r0,#15
 bl sysload
 cmp r0,#0
 bne failure
 mov r0,#15
 bl sysload
 cmp r0,#0
 bne failure
 mov r0,#15
 bl sysquery
 cmp r0,#0
 bne failure
 mov r0,#5
 bl import_a''').replace('state_ptr: .word state', '''.global sysload,sysquery
sysload: bx lr
 nop
sysquery: bx lr
 nop
unloaded: .word 0x805a1001
state_ptr: .word state''')
            main,sym=fixture.build_one(d/'inputs','main',code)
            provider,_=fixture.build_one(d/'inputs','support_a',fixture.SUPPORT,fixture.LIB_A)
            raw=bytearray(main.read_bytes())
            struct.pack_into('<I',raw,0x100+0x830,0xa68)
            struct.pack_into('<BBHHHHH',raw,0x100+0xa34,0x34,0,1,0,2,0,0)
            struct.pack_into('<II',raw,0x100+0xa44,0x03fcf19d,0)
            struct.pack_into('<II',raw,0x100+0xa50,0x10c20,0x10c28)
            struct.pack_into('<IIII',raw,0x100+0xc20,0x79a0160a,0x53099b7a,sym['sysload'],sym['sysquery'])
            main.write_bytes(raw)
            session=ModuleSession([main],d/'run',sysmodules={15:provider})
            report=session.run()
            self.assertEqual(report['status'],0,report)
            self.assertEqual(report['r'][0],42)
            self.assertEqual([m.name for m in session.process.modules],['main','support_a'])
            self.assertEqual([x['phase'] for x in report['module_phases']],['lazy_start','stop'])
            off=session.process.modules[0].new_base+0x1008-session.base
            self.assertEqual(struct.unpack('<I',bytes(session.memory[off:off+4]))[0],1)
            self.assertEqual(report['system_modules']['loaded'],{15:'support_a'})
            self.assertEqual([e['result'] for e in report['system_modules']['events']],[SYSMODULE_UNLOADED,0,0,0])

    def test_missing_invalid_and_pinned_provider_results(self):
        with tempfile.TemporaryDirectory() as tmp:
            d=Path(tmp)
            main,_=fixture.build_one(d/'inputs','main',fixture.MAIN.replace('mov r0,#5','mov r0,#15').replace('cmp r1,#5','cmp r1,#15').replace('cmp r0,#42','ldr r1,error_value\n cmp r0,r1').replace('state_ptr: .word state','error_value: .word 0x805a10ff\nstate_ptr: .word state'))
            raw=bytearray(main.read_bytes());struct.pack_into('<I',raw,0x100+0xa10,0x03fcf19d);struct.pack_into('<I',raw,0x100+0xc00,0x79a0160a);main.write_bytes(raw)
            session=ModuleSession([main],d/'run',native_apputil=False)
            # Validate the API errors, then exercise a guest failure handler.
            state=session.state
            for ident,nid,expected in [(0,'79a0160a',SYSMODULE_INVALID),(0x56,'53099b7a',SYSMODULE_INVALID),(15,'53099b7a',SYSMODULE_UNLOADED),(15,'31d87805',SYSMODULE_UNLOADED)]:
                state.r[0]=ident
                session._system_call({'function_nid':nid},C.pointer(state))
                self.assertEqual(state.r[0],expected)
            session.sysmodule_loaded[7]='actual-provider'
            state.r[0]=7;session._system_call({'function_nid':'31d87805'},C.pointer(state))
            self.assertEqual(state.r[0],SYSMODULE_FATAL);self.assertIn(7,session.sysmodule_loaded)
            report=session.run()
            self.assertEqual(report['status'],0,report)
            self.assertEqual(report['r'][0],42)
            self.assertEqual(report['system_modules']['events'][-1],{'id':15,'operation':'load','result':SYSMODULE_FATAL})
            self.assertNotIn(15,report['system_modules']['loaded'])

    def test_failed_initializer_is_never_reported_loaded(self):
        with tempfile.TemporaryDirectory() as tmp:
            d=Path(tmp)
            main,_=fixture.build_one(d/'inputs','main',fixture.MAIN.replace('mov r0,#5','mov r0,#15'))
            provider,_=fixture.build_one(d/'inputs','support_a',fixture.SUPPORT.replace('mov r0,#0','mov r0,#1'),fixture.LIB_A)
            raw=bytearray(main.read_bytes());struct.pack_into('<I',raw,0x100+0xa10,0x03fcf19d);struct.pack_into('<I',raw,0x100+0xc00,0x79a0160a);main.write_bytes(raw)
            session=ModuleSession([main],d/'run',sysmodules={15:provider})
            report=session.run()
            self.assertEqual(report['status'],-10,report)
            self.assertIn('module_start returned failure',report['error'])
            self.assertNotIn(15,report['system_modules']['loaded'])
            self.assertFalse(any(e['result']==0 for e in report['system_modules']['events']))
