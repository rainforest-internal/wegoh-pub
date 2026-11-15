"""Explicit local-loss recovery only, immutable selector and source preservation."""
import contextlib,io,json,os,unittest
from pathlib import Path
from unittest.mock import patch
import test_native_connect as fixture
client=fixture.client
codec=fixture.codec

class NativeInstallationRecoveryTests(unittest.TestCase):
    setUp=fixture.NativeConnectTest.setUp
    tearDown=fixture.NativeConnectTest.tearDown

    def test_valid_or_network_pending_profile_never_generates_another_private_key(self):
        original=(self.path/'identity.pem').read_bytes()
        with client.Profile(self.path) as profile:
            profile.state['phase']='credential_unconfirmed';profile.save()
        with self.assertRaisesRegex(client.ClientError,'RECOVERY_NOT_NEEDED_USE_CONNECT'):
            client.recover_installation_directory(self.path,'Test',sorted(s.value for s in codec.REQUIRED_SCOPES))
        self.assertEqual((self.path/'identity.pem').read_bytes(),original)
        self.assertEqual(list(self.path.glob('recovered_*')),[])
        self.assertEqual(list(self.path.glob('selection-*.key')),[])

    def test_missing_public_csr_restores_same_bytes_instead_of_rekeying(self):
        csr=(self.path/'identity.csr.pem').read_bytes();key=(self.path/'identity.pem').read_bytes()
        (self.path/'identity.csr.pem').unlink()  # Only newly-created synthetic profile.
        with self.assertRaisesRegex(client.ClientError,'RECOVERY_NOT_NEEDED_USE_CONNECT'):
            client.recover_installation_directory(self.path,'Test',sorted(s.value for s in codec.REQUIRED_SCOPES))
        self.assertEqual((self.path/'identity.csr.pem').read_bytes(),csr)
        self.assertEqual((self.path/'identity.pem').read_bytes(),key)

    def test_explicit_missing_private_key_retains_original_cipher_history_and_uses_fresh_phone(self):
        cipher=(self.path/'state.enc').read_bytes();public=(self.path/'identity.csr.pem').read_bytes()
        history=self.path/'synthetic-original-history.bin';client.exclusive(history,b'Preserve original history')
        (self.path/'identity.pem').unlink()  # Simulated loss only in this synthetic profile.
        selected=client.recover_installation_directory(self.path,'Test',sorted(s.value for s in codec.REQUIRED_SCOPES))
        self.assertNotEqual(selected,self.path);self.assertEqual(client.selected_directory(self.path),selected)
        self.assertFalse((self.path/'identity.pem').exists());self.assertEqual((self.path/'state.enc').read_bytes(),cipher)
        self.assertEqual((self.path/'identity.csr.pem').read_bytes(),public);self.assertEqual(history.read_bytes(),b'Preserve original history')
        with client.Profile(selected) as profile:
            api=fixture.SyntheticAPI(profile);api.scopes=sorted(s.value for s in codec.REQUIRED_SCOPES);output=io.StringIO()
            with patch.object(client,'transport',api),patch.object(client,'wait_for_poll'),contextlib.redirect_stdout(output):
                self.assertEqual(client.connect(profile,self.args),{'status':'connected'})
            self.assertEqual(len(output.getvalue().strip().splitlines()),1)
            self.assertEqual(profile.state['credentials']['scopes'],sorted(s.value for s in codec.REQUIRED_SCOPES))
        self.assertEqual(api.issued,1)
        for file in selected.iterdir():self.assertEqual(file.stat().st_mode&0o777,0o600)
        for file in self.path.glob('selection-*'):self.assertEqual(file.stat().st_mode&0o777,0o600)

    def test_corrupt_state_and_missing_state_key_preserve_every_existing_original(self):
        for kind in ('corrupt','state-key'):
            with self.subTest(kind=kind):
                path=self.root/kind;client.initialize(path,'Test',sorted(s.value for s in codec.REQUIRED_SCOPES))
                if kind=='corrupt':
                    raw=(path/'state.enc').read_bytes();(path/'state.enc').write_bytes(raw[:-1]+bytes([raw[-1]^1]))
                else:(path/'state.key').unlink()
                originals={f.name:f.read_bytes() for f in path.iterdir() if f.is_file()}
                selected=client.recover_installation_directory(path,'Test',sorted(s.value for s in codec.REQUIRED_SCOPES))
                self.assertEqual(client.selected_directory(path),selected)
                for name,raw in originals.items():self.assertEqual((path/name).read_bytes(),raw,name)
                with client.Profile(selected) as profile:self.assertEqual(profile.state['phase'],'ready')

    def test_explicit_command_selects_new_profile_and_subsequent_connect_uses_it(self):
        (self.path/'identity.pem').unlink();peers={};output=io.StringIO()
        def transport(profile,*args,**kwargs):
            if 'api' not in peers:
                peers['api']=fixture.SyntheticAPI(profile);peers['api'].scopes=profile.state['requestedScopes']
            peers['api'].profile=profile
            return peers['api'](profile,*args,**kwargs)
        with patch.object(client,'transport',transport),contextlib.redirect_stdout(output):
            self.assertEqual(client.main(['--directory',str(self.path),'recover-installation','--no-browser','--wait','0']),0)
            selected=client.selected_directory(self.path);key=(selected/'identity.pem').read_bytes()
            self.assertEqual(client.main(['--directory',str(self.path),'connect','--no-browser','--wait','0']),0)
        public=[json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual(public[0],{'status':'previous_device_review_required','manageDevices':'iPhone WegoH 앱 > 설정 > 연결 차량 설정'})
        self.assertEqual((selected/'identity.pem').read_bytes(),key)
        self.assertFalse((self.path/'identity.pem').exists())

    def test_damaged_newest_selector_never_falls_back_or_silently_replaces_state(self):
        (self.path/'identity.pem').unlink()
        selected=client.recover_installation_directory(self.path,'Test',sorted(s.value for s in codec.REQUIRED_SCOPES))
        cipher=(self.path/'selection-00001.enc').read_bytes();new_key=(selected/'identity.pem').read_bytes()
        (self.path/'selection-00001.key').unlink()
        with self.assertRaisesRegex(client.ClientError,'LOCAL_SELECTOR_DAMAGED'):client.selected_directory(self.path)
        self.assertEqual((selected/'identity.pem').read_bytes(),new_key)
        self.assertEqual((self.path/'selection-00001.enc').read_bytes(),cipher)
        replacement=client.recover_installation_directory(self.path,'Test',sorted(s.value for s in codec.REQUIRED_SCOPES))
        self.assertNotEqual(replacement,selected);self.assertEqual(client.selected_directory(self.path),replacement)
        self.assertEqual((selected/'identity.pem').read_bytes(),new_key)
        self.assertEqual((self.path/'selection-00001.enc').read_bytes(),cipher)

if __name__=='__main__':unittest.main()
