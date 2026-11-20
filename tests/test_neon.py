"""Native execution of bounded SIMD with S/D/Q aliasing and wraparound."""
import unittest
import test_recompiler as support


class NeonTests(unittest.TestCase):
    translate=support.RecompilerTests.translate
    run_code=support.RecompilerTests.run_code

    def test_contiguous_structure_memory_and_atomic_faults(self):
        for thumb in (False,True):
            for typ,count in [(7,1),(10,2),(6,3),(2,4)]:
                # Load D14 onward, then store with immediate writeback.
                load=0xf422e00f|(typ<<8);store=0xf403e00d|(typ<<8)
                code=([h for w in (load,store) for h in ((w>>16)+0x500,w&65535)]+[0x4770]
                      if thumb else [load,store,0xe12fff1e])
                result=self.translate(support.elf(code,thumb))
                initial='r[2]=601;r[3]=701;'+''.join(f'mem[{601+i}]={i+1};' for i in range(32))
                checks=f'if(r[2]!=601||r[3]!={701+count*8})return 88;'+''.join(f'if(mem[{701+i}]!={i+1})return 89;' for i in range(count*8))
                self.run_code(result,initial,checks)
                self.run_code(result,'r[2]=65530;r[3]=701;mem[701]=77;',
                              'if(rc!=-2||r[2]!=65530||r[3]!=701||mem[701]!=77)return 90;rc=0;')
                self.run_code(result,'r[2]=601;r[3]=65530;mem[65530]=77;',
                              'if(rc!=-2||r[3]!=65530||mem[65530]!=77)return 91;rc=0;')
        # Register writeback snapshots an aliased base/offset before transfer.
        result=self.translate(support.elf([0xf422e702,0xe12fff1e]))
        self.run_code(result,'r[2]=601;', 'if(r[2]!=1202)return 92;')
        for word in (0xf40fe70f,0xf403e71f,0xf443fa0f,0xf403eb0f):
            with self.assertRaises(ValueError):self.translate(support.elf([word,0xe12fff1e]))

    def test_modified_immediate_d_q_and_high_aliases(self):
        cases=[(0,0,0,0),(0,0,0xa5,0x000000a5000000a5),
               (2,0,0x12,0x120000001200),(6,1,0x80,0x7fffffff7fffffff),
               (8,0,0x12,0x0012001200120012),(10,0,0x34,0x3400340034003400),
               (12,0,0x56,0x56ff000056ff),(13,0,0x78,0x78ffff0078ffff),
               (14,0,0xa5,0xa5a5a5a5a5a5a5a5),(14,1,0x81,0xff000000000000ff),
               (15,0,0x70,0x3f8000003f800000),
               (1,0,0x12,0xffffffffffffffff),(1,1,0x12,0xffffffedffffffed),
               (9,1,0x12,0xffedffedffedffed)]
        initial='r[2]=600;r[3]=700;'+''.join(f'vx_write32(mem+{600+i*4},0xffffffffu);' for i in range(4))
        for thumb in (False,True):
            for cmode,op,imm,expected in cases:
                word=0xf2800050|((imm&128)<<17)|((imm&112)<<12)|(imm&15)|(cmode<<8)|(op<<5)
                if thumb:
                    raw=0xef000000|(word&0x00ffffff)|((word&0x01000000)<<4)
                    code=[0xec92,0x0b04,raw>>16,raw&65535,0xec83,0x0b04,0x4770]
                else:code=[0xec920b04,word,0xec830b04,0xe12fff1e]
                result=self.translate(support.elf(code,thumb))
                checks=''.join(f'if(vx_read32(mem+{700+i*4})!={(expected>>(32*(i&1)))&0xffffffff}u)return 85;' for i in range(4))
                with self.subTest(thumb=thumb,cmode=cmode,op=op):self.run_code(result,initial,checks)
        # Exact commercial Q7 zero; store D14-D15 through their shared lanes.
        result=self.translate(support.elf([0xec92,0xeb04,0xef80,0xe050,0xec83,0xeb04,0x4770],True))
        self.run_code(result,initial,'for(int i=700;i<716;i++)if(mem[i])return 86;')
        result=self.translate(support.elf([0xec920b04,0xf2800013,0xec830b04,0xe12fff1e]))
        self.run_code(result,initial,'if(vx_read32(mem+700)!=3||vx_read32(mem+704)!=3||vx_read32(mem+708)!=0xffffffffu||vx_read32(mem+712)!=0xffffffffu)return 87;')
        for word in (0xf2801050,0xf2800f70):
            with self.assertRaises(ValueError):self.translate(support.elf([word,0xe12fff1e]))

    def test_bitwise_and_wrapping_integer_lanes(self):
        a=[0xffffffff,0x80000000,0x12345678,0x7fffffff]
        b=[1,0xffffffff,0xabcdef01,2]
        cases=[(0xf2020154,lambda x,y:x&y),
               (0xf2220154,lambda x,y:x|y),
               (0xf3020154,lambda x,y:x^y),
               (0xf2220844,lambda x,y:(x+y)&0xffffffff),
               (0xf3220844,lambda x,y:(x-y)&0xffffffff)]
        for thumb in (False,True):
            for op,operation in cases:
                # Load Q0-Q2; write Q0; store D0-D1, preserving raw payloads.
                words=[0xec920b0c,op,0xec830b04]
                if thumb:
                    words[1]=0xef000000|(op&0x00ffffff)|((op&0x01000000)<<4)
                    code=[h for w in words for h in (w>>16,w&65535)]+[0x4770]
                else:code=words+[0xe12fff1e]
                result=self.translate(support.elf(code,thumb))
                initial='r[2]=600;r[3]=700;'+''.join(
                    f'vx_write32(mem+{616+i*4},{x}u);vx_write32(mem+{632+i*4},{y}u);'
                    for i,(x,y) in enumerate(zip(a,b)))
                checks=''.join(f'if(vx_read32(mem+{700+i*4})!={operation(x,y)}u)return 80;'
                               for i,(x,y) in enumerate(zip(a,b)))
                with self.subTest(thumb=thumb,op=hex(op)):
                    self.run_code(result,initial,checks)

    def test_high_registers_alias_sources_and_invalid_encodings(self):
        # Q8 = Q9 & Q10; Q9 = Q9 + Q10 (destination aliases input).
        result=self.translate(support.elf([0xecd20b0c,0xf24201f4,0xf26228e4,
                                          0xecc30b08,0xe12fff1e]))
        self.run_code(result,'r[2]=600;r[3]=700;'+''.join(
            f'vx_write32(mem+{616+i*4},0xffffffffu);vx_write32(mem+{632+i*4},{i+1}u);'
            for i in range(4)), ''.join(
            f'if(vx_read32(mem+{700+i*4})!={i+1}u||vx_read32(mem+{716+i*4})!={i}u)return 81;'
            for i in range(4)))
        for op in (0xf2221844,0xf2230844,0xf2220845,0xf2000d40):
            with self.subTest(op=hex(op)),self.assertRaises(ValueError):
                self.translate(support.elf([op,0xe12fff1e]))
        # D form writes exactly two words; the adjacent D register is intact.
        result=self.translate(support.elf([0xec920b06,0xf2210802,0xec830b04,0xe12fff1e]))
        self.run_code(result,'r[2]=600;r[3]=700;vx_write32(mem+608,0xffffffff);'
                      'vx_write32(mem+616,1);vx_write32(mem+612,7);',
                      'if(vx_read32(mem+700)||vx_read32(mem+704)!=7||vx_read32(mem+708)!=0xffffffff)return 83;')

    def test_integer_element_widths_and_no_cross_lane_carries(self):
        for bits,size in ((8,0),(16,1),(32,2),(64,3)):
            for subtract in (False,True):
                op=0xf2020844|(size<<20)|(int(subtract)<<24)
                result=self.translate(support.elf([0xec920b0c,op,0xec830b04,0xe12fff1e]))
                # Every source word is all ones, every second operand is 1.
                initial='r[2]=600;r[3]=700;'+''.join(
                    f'vx_write32(mem+{616+i*4},0xffffffffu);vx_write32(mem+{632+i*4},1);'
                    for i in range(4))
                a=(1<<128)-1;b=sum(1<<(32*i) for i in range(4));mask=(1<<bits)-1
                expected=sum((((a>>shift)&mask)+(-1 if subtract else 1)*((b>>shift)&mask)&mask)<<shift
                             for shift in range(0,128,bits))
                checks=''.join(f'if(vx_read32(mem+{700+i*4})!={(expected>>(32*i))&0xffffffff}u)return 82;'
                               for i in range(4))
                with self.subTest(bits=bits,subtract=subtract):self.run_code(result,initial,checks)
