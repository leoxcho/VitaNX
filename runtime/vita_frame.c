#define _POSIX_C_SOURCE 200809L
#include "vita_frame.h"
#include <errno.h>
#include <string.h>
#include <time.h>
#define NS UINT64_C(1000000000)
static int valid(const vx_frame_clock *clock){
 return clock&&clock->render_hz&&clock->render_hz<=1000&&clock->simulation_hz&&clock->simulation_hz<=1000&&clock->last_ns>=clock->start_ns;
}
int vx_frame_init(vx_frame_clock *clock,uint32_t render_hz,uint32_t simulation_hz,uint64_t start_ns){
 if(!clock||!render_hz||render_hz>1000||!simulation_hz||simulation_hz>1000)return VX_FRAME_INVALID;
 memset(clock,0,sizeof *clock);clock->start_ns=start_ns;clock->last_ns=start_ns;
 clock->render_hz=render_hz;clock->simulation_hz=simulation_hz;return VX_FRAME_OK;
}
int vx_frame_next_deadline(const vx_frame_clock *clock,uint64_t *deadline_ns){
 if(!valid(clock)||!deadline_ns)return VX_FRAME_INVALID;
 /* Ceil prevents an integer-nanosecond deadline from firing before its event. */
 __uint128_t delay=((__uint128_t)clock->render_count*NS+clock->render_hz-1)/clock->render_hz;
 if(delay>UINT64_MAX-clock->start_ns)return VX_FRAME_OVERFLOW;
 *deadline_ns=clock->start_ns+(uint64_t)delay;return VX_FRAME_OK;
}
int vx_frame_advance(vx_frame_clock *clock,uint64_t now_ns,vx_frame_sample *sample){
 if(!valid(clock)||!sample||now_ns<clock->last_ns)return VX_FRAME_INVALID;
 uint64_t elapsed=now_ns-clock->start_ns;
 uint64_t renders=(uint64_t)((__uint128_t)elapsed*clock->render_hz/NS)+1;
 uint64_t ticks=(uint64_t)((__uint128_t)elapsed*clock->simulation_hz/NS);
 if(renders<clock->render_count||ticks<clock->simulation_count)return VX_FRAME_INVALID;
 vx_frame_clock next=*clock;next.last_ns=now_ns;next.render_count=renders;next.simulation_count=ticks;
 uint64_t deadline;int status=vx_frame_next_deadline(&next,&deadline);
 if(status)return status;
 vx_frame_sample value={0};value.render_index=renders-1;
 value.render_due=renders>clock->render_count;
 value.skipped_renders=value.render_due?renders-clock->render_count-1:0;
 value.simulation_steps=ticks-clock->simulation_count;
 value.simulation_hz=clock->simulation_hz;value.next_deadline_ns=deadline;
 *clock=next;*sample=value;return VX_FRAME_OK;
}
int vx_frame_now(uint64_t *now_ns){
 if(!now_ns)return VX_FRAME_INVALID;
 struct timespec ts;if(clock_gettime(CLOCK_MONOTONIC,&ts)||ts.tv_sec<0)return VX_FRAME_CLOCK;
 if((uint64_t)ts.tv_sec>UINT64_MAX/NS)return VX_FRAME_OVERFLOW;
 uint64_t base=(uint64_t)ts.tv_sec*NS;
 if((uint64_t)ts.tv_nsec>UINT64_MAX-base)return VX_FRAME_OVERFLOW;
 *now_ns=base+(uint64_t)ts.tv_nsec;return VX_FRAME_OK;
}
int vx_frame_wait(vx_frame_clock *clock,vx_frame_sample *sample){
 if(!sample)return VX_FRAME_INVALID;
 uint64_t deadline,now;int status=vx_frame_next_deadline(clock,&deadline);
 if(status)return status;
 for(;;){
  status=vx_frame_now(&now);if(status)return status;
  if(now>=deadline)break;
  uint64_t wait=deadline-now;
  struct timespec ts={(time_t)(wait/NS),(long)(wait%NS)};
  while(nanosleep(&ts,&ts))if(errno!=EINTR)return VX_FRAME_CLOCK;
 }
 return vx_frame_advance(clock,now,sample);
}
