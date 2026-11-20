import struct,tempfile,unittest
from pathlib import Path
from test_module_execution import fixture
from vitanx.modules import ModuleSession

class LiveBoundaryTests(unittest.TestCase):
    def test_resolve_in_same_live_process_without_replaying_entry(self):
        with tempfile.TemporaryDirectory() as tmp:
            d=Path(tmp);paths,_=fixture.build(d/'input');calls=[]
            def resolve(session,item,state):
                calls.append((item['key'],state.contents.r[0],state.contents.r[14]))
                session.deferred.append(paths[1]);return True
            s=ModuleSession(paths[:1],d/'run',allow_unresolved=True,boundary_handler=resolve)
            report=s.run()
            self.assertEqual(report['status'],0,report);self.assertEqual(report['r'][0],42)
            self.assertEqual(len(calls),1);self.assertEqual(calls[0][0],(fixture.LIB_A,fixture.FUNCTION));self.assertEqual(calls[0][1],5)
            off=s.process.modules[0].new_base+0x1008-s.base
            self.assertEqual(struct.unpack('<I',bytes(s.memory[off:off+4]))[0],1)
            self.assertEqual([e['phase'] for e in report['module_phases']],['lazy_start','stop'])
