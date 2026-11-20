#ifndef VITA_GUEST_H
#define VITA_GUEST_H
#include <stdint.h>
#include <stddef.h>
/* Resumable translated CPU state. PC bit zero carries ARM/Thumb state.
   This stores guest values only; executable memory is signed static ARM64 code. */
typedef struct {
 uint32_t r[16],f[64],pc,n,z,c,v,fpscr;
 uint64_t instructions,services;
 /* One virtual processor, cooperative guest threads. Reservation belongs to
    this context; the shared write generation detects even ABA conflicts. */
 uint64_t exclusive_epoch;
 uintptr_t exclusive_memory;
 uint32_t exclusive_address,exclusive_size,exclusive_valid;
 uint32_t tpidruro;
} vx_guest_state;
typedef int (*vx_guest_resume_fn)(vx_guest_state *,uint8_t *,size_t,uint32_t);
typedef struct {uint64_t threads_created,context_switches,waits,callbacks,instructions;} vx_kernel_stats;
int vx_runtime_run(vx_guest_state *,uint8_t *,size_t,vx_guest_resume_fn);
void vx_runtime_kernel_stats(vx_kernel_stats *);
/* Notify any out-of-band guest-memory write or processor context switch.
   Generated stores/import boundaries call this automatically. */
void vx_guest_memory_written(void);
#endif
