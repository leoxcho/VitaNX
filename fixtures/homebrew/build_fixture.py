"""Rebuild original C fixture without replacing the checked-in ELF."""
import argparse
from pathlib import Path
import subprocess
import tempfile

HERE = Path(__file__).resolve().parent

def build(output, source="main.c", thumb=False):
    output = Path(output)
    if output.exists() or output.is_symlink():
        raise FileExistsError(output)
    with tempfile.TemporaryDirectory() as tmp:
        obj = Path(tmp)/'main.o'
        subprocess.run(['clang','-target','armv7-none-eabi','-mthumb' if thumb else '-marm','-march=armv7-a',
                        '-O1','-ffreestanding','-fno-builtin','-fno-unwind-tables',
                        '-fno-asynchronous-unwind-tables','-c',str(HERE/source),'-o',str(obj)],check=True)
        elf = Path(tmp)/'main.elf'
        subprocess.run(['ld.lld','-m','armelf','-T',str(HERE/'link.ld'),str(obj),'-o',str(elf)],check=True)
        with output.open('xb') as handle:
            handle.write(elf.read_bytes())

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('output',type=Path)
    parser.add_argument('--source', choices=['main.c','save.c','assets.c','thumb.c'], default='main.c')
    parser.add_argument('--thumb', action='store_true')
    args = parser.parse_args()
    build(args.output, args.source, args.thumb)
