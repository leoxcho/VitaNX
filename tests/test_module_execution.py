import importlib.util
import ctypes as C
import json,os,struct,tempfile
from pathlib import Path
import unittest
from vitanx.modules import ModuleSession,ModuleImage,LinkError,runtime_bindings
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('module_fixture',ROOT/'fixtures/modules/build.py')
fixture=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixture)

class ModuleExecutionTests(unittest.TestCase):
    def test_relocation_library_collision_cross_module_start_stop(self):
        with tempfile.TemporaryDirectory() as d:
            d=Path(d);paths,symbols=fixture.build(d/'input')
            session=ModuleSession(paths,d/'run');sp=session.state.r[13]
            report=session.run()
            self.assertEqual(report['status'],0,report)
            self.assertEqual(report['r'][0],42)
            self.assertEqual(report['r'][13],sp)
            self.assertEqual(report['f'][0],5)
            tls=report['tpidruro']-session.base
            self.assertEqual(bytes(session.memory[tls:tls+16]),b'TLS!'+bytes(12))
            self.assertEqual(len(report['module_loader']['function_bindings']),1)
            self.assertEqual(report['module_loader']['function_bindings'][0]['provider'],'support_a')
            for m in session.process.modules:
                off=m.new_base+0x1000-session.base
                data=struct.unpack('<III',bytes(session.memory[off:off+12]))
                self.assertEqual(data,(5,42,1) if m.name=='main' else (10,42,20) if m.name=='support_a' else (10,0,20))
                self.assertEqual(m.relocation_counts,{2:1})
                literal=m.word(symbols[session.process.modules.index(m)]['state_ptr'])
                self.assertEqual(literal,m.new_base+0x1000)
            self.assertEqual([x['phase'] for x in report['module_phases']],['start','start','stop','stop'])
            if os.environ.get('VITANX_MODULE_EVIDENCE'):
                out=Path(os.environ['VITANX_MODULE_EVIDENCE']);out.mkdir(parents=True,exist_ok=True)
                (out/'execution.json').write_text(json.dumps(report,indent=2)+'\n')
                for path in paths:(out/path.name).write_bytes(path.read_bytes())

    def test_lazy_provider_load_initializes_without_replaying_main(self):
        with tempfile.TemporaryDirectory() as d:
            d=Path(d);paths,_=fixture.build(d/'input')
            session=ModuleSession(paths[:1],d/'run',deferred=[paths[1],paths[1].parent/'.'/paths[1].name])
            report=session.run()
            self.assertEqual(report['status'],0,report)
            self.assertEqual(report['r'][0],42)
            self.assertEqual([m.name for m in session.process.modules],['main','support_a'])
            self.assertEqual(report['module_phases'][0]['phase'],'lazy_start')
            self.assertFalse(report['module_loader']['pending_imports'])
            off=session.process.modules[0].new_base+0x1008-session.base
            self.assertEqual(struct.unpack('<I',bytes(session.memory[off:off+4]))[0],1)

    def test_unresolved_and_ambiguous_links_are_transactional(self):
        with tempfile.TemporaryDirectory() as d:
            d=Path(d);paths,_=fixture.build(d/'input')
            image=ModuleImage(d/'stage')
            with self.assertRaisesRegex(LinkError,'unresolved'):image.load(paths[0])
            self.assertEqual(image.modules,[])
            image.load(paths[0],allow_unresolved=True);image.load(paths[1])
            before=[bytes(m.memory) for m in image.modules]
            duplicate=bytearray(paths[2].read_bytes())
            struct.pack_into('<I',duplicate,0x100+0x900+32+16,int(fixture.LIB_A,16))
            dup=d/'ambiguous.elf';dup.write_bytes(duplicate)
            with self.assertRaisesRegex(LinkError,'ambiguous'):image.load(dup)
            self.assertEqual([bytes(m.memory) for m in image.modules],before)

    def test_runtime_registry_requires_exact_library_and_function(self):
        bindings=runtime_bindings()
        self.assertEqual(bindings[('f2ff276e','34efd876')],0x34efd876)
        self.assertNotIn(('a0000001','34efd876'),bindings)

    def test_initializer_thread_exit_does_not_skip_later_modules_or_main(self):
        with tempfile.TemporaryDirectory() as d:
            d=Path(d);paths,_=fixture.build(d/'input')
            source=bytearray(paths[1].read_bytes())
            # Call the real Vita thread-exit service. Instructions at the return
            # address (the stop routine) MUST NOT execute after the thread exits.
            pc=0x10010;target=0x10700
            struct.pack_into('<I',source,0x100+0x10,0xeb000000|(((target-pc-8)>>2)&0xffffff))
            struct.pack_into('<I',source,0x100+0x700,0xe12fff1e)
            struct.pack_into('<II',source,0x100+0x800+0x2c,0xa00,0xa34)
            struct.pack_into('<BBHHHHH',source,0x100+0xa00,0x34,0,1,0,1,0,0)
            struct.pack_into('<II',source,0x100+0xa10,0x859a24b1,0)
            struct.pack_into('<II',source,0x100+0xa1c,0x10c80,0x10c84)
            struct.pack_into('<II',source,0x100+0xc80,0x0c8a38e1,target)
            paths[1].write_bytes(source)
            session=ModuleSession(paths,d/'run')
            report=session.run()
            self.assertEqual(report['status'],0,report)
            self.assertTrue(report['main_executed'])
            self.assertEqual(report['r'][0],42)
            self.assertTrue(any(x['nid']=='0c8a38e1' for x in report['runtime_imports']))
            other=session.process.modules[2].new_base+0x1000-session.base
            self.assertEqual(struct.unpack('<I',bytes(session.memory[other:other+4]))[0],10)

    def test_encrypted_self_is_refused_without_original_changes(self):
        from test_self_extract import fixture as self_fixture
        with tempfile.TemporaryDirectory() as d:
            d=Path(d);path=d/'encrypted.self';data=self_fixture(encryption=1);path.write_bytes(data)
            image=ModuleImage(d/'stage')
            with self.assertRaisesRegex(ValueError,'encrypted SELF'):image.load(path)
            self.assertEqual(path.read_bytes(),data)
            self.assertEqual(image.modules,[])

    def test_unknown_library_cannot_borrow_known_stdout_nid(self):
        with tempfile.TemporaryDirectory() as d:
            d=Path(d);paths,_=fixture.build(d/'input')
            data=bytearray(paths[0].read_bytes())
            struct.pack_into('<I',data,0x100+0xc00,0x34efd876)
            paths[0].write_bytes(data)
            session=ModuleSession(paths[:1],d/'run',allow_unresolved=True)
            report=session.run()
            self.assertEqual(report['status'],-9)
            self.assertEqual(report['r'][0],5)
            self.assertEqual(report['runtime_imports'],[])
            self.assertEqual(report['fault_context']['library_nid'],'a0000001')
            self.assertEqual(report['fault_context']['function_nid'],'34efd876')
            self.assertEqual(report['fault_context']['args'][0],5)
            self.assertEqual(report['fault_context']['reason'],'no qualified provider')
            self.assertEqual(report['fault_context']['deferred_candidates'],[])
            self.assertIn({'library_nid':'f2ff276e','provider':'explicit host runtime'},
                          report['fault_context']['same_function_other_libraries'])

    def test_dynamic_debug_device_binding_retains_full_output_word(self):
        with tempfile.TemporaryDirectory() as d:
            d=Path(d)
            main,_=fixture.build_one(d/'input','main',fixture.MAIN.replace('cmp r0,#42','cmp r0,#0'))
            paths=[main]
            data=bytearray(paths[0].read_bytes())
            struct.pack_into('<I',data,0x100+0xa10,0xae004c0a)
            struct.pack_into('<I',data,0x100+0xc00,0x78e702d3)
            paths[0].write_bytes(data)
            session=ModuleSession(paths[:1],d/'run')
            session.runtime.vn_devices_set_gpi.argtypes=[C.c_uint32]
            session.runtime.vn_devices_set_gpi(0xfedcba98)
            session.runtime.vn_device_import.argtypes=[C.c_uint32,C.POINTER(C.c_uint32),C.POINTER(C.c_uint32)]
            session.runtime.vn_devices_get_gpo.restype=C.c_uint32
            regs=(C.c_uint32*16)();regs[0]=0xf1234567;result=C.c_uint32(123)
            self.assertEqual(session.runtime.vn_device_import(0x78e702d3,regs,C.byref(result)),1)
            self.assertEqual(result.value,0)
            self.assertEqual(session.runtime.vn_devices_get_gpo(),0xf1234567)
            self.assertEqual(session.runtime.vn_device_import(0x14f582cf,regs,C.byref(result)),1)
            self.assertEqual(result.value,0xfedcba98)
            result.value=123
            self.assertEqual(session.runtime.vn_device_import(0xdeadbeef,regs,C.byref(result)),0)
            self.assertEqual(result.value,123)
            report=session.run()
            self.assertEqual(report['status'],0,report)
            self.assertEqual(report['r'][0],42)
            self.assertEqual(report['devices'],{'gpo':5,'gpi':0xfedcba98})
            self.assertEqual(session.runtime.vn_devices_get_gpo(),0)
            self.assertEqual(report['runtime_imports'][0]['nid'],'78e702d3')
            self.assertEqual(report['runtime_imports'][0]['result'],0)
            self.assertEqual(report['services'],1)

    def test_game_classification_requires_known_sfo_metadata(self):
        with tempfile.TemporaryDirectory() as d:
            d=Path(d)
            main,_=fixture.build_one(d/'input','main',fixture.MAIN.replace('cmp r0,#42','cmp r0,#1'))
            data=bytearray(main.read_bytes())
            struct.pack_into('<I',data,0x100+0xa10,0x8af17416)
            struct.pack_into('<I',data,0x100+0xc00,0xfff8f7f0);main.write_bytes(data)
            assets=d/'assets';(assets/'sce_sys').mkdir(parents=True)
            key=b'CATEGORY\0';value=b'gd\0'
            sfo=struct.pack('<4sIIII',b'\0PSF',0x101,36,36+len(key),1)+struct.pack('<HHIII',0,0x0204,len(value),len(value),0)+key+value
            (assets/'sce_sys/param.sfo').write_bytes(sfo)
            session=ModuleSession([main],d/'known',assets=assets)
            report=session.run()
            self.assertEqual(report['status'],0,report)
            self.assertEqual(report['r'][0],42)
            self.assertEqual(report['application_type'],1)
            self.assertEqual(report['runtime_imports'][0]['result'],1)
            unknown=ModuleSession([main],d/'unknown',allow_unresolved=True)
            result=unknown.run()
            self.assertEqual(result['status'],-9)
            self.assertEqual(result['fault_context']['function_nid'],'fff8f7f0')

    def test_vfp_status_import_yields_without_expanding_cached_hooks(self):
        with tempfile.TemporaryDirectory() as d:
            d=Path(d);paths,_=fixture.build(d/'input')
            source=bytearray(paths[0].read_bytes())
            struct.pack_into('<I',source,0x100+0xa10,0x859a24b1)
            struct.pack_into('<I',source,0x100+0xc00,0xcc18fbae)
            paths[0].write_bytes(source)
            session=ModuleSession([paths[0]],d/'run')
            self.assertNotIn(0xcc18fbae,session.process.hooks.values())
            self.assertTrue(any(row['key']==('859a24b1','cc18fbae') for row in session.process.intercepts.values()))
            session.state.fpscr=0x0800009f
            report=session.run()
            self.assertEqual(report['status'],0,report)
            self.assertEqual(report['fpscr'],0x0800009b)
            calls=[row for row in report['runtime_imports'] if row['nid']=='cc18fbae']
            self.assertEqual(len(calls),1)
            self.assertEqual(calls[0]['result'],0)
