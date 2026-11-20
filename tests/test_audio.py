"""Audio ABI validation; device completion is recorded separately from audibility."""
from pathlib import Path
import platform
import subprocess
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[1]
@unittest.skipUnless(platform.system()=='Darwin','AudioToolbox requires macOS')
class AudioBoundsTests(unittest.TestCase):
    def test_audio_errors_before_device_open(self):
        source=r'''
#include "vita_audio.h"
#include <assert.h>
int main(void){uint32_t r[16]={0},out=123;uint8_t m[64]={0};
 assert(!vx_audio_import(0,r,m,64,0x81000000,&out)&&out==123);
 r[0]=3;assert(vx_audio_import(0x5bc341e4,r,m,64,0x81000000,&out)&&out==0x8026000a);
 r[0]=0;r[1]=63;assert(vx_audio_import(0x5bc341e4,r,m,64,0x81000000,&out)&&out==0x80260006);
 r[1]=64;r[3]=2;assert(vx_audio_import(0x5bc341e4,r,m,64,0x81000000,&out)&&out==0x80260007);
 r[3]=0;r[2]=44100;assert(vx_audio_import(0x5bc341e4,r,m,64,0x81000000,&out)&&out==0x80260008);
 r[0]=4;assert(vx_audio_import(0x02db3f5f,r,m,64,0x81000000,&out)&&out==0x80260003);
 vx_audio_shutdown();return 0;}
'''
        with tempfile.TemporaryDirectory() as d:
            d=Path(d);(d/'test.c').write_text(source)
            subprocess.run(['clang','-std=c11','-Wall','-Wextra','-Werror','-I',str(ROOT/'runtime'),str(d/'test.c'),str(ROOT/'runtime/vita_audio.c'),'-framework','AudioToolbox','-o',str(d/'test')],check=True,capture_output=True)
            subprocess.run([str(d/'test')],check=True,capture_output=True,timeout=5)

    def test_buffered_ports_scaling_completion_and_drain(self):
        # The real bridge is linked against a deterministic AudioQueue provider.
        # This proves queue ownership/PCM handling, not physical device audibility.
        source=r'''
#include "vita_audio.h"
#include <AudioToolbox/AudioToolbox.h>
#include <assert.h>
#include <stdlib.h>
#include <string.h>
#include <pthread.h>
#include <time.h>
struct OpaqueAudioQueue {AudioQueueOutputCallback callback;void *user;AudioQueueBufferRef buffers[3];int count;int live[3];};
static AudioQueueRef queues[16];static unsigned nq,starts,pauses,disposed;static int fail_allocate,fail_enqueue,fail_start;
OSStatus AudioQueueNewOutput(const AudioStreamBasicDescription *f,AudioQueueOutputCallback c,void *u,CFRunLoopRef l,CFStringRef m,UInt32 flags,AudioQueueRef *out){
 (void)f;(void)l;(void)m;(void)flags;*out=calloc(1,sizeof **out);(*out)->callback=c;(*out)->user=u;queues[nq++]=*out;return 0;}
OSStatus AudioQueueAllocateBuffer(AudioQueueRef q,UInt32 n,AudioQueueBufferRef *out){
 if(fail_allocate){fail_allocate=0;return -1;}
 AudioQueueBuffer value={.mAudioDataBytesCapacity=n,.mAudioData=calloc(1,n)};
 *out=malloc(sizeof value);memcpy(*out,&value,sizeof value);q->buffers[q->count++]=*out;return 0;}
OSStatus AudioQueueEnqueueBuffer(AudioQueueRef q,AudioQueueBufferRef b,UInt32 n,const AudioStreamPacketDescription *p){
 (void)n;(void)p;if(fail_enqueue){fail_enqueue=0;return -1;}for(int i=0;i<q->count;i++)if(q->buffers[i]==b){assert(!q->live[i]);q->live[i]=1;return 0;}return -1;}
OSStatus AudioQueueStart(AudioQueueRef q,const AudioTimeStamp *t){(void)q;(void)t;starts++;if(fail_start){fail_start=0;return -1;}return 0;}
OSStatus AudioQueuePause(AudioQueueRef q){(void)q;pauses++;return 0;}
static void complete(AudioQueueRef q,int i){if(q->live[i]){q->live[i]=0;q->callback(q->user,q,q->buffers[i]);}}
OSStatus AudioQueueDispose(AudioQueueRef q,Boolean now){(void)now;disposed++;for(int i=0;i<q->count;i++){complete(q,i);free(q->buffers[i]->mAudioData);free(q->buffers[i]);}free(q);return 0;}
static void *finish_all(void *arg){struct timespec t={0,2000000};nanosleep(&t,0);AudioQueueRef q=arg;for(int i=0;i<q->count;i++)complete(q,i);return 0;}
static uint8_t memory[1024];static uint32_t r[16],out;
static uint32_t call(uint32_t n,uint32_t a,uint32_t b,uint32_t c,uint32_t d){r[0]=a;r[1]=b;r[2]=c;r[3]=d;assert(vx_audio_import(n,r,memory,sizeof memory,0x81000000,&out));return out;}
int main(void){
 const uint32_t base=0x81000000;uint32_t volume[2]={16384,32768};memcpy(memory+32,volume,8);
 for(int i=0;i<64;i++){int16_t pair[2]={32767,-32768};memcpy(memory+128+i*4,pair,4);}
 assert(call(0x5bc341e4,0,64,48000,1)==0);assert(call(0x5bc341e4,0,64,48000,1)==1);
 assert(!call(0x64167f11,0,3,base+32,0));
 for(int i=0;i<3;i++)assert(!call(0x02db3f5f,0,base+128,0,0));
 assert(call(0x9a5370c4,0,0,0,0)==192);
 vx_audio_set_nonblocking(1);assert(call(0x02db3f5f,0,base+128,0,0)==VX_AUDIO_WOULD_BLOCK);
 assert(call(0x02db3f5f,0,0,0,0)==VX_AUDIO_WOULD_BLOCK);vx_audio_set_nonblocking(0);
 const int16_t *pcm=queues[0]->buffers[0]->mAudioData;assert(pcm[0]==16383&&pcm[1]==-32768);
 assert(call(0x02db3f5f,0,base+1020,0,0)==0x80260004);
 assert(!call(0x02db3f5f,1,base+128,0,0));assert(call(0x9a5370c4,1,0,0,0)==64);
 vx_audio_pause(1);vx_audio_pause(1);assert(pauses==2);vx_audio_pause(0);assert(starts>=6);
 pthread_t worker;pthread_create(&worker,0,finish_all,queues[0]);assert(!call(0x02db3f5f,0,0,0,0));pthread_join(worker,0);
 assert(!call(0x9a5370c4,0,0,0,0));
 complete(queues[1],0);vx_audio_stats stats;vx_audio_get_stats(&stats);
 assert(stats.ports_opened==2&&stats.buffers_queued==4&&stats.buffers_completed==4&&stats.frames_completed==256&&!stats.timeouts);
 assert(!call(0x69e2e6b5,0,0,0,0));assert(!call(0x69e2e6b5,1,0,0,0));
 vx_audio_get_stats(&stats);assert(stats.buffers_completed==4);
 /* Release must cancel queued PCM without pretending it completed playback. */
 assert(call(0x5bc341e4,0,64,48000,1)==0);
 assert(!call(0x02db3f5f,0,base+128,0,0));
 memset(memory+128,0,256);assert(((int16_t *)queues[nq-1]->buffers[0]->mAudioData)[0]==32767);
 assert(!call(0x69e2e6b5,0,0,0,0));vx_audio_get_stats(&stats);
 assert(stats.buffers_queued==5&&stats.buffers_completed==4&&stats.frames_completed==256);
 /* Partial allocation, rejected submission and failed playback all dispose
    their queue and leave the same guest port available for reuse. */
 unsigned before=disposed;fail_allocate=1;assert(call(0x5bc341e4,0,64,48000,1)==0x80260001);assert(disposed==before+1);
 assert(call(0x5bc341e4,0,64,48000,1)==0);fail_enqueue=1;
 assert(call(0x02db3f5f,0,base+128,0,0)==0x80260001);vx_audio_get_stats(&stats);
 assert(stats.buffers_queued==5&&stats.buffers_completed==4);
 assert(call(0x5bc341e4,0,64,48000,1)==0);fail_start=1;
 assert(call(0x02db3f5f,0,base+128,0,0)==0x80260001);vx_audio_get_stats(&stats);
 assert(stats.buffers_queued==6&&stats.buffers_completed==4);
 assert(call(0x5bc341e4,0,64,48000,1)==0);assert(!call(0x69e2e6b5,0,0,0,0));
 vx_audio_shutdown();vx_audio_get_stats(&stats);assert(!stats.ports_opened&&!stats.buffers_queued&&!stats.buffers_completed);return 0;}
'''
        with tempfile.TemporaryDirectory() as d:
            d=Path(d);(d/'test.c').write_text(source)
            subprocess.run(['clang','-std=c11','-Wall','-Wextra','-Werror','-I',str(ROOT/'runtime'),str(d/'test.c'),str(ROOT/'runtime/vita_audio.c'),'-framework','AudioToolbox','-o',str(d/'test')],check=True,capture_output=True)
            subprocess.run([str(d/'test')],check=True,capture_output=True,timeout=5)
