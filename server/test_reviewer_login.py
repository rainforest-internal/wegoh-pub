"""Reviewer instant login under /reviewer: real HTTP, isolated PostgreSQL and synthetic Access."""
import os
import secrets
import unittest
from unittest import mock

import psycopg

import test_team_auth as fixture
from reviewer_login import reviewer_email

DOMAINS = {'WEGOH_REVIEWER_EMAIL_DOMAINS': 'reviewer.example'}
EMAIL = 'review-check@reviewer.example'


class ReviewerEmailTests(unittest.TestCase):
    def test_exact_domain_and_rfc_local_part(self):
        with mock.patch.dict(os.environ, DOMAINS):
            self.assertEqual(reviewer_email('Review.Check+1@Reviewer.EXAMPLE'), 'review.check+1@reviewer.example')
            for value in ('a@mail.reviewer.example', 'a@reviewer.example.invalid', 'a@example.invalid',
                          'a..b@reviewer.example', '.a@reviewer.example', 'a.@reviewer.example',
                          '"a"@reviewer.example', 'a b@reviewer.example', 'a@b@reviewer.example',
                          '@reviewer.example', 'x' * 65 + '@reviewer.example', None, 3):
                with self.subTest(value=value):
                    self.assertIsNone(reviewer_email(value))
        with mock.patch.dict(os.environ, {'WEGOH_REVIEWER_EMAIL_DOMAINS': ''}):
            self.assertIsNone(reviewer_email(EMAIL))


class ReviewerLoginTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixture.TeamTests.setUpClass()

    @classmethod
    def tearDownClass(cls):
        fixture.TeamTests.tearDownClass()

    def setUp(self):
        self.api = fixture.TeamTests('test_01_jwt_verification_and_exact_hosts')
        self.api.setUp()
        patcher = mock.patch.dict(os.environ, DOMAINS)
        patcher.start()
        self.addCleanup(patcher.stop)

    def call(self, path, data=None, method='GET', *, session=None, origin=fixture.WEB, **options):
        return self.api.call(path, data, method, who=None, session=session, origin=origin, **options)

    def login(self, email=EMAIL):
        status, headers, value = self.call('/reviewer/v1/login', {'email': email}, 'POST')
        self.assertEqual(status, 200, value)
        cookie = next(v for k, v in headers.items() if k.lower() == 'set-cookie')
        for attribute in ('HttpOnly', 'Secure', 'SameSite=strict', 'Path=/reviewer', 'Max-Age=604800'):
            self.assertIn(attribute, cookie)
        value['cookie'] = cookie.split(';', 1)[0]
        return value

    def pending(self):
        from test_enrollment import SyntheticIssuer, make_csr
        from enrollment_crypto import challenge
        from native_access_codec import derive_revoke_capability, revoke_commitment
        from enrollment_crypto import validate_csr, public_bytes, digest
        _, csr = make_csr()
        key_id = digest(public_bytes(validate_csr(csr).public_key()))
        verifier, operation = secrets.token_urlsafe(32), secrets.token_hex(16)
        service = self.api.module.TEAM_NATIVE_AUTHORIZATION
        previous, service.issuer = service.issuer, SyntheticIssuer()
        try:
            return service.begin(dict(authorizationVersion=1, operationId=operation, name='Synthetic vehicle', csrPem=csr,
                codeChallenge=challenge(verifier), requestedScopes=sorted(['account:read', 'device:self:manage', 'courses:read']),
                revokeCommitment=revoke_commitment(derive_revoke_capability(verifier, key_id, operation))))[1]
        finally:
            service.issuer = previous

    def approval(self, detail):
        return dict(authorizationVersion=1, consentVersion=detail['consentVersion'], approvedScopes=detail['requestedScopes'],
                    keepSignedIn=False, disclosureVersion=detail['disclosureSnapshot']['disclosureVersion'],
                    disclosureSha256=detail['disclosureSnapshot']['disclosureSha256'])

    def test_allowed_domain_signs_in_and_approves_vehicle_connection(self):
        session = self.login('Review-Check@Reviewer.EXAMPLE')
        self.assertEqual(session['user'], {'displayName': 'WegoH 심사자', 'role': 'creator'})
        status, _, current = self.call('/reviewer/v1/session', session=session)
        self.assertEqual((status, current['authenticated'], current['csrfToken']), (200, True, session['csrfToken']))
        self.assertEqual(self.login()['user'], session['user'])
        with psycopg.connect(self.api.dsn) as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM team_accounts').fetchone(), (1,))
        code = self.pending()['userCode']
        status, _, detail = self.call('/reviewer/v1/connections/' + code, session=session)
        self.assertEqual((status, detail['state']), (200, 'PENDING'), detail)
        status, _, result = self.call('/reviewer/v1/connections/' + code, self.approval(detail), 'POST', session=session)
        self.assertEqual((status, result['state']), (200, 'APPROVED'), result)
        status, _, result = self.call('/reviewer/v1/connections/' + code, {'authorizationVersion': 1}, 'DELETE', session=session)
        self.assertEqual((status, result['state']), (200, 'DENIED'), result)

    def test_enrollment_process_claims_after_reviewer_approval(self):
        # The vehicle claim runs in the enrollment process (enrollment_only TeamAuth).
        import base64
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import padding
        from test_enrollment import SyntheticIssuer, make_csr
        from enrollment_crypto import challenge, validate_csr, public_bytes, digest
        from native_access_codec import derive_revoke_capability, revoke_commitment, decode_request, proof_transcript
        session = self.login()
        key, csr = make_csr()
        key_id = digest(public_bytes(validate_csr(csr).public_key()))
        verifier, operation = secrets.token_urlsafe(32), secrets.token_hex(16)
        service = self.api.module.TEAM_NATIVE_AUTHORIZATION
        previous, service.issuer = service.issuer, SyntheticIssuer()
        self.addCleanup(setattr, service, 'issuer', previous)
        pending = service.begin(dict(authorizationVersion=1, operationId=operation, name='Synthetic vehicle', csrPem=csr,
            codeChallenge=challenge(verifier), requestedScopes=sorted(['account:read', 'device:self:manage', 'courses:read']),
            revokeCommitment=revoke_commitment(derive_revoke_capability(verifier, key_id, operation))))[1]
        status, _, detail = self.call('/reviewer/v1/connections/' + pending['userCode'], session=session)
        self.assertEqual(status, 200, detail)
        status, _, result = self.call('/reviewer/v1/connections/' + pending['userCode'], self.approval(detail), 'POST', session=session)
        self.assertEqual((status, result['state']), (200, 'APPROVED'), result)
        claim = dict(authorizationVersion=1, operationId=secrets.token_hex(16), codeVerifier=verifier,
                     proofNonce=pending['proofNonce'], proof=base64.urlsafe_b64encode(bytes(256)).rstrip(b'=').decode())
        transcript = proof_transcript('CONNECTION_CLAIM', decode_request('CONNECTION_CLAIM', claim), installation_key_id=key_id,
                                      code_challenge=challenge(verifier), connection_id=pending['connectionId'])
        claim['proof'] = base64.urlsafe_b64encode(key.sign(transcript, padding.PKCS1v15(), hashes.SHA256())).rstrip(b'=').decode()
        with mock.patch.object(service.auth, 'enrollment_only', True):
            status, issued = service.claim(pending['connectionId'], claim)
        self.assertEqual((status, issued['state']), (200, 'ISSUED'), issued)

    def test_connected_reviewer_passes_native_functional_identity(self):
        # After connection, every vehicle feature revalidates the owner (native_functional_identity).
        from psycopg.rows import dict_row
        import native_functional_identity as identity
        self.login()
        with psycopg.connect(self.api.dsn, row_factory=dict_row) as conn, conn.cursor() as cursor:
            account = cursor.execute('SELECT account_id FROM team_accounts').fetchone()['account_id']
            saved = identity._current_account(self.api.module.TEAM_AUTH, cursor, account)
        self.assertTrue(saved['email'].endswith('@reviewer.example'))
        with mock.patch.dict(os.environ, {'WEGOH_REVIEWER_EMAIL_DOMAINS': ''}):
            with psycopg.connect(self.api.dsn, row_factory=dict_row) as conn, conn.cursor() as cursor:
                with self.assertRaises(identity.FunctionalError):
                    identity._current_account(self.api.module.TEAM_AUTH, cursor, account)

    def test_other_domains_subdomains_and_roster_are_rejected(self):
        for email in ('a@example.invalid', 'a@mail.reviewer.example', 'a@reviewer.example.invalid', 'a..b@reviewer.example'):
            with self.subTest(email=email):
                self.assertEqual(self.call('/reviewer/v1/login', {'email': email}, 'POST')[0], 403)
        self.assertEqual(self.call('/reviewer/v1/login', {'email': EMAIL, 'role': 'admin'}, 'POST')[0], 400)
        self.api.write_members(self.api.members_rows + [dict(email=EMAIL, name='member', role='admin')])
        self.assertEqual(self.call('/reviewer/v1/login', {'email': EMAIL}, 'POST')[0], 403)
        with psycopg.connect(self.api.dsn) as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM team_accounts').fetchone(), (0,))

    def test_missing_forged_and_expired_cookies_are_rejected(self):
        session = self.login()
        code = self.pending()['userCode']
        self.assertEqual(self.call('/reviewer/v1/connections/' + code)[0], 401)
        value = session['cookie'].split('=', 1)[1]
        prefix, account, expires, signature = value.split('.')
        other = 'team-' + 'a' * 40
        for forged in ('.'.join((prefix, account, expires, '0' * 64)), '.'.join((prefix, other, expires, signature)),
                       '.'.join((prefix, account, str(int(expires) + 1), signature)), 'garbage'):
            with self.subTest(forged=forged[:20]):
                status = self.call('/reviewer/v1/connections/' + code, session=dict(session, cookie='__Secure-wegoh_reviewer=' + forged))[0]
                self.assertEqual(status, 401)
        reviewer = self.api.module.TEAM_AUTH.reviewer
        expired = reviewer.token(account, 1000000000)
        self.assertEqual(self.call('/reviewer/v1/connections/' + code,
                                   session=dict(session, cookie='__Secure-wegoh_reviewer=' + expired))[0], 401)
        self.assertFalse(self.call('/reviewer/v1/session', session=dict(session, cookie='__Secure-wegoh_reviewer=' + expired))[2]['authenticated'])

    def test_cookie_reaches_nothing_outside_reviewer_and_cannot_deploy(self):
        session = self.login()
        code = self.pending()['userCode']
        for path, method in (('/v1/connections/' + code, 'GET'), ('/v1/devices', 'GET'), ('/v1/auth/session', 'GET'),
                             ('/v1/operations/deployment', 'GET'), ('/api-docs', 'GET'), ('/reviewer.html', 'GET')):
            with self.subTest(path=path):
                self.assertEqual(self.call(path, method=method, session=session)[0], 401)
        for path, method in (('/reviewer/v1/devices', 'GET'), ('/reviewer/v1/auth/session', 'POST'),
                             ('/reviewer/assets/team_auth.py', 'GET'), ('/reviewer/assets/', 'GET'), ('/reviewerx', 'GET')):
            with self.subTest(path=path):
                self.assertIn(self.call(path, method=method, session=session)[0], (401, 404))
        from fastapi import HTTPException
        auth = self.api.module.TEAM_AUTH
        account = auth.reviewer.account_id(EMAIL)[0]
        with self.assertRaises(HTTPException) as error:
            auth.current_account(account, require_roster=True)
        self.assertEqual(error.exception.status_code, 403)

    def test_access_identity_with_same_email_is_a_separate_account(self):
        session = self.login()
        token = self.api.assertion('reviewer', type='app', email=EMAIL)
        access = self.api.login(assertion=token)
        auth = self.api.module.TEAM_AUTH
        self.assertNotEqual(access['user']['id'], auth.reviewer.account_id(EMAIL)[0])
        self.assertEqual(self.login()['user'], session['user'])

    def test_origin_and_csrf_are_required_for_mutations(self):
        self.assertEqual(self.call('/reviewer/v1/login', {'email': EMAIL}, 'POST', origin='https://evil.invalid')[0], 403)
        self.assertEqual(self.call('/reviewer/v1/login', {'email': EMAIL}, 'POST', origin=None)[0], 403)
        session = self.login()
        code = self.pending()['userCode']
        detail = self.call('/reviewer/v1/connections/' + code, session=session)[2]
        approval = self.approval(detail)
        self.assertEqual(self.call('/reviewer/v1/connections/' + code, approval, 'POST', session=session, origin='https://evil.invalid')[0], 403)
        self.assertEqual(self.call('/reviewer/v1/connections/' + code, approval, 'POST', session=session, csrf=False)[0], 403)
        self.assertEqual(self.call('/reviewer/v1/connections/' + code, approval, 'POST',
                                   session=dict(session, csrfToken='0' * 64))[0], 403)
        self.assertEqual(self.call('/reviewer/v1/connections/' + code, session=session)[2]['state'], 'PENDING')

    def test_login_is_rate_limited_per_address(self):
        for _ in range(10):
            self.assertEqual(self.call('/reviewer/v1/login', {'email': EMAIL}, 'POST')[0], 200)
        status, headers, _ = self.call('/reviewer/v1/login', {'email': EMAIL}, 'POST')
        self.assertEqual((status, headers.get('retry-after') or headers.get('Retry-After')), (429, '60'))

    def test_page_assets_and_disabled_domain(self):
        status, headers, body = self.call('/reviewer', origin=None)
        self.assertEqual(status, 200)
        self.assertIn(b'/reviewer/assets/reviewer.js', body)
        for name in ('reviewer.js', 'pleos-tokens.css', 'studio.css', 'enroll.css', 'native-access-wire.json'):
            with self.subTest(name=name):
                self.assertEqual(self.call('/reviewer/assets/' + name, origin=None)[0], 200)
        with mock.patch.dict(os.environ, {'WEGOH_REVIEWER_EMAIL_DOMAINS': ''}):
            self.assertEqual(self.call('/reviewer', origin=None)[0], 404)
            self.assertEqual(self.call('/reviewer/v1/login', {'email': EMAIL}, 'POST')[0], 404)

    def test_every_mounted_reviewer_route_is_documented(self):
        from team_api_docs import build_schema
        from api_doc_reviewer import OPS, mounted_reviewer_operations
        module = self.api.module
        self.assertEqual(mounted_reviewer_operations(module.app), set(OPS))
        schema = build_schema(module.app, module.TEAM_AUTH)
        for method, path in OPS:
            with self.subTest(path=path, method=method):
                self.assertEqual(schema['paths'][path][method]['tags'], ['심사자 00 즉시 로그인'])
        self.assertIn('requestBody', schema['paths']['/reviewer/v1/connections/{user_code}']['post'])


if __name__ == '__main__':
    unittest.main()
