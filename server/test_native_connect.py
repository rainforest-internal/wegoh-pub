"""Client-side single-public-contract flow regression. Synthetic certs/phone/API; no live CA or user data."""
import argparse
import base64
import contextlib
import hashlib
import io
import http.server
import threading
import socket
import json
import os
from pathlib import Path
import ssl
import stat
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
from datetime import datetime, timedelta, timezone

sys.path.insert(0, str(Path(__file__).absolute().parents[1] / 'scripts'))
import native_connect as bootstrap
import native_connect_runtime as client
import native_access_codec as codec
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID


class SyntheticAPI:
    """Independent deterministic wire peer. CA signing happens only once per begin."""
    def __init__(self, profile, *, remember=True):
        self.profile = profile
        self.calls = []
        self.remember = remember
        self.ca = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.now = int(time.time())
        self.scopes = sorted(item.value for item in codec.Scope)
        self.nonce = client.encoded(bytes(range(32)))
        self.connection_id = 'b' * 32
        self.grant_id = 'c' * 32
        self.device_id = 'd' * 32
        self.account_id = 'team-' + 'e' * 40
        self.begin = None
        self.issued = 0
        self.lost = None
        self.credential = None
        self.certificate = None
        self.epoch = 1
        self.refresh_operations = {}
        self.force_expired = False

    def response(self, action, request, state, disposition, **values):
        return dict(authorizationVersion=1, operation=action, operationId=request['operationId'],
                    state=state, disposition=disposition, serverTime=self.now, **values)

    def issue(self):
        if self.certificate:
            return
        self.issued += 1
        csr = x509.load_pem_x509_csr(self.profile.csr_pem.encode())
        builder = (x509.CertificateBuilder().subject_name(csr.subject)
                .issuer_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'Synthetic CA')]))
                .public_key(csr.public_key()).serial_number(1)
                .not_valid_before(datetime.fromtimestamp(self.now - 60, timezone.utc))
                .not_valid_after(datetime.fromtimestamp(self.now + getattr(self,'certificate_lifetime',90 * 86400), timezone.utc))
                .add_extension(x509.BasicConstraints(ca=False, path_length=None), True))
        if getattr(self, 'include_key_usage', True):
            builder = builder.add_extension(x509.KeyUsage(True, False, False, False, False, False, False, None, None), True)
        cert = (builder.add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.CLIENT_AUTH]), False)
                .sign(self.ca, hashes.SHA256()))
        self.certificate = dict(certificatePem=cert.public_bytes(serialization.Encoding.PEM).decode(),
            certificateSha256=cert.fingerprint(hashes.SHA256()).hex(),
            installationKeyId=self.profile.state['installationKeyId'], generation=1,
            generationOperationId=self.begin['operationId'], expiresAt=self.now + getattr(self,'certificate_lifetime',90 * 86400))

    def credential_receipt(self, verifier=None):
        if not self.credential:
            self.credential = dict(accessToken=client.encoded(b'a' * 32), refreshToken=client.encoded(b'f' * 32),
                tokenType='Bearer', accountId=self.account_id, grantId=self.grant_id, deviceId=self.device_id,
                installationKeyId=self.profile.state['installationKeyId'],
                certificateSha256=self.certificate['certificateSha256'], generation=1, slotRevision=1,
                credentialEpoch=self.epoch, consentVersion=1, scopes=self.scopes,
                expiresAt=self.now + 900, grantExpiresAt=self.now + 604800,
                recoveryCapability=codec.derive_capability(verifier, self.grant_id, 'recovery'),
                revokeCapability=codec.derive_revoke_capability(verifier,self.profile.state['installationKeyId'],self.begin['operationId']))
        return dict(self.credential)

    def verify_proof(self, action, record):
        request = record.for_transport()
        message = codec.proof_transcript(action, record,
            installation_key_id=self.profile.state['installationKeyId'],
            code_challenge=request['codeChallenge'] if action == 'CONNECTION_RESTART' else self.begin['codeChallenge'],
            connection_id=self.connection_id if action in ('CONNECTION_CLAIM', 'CONNECTION_RESTART') else None)
        signature = base64.urlsafe_b64decode(request['proof'] + '==')
        self.profile.key.public_key().verify(signature, message, padding.PKCS1v15(), hashes.SHA256())

    def __call__(self, profile, host, path, method='POST', body=None, access=None):
        if method == 'GET':
            self.calls.append(('GET', path))
            assert access == self.credential['accessToken']
            if path == '/v1/account':
                return 200, json.dumps(dict(user=dict(id=self.account_id,displayName='Synthetic owner'), deviceId=self.device_id)).encode()
            return 200, json.dumps(dict(deviceId=self.device_id, scopes=self.scopes,
                keepSignedIn=self.remember, consentVersion=1, grantExpiresAt=self.credential['grantExpiresAt'])).encode()
        request = body.for_transport()
        actions = [name for name, operation in client.OPERATIONS.items()
                   if operation['host'] == host and operation['path'].replace('{connectionId}', self.connection_id)
                   .replace('{deviceId}', self.device_id) == path]
        if path == '/v1/connections':
            action = 'CONNECTION_RESTART' if 'previousConnectionId' in request else 'CONNECTION_BEGIN'
        else:
            action = actions[0]
        codec.decode_request(action, request)
        self.calls.append((action, dict(request)))
        if action == 'CONNECTION_BEGIN':
            if self.begin:
                assert self.begin == request
            self.begin = dict(request)
            values = dict(connectionId=self.connection_id, userCode='ABCD2345',
                verificationUri=client.CONTRACT['phone']['current'].replace('<UserCode>', 'ABCD2345'),
                proofNonce=self.nonce, expiresAt=self.now + 300, interval=5)
            response = self.response(action, request, 'PENDING', 'WAIT', **values)
            status = 201
        elif action == 'CONNECTION_RECOVER':
            self.verify_proof(action, body)
            if self.force_expired:
                response = self.response(action, request, 'EXPIRED_NOT_ISSUED', 'USER_RESTART_ALLOWED',
                    connectionId=self.connection_id, proofNonce=self.nonce,
                    restartTicket=client.encoded(b'r' * 32), restartExpiresAt=self.now + 60)
            elif self.certificate:
                response = self.response(action, request, 'ISSUED', 'EXCHANGE', connectionId=self.connection_id,
                    certificateReceipt=self.certificate, grantId=self.grant_id, proofNonce=self.nonce,
                    exchangeExpiresAt=self.now + 300)
            else:
                response = self.response(action, request, 'APPROVED', 'CONTINUE_CLAIM',
                    connectionId=self.connection_id, proofNonce=self.nonce, expiresAt=self.now + 300, interval=5)
            status = 200
        elif action == 'CONNECTION_RESTART':
            self.verify_proof(action, body)
            assert request['oldCodeVerifier'] != request['codeChallenge']
            self.force_expired = False
            self.begin = dict(request)
            response = self.response(action, request, 'PENDING', 'WAIT', connectionId=self.connection_id,
                userCode='ABCD2345', verificationUri=client.CONTRACT['phone']['current'].replace('<UserCode>', 'ABCD2345'),
                proofNonce=self.nonce, expiresAt=self.now + 300, interval=5)
            status = 201
        elif action == 'CONNECTION_CLAIM':
            self.verify_proof(action, body)
            self.issue()
            response = self.response(action, request, 'ISSUED', 'EXCHANGE', connectionId=self.connection_id,
                certificateReceipt=self.certificate, grantId=self.grant_id, proofNonce=self.nonce,
                exchangeExpiresAt=self.now + 300)
            status = 200
        elif action == 'SESSION_EXCHANGE':
            response = self.response(action, request, 'TOKEN_ISSUED', 'CREDENTIAL_RECEIPT',
                credentialReceipt=self.credential_receipt(request['codeVerifier']))
            status = 200
        elif action in ('SESSION_REFRESH', 'SESSION_RECOVER'):
            if request['operationId'] not in self.refresh_operations:
                self.epoch += 1
                self.credential.update(accessToken=client.encoded(bytes([self.epoch]) * 32),
                                       refreshToken=client.encoded(bytes([self.epoch + 1]) * 32),
                                       credentialEpoch=self.epoch, expiresAt=self.now + 900)
                self.refresh_operations[request['operationId']] = dict(self.credential)
            response = self.response(action, request, 'TOKEN_ISSUED', 'CREDENTIAL_RECEIPT',
                credentialReceipt=self.refresh_operations[request['operationId']])
            status = 200
        elif action in ('SESSION_REVOKE','GRANT_REVOKE'):
            assert set(request) == {'authorizationVersion', 'operationId', 'grantId', 'revokeCapability'}
            if action=='GRANT_REVOKE':assert codec.revoke_commitment(request['revokeCapability'])==self.begin['revokeCommitment']
            response = self.response(action, request, 'REVOKED', 'TERMINAL', **({'grantId':self.grant_id} if action=='GRANT_REVOKE' else {'deviceId':self.device_id}), revokedAt=self.now)
            status = 200
        else:
            raise AssertionError(action)
        if self.lost == action:
            self.lost = None
            raise client.ClientError('REQUEST_UNCONFIRMED')
        return status, json.dumps(response).encode()


class RenewalAPI(SyntheticAPI):
    """Independent staged-generation peer; CA issuance and rebind are distinct."""
    def __init__(self,profile):
        super().__init__(profile)
        self.certificate_lifetime=7200
        self.renewals={};self.staged=None;self.rebinds={};self.uncertain_once=False
        self.stale_once=False;self.after_rebind=None

    def __call__(self,profile,host,path,method='POST',body=None,access=None):
        if method=='GET' and path=='/v1/device/permissions':
            self.calls.append(('GET',path))
            assert access==self.credential['accessToken']
            return 200,json.dumps(dict(deviceId=self.device_id,scopes=self.scopes,keepSignedIn=True,
                consentVersion=self.credential['consentVersion'],grantExpiresAt=self.credential['grantExpiresAt'])).encode()
        if not body:return super().__call__(profile,host,path,method,body,access)
        request=body.for_transport()
        if path=='/v1/installations/certificate-renew':action='CERTIFICATE_RENEW_BEGIN'
        elif path=='/v1/device-sessions/rebind':action='CREDENTIAL_REBIND'
        elif path.endswith('/claim') and any(value['connectionId'] in path for value in self.renewals.values()):action='CERTIFICATE_RENEW_CLAIM'
        else:
            if path.endswith('/revoke') and self.staged and self.certificate==self.staged:
                actual=profile.state.get('revocationCertificate') or profile.state['certificate']
                if actual['certificateSha256']!=self.certificate['certificateSha256']:
                    return 403,json.dumps(dict(authorizationVersion=1,error='CERTIFICATE_BINDING_MISMATCH')).encode()
            return super().__call__(profile,host,path,method,body,access)
        codec.decode_request(action,request);self.calls.append((action,dict(request)))
        if action=='CERTIFICATE_RENEW_BEGIN':
            message=codec.proof_transcript(action,body,installation_key_id=profile.state['installationKeyId'],code_challenge=request['codeChallenge'])
            profile.key.public_key().verify(base64.urlsafe_b64decode(request['proof']+'=='),message,padding.PKCS1v15(),hashes.SHA256())
            assert request['grantId']==self.credential['grantId'] and request['recoveryCapability']==self.credential['recoveryCapability']
            if request['operationId'] not in self.renewals:
                self.renewals[request['operationId']]=dict(request=request,connectionId=hashlib.sha256(request['operationId'].encode()).hexdigest()[:32])
            renewal=self.renewals[request['operationId']]
            value=self.response(action,request,'APPROVED','CONTINUE_CLAIM',connectionId=renewal['connectionId'],proofNonce=self.nonce,expiresAt=self.now+300,interval=5)
            status=201
        elif action=='CERTIFICATE_RENEW_CLAIM':
            renewal=next(value for value in self.renewals.values() if value['connectionId'] in path)
            message=codec.proof_transcript(action,body,installation_key_id=profile.state['installationKeyId'],code_challenge=renewal['request']['codeChallenge'],connection_id=renewal['connectionId'])
            profile.key.public_key().verify(base64.urlsafe_b64decode(request['proof']+'=='),message,padding.PKCS1v15(),hashes.SHA256())
            assert client.challenge(request['codeVerifier'])==renewal['request']['codeChallenge']
            if self.staged is None:
                old=self.certificate;self.certificate=None;self.certificate_lifetime=90*86400
                self.issue();self.staged=self.certificate;self.certificate=old
                self.staged.update(generation=old['generation']+1,generationOperationId=renewal['request']['operationId'])
            self.staged['generationOperationId']=renewal['request']['operationId']
            if self.uncertain_once:
                self.uncertain_once=False
                value=self.response(action,request,'UNCERTAIN','RECONCILE',connectionId=renewal['connectionId'],interval=5);status=202
            else:
                value=self.response(action,request,'ISSUED','CERTIFICATE_RECEIPT',connectionId=renewal['connectionId'],certificateReceipt=self.staged);status=200
        else:
            assert profile.state['renewal']['certificate']['certificateSha256']==self.staged['certificateSha256']
            assert request['recoveryCapability']==self.credential['recoveryCapability']
            if self.stale_once:
                self.stale_once=False;self.scopes=sorted(item.value for item in codec.REQUIRED_SCOPES)
                self.credential['scopes']=self.scopes;self.credential['consentVersion']+=1;self.credential['credentialEpoch']+=1
                return 409,json.dumps(dict(authorizationVersion=1,error='STALE_EPOCH')).encode()
            if request['operationId'] not in self.rebinds:
                self.certificate=self.staged;self.epoch=self.credential['credentialEpoch']+1
                self.credential.update(certificateSha256=self.staged['certificateSha256'],generation=self.staged['generation'],
                    credentialEpoch=self.epoch,accessToken=client.encoded(bytes([self.epoch])*32),refreshToken=client.encoded(bytes([self.epoch+1])*32))
                self.rebinds[request['operationId']]=dict(self.credential)
            value=self.response(action,request,'TOKEN_ISSUED','CREDENTIAL_RECEIPT',credentialReceipt=self.rebinds[request['operationId']]);status=200
            if self.after_rebind:self.after_rebind()
        if self.lost==action:
            self.lost=None;raise client.ClientError('REQUEST_UNCONFIRMED')
        return status,json.dumps(value).encode()


class ReauthorizationAPI(RenewalAPI):
    """Same persisted installation, one fresh explicit phone approval, fresh grant."""
    def __init__(self,profile):
        super().__init__(profile);self.reauth=None;self.old_grant=None;self.approvals=0;self.ca_active=True;self.claimed=False
    def credential_receipt(self,verifier=None):
        value=super().credential_receipt(verifier)
        self.credential['generation']=self.certificate['generation']
        value['generation']=self.certificate['generation']
        return value
    def __call__(self,profile,host,path,method='POST',body=None,access=None):
        if not body:return super().__call__(profile,host,path,method,body,access)
        request=body.for_transport()
        is_public=path=='/v1/connections' and 'installationKeyId' in request
        is_account=path=='/v1/device-authorizations'
        if is_public or is_account:
            action='CONNECTION_REAUTHORIZE' if is_public else 'ACCOUNT_AUTHORIZE'
            codec.decode_request(action,request);self.calls.append((action,dict(request)))
            if is_public:
                assert host=='enroll' and request['expectedGeneration']==self.certificate['generation']
                message=codec.proof_transcript(action,body,installation_key_id=profile.state['installationKeyId'],code_challenge=request['codeChallenge'])
                profile.key.public_key().verify(base64.urlsafe_b64decode(request['proof']+'=='),message,padding.PKCS1v15(),hashes.SHA256())
                if not self.ca_active:return 403,json.dumps(dict(authorizationVersion=1,error='INSTALLATION_REVOKED')).encode()
            if self.reauth is None:
                self.reauth=dict(request);self.old_grant=dict(self.credential);self.begin=dict(request)
                self.connection_id='9'*32;self.grant_id='8'*32;self.device_id='7'*32
                self.credential=None;self.scopes=request['requestedScopes'];self.approvals+=1
                state,disposition='PENDING','WAIT'
            else:
                assert self.reauth==request
                state,disposition=('APPROVED','EXCHANGE') if is_account else ('PENDING','WAIT')
            if disposition=='EXCHANGE':
                response=self.response(action,request,state,disposition,connectionId=self.connection_id,grantId=self.grant_id,proofNonce=self.nonce,exchangeExpiresAt=self.now+300);status=200
            else:
                response=self.response(action,request,state,disposition,connectionId=self.connection_id,userCode='WXYZ2345',verificationUri=client.CONTRACT['phone']['current'].replace('<UserCode>','WXYZ2345'),proofNonce=self.nonce,expiresAt=self.now+300,interval=5);status=201
        elif self.reauth and path=='/v1/connections/recover':
            action='CONNECTION_RECOVER';self.calls.append((action,dict(request)));self.verify_proof(action,body)
            if self.claimed:
                response=self.response(action,request,'ISSUED','EXCHANGE',connectionId=self.connection_id,certificateReceipt=self.certificate,grantId=self.grant_id,proofNonce=self.nonce,exchangeExpiresAt=self.now+300)
            else:response=self.response(action,request,'APPROVED','CONTINUE_CLAIM',connectionId=self.connection_id,proofNonce=self.nonce,expiresAt=self.now+300,interval=5)
            status=200
        elif self.reauth and path=='/v1/connections/'+self.connection_id+'/claim':
            action='CONNECTION_CLAIM';self.calls.append((action,dict(request)));self.verify_proof(action,body)
            if not self.claimed:
                previous=self.certificate;self.certificate=None;self.certificate_lifetime=90*86400;self.issue()
                self.certificate.update(generation=previous['generation']+1,generationOperationId=self.reauth['operationId']);self.claimed=True
            response=self.response(action,request,'ISSUED','EXCHANGE',connectionId=self.connection_id,certificateReceipt=self.certificate,grantId=self.grant_id,proofNonce=self.nonce,exchangeExpiresAt=self.now+300);status=200
        elif self.reauth and path.endswith('/revoke'):
            action='GRANT_REVOKE' if path=='/v1/device-sessions/revoke' else 'SESSION_REVOKE';self.calls.append((action,dict(request)))
            assert request['grantId']==self.old_grant['grantId'] and request['revokeCapability']==self.old_grant['revokeCapability']
            response=self.response(action,request,'REVOKED','TERMINAL',**({'grantId':self.old_grant['grantId']} if action=='GRANT_REVOKE' else {'deviceId':self.old_grant['deviceId']}),expiredAt=self.old_grant['grantExpiresAt']);status=200
        else:return super().__call__(profile,host,path,method,body,access)
        if action=='ACCOUNT_AUTHORIZE':response.pop('proofNonce',None)
        if self.lost==action:self.lost=None;raise client.ClientError('REQUEST_UNCONFIRMED')
        return status,json.dumps(response).encode()


class NativeConnectTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='wegoh-cli-', dir=Path.home())
        self.root = Path(self.temp.name)
        self.path = self.root / 'personal'
        self.args = argparse.Namespace(name=None, scopes=None, no_browser=True, wait=30, restart=False)
        client.initialize(self.path, '개인 시험 기기', sorted(item.value for item in codec.Scope))

    def tearDown(self):
        self.temp.cleanup()

    def connected(self, remember=True):
        with client.Profile(self.path) as profile:
            api = SyntheticAPI(profile, remember=remember)
            with patch.object(client, 'transport', api), patch.object(client, 'wait_for_poll'), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(client.connect(profile, self.args), {'status': 'connected'})
        return api

    def renewal_connected(self):
        with client.Profile(self.path) as profile:
            api=RenewalAPI(profile)
            with patch.object(client,'transport',api),patch.object(client,'wait_for_poll'),contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(client.connect(profile,self.args),{'status':'connected'})
        return api

    def test_cancelled_pending_phone_terminal_allows_same_key_fresh_prompt_without_exchange(self):
        class CancelPeer(SyntheticAPI):
            denied = False
            original = None
            fresh_operation = None
            def __call__(peer, profile, host, path, method='POST', body=None, access=None):
                request = body.for_transport() if body else None
                if path == client.OPERATIONS['CONNECTION_RECOVER']['path']:
                    # Only the new unconfirmed operation is queried. Old PKCE
                    # was removed before the first reconnection network call.
                    assert request['operationId'] != peer.original['operationId']
                    assert request['operationId'] == peer.fresh_operation
                    peer.calls.append(('CONNECTION_RECOVER', dict(request)))
                    return 404, json.dumps(dict(authorizationVersion=1,error='OPERATION_NOT_FOUND')).encode()
                if path == '/v1/connections' and peer.begin and peer.begin['operationId'] != request['operationId']:
                    if peer.fresh_operation is None:peer.fresh_operation=request['operationId']
                    assert peer.fresh_operation == request['operationId']
                    if not peer.denied:
                        peer.calls.append(('CONNECTION_BEGIN_CONFLICT',dict(request)))
                        return 409, json.dumps(dict(authorizationVersion=1,error='OPERATION_CONFLICT')).encode()
                    peer.begin = None
                result = super(CancelPeer,peer).__call__(profile,host,path,method,body,access)
                if path == '/v1/connections' and peer.original is None:peer.original=dict(request)
                return result
        key = (self.path/'identity.pem').read_bytes()
        self.args.wait = 0
        with client.Profile(self.path) as profile:
            api = CancelPeer(profile)
            with patch.object(client,'transport',api),contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(client.connect(profile,self.args),{'status':'approval_pending'})
                old_operation = profile.state['authorization']['request']['operationId']
                old_verifier = profile.state['authorization']['verifier']
                public = dict(profile.state['authorization']['public'])
                approved = api.response('CONNECTION_RECOVER', {'operationId':old_operation},
                    'APPROVED','CONTINUE_CLAIM',connectionId=api.connection_id,
                    proofNonce=api.nonce,expiresAt=api.now+300,interval=5)
                client.persist_response(profile,codec.decode_response('CONNECTION_RECOVER',200,approved,expected_operation_id=old_operation))
                self.assertNotIn('verificationUri',profile.state['authorization']['response'])
        logout_output=io.StringIO()
        with contextlib.redirect_stdout(logout_output):
            self.assertEqual(client.main(['--directory',str(self.path),'logout']),0)
        logout=json.loads(logout_output.getvalue())
        self.assertEqual(set(logout),{'status','approvalCancellation','verificationUri','userCode','expiresAt'})
        self.assertEqual({name:logout[name] for name in public},public)
        self.assertNotIn(old_verifier,logout_output.getvalue())
        with client.Profile(self.path) as profile:
            api.profile=profile
            self.assertEqual(profile.state['cancelledAuthorization']['public'],public)
            self.assertEqual(set(profile.state['cancelledAuthorization']),{'public','operationId'})
            self.assertNotIn(old_verifier,json.dumps(profile.state))
            output=io.StringIO()
            with patch.object(client,'transport',api),contextlib.redirect_stdout(output):
                with self.assertRaisesRegex(client.ClientError,'APPROVAL_CANCELLED_CHECK_PHONE'):
                    client.connect(profile,self.args)
                guide=json.loads(output.getvalue())
                self.assertEqual(guide,logout)
                self.assertNotIn(old_verifier,output.getvalue())
                self.assertIn('cancelledAuthorization',profile.state)
                self.assertNotIn(old_verifier,json.dumps(profile.state))
                self.assertNotEqual(profile.state['authorization']['verifier'],old_verifier)
                api.denied = True
                self.assertEqual(client.connect(profile,self.args),{'status':'approval_pending'})
                self.assertNotIn('cancelledAuthorization',profile.state)
                self.assertNotIn('credentials',profile.state)
                self.assertEqual(profile.state['authorization']['request']['operationId'],api.fresh_operation)
                self.assertNotEqual(api.fresh_operation,old_operation)
                self.assertEqual(api.issued,0)
                self.assertFalse(any(action.startswith('SESSION_') or action=='CONNECTION_CLAIM' for action,_ in api.calls))
        self.assertEqual((self.path/'identity.pem').read_bytes(),key)

    def test_renewal_preserves_key_owner_grant_scope_expiry_and_uses_no_new_phone(self):
        api=self.renewal_connected();key=(self.path/'identity.pem').read_bytes()
        with client.Profile(self.path) as profile:
            api.profile=profile;before=dict(profile.state['credentials']);out=io.StringIO()
            with patch.object(client,'transport',api),patch.object(client,'wait_for_poll'),contextlib.redirect_stdout(out):
                self.assertEqual(client.connect(profile,self.args),{'status':'connected'})
            after=profile.state['credentials']
            for field in ('accountId','grantId','deviceId','scopes','consentVersion','slotRevision','grantExpiresAt'):
                self.assertEqual(before[field],after[field],field)
            self.assertEqual(after['generation'],2);self.assertGreater(after['credentialEpoch'],before['credentialEpoch'])
            self.assertNotIn('renewal',profile.state);self.assertEqual(out.getvalue(),'')
        self.assertEqual(key,(self.path/'identity.pem').read_bytes());self.assertEqual(api.issued,2)
        self.assertEqual(sum(action=='CONNECTION_BEGIN' for action,_ in api.calls),1)

    def test_renewal_response_losses_resume_exact_operations_without_duplicate_ca(self):
        for lost in ('CERTIFICATE_RENEW_BEGIN','CERTIFICATE_RENEW_CLAIM','CREDENTIAL_REBIND'):
            with self.subTest(lost=lost):
                path=self.root/lost;client.initialize(path,'같은 키 갱신',sorted(item.value for item in codec.Scope))
                with client.Profile(path) as profile:
                    api=RenewalAPI(profile)
                    with patch.object(client,'transport',api),patch.object(client,'wait_for_poll'),contextlib.redirect_stdout(io.StringIO()):client.connect(profile,self.args)
                    api.lost=lost
                    with patch.object(client,'transport',api),patch.object(client,'wait_for_poll'):
                        with self.assertRaisesRegex(client.ClientError,'REQUEST_UNCONFIRMED'):client.connect(profile,self.args)
                    pending=dict(profile.state['renewal']['request']);rebind=profile.state['renewal']['rebindOperation']
                with client.Profile(path) as profile:
                    api.profile=profile
                    with patch.object(client,'transport',api),patch.object(client,'wait_for_poll'):
                        self.assertEqual(client.connect(profile,self.args),{'status':'connected'})
                self.assertEqual(api.issued,2)
                begins=[body for action,body in api.calls if action=='CERTIFICATE_RENEW_BEGIN']
                self.assertTrue(all(value==pending for value in begins))
                self.assertTrue(all(body['operationId']==rebind for action,body in api.calls if action=='CREDENTIAL_REBIND'))

    def test_renewal_unknown_issuance_and_scope_race_never_expand_or_blindly_reissue(self):
        api=self.renewal_connected();api.uncertain_once=True;api.stale_once=True
        with client.Profile(self.path) as profile:
            api.profile=profile;expiry=profile.state['credentials']['grantExpiresAt']
            with patch.object(client,'transport',api),patch.object(client,'wait_for_poll'):
                self.assertEqual(client.check_with_recovery(profile),{'status':'connected'})
            self.assertEqual(profile.state['credentials']['scopes'],sorted(item.value for item in codec.REQUIRED_SCOPES))
            self.assertEqual(profile.state['credentials']['grantExpiresAt'],expiry)
        self.assertEqual(api.issued,2)

    def test_logout_during_lost_or_late_rebind_keeps_only_exact_revoke_and_public_certificates(self):
        for lost in (True,False):
            with self.subTest(lost=lost):
                path=self.root/('lost' if lost else 'late');client.initialize(path,'해제 경합',sorted(item.value for item in codec.Scope))
                with client.Profile(path) as profile:
                    api=RenewalAPI(profile)
                    with patch.object(client,'transport',api),patch.object(client,'wait_for_poll'),contextlib.redirect_stdout(io.StringIO()):client.connect(profile,self.args)
                    if lost:api.lost='CREDENTIAL_REBIND'
                    else:api.after_rebind=lambda:client.request_logout(path)
                    with patch.object(client,'transport',api),patch.object(client,'wait_for_poll'):
                        with self.assertRaises(client.ClientError):client.connect(profile,self.args)
                    if lost:client.lock_account(profile)
                    self.assertNotIn('credentials',profile.state);self.assertNotIn('renewal',profile.state)
                    self.assertEqual(len(profile.state['outbox']),1)
                    self.assertNotIn('recoveryCapability',json.dumps(profile.state['outbox']))
                    with patch.object(client,'transport',api):client.drain_revokes(profile)
                    self.assertEqual(profile.state['outbox'],[])

    def test_renewal_rejects_wrong_generation_operation_or_changed_same_grant_capability(self):
        for bad_field in ('generationOperationId','recoveryCapability','revokeCapability'):
            with self.subTest(field=bad_field):
                path=self.root/bad_field;client.initialize(path,'동일 grant 검사',sorted(item.value for item in codec.Scope))
                with client.Profile(path) as profile:
                    api=RenewalAPI(profile)
                    with patch.object(client,'transport',api),patch.object(client,'wait_for_poll'),contextlib.redirect_stdout(io.StringIO()):client.connect(profile,self.args)
                    previous=dict(profile.state['credentials'])
                    def bad(*args,**kwargs):
                        status,raw=api(*args,**kwargs);value=json.loads(raw)
                        if bad_field=='generationOperationId' and value.get('operation')=='CERTIFICATE_RENEW_CLAIM' and 'certificateReceipt' in value:
                            value['certificateReceipt']['generationOperationId']='f'*32
                        elif value.get('operation')=='CREDENTIAL_REBIND':
                            value['credentialReceipt'][bad_field]=client.encoded(b'z'*32)
                        return status,json.dumps(value).encode()
                    with patch.object(client,'transport',bad),patch.object(client,'wait_for_poll'):
                        with self.assertRaisesRegex(client.ClientError,'CERTIFICATE_GENERATION_MISMATCH|CREDENTIAL_REVISION_MISMATCH'):
                            client.connect(profile,self.args)
                    self.assertEqual(profile.state['credentials'],previous)
                    self.assertIn('renewal',profile.state)

    def test_expired_certificate_and_grant_use_same_key_one_phone_and_fresh_grant(self):
        key=(self.path/'identity.pem').read_bytes()
        with client.Profile(self.path) as profile:
            api=ReauthorizationAPI(profile)
            with patch.object(client,'transport',api),patch.object(client,'wait_for_poll'),contextlib.redirect_stdout(io.StringIO()):client.connect(profile,self.args)
            previous=dict(profile.state['credentials']);api.now+=8*86400;output=io.StringIO()
            with patch.object(client,'transport',api),patch.object(client,'wait_for_poll'),patch.object(client.time,'time',return_value=api.now),contextlib.redirect_stdout(output):
                self.assertEqual(client.connect(profile,self.args),{'status':'connected'})
            current=profile.state['credentials']
            self.assertNotEqual(current['grantId'],previous['grantId']);self.assertNotEqual(current['deviceId'],previous['deviceId'])
            self.assertEqual(current['accountId'],previous['accountId']);self.assertEqual(current['generation'],2)
            self.assertEqual(current['grantExpiresAt'],api.now+604800);self.assertEqual(profile.state['outbox'],[])
            self.assertEqual(api.approvals,1);self.assertEqual(len(output.getvalue().strip().splitlines()),1)
        self.assertEqual(key,(self.path/'identity.pem').read_bytes());self.assertEqual(api.issued,2)

    def test_live_certificate_expired_grant_reuses_leaf_after_one_new_phone(self):
        with client.Profile(self.path) as profile:
            api=ReauthorizationAPI(profile);api.certificate_lifetime=90*86400
            with patch.object(client,'transport',api),patch.object(client,'wait_for_poll'),contextlib.redirect_stdout(io.StringIO()):client.connect(profile,self.args)
            old=dict(profile.state['credentials']);api.now+=8*86400
            with patch.object(client,'transport',api),patch.object(client,'wait_for_poll'),patch.object(client.time,'time',return_value=api.now),contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(client.connect(profile,self.args),{'status':'connected'})
            self.assertNotEqual(profile.state['credentials']['grantId'],old['grantId'])
            self.assertEqual(profile.state['credentials']['certificateSha256'],old['certificateSha256'])
            self.assertEqual(api.issued,1);self.assertEqual(api.approvals,1)

    def test_expired_installation_explicit_ca_rejection_never_reissues_or_reactivates(self):
        with client.Profile(self.path) as profile:
            api=ReauthorizationAPI(profile)
            with patch.object(client,'transport',api),patch.object(client,'wait_for_poll'),contextlib.redirect_stdout(io.StringIO()):client.connect(profile,self.args)
            api.now+=8*86400;api.ca_active=False
            with patch.object(client,'transport',api),patch.object(client,'wait_for_poll'),patch.object(client.time,'time',return_value=api.now):
                with self.assertRaisesRegex(client.ClientError,'INSTALLATION_REVOKED'):client.connect(profile,self.args)
            self.assertNotIn('credentials',profile.state);self.assertEqual(api.issued,1);self.assertEqual(api.approvals,0)
            self.assertEqual(len(profile.state['outbox']),1)

    def test_public_reauthorization_loss_resumes_original_key_and_operation(self):
        for lost in ('CONNECTION_REAUTHORIZE','CONNECTION_CLAIM','SESSION_EXCHANGE'):
            with self.subTest(lost=lost):
                path=self.root/lost;client.initialize(path,'같은 키 재연결',sorted(item.value for item in codec.Scope))
                with client.Profile(path) as profile:
                    api=ReauthorizationAPI(profile)
                    with patch.object(client,'transport',api),patch.object(client,'wait_for_poll'),contextlib.redirect_stdout(io.StringIO()):client.connect(profile,self.args)
                    api.now+=8*86400;api.lost=lost
                    with patch.object(client,'transport',api),patch.object(client,'wait_for_poll'),patch.object(client.time,'time',return_value=api.now),contextlib.redirect_stdout(io.StringIO()):
                        with self.assertRaisesRegex(client.ClientError,'REQUEST_UNCONFIRMED'):client.connect(profile,self.args)
                    operation=profile.state['authorization']['request']['operationId']
                with client.Profile(path) as profile:
                    api.profile=profile
                    with patch.object(client,'transport',api),patch.object(client,'wait_for_poll'),patch.object(client.time,'time',return_value=api.now),contextlib.redirect_stdout(io.StringIO()):
                        self.assertEqual(client.connect(profile,self.args),{'status':'connected'})
                    self.assertEqual(api.approvals,1);self.assertEqual(api.issued,2)
                    for action,request in api.calls:
                        if action=='CONNECTION_REAUTHORIZE':self.assertEqual(request['operationId'],operation)

    def test_lost_exchange_logout_uses_precommitted_grant_revoke_without_device_id(self):
        with client.Profile(self.path) as profile:
            api=SyntheticAPI(profile);api.lost='SESSION_EXCHANGE'
            with patch.object(client,'transport',api),patch.object(client,'wait_for_poll'),contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaisesRegex(client.ClientError,'REQUEST_UNCONFIRMED'):client.connect(profile,self.args)
            self.assertNotIn('credentials',profile.state)
            approved=profile.state['authorization'];grant=approved['response']['grantId']
            capability=codec.derive_revoke_capability(approved['verifier'],profile.state['installationKeyId'],approved['request']['operationId'])
            self.assertEqual(codec.revoke_commitment(capability),approved['request']['revokeCommitment'])
            client.lock_account(profile)
            self.assertNotIn('authorization',profile.state);self.assertNotIn('credentials',profile.state)
            self.assertEqual(len(profile.state['outbox']),1)
            pending=profile.state['outbox'][0]
            self.assertNotIn('deviceId',pending);self.assertEqual(pending['action'],'GRANT_REVOKE')
            self.assertEqual(pending['request']['grantId'],grant)
            self.assertEqual(set(pending['request']),{'authorizationVersion','operationId','grantId','revokeCapability'})
            with patch.object(client,'transport',api):client.drain_revokes(profile)
            self.assertEqual(profile.state['outbox'],[])

    def test_missing_public_certificate_restores_exact_state_leaf_and_rejects_wrong_binding(self):
        api=self.connected();key=(self.path/'identity.pem').read_bytes()
        with client.Profile(self.path) as profile:
            receipt=profile.state['certificate'];target=self.path/('certificate-'+receipt['certificateSha256']+'.pem')
            original=target.read_bytes();target.unlink();credential=dict(profile.state['credentials'])
            client.tls_context(profile,True)
            self.assertEqual(target.read_bytes(),original);self.assertEqual(profile.state['credentials'],credential)
            self.assertEqual((self.path/'identity.pem').read_bytes(),key);self.assertEqual(api.issued,1)
            profile.state['certificate']=dict(receipt,certificateSha256='f'*64)
            wrong=self.path/('certificate-'+'f'*64+'.pem')
            with self.assertRaisesRegex(client.ClientError,'CERTIFICATE_BINDING_MISMATCH'):client.tls_context(profile,True)
            self.assertFalse(wrong.exists());self.assertEqual(target.read_bytes(),original)

    def test_one_flow_public_only_encrypted_state_and_remembered_resume(self):
        output = io.StringIO()
        with client.Profile(self.path) as profile:
            api = SyntheticAPI(profile)
            with patch.object(client, 'transport', api), patch.object(client, 'wait_for_poll'), contextlib.redirect_stdout(output):
                self.assertEqual(client.connect(profile, self.args), {'status': 'connected'})
            saved = dict(profile.state['credentials'])
            verifier = next(x[1]['codeVerifier'] for x in api.calls if x[0] == 'SESSION_EXCHANGE')
        public = json.loads(output.getvalue())
        self.assertEqual(set(public), {'status', 'userCode', 'verificationUri'})
        for secret in [verifier, saved['accessToken'], saved['refreshToken'], saved['recoveryCapability']]:
            self.assertNotIn(secret, output.getvalue())
            self.assertNotIn(secret.encode(), (self.path / 'state.enc').read_bytes())
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o700)
        for value in self.path.iterdir():
            self.assertEqual(stat.S_IMODE(value.stat().st_mode), 0o600)
        with client.Profile(self.path) as profile:
            api.profile = profile
            with patch.object(client, 'transport', api):
                self.assertEqual(client.connect(profile, self.args), {'status': 'connected'})
        self.assertEqual(api.issued, 1)
        self.assertEqual(sum(x[0] == 'CONNECTION_BEGIN' for x in api.calls), 1)
        self.assertEqual(sum(x[0] == 'SESSION_EXCHANGE' for x in api.calls), 1)

    def test_lost_begin_claim_and_exchange_keep_key_and_operation(self):
        for lost in ('CONNECTION_BEGIN', 'CONNECTION_CLAIM', 'SESSION_EXCHANGE'):
            with self.subTest(lost=lost):
                path = self.root / lost
                client.initialize(path, '응답 유실 시험', sorted(item.value for item in codec.Scope))
                key_bytes = (path / 'identity.pem').read_bytes()
                with client.Profile(path) as profile:
                    api = SyntheticAPI(profile)
                    api.lost = lost
                    with patch.object(client, 'transport', api), patch.object(client, 'wait_for_poll'), contextlib.redirect_stdout(io.StringIO()):
                        with self.assertRaises(client.ClientError):
                            client.connect(profile, self.args)
                    operation = profile.state['authorization']['request']['operationId']
                with client.Profile(path) as profile:
                    api.profile = profile
                    with patch.object(client, 'transport', api), patch.object(client, 'wait_for_poll'), contextlib.redirect_stdout(io.StringIO()):
                        self.assertEqual(client.connect(profile, self.args), {'status': 'connected'})
                self.assertEqual(key_bytes, (path / 'identity.pem').read_bytes())
                self.assertEqual(api.issued, 1)
                for action, request in api.calls:
                    if action != 'GET':
                        self.assertEqual(request['operationId'], operation)
                self.assertEqual(sum(x[0] == 'CONNECTION_CLAIM' for x in api.calls), 1)

    def test_offline_logout_locks_before_network_and_only_keeps_revoke_capability(self):
        self.connected()
        with client.Profile(self.path) as profile:
            old = profile.state['credentials']
            client.lock_account(profile)
            self.assertNotIn('credentials', profile.state)
            pending = profile.state['outbox'][0]
            wire = json.dumps(pending)
            for key in ('accessToken', 'refreshToken', 'recoveryCapability'):
                self.assertNotIn(old[key], wire)
            with patch.object(client, 'transport', side_effect=client.ClientError('CONNECTION_FAILED')):
                with self.assertRaises(client.ClientError):
                    client.drain_revokes(profile)
            self.assertEqual(profile.state['phase'], 'revoke_pending')
        with client.Profile(self.path) as profile:
            self.assertNotIn('credentials', profile.state)
            self.assertEqual(len(profile.state['outbox']), 1)

    def test_temporary_cold_start_revokes_before_new_phone_flow(self):
        api = self.connected(remember=False)
        with client.Profile(self.path) as profile:
            api.profile = profile
            self.args.wait = 0
            with patch.object(client, 'transport', side_effect=client.ClientError('OFFLINE')) as request:
                with self.assertRaises(client.ClientError):
                    client.connect(profile, self.args)
                self.assertEqual(request.call_args.args[2], '/v1/device-sessions/revoke')
            self.assertNotIn('credentials', profile.state)
            self.assertEqual(profile.state['phase'], 'revoke_pending')

    def test_lost_refresh_replays_exact_operation_without_new_phone_or_certificate(self):
        api = self.connected()
        with client.Profile(self.path) as profile:
            api.profile = profile
            api.lost = 'SESSION_REFRESH'
            with patch.object(client, 'transport', api):
                with self.assertRaises(client.ClientError):
                    client.credential_operation(profile, 'SESSION_REFRESH')
            request = dict(profile.state['pendingCredential']['request'])
        with client.Profile(self.path) as profile:
            api.profile = profile
            with patch.object(client, 'transport', api):
                self.assertEqual(client.connect(profile, self.args), {'status': 'connected'})
            self.assertEqual(profile.state['credentials']['credentialEpoch'], 2)
        refreshes = [x[1] for x in api.calls if x[0] == 'SESSION_REFRESH']
        self.assertEqual(refreshes, [request, request])
        self.assertEqual(api.issued, 1)

    def test_expiry_requires_explicit_restart_same_key(self):
        with client.Profile(self.path) as profile:
            api = SyntheticAPI(profile)
            self.args.wait = 0
            with patch.object(client, 'transport', api), contextlib.redirect_stdout(io.StringIO()):
                client.connect(profile, self.args)
            api.force_expired = True
            key = (self.path / 'identity.pem').read_bytes()
            with patch.object(client, 'transport', api), contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaisesRegex(client.ClientError, 'CODE_EXPIRED_RUN_CONNECT_RESTART'):
                    client.connect(profile, self.args)
            self.assertEqual(sum(x[0] == 'CONNECTION_RESTART' for x in api.calls), 0)
            self.args.restart = True
            with patch.object(client, 'transport', api), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(client.connect(profile, self.args), {'status': 'approval_pending'})
            self.assertEqual(sum(x[0] == 'CONNECTION_RESTART' for x in api.calls), 1)
            self.assertEqual(key, (self.path / 'identity.pem').read_bytes())
            self.assertEqual(api.issued, 0)

    def test_bad_receipt_never_installs_wrong_key(self):
        with client.Profile(self.path) as profile:
            api = SyntheticAPI(profile)
            original = api.__call__
            def bad(*args, **kwargs):
                status, raw = original(*args, **kwargs)
                value = json.loads(raw)
                if 'certificateReceipt' in value:
                    value['certificateReceipt']['installationKeyId'] = 'f' * 64
                return status, json.dumps(value).encode()
            with patch.object(client, 'transport', bad), patch.object(client, 'wait_for_poll'), contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaises(codec.CodecError):
                    client.connect(profile, self.args)
            self.assertEqual(api.issued, 1)
            self.assertNotIn('credentials', profile.state)
            self.assertNotIn('certificate', profile.state)
            self.assertEqual(list(self.path.glob('certificate-*.pem')), [])

    def test_existing_data_symlinks_lock_and_damaged_state_are_preserved(self):
        key = (self.path / 'identity.pem').read_bytes()
        with self.assertRaises(FileExistsError):
            client.initialize(self.path, 'existing', sorted(item.value for item in codec.Scope))
        self.assertEqual(key, (self.path / 'identity.pem').read_bytes())
        linked = self.root / 'linked'
        linked.symlink_to(self.path)
        with self.assertRaises(client.ClientError):
            with client.Profile(linked):
                pass
        with client.Profile(self.path):
            with self.assertRaises(BlockingIOError):
                with client.Profile(self.path):
                    pass
        raw = (self.path / 'state.enc').read_bytes()
        (self.path / 'state.enc').write_bytes(raw[:-1] + bytes([raw[-1] ^ 1]))
        damaged = (self.path / 'state.enc').read_bytes()
        with self.assertRaisesRegex(client.ClientError, 'LOCAL_STATE_DAMAGED'):
            with client.Profile(self.path):
                pass
        self.assertEqual(damaged, (self.path / 'state.enc').read_bytes())
        self.assertEqual(key, (self.path / 'identity.pem').read_bytes())

    def test_actual_tls13_default_hostname_and_mutual_certificate_transport(self):
        with client.Profile(self.path) as profile:
            api = SyntheticAPI(profile)
            server_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
            ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'Synthetic CA')])
            now = datetime.now(timezone.utc)
            ca_cert = (x509.CertificateBuilder().subject_name(ca_name).issuer_name(ca_name)
                .public_key(api.ca.public_key()).serial_number(20).not_valid_before(now-timedelta(minutes=1))
                .not_valid_after(now+timedelta(days=1)).add_extension(x509.BasicConstraints(ca=True,path_length=None), True)
                .sign(api.ca, hashes.SHA256()))
            names = [x509.DNSName('enroll-wegoh.devforest.io'), x509.DNSName('api-wegoh.devforest.io')]
            server_cert = (x509.CertificateBuilder().subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'synthetic')]))
                .issuer_name(ca_name).public_key(server_key.public_key()).serial_number(21)
                .not_valid_before(now-timedelta(minutes=1)).not_valid_after(now+timedelta(days=1))
                .add_extension(x509.SubjectAlternativeName(names), False)
                .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), False)
                .sign(api.ca, hashes.SHA256()))
            ca_path, cert_path, key_path = [self.root / item for item in ('ca.pem','server.pem','server.key')]
            for path, raw in [(ca_path, ca_cert.public_bytes(serialization.Encoding.PEM)),
                (cert_path, server_cert.public_bytes(serialization.Encoding.PEM)),
                (key_path, server_key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))]:
                client.exclusive(path, raw)
            observations = []
            class Handler(http.server.BaseHTTPRequestHandler):
                def log_message(self, *_):
                    pass
                def do_POST(self):
                    self.handle_api('POST')
                def do_GET(self):
                    self.handle_api('GET')
                def handle_api(self, method):
                    raw = self.rfile.read(int(self.headers.get('Content-Length', 0)))
                    host = 'enroll' if self.path.startswith('/v1/connections') else 'native'
                    peer = bool(self.connection.getpeercert())
                    observations.append((self.connection.version(), host, peer))
                    if host == 'native' and not peer:
                        self.send_error(403)
                        return
                    record = None
                    if raw:
                        values = codec.decode_json(raw)
                        action = next(name for name, item in client.OPERATIONS.items()
                            if item['host']==host and item['path'].replace('{connectionId}',api.connection_id)==self.path)
                        record = codec.decode_request(action, values)
                    access = self.headers.get('Authorization', '').removeprefix('Bearer ') or None
                    status, response = api(profile, host, self.path, method, record, access)
                    self.send_response(status)
                    self.send_header('Content-Type','application/json')
                    self.send_header('Content-Length',str(len(response)))
                    self.end_headers()
                    self.wfile.write(response)
            server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
            server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            server_context.minimum_version = server_context.maximum_version = ssl.TLSVersion.TLSv1_3
            server_context.load_cert_chain(str(cert_path), str(key_path))
            server_context.load_verify_locations(cafile=str(ca_path))
            server_context.verify_mode = ssl.CERT_OPTIONAL
            server.socket = server_context.wrap_socket(server.socket, server_side=True)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            original_connect = socket.create_connection
            original_context = ssl.create_default_context
            def connect(address, *args, **kwargs):
                return original_connect(('127.0.0.1', server.server_port), *args, **kwargs)
            def trusted_context(*args, **kwargs):
                return original_context(cafile=str(ca_path))
            try:
                with patch.object(socket, 'create_connection', connect), patch.object(client.ssl,'create_default_context',trusted_context), patch.object(client,'wait_for_poll'), contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(client.connect(profile,self.args), {'status':'connected'})
                self.assertTrue(any(host=='enroll' and not peer for _,host,peer in observations))
                self.assertTrue(any(host=='native' and peer for _,host,peer in observations))
                self.assertEqual({version for version,_,_ in observations},{'TLSv1.3'})
            finally:
                server.shutdown()
                server.server_close()
                thread.join(2)

    def test_concurrent_logout_is_durable_before_network_lock_and_delayed_receipt(self):
        api = self.connected()
        with client.Profile(self.path) as profile:
            api.profile = profile
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(client.main(['--directory', str(self.path), 'logout']), 0)
            self.assertEqual(json.loads(output.getvalue()), {'status':'locked','remoteRevocation':'pending'})
            self.assertTrue((self.path / 'logout.request').exists())
            with self.assertRaisesRegex(client.ClientError, 'LOCAL_LOCKED_REMOTE_REVOCATION_PENDING'):
                client.ensure_unlocked(profile)
            self.assertNotIn('credentials', profile.state)
            self.assertEqual(len(profile.state['outbox']), 1)
            self.assertFalse((self.path / 'logout.request').exists())

    def test_logout_during_exchange_never_stores_or_returns_new_personal_credential(self):
        with client.Profile(self.path) as profile:
            api = SyntheticAPI(profile)
            original = api.__call__
            def concurrent(*args, **kwargs):
                status, raw = original(*args, **kwargs)
                if json.loads(raw).get('operation') == 'SESSION_EXCHANGE':
                    client.request_logout(self.path)
                return status, raw
            with patch.object(client,'transport',concurrent), patch.object(client,'wait_for_poll'), contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaisesRegex(client.ClientError, 'LOCAL_LOCKED_REMOTE_REVOCATION_PENDING'):
                    client.connect(profile,self.args)
            self.assertNotIn('credentials',profile.state)
            self.assertEqual(profile.state['outbox'][0]['deviceId'],api.device_id)
            self.assertNotIn(api.credential['accessToken'],json.dumps(profile.state))

    def test_actual_account_shape_rejects_root_id_impostor(self):
        api = self.connected()
        original = api.__call__
        def wrong_shape(*args,**kwargs):
            if args[2] == '/v1/account':
                return 200,json.dumps(dict(id=api.account_id,deviceId=api.device_id)).encode()
            return original(*args,**kwargs)
        with client.Profile(self.path) as profile:
            api.profile=profile
            with patch.object(client,'transport',wrong_shape):
                with self.assertRaisesRegex(client.ClientError,'ACCOUNT_NOT_CONFIRMED'):
                    client.check_account(profile)

    def test_existing_identity_preserves_every_original_byte_without_old_authority(self):
        path = self.root/'previous'
        path.mkdir(mode=0o700)
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'WegoH personal native client')])
        csr = x509.CertificateSigningRequestBuilder().subject_name(subject).sign(key, hashes.SHA256())
        ca = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        now = datetime.now(timezone.utc)
        cert = (x509.CertificateBuilder().subject_name(subject)
            .issuer_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'Synthetic previous CA')]))
            .public_key(key.public_key()).serial_number(30).not_valid_before(now-timedelta(minutes=1))
            .not_valid_after(now+timedelta(days=1))
            .add_extension(x509.BasicConstraints(ca=False,path_length=None),True)
            .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.CLIENT_AUTH]),False)
            .sign(ca,hashes.SHA256()))
        for name,data in {'client.key.pem':key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()),
            'client.csr.pem':csr.public_bytes(serialization.Encoding.PEM),'client.crt.pem':cert.public_bytes(serialization.Encoding.PEM),'lock':b''}.items():
            client.exclusive(path/name,data)
        old_access=client.encoded(b'a'*32)
        old_state=dict(version=1,phase='authenticated',origin=client.CONTRACT['origins']['native'],
            certificateSha256=cert.fingerprint(hashes.SHA256()).hex(),deviceId='d'*32,
            credentials=dict(accessToken=old_access,refreshToken=client.encoded(b'r'*32)))
        client.exclusive(path/'state.json',json.dumps(old_state).encode())
        originals={p.name:p.read_bytes() for p in path.iterdir()}
        client.prepare_existing_identity(path)
        client.prepare_existing_identity(path)
        for name,raw in originals.items():self.assertEqual((path/name).read_bytes(),raw)
        with client.Profile(path) as profile:
            self.assertEqual(profile.identity_file,'client.key.pem')
            self.assertEqual(client.public_bytes(profile.key.public_key()),client.public_bytes(key.public_key()))
            self.assertNotIn('credentials',profile.state)
            self.assertNotIn(old_access,json.dumps(profile.state))
            client.new_authorization(profile)
            self.assertEqual(profile.state['authorization']['action'],'ACCOUNT_AUTHORIZE')
            self.assertEqual(profile.state['authorization']['request']['authorizationVersion'],1)
            self.assertNotIn('legacyDeviceId',profile.state['authorization']['request'])

    def test_optional_scope_reduction_recovers_same_grant_without_phone_or_new_cert(self):
        api=self.connected()
        required=sorted(item.value for item in codec.REQUIRED_SCOPES)
        original=api.__call__
        stale=True
        def reduced(profile,host,path,method='POST',body=None,access=None):
            nonlocal stale
            if path=='/v1/account' and stale:
                return 401,b'{"detail":"INVALID_CREDENTIAL"}'
            if path=='/v1/device-sessions/recover':
                stale=False
                api.scopes=required
                api.credential.update(scopes=required,consentVersion=2)
            status,raw=original(profile,host,path,method,body,access)
            if path=='/v1/device/permissions':
                value=json.loads(raw);value['consentVersion']=2;raw=json.dumps(value).encode()
            return status,raw
        with client.Profile(self.path) as profile:
            api.profile=profile
            before=dict(profile.state['credentials'])
            with patch.object(client,'transport',reduced):
                self.assertEqual(client.connect(profile,self.args),{'status':'connected'})
            receipt=profile.state['credentials']
            for field in ('grantId','deviceId','accountId','grantExpiresAt','slotRevision'):
                self.assertEqual(receipt[field],before[field])
            self.assertEqual(receipt['scopes'],required)
            self.assertEqual(receipt['consentVersion'],2)
            self.assertEqual(api.issued,1)
            self.assertEqual(sum(call[0]=='CONNECTION_BEGIN' for call in api.calls),1)

    def test_recovery_never_accepts_broader_scope_or_reactivates_required_revocation(self):
        api=self.connected()
        with client.Profile(self.path) as profile:
            api.profile=profile
            profile.state['credentials']['scopes']=sorted(item.value for item in codec.REQUIRED_SCOPES)
            profile.save()
            with patch.object(client,'transport',api):
                with self.assertRaisesRegex(client.ClientError,'CREDENTIAL_REVISION_MISMATCH'):
                    client.credential_operation(profile,'SESSION_RECOVER')
            self.assertEqual(profile.state['credentials']['scopes'],sorted(item.value for item in codec.REQUIRED_SCOPES))
        with client.Profile(self.path) as profile:
            def revoked(*args,**kwargs):
                return 403,b'{"detail":"CONSENT_REVOKED"}'
            with patch.object(client,'transport',side_effect=revoked) as network:
                with self.assertRaisesRegex(client.ClientError,'CONSENT_REVOKED'):
                    client.check_with_recovery(profile)
                self.assertEqual(network.call_count,1)
            self.assertNotIn('credentials',profile.state)

    def test_permission_snapshot_rejects_bool_counters_and_non_string_scope(self):
        api=self.connected()
        original=api.__call__
        for field,bad in [('consentVersion',True),('grantExpiresAt',True),('scopes',[True])]:
            def malformed(*args,**kwargs):
                status,raw=original(*args,**kwargs)
                if args[2]=='/v1/device/permissions':
                    value=json.loads(raw);value[field]=bad;raw=json.dumps(value).encode()
                return status,raw
            with self.subTest(field=field),client.Profile(self.path) as profile:
                api.profile=profile
                with patch.object(client,'transport',malformed):
                    with self.assertRaisesRegex(client.ClientError,'CONSENT_NOT_CONFIRMED'):
                        client.check_account(profile)

    def test_old_manual_public_commands_cannot_create_keys_or_requests(self):
        for command in ('init','pair','token','refresh','revoke'):
            with self.subTest(command=command),patch.object(client,'initialize') as initialize,patch.object(client,'transport') as transport,contextlib.redirect_stderr(io.StringIO()) as output:
                self.assertEqual(client.main([command]),1)
                self.assertEqual(json.loads(output.getvalue())['error'],'INVALID_ARGUMENTS')
                initialize.assert_not_called()
                transport.assert_not_called()

    def test_runtime_fails_before_bootstrap_or_key_for_apple_python(self):
        for values, expected in [({'version_info': (3, 9, 6)}, 'PYTHON_312_REQUIRED'),
                                 ({'HAS_TLSv1_3': False}, 'TLS13_UNAVAILABLE')]:
            with self.subTest(expected=expected), contextlib.redirect_stderr(io.StringIO()) as output:
                target = bootstrap.sys if 'version_info' in values else bootstrap.ssl
                with patch.multiple(target, **values), patch.object(bootstrap, 'bootstrap') as install:
                    self.assertEqual(bootstrap.main(['connect']), 1)
                    install.assert_not_called()
                self.assertEqual(json.loads(output.getvalue())['error'], expected)


if __name__ == '__main__':
    unittest.main()
