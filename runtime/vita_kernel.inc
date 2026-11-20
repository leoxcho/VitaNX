/* Included in vita_runtime.c: one host thread, shared mounts/Metal state, bounded
   resumable guest contexts. Public ABI from installed VitaSDK db/360 headers. */
__attribute__((weak,noinline)) int vx_guest_target_valid(uint32_t pc){(void)pc;return 0;}
#define KT_UID UINT32_C(0x80028021)
#define KT_DORMANT UINT32_C(0x80028027)
#define KT_NOT_DORMANT UINT32_C(0x80028028)
#define KW_DELETED UINT32_C(0x80028006)
#define KM_UID UINT32_C(0x80028141)
#define KM_RECURSIVE UINT32_C(0x80028142)
#define KM_BUSY UINT32_C(0x80028145)
#define KM_NOT_OWNED UINT32_C(0x80028146)
#define KE_UID UINT32_C(0x800280E1)
#define KE_COND UINT32_C(0x800280E3)
enum {KT_FREE,KT_NEW,KT_READY,KT_WAIT,KT_DEAD};
enum {KW_SLEEP=1,KW_SEMA,KW_MUTEX,KW_EVENT,KW_JOIN,KW_AUDIO,KW_LWMUTEX};
typedef struct {uint32_t kind,object,count,mode,out,timeout;uint64_t deadline,ticket;int callbacks;} kernel_wait;
typedef struct {
 uint32_t uid,entry,priority,stack_uid,stack_base,stack_size,status;
 int state,auto_delete,callback_active,callback_request,saved_state,tls_initialized;
 vx_guest_state cpu,saved_cpu;
 kernel_wait wait,saved_wait;
 uint64_t service_mark,instruction_mark;
 uint32_t fpscr_clear,fpscr_set;
} kernel_thread;
typedef struct {uint32_t uid,owner,count,attr;} kernel_mutex;
typedef struct {uint32_t uid,work,attr;} kernel_lwmutex;
static _Thread_local kernel_lwmutex kernel_lwmutexes[64];
typedef struct {uint32_t uid,work,mutex_uid,attr;} kernel_lwcond;
static _Thread_local kernel_lwcond kernel_lwconds[32];
typedef struct {uint32_t uid,bits,attr;} kernel_event;
typedef struct {uint32_t uid,owner,entry,user,count,arg;} kernel_callback;
static _Thread_local kernel_thread kernel_threads[32];
static _Thread_local kernel_mutex kernel_mutexes[32];
static _Thread_local kernel_event kernel_events[32];
static _Thread_local kernel_callback kernel_callbacks[32];
static _Thread_local vx_kernel_stats kernel_stats;
static _Thread_local int kernel_active,kernel_current,kernel_root_exited;
static _Thread_local uint64_t kernel_ticket;
static _Thread_local uint32_t kernel_module_root;
static _Thread_local uint32_t tls_base,tls_stride,tls_source,tls_filesz,tls_memsz;
static _Thread_local uint32_t tls_user_offset=256;
int vx_runtime_set_tls(uint32_t base,uint32_t stride,uint32_t source,uint32_t filesz,uint32_t memsz){
 if(kernel_active||!base||(base&15)||stride<256||stride&15||filesz>memsz||memsz>stride-256||(uint64_t)base+32ull*stride>UINT32_MAX)return -1;
 tls_base=base;tls_stride=stride;tls_source=source;tls_filesz=filesz;tls_memsz=memsz;tls_user_offset=256;return 0;
}
int vx_runtime_set_tls_user_offset(uint32_t offset){
 if(kernel_active||!tls_stride||offset<256||offset&15||offset>tls_stride||tls_memsz>tls_stride-offset)return -1;
 tls_user_offset=offset;return 0;
}
static int kernel_prepare_tls(kernel_thread*t,uint8_t*mem,size_t size){
 if(!tls_base)return 0;
 uint32_t base=tls_base+(uint32_t)(t-kernel_threads)*tls_stride;
 if(!range(base,tls_stride,size)||(tls_filesz&&!range(tls_source,tls_filesz,size)))return -1;
 if(!t->tls_initialized){
  vx_guest_memory_written();memset(guest_ptr(mem,base),0,tls_stride);
  if(tls_filesz)memcpy(guest_ptr(mem,base+tls_user_offset),guest_ptr(mem,tls_source),tls_filesz);
  t->tls_initialized=1;
 }
 t->cpu.tpidruro=base+tls_user_offset;return 0;
}
static void kernel_reset(void){
 process_param=0;tls_base=tls_stride=tls_source=tls_filesz=tls_memsz=0;tls_user_offset=256;
 memset(kernel_lwmutexes,0,sizeof kernel_lwmutexes);memset(kernel_lwconds,0,sizeof kernel_lwconds);
 memset(kernel_threads,0,sizeof kernel_threads);memset(kernel_mutexes,0,sizeof kernel_mutexes);
 memset(kernel_events,0,sizeof kernel_events);memset(kernel_callbacks,0,sizeof kernel_callbacks);
 memset(&kernel_stats,0,sizeof kernel_stats);kernel_active=kernel_current=kernel_root_exited=0;kernel_ticket=0;
}
void vx_runtime_kernel_stats(vx_kernel_stats *out){if(out)*out=kernel_stats;}
static kernel_thread *kernel_find_thread(uint32_t uid){for(int i=0;i<32;i++)if(kernel_threads[i].uid==uid&&uid)return &kernel_threads[i];return NULL;}
static kernel_mutex *kernel_find_mutex(uint32_t uid){for(int i=0;i<32;i++)if(kernel_mutexes[i].uid==uid&&uid)return &kernel_mutexes[i];return NULL;}
static kernel_event *kernel_find_event(uint32_t uid){for(int i=0;i<32;i++)if(kernel_events[i].uid==uid&&uid)return &kernel_events[i];return NULL;}
static kernel_callback *kernel_find_callback(uint32_t uid){for(int i=0;i<32;i++)if(kernel_callbacks[i].uid==uid&&uid)return &kernel_callbacks[i];return NULL;}
static uint32_t kernel_uid(void){return next_uid<INT32_MAX?next_uid++:0;}
static uint32_t kernel_owner(void){return kernel_active?kernel_threads[kernel_current].uid:1;}
static void kernel_reap(kernel_thread *t){memory_block *b=find_block(t->stack_uid);if(b)*b=(memory_block){0};*t=(kernel_thread){0};}
static uint32_t kernel_block(uint32_t kind,uint32_t object,uint32_t count,uint32_t mode,uint32_t out,uint32_t timeout,int callbacks,uint8_t *mem,size_t size){
 if(timeout&&!range(timeout,4,size))return K_ADDRESS;
 if(timeout&&!read32(guest_ptr(mem,timeout)))return K_TIMEOUT;
 if(!kernel_active)return VX_ENOSYS;
 kernel_thread *t=&kernel_threads[kernel_current];uint64_t now=0;process_time(&now);
 t->wait=(kernel_wait){kind,object,count,mode,out,timeout,timeout?now+read32(guest_ptr(mem,timeout)):0,++kernel_ticket,callbacks};
 t->state=KT_WAIT;kernel_stats.waits++;return 0;
}
/* Guest workarea ABI: owner +0, count +8, attributes +12, UID +16.
   Attribute 0x2000 orders waiters by guest priority, with FIFO ties; 2 is recursive.
   Guest memory remains authoritative for user-mode fast-path owner/count updates. */
static kernel_lwmutex *kernel_lw_find(uint32_t uid){for(int i=0;i<64;i++)if(uid&&kernel_lwmutexes[i].uid==uid)return &kernel_lwmutexes[i];return NULL;}
static uint32_t kernel_lw_get(kernel_lwmutex*m,uint8_t*mem,unsigned offset){return read32(guest_ptr(mem,m->work)+offset);}
static void kernel_lw_set(kernel_lwmutex*m,uint8_t*mem,uint32_t owner,uint32_t count){write32(guest_ptr(mem,m->work),owner);write32(guest_ptr(mem,m->work)+8,count);}
static kernel_thread *kernel_lw_first(kernel_lwmutex*m,uint64_t now){
 kernel_thread *best=NULL;
 for(int i=0;i<32;i++){kernel_thread*t=&kernel_threads[i];if(t->state!=KT_WAIT||t->wait.kind!=KW_LWMUTEX||t->wait.object!=m->uid||(t->wait.deadline&&t->wait.deadline<=now))continue;
  if(!best||((m->attr&0x2000)&&t->priority<best->priority)||((!(m->attr&0x2000)||t->priority==best->priority)&&t->wait.ticket<best->wait.ticket))best=t;
 }return best;
}
static int kernel_lw_import(uint32_t nid,uint32_t*r,uint8_t*mem,size_t size,uint32_t*out){
 int create=nid==0xDA6EC8EF||nid==0xB84EF718;
 if(!create&&nid!=0x244E76D2&&nid!=0x46E7BE7B&&nid!=0x3148C6B6&&nid!=0xA6A2C915&&nid!=0x91FA6614&&nid!=0x120AFC8C)return 0;
 uint32_t result=0;
 if(!r[0]||(r[0]&7)||!range(r[0],32,size)){*out=K_ADDRESS;return 1;}
 kernel_lwmutex*m=kernel_lw_find(read32(guest_ptr(mem,r[0])+16));
 if(create){
  if(!guest_name(mem,r[1],size)||!range(r[13],4,size)){result=K_ADDRESS;goto done;}
  if(r[2]&~0x2002u){result=0x8002000e;goto done;}
  if(r[3]>INT32_MAX||(!(r[2]&2)&&r[3]>1)){result=0x8002000f;goto done;}
  uint32_t option=read32(guest_ptr(mem,r[13]));
  if(option&&(!range(option,4,size)||read32(guest_ptr(mem,option))!=4)){result=K_ARGUMENT;goto done;}
  for(int i=0;i<64;i++)if(kernel_lwmutexes[i].uid&&kernel_lwmutexes[i].work==r[0]){result=0x80028180;goto done;}
  m=NULL;for(int i=0;i<64;i++)if(!kernel_lwmutexes[i].uid){m=&kernel_lwmutexes[i];break;}
  if(!m){result=K_MEMORY;goto done;}uint32_t uid=kernel_uid();if(!uid){result=K_MEMORY;goto done;}
  *m=(kernel_lwmutex){uid,r[0],r[2]};memset(guest_ptr(mem,r[0]),0,32);kernel_lw_set(m,mem,r[3]?kernel_owner():0,r[3]);
  write32(guest_ptr(mem,r[0])+12,r[2]);write32(guest_ptr(mem,r[0])+16,uid);goto done;
 }
 if(!m||m->work!=r[0]){result=(nid==0x91FA6614||nid==0x120AFC8C)?0x80028186:0x80028181;goto done;}
 if(nid==0x244E76D2){write32(guest_ptr(mem,m->work)+16,UINT32_MAX);*m=(kernel_lwmutex){0};goto done;}
 if(!r[1]||r[1]>INT32_MAX||(!(m->attr&2)&&r[1]!=1)){result=0x8002000f;goto done;}
 uint32_t owner=kernel_lw_get(m,mem,0),count=kernel_lw_get(m,mem,8);
 if(nid==0x91FA6614||nid==0x120AFC8C){
  if(owner!=kernel_owner()){result=0x80028186;goto done;}
  if((int32_t)count<0||r[1]>count){result=0x80028184;goto done;}
  count-=r[1];kernel_lw_set(m,mem,count?owner:0,count);goto done;
 }
 if(nid!=0xA6A2C915&&r[2]&&!range(r[2],4,size)){result=K_ADDRESS;goto done;}
 if(owner==kernel_owner()&&!(m->attr&2)){result=0x80028182;goto done;}
 if(!owner||owner==kernel_owner()){
  /* Lightweight recursion is an unsigned 32-bit counter, unlike heavy mutexes. */
  if(owner&&(int64_t)(int32_t)count+(int32_t)r[1]<0){result=0x80028183;goto done;}
  kernel_lw_set(m,mem,kernel_owner(),count+r[1]);goto done;
 }
 if(nid==0xA6A2C915){result=0x80028185;goto done;}
 result=kernel_block(KW_LWMUTEX,m->uid,r[1],0,0,r[2],nid==0x3148C6B6,mem,size);
 done:*out=result;return 1;
}
static int kernel_event_ready(kernel_event *e,uint32_t bits,uint32_t mode){return mode&1?(e->bits&bits)!=0:(e->bits&bits)==bits;}
static void kernel_event_take(kernel_event *e,uint32_t bits,uint32_t mode,uint32_t out,uint8_t *mem){
 if(out)write32(guest_ptr(mem,out),e->bits);
 if(mode&2)e->bits=0;else if(mode&4)e->bits&=~bits;
}
static void kernel_wake(uint8_t *mem,size_t size){
 (void)size;uint64_t now=0;process_time(&now);uint64_t previous=0;
 /* FIFO service order; unsupported priority/recursive semaphore attributes are
    rejected at creation rather than approximated silently. */
 for(int pass=0;pass<32;pass++){
  kernel_thread *t=NULL;for(int i=0;i<32;i++)if(kernel_threads[i].state==KT_WAIT&&kernel_threads[i].wait.ticket>previous&&(!t||kernel_threads[i].wait.ticket<t->wait.ticket))t=&kernel_threads[i];
  if(!t)break;previous=t->wait.ticket;kernel_wait *w=&t->wait;uint32_t result=0;int ready=0;
  if(w->kind==KW_LWMUTEX){kernel_lwmutex*m=kernel_lw_find(w->object);
   if(!m){ready=1;result=0x800281c2;}
   else if(!(w->deadline&&w->deadline<=now)&&!kernel_lw_get(m,mem,0)&&kernel_lw_first(m,now)==t){kernel_lw_set(m,mem,t->uid,w->count);ready=1;}
  }
  else if(w->kind==KW_SLEEP)ready=now>=w->deadline;
  else if(w->kind==KW_SEMA){semaphore *s=find_semaphore(w->object);if(!s){ready=1;result=KW_DELETED;}else if(s->count>=w->count){s->count-=w->count;ready=1;}}
  else if(w->kind==KW_MUTEX){kernel_mutex *m=kernel_find_mutex(w->object);if(!m){ready=1;result=KW_DELETED;}else if(!m->owner){m->owner=t->uid;m->count=w->count;ready=1;}}
  else if(w->kind==KW_EVENT){kernel_event *e=kernel_find_event(w->object);if(!e){ready=1;result=KW_DELETED;}else if(kernel_event_ready(e,w->count,w->mode)){kernel_event_take(e,w->count,w->mode,w->out,mem);ready=1;}}
  else if(w->kind==KW_JOIN){kernel_thread *other=kernel_find_thread(w->object);if(!other){ready=1;result=KW_DELETED;}else if(other->state==KT_DEAD){if(w->out)write32(guest_ptr(mem,w->out),other->status);ready=1;}}
#ifdef VX_ENABLE_AUDIO
  else if(w->kind==KW_AUDIO){uint32_t args[16]={0},audio_result;args[0]=w->object;args[1]=w->count;
   if(vx_audio_import(w->mode,args,mem,size,memory_base,&audio_result)&&audio_result!=VX_AUDIO_WOULD_BLOCK){ready=1;result=audio_result;}}
#endif
  if(!ready&&w->deadline&&now>=w->deadline){ready=1;result=w->kind==KW_SLEEP?0:w->kind==KW_AUDIO?UINT32_C(0x80260001):K_TIMEOUT;}
  if(ready){if(w->timeout)write32(guest_ptr(mem,w->timeout),(uint32_t)(w->deadline>now?w->deadline-now:0));t->cpu.r[0]=result;t->state=KT_READY;t->wait=(kernel_wait){0};}
 }
 for(int i=1;i<32;i++)if(kernel_threads[i].state==KT_DEAD&&kernel_threads[i].auto_delete)kernel_reap(&kernel_threads[i]);
}
static int kernel_callback_dispatch(kernel_thread *t,size_t size){
 if(t->callback_active||!(t->callback_request||(t->state==KT_WAIT&&t->wait.callbacks)))return 0;
 for(int i=0;i<32;i++){kernel_callback *cb=&kernel_callbacks[i];if(cb->uid&&cb->owner==t->uid&&cb->count){
  if(t->cpu.r[13]<memory_base+512u||!range(t->cpu.r[13]-512u,512,size)||(t->stack_uid&&t->cpu.r[13]<t->stack_base+512u))return -1;
  vx_guest_memory_written();t->cpu.exclusive_valid=0;
  t->saved_cpu=t->cpu;t->saved_state=t->state;t->saved_wait=t->wait;t->callback_active=1;
  t->cpu=(vx_guest_state){0};t->cpu.tpidruro=t->saved_cpu.tpidruro;t->cpu.pc=cb->entry;t->cpu.r[13]=(t->saved_cpu.r[13]-256)&~7u;t->cpu.r[14]=UINT32_MAX;
  t->cpu.r[0]=cb->uid;t->cpu.r[1]=cb->count;t->cpu.r[2]=cb->arg;t->cpu.r[3]=cb->user;
  cb->count=0;t->state=KT_READY;t->wait=(kernel_wait){0};kernel_stats.callbacks++;return 1;
 }}
 t->callback_request=0;return 0;
}
static int kernel_import(uint32_t nid,uint32_t r[16],uint8_t *mem,size_t size,uint32_t *out){
 uint32_t result=VX_ENOSYS;
 if(kernel_lw_import(nid,r,mem,size,out))return 1;
 if(nid==0x48C7EAE6||nid==0x721F6CB3){
  if(!r[0]||(r[0]&3)||!range(r[0],16,size)){*out=K_ADDRESS;return 1;}
  if(nid==0x721F6CB3){
   uint32_t uid=read32(guest_ptr(mem,r[0]));for(int i=0;i<32;i++)if(uid&&kernel_lwconds[i].uid==uid&&kernel_lwconds[i].work==r[0]){kernel_lwconds[i]=(kernel_lwcond){0};write32(guest_ptr(mem,r[0]),UINT32_MAX);*out=0;return 1;}
   *out=0x800281c1;return 1;
  }
  if(!guest_name(mem,r[1],size)||!range(r[13],4,size)||!range(r[3],32,size)){*out=K_ADDRESS;return 1;}
  if(r[2]&~0x2000u){*out=0x8002000e;return 1;}
  uint32_t option=read32(guest_ptr(mem,r[13]));if(option&&(!range(option,4,size)||read32(guest_ptr(mem,option))!=4)){*out=K_ARGUMENT;return 1;}
  kernel_lwmutex*m=kernel_lw_find(read32(guest_ptr(mem,r[3])+16));if(!m||m->work!=r[3]){*out=0x80028181;return 1;}
  for(int i=0;i<32;i++)if(kernel_lwconds[i].uid&&kernel_lwconds[i].work==r[0]){*out=0x800281c0;return 1;}
  for(int i=0;i<32;i++)if(!kernel_lwconds[i].uid){uint32_t uid=kernel_uid();if(!uid)break;kernel_lwconds[i]=(kernel_lwcond){uid,r[0],m->uid,r[2]};memset(guest_ptr(mem,r[0]),0,16);write32(guest_ptr(mem,r[0]),uid);write32(guest_ptr(mem,r[0])+4,m->uid);*out=0;return 1;}
  *out=K_MEMORY;return 1;
 }
 switch(nid){
 case UINT32_C(0xB295EB61):
 case UINT32_C(0xBACA6891):{
  if(!kernel_active||!tls_base)break;
  kernel_thread *t=nid==0xB295EB61?&kernel_threads[kernel_current]:kernel_find_thread(r[0]?r[0]:kernel_owner());
  uint32_t key=nid==0xB295EB61?r[0]:r[1];
  if(!t){result=KT_UID;break;}if(key>256||key*4>=tls_user_offset){result=K_ARGUMENT;break;}
  uint32_t base=tls_base+(uint32_t)(t-kernel_threads)*tls_stride;
  if(kernel_prepare_tls(t,mem,size)){result=K_ADDRESS;break;}
  result=base+4*key;break;
 }
 case UINT32_C(0xCC18FBAE):{
  /* VitaSDK vfp.h: clear/set FPSCR cumulative exception status, not trap enables.
     Generated regions keep FPSCR local until their mandatory import yield. Apply
     only after resume writes it back, so existing region binaries remain valid. */
  if(!kernel_active)break;
  if((r[0]|r[1])&~UINT32_C(0x0800009f)){result=K_ARGUMENT;break;}
  kernel_thread *t=&kernel_threads[kernel_current];
  t->fpscr_clear|=r[0];t->fpscr_set=(t->fpscr_set&~r[0])|r[1];result=0;break;
 }
 case UINT32_C(0x0FB972F9):result=kernel_owner();break;
 case UINT32_C(0xC5C11EE7):{ /* public 7-argument create */
  if(!kernel_active)break;
  if(!guest_name(mem,r[0],size)||!range(r[13],12,size)){result=K_ADDRESS;break;}
  uint32_t attr=read32(guest_ptr(mem,r[13])),affinity=read32(guest_ptr(mem,r[13])+4),option=read32(guest_ptr(mem,r[13])+8);
  if(attr||option||(affinity&~UINT32_C(0x70000))){result=VX_ENOSYS;break;}
  uint32_t priority=r[2]&0xfff;
  if((r[2]&~0xfffu)!=0&&(r[2]&~0xfffu)!=0x10000000u){result=K_ARGUMENT;break;}
  if(!priority||priority>511||r[3]<4096||r[3]>1024*1024){result=K_ARGUMENT;break;}
  if(!vx_guest_target_valid(r[1])){result=K_ADDRESS;break;}
  kernel_thread *t=NULL;for(int i=1;i<32;i++)if(!kernel_threads[i].uid){t=&kernel_threads[i];break;}
  if(!t){result=K_MEMORY;break;}
  uint32_t args[16]={0};args[0]=r[0];args[1]=0x0c20d060;args[2]=(r[3]+4095)&~4095u;
  uint32_t uid=vx_import(0xB9D5EBDE,args,mem,size);memory_block *block=find_block(uid);
  if(!block){result=uid;break;}
  *t=(kernel_thread){0};t->uid=kernel_uid();if(!t->uid){*block=(memory_block){0};result=K_MEMORY;break;}
  t->entry=r[1];t->priority=priority;t->stack_uid=uid;t->stack_base=block->base;t->stack_size=block->size;t->state=KT_NEW;
  result=t->uid;kernel_stats.threads_created++;break;
 }
 case UINT32_C(0xF08DE149):{
  kernel_thread *t=kernel_find_thread(r[0]);if(!t){result=KT_UID;break;}
  if(t->state!=KT_NEW){result=KT_NOT_DORMANT;break;}
  if(r[1]>t->stack_size-1024||(r[1]&&(!r[2]||!range(r[2],r[1],size)))){result=K_ADDRESS;break;}
  uint32_t sp=(t->stack_base+t->stack_size-r[1])&~7u;
  if(r[1])memmove(guest_ptr(mem,sp),guest_ptr(mem,r[2]),r[1]);
  t->cpu=(vx_guest_state){0};t->cpu.pc=t->entry;t->cpu.r[0]=r[1];t->cpu.r[1]=r[1]?sp:0;t->cpu.r[13]=sp;t->cpu.r[14]=UINT32_MAX;t->state=KT_READY;result=0;break;
 }
 case UINT32_C(0x1BBDE3D9):{
  kernel_thread *t=kernel_find_thread(r[0]);if(!t)result=KT_UID;
  else if(t->state!=KT_NEW&&t->state!=KT_DEAD)result=KT_NOT_DORMANT;
  else if(t==&kernel_threads[0])result=K_ARGUMENT;else {kernel_reap(t);result=0;}break;
 }
 case UINT32_C(0x0C8A38E1):case UINT32_C(0x1D17DECF):
  if(!kernel_active)return 0;
  kernel_threads[kernel_current].status=r[0];kernel_threads[kernel_current].state=KT_DEAD;
  kernel_threads[kernel_current].auto_delete=nid==UINT32_C(0x1D17DECF);
  if(!kernel_current)kernel_root_exited=1;result=r[0];break;
 case UINT32_C(0xDDB395A9):case UINT32_C(0xC54941ED):{
  kernel_thread *t=kernel_find_thread(r[0]);
  if(!t){result=KT_UID;break;}if(t->uid==kernel_owner()){result=K_ARGUMENT;break;}
  if((r[1]&&!range(r[1],4,size))||(r[2]&&!range(r[2],4,size))){result=K_ADDRESS;break;}
  if(t->state==KT_NEW){result=KT_DORMANT;break;}
  if(t->state==KT_DEAD){if(r[1])write32(guest_ptr(mem,r[1]),t->status);result=0;break;}
  result=kernel_block(KW_JOIN,r[0],0,0,r[1],r[2],nid==UINT32_C(0xC54941ED),mem,size);break;
 }
 case UINT32_C(0x4B675D05):case UINT32_C(0x9C0180E1):{
  if(!kernel_active)return 0;
  uint64_t now=0;process_time(&now);kernel_thread *t=&kernel_threads[kernel_current];
  t->wait=(kernel_wait){.kind=KW_SLEEP,.deadline=now+r[0],.ticket=++kernel_ticket,.callbacks=nid==UINT32_C(0x9C0180E1)};
  t->state=KT_WAIT;kernel_stats.waits++;result=0;break;
 }
 case UINT32_C(0x0C7B834B):{
  if(!kernel_active)return 0;
  semaphore *s=find_semaphore(r[0]);if(!s){result=K_UID;break;}
  if(!r[1]||r[1]>INT32_MAX){result=K_ARGUMENT;break;}
  if(r[2]&&!range(r[2],4,size)){result=K_ADDRESS;break;}
  if(s->count>=r[1]){s->count-=r[1];result=0;break;}
  result=kernel_block(KW_SEMA,r[0],r[1],0,0,r[2],0,mem,size);break;
 }
 case UINT32_C(0xED53334A):{
  if(!guest_name(mem,r[0],size)){result=K_ADDRESS;break;}
  if(r[1]&~2u||r[3]){result=VX_ENOSYS;break;}
  if(r[2]>INT32_MAX||(!(r[1]&2)&&r[2]>1)){result=K_ARGUMENT;break;}
  result=K_MEMORY;for(int i=0;i<32;i++)if(!kernel_mutexes[i].uid){uint32_t uid=kernel_uid();if(uid){kernel_mutexes[i]=(kernel_mutex){uid,r[2]?kernel_owner():0,r[2],r[1]};result=uid;}break;}break;
 }
 case UINT32_C(0xCB78710D):{kernel_mutex *m=kernel_find_mutex(r[0]);if(!m)result=KM_UID;else{*m=(kernel_mutex){0};result=0;}break;}
 case UINT32_C(0x1D8D7945):case UINT32_C(0x2BDAA524):case UINT32_C(0x72FC1F54):{
  kernel_mutex *m=kernel_find_mutex(r[0]);if(!m){result=KM_UID;break;}
  if(!r[1]||r[1]>INT32_MAX||(!(m->attr&2)&&r[1]!=1)){result=K_ARGUMENT;break;}
  if(nid!=UINT32_C(0x72FC1F54)&&r[2]&&!range(r[2],4,size)){result=K_ADDRESS;break;}
  if(m->owner==kernel_owner()&&!(m->attr&2)){result=KM_RECURSIVE;break;}
  if(!m->owner||m->owner==kernel_owner()){
   if(r[1]>INT32_MAX-m->count){result=UINT32_C(0x80028143);break;}
   m->owner=kernel_owner();m->count+=r[1];result=0;break;
  }
  if(nid==UINT32_C(0x72FC1F54)){result=KM_BUSY;break;}
  result=kernel_block(KW_MUTEX,r[0],r[1],0,0,r[2],nid==UINT32_C(0x2BDAA524),mem,size);break;
 }
 case UINT32_C(0x1A372EC8):{
  kernel_mutex *m=kernel_find_mutex(r[0]);if(!m)result=KM_UID;
  else if(m->owner!=kernel_owner())result=KM_NOT_OWNED;
  else if(!r[1]||r[1]>m->count)result=UINT32_C(0x80028144);
  else{m->count-=r[1];if(!m->count)m->owner=0;result=0;}break;
 }
 case UINT32_C(0x8516D040):{
  if(!guest_name(mem,r[0],size)){result=K_ADDRESS;break;}
  if(r[1]&~0x1000u||r[3]){result=VX_ENOSYS;break;}
  result=K_MEMORY;for(int i=0;i<32;i++)if(!kernel_events[i].uid){uint32_t uid=kernel_uid();if(uid){kernel_events[i]=(kernel_event){uid,r[2],r[1]};result=uid;}break;}break;
 }
 case UINT32_C(0xEC94DFF7):case UINT32_C(0x4CB87CA7):case UINT32_C(0x5840162C):{
  kernel_event *e=kernel_find_event(r[0]);if(!e){result=KE_UID;break;}
  if(nid==UINT32_C(0x5840162C))*e=(kernel_event){0};else if(nid==UINT32_C(0xEC94DFF7))e->bits|=r[1];else e->bits&=r[1];result=0;break;
 }
 case UINT32_C(0x1FBB0FE1):case UINT32_C(0x83C0E2AF):case UINT32_C(0xE737B1DF):{
  kernel_event *e=kernel_find_event(r[0]);if(!e){result=KE_UID;break;}
  if(!r[1]||(r[2]&~7u)||((r[2]&6)==6)){result=K_ARGUMENT;break;}
  if(r[3]&&!range(r[3],4,size)){result=K_ADDRESS;break;}
  uint32_t timeout=0;
  if(nid!=UINT32_C(0x1FBB0FE1)){if(!range(r[13],4,size)){result=K_ADDRESS;break;}timeout=read32(guest_ptr(mem,r[13]));if(timeout&&!range(timeout,4,size)){result=K_ADDRESS;break;}}
  if(kernel_event_ready(e,r[1],r[2])){kernel_event_take(e,r[1],r[2],r[3],mem);result=0;break;}
  if(nid==UINT32_C(0x1FBB0FE1)){result=KE_COND;break;}
  if(!(e->attr&0x1000)){int busy=0;for(int i=0;i<32;i++)if(kernel_threads[i].state==KT_WAIT&&kernel_threads[i].wait.kind==KW_EVENT&&kernel_threads[i].wait.object==e->uid)busy=1;if(busy){result=UINT32_C(0x800280E2);break;}}
  result=kernel_block(KW_EVENT,r[0],r[1],r[2],r[3],timeout,nid==UINT32_C(0xE737B1DF),mem,size);break;
 }
 case UINT32_C(0xB19CF7E9):{
  if(!kernel_active)break;
  if(!guest_name(mem,r[0],size)||!vx_guest_target_valid(r[2])){result=K_ADDRESS;break;}
  if(r[1]){result=VX_ENOSYS;break;}
  result=K_MEMORY;for(int i=0;i<32;i++)if(!kernel_callbacks[i].uid){uint32_t uid=kernel_uid();if(uid){kernel_callbacks[i]=(kernel_callback){uid,kernel_owner(),r[2],r[3],0,0};result=uid;}break;}break;
 }
 case UINT32_C(0xD469676B):case UINT32_C(0x30741EF2):case UINT32_C(0x038644D5):case UINT32_C(0xA4683592):{
  kernel_callback *cb=kernel_find_callback(r[0]);if(!cb){result=K_UID;break;}
  if(nid==UINT32_C(0xD469676B)){*cb=(kernel_callback){0};result=0;}
  else if(nid==UINT32_C(0x30741EF2)){cb->count=0;result=0;}
  else if(nid==UINT32_C(0x038644D5))result=cb->count;
  else if(cb->count==INT32_MAX)result=K_ARGUMENT;else {cb->count++;cb->arg=r[1];result=0;}break;
 }
 case UINT32_C(0xE53E41F6):if(kernel_active)kernel_threads[kernel_current].callback_request=1;result=0;break;
 default:return 0;
 }
 *out=result;return 1;
}
int vx_runtime_run(vx_guest_state *initial,uint8_t *mem,size_t size,vx_guest_resume_fn resume){
 if(!initial||!mem||!resume||kernel_active)return -8;
 memset(kernel_threads,0,sizeof kernel_threads);memset(&kernel_stats,0,sizeof kernel_stats);
#ifdef VX_ENABLE_AUDIO
 vx_audio_set_nonblocking(1);
#endif
 kernel_active=1;kernel_current=kernel_root_exited=0;kernel_threads[0]=(kernel_thread){.uid=kernel_module_root?kernel_module_root:1,.priority=256,.state=KT_READY,.cpu=*initial};
 int result=0,last=31;
 for(;;){
  if(stop_reason)break;
#ifdef VX_ENABLE_WINDOW
  vx_window_input host_input;
  if(!vx_display_input_state(&host_input)){
   if(host_input.close_requested){stop_reason=VX_STOP_PROCESS;stop_status=0;break;}
   if(host_input.connected&&host_input.suspended){
#ifdef VX_ENABLE_AUDIO
    vx_audio_pause(1);
#endif
    struct timespec pause={0,5000000};while(nanosleep(&pause,&pause)&&errno==EINTR){}continue;}
  }
#endif
#ifdef VX_ENABLE_AUDIO
  vx_audio_pause(0);
#endif
  for(int i=0;i<64;i++){kernel_lwmutex*m=&kernel_lwmutexes[i];if(!m->uid)continue;
  uint32_t owner=kernel_lw_get(m,mem,0);kernel_thread*t=kernel_find_thread(owner);
  if(t&&t->state==KT_DEAD)kernel_lw_set(m,mem,0,0);
 }
 kernel_wake(mem,size);
  for(int i=0;i<32;i++)if(kernel_threads[i].uid&&kernel_callback_dispatch(&kernel_threads[i],size)<0){result=-2;break;}
  if(result)break;
  int pick=-1;uint32_t priority=UINT32_MAX;
  for(int j=1;j<=32;j++){int i=(last+j)%32;kernel_thread *t=&kernel_threads[i];if(t->state==KT_READY&&t->priority<priority){priority=t->priority;pick=i;}}
  if(pick<0){
   int alive=0,timed=0;for(int i=0;i<32;i++)if(kernel_threads[i].state==KT_WAIT){alive=1;timed|=kernel_threads[i].wait.deadline!=0;}
   if(!alive){if(kernel_root_exited){stop_reason=VX_STOP_THREAD;stop_status=kernel_threads[0].status;}break;}
   if(!timed){result=-7;break;} /* diagnosed deadlock, never fake successful waits */
   struct timespec pause={0,1000000};while(nanosleep(&pause,&pause)&&errno==EINTR){}continue;
  }
  if(pick!=last){vx_guest_memory_written();kernel_threads[pick].cpu.exclusive_valid=0;}
  kernel_current=pick;last=pick;kernel_thread *t=&kernel_threads[pick];kernel_stats.context_switches++;
  if(kernel_prepare_tls(t,mem,size)){result=-2;break;}
  uint64_t before=t->cpu.instructions;int rc=resume(&t->cpu,mem,size,10000);kernel_stats.instructions+=t->cpu.instructions-before;
  t->cpu.fpscr=(t->cpu.fpscr&~t->fpscr_clear)|t->fpscr_set;
  t->fpscr_clear=t->fpscr_set=0;
  if(rc<0){result=rc;break;}
  if(t->cpu.services!=t->service_mark){t->service_mark=t->cpu.services;t->instruction_mark=t->cpu.instructions;}
  else if(t->cpu.instructions-t->instruction_mark>1000000u){result=-4;break;}
  if(t->state==KT_DEAD)continue;
  if(!rc){
   if(t->callback_active){vx_guest_memory_written();t->cpu=t->saved_cpu;t->cpu.exclusive_valid=0;t->state=t->saved_state;t->wait=t->saved_wait;t->callback_active=0;if(t->callback_request)t->cpu.r[0]=1;t->callback_request=0;t->service_mark=t->cpu.services;t->instruction_mark=t->cpu.instructions;}
   else {t->status=t->cpu.r[0];t->state=KT_DEAD;}
  }
 }
 *initial=kernel_threads[0].cpu;
 if(stop_reason)initial->r[0]=stop_status;
 for(int i=1;i<32;i++)if(kernel_threads[i].uid)kernel_reap(&kernel_threads[i]);
#ifdef VX_ENABLE_AUDIO
 vx_audio_set_nonblocking(0);
#endif
 kernel_active=0;return result;
}

/* Each loader initializer runs as its own guest thread in the shared process. */
int vx_runtime_run_module(vx_guest_state *state,uint8_t *mem,size_t size,vx_guest_resume_fn resume){
 if(kernel_active||kernel_module_root)return -8;
 kernel_module_root=kernel_uid();if(!kernel_module_root)return -8;
 int result=vx_runtime_run(state,mem,size,resume);kernel_module_root=0;return result;
}
