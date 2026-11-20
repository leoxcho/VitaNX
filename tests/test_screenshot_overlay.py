import ctypes as C
import struct
import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest
import zlib
from vitanx.screenshot import ScreenShotPolicy,INVALID_ARGUMENT,NOT_SUPPORTED_FORMAT,FILE_NOT_FOUND
from vitanx.screenshot_png import decode_rgba8

def png(width,height,filtered,depth=8):
    def chunk(kind,data):return struct.pack('>I',len(data))+kind+data+struct.pack('>I',zlib.crc32(kind+data)&0xffffffff)
    return b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',width,height,depth,6,0,0,0))+chunk(b'IDAT',zlib.compress(filtered))+chunk(b'IEND',b'')

class OverlayTests(unittest.TestCase):
    def test_all_png_filters_decode_original_pixels(self):
        pixel=bytes([5,10,15,20])
        for mode in range(5):
            # First row has no upper neighbours. Second pixel equals the first.
            residual=pixel if mode in (0,2) else bytes(4) if mode in (1,4) else bytes((x-x//2) for x in pixel)
            raw=png(2,1,bytes([mode])+pixel+residual)
            self.assertEqual(decode_rgba8(raw),(2,1,pixel*2))
        for broken in (raw[:-1],raw+b'extra',png(961,1,b''),png(1,1,b'\0'+bytes(4),16),png(1,1,b'\x05'+bytes(4)),png(1,1,b'\0'+bytes(5))):
            with self.assertRaises(ValueError):decode_rgba8(broken)
    def test_overlay_reads_only_original_app0_and_commits_after_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'sysdata').mkdir();image=root/'sysdata/overlay.png'
            pixel=bytes([5,10,15,20]);image.write_bytes(png(1,1,b'\0'+pixel))
            memory=(C.c_uint8*2048)();session=SimpleNamespace(base=0x10000,memory=memory,assets=root);policy=ScreenShotPolicy(session)
            def call(path,x=10,y=20):
                raw=path.encode()+b'\0';C.memmove(C.addressof(memory)+32,raw,len(raw))
                return policy.invoke(0x7061665b,[0x10020,x,y])
            self.assertEqual(call('app0:/sysdata/overlay.png'),0)
            before=policy.report()['overlay'];self.assertEqual(policy.overlay_pixels,pixel)
            for path in ('app0:/../escape','ux0:/sysdata/overlay.png','app0:/sysdata//overlay.png'):
                self.assertEqual(call(path),INVALID_ARGUMENT)
            self.assertEqual(call('app0:/missing.png'),FILE_NOT_FOUND)
            self.assertEqual(call('app0:/sysdata/overlay.png',0xffffffff,960),0)
            self.assertEqual(policy.report()['overlay']['offset_x'],-1)
            self.assertEqual(call('app0:/sysdata/overlay.png'),0)
            image.write_bytes(b'not a png');self.assertEqual(call('app0:/sysdata/overlay.png'),NOT_SUPPORTED_FORMAT)
            self.assertEqual(policy.report()['overlay'],before)
            policy.report()['overlay']['path']='changed';self.assertEqual(policy.report()['overlay'],before)
            (root/'link.png').symlink_to(image);self.assertEqual(call('app0:/link.png'),INVALID_ARGUMENT)
