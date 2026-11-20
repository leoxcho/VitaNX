import struct
import tempfile
from pathlib import Path
import unittest
import zlib
from vitaxnative.psarc import Psarc


def archive(name='/System/Shaders.Zip',payload=b'abc'*100):
    values=[name.encode()+b'\n',payload];compressed=[zlib.compress(x) for x in values]
    compressed=[data if len(data)<len(raw) else raw for raw,data in zip(values,compressed)]
    toc=32+60+4;offset=toc;entries=[]
    for i,(raw,data) in enumerate(zip(values,compressed)):
        entries.append(bytes(16)+struct.pack('>I',i)+len(raw).to_bytes(5,'big')+offset.to_bytes(5,'big'))
        offset+=len(data)
    return (struct.pack('>4sI4sIIIII',b'PSAR',0x10004,b'zlib',toc,30,2,65536,3)+
            b''.join(entries)+b''.join(len(x).to_bytes(2,'big') for x in compressed)+b''.join(compressed))


class PsarcTests(unittest.TestCase):
    def load(self,data):
        directory=tempfile.TemporaryDirectory();self.addCleanup(directory.cleanup)
        path=Path(directory.name)/'assets.psarc';path.write_bytes(data)
        return Psarc(path)

    def test_compressed_and_raw_resource_read_preserves_archive(self):
        for payload in (b'abc'*100,b'X'):
            data=archive(payload=payload);reader=self.load(data)
            self.assertEqual(reader.read('System/Shaders.Zip'),payload)
            self.assertEqual(reader.path.read_bytes(),data)
            self.assertEqual(reader.inventory()['members'][0]['size'],len(payload))

    def test_invalid_tables_truncation_compression_and_member_names(self):
        bad=[b'',archive()[:31],archive()[:-1],archive(name='/../Shaders.Zip'),
             archive(name='/System//Shaders.Zip'),archive(name='/System\\Shaders.Zip')]
        for offset,value in ((4,0),(12,32),(16,31),(20,0),(24,0),(28,4)):
            data=bytearray(archive());struct.pack_into('>I',data,offset,value);bad.append(data)
        data=bytearray(archive());data[-1]^=255;bad.append(data)
        for index,data in enumerate(bad):
            with self.subTest(index=index),self.assertRaises(ValueError):
                reader=self.load(data);reader.read('System/Shaders.Zip')

    def test_missing_member_is_explicit(self):
        reader=self.load(archive())
        with self.assertRaisesRegex(ValueError,'not found'):reader.read('missing')
