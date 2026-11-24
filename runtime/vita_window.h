#ifndef VITA_WINDOW_H
#define VITA_WINDOW_H
#include <stdint.h>
#include "vita_metal.h"
/* Main-thread Cocoa/CAMetalLayer owner. No host handles cross the guest ABI. */
typedef struct vx_window vx_window;
typedef struct {
 uint32_t buttons;
 uint8_t lx,ly,rx,ry;
 uint32_t ext_buttons;
 uint8_t left_trigger,right_trigger;
 uint16_t touch_x[2],touch_y[2];
 uint8_t touch_down[2],touch_id[2];
 int connected,close_requested,suspended;
} vx_window_input;
typedef struct {
 uint64_t frames_presented,events_processed,key_events;
 int fullscreen,closed,controller_connected;
} vx_window_stats;
int vx_window_create(const char *title,uint32_t width,uint32_t height,
                     int fullscreen,int vsync,int linear_filter,vx_window **out);
int vx_window_present(vx_window *window,vx_metal *framebuffer);
int vx_window_pump(vx_window *window);
int vx_window_close_requested(vx_window *window);
int vx_window_set_fullscreen(vx_window *window,int fullscreen);
int vx_window_input_state(vx_window *window,vx_window_input *out);
void vx_window_get_stats(vx_window *window,vx_window_stats *out);
void vx_window_destroy(vx_window *window);
#endif
