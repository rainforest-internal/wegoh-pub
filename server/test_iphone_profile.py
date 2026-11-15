"""Native account edits reuse existing profile rules and encrypted identity records."""
import unittest
from unittest.mock import patch
import psycopg
from private_records import VisitCipher
import test_iphone_session as fixture

PROFILE = '/v1/iphone/profile'

class IPhoneProfileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.addClassCleanup(fixture.IphoneSessionTests.doClassCleanups)
        fixture.IphoneSessionTests.setUpClass()

    def setUp(self):
        self.phone = fixture.IphoneSessionTests()
        self.phone.setUp()
        self.token = self.phone.login()['accessToken']

    def call(self, path=PROFILE, body=None, method='GET', token=None):
        return self.phone.iphone(path, body, method, token=token or self.token)

    def test_name_handle_rules_conflicts_and_existing_record_preservation(self):
        status, headers, before = self.call()
        self.assertEqual(status, 200)
        self.assertIn('no-store', self.phone.header(headers, 'cache-control'))
        user = before['user']
        status, _, result = self.call(body=dict(displayName='새 이름', expectedDisplayName='alice'), method='PUT')
        self.assertEqual((status, result['user']['displayName']), (200, '새 이름'))
        self.assertEqual(self.call()[2]['user']['displayName'], '새 이름')
        self.assertEqual(self.call(body=dict(displayName='오래된 수정', expectedDisplayName='alice'), method='PUT')[0], 409)
        self.assertEqual(self.call(body=dict(displayName=' bad ', expectedDisplayName='새 이름'), method='PUT')[0], 400)
        handle = PROFILE + '/handle'
        payload = dict(handle='new_code', expectedHandle=user['handle'])
        self.assertEqual(self.call(handle, payload, 'PUT')[2], dict(handle='new_code'))
        self.assertEqual(self.call(handle, payload, 'PUT')[0], 409)
        self.assertEqual(self.call(handle, dict(handle='another_code', expectedHandle='new_code'), 'PUT')[0], 429)
        web = self.phone.api.login()
        current = self.phone.api.call('/v1/auth/session', session=web)[2]['user']
        self.assertEqual((current['displayName'], current['handle']), ('새 이름', 'new_code'))
        with psycopg.connect(self.phone.api.dsn) as conn:
            raw = conn.execute('SELECT protected FROM team_accounts WHERE account_id=%s', (user['id'],)).fetchone()[0]
        self.assertNotIn('새 이름'.encode(), bytes(raw))
        saved = VisitCipher().restore('team-account:' + user['id'], 'identity', raw)
        self.assertEqual(saved['email'], 'alice@example.invalid')

    def test_scopes_hosts_ownership_and_revocation(self):
        with psycopg.connect(self.phone.api.dsn) as conn:
            conn.execute('UPDATE iphone_sessions SET scopes=%s', (['account:read', 'maps:read', 'vehicles:manage'],))
        self.assertEqual(self.call()[0], 200)
        self.phone.assert_error(self.call(body=dict(displayName='Denied', expectedDisplayName='alice'), method='PUT'), 403, 'IPHONE_SCOPE_DENIED')
        self.phone.assert_error(self.call(PROFILE+'/handle', dict(handle='denied', expectedHandle='ignored'), 'PUT'), 403, 'IPHONE_SCOPE_DENIED')
        web = self.phone.api.login()
        _, _, credential = self.phone.api.pair(web)
        self.assertEqual(self.call('/v1/iphone/vehicles')[0], 200)
        plate = '/v1/iphone/vehicles/' + credential['deviceId'] + '/profile'
        self.phone.assert_error(self.call(plate), 403, 'IPHONE_SCOPE_DENIED')
        self.phone.assert_error(self.call(plate, dict(plateNumber='123가4567', name='', expectedRevision=0), 'PUT'),
                                403, 'IPHONE_SCOPE_DENIED')
        self.assertEqual(self.phone.api.call(PROFILE, session=web, bearer=self.token)[0], 404)
        self.assertEqual(self.phone.api.native(PROFILE, token=self.token)[0], 404)
        self.assertEqual(self.call(PROFILE+'?ignored=1')[0], 400)
        self.assertEqual(self.phone.iphone(fixture.SESSION, method='DELETE', token=self.token)[0], 204)
        self.assertEqual(self.call()[0], 401)

    def test_vehicle_plate_is_the_same_encrypted_profile_and_exact_owned_device(self):
        web = self.phone.api.login()
        _, _, credential = self.phone.api.pair(web)
        path = '/v1/iphone/vehicles/' + credential['deviceId'] + '/profile'
        self.assertEqual(self.call(path)[2]['revision'], 0)
        payload = dict(plateNumber='123가4567', name='', expectedRevision=0)
        self.assertEqual(self.call(path, payload, 'PUT')[2]['revision'], 1)
        self.assertEqual(self.call(path, payload, 'PUT')[0], 409)
        self.assertEqual(self.phone.api.native('/v1/device/vehicle-profile', token=credential['accessToken'])[2]['plateNumber'], '123가4567')
        bob = self.phone.login(who='bob')['accessToken']
        self.assertEqual(self.call(path, token=bob)[0], 404)
        self.assertEqual(self.call(path, payload, 'PUT', token=bob)[0], 404)
        self.assertEqual(self.call(body=dict(displayName='차주', expectedDisplayName='alice'), method='PUT')[0], 200)
        self.assertEqual(self.call(path)[2]['plateNumber'], '123가4567')
        self.assertEqual(self.call(path, dict(plateNumber='', name='', expectedRevision=1), 'PUT')[2]['plateNumber'], '')
        vehicles = lambda: [row['name'] for row in self.call('/v1/iphone/vehicles')[2]['devices']]
        self.assertEqual(vehicles(), ['차주의 차'])
        renamed = self.call(path, dict(plateNumber='', name='출근 차', expectedRevision=2), 'PUT')[2]
        self.assertEqual((renamed['name'], renamed['defaultName']), ('출근 차', '차주의 차'))
        self.assertEqual(vehicles(), ['출근 차'])
        self.assertEqual(self.call(path, dict(plateNumber='', name='출근 차 ', expectedRevision=3), 'PUT')[0], 400)
        self.phone.iphone('/v1/iphone/vehicles/'+credential['deviceId'], method='DELETE', token=self.token)
        self.assertEqual(self.call(path)[0], 404)

    def test_writes_recheck_session_inside_transaction(self):
        service = self.phone.api.module.TEAM_AUTH.iphone_sessions
        original = service.authenticate
        def revoke_before_write(request, scope, **options):
            if options.get('lock'):
                from iphone_sessions import fail
                fail(401, 'SESSION_REVOKED')
            return original(request, scope, **options)
        with patch.object(service, 'authenticate', side_effect=revoke_before_write):
            self.assertEqual(self.call(body=dict(displayName='Never stored', expectedDisplayName='alice'), method='PUT')[0], 401)
        self.assertEqual(self.call()[2]['user']['displayName'], 'alice')
