"""Rebuild original genuine VitaSDK fixtures without replacing existing outputs."""
import argparse
import os
from pathlib import Path
import subprocess

ROOT=Path(__file__).resolve().parents[2]
KINDS=('gameplay_stability','gameplay_runtime','indirect','main','display','graphics','runtime','audio','interactive','interactive_demo',
       'cpu_core','gxm_transfer','gxm_uniforms','gxm_scene','gxm_bindings','gxm_cube','gxm_texture','gxm_disabled_depth','gxm_depth','gxm_depth_load','gxm_stencil','vfp_scalar','vfp_registers','vfp_math','neon_integer','neon_widths')

def build(output,kind='main',thumb=False):
    output=Path(output)
    output.mkdir(parents=True,exist_ok=False)
    sdk=Path(os.environ.get('VITASDK',ROOT.parent/'vitasdk'))
    elf=output/'homebrew.elf';velf=output/'homebrew.velf';self_path=output/'eboot.bin'
    command=[str(sdk/'bin/arm-vita-eabi-gcc'),'-mthumb' if thumb else '-marm','-O1','-nostdlib',
             '-fno-unwind-tables','-fno-asynchronous-unwind-tables','-Wl,-q',
             '-Wl,-e,module_start','-Wl,-Ttext=0x81000000']
    if kind=='gxm_stencil':command+=['-fno-jump-tables']
    if kind!='main':command+=['-fno-omit-frame-pointer']
    if kind not in KINDS:
        raise ValueError('unknown VitaSDK fixture')
    source=output/'source.c'
    source.write_bytes((b'#define VX_GXM_BINDINGS_ONLY 1\n' if kind=='gxm_bindings' else b'#define VX_RUNTIME_FRAMES 7200\n#define VX_RUNTIME_DELAY 16667\n' if kind=='gameplay_stability' else b'')+(ROOT/f'fixtures/vitasdk/{"gxm_scene" if kind=="gxm_bindings" else "gameplay_runtime" if kind=="gameplay_stability" else kind}.c').read_bytes())
    command += [str(source),'-lSceIofilemgr_stub',
                '-lSceLibKernel_stub','-lSceProcessmgr_stub','-lSceDisplay_stub',
                '-lSceCtrl_stub','-lSceSysmem_stub','-lSceKernelThreadMgr_stub',
                '-lSceAudio_stub','-lSceGxm_stub','-o',str(elf)]
    commands=[command,[str(sdk/'bin/vita-elf-create'),str(elf),str(velf)],
              [str(sdk/'bin/vita-make-fself'),str(velf),str(self_path)]]
    import json
    (output/'commands.json').write_text(json.dumps(commands,indent=2))
    for command in commands:subprocess.run(command,check=True,capture_output=True,timeout=60)
    return velf

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output',type=Path)
    parser.add_argument('--kind',choices=KINDS,default='main')
    parser.add_argument('--thumb',action='store_true')
    args=parser.parse_args();print(build(args.output,args.kind,args.thumb))
