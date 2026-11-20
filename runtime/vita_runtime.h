#ifndef VITA_RUNTIME_H
#define VITA_RUNTIME_H
#include <stddef.h>
#include <stdint.h>
#include "vita_guest.h"
/* Single guest instance per host thread. Explicit allowlisted descriptors only.
   _sceIoOpen uses r0=path, r1=flags, r2=mode, r3=non-null 8-byte option block.
   Reserved option bytes are ignored as in firmware 3.60. Creation uses host 0600.
   Guest pointers use the configured 32-bit guest virtual base; no host pointers cross this API. */
/* Default base is zero for synthetic fixtures. Configure before mount/import.
   All checked guest pointers are translated by subtracting base, never rebased
   in guest register state. Shutdown resets base to zero. */
void vx_runtime_set_memory_base(uint32_t base);
uint32_t vx_runtime_get_memory_base(void);
/* Enumerates only imports compiled into this runtime. A declared import is a
   bounded service, not a claim of full firmware behavior or module loading.
   Names/features/limits are static UTF-8 strings owned by the runtime. */
typedef struct {
 uint32_t nid;
 const char *name;
 const char *feature;
 const char *limits;
} vx_import_capability;
/* Stable optional-feature list for build/preflight tools, parsed without having
   to load host libraries. Kept consistent with the compiled capability table. */
#define VX_WINDOW_IMPORT_NIDS UINT32_C(0x67E7AB83), UINT32_C(0xA497B150), UINT32_C(0xA9C3CED6), UINT32_C(0xEC752AAF), UINT32_C(0x1B9C5D14), UINT32_C(0x26531526), UINT32_C(0x10A2CA25), UINT32_C(0xB18370C2), UINT32_C(0x41194411), UINT32_C(0xFF082DF0), UINT32_C(0x169A1D58)
const vx_import_capability *vx_runtime_import_capabilities(size_t *count);
/* Reserve a page-aligned heap within the caller's guest backing, separate from
   image and stack. Imports verify the reservation fits the actual backing.
   No guest addresses are host pointers. Default capacity zero disables alloc. */
int vx_runtime_set_heap(uint32_t guest_start, uint32_t capacity);
uint32_t vx_import_vfp(uint32_t nid,uint32_t r[16],uint32_t f[64],uint8_t *mem,size_t size);
uint32_t vx_import(uint32_t nid, uint32_t r[16], uint8_t *mem, size_t size);
/* Reserve 32 disjoint per-thread TLS slices outside the guest heap/stack.
   First 256 bytes hold 64 bounded kernel key slots; module TLS follows. */
void vx_runtime_set_process_param(uint32_t address);
int vx_runtime_run_module(vx_guest_state *,uint8_t *,size_t,vx_guest_resume_fn);
int vx_runtime_set_tls(uint32_t base,uint32_t stride,uint32_t source,uint32_t filesz,uint32_t memsz);
/* Legacy bounded layout defaults to 256; commercial Vita user TLS follows
   the 0x800-byte kernel prefix. Configure before executing any thread. */
int vx_runtime_set_tls_user_offset(uint32_t offset);
int vx_runtime_mount(const char *save_directory);
/* Optional app0 mount: nested regular assets, read only, no symlink components.
   Neither mount can replace an active mount. Shutdown closes both and all files. */
int vx_runtime_mount_app(const char *app_directory);
/* The scheduler runs bounded guest threads on one host thread. Process exits
   stop the instance; child exits stop only that guest context. Outside scheduled
   execution, thread exits stop the direct import caller. Never calls host exit().
   The first exit request wins, and status retains all 32 guest bits. */
enum { VX_STOP_NONE=0, VX_STOP_PROCESS=1, VX_STOP_THREAD=2 };
int vx_runtime_stop_requested(uint32_t *exit_status);
void vx_runtime_reset_stop(void);
/* Process-time imports use monotonic microseconds since initial mount/import.
   Shutdown resets this origin, mounts, open files and guest stop state. */
void vx_runtime_shutdown(void);
#endif
