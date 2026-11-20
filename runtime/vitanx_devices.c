/* Original virtual debug device implementation, 2026-11-09.
   Contract: https://docs.vitasdk.org/group__SceDebugLedUser.html
   GPO retains the complete word; its low byte is the PDEL LED display.
   GPI is an independently configured input register. No physical host IO. */
#include "vitanx_devices.h"
static _Thread_local uint32_t gpi,gpo;
static _Thread_local int application_type=-1;
int vn_process_set_application_type(int type){if(type<0||type>2)return -1;application_type=type;return 0;}
int vn_process_get_application_type(void){return application_type;}
void vn_devices_reset(void){gpi=gpo=0;application_type=-1;}
void vn_devices_set_gpi(uint32_t bits){gpi=bits;}
uint32_t vn_devices_get_gpi(void){return gpi;}
uint32_t vn_devices_get_gpo(void){return gpo;}
int vn_device_import(uint32_t nid,uint32_t *r,uint32_t *result){
 switch(nid){
 case UINT32_C(0xfff8f7f0):if(application_type<0)return 0;*result=application_type==1;return 1;
 case UINT32_C(0x78e702d3):gpo=r[0];*result=0;return 1;
 case UINT32_C(0x14f582cf):*result=gpi;return 1;
 default:return 0;
 }
}
