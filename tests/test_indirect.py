"""Exact indirect dispatch, execution-state and genuine VitaSDK regressions."""
from pathlib import Path
import importlib.util
import os
import shutil
import subprocess
import tempfile
import unittest
import test_recompiler as support

ROOT=Path(__file__).resolve().parents[1]


class IndirectTests(unittest.TestCase):
    translate=support.RecompilerTests.translate
    run_code=support.RecompilerTests.run_code

    def test_bx_state_alignment_unknown_targets(self):
        blob=support.elf([0xe12fff10,0xe1a00000,0xe3a0102a,0xe12fff1e,0x47702135])
        r=self.translate(blob,indirect_targets=[0x108,0x111])
        for address,want in ((0x108,42),(0x111,53)):
            self.run_code(r,f'r[0]={address};',f'if(r[1]!={want})return 10;')
        for address in (0x109,0x10a,0x114,0x80000000):
            self.run_code(r,f'r[0]={address}u;', 'if(rc!=-3)return 11;rc=0;')

    def test_blx_lr_snapshots_target_before_link_write(self):
        r=self.translate(support.elf([0xe12fff3e,0xe12fff13,0xe1a0200e,0xe12fff1e]),
                         indirect_targets=[0x108])
        self.run_code(r,'r[14]=0x108;r[3]=0xffffffff;', 'if(r[2]!=0x104)return 12;')

    def test_arm_loaded_pc_interworks_and_fault_preserves_base(self):
        r=self.translate(support.elf([0xe491f004,0xe12fff1e,0xe3a0202a,0xe12fff1e,0x47702235]),
                         indirect_targets=[0x108,0x111])
        for address,want in ((0x108,42),(0x111,53)):
            self.run_code(r,f'r[1]=600;vx_write32(mem+600,{address});',
                          f'if(r[1]!=604||r[2]!={want})return 13;')
        for address in (601,65534):
            self.run_code(r,f'r[1]={address};',f'if(rc!=-2||r[1]!={address})return 14;rc=0;')

    def test_tbb_pc_base_and_data_bounds(self):
        # Inline byte table; only the two case starts are declared as code roots.
        r=self.translate(support.elf([0xe8df,0xf000,0x0301,0x212a,0x4770,0x2135,0x4770],True),
                         indirect_targets=[0x107,0x10b])
        for index,want in ((0,42),(1,53)):
            self.run_code(r,f'r[0]={index};',f'if(r[1]!={want})return 15;')
        self.run_code(r,'r[0]=65536;', 'if(rc!=-2)return 16;rc=0;')

    def test_thumb_mov_pc_stays_thumb(self):
        r=self.translate(support.elf([0x4687,0x4770,0x212a,0x4770],True),
                         indirect_targets=[0x105])
        for target in (0x104,0x105):
            self.run_code(r,f'r[0]={target};','if(r[1]!=42)return 17;')

    def test_multi_slot_it_predicates_flags_and_final_branch(self):
        # ITE EQ: implicit MOVS must preserve the predicate for the else slot.
        r=self.translate(support.elf([0x2800,0xbf0c,0x2107,0x2109,0x4770],True))
        for value,want in ((0,7),(1,9)):
            self.run_code(r,f'r[0]={value};',f'if(r[1]!={want})return 18;')
        # IT EQ; BX r1 in final slot keeps the not-taken fallthrough.
        r=self.translate(support.elf([0x2800,0xbf08,0x4708,0x2209,0x4770,0x2207,0x4770],True),
                         indirect_targets=[0x10b])
        for value,want in ((0,7),(1,9)):
            self.run_code(r,f'r[0]={value};r[1]=0x10b;',f'if(r[2]!={want})return 19;')
        # Non-final branch and external edges into IT slots are invalid.
        for words in ([0xbf04,0x4700,0x2101,0x4770],):
            with self.assertRaises(ValueError):self.translate(support.elf(words,True))
        with self.assertRaises(ValueError):
            self.translate(support.elf([0xe000,0xbf08,0x2101,0x4770],True),indirect_targets=[0x103])

    def test_four_slot_ittee(self):
        r=self.translate(support.elf([0x2800,0xbf07,0x2101,0x2202,0x2303,0x2404,0x4770],True))
        self.run_code(r,'r[0]=0;', 'if(r[1]!=1||r[2]!=2||r[3]||r[4])return 28;')
        self.run_code(r,'r[0]=1;', 'if(r[1]||r[2]||r[3]!=3||r[4]!=4)return 29;')

    def test_thumb_register_offset_and_mvn_alias(self):
        r=self.translate(support.elf([0xf851,0x0022,0xf06f,0x0308,0x4770],True))
        self.run_code(r,'r[1]=600;r[2]=2;vx_write32(mem+608,0x81234567);',
                      'if(r[0]!=0x81234567u||r[3]!=0xfffffff7u)return 20;')
        self.run_code(r,'r[1]=65532;r[2]=1;r[0]=7;',
                      'if(rc!=-2||r[0]!=7)return 21;rc=0;')

    def test_arm_pc_read_shift_bias_and_unpredictable_forms(self):
        # Immediate shifts read architectural PC+8. Register-controlled PC
        # operands are unpredictable in ARMv7 and must not be translated.
        r=self.translate(support.elf([0xe1a0008f,0xe12fff1e]))
        self.run_code(r,checks='if(r[0]!=0x210)return 22;')
        for word in (0xe1a0011f,0xe08f0112,0xe080f112,0xe12fff3f):
            with self.assertRaises(ValueError):
                self.translate(support.elf([word,0xe12fff1e]))


    def test_tbh_unaligned_pc_base_and_unsigned_halfword_offsets(self):
        # TBH starts at address 0x102: PC reads 0x106, not Align(PC,4).
        r=self.translate(support.elf([0xbf00,0xe8df,0xf010,2,4,0x212a,0x4770,0x2135,0x4770],True),
                         indirect_targets=[0x10b,0x10f])
        for index,want in ((0,42),(1,53)):
            self.run_code(r,f'r[0]={index};',f'if(r[1]!={want})return 23;')
        # Register base, a halfword value above 255 must not be truncated.
        r=self.translate(support.elf([0xe8d1,0xf010,0x4770],True))
        self.run_code(r,'r[1]=600;mem[600]=0;mem[601]=1;',
                      'if(rc!=-3)return 24;rc=0;')
        self.run_code(r,'r[1]=65535;', 'if(rc!=-2)return 25;rc=0;')

    def test_thumb_literal_and_immediate_loaded_pc_interwork(self):
        # LDR.W pc,[pc,#0] at halfword alignment uses Align(PC+4,4).
        r=self.translate(support.elf([0xbf00,0xf8df,0xf004,0xbf00,0x010d,0,0x212a,0x4770],True),
                         indirect_targets=[0x10d])
        self.run_code(r,checks='if(r[1]!=42)return 26;')
        r=self.translate(support.elf([0xf8d1,0xf000,0x4770,0x212a,0x4770],True),
                         indirect_targets=[0x107])
        self.run_code(r,'r[1]=600;vx_write32(mem+600,0x107);','if(r[1]!=42)return 27;')


class GenuineSDKIndirectTests(unittest.TestCase):
    def test_arm_and_thumb_compiler_switches_native(self):
        sdk=Path(os.environ.get('VITASDK',ROOT.parent/'vitasdk'))
        if not (sdk/'bin/arm-vita-eabi-gcc').exists() or not shutil.which('clang'):
            self.skipTest('VitaSDK and native Clang required')
        from vitaxnative.build import build_native
        spec=importlib.util.spec_from_file_location('sdk_builder',ROOT/'fixtures/vitasdk/build_fixture.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as temp:
            for thumb in (False,True):
                with self.subTest(thumb=thumb):
                    base=Path(temp)/('thumb' if thumb else 'arm')
                    velf=module.build(base/'sdk','indirect',thumb)
                    out=base/'native'
                    build_native(velf,out,name='SDK indirect')
                    app=next(out.glob('*.app'));binary=app/'Contents/MacOS/Game'
                    subprocess.run(['codesign','--verify','--strict',str(app)],check=True,capture_output=True)
                    saves=base/'saves';saves.mkdir()
                    run=subprocess.run([str(binary)],env={**os.environ,'VX_SAVE_ROOT':str(saves)},
                                       capture_output=True,text=True,timeout=15)
                    self.assertEqual(run.returncode,0,run.stderr)
                    self.assertIn('VitaSDK indirect ARM/Thumb switch/interwork PASS',run.stdout)
                    self.assertIn('arm64',subprocess.check_output(['file',str(binary)],text=True))
