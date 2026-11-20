"""Deterministic malformed SELF coverage; no commercial input required."""
import random
import struct
import tempfile
from pathlib import Path
import unittest
from vitaxnative.self_extract import inspect_self_layout, extract_self
from test_self_extract import fixture

class SelfAdversarialTests(unittest.TestCase):
    def test_header_and_segment_bounds_mutations(self):
        randomizer = random.Random(0x56495441)
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp)/'in.self'
            for case in range(256):
                data = fixture(bool(case & 1))
                offset = randomizer.choice([16,24,64,72,88,256,264])
                value = randomizer.choice([0,1,127,4095,len(data)+1,0xffffffffffffffff])
                struct.pack_into('<Q',data,offset,value)
                source.write_bytes(data)
                try:
                    result = inspect_self_layout(source)
                except ValueError:
                    continue
                self.assertLessEqual(result['elf_size'],128*1024*1024)
                for seg in result['segments']:
                    self.assertLessEqual(seg['source']+seg['stored_size'],len(data))
                    self.assertLessEqual(seg['offset']+seg['size'],result['elf_size'])

    def test_compressed_size_truncation_and_trailing_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, output = Path(tmp)/'in.self', Path(tmp)/'out.elf'
            for change in ('too-small','too-large','truncated','trailing'):
                with self.subTest(change=change):
                    data = fixture(True)
                    stored = struct.unpack_from('<Q',data,264)[0]
                    if change == 'too-small': struct.pack_into('<I',data,240,4)
                    if change == 'too-large':
                        struct.pack_into('<II',data,240,9,9)
                        struct.pack_into('<Q',data,24,265)
                    if change == 'truncated': struct.pack_into('<Q',data,264,stored-1)
                    if change == 'trailing':
                        data += b'x'
                        struct.pack_into('<Q',data,264,stored+1)
                    source.write_bytes(data)
                    with self.assertRaises(ValueError): extract_self(source,output)
                    self.assertFalse(output.exists())
