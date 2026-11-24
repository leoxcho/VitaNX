#ifndef VITA_AUDIODEC_H
#define VITA_AUDIODEC_H
#include <stddef.h>
#include <stdint.h>

typedef struct vx_atrac9 vx_atrac9;
vx_atrac9 *vx_atrac9_create(const uint8_t config[4], unsigned *channels, unsigned *rate,
                           unsigned *packet_bytes, unsigned *samples);
void vx_atrac9_destroy(vx_atrac9 *codec);
void vx_atrac9_clear(vx_atrac9 *codec);
/* Consumes one complete superframe. PCM capacity and return value count interleaved samples. */
int vx_atrac9_decode(vx_atrac9 *codec,const uint8_t *input,size_t bytes,
                     int16_t *output,size_t capacity);
int vx_audiodec_import(uint32_t nid,const uint32_t r[16],uint8_t *mem,size_t size,
                       uint32_t base,uint32_t *result);
void vx_audiodec_shutdown(void);
#endif
