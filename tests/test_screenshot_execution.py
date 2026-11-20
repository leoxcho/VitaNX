import struct
import tempfile
import unittest
from pathlib import Path
from test_module_execution import fixture
from vitanx.modules import ModuleSession

class ScreenShotExecutionTests(unittest.TestCase):
    def test_original_arm_permission_call_preserves_guest_registers(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory=Path(tmp)
            code=fixture.MAIN.replace(' bl import_a',''' bl import_a
 cmp r0,#0
 bne failure
 mov r0,#42''')
            main,_=fixture.build_one(directory/'input','main',code)
            raw=bytearray(main.read_bytes())
            struct.pack_into('<I',raw,0x100+0xa10,0xf26fc97d)
            struct.pack_into('<I',raw,0x100+0xc00,0x76e674d1)
            main.write_bytes(raw)
            session=ModuleSession([main],directory/'run');stack=session.state.r[13]
            report=session.run()
            self.assertEqual(report['status'],0,report)
            self.assertEqual(report['r'][0],42)
            self.assertEqual(report['r'][13],stack)
            self.assertEqual(report['f'][0],5)
            self.assertTrue(report['screenshot']['enabled'])
            self.assertEqual(report['screenshot']['captures_written'],0)
    def test_wrong_library_keeps_same_function_unresolved(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory=Path(tmp)
            main,_=fixture.build_one(directory/'input','main',fixture.MAIN)
            raw=bytearray(main.read_bytes())
            struct.pack_into('<I',raw,0x100+0xa10,0xf26fc97e)
            struct.pack_into('<I',raw,0x100+0xc00,0x76e674d1)
            main.write_bytes(raw)
            session=ModuleSession([main],directory/'run',allow_unresolved=True)
            report=session.run()
            self.assertEqual(report['status'],-9,report)
            self.assertEqual(report['screenshot']['trace'],[])
