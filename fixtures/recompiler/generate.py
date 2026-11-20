"""Generate the original, hand-encoded ARM homebrew ABI fixture (no game code)."""
import json
import struct
from pathlib import Path

HERE = Path(__file__).resolve().parent
message = b'vitaxnative ARM homebrew: hello native macOS!\n'
# ARMv7 A32: preserve incoming LR in r4; call explicit sceIoWrite import.
words = [0xe1a0400e, 0xe3a00001, 0xe3a01d06, 0xe3a02000 | len(message)]
bl_pc = 0x100 + len(words) * 4
words += [0xeb000000 | (((0x2000 - bl_pc - 8) >> 2) & 0xffffff),
          0xe1a0e004, 0xe12fff1e]
payload = bytearray(0x80 + len(message))
payload[:len(words)*4] = struct.pack('<'+'I'*len(words), *words)
payload[0x80:] = message
header = bytearray(0x100)
header[:16] = b'\x7fELF\x01\x01\x01' + bytes(9)
struct.pack_into('<HHIIIIIHHHHHH', header, 16, 2, 40, 1, 0x100, 52, 0, 0x05000000, 52, 32, 1, 0, 0, 0)
struct.pack_into('<IIIIIIII', header, 52, 1, 0x100, 0x100, 0x100, len(payload), len(payload), 5, 0x100)
(HERE / 'hello.elf').write_bytes(header + payload)
(HERE / 'hello.json').write_text(json.dumps({'entry': 256, 'imports': {'8192': 0x34efd876}, 'expected_stdout': message.decode(), 'expected_r0': len(message), 'provenance': 'Original synthetic ARMv7 homebrew ABI test. Fixed-address ELF32, not VitaSDK VELF or retail game.'}, indent=2)+'\n')
