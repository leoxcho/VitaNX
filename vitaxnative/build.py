# Modified for vitanx 2026-11-09: independent save namespace and default bundle ID.
"""Atomic bounded homebrew compilation and standalone ARM64 app orchestration."""
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import tempfile
from .recompiler import translate_elf
from .packaging import package_native

ROOT = Path(__file__).resolve().parent.parent

class NativeVerificationError(RuntimeError):
    """Failed execution retaining structured evidence for diagnostic callers."""
    def __init__(self, message, evidence):
        super().__init__(message)
        self.evidence = evidence


def verify_native(binary, *, env=None, mode='exit', timeout=10):
    """Observe a bounded probe; always reap it, never infer playability."""
    import math
    import time
    if mode not in ('exit', 'startup') or isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or not 0 < timeout <= 15:
        raise ValueError('invalid native verification mode or timeout')
    started = time.monotonic()
    evidence = {'executed': True, 'mode': mode, 'timeout_seconds': timeout,
                'native_exit_verified': False, 'playable_verified': False,
                'method': 'bounded direct execution of final signed bundled ARM64 Mach-O'}
    def decoded(value):
        return value.decode(errors='replace') if isinstance(value, bytes) else value or ''
    try:
        run = subprocess.run([str(binary)], capture_output=True, text=True,
                             errors='replace', timeout=timeout, env=env, check=False)
    except subprocess.TimeoutExpired as error:
        # subprocess.run kills and reaps the timed-out child before raising.
        evidence.update(returncode=None, stdout=decoded(error.stdout), stderr=decoded(error.stderr),
                        elapsed_seconds=time.monotonic()-started, probe_terminated=True,
                        observation='running_at_deadline_then_terminated' if mode == 'startup' else 'timed_out')
        if mode == 'exit':
            raise NativeVerificationError(f'native verification exceeded {timeout}s timeout', evidence) from error
        return evidence
    evidence.update(returncode=run.returncode, stdout=run.stdout, stderr=run.stderr,
                    elapsed_seconds=time.monotonic()-started, probe_terminated=False,
                    observation='crashed' if run.returncode < 0 else 'exited_with_error' if run.returncode else 'exited_successfully',
                    signal=-run.returncode if run.returncode < 0 else None,
                    native_exit_verified=run.returncode == 0)
    if run.returncode:
        raise NativeVerificationError(f'native verification failed ({evidence['observation']}, {run.returncode}): {(run.stderr or run.stdout)[-3000:]}', evidence)
    return evidence

def _run(argv, timeout=120, **kwargs):
    try:
        p = subprocess.run([str(a) for a in argv], capture_output=True, text=True,
                           timeout=timeout, check=False, **kwargs)
    except subprocess.TimeoutExpired as error:
        raise RuntimeError(f'{Path(str(argv[0])).name} exceeded {timeout}s timeout') from error
    if p.returncode:
        raise RuntimeError(f'{Path(str(argv[0])).name} failed ({p.returncode}): {(p.stderr or p.stdout)[-3000:]}')
    return p


def build_native(source, output, *, imports=None, entry=None, name='Vita Homebrew',
                 bundle_id='org.vitanx.homebrew', verify=False, expected_r0=0, assets=None,
                 display=None, heap_size=4*1024*1024, audio=False, gxm=False, verification='exit'):
    """Compile supported ELF only. Execution requires explicit verify=True.

    Failed builds leave no published output; unknown errors are never bypassed.
    Outputs include source, manifest and diagnostics for reproducibility.
    """
    if platform.system() != 'Darwin' or platform.machine() != 'arm64':
        raise RuntimeError('native build requires Apple Silicon macOS')
    clang = shutil.which('clang')
    if not clang:
        raise RuntimeError('clang unavailable; install Apple command line tools')
    source, output = Path(source), Path(output)
    if output.exists() or output.is_symlink():
        raise FileExistsError(output)
    if type(expected_r0) is not int or not 0 <= expected_r0 <= 0xffffffff:
        raise ValueError('expected_r0 must be uint32')
    if type(heap_size) is not int or not 4096 <= heap_size <= 128*1024*1024 or heap_size % 4096:
        raise ValueError('heap_size must be page-aligned, between 4KiB and 128MiB')
    if type(audio) is not bool:
        raise ValueError('audio must be boolean')
    if type(gxm) is not bool:
        raise ValueError('gxm must be boolean')
    if verification not in ('exit','startup'):
        raise ValueError('invalid native verification mode')
    if display is not None:
        if not isinstance(display, dict) or set(display) - {'render_hz','simulation_hz','width','height','window','fullscreen','vsync','filter'}:
            raise ValueError('invalid display configuration')
        display = {'render_hz':60,'simulation_hz':60,'width':0,'height':0,**display}
        if any(type(display[k]) is not int for k in ('render_hz','simulation_hz','width','height')) or display['render_hz'] not in (30,60,120) or not 1 <= display['simulation_hz'] <= 1000 or not 0 <= display['width'] <= 4096 or not 0 <= display['height'] <= 4096 or bool(display['width']) != bool(display['height']):
            raise ValueError('invalid display configuration')
        if any(type(display.get(k,False)) is not bool for k in ('window','fullscreen','vsync')) or display.get('filter','nearest') not in ('nearest','linear'):
            raise ValueError('invalid display configuration')
    translated = None
    output.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix='.vx-build-', dir=output.parent))
    try:
        executable_source = source
        if source.read_bytes()[:4] == b'SCE\0':
            from .self_extract import extract_self
            executable_source = stage/'extracted.elf'
            extract_self(source, executable_source)
        translated = translate_elf(executable_source, imports=imports, entry=entry)
        translated['container_sha256'] = hashlib.sha256(source.read_bytes()).hexdigest()
        (stage/'guest.c').write_text(translated['c_source'])
        image = translated.pop('memory_image')
        backing_size = ((len(image)+4095)&~4095)+heap_size+65536
        if translated['memory_base']+backing_size > 0xffffffff:
            raise ValueError('guest backing and heap exceed uint32 address space')
        translated.pop('c_source')
        # Guest bytes are compiled into the app; no external ROM path needed.
        (stage/'image.h').write_text('static const unsigned char image[] = {' +
                                  ','.join(str(b) for b in image) + '};\n')
        runner = r'''
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <limits.h>
#include <mach-o/dyld.h>
#include "vita_runtime.h"
#include "image.h"
extern int vx_guest(uint32_t*,uint8_t*,size_t);
int main(void){
 DISPLAY_INIT
 ASSET_MOUNT
 char path[PATH_MAX];const char*save=getenv("VX_SAVE_ROOT");
 if(!save){const char*home=getenv("HOME");if(!home)return 120;
  if(snprintf(path,sizeof(path),"%s/Library/Application Support/vitanx",home)>=(int)sizeof(path))return 120;
  if(mkdir(path,0700)&&errno!=EEXIST)return 120;
  size_t n=strlen(path);if(snprintf(path+n,sizeof(path)-n,"/INPUT_HASH")>=(int)(sizeof(path)-n))return 120;
  if(mkdir(path,0700)&&errno!=EEXIST)return 120;save=path;
 }
 if(vx_runtime_mount(save)){fputs("save mount failed\n",stderr);return 121;}
 size_t heap_offset=(sizeof(image)+4095u)&~(size_t)4095u;
 size_t size=heap_offset+HEAP_SIZEu+65536;uint8_t*mem=calloc(1,size);if(!mem)return 122;
 memcpy(mem,image,sizeof(image));vx_runtime_set_memory_base(MEMORY_BASEu);
 if(vx_runtime_set_heap(MEMORY_BASEu+(uint32_t)heap_offset,HEAP_SIZEu)){free(mem);return 127;}
 uint32_t r[16]={0};r[13]=(MEMORY_BASEu+(uint32_t)size)&~7u;r[14]=UINT32_MAX;
 int status=vx_guest(r,mem,size);uint32_t exit_status=0;int reason=vx_runtime_stop_requested(&exit_status);
 vx_kernel_stats ks;vx_runtime_kernel_stats(&ks);fprintf(stderr,"vitaxnative: kernel threads %llu switches %llu waits %llu callbacks %llu instructions %llu\n",(unsigned long long)ks.threads_created,(unsigned long long)ks.context_switches,(unsigned long long)ks.waits,(unsigned long long)ks.callbacks,(unsigned long long)ks.instructions);
 fprintf(stderr,"vitaxnative: termination reason %d status %u\n",reason,exit_status);DISPLAY_STATS vx_runtime_shutdown();free(mem);
 if(status){fprintf(stderr,"guest fault %d\n",status);return 123;}
 fprintf(stderr,"vitaxnative: guest returned %u\n",r[0]);return r[0]!=EXPECTED_R0u?124:0;
}
'''.replace('INPUT_HASH', translated['input_sha256']).replace('EXPECTED_R0', str(expected_r0)).replace('MEMORY_BASE', str(translated['memory_base'])).replace('HEAP_SIZE',str(heap_size))
        asset_mount = r'''
 char app_path[PATH_MAX];uint32_t capacity=sizeof(app_path);
 if(_NSGetExecutablePath(app_path,&capacity))return 125;
 char *slash=strrchr(app_path,'/');if(!slash)return 125;*slash=0;
 size_t used=strlen(app_path);
 if(snprintf(app_path+used,sizeof(app_path)-used,"/../Resources/app0")>=(int)(sizeof(app_path)-used))return 125;
 if(vx_runtime_mount_app(app_path))return 125;
''' if assets is not None else ''
        runner = runner.replace('ASSET_MOUNT', asset_mount)
        display_init = display_stats = ''
        if display is not None:
            runner = '#include "vita_display.h"\n' + runner
            display_init = 'if(vx_display_configure(%du,%du,%du,%du))return 126;' % tuple(display[k] for k in ('render_hz','simulation_hz','width','height'))
            display_init += 'if(vx_display_set_filter(%d))return 126;' % (display.get('filter','nearest')=='linear')
            if display.get('window'):
                display_init += 'if(vx_display_configure_window(%s,%d,%d,%d))return 126;' % (json.dumps(name),display.get('fullscreen',False),display.get('vsync',True),display.get('filter','nearest')=='linear')
            display_stats = 'vx_display_stats ds;vx_display_get_stats(&ds);fprintf(stderr,"vitaxnative: display submitted %llu presented %llu waits %llu simulation ticks %llu metal %d\\n",(unsigned long long)ds.frames_submitted,(unsigned long long)ds.frames_presented,(unsigned long long)ds.wait_calls,(unsigned long long)ds.simulation_ticks,ds.metal_status);'
            if display.get('window'):
                display_stats += 'vx_window_stats ws;vx_display_window_stats(&ws);fprintf(stderr,"vitaxnative: window presented %llu events %llu keys %llu fullscreen %d closed %d controller %d\\n",(unsigned long long)ws.frames_presented,(unsigned long long)ws.events_processed,(unsigned long long)ws.key_events,ws.fullscreen,ws.closed,ws.controller_connected);'
        runner = runner.replace('DISPLAY_INIT',display_init).replace('DISPLAY_STATS',display_stats)
        if gxm:
            from .gxm_catalog import write_catalog
            catalog_report=write_catalog(assets,stage/'gxm_catalog.h')
            (stage/'gxm-catalog.json').write_text(json.dumps(catalog_report,indent=2)+'\n')
            runner='#include "vita_gxm.h"\n#include "gxm_catalog.h"\n'+runner
            runner=runner.replace('memcpy(mem,image,sizeof(image));','if(vx_install_gxm_catalog())return 126;memcpy(mem,image,sizeof(image));')
            runner=runner.replace('vx_runtime_shutdown();free(mem);',
                'vx_gxm_stats gs;vx_gxm_get_stats(&gs);fprintf(stderr,"vitaxnative: GXM fills %llu copies %llu bytes %llu draws %llu scenes %llu metal_status %d\\n",(unsigned long long)gs.fills,(unsigned long long)gs.copies,(unsigned long long)gs.bytes,(unsigned long long)gs.draws,(unsigned long long)gs.scenes,gs.metal_status);vx_runtime_shutdown();free(mem);')
        (stage/'main.c').write_text('#include <errno.h>\n' + runner)
        for file in ('vita_runtime.c','vita_runtime.h','vita_guest.h','vita_kernel.inc','vita_memblock_diag.h'):
            shutil.copyfile(ROOT/'runtime'/file,stage/file)
        command = [clang, '-arch','arm64','-std=c11','-O2','-Wall','-Wextra',
                   str(stage/'guest.c'),str(stage/'main.c'),str(stage/'vita_runtime.c'),
                   '-o',str(stage/'native')]
        runtime_files = ['vita_runtime.c','vita_runtime.h','vita_guest.h','vita_kernel.inc','vita_memblock_diag.h']
        if display is not None:
            runtime_files += ['vita_display.m','vita_display.h','vita_metal.m','vita_metal.h','vita_frame.c','vita_frame.h']
            for file in runtime_files[5:]:
                shutil.copyfile(ROOT/'runtime'/file,stage/file)
            command += ['-DVX_ENABLE_DISPLAY','-fobjc-arc',str(stage/'vita_display.m'),
                        str(stage/'vita_metal.m'),str(stage/'vita_frame.c'),
                        '-framework','Foundation','-framework','Metal']
            if display.get('window'):
                for file in ('vita_window.h','vita_window.m'):
                    shutil.copyfile(ROOT/'runtime'/file,stage/file)
                    runtime_files.append(file)
                command += ['-DVX_ENABLE_WINDOW',str(stage/'vita_window.m'),
                            '-framework','Cocoa','-framework','QuartzCore','-framework','GameController']
        if audio:
            runner=runner.replace('vx_runtime_shutdown();free(mem);', 'vx_audio_stats ast;vx_audio_get_stats(&ast);fprintf(stderr,"vitaxnative: audio queued %llu completed %llu frames %llu timeouts %llu\\n",(unsigned long long)ast.buffers_queued,(unsigned long long)ast.buffers_completed,(unsigned long long)ast.frames_completed,(unsigned long long)ast.timeouts);vx_runtime_shutdown();free(mem);')
            runner='#include "vita_audio.h"\n'+runner
            (stage/'main.c').write_text('#include <errno.h>\n'+runner)
            for file in ('vita_audio.c','vita_audio.h'):
                shutil.copyfile(ROOT/'runtime'/file,stage/file)
                runtime_files.append(file)
            command += ['-DVX_ENABLE_AUDIO',str(stage/'vita_audio.c'),'-framework','AudioToolbox']
        if gxm:
            for file in ('vita_gxm.c','vita_gxm.h'):
                shutil.copyfile(ROOT/'runtime'/file,stage/file)
                runtime_files.append(file)
            command+=['-DVX_ENABLE_GXM',str(stage/'vita_gxm.c')]
            if display is None:
                for file in ('vita_metal.m','vita_metal.h'):
                    shutil.copyfile(ROOT/'runtime'/file,stage/file)
                    runtime_files.append(file)
                command+=['-fobjc-arc',str(stage/'vita_metal.m'),'-framework','Foundation','-framework','Metal']
        compiled = _run(command)
        (stage/'compile.log').write_text(compiled.stderr)
        app = package_native(stage/'native', stage, name, bundle_id)
        asset_manifest = []
        if assets is not None:
            asset_root = Path(assets)
            if not asset_root.is_dir() or asset_root.is_symlink():
                raise ValueError('assets must be a real directory')
            destination = app/'Contents/Resources/app0'
            destination.mkdir()
            total = 0
            for item in sorted(asset_root.rglob('*')):
                relative = item.relative_to(asset_root)
                if item.is_symlink():
                    raise ValueError('asset symlinks unsupported')
                target = destination/relative
                if item.is_dir():
                    target.mkdir(exist_ok=True)
                elif item.is_file():
                    total += item.stat().st_size
                    if total > 256*1024*1024:
                        raise ValueError('asset fixture exceeds 256MiB limit')
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(item, target)
                    asset_manifest.append({'path':relative.as_posix(),
                        'sha256':hashlib.sha256(target.read_bytes()).hexdigest()})
                else:
                    raise ValueError('unsupported asset file type')
        manifest = {**translated, 'source':str(source.resolve()),
                    'app':name+'.app','vita_recompiled':True,
                    'commercial_compatibility':False,
                    'expected_r0':expected_r0, 'fps_validated':False,'resolution_validated':False,
                    'assets':asset_manifest,
                    'display':display,
                    'heap_size':heap_size,'audio':audio,'gxm':gxm,
                    **({'gxm_shader_catalog':catalog_report,
                        'gxm_catalog_sha256':hashlib.sha256((stage/'gxm_catalog.h').read_bytes()).hexdigest()} if gxm else {}),
                    'generated_c_sha256':hashlib.sha256((stage/'guest.c').read_bytes()).hexdigest(),
                    'runtime_sources':{file:hashlib.sha256((stage/file).read_bytes()).hexdigest()
                                       for file in runtime_files},
                    'compiler_output_sha256':hashlib.sha256((stage/'native').read_bytes()).hexdigest()}
        # Bundle records conversion provenance. Execution evidence is written to
        # external build.json after final signing, so verification runs exact bytes.
        (app/'Contents'/'Resources'/'conversion.json').write_text(json.dumps(manifest,indent=2))
        _run(['/usr/bin/codesign','--force','--sign','-',str(app)])
        _run(['/usr/bin/codesign','--verify','--strict',str(app)])
        evidence = {'executed':False}
        if verify:
            (stage/'saves').mkdir()
            evidence = verify_native(app/'Contents/MacOS/Game',mode=verification,
                       env={**os.environ,'VX_SAVE_ROOT':str(stage/'saves')})
        manifest['execution'] = evidence
        manifest['binary_sha256'] = hashlib.sha256((app/'Contents/MacOS/Game').read_bytes()).hexdigest()
        (stage/'build.json').write_text(json.dumps(manifest,indent=2))
        if output.exists() or output.is_symlink():
            raise FileExistsError(output)
        os.rename(stage,output)
        return {**manifest,'output':str(output),'app':str(output/(name+'.app'))}
    finally:
        if stage.exists(): shutil.rmtree(stage)
