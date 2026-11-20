"""Execute native translations of opcodes encountered in genuine Gravity Rush."""
import unittest
import test_recompiler as support
from vitaxnative.recompiler import _decode_thumb32

class CommercialThumbTests(unittest.TestCase):
    translate=support.RecompilerTests.translate
    run_code=support.RecompilerTests.run_code

    def test_wide_stack_roundtrip_and_fault_atomicity(self):
        result=self.translate(support.elf([0xe92d,0x4e30,0x2400,0xe8bd,0x8e30],True))
        self.run_code(result,'r[13]=600;r[4]=99;r[9]=42;', 'if(r[13]!=600||r[4]!=99||r[9]!=42)return 10;')
        self.run_code(result,'r[13]=16;r[4]=99;', 'if(rc!=-2||r[13]!=16||r[4]!=99)return 11;rc=0;')
        for mask in (0,0x2000,0x8000,0xc010):
            with self.assertRaises(ValueError):_decode_thumb32((mask<<16)|0xe8bd,0)

    def test_register_signed_load_and_indexed_byte_store(self):
        result=self.translate(support.elf([0x5488,0x568b,0xf800,0x3b01,0x4770],True))
        # STRB r0,[r1,r2]; LDRSB r3,[r1,r2]; STRB r3,[r0],#1
        self.run_code(result,'r[0]=512;r[1]=600;r[2]=3;mem[603]=0x80;',
                      'if(r[0]!=513||mem[512]||r[3])return 12;')
        result=self.translate(support.elf([0xf991,0x0001,0x4770],True))
        self.run_code(result,'r[1]=600;mem[601]=0x80;', 'if(r[0]!=0xffffff80u)return 13;')

    def test_core_duplicate_bitfield_and_multiple_store(self):
        result=self.translate(support.elf([0xeee0,0x1b10,0xef20,0x2150,0xeca0,0x0b08,0xf361,0x210f,0xf361,0x411f,0x4770],True))
        self.run_code(result,'r[0]=512;r[1]=0xa5;',
                      'if(r[1]!=0xa5a5a5a5u||r[0]!=544)return 14;for(int i=512;i<544;i++)if(mem[i]!=0xa5)return 15;')
        result=self.translate(support.elf([0xe881,0x0030,0xe9d1,0x2300,0x4770],True))
        self.run_code(result,'r[1]=512;r[4]=0x12345678;r[5]=0xabcdef01;',
                      'if(r[2]!=r[4]||r[3]!=r[5]||r[1]!=512)return 16;')
        self.run_code(result,'r[1]=65532;r[4]=123;mem[65532]=9;',
                      'if(rc!=-2||mem[65532]!=9||r[1]!=65532)return 17;rc=0;')

    def test_long_multiply_alias_and_adc_without_flags(self):
        result=self.translate(support.elf([0xfba4,0x2302,0x4770],True))
        self.run_code(result,'r[4]=0xffffffffu;r[2]=0xffffffffu;',
                      'if(r[2]!=1||r[3]!=0xfffffffeu)return 18;')
        result=self.translate(support.elf([0x2800,0xeb43,0x0305,0xd200,0x2201,0x4770],True))
        self.run_code(result,'r[0]=0;r[3]=0xffffffffu;', 'if(r[3]||r[2])return 19;')

    def test_sp_add_nop_and_test_immediate(self):
        result=self.translate(support.elf([0xbf00,0xf10d,0x0009,0xf010,0x0f03,0x4770],True))
        self.run_code(result,'r[13]=600;', 'if(r[0]!=609)return 20;')

    def test_mov_shift_aliases_and_flags(self):
        # Exact commercial opcode 510847567: ROR.W lr,r2,#5, no flags.
        # Save the return sentinel in r3 and restore it after copying LR.
        result=self.translate(support.elf([0x4673,0xea4f,0x1e72,0x4670,0x469e,0x4770],True))
        self.run_code(result,'r[2]=0xfedcba98u;r[13]=600;',
                      'if(r[0]!=0xc7f6e5d4u||r[13]!=600)return 40;')
        cases=[(0x0041,0x80000001,2),     # LSL #1
               (0x0011,0x80000001,0),   # LSR #32
               (0x0021,0x80000001,0xffffffff), # ASR #32
               (0x0071,0x80000001,0xc0000000), # ROR #1
               (0x0031,3,0x80000001),   # RRX with C=1
               (0x0001,0x80000001,0x80000001)] # MOV, LSL #0
        for second,value,expected in cases:
            with self.subTest(second=hex(second)):
                result=self.translate(support.elf([0x2a00,0xea4f,second,0xd200,0x2401,0x4770],True))
                self.run_code(result,f'r[1]={value}u;',f'if(r[0]!={expected}u||r[4])return 41;')
        # LSRS #32 sets Z/C and preserves V from signed CMP overflow.
        result=self.translate(support.elf([0x2a01,0xea5f,0x0011,0xd200,0x2401,0xd000,0x2501,0xd600,0x2601,0x4770],True))
        self.run_code(result,'r[1]=0x80000000u;r[2]=0x80000000u;',
                      'if(r[0]||r[4]||r[5]||r[6])return 42;')
        result=self.translate(support.elf([0xea6f,0x0001,0x4770],True))
        self.run_code(result,'r[1]=0x12345678u;', 'if(r[0]!=0xedcba987u)return 43;')
        for first,second in [(0xea0f,0x0001),(0xea4f,0x0d11),
                             (0xea4f,0x001d),(0xea4f,0x001f),(0xea4f,0x0f11)]:
            with self.assertRaises(ValueError):_decode_thumb32(first|(second<<16),0)

    def test_clz_zero_alias_and_flags(self):
        for value,expected in [(0,32),(1,31),(16,27),(0x80000000,0),(0xffffffff,0)]:
            result=self.translate(support.elf([0x2a00,0xfab0,0xf080,0xd200,0x2401,0xd000,0x2501,0x4770],True))
            self.run_code(result,f'r[0]={value}u;',f'if(r[0]!={expected}u||r[4]||r[5])return 44;')
        for first,second in [(0xfab0,0xf081),(0xfabd,0xf08d),(0xfabf,0xf08f),(0xfab0,0xfd80),(0xfab0,0xff80)]:
            with self.assertRaises(ValueError):_decode_thumb32(first|(second<<16),0)

    def test_wide_move_alias_obeys_it_condition(self):
        result=self.translate(support.elf([0x2a00,0xbf08,0xea4f,0x0011,0x4770],True))
        self.run_code(result,'r[0]=17;r[1]=0x80000000u;', 'if(r[0])return 47;')
        self.run_code(result,'r[0]=17;r[1]=0x80000000u;r[2]=1;', 'if(r[0]!=17)return 48;')

    def test_rsb_immediate_result_and_nzcv(self):
        for value in (0,27,31,32,0x80000000,0xffffffff):
            expected=(31-value)&0xffffffff
            flags=[expected>>31,int(expected==0),int(31>=value),
                   int(bool(((31^value)&(31^expected))&0x80000000))]
            words=[0xf1d0,0x001f]
            for bit,cond in zip(flags,(4,0,2,6)):
                words += [0xd000|((cond if bit else cond^1)<<8),0x2401]
            result=self.translate(support.elf(words+[0x4770],True))
            self.run_code(result,f'r[0]={value}u;',f'if(r[0]!={expected}u||r[4])return 45;')
        result=self.translate(support.elf([0x2900,0xf1c0,0x001f,0xd200,0x2401,0x4770],True))
        self.run_code(result,'r[0]=32;', 'if(r[0]!=0xffffffffu||r[4])return 46;')

    def test_deferred_unsupported_traps_only_when_reached(self):
        blob=support.elf([0x2007,0xde00],True)
        with self.assertRaises(ValueError):self.translate(blob)
        result=self.translate(blob,defer_decode_errors=True)
        self.run_code(result,checks='if(rc!=-8||r[0]!=7)return 21;rc=0;')

    def test_negative_offset_alias_extensions_and_bitfield_extract(self):
        result=self.translate(support.elf([0xf851,0x1c0c,0x4770],True))
        self.run_code(result,'r[1]=600;vx_write32(mem+588,0x12345678);','if(r[1]!=0x12345678)return 30;')
        self.run_code(result,'r[1]=8;','if(rc!=-2||r[1]!=8)return 31;rc=0;')
        result=self.translate(support.elf([0xb2d1,0xfa5f,0xf892,0xf3c0,0x001e,0x4770],True))
        self.run_code(result,'r[0]=0xffffffffu;r[2]=0xabcdef80;','if(r[0]!=0x7fffffffu||r[1]!=0x80||r[8]!=0xef)return 32;')
