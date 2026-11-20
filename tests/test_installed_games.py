import struct
import tempfile
import unittest
from pathlib import Path
from vitanx.installed_games import list_installed_games, read_param_sfo


def sfo(values):
    keys = bytearray()
    data = bytearray()
    entries = bytearray()
    for name, value in values.items():
        key_offset = len(keys)
        keys.extend(name.encode('ascii') + b'\x00')
        val = value.encode('utf-8') + b'\x00'
        offset = len(data)
        data.extend(val)
        entries.extend(struct.pack('<HHIII', key_offset, 0x0204, len(val), len(val), offset))
    key_start = 20 + len(entries)
    value_start = key_start + len(keys)
    return struct.pack('<4sIIII', b'\x00PSF', 0x101, key_start, value_start, len(values)) + entries + keys + data


class InstalledGamesTests(unittest.TestCase):
    def test_base_patch_dlc(self):
        with tempfile.TemporaryDirectory() as d:
            ux0 = Path(d) / 'ux0'
            base = ux0 / 'app' / 'PCSF00024' / 'sce_sys'
            patch = ux0 / 'patch' / 'PCSF00024' / 'sce_sys'
            dlc = ux0 / 'addcont' / 'PCSF00024' / 'DLC_A'
            base.mkdir(parents=True)
            patch.mkdir(parents=True)
            dlc.mkdir(parents=True)
            (base / 'param.sfo').write_bytes(sfo({'TITLE_ID':'PCSF00024', 'TITLE':'Gravity Rush', 'APP_VER':'01.00'}))
            (patch / 'param.sfo').write_bytes(sfo({'TITLE_ID':'PCSF00024', 'APP_VER':'01.02'}))
            result = list_installed_games(ux0 / 'app')
            self.assertEqual(result['count'], 1)
            game = result['games'][0]
            self.assertEqual(game['title'], 'Gravity Rush')
            self.assertEqual(game['version'], '01.00')
            self.assertEqual(game['patch_version'], '01.02')
            self.assertEqual(game['dlc_content_ids'], ['DLC_A'])
            self.assertFalse(game['base_metadata_error'])
            self.assertFalse(game['patch_metadata_error'])

    def test_invalid_metadata_and_symlink(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)/'app'; root.mkdir()
            base = root/'PCSF00024'/'sce_sys'; base.mkdir(parents=True)
            (base/'param.sfo').write_bytes(sfo({'TITLE_ID':'PCSB12345'}))
            (root/'PCSF00025').symlink_to(base.parent)
            result = list_installed_games(root)
            self.assertEqual(result['count'], 1)
            self.assertIn('mismatch', result['games'][0]['base_metadata_error'])
            with self.assertRaises(ValueError):read_param_sfo(base/'no-such-file')

    def test_sfo_invalid_bounds_and_duplicate_key(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)/'param.sfo';p.write_bytes(sfo({'TITLE':'Test'}))
            self.assertEqual(read_param_sfo(p)['TITLE'], 'Test')
            data=bytearray(p.read_bytes());struct.pack_into('<I',data,12,0xfffffff0)
            p.write_bytes(data)
            with self.assertRaises(ValueError):read_param_sfo(p)
            p.unlink();p.symlink_to('/etc/passwd')
            with self.assertRaises(ValueError):read_param_sfo(p)

if __name__=='__main__':unittest.main()
