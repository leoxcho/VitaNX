/* vitanx 2026-11-09: shared process state for on-demand native translations.
   All loaded blocks use this monitor and the same compatibility runtime. */
#include "vita_runtime.h"
#include "vitanx_devices.h"
#include "vitanx_format.h"
#include "vitanx_memory.h"
#include <stddef.h>
_Thread_local uint64_t vx_exclusive_epoch;
void vx_guest_memory_written(void){vx_exclusive_epoch++;}
typedef int (*target_fn)(uint32_t);
static target_fn active_target;
void vn_set_target_validator(target_fn fn){active_target=fn;}
int vx_guest_target_valid(uint32_t pc){return active_target?active_target(pc):0;}
size_t vn_state_size(void){return sizeof(vx_guest_state);}
size_t vn_state_monitor_offset(void){return offsetof(vx_guest_state,exclusive_epoch);}

/* Native guest stores may not alter executable input bytes. Runtime-import
   writes are additionally checked at the service return boundary by the host. */
static struct {uintptr_t start,end;} code_ranges[512];
static size_t range_count;
int vn_protect_executable(const uint8_t *p,size_t size){
 uintptr_t start=(uintptr_t)p;
 if(range_count==512||size>UINTPTR_MAX-start)return -1;
 code_ranges[range_count].start=start;code_ranges[range_count++].end=start+size;
 return 0;
}
int vn_guest_write_allowed(const uint8_t *p,size_t size){
 uintptr_t start=(uintptr_t)p;
 if(size>UINTPTR_MAX-start)return 0;
 for(size_t i=0;i<range_count;i++)
  if(start<code_ranges[i].end&&code_ranges[i].start<start+size)return 0;
 return 1;
}

void vn_reset_executable(void){range_count=0;}
/* Bounded import diagnostics; the actual runtime decides every result. */
static struct {uint32_t nid,args[4],result,fault,r1_after;} import_trace[64];
static size_t import_count;
static _Thread_local const char *last_import_error;
const char *vn_import_error(void){return last_import_error;}
static size_t trace_begin(uint32_t nid,uint32_t *r){
 size_t slot=import_count++%64;import_trace[slot].nid=nid;import_trace[slot].fault=0;
 for(int i=0;i<4;i++)import_trace[slot].args[i]=r[i];return slot;
}
uint32_t vn_import(uint32_t nid,uint32_t *r,uint8_t *mem,size_t size){
 size_t slot=trace_begin(nid,r);uint32_t result;last_import_error=NULL;
 int handled=vn_device_import(nid,r,&result);
 if(!handled){handled=vn_memory_import(nid,r,mem,size,vx_runtime_get_memory_base(),&result);
  if(handled<0){last_import_error=vn_memory_error();import_trace[slot].fault=1;import_trace[slot].result=r[0];import_trace[slot].r1_after=r[1];return r[0];}}
 if(!handled)handled=vn_format_import(nid,r,mem,size,vx_runtime_get_memory_base(),&result);
 if(handled<0){last_import_error=vn_format_error();import_trace[slot].fault=1;import_trace[slot].result=r[0];import_trace[slot].r1_after=r[1];return r[0];}
 if(!handled)result=vx_import(nid,r,mem,size);
 else {vx_guest_memory_written();r[0]=result;}
 import_trace[slot].result=result;import_trace[slot].r1_after=r[1];return result;
}
uint32_t vn_import_vfp(uint32_t nid,uint32_t *r,uint32_t *f,uint8_t *mem,size_t size){
 size_t slot=trace_begin(nid,r);last_import_error=NULL;uint32_t result=vx_import_vfp(nid,r,f,mem,size);
 import_trace[slot].result=result;import_trace[slot].r1_after=r[1];return result;
}
size_t vn_import_trace_count(void){return import_count;}
uint32_t vn_import_trace_field(size_t index,unsigned field){
 if(index>=import_count||import_count-index>64||field>7)return 0;
 size_t slot=index%64;
 return field==7?import_trace[slot].r1_after:field==6?import_trace[slot].fault:field==0?import_trace[slot].nid:field==5?import_trace[slot].result:import_trace[slot].args[field-1];
}
