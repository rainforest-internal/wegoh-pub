"""Temporary-HOME default selection only; no actual identity/profile/network access."""
import contextlib,io,json,os,stat,sys,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).absolute().parents[1]/'scripts'))
import native_connect_runtime as client

class DefaultDirectoryTests(unittest.TestCase):
 def temporary_home(self):return tempfile.TemporaryDirectory(prefix='wegoh-directory-selection-')
 def snapshot(self,home):
  return {str(p.relative_to(home)):(stat.S_IMODE(p.lstat().st_mode),p.read_bytes()if p.is_file()and not p.is_symlink()else None)for p in home.rglob('*')}
 def test_empty_home_chooses_neutral_without_creating_profile(self):
  with self.temporary_home()as raw,patch.object(Path,'home',return_value=Path(raw)):
   home=Path(raw);self.assertEqual(client.default_directory(),home/'.wegoh-native');self.assertEqual(list(home.iterdir()),[])
 def test_each_single_existing_root_reuses_every_original_byte_and_mode(self):
  for name in ['.wegoh-native','.wegoh-native-v2','.wegoh-native-personal']:
   with self.subTest(name=name),self.temporary_home()as raw,patch.object(Path,'home',return_value=Path(raw)):
    home=Path(raw);root=home/name;root.mkdir(mode=0o700)
    for filename in ['identity.pem','identity.v2.csr.pem','state.key','state.enc','state.json','selection-00001.enc']:
     item=root/filename;item.write_bytes(b'owned synthetic preservation sentinel:'+filename.encode());item.chmod(0o600)
    before=self.snapshot(home)
    self.assertEqual(client.default_directory(),root);self.assertEqual(self.snapshot(home),before)
 def test_multiple_roots_fail_closed_without_preference_or_new_key(self):
  for names in [('.wegoh-native','.wegoh-native-v2'),('.wegoh-native','.wegoh-native-personal'),('.wegoh-native-v2','.wegoh-native-personal'),('.wegoh-native','.wegoh-native-v2','.wegoh-native-personal')]:
   with self.subTest(names=names),self.temporary_home()as raw,patch.object(Path,'home',return_value=Path(raw)):
    home=Path(raw)
    for name in names:(home/name).mkdir(mode=0o700)
    before=self.snapshot(home)
    with self.assertRaisesRegex(client.ClientError,'^EXPLICIT_PROFILE_DIRECTORY_REQUIRED$'):client.default_directory()
    self.assertEqual(self.snapshot(home),before)
 def test_explicit_directory_bypasses_conflict_and_implicit_error_is_caught(self):
  with self.temporary_home()as raw,patch.object(Path,'home',return_value=Path(raw)),patch('native_connect.preflight',return_value={}):
   home=Path(raw)
   for name in ['.wegoh-native','.wegoh-native-v2']:(home/name).mkdir(mode=0o700)
   before=self.snapshot(home);stdout,stderr=io.StringIO(),io.StringIO()
   with patch.object(client,'Profile',side_effect=AssertionError('No implicit profile open')),patch.object(client,'initialize',side_effect=AssertionError('No new key')),contextlib.redirect_stdout(stdout),contextlib.redirect_stderr(stderr):
    self.assertEqual(client.main(['check']),1)
   self.assertEqual(stdout.getvalue(),'');self.assertEqual(json.loads(stderr.getvalue()),{'error':'EXPLICIT_PROFILE_DIRECTORY_REQUIRED'});self.assertNotIn('Traceback',stderr.getvalue());self.assertEqual(self.snapshot(home),before)
   selected=home/'.wegoh-native-v2';profile=SimpleNamespace(state={'keepSignedIn':True});stdout,stderr=io.StringIO(),io.StringIO()
   @contextlib.contextmanager
   def open_profile(path):
    self.assertEqual(path,selected);yield profile
   with patch.object(client,'default_directory',side_effect=AssertionError('Explicit path must bypass discovery')),patch.object(client,'selected_directory',side_effect=lambda path:path),patch.object(client,'Profile',side_effect=open_profile),patch.object(client,'ensure_unlocked'),patch.object(client,'check_with_recovery',return_value={'status':'owned synthetic guarded check'}),patch.object(client,'initialize',side_effect=AssertionError('No new key')),contextlib.redirect_stdout(stdout),contextlib.redirect_stderr(stderr):
    self.assertEqual(client.main(['--directory',str(selected),'check']),0)
   self.assertEqual(stderr.getvalue(),'');self.assertEqual(json.loads(stdout.getvalue()),{'status':'owned synthetic guarded check'});self.assertEqual(self.snapshot(home),before)
 def test_dangling_symlink_is_occupied_never_a_new_profile_fallback(self):
  with self.temporary_home()as raw,patch.object(Path,'home',return_value=Path(raw)),patch('native_connect.preflight',return_value={}):
   home=Path(raw);old=home/'.wegoh-native-v2';old.symlink_to(home/'missing-original');self.assertEqual(client.default_directory(),old)
   stdout,stderr=io.StringIO(),io.StringIO()
   with patch.object(client,'Profile',side_effect=AssertionError('No symlink profile open')),patch.object(client,'initialize',side_effect=AssertionError('No new key')),contextlib.redirect_stdout(stdout),contextlib.redirect_stderr(stderr):self.assertEqual(client.main(['check']),1)
   self.assertEqual(json.loads(stderr.getvalue()),{'error':'SYMLINK_REFUSED'});self.assertTrue(old.is_symlink());self.assertFalse((home/'.wegoh-native').exists());self.assertFalse((home/'missing-original').exists())
