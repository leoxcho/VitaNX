#ifndef VITANX_FORMAT_H
#define VITANX_FORMAT_H
#include <stdint.h>
#include <stddef.h>
int vn_format_import(uint32_t,uint32_t *,uint8_t *,size_t,uint32_t,uint32_t *);
const char *vn_format_error(void);
#endif
