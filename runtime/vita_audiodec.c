#include "vita_audiodec.h"
#include <libavcodec/avcodec.h>
#include <libavutil/mem.h>
#include <math.h>
#include <stdlib.h>
#include <string.h>

enum { AT9=0x1003, MP3, AAC, CELP, DECODERS=32, CONTEXT_BYTES=256 };
enum {
 AD_FAIL=0x807F0000, AD_TYPE, AD_INIT_PARAM, AD_INITIALIZED, AD_MEMORY,
 AD_NOT_INITIALIZED, AD_IN_USE, AD_NO_HANDLES, AD_POINTER, AD_HANDLE,
 AD_NOT_IN_USE, AD_CHANNELS, AD_WORD, AD_SIZE, AD_UNSUPPORTED,
 AD_FRAMES, AD_STREAMS, AD_DIFFERENT_TYPES, AD_SAME_HANDLES, AD_BUSY,
 AD_AT9_CONFIG=0x807F2000, AD_MP3_CHANNELS=0x807F2800, AD_MP3_VERSION,
 AD_AAC_CHANNELS=0x807F3000
};
enum { MAX_DECODE_SAMPLES=4096, MAX_BATCH_FRAMES=8 };
/* Wire structures are all little-endian 32-bit words, including guest pointers. */
typedef struct {
 uint32_t size,handle,es,input_es,max_es,pcm,output_pcm,max_pcm,word_length,info;
} guest_ctrl;
_Static_assert(sizeof(guest_ctrl)==40,"SceAudiodecCtrl ABI");

typedef struct {AVCodecContext *context; AVFrame *frame; AVPacket *packet;} decoder;
struct vx_atrac9 {
 decoder codec;
 uint8_t config[4];
 unsigned channels,rate,packet_bytes,samples,frames;
};
typedef struct {
 uint32_t handle,type,external,max_es,max_pcm;
 unsigned channels,version,adts,at9_read,at9_count;
 int error;
 decoder codec;
 vx_atrac9 *at9;
 int16_t at9_pcm[2048];
} dec_slot;
typedef struct {uint8_t *mem;size_t size;uint32_t base;} guest_memory;

static _Thread_local dec_slot slots[DECODERS];
static _Thread_local unsigned library_limits[3];
static _Thread_local uint32_t next_handle=0x72000000;
extern int vn_guest_write_allowed(const uint8_t *,size_t);

static void close_decoder(decoder *codec){
 av_packet_free(&codec->packet);
 av_frame_free(&codec->frame);
 avcodec_free_context(&codec->context);
}
static int open_decoder(decoder *codec,enum AVCodecID id,unsigned rate,unsigned channels,
                        unsigned align,const uint8_t *config,unsigned config_size){
 const AVCodec *impl=avcodec_find_decoder(id);
 if(!impl)return AVERROR_DECODER_NOT_FOUND;
 int error=AVERROR(ENOMEM);
 codec->context=avcodec_alloc_context3(impl);
 codec->frame=av_frame_alloc();
 codec->packet=av_packet_alloc();
 if(!codec->context||!codec->frame||!codec->packet)goto fail;
 AVCodecContext *context=codec->context;
 context->thread_count=1;
 context->max_samples=MAX_DECODE_SAMPLES;
 context->sample_rate=(int)rate;
 context->block_align=(int)align;
 if(channels)av_channel_layout_default(&context->ch_layout,(int)channels);
 if(config_size){
  context->extradata=av_mallocz(config_size+AV_INPUT_BUFFER_PADDING_SIZE);
  if(!context->extradata)goto fail;
  memcpy(context->extradata,config,config_size);
  context->extradata_size=(int)config_size;
 }
 error=avcodec_open2(context,impl,NULL);
 if(error<0)goto fail;
 return 0;
fail:
 close_decoder(codec);
 return error;
}
static int16_t float_pcm(float sample){
 if(!isfinite(sample))return 0;
 if(sample<=-1.f)return INT16_MIN;
 if(sample>=32767.f/32768.f)return INT16_MAX;
 return (int16_t)lrintf(sample*32768.f);
}
static int copy_frame(const AVFrame *frame,unsigned channels,int16_t *output,size_t capacity){
 size_t samples=(size_t)frame->nb_samples*channels;
 if(frame->nb_samples<0||frame->ch_layout.nb_channels!=(int)channels||
    samples>capacity||(!frame->extended_data&&samples))return AVERROR_INVALIDDATA;
 switch(frame->format){
 case AV_SAMPLE_FMT_S16:
  memcpy(output,frame->extended_data[0],samples*sizeof *output);
  break;
 case AV_SAMPLE_FMT_S16P:
 case AV_SAMPLE_FMT_FLTP:
  for(unsigned c=0;c<channels;c++){
   const uint8_t *plane=frame->extended_data[c];
   for(int i=0;i<frame->nb_samples;i++)
    output[(size_t)i*channels+c]=frame->format==AV_SAMPLE_FMT_FLTP?
        float_pcm(((const float *)plane)[i]):((const int16_t *)plane)[i];
  }
  break;
 case AV_SAMPLE_FMT_FLT:
  for(size_t i=0;i<samples;i++)output[i]=float_pcm(((const float *)frame->extended_data[0])[i]);
  break;
 default:return AVERROR(ENOSYS);
 }
 return (int)samples;
}
static int decode_packet(decoder *codec,unsigned channels,const uint8_t *input,size_t bytes,
                         int16_t *output,size_t capacity){
 if(!bytes||bytes>8192)return AVERROR(EINVAL);
 int error=av_new_packet(codec->packet,(int)bytes);
 if(error<0)return error;
 memcpy(codec->packet->data,input,bytes);
 error=avcodec_send_packet(codec->context,codec->packet);
 av_packet_unref(codec->packet);
 if(error<0)return error;
 size_t written=0;
 while((error=avcodec_receive_frame(codec->context,codec->frame))>=0){
  int count=copy_frame(codec->frame,channels,output+written,capacity-written);
  av_frame_unref(codec->frame);
  if(count<0)return count;
  written+=(size_t)count;
 }
 return error==AVERROR(EAGAIN)?(int)written:error;
}
static int open_at9(vx_atrac9 *codec){
 uint8_t extradata[12]={1,0,0,0};
 memcpy(extradata+4,codec->config,4);
 return open_decoder(&codec->codec,AV_CODEC_ID_ATRAC9,0,0,codec->packet_bytes,extradata,sizeof extradata);
}
vx_atrac9 *vx_atrac9_create(const uint8_t config[4],unsigned *channels,unsigned *rate,
                           unsigned *packet_bytes,unsigned *samples){
 if(!config||config[0]!=0xfe||(config[1]&1)||(config[1]&0xe)>4||(config[3]&8))return NULL;
 static const unsigned sample_per_frame[]={64,64,128,128,128,256,256,256};
 vx_atrac9 *codec=calloc(1,sizeof *codec);
 if(!codec)return NULL;
 codec->frames=1u<<((config[3]>>3)&3);
 unsigned frame_bytes=((config[2]<<3)|(config[3]>>5))+1u;
 codec->packet_bytes=frame_bytes*codec->frames;
 codec->samples=sample_per_frame[(config[1]>>4)%8]*codec->frames;
 memcpy(codec->config,config,4);
 if(open_at9(codec)<0){free(codec);return NULL;}
 codec->channels=(unsigned)codec->codec.context->ch_layout.nb_channels;
 codec->rate=(unsigned)codec->codec.context->sample_rate;
 if(!codec->channels||codec->channels>2||!codec->rate){
  vx_atrac9_destroy(codec);
  return NULL;
 }
 if(channels)*channels=codec->channels;
 if(rate)*rate=codec->rate;
 if(packet_bytes)*packet_bytes=codec->packet_bytes;
 if(samples)*samples=codec->samples;
 return codec;
}
void vx_atrac9_destroy(vx_atrac9 *codec){
 if(!codec)return;
 close_decoder(&codec->codec);
 free(codec);
}
void vx_atrac9_clear(vx_atrac9 *codec){
 if(!codec)return;
 close_decoder(&codec->codec);
 /* Reopening also discards ATRAC overlap history and partial frame state. */
 open_at9(codec);
}
int vx_atrac9_decode(vx_atrac9 *codec,const uint8_t *input,size_t bytes,int16_t *output,size_t capacity){
 if(!codec||!codec->codec.context||!input||!output||bytes!=codec->packet_bytes||
    capacity<codec->channels*codec->samples)return AVERROR(EINVAL);
 return decode_packet(&codec->codec,codec->channels,input,bytes,output,capacity);
}

static uint8_t *span(guest_memory memory,uint32_t ptr,size_t length,int write){
 if(!ptr||ptr<memory.base||(uint64_t)(ptr-memory.base)+length>memory.size)return NULL;
 uint8_t *result=memory.mem+(ptr-memory.base);
 return !write||vn_guest_write_allowed(result,length)?result:NULL;
}
static uint8_t *control(guest_memory m,uint32_t ptr,guest_ctrl *ctrl,int write){
 uint8_t *address=span(m,ptr,sizeof *ctrl,write);
 if(!address||ptr%4)return NULL;
 memcpy(ctrl,address,sizeof *ctrl);
 return ctrl->size==sizeof *ctrl?address:NULL;
}
static dec_slot *find_slot(uint32_t handle){
 if(handle)for(size_t i=0;i<DECODERS;i++)if(slots[i].handle==handle)return &slots[i];
 return NULL;
}
static void delete_slot(dec_slot *slot){
 vx_atrac9_destroy(slot->at9);
 close_decoder(&slot->codec);
 *slot=(dec_slot){0};
}
void vx_audiodec_shutdown(void){
 for(size_t i=0;i<DECODERS;i++)if(slots[i].handle)delete_slot(&slots[i]);
 memset(library_limits,0,sizeof library_limits);
}
static uint32_t library(uint32_t type,uint32_t ptr,int init,guest_memory memory){
 if(type==CELP)return AD_UNSUPPORTED;
 if(type<AT9||type>AAC)return AD_TYPE;
 unsigned *limit=&library_limits[type-AT9];
 if(!init){
  if(!*limit)return AD_NOT_INITIALIZED;
  for(size_t i=0;i<DECODERS;i++)if(slots[i].handle&&slots[i].type==type)delete_slot(&slots[i]);
  *limit=0;
  return 0;
 }
 if(*limit)return AD_INITIALIZED;
 uint32_t words[2];
 uint8_t *data=span(memory,ptr,sizeof words,0);
 if(!data||ptr%4)return AD_POINTER;
 memcpy(words,data,sizeof words);
 if(words[0]!=sizeof words||!words[1]||words[1]>(type==AT9?16u:8u))return AD_INIT_PARAM;
 *limit=words[1];
 return 0;
}
static int aac_rate_index(unsigned rate){
 static const unsigned rates[]={96000,88200,64000,48000,44100,32000,24000,22050,16000,12000,11025,8000,7350};
 for(unsigned i=0;i<sizeof rates/sizeof *rates;i++)if(rates[i]==rate)return (int)i;
 return -1;
}
static uint32_t configure_codec(dec_slot *slot,uint32_t info[7]){
 if(slot->type==AT9){
  unsigned samples,rate;
  slot->at9=vx_atrac9_create((const uint8_t *)&info[1],&slot->channels,&rate,&slot->max_es,&samples);
  if(!slot->at9)return AD_AT9_CONFIG;
  slot->max_pcm=samples/slot->at9->frames*slot->channels*sizeof(int16_t);
  info[2]=slot->channels;
  info[3]=(uint32_t)((uint64_t)slot->max_es*8*rate/samples);
  info[4]=rate;info[5]=slot->max_es;info[6]=slot->at9->frames;
  return 0;
 }
 slot->channels=info[slot->type==MP3?1:2];
 if(!slot->channels||slot->channels>2)return slot->type==MP3?AD_MP3_CHANNELS:AD_AAC_CHANNELS;
 int error;
 if(slot->type==MP3){
  slot->version=info[2];
  if(slot->version!=0&&slot->version!=2&&slot->version!=3)return AD_MP3_VERSION;
  slot->max_es=1441;
  slot->max_pcm=(slot->version==3?1152:576)*slot->channels*sizeof(int16_t);
  error=open_decoder(&slot->codec,AV_CODEC_ID_MP3,0,slot->channels,0,NULL,0);
 }else{
  int rate=aac_rate_index(info[3]);
  if(rate<0||info[1]>1||info[4]>1)return AD_INIT_PARAM;
  slot->adts=info[1];
  slot->max_es=1536+(slot->adts?256:0);
  slot->max_pcm=1024*(info[4]?2:1)*slot->channels*sizeof(int16_t);
  uint8_t config[4]={(uint8_t)(0x10|(rate>>1)),(uint8_t)((rate<<7)|(slot->channels<<3))};
  unsigned config_size=slot->adts?0:2;
  if(!slot->adts&&info[4]){
   int sbr_rate=aac_rate_index(info[3]*2);
   if(sbr_rate<0)return AD_INIT_PARAM;
   /* HE-AAC: SBR object followed by the extension rate and AAC-LC object. */
   uint32_t asc=(5u<<27)|((unsigned)rate<<23)|(slot->channels<<19)|
                ((unsigned)sbr_rate<<15)|(2u<<10);
   config[0]=(uint8_t)(asc>>24);config[1]=(uint8_t)(asc>>16);
   config[2]=(uint8_t)(asc>>8);config[3]=(uint8_t)asc;
   config_size=4;
  }
  error=open_decoder(&slot->codec,AV_CODEC_ID_AAC,info[3],slot->channels,0,config,config_size);
 }
 return error<0?AD_FAIL:0;
}
static int overlaps(uint32_t a,size_t an,uint32_t b,size_t bn){
 return (uint64_t)a+an>b&&(uint64_t)b+bn>a;
}
static uint32_t create(uint32_t ptr,uint32_t type,uint32_t external,uint32_t external_size,
                       int query,guest_memory memory){
 if(type==CELP)return AD_UNSUPPORTED;
 if(type<AT9||type>AAC)return AD_TYPE;
 guest_ctrl ctrl;
 uint8_t *control_address=control(memory,ptr,&ctrl,!query);
 if(!control_address)return AD_POINTER;
 if(ctrl.word_length!=16)return AD_WORD;
 unsigned info_size=type==AT9?28:type==MP3?12:20;
 uint8_t *info_address=span(memory,ctrl.info,info_size,!query&&type==AT9);
 if(!info_address||ctrl.info%4||overlaps(ptr,sizeof ctrl,ctrl.info,info_size))return AD_POINTER;
 uint32_t info[7]={0};
 memcpy(info,info_address,info_size);
 if(info[0]<info_size||info[0]>28)return AD_SIZE;
 if(query)return CONTEXT_BYTES;
 if(!library_limits[type-AT9]&&!external)return AD_NOT_INITIALIZED;
 if(find_slot(ctrl.handle))return AD_IN_USE;
 if(external&&((external%CONTEXT_BYTES)||external_size<CONTEXT_BYTES||
     !span(memory,external,external_size,1)||overlaps(ptr,sizeof ctrl,external,external_size)||
     overlaps(ctrl.info,info_size,external,external_size)))return AD_POINTER;
 dec_slot *available=NULL;
 unsigned in_use=0;
 for(size_t i=0;i<DECODERS;i++){
  dec_slot *slot=&slots[i];
  if(!slot->handle){if(!available)available=slot;continue;}
  if(external&&slot->external==external)return AD_IN_USE;
  if(slot->type==type&&!slot->external)in_use+=type==AT9?slot->channels:1;
 }
 if(!available)return AD_NO_HANDLES;
 available->type=type;
 uint32_t status=configure_codec(available,info);
 if(!status&&!external&&in_use+(type==AT9?available->channels:1)>library_limits[type-AT9])
  status=type==AT9?AD_CHANNELS:AD_NO_HANDLES;
 if(status){delete_slot(available);return status;}
 available->external=external;
 available->handle=++next_handle;
 if(next_handle==0x73000000)next_handle=0x72000000;
 ctrl.handle=available->handle;
 ctrl.max_es=available->max_es;
 ctrl.max_pcm=available->max_pcm;
 ctrl.input_es=ctrl.output_pcm=0;
 memcpy(control_address,&ctrl,sizeof ctrl);
 if(type==AT9)memcpy(info_address,info,info_size);
 return 0;
}

static size_t mpeg_packet_size(const uint8_t *data,size_t available,unsigned version){
 static const unsigned v1[]={0,32,40,48,56,64,80,96,112,128,160,192,224,256,320};
 static const unsigned v2[]={0,8,16,24,32,40,48,56,64,80,96,112,128,144,160};
 static const unsigned rates[]={44100,48000,32000};
 if(available<4||data[0]!=0xff||(data[1]&0xe0)!=0xe0||
    ((data[1]>>3)&3)!=version||((data[1]>>1)&3)!=1)return 0;
 unsigned bitrate=data[2]>>4,rate=(data[2]>>2)&3;
 if(!bitrate||bitrate==15||rate==3)return 0;
 unsigned divisor=version==3?1:version==2?2:4;
 unsigned denominator=rates[rate]/divisor;
 return (version==3?144000u*v1[bitrate]:72000u*v2[bitrate])/denominator+((data[2]>>1)&1);
}
static size_t aac_packet_size(const uint8_t *data,size_t available){
 if(available<7||data[0]!=0xff||(data[1]&0xf6)!=0xf0)return 0;
 size_t length=((data[3]&3u)<<11)|(data[4]<<3)|(data[5]>>5);
 return length>=(data[1]&1?7u:9u)?length:0;
}
static size_t read_bound(guest_memory m,uint32_t ptr,size_t capacity){
 if(!ptr||ptr<m.base||ptr-m.base>=m.size)return 0;
 size_t available=m.size-(ptr-m.base);
 return available<capacity?available:capacity;
}
static int frame_decode(dec_slot *slot,const uint8_t *es,size_t avail,size_t raw_bytes,
                        int16_t *out,size_t capacity,size_t *consumed){
 *consumed=0;
 if(slot->at9){
  if(slot->at9_read==slot->at9_count){
   size_t bytes=slot->at9->packet_bytes;
   if(!es||bytes>avail)return AVERROR(EINVAL);
   int elements=vx_atrac9_decode(slot->at9,es,bytes,slot->at9_pcm,
                                sizeof slot->at9_pcm/sizeof *slot->at9_pcm);
   if(elements<0)return elements;
   if((unsigned)elements!=slot->at9->samples*slot->channels)return AVERROR_INVALIDDATA;
   slot->at9_read=0;
   slot->at9_count=(unsigned)elements;
   *consumed=bytes;
  }
  size_t frame_elements=slot->max_pcm/sizeof(int16_t);
  if(capacity<frame_elements||slot->at9_count-slot->at9_read<frame_elements)
   return AVERROR(EINVAL);
  memcpy(out,slot->at9_pcm+slot->at9_read,slot->max_pcm);
  slot->at9_read+=(unsigned)frame_elements;
  return (int)frame_elements;
 }
 if(!es||!avail)return AVERROR(EINVAL);
 size_t bytes=slot->type==MP3?mpeg_packet_size(es,avail,slot->version):
              slot->adts?aac_packet_size(es,avail):raw_bytes;
 if(!bytes||bytes>avail)return AVERROR_INVALIDDATA;
 int elements=decode_packet(&slot->codec,slot->channels,es,bytes,out,capacity);
 if(elements>=0)*consumed=bytes;
 return elements;
}
static uint32_t decode_guest(dec_slot *slot,guest_ctrl *ctrl,uint8_t *control_address,
                             uint32_t ptr,unsigned frames,unsigned skip,unsigned requested,
                             guest_memory m){
 if(!frames||frames>(slot->at9?MAX_BATCH_FRAMES:1u))return AD_FRAMES;
 if(ctrl->word_length!=16)return AD_WORD;
 if(!ctrl->max_es||ctrl->max_es>slot->max_es||ctrl->max_pcm<slot->max_pcm)return AD_SIZE;
 size_t frame_samples=slot->max_pcm/(sizeof(int16_t)*slot->channels);
 size_t max_output=(size_t)frames*slot->max_pcm;
 size_t output_check=requested?(size_t)(skip+requested)*slot->channels*sizeof(int16_t):max_output;
 uint8_t *out=span(m,ctrl->pcm,output_check,1);
 if(!out||ctrl->pcm%2||overlaps(ctrl->pcm,output_check,ptr,sizeof *ctrl))return AD_POINTER;
 int16_t pcm[MAX_DECODE_SAMPLES];
 size_t total_bytes=0,total_elements=0;
 size_t input_capacity=(size_t)ctrl->max_es*frames;
 size_t available=read_bound(m,ctrl->es,input_capacity);
 size_t raw_bytes=ctrl->input_es&&ctrl->input_es<=ctrl->max_es?ctrl->input_es:ctrl->max_es;
 const uint8_t *input=available?m.mem+(ctrl->es-m.base):NULL;
 for(unsigned i=0;i<frames;i++){
  size_t consumed=0;
  int got=frame_decode(slot,input?input+total_bytes:NULL,available-total_bytes,
                       raw_bytes,pcm+total_elements,sizeof pcm/sizeof *pcm-total_elements,&consumed);
  slot->error=got<0?got:0;
  if(got<0){
   /* Do not lose the stream offset when earlier packets in a batch decoded. */
   ctrl->input_es=(uint32_t)total_bytes;
   ctrl->output_pcm=0;
   memcpy(control_address,ctrl,sizeof *ctrl);
   return AD_FAIL;
  }
  total_bytes+=consumed;
  total_elements+=(size_t)got;
 }
 size_t first=(size_t)skip*slot->channels;
 size_t written=requested?(size_t)requested*slot->channels:total_elements;
 if(first+written>total_elements||total_elements>frame_samples*frames*slot->channels)return AD_FAIL;
 memcpy(out+first*sizeof(int16_t),pcm+first,written*sizeof(int16_t));
 ctrl->input_es=(uint32_t)total_bytes;
 ctrl->output_pcm=(uint32_t)(written*sizeof(int16_t));
 memcpy(control_address,ctrl,sizeof *ctrl);
 return 0;
}
static uint32_t decode_streams(guest_memory m,uint32_t ptr,unsigned count){
 if(!count||count>6)return AD_STREAMS;
 uint8_t *array=span(m,ptr,count*sizeof(uint32_t),0);
 if(!array||ptr%4)return AD_POINTER;
 uint32_t addresses[6];
 memcpy(addresses,array,count*sizeof *addresses);
 guest_ctrl controls[6];
 uint8_t *destination[6];
 dec_slot *streams[6];
 for(unsigned i=0;i<count;i++){
  destination[i]=control(m,addresses[i],&controls[i],1);
  if(!destination[i])return AD_POINTER;
  streams[i]=find_slot(controls[i].handle);
  if(!streams[i])return AD_HANDLE;
  if(i&&streams[i]->type!=streams[0]->type)return AD_DIFFERENT_TYPES;
  for(unsigned j=0;j<i;j++)if(streams[j]==streams[i])return AD_SAME_HANDLES;
 }
 for(unsigned i=0;i<count;i++){
  uint32_t status=decode_guest(streams[i],&controls[i],destination[i],addresses[i],1,0,0,m);
  if(status)return status;
 }
 return 0;
}
int vx_audiodec_import(uint32_t nid,const uint32_t r[16],uint8_t *mem,size_t size,
                       uint32_t base,uint32_t *result){
 guest_memory m={.mem=mem,.size=size,.base=base};
 switch(nid){
 case 0x445c2cef: *result=library(r[0],r[1],1,m);return 1;
 case 0x45719b9d: *result=library(r[0],0,0,m);return 1;
 case 0xdb712abc: *result=create(r[0],r[1],0,0,1,m);return 1;
 case 0x4dfd3aaa: *result=create(r[0],r[1],0,0,0,m);return 1;
 case 0x56085dfb: *result=r[2]?create(r[0],r[1],r[2],r[3],0,m):AD_POINTER;return 1;
 case 0x68f4a9cb: *result=decode_streams(m,r[0],r[1]);return 1;
 case 0xf72f9b64:case 0xccdaba04:case 0x8018aa9b:case 0xe7a24e16:
 case 0xe4ea05bb:case 0x883b0cf5:case 0x2742e642:break;
 default:return 0;
 }
 guest_ctrl ctrl;
 uint8_t *address=control(m,r[0],&ctrl,nid!=0x883b0cf5);
 if(!address){*result=AD_POINTER;return 1;}
 dec_slot *slot=find_slot(ctrl.handle);
 if(!slot){*result=ctrl.handle?AD_NOT_IN_USE:AD_HANDLE;return 1;}
 *result=0;
 switch(nid){
 case 0xf72f9b64:
  if(slot->at9){
   vx_atrac9_clear(slot->at9);
   if(!slot->at9->codec.context){*result=AD_MEMORY;break;}
   slot->at9_read=slot->at9_count=0;
  }else avcodec_flush_buffers(slot->codec.context);
  slot->error=0;
  break;
 case 0xccdaba04:case 0x8018aa9b:
  *result=decode_guest(slot,&ctrl,address,r[0],nid==0xccdaba04?1:r[1],0,0,m);
  break;
 case 0x2742e642:{
  if(!slot->at9){*result=AD_UNSUPPORTED;break;}
  unsigned frame_samples=slot->max_pcm/(sizeof(int16_t)*slot->channels);
  uint64_t end=(uint64_t)r[1]+r[2];
  if(!r[2]||end>MAX_BATCH_FRAMES*frame_samples){*result=AD_FRAMES;break;}
  unsigned frames=(unsigned)((end+frame_samples-1)/frame_samples);
  *result=decode_guest(slot,&ctrl,address,r[0],frames,r[1],r[2],m);
  break;
 }
 case 0xe7a24e16:case 0xe4ea05bb:{
  if((nid==0xe4ea05bb)!=!!slot->external){*result=AD_HANDLE;break;}
  if(slot->external){
   uint8_t *out=span(m,r[1],sizeof slot->external,1);
   if(!out||r[1]%4||overlaps(r[0],sizeof ctrl,r[1],sizeof slot->external)){*result=AD_POINTER;break;}
   memcpy(out,&slot->external,sizeof slot->external);
  }
  delete_slot(slot);
  ctrl.handle=0;
  memcpy(address,&ctrl,sizeof ctrl);
  break;
 }
 case 0x883b0cf5:{
  uint8_t *out=span(m,r[1],sizeof(int32_t),1);
  if(!out||r[1]%4){*result=AD_POINTER;break;}
  int32_t error=slot->error;
  memcpy(out,&error,sizeof error);
  break;
 }
 }
 return 1;
}
