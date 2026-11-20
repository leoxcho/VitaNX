import ctypes as C
import os,struct,tempfile,threading,unittest
from pathlib import Path
from types import SimpleNamespace
from vitanx.apputil import *

class Runtime:
    def vn_guest_write_allowed(self,p,n):return int(p>=self.start+0x100)
    def vx_guest_memory_written(self):pass

class AppUtilTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        memory=(C.c_uint8*16384)();runtime=Runtime();runtime.start=C.addressof(memory)
        self.session=SimpleNamespace(base=0x10000,memory=memory,runtime=runtime,output=self.root)
        (self.root/'saves').mkdir();self.app=AppUtil(self.session,{'boot_version':0x1000000,'language':18,'username':'Player'})
        self.r=(C.c_uint32*16)();self.r[13]=0x13f00
    def tearDown(self):self.app.close();self.temp.cleanup()
    def call(self,nid,*args):
        for i,x in enumerate(args):self.r[i]=x
        return self.app.invoke(nid,self.r)
    def initialize(self):self.assertEqual(self.call(0xdaffe671,0x10100,0x10200),0)
    def test_lifecycle_validation_configuration_and_cleanup(self):
        self.assertEqual(self.call(0x5dfb9ca0,1,0x10300),NOT_INIT)
        self.assertEqual(self.call(0xdaffe671,0x10000,0x10200),PARAM)
        self.assertFalse(self.app.initialized)
        self.assertEqual(self.call(0xdaffe671,0x10100,0x10120),PARAM)
        self.app.write(0x10100,b'X');self.assertEqual(self.call(0xdaffe671,0x10100,0x10200),PARAM)
        self.app.write(0x10100,b'\0');self.initialize()
        self.assertEqual(self.app.read(0x10200,8),struct.pack('<II',0,0x1000000))
        self.assertEqual(self.call(0xdaffe671,0x10100,0x10200),BUSY)
        self.assertEqual(self.call(0x5dfb9ca0,1,0x10300),0);self.assertEqual(self.app.word(0x10300),18)
        self.assertEqual(self.call(0x5dfb9ca0,3,0x10300),PARAM)
        self.assertEqual(self.call(0x6e6aa267,3,0x10300,3),PARAM)
        self.assertEqual(self.call(0x6e6aa267,3,0x10300,17),0);self.assertEqual(self.app.string(0x10300),'Player')
        self.assertEqual(self.call(0xb220b00b),0);self.assertIsNone(self.app.root)
        self.assertEqual(self.call(0xee0dbed9,0x10400),NOT_INIT)
    def test_events_thread_serialization_and_invalid_output_preserves_queue(self):
        self.initialize()
        threads=[threading.Thread(target=self.app.queue_event,args=(i,b'event')) for i in range(1,17)]
        for t in threads:t.start()
        for t in threads:t.join()
        self.assertEqual(self.call(0xee0dbed9,0x13fff),PARAM);self.assertEqual(len(self.app.events),16)
        got=[]
        for _ in threads:
            self.assertEqual(self.call(0xee0dbed9,0x10400),0);got.append(self.app.word(0x10400))
        self.assertEqual(set(got),set(range(1,17)))
        self.assertEqual(self.call(0xee0dbed9,0x10400),0);self.assertEqual(self.app.read(0x10400,1028),bytes(1028))
    def test_slots_safe_memory_and_shutdown_persistence(self):
        self.initialize();data=b'S'*844;self.app.write(0x10400,data)
        self.assertEqual(self.call(0x7e8fe96a,3,0x10400,0),0)
        self.assertEqual(self.call(0x7e8fe96a,3,0x10400,0),EXISTS)
        self.assertEqual(self.call(0x93f0d89f,3,0x10800,0),0);self.assertEqual(self.app.read(0x10800,844),data)
        self.app.write(0x10c00,b'abcd');self.assertEqual(self.call(0x9d8ac677,0x10c00,4,8,0),4)
        self.assertEqual(self.call(0x3424d772,0x10d00,4,8,0),4);self.assertEqual(self.app.read(0x10d00,4),b'abcd')
        self.assertEqual(self.call(0x3424d772,0x10d00,4,0xffffffff,0xffffffff),PARAM)
        self.assertEqual(self.call(0xb220b00b),0)
        self.app.write(0x10200,bytes(40));self.initialize()
        self.assertEqual(self.call(0x93f0d89f,3,0x10800,0),0)
        self.assertEqual(self.call(0x266a7646,3,0),0)
        self.assertEqual(self.call(0x93f0d89f,3,0x10800,0),NOT_FOUND)
    def test_save_files_offsets_truncate_quota_remove_and_path_escape(self):
        self.initialize();self.app.write(0x10400,b'savedata0:data.bin\0');self.app.write(0x10500,b'hello')
        record=struct.pack('<IIIIqI',0x10400,0x10500,5,0,3,0)+bytes(36)
        self.app.write(0x10600,record);self.app.write(self.r[13],struct.pack('<I',0x10700))
        self.assertEqual(self.call(0x607647ba,0,0x10600,1,0),0)
        self.assertEqual((self.root/'saves/data.bin').read_bytes(),bytes(3)+b'hello')
        self.app.write(0x10600,struct.pack('<IIIIqI',0x10400,0x10500,1,0,1,1)+bytes(36))
        self.assertEqual(self.call(0x607647ba,0,0x10600,1,0),0)
        self.assertEqual((self.root/'saves/data.bin').read_bytes(),b'\0h')
        self.app.write(0x10400,b'../escape\0');self.assertEqual(self.call(0x607647ba,0,0x10600,1,0),PERMISSION)
        outside=self.root/'outside';outside.mkdir();os.symlink(outside,self.root/'saves/link')
        self.app.write(0x10400,b'link/file\0');self.assertNotEqual(self.call(0x607647ba,0,0x10600,1,0),0);self.assertEqual(list(outside.iterdir()),[])
        self.app.write(0x10400,b'data.bin\0');self.app.write(0x10600,struct.pack('<II',0x10400,1)+bytes(36))
        self.assertEqual(self.call(0xd1c6ab8e,0,0x10600,1,0),0);self.assertFalse((self.root/'saves/data.bin').exists())
        self.app.config['quota_kib']=1
        self.app.write(0x10600,struct.pack('<IIIIqI',0x10400,0x10500,1,0,2048,0)+bytes(36))
        self.assertEqual(self.call(0x607647ba,0,0x10600,1,0),QUOTA);self.assertGreater(self.app.word(0x10700),0)
        self.assertFalse((self.root/'saves/data.bin').exists())
    def test_batch_prevalidation_and_metadata_quota(self):
        self.initialize();self.app.config['quota_kib']=1
        self.app.write(0x10400,b'P'*844)
        self.assertEqual(self.call(0x7e8fe96a,1,0x10400,0),0)
        self.assertEqual(self.call(0x7e8fe96a,2,0x10400,0),QUOTA)
        self.assertEqual(self.call(0x9d8ac677,0x10400,1,0,0),QUOTA)
        self.app.write(0x10800,b'valid.bin\0');self.app.write(0x10900,b'../escape\0')
        a=struct.pack('<IIIIqI',0x10800,0x10400,1,0,0,0)+bytes(36)
        b=struct.pack('<IIIIqI',0x10900,0x10400,1,0,0,0)+bytes(36)
        self.app.write(0x10a00,a+b);self.app.write(self.r[13],bytes(4))
        self.assertEqual(self.call(0x607647ba,0,0x10a00,2,0),PERMISSION)
        self.assertFalse((self.root/'saves/valid.bin').exists())
    def test_duplicate_batch_paths_rejected_without_writing(self):
        self.initialize();self.app.write(0x10800,b'data.bin\0');self.app.write(0x10400,b'Q')
        record=struct.pack('<IIIIqI',0x10800,0x10400,1,0,0,0)+bytes(36)
        self.app.write(0x10a00,record*2);self.app.write(self.r[13],bytes(4))
        self.assertEqual(self.call(0x607647ba,0,0x10a00,2,0),PARAM)
        self.assertFalse((self.root/'saves/data.bin').exists())
    def test_save_quota_uses_sfo_metadata_with_explicit_override(self):
        self.session.application_metadata={'SAVEDATA_MAX_SIZE':4096}
        self.assertEqual(AppUtil(self.session).config['quota_kib'],4096)
        self.assertEqual(AppUtil(self.session,{'quota_kib':8192}).config['quota_kib'],8192)
        self.session.application_metadata['SAVEDATA_MAX_SIZE']=-1
        self.assertEqual(AppUtil(self.session).config['quota_kib'],65536)
    def test_missing_slot_does_not_delete_files_before_error(self):
        self.initialize();(self.root/'saves/data.bin').write_bytes(b'keep')
        self.app.write(0x10800,b'data.bin\0');self.app.write(0x10900,struct.pack('<II',9,0)+bytes(32))
        self.app.write(0x10a00,struct.pack('<II',0x10800,0)+bytes(36))
        self.assertEqual(self.call(0xd1c6ab8e,0x10900,0x10a00,1,0),NOT_FOUND)
        self.assertEqual((self.root/'saves/data.bin').read_bytes(),b'keep')
