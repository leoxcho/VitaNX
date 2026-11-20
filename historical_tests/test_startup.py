"""Real subprocess lifecycle tests; these fixtures assert no Vita compatibility."""
import math
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from vitaxnative.build import verify_native, NativeVerificationError

class StartupTests(unittest.TestCase):
    def probe(self, code, **kwargs):
        with tempfile.TemporaryDirectory() as directory:
            script=Path(directory)/'probe'
            script.write_text('#!'+sys.executable+'\n'+code)
            script.chmod(0o755)
            return verify_native(script, **kwargs)

    def test_success(self):
        result=self.probe('print("completed")', mode='startup')
        self.assertEqual(result['observation'],'exited_successfully')
        self.assertTrue(result['native_exit_verified'])
        self.assertFalse(result['playable_verified'])

    def test_error_exit(self):
        with self.assertRaises(NativeVerificationError) as error:
            self.probe('raise SystemExit(7)')
        self.assertEqual(error.exception.evidence['observation'],'exited_with_error')
        self.assertEqual(error.exception.evidence['returncode'],7)

    def test_signal_crash(self):
        with self.assertRaises(NativeVerificationError) as error:
            self.probe('import os, signal; os.kill(os.getpid(),signal.SIGKILL)',mode='startup')
        self.assertEqual(error.exception.evidence['observation'],'crashed')
        self.assertEqual(error.exception.evidence['signal'],9)

    def test_timeout_and_running_are_distinct_and_reaped(self):
        import os
        for mode in ('exit','startup'):
            code='import os,time; print(os.getpid(),flush=True); time.sleep(30)'
            if mode=='exit':
                with self.assertRaises(NativeVerificationError) as error:
                    self.probe(code,mode=mode,timeout=0.3)
                result=error.exception.evidence
                self.assertEqual(result['observation'],'timed_out')
            else:
                result=self.probe(code,mode=mode,timeout=0.3)
                self.assertEqual(result['observation'],'running_at_deadline_then_terminated')
            self.assertFalse(result['native_exit_verified'])
            self.assertTrue(result['probe_terminated'])
            with self.assertRaises(ProcessLookupError):os.kill(int(result['stdout'].strip()),0)

    def test_invalid_options(self):
        for timeout in (True,0,-1,16,float('nan'),float('inf'),'10'):
            with self.assertRaises(ValueError):verify_native('/unused',timeout=timeout)
        with self.assertRaises(ValueError):verify_native('/unused',mode='playable')

    def test_cli_observe_startup_wiring(self):
        from vitaxnative.__main__ import main
        from contextlib import redirect_stdout
        import io
        with patch.object(sys,'argv',['vitaxnative','build-native','input.velf','output','--observe-startup']),patch('vitaxnative.build.build_native',return_value={}) as build,redirect_stdout(io.StringIO()):
            main()
        self.assertTrue(build.call_args.kwargs['verify'])
        self.assertEqual(build.call_args.kwargs['verification'],'startup')

    def test_cli_failed_observation_exposes_evidence(self):
        from vitaxnative.__main__ import main
        from contextlib import redirect_stderr
        import io
        with patch.object(sys,'argv',['vitaxnative','build-native','input.velf','output','--observe-startup']),patch('vitaxnative.build.build_native',side_effect=NativeVerificationError('signal crash',{'observation':'crashed','signal':9})),redirect_stderr(io.StringIO()) as output:
            with self.assertRaises(SystemExit) as error:main()
        self.assertEqual(error.exception.code,2)
        self.assertIn('"observation": "crashed"',output.getvalue())

    def test_cli_verification_options_are_exclusive(self):
        from vitaxnative.__main__ import main
        from contextlib import redirect_stderr
        import io
        with patch.object(sys,'argv',['vitaxnative','build-native','input','output','--verify','--observe-startup']),redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as error:main()
        self.assertEqual(error.exception.code,2)
