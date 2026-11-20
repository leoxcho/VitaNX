#ifndef VITANX_MEMORY_H
#define VITANX_MEMORY_H
#include <stdint.h>
#include <stddef.h>
int vn_memory_import(uint32_t,uint32_t *,uint8_t *,size_t,uint32_t,uint32_t *);
const char *vn_memory_error(void);
#endif
