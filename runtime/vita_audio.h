#ifndef VITA_AUDIO_H
#define VITA_AUDIO_H
#include <stddef.h>
#include <stdint.h>
/* Bounded buffered S16 PCM AudioQueue bridge; independent ports mix in CoreAudio. Does not decode ATRAC or
   establish physical speaker output; tests distinguish callbacks from hearing. */
int vx_audio_import(uint32_t nid,uint32_t r[16],uint8_t *mem,size_t size,
                    uint32_t memory_base,uint32_t *out_result);
typedef struct {uint64_t ports_opened,buffers_queued,buffers_completed,frames_queued,frames_completed,timeouts;} vx_audio_stats;
void vx_audio_get_stats(vx_audio_stats *out);
#define VX_AUDIO_WOULD_BLOCK UINT32_C(0x7ffffff0)
/* Internal scheduler contract: pending imports never escape to guest code. */
void vx_audio_set_nonblocking(int enabled);
uint32_t vx_audio_port_generation(uint32_t number);
void vx_audio_pause(int paused);
void vx_audio_shutdown(void);
#endif
