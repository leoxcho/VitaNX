#ifndef VITA_NGS_H
#define VITA_NGS_H
#include <stddef.h>
#include <stdint.h>

typedef struct {
    uint32_t entry;
    uint32_t args[7];
} vx_ngs_event;

int vx_ngs_import(uint32_t nid, const uint32_t regs[16], uint8_t *memory,
                  size_t size, uint32_t base, uint32_t owner, uint32_t *result);
int vx_ngs_pop_event(uint32_t owner, vx_ngs_event *event);
void vx_ngs_shutdown(void);
#endif
