#include "vita_gxm.h"
#include "vita_metal.h"
#include <string.h>
#include <limits.h>
#include <stdlib.h>
#include <math.h>
/* ABI/enums/NIDs: installed VitaSDK gxm.h and db/360/SceGxm.yml.
   Scene submission and display callbacks share guest sync objects; tiled layouts and color keys reject;
   successful transfers have completed GPU work and guest readback. */
#define G_UNINITIALIZED UINT32_C(0x805B0000)
#define G_INITIALIZED UINT32_C(0x805B0001)
#define G_MEMORY UINT32_C(0x805B0002)
#define G_VALUE UINT32_C(0x805B0003)
#define G_POINTER UINT32_C(0x805B0004)
#define G_ALIGNMENT UINT32_C(0x805B0005)
#define G_UNSUPPORTED UINT32_C(0x805B0009)
#define G_DRIVER UINT32_C(0x805B0017)
enum { GPU_READ=1, GPU_WRITE=2, FRAGMENT_USSE=4, VERTEX_USSE=8 };
typedef struct {uint32_t base,size,attr;} mapping;
static _Thread_local mapping maps[32];
static _Thread_local int initialized;
static _Thread_local vx_metal *transfer;
static _Thread_local vx_gxm_stats stats;
static _Thread_local vx_gxm_readiness readiness;
static _Thread_local vx_gxm_initialize_state init_state;
static _Thread_local uint8_t *queue_data,*parameter_buffer;
typedef struct {uint32_t handle,rendering,display_refs;} gpu_sync;
typedef struct {gpu_sync *old_buffer,*new_buffer;} display_entry;
static _Thread_local gpu_sync syncs[64];
static _Thread_local display_entry queue[16];
static _Thread_local unsigned queue_head,queue_count;
static _Thread_local int queue_running;

static gpu_sync *find_sync(uint32_t handle){
 if(!handle)return NULL;
 for(size_t i=0;i<sizeof syncs/sizeof *syncs;i++)if(syncs[i].handle==handle)return &syncs[i];
 return NULL;
}

uint32_t vx_gxm_queue_worker(void){return init_state.worker;}
size_t vx_gxm_queue_take(uint32_t worker,uint8_t *data,size_t capacity){
 if(!worker||worker!=init_state.worker||!queue_count||queue_running||
    queue[queue_head].new_buffer->rendering||capacity<init_state.data_size)return 0;
 memcpy(data,queue_data+queue_head*init_state.data_size,init_state.data_size);
 queue_running=1;
 return init_state.data_size;
}
void vx_gxm_queue_complete(uint32_t worker){
 if(worker!=init_state.worker||!queue_running)return;
 display_entry *entry=&queue[queue_head];
 entry->old_buffer->display_refs--;
 if(entry->new_buffer!=entry->old_buffer)entry->new_buffer->display_refs--;
 *entry=(display_entry){0};
 queue_head=(queue_head+1)%init_state.max_pending;
 queue_count--;
 queue_running=0;
}
void vx_gxm_queue_detach(uint32_t worker){
 if(!worker||worker!=init_state.worker)return;
 while(queue_count){
  queue_running=1;
  vx_gxm_queue_complete(worker);
 }
 init_state.worker=0;
}
static _Thread_local vx_gxm_queue_create queue_create;
static _Thread_local vx_gxm_queue_destroy queue_destroy;
void vx_gxm_set_queue_backend(vx_gxm_queue_create create,vx_gxm_queue_destroy destroy){
 if(!initialized){queue_create=create;queue_destroy=destroy;}
}
int vx_gxm_get_initialize_state(vx_gxm_initialize_state *out){
 if(!initialized||!out)return -1;*out=init_state;return 0;
}
static void release_initialize(void){
 if(init_state.worker&&queue_destroy)queue_destroy(init_state.worker);
 memset(queue,0,sizeof queue);memset(syncs,0,sizeof syncs);
 queue_head=queue_count=0;queue_running=0;
 free(queue_data);free(parameter_buffer);queue_data=parameter_buffer=0;
 memset(&init_state,0,sizeof init_state);
}

static _Thread_local const vx_gxm_shader *catalog;
static _Thread_local size_t catalog_count;
static _Thread_local vx_gxm_shader_resolver shader_resolver;
void vx_gxm_set_shader_resolver(vx_gxm_shader_resolver resolver){shader_resolver=resolver;}
/* Handles are opaque identity tokens, never host pointers or guest addresses. */
static _Thread_local uint32_t serial=0x70000000;
typedef struct {uint32_t handle,stream,vu,fu,vp,fp,pipeline_vp,pipeline_fp;int scene;uint32_t target,fragment_usse,vertex_sync,fragment_sync,cull,region[5],polygon,texture[VX_GXP_FRAGMENT_TEXTURES][4],ring[2],ring_size[2],ring_used[2];uint32_t data,width,height,stride,depth,depth_stride,depth_compare,depth_write,stencil,stencil_stride,stencil_state[2][7];} scene_context;
static _Thread_local scene_context context;
enum { DEFERRED_COMMAND_CAP = 256, VDM_STAGE = 2, VDM_RESERVATION = 1024, COMMAND_LIST_MAGIC = 0x5658434c };
typedef struct {uint32_t nid,args[9];} recorded_command;
typedef struct {
 uint32_t handle,count,programs[2],buffer[3],capacity[3],allocator[3],user,vdm;
 int recording,allocating;
 recorded_command commands[DEFERRED_COMMAND_CAP];
} deferred_context;
typedef struct {
 uint32_t handle,owner,output,count,vdm;
 recorded_command commands[DEFERRED_COMMAND_CAP];
} command_list;
static _Thread_local deferred_context deferred[8];
static _Thread_local command_list lists[32];
static _Thread_local vx_gxm_allocation allocation_request;

static deferred_context *find_deferred(uint32_t handle){
 if(handle)for(size_t i=0;i<sizeof deferred/sizeof *deferred;i++)if(deferred[i].handle==handle)return &deferred[i];
 return NULL;
}
static int can_record(uint32_t nid){
 switch(nid){
  case 0xE1CA72AE:case 0x70C86868:case 0xFD93209D: /* raster */
  case 0x14BD831F:case 0xF32CBF34: /* depth */
  case 0xB8645A9A:case 0x1A68C8D2:case 0x8FA6FE44:case 0x866A0517: /* stencil */
  case 0x895DF2E9:case 0xC697CAE5:case 0xA824EB24: /* stream and uniforms */
  case 0x29C34DF5:case 0x31FF8ABD:case 0xAD2F48D9:case 0xBC059AFC: /* texture, shaders, draw */
   return 1;
 }
 return 0;
}
typedef struct {uint32_t handle,width,height;} render_target;
static _Thread_local render_target targets[32];
static _Thread_local uint32_t patcher;
typedef struct {uint32_t handle,owner;const vx_gxm_shader *shader;uint32_t kind,stride,index_source;vx_gxp_attribute attrs[16];} program;
static _Thread_local program programs[32];
static _Thread_local vx_metal *renderer;
int vx_gxm_set_catalog(const vx_gxm_shader *shaders,size_t count){
 if(initialized||count>256||(count&&!shaders))return -1;
 for(size_t i=0;i<count;i++)if(!shaders[i].gxp||shaders[i].size<156||!shaders[i].msl||shaders[i].stage>1||shaders[i].input_count>16||shaders[i].uniform_words>120||shaders[i].texture_mask>=1u<<VX_GXP_FRAGMENT_TEXTURES)return -1;
 catalog=shaders;catalog_count=count;return 0;
}
static void reset_scene(void){
 vx_metal_destroy(renderer);renderer=0;memset(&context,0,sizeof context);
 patcher=0;memset(targets,0,sizeof targets);memset(programs,0,sizeof programs);
 memset(deferred,0,sizeof deferred);memset(lists,0,sizeof lists);allocation_request=(vx_gxm_allocation){0};
}
static program *find_program(uint32_t handle,uint32_t kind){
 for(unsigned i=0;i<32;i++)if(programs[i].handle==handle&&handle&&programs[i].kind==kind)return &programs[i];return 0;
}
static program *free_program(void){for(unsigned i=0;i<32;i++)if(!programs[i].handle)return &programs[i];return 0;}
static uint32_t token(void){return ++serial;}

static uint32_t u32(const uint8_t *p){return (uint32_t)p[0]|(uint32_t)p[1]<<8|(uint32_t)p[2]<<16|(uint32_t)p[3]<<24;}
static int range(uint32_t p,uint64_t length,uint32_t base,size_t size){return p&&p>=base&&(uint64_t)p-base<=size&&length<=size-((uint64_t)p-base)&&length<=UINT64_C(0x100000000)-p;}
static int mapped(uint32_t p,uint64_t n,unsigned attr){
 for(unsigned i=0;i<32;i++)if(maps[i].size&&p>=maps[i].base&&
   (uint64_t)p-maps[i].base<=maps[i].size&&n<=maps[i].size-((uint64_t)p-maps[i].base)&&(maps[i].attr&attr)==attr)return 1;
 return 0;
}
static uint32_t map_range(uint32_t address,uint32_t length,unsigned attr){
 mapping *slot=NULL;
 for(size_t i=0;i<sizeof maps/sizeof *maps;i++){
  mapping *m=&maps[i];
  if(!m->size){if(!slot)slot=m;continue;}
  unsigned kind=attr&~(GPU_READ|GPU_WRITE);
  if((m->attr&~(GPU_READ|GPU_WRITE))==kind&&
     (uint64_t)address<(uint64_t)m->base+m->size&&m->base<(uint64_t)address+length)return G_VALUE;
 }
 if(!slot)return G_MEMORY;
 *slot=(mapping){address,length,attr};
 return 0;
}
static uint32_t unmap_range(uint32_t address,unsigned kind){
 for(size_t i=0;i<sizeof maps/sizeof *maps;i++){
  mapping *m=&maps[i];
  if(m->size&&m->base==address&&(m->attr&~(GPU_READ|GPU_WRITE))==kind){
   if(kind==FRAGMENT_USSE&&context.handle&&context.fragment_usse>=address&&
      (uint64_t)context.fragment_usse-address<m->size)return G_VALUE;
   *m=(mapping){0};
   return 0;
  }
 }
 return G_POINTER;
}
static render_target *find_target(uint32_t handle){
 if(!handle)return NULL;
 for(size_t i=0;i<sizeof targets/sizeof *targets;i++)if(targets[i].handle==handle)return &targets[i];
 return NULL;
}
int vx_gxm_take_allocation(vx_gxm_allocation *request){
 if(!allocation_request.entry)return 0;
 *request=allocation_request;
 allocation_request=(vx_gxm_allocation){0};
 return 1;
}
/* A descriptor can be replayed until replaced. Keep every range referenced
   by a live descriptor or a recording reserved, across all deferred contexts. */
static uint64_t advance_past(uint64_t address,uint32_t bytes,uint32_t used,uint32_t length){
 if(length&&address<(uint64_t)used+length&&(uint64_t)used<address+bytes)
  return (uint64_t)used+length;
 return address;
}
static uint64_t advance_past_commands(uint64_t address,uint32_t bytes,const recorded_command *commands,uint32_t count){
 uint64_t next=address;
 for(uint32_t i=0;i<count;i++){
  const recorded_command *command=&commands[i];
  if(command->nid==0xC697CAE5||command->nid==0xA824EB24){
   uint64_t end=advance_past(address,bytes,command->args[1],command->args[8]);
   if(end>next)next=end;
  }
 }
 return next;
}
static uint32_t deferred_space(uint32_t buffer,uint32_t capacity,uint32_t bytes){
 if(!buffer)return 0;
 uint64_t end=(uint64_t)buffer+capacity;
 for(uint64_t address=buffer;address+bytes<=end;){
  uint64_t next=address;
  for(size_t i=0;i<sizeof lists/sizeof *lists;i++){
   const command_list *list=&lists[i];
   if(!list->handle)continue;
   uint64_t vdm=advance_past(address,bytes,list->vdm,list->vdm?VDM_RESERVATION:0);
   uint64_t uniforms=advance_past_commands(address,bytes,list->commands,list->count);
   if(vdm>next)next=vdm;
   if(uniforms>next)next=uniforms;
  }
  for(size_t i=0;i<sizeof deferred/sizeof *deferred;i++){
   const deferred_context *pending=&deferred[i];
   if(!pending->recording)continue;
   uint64_t vdm=advance_past(address,bytes,pending->vdm,pending->vdm?VDM_RESERVATION:0);
   uint64_t uniforms=advance_past_commands(address,bytes,pending->commands,pending->count);
   if(vdm>next)next=vdm;
   if(uniforms>next)next=uniforms;
  }
  if(next==address)return (uint32_t)address;
  address=(next+15)&~UINT64_C(15);
 }
 return 0;
}
static uint32_t begin_deferred(deferred_context *pending,uint32_t address){
 pending->count=0;
 pending->programs[0]=pending->programs[1]=0;
 pending->vdm=address;
 pending->recording=1;
 return 0;
}
static uint32_t reserve_deferred(deferred_context *pending,unsigned stage,uint32_t bytes,uint32_t output,
                                uint8_t *mem,size_t size,uint32_t base,int refill){
 if(stage!=VDM_STAGE&&pending->count==DEFERRED_COMMAND_CAP)return G_MEMORY;
 uint32_t address=deferred_space(pending->buffer[stage],pending->capacity[stage],bytes);
 if(!address){
  uint32_t entry=pending->allocator[stage];
  if(!refill||!entry||pending->allocating||allocation_request.entry)return UINT32_C(0x805B000B);
  allocation_request=(vx_gxm_allocation){pending->handle,stage,entry,pending->user,bytes,output};
  pending->allocating=1;
  return VX_GXM_ALLOCATE;
 }
 if((address&15)||!range(address,bytes,base,size)||!mapped(address,bytes,GPU_READ))return G_POINTER;
 if(stage==VDM_STAGE)return begin_deferred(pending,address);
 recorded_command *cmd=&pending->commands[pending->count++];
 *cmd=(recorded_command){.nid=stage?0xA824EB24:0xC697CAE5,.args={pending->handle,address,[8]=bytes}};
 memcpy(mem+(output-base),&address,4);
 return 0;
}
uint32_t vx_gxm_finish_allocation(const vx_gxm_allocation *request,uint32_t address,uint32_t length,
                                  uint8_t *mem,size_t size,uint32_t base){
 deferred_context *pending=find_deferred(request->context);
 if(!pending||!pending->allocating)return G_VALUE;
 pending->allocating=0;
 if(!mem)return G_DRIVER;
 unsigned stage=request->stage;
 if(stage>VDM_STAGE||length<request->bytes||(address&15)||!range(address,length,base,size)||
    !mapped(address,length,GPU_READ)||(stage!=VDM_STAGE&&!range(request->output,4,base,size)))
  return UINT32_C(0x805B000B);
 uint32_t old_address=pending->buffer[stage],old_length=pending->capacity[stage];
 pending->buffer[stage]=address;
 pending->capacity[stage]=length;
 uint32_t result=reserve_deferred(pending,stage,request->bytes,request->output,mem,size,base,0);
 if(result){pending->buffer[stage]=old_address;pending->capacity[stage]=old_length;}
 return result;
}
/* Keep the previous private RGBA8 descriptor valid. Store the other
   Vita formats as a relative base ID plus the SDK swizzle bits. */
static uint32_t texture_format(uint32_t stamp){
 return (((stamp&0xffu)^0x0cu)<<24)|(stamp&0x7000u);
}
static unsigned texture_pixel_bytes(uint32_t stamp){
 if((stamp&~0x70ffu)!=0x80000000u)return 0;
 return vx_metal_gxp_texture_pixel_bytes(texture_format(stamp));
}
static unsigned pixel_size(uint32_t format){
 switch(format){case 0:return 1;case UINT32_C(0x30000):case UINT32_C(0x40000):case UINT32_C(0xf0000):return 2;
 case UINT32_C(0x60000):case UINT32_C(0x110000):return 4;default:return 0;}
}
static uint32_t rectangle(uint32_t address,uint32_t x,uint32_t y,uint32_t width,uint32_t height,
                          uint32_t stride,unsigned bpp,unsigned attr,uint32_t base,size_t size,
                          uint32_t *start,size_t *extent){
 if(!width||!height||width>4096||height>4096||!bpp||!stride||stride>16384||stride%bpp||(uint64_t)x+width>stride/bpp)return G_VALUE;
 uint64_t offset=(uint64_t)y*stride+(uint64_t)x*bpp;
 uint64_t n=(uint64_t)(height-1)*stride+(uint64_t)width*bpp;
 if(offset>UINT32_MAX-address)return G_POINTER;
 *start=address+(uint32_t)offset;
 if(!range(*start,n,base,size)||!mapped(*start,n,attr))return G_POINTER;
 *extent=(size_t)n;return 0;
}
/* Read-only GXP 1.4 structural subset. Format facts cross-checked against
   Vita3K gxm/types.h (SceGxmProgram). No USSE decoder or shader substitution. */
static uint32_t gxp_header(const uint8_t *mem,size_t capacity,uint32_t base,uint32_t address,const uint8_t **header){
 if(address&3)return G_ALIGNMENT;
 if(!range(address,156,base,capacity))return G_POINTER;
 const uint8_t *p=mem+(address-base);uint32_t size=u32(p+8);
 if(memcmp(p,"GXP\0",4)||size<156||size>16*1024*1024||!range(address,size,base,capacity))return G_VALUE;
 if(p[4]!=1||(p[5]!=4&&p[5]!=5))return G_UNSUPPORTED;
 /* All offsets below are relative to their field, not to the file start. */
 const unsigned fields[]={64,72,40},counts[]={60,68,36},widths[]={8,8,16};
 uint32_t starts[3]={0},ends[3]={0};
 for(unsigned i=0;i<3;i++){
  uint32_t count=u32(p+counts[i]);if(!count)continue;
  if(i==2&&count>65536)return G_VALUE;
  uint64_t start=(uint64_t)fields[i]+u32(p+fields[i]),length=(uint64_t)count*widths[i];
  if(start<156||start>size||length>size-start||(start&3))return G_VALUE;
  starts[i]=(uint32_t)start;ends[i]=(uint32_t)(start+length);
  for(unsigned j=0;j<i;j++)if(ends[j]&&starts[i]<ends[j]&&starts[j]<ends[i])return G_VALUE;
 }
 if(!u32(p+60))return G_VALUE;
 for(unsigned i=0;i<u32(p+36);i++){
  uint32_t offset=starts[2]+i*16;
  int64_t name=(int64_t)offset+(int32_t)u32(p+offset);
  if(name<156||name>=size)return G_VALUE;
  uint32_t limit=size-(uint32_t)name;if(limit>256)limit=256;
  if(!memchr(p+name,0,limit))return G_VALUE;
 }
 *header=p;return 0;
}
static int guest_string(const uint8_t *mem,size_t size,uint32_t base,uint32_t address,size_t *length){
 if(!range(address,1,base,size))return 0;
 size_t limit=size-(address-base);if(limit>256)limit=256;
 const uint8_t *end=memchr(mem+(address-base),0,limit);if(!end)return 0;
 *length=(size_t)(end-(mem+(address-base)));return 1;
}
static uint32_t parameter_name(const uint8_t *mem,size_t size,uint32_t base,uint32_t parameter,size_t *length){
 if((parameter&3)||!range(parameter,16,base,size))return 0;
 int64_t address=(int64_t)parameter+(int32_t)u32(mem+(parameter-base));
 if(address<0||address>UINT32_MAX||!guest_string(mem,size,base,(uint32_t)address,length))return 0;
 return (uint32_t)address;
}

void vx_gxm_shutdown(void){release_initialize();queue_create=0;queue_destroy=0;reset_scene();catalog=0;catalog_count=0;shader_resolver=0;vx_metal_destroy(transfer);transfer=0;initialized=0;memset(maps,0,sizeof maps);memset(&stats,0,sizeof stats);memset(&readiness,0,sizeof readiness);}
void vx_gxm_get_readiness(vx_gxm_readiness *out){if(out){*out=readiness;out->initialized=initialized;}}
void vx_gxm_get_stats(vx_gxm_stats *out){if(out)*out=stats;}
static uint32_t device(void){
 if(transfer)return 0;
 int status=vx_metal_create(1,1,&transfer);stats.metal_status=status;return status?G_DRIVER:0;
}
/* Vita hard-float imports carry scalar float arguments/results in S0.
   Keep these out of the integer-only import entry point. */
int vx_gxm_float_import(uint32_t nid,uint32_t r[16],uint32_t f[64],uint8_t *mem,size_t size,uint32_t base,uint32_t *out){
 if(!(nid==UINT32_C(0x32F280F0)||nid==UINT32_C(0x269B56BE)))return 0;
 if(!r||!f||!mem||!out)return 0;
 *out=0;
 if(!initialized){*out=G_UNINITIALIZED;return 1;}
 if((r[0]&3)||!range(r[0],20,base,size)){*out=G_POINTER;return 1;}
 uint8_t *ds=mem+(r[0]-base);
 if(u32(ds)!=0x56584431||(u32(ds+16)&0x39u)){*out=G_UNSUPPORTED;return 1;}
 if(nid==UINT32_C(0x269B56BE))f[0]=u32(ds+12);
 else {float value;memcpy(&value,f,4);
  if(!isfinite(value)||value<0||value>1){*out=G_VALUE;return 1;}
  memcpy(ds+12,f,4);}
 return 1;
}
static int gxm_command(uint32_t nid,uint32_t r[16],uint8_t *mem,size_t size,uint32_t base,const uint32_t *recorded,uint32_t *out){
 if(!r||!mem||!out)return 0;
 uint32_t result=0;
 /* Stack arguments are fetched only by operations that need them. */
 uint32_t a[9]={r[0],r[1],r[2],r[3],0,0,0,0,0};
 unsigned extra=0;
 switch(nid){case UINT32_C(0xB7BBA6D5):case UINT32_C(0x4ED2E49D):extra=3;break;
 case UINT32_C(0x8734FF4E):extra=4;break;case UINT32_C(0xED0F6E25):extra=5;break;
 case UINT32_C(0xCA9D41D1):case UINT32_C(0x4811AECB):extra=2;break;
 case UINT32_C(0xB8645A9A):case UINT32_C(0x1A68C8D2):extra=3;break;
 case UINT32_C(0xBC059AFC):extra=1;break;
 case UINT32_C(0x70C86868):extra=2;break;default:break;}
 if(recorded){
  memcpy(a,recorded,sizeof a);
  a[0]=context.handle;
 }else if(extra){
  if((r[13]&3)||!range(r[13],extra*4,base,size)){*out=G_POINTER;return 1;}
  for(unsigned i=0;i<extra;i++)a[4+i]=u32(mem+(r[13]-base)+4*i);
 }
 if(!recorded&&can_record(nid)){
  deferred_context *pending=find_deferred(a[0]);
  if(pending){
   if(!pending->recording){*out=UINT32_C(0x805B0006);return 1;}
   if(pending->allocating){*out=G_VALUE;return 1;}
   if(pending->count==DEFERRED_COMMAND_CAP){*out=G_MEMORY;return 1;}
   if(nid==0x29C34DF5){
    if((a[2]&3)||!range(a[2],16,base,size)){*out=G_POINTER;return 1;}
    memcpy(a+3,mem+(a[2]-base),16);
   }
   recorded_command *cmd=&pending->commands[pending->count++];
   cmd->nid=nid;memcpy(cmd->args,a,sizeof a);
   if(nid==0x31FF8ABD||nid==0xAD2F48D9)pending->programs[nid==0xAD2F48D9]=a[1];
   *out=0;return 1;
  }
 }
 switch(nid){
 case UINT32_C(0x249D5B00):{ /* CreateDeferredContext */
  if(!initialized){result=G_UNINITIALIZED;break;}
  if((a[0]&3)||(a[1]&3)||!range(a[0],48,base,size)||!range(a[1],4,base,size)){result=G_POINTER;break;}
  const uint8_t *p=mem+(a[0]-base);
  if(u32(p+4)<2048||!range(u32(p),u32(p+4),base,size)){result=G_POINTER;break;}
  for(unsigned i=24;i<48;i+=8){
   uint32_t address=u32(p+i),length=u32(p+i+4);
   if((address||length)&&(!length||!range(address,length,base,size))){result=G_POINTER;break;}
  }
  if(result)break;
  deferred_context *slot=NULL;
  for(size_t i=0;i<sizeof deferred/sizeof *deferred;i++)if(!deferred[i].handle){slot=&deferred[i];break;}
  if(!slot){result=G_MEMORY;break;}
  slot->handle=token();slot->user=u32(p+20);
  slot->allocator[VDM_STAGE]=u32(p+8);
  slot->buffer[VDM_STAGE]=u32(p+24);
  slot->capacity[VDM_STAGE]=u32(p+28);
  for(unsigned stage=0;stage<2;stage++){
   slot->allocator[stage]=u32(p+12+stage*4);
   slot->buffer[stage]=u32(p+32+stage*8);
   slot->capacity[stage]=u32(p+36+stage*8);
  }
  memcpy(mem+(a[1]-base),&slot->handle,4);break;
 }
 case UINT32_C(0x27CAD127):case UINT32_C(0xC6B3FCD0):case UINT32_C(0x0B9D13CE):
 case UINT32_C(0x87632B9C):case UINT32_C(0xFA081D05):case UINT32_C(0xAD8C2EBA):{
  if(!initialized){result=G_UNINITIALIZED;break;}
  deferred_context *pending=find_deferred(a[0]);
  if(!pending){result=G_POINTER;break;}
  unsigned stage=(nid==0x27CAD127||nid==0x87632B9C)?0:(nid==0xC6B3FCD0||nid==0xFA081D05)?1:VDM_STAGE;
  if(nid==0x87632B9C||nid==0xFA081D05||nid==0xAD8C2EBA){
   if((a[1]&3)||!range(a[1],4,base,size)){result=G_POINTER;break;}
   memcpy(mem+(a[1]-base),&pending->buffer[stage],4);
   break;
  }
  if(pending->recording||pending->allocating){result=UINT32_C(0x805B0007);break;}
  if((a[1]||a[2])&&(!a[1]||(a[1]&15)||a[2]<1024||
      !range(a[1],a[2],base,size)||!mapped(a[1],a[2],GPU_READ))){result=G_VALUE;break;}
  pending->buffer[stage]=a[1];
  pending->capacity[stage]=a[2];
  break;
 }
 case UINT32_C(0xD6A2FF2F):case UINT32_C(0x944D3F83):case UINT32_C(0x36D85916):{
  if(!initialized){result=G_UNINITIALIZED;break;}
  deferred_context *pending=find_deferred(a[0]);
  if(!pending){result=G_POINTER;break;}
  if(pending->allocating){result=G_VALUE;break;}
  if(nid==0x944D3F83){
   if(pending->recording){result=UINT32_C(0x805B0007);break;}
   if(!pending->allocator[VDM_STAGE]&&!pending->buffer[VDM_STAGE])result=begin_deferred(pending,0);
   else result=reserve_deferred(pending,VDM_STAGE,VDM_RESERVATION,0,mem,size,base,1);
   break;
  }
  if(nid==0xD6A2FF2F){
   if(pending->recording){result=UINT32_C(0x805B0007);break;}
   for(size_t i=0;i<sizeof lists/sizeof *lists;i++)if(lists[i].owner==a[0])lists[i].handle=lists[i].owner=0;
   *pending=(deferred_context){0};break;
  }
  if(!pending->recording){result=UINT32_C(0x805B0006);break;}
  if((a[1]&3)||!range(a[1],32,base,size)){result=G_POINTER;break;}
  command_list *slot=NULL;
  for(size_t i=0;i<sizeof lists/sizeof *lists;i++){
   if(lists[i].handle&&lists[i].output==a[1]){slot=&lists[i];break;}
   if(!slot&&!lists[i].handle)slot=&lists[i];
  }
  if(!slot){result=G_MEMORY;break;}
  slot->handle=token();slot->owner=a[0];slot->output=a[1];slot->count=pending->count;slot->vdm=pending->vdm;
  memcpy(slot->commands,pending->commands,slot->count*sizeof *slot->commands);
  uint32_t descriptor[8]={COMMAND_LIST_MAGIC,slot->handle};
  memcpy(mem+(a[1]-base),descriptor,sizeof descriptor);
  pending->recording=0;pending->vdm=0;break;
 }
 case UINT32_C(0xE8E139DD):{ /* ExecuteCommandList */
  if(!initialized){result=G_UNINITIALIZED;break;}
  if(!context.handle||a[0]!=context.handle||(a[1]&3)||!range(a[1],32,base,size)){result=G_POINTER;break;}
  if(!context.scene){result=UINT32_C(0x805B0006);break;}
  const uint8_t *descriptor=mem+(a[1]-base);
  command_list *list=NULL;
  if(u32(descriptor)==COMMAND_LIST_MAGIC){
   uint32_t handle=u32(descriptor+4);
   for(size_t i=0;i<sizeof lists/sizeof *lists;i++)if(handle&&lists[i].handle==handle){list=&lists[i];break;}
  }
  if(!list){result=G_POINTER;break;}
  scene_context saved=context;
  memset(context.region,0,sizeof context.region);
  context.polygon=0;
  context.cull=context.stream=context.vp=context.fp=context.vu=context.fu=0;
  context.depth_compare=3;context.depth_write=1;
  const uint32_t stencil[2][7]={{7,0,0,0,255,255,0},{7,0,0,0,255,255,0}};
  memcpy(context.stencil_state,stencil,sizeof stencil);
  memset(context.texture,0,sizeof context.texture);
  for(uint32_t i=0;i<list->count;i++){
   const recorded_command *cmd=&list->commands[i];
   if(!gxm_command(cmd->nid,r,mem,size,base,cmd->args,&result)){result=G_UNSUPPORTED;break;}
   if(result)break;
  }
  context=saved;
  context.pipeline_vp=context.pipeline_fp=0;
  break;
 }
 case UINT32_C(0x70C86868): /* SetRegionClip */
 case UINT32_C(0xFD93209D): /* SetFrontPolygonMode */
  if(!initialized){result=G_UNINITIALIZED;break;}
  if(!context.handle||a[0]!=context.handle){result=G_POINTER;break;}
  if(nid==0xFD93209D){
   if(a[1]!=0&&a[1]!=0x00028000){result=G_UNSUPPORTED;break;}
   context.polygon=a[1];
  }else{
   if(a[1]&0x3fffffffu){result=G_VALUE;break;}
   if(a[1]>=0x80000000u&&(a[2]>a[4]||a[3]>a[5])){result=G_VALUE;break;}
   memcpy(context.region,a+1,sizeof context.region);
  }
  break;

 case UINT32_C(0xE1CA72AE): /* SetCullMode */
  if(!initialized){result=G_UNINITIALIZED;break;}
  if(!context.handle||a[0]!=context.handle){result=G_POINTER;break;}
  if(a[1]>2){result=G_VALUE;break;}
  context.cull=a[1];break;


 case UINT32_C(0xCA9D41D1):{
  if(!initialized){result=G_UNINITIALIZED;break;}
  if((a[0]&3)||!range(a[0],20,base,size)){result=G_POINTER;break;}
  if((a[1]!=0x44000&&a[1]!=0x22000&&a[1]!=0x66000)||a[2]){result=G_UNSUPPORTED;break;}
  if(!a[3]||a[3]>4096||(a[3]&31)){result=G_VALUE;break;}
  int has_depth=a[1]!=0x22000,has_stencil=a[1]!=0x44000;
  if((!has_depth&&a[4])||(!has_stencil&&a[5])){result=G_VALUE;break;}
  if((has_depth&&((a[4]&63)||!range(a[4],a[3]*4,base,size)||!mapped(a[4],a[3]*4,3)))||
     (has_stencil&&((a[5]&63)||!range(a[5],a[3],base,size)||!mapped(a[5],a[3],3)))){result=G_POINTER;break;}
  /* Private opaque layout: word 2 holds stride in low 16 bits and
     background stencil in high 8. Word 4 holds the aligned S8 pointer
     plus force-load/store bits 1/2. */
  const uint32_t surface[5]={0x56584431,has_depth?a[4]:0,a[3],0x3f800000,has_stencil?a[5]:0};
  memcpy(mem+(a[0]-base),surface,20);break;
 }
 /* Force-store disabled permits normal store; this synchronous backend always
    stores enabled attachments. Force-load imports both guest attachments. */
 case UINT32_C(0x0C44ACD7):case UINT32_C(0x12AAA7AF):
 case UINT32_C(0x2F5CC20C):case UINT32_C(0x544AA05A):{
  if(!initialized){result=G_UNINITIALIZED;break;}
  if((a[0]&3)||!range(a[0],20,base,size)){result=G_POINTER;break;}
  uint8_t *ds=mem+(a[0]-base);uint32_t flags=u32(ds+16);
  if(u32(ds)!=0x56584431||(flags&0x39u)){result=G_UNSUPPORTED;break;}
  unsigned mask=(nid==UINT32_C(0x0C44ACD7)||nid==UINT32_C(0x2F5CC20C))?2:4;
  if(nid==UINT32_C(0x2F5CC20C)||nid==UINT32_C(0x544AA05A))result=flags&mask;
  else {if(a[1]!=0&&a[1]!=mask){result=G_VALUE;break;}
   flags=(flags&~mask)|a[1];memcpy(ds+16,&flags,4);}
  break;
 }
 case UINT32_C(0xAAFC062B):case UINT32_C(0xF5D3F3E8):{
  if(!initialized){result=G_UNINITIALIZED;break;}
  if((a[0]&3)||!range(a[0],20,base,size)){result=G_POINTER;break;}
  uint8_t *ds=mem+(a[0]-base);
  if(u32(ds)!=0x56584431){result=G_UNSUPPORTED;break;}
  if(nid==0xAAFC062B)result=u32(ds+8)>>24;
  else {if(a[1]>255){result=G_VALUE;break;}uint32_t value=(u32(ds+8)&0xffffu)|(a[1]<<24);memcpy(ds+8,&value,4);}
  break;
 }
 case UINT32_C(0xB8645A9A):case UINT32_C(0x1A68C8D2):
 case UINT32_C(0x8FA6FE44):case UINT32_C(0x866A0517):{
  if(!initialized){result=G_UNINITIALIZED;break;}
  if(!context.handle||a[0]!=context.handle){result=G_POINTER;break;}
  unsigned face=(nid==0x1A68C8D2||nid==0x866A0517);uint32_t *state=context.stencil_state[face];
  if(nid==0x8FA6FE44||nid==0x866A0517){if(a[1]>255){result=G_VALUE;break;}state[6]=a[1];}
  else {if((a[1]&~0x0e000000u)||a[2]>7||a[3]>7||a[4]>7||a[5]>255||a[6]>255){result=G_VALUE;break;}
   state[0]=a[1]>>25;for(unsigned i=1;i<6;i++)state[i]=a[i+1];}
  break;
 }
 case UINT32_C(0x14BD831F):case UINT32_C(0xF32CBF34):{
  if(!initialized){result=G_UNINITIALIZED;break;}
  if(!context.handle||a[0]!=context.handle){result=G_POINTER;break;}
  if(nid==UINT32_C(0x14BD831F)){
   if((a[1]&~0x01c00000u)){result=G_VALUE;break;}context.depth_compare=a[1]>>22;
  }else {if(a[1]!=0&&a[1]!=0x100000){result=G_VALUE;break;}context.depth_write=!a[1];}
  break;
 }
 /* Private opaque disabled-surface representation, like the color surface below.
    Active surfaces use a different private tag. */
 case UINT32_C(0xA41DB0D6):case UINT32_C(0x082200E1):{
  if(!initialized){result=G_UNINITIALIZED;break;}
  if((a[0]&3)||!range(a[0],20,base,size)){result=G_POINTER;break;}
  const uint32_t disabled[5]={0x56584430,0,0,0x3f800000,0};
  if(nid==UINT32_C(0xA41DB0D6))memcpy(mem+(a[0]-base),disabled,20);
  else if(u32(mem+(a[0]-base))==0x56584431)result=1;
  else if(memcmp(mem+(a[0]-base),disabled,20))result=G_UNSUPPORTED;
  break;
 }
 case UINT32_C(0x4811AECB):{ /* Bounded linear texture, one mip level */
  if(!initialized){result=G_UNINITIALIZED;break;}
  if((a[0]&3)||!range(a[0],16,base,size)){result=G_POINTER;break;}
  unsigned pixel=vx_metal_gxp_texture_pixel_bytes(a[2]);
  if(!pixel||a[5]!=1){result=G_UNSUPPORTED;break;}
  if(!a[3]||!a[4]||a[3]>4096||a[4]>4096){result=G_VALUE;break;}
  uint64_t bytes=(uint64_t)a[3]*a[4]*pixel;
  if((a[1]&3)||!range(a[1],bytes,base,size)||!mapped(a[1],bytes,1)){result=G_POINTER;break;}
  uint32_t texture[4]={(2u<<3)|(2u<<6),0x6c000000|((a[3]-1)<<12)|(a[4]-1),a[1],0x80000000|((a[2]>>24)^0x0c)|(a[2]&0x7000)};
  memcpy(mem+(a[0]-base),texture,16);break;
 }
 case UINT32_C(0xFA695FD7):case UINT32_C(0x416764E3):case UINT32_C(0x4281763E):case UINT32_C(0x126CDAA3):{
  if(!initialized){result=G_UNINITIALIZED;break;}
  if((a[0]&3)||!range(a[0],16,base,size)){result=G_POINTER;break;}
  uint8_t *p=mem+(a[0]-base);uint32_t word=u32(p);
  if((u32(p+4)&0xff000000)!=0x6c000000||!texture_pixel_bytes(u32(p+12))){result=G_UNSUPPORTED;break;}
  unsigned shift,width;
  if(nid==0x4281763E||nid==0x126CDAA3){
   if(a[1]!=2){result=G_UNSUPPORTED;break;}shift=nid==0x4281763E?6:3;width=3;
  }else {if(a[1]>1){result=G_UNSUPPORTED;break;}shift=nid==0xFA695FD7?12:10;width=2;}
  word=(word&~(((1u<<width)-1)<<shift))|(a[1]<<shift);memcpy(p,&word,4);break;
 }
 case UINT32_C(0x29C34DF5):{
  if(!initialized){result=G_UNINITIALIZED;break;}
  if(!context.handle||a[0]!=context.handle){result=G_POINTER;break;}
  if(a[1]>=VX_GXP_FRAGMENT_TEXTURES){result=G_UNSUPPORTED;break;}
  uint32_t texture[4];
  if(recorded)memcpy(texture,a+3,sizeof texture);
  else{
   if((a[2]&3)||!range(a[2],16,base,size)){result=G_POINTER;break;}
   memcpy(texture,mem+(a[2]-base),sizeof texture);
  }
  uint32_t min=(texture[0]>>10)&3,mag=(texture[0]>>12)&3;
  unsigned pixel=texture_pixel_bytes(texture[3]);
  if((texture[1]&0xff000000)!=0x6c000000||!pixel||
     (texture[0]&~((3u<<10)|(3u<<12)))!=((2u<<3)|(2u<<6))||min>1||mag!=min||(texture[2]&3)){result=G_UNSUPPORTED;break;}
  uint64_t bytes=(uint64_t)(((texture[1]>>12)&4095)+1)*((texture[1]&4095)+1)*pixel;
  if(!range(texture[2],bytes,base,size)||!mapped(texture[2],bytes,1)){result=G_POINTER;break;}
  memcpy(context.texture[a[1]],texture,16);break;
 }
 case UINT32_C(0xE84CE5B4):{ /* CreateContext: immediate, synchronous single-owner context */
  if(!initialized){result=G_UNINITIALIZED;break;}
  if(context.handle){result=G_UNSUPPORTED;break;}
  if((a[0]&3)||(a[1]&3)||!range(a[0],44,base,size)||!range(a[1],4,base,size)){result=G_POINTER;break;}
  const uint8_t *p=mem+(a[0]-base);
  if(!u32(p+4)||!range(u32(p),u32(p+4),base,size)){result=G_POINTER;break;}
  for(unsigned i=8;i<32;i+=8){uint32_t addr=u32(p+i),n=u32(p+i+4);
   if(n&&(!range(addr,n,base,size)||!mapped(addr,n,1))){result=G_POINTER;break;}}
  if(result)break;
  uint32_t usse=u32(p+32),usse_size=u32(p+36),offset=u32(p+40);
  if(usse_size){
   /* A USSE offset is a guest address in the translated backend. */
   if(offset!=usse){result=G_VALUE;break;}
   if(!range(usse,usse_size,base,size)||!mapped(usse,usse_size,FRAGMENT_USSE)){result=G_POINTER;break;}
  }else if(usse||offset){result=G_VALUE;break;}
  context=(scene_context){.handle=token(),.fragment_usse=usse,.depth_compare=3,.depth_write=1,.stencil_state={{7,0,0,0,255,255,0},{7,0,0,0,255,255,0}}};
  for(unsigned i=0;i<2;i++){context.ring[i]=u32(p+16+i*8);context.ring_size[i]=u32(p+20+i*8);}
  memcpy(mem+(a[1]-base),&context.handle,4);break;
 }
 case UINT32_C(0xEDDC5FB2):
  if(!initialized){result=G_UNINITIALIZED;break;}
  if(!context.handle||a[0]!=context.handle){result=G_POINTER;break;}
  if(context.scene){result=G_VALUE;break;}
  vx_metal_destroy(renderer);renderer=0;memset(&context,0,sizeof context);break;
 case UINT32_C(0x97118913):case UINT32_C(0x7B1FABB6):{
  if(!initialized){result=G_UNINITIALIZED;break;}
  deferred_context *pending=find_deferred(a[0]);
  if(!pending&&(!context.handle||a[0]!=context.handle)){result=G_POINTER;break;}
  if(pending?(!pending->recording||pending->allocating):!context.scene){result=G_VALUE;break;}
  if((a[1]&3)||!range(a[1],4,base,size)){result=G_POINTER;break;}
  unsigned stage=nid==0x97118913?0:1;
  uint32_t handle=pending?pending->programs[stage]:stage?context.fp:context.vp;
  program *p=find_program(handle,stage+1);
  if(!p){result=G_VALUE;break;}
  uint32_t bytes=p->shader->uniform_words*4;
  if(!bytes)bytes=4;
  bytes=(bytes+15)&~15u;
  if(pending){result=reserve_deferred(pending,stage,bytes,a[1],mem,size,base,1);break;}
  uint32_t used=context.ring_used[stage],capacity=context.ring_size[stage];
  if(used>capacity||bytes>capacity-used){result=G_MEMORY;break;}
  uint64_t address=(uint64_t)context.ring[stage]+used;
  if((address&15)||address>UINT32_MAX||!range((uint32_t)address,bytes,base,size)||!mapped((uint32_t)address,bytes,GPU_READ)){result=G_POINTER;break;}
  uint32_t output=(uint32_t)address;memcpy(mem+(a[1]-base),&output,4);
  context.ring_used[stage]+=bytes;if(stage)context.fu=output;else context.vu=output;break;
 }
 case UINT32_C(0x0733D8AE):
  if(!initialized)result=G_UNINITIALIZED;
  else if(!context.handle||a[0]!=context.handle)result=G_POINTER;
  else if(context.scene)result=G_VALUE;
  break;
 case UINT32_C(0x895DF2E9):case UINT32_C(0xC697CAE5):case UINT32_C(0xA824EB24):
  if(!initialized){result=G_UNINITIALIZED;break;}
  if(!context.handle||a[0]!=context.handle){result=G_POINTER;break;}
  if(nid==0x895DF2E9&&a[1]){result=G_UNSUPPORTED;break;}
  {uint32_t address=nid==0x895DF2E9?a[2]:a[1];
   if((address&3)||!range(address,4,base,size)||!mapped(address,4,1)){result=G_POINTER;break;}
   if(nid==0x895DF2E9)context.stream=address;
   else if(nid==0xC697CAE5)context.vu=address;else context.fu=address;}
  break;
 case UINT32_C(0x05032658):{ /* Shader patcher: bounded host-owned storage, callbacks reject */
  if(!initialized){result=G_UNINITIALIZED;break;}
  if(patcher){result=G_UNSUPPORTED;break;}
  if((a[0]&3)||(a[1]&3)||!range(a[0],68,base,size)||!range(a[1],4,base,size)){result=G_POINTER;break;}
  const unsigned callbacks[]={4,8,12,16,28,32,48,52};
  for(unsigned i=0;i<8;i++)if(u32(mem+(a[0]-base)+callbacks[i]))result=G_UNSUPPORTED;
  if(result)break;
  patcher=token();memcpy(mem+(a[1]-base),&patcher,4);break;
 }
 case UINT32_C(0x2B528462):{
  readiness.registration_calls++;
  if(!initialized){result=G_UNINITIALIZED;break;}
  if(!patcher||a[0]!=patcher){result=G_POINTER;break;}
  if((a[2]&3)||!range(a[2],4,base,size)){result=G_POINTER;break;}
  const uint8_t *p=0;result=gxp_header(mem,size,base,a[1],&p);if(result)break;
  const vx_gxm_shader *shader=0;
  for(size_t i=0;i<catalog_count;i++)if(catalog[i].size==u32(p+8)&&!memcmp(catalog[i].gxp,p,catalog[i].size)){shader=&catalog[i];break;}
  if(!shader&&shader_resolver){
   shader=shader_resolver(p,u32(p+8));
   /* A resolver cannot substitute unrelated code or unchecked metadata. */
   if(shader&&(!shader->gxp||shader->size!=u32(p+8)||memcmp(shader->gxp,p,shader->size)||!shader->msl||
      shader->stage>1||shader->input_count>16||shader->uniform_words>120||shader->texture_mask>=1u<<VX_GXP_FRAGMENT_TEXTURES))shader=0;
  }
  if(!shader){result=G_UNSUPPORTED;break;}
  program *slot=free_program();if(!slot){result=G_MEMORY;break;}
  *slot=(program){.handle=token(),.owner=patcher,.shader=shader};memcpy(mem+(a[2]-base),&slot->handle,4);break;
 }
 case UINT32_C(0xB7BBA6D5):case UINT32_C(0x4ED2E49D):{
  if(!initialized){result=G_UNINITIALIZED;break;}
  program *registered=find_program(a[1],0);
  if(!patcher||a[0]!=patcher||!registered||registered->owner!=patcher){result=G_POINTER;break;}
  if((a[6]&3)||!range(a[6],4,base,size)){result=G_POINTER;break;}
  int vertex=nid==0xB7BBA6D5;
  if(registered->shader->stage!=(uint32_t)!vertex){result=G_VALUE;break;}
  program next={.owner=patcher,.shader=registered->shader,.kind=vertex?1:2};
  if(vertex){
   if(!a[3]||a[3]>16||a[3]!=next.shader->input_count||a[5]!=1){result=G_UNSUPPORTED;break;}
   if((a[2]&3)||(a[4]&3)||!range(a[2],a[3]*8,base,size)||!range(a[4],4,base,size)){result=G_POINTER;break;}
   const uint8_t *stream=mem+(a[4]-base);next.stride=stream[0]|stream[1]<<8;next.index_source=stream[2]|stream[3]<<8;
   if(!next.stride||next.stride>4096||(next.stride&3)||next.index_source>1){result=G_UNSUPPORTED;break;}
   unsigned seen=0;
   for(unsigned i=0;i<a[3];i++){
    const uint8_t *p=mem+(a[2]-base)+8*i;unsigned reg=p[6]|p[7]<<8,j;
    for(j=0;j<next.shader->input_count;j++)if(next.shader->registers[j]==reg)break;
    if(p[0]||p[1]||p[4]!=9||j==next.shader->input_count||(seen&(1u<<j))||p[5]!=next.shader->components[j]){result=G_UNSUPPORTED;break;}
    unsigned offset=p[2]|p[3]<<8;
    if((offset&3)||offset>next.stride||4u*p[5]>next.stride-offset){result=G_VALUE;break;}
    next.attrs[j]=(vx_gxp_attribute){p[5],offset};seen|=1u<<j;
   }
   if(result)break;
  }else{
   /* Declared or UCHAR4 output, no MSAA or blend state. Vertex linkage checked at draw. */
   if((a[2]!=0&&a[2]!=1)||a[3]||a[4]){result=G_UNSUPPORTED;break;}
  }
  program *slot=free_program();if(!slot){result=G_MEMORY;break;}
  next.handle=token();*slot=next;memcpy(mem+(a[6]-base),&slot->handle,4);break;
 }
 case UINT32_C(0x31FF8ABD):case UINT32_C(0xAD2F48D9):{
  if(!initialized){result=G_UNINITIALIZED;break;}
  if(!context.handle||a[0]!=context.handle){result=G_POINTER;break;}
  if(!find_program(a[1],nid==0x31FF8ABD?1:2)){result=G_POINTER;break;}
  if(nid==0x31FF8ABD)context.vp=a[1];else context.fp=a[1];break;
 }
 case UINT32_C(0xAC1FF2DA):case UINT32_C(0xBE2743D1):case UINT32_C(0xF103AF8A):{
  if(!initialized){result=G_UNINITIALIZED;break;}
  program *p=find_program(a[1],nid==0xAC1FF2DA?1:nid==0xBE2743D1?2:0);
  if(!patcher||a[0]!=patcher||!p){result=G_POINTER;break;}
  if(context.scene&&(context.vp==a[1]||context.fp==a[1])){result=G_VALUE;break;}
  if(context.vp==a[1])context.vp=0;if(context.fp==a[1])context.fp=0;
  memset(p,0,sizeof *p);break;
 }
 case UINT32_C(0xEAA5B100):
  if(!initialized){result=G_UNINITIALIZED;break;}
  if(!patcher||a[0]!=patcher){result=G_POINTER;break;}
  for(unsigned i=0;i<32;i++)if(programs[i].handle)result=G_VALUE;
  if(!result)patcher=0;break;
 case UINT32_C(0x207AF96B):{
  if(!initialized){result=G_UNINITIALIZED;break;}
  if((a[0]&3)||(a[1]&3)||!range(a[0],20,base,size)||!range(a[1],4,base,size)){result=G_POINTER;break;}
  const uint8_t *p=mem+(a[0]-base);unsigned w=p[4]|p[5]<<8,h=p[6]|p[7]<<8;
  if(u32(p)||u32(p+12)||p[10]||p[11]||u32(p+16)!=UINT32_MAX){result=G_UNSUPPORTED;break;}
  unsigned scenes=p[8]|p[9]<<8;if(!w||!h||w>4096||h>4096||!scenes||scenes>8){result=G_VALUE;break;}
  render_target *slot=NULL;
  for(size_t i=0;i<sizeof targets/sizeof *targets;i++)if(!targets[i].handle){slot=&targets[i];break;}
  if(!slot){result=G_MEMORY;break;}
  *slot=(render_target){token(),w,h};memcpy(mem+(a[1]-base),&slot->handle,4);break;
 }
 case UINT32_C(0x0B94C50A):
  if(!initialized){result=G_UNINITIALIZED;break;}
  render_target *target=find_target(a[0]);
  if(!target){result=G_POINTER;break;}
  if(context.scene&&context.target==a[0]){result=G_VALUE;break;}
  *target=(render_target){0};break;
 case UINT32_C(0xED0F6E25):{
  if(!initialized){result=G_UNINITIALIZED;break;}
  if((a[0]&3)||!range(a[0],48,base,size)){result=G_POINTER;break;}
  if(a[1]||a[2]||a[3]||a[4]){result=G_UNSUPPORTED;break;}
  if(!a[5]||!a[6]||a[5]>4096||a[6]>4096||a[7]<a[5]||a[7]>4096){result=G_VALUE;break;}
  uint64_t extent=((uint64_t)(a[6]-1)*a[7]+a[5])*4;
  if((a[8]&3)||!range(a[8],extent,base,size)||!mapped(a[8],extent,2)){result=G_POINTER;break;}
  /* Private opaque representation; copied surfaces retain validated metadata. */
  uint32_t surface[12]={0x56585346,a[5],a[6],a[7],a[8],0,0,0};memcpy(mem+(a[0]-base),surface,48);break;
 }
 case UINT32_C(0x8734FF4E):{
  if(!initialized){result=G_UNINITIALIZED;break;}
  render_target *target=find_target(a[2]);
  if(!context.handle||a[0]!=context.handle||!target){result=G_POINTER;break;}
  uint32_t target_width=target->width,target_height=target->height;
  if(context.scene){result=G_VALUE;break;}
  if(a[1]||a[3]){result=G_UNSUPPORTED;break;}
  gpu_sync *vertex=find_sync(a[4]),*fragment=find_sync(a[5]);
  if((a[4]&&!vertex)||(a[5]&&!fragment)){result=G_POINTER;break;}
  if((vertex&&(vertex->rendering||vertex->display_refs))||
     (fragment&&(fragment->rendering||fragment->display_refs))){result=VX_GXM_WOULD_BLOCK;break;}
  uint32_t depth=0,stencil=0,depth_stride=0,depth_flags=0,background_stencil=0;float background_depth=1;
  if(a[7]){
   if((a[7]&3)||!range(a[7],20,base,size)){result=G_POINTER;break;}
   const uint32_t disabled[5]={0x56584430,0,0,0x3f800000,0};
   const uint8_t *ds=mem+(a[7]-base);
   if(u32(ds)==0x56584431){
    depth=u32(ds+4);depth_stride=u32(ds+8)&0xffff; background_stencil=u32(ds+8)>>24;
    depth_flags=u32(ds+16);stencil=depth_flags&~63u;
    memcpy(&background_depth,ds+12,4);
    if(!isfinite(background_depth)||background_depth<0||background_depth>1||(depth_flags&0x39u)){result=G_UNSUPPORTED;break;}
    if((u32(ds+8)&0x00ff0000u)||(!depth&&!stencil)){result=G_UNSUPPORTED;break;}
    if(depth_stride<target_width||depth_stride>4096||(depth_stride&31)){result=G_VALUE;break;}
    uint64_t n=((uint64_t)(target_height-1)*depth_stride+target_width)*4;
    if(depth&&((depth&63)||!range(depth,n,base,size)||!mapped(depth,n,3))){result=G_POINTER;break;}
   if(stencil){n=(uint64_t)(target_height-1)*depth_stride+target_width;if(!range(stencil,n,base,size)||!mapped(stencil,n,3)){result=G_POINTER;break;}}
   }else if(memcmp(ds,disabled,20)){result=G_UNSUPPORTED;break;}
  }
  if((a[6]&3)||!range(a[6],48,base,size)){result=G_POINTER;break;}
  const uint8_t *p=mem+(a[6]-base);uint32_t w=u32(p+4),h=u32(p+8),stride=u32(p+12),data=u32(p+16);
  if(u32(p)!=0x56585346||w!=target_width||h!=target_height||stride<w||stride>4096||u32(p+20)||u32(p+24)||u32(p+28)||u32(p+32)||u32(p+36)||u32(p+40)||u32(p+44)){result=G_VALUE;break;}
  uint64_t extent=((uint64_t)(h-1)*stride+w)*4;
  if(!range(data,extent,base,size)||!mapped(data,extent,3)){result=G_POINTER;break;}
  uint64_t depth_extent=depth?((uint64_t)(h-1)*depth_stride+w)*4:0;
  if(depth&&(uint64_t)data<depth+depth_extent&&(uint64_t)depth<data+extent){result=G_VALUE;break;}
  uint64_t stencil_extent=stencil?(uint64_t)(h-1)*depth_stride+w:0;
  if(stencil&&(((uint64_t)data<stencil+stencil_extent&&(uint64_t)stencil<data+extent)||
     (depth&&(uint64_t)depth<stencil+stencil_extent&&(uint64_t)stencil<depth+depth_extent))){result=G_VALUE;break;}
  int status=renderer?vx_metal_resize(renderer,w,h):vx_metal_create(w,h,&renderer);stats.metal_status=status;
  if(status){result=G_DRIVER;break;}
  status=vx_metal_upload(renderer,mem+(data-base),(size_t)extent,stride*4,VX_PIXELS_RGBA8);stats.metal_status=status;
  if(status){result=G_DRIVER;break;}
  status=vx_metal_gxp_depth_begin(renderer,depth!=0,background_depth);
  if(!status&&depth&&(depth_flags&2))status=vx_metal_gxp_depth_upload(renderer,mem+(depth-base),(size_t)depth_extent,depth_stride*4);
  if(!status)status=vx_metal_gxp_stencil_begin(renderer,stencil!=0,background_stencil);
  if(!status&&stencil&&(depth_flags&2))status=vx_metal_gxp_stencil_upload(renderer,mem+(stencil-base),(size_t)stencil_extent,depth_stride);
  stats.metal_status=status;
  if(status){context.pipeline_vp=context.pipeline_fp=0;result=G_DRIVER;break;}
  /* Pipeline attachment formats change only when depth enablement changes. */
  if(!!context.depth!=!!depth||!!context.stencil!=!!stencil)context.pipeline_vp=context.pipeline_fp=0;
  context.stencil=stencil;context.stencil_stride=depth_stride;context.depth=depth;context.depth_stride=depth_stride;
  context.ring_used[0]=context.ring_used[1]=0;context.scene=1;context.target=a[2];
  context.vertex_sync=a[4];context.fragment_sync=a[5];
  if(vertex)vertex->rendering=1;
  if(fragment)fragment->rendering=1;
  context.data=data;context.width=w;context.height=h;context.stride=stride;break;
 }
 case UINT32_C(0xBC059AFC):{
  if(!initialized){result=G_UNINITIALIZED;break;}
  if(!context.handle||a[0]!=context.handle){result=G_POINTER;break;}
  if(!context.scene){result=G_VALUE;break;}
  if(a[2]!=0&&a[2]!=0x01000000){result=G_UNSUPPORTED;break;}
  if(!a[4]||a[4]>65535){result=G_VALUE;break;}
  vx_metal_primitive primitive;
  unsigned count=a[4];
  int fan=0;
  switch(a[1]){
   case 0:primitive=VX_METAL_TRIANGLES;if(count%3)result=G_VALUE;break;
   case 0x04000000:primitive=VX_METAL_LINES;if(count%2)result=G_VALUE;break;
   case 0x0c000000:primitive=VX_METAL_TRIANGLE_STRIP;if(count<3)result=G_VALUE;break;
   case 0x10000000:
    primitive=VX_METAL_TRIANGLES;fan=1;
    if(count<3||count>65535/3+2)result=G_VALUE;
    else count=(count-2)*3;
    break;
   default:result=G_UNSUPPORTED;break;
  }
  if(result)break;
  program *v=find_program(context.vp,1),*f=find_program(context.fp,2);
  if(!v||!f||!context.stream){result=G_VALUE;break;}
  for(unsigned slot=0;slot<VX_GXP_FRAGMENT_TEXTURES;slot++)if(f->shader->texture_mask&(1u<<slot)){
   uint32_t *t=context.texture[slot];
   if(!t[3]){result=G_VALUE;break;}
   uint64_t bytes=(uint64_t)(((t[1]>>12)&4095)+1)*((t[1]&4095)+1)*texture_pixel_bytes(t[3]);
   if(!range(t[2],bytes,base,size)||!mapped(t[2],bytes,1)){result=G_POINTER;break;}
  }
  if(result)break;
  if((f->shader->varyings&~v->shader->varyings)||(a[2]?1u:0u)!=v->index_source){result=G_UNSUPPORTED;break;}
  unsigned bytes=a[2]?4:2;
  if((a[3]&(bytes-1))||!range(a[3],a[4]*bytes,base,size)||!mapped(a[3],a[4]*bytes,1)){result=G_POINTER;break;}
  uint32_t max=0;
  for(unsigned i=0;i<a[4];i++){const uint8_t *p=mem+(a[3]-base)+i*bytes;uint32_t index=bytes==4?u32(p):(uint32_t)p[0]|(uint32_t)p[1]<<8;if(index>max)max=index;}
  uint64_t extent=((uint64_t)max+1)*v->stride;
  if(!range(context.stream,extent,base,size)||!mapped(context.stream,extent,1)){result=G_POINTER;break;}
  uint32_t vu[120]={0},fu[120]={0};
  if((v->shader->uniform_words&&(!range(context.vu,v->shader->uniform_words*4,base,size)||!mapped(context.vu,v->shader->uniform_words*4,1)))||
     (f->shader->uniform_words&&(!range(context.fu,f->shader->uniform_words*4,base,size)||!mapped(context.fu,f->shader->uniform_words*4,1)))){result=G_POINTER;break;}
  if(v->shader->uniform_words)memcpy(vu,mem+(context.vu-base),v->shader->uniform_words*4);
  if(f->shader->uniform_words)memcpy(fu,mem+(context.fu-base),f->shader->uniform_words*4);
  char diagnostic[1024];int status=0;
  if(context.depth)status=vx_metal_gxp_depth_state(renderer,context.depth_compare,context.depth_write);
  if(!status&&context.stencil)for(unsigned face=0;face<2&&!status;face++){uint32_t *t=context.stencil_state[face];status=vx_metal_gxp_stencil_face_state(renderer,face,t[0],t[1],t[2],t[3],t[4],t[5],t[6]);}
  if(!status&&(context.pipeline_vp!=context.vp||context.pipeline_fp!=context.fp)){context.pipeline_vp=context.pipeline_fp=0;status=vx_metal_gxp_pipeline(renderer,v->shader->msl,f->shader->msl,v->attrs,v->shader->input_count,v->stride,v->shader->uniform_words,f->shader->uniform_words,f->shader->texture_mask,diagnostic,sizeof diagnostic);}
  if(!status){context.pipeline_vp=context.vp;context.pipeline_fp=context.fp;}
  for(unsigned slot=0;slot<VX_GXP_FRAGMENT_TEXTURES&&!status;slot++)if(f->shader->texture_mask&(1u<<slot)){
   uint32_t *t=context.texture[slot];unsigned w=((t[1]>>12)&4095)+1,h=(t[1]&4095)+1;
   unsigned pixel=texture_pixel_bytes(t[3]);
   status=vx_metal_gxp_upload_texture_format(renderer,slot,mem+(t[2]-base),(size_t)w*h*pixel,w,h,
                                             w*pixel,(t[0]>>10)&3,texture_format(t[3]));
  }
  /* Gather checked indices into a bounded packed stream; Metal sees real guest geometry. */
  uint8_t *vertices=0;
  if(!status){
   vertices=malloc((size_t)count*v->stride);if(!vertices){result=G_MEMORY;break;}
   for(unsigned i=0;i<count;i++){
    /* Metal has no triangle fan. Preserve the anchor and edge order. */
    unsigned element=fan?(i%3?i/3+i%3:0):i;
    const uint8_t *p=mem+(a[3]-base)+element*bytes;
    uint32_t index=bytes==4?u32(p):(uint32_t)p[0]|(uint32_t)p[1]<<8;
    memcpy(vertices+(size_t)i*v->stride,mem+(context.stream-base)+(size_t)index*v->stride,v->stride);
   }
   status=vx_metal_gxp_set_cull(renderer,context.cull);
   if(!status)status=vx_metal_gxp_set_raster(renderer,context.polygon!=0,context.region);
   if(!status)status=vx_metal_gxp_draw_primitive_load(renderer,primitive,vertices,(size_t)count*v->stride,count,
     vu,v->shader->uniform_words,fu,f->shader->uniform_words);
   free(vertices);
  }
  stats.metal_status=status;if(status){result=G_DRIVER;break;}stats.draws++;break;
 }
 case UINT32_C(0xFE300E2F):{
  if(!initialized){result=G_UNINITIALIZED;break;}
  if(!context.handle||a[0]!=context.handle){result=G_POINTER;break;}
  if(!context.scene){result=G_VALUE;break;}
  uint32_t notify_address[2]={0},notify_value[2]={0};
  for(unsigned i=0;i<2;i++)if(a[i+1]){
   uint32_t address=a[i+1];
   if((address&3)||!range(address,8,base,size)){result=G_POINTER;break;}
   notify_address[i]=u32(mem+(address-base));
   notify_value[i]=u32(mem+(address-base)+4);
   if((notify_address[i]&3)||!range(notify_address[i],4,base,size)){result=G_POINTER;break;}
  }
  if(result)break;
  uint64_t extent=((uint64_t)(context.height-1)*context.stride+context.width)*4;
  if(!range(context.data,extent,base,size)||!mapped(context.data,extent,2)){result=G_POINTER;break;}
  size_t bytes=(size_t)context.width*context.height*4;uint8_t *pixels=malloc(bytes);if(!pixels){result=G_MEMORY;break;}
  float *depth_pixels=0;
  if(context.depth){
   uint64_t n=((uint64_t)(context.height-1)*context.depth_stride+context.width)*4;
   if(!range(context.depth,n,base,size)||!mapped(context.depth,n,2)){free(pixels);result=G_POINTER;break;}
   depth_pixels=malloc(bytes);if(!depth_pixels){free(pixels);result=G_MEMORY;break;}
  }
  uint8_t *stencil_pixels=0;
  if(context.stencil){uint64_t n=(uint64_t)(context.height-1)*context.stencil_stride+context.width;
   if(!range(context.stencil,n,base,size)||!mapped(context.stencil,n,2)){free(depth_pixels);free(pixels);result=G_POINTER;break;}
   stencil_pixels=malloc(bytes/4);if(!stencil_pixels){free(depth_pixels);free(pixels);result=G_MEMORY;break;}}
  int status=vx_metal_readback(renderer,pixels,bytes);
  if(!status&&depth_pixels)status=vx_metal_gxp_depth_readback(renderer,depth_pixels,bytes/4);
  if(!status&&stencil_pixels)status=vx_metal_gxp_stencil_readback(renderer,stencil_pixels,bytes/4);
  stats.metal_status=status;
  if(!status){for(unsigned y=0;y<context.height;y++)memcpy(mem+(context.data-base)+(size_t)y*context.stride*4,pixels+(size_t)y*context.width*4,context.width*4);
   if(depth_pixels)for(unsigned y=0;y<context.height;y++)memcpy(mem+(context.depth-base)+(size_t)y*context.depth_stride*4,depth_pixels+(size_t)y*context.width,context.width*4);
   if(stencil_pixels)for(unsigned y=0;y<context.height;y++)memcpy(mem+(context.stencil-base)+(size_t)y*context.stencil_stride,stencil_pixels+(size_t)y*context.width,context.width);
   for(unsigned i=0;i<2;i++)if(notify_address[i])memcpy(mem+(notify_address[i]-base),&notify_value[i],4);
   gpu_sync *vertex=find_sync(context.vertex_sync),*fragment=find_sync(context.fragment_sync);
   if(vertex)vertex->rendering=0;
   if(fragment)fragment->rendering=0;
   context.scene=0;stats.scenes++;}else result=G_DRIVER;free(stencil_pixels);free(depth_pixels);free(pixels);break;
 }
 case UINT32_C(0x06FF9151): /* sceGxmProgramGetParameter */
 case UINT32_C(0x277794C4): /* sceGxmProgramFindParameterByName */
 case UINT32_C(0x633CAA54): /* sceGxmProgramFindParameterBySemantic */
 case UINT32_C(0x6E61DDF5):{ /* sceGxmProgramParameterGetIndex */
  const uint8_t *p=0;result=gxp_header(mem,size,base,r[0],&p);if(result)break;
  uint32_t count=u32(p+36),start=40+u32(p+40);
  if(nid==UINT32_C(0x06FF9151)){result=r[1]<count?r[0]+start+r[1]*16:0;break;}
  if(nid==UINT32_C(0x6E61DDF5)){
   uint64_t first=(uint64_t)r[0]+start;
   result=r[1]>=first&&(r[1]-first)%16==0&&(r[1]-first)/16<count?(uint32_t)((r[1]-first)/16):UINT32_MAX;break;
  }
  size_t requested=0;if(nid==UINT32_C(0x277794C4)&&!guest_string(mem,size,base,r[1],&requested)){result=G_POINTER;break;}
  result=0;
  for(uint32_t i=0;i<count;i++){
   uint32_t address=r[0]+start+i*16;const uint8_t *parameter=mem+(address-base);
   int match=0;
   if(nid==UINT32_C(0x277794C4)){
    size_t length;uint32_t name=parameter_name(mem,size,base,address,&length);
    if(!name){result=G_VALUE;break;}
    match=length==requested&&!memcmp(mem+(name-base),mem+(r[1]-base),length);
   }else match=parameter[6]==r[1]&&parameter[7]==r[2];
   if(match){result=address;break;}
  }break;
 }
 case UINT32_C(0x1997DC17): /* category */
 case UINT32_C(0x6AF88A5D): /* name */
 case UINT32_C(0xE6D9C4CE): /* semantic */
 case UINT32_C(0xB85CC13E): /* semantic index */
 case UINT32_C(0x7B9023C3): /* type */
 case UINT32_C(0xBD2998D1): /* components */
 case UINT32_C(0xDBA8D061): /* array size */
 case UINT32_C(0x5C79D59A): /* resource index */
 case UINT32_C(0xBB58267D): /* container index */
 case UINT32_C(0xF7AA978B):{ /* sampler cube */
  if((r[0]&3)||!range(r[0],16,base,size)){result=G_POINTER;break;}
  const uint8_t *p=mem+(r[0]-base);size_t length;
  switch(nid){
   case UINT32_C(0x1997DC17):result=p[4]&15;break;
   case UINT32_C(0x6AF88A5D):result=parameter_name(mem,size,base,r[0],&length);break;
   case UINT32_C(0xE6D9C4CE):result=p[6];break;
   case UINT32_C(0xB85CC13E):result=p[7];break;
   case UINT32_C(0x7B9023C3):result=p[4]>>4;break;
   case UINT32_C(0xBD2998D1):result=p[5]&15;break;
   case UINT32_C(0xDBA8D061):result=u32(p+8);break;
   case UINT32_C(0x5C79D59A):result=u32(p+12);break;
   case UINT32_C(0xBB58267D):result=p[5]>>4;break;
   default:result=(p[4]&15)==2&&!!(p[7]&16);break;
  }break;
 }
 case UINT32_C(0x65DD0C84):{ /* sceGxmSetUniformDataF: default F32, packed vectors/arrays */
  if((r[1]&3)||!range(r[1],16,base,size)||(r[13]&3)||!range(r[13],4,base,size)){result=G_POINTER;break;}
  const uint8_t *p=mem+(r[1]-base);uint32_t components=p[5]&15,arrays=u32(p+8);
  if((p[4]&15)!=1||(p[4]>>4)!=0||(p[5]>>4)!=14){result=G_UNSUPPORTED;break;}
  if(!components||components>4||!arrays||arrays>64||!r[3]||r[3]>256||r[2]>arrays*components||r[3]>arrays*components-r[2]){result=G_VALUE;break;}
  uint32_t source=u32(mem+(r[13]-base));
  if((r[0]&3)||(source&3)||!range(r[0],1,base,size)||!range(source,r[3]*4,base,size)){
   result=G_POINTER;break;
  }
  /* Arrays of float vectors align elements to pairs of 32-bit registers;
     float3 arrays retain one padding word. Validate every write first. */
  unsigned stride=arrays>1&&components>1?(components+1)&~1u:components;
  uint32_t destinations[256],values[256];
  for(uint32_t i=0;i<r[3];i++){
   uint32_t component=r[2]+i;
   uint64_t offset=((uint64_t)u32(p+12)+(component/components)*stride+component%components)*4;
   if(offset>UINT32_MAX-r[0]||!range(r[0]+(uint32_t)offset,4,base,size)){result=G_POINTER;break;}
   destinations[i]=r[0]+(uint32_t)offset;
  }
  if(result)break;
  memcpy(values,mem+(source-base),r[3]*4);
  for(uint32_t i=0;i<r[3];i++)memcpy(mem+(destinations[i]-base),values+i,4);
  break;
 }
 case UINT32_C(0xED8B6C69): /* sceGxmProgramCheck: structure only, not USSE support */
 case UINT32_C(0xBF5E2090): /* sceGxmProgramGetSize */
 case UINT32_C(0x04BB3C59): /* sceGxmProgramGetType */
 case UINT32_C(0xD5D5FCCD): /* sceGxmProgramGetParameterCount */
 case UINT32_C(0x8FA3F9C3): /* sceGxmProgramGetDefaultUniformBufferSize */
 case UINT32_C(0x029B4F1C): /* sceGxmProgramIsDiscardUsed */
 case UINT32_C(0x89613EF2): /* sceGxmProgramIsDepthReplaceUsed */
 case UINT32_C(0xE63C53D8):{ /* sceGxmProgramIsSpriteCoordUsed */
  const uint8_t *p=0;result=gxp_header(mem,size,base,r[0],&p);if(result)break;
  switch(nid){
   case UINT32_C(0xBF5E2090):result=u32(p+8);break;
   case UINT32_C(0x04BB3C59):result=u32(p+20)&1;break;
   case UINT32_C(0xD5D5FCCD):result=u32(p+36);break;
   case UINT32_C(0x8FA3F9C3):result=u32(p+100);break;
   case UINT32_C(0x029B4F1C):result=!!(u32(p+20)&8);break;
   case UINT32_C(0x89613EF2):result=!!(u32(p+20)&16);break;
   case UINT32_C(0xE63C53D8):result=!!(u32(p+20)&32);break;
   default:break;
  }break;
 }
 case UINT32_C(0xB0F1E4EC):{ /* VitaSDK SceGxmInitializeParams: five 32-bit fields. */
  readiness.initialize_calls++;
  if(initialized){result=G_INITIALIZED;break;}
  if((r[0]&3)||!range(r[0],20,base,size)){result=G_POINTER;break;}
  const uint8_t *p=mem+(r[0]-base);
  vx_gxm_initialize_state next={u32(p),u32(p+4),u32(p+8),u32(p+12),u32(p+16),0};
  /* Ordinary sceGxmInitialize requires default flags. Other modes are not
     implemented; do not silently enable them. VitaSDK minimum is 256 KiB. */
  if(next.flags){result=G_UNSUPPORTED;break;}
  if(next.parameter_size<0x40000||(next.parameter_size&0x3ffff)||
     (uint64_t)next.max_pending*next.data_size>0x200||
     (next.callback&&(!next.max_pending||next.max_pending>16||!next.data_size))||
     (!next.callback&&(next.max_pending||next.data_size))){result=G_VALUE;break;}
  /* Bound host reservations independently of potentially malicious guest sizes. */
  if(next.parameter_size>256u*1024*1024){result=G_MEMORY;break;}
  if(next.callback&&(!queue_create||!queue_destroy)){result=G_UNSUPPORTED;break;}
  uint8_t *parameters=calloc(1,next.parameter_size),*data=0;
  if(next.callback)data=calloc(next.max_pending,next.data_size);
  if(!parameters||(next.callback&&!data)){free(parameters);free(data);result=G_MEMORY;break;}
  if(next.callback){
   result=queue_create(next.callback,&next.worker,mem,size);
   if(result){free(parameters);free(data);break;}
  }
  /* Commit only after backing storage and a real dormant worker exist. No
     callback executes before an entry is submitted; never discard submissions. */
  init_state=next;parameter_buffer=parameters;queue_data=data;
  memset(&stats,0,sizeof stats);initialized=1;readiness.initializations++;break;
 }
 case UINT32_C(0x6A6013E1):{ /* SyncObjectCreate */
  if(!initialized){result=G_UNINITIALIZED;break;}
  if((a[0]&3)||!range(a[0],4,base,size)){result=G_POINTER;break;}
  gpu_sync *slot=NULL;
  for(size_t i=0;i<sizeof syncs/sizeof *syncs;i++)if(!syncs[i].handle){slot=&syncs[i];break;}
  if(!slot){result=G_MEMORY;break;}
  slot->handle=token();
  memcpy(mem+(a[0]-base),&slot->handle,4);break;
 }
 case UINT32_C(0x889AE88C):{ /* SyncObjectDestroy */
  if(!initialized){result=G_UNINITIALIZED;break;}
  gpu_sync *sync=find_sync(a[0]);
  if(!sync){result=G_POINTER;break;}
  if(sync->rendering||sync->display_refs){result=G_VALUE;break;}
  *sync=(gpu_sync){0};break;
 }
 case UINT32_C(0xEC5C26B5):{ /* DisplayQueueAddEntry */
  if(!initialized){result=G_UNINITIALIZED;break;}
  if(!init_state.callback||!queue_create){result=G_DRIVER;break;}
  gpu_sync *old=find_sync(a[0]),*next=find_sync(a[1]);
  if(!old||!next||!range(a[2],init_state.data_size,base,size)){result=G_POINTER;break;}
  if(!init_state.worker){
   result=queue_create(init_state.callback,&init_state.worker,mem,size);
   if(result)break;
  }
  if(queue_count==init_state.max_pending){result=VX_GXM_WOULD_BLOCK;break;}
  unsigned slot=(queue_head+queue_count)%init_state.max_pending;
  memcpy(queue_data+slot*init_state.data_size,mem+(a[2]-base),init_state.data_size);
  queue[slot]=(display_entry){old,next};
  old->display_refs++;
  if(next!=old)next->display_refs++;
  queue_count++;break;
 }
 case UINT32_C(0xB98C5B0D): /* DisplayQueueFinish */
  if(!initialized)result=G_UNINITIALIZED;
  else if(queue_count)result=VX_GXM_WOULD_BLOCK;
  break;
 case UINT32_C(0x9F448E79):{ /* NotificationWait */
  if(!initialized){result=G_UNINITIALIZED;break;}
  if((a[0]&3)||!range(a[0],8,base,size)){result=G_POINTER;break;}
  uint32_t address=u32(mem+(a[0]-base)),value=u32(mem+(a[0]-base)+4);
  if((address&3)||!range(address,4,base,size)){result=G_POINTER;break;}
  if(u32(mem+(address-base))!=value)result=VX_GXM_WOULD_BLOCK;
  break;
 }
 case UINT32_C(0xB627DE66):
  if(!initialized){result=G_UNINITIALIZED;break;}
  if(queue_count||context.scene){result=G_VALUE;break;}
  release_initialize();reset_scene();vx_metal_destroy(transfer);transfer=0;initialized=0;memset(maps,0,sizeof maps);break;
 case UINT32_C(0xC61E34FC): /* MapMemory */
 case UINT32_C(0x008402C6): /* MapFragmentUsseMemory */
 case UINT32_C(0xFA437510):{ /* MapVertexUsseMemory */
  if(!initialized){result=G_UNINITIALIZED;break;}
  if((r[0]&4095)||(r[1]&4095)){result=G_ALIGNMENT;break;}
  if(!r[1]){result=G_VALUE;break;}
  if(!range(r[0],r[1],base,size)){result=G_POINTER;break;}
  if(nid==0xC61E34FC){
   if(!r[2]||(r[2]&~(GPU_READ|GPU_WRITE))){result=G_VALUE;break;}
   result=map_range(r[0],r[1],r[2]);
  }else{
   if((r[2]&3)||!range(r[2],4,base,size)){result=G_POINTER;break;}
   result=map_range(r[0],r[1],nid==0x008402C6?FRAGMENT_USSE:VERTEX_USSE);
   if(!result)memcpy(mem+(r[2]-base),&r[0],4);
  }
  break;
 }
 case UINT32_C(0x828C68E8): /* UnmapMemory */
 case UINT32_C(0x80CCEDBB): /* UnmapFragmentUsseMemory */
 case UINT32_C(0x099134F5): /* UnmapVertexUsseMemory */
  if(!initialized){result=G_UNINITIALIZED;break;}
  result=unmap_range(r[0],nid==0x80CCEDBB?FRAGMENT_USSE:nid==0x099134F5?VERTEX_USSE:0);break;
 case UINT32_C(0x45229C39): /* TransferFinish: all supported work is synchronous */
  if(!initialized)result=G_UNINITIALIZED;break;
 case UINT32_C(0x69DDFF5E):
 case UINT32_C(0x62312BF8):{
  if(!initialized){result=G_UNINITIALIZED;break;}
  int fill=nid==UINT32_C(0x69DDFF5E);unsigned count=fill?11:20;
  if((r[13]&3)||!range(r[13],(count-4)*4,base,size)){result=G_POINTER;break;}
  uint32_t a[20];for(unsigned i=0;i<4;i++)a[i]=r[i];
  for(unsigned i=4;i<count;i++)a[i]=u32(mem+(r[13]-base)+(i-4)*4);
  uint32_t width=fill?a[5]:a[0],height=fill?a[6]:a[1];
  unsigned bpp=pixel_size(fill?a[1]:a[5]);
  if(!bpp||(!fill&&(a[5]!=a[11]||a[4]||a[6]||a[12]))||
     (fill?(a[8]||a[9]||a[10]):(a[17]||a[18]||a[19]))){result=G_UNSUPPORTED;break;}
  uint32_t dst;size_t dst_extent;
  result=rectangle(fill?a[2]:a[13],fill?a[3]:a[14],fill?a[4]:a[15],width,height,
                    fill?a[7]:a[16],bpp,2,base,size,&dst,&dst_extent);
  if(result)break;
  uint32_t src=0;size_t src_extent=0;
  if(!fill){result=rectangle(a[7],a[8],a[9],width,height,a[10],bpp,1,base,size,&src,&src_extent);if(result)break;
   if((uint64_t)src+src_extent>dst&&(uint64_t)dst+dst_extent>src){result=G_UNSUPPORTED;break;}}
  result=device();if(result)break;
  int status=fill?vx_metal_transfer_fill(transfer,a[0],bpp,width,height,mem+(dst-base),dst_extent,a[7]):
    vx_metal_transfer_copy(transfer,bpp,width,height,mem+(src-base),src_extent,a[10],mem+(dst-base),dst_extent,a[16]);
  stats.metal_status=status;
  if(status){result=G_DRIVER;break;}
  if(fill)stats.fills++;else stats.copies++;stats.bytes+=(uint64_t)width*height*bpp;
  break;
 }
 default:return 0;
 }
 *out=result;return 1;
}


int vx_gxm_import(uint32_t nid,uint32_t r[16],uint8_t *mem,size_t size,uint32_t base,uint32_t *out){
 return gxm_command(nid,r,mem,size,base,NULL,out);
}
