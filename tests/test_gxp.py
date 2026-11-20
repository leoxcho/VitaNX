"""Synthetic format tests only; these bytes are not valid executable shaders."""
import json
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
from vitaxnative.gxp import inspect_gxp


def fixture():
    data=bytearray(224)
    data[:4]=b'GXP\0'
    struct.pack_into('<BBHI',data,4,1,4,0x350,len(data))
    struct.pack_into('<I',data,20,1)
    struct.pack_into('<II',data,36,1,176-40)
    struct.pack_into('<II',data,60,2,160-64)
    struct.pack_into('<QQ',data,160,0x123456789abcdef0,0xfedcba9876543210)
    struct.pack_into('<iBBBBII',data,176,192-176,0x12,0x24,0,0,1,3)
    data[192:200]=b'uColor\0\0'
    return data


class GxpTests(unittest.TestCase):
    def inspect(self,raw):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'shader.gxp';path.write_bytes(raw)
            result=inspect_gxp(path)
            self.assertEqual(path.read_bytes(),raw)
            return result

    def test_relative_fields_metadata_and_explicit_translation_gate(self):
        result=self.inspect(fixture()+b'padding')
        self.assertEqual(result['stage'],'fragment')
        self.assertEqual(result['trailing_bytes'],7)
        self.assertEqual(result['parameters'][0]['name'],'uColor')
        self.assertEqual(result['parameters'][0]['category'],2)
        self.assertEqual(result['programs'][0]['preview_words'][0],'123456789abcdef0')
        self.assertFalse(result['translation_supported'])
        self.assertIn('USSE',result['unsupported_reason'])
        data=fixture();data[156:160]=b'uC\0\0'
        struct.pack_into('<i',data,176,156-176)
        self.assertEqual(self.inspect(data)['parameters'][0]['name'],'uC')

    def test_reject_bad_headers_and_out_of_bounds_tables(self):
        bad=[b'',b'GXP\0',bytes(156)]
        for at,value in ((8,100),(8,10000),(36,0xffffffff),(40,0),
                         (40,0xfffffff0),(64,0),(64,99),(60,0xffffffff),
                         (44,0xfffffff0),(176,0xfffffff0),(4,0)):
            data=fixture();struct.pack_into('<I',data,at,value);bad.append(data)
        data=fixture();data[192:]=b'x'*32;bad.append(data)
        data=fixture();struct.pack_into('<I',data,40,160-40);bad.append(data)
        for index,data in enumerate(bad):
            with self.subTest(index=index),self.assertRaises(ValueError):self.inspect(data)

    def test_cli_reports_json_without_accepting_shader(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'shader.gxp';path.write_bytes(fixture())
            process=subprocess.run([sys.executable,'-m','vitaxnative','inspect-gxp',str(path)],
                                   capture_output=True,text=True,timeout=10)
            self.assertEqual(process.returncode,0,process.stderr)
            self.assertFalse(json.loads(process.stdout)['translation_supported'])

    def test_real_layout_four_byte_code_alignment_and_unused_varying_tail(self):
        data=bytearray(196);data[:4]=b'GXP\0'
        struct.pack_into('<BBHI',data,4,1,5,0x200,len(data))
        struct.pack_into('<I',data,20,1);struct.pack_into('<I',data,44,156-44)
        struct.pack_into('<II',data,60,2,180-64)
        self.assertEqual(self.inspect(data)['programs'][0]['offset'],180)
