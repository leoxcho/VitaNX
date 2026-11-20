#define _POSIX_C_SOURCE 200809L
#include "vita_audio.h"
#include <AudioToolbox/AudioToolbox.h>
#include <pthread.h>
#include <string.h>
#include <time.h>
#include <errno.h>
#define NOT_OPENED UINT32_C(0x80260001)
#define INVALID_PORT UINT32_C(0x80260003)
#define INVALID_POINTER UINT32_C(0x80260004)
#define PORT_FULL UINT32_C(0x80260005)
#define INVALID_SIZE UINT32_C(0x80260006)
#define INVALID_FORMAT UINT32_C(0x80260007)
#define INVALID_FREQ UINT32_C(0x80260008)
#define INVALID_VOLUME UINT32_C(0x80260009)
#define INVALID_TYPE UINT32_C(0x8026000A)
#define NO_MEMORY UINT32_C(0x8026000D)
/* ABI references: installed VitaSDK audioout.h and db/360/SceAudio.yml. */
enum {BUFFER_COUNT=3};
typedef struct {
 AudioQueueRef queue;AudioQueueBufferRef buffers[BUFFER_COUNT];pthread_mutex_t mutex;
 pthread_cond_t condition;int ready,closing;unsigned free_mask,queued;uint32_t length,frequency,channels;
 int32_t volume[2];vx_audio_stats stats;
} port;
static _Thread_local port ports[4];
static _Thread_local vx_audio_stats history;
static _Thread_local int paused,nonblocking;
void vx_audio_set_nonblocking(int enabled){nonblocking=!!enabled;}
static void finished(void *user,AudioQueueRef queue,AudioQueueBufferRef buffer){
 (void)queue;port *p=user;
 pthread_mutex_lock(&p->mutex);
 for(unsigned i=0;i<BUFFER_COUNT;i++)if(p->buffers[i]==buffer&&!(p->free_mask&(1u<<i))){
  p->free_mask|=1u<<i;if(p->queued)p->queued--;
  /* A disposal callback makes a buffer reusable but does not prove playback. */
  if(!p->closing){p->stats.buffers_completed++;p->stats.frames_completed+=p->length;}break;
 }
 pthread_cond_signal(&p->condition);pthread_mutex_unlock(&p->mutex);
}
static void add_stats(vx_audio_stats *to,const vx_audio_stats *from){
 to->ports_opened+=from->ports_opened;to->buffers_queued+=from->buffers_queued;to->buffers_completed+=from->buffers_completed;
 to->frames_queued+=from->frames_queued;to->frames_completed+=from->frames_completed;to->timeouts+=from->timeouts;
}
static void release(port *p){
 /* Immediate disposal cancels pending buffers. Mark before the synchronous
    call so callbacks racing with teardown cannot report canceled PCM as done.
    Apple AudioQueueDispose guarantees no callbacks after it returns. */
 if(p->ready){pthread_mutex_lock(&p->mutex);p->closing=1;pthread_mutex_unlock(&p->mutex);}
 if(p->queue)AudioQueueDispose(p->queue,true);
 if(p->ready){add_stats(&history,&p->stats);pthread_cond_destroy(&p->condition);pthread_mutex_destroy(&p->mutex);}
 memset(p,0,sizeof *p);
}
void vx_audio_get_stats(vx_audio_stats *out){
 if(!out)return;*out=history;
 for(unsigned i=0;i<4;i++)if(ports[i].ready){pthread_mutex_lock(&ports[i].mutex);add_stats(out,&ports[i].stats);pthread_mutex_unlock(&ports[i].mutex);}
}
void vx_audio_pause(int value){
 value=!!value;if(paused==value)return;paused=value;
 for(unsigned i=0;i<4;i++)if(ports[i].queue){if(value)AudioQueuePause(ports[i].queue);else AudioQueueStart(ports[i].queue,NULL);}
}
void vx_audio_shutdown(void){for(unsigned i=0;i<4;i++)release(&ports[i]);memset(&history,0,sizeof history);paused=nonblocking=0;}
static int wait_buffer(port *p,int drain){
 struct timespec limit;if(clock_gettime(CLOCK_REALTIME,&limit))return -1;
 /* Account for long valid voice-port buffers instead of a fixed short timeout. */
 limit.tv_sec+=(time_t)(((uint64_t)p->length*BUFFER_COUNT+p->frequency-1)/p->frequency+2);
 pthread_mutex_lock(&p->mutex);int error=0;
 while((drain?p->queued!=0:p->free_mask==0)&&!error)error=pthread_cond_timedwait(&p->condition,&p->mutex,&limit);
 if(error)p->stats.timeouts++;
 pthread_mutex_unlock(&p->mutex);return error?-1:0;
}
static int range(uint32_t a,size_t n,size_t size,uint32_t base){return a>=base&&(uint64_t)a-base<=size&&n<=size-((uint64_t)a-base);}
static uint32_t read32(const uint8_t *p){return (uint32_t)p[0]|(uint32_t)p[1]<<8|(uint32_t)p[2]<<16|(uint32_t)p[3]<<24;}
int vx_audio_import(uint32_t nid,uint32_t r[16],uint8_t *mem,size_t size,uint32_t base,uint32_t *out){
 if(!r||!out)return 0;
 uint32_t result;
 switch(nid){
 case UINT32_C(0x5BC341E4):{
  if(r[0]>2){result=INVALID_TYPE;break;}
  if(r[1]<64||r[1]>65472||r[1]%64){result=INVALID_SIZE;break;}
  if(r[3]>1){result=INVALID_FORMAT;break;}
  uint32_t freq=r[2];
  if((r[0]==0&&freq!=48000)||(freq!=8000&&freq!=11025&&freq!=12000&&freq!=16000&&freq!=22050&&freq!=24000&&freq!=32000&&freq!=44100&&freq!=48000)){result=INVALID_FREQ;break;}
  unsigned i;for(i=0;i<4;i++)if(!ports[i].queue)break;
  if(i==4){result=PORT_FULL;break;}
  port *p=&ports[i];p->length=r[1];p->frequency=freq;p->channels=r[3]+1;p->volume[0]=p->volume[1]=32768;
  if(pthread_mutex_init(&p->mutex,NULL)){memset(p,0,sizeof *p);result=NO_MEMORY;break;}
  if(pthread_cond_init(&p->condition,NULL)){pthread_mutex_destroy(&p->mutex);memset(p,0,sizeof *p);result=NO_MEMORY;break;}
  p->ready=1;
  AudioStreamBasicDescription format={0};format.mSampleRate=freq;format.mFormatID=kAudioFormatLinearPCM;
  format.mFormatFlags=kAudioFormatFlagIsSignedInteger|kAudioFormatFlagIsPacked;
  format.mFramesPerPacket=1;format.mChannelsPerFrame=p->channels;format.mBitsPerChannel=16;
  format.mBytesPerFrame=format.mBytesPerPacket=p->channels*2;
  OSStatus status=AudioQueueNewOutput(&format,finished,p,NULL,NULL,0,&p->queue);
  for(unsigned j=0;j<BUFFER_COUNT&&!status;j++)status=AudioQueueAllocateBuffer(p->queue,p->length*p->channels*2,&p->buffers[j]);
  if(status){release(p);result=NOT_OPENED;break;}
  p->free_mask=(1u<<BUFFER_COUNT)-1;p->stats.ports_opened=1;result=i;break;
 }
 case UINT32_C(0x69E2E6B5):
  if(r[0]>=4||!ports[r[0]].queue){result=INVALID_PORT;break;}
  release(&ports[r[0]]);result=0;break;
 case UINT32_C(0x9A5370C4):{
  if(r[0]>=4||!ports[r[0]].queue){result=INVALID_PORT;break;}
  port *p=&ports[r[0]];pthread_mutex_lock(&p->mutex);result=p->queued*p->length;pthread_mutex_unlock(&p->mutex);break;
 }
 case UINT32_C(0x9C8EDAEA):{
  if(r[0]>=4||!ports[r[0]].queue){result=INVALID_PORT;break;}
  port *p=&ports[r[0]];
  result=r[1]==0?p->length:r[1]==1?p->frequency:r[1]==2?p->channels-1:UINT32_C(0x8026000C);break;
 }
 case UINT32_C(0x64167F11):{
  if(r[0]>=4||!ports[r[0]].queue){result=INVALID_PORT;break;}
  if(!r[1]||(r[1]&~3u)){result=INVALID_VOLUME;break;}
  if(!mem||!r[2]||!range(r[2],8,size,base)){result=INVALID_POINTER;break;}
  port *p=&ports[r[0]];const uint8_t *v=mem+(r[2]-base);
  int32_t volumes[2]={(int32_t)read32(v),(int32_t)read32(v+4)};
  if(((r[1]&1)&&(volumes[0]<0||volumes[0]>32768))||((r[1]&2)&&(volumes[1]<0||volumes[1]>32768))){result=INVALID_VOLUME;break;}
  for(unsigned i=0;i<2;i++)if(r[1]&(1u<<i))p->volume[i]=volumes[i];
  result=0;break;
 }
 case UINT32_C(0x02DB3F5F):{
  if(r[0]>=4||!ports[r[0]].queue){result=INVALID_PORT;break;}
  port *p=&ports[r[0]];size_t bytes=p->length*p->channels*2;
  if(r[1]&&(!mem||!range(r[1],bytes,size,base))){result=INVALID_POINTER;break;}
  pthread_mutex_lock(&p->mutex);int pending=nonblocking&&(r[1]?p->free_mask==0:p->queued!=0);pthread_mutex_unlock(&p->mutex);
  if(pending){result=VX_AUDIO_WOULD_BLOCK;break;}
  if(!r[1]){if(wait_buffer(p,1)){release(p);result=NOT_OPENED;}else result=0;break;}
  if(!mem||!range(r[1],bytes,size,base)){result=INVALID_POINTER;break;}
  if(wait_buffer(p,0)){release(p);result=NOT_OPENED;break;}
  pthread_mutex_lock(&p->mutex);unsigned index=0;while(index<BUFFER_COUNT&&!(p->free_mask&(1u<<index)))index++;
  if(index==BUFFER_COUNT){pthread_mutex_unlock(&p->mutex);result=NOT_OPENED;break;}
  p->free_mask&=~(1u<<index);p->queued++;
  pthread_mutex_unlock(&p->mutex);AudioQueueBufferRef buffer=p->buffers[index];
  const uint8_t *source=mem+(r[1]-base);uint8_t *target=buffer->mAudioData;
  for(uint32_t i=0;i<p->length*p->channels;i++){
   int16_t sample=(int16_t)((uint16_t)source[i*2]|(uint16_t)source[i*2+1]<<8);
   int16_t scaled=(int16_t)((int32_t)sample*p->volume[i%p->channels]/32768);
   target[i*2]=(uint8_t)scaled;target[i*2+1]=(uint8_t)((uint16_t)scaled>>8);
  }
  buffer->mAudioDataByteSize=(UInt32)bytes;
  OSStatus status=AudioQueueEnqueueBuffer(p->queue,buffer,0,NULL);
  if(!status){pthread_mutex_lock(&p->mutex);p->stats.buffers_queued++;p->stats.frames_queued+=p->length;pthread_mutex_unlock(&p->mutex);}
  if(!status&&!paused)status=AudioQueueStart(p->queue,NULL);
  if(status){release(p);result=NOT_OPENED;break;}
  result=0;break;
 }
 default:return 0;
 }
 *out=result;return 1;
}
