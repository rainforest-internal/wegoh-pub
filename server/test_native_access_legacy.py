"""Retired credentials remain inert; known same-key leaf needs fresh public1 consent.
Synthetic certificate inventory/private PG only. No retired API creates a fixture.
"""
import secrets,unittest
import psycopg
from cryptography import x509
from enrollment_crypto import challenge,digest,public_bytes
from native_authorization import protect,hash_secret
from native_access_codec import derive_revoke_capability
from private_records import VisitCipher
from team_auth import hashed
import test_native_authorization_http as http_fixture
from test_enrollment import make_csr

class LegacyMigrationTests(http_fixture.NativeAuthorizationHttpTests):
    def old_device(self,who,session,*,same_key=False):
        key,csr=make_csr(self.key if same_key else None,cn="Owned legacy developer")
        provider=self.issuer.response(x509.load_pem_x509_csr(csr.encode()))
        pem=provider["certificate"];fingerprint=provider["fingerprint_sha256"]
        installation=digest(public_bytes(key.public_key()));cert=x509.load_pem_x509_certificate(pem.encode())
        expires=int(cert.not_valid_after_utc.timestamp());identifier=secrets.token_hex(16);token=secrets.token_urlsafe(32)
        owner=session['user']['id']
        provenance=dict(source="authenticated-cloudflare-api",certificatePem=pem,certificateSha256=fingerprint,
            installationKeyId=installation,issuerId=provider["certificate_authority"]["id"],certificateId=provider["id"])
        saved=dict(name="Legacy "+who,nativeReadPermissions=dict(friends=False,rooms=False,history=False),nativePermissionRevision=1,
            certificateSha256=fingerprint,installationKeyId=installation)
        with psycopg.connect(self.auth.dsn) as conn:
            conn.execute("INSERT INTO native_v2_legacy_certificates(certificate_sha256,installation_key_id,expires_at,protected_provenance) "
                "VALUES(%s,%s,%s,%s)",(fingerprint,installation,expires,protect("legacy-certificate",fingerprint,provenance)))
            conn.execute("INSERT INTO team_devices(device_id,account_id,protected,access_hash,access_expires_at,refresh_hash,expires_at) "
                "VALUES(%s,%s,%s,%s,now()+interval '1 hour',%s,now()+interval '7 days')",
                (identifier,owner,VisitCipher().protect('team-device:'+owner,identifier,saved),hashed(token),hashed(secrets.token_urlsafe(32))))
        return dict(key=key,certificate=pem,fingerprint=fingerprint,installation=installation,device=identifier,token=token)

    def old_rows(self):
        with psycopg.connect(self.auth.dsn) as conn:
            return conn.execute('SELECT row_to_json(t)::text FROM team_devices t ORDER BY device_id').fetchall()

    def begin_authorization(self,old):
        self.fingerprint=old["fingerprint"]
        body=dict(authorizationVersion=1,operationId=secrets.token_hex(16),name="Fresh same key",
            certificatePem=old["certificate"],codeChallenge=self.challenge,requestedScopes=self.scopes)
        body["revokeCommitment"]=hash_secret("revoke",derive_revoke_capability(self.verifier,old["installation"],body["operationId"]))
        return body

    def test_10_known_generic_leaf_requires_fresh_public1_consent_preserves_retired_cipher(self):
        old=self.old_device("alice",self.session,same_key=True)
        other=self.old_device("bob",self.api.login("bob"));before=self.old_rows();body=self.begin_authorization(old)
        self.assertEqual(self.native('/v1/account',token=old['token'])[0],401)
        status,_,pending=self.native('/v1/device-authorizations',body,'POST');self.assertEqual(status,201,pending)
        self.assertNotIn('certificateReceipt',pending);self.assertNotIn('proofNonce',pending)
        path='/v1/connections/'+pending['userCode'];status,_,detail=self.api.call(path,session=self.session);self.assertEqual(status,200,detail)
        approval=dict(authorizationVersion=1,consentVersion=detail['consentVersion'],approvedScopes=self.scopes,keepSignedIn=False,
            disclosureVersion=2,disclosureSha256=detail['disclosureSnapshot']['disclosureSha256'])
        self.assertEqual(self.api.call(path,approval,'POST',session=self.session)[0],200)
        self.assertEqual(self.api.call(path,approval,'POST',session=self.api.login('bob'),who='bob')[0],409)
        status,_,approved=self.native('/v1/device-authorizations',body,'POST');self.assertEqual(status,200,approved)
        status,_,connected=self.native('/v1/device-sessions/exchange',dict(authorizationVersion=1,operationId=secrets.token_hex(16),
            grantId=approved['grantId'],codeVerifier=self.verifier),'POST');self.assertEqual(status,200,connected)
        receipt=connected['credentialReceipt'];self.assertEqual(receipt['installationKeyId'],old['installation'])
        self.assertEqual(receipt['certificateSha256'],old['fingerprint']);self.assertEqual(receipt['generation'],1)
        self.assertEqual(self.native('/v1/account',token=receipt['accessToken'])[0],200)
        self.assertEqual(self.native('/v1/account',token=old['token'])[0],401)
        self.assertEqual(self.api.native('/v1/account',token=other['token'],certificate=other['fingerprint'])[0],401)
        self.assertEqual(self.old_rows(),before);self.assertEqual(self.issuer.calls,0)

    def test_11_retired_identity_or_bearer_cannot_create_personal_grant(self):
        old=self.old_device('alice',self.session,same_key=True);before=self.old_rows();body=self.begin_authorization(old)
        self.assertEqual(self.native('/v1/device-authorizations',dict(body,legacyDeviceId=old['device']),'POST')[0],400)
        self.assertEqual(self.native('/v1/device-authorizations',body,'POST',token=old['token'])[0],400)
        for path in ['/v1/devices/pairings','/v1/devices/token','/v2/device-authorizations','/v2/device-sessions/exchange']:
            self.assertEqual(self.native(path,body,'POST')[0],404)
        with psycopg.connect(self.auth.dsn) as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM native_v2_grants').fetchone()[0],0)
        self.assertEqual(self.old_rows(),before);self.assertEqual(self.issuer.calls,0)

if __name__=="__main__":unittest.main()
