"""Safe frontend for the existing multi-module native execution engine."""
from pathlib import Path
import platform
import sys
import subprocess
from vitaxnative.elf_segments import inspect_elf_segments

ROOT = Path(__file__).resolve().parents[1]

def game_command(main, output, *, modules=(), assets=None, cache=None, limit=1000000, regions=4096, heap=256, media=True):
    main, output = Path(main).resolve(), Path(output).resolve()
    modules = [Path(p).resolve() for p in modules]
    if output.exists():
        raise ValueError('output must be a new directory')
    if len(set([main,*modules])) != 1+len(modules):
        raise ValueError('duplicate executable/module')
    if min(limit,regions,heap)<1:
        raise ValueError('execution budgets must be positive')
    for path in [main,*modules]:
        inspect_elf_segments(path)
    if assets is not None:
        assets=Path(assets).resolve()
        if not assets.is_dir(): raise ValueError('asset directory missing')
        if output.is_relative_to(assets): raise ValueError('output cannot be inside original assets')
    if cache is not None:
        cache=Path(cache).resolve()
        if not cache.is_dir(): raise ValueError('native cache directory missing')
        if output.is_relative_to(cache): raise ValueError('output cannot be inside native cache')
    command=[sys.executable,str(ROOT/'scripts/run_vita_modules.py'),str(main),str(output),
             '--heap-mib',str(heap),'--instruction-limit',str(limit),'--max-regions',str(regions),'--diagnostic-unresolved']
    for path in modules: command.extend(['--module',str(path)])
    if assets is not None: command.extend(['--assets',str(assets)])
    if cache is not None: command.extend(['--native-cache',str(cache)])
    if media: command.append('--media')
    return command

def run_game(command):
    if platform.system()!='Darwin' or platform.machine()!='arm64':
        raise RuntimeError('Apple Silicon macOS required for native game execution')
    return subprocess.run(command,check=False).returncode
