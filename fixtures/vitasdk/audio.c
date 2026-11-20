/* Genuine SceAudio PCM bridge fixture. Silent samples validate completion only. */
#include <psp2/audioout.h>
#include <psp2/kernel/processmgr.h>
static short silence[256];
static int volume[2]={32768,32768};
int module_start(unsigned argc,const void *argp){
 (void)argc;(void)argp;
 int port=sceAudioOutOpenPort(SCE_AUDIO_OUT_PORT_TYPE_MAIN,128,48000,SCE_AUDIO_OUT_MODE_STEREO);
 if(port<0)return 1;
 if(sceAudioOutGetConfig(port,SCE_AUDIO_OUT_CONFIG_TYPE_FREQ)!=48000)return 2;
 if(sceAudioOutSetVolume(port,SCE_AUDIO_VOLUME_FLAG_L_CH|SCE_AUDIO_VOLUME_FLAG_R_CH,volume)<0)return 3;
 if(sceAudioOutOutput(port,silence)<0)return 4;
 if(sceAudioOutOutput(port,0)<0)return 5;
 if(sceAudioOutReleasePort(port)<0)return 6;
 sceKernelExitProcess(0);return 99;
}
