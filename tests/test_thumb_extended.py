"""Native regressions for integer forms required by the SDK NEON fixture."""
import unittest
import test_recompiler as support


class ThumbExtendedTests(unittest.TestCase):
    translate=support.RecompilerTests.translate
    run_code=support.RecompilerTests.run_code

    def test_modified_immediates_and_arithmetic_flags(self):
        # ADDS; BCS skip failure marker, with wraparound and signed overflow.
        result=self.translate(support.elf([0xf111,0x0001,0xd200,0x2201,0x4770],True))
        self.run_code(result,'r[1]=0xffffffff;', 'if(r[0]||r[2])return 90;')
        self.run_code(result,'r[1]=0x7fffffff;', 'if(r[0]!=0x80000000u||r[2]!=1)return 91;')
        # Rotated immediates set C to bit31; replicated immediates preserve C.
        result=self.translate(support.elf([0x2900,0xf051,0x10ff,0xd200,0x2201,0x4770],True))
        self.run_code(result,'r[1]=0;', 'if(r[0]!=0x00ff00ff||r[2])return 92;')
        result=self.translate(support.elf([0xf051,0x4000,0xd200,0x2201,0x4770],True))
        self.run_code(result,checks='if(r[0]!=0x80000000u||r[2])return 93;')

    def test_shifted_arithmetic_and_explicit_compare_in_it(self):
        result=self.translate(support.elf([0xeb01,0x0082,0x4770],True))
        self.run_code(result,'r[1]=1;r[2]=0xffffffff;', 'if(r[0]!=0xfffffffdu)return 94;')
        # High-register CMP in IT must update flags (unlike implicit MOVS).
        result=self.translate(support.elf([0x2800,0xbf08,0x45c8,0xd200,0x2301,0x4770],True))
        self.run_code(result,'r[0]=0;r[8]=1;r[9]=2;', 'if(r[3]!=1)return 95;')

    def test_indexed_memory_writeback_and_fault_atomicity(self):
        result=self.translate(support.elf([0xf851,0x0b04,0xf841,0x0d04,0x4770],True))
        self.run_code(result,'r[1]=600;vx_write32(mem+600,0x12345678);',
                      'if(r[0]!=0x12345678||r[1]!=600||vx_read32(mem+600)!=r[0])return 96;')
        self.run_code(result,'r[0]=7;r[1]=65534;',
                      'if(rc!=-2||r[1]!=65534||r[0]!=7)return 97;rc=0;')
        for halves in ([0xf851,0x1b04,0x4770],[0xf84f,0x0b04,0x4770],
                       [0xf851,0xfb04,0x4770],[0xf001,0x1000,0x4770]):
            with self.subTest(halves=halves),self.assertRaises(ValueError):
                self.translate(support.elf(halves,True))

    def test_cbz_cbnz_do_not_change_flags(self):
        for branch,zero_taken in ((0xb100,True),(0xb900,False)):
            result=self.translate(support.elf([0x2900,branch,0x2207,0xd200,0x2301,0x4770],True))
            for value in (0,1):
                # Skipped MOVS preserves CMP's C=1; executed MOVS also keeps C.
                self.run_code(result,f'r[0]={value};r[1]=0;',
                              f'if(r[2]!={0 if (value==0)==zero_taken else 7}||r[3])return 98;')
