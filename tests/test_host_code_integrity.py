"""Host-provider mutations must be detected even when yielding or exiting."""
import ctypes as C
import hashlib
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from vitanx.dynamic import GuestState, NativeSession


class HostCodeIntegrityTests(unittest.TestCase):
    def probe(self, path, after_resume=False, process_exit=False, mutate=True):
        original = b'ABCD'
        path.write_bytes(original)
        session = NativeSession.__new__(NativeSession)
        session.source = path
        session.cache = SimpleNamespace(digest=hashlib.sha256(original).hexdigest())
        session.base = 0x1000
        session.segments = [{'flags': 1, 'virtual_address': 0x1000, 'file_size': 4}]
        session.image = original
        session.instruction_limit = 10
        session.retired = 0
        session.execution_checkpoints = ()
        session.error = None
        memory = (C.c_uint8 * 4).from_buffer_copy(original)
        state = GuestState()
        calls = []
        def control(cpu, mem):
            calls.append('control')
            if after_resume and len(calls) == 1:
                return False
            if mutate:
                mem[0] = 0
            if process_exit:
                session.exit_requested = True
            return 2
        def resume(cpu, mem, size, budget):
            calls.append('resume')
            return 2
        session._control = control
        session.active_resume = resume
        result = session._dispatch(C.pointer(state), C.cast(memory, C.POINTER(C.c_uint8)), 4, 10)
        return session, result, calls

    def test_host_write_before_initial_yield_and_exit_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            for exit_requested in (False, True):
                with self.subTest(exit_requested=exit_requested):
                    session, result, calls = self.probe(Path(tmp)/'source', process_exit=exit_requested)
                    self.assertEqual(result, -10)
                    self.assertIn('self-modifying', session.error)
                    self.assertEqual(calls, ['control'])

    def test_host_write_after_region_yield_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            session, result, calls = self.probe(Path(tmp)/'source', after_resume=True)
            self.assertEqual(result, -10)
            self.assertIn('self-modifying', session.error)
            self.assertEqual(calls, ['control', 'resume', 'control'])

    def test_unchanged_host_yield_is_allowed(self):
        with tempfile.TemporaryDirectory() as tmp:
            session, result, _ = self.probe(Path(tmp)/'source', mutate=False, process_exit=True)
            self.assertEqual(result, 1)
            self.assertIsNone(session.error)

    def test_native_import_writes_are_checked_before_every_return_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            for rc in (0, 1, -4):
                with self.subTest(return_status=rc):
                    path=Path(tmp)/'source';original=b'ABCD';path.write_bytes(original)
                    s=NativeSession.__new__(NativeSession)
                    s.source=path;s.cache=SimpleNamespace(digest=hashlib.sha256(original).hexdigest())
                    s.base=0x1000;s.segments=[{'flags':1,'virtual_address':0x1000,'file_size':4}]
                    s.image=original;s.retired=0;s.instruction_limit=10;s.execution_checkpoints=()
                    s.error=None;s._control=lambda cpu,mem:False
                    mem=(C.c_uint8*4).from_buffer_copy(original);cpu=GuestState()
                    def resume(state,memory,size,budget):
                        memory[0]=0;state.contents.services+=1
                        return rc
                    s.active_resume=resume
                    result=s._dispatch(C.pointer(cpu),C.cast(mem,C.POINTER(C.c_uint8)),4,10)
                    self.assertEqual(result,-10)
                    self.assertIn('self-modifying',s.error)
