import ctypes as C
import struct,unittest
from types import SimpleNamespace
from vitanx.common_dialog import CommonDialog
class CommonDialogTests(unittest.TestCase):
    def test_configuration_inheritance_and_errors_preserve_previous_state(self):
        mem=(C.c_uint8*256)();s=SimpleNamespace(base=0x10000,memory=mem,apputil=SimpleNamespace(config={'language':18,'enter_button':1}))
        dialog=CommonDialog(s);r=(C.c_uint32*16)();r[0]=0x10040
        def config(language,button,reserved=bytes(32)):
            raw=struct.pack('<III',0x1670011,language,button)+reserved;C.memmove(C.addressof(mem)+64,raw,44)
            return dialog.invoke(0xbecd35c8,r)
        self.assertEqual(config(0xffffffff,0xffffffff),0)
        self.assertEqual(dialog.config,{'sdk_version':0x1670011,'language':18,'enter_button':1})
        before=dict(dialog.config)
        self.assertEqual(config(20,0),0x80020431);self.assertEqual(dialog.config,before)
        self.assertEqual(config(1,2),0x80020432);self.assertEqual(dialog.config,before)
        self.assertEqual(config(1,1,b'X'+bytes(31)),0x80020403)
        r[0]=0;self.assertEqual(dialog.invoke(0xbecd35c8,r),0x80020402)
        r[0]=0x100ff;self.assertEqual(dialog.invoke(0xbecd35c8,r),0x80020403)
        self.assertEqual(dialog.invoke(0x043a353e,r),0);self.assertFalse(dialog.report()['running'])
