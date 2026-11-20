/* Genuine VitaSDK integer regression. The volatile inputs prevent folding. */
#include <psp2/kernel/processmgr.h>
#include <psp2/io/fcntl.h>
static volatile unsigned inputs[4]={0x81234567u,0x12345678u,7u,0x55aau};
static volatile unsigned output[6];
static const char success[]="VitaSDK integer core PASS\n";
int module_start(unsigned argc,const void *argp){
 (void)argc;(void)argp;
 unsigned a=inputs[0],b=inputs[1],n=inputs[2];
 output[0]=(a<<n)^(b>>n);
 output[1]=(a&b)|(a&~b);
 output[2]=a*b+inputs[3];
 output[3]=(unsigned)((int)a>>n);
 output[4]=a-b;
 unsigned sum=0;
 for(unsigned i=0;i<7;i++)sum+=i*3;
 output[5]=sum;
 if(output[0]!=0x9186db2cu||output[1]!=a||output[2]!=0xb8c577f2u||
    output[3]!=0xff02468au||output[4]!=0x6eeeeeefu||output[5]!=63){
  sceKernelExitProcess(31);return 31;
 }
 sceIoWrite(1,success,sizeof(success)-1);
 sceKernelExitProcess(0);return 99;
}
