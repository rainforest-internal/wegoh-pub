"""One-public-contract PC migration using isolated synthetic native-home profiles."""
import contextlib
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import test_native_connect as fixtures
from test_native_connect import client, codec


class PublicContractMigrationTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='wegoh-public-contract-', dir=Path.home())
        self.path = Path(self.tmp.name)/'personal'
        client.initialize(self.path, 'Migration fixture', sorted(x.value for x in codec.REQUIRED_SCOPES))
        self.key = (self.path/'identity.pem').read_bytes()
        self.csr = (self.path/'identity.csr.pem').read_bytes()
        self.cap = client.encoded(b'r'*32)
        self.access = client.encoded(b'a'*32)
        self.refresh = client.encoded(b'f'*32)

    def tearDown(self):
        self.tmp.cleanup()

    def old_profile(self, *, credential=False, outbox=False, pending=True, renewal=False):
        with client.Profile(self.path) as profile:
            api = fixtures.SyntheticAPI(profile)
            self.api = api
            api.begin = dict(operationId="b"*32)
            api.issue()
            profile.state['certificate'] = api.certificate
            client.store_certificate(profile, api.certificate)
            profile.state.pop('publicApiVersion')
            profile.state['phase'] = 'authorizing'
            profile.state['keepSignedIn'] = True
            if credential:
                profile.state['credentials'] = dict(authorizationVersion=2, grantId='c'*32,
                    deviceId='d'*32, accountId='previous-owner', accessToken=self.access,
                    refreshToken=self.refresh, revokeCapability=self.cap)
            if outbox:
                profile.state['outbox'] = [dict(action='GRANT_REVOKE', request=dict(
                    authorizationVersion=2, operationId='a'*32, grantId='c'*32,
                    revokeCapability=self.cap), certificates=[api.certificate])]
            if pending:
                profile.state['authorization'] = dict(action='CONNECTION_BEGIN',
                    verifier='old-private-pkce', request=dict(authorizationVersion=2,
                    operationId='b'*32, oldPath='/v2/connections'), response=dict(state='PENDING'))
                profile.state['pendingCredential'] = {'oldPrivate':'not-for-replay'}
            self.certificate = dict(profile.state['certificate'])
            if renewal:
                api.certificate=None;api.now+=1
                api.issue()
                self.staged = dict(api.certificate)
                profile.state['renewal'] = {'request':{'grantId':'c'*32},'certificate':self.staged}
            profile.save()
        self.original = (self.path/'state.enc').read_bytes()
        self.state_key = (self.path/'state.key').read_bytes()
        return self.original

    def archive(self):
        return self.path/('pre-public-v1-'+hashlib.sha256(self.original).hexdigest()+'.enc')

    def assert_identity_preserved(self):
        self.assertEqual((self.path/'identity.pem').read_bytes(), self.key)
        self.assertEqual((self.path/'identity.csr.pem').read_bytes(), self.csr)
        self.assertEqual((self.path/'state.key').read_bytes(), self.state_key)
        self.assertEqual(self.archive().read_bytes(), self.original)
        self.assertEqual(self.archive().stat().st_mode & 0o777, 0o600)

    def test_old_pending_locks_then_new_explicit_authorization_keeps_key_and_cert(self):
        self.old_profile()
        with patch.object(client, 'transport') as transport, client.Profile(self.path) as profile:
            transport.assert_not_called()
            self.assertEqual(profile.state['publicApiVersion'], 1)
            self.assertEqual(profile.state['version'], 2)  # unchanged encrypted storage format
            self.assertEqual(profile.state['phase'], 'locked')
            self.assertEqual(profile.state['certificate'], self.certificate)
            for name in ('authorization','credentials','pendingCredential','keepSignedIn','cancelledAuthorization'):
                self.assertNotIn(name, profile.state)
            client.new_authorization(profile)
            request = profile.state['authorization']['request']
            self.assertEqual(request['authorizationVersion'], 1)
            self.assertNotEqual(request['operationId'], 'b'*32)
            self.assertEqual(request['certificatePem'], self.certificate['certificatePem'])
            self.assertNotIn('old-private-pkce', json.dumps(profile.state))
            transport.assert_not_called()
        self.assert_identity_preserved()

    def test_revoke_only_outbox_new_operation_is_durable_without_personal_authority(self):
        self.old_profile(credential=True, outbox=True, renewal=True)
        with client.Profile(self.path) as profile:
            pending = profile.state['outbox']
            self.assertEqual(len(pending), 1)
            request = pending[0]['request']
            self.assertEqual(set(request), {'authorizationVersion','operationId','grantId','revokeCapability'})
            self.assertEqual(request['authorizationVersion'], 1)
            self.assertNotEqual(request['operationId'], 'a'*32)
            self.assertEqual(request['grantId'], 'c'*32)
            self.assertEqual(request['revokeCapability'], self.cap)
            self.assertEqual(profile.state['phase'], 'revoke_pending')
            self.assertEqual(len(pending[0]['certificates']),2)
            self.assertEqual({x['certificateSha256'] for x in pending[0]['certificates']},
                             {self.certificate['certificateSha256'],self.staged['certificateSha256']})
            serialized = json.dumps(profile.state)
            for value in (self.access,self.refresh,'previous-owner','old-private-pkce'):
                self.assertNotIn(value, serialized)
            operation = request['operationId']
        with client.Profile(self.path) as profile:
            self.assertEqual(profile.state['outbox'][0]['request']['operationId'], operation)
        self.assert_identity_preserved()

    def test_atomic_failure_retains_original_cipher_and_retries_without_key_regeneration(self):
        self.old_profile(outbox=True)
        with patch.object(client.os, 'replace', side_effect=OSError('synthetic atomic failure')):
            with self.assertRaises(OSError):
                with client.Profile(self.path): pass
        self.assertEqual((self.path/'state.enc').read_bytes(), self.original)
        self.assert_identity_preserved()
        with client.Profile(self.path) as profile:
            self.assertEqual(profile.state['publicApiVersion'], 1)
        self.assert_identity_preserved()

    def test_changed_archive_and_corrupt_cipher_fail_closed(self):
        self.old_profile()
        client.exclusive(self.archive(), b'not-original-ciphertext')
        with patch.object(client, 'initialize') as initialize:
            with self.assertRaisesRegex(client.ClientError, 'LOCAL_ARCHIVE_CHANGED'):
                with client.Profile(self.path): pass
            initialize.assert_not_called()
        self.assertEqual((self.path/'state.enc').read_bytes(), self.original)
        self.assertEqual((self.path/'identity.pem').read_bytes(), self.key)

    def test_wrong_grant_key_or_conflicting_der_candidate_preserves_original_locked(self):
        # Three malformed authenticated-at-rest fixtures; no CA/network invocation.
        for mode in ('wrong_grant','wrong_key','conflicting_der'):
            with self.subTest(mode=mode):
                if (self.path/'state.enc').exists():
                    # Each old source is written through the synthetic fixture, never real data.
                    with client.Profile(self.path) as profile:
                        profile.state.pop('publicApiMigration',None)
                        profile.state['publicApiVersion']=1
                        profile.state.pop('credentials',None);profile.state.pop('renewal',None)
                        profile.state['outbox']=[];profile.save()
                self.old_profile(credential=True,outbox=True)
                raw=(self.path/'state.enc').read_bytes()
                key=(self.path/'state.key').read_bytes()
                value=json.loads(client.AESGCM(key).decrypt(raw[:12],raw[12:],client.AAD))
                if mode=='wrong_grant':
                    value['renewal']={'request':{'grantId':'e'*32},'certificate':dict(self.certificate)}
                elif mode=='wrong_key':
                    value['outbox'][0]['certificates'][0]['installationKeyId']='f'*64
                else:
                    # A second PEM/DER cannot claim the first fingerprint and win merge order.
                    self.api.certificate=None;self.api.now+=1
                    self.api.issue()
                    value['outbox'][0]['certificates'][0]['certificatePem']=self.api.certificate['certificatePem']
                nonce=b'fixture-old!'  # 12-byte synthetic AES nonce, isolated per fixture only.
                original=nonce+client.AESGCM(key).encrypt(nonce,json.dumps(value).encode(),client.AAD)
                (self.path/'state.enc').write_bytes(original)
                with patch.object(client,'transport') as transport,patch.object(client,'initialize') as initialize:
                    with self.assertRaises((client.ClientError,codec.CodecError)):
                        with client.Profile(self.path):pass
                    transport.assert_not_called();initialize.assert_not_called()
                self.assertEqual((self.path/'state.enc').read_bytes(),original)
                self.assertEqual((self.path/('pre-public-v1-'+hashlib.sha256(original).hexdigest()+'.enc')).read_bytes(),original)
                self.assertEqual((self.path/'identity.pem').read_bytes(),self.key)
                # Restore only the owned temporary fixture between independent subcases.
                (self.path/'state.enc').write_bytes(raw)

    def test_locked_check_cannot_restore_old_personal_session(self):
        self.old_profile(credential=True)
        with patch.object(client, 'transport') as transport, contextlib.redirect_stderr(io.StringIO()) as output:
            self.assertEqual(client.main(['--directory',str(self.path),'check']), 1)
            self.assertEqual(json.loads(output.getvalue())['error'], 'ACCOUNT_LOCKED_RUN_CONNECT')
            transport.assert_not_called()
        self.assert_identity_preserved()
