# Modified for vitanx 2026-11-09: opt-in live target yield and shared monitor; AOT default retained.
"""Small, fail-closed ARM/Thumb static translator for explicit homebrew fixtures.

Generated C contains translated statements, never an instruction decoder. This is
not a commercial Vita converter: most Thumb-2 and VFP remain unsupported. Bounded
Vita module metadata supplies SCE imports and entry; identity relocations must
match linked bytes. Ordinary ELF imports use explicit manifests.
"""
import hashlib
import re
import struct
from pathlib import Path
from .elf_segments import inspect_elf_segments
from .elf_dependencies import inspect_elf_dependencies

MAX_MEMORY = 16 * 1024 * 1024
MAX_INSTRUCTIONS = 65536

# Static scalar operations, compiled by Clang into host ARM64 floating point.
# Guest FPSCR control writes, double arithmetic and other SIMD fail closed.
VFP_HELPERS = r'''
#pragma STDC FENV_ACCESS ON
static float vx_float(uint32_t bits){float value;memcpy(&value,&bits,4);return value;}
static uint32_t vx_bits(float value){uint32_t bits;memcpy(&bits,&value,4);return bits;}
static void vx_fp_exceptions(uint32_t *fpscr){int e=fetestexcept(FE_ALL_EXCEPT);
 if(e&FE_INVALID)*fpscr|=1;if(e&FE_DIVBYZERO)*fpscr|=2;if(e&FE_OVERFLOW)*fpscr|=4;
 if(e&FE_UNDERFLOW)*fpscr|=8;if(e&FE_INEXACT)*fpscr|=16;}
static uint32_t vx_fp_binary(uint32_t a,uint32_t b,unsigned op,uint32_t *fpscr){
 float x=vx_float(a),y=vx_float(b);feclearexcept(FE_ALL_EXCEPT);volatile float result;
 switch(op){case 0:result=x+y;break;case 1:result=x-y;break;case 2:result=x*y;break;default:result=x/y;break;}
 vx_fp_exceptions(fpscr);return vx_bits(result);
}
static uint32_t vx_fp_sqrt(uint32_t bits,uint32_t *fpscr){
 feclearexcept(FE_ALL_EXCEPT);volatile float result=sqrtf(vx_float(bits));
 vx_fp_exceptions(fpscr);return vx_bits(result);
}
static uint32_t vx_fp_fromint(uint32_t bits,int is_signed,uint32_t *fpscr){
 feclearexcept(FE_ALL_EXCEPT);volatile float value;
 if(is_signed)value=(float)(int32_t)bits;else value=(float)bits;
 vx_fp_exceptions(fpscr);return vx_bits(value);
}
static uint32_t vx_fp_toint(uint32_t bits,int is_signed,uint32_t *fpscr){
 float f=vx_float(bits);if(isnan(f)){*fpscr|=1;return 0;}
 double value=trunc((double)f);
 if(is_signed){if(value>=2147483648.0){*fpscr|=1;return 0x7fffffff;}
  if(value< -2147483648.0){*fpscr|=1;return 0x80000000;}}
 else {if(value>=4294967296.0){*fpscr|=1;return 0xffffffff;}
  if(value<0){*fpscr|=1;return 0;}}
 if(value!=(double)f)*fpscr|=16;
 return is_signed?(uint32_t)(int32_t)value:(uint32_t)value;
}
static void vx_fp_compare(uint32_t a,uint32_t b,int signaling,uint32_t *fpscr){
 float x=vx_float(a),y=vx_float(b);uint32_t flags;
 if(isnan(x)||isnan(y)){flags=0x30000000;
  if(signaling||((a&0x7fffffff)>0x7f800000&&!(a&0x400000))||
                ((b&0x7fffffff)>0x7f800000&&!(b&0x400000)))*fpscr|=1;}
 else flags=x==y?0x60000000:x<y?0x80000000:0x20000000;
 *fpscr=(*fpscr&0x0fffffff)|flags;
}
'''


def _sx(value, bits):
    return value - (1 << bits) if value & (1 << (bits - 1)) else value


def _reg(n):
    if n >= 15:
        raise ValueError('PC register operand unsupported')
    return f'r[{n}]'


def _condition(c):
    return ['z', '!z', 'c', '!c', 'n', '!n', 'v', '!v',
            'c&&!z', '!c||z', 'n==v', 'n!=v', '!z&&(n==v)',
            'z||(n!=v)', '1'][c] if c < 15 else None


def _flags(a, b, subtract=False):
    # uint64 intermediates avoid signed overflow and preserve ARM carry convention.
    op = '-' if subtract else '+'
    carry = f'((uint32_t)({a}) >= (uint32_t)({b}))' if subtract else '(wide>>32)'
    overflow = f'(((a^b)&(a^t))>>31)' if subtract else '(~(a^b)&(a^t))>>31'
    return f'{{uint32_t a={a},b={b},t=a{op}b; uint64_t wide=(uint64_t)a{op}b; n=t>>31;z=t==0;c={carry};v={overflow};}}'


def _arm_operand(w, pc=None):
    if w & (1 << 25):
        imm, rot = w & 255, ((w >> 8) & 15) * 2
        value=((imm >> rot) | (imm << (32-rot))) & 0xffffffff
        return f'uint32_t operand={value}u,shift_c={value>>31 if rot else "c"};'
    if w & 0x90 == 0x90:
        raise ValueError('ARM miscellaneous/extra load-store encoding unsupported')
    register=bool(w & 16)
    amount=f'({_reg((w>>8)&15)}&255u)' if register else str((w>>7)&31)+'u'
    source = (f'{(pc + 8) & 0xffffffff}u'
              if w&15 == 15 and pc is not None else _reg(w&15))
    return (f'uint64_t shifted=vx_shift({source},{(w>>5)&3}u,{amount},c,{int(register)});'
            'uint32_t operand=(uint32_t)shifted,shift_c=(uint32_t)(shifted>>32);')


def _carry_arithmetic(a,b,destination,subtract=False,flags=True):
    code=(f'{{uint32_t aa={a},bb={b},cc=c;uint64_t wide=(uint64_t)aa+'
          f'{"(uint32_t)~bb" if subtract else "bb"}+cc;uint32_t t=(uint32_t)wide;')
    if flags:
        overflow='(aa^bb)&(aa^t)' if subtract else '~(aa^bb)&(aa^t)'
        code+=f'n=t>>31;z=t==0;c=(uint32_t)(wide>>32);v=({overflow})>>31;'
    return code+f'{destination}=t;}}'


def _decode_vfp(w,pc,cond,thumb=False):
    if w & 0x0f900f5f == 0x0e800b10:  # VDUP core register to D/Q lanes
        rt=(w>>12)&15;d=((w>>16)&15)|((w>>3)&16);quad=bool(w&(1<<21))
        if rt in (13,15) or (quad and d&1) or (w&(1<<22) and w&32):
            raise ValueError('invalid core VDUP operands')
        bits=8 if w&(1<<22) else 16 if w&32 else 32
        expression=f'({_reg(rt)}&255u)*0x01010101u' if bits==8 else f'({_reg(rt)}&65535u)*0x00010001u' if bits==16 else _reg(rt)
        return cond,'{uint32_t duplicate='+expression+';'+''.join(f'f[{d*2+i}]=duplicate;' for i in range(4 if quad else 2))+'}',[],False
    if w & 0x0fe00fd0 == 0x0c400b10:  # VMOV two core registers <-> Dm
        rt,rt2=(w>>12)&15,(w>>16)&15
        if rt==rt2 or rt in (13,15) or rt2 in (13,15):
            raise ValueError('VFP core pair register operands unsupported')
        lane=((w&15)|((w>>1)&16))*2
        code=(f'{_reg(rt)}=f[{lane}];{_reg(rt2)}=f[{lane+1}];' if w&(1<<20) else
              f'f[{lane}]={_reg(rt)};f[{lane+1}]={_reg(rt2)};')
        return cond,code,[],False
    if w & 0x0e000e00 == 0x0c000a00 and (not w & (1<<24) or w & (1<<21)):
        # VLDM/VSTM IA and DB (including VPOP/VPUSH). D registers are
        # transferred as raw adjacent 32-bit lanes, without host FP conversion.
        pre,add,writeback=bool(w&(1<<24)),bool(w&(1<<23)),bool(w&(1<<21))
        rn=(w>>16)&15;count=w&255;double=bool(w&256)
        start=((((w>>22)&1)*16+((w>>12)&15))*2 if double else
               ((w>>12)&15)*2+((w>>22)&1))
        if pre==add or (pre and not writeback) or rn==15:
            raise ValueError('VFP multiple addressing mode unsupported')
        if not count or (double and (count&1 or count>32)) or start+count>(64 if double else 32):
            raise ValueError('invalid VFP multiple register list')
        length=count*4
        code=f'addr={_reg(rn)}'+(';' if add else f'-{length}u;')
        code+=f'if((addr&3u)||addr<memory_base||addr-memory_base>size||{length}u>size-(addr-memory_base))return -2;'
        for index in range(count):
            pointer=f'mem+(addr-memory_base)+{index*4}u'
            code+=(f'f[{start+index}]=vx_read32({pointer});' if w&(1<<20) else
                   f'vx_write32({pointer},f[{start+index}]);')
        if writeback:code+=f'{_reg(rn)}'+(f'+={length}u;' if add else '=addr;')
        return cond,code,[],False
    sd=((w>>12)&15)*2+((w>>22)&1)
    sn=((w>>16)&15)*2+((w>>7)&1)
    sm=(w&15)*2+((w>>5)&1)
    if w&0x0f200e00==0x0d000a00:  # VLDR/VSTR raw single/double, immediate
        double=bool(w&256);width=8 if double else 4
        if double:sd=(((w>>22)&1)*16+((w>>12)&15))*2
        rn=(w>>16)&15;load=bool(w&(1<<20));offset=(w&255)*4
        if rn==15 and not load:raise ValueError('VFP PC-relative store unsupported')
        base=f'{(pc+(4 if thumb else 8))&~3}u' if rn==15 else _reg(rn)
        code=f'addr={base}{"+" if w&(1<<23) else "-"}{offset}u;if((addr&3u)||addr<memory_base||addr-memory_base>size||{width}u>size-(addr-memory_base))return -2;'
        for i in range(width//4):
            pointer=f'mem+(addr-memory_base)+{i*4}u'
            code+=f'f[{sd+i}]=vx_read32({pointer});' if load else f'vx_write32({pointer},f[{sd+i}]);'
        return cond,code,[],False
    if (w>>8)&15!=10:raise ValueError('VFP double precision arithmetic/SIMD unsupported')
    if w&0x0fff0fff==0x0ef10a10:  # VMRS
        rt=(w>>12)&15
        code='n=fpscr>>31;z=(fpscr>>30)&1;c=(fpscr>>29)&1;v=(fpscr>>28)&1;' if rt==15 else f'{_reg(rt)}=fpscr;'
        return cond,code,[],False
    if w&0x0fe00f7f==0x0e000a10:  # VMOV scalar <-> core register
        rt=(w>>12)&15
        code=f'{_reg(rt)}=f[{sn}];' if w&(1<<20) else f'f[{sn}]={_reg(rt)};'
        return cond,code,[],False
    binary={0x0e300a00:0,0x0e300a40:1,0x0e200a00:2,0x0e800a00:3}
    op=w&0x0fb00f50
    if op in (0x0e000a00,0x0e000a40):  # VMLA/VMLS: two roundings, not FMA
        return cond,(f'{{uint32_t product=vx_fp_binary(f[{sn}],f[{sm}],2,&fpscr);'
                     f'f[{sd}]=vx_fp_binary(f[{sd}],product,{int(bool(w&64))},&fpscr);}}'),[],False
    if op in (0x0e100a00,0x0e100a40):  # VNMLS / VNMLA, separate multiply/add
        # Arm DUI0646C: negate accumulator, then add product (VNMLS) or
        # negated product (VNMLA). Negating the final sum changes signed zero.
        product='product^0x80000000u' if w&64 else 'product'
        return cond,(f'{{uint32_t product=vx_fp_binary(f[{sn}],f[{sm}],2,&fpscr);'
                     f'f[{sd}]=vx_fp_binary(f[{sd}]^0x80000000u,{product},0,&fpscr);}}'),[],False
    if op==0x0e200a40:  # VNMUL
        return cond,f'f[{sd}]=vx_fp_binary(f[{sn}],f[{sm}],2,&fpscr)^0x80000000u;',[],False
    if op in binary:
        return cond,f'f[{sd}]=vx_fp_binary(f[{sn}],f[{sm}],{binary[op]},&fpscr);',[],False
    if w&0x0fb00ff0==0x0eb00a00:  # VMOV immediate, VFPExpandImm
        imm=((w>>12)&0xf0)|(w&15)
        bits=((imm&128)<<24)|((1^((imm>>6)&1))<<30)|((31 if imm&64 else 0)<<25)|((imm&63)<<19)
        return cond,f'f[{sd}]={bits}u;',[],False
    op=w&0x0fbf0fd0
    if op==0x0eb10ac0:
        return cond,f'f[{sd}]=vx_fp_sqrt(f[{sm}],&fpscr);',[],False
    if op in (0x0eb00a40,0x0eb00ac0,0x0eb10a40):
        expression=f'f[{sm}]'+('&0x7fffffffu' if op==0x0eb00ac0 else '^0x80000000u' if op==0x0eb10a40 else '')
        return cond,f'f[{sd}]={expression};',[],False
    if op in (0x0eb80ac0,0x0eb80a40,0x0ebd0ac0,0x0ebc0ac0):
        fromint=op in (0x0eb80ac0,0x0eb80a40)
        signed=op in (0x0eb80ac0,0x0ebd0ac0)
        return cond,f'f[{sd}]=vx_fp_{"fromint" if fromint else "toint"}(f[{sm}],{int(signed)},&fpscr);',[],False
    if op in (0x0eb40a40,0x0eb40ac0,0x0eb50a40,0x0eb50ac0):
        zero=bool(w&(1<<16))
        if zero and w&0x2f:raise ValueError('invalid VFP compare-zero encoding')
        return cond,f'vx_fp_compare(f[{sd}],{"0u" if zero else f"f[{sm}]"},{int(bool(w&128))},&fpscr);',[],False
    raise ValueError('VFP instruction/control mode unsupported')


def _decode_neon_memory(w):
    # VLD1/VST1 contiguous full D registers, default alignment only. Guest
    # little-endian elements preserve the raw D/S lane representation.
    rn=(w>>16)&15;rm=w&15;d=((w>>12)&15)|((w>>18)&16)
    count={7:1,10:2,6:3,2:4}.get((w>>8)&15)
    if count is None or rn==15 or d+count>32 or w&48:
        raise ValueError('NEON structure type/alignment/registers unsupported')
    length=count*8
    code=f'addr={_reg(rn)};'
    if rm!=15:code+=f'uint32_t updated=addr+{str(length)+"u" if rm==13 else _reg(rm)};'
    code+=f'if(addr<memory_base||addr-memory_base>size||{length}u>size-(addr-memory_base))return -2;'
    for i in range(count*2):
        pointer=f'mem+(addr-memory_base)+{i*4}u'
        code+=(f'f[{d*2+i}]=vx_read32({pointer});' if w&(1<<21) else
               f'vx_write32({pointer},f[{d*2+i}]);')
    if rm!=15:code+=f'{_reg(rn)}=updated;'
    return '1',code,[],False


def _decode_neon(w):
    """Bounded raw/integer SIMD and ARM-standard binary32 vector operations."""
    if w & 0xff900f10 == 0xf2000f00:  # VMIN/VMAX.F32 (not minNum/maxNum)
        d=((w>>12)&15)|((w>>18)&16);n=((w>>16)&15)|((w>>3)&16);m=(w&15)|((w>>1)&16);quad=bool(w&64)
        if quad and (d|n|m)&1:raise ValueError('invalid NEON min/max registers')
        count=4 if quad else 2
        values=','.join(f'vx_neon_minmax(f[{n*2+i}],f[{m*2+i}],{(w>>21)&1},&fpscr)' for i in range(count))
        return '1',f'{{uint32_t lanes[{count}]={{{values}}};'+''.join(f'f[{d*2+i}]=lanes[{i}];' for i in range(count))+'}',[],False
    if w & 0xfeb00f50 in (0xf2a00140,0xf2a00540,0xf2a00940):  # F32 by scalar
        d=((w>>12)&15)|((w>>18)&16);n=((w>>16)&15)|((w>>3)&16)
        scalar=(w&15)*2+((w>>5)&1);quad=bool(w&0x01000000)
        if quad and (d|n)&1:raise ValueError('invalid NEON scalar multiply registers')
        count=4 if quad else 2;values=[]
        for i in range(count):
            product=f'vx_neon_binary(f[{n*2+i}],scalar,2u,&fpscr)'
            values.append(product if w&0x800 else f'vx_neon_binary(f[{d*2+i}],{product},{int(bool(w&0x400))}u,&fpscr)')
        code=f'{{uint32_t scalar=f[{scalar}],lanes[{count}]={{{",".join(values)}}};'
        return '1',code+''.join(f'f[{d*2+i}]=lanes[{i}];' for i in range(count))+'}',[],False
    if w & 0xffbf0f90 == 0xf3b90780:  # VNEG.F32 is a raw sign-bit inversion
        d=((w>>12)&15)|((w>>18)&16);m=(w&15)|((w>>1)&16);quad=bool(w&64)
        if quad and (d|m)&1:raise ValueError('invalid NEON negate registers')
        count=4 if quad else 2;values=','.join(f'f[{m*2+i}]^0x80000000u' for i in range(count))
        return '1',f'{{uint32_t lanes[{count}]={{{values}}};'+''.join(f'f[{d*2+i}]=lanes[{i}];' for i in range(count))+'}',[],False
    if w & 0xffb00f10 in (0xf3100110,0xf3200110,0xf3300110):  # VBSL/VBIT/VBIF
        d=((w>>12)&15)|((w>>18)&16);n=((w>>16)&15)|((w>>3)&16);m=(w&15)|((w>>1)&16);quad=bool(w&64)
        if quad and (d|n|m)&1:raise ValueError('invalid NEON select registers')
        count=4 if quad else 2;values=[]
        for i in range(count):
            a,b,c=f'f[{d*2+i}]',f'f[{n*2+i}]',f'f[{m*2+i}]'
            values.append({0xf3100110:f'({b}&{a})|({c}&~{a})',
                           0xf3200110:f'({a}&~{c})|({b}&{c})',
                           0xf3300110:f'({a}&{c})|({b}&~{c})'}[w&0xffb00f10])
        return '1',f'{{uint32_t lanes[{count}]={{{",".join(values)}}};'+''.join(f'f[{d*2+i}]=lanes[{i}];' for i in range(count))+'}',[],False
    if w & 0xffb00010 == 0xf2b00000:  # VEXT.8: byte slice of N:M
        d=((w>>12)&15)|((w>>18)&16);n=((w>>16)&15)|((w>>3)&16);m=(w&15)|((w>>1)&16)
        quad=bool(w&64);count=4 if quad else 2;offset=(w>>8)&15
        if offset>=count*4 or (quad and (d|n|m)&1):raise ValueError('invalid NEON byte extract operands')
        sources=[f'f[{r*2+i}]' for r in (n,m) for i in range(count)]
        values=[]
        for i in range(count):
            word,byte=divmod(offset+i*4,4)
            values.append(sources[word] if not byte else f'({sources[word]}>>{byte*8})|({sources[word+1]}<<{32-byte*8})')
        code=f'{{uint32_t lanes[{count}]={{{",".join(values)}}};'
        return '1',code+''.join(f'f[{d*2+i}]=lanes[{i}];' for i in range(count))+'}',[],False
    if w & 0xff800f10 in (0xf3800410,0xf3800510):  # VSRI/VSLI
        d=((w>>12)&15)|((w>>18)&16);m=(w&15)|((w>>1)&16);quad=bool(w&64)
        imm=((w>>16)&63)|((w>>1)&64)
        if imm<8 or (quad and (d|m)&1):raise ValueError('invalid NEON insert shift')
        bits=1<<(imm.bit_length()-1);left=bool(w&256)
        shift=imm-bits if left else 2*bits-imm;mask=(1<<bits)-1
        keep=(1<<shift)-1 if left else (mask^((1<<(bits-shift))-1))
        elements=(128 if quad else 64)//bits
        def element(reg,index):
            if bits==64:return f'((uint64_t)f[{reg*2+index*2}]|((uint64_t)f[{reg*2+index*2+1}]<<32))'
            return f'(uint64_t)((f[{reg*2+index//(32//bits)}]>>{(index%(32//bits))*bits})&{mask}u)'
        values=[]
        for i in range(elements):
            source='0' if shift==64 else f'({element(m,i)}{"<<" if left else ">>"}{shift})'
            values.append(f'({element(d,i)}&UINT64_C({keep}))|({source}&UINT64_C({mask^keep}))')
        code=f'{{uint64_t elements[{elements}]={{{",".join(values)}}};'
        for i in range(4 if quad else 2):
            value=f'(uint32_t)(elements[{i//2}]>>{32*(i&1)})' if bits==64 else '|'.join(f'((uint32_t)elements[{i*(32//bits)+j}]<<{bits*j})' for j in range(32//bits))
            code+=f'f[{d*2+i}]={value};'
        return '1',code+'}',[],False
    if w & 0xffbf0f90 in (0xf3bb0580,0xf3bb0500):  # VRSQRTE/VRECPE.F32
        d=((w>>12)&15)|((w>>18)&16);m=(w&15)|((w>>1)&16);quad=bool(w&64)
        if quad and (d|m)&1:raise ValueError('invalid NEON estimate registers')
        count=4 if quad else 2
        helper='vx_neon_rsqrte' if w&128 else 'vx_neon_recip'
        values=','.join(f'{helper}(f[{m*2+i}],&fpscr)' for i in range(count))
        return '1',f'{{uint32_t lanes[{count}]={{{values}}};'+''.join(f'f[{d*2+i}]=lanes[{i}];' for i in range(count))+'}',[],False
    if w & 0xffb00f90 == 0xf3b00c00:  # VDUP scalar lane (raw bits)
        d=((w>>12)&15)|((w>>18)&16);m=(w&15)|((w>>1)&16)
        imm=(w>>16)&15;quad=bool(w&64)
        if not imm or imm==8 or (quad and d&1):raise ValueError('invalid NEON scalar duplicate')
        shift=(imm&-imm).bit_length()-1;bits=8<<shift;index=imm>>(shift+1)
        mask=(1<<bits)-1;lane=m*2+(index*bits)//32;offset=(index*bits)%32
        factor=0xffffffff//mask
        code=f'{{uint32_t duplicate=((f[{lane}]>>{offset})&{mask}u)*{factor}u;'
        return '1',code+''.join(f'f[{d*2+i}]=duplicate;' for i in range(4 if quad else 2))+'}',[],False
    fp=w & 0xffb00f10
    if w & 0xff900f10 == 0xf2000d00 or fp in (0xf3000d10,0xf3000d00,0xf2200f10,0xf2000f10,0xf2000d10,0xf2200d10):
        # Standard binary32 arithmetic, nonfused accumulate, and estimate steps.
        d=((w>>12)&15)|((w>>18)&16);n=((w>>16)&15)|((w>>3)&16);m=(w&15)|((w>>1)&16)
        quad=bool(w&64)
        pair=fp==0xf3000d00
        if (quad and (d|n|m)&1) or (pair and quad):raise ValueError('invalid NEON floating-point vector registers')
        count=4 if quad else 2;op=2 if fp==0xf3000d10 else (w>>21)&1
        values=(','.join(f'vx_neon_binary(f[{d*2+i}],vx_neon_binary(f[{n*2+i}],f[{m*2+i}],2u,&fpscr),{(w>>21)&1}u,&fpscr)' for i in range(count)) if fp in (0xf2000d10,0xf2200d10) else
                ','.join(f'{"vx_neon_rsqrt_step" if fp==0xf2200f10 else "vx_neon_recip_step"}(f[{n*2+i}],f[{m*2+i}],&fpscr)' for i in range(count)) if fp in (0xf2200f10,0xf2000f10) else
                ','.join(f'vx_neon_binary(f[{r*2}],f[{r*2+1}],0u,&fpscr)' for r in (n,m)) if pair else
                ','.join(f'vx_neon_binary(f[{n*2+i}],f[{m*2+i}],{op}u,&fpscr)' for i in range(count)))
        code=f'{{uint32_t lanes[{count}]={{{values}}};'
        return '1',code+''.join(f'f[{d*2+i}]=lanes[{i}];' for i in range(count))+'}',[],False
    if w & 0xfeb80090 == 0xf2800010:  # Advanced SIMD modified immediate
        d=((w>>12)&15)|((w>>18)&16);quad=bool(w&64)
        cmode=(w>>8)&15;invert=bool(w&32)
        if quad and d&1:raise ValueError('NEON Q register must have even D encoding')
        imm=((w>>17)&128)|((w>>12)&112)|(w&15)
        logical=cmode<12 and bool(cmode&1)
        if cmode<8:value=imm<<(8*(cmode>>1))
        elif cmode<12:value=(imm<<(8*((cmode>>1)&1)))*0x00010001
        elif cmode==12:value=(imm<<8)|255
        elif cmode==13:value=(imm<<16)|65535
        elif cmode==14:
            value=imm*0x01010101
        else:
            if invert:raise ValueError('reserved NEON modified immediate')
            value=((imm>>7)<<31)|(((~imm>>6)&1)<<30)|((31 if imm&64 else 0)<<25)|((imm&63)<<19)
        wide=value|(value<<32)
        if cmode==14 and invert:
            wide=sum((255 if imm&(1<<i) else 0)<<(8*i) for i in range(8))
        elif invert:wide=(~wide)&0xffffffffffffffff
        code=''
        for i in range(4 if quad else 2):
            lane=(wide>>(32*(i&1)))&0xffffffff
            operation=('&=' if invert else '|=') if logical else '='
            code+=f'f[{d*2+i}]{operation}{lane}u;'
        return '1',code,[],False
    operations={0xf2000110:'&',0xf2200110:'|',0xf3000110:'^'}
    op=w & 0xffb00f10
    integer=op & ~0x00300000 in (0xf2000800,0xf3000800)
    if op not in operations and not integer:raise ValueError('NEON opcode unsupported')
    symbol=('-' if w&0x01000000 else '+') if integer else operations[op]
    bits=8<<((w>>20)&3) if integer else 32
    d=((w>>12)&15)|((w>>18)&16)
    n=((w>>16)&15)|((w>>3)&16)
    m=(w&15)|((w>>1)&16)
    quad=bool(w&64)
    if quad and (d|n|m)&1:raise ValueError('NEON Q register must have even D encoding')
    count=4 if quad else 2
    # Snapshot every source result before writes; preserve D/Q/S aliasing.
    if bits==64:
        code='{'+''.join(
            f'uint64_t wide{i}=(((uint64_t)f[{n*2+i+1}]<<32)|f[{n*2+i}])'
            f'{symbol}(((uint64_t)f[{m*2+i+1}]<<32)|f[{m*2+i}]);'
            for i in range(0,count,2))
        values=','.join(f'(uint32_t)(wide{i//2*2}'+('>>32)' if i&1 else ')') for i in range(count))
    elif bits<32:
        code='{'
        mask=(1<<bits)-1
        values=','.join('|'.join(
            f'((((f[{n*2+i}]>>{shift}){symbol}(f[{m*2+i}]>>{shift}))&{mask}u)<<{shift})'
            for shift in range(0,32,bits)) for i in range(count))
    else:
        code='{'
        values=','.join(f'f[{n*2+i}]{symbol}f[{m*2+i}]' for i in range(count))
    code+=f'uint32_t lanes[{count}]={{{values}}};'
    code+=''.join(f'f[{d*2+i}]=lanes[{i}];' for i in range(count))+'}'
    return '1',code,[],False


def _exclusive_word(rn,rt,rd=None,offset=0,cond='1'):
    code='s->exclusive_valid=0;' if rd is None else ''
    code+=f'addr={_reg(rn)}+{offset}u;'
    code+='if((addr&3u)||addr<memory_base||addr-memory_base>size||4u>size-(addr-memory_base)){s->exclusive_valid=0;return -2;}'
    if rd is None:
        code+=f'{_reg(rt)}=vx_read32(mem+(addr-memory_base));'
        code+='s->exclusive_address=addr;s->exclusive_size=4;s->exclusive_memory=(uintptr_t)mem;s->exclusive_epoch=vx_exclusive_epoch;s->exclusive_valid=1;'
    else:
        code+='if(s->exclusive_valid&&s->exclusive_address==addr&&s->exclusive_size==4&&s->exclusive_memory==(uintptr_t)mem&&s->exclusive_epoch==vx_exclusive_epoch){'
        code+=f'vx_write32(mem+(addr-memory_base),{_reg(rt)});{_reg(rd)}=0;'
        code+=f'}}else {_reg(rd)}=1;s->exclusive_valid=0;'
    return cond,code,[],False


def _decode_arm(w, pc):
    if w>>28!=15 and w & 0x0fff0fff == 0x0e1d0f70:
        rt=(w>>12)&15
        if rt in (13,15):raise ValueError('unsupported TPIDRURO destination')
        return _condition(w>>28),f'{_reg(rt)}=s->tpidruro;',[],False
    if w==0xf57ff01f:return '1','s->exclusive_valid=0;',[],False  # CLREX
    if w>>28!=15 and w & 0x0ff00fff == 0x01900f9f:
        rn,rt=(w>>16)&15,(w>>12)&15
        if 15 in (rn,rt):raise ValueError('invalid ARM LDREX operands')
        return _exclusive_word(rn,rt,cond=_condition(w>>28))
    if w>>28!=15 and w & 0x0ff00ff0 == 0x01800f90:
        rn,rd,rt=(w>>16)&15,(w>>12)&15,w&15
        if 15 in (rn,rd,rt) or rd in (rn,rt):raise ValueError('invalid ARM STREX operands')
        return _exclusive_word(rn,rt,rd,cond=_condition(w>>28))
    if w & 0x0f8000f0 == 0x01800090:
        raise ValueError('ARM exclusive variant unsupported (word LDREX/STREX only)')
    if w & 0xff900000 == 0xf4000000:return _decode_neon_memory(w)
    if w & 0xfe000000 == 0xf2000000:
        return _decode_neon(w)
    if w & 0xfe000000 == 0xfa000000:  # BLX immediate ARM -> Thumb
        offset=(_sx(w&0xffffff,24)<<2)|((w>>23)&2)
        target=((pc+8+offset)&0xffffffff)|1
        return '1',f'r[14]={pc+4}u;pc={target}u;goto dispatch;',[target],True
    cond = _condition(w >> 28)
    if cond is None:
        raise ValueError('unconditional extension unsupported')
    if w&0x0c000000==0x0c000000 and (w>>8)&15 in (10,11):
        return _decode_vfp(w,pc,cond)
    if w & 0x0e000090 == 0x00000090 and (w>>5)&3:
        # Halfword and signed byte/halfword transfers. Doubleword and
        # unprivileged variants remain explicit blockers.
        kind=(w>>5)&3;load=bool(w&(1<<20));rn=(w>>16)&15;rt=(w>>12)&15
        pre=bool(w&(1<<24));writeback=not pre or bool(w&(1<<21));immediate=bool(w&(1<<22))
        if (not load and kind!=1) or (not pre and w&(1<<21)) or rt==15 or (writeback and (rn==15 or rn==rt)):
            raise ValueError('ARM extra memory doubleword/unprivileged/operand unsupported')
        if rn==15 and not load:raise ValueError('ARM extra PC-relative store unsupported')
        if not immediate and w&0xf00:raise ValueError('invalid ARM extra memory register offset')
        base=f'{pc+8}u' if rn==15 else _reg(rn)
        offset=f'{((w>>4)&240)|(w&15)}u' if immediate else _reg(w&15)
        code=f'uint32_t updated={base}{"+" if w&(1<<23) else "-"}{offset};addr={"updated" if pre else base};'
        width=1 if kind==2 else 2
        code+=f'if(addr<memory_base||addr-memory_base>size||{width}u>size-(addr-memory_base))return -2;'
        if load:
            value='mem[addr-memory_base]'+('|((uint32_t)mem[addr-memory_base+1]<<8)' if width==2 else '')
            if kind>1:value=f'(uint32_t)(int32_t)(int{width*8}_t)({value})'
            code+=f'{_reg(rt)}={value};'
        else:code+=f'mem[addr-memory_base]=(uint8_t){_reg(rt)};mem[addr-memory_base+1]=(uint8_t)({_reg(rt)}>>8);'
        if writeback:code+=f'{_reg(rn)}=updated;'
        return cond,code,[],False
    if w & 0x0fffffff == 0x0320f000:  # architectural NOP
        return cond, '', [], False
    next_pc = pc + 4
    if w & 0x0ffffff0 in (0x012fff10, 0x012fff30):  # BX / BLX register
        rm = w & 15
        link = bool(w & 0x20)
        if link and rm==15:raise ValueError('invalid ARM BLX PC operand')
        source=f'{(pc+8)&0xffffffff}u' if rm==15 else _reg(rm)
        code = f'pc={source};' + (f'r[14]={next_pc}u;' if link else '')
        return cond, code + 'goto dispatch;', [], link
    if w & 0x0e000000 == 0x0a000000:
        target = (pc + 8 + (_sx(w & 0xffffff, 24) << 2)) & 0xffffffff
        link = bool(w & 0x01000000)
        return cond, ('r[14]=%du;' % next_pc if link else '') + f'pc={target}u;goto dispatch;', [target], link
    if w & 0x0fff0000 in (0x092d0000, 0x08bd0000):  # PUSH/POP (SP writeback)
        load = bool(w & (1 << 20))
        regs = [i for i in range(16) if w & (1 << i)]
        if not regs or 13 in regs or (15 in regs and not load):
            raise ValueError('unsupported stack register list')
        count = len(regs) * 4
        code = f'addr=r[13]{"" if load else "-"+str(count)+"u"};'
        code += f'if(addr<memory_base||addr-memory_base>size||{count}u>size-(addr-memory_base))return -2;'
        for index, reg in enumerate(regs):
            offset = index * 4
            code += (f'{"pc" if reg == 15 else _reg(reg)}=vx_read32(mem+(addr-memory_base)+{offset});' if load
                     else f'vx_write32(mem+(addr-memory_base)+{offset},{_reg(reg)});')
        code += f'r[13]{"+=" if load else "-="}{count}u;'
        if 15 in regs:
            code += 'goto dispatch;'
        return cond, code, [], False
    if w & 0x0e000000 == 0x08000000:
        # General ARM LDM/STM. User-bank/SPSR and PC lists remain unsupported.
        load=bool(w&(1<<20));writeback=bool(w&(1<<21));up=bool(w&(1<<23));pre=bool(w&(1<<24))
        rn=(w>>16)&15;regs=[i for i in range(16) if w&(1<<i)]
        if w&(1<<22) or rn==15 or not regs or 15 in regs or (writeback and rn in regs):
            raise ValueError('ARM multiple transfer user/PC/base-alias register list unsupported')
        count=len(regs)*4
        offset=(4 if pre else 0) if up else (-count if pre else 4-count)
        code=f'uint32_t original={_reg(rn)};int64_t first=(int64_t)(uint64_t)original+({offset});'
        code+=f'if(first<0||first>UINT32_MAX)return -2;addr=(uint32_t)first;'
        code+=f'if((addr&3u)||addr<memory_base||addr-memory_base>size||{count}u>size-(addr-memory_base))return -2;'
        for i,reg in enumerate(regs):
            code+=(f'{_reg(reg)}=vx_read32(mem+(addr-memory_base)+{i*4});' if load else f'vx_write32(mem+(addr-memory_base)+{i*4},{_reg(reg)});')
        if writeback:code+=f'{_reg(rn)}=original{"+" if up else "-"}{count}u;'
        return cond,code,[],False
    if w & 0x0ff00000 in (0x03000000, 0x03400000):  # MOVW/MOVT
        rd = (w >> 12) & 15
        imm = ((w >> 4) & 0xf000) | (w & 0xfff)
        value = f'({_reg(rd)}&65535u)|{imm << 16}u' if w & (1 << 22) else f'{imm}u'
        return cond, f'{_reg(rd)}={value};', [], False
    if w & 0x0fe00070 == 0x07c00010:  # BFI / BFC (ARMv7)
        rd, rm = (w >> 12) & 15, w & 15
        low, high = (w >> 7) & 31, (w >> 16) & 31
        if high < low:
            raise ValueError('invalid ARM bitfield extent')
        mask = (((1 << (high-low+1))-1) << low) & 0xffffffff
        source = '0u' if rm == 15 else _reg(rm)
        return cond, f'{_reg(rd)}=({_reg(rd)}&{(~mask)&0xffffffff}u)|(({source}<<{low})&{mask}u);', [], False
    if w & 0x0fff03f0 in (0x06af0070,0x06bf0070,0x06ef0070,0x06ff0070):
        # ARMv6/7 SXTB/SXTH/UXTB/UXTH, optional byte-multiple ROR.
        rd,rm=(w>>12)&15,w&15
        source=_reg(rm);destination=_reg(rd)
        rotation=((w>>10)&3)*8
        if rotation:source=f'(({source}>>{rotation})|({source}<<{32-rotation}))'
        width=16 if w&(1<<20) else 8
        value=f'(uint{width}_t)({source})'
        if not w&(1<<22):value=f'(uint32_t)(int32_t)(int{width}_t)({value})'
        return cond,f'{destination}={value};',[],False
    if w & 0x0fc000f0 == 0x00000090:  # MUL / MLA
        rd,rn,rs,rm=(w>>16)&15,(w>>12)&15,(w>>8)&15,w&15
        accumulate=bool(w&(1<<21))
        if not accumulate and rn:raise ValueError('invalid ARM multiply accumulator')
        expression=f'{_reg(rm)}*{_reg(rs)}'+(f'+{_reg(rn)}' if accumulate else '')
        code=f'{_reg(rd)}={expression};'
        if w&(1<<20):code+=f'n={_reg(rd)}>>31;z={_reg(rd)}==0;'
        return cond,code,[],False
    if w & 0x0c000000 == 0x04000000:
        # Immediate or shifted-register pre/post-index word/byte accesses.
        pre=bool(w&(1<<24));writeback=not pre or bool(w&(1<<21))
        if (not pre and w&(1<<21)):
            raise ValueError('unprivileged memory operation unsupported')
        register_offset=bool(w&(1<<25))
        if register_offset and w&16:
            raise ValueError('register-shifted memory offset unsupported')
        rn, rd, off = (w >> 16) & 15, (w >> 12) & 15, w & 4095
        if rn == 15 and not w & (1 << 20):
            raise ValueError('PC-relative store unsupported')
        if writeback and (rn==15 or rn==rd):
            raise ValueError('unpredictable ARM memory writeback operands')
        base = f'{(pc + 8) & 0xffffffff}u' if rn == 15 else _reg(rn)
        offset=(f'(uint32_t)vx_shift({_reg(w&15)},{(w>>5)&3}u,{(w>>7)&31}u,c,0)'
                if register_offset else f'{off}u')
        a = f'({base} {"+" if w & (1 << 23) else "-"} {offset})'
        byte = bool(w & (1 << 22))
        width = 1 if byte else 4
        code = f'uint32_t adjusted={a};addr={"adjusted" if pre else base};if(addr<memory_base||addr-memory_base>size||{width}u>size-(addr-memory_base))return -2;'
        if rd==15:
            if byte or not w&(1<<20):
                raise ValueError('ARM byte/store PC operand unsupported')
            code+='if(addr&3u)return -2;pc=vx_read32(mem+(addr-memory_base));'
            if writeback:code+=f'{_reg(rn)}=adjusted;'
            return cond,code+'goto dispatch;',[],False
        if w & (1 << 20):
            code += f'{_reg(rd)}=mem[addr-memory_base];' if byte else f'{_reg(rd)}=vx_read32(mem+(addr-memory_base));'
        else:
            code += f'mem[addr-memory_base]=(uint8_t){_reg(rd)};' if byte else f'vx_write32(mem+(addr-memory_base),{_reg(rd)});'
        if writeback:code+=f'{_reg(rn)}=adjusted;'
        return cond, code, [], False
    if w & 0x0c000000 == 0:
        opcode, s, rn, rd = (w >> 21) & 15, bool(w & (1 << 20)), (w >> 16) & 15, (w >> 12) & 15
        if not w&(1<<25) and w&16 and (rd==15 or w&15==15 or (w>>8)&15==15 or (rn==15 and opcode not in (13,15))):
            raise ValueError('unpredictable PC operand in register-controlled shift')
        operand=_arm_operand(w,pc);b='operand'
        if rn==15 and opcode in (2,4) and not s:
            # ADR reads the architectural ARM PC, independent of r[15].
            a=f'{(pc+8)&0xffffffff}u'
        else:
            a = _reg(rn) if opcode not in (13,15) else '0u'
        if rd==15 and opcode not in (8,9,10,11):
            if s or opcode not in (0,1,2,3,4,12,13,14,15):
                raise ValueError('ARM exception return/PC arithmetic unsupported')
            expressions={0:f'{a}&{b}',1:f'{a}^{b}',2:f'{a}-{b}',3:f'{b}-{a}',
                         4:f'{a}+{b}',12:f'{a}|{b}',13:b,14:f'{a}&~{b}',15:f'~{b}'}
            return cond,operand+f'pc={expressions[opcode]};goto dispatch;',[],False
        if opcode in (8,9,10,11) and (not s or rd):
            raise ValueError('ARM test/compare encoding unsupported')
        if opcode in (10,11):  # CMP / CMN
            return cond,operand+_flags(a,b,opcode==10),[],False
        if opcode in (5,6,7):
            code=_carry_arithmetic(b,a,_reg(rd),True,s) if opcode==7 else _carry_arithmetic(a,b,_reg(rd),opcode==6,s)
            return cond,operand+code,[],False
        expressions={0:f'{a}&{b}',1:f'{a}^{b}',2:f'{a}-{b}',3:f'{b}-{a}',
                     4:f'{a}+{b}',8:f'{a}&{b}',9:f'{a}^{b}',12:f'{a}|{b}',
                     13:b,14:f'{a}&~{b}',15:f'~{b}'}
        if opcode not in expressions:
            raise ValueError('ARM arithmetic opcode/flag mode unsupported')
        if opcode in (2,3,4):
            flags=(_flags(b,a,True) if opcode==3 else _flags(a,b,opcode==2)) if s else ''
            code=flags+f'{_reg(rd)}={expressions[opcode]};'
        else:
            code=f'uint32_t result={expressions[opcode]};'
            if s:code+='n=result>>31;z=result==0;c=shift_c;'
            if opcode not in (8,9):code+=f'{_reg(rd)}=result;'
        return cond,operand+code,[],False
    raise ValueError('ARM opcode unsupported')


def _decode_thumb32(w, pc):
    """Bounded Thumb-2 integer forms; first halfword is in low bits."""
    first, second = w & 0xffff, w >> 16
    if first==0xee1d and second & 0x0fff == 0x0f70:
        rt=second>>12
        if rt in (13,15):raise ValueError('unsupported TPIDRURO destination')
        return '1',f'{_reg(rt)}=s->tpidruro;',[],False
    if w==0x8f2ff3bf:return '1','s->exclusive_valid=0;',[],False  # CLREX
    if first & 0xfff0 == 0xe850 and second & 0x0f00 == 0x0f00:
        rn,rt=first&15,second>>12
        if rn==15 or rt in (13,15):raise ValueError('invalid Thumb LDREX operands')
        return _exclusive_word(rn,rt,offset=(second&255)*4)
    if first & 0xfff0 == 0xe840:
        rn,rt,rd=first&15,second>>12,(second>>8)&15
        if rn==15 or rt in (13,15) or rd in (13,15,rn,rt):raise ValueError('invalid Thumb STREX operands')
        return _exclusive_word(rn,rt,rd,(second&255)*4)
    if first & 0xfff0 in (0xe8c0,0xe8d0) and second & 0x00f0 in (0x40,0x50,0x70):
        raise ValueError('Thumb exclusive variant unsupported (word LDREX/STREX only)')
    if first & 0xff90 == 0xf900:
        return _decode_neon_memory(0xf4000000|((first&255)<<16)|second)
    if first & 0xfff0 == 0xfab0 and second & 0xf0f0 == 0xf080:
        rm,rd=first&15,(second>>8)&15
        if second&15 != rm or rm in (13,15) or rd in (13,15):
            raise ValueError('invalid Thumb CLZ operands')
        return '1',f'{_reg(rd)}={_reg(rm)}?(uint32_t)__builtin_clz({_reg(rm)}):32u;',[],False
    if first & 0xffc0 == 0xe880:  # STMIA/LDMIA, optional writeback
        rn=first&15;load=bool(first&16);wb=bool(first&32)
        regs=[i for i in range(16) if second&(1<<i)]
        if rn==15 or len(regs)<2 or second&(1<<13) or (wb and rn in regs) or (not load and second&(1<<15)) or (load and second&0xc000==0xc000):
            raise ValueError('invalid Thumb multiple-register operands')
        length=4*len(regs);code=f'addr={_reg(rn)};'
        code+=f'if((addr&3u)||addr<memory_base||addr-memory_base>size||{length}u>size-(addr-memory_base))return -2;'
        for i,reg in enumerate(regs):
            code+=(f'{"pc" if reg==15 else _reg(reg)}=vx_read32(mem+(addr-memory_base)+{4*i}u);' if load else f'vx_write32(mem+(addr-memory_base)+{4*i}u,{_reg(reg)});')
        if wb:code+=f'{_reg(rn)}=addr+{length}u;'
        if load and second&(1<<15):code+='goto dispatch;'
        return '1',code,[],False
    if first & 0xffe0 == 0xe9c0:  # STRD/LDRD positive immediate, no writeback
        rn,rt,rt2=first&15,second>>12,(second>>8)&15
        if rn==15 or rt in (13,15) or rt2 in (13,15) or (first&16 and rt==rt2):raise ValueError('invalid Thumb dual transfer operands')
        code=f'addr={_reg(rn)}+{(second&255)*4}u;'
        code+='if((addr&3u)||addr<memory_base||addr-memory_base>size||8u>size-(addr-memory_base))return -2;'
        if not first&16:
            code+='\n#ifdef vx_write32\nif(!vn_guest_write_allowed(mem+(addr-memory_base),8))return -2;\n#endif\n'
        for i,reg in enumerate((rt,rt2)):
            code+=(f'{_reg(reg)}=vx_read32(mem+(addr-memory_base)+{i*4}u);' if first&16 else f'vx_write32(mem+(addr-memory_base)+{i*4}u,{_reg(reg)});')
        return '1',code,[],False
    if first & 0xfff0 in (0xf340,0xf3c0) and not second&0x8020:  # SBFX/UBFX
        rn,rd=first&15,(second>>8)&15;lsb=(((second>>12)&7)<<2)|((second>>6)&3);width=(second&31)+1
        if rn in (13,15) or rd in (13,15) or lsb+width>32:raise ValueError('invalid Thumb extraction operands')
        value=f'(({_reg(rn)}>>{lsb})&{(1<<width)-1}u)'
        if first&0xfff0==0xf340:value=f'(({value}^{1<<(width-1)}u)-{1<<(width-1)}u)'
        return '1',f'{_reg(rd)}={value};',[],False
    if first & 0xfff0 == 0xf360 and not second & 0x8020:  # BFI / BFC
        rn,rd=first&15,(second>>8)&15
        lsb=(((second>>12)&7)<<2)|((second>>6)&3);msb=second&31
        if rd in (13,15) or rn==13 or msb<lsb:raise ValueError('invalid Thumb bitfield operands')
        mask=((1<<(msb-lsb+1))-1)<<lsb
        source='0u' if rn==15 else _reg(rn)
        return '1',f'{_reg(rd)}=({_reg(rd)}&{(~mask)&0xffffffff}u)|(({source}<<{lsb})&{mask}u);',[],False
    if first in (0xe92d,0xe8bd):  # PUSH.W / POP.W, checked full transfer
        if second & (1 << 13) or second.bit_count()<2 or (first==0xe92d and second & (1<<15)) or (first==0xe8bd and second & 0xc000==0xc000):
            raise ValueError('invalid Thumb-2 PUSH/POP register mask')
        regs=[i for i in range(16) if second & (1<<i)]
        length=4*len(regs)
        code=f'addr=r[13]-{length}u;' if first==0xe92d else 'addr=r[13];'
        code+=f'if((addr&3u)||addr<memory_base||addr-memory_base>size||{length}u>size-(addr-memory_base))return -2;'
        for i,reg in enumerate(regs):
            if first==0xe92d:code+=f'vx_write32(mem+(addr-memory_base)+{4*i}u,r[{reg}]);'
            else:code+=f'{"pc" if reg==15 else _reg(reg)}=vx_read32(mem+(addr-memory_base)+{4*i}u);'
        code+=f'r[13]={"addr" if first==0xe92d else f"addr+{length}u"};'
        if second&(1<<15):code+='goto dispatch;'
        return '1',code,[],False
    if first & 0xfff0 in (0xf910,0xf930) and not second&0x0fc0:  # Signed register-offset load
        rn,rt,rm=first&15,second>>12,second&15
        if rn==15 or rt in (13,15) or rm in (13,15):raise ValueError('invalid signed indexed load operands')
        width=1 if first&0xfff0==0xf910 else 2
        code=f'addr={_reg(rn)}+({_reg(rm)}<<{(second>>4)&3});'
        code+=f'if(addr<memory_base||addr-memory_base>size||{width}u>size-(addr-memory_base))return -2;'
        value='mem[addr-memory_base]' if width==1 else '(mem[addr-memory_base]|((uint32_t)mem[addr-memory_base+1]<<8))'
        return '1',code+f'{_reg(rt)}=(uint32_t)(int32_t)(int{width*8}_t){value};',[],False
    if first & 0xfff0 in (0xf990,0xf9b0):  # LDRSB/LDRSH immediate
        rn,rt=first&15,second>>12
        if rn==15 or rt in (13,15):raise ValueError('Thumb signed-load SP/PC unsupported')
        width=1 if first&0xfff0==0xf990 else 2
        code=f'addr={_reg(rn)}+{second&4095}u;'
        code+=f'if(addr<memory_base||addr-memory_base>size||{width}u>size-(addr-memory_base))return -2;'
        value='(int8_t)mem[addr-memory_base]' if width==1 else '(int16_t)(mem[addr-memory_base]|((uint16_t)mem[addr-memory_base+1]<<8))'
        return '1',code+f'{_reg(rt)}=(uint32_t)(int32_t){value};',[],False
    if first & 0xfff0 == 0xe8d0 and second & 0xffe0 == 0xf000:
        rn, rm = first & 15, second & 15
        if rn == 13 or rm in (13,15):
            raise ValueError('invalid Thumb table branch operands')
        half = bool(second & 16)
        base = f'{(pc+4)&0xffffffff}u' if rn == 15 else _reg(rn)
        code = f'addr={base}+({_reg(rm)}<<{int(half)});'
        width = 2 if half else 1
        code += f'if(addr<memory_base||addr-memory_base>size||{width}u>size-(addr-memory_base))return -2;'
        value = 'mem[addr-memory_base]' + ('|((uint32_t)mem[addr-memory_base+1]<<8)' if half else '')
        code += f'uint32_t offset={value};pc=({(pc+4)&0xffffffff}u+2u*offset)|1u;goto dispatch;'
        return '1',code,[],False
    if first & 0xef00 == 0xef00:
        raw=(first<<16)|second
        return _decode_neon(0xf2000000|(raw&0x00ffffff)|((raw&0x10000000)>>4))
    if first & 0xfa00 == 0xf000 and not second & 0x8000:
        # Thumb modified immediate logical and ADD/SUB forms.
        op=(first>>5)&15;rn=first&15;rd=(second>>8)&15;flags=bool(first&16)
        imm=(((first>>10)&1)<<11)|(((second>>12)&7)<<8)|(second&255)
        sp_adjust=rn==13 and op in (8,13) and not flags
        if op not in (0,1,2,3,4,8,13,14) or (rn==13 and not sp_adjust) or (rn==15 and op not in (2,3)) or (rd==13 and not sp_adjust):
            raise ValueError('Thumb-2 modified immediate operand/opcode unsupported')
        compare=rd==15 and flags and op in (0,4,8,13)
        if rd==15 and not compare:raise ValueError('Thumb-2 immediate PC destination unsupported')
        if imm>>10==0:
            byte=imm&255;mode=(imm>>8)&3
            if mode and not byte:raise ValueError('invalid Thumb expanded immediate')
            value=(byte,byte|(byte<<16),(byte<<8)|(byte<<24),byte*0x01010101)[mode]
            carry='c'
        else:
            base=128|(imm&127);rotate=imm>>7
            value=((base>>rotate)|(base<<(32-rotate)))&0xffffffff;carry=str(value>>31)
        a='0u' if rn==15 else _reg(rn);b=f'{value}u'
        if op in (8,13,14):
            if op==14:a,b=b,a  # RSB: immediate minus register, including flags.
            code=_flags(a,b,op in (13,14)) if flags else ''
            if not compare:code+=f'{_reg(rd)}={a}{"-" if op in (13,14) else "+"}{b};'
        else:
            expression={0:f'{a}&{b}',1:f'{a}&~{b}',2:f'{a}|{b}',3:f'{a}|~{b}',4:f'{a}^{b}'}[op]
            code=f'uint32_t result={expression};'
            if flags:code+=f'n=result>>31;z=result==0;c={carry};'
            if not compare:code+=f'{_reg(rd)}=result;'
        return '1',code,[],False
    if first in (0xfa0f,0xfa1f,0xfa4f,0xfa5f) and second&0xf0c0==0xf080:  # Rotated extension
        rd,rm=(second>>8)&15,second&15
        if rd in (13,15) or rm in (13,15):raise ValueError('invalid Thumb extension operands')
        rotation=((second>>4)&3)*8
        source=_reg(rm) if not rotation else f'({_reg(rm)}>>{rotation})|({_reg(rm)}<<{32-rotation})'
        cast={0xfa0f:'(uint32_t)(int32_t)(int16_t)',0xfa1f:'(uint32_t)(uint16_t)',0xfa4f:'(uint32_t)(int32_t)(int8_t)',0xfa5f:'(uint32_t)(uint8_t)'}[first]
        return '1',f'{_reg(rd)}={cast}({source});',[],False
    if first & 0xfff0 in (0xfb80,0xfba0) and not second&0x00f0:  # SMULL/UMULL
        rn,rm,lo,hi=first&15,second&15,second>>12,(second>>8)&15
        if any(r in (13,15) for r in (rn,rm,lo,hi)) or lo==hi:raise ValueError('invalid Thumb long multiply operands')
        cast='(int64_t)(int32_t)' if first&0xfff0==0xfb80 else '(uint64_t)'
        return '1',f'{{uint64_t product={cast}{_reg(rn)}*{cast}{_reg(rm)};{_reg(lo)}=(uint32_t)product;{_reg(hi)}=(uint32_t)(product>>32);}}',[],False
    if first & 0xffe0 in (0xeb40,0xeb60,0xebc0) and not second&0x8000:
        rn,rd,rm=first&15,(second>>8)&15,second&15
        if any(r in (13,15) for r in (rn,rd,rm)):raise ValueError('invalid Thumb carry arithmetic operands')
        amount=(((second>>12)&7)<<2)|((second>>6)&3)
        code=f'uint32_t operand=(uint32_t)vx_shift({_reg(rm)},{(second>>4)&3}u,{amount}u,c,0);'
        if first&0xffe0==0xebc0:
            if first&16:code+=_flags('operand',_reg(rn),True)
            code+=f'{_reg(rd)}=operand-{_reg(rn)};'
        else:
            body=_carry_arithmetic(_reg(rn),'operand',_reg(rd),bool(first&32))
            if not first&16:body='{uint32_t old_n=n,old_z=z,old_c=c,old_v=v;'+body+'n=old_n;z=old_z;c=old_c;v=old_v;}'
            code+=body
        return '1',code,[],False
    if first & 0xffe0 in (0xeb00,0xeba0) and not second & 0x8000:
        rn,rd,rm=first&15,(second>>8)&15,second&15
        amount=(((second>>12)&7)<<2)|((second>>6)&3)
        if rn==15 or rd in (13,15) or rm in (13,15) or (rn==13 and (first!=0xeb0d or second&0x30 or amount>3)):
            raise ValueError('Thumb-2 shifted arithmetic SP/PC/alias unsupported')
        subtract=bool(first&0x80)
        code=(f'uint64_t shifted=vx_shift({_reg(rm)},{(second>>4)&3}u,{amount}u,c,0);'
              'uint32_t operand=(uint32_t)shifted;')
        if first&16:code+=_flags(_reg(rn),'operand',subtract)
        code+=f'{_reg(rd)}={_reg(rn)}{"-" if subtract else "+"}operand;'
        return '1',code,[],False
    if first in (0xf8df,0xf85f):  # LDR literal, aligned PC base
        rt=second>>12
        base=(pc+4)&~3
        code=f'addr={base}u{"+" if first&0x80 else "-"}{second&4095}u;'
        code+='if(addr<memory_base||addr-memory_base>size||4u>size-(addr-memory_base))return -2;'
        if rt==15:
            return '1',code+'if(addr&3u)return -2;pc=vx_read32(mem+(addr-memory_base));goto dispatch;',[],False
        return '1',code+f'{_reg(rt)}=vx_read32(mem+(addr-memory_base));',[],False
    if first & 0xffe0 in (0xf800,0xf820,0xf840) and second & 0x0fc0 == 0:
        rn, rt, rm = first & 15, second >> 12, second & 15
        width = {0xf800:1,0xf820:2,0xf840:4}[first & 0xffe0]
        load = bool(first & 16)
        if rn == 15 or rm in (13,15) or (rt == 15 and (not load or width != 4)):
            raise ValueError('invalid Thumb register-offset memory operands')
        code=f'addr={_reg(rn)}+({_reg(rm)}<<{(second>>4)&3});'
        code+=f'if(addr<memory_base||addr-memory_base>size||{width}u>size-(addr-memory_base))return -2;'
        if rt == 15:
            return '1',code+'if(addr&3u)return -2;pc=vx_read32(mem+(addr-memory_base));goto dispatch;',[],False
        if load:
            value = 'vx_read32(mem+(addr-memory_base))' if width == 4 else 'mem[addr-memory_base]'
            if width == 2:value+='|((uint32_t)mem[addr-memory_base+1]<<8)'
            code+=f'{_reg(rt)}={value};'
        else:
            code+=''.join(f'mem[addr-memory_base+{i}]=(uint8_t)({_reg(rt)}>>{8*i});' for i in range(width))
        return '1',code,[],False
    if first & 0xffe0 in (0xf800,0xf820,0xf840,0xf900,0xf920) and second & 0x0800 == 0x0800:
        # Word LDR/STR immediate with explicit pre/post-index writeback.
        rn,rt=first&15,(second>>12)&15
        wb=bool(second&0x100)
        if rn==15 or rt in (13,15) or (wb and rn==rt) or not second&0x500 or second&0x700==0x600 or (first&0xff80==0xf900 and not first&16):
            raise ValueError('Thumb-2 indexed memory base/destination unsupported')
        width={0xf800:1,0xf820:2,0xf840:4,0xf900:1,0xf920:2}[first&0xffe0]
        delta=second&255;pre=bool(second&0x400);add=bool(second&0x200)
        code=f'uint32_t updated={_reg(rn)}{"+" if add else "-"}{delta}u;'
        code+=f'addr={"updated" if pre else _reg(rn)};'
        code+=f'if(addr<memory_base||addr-memory_base>size||{width}u>size-(addr-memory_base))return -2;'
        if first&16:
            value='vx_read32(mem+(addr-memory_base))' if width==4 else 'mem[addr-memory_base]'
            if width==2:value='('+value+'|((uint32_t)mem[addr-memory_base+1]<<8))'
            if first&0xff80==0xf900:value=f'(uint32_t)(int32_t)(int{width*8}_t)({value})'
            code+=f'{_reg(rt)}={value};'
        else:code+=''.join(f'mem[addr-memory_base+{i}]=(uint8_t)({_reg(rt)}>>{8*i});' for i in range(width))
        return '1',code+(f'{_reg(rn)}=updated;' if wb else ''),[],False
    if first&0xff00 in (0xec00,0xed00,0xee00) and (second>>8)&15 in (10,11):
        return _decode_vfp((first<<16)|second,pc,'1',thumb=True)
    if first & 0xfff0 == 0xf890 and second>>12==15:  # PLD immediate: non-faulting memory hint
        return '1',';',[],False
    if first & 0xffe0 in (0xf880,0xf8a0,0xf8c0):  # unsigned byte/half/word imm12
        rn,rd=first&15,(second>>12)&15
        if rn==15 or (rd==15 and (first&0xffe0!=0xf8c0 or not first&16)):
            raise ValueError('Thumb-2 memory PC form unsupported')
        width={0xf880:1,0xf8a0:2,0xf8c0:4}[first&0xffe0]
        code=f'addr={_reg(rn)}+{second&4095}u;if(addr<memory_base||addr-memory_base>size||{width}u>size-(addr-memory_base))return -2;'
        if width==4 and rd==15:
            return '1',code+'if(addr&3u)return -2;pc=vx_read32(mem+(addr-memory_base));goto dispatch;',[],False
        if width==4:
            code+=f'{_reg(rd)}=vx_read32(mem+(addr-memory_base));' if first&0x10 else f'vx_write32(mem+(addr-memory_base),{_reg(rd)});'
        elif first&0x10:
            code+=f'{_reg(rd)}=mem[addr-memory_base]'+('|((uint32_t)mem[addr-memory_base+1]<<8)' if width==2 else '')+';'
        else:
            code+=f'mem[addr-memory_base]=(uint8_t){_reg(rd)};'
            if width==2:code+=f'mem[addr-memory_base+1]=(uint8_t)({_reg(rd)}>>8);'
        return '1',code,[],False
    if first & 0xff80 == 0xfa00 and second & 0xf0f0 == 0xf000:
        rn,rd,rm=first&15,(second>>8)&15,second&15
        if any(r in (13,15) for r in (rn,rd,rm)):
            raise ValueError('Thumb-2 shift SP/PC operand unsupported')
        code=(f'uint64_t shifted=vx_shift({_reg(rn)},{(first>>5)&3}u,{_reg(rm)}&255u,c,1);'
              f'{_reg(rd)}=(uint32_t)shifted;')
        if first&16:code+=f'c=(uint32_t)(shifted>>32);n={_reg(rd)}>>31;z={_reg(rd)}==0;'
        return '1',code,[],False
    if first & 0xffe0 in (0xea00,0xea20,0xea40,0xea60,0xea80) and not second&0x8000:
        rn,rd,rm=first&15,(second>>8)&15,second&15;op=(first>>5)&15
        test=rd==15 and bool(first&16) and op in (0,4)
        # Rn=1111 selects MOV (ORR) / MVN (ORN), including immediate
        # shift and RRX aliases. It is not an architectural PC read.
        move=rn==15 and op in (2,3)
        if (rn in (13,15) and not move) or rm in (13,15) or rd==13 or (rd==15 and not test):
            raise ValueError('Thumb-2 logical SP/PC/alias form unsupported')
        amount=(((second>>12)&7)<<2)|((second>>6)&3)
        a='0u' if move else _reg(rn);b='operand'
        expression={0:f'{a}&{b}',1:f'{a}&~{b}',2:f'{a}|{b}',3:f'{a}|~{b}',4:f'{a}^{b}'}[op]
        code=(f'uint64_t shifted=vx_shift({_reg(rm)},{(second>>4)&3}u,{amount}u,c,0);'
              f'uint32_t operand=(uint32_t)shifted,result={expression};')
        if first&16:code+='c=(uint32_t)(shifted>>32);n=result>>31;z=result==0;'
        if not test:code+=f'{_reg(rd)}=result;'
        return '1',code,[],False
    if first & 0xfff0 == 0xfb00 and second & 0x00f0 == 0:
        rn,rd,rm,ra=first&15,(second>>8)&15,second&15,second>>12
        if any(r in (13,15) for r in (rn,rd,rm)) or ra==13:
            raise ValueError('Thumb-2 multiply SP/PC operand unsupported')
        return '1',f'{_reg(rd)}={_reg(rn)}*{_reg(rm)}'+(f'+{_reg(ra)}' if ra!=15 else '')+';',[],False
    if first & 0xfbf0 in (0xf240, 0xf2c0) and not second & 0x8000:
        rd = (second >> 8) & 15
        if rd in (13, 15):
            raise ValueError('Thumb MOVW/MOVT SP/PC destination unsupported')
        imm = ((first & 15) << 12) | (((first >> 10) & 1) << 11) | (((second >> 12) & 7) << 8) | (second & 255)
        value = f'({_reg(rd)}&65535u)|{imm << 16}u' if first & 0x80 else f'{imm}u'
        return '1', f'{_reg(rd)}={value};', [], False
    if first & 0xf800 == 0xf000 and second & 0xd000 == 0x8000:  # B<c>.W T3
        condition=(first>>6)&15
        if condition>=14:raise ValueError('reserved Thumb-2 conditional branch')
        offset=(((first>>10)&1)<<20)|(((second>>11)&1)<<19)|(((second>>13)&1)<<18)|((first&63)<<12)|((second&2047)<<1)
        target=((pc+4+_sx(offset,21))&0xffffffff)|1
        return _condition(condition),f'pc={target}u;goto dispatch;',[target],False
    if first & 0xf800 == 0xf000 and second & 0xd000 == 0x9000:  # B.W T4
        sign=(first>>10)&1
        i1=1^((second>>13)&1)^sign;i2=1^((second>>11)&1)^sign
        offset=(sign<<24)|(i1<<23)|(i2<<22)|((first&1023)<<12)|((second&2047)<<1)
        target=((pc+4+_sx(offset,25))&0xffffffff)|1
        return '1',f'pc={target}u;goto dispatch;',[target],False
    if first & 0xf800 == 0xf000 and (second & 0xd000 == 0xd000 or second & 0xd001 == 0xc000):
        sign = (first >> 10) & 1
        i1 = 1 ^ ((second >> 13) & 1) ^ sign
        i2 = 1 ^ ((second >> 11) & 1) ^ sign
        offset = (sign << 24) | (i1 << 23) | (i2 << 22) | ((first & 1023) << 12) | ((second & 2047) << 1)
        thumb=bool(second&0x1000)
        base=pc+4 if thumb else (pc+4)&~3
        target=((base+_sx(offset,25))&0xffffffff)|int(thumb)
        return '1', f'r[14]={pc + 5}u;pc={target}u;goto dispatch;', [target], True
    raise ValueError('Thumb-2 instruction unsupported')


def _decode_thumb(w, pc):
    """Narrow Thumb-1 subset; wide encodings are decoded separately."""
    if w == 0xbf00:
        return '1','',[],False
    if w >> 11 in (0b11101, 0b11110, 0b11111):
        raise ValueError('Thumb-2 instruction unsupported')
    if w & 0xff00 in (0x4400,0x4600):  # ADD/MOV high register, no flags
        rd=(w&7)|((w>>4)&8);rm=(w>>3)&15
        source=f'{(pc+4)&0xffffffff}u' if rm==15 else _reg(rm)
        dest=f'{(pc+4)&0xffffffff}u' if rd==15 else _reg(rd)
        value=f'{dest}+{source}' if w&0xff00==0x4400 else source
        if rd==15:
            return '1',f'pc=(({value})&~1u)|1u;goto dispatch;',[],False
        return '1',f'{dest}={value};',[],False
    if w & 0xff00 == 0x4500:  # CMP high registers, explicit flag update
        rn=(w&7)|((w>>4)&8);rm=(w>>3)&15
        return '1',_flags(_reg(rn),_reg(rm),True),[],False
    if w & 0xf500 == 0xb100:  # CBZ/CBNZ, independent of APSR flags
        offset=(((w>>9)&1)<<6)|(((w>>3)&31)<<1)
        target=((pc+4+offset)&0xffffffff)|1
        cond=f'{_reg(w&7)}{"!=" if w&0x800 else "=="}0'
        return cond,f'pc={target}u;goto dispatch;',[target],False
    if w & 0xe000 == 0 and w & 0x1800 != 0x1800:  # LSLS/LSRS/ASRS immediate
        rd,rm,amount,kind=w&7,(w>>3)&7,(w>>6)&31,(w>>11)&3
        code=(f'uint64_t shifted=vx_shift({_reg(rm)},{kind}u,{amount}u,c,0);'
              f'{_reg(rd)}=(uint32_t)shifted;c=(uint32_t)(shifted>>32);n={_reg(rd)}>>31;z={_reg(rd)}==0;')
        return '1',code,[],False
    if w & 0xf800 == 0x1800:  # ADDS/SUBS three operands, register or imm3
        rd,rn=w&7,(w>>3)&7
        a=_reg(rn);b=f'{(w>>6)&7}u' if w&0x400 else _reg((w>>6)&7)
        subtract=bool(w&0x200)
        return '1',_flags(a,b,subtract)+f'{_reg(rd)}={a}{"-" if subtract else "+"}{b};',[],False
    if w & 0xfc00 == 0x4000:  # Thumb data processing registers
        op,rd,rm=(w>>6)&15,w&7,(w>>3)&7
        a,b=_reg(rd),_reg(rm)
        if op in (2,3,4,7):
            kind={2:0,3:1,4:2,7:3}[op]
            code=(f'uint64_t shifted=vx_shift({a},{kind}u,{b}&255u,c,1);'
                  f'{a}=(uint32_t)shifted;c=(uint32_t)(shifted>>32);n={a}>>31;z={a}==0;')
        elif op in (5,6):
            code=_carry_arithmetic(a,b,a,op==6)
        elif op in (9,10,11):
            code=_flags('0u' if op==9 else a,b,op!=11)
            if op==9:code+=f'{a}=0u-{b};'
        else:
            expressions={0:f'{a}&{b}',1:f'{a}^{b}',8:f'{a}&{b}',12:f'{a}|{b}',
                         13:f'{a}*{b}',14:f'{a}&~{b}',15:f'~{b}'}
            if op not in expressions:raise ValueError('Thumb carry arithmetic unsupported')
            code=f'uint32_t result={expressions[op]};n=result>>31;z=result==0;'
            if op!=8:code+=f'{a}=result;'
        return '1',code,[],False
    if w & 0xff00 == 0xb200:  # SXTH/SXTB/UXTH/UXTB
        op=(w>>6)&3;rd,rm=w&7,(w>>3)&7
        cast=('(uint32_t)(int32_t)(int16_t)','(uint32_t)(int32_t)(int8_t)','(uint32_t)(uint16_t)','(uint32_t)(uint8_t)')[op]
        return '1',f'{_reg(rd)}={cast}{_reg(rm)};',[],False
    if w & 0xff00 == 0xb000:  # ADD/SUB SP immediate
        return '1',f'r[13]{"-=" if w&0x80 else "+="}{(w&127)*4}u;',[],False
    if w & 0xf000 == 0x5000:  # Register-offset load/store, signed extension
        op,rm,rn,rt=(w>>9)&7,(w>>6)&7,(w>>3)&7,w&7
        width=(4,2,1,1,4,2,1,2)[op]
        code=f'addr={_reg(rn)}+{_reg(rm)};'
        code+=f'if(addr<memory_base||addr-memory_base>size||{width}u>size-(addr-memory_base))return -2;'
        if op in (0,1,2):
            code+=''.join(f'mem[addr-memory_base+{i}]=(uint8_t)({_reg(rt)}>>{8*i});' for i in range(width))
        else:
            value='vx_read32(mem+(addr-memory_base))' if width==4 else 'mem[addr-memory_base]'
            if width==2:value='('+value+'|((uint32_t)mem[addr-memory_base+1]<<8))'
            if op in (3,7):value=f'(uint32_t)(int32_t)(int{width*8}_t)({value})'
            code+=f'{_reg(rt)}={value};'
        return '1',code,[],False
    if w & 0xf000 == 0xa000:  # ADR / ADD Rd,SP,#imm
        base='r[13]' if w&0x800 else f'{(pc+4)&~3}u'
        return '1',f'{_reg((w>>8)&7)}={base}+{(w&255)*4}u;',[],False
    if w & 0xf800 == 0x4800 or w & 0xf000 == 0x9000:  # literal / SP-relative word
        literal=w & 0xf800 == 0x4800
        base=f'{(pc+4)&~3}u' if literal else 'r[13]'
        rd=(w>>8)&7;load=literal or bool(w&0x800)
        code=f'addr={base}+{(w&255)*4}u;if(addr<memory_base||addr-memory_base>size||4u>size-(addr-memory_base))return -2;'
        code+=f'{_reg(rd)}=vx_read32(mem+(addr-memory_base));' if load else f'vx_write32(mem+(addr-memory_base),{_reg(rd)});'
        return '1',code,[],False
    if w & 0xff87 in (0x4700, 0x4780):  # BX / BLX register
        link = bool(w & 0x80)
        rm=(w>>3)&15
        if link and rm==15:raise ValueError('invalid Thumb BLX PC operand')
        source=f'{(pc+4)&0xffffffff}u' if rm==15 else _reg(rm)
        code = f'pc={source};' + (f'r[14]={pc + 3}u;' if link else '')
        return '1', code + 'goto dispatch;', [], link
    if w & 0xfe00 in (0xb400, 0xbc00):  # PUSH/POP low registers plus LR/PC
        load = bool(w & 0x800)
        regs = [i for i in range(8) if w & (1 << i)]
        if w & 0x100:
            regs.append(15 if load else 14)
        if not regs:
            raise ValueError('empty Thumb stack register list unsupported')
        count = len(regs) * 4
        code = f'addr=r[13]{"" if load else "-"+str(count)+"u"};'
        code += f'if(addr<memory_base||addr-memory_base>size||{count}u>size-(addr-memory_base))return -2;'
        for index, reg in enumerate(regs):
            offset = index * 4
            code += (f'{"pc" if reg == 15 else _reg(reg)}=vx_read32(mem+(addr-memory_base)+{offset});' if load
                     else f'vx_write32(mem+(addr-memory_base)+{offset},{_reg(reg)});')
        code += f'r[13]{"+=" if load else "-="}{count}u;'
        if 15 in regs:
            code += 'goto dispatch;'
        return '1', code, [], False
    if w & 0xf800 in (0x2000, 0x2800, 0x3000, 0x3800):
        op, rd, imm = (w >> 11) & 3, (w >> 8) & 7, w & 255
        a, b = _reg(rd), f'{imm}u'
        if op == 1:
            code = _flags(a, b, True)
        elif op == 0:
            code = f'{a}={b};n={a}>>31;z={a}==0;'
        else:
            code = _flags(a, b, op == 3) + f'{a}={a}{"-" if op == 3 else "+"}{b};'
        return '1', code, [], False
    if w & 0xf800 == 0xe000:
        target = (pc + 4 + (_sx(w & 2047, 11) << 1)) | 1
        return '1', f'pc={target}u;goto dispatch;', [target], False
    if w & 0xf000 == 0xd000 and ((w >> 8) & 15) < 14:
        cond = _condition((w >> 8) & 15)
        target = (pc + 4 + (_sx(w & 255, 8) << 1)) | 1
        return cond, f'pc={target}u;goto dispatch;', [target], False
    if w & 0xe000 == 0x6000 or w & 0xf000 == 0x8000:  # word/byte/halfword immediate
        width=2 if w&0xf000==0x8000 else 1 if w&0x1000 else 4
        rd,rn,off=w&7,(w>>3)&7,((w>>6)&31)*width
        code=f'addr={_reg(rn)}+{off}u;if(addr<memory_base||addr-memory_base>size||{width}u>size-(addr-memory_base))return -2;'
        if width==4:
            code+=f'{_reg(rd)}=vx_read32(mem+(addr-memory_base));' if w&0x800 else f'vx_write32(mem+(addr-memory_base),{_reg(rd)});'
        elif w&0x800:
            code+=f'{_reg(rd)}=mem[addr-memory_base]'+('|((uint32_t)mem[addr-memory_base+1]<<8)' if width==2 else '')+';'
        else:
            code+=f'mem[addr-memory_base]=(uint8_t){_reg(rd)};'
            if width==2:code+=f'mem[addr-memory_base+1]=(uint8_t)({_reg(rd)}>>8);'
        return '1', code, [], False
    raise ValueError('Thumb opcode unsupported')


def _thumb_implicit_flags(w):
    """16-bit forms whose implicit S bit is disabled inside an IT block."""
    if w & 0xe000 == 0:  # immediate shifts and ADD/SUB three operands
        return True
    if w & 0xe000 == 0x2000:
        return w & 0xf800 != 0x2800  # CMP always updates flags
    if w & 0xfc00 == 0x4000:
        return (w >> 6) & 15 not in (8, 10, 11)  # TST/CMP/CMN
    return False


def _thumb_it_slots(memory, offset, end, pc):
    """Return controlled instruction boundaries and evolving IT conditions."""
    first = int.from_bytes(memory[offset:offset+2], 'little')
    state = first & 255
    if not state & 15 or state >> 4 >= 14:
        raise ValueError('invalid Thumb IT condition/mask')
    cursor = offset + 2
    slots = []
    while state & 15:
        if cursor + 2 > end:
            raise ValueError('truncated Thumb IT instruction')
        word = int.from_bytes(memory[cursor:cursor+2], 'little')
        width = 4 if word >> 11 in (0b11101, 0b11110, 0b11111) else 2
        if cursor + width > end:
            raise ValueError('truncated Thumb IT instruction')
        slots.append((pc + cursor - offset, width, _condition(state >> 4)))
        cursor += width
        state = 0 if state & 7 == 0 else (state & 0xe0) | ((state << 1) & 31)
    return slots, cursor - offset


def translate_elf(path: Path, imports=None, entry=None, indirect_targets=(), *, defer_decode_errors=False, max_instructions=MAX_INSTRUCTIONS, discover_literal_calls=False, runtime_fallback=False, partial_regions=False, retain_image=True) -> dict:
    """Translate a bounded fixed-address ARM ELF; never execute it.

    ET_SCE_* entry/imports come from validated module metadata.
    All reachable direct code, plus register-dispatch targets statically discovered,
    are emitted. Unknown dynamic targets stop with -3; step limit stops with -4.
    Zero means return through initial LR=0xffffffff; r0 is guest result.
    """
    if not isinstance(max_instructions,int) or not 1<=max_instructions<=262144:
        raise ValueError('translation instruction bound must be between 1 and 262144')
    if type(partial_regions) is not bool or (partial_regions and not runtime_fallback):
        raise ValueError('partial regions require the live fallback backend')
    if type(runtime_fallback) is not bool:
        raise ValueError('runtime_fallback must be boolean')
    path = Path(path)
    info = inspect_elf_segments(path)
    deps = inspect_elf_dependencies(path)
    module = None
    relocation_validation = None
    if info['elf_type'] in (0xfe00, 0xfe04):
        from .vita_module import inspect_vita_module, validate_identity_relocations, reconcile_imports
        module = inspect_vita_module(path)
        relocation_validation = validate_identity_relocations(path)
        imports = reconcile_imports(module['imports'], imports)
        if entry is not None and entry != module['entry']:
            raise ValueError('explicit entry conflicts with Vita module metadata')
        entry = module['entry']
    elif info['elf_type']==2:
        from .vita_module import inspect_vitasdk_elf, reconcile_imports
        module=inspect_vitasdk_elf(path,allow_missing=True)
        if module is not None:
            imports=reconcile_imports(module['imports'],imports)
            if entry is not None and entry!=module['entry']:
                raise ValueError('explicit entry conflicts with VitaSDK ELF metadata')
            entry=module['entry']
    if deps['undefined_symbols'] or (deps['relocations'] and info['elf_type'] not in (0xfe00,0xfe04)):
        raise ValueError('relocations/undefined ELF symbols require unsupported linking')
    raw = path.read_bytes()
    phoff = struct.unpack_from('<I', raw, 28)[0]
    phentsize, phnum = struct.unpack_from('<HH', raw, 42)
    for i in range(phnum):
        typ = struct.unpack_from('<I', raw, phoff + i * phentsize)[0]
        if typ not in (0, 1, 4, 6, 0x6474e551) and not (module is not None and typ == 0x60000000):
            raise ValueError('unsupported program header (including SCE relocation/dynamic linking)')
    if entry is None and info['elf_type'] != 2:
        raise ValueError('explicit code entry required for non-ET_EXEC; SCE entry may be metadata')
    entry = info['entry_point'] if entry is None else entry
    if not isinstance(entry, int) or not 0 <= entry <= 0xffffffff:
        raise ValueError('invalid entry')
    segments = info['segments']
    size = max((s['virtual_address'] + s['memory_size'] for s in segments), default=0)
    memory_base = min((s['virtual_address'] for s in segments), default=0) & ~4095 if size > MAX_MEMORY else 0
    if not size or size-memory_base > MAX_MEMORY or size+65536 > 0xffffffff:
        raise ValueError('guest image exceeds bounded supported address space')
    memory = bytearray(size-memory_base)
    ranges = []
    for s in segments:
        a, end = s['virtual_address'], s['virtual_address'] + s['memory_size']
        if any(a < hi and lo < end for lo, hi in ranges):
            raise ValueError('overlapping load segments unsupported')
        ranges.append((a, end))
        memory[a-memory_base:a-memory_base + s['file_size']] = raw[s['file_offset']:s['file_offset'] + s['file_size']]
    hooks = dict(imports or {})
    for a, nid in hooks.items():
        if not isinstance(a, int) or not isinstance(nid, int) or not 0 <= a <= 0xffffffff or not 0 <= nid <= 0xffffffff:
            raise ValueError('invalid explicit import mapping')
    exported_entries=[address for library in (module or {}).get('exports',[])
                      for address in library['functions'].values()]
    declared_targets = list(indirect_targets)
    if any(not isinstance(a, int) or not 0 <= a <= 0xffffffff for a in declared_targets):
        raise ValueError('invalid indirect target')
    pending, decoded = [entry]+exported_entries+declared_targets, {}
    indirect_discovered = False
    indirect_roots = set(declared_targets)

    def discover_indirect():
        # Never decode arbitrary executable bytes as instructions. Compiler mapping
        # symbols supply state and exclude literal/switch data, and the width scan
        # excludes Thumb-2 second halves and fused IT slots from dispatch roots.
        roots = set(deps.get('function_entries', []))
        for region in deps.get('code_ranges', []):
            start, end, thumb = region['start'], region['end'], region['thumb']
            if not any(s['flags'] & 1 and s['virtual_address'] <= start and
                       end <= s['virtual_address'] + s['file_size'] for s in segments):
                raise ValueError('ARM mapping range outside executable file bytes')
            if module and any(h <= start and end <= h + 16 for h in hooks):
                continue  # SDK import-stub padding is not guest code.
            cursor = start
            while cursor < end:
                if len(roots) >= max_instructions:
                    raise ValueError('indirect target limit exceeded')
                roots.add(cursor | int(thumb))
                width = 2 if thumb else 4
                if thumb:
                    half = int.from_bytes(memory[cursor-memory_base:cursor-memory_base+2], 'little')
                    if half >> 11 in (0b11101, 0b11110, 0b11111):
                        width = 4
                    elif half & 0xff00 == 0xbf00 and half & 15:
                        _, width = _thumb_it_slots(memory, cursor-memory_base, end-memory_base, cursor)
                if cursor + width > end:
                    raise ValueError(f'truncated instruction in ARM mapping range {start:#x}-{end:#x} cursor {cursor:#x} width {width}')
                cursor += width
        return roots

    if any(nid in (0xC5C11EE7,0xB19CF7E9) for nid in hooks.values()):
        indirect_discovered = True
        roots = discover_indirect()
        indirect_roots.update(roots)
        pending.extend(sorted(roots))

    decode_errors = {}
    instruction_bytes = set()
    fallthrough_previous = {}
    literal_call_targets = {}

    def literal_thumb_call(ip,register):
        # Walk only already decoded, straight-line predecessors. A complete
        # MOVW[/MOVT] definition is a declared call candidate, not a guess from
        # arbitrary executable/data bytes. Clobbers, predicates and calls stop
        # the proof. Runtime BLX remains indirect and still traps other targets.
        cursor=ip;high=None
        for _ in range(32):
            previous=fallthrough_previous.get(cursor)
            if previous is None or not previous&1:return None
            condition,statement,_next=decoded[previous]
            if condition!='1' or 'goto dispatch;' in statement:return None
            off=(previous&~1)-memory_base
            raw=int.from_bytes(memory[off:off+4],'little');first,second=raw&65535,raw>>16
            if first&0xfbf0 in (0xf240,0xf2c0) and not second&0x8000 and (second>>8)&15==register:
                imm=((first&15)<<12)|(((first>>10)&1)<<11)|(((second>>12)&7)<<8)|(second&255)
                if first&128:
                    if high is None:high=imm<<16
                else:return (high or 0)|imm
            elif re.search(r'r\['+str(register)+r'\]\s*(?:[+\-^|&]?=|\+\+|--)',statement):return None
            cursor=previous
        return None
    frontier=[]
    while pending:
        ip = pending.pop()
        if ip in decoded or ip in hooks:
            continue
        if len(decoded) >= max_instructions:
            if partial_regions:
                frontier=sorted(set(pending+[ip])-set(decoded)-set(hooks))
                break
            raise ValueError('reachable instruction limit exceeded')
        thumb, pc = bool(ip & 1), ip & ~1
        width = 2 if thumb else 4
        if pc % width or not any(s['flags'] & 1 and s['virtual_address'] <= pc and pc + width <= s['virtual_address'] + s['file_size'] for s in segments):
            raise ValueError(f'code target outside executable file bytes: {ip:#x}')
        word = int.from_bytes(memory[pc-memory_base:pc-memory_base + width], 'little')
        decoder = _decode_thumb if thumb else _decode_arm
        if thumb and word >> 11 in (0b11101, 0b11110, 0b11111):
            width = 4
            if not any(s['flags'] & 1 and s['virtual_address'] <= pc and pc + width <= s['virtual_address'] + s['file_size'] for s in segments):
                raise ValueError(f'truncated Thumb-2 instruction at {ip:#x}')
            word = int.from_bytes(memory[pc-memory_base:pc-memory_base + width], 'little')
            decoder = _decode_thumb32
        it_block = thumb and width == 2 and word & 0xff00 == 0xbf00 and word & 15
        if it_block:
            region_end = next(s['virtual_address'] + s['file_size'] - memory_base
                              for s in segments if s['flags'] & 1 and
                              s['virtual_address'] <= pc < s['virtual_address'] + s['file_size'])
            slots, width = _thumb_it_slots(memory, pc-memory_base, region_end, pc)
        if any(address in instruction_bytes for address in range(pc, pc + width)):
            raise ValueError(f'overlapping instruction encodings at {ip:#x}')
        try:
            if it_block:
                code, targets, link = '', [], False
                for index, (slot_pc, slot_width, slot_cond) in enumerate(slots):
                    slot_word = int.from_bytes(memory[slot_pc-memory_base:slot_pc-memory_base+slot_width], 'little')
                    if slot_width == 4 and slot_word & 0xef00 == 0xef00:
                        raise ValueError('NEON inside Thumb IT unsupported')
                    if slot_width == 2 and slot_word & 0xff00 == 0xbf00 and slot_word & 15:
                        raise ValueError('nested Thumb IT unsupported')
                    decode = _decode_thumb32 if slot_width == 4 else _decode_thumb
                    condition, statement, edges, continuation = decode(slot_word, slot_pc)
                    control = bool(edges or continuation or 'goto dispatch;' in statement)
                    if condition != '1' or (control and index != len(slots)-1):
                        raise ValueError('Thumb IT control flow must be in final slot')
                    if slot_width == 2 and _thumb_implicit_flags(slot_word):
                        statement = ('{uint32_t saved_n=n,saved_z=z,saved_c=c,saved_v=v;'+statement+
                                     'n=saved_n;z=saved_z;c=saved_c;v=saved_v;}')
                    code += f'if({slot_cond}){{{statement}}}'
                    targets.extend(edges)
                    link |= control  # Conditional last-slot branch retains fallthrough.
                cond = '1'
            else:
                cond, code, targets, link = decoder(word, pc)
        except ValueError as e:
            if not defer_decode_errors:
                raise ValueError(f'{e} at {ip:#x} opcode {word:#x}') from e
            decode_errors[ip] = {'opcode': word, 'reason': str(e)}
            cond, code, targets, link = '1', 'VX_RETURN(-8);goto dispatch;', [], False
        if discover_literal_calls and thumb and width==2 and word&0xff87==0x4780 and ip not in decode_errors:
            candidate=literal_thumb_call(ip,(word>>3)&15)
            if candidate is not None:
                address=candidate&~1;minimum=2 if candidate&1 else 4
                if address%minimum==0 and any(s['flags']&1 and s['virtual_address']<=address and address+minimum<=s['virtual_address']+s['file_size'] for s in segments):
                    literal_call_targets[ip]=candidate
                    indirect_roots.add(candidate);targets=list(targets)+[candidate]
        # Dynamic calls/jumps need address-taken functions and switch case labels,
        # which direct-edge traversal alone cannot discover. Returns through LR or
        # the stack already point to translated call continuations.
        dynamic = 'goto dispatch;' in code and not targets
        returning = ((not thumb and word & 0x0fffffff == 0x012fff1e) or
                     (thumb and width == 2 and word == 0x4770) or
                     ('r[13]+=' in code))
        if dynamic and not returning and not indirect_discovered:
            indirect_discovered = True
            roots = discover_indirect()
            indirect_roots.update(roots)
            pending.extend(sorted(roots))
        next_ip = (pc + width) | int(thumb)
        decoded[ip] = (cond, code, next_ip)
        fallthrough_previous[next_ip]=ip
        instruction_bytes.update(range(pc, pc + width))
        pending.extend(targets)
        terminates = 'goto dispatch;' in code and cond == '1' and not link
        if not terminates and (not indirect_discovered or not deps.get('code_ranges') or
                               next_ip in indirect_roots or next_ip in hooks):
            pending.append(next_ip)
    if entry in hooks:
        raise ValueError('entry cannot be an import hook')
    guest_abi = (Path(__file__).resolve().parents[1]/'runtime/vita_guest.h').read_text()
    lines = [guest_abi,'#include <stdint.h>', '#include <stddef.h>','#include <string.h>','#include <math.h>','#include <fenv.h>',VFP_HELPERS,
             (Path(__file__).resolve().parents[1]/'runtime/vita_neon_fp.h').read_text(),
             'static uint64_t vx_shift(uint32_t x,unsigned type,unsigned amount,uint32_t carry,int reg){'
             'uint32_t result=x,c=carry;if(!amount&&reg)return ((uint64_t)c<<32)|x;'
             'switch(type){case 0:if(amount){c=amount<=32?(x>>(32-amount))&1u:0;result=amount<32?x<<amount:0;}break;'
             'case 1:if(!amount)amount=32;c=amount<=32?(x>>(amount-1))&1u:0;result=amount<32?x>>amount:0;break;'
             'case 2:if(!amount)amount=32;c=amount<32?(x>>(amount-1))&1u:x>>31;'
             'result=amount>=32?(0u-(x>>31)):(x>>amount)|((0u-(x>>31))<<(32-amount));break;'
             'case 3:if(!amount){result=(carry<<31)|(x>>1);c=x&1u;}else{amount&=31;result=amount?(x>>amount)|(x<<(32-amount)):x;c=result>>31;}break;}'
             'return ((uint64_t)c<<32)|result;}',
             'extern uint32_t vx_import(uint32_t,uint32_t*,uint8_t*,size_t);',
             'extern uint32_t vx_import_vfp(uint32_t,uint32_t*,uint32_t*,uint8_t*,size_t);',
             'static uint32_t vx_read32(const uint8_t*p){return (uint32_t)p[0]|(uint32_t)p[1]<<8|(uint32_t)p[2]<<16|(uint32_t)p[3]<<24;}',
             ('extern _Thread_local uint64_t vx_exclusive_epoch;extern void vx_guest_memory_written(void);' if runtime_fallback else
              'static _Thread_local uint64_t vx_exclusive_epoch;void vx_guest_memory_written(void){vx_exclusive_epoch++;}'),
             'static void vx_write32(uint8_t*p,uint32_t v){vx_guest_memory_written();for(int i=0;i<4;i++)p[i]=(uint8_t)(v>>(8*i));}',
             'static void vx_write8(uint8_t*p,uint8_t v){vx_guest_memory_written();*p=v;}',
             '#ifdef __APPLE__',
             'extern int vx_runtime_stop_requested(uint32_t*) __attribute__((weak_import));',
             '#else',
             'extern int vx_runtime_stop_requested(uint32_t*) __attribute__((weak));',
             '#endif',
             '#define VX_RETURN(rc) do{int vx_rc=(rc);if(vx_rc<=0)s->exclusive_valid=0;s->pc=pc;s->n=n;s->z=z;s->c=c;s->v=v;s->fpscr=fpscr;return vx_rc;}while(0)',
             'int vx_guest_target_valid(uint32_t);',
             'int vx_guest_resume(vx_guest_state*s,uint8_t*mem,size_t size,uint32_t budget){',
             'uint32_t *r=s->r,*f=s->f;',
             f'const uint32_t memory_base={memory_base}u;',
             'uint32_t pc=s->pc,addr=0,n=s->n,z=s->z,c=s->c,v=s->v;uint64_t steps=0;',
             'uint32_t fpscr=s->fpscr;if(fegetround()!=FE_TONEAREST)VX_RETURN(-6);',
             'dispatch: if(vx_runtime_stop_requested){uint32_t status;if(vx_runtime_stop_requested(&status)){r[0]=status;VX_RETURN(0);}} if(pc==0xffffffffu)VX_RETURN(0);' +
             ('if(!vx_guest_target_valid(pc))VX_RETURN(2);' if runtime_fallback else '') +
             'if(steps++>=budget)VX_RETURN(1);s->instructions++;switch(pc){']
    for ip in sorted(decoded):
        lines.append(f'case {ip}u:goto L_{ip:x};')
    for ip, nid in sorted(hooks.items()):
        bridge=f'vx_import_vfp({nid}u,r,f,mem,size)' if nid in (0x32F280F0,0x269B56BE) else f'vx_import({nid}u,r,mem,size)'
        lines.append(f'case {ip}u:s->exclusive_valid=0;vx_guest_memory_written();r[0]={bridge};pc=r[14];s->services++;VX_RETURN(1);')
    lines.append('default:VX_RETURN(-3);}')
    for ip, (cond, code, next_ip) in sorted(decoded.items()):
        code=code.replace('return -2;','VX_RETURN(-2);')
        # All generated guest stores use the instrumented word/byte writers.
        # Only lvalue assignments match: reads retain their original spelling.
        code=re.sub(r'mem\[([^\]]+)\]\s*=(?!=)([^;]+);',lambda m:f'vx_write8(mem+({m[1]}),{m[2]});',code)
        lines.append(f'L_{ip:x}: if({cond}){{{code}}} pc={next_ip}u;goto dispatch;')
    lines.extend(['}', '#undef VX_RETURN',
                  'int vx_guest_target_valid(uint32_t pc){switch(pc){'])
    for ip in sorted(set(decoded)|set(hooks)):
        lines.append(f'case {ip}u:return 1;')
    lines.extend(['default:return 0;}}',
                  '__attribute__((weak,noinline)) int vx_runtime_run(vx_guest_state*s,uint8_t*mem,size_t size,vx_guest_resume_fn resume){int rc;do{uint32_t budget=s->instructions<1000000u?(uint32_t)(1000000u-s->instructions):0;if(!budget)return -4;rc=resume(s,mem,size,budget);}while(rc==1);return rc;}',
                  'int vx_guest(uint32_t r[16],uint8_t*mem,size_t size){',
                  f'vx_guest_state s={{0}};memcpy(s.r,r,sizeof s.r);s.pc={entry}u;int rc;',
                  'rc=vx_runtime_run(&s,mem,size,vx_guest_resume);',
                  'memcpy(r,s.r,sizeof s.r);return rc;}'])
    c_source='\n'.join(lines)+'\n'
    if runtime_fallback:
        # Reject guest stores into immutable input code before changing bytes.
        c_source=c_source.replace('static void vx_write32(', 'static void vx_store32(').replace('static void vx_write8(', 'static void vx_store8(')
        guard=('extern int vn_guest_write_allowed(const uint8_t*,size_t);\n'
               '#define vx_write32(p,v) do{if(!vn_guest_write_allowed((p),4))VX_RETURN(-2);vx_store32((p),(v));}while(0)\n'
               '#define vx_write8(p,v) do{if(!vn_guest_write_allowed((p),1))VX_RETURN(-2);vx_store8((p),(v));}while(0)\n')
        c_source=c_source.replace('int vx_guest_target_valid(uint32_t);',guard+'int vx_guest_target_valid(uint32_t);')
        c_source=c_source.replace('vx_import(', 'vn_import(').replace('vx_import_vfp(', 'vn_import_vfp(')
    return {'c_source': c_source, 'memory_image': bytes(memory) if retain_image else None,
            'memory_base':memory_base, 'module':module, 'relocation_validation':relocation_validation,
            'entry': entry, 'instruction_count': len(decoded), 'decode_errors':decode_errors,
            'dispatch_addresses':sorted(set(decoded)|set(hooks)),
            'instruction_limit':max_instructions,
            'indirect_target_count': len(indirect_roots),
            'indirect_target_source': 'ELF mapping/function symbols plus explicit roots',
            'literal_call_targets':literal_call_targets,
            'literal_discovery_enabled':discover_literal_calls,
            'input_sha256': hashlib.sha256(raw).hexdigest(),
            'backend': 'bounded-arm-thumb-static-c-v1',
            'runtime_fallback':runtime_fallback,'partial_region':bool(frontier),'frontier':frontier,
             'limitations': ['bounded integer/scalar VFP and NEON bitwise/integer add/sub subset; NEON in Thumb IT and double arithmetic unsupported', 'declared virtual addresses; SCE relocation identity validation only',
                            'explicit imports and executable entry required', 'not commercial Vita compatibility']}
