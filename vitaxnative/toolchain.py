"""Host toolchain diagnostics and a native macOS packaging smoke test.

No Vita executable is translated or executed by this module.
"""
import json
import platform
import shutil
import subprocess
import tempfile
from pathlib import Path
from .packaging import package_native

SOURCE = r'''#include <stdio.h>
int main(void) { puts("vitaxnative native ARM64 toolchain smoke test"); return 0; }
'''


def diagnose() -> dict:
    system = platform.system()
    machine = platform.machine()
    clang = shutil.which('clang')
    result = {'host_os': system, 'host_arch': machine, 'clang': clang,
              'native_arm64_build_supported': system == 'Darwin' and machine == 'arm64' and bool(clang),
              'vita_recompiler': False, 'vita_runtime': False, 'metal_backend': False,
              'fps_patches': False, 'resolution_patches': False,
              'bounded_homebrew_recompiler': True, 'native_conversion_cli': True,
              'runtime_services': ['io_open', 'io_read', 'io_write', 'io_close',
                                   'io_lseek32', 'io_sync_by_fd', 'monotonic_time', 'delay'],
              'host_metal_offscreen_source': True,
              'gxm_gxp_translation': False, 'vitasdk_module_linking': False}
    if clang:
        try:
            p = subprocess.run([clang, '--version'], capture_output=True, text=True, timeout=10, check=False)
            result['clang_version'] = (p.stdout or p.stderr).splitlines()[0][:200]
        except (OSError, subprocess.TimeoutExpired, IndexError):
            result['clang_version'] = 'unavailable'
    return result


def smoke_test(output_dir: Path) -> dict:
    """Compile a tiny C program and package it, exercising the real macOS toolchain."""
    info = diagnose()
    if not info['native_arm64_build_supported']:
        raise RuntimeError('native smoke test requires an Apple Silicon Mac with clang installed')
    output_dir = Path(output_dir)
    with tempfile.TemporaryDirectory(prefix='vitaxnative-smoke-') as tmp:
        src = Path(tmp) / 'smoke.c'
        binary = Path(tmp) / 'smoke'
        src.write_text(SOURCE)
        result = subprocess.run([info['clang'], '-arch', 'arm64', '-O2', str(src), '-o', str(binary)],
                                capture_output=True, text=True, timeout=120, check=False)
        if result.returncode:
            raise RuntimeError('clang compilation failed: ' + result.stderr[-2000:])
        run = subprocess.run([str(binary)], capture_output=True, text=True, timeout=15, check=False)
        if run.returncode or run.stdout.strip() != 'vitaxnative native ARM64 toolchain smoke test':
            raise RuntimeError('compiled ARM64 smoke executable failed to run')
        app = package_native(binary, output_dir, 'vitaxnative Smoke Test', 'org.vitaxnative.smoketest')
    return {'app': str(app), 'compiled_and_executed_on_mac': True,
            'vita_recompiled': False, 'note': 'Host compiler/package test only; not Vita conversion.'}
