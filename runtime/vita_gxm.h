#ifndef VITA_GXM_H
#define VITA_GXM_H
#include <stdint.h>
#include <stddef.h>
/* Bounded synchronous SceGxm subset.
   Guest pointers are translated and checked, never passed as host pointers. */
typedef struct {uint64_t fills,copies,bytes,draws,scenes;int32_t metal_status;} vx_gxm_stats;
/* Catalog lifetime must cover runtime lifetime. Exact original GXP bytes are
   compared on registration; never accept guest-supplied MSL. */
typedef struct {
 const uint8_t *gxp;size_t size;const char *msl;
 uint32_t stage,uniform_words,input_count,texture_mask,varyings;
 uint32_t registers[16],components[16];
} vx_gxm_shader;
int vx_gxm_set_catalog(const vx_gxm_shader *shaders,size_t count);
/* Trusted host translator only: original validated guest GXP bytes in, stable
   exact-byte metadata out. Callback/result storage must outlive all programs. */
typedef const vx_gxm_shader *(*vx_gxm_shader_resolver)(const uint8_t *,size_t);
void vx_gxm_set_shader_resolver(vx_gxm_shader_resolver resolver);
int vx_gxm_float_import(uint32_t nid,uint32_t r[16],uint32_t f[64],uint8_t *mem,size_t size,uint32_t base,uint32_t *out);
int vx_gxm_import(uint32_t nid,uint32_t r[16],uint8_t *mem,size_t size,
                   uint32_t memory_base,uint32_t *out);
void vx_gxm_get_stats(vx_gxm_stats *out);
/* Lifetime counters distinguish startup not reached from rejected initialization. */
typedef struct {uint64_t initialize_calls,initializations,registration_calls;uint32_t initialized;} vx_gxm_readiness;
void vx_gxm_get_readiness(vx_gxm_readiness *out);
/* Private service result consumed by the cooperative guest scheduler. */
#define VX_GXM_WOULD_BLOCK UINT32_C(0xffffffff)
#define VX_GXM_ALLOCATE UINT32_C(0xfffffffe)
typedef struct {uint32_t context,stage,entry,user,bytes,output;} vx_gxm_allocation;
int vx_gxm_take_allocation(vx_gxm_allocation *request);
uint32_t vx_gxm_finish_allocation(const vx_gxm_allocation *request,uint32_t address,uint32_t length,
                                  uint8_t *mem,size_t size,uint32_t base);
uint32_t vx_gxm_queue_worker(void);
size_t vx_gxm_queue_take(uint32_t worker,uint8_t *data,size_t capacity);
void vx_gxm_queue_complete(uint32_t worker);
void vx_gxm_queue_detach(uint32_t worker);
typedef uint32_t (*vx_gxm_queue_create)(uint32_t,uint32_t *,uint8_t *,size_t);
typedef void (*vx_gxm_queue_destroy)(uint32_t);
void vx_gxm_set_queue_backend(vx_gxm_queue_create create,vx_gxm_queue_destroy destroy);
typedef struct {uint32_t flags,max_pending,callback,data_size,parameter_size,worker;} vx_gxm_initialize_state;
int vx_gxm_get_initialize_state(vx_gxm_initialize_state *out);

void vx_gxm_shutdown(void);
#endif
