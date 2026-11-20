"""Recover declared MOVW/MOVT/BLX targets without changing indirect semantics."""
import unittest
import struct
import test_recompiler as support

class LiteralCallTests(unittest.TestCase):
    translate=support.RecompilerTests.translate
    run_code=support.RecompilerTests.run_code

    def program(self,clobber=False):
        code=[0xb500,0xf240,0x1c41,0xf2c0,0x0c00,0x2107]
        if clobber:code += [0x4694]  # MOV ip,r2 destroys the literal proof.
        code += [0x47e0,0xbd00]
        return support.elf(code+[0]*(32-len(code))+[0x2009,0x4770],True)

    def test_complete_definition_seeds_target_and_preserves_native_call(self):
        r=self.translate(self.program(),discover_literal_calls=True)
        self.assertEqual(list(r['literal_call_targets'].values()),[0x141])
        self.run_code(r,'r[13]=600;', 'if(r[0]!=9||r[1]!=7||r[13]!=600)return 1;')

    def test_intervening_write_stays_dynamic_and_unknown_target_traps(self):
        r=self.translate(self.program(True),discover_literal_calls=True)
        self.assertFalse(r['literal_call_targets'])
        self.run_code(r,'r[13]=600;r[2]=0x141;', 'if(rc!=-3)return 2;rc=0;')

    def test_high_address_movt_and_explicit_bound(self):
        blob=bytearray(self.program());struct.pack_into('<I',blob,24,0x81000101)
        struct.pack_into('<II',blob,60,0x81000100,0x81000100)
        struct.pack_into('<HH',blob,0x106,0xf2c8,0x1c00)
        r=self.translate(blob,discover_literal_calls=True)
        self.assertEqual(list(r['literal_call_targets'].values()),[0x81000141])
        self.run_code(r,'r[13]=0x81001000u;','if(r[0]!=9||r[13]!=0x81001000u)return 3;')
        with self.assertRaisesRegex(ValueError,'instruction limit'):self.translate(blob,max_instructions=2)
