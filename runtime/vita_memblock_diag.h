#ifndef VITA_MEMBLOCK_DIAG_H
#define VITA_MEMBLOCK_DIAG_H
#include <stdint.h>
/* Host-side allocation diagnostics, not part of the generated guest-region ABI.
   These codes are for VitaNX reports, never returned to guest applications. */
enum {
 VX_MEMBLOCK_OK=0, VX_MEMBLOCK_BAD_NAME=1, VX_MEMBLOCK_UNSUPPORTED_TYPE=2,
 VX_MEMBLOCK_BAD_SIZE=3, VX_MEMBLOCK_BAD_OPTIONS_ADDRESS=4,
 VX_MEMBLOCK_UNSUPPORTED_OPTIONS=5, VX_MEMBLOCK_BAD_ALIGNMENT=6,
 VX_MEMBLOCK_INVALID_HEAP=7, VX_MEMBLOCK_OUT_OF_MEMORY=8,
 VX_MEMBLOCK_NAME_UNTERMINATED=9
};
uint32_t vx_runtime_memblock_failure_reason(void);
#endif
