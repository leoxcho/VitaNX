#ifndef VITANX_DEVICES_H
#define VITANX_DEVICES_H
#include <stdint.h>
int vn_device_import(uint32_t nid,uint32_t *r,uint32_t *result);
void vn_devices_reset(void);
void vn_devices_set_gpi(uint32_t bits);
uint32_t vn_devices_get_gpi(void);
uint32_t vn_devices_get_gpo(void);
int vn_process_set_application_type(int type);
int vn_process_get_application_type(void);
#endif
