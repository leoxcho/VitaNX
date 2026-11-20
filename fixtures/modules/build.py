"""Original assembled ARM/Thumb code wrapped in public Vita SCE ELF metadata.

No SDK, firmware or game code. Two load segments and real R_ARM_ABS32 records.
"""
from pathlib import Path
import struct,subprocess
HERE=Path(__file__).resolve().parent
LIB_A='a0000001';LIB_B='b0000001';FUNCTION='11111111'
MAIN=r'''
.syntax unified
.arch armv7-a
.fpu neon
.arm
.global _start, state, state_ptr, import_a
.text
_start:
 push {r4-r8,lr}
 mov r0,#5
 vmov s0,r0
 ldr r4,state_ptr
 str r0,[r4]
 ldr r1,[r4,#8]
 add r1,r1,#1
 str r1,[r4,#8]
 bl import_a
 str r0,[r4,#4]
 cmp r0,#42
 bne failure
 vmov r1,s0
 cmp r1,#5
 bne failure
 mov r0,#42
 pop {r4-r8,pc}
failure: mov r0,#99
 pop {r4-r8,pc}
.align 2
import_a: bx lr
 nop
 nop
 nop
state_ptr: .word state
.data
state: .word 0,0,0
'''
SUPPORT=r'''
.syntax unified
.arch armv7-a
.fpu neon
.arm
.global _start, stop, worker, state, state_ptr
.text
_start:
 ldr r1,state_ptr
 mov r0,#10
 str r0,[r1]
 mov r0,#0
 bx lr
stop:
 ldr r1,state_ptr
 mov r0,#20
 str r0,[r1,#8]
 mov r0,#0
 bx lr
.thumb
.thumb_func
worker:
 push {r4,lr}
 ldr r4,state_ptr
 ldr r1,[r4]
 cmp r1,#10
 bne failed
 ldr r1,[r4,#8]
 cmp r1,#0
 bne failed
 add.w r0,r0,#37
 str r0,[r4,#4]
 pop {r4,pc}
failed: movs r0,#99
 pop {r4,pc}
.align 2
state_ptr: .word state
.data
state: .word 0,0,0
'''

def read_symbols(data):
    shoff=struct.unpack_from('<I',data,32)[0];sz,n=struct.unpack_from('<HH',data,46)
    headers=[struct.unpack_from('<IIIIIIIIII',data,shoff+i*sz) for i in range(n)]
    result={}
    for h in headers:
        if h[1]!=2:continue
        names=headers[h[6]];strings=data[names[4]:names[4]+names[5]]
        for off in range(h[4],h[4]+h[5],h[9]):
            name,value,size,info,other,idx=struct.unpack_from('<IIIBBH',data,off)
            if name:result[strings[name:].split(b'\0',1)[0].decode()]=value
    return result

def build_one(folder,name,source,library=None):
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    (folder/(name+'.S')).write_text(source)
    obj=folder/(name+'.o');linked=folder/(name+'-linked.elf')
    subprocess.run(['clang','-target','armv7-none-eabi','-c',str(folder/(name+'.S')),'-o',str(obj)],check=True,capture_output=True)
    subprocess.run(['ld.lld','-m','armelf','-T',str(HERE.parent/'homebrew/link.ld'),str(obj),'-o',str(linked)],check=True,capture_output=True)
    data=linked.read_bytes();sym=read_symbols(data);text=bytearray(0x1000);values=bytearray(0x1000)
    phoff=struct.unpack_from('<I',data,28)[0];n=struct.unpack_from('<H',data,44)[0]
    for i in range(n):
        t,off,addr,_,size,_,flags,_=struct.unpack_from('<IIIIIIII',data,phoff+32*i)
        if t==1:
            target=text if flags&1 else values;target[:size]=data[off:off+size]
    module=0x800
    struct.pack_into('<HH',text,module,0,0x101);text[module+4:module+4+len(name)+1]=name.encode()+b'\0';text[module+31]=6
    exports=[('936c8a78',['935cd196']+(['79f8e492'] if library else []),[sym['_start']]+([sym['stop']] if library else []))]
    if library:exports.append((library,[FUNCTION],[sym['worker']]))
    struct.pack_into('<IIII',text,module+0x24,0x900,0x900+32*len(exports),0xa00,0xa00+(0 if library else 0x34))
    struct.pack_into('<IIIIII',text,module+0x34,0x1234,0,0,0,sym['_start']-0x10000,0xffffffff)
    cursor=0xb00
    for i,(lib,nids,addresses) in enumerate(exports):
        count=len(nids);nptr=cursor;aptr=cursor+4*count
        for j,nid in enumerate(nids):struct.pack_into('<I',text,nptr+4*j,int(nid,16))
        for j,addr in enumerate(addresses):struct.pack_into('<I',text,aptr+4*j,addr)
        struct.pack_into('<BBH',text,0x900+32*i,0x20,0,1)
        struct.pack_into('<HHIIIIII',text,0x904+32*i,0,count,0,0,int(lib,16),0,0x10000+nptr,0x10000+aptr)
        cursor+=count*8
    if not library:
        struct.pack_into('<BBHHHHH',text,0xa00,0x34,0,1,0,1,0,0)
        struct.pack_into('<II',text,0xa10,int(LIB_A,16),0)
        struct.pack_into('<II',text,0xa1c,0x10c00,0x10c04)
        struct.pack_into('<II',text,0xc00,int(FUNCTION,16),sym['import_a'])
    if not library:
        struct.pack_into('<III',text,module+0x38,0x1020,4,16)
        values[0x20:0x24]=b'TLS!'
    out=bytearray(0x210c)
    struct.pack_into('<16sHHIIIIIHHHHHH',out,0,b'\x7fELF\x01\x01\x01'+bytes(9),0xfe04,40,1,module,52,0,0x5000000,52,32,3,0,0,0)
    struct.pack_into('<IIIIIIII',out,52,1,0x100,0x10000,0x10000,0x1000,0x1000,5,0x100)
    struct.pack_into('<IIIIIIII',out,84,1,0x1100,0x11000,0x11000,0x1000,0x1000,6,0x100)
    struct.pack_into('<IIIIIIII',out,116,0x60000000,0x2100,0,0,12,12,0,4)
    out[0x100:0x1100]=text;out[0x1100:0x2100]=values
    struct.pack_into('<III',out,0x2100,(1<<4)|(2<<8),0,sym['state_ptr']-0x10000)
    path=folder/(name+'.elf');path.write_bytes(out)
    return path,sym

def build(folder):
    folder=Path(folder)
    a,sa=build_one(folder,'main',MAIN)
    b,sb=build_one(folder,'support_a',SUPPORT,LIB_A)
    c,sc=build_one(folder,'support_b',SUPPORT.replace('#37','#94'),LIB_B)
    return [a,b,c], [sa,sb,sc]
