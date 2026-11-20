"""Only new live-translation and dispatch-yield behavior; no packaging tests."""
import ctypes as C
import importlib.util
from pathlib import Path
import struct
import json
import os
import tempfile
import unittest
from vitanx.dynamic import NativeSession
from vitaxnative.recompiler import translate_elf
import test_recompiler as support
ROOT=Path(__file__).resolve().parents[1]

class DynamicExecutionTests(unittest.TestCase):
    def test_arm_thumb_indirect_call_preserves_exclusive_flags_fp_stack(self):
        spec=importlib.util.spec_from_file_location('dynamic_fixture',ROOT/'fixtures/dynamic/build.py')
        builder=importlib.util.module_from_spec(spec);spec.loader.exec_module(builder)
        with tempfile.TemporaryDirectory() as d:
            d=Path(d);elf=builder.build(d/'input')
            session=NativeSession(elf,d/'native',imports={8192:0x34efd876})
            session.state.f[63]=0x7fc12345
            session.state.fpscr=0x08000010
            initial_sp=session.state.r[13]
            report=session.run()
            self.assertEqual(report['status'],0,report)
            self.assertEqual(report['r'][0],42,report)
            self.assertEqual(report['r'][13],initial_sp)
            self.assertEqual(report['f'][0],7)
            self.assertEqual(report['f'][63],0x7fc12345)
            self.assertEqual(report['fpscr'],0x08000010)
            self.assertEqual(len(report['translation_misses']),1)
            self.assertEqual(report['translation_misses'][0]['pc']&1,1)
            self.assertEqual(report['translation_misses'][0]['lr']&1,0)
            self.assertEqual(report['services'],1)
            self.assertEqual(report['translation_misses'][0]['instructions'],9)
            self.assertEqual(report['instructions'],33)
            if os.environ.get('VITANX_DYNAMIC_EVIDENCE'):
                dest=Path(os.environ['VITANX_DYNAMIC_EVIDENCE']);dest.mkdir(parents=True,exist_ok=True)
                (dest/'interwork-execution.json').write_text(json.dumps(report,indent=2)+'\n')
                (dest/'interwork.elf').write_bytes(elf.read_bytes())
            data=next(s for s in session.segments if s['flags']==6)
            off=data['virtual_address']-session.base
            self.assertEqual(bytes(session.memory[off:off+4]),struct.pack('<I',42))
            # STREX must see the LDREX reservation from the original native block.
            self.assertEqual(report['r'][7],0)

    def test_bad_indirect_target_stops_at_original_pc_without_replay(self):
        with tempfile.TemporaryDirectory() as d:
            d=Path(d);elf=d/'x.elf'
            # Increment once, then branch to misaligned ARM target loaded in r1.
            elf.write_bytes(support.elf([0xe2800001,0xe12fff11]))
            session=NativeSession(elf,d/'native');session.state.r[1]=0x102
            report=session.run()
            self.assertEqual(report['status'],-10)
            self.assertEqual(report['r'][0],1)
            self.assertEqual(report['pc'],0x102)
            self.assertEqual(report['instructions'],2)
            self.assertIn('outside executable',report['error'])

    def test_executable_write_is_rejected_before_memory_mutation(self):
        with tempfile.TemporaryDirectory() as d:
            d=Path(d);elf=d/'x.elf'
            elf.write_bytes(support.elf([0xe5810000,0xe12fff1e]))
            session=NativeSession(elf,d/'native')
            session.state.r[0]=0;session.state.r[1]=0x100
            original=bytes(session.memory[0x100:0x104])
            report=session.run()
            self.assertEqual(report['status'],-2)
            self.assertEqual(report['pc'],0x100)
            self.assertEqual(bytes(session.memory[0x100:0x104]),original)

    def test_multiple_misses_reuse_code_and_budget_is_global(self):
        with tempfile.TemporaryDirectory() as d:
            d=Path(d);elf=d/'x.elf'
            # Two dynamically entered ARM targets form a loop. Initial target
            # is loaded into r1, second into r2; each increments r0 once.
            elf.write_bytes(support.elf([0xe12fff11,0xe2800001,0xe12fff12,0xe2800001,0xe12fff11]))
            session=NativeSession(elf,d/'native',instruction_limit=11)
            session.state.r[1]=0x104;session.state.r[2]=0x10c
            report=session.run()
            self.assertEqual(report['status'],-4,report)
            self.assertEqual(report['instructions'],11)
            self.assertEqual(report['total_instructions'],11)
            self.assertEqual(len(report['translation_misses']),2)
            self.assertEqual(report['r'][0],5)

    def test_exclusive_state_across_separate_native_regions(self):
        spec=importlib.util.spec_from_file_location('dynamic_region_fixture',ROOT/'fixtures/dynamic/build.py')
        builder=importlib.util.module_from_spec(spec);spec.loader.exec_module(builder)
        with tempfile.TemporaryDirectory() as d:
            d=Path(d);elf=builder.build(d/'input')
            session=NativeSession(elf,d/'native',imports={8192:0x34efd876},region_entry=True)
            report=session.run()
            self.assertEqual(report['status'],0,report)
            self.assertEqual(report['r'][0],42)
            self.assertEqual(report['instructions'],33)
            self.assertGreaterEqual(len(session.regions),2)
            self.assertEqual(len(report['translation_misses']),1)

    def test_native_cache_reuses_code_with_fresh_runtime_state(self):
        with tempfile.TemporaryDirectory() as d:
            d=Path(d);source=ROOT/'fixtures/recompiler/hello.elf'
            first=NativeSession(source,d/'first',imports={8192:0x34efd876});a=first.run()
            second=NativeSession(source,d/'second',imports={8192:0x34efd876},native_cache=d/'first');b=second.run()
            self.assertEqual((a['status'],b['status']),(0,0))
            self.assertEqual(a['r'][0],b['r'][0])
            self.assertTrue(all(x['cache_hit'] for x in b['native_builds']))
            self.assertEqual(len(b['runtime_imports']),1)

    def test_large_function_executes_across_bounded_region_frontiers(self):
        with tempfile.TemporaryDirectory() as d:
            d=Path(d);source=d/'large.elf'
            source.write_bytes(support.elf([0xe3a00000]+[0xe2800001]*11+[0xe12fff1e]))
            with self.assertRaisesRegex(ValueError,'instruction limit'):
                translate_elf(source,max_instructions=3)
            session=NativeSession(source,d/'native',region_entry=True,partial_regions=True,translation_limit=3,execution_checkpoints=[5])
            report=session.run()
            self.assertEqual(report['status'],0,report)
            self.assertEqual(report['r'][0],11)
            self.assertEqual(report['instructions'],13)
            self.assertEqual(report['total_instructions'],13)
            self.assertEqual(len(report['translation_misses']),4)
            self.assertEqual(len(session.regions),5)
            check=json.loads((d/'native/cpu-at-5.json').read_text())
            self.assertEqual(check['r'][0],4)

    def test_cold_guest_thread_entry_translates_when_scheduled(self):
        import subprocess
        with tempfile.TemporaryDirectory() as d:
            d=Path(d);obj=d/'thread.o';source=d/'thread.elf'
            subprocess.run(['clang','-target','armv7-none-eabi','-mthumb','-march=armv7-a','-O1','-ffreestanding','-fno-unwind-tables','-fno-asynchronous-unwind-tables','-c',str(ROOT/'fixtures/modules/thread.c'),'-o',str(obj)],check=True,capture_output=True)
            subprocess.run(['ld.lld','-m','armelf','-T',str(ROOT/'fixtures/homebrew/link.ld'),str(obj),'-o',str(source)],check=True,capture_output=True)
            data=bytearray(source.read_bytes());struct.pack_into('<I',data,32,0);struct.pack_into('<HHH',data,46,0,0,0);source.write_bytes(data)
            session=NativeSession(source,d/'native',imports={0x2000:0xc5c11ee7,0x2004:0xf08de149,0x2008:0xddb395a9},region_entry=True,partial_regions=True,translation_limit=64)
            report=session.run()
            self.assertEqual(report['status'],0,report)
            self.assertEqual(report['r'][0],42,report)
            self.assertGreaterEqual(len(report['translation_misses']),1)
            self.assertTrue(any(x['nid']=='c5c11ee7' and x['result']<0x80000000 for x in report['runtime_imports']))

    def test_thumb_strd_duplicate_source_and_pair_fault_atomicity(self):
        blob=support.elf([0xe9cd,0x1100,0x4770],True)
        with tempfile.TemporaryDirectory() as d:
            d=Path(d);source=d/'strd.elf';source.write_bytes(blob)
            result=translate_elf(source)
            harness=support.RecompilerTests()
            harness.run_code(result,'r[13]=512;r[1]=0xa5a5a5a5;',
                             'if(vx_read32(mem+512)!=r[1]||vx_read32(mem+516)!=r[1])return 31;')
            harness.run_code(result,'r[13]=65532;r[1]=0xa5a5a5a5;',
                             'if(rc!=-2||vx_read32(mem+65532))return 32;rc=0;')
            session=NativeSession(source,d/'native',region_entry=True)
            session.state.r[13]=0xfc;session.state.r[1]=0xa5a5a5a5
            before=bytes(session.memory[0xfc:0x104]);report=session.run()
            self.assertEqual(report['status'],-2)
            self.assertEqual(bytes(session.memory[0xfc:0x104]),before)
            source.write_bytes(support.elf([0xe9dd,0x1100,0x4770],True))
            with self.assertRaisesRegex(ValueError,'dual transfer'):translate_elf(source)
