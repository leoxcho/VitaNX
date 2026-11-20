"""Native scalar VFP results, cumulative FPSCR exceptions and edge cases."""
import unittest
import test_recompiler as support

class ScalarVfpTests(unittest.TestCase):
    translate=support.RecompilerTests.translate
    run_code=support.RecompilerTests.run_code

    def program(self,opcode):
        return self.translate(support.elf([0xee000a10,0xee001a90,opcode,0xee112a10,0xeef13a10,0xe12fff1e]))

    def test_thumb_scalar_arithmetic_and_literal_alignment(self):
        # Thumb VFP uses the same fields, with the first halfword stored first.
        words=[0xee000a10,0xee001a90,0xee301a20,0xee112a10]
        halves=[half for word in words for half in (word>>16,word&65535)]
        result=self.translate(support.elf(halves+[0x4770],True))
        self.run_code(result,'r[0]=0x3fc00000;r[1]=0x40100000;',
                      'if(r[2]!=0x40700000u)return 66;')
        # At PC=0x102 the literal base is Align(PC+4,4)=0x104.
        result=self.translate(support.elf([0x4624,0xed9f,0x0a02,0xee10,0x0a10,
                                           0x4770,0x1234,0x7fc0],True))
        self.run_code(result,checks='if(r[0]!=0x7fc01234u)return 67;')
        for halves in ([0xeee1,0x0a10,0x4770],[0xee30,0x0b01,0x4770]):
            with self.assertRaises(ValueError):
                self.translate(support.elf(halves,True))

    def test_thumb_it_vfp_and_implicit_flags(self):
        # CMP; IT EQ; MOV r1,#0; BNE failure; return. MOV must preserve Z.
        result=self.translate(support.elf([0x2800,0xbf08,0x2100,0xd100,0x4770,0x2201,0x4770],True))
        self.run_code(result,'r[0]=0;r[1]=7;', 'if(r[1]||r[2])return 68;')
        self.run_code(result,'r[0]=1;r[1]=7;', 'if(r[1]!=7||r[2]!=1)return 69;')
        # Conditional 32-bit VFP literal uses the slot PC, not the IT PC.
        result=self.translate(support.elf([0x2800,0xbf08,0xed9f,0x0a02,
                                           0xee10,0x1a10,0x4770,0x4624,0x5678,0x3f80],True))
        self.run_code(result,'r[0]=0;', 'if(r[1]!=0x3f805678u)return 70;')
        self.run_code(result,'r[0]=1;', 'if(r[1])return 71;')

    def test_thumb_it_rejects_unsupported_or_ambiguous_blocks(self):
        for halves in ([0xbf0c,0x2000],  # truncated ITE
                       [0xbfe8,0x2000,0x4770],  # invalid AL
                       [0xbf04,0xe000,0x2000,0x4770],  # non-final branch
                       [0xbf08], [0xbf08,0xee00],  # truncated
                       [0x2800,0xd000,0xbf08,0x2000,0x4770]):  # branch into slot
            with self.subTest(halves=halves),self.assertRaises(ValueError):
                self.translate(support.elf(halves,True))

    def test_multiple_transfers_stack_aliases_and_bounds(self):
        # Save caller D8-D15 raw bits, fill S16 via scalar move, restore.
        words=[0xed2d8b10,0xee080a10,0xecbd8b10,0xee182a10,0xe12fff1e]
        for thumb in (False,True):
            encoded=([h for w in words[:-1] for h in (w>>16,w&65535)]+[0x4770]
                     if thumb else words)
            result=self.translate(support.elf(encoded,thumb))
            self.run_code(result,'r[13]=640;r[0]=0x7f800001;',
                          'if(r[2]||r[13]!=640||mem[576])return 72;')
            self.run_code(result,'r[13]=65540;',
                          'if(rc!=-2||r[13]!=65540)return 73;rc=0;')
            self.run_code(result,'r[13]=642;',
                          'if(rc!=-2||r[13]!=642)return 74;rc=0;')
        # S4-S7 overlap D2-D3; IA without writeback must leave the base alone.
        result=self.translate(support.elf([0xee020a10,0xeca12a04,0xed212b04,
                                           0xec912a04,0xee122a10,0xe12fff1e]))
        self.run_code(result,'r[0]=0x7fc01234;r[1]=600;',
                      'if(r[2]!=r[0]||r[1]!=600)return 75;')
        for op in (0xecb00a00,0xecb0fa04,0xecb00b03,0xecb00b22,0xecbf0a04):
            with self.subTest(op=hex(op)),self.assertRaises(ValueError):
                self.translate(support.elf([op,0xe12fff1e]))

    def test_sqrt_and_nonfused_multiply_accumulate(self):
        for op,expected in ((0xee000a81,0x40800000),(0xee000ac1,0xc0000000)):
            result=self.translate(support.elf([0xee000a10,0xee001a90,0xee012a10,
                                               op,0xee103a10,0xeef14a10,0xe12fff1e]))
            self.run_code(result,'r[0]=0x3f800000;r[1]=0x3fc00000;r[2]=0x40000000;',
                          f'if(r[3]!={expected}u||r[4])return 76;')
            if op==0xee000a81:
                self.run_code(result,'r[0]=0xbf800000;r[1]=0x3f800001;r[2]=0x3f7ffffe;',
                              'if(r[3]||r[4]!=16)return 77;')
        result=self.translate(support.elf([0xee000a10,0xeeb10ac0,0xee101a10,
                                           0xeef12a10,0xe12fff1e]))
        for bits,expected,flags in ((0x40800000,0x40000000,0),(0x40000000,0x3fb504f3,16),
                                    (0x80000000,0x80000000,0),(0x7f800000,0x7f800000,0)):
            self.run_code(result,f'r[0]={bits}u;',f'if(r[1]!={expected}u||r[2]!={flags})return 78;')
        self.run_code(result,'r[0]=0xbf800000;',
                      'if((r[1]&0x7fffffffu)<=0x7f800000u||r[2]!=1)return 79;')

    def test_core_pairs_and_raw_double_memory(self):
        words=[0xec410b3f,0xedc4fb01,0xedd4eb01,0xec532b3e]
        for thumb in (False,True):
            code=([h for w in words for h in (w>>16,w&65535)]+[0x4770]
                  if thumb else words+[0xe12fff1e])
            result=self.translate(support.elf(code,thumb))
            self.run_code(result,'r[0]=0x7f800001;r[1]=0xffc01234;r[4]=600;',
                          'if(r[2]!=r[0]||r[3]!=r[1])return 84;')
            self.run_code(result,'r[2]=7;r[3]=8;r[4]=65528;',
                          'if(rc!=-2||r[2]!=7||r[3]!=8)return 85;rc=0;')
            self.run_code(result,'r[4]=601;', 'if(rc!=-2)return 86;rc=0;')
        # Invalid/ambiguous core pair and double arithmetic remain rejected.
        for op in (0xec400b10,0xec4f0b10,0xec410b50,0xee300b01):
            with self.subTest(op=hex(op)),self.assertRaises(ValueError):
                self.translate(support.elf([op,0xe12fff1e]))

    def test_binary_rounding_signed_zero_exceptions_and_denormals(self):
        cases=[(0xee301a20,0x3fc00000,0x40100000,0x40700000,0),
               (0xee301a60,0x3f800000,0x3f800000,0,0),
               (0xee201a20,0x80000000,0x40000000,0x80000000,0),
               (0xee801a20,0x3f800000,0,0x7f800000,2),
               (0xee801a20,0x3f800000,0x40400000,0x3eaaaaab,16),
               (0xee201a20,0x7f7fffff,0x40000000,0x7f800000,20),
               (0xee201a20,0x00800000,0x3f000000,0x00400000,0),
               (0xee201a20,1,0x3f000000,0,24)]
        for op,a,b,expected,flags in cases:
            with self.subTest(op=hex(op),a=hex(a),b=hex(b)):
                self.run_code(self.program(op),f'r[0]={a}u;r[1]={b}u;',
                              f'if(r[2]!={expected}u||r[3]!={flags}u)return 60;')
        self.run_code(self.program(0xee801a20),'r[0]=0;r[1]=0;',
                      'if((r[2]&0x7fffffffu)<=0x7f800000u||r[3]!=1)return 61;')

    def test_conversions_saturate_without_undefined_c_casts(self):
        operations=[(0xeefd0ac0,[(0x4079999a,3,16),(0xc079999a,0xfffffffd,16),
                               (0x4f000000,0x7fffffff,1),(0xcf000000,0x80000000,0),
                               (0x7fc00000,0,1),(0xff800000,0x80000000,1)]),
                    (0xeefc0ac0,[(0xbf000000,0,16),(0xbf800000,0,1),
                               (0x4f800000,0xffffffff,1),(0x7fc00000,0,1)]),
                    (0xeef80ac0,[(0xfffffffd,0xc0400000,0),(0x7fffffff,0x4f000000,16)]),
                    (0xeef80a40,[(0xffffffff,0x4f800000,16),(7,0x40e00000,0)])]
        for op,cases in operations:
            result=self.translate(support.elf([0xee000a10,op,0xee101a90,0xeef12a10,0xe12fff1e]))
            rows=','.join('{'+','.join(str(v)+'u' for v in row)+'}' for row in cases)
            checks=('uint32_t cases[][3]={'+rows+'};for(unsigned i=0;i<sizeof(cases)/sizeof(cases[0]);i++){'
                    'for(int j=0;j<16;j++)r[j]=0;r[0]=cases[i][0];r[14]=0xffffffffu;rc=vx_guest(r,mem,sizeof mem);'
                    'if(rc||r[1]!=cases[i][1]||r[2]!=cases[i][2])return 62;}')
            self.run_code(result,checks=checks)

    def test_compare_nan_signed_zero_and_apsr_transfer(self):
        for signaling in (False,True):
            compare=0xeeb40ae0 if signaling else 0xeeb40a60
            result=self.translate(support.elf([0xee000a10,0xee001a90,compare,0xeef1fa10,
                                               0x43a04001,0x03a05001,0x23a06001,0x63a07001,0xeef12a10,0xe12fff1e]))
            cases=[(0x80000000,0,0x60000000),(0xbf800000,0x3f800000,0x80000000),
                   (0x3f800000,0xbf800000,0x20000000),
                   (0x7fc00000,0,0x30000000|int(signaling)),(0x7f800001,0,0x30000001)]
            rows=','.join('{'+','.join(str(v)+'u' for v in row)+'}' for row in cases)
            checks=('uint32_t cases[][3]={'+rows+'};for(unsigned i=0;i<sizeof(cases)/sizeof(cases[0]);i++){'
                    'for(int j=0;j<16;j++)r[j]=0;r[0]=cases[i][0];r[1]=cases[i][1];r[14]=0xffffffffu;rc=vx_guest(r,mem,sizeof mem);'
                    'if(rc||r[2]!=cases[i][2]||r[4]!=(r[2]>>31)||r[5]!=((r[2]>>30)&1)||r[6]!=((r[2]>>29)&1)||r[7]!=((r[2]>>28)&1))return 63;}')
            self.run_code(result,checks=checks)

    def test_memory_bit_moves_and_unsupported_modes(self):
        # Core -> s0; VSTR; VLDR s1; VMOV core preserves all payload bits.
        result=self.translate(support.elf([0xee000a10,0xed810a00,0xedd10a00,0xee102a90,0xe12fff1e]))
        self.run_code(result,'r[0]=0x7f800001u;r[1]=600;', 'if(r[2]!=r[0])return 64;')
        self.run_code(result,'r[1]=65534;', 'if(rc!=-2)return 65;rc=0;')
        for op in (0xeee10a10,0xee300b01,0xf2000d40):
            with self.subTest(op=hex(op)),self.assertRaises(ValueError):
                self.translate(support.elf([op,0xe12fff1e]))

    def test_negative_multiply_accumulate_rounding_and_zero(self):
        for opcode,expected in ((0xee100a81,0x40000000),(0xee100ac1,0xc0800000),(0xee200ac1,0xc0400000)):
            result=self.translate(support.elf([0xee000a10,0xee001a90,0xee012a10,opcode,0xee103a10,0xeef14a10,0xe12fff1e]))
            self.run_code(result,'r[0]=0x3f800000;r[1]=0x3fc00000;r[2]=0x40000000;',f'if(r[3]!={expected}u||r[4])return 90;')
            if opcode==0xee100a81:
                self.run_code(result,'r[0]=0x3f800000;r[1]=0x3f800001;r[2]=0x3f7ffffe;', 'if(r[3]||r[4]!=16)return 91;')
            if opcode==0xee200ac1:
                self.run_code(result,'r[0]=0;r[1]=0;r[2]=0x3f800000;', 'if(r[3]!=0x80000000u||r[4])return 92;')
