import unittest
import test_recompiler as support


class ArmExtraMemoryTests(unittest.TestCase):
    translate=support.RecompilerTests.translate
    run_code=support.RecompilerTests.run_code

    def test_signed_and_unsigned_loads_and_halfword_store(self):
        # STRH r0,[r1]; LDRH r2,[r1]; LDRSB r3,[r1]; LDRSH r4,[r1].
        result=self.translate(support.elf([0xe1c100b0,0xe1d120b0,0xe1d130d0,0xe1d140f0,0xe12fff1e]))
        self.run_code(result,'r[0]=0xffff8080;r[1]=601;',
                      'if(r[2]!=0x8080||r[3]!=0xffffff80||r[4]!=0xffff8080)return 100;')
        self.run_code(result,'r[1]=65535;', 'if(rc!=-2)return 101;rc=0;')

    def test_pre_post_writeback_and_fault_preservation(self):
        result=self.translate(support.elf([0xe0d120b2,0xe17130b2,0xe12fff1e]))
        self.run_code(result,'r[1]=600;mem[600]=0xff;mem[601]=0x80;',
                      'if(r[1]!=600||r[2]!=0x80ff||r[3]!=0x80ff)return 102;')
        self.run_code(result,'r[1]=65535;r[2]=7;',
                      'if(rc!=-2||r[1]!=65535||r[2]!=7)return 103;rc=0;')
        for word in (0xe0d110b2,0xe1c100d0,0xe0f120b2):
            with self.assertRaises(ValueError):self.translate(support.elf([word,0xe12fff1e]))

    def test_extend_rotations_aliasing_and_signed_values(self):
        for opcode,signed,width in ((0xe6af0070,True,8),(0xe6bf0070,True,16),(0xe6ef0070,False,8),(0xe6ff0070,False,16)):
            for rotation in (0,8,16,24):
                result=self.translate(support.elf([opcode|(rotation//8)<<10,0xe12fff1e]))
                value=0x81fe807f
                rotated=((value>>rotation)|(value<<(32-rotation)))&0xffffffff if rotation else value
                expected=rotated&((1<<width)-1)
                if signed and expected&(1<<(width-1)):expected|=0xffffffff^((1<<width)-1)
                self.run_code(result,f'r[0]={value}u;',f'if(r[0]!={expected}u)return 104;')
        for word in (0xe6eff071,0xe6ef107f):
            with self.assertRaises(ValueError):self.translate(support.elf([word,0xe12fff1e]))

    def test_general_multiple_transfer_modes_and_atomic_faults(self):
        # STM/LDM through r12; full-span prevalidation prevents partial effects.
        for up in (False,True):
            for pre in (False,True):
                mode=(int(up)<<23)|(int(pre)<<24)
                store=0xe82c0003|mode
                load=0xe81c0003|mode  # no writeback, preserve base for postchecks
                first=600+(4 if pre else 0) if up else 600+(-8 if pre else -4)
                result=self.translate(support.elf([store,0xe12fff1e]))
                updated=608 if up else 592
                self.run_code(result,'r[12]=600;r[0]=0x12345678;r[1]=0xabcdef01;',
                    f'if(r[12]!={updated}||vx_read32(mem+{first})!=0x12345678u||vx_read32(mem+{first+4})!=0xabcdef01u)return 110;')
                result=self.translate(support.elf([load,0xe12fff1e]))
                self.run_code(result,f'r[12]=600;vx_write32(mem+{first},0x81234567);vx_write32(mem+{first+4},0xabcdef01);',
                    'if(r[12]!=600||r[0]!=0x81234567u||r[1]!=0xabcdef01u)return 111;')
        for word in (0xe8ac0003,0xe8bc0003):
            result=self.translate(support.elf([word,0xe12fff1e]))
            self.run_code(result,'r[12]=65532;r[0]=7;r[1]=8;vx_write32(mem+65532,9);',
                'if(rc!=-2||r[12]!=65532||r[0]!=7||r[1]!=8||vx_read32(mem+65532)!=9)return 112;rc=0;')
            self.run_code(result,'r[12]=601;', 'if(rc!=-2||r[12]!=601)return 113;rc=0;')
        for word in (0xe8bc1001,0xe8fc0003,0xe89c8001,0xe88c0000):
            with self.assertRaises(ValueError):self.translate(support.elf([word,0xe12fff1e]))

    def test_arm_adr_architectural_pc(self):
        for word,expected in ((0xe28f0010,0x118),(0xe24f0010,0xf8)):
            result=self.translate(support.elf([word,0xe12fff1e]))
            self.run_code(result,'r[15]=0xdeadbeef;',f'if(r[0]!={expected})return 120;')

    def test_register_offset_memory_shifts_and_atomic_faults(self):
        # STR r0,[r1,r2,LSL #2]!; LDR r3,[r1],-r2,LSL #2.
        result=self.translate(support.elf([0xe7a10102,0xe6113102,0xe12fff1e]))
        self.run_code(result,'r[0]=0x81234567;r[1]=600;r[2]=3;',
            'if(r[1]!=600||r[3]!=r[0]||vx_read32(mem+612)!=r[0])return 121;')
        self.run_code(result,'r[0]=7;r[1]=65532;r[2]=1;',
            'if(rc!=-2||r[1]!=65532||vx_read32(mem+65532))return 122;rc=0;')
        # LDRB r0,[r1,r2,ROR #0] uses RRX and preserves flags.
        result=self.translate(support.elf([0xe7d10062,0xe12fff1e]))
        self.run_code(result,'r[1]=600;r[2]=2;mem[601]=0xab;',
            'if(r[0]!=0xab)return 123;')
        for word in (0xe7910012,0xe791000f,0xe7b11002):
            with self.assertRaises(ValueError):self.translate(support.elf([word,0xe12fff1e]))
