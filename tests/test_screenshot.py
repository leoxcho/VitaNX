import ctypes as C
import struct
from types import SimpleNamespace
import unittest
from vitanx.screenshot import ScreenShotPolicy, INVALID_ARGUMENT

class ScreenShotTests(unittest.TestCase):
    def setUp(self):
        self.memory = (C.c_uint8 * 2048)()
        self.policy = ScreenShotPolicy(SimpleNamespace(base=0x10000, memory=self.memory))
    def put(self, offset, data):
        C.memmove(C.addressof(self.memory)+offset, data, len(data))
    def params(self, photo=0x10080, game=0, comment=0, reserved=0):
        self.put(32, struct.pack('<IIII', photo, game, comment, reserved))
        return self.policy.invoke(0x05db59c7, [0x10020])
    def test_enable_disable_are_retained_without_fabricating_capture(self):
        self.assertIsNone(self.policy.report()['enabled'])
        for nid, enabled in ((0x76e674d1,True),(0x76e674d1,True),(0x50ae9ff9,False)):
            self.assertEqual(self.policy.invoke(nid, []),0)
            self.assertEqual(self.policy.report()['enabled'],enabled)
        self.assertFalse(self.policy.report()['capture_implemented'])
        self.assertEqual(self.policy.report()['captures_written'],0)
        with self.assertRaises(ValueError):self.policy.invoke(0xd509fb08,[])
    def test_metadata_bounds_reserved_and_unicode_validation_are_transactional(self):
        self.put(128,'Kat 🐈\0'.encode('utf-32-le'))
        self.assertEqual(self.params(),0)
        before=self.policy.report()['parameters']
        self.assertEqual(before['photo_title'],'Kat 🐈')
        self.assertEqual(self.params(reserved=1),INVALID_ARGUMENT)
        self.assertEqual(self.params(photo=0x10800),INVALID_ARGUMENT)
        self.assertEqual(self.params(photo=0x10081),INVALID_ARGUMENT)
        for scalar in (0xd800,0x110000):
            self.put(128,struct.pack('<II',scalar,0))
            self.assertEqual(self.params(),INVALID_ARGUMENT)
        self.put(128,struct.pack('<64I',*[65]*64))
        self.assertEqual(self.params(),INVALID_ARGUMENT)
        self.assertEqual(self.policy.report()['parameters'],before)
        self.assertEqual(self.policy.invoke(0x05db59c7,[0]),INVALID_ARGUMENT)
        self.assertEqual(self.policy.invoke(0x05db59c7,[0x107fc]),INVALID_ARGUMENT)
    def test_boundary_terminator_null_fields_and_report_isolation(self):
        self.put(2044,bytes(4))
        self.assertEqual(self.params(photo=0x107fc),0)
        self.assertEqual(self.policy.report()['parameters'],{'photo_title':'','game_title':None,'game_comment':None})
        self.assertEqual(self.params(photo=0),0)
        report=self.policy.report();report['parameters']['photo_title']='changed';report['trace'][0]['result']=42
        self.assertIsNone(self.policy.report()['parameters']['photo_title'])
        self.assertEqual(self.policy.report()['trace'][0]['result'],0)
        for _ in range(70):self.policy.invoke(0x76e674d1,[])
        self.assertEqual(len(self.policy.report()['trace']),64)
