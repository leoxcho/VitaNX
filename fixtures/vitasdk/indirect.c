/* Real SDK compiler switch plus explicit architectural dispatch regressions. */
#include <psp2/io/fcntl.h>
#include <psp2/kernel/processmgr.h>
#define FN __attribute__((noinline,noclone))
FN __attribute__((target("arm"))) int arm_leaf(int x) { return x+17; }
FN __attribute__((target("thumb"))) int thumb_leaf(int x) { return x*3-2; }
static int (*volatile calls[2])(int) = {arm_leaf,thumb_leaf};
FN int compiler_switch(unsigned x) {
 switch(x) {
 case 0: return arm_leaf(1);
 case 1: return arm_leaf(8)+2;
 case 2: return thumb_leaf(7);
 case 3: return arm_leaf(4)-1;
 case 4: return thumb_leaf(11)+3;
 case 5: return arm_leaf(13);
 case 6: return thumb_leaf(15)-4;
 default: return -9;
 }
}
__asm__(
 ".text\n .arm\n .align 2\n"
 ".global signed_switch\n .type signed_switch,%function\n"
 "signed_switch:\n b 2f\n"
 "3: mov r0,#31\n bx lr\n 4: mov r0,#47\n bx lr\n 5: mov r0,#59\n bx lr\n"
 "2: adr r3,1f\n add r3,r3,r0\n ldrsh r3,[r3,r0]\n"
 "6: add pc,pc,r3,lsl #2\n nop\n"
 "1: .hword (3b-(6b+8))/4,(4b-(6b+8))/4,(5b-(6b+8))/4\n .align 2\n"
 ".size signed_switch,.-signed_switch\n"
 ".global absolute_switch\n .type absolute_switch,%function\n"
 "absolute_switch:\n ldr pc,[pc,r0,lsl #2]\n nop\n .word arm_leaf,thumb_leaf\n"
 ".size absolute_switch,.-absolute_switch\n"
 ".thumb\n .align 1\n .global byte_switch\n .type byte_switch,%function\n .thumb_func\n"
 "byte_switch:\n tbb [pc,r0]\n 1: .byte (2f-1b)/2,(3f-1b)/2,(4f-1b)/2,0\n"
 "2: movs r0,#11\n bx lr\n 3: movs r0,#23\n bx lr\n 4: movs r0,#37\n bx lr\n"
 ".size byte_switch,.-byte_switch\n"
 ".align 1\n .global half_switch\n .type half_switch,%function\n .thumb_func\n"
 "half_switch:\n nop\n tbh [pc,r0,lsl #1]\n 1: .hword (2f-1b)/2,(3f-1b)/2,(4f-1b)/2\n"
 "2: movs r0,#41\n bx lr\n 3: movs r0,#53\n bx lr\n 4: movs r0,#67\n bx lr\n"
 ".size half_switch,.-half_switch\n .arm\n"
);
extern int signed_switch(unsigned),absolute_switch(int),byte_switch(unsigned),half_switch(unsigned);
static const int expected[9]={18,27,19,20,34,30,39,-9,-9};
static const int a[3]={31,47,59}, b[3]={11,23,37}, h[3]={41,53,67};
int module_start(unsigned argc,const void *argp) {
 (void)argc;(void)argp;
 int status=0;
 for(unsigned i=0;i<9;i++) if(compiler_switch(i)!=expected[i])status=1;
 for(unsigned i=0;i<3;i++)
  if(signed_switch(i)!=a[i]||byte_switch(i)!=b[i]||half_switch(i)!=h[i])status=2;
 for(unsigned i=0;i<2;i++) {
  int want=i?1:17; /* absolute switch passes its index as leaf argument */
  if(absolute_switch(i)!=want || calls[i](9)!=(i?25:26))status=3;
 }
 if(!status) { static const char pass[]="VitaSDK indirect ARM/Thumb switch/interwork PASS\n"; sceIoWrite(1,pass,sizeof(pass)-1); }
 sceKernelExitProcess(status);return status;
}
