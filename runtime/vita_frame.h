#ifndef VITA_FRAME_H
#define VITA_FRAME_H
#include <stdint.h>
/* Host pacing for offscreen homebrew. This is a monotonic software timer, not
   display VSync. Callers select the original rate explicitly; no game is patched.
   Simulation ticks use a separate fixed rational rate, never render frame count. */
typedef struct {
 uint64_t start_ns,last_ns,render_count,simulation_count;
 uint32_t render_hz,simulation_hz;
} vx_frame_clock;
typedef struct {
 uint64_t render_index,skipped_renders,simulation_steps,next_deadline_ns;
 uint32_t render_due,simulation_hz;
} vx_frame_sample;
enum {VX_FRAME_OK=0,VX_FRAME_INVALID=-1,VX_FRAME_CLOCK=-2,VX_FRAME_OVERFLOW=-3};
int vx_frame_init(vx_frame_clock *clock,uint32_t render_hz,uint32_t simulation_hz,uint64_t start_ns);
int vx_frame_next_deadline(const vx_frame_clock *clock,uint64_t *deadline_ns);
int vx_frame_advance(vx_frame_clock *clock,uint64_t now_ns,vx_frame_sample *sample);
int vx_frame_now(uint64_t *now_ns);
int vx_frame_wait(vx_frame_clock *clock,vx_frame_sample *sample);
#endif
