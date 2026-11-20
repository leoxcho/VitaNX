import struct
import tempfile
import unittest
from pathlib import Path
from test_module_execution import fixture
from vitanx.modules import ModuleSession


class PowerExecutionTests(unittest.TestCase):
    def test_translated_arm_retains_profile_and_preserves_guest_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            code = fixture.MAIN.replace(' bl import_a', ''' mov r0,#0x800
 bl import_a
 cmp r0,#0
 bne failure
 mov r0,#42''')
            main, _ = fixture.build_one(directory/'input', 'main', code)
            raw = bytearray(main.read_bytes())
            struct.pack_into('<I', raw, 0x100+0xa10, 0x1082da7f)
            struct.pack_into('<I', raw, 0x100+0xc00, 0x3ce187b6)
            main.write_bytes(raw)
            session = ModuleSession([main], directory/'run')
            stack = session.state.r[13]
            report = session.run()
            self.assertEqual(report['status'], 0, report)
            self.assertEqual(report['r'][0], 42)
            self.assertEqual(report['r'][13], stack)
            self.assertEqual(report['f'][0], 5)
            self.assertEqual(report['power']['requested_configuration_mode'], 0x800)
            self.assertEqual(report['power']['trace'][0]['result'], 0)

    def test_same_nid_from_wrong_library_is_not_intercepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            main, _ = fixture.build_one(directory/'input', 'main', fixture.MAIN)
            raw = bytearray(main.read_bytes())
            struct.pack_into('<I', raw, 0x100+0xa10, 0x1082da7e)
            struct.pack_into('<I', raw, 0x100+0xc00, 0x3ce187b6)
            main.write_bytes(raw)
            session = ModuleSession([main], directory/'run', allow_unresolved=True)
            report = session.run()
            self.assertEqual(report['status'], -9, report)
            self.assertEqual(report['power']['trace'], [])
            self.assertIsNone(report['power']['requested_configuration_mode'])
