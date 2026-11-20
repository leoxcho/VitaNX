/* Genuine VitaSDK gameplay service integration, shared with the 3D game fixture. */
#include <psp2/kernel/threadmgr.h>
#include <psp2/kernel/processmgr.h>
#include <psp2/io/fcntl.h>
#ifndef VX_RUNTIME_FRAMES
#define VX_RUNTIME_FRAMES 240
#endif
#ifndef VX_RUNTIME_DELAY
#define VX_RUNTIME_DELAY 1000
#endif
static volatile unsigned checksum;
static SceUID work,ack,lock,event,callback;
static volatile unsigned total,notices,worker_status;
static int notified(int id,int count,int arg,void *user){
 if(id!=callback||arg!=73||user!=(void *)&notices||count<1)return -1;
 notices+=(unsigned)count;return 0;
}
static int worker(unsigned length,void *arg){
 if(length!=4||*(unsigned *)arg!=0x12345678)return 20;
 volatile float a=1.25f;
 for(unsigned frame=0;frame<VX_RUNTIME_FRAMES;frame++){
  if(sceKernelWaitSema(work,1,0))return 21;
  if(sceKernelLockMutex(lock,1,0))return 22;
  total++;a+=.5f;
  if(sceKernelUnlockMutex(lock,1))return 23;
  if(!(frame&31)&&sceKernelNotifyCallback(callback,73))return 24;
  if(sceKernelSignalSema(ack,1))return 25;
 }
 if(a!=1.25f+VX_RUNTIME_FRAMES*.5f)return 26;
 if(sceKernelSetEventFlag(event,4))return 27;
 worker_status=1;return 37;
}
int module_start(unsigned argc,const void *argp){
 (void)argc;(void)argp;int status=1;
 work=sceKernelCreateSema("frame jobs",0,0,1,0);
 ack=sceKernelCreateSema("frame done",0,0,1,0);
 lock=sceKernelCreateMutex("world",0,0,0);
 event=sceKernelCreateEventFlag("scene",0,0,0);
 callback=sceKernelCreateCallback("scene notice",0,notified,(void *)&notices);
 if(work<0||ack<0||lock<0||event<0||callback<0)goto done;
 SceUID id=sceKernelCreateThread("simulation",worker,0x10000100,16384,0,0,0);
 status=2;if(id<0)goto done;
 unsigned argument=0x12345678;
 if(sceKernelStartThread(id,4,&argument))goto done;
 argument=0; /* worker must receive a private copy */
 for(unsigned frame=0;frame<VX_RUNTIME_FRAMES;frame++){
  status=3;
  if(sceKernelSignalSema(work,1)||sceKernelWaitSema(ack,1,0))goto done;
  for(unsigned check=0;check<32;check++)checksum+=frame+check;
  if(sceKernelCheckCallback()<0)goto done;
  if(sceKernelDelayThreadCB(VX_RUNTIME_DELAY))goto done;
 }
 unsigned timeout=50000,bits=0;int code=0;status=4;
 if(sceKernelWaitEventFlag(event,4,SCE_EVENT_WAITAND|SCE_EVENT_WAITCLEAR_PAT,&bits,&timeout)||bits!=4)goto done;
 if(sceKernelWaitThreadEnd(id,&code,0)||code!=37||!worker_status||total!=VX_RUNTIME_FRAMES||notices!=(VX_RUNTIME_FRAMES+31)/32||checksum!=16u*VX_RUNTIME_FRAMES*(VX_RUNTIME_FRAMES+30u))goto done;
 status=5;
 if(sceKernelDeleteThread(id)||sceKernelDeleteSema(work)||sceKernelDeleteSema(ack)||sceKernelDeleteMutex(lock)||sceKernelDeleteEventFlag(event)||sceKernelDeleteCallback(callback))goto done;
 static const char pass[]="VitaSDK gameplay threads/synchronization/callbacks/timers PASS\n";
 sceIoWrite(1,pass,sizeof(pass)-1);status=0;
 done:sceKernelExitProcess(status);return status;
}
