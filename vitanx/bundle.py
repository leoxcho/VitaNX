"""Build a local ARM64 app from explicit plaintext Vita inputs."""
import argparse
import json
import os
from pathlib import Path
import plistlib
import re
import shutil
import subprocess
import struct
import tempfile

from .installed_games import TITLE_ID, read_param_sfo
from vitaxnative.elf_segments import inspect_elf_segments
from vitaxnative.packaging import require_arm64_macho
from vitaxnative.self_extract import EncryptedSelfError, extract_self

ROOT = Path(__file__).resolve().parents[1]
SIGN = ('/usr/bin/codesign', '--force', '--sign', '-')
LAUNCHER = r'''
#include <mach-o/dyld.h>
#include <dlfcn.h>
#include <libgen.h>
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>

int main(void) {
    char self[PATH_MAX], resolved[PATH_MAX], resources[PATH_MAX], python[PATH_MAX], library[PATH_MAX];
    uint32_t length = sizeof self;
    if (_NSGetExecutablePath(self, &length) || !realpath(self, resolved)) return 1;
    if (snprintf(resources, sizeof resources, "%s/../Resources", dirname(resolved))
        >= sizeof resources) return 1;
    if (snprintf(python, sizeof python, "%s/Python/bin/python3", resources)
        >= sizeof python || chdir(resources)) return 1;
    unsetenv("__PYVENV_LAUNCHER__");
    if (setenv("PYTHONPATH", resources, 1)) return 1;
    // The relocated runtime lives under Resources/Python.
    char home[PATH_MAX];
    if (snprintf(home, sizeof home, "%s/Python", resources) >= sizeof home ||
        setenv("PYTHONHOME", home, 1)) return 1;
    if (snprintf(library, sizeof library, "%s/Python", home) >= sizeof library) return 1;
    void *runtime = dlopen(library, RTLD_NOW | RTLD_GLOBAL);
    if (!runtime) return 1;
    int (*python_main)(int, char **) = (int (*)(int, char **))dlsym(runtime, "Py_BytesMain");
    if (!python_main) return 1;
    char *args[] = {python, "-B", "-s", "-P", "-m", "vitanx.bundle_entry", NULL};
    return python_main(6, args);
}
'''


def run(*args):
    completed = subprocess.run([str(arg) for arg in args], capture_output=True, text=True)
    if completed.returncode:
        raise RuntimeError(completed.stderr.strip() or completed.stdout.strip())
    return completed.stdout.strip()


def copy_arm64(source, dest):
    if run('/usr/bin/lipo', '-archs', source) == 'arm64':
        shutil.copy2(source, dest)
    else:
        run('/usr/bin/lipo', source, '-thin', 'arm64', '-output', dest)
        dest.chmod(source.stat().st_mode & 0o777)


def copy_python(source, dest):
    if not re.fullmatch(r'3\.\d+', source.name):
        raise ValueError('use a versioned Python.org framework directory')
    (dest/'bin').mkdir(parents=True)
    (dest/'lib').mkdir()
    binary = dest/'bin/python3'
    copy_arm64(source/'Resources/Python.app/Contents/MacOS/Python', binary)
    copy_arm64(source/'Python', dest/'Python')
    library = dest/'lib'/f'python{source.name}'
    shutil.copytree(source/'lib'/library.name, library,
                    ignore=shutil.ignore_patterns('__pycache__', 'site-packages', 'test',
                                                 'tests', 'idlelib', 'tkinter', '_tkinter.*', 'config-*'))
    for path in (source/'lib').glob('*.dylib'):
        if path.is_file() and not path.is_symlink():
            copy_arm64(path, dest/'lib'/path.name)
    for path in (source/'lib').glob('*.dylib'):
        if path.is_symlink() and (dest/'lib'/path.resolve().name).is_file():
            (dest/'lib'/path.name).symlink_to(path.resolve().name)
    code = [binary, dest/'Python', *(p for p in (dest/'lib').glob('*.dylib') if not p.is_symlink()),
            *(library/'lib-dynload').glob('*.so')]
    for path in code:
        if path.suffix == '.so':
            thin = path.with_suffix('.arm64')
            copy_arm64(path, thin)
            thin.replace(path)
        changes = []
        for line in run('/usr/bin/otool', '-L', path).splitlines()[1:]:
            dep = line.strip().split(' (compatibility version ', 1)[0]
            if dep.startswith(('/usr/lib/', '/System/Library/')):
                continue
            dependency = dest/'Python' if Path(dep).name == 'Python' else dest/'lib'/Path(dep).name
            if not dependency.is_file():
                raise ValueError(f'Unbundled Python dependency {dep}')
            if path == dependency:
                changes.extend(('-id', '@loader_path/'+path.name))
            else:
                changes.extend(('-change', dep, '@loader_path/'+os.path.relpath(dependency, path.parent)))
        if changes:
            run('/usr/bin/install_name_tool', *changes, path)
        run(*SIGN, path)


def copy_ffmpeg(dest, source=None):
    """Bundle the native codec libraries and their relocatable dependency closure."""
    from .graphics import ffmpeg_root

    source = Path(source).resolve() if source is not None else ffmpeg_root()
    if source is None:
        raise RuntimeError('FFmpeg development libraries are required to package audio codecs')
    libdir = dest/'lib'
    libdir.mkdir(parents=True)
    for name in ('libavcodec', 'libavutil'):
        shutil.copytree(source/'include'/name, dest/'include'/name)
    copied = {}

    def copy_library(path):
        library = path.resolve(strict=True)
        output = libdir/library.name
        if output.name in copied:
            if copied[output.name] != library:
                raise RuntimeError(f'Conflicting FFmpeg dependencies named {output.name}')
            return output
        copied[output.name] = library
        copy_arm64(library, output)
        dependencies = run('/usr/bin/otool', '-L', output).splitlines()[2:]
        changes = ['-id', '@rpath/'+output.name]
        for line in dependencies:
            name = line.strip().split(' (compatibility version ', 1)[0]
            if name.startswith(('/usr/lib/', '/System/Library/')):
                continue
            dependency = Path(name)
            if name.startswith('@loader_path/'):
                dependency = library.parent/name.removeprefix('@loader_path/')
            elif name.startswith('@rpath/'):
                dependency = library.parent/name.removeprefix('@rpath/')
            elif not dependency.is_absolute():
                raise RuntimeError(f'Cannot relocate FFmpeg dependency {name}')
            embedded = copy_library(dependency)
            changes.extend(('-change', name, '@loader_path/'+embedded.name))
        run('/usr/bin/install_name_tool', *changes, output)
        run(*SIGN, output)
        return output

    for name in ('libavcodec.dylib', 'libavutil.dylib'):
        output = copy_library(source/'lib'/name)
        if name != output.name:
            (libdir/name).symlink_to(output.name)


def copy_toolchain(dest):
    clang = Path(run('/usr/bin/xcrun', '--find', 'clang'))
    linker = Path(run('/usr/bin/xcrun', '--find', 'ld'))
    tc = clang.parent.parent
    resource = Path(run(clang, '--print-resource-dir'))
    (dest/'bin').mkdir(parents=True)
    (dest/'lib/clang').mkdir(parents=True)
    for source, target in [(clang, dest/'bin/clang'), (linker, dest/'bin/ld'),
                           *((tc/'lib'/name, dest/'lib'/name) for name in
                             ('libtapi.dylib', 'libcodedirectory.dylib', 'libLTO.dylib',
                              'libswiftDemangle.dylib'))]:
        copy_arm64(source, target)
        run(*SIGN, target)
    shutil.copytree(resource, dest/'lib/clang'/resource.name, symlinks=True)
    shutil.copytree(run('/usr/bin/xcrun', '--show-sdk-path'), dest/'SDK', symlinks=True)


def sign_app(app, staging):
    source = staging/'entry.c'
    source.write_text(LAUNCHER)
    binary = app/'Contents/MacOS/Game'
    run('/usr/bin/xcrun', 'clang', '-arch', 'arm64', '-O2', source, '-o', binary)
    require_arm64_macho(binary)
    run(*SIGN, app)


def build(main, modules, assets, output, python, cache=None, *, patch=None):
    for executable in (main, *modules):
        inspect_elf_segments(executable)
    metadata = read_param_sfo(assets/'sce_sys/param.sfo')
    title_id, title = metadata.get('TITLE_ID'), metadata.get('TITLE')
    if not isinstance(title_id, str) or not TITLE_ID.fullmatch(title_id):
        raise ValueError('invalid TITLE_ID in game metadata')
    if not isinstance(title, str) or not title.strip():
        raise ValueError('missing game title')
    bundle_id = f'org.vitanx.game.{title_id.lower()}'
    output = output.resolve()
    if any(output.is_relative_to(path.resolve()) for path in (assets, patch) if path is not None):
        raise ValueError('output must be outside the original game and update directories')
    output.mkdir(parents=True, exist_ok=True)
    app_name = re.sub(r'[^\w .()-]', '', title).strip(' .')[:100] or title_id
    target = output/(app_name+'.app')
    if target.exists() or target.is_symlink():
        raise FileExistsError(target)
    with tempfile.TemporaryDirectory(prefix='.vitanx-', dir=output) as temp:
        app = Path(temp)/target.name
        contents = app/'Contents'
        resources = contents/'Resources'
        game = resources/'Game'
        game.mkdir(parents=True)
        (contents/'MacOS').mkdir()
        executables = ['main.elf', *(f'module-{i}.elf' for i in range(len(modules)))]
        for source, name in zip((main, *modules), executables, strict=True):
            shutil.copyfile(source, game/name)
        bundled_assets = game/'Assets'
        shutil.copytree(assets, bundled_assets, ignore=shutil.ignore_patterns('.DS_Store'))
        if patch is not None:
            shutil.copytree(patch, bundled_assets, dirs_exist_ok=True,
                            ignore=shutil.ignore_patterns('.DS_Store'))

        if cache:
            native_cache = resources/'NativeCache'
            native_cache.mkdir()
            for path in cache.iterdir():
                if path.is_file() and (path.suffix in ('.c', '.h', '.inc', '.m', '.dylib')
                                       or path.name == 'runtime-build.json'):
                    shutil.copyfile(path, native_cache/path.name)
        copy_python(python.resolve(), resources/'Python')
        copy_toolchain(resources/'Toolchain')
        copy_ffmpeg(resources/'FFmpeg')
        (resources/'game.json').write_text(json.dumps({'executables': executables, 'bundle_id': bundle_id}))
        image = Path(temp)/'icon.png'
        entries = []
        for size, kind in ((32, b'icp5'), (128, b'ic07'), (256, b'ic08'), (512, b'ic09')):
            run('/usr/bin/sips', '-s', 'format', 'png', '-z', size, size,
                bundled_assets/'sce_sys/icon0.png', '--out', image)
            data = image.read_bytes()
            if data[:8] != b'\x89PNG\r\n\x1a\n' or struct.unpack_from('>II', data, 16) != (size, size):
                raise ValueError(f'failed to create {size}-pixel application icon')
            entries.append(struct.pack('>4sI', kind, len(data)+8)+data)
        icons = b''.join(entries)
        (resources/'Game.icns').write_bytes(struct.pack('>4sI', b'icns', len(icons)+8)+icons)
        with (contents/'Info.plist').open('wb') as file:
            plistlib.dump({'CFBundleExecutable': 'Game', 'CFBundleName': title,
                           'CFBundleIdentifier': bundle_id, 'CFBundlePackageType': 'APPL',
                           'CFBundleShortVersionString': '0.1.0', 'CFBundleVersion': '1',
                           'CFBundleIconFile': 'Game.icns', 'LSMinimumSystemVersion': '26.0',
                           'LSArchitecturePriority': ['arm64'], 'NSHighResolutionCapable': True}, file)
        for package in ('vitanx', 'vitaxnative', 'runtime'):
            shutil.copytree(ROOT/package, resources/package, ignore=shutil.ignore_patterns('__pycache__'))
        sign_app(app, Path(temp))
        app.rename(target)
    return target



def _prepare_executable(source, target):
    with source.open('rb') as handle:
        magic = handle.read(4)
    if magic == b'SCE\0':
        extract_self(source, target)
        return target
    inspect_elf_segments(source)
    return source


def build_installed(game, output, *, include_extras=True, plaintext=None,
                    python=Path('/Library/Frameworks/Python.framework/Versions/Current')):
    """Stage the selected title's plaintext code and reuse the standalone builder."""
    assets = Path(game['game_path'])
    patch = Path(game['patch_path']) if include_extras and game['patch_path'] else None
    if game.get('base_metadata_error') or (patch is not None and game.get('patch_metadata_error')):
        raise ValueError('resolve the selected game or update metadata error before building')
    if include_extras and game['dlc_content_ids']:
        raise ValueError('DLC mounts are unavailable. Select Use base game only to build this title.')
    if plaintext is not None and not plaintext.is_dir():
        raise ValueError('plaintext input directory does not exist')
    executables = {Path('eboot.bin'): assets/'eboot.bin'}
    for root in (assets, patch):
        if root is None:
            continue
        main = root/'eboot.bin'
        if main.is_file():
            executables[Path('eboot.bin')] = main
        module_dir = root/'sce_module'
        if module_dir.is_symlink():
            raise ValueError('sce_module must be a regular directory')
        for module in sorted(module_dir.glob('*.suprx')):
            executables[Path('sce_module')/module.name] = module

    with tempfile.TemporaryDirectory(prefix='vitanx-plaintext-') as folder:
        staged = []
        for index, (name, source) in enumerate(executables.items()):
            if source.is_symlink() or not source.is_file():
                raise ValueError(f'missing or symlinked executable {name}')
            scratch = Path(folder)/f'input-{index}.elf'
            try:
                staged.append(_prepare_executable(source, scratch))
            except EncryptedSelfError:
                if plaintext is None:
                    raise
                candidates = (plaintext/name, (plaintext/name).with_suffix('.elf'),
                              plaintext/(name.stem+'.elf'))
                replacement = next((path for path in candidates
                                    if path.is_file() and not path.is_symlink()), None)
                if replacement is None:
                    raise ValueError(f'no plaintext replacement found for {name}') from None
                staged.append(_prepare_executable(replacement, scratch))
        return build(staged[0], staged[1:], assets, output, python, patch=patch)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('main', type=Path)
    parser.add_argument('assets', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--module', action='append', type=Path, default=[])
    parser.add_argument('--native-cache', type=Path)
    parser.add_argument('--python-framework', type=Path, required=True)
    args = parser.parse_args()
    print(build(args.main, args.module, args.assets, args.output,
                args.python_framework, args.native_cache))


if __name__ == '__main__':
    main()
