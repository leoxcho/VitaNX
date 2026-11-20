"""Precise diagnostics for rejected CPU operations, without fabricated handlers."""
import tempfile,unittest
from pathlib import Path
from vitanx.dynamic import NativeSession
import test_recompiler as support
class CpuFaultTests(unittest.TestCase):
    def test_unsupported_instruction_retains_pc_opcode_and_reason(self):
        with tempfile.TemporaryDirectory() as tmp:
            d=Path(tmp);elf=d/'x.elf';elf.write_bytes(support.elf([0xe7f000f0,0xe12fff1e]))
            s=NativeSession(elf,d/'run',decode_traps=True)
            self.assertIn(0x100,s.initial['decode_errors'])
            report=s.run();self.assertEqual(report['status'],-8)
            self.assertEqual(report['pc'],0x100)
            self.assertEqual(report['fault_context']['opcode'],0xe7f000f0)
            self.assertEqual(report['fault_context']['stage'],'cpu')
            self.assertIn('reason',report['fault_context'])
    def test_invalid_guest_load_retains_destination_and_faulting_pc(self):
        with tempfile.TemporaryDirectory() as tmp:
            d=Path(tmp);elf=d/'x.elf';elf.write_bytes(support.elf([0xe5910000,0xe12fff1e]))
            s=NativeSession(elf,d/'run');s.state.r[1]=0xffffffff;s.state.r[0]=123
            report=s.run();self.assertEqual(report['status'],-2)
            self.assertEqual(report['r'][0],123);self.assertEqual(report['pc'],0x100)
            self.assertEqual(report['fault_context']['kind'],'memory access or executable write rejected')
