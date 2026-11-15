"""iPhone login and session contracts over HTTP with signed Access and disposable PostgreSQL."""
import base64
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import hashlib
import hmac
import http.client
from html.parser import HTMLParser
import os
import secrets
import sys
import time
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlencode, urlsplit

import psycopg

import test_team_auth as fixture


IPHONE = 'ios-api-wegoh.devforest.io'
LOGIN = '/v1/iphone/login'
SESSION = '/v1/iphone/session'
DECISION = '/v1/iphone/browser/login/decision'
REVOKE = '/v1/iphone/browser/sessions'


class HiddenFields(HTMLParser):
    def __init__(self, body):
        super().__init__()
        self.values = {}
        self.feed(body.decode('utf-8'))

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'input' and attrs.get('type') == 'hidden':
            self.values[attrs['name']] = attrs['value']


class IphoneSessionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        env = patch.dict(os.environ, {'WEGOH_IPHONE_API_ORIGIN': 'https://' + IPHONE})
        env.start()
        cls.addClassCleanup(env.stop)
        previous_app = sys.modules.pop('app', None)

        def restore_app():
            sys.modules.pop('app', None)
            if previous_app is not None:
                sys.modules['app'] = previous_app

        cls.addClassCleanup(restore_app)
        fixture.TeamTests.setUpClass()
        cls.addClassCleanup(fixture.TeamTests.tearDownClass)

    def setUp(self):
        self.api = fixture.TeamTests('test_01_jwt_verification_and_exact_hosts')
        self.api.setUp()
        with psycopg.connect(self.api.dsn) as conn:
            conn.execute('TRUNCATE iphone_login_requests, iphone_sessions, iphone_push_installations, iphone_push_outbox')

    def iphone(self, path, data=None, method='GET', *, token=None, **options):
        return self.api.call(path, data, method, who=None, host=IPHONE,
                             bearer=token, origin=None, **options)

    def start(self):
        verifier = secrets.token_urlsafe(32)
        state = secrets.token_urlsafe(32)
        digest = hashlib.sha256(verifier.encode('ascii')).digest()
        challenge = base64.urlsafe_b64encode(digest).rstrip(b'=').decode('ascii')
        status, headers, request = self.iphone(
            LOGIN + '/requests', dict(codeChallenge=challenge, state=state), 'POST')
        self.assertEqual(status, 201, request)
        self.assertIn('no-store', self.header(headers, 'cache-control'))
        self.assertEqual(set(request), {'requestId', 'authorizationUrl', 'expiresAt'})
        self.assertEqual(request['authorizationUrl'], fixture.WEB + '/iphone-login?' +
                         urlencode({'request_id': request['requestId']}))
        self.assertLessEqual(abs(request['expiresAt'] - int(time.time()) - 300), 2)
        return request, verifier, state

    @staticmethod
    def header(headers, name):
        return next((value for key, value in headers.items() if key.lower() == name), None)

    def browser_page(self, request, *, who='alice', assertion=None):
        url = urlsplit(request['authorizationUrl'])
        return self.api.call(url.path + '?' + url.query, who=who, origin=None, assertion=assertion)

    def submit(self, fields, decision, *, who='alice', origin=fixture.WEB, assertion=None):
        headers = {'Host': urlsplit(fixture.WEB).netloc,
                   'Content-Type': 'application/x-www-form-urlencoded'}
        if origin:
            headers['Origin'] = origin
        if who:
            headers['Cf-Access-Jwt-Assertion'] = assertion or self.api.assertion(who)
        with closing(http.client.HTTPConnection('127.0.0.1', self.api.port, timeout=5)) as connection:
            connection.request('POST', DECISION,
                               body=urlencode(dict(fields, decision=decision)), headers=headers)
            response = connection.getresponse()
            return response.status, dict(response.getheaders()), response.read()

    def decide(self, request, state, decision, *, who='alice', assertion=None):
        status, headers, page = self.browser_page(request, who=who, assertion=assertion)
        self.assertEqual(status, 200, page)
        self.assertIn('no-store', self.header(headers, 'cache-control'))
        fields = HiddenFields(page).values
        self.assertEqual(fields['request_id'], request['requestId'])
        self.assertTrue(fields['csrf'])
        status, headers, body = self.submit(fields, decision, who=who, assertion=assertion)
        self.assertEqual(status, 303, body)
        self.assertIsNone(self.header(headers, 'set-cookie'))
        callback = urlsplit(self.header(headers, 'location'))
        self.assertEqual((callback.scheme, callback.netloc, callback.path),
                         ('io.wegoh.iphone', 'login', '/callback'))
        self.assertEqual(callback.fragment, '')
        fields = parse_qs(callback.query, strict_parsing=True)
        self.assertEqual(fields.pop('state'), [state])
        return fields

    def exchange(self, request, verifier, code):
        return self.iphone(LOGIN + '/exchange', dict(requestId=request['requestId'],
                           code=code, codeVerifier=verifier), 'POST')

    def login(self, *, who='alice'):
        request, verifier, state = self.start()
        approved = self.decide(request, state, 'approve', who=who)
        self.assertEqual(set(approved), {'code'})
        self.assertEqual(len(approved['code']), 1)
        status, headers, session = self.exchange(request, verifier, approved['code'][0])
        self.assertEqual(status, 200, session)
        self.assertIn('no-store', self.header(headers, 'cache-control'))
        self.assertIsNone(self.header(headers, 'set-cookie'))
        self.assertNotEqual(session['accessToken'], approved['code'][0])
        self.assertEqual(session['tokenType'], 'Bearer')
        return session

    def assert_error(self, response, status, detail):
        actual_status, _, value = response
        self.assertEqual((actual_status, value), (status, {'detail': detail}))

    def test_callback_form_policy_is_limited_to_pending_login_page(self):
        request, _, _ = self.start()
        status, headers, page = self.browser_page(request)
        self.assertEqual(status, 200)
        directives = dict(item.strip().split(' ', 1) for item in
                          self.header(headers, 'content-security-policy').split(';') if item.strip())
        self.assertEqual(directives['form-action'].split(),
                         ["'self'", 'io.wegoh.iphone://login/callback'])
        fields = HiddenFields(page).values
        status, headers, _ = self.submit(fields, 'deny')
        self.assertEqual(status, 303)
        self.assertTrue(self.header(headers, 'location').startswith('io.wegoh.iphone://login/callback?'))
        self.assertNotIn('io.wegoh.iphone:', self.header(headers, 'content-security-policy'))
        status, headers, _ = self.browser_page(request)
        self.assertEqual(status, 409)
        self.assertNotIn('io.wegoh.iphone:', self.header(headers, 'content-security-policy'))
        status, headers, _ = self.api.call('/studio.html', origin=None)
        self.assertEqual(status, 200)
        self.assertNotIn('io.wegoh.iphone:', self.header(headers, 'content-security-policy'))

    def test_login_bootstraps_same_account_and_restores_then_logs_out(self):
        session = self.login()
        self.assertEqual(session['user']['displayName'], 'alice')
        web = self.api.login()
        self.assertEqual(session['user']['id'], web['user']['id'])
        self.assertEqual(set(session['scopes']), {'account:read', 'account:write', 'maps:read', 'vehicles:manage', 'courses:read', 'courses:write', 'friends:read', 'friends:manage', 'trips:read', 'trips:manage'})
        self.assertLessEqual(abs(session['expiresAt'] - int(time.time()) - 604800), 2)
        token = session['accessToken']
        status, headers, restored = self.iphone(SESSION, token=token)
        self.assertEqual(status, 200, restored)
        self.assertIn('no-store', self.header(headers, 'cache-control'))
        self.assertEqual(restored, {key: session[key] for key in ('user', 'scopes', 'expiresAt')})
        updated_name = '새 표시 이름'
        status, _, updated = self.api.call('/v1/profile',
            dict(displayName=updated_name, expectedDisplayName='alice'), 'PUT', session=web)
        self.assertEqual(status, 200, updated)
        self.assertEqual(self.iphone(SESSION, token=token)[2]['user'],
                         dict(id=session['user']['id'], displayName=updated_name))
        status, _, body = self.iphone(SESSION, method='DELETE', token=token)
        self.assertEqual((status, body), (204, b''))
        self.assert_error(self.iphone(SESSION, token=token), 401, 'IPHONE_SESSION_REVOKED')
        self.assert_error(self.iphone(SESSION), 401, 'IPHONE_SESSION_REQUIRED')

    def test_access_new_email_joins_only_after_iphone_approval(self):
        newcomer = self.api.assertion('newcomer', type='app', role='creator')
        denied, _, denied_state = self.start()
        self.assertEqual(self.decide(denied, denied_state, 'deny', assertion=newcomer),
                         {'error': ['access_denied']})
        with psycopg.connect(self.api.dsn) as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM team_accounts').fetchone(), (0,))

        request, verifier, state = self.start()
        code = self.decide(request, state, 'approve', assertion=newcomer)['code'][0]
        status, _, session = self.exchange(request, verifier, code)
        self.assertEqual(status, 200, session)
        account = session['user']
        web = self.api.login(assertion=newcomer)['user']
        self.assertEqual((web['id'], web['displayName'], web['role']),
                         (account['id'], account['displayName'], 'admin'))
        self.assertEqual(self.iphone(SESSION, token=session['accessToken'])[2]['user'], account)
        self.assert_error(self.iphone('/v1/iphone/connections/ABCDEFGH', token=session['accessToken']),
                          403, 'Team access denied')
        with psycopg.connect(self.api.dsn) as conn:
            self.assertEqual(conn.execute('SELECT account_id FROM team_accounts').fetchall(),
                             [(account['id'],)])
            conn.execute("UPDATE team_accounts SET account_status='suspended' WHERE account_id=%s",
                         (account['id'],))
        self.assert_error(self.iphone(SESSION, token=session['accessToken']), 401, 'IPHONE_SESSION_REVOKED')

    def test_browser_access_origin_and_csrf_are_bound_to_the_approval(self):
        request, _, _ = self.start()
        self.assertEqual(self.browser_page(request, who=None)[0], 401)
        status, _, page = self.browser_page(request)
        self.assertEqual(status, 200, page)
        fields = HiddenFields(page).values
        self.assertEqual(self.submit(fields, 'approve', who=None)[0], 401)
        self.assertEqual(self.submit(fields, 'approve', origin='https://other.invalid')[0], 403)
        self.assertEqual(self.submit(dict(fields, csrf='invalid'), 'approve')[0], 403)
        self.assertEqual(self.submit(fields, 'approve', who='bob')[0], 403)
        self.assertEqual(self.submit(fields, 'approve')[0], 303)

    def assert_legacy_consent_exchange(self, request, verifier, code):
        status, _, session = self.exchange(request, verifier, code)
        self.assertEqual(status, 200, session)
        self.assertEqual(set(session['scopes']), {'account:read', 'maps:read', 'vehicles:manage'})
        token = session['accessToken']
        self.assertEqual(self.iphone(SESSION, token=token)[2]['scopes'], session['scopes'])
        self.assert_error(self.iphone('/v1/iphone/courses', token=token), 403, 'IPHONE_SCOPE_DENIED')
        self.assert_error(self.iphone('/v1/iphone/profile',
            dict(displayName='새 이름', expectedDisplayName='alice'), 'PUT', token=token),
            403, 'IPHONE_SCOPE_DENIED')

    def test_legacy_consent_form_keeps_disclosed_scopes_when_submitted_after_upgrade(self):
        request, verifier, state = self.start()
        account = self.api.login()['user']['id']
        secret = self.api.module.TEAM_AUTH.secret
        message = f"wegoh-iphone-login-v1:{request['requestId']}:{account}".encode('ascii')
        fields = dict(request_id=request['requestId'], csrf=hmac.new(secret, message, hashlib.sha256).hexdigest())
        status, headers, _ = self.submit(fields, 'approve')
        self.assertEqual(status, 303)
        callback = parse_qs(urlsplit(self.header(headers, 'location')).query, strict_parsing=True)
        self.assertEqual(callback['state'], [state])
        self.assert_legacy_consent_exchange(request, verifier, callback['code'][0])

    def test_pre_upgrade_approval_keeps_disclosed_scopes_when_exchanged_after_upgrade(self):
        request, verifier, _ = self.start()
        account = self.api.login()['user']['id']
        code = secrets.token_urlsafe(32)
        old_receipt = hashlib.sha256(('WegoH iPhone code\n' + code).encode('ascii')).hexdigest()
        with psycopg.connect(self.api.dsn) as conn:
            conn.execute("UPDATE iphone_login_requests SET status='APPROVED',account_id=%s,code_hash=%s "
                         'WHERE request_id=%s', (account, old_receipt, request['requestId']))
        self.assert_legacy_consent_exchange(request, verifier, code)

    def test_pkce_approval_code_is_single_use_even_for_simultaneous_exchanges(self):
        request, verifier, state = self.start()
        code = self.decide(request, state, 'approve')['code'][0]
        with psycopg.connect(self.api.dsn) as conn:
            code_hash = conn.execute('SELECT code_hash FROM iphone_login_requests WHERE request_id=%s',
                                     (request['requestId'],)).fetchone()[0]
        self.assertTrue(code_hash)
        self.assertNotEqual(code_hash, code)
        self.assert_error(self.exchange(request, secrets.token_urlsafe(32), code),
                          401, 'IPHONE_INVALID_PROOF')
        with ThreadPoolExecutor(max_workers=2) as workers:
            attempts = [workers.submit(self.exchange, request, verifier, code) for _ in range(2)]
            success, replay = sorted((attempt.result() for attempt in attempts),
                                     key=lambda result: result[0])
        self.assertEqual(success[0], 200, success[2])
        self.assert_error(replay, 409, 'IPHONE_LOGIN_USED')
        with psycopg.connect(self.api.dsn) as conn:
            stored_hashes = conn.execute('SELECT token_hash FROM iphone_sessions').fetchall()
        self.assertEqual(len(stored_hashes), 1)
        self.assertNotEqual(stored_hashes[0][0], success[2]['accessToken'])

    def test_denial_cancel_and_expiry_have_distinct_results(self):
        request, verifier, state = self.start()
        self.assert_error(self.exchange(request, verifier, secrets.token_urlsafe(32)),
                          409, 'IPHONE_LOGIN_PENDING')
        self.assertEqual(self.decide(request, state, 'deny'), {'error': ['access_denied']})
        self.assert_error(self.exchange(request, verifier, secrets.token_urlsafe(32)),
                          403, 'IPHONE_LOGIN_DENIED')

        cancelled, verifier, _ = self.start()
        self.assertEqual(self.iphone(LOGIN + '/cancel',
                         dict(requestId=cancelled['requestId'], codeVerifier=verifier), 'POST')[0], 204)
        self.assert_error(self.browser_page(cancelled), 409, 'IPHONE_LOGIN_USED')
        self.assert_error(self.exchange(cancelled, verifier, secrets.token_urlsafe(32)),
                          403, 'IPHONE_LOGIN_DENIED')

        expired, verifier, state = self.start()
        code = self.decide(expired, state, 'approve')['code'][0]
        with psycopg.connect(self.api.dsn) as conn:
            conn.execute('UPDATE iphone_login_requests SET expires_at=%s', (int(time.time()) - 1,))
        self.assert_error(self.exchange(expired, verifier, code), 410, 'IPHONE_LOGIN_EXPIRED')

    def test_session_expiry_and_membership_loss_require_reauthentication(self):
        token = self.login()['accessToken']
        with psycopg.connect(self.api.dsn) as conn:
            conn.execute('UPDATE iphone_sessions SET expires_at=%s', (int(time.time()) - 1,))
        self.assert_error(self.iphone(SESSION, token=token), 401, 'IPHONE_SESSION_EXPIRED')
        another = self.login()['accessToken']
        self.api.write_members([member for member in self.api.members_rows
                                if member['email'] != 'alice@example.invalid'])
        self.assert_error(self.iphone(SESSION, token=another), 401, 'IPHONE_SESSION_REVOKED')
        self.api.write_members(self.api.members_rows)
        self.assert_error(self.iphone(SESSION, token=another), 401, 'IPHONE_SESSION_REVOKED')
        self.assertEqual(self.iphone(SESSION, token=self.login()['accessToken'])[0], 200)

    def test_browser_revocation_targets_own_sessions_and_keeps_other_auth_surfaces_isolated(self):
        alice = self.api.login()
        alice_token = self.login()['accessToken']
        bob_token = self.login(who='bob')['accessToken']
        request, verifier, state = self.start()
        approved_code = self.decide(request, state, 'approve')['code'][0]
        self.assertEqual(self.api.call(SESSION, bearer=alice_token, session=alice)[0], 404)
        self.assertEqual(self.api.native(SESSION, token=alice_token)[0], 404)
        self.assertEqual(self.iphone('/v1/auth/session', token=alice_token)[0], 404)
        self.assert_error(self.iphone(SESSION, token=alice_token, session=alice),
                          400, 'IPHONE_INVALID_REQUEST')
        self.assertEqual(self.api.call(REVOKE, method='DELETE', session=alice, csrf=False)[0], 403)
        self.assertEqual(self.api.call(REVOKE, method='DELETE', session=alice)[0], 204)
        self.assert_error(self.iphone(SESSION, token=alice_token), 401, 'IPHONE_SESSION_REVOKED')
        self.assert_error(self.exchange(request, verifier, approved_code), 403, 'IPHONE_LOGIN_DENIED')
        self.assertEqual(self.iphone(SESSION, token=bob_token)[0], 200)
        self.assertTrue(self.api.call('/v1/auth/session', session=alice)[2]['authenticated'])

    def test_session_scope_is_enforced_for_the_current_request(self):
        token = self.login()['accessToken']
        with psycopg.connect(self.api.dsn) as conn:
            conn.execute('UPDATE iphone_sessions SET scopes=%s', (['maps:read'],))
        self.assert_error(self.iphone(SESSION, token=token), 403, 'IPHONE_SCOPE_DENIED')
