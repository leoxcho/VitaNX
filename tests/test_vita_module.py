"""SCE module structure bounds tests; genuine artifact coverage is separate."""
from pathlib import Path
import struct
import tempfile
import unittest
from vitaxnative.vita_module import inspect_vita_module


def fixture(short=False, reloc=False):
    image = bytearray(0x500 + (12 if reloc else 0))
    image[:16] = b'\x7fELF\x01\x01\x01' + bytes(9)
    struct.pack_into('<HHIIIIIHHHHHH', image, 16, 0xfe04, 40, 1, 0x80,
                     52, 0, 0x5000000, 52, 32, 2 if reloc else 1, 0, 0, 0)
    struct.pack_into('<IIIIIIII', image, 52, 1, 0x100, 0x10000, 0x10000, 0x400, 0x400, 5, 0x100)
    struct.pack_into('<I',image,0x100,0xe12fff1e)
    struct.pack_into('<III',image,0x110,0xe3e00000,0xe12fff1e,0xe1a00000)
    module=0x180
    struct.pack_into('<HH',image,module,0,0x101)
    image[module+4:module+4+8]=b'TestApp\0'
    image[module+31]=6
    size=0x24 if short else 0x34
    struct.pack_into('<IIII',image,module+0x24,0,0,0x100,0x100+size)
    struct.pack_into('<IIIIII',image,module+0x34,0x1234,0,0,0,0,0xffffffff)
    imp=0x200
    struct.pack_into('<BBHHHHH',image,imp,size,0,1,0,1,0,0)
    if short:
        struct.pack_into('<IIII',image,imp+0xc,0x5678,0x10180,0x101a0,0x101a4)
    else:
        struct.pack_into('<II',image,imp+0x10,0x5678,0x10180)
        struct.pack_into('<II',image,imp+0x1c,0x101a0,0x101a4)
    image[0x280:0x280+12]=b'SceIofilemgr\0'
    struct.pack_into('<II',image,0x2a0,0x34efd876,0x10010)
    if reloc:
        struct.pack_into('<IIIIIIII',image,84,0x60000000,0x500,0,0,12,12,0,4)
        struct.pack_into('<III',image,0x500,2<<8,0x10,0x20)
    return image


class VitaModuleTests(unittest.TestCase):
    def inspect(self, data):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'module.velf';path.write_bytes(data)
            return inspect_vita_module(path)

    def test_module_entry_and_both_import_layouts(self):
        for short in (False,True):
            with self.subTest(short=short):
                result=self.inspect(fixture(short))
                self.assertEqual(result['entry'],0x10000)
                self.assertEqual(result['module_info_address'],0x10080)
                self.assertEqual(result['module_name'],'TestApp')
                self.assertEqual(result['imports'],{0x10010:0x34efd876})
                self.assertEqual(result['libraries'][0]['name'],'SceIofilemgr')

    def test_relocations_inventoried_never_claimed_applied(self):
        result=self.inspect(fixture(reloc=True))
        self.assertEqual(result['relocations'][0]['types'],{2:1})
        self.assertFalse(result['relocations_applied'])
        self.assertFalse(result['relocations'][0]['applied'])

    def test_malformed_metadata_rejected(self):
        for change in ('module-segment','module-offset','no-entry','entry-not-code','tls',
                       'imports-reversed','short-import','unknown-import','variables',
                       'nid-unmapped','stub-unmapped','stub-unaligned','library-unmapped',
                       'truncated-relocation','paired-relocation'):
            with self.subTest(change=change):
                image=fixture(reloc='relocation' in change)
                if change=='module-segment':struct.pack_into('<I',image,24,0xc0000080)
                if change=='module-offset':struct.pack_into('<I',image,24,0x10000)
                if change=='no-entry':struct.pack_into('<I',image,0x180+0x44,0xffffffff)
                if change=='entry-not-code':struct.pack_into('<I',image,76,4)
                if change=='tls':struct.pack_into('<I',image,0x180+0x40,4)
                if change=='imports-reversed':struct.pack_into('<II',image,0x180+0x2c,0x134,0x100)
                if change=='short-import':struct.pack_into('<I',image,0x180+0x30,0x101)
                if change=='unknown-import':image[0x200]=0x30
                if change=='variables':struct.pack_into('<H',image,0x208,1)
                if change=='nid-unmapped':struct.pack_into('<I',image,0x21c,0xffffffff)
                if change=='stub-unmapped':struct.pack_into('<I',image,0x2a4,0xffffffff-3)
                if change=='stub-unaligned':struct.pack_into('<I',image,0x2a4,0x10011)
                if change=='library-unmapped':struct.pack_into('<I',image,0x214,0xffffffff)
                if change=='truncated-relocation':struct.pack_into('<I',image,100,8)
                if change=='paired-relocation':struct.pack_into('<I',image,0x500,0x100000)
                with self.assertRaises(ValueError):self.inspect(image)


def linked_fixture():
    image=fixture()+bytes(0x200)
    struct.pack_into('<H',image,16,2)
    struct.pack_into('<I',image,24,0x10000)
    struct.pack_into('<I',image,32,0x500)
    struct.pack_into('<HHH',image,46,40,3,1)
    names=b'\0.shstrtab\0.vitalink.fstubs.SceIofilemgr\0'
    struct.pack_into('<IIIIIIIIII',image,0x528,1,3,0,0,0x600,len(names),0,0,1,0)
    struct.pack_into('<IIIIIIIIII',image,0x550,11,1,6,0x10010,0x110,16,0,0,4,0)
    image[0x600:0x600+len(names)]=names
    struct.pack_into('<IIII',image,0x110,0,0x1234,0x34efd876,0)
    return image


class VitaLinkedElfTests(unittest.TestCase):
    def inspect(self,data):
        from vitaxnative.vita_module import inspect_vitasdk_elf
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'linked.elf';path.write_bytes(data)
            return inspect_vitasdk_elf(path)

    def test_official_stub_record_discovery(self):
        result=self.inspect(linked_fixture())
        self.assertEqual(result['entry'],0x10000)
        self.assertEqual(result['imports'],{0x10010:0x34efd876})
        self.assertEqual(result['libraries'][0]['name'],'SceIofilemgr')
        self.assertFalse(result['relocations_applied'])

    def test_invalid_stub_section_rejected(self):
        for change in ('no-sections','bad-string-table','bad-name','bad-stub-size','unmapped','not-code'):
            with self.subTest(change=change):
                image=linked_fixture()
                if change=='no-sections':struct.pack_into('<H',image,48,0)
                if change=='bad-string-table':struct.pack_into('<I',image,0x528+16,0xffffffff)
                if change=='bad-name':struct.pack_into('<I',image,0x550,0xffffffff)
                if change=='bad-stub-size':struct.pack_into('<I',image,0x550+20,15)
                if change=='unmapped':struct.pack_into('<I',image,0x550+12,0x10014)
                if change=='not-code':struct.pack_into('<I',image,76,4)
                with self.assertRaises(ValueError):self.inspect(image)


class VitaIdentityRelocationTests(unittest.TestCase):
    def validate(self,image):
        from vitaxnative.vita_module import validate_identity_relocations
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'module.velf';path.write_bytes(image)
            return validate_identity_relocations(path)

    def test_identity_abs32_and_rebasing_refusal(self):
        image=fixture(reloc=True)
        struct.pack_into('<I',image,0x120,0x10010)
        result=self.validate(image)
        self.assertTrue(result['identity_load_validated'])
        self.assertEqual(result['relocation_count'],1)
        self.assertFalse(result['image_modified'])
        struct.pack_into('<I',image,0x120,0x10014)
        with self.assertRaisesRegex(ValueError,'rebasing'):
            self.validate(image)

    def test_unsupported_and_malformed_records_refused(self):
        for change in ('unknown-type','missing-segment','site-outside','compressed','paired','size'):
            with self.subTest(change=change):
                image=fixture(reloc=True)
                struct.pack_into('<I',image,0x120,0x10010)
                if change=='unknown-type':struct.pack_into('<I',image,0x500,255<<8)
                if change=='missing-segment':struct.pack_into('<I',image,0x500,(2<<8)|(15<<16))
                if change=='site-outside':struct.pack_into('<I',image,0x508,0x400)
                if change=='compressed':struct.pack_into('<I',image,0x500,(2<<8)|1)
                if change=='paired':struct.pack_into('<I',image,0x500,(2<<8)|(1<<20))
                if change=='size':struct.pack_into('<I',image,100,11)
                with self.assertRaises(ValueError):self.validate(image)

    def test_genuine_sdk_linked_elf_and_velf_agree(self):
        import os
        import shutil
        import subprocess
        from vitaxnative.vita_module import inspect_vitasdk_elf,validate_identity_relocations
        root=Path(__file__).resolve().parents[1]
        sdk=Path(os.environ.get('VITASDK',root.parent/'vitasdk'))
        gcc=sdk/'bin/arm-vita-eabi-gcc'
        create=sdk/'bin/vita-elf-create'
        if not gcc.is_file() or not create.is_file():
            self.skipTest('official VitaSDK GCC and vita-elf-create required')
        with tempfile.TemporaryDirectory() as tmp:
            tmp=Path(tmp)
            source=tmp/'main.c';elf=tmp/'module.elf';velf=tmp/'module.velf'
            source.write_text('#include <psp2/kernel/processmgr.h>\nint module_start(unsigned n,const void*p){(void)n;(void)p;return sceKernelGetStdout();}\n')
            subprocess.run([str(gcc),'-marm','-O1','-nostdlib','-fno-unwind-tables',
                            '-fno-asynchronous-unwind-tables','-Wl,-q','-Wl,-e,module_start',
                            '-Wl,-Ttext=0x81000000',str(source),'-lSceProcessmgr_stub','-o',str(elf)],
                           check=True,capture_output=True,timeout=30)
            subprocess.run([str(create),str(elf),str(velf)],check=True,capture_output=True,timeout=30)
            linked=inspect_vitasdk_elf(elf)
            module=inspect_vitasdk_elf(velf)
            self.assertEqual(linked['imports'],module['imports'])
            self.assertIn(0xe5aa625c,module['imports'].values())
            self.assertEqual(linked['entry'],module['entry'])
            relocation=validate_identity_relocations(velf)
            self.assertTrue(relocation['identity_load_validated'])
            self.assertGreater(relocation['relocation_count'],0)
            # An altered function call must not pass as an already linked image.
            image=bytearray(velf.read_bytes())
            original=struct.unpack_from('<I',image,0x1000+4)[0]
            struct.pack_into('<I',image,0x1000+4,original^1)
            velf.write_bytes(image)
            with self.assertRaises(ValueError):validate_identity_relocations(velf)

    def test_supported_identity_encodings_and_tamper_rejection(self):
        for code in (2,3,38,41,42,43,44,47,48,28,29,10):
            for target in (0x10120,0x10000):
                with self.subTest(code=code,target=target):
                    image=fixture(reloc=True)
                    relative=(target-0x10020)&0xffffffff
                    if code in (2,38):word=target
                    elif code in (3,41):word=relative
                    elif code==42:word=0x80000000|(relative&0x7fffffff)
                    elif code in (43,44):
                        imm=(target if code==43 else target>>16)&0xffff
                        word=(0xe3000000 if code==43 else 0xe3400000)|((imm&0xf000)<<4)|(imm&0xfff)
                    elif code in (47,48):
                        imm=(target if code==47 else target>>16)&0xffff
                        first=(0xf240 if code==47 else 0xf2c0)|((imm>>12)&15)|(((imm>>11)&1)<<10)
                        second=(((imm>>8)&7)<<12)|(imm&255)
                        word=first|(second<<16)
                    elif code in (28,29):word=(0xeb000000 if code==28 else 0xea000000)|((relative>>2)&0xffffff)
                    else:
                        sign=(relative>>24)&1;i1=(relative>>23)&1;i2=(relative>>22)&1
                        first=0xf000|(sign<<10)|((relative>>12)&1023)
                        second=0xd000|((1^i1^sign)<<13)|((1^i2^sign)<<11)|((relative>>1)&2047)
                        word=first|(second<<16)
                    struct.pack_into('<III',image,0x500,code<<8,target-0x10000,0x20)
                    struct.pack_into('<I',image,0x120,word)
                    self.assertEqual(self.validate(image)['types'],{code:1})
                    struct.pack_into('<I',image,0x120,word^1)
                    with self.assertRaises(ValueError):self.validate(image)

class ImportReconciliationTests(unittest.TestCase):
    def test_empty_partial_matching_and_order(self):
        from vitaxnative.vita_module import reconcile_imports
        metadata={0x10020:2,0x10010:1}
        for explicit in (None,{}, {0x10010:1},metadata,[(0x10010,1),(0x10010,1)]):
            result=reconcile_imports(metadata,explicit)
            self.assertEqual(result,metadata)
            self.assertEqual(list(result),[0x10010,0x10020])
        self.assertEqual(metadata,{0x10020:2,0x10010:1})

    def test_conflicts_and_unknown_addresses_fail(self):
        from vitaxnative.vita_module import reconcile_imports
        for explicit, message in (({0x10010:2},'metadata NID'),
                                  ({0x10020:1},'absent'),
                                  ([(0x10010,1),(0x10010,2)],'duplicate'),
                                  ({True:1},'invalid')):
            with self.assertRaisesRegex(ValueError,message):
                reconcile_imports({0x10010:1},explicit)

    def test_json_duplicates_and_address_aliases(self):
        import json
        from vitaxnative.__main__ import _manifest_object,_manifest_imports
        self.assertEqual(json.loads('{"x":1,"x":1}',object_pairs_hook=_manifest_object),{'x':1})
        with self.assertRaisesRegex(ValueError,'duplicate'):
            json.loads('{"x":1,"x":2}',object_pairs_hook=_manifest_object)
        self.assertEqual(_manifest_imports({'16':1,'0x10':1}),{16:1})
        with self.assertRaisesRegex(ValueError,'duplicate'):
            _manifest_imports({'16':1,'0x10':2})

    def test_translation_uses_metadata_for_empty_and_partial_assertions(self):
        from vitaxnative.recompiler import translate_elf
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'module.velf';path.write_bytes(fixture())
            for imports in ({},{0x10010:0x34efd876}):
                result=translate_elf(path,imports=imports)
                self.assertEqual(result['module']['module_nid'],0x1234)
                self.assertEqual(result['module']['libraries'][0]['nid'],0x5678)
                self.assertEqual(result['module']['imports'],{0x10010:0x34efd876})

class AutomaticLinkedElfTests(unittest.TestCase):
    def test_translation_discovers_official_linked_imports_and_rejects_conflicts(self):
        from vitaxnative.recompiler import translate_elf
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'linked.elf';path.write_bytes(linked_fixture())
            result=translate_elf(path)
            self.assertEqual(result['module']['imports'],{0x10010:0x34efd876})
            with self.assertRaisesRegex(ValueError,'metadata NID'):
                translate_elf(path,imports={0x10010:1})

    def test_thumb_blx_identity_relocation_alignment_and_mismatch(self):
        from vitaxnative.vita_module import validate_identity_relocations
        with tempfile.TemporaryDirectory() as d:
            image=fixture(reloc=True)
            # THM_CALL targeting +0x3c from a site +0x20 (encoded +0x1c).
            struct.pack_into('<HH',image,0x120,0xf000,0xe80e)
            struct.pack_into('<III',image,0x500,10<<8,0x3c,0x20)
            path=Path(d)/'blx.velf';path.write_bytes(image)
            self.assertEqual(validate_identity_relocations(path)['relocation_count'],1)
            struct.pack_into('<I',image,0x504,0x3e);path.write_bytes(image)
            with self.assertRaisesRegex(ValueError,'out of range'):
                validate_identity_relocations(path)

class VitaExportTests(unittest.TestCase):
    def image(self):
        image=fixture()
        struct.pack_into('<II',image,0x180+0x24,0x200,0x220)
        struct.pack_into('<BBHHHIIIIII',image,0x300,0x20,0,1,1,1,1,0,0x7654,0,0x10240,0x10248)
        struct.pack_into('<IIII',image,0x340,0x1111,0x2222,0x10004,0x10300)
        struct.pack_into('<I',image,0x104,0xe12fff1e)
        return image

    def test_exports_inventory_and_translation_of_nonentry_function(self):
        from vitaxnative.recompiler import translate_elf
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'exports.velf';path.write_bytes(self.image())
            module=inspect_vita_module(path)
            self.assertEqual(module['exports'][0]['functions'],{0x1111:0x10004})
            self.assertEqual(module['exports'][0]['variables'],{0x2222:0x10300})
            result=translate_elf(path)
            self.assertEqual(result['instruction_count'],2)
            self.assertIn('L_10004:',result['c_source'])

    def test_invalid_exports_rejected_before_conversion(self):
        for mode in ('size','truncated','tls','count','duplicate','address','alignment','variable','name','unsupported-code'):
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as d:
                image=self.image()
                if mode=='size':image[0x300]=0x24
                elif mode=='truncated':struct.pack_into('<I',image,0x180+0x28,0x21f)
                elif mode=='tls':struct.pack_into('<I',image,0x30c,1)
                elif mode=='count':struct.pack_into('<I',image,0x308,65536)
                elif mode=='duplicate':struct.pack_into('<I',image,0x344,0x1111)
                elif mode=='address':struct.pack_into('<I',image,0x348,0xffffffff)
                elif mode=='alignment':struct.pack_into('<I',image,0x348,0x10002)
                elif mode=='variable':struct.pack_into('<I',image,0x34c,0xfffffffc)
                elif mode=='name':struct.pack_into('<I',image,0x314,0xffffffff)
                else:struct.pack_into('<I',image,0x104,0xffffffff)
                path=Path(d)/'bad.velf';path.write_bytes(image)
                from vitaxnative.recompiler import translate_elf
                with self.assertRaises(ValueError):translate_elf(path)


class InterworkingIdentityTests(unittest.TestCase):
    def test_arm_blx_h_bit_and_thumb_bl_tag_validation(self):
        from vitaxnative.vita_module import validate_identity_relocations
        cases=[(28,0xfa000002,0x28),(28,0xfb000002,0x2a),
               (10,0xf804f000,0x29),(10,0xe804f000,0x28)]
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'interwork.velf'
            for code,word,addend in cases:
                with self.subTest(code=code,word=hex(word)):
                    image=fixture(reloc=True)
                    struct.pack_into('<I',image,0x120,word)
                    struct.pack_into('<III',image,0x500,code<<8,addend,0x20)
                    path.write_bytes(image)
                    result=validate_identity_relocations(path)
                    self.assertTrue(result['identity_load_validated'])
                    self.assertEqual(path.read_bytes(),image)
                    struct.pack_into('<I',image,0x504,addend+4);path.write_bytes(image)
                    with self.assertRaisesRegex(ValueError,'requires unsupported rebasing'):
                        validate_identity_relocations(path)
