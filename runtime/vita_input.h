#ifndef VITA_INPUT_H
#define VITA_INPUT_H
#include <stdint.h>
/* Host key state is retained per physical key, then combined. Multiple keys
   bound to one Vita button must not release one another. No guest pointers. */
typedef struct { uint8_t held[128]; } vx_input_keys;
static inline uint32_t vx_input_key_button(unsigned code){
 switch(code){case 126:return 0x10;case 124:return 0x20;case 125:return 0x40;case 123:return 0x80;
 case 6:return 0x4000;case 7:return 0x2000;case 12:return 0x8000;case 14:return 0x1000;
 case 36:return 8;case 48:return 1;case 8:case 56:return 0x100;case 9:case 60:return 0x200;default:return 0;}
}
static inline uint32_t vx_input_key_axis(unsigned code){
 switch(code){case 0:return 1;case 2:return 2;case 13:return 4;case 1:return 8;
 case 38:return 16;case 40:return 32;case 34:return 64;case 37:return 128;default:return 0;}
}
static inline void vx_input_key_set(vx_input_keys *state,unsigned code,int down){if(code<128)state->held[code]=!!down;}
static inline uint32_t vx_input_key_buttons(const vx_input_keys *state){uint32_t value=0;for(unsigned i=0;i<128;i++)if(state->held[i])value|=vx_input_key_button(i);return value;}
static inline uint32_t vx_input_key_axes(const vx_input_keys *state){uint32_t value=0;for(unsigned i=0;i<128;i++)if(state->held[i])value|=vx_input_key_axis(i);return value;}
#endif
