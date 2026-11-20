/* Genuine VitaSDK scalar VFP regression. Arithmetic is computed at runtime. */
#include <psp2/kernel/processmgr.h>
#include <psp2/io/fcntl.h>
static volatile float inputs[]={1.5f,-2.0f,0.5f};
static volatile float output[4];
static volatile int integer=7,converted;
static const char success[]="VitaSDK scalar VFP PASS\n";
int module_start(unsigned argc,const void *argp){
 (void)argc;(void)argp;
 float a=inputs[0],b=inputs[1],c=inputs[2];
 output[0]=(a+b)*c;output[1]=a/c;output[2]=-b;output[3]=(float)integer;
 converted=(int)output[1];
 int status=output[0]!=-0.25f||output[1]!=3.0f||output[2]!=2.0f||output[3]!=7.0f||converted!=3;
 if(!status)sceIoWrite(1,success,sizeof(success)-1);
 sceKernelExitProcess(status);return 99;
}
