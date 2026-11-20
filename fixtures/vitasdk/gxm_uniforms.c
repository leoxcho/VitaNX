/* Genuine SDK reflection/uniform ABI test using a staged, unchanged GXP asset. */
#include <psp2/gxm.h>
#include <psp2/io/fcntl.h>
#include <psp2/kernel/processmgr.h>
static unsigned shader[1024];
static float uniform[8]={-1,-1,-1,-1,-1,-1,-1,-1};
static const float values[2]={0.25f,0.75f};
static const char pass[]="VitaSDK GXM reflection/uniform PASS\n";
int module_start(unsigned argc,const void *argp){
 (void)argc;(void)argp;int status=1;
 int fd=sceIoOpen("app0:/shader.vpo",SCE_O_RDONLY,0);
 if(fd<0)goto done;
 int count=sceIoRead(fd,shader,sizeof shader);sceIoClose(fd);
 if(count<156||sceGxmProgramCheck((SceGxmProgram *)shader))goto done;
 SceGxmProgram *program=(SceGxmProgram *)shader;
 const SceGxmProgramParameter *p=sceGxmProgramFindParameterByName(program,"gvColor");
 status=2;if(!p||sceGxmProgramGetParameterCount(program)!=2||sceGxmProgramGetParameter(program,1)!=p)goto done;
 status=3;
 if(sceGxmProgramParameterGetCategory(p)!=SCE_GXM_PARAMETER_CATEGORY_UNIFORM||
    sceGxmProgramParameterGetType(p)!=SCE_GXM_PARAMETER_TYPE_F32||
    sceGxmProgramParameterGetComponentCount(p)!=4||sceGxmProgramParameterGetArraySize(p)!=1||
    sceGxmProgramParameterGetContainerIndex(p)!=14||sceGxmProgramParameterGetResourceIndex(p)!=0||
    sceGxmProgramParameterGetIndex(program,p)!=1||sceGxmProgramParameterGetName(p)[0]!='g')goto done;
 status=4;
 const SceGxmProgramParameter *position=sceGxmProgramFindParameterBySemantic(program,SCE_GXM_PARAMETER_SEMANTIC_POSITION,0);
 if(!position||position!=sceGxmProgramGetParameter(program,0))goto done;
 status=5;
 if(sceGxmSetUniformDataF(uniform,p,1,2,values)||uniform[0]!=-1||uniform[1]!=values[0]||
    uniform[2]!=values[1]||uniform[3]!=-1)goto done;
 status=0;sceIoWrite(1,pass,sizeof(pass)-1);
done:sceKernelExitProcess(status);return 99;
}
