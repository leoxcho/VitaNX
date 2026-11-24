import os
from pathlib import Path
import unittest
import struct
import tempfile

from vitaxnative.commercial_loader import (map_commercial_game, map_module,
                                            make_link_plan, _thumb_mov_imm, PT_SCE_RELA)

ROOT=Path(os.environ.get('GRAVITY_ELF_DIR',str(Path.home() / 'gravity-rush-arm-extracted')))
PATHS=[ROOT/(name+'.elf') for name in ('eboot','libc','libfios2','libult')]

@unittest.skipUnless(all(p.is_file() for p in PATHS),'Requires four user-supplied, decrypted Gravity Rush ARM ELFs')
class CommercialLoaderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.modules=map_commercial_game(PATHS)

    def test_nonoverlap_and_relocation_counts(self):
        modules=self.modules
        self.assertEqual([m.new_base for m in modules],[0x81000000,0x90000000,0x90040000,0x90070000])
        self.assertEqual([sum(m.relocation_counts.values()) for m in modules],[0,6044,5553,3971])
        for index,a in enumerate(modules):
            for b in modules[index+1:]:
                self.assertFalse(a.new_base < b.new_base+len(b.memory) and b.new_base<a.new_base+len(a.memory))

    def test_tls_template_per_thread(self):
        m=self.modules[0]
        self.assertEqual((len(m.tls_template),m.tls_memsz),(12,160))
        self.assertEqual(m.tls_template,m.memory[0x5253bc:0x5253bc+12])
        a,b=m.tls_for_thread(),m.tls_for_thread()
        self.assertEqual(len(a),160);self.assertEqual(a[:12],m.tls_template)
        self.assertEqual(a[12:],bytes(148))
        a[0]^=1
        self.assertNotEqual(a,b)

    def test_every_rebased_record_is_encoded_correctly(self):
        count=0
        for mod in self.modules[1:]:
            data=mod.path.read_bytes()
            phoff,phnum=struct.unpack_from('<I',data,28)[0],struct.unpack_from('<H',data,44)[0]
            lookup={s['index']:s for s in mod.segments}
            for i in range(phnum):
                typ,off,_,_,length=struct.unpack_from('<IIIII',data,phoff+32*i)
                if typ!=PT_SCE_RELA:continue
                for pos in range(off,off+length,12):
                    first,addend,site_offset=struct.unpack_from('<III',data,pos)
                    symi,code,datai=(first>>4)&15,(first>>8)&255,(first>>16)&15
                    sym,dst=lookup[symi],lookup[datai]
                    new_target=(sym['address']+mod.delta+addend)&0xffffffff
                    idx=dst['address']+site_offset-mod.old_base
                    word=struct.unpack_from('<I',mod.memory,idx)[0]
                    if code==2:self.assertEqual(word,new_target)
                    elif code==47:self.assertEqual(_thumb_mov_imm(word),new_target&0xffff)
                    elif code==48:self.assertEqual(_thumb_mov_imm(word),new_target>>16)
                    else:self.fail('unexpected relocation type')
                    count+=1
        self.assertEqual(count,15568)

    def test_real_nid_link_addresses(self):
        plan=make_link_plan(self.modules)
        self.assertEqual(plan['eboot']['resolved'],128)
        self.assertEqual(plan['eboot']['unresolved_or_ambiguous'],367)
        self.assertEqual(plan['eboot']['other_imports']['variable'],13)
        for match in plan['eboot']['bound_targets']:
            target=int(match['target']['address'],16)
            self.assertGreaterEqual(target,0x90000000)

    def test_bad_addresses_fail_closed(self):
        with self.assertRaises(ValueError):map_module(PATHS[0],0x90000001)
        with self.assertRaises(ValueError):map_module(PATHS[0],0xffff0000)

    def test_variable_linking_matches_real_provider_and_preserves_missing(self):
        from vitaxnative.commercial_loader import link_variables
        modules=map_commercial_game(PATHS)
        report=link_variables(modules)
        self.assertEqual(len(report['bound']),13)
        self.assertEqual(report['relocations_applied'],1461)
        self.assertEqual([(x['module'],x['nid']) for x in report['missing']],[('SceLibc','df084dfa')])
        # The first real C locale variable uses a Thumb MOVW/MOVT pair.
        main,libc=modules[:2]
        self.assertEqual(_thumb_mov_imm(main.word(main.old_base+0x270360)),0x586c)
        self.assertEqual(_thumb_mov_imm(main.word(main.old_base+0x270368)),libc.new_base>>16|3)

    def test_actual_process_libc_parameter_binding(self):
        from vitaxnative.commercial_loader import link_variables
        modules=map_commercial_game(PATHS)
        main,libc=modules[:2];param=main.word(0x81526094+44)
        self.assertEqual(param,0x814b36b4);self.assertEqual(main.word(param),0x28)
        report=link_variables(modules,{('5ad9c136','df084dfa'):param})
        self.assertFalse(report['missing']);self.assertEqual(len(report['bound']),14)
        self.assertEqual(_thumb_mov_imm(libc.word(libc.old_base+0xd56a)),param&65535)
        self.assertEqual(_thumb_mov_imm(libc.word(libc.old_base+0xd56e)),param>>16)

class InvalidInputTests(unittest.TestCase):
    def test_nonsense_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'x.elf';path.write_bytes(b'not an elf')
            with self.assertRaises(ValueError):map_module(path)



