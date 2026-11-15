"""Read-only identity preservation and private-file boundaries; no public old CLI."""
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import native_client_support as support


class NativeClientSupportTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='wegoh-private-support-')
        self.addCleanup(self.temp.cleanup)
        self.home=Path(self.temp.name)/'identity';self.home.mkdir(mode=0o700)
        for name,value in [('lock',b''),('client.key.pem',b'synthetic-private-marker'),('state.json',json.dumps({'version':1,'privateMarker':'never-copy'}).encode())]:
            support.exclusive(self.home/name,value)
        self.before=self.snapshot()
    def snapshot(self):
        return {p.name:(p.read_bytes(),p.stat().st_mode) for p in self.home.iterdir() if p.is_file()}
    def test_01_reader_preserves_original_bytes_and_has_no_network_or_save(self):
        with support.ExistingIdentityProfile(self.home) as value:
            self.assertEqual(value.state['version'],1)
            self.assertFalse(hasattr(value,'save'))
            self.assertFalse(hasattr(value,'request'))
        self.assertEqual(self.snapshot(),self.before)
    def test_02_existing_file_never_overwritten_and_symlinks_refused(self):
        with self.assertRaises(FileExistsError):support.exclusive(self.home/'client.key.pem',b'replacement')
        link=self.home.parent/'linked';link.symlink_to(self.home,target_is_directory=True)
        with self.assertRaises(support.ClientError):support.native_path(link/'state.json')
        self.assertEqual(self.snapshot(),self.before)
    def test_03_permissions_and_hardlinks_refused_without_repairing_original(self):
        p=self.home/'client.key.pem';p.chmod(0o644)
        with self.assertRaises(support.ClientError):support.read_file(p)
        self.assertEqual(p.stat().st_mode&0o777,0o644)
        p.chmod(0o600);hard=self.home.parent/'hard';os.link(p,hard)
        with self.assertRaises(support.ClientError):support.read_file(p)
        self.assertEqual(p.read_bytes(),self.before[p.name][0])
    def test_04_nested_lock_fails_then_releases_without_state_mutation(self):
        with support.ExistingIdentityProfile(self.home):
            with self.assertRaises(BlockingIOError):
                with support.ExistingIdentityProfile(self.home):pass
        with support.ExistingIdentityProfile(self.home):pass
        self.assertEqual(self.snapshot(),self.before)
    def test_05_bool_or_unknown_storage_version_refused(self):
        for value in (True,2,'1'):
            raw=json.dumps({'version':value}).encode();p=self.home/'state.json';p.write_bytes(raw)
            with self.subTest(value=value),self.assertRaises(support.ClientError):
                with support.ExistingIdentityProfile(self.home):pass
            self.assertEqual(p.read_bytes(),raw)


if __name__=='__main__':unittest.main(verbosity=2)
