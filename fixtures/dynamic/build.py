"""Build original plaintext regression executable; remove mapping symbols only.

The stripped executable retains PT_LOADs and entry. Runtime-loaded function
pointer requires indirect resolution, as in stripped original binaries.
"""
from pathlib import Path
import struct
import subprocess

def build(output):
    output=Path(output)
    if output.exists(): raise FileExistsError(output)
    output.mkdir(parents=True)
    here=Path(__file__).resolve().parent
    subprocess.run(['clang','-target','armv7-none-eabi','-c',str(here/'interwork.S'),'-o',str(output/'input.o')],check=True,capture_output=True)
    subprocess.run(['ld.lld','-m','armelf','-T',str(here.parent/'homebrew/link.ld'),str(output/'input.o'),'-o',str(output/'linked.elf')],check=True,capture_output=True)
    data=bytearray((output/'linked.elf').read_bytes())
    struct.pack_into('<I',data,32,0)  # e_shoff
    struct.pack_into('<HHH',data,46,0,0,0)
    path=output/'interwork.elf';path.write_bytes(data)
    return path
