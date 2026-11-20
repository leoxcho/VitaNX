#ifndef VITA_DISPLAY_H
#define VITA_DISPLAY_H
#include <stddef.h>
#include <stdint.h>
/* Limited SceDisplayUser ABI, verified against VitaSDK display.h and db/360.
   Guest framebuffer is software-rendered A8B8G8R8, presented through a Metal
   sampling pass. Optional Cocoa windows use CAMetalLayer display synchronization.
   This does not implement GXM command buffers or GXP shader translation.
   Clock configuration changes modeled software vblank pacing, not game physics.
   Optional target size scales presentation; it does not increase guest rendering. */
typedef struct {
 uint64_t frames_submitted,frames_presented,wait_calls,simulation_ticks;
 uint32_t guest_width,guest_height,target_width,target_height,render_hz,simulation_hz;
 int32_t metal_status;
} vx_display_stats;
int vx_display_configure(uint32_t render_hz,uint32_t simulation_hz,
                         uint32_t target_width,uint32_t target_height);
int vx_display_set_filter(int linear_filter);
#ifdef VX_ENABLE_WINDOW
#include "vita_window.h"
int vx_display_configure_window(const char *title,int fullscreen,int vsync,int linear_filter);
int vx_display_input_state(vx_window_input *out);
int vx_display_close_requested(void);
void vx_display_window_stats(vx_window_stats *out);
#endif
/* Returns 1 for a recognized NID, 0 for unknown. Writes result only if handled.
   Guest addresses are checked then translated relative to memory_base. */
int vx_display_import(uint32_t nid,uint32_t r[16],uint8_t *mem,size_t size,
                       uint32_t memory_base,uint32_t *out_result);
int vx_display_readback(uint8_t *rgba,size_t capacity);
void vx_display_get_stats(vx_display_stats *stats);
void vx_display_shutdown(void);
#endif
