"""Targeted real temporary-PG/HTTP/WebSocket device purpose contracts.
This fixture contains no real account, GPS input, production key or Cloudflare token.
"""
import io
import json
import secrets
import socket
import unittest
import psycopg
from websockets.exceptions import ConnectionClosed, InvalidStatus
from websockets.sync.client import connect
from enrollment_crypto import challenge, digest, public_bytes, validate_csr
from test_enrollment import make_csr
from native_functional_defaults import ACCOUNT_PURPOSES, INITIAL_PURPOSES
import test_native_authorization_http as authorization
import test_team_auth as fixture
import test_team_history as history
from PIL import Image


class NativeAccessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.addClassCleanup(authorization.NativeAuthorizationHttpTests.doClassCleanups)
        authorization.NativeAuthorizationHttpTests.setUpClass()
        from team_api_docs import install_api_docs
        install_api_docs(fixture.TeamTests.module.app, fixture.TeamTests.module.TEAM_AUTH, fixture.TeamTests.module.WEB)

    def setUp(self):
        self.flow = authorization.NativeAuthorizationHttpTests()
        self.flow.setUp()
        self.api = self.flow.api
        self.flow.scopes = sorted(self.flow.scopes + ['playlists:read'])
        self.actor = 'alice'

    def users(self):
        return self.flow.session, self.api.login('bob')

    def pair(self, session, who='alice'):
        flow = self.flow
        if who != self.actor:
            flow.key, flow.csr = make_csr()
            flow.key_id = digest(public_bytes(validate_csr(flow.csr).public_key()))
            flow.verifier = secrets.token_urlsafe(32)
            flow.challenge = challenge(flow.verifier)
        flow.session = session
        self.actor = who
        pending, approval = flow.start(who=who)
        status, _, _ = self.api.call('/v1/connections/' + pending['userCode'], approval, 'POST', session=session, who=who)
        self.assertEqual(status, 200)
        return flow.exchange(flow.claim(pending))

    def native(self, credential, path, body=None, method='GET'):
        return self.api.native(path, body, method, token=credential['accessToken'], certificate=credential['certificateSha256'])

    def socket(self, credential, *, path='/v1/events', origin=None):
        headers = {'Authorization': 'Bearer ' + credential['accessToken'],
                   'cf-cert-sha256': credential['certificateSha256'], 'cf-cert-presented': 'true',
                   'cf-cert-verified':'true', 'cf-cert-revoked':'false'}
        return connect('ws://api.wegoh.invalid' + path, sock=socket.create_connection(('127.0.0.1', self.api.port), timeout=5),
                       additional_headers=headers, origin=origin, open_timeout=3, close_timeout=1)

    def permissions(self, credential, session, who='alice'):
        return self.api.call('/v1/devices/' + credential['deviceId'] + '/functional-permissions', session=session, who=who)

    def permission_body(self, current, purposes):
        return {**{k: current[k] for k in ('authorizationVersion', 'grantId', 'revision', 'functionalDisclosureVersion',
                                           'functionalDisclosureSha256')},
                'approvedPurposes': self.api.web_purposes(current, purposes)}

    def grant(self, credential, session, purposes):
        status, _, current = self.permissions(credential, session)
        self.assertEqual(status, 200)
        return self.api.call('/v1/devices/' + credential['deviceId'] + '/functional-permissions',
                             self.permission_body(current,purposes), 'PUT', session=session)

    def create_record(self, session, who='alice'):
        body = dict(title='Synthetic device-visible trip', startedAt='2026-01-02T01:00:00Z',
                    endedAt=None, courseId=None, courseVersion=None)
        status, _, value = self.api.call('/v1/social/history', body, 'POST', session=session, who=who)
        self.assertEqual(status, 201)
        return value['id']

    def create_room(self, session, who='alice'):
        status, _, value = self.api.call('/v1/social/rooms', dict(name='Synthetic private room',
            expiresInHours=1, courseId=None, courseVersion=None), 'POST', session=session, who=who)
        self.assertEqual(status, 201, value)
        return value['id']

    def test_01_link_has_account_defaults_but_no_optional_location_or_history_write(self):
        a, _ = self.users()
        receipt = self.pair(a)
        status, headers, view = self.permissions(receipt, a)
        self.assertEqual(status, 200)
        self.assertIn('no-store', headers.get('cache-control', ''))
        self.assertEqual(set(view['approvedPurposes']), set(INITIAL_PURPOSES) | ACCOUNT_PURPOSES)
        native = self.native(receipt, '/v1/device/functional-permissions')
        self.assertEqual(native[0], 200)
        self.assertEqual(native[2]['approvedPurposes'], view['approvedPurposes'])
        self.assertEqual(self.native(receipt, '/v1/account')[0], 200)
        self.assertEqual(self.native(receipt, '/v1/playlists')[0], 200)
        self.assertNotIn('history:write', view['approvedPurposes'])
        self.assertNotIn('vehicle-location:report', view['approvedPurposes'])
        self.assertEqual(self.native(receipt, '/v1/native/rooms/' + 'a' * 32 + '/reports/location',
                                     {'functionalRevision': view['revision']}, 'POST')[0], 403)

    def test_02_owner_revision_csrf_and_individual_revoke(self):
        a, b = self.users()
        device, other = self.pair(a), self.pair(b, 'bob')
        self.assertEqual(self.permissions(device, b, 'bob')[0], 404)
        self.assertEqual(self.permissions(other, a)[0], 404)
        self.assertEqual(self.api.native('/v1/account', token=device['accessToken'],
                                          certificate=other['certificateSha256'])[0], 401)
        path = '/v1/devices/' + device['deviceId'] + '/functional-permissions'
        old = self.permissions(device, a)[2]
        body = self.permission_body(old, ['history:write','vehicle-location:report'])
        self.assertEqual(self.api.call(path, body, 'PUT', session=a, csrf=False)[0], 403)
        status, _, current = self.api.call(path, body, 'PUT', session=a)
        self.assertEqual(status, 200)
        self.assertIn('history:write', current['approvedPurposes'])
        self.assertEqual(self.api.call(path, body, 'PUT', session=a)[0], 409)
        self.assertEqual(self.api.call(path, dict(body, revision=current['revision'], approvedPurposes=[1]), 'PUT', session=a)[0], 400)
        status, _, cut = self.api.call(path + '/history:write', method='DELETE', session=a)
        self.assertEqual(status, 200)
        self.assertNotIn('history:write', cut['approvedPurposes'])
        self.assertIn('vehicle-location:report', cut['approvedPurposes'])
        self.assertEqual(self.api.call(path + '/unknown', method='DELETE', session=a)[0], 404)

    def test_03_purposes_are_separate_and_read_dtos_minimize_other_scopes(self):
        a, b = self.users(); device = self.pair(a)
        self.assertEqual(self.api.call('/v1/social/friends/requests', dict(targetId=b['user']['id']), 'POST', session=a)[0], 201)
        self.assertEqual(self.api.call('/v1/social/friends/requests/' + a['user']['id'] + '/respond',
            dict(accept=True), 'POST', session=b, who='bob')[0], 200)
        room = self.create_room(a); item = self.create_record(a)
        helper=history.HistoryTests(methodName='test_01_owner_admin_and_personal_crud_capabilities');helper.api=self.api
        status,_,visit=helper.visit(item,a);self.assertEqual(status,201)
        image = io.BytesIO()
        Image.new('RGB', (8, 8), color='navy').save(image, format='JPEG')
        photo = self.api.module.TEAM_PHOTOS.store(a['user']['id'], item, visit['id'], helper.detail(item, a)['revision'],
            dict(width=8, height=8), image.getvalue())
        self.assertEqual(self.api.call(photo['photo']['url'], session=a)[0], 200)
        self.assertEqual(len(helper.detail(item,a)['visits'][0]['photos']),1)
        foreign_room = self.create_room(b, who='bob')
        status, _, overview = self.native(device, '/v1/social/overview')
        self.assertEqual(status, 200); self.assertEqual([x['id'] for x in overview['friends']], [b['user']['id']])
        for field in ['people', 'requests', 'blocks']: self.assertEqual(overview[field], [])
        self.assertEqual([r['id'] for r in overview['rooms']], [room])
        self.assertEqual(self.native(device, '/v1/social/rooms/' + foreign_room)[0], 404)
        self.assertEqual(self.native(device, '/v1/native/rooms')[0], 404)
        detail = self.native(device, '/v1/social/rooms/' + room)
        self.assertEqual(detail[0], 200)
        for field in ['code', 'inviteUri', 'consents', 'availableConsentKeys']: self.assertNotIn(field, detail[2])
        foreign_item = self.create_record(b, 'bob')
        self.assertEqual(self.native(device, '/v1/social/history/' + foreign_item)[0], 404)
        listing = self.native(device, '/v1/social/history')
        self.assertEqual(listing[0], 200); self.assertEqual(listing[2]['friends'], [])
        self.assertEqual(listing[2]['history'][0]['sharedWith'], [])
        detail = self.native(device, '/v1/social/history/' + item)
        self.assertEqual(detail[0], 200); self.assertTrue(detail[2]['nativeReadOnly'])
        self.assertEqual(detail[2]['grants'], []); self.assertIsNone(detail[2]['permissions'])
        self.assertFalse(detail[2]['capabilities']['historyTraceIngest'])
        self.assertFalse(detail[2]['capabilities']['historyPhotos']); self.assertFalse(detail[2]['capabilities']['historyPhotoUpload'])
        self.assertNotIn('roomId',detail[2]['source'])
        self.assertEqual(len(detail[2]['visits']),1)
        for visit in detail[2]['visits']: self.assertEqual(visit['photos'],[])
        self.assertNotIn(photo['photo']['id'],json.dumps(detail[2]))
        self.assertEqual(self.native(device, photo['photo']['url'])[0],401)

    def test_04_native_does_not_gain_browser_only_mutations_or_photo_access(self):
        a, b = self.users()
        device = self.pair(a)
        item = self.create_record(a)
        self.assertEqual(self.grant(device, a, ['history:write'])[0], 200)
        for path, method, body in [('/v1/social/friends/requests', 'POST', dict(targetId=b['user']['id'])),
                                   ('/v1/social/history', 'POST', {}), ('/v1/social/rooms', 'POST', {})]:
            with self.subTest(path=path):
                self.assertEqual(self.native(device, path, body, method)[0], 400)
        for path, method, body in [('/v1/social/history/' + item + '/permissions', 'PATCH', {}),
                                   ('/v1/devices/' + device['deviceId'] + '/functional-permissions', 'PUT', {})]:
            with self.subTest(path=path):
                self.assertEqual(self.native(device, path, body, method)[0], 404)
        photo = '/v1/social/history/' + item + '/visits/' + 'a'*32 + '/photos/' + 'b'*32
        self.assertEqual(self.native(device, photo)[0], 401)

    def test_05_only_scoped_socket_resources_and_credential_rotation_require_new_snapshot(self):
        a, b = self.users()
        device = self.pair(a)
        with self.api.websocket(a) as browser:
            self.assertIn('content',json.loads(browser.recv(timeout=2))['resources'])
        with self.api.websocket(b,who='bob') as browser:
            self.assertNotIn('content',json.loads(browser.recv(timeout=2))['resources'])
        with self.socket(device) as channel:
            snapshot = json.loads(channel.recv(timeout=2))
            self.assertEqual(set(snapshot['resources']), {'courses','playlists','devices'})
            self.assertEqual(self.grant(device, a, ['history:write'])[0],200)
            self.assertEqual(json.loads(channel.recv(timeout=3)), dict(type='invalidate', epoch=snapshot['epoch'],
                                                                      seq=1, resources=['devices']))
            refresh = dict(authorizationVersion=1, operationId=secrets.token_hex(16), grantId=device['grantId'],
                           deviceId=device['deviceId'], refreshToken=device['refreshToken'])
            status, _, result = self.flow.native('/v1/device-sessions/refresh', refresh, 'POST')
            self.assertEqual(status, 200, result)
            with self.assertRaises(ConnectionClosed): channel.recv(timeout=3)
        fresh = result['credentialReceipt']
        self.assertEqual(self.native(device, '/v1/account')[0], 401)
        with self.socket(fresh) as channel:
            next_snapshot = json.loads(channel.recv(timeout=2))
            self.assertEqual((next_snapshot['type'], next_snapshot['seq']), ('snapshot',0))
            self.assertNotEqual(next_snapshot['epoch'], snapshot['epoch'])

    def test_06_device_and_allowlist_revoke_close_current_access(self):
        a, _ = self.users()
        device = self.pair(a)
        self.addCleanup(fixture.TeamTests.write_members, fixture.TeamTests.members_rows)
        with self.socket(device) as channel:
            channel.recv(timeout=2)
            fixture.TeamTests.write_members(fixture.TeamTests.members_rows[1:])
            self.assertEqual(self.native(device, '/v1/social/history')[0], 403)
            with self.assertRaises(ConnectionClosed): channel.recv(timeout=3)
        fixture.TeamTests.write_members(fixture.TeamTests.members_rows)
        self.assertEqual(self.api.call('/v1/devices/' + device['deviceId'], method='DELETE', session=a)[0], 200)
        self.assertEqual(self.native(device, '/v1/social/history')[0], 401)

    def test_07_encrypted_grants_and_corruption_fail_closed(self):
        a, _ = self.users()
        device = self.pair(a)
        self.assertEqual(self.grant(device, a, ['history:write'])[0], 200)
        with psycopg.connect(self.api.dsn) as conn:
            raw = bytes(conn.execute('SELECT protected FROM native_functional_authorizations WHERE grant_id=%s',
                                      (device['grantId'],)).fetchone()[0])
            self.assertNotIn(b'approvedPurposes', raw)
            self.assertNotIn(b'history:write', raw)
            broken = bytearray(raw)
            broken[-1] ^= 1
            conn.execute('UPDATE native_functional_authorizations SET protected=%s WHERE grant_id=%s',
                         (bytes(broken), device['grantId']))
        self.assertEqual(self.permissions(device, a)[0], 503)
        self.assertEqual(self.native(device, '/v1/social/history')[0], 503)

    def test_08_origin_url_credentials_and_disabled_host_remain_closed(self):
        a, _ = self.users()
        device = self.pair(a)
        for options in [dict(path='/v1/events?token=not-a-credential'), dict(origin=fixture.WEB)]:
            with self.subTest(options=options), self.assertRaises(InvalidStatus) as denied:
                with self.socket(device, **options): pass
            self.assertEqual(denied.exception.response.status_code, 403)
        with self.socket(device) as channel:
            self.assertEqual(json.loads(channel.recv(timeout=2))['type'],'snapshot')
            channel.send('unexpected client command')
            with self.assertRaises(ConnectionClosed) as closed: channel.recv(timeout=3)
            self.assertEqual(closed.exception.rcvd.code,1008)
        auth = self.api.module.TEAM_AUTH
        previous = auth.native_origin
        try:
            auth.native_origin = ''
            self.assertEqual(self.native(device, '/v1/device/permissions')[0], 404)
            status, _, schema = self.api.call('/openapi.json', session=a)
            self.assertEqual(status, 200)
            operation = schema['paths']['/v1/native/courses/library']['get']
            self.assertFalse(operation['x-wegoh-native-configured'])
            self.assertTrue(operation['x-wegoh-native-read-only'])
            self.assertFalse(operation['x-wegoh-executable'])
            photo = schema['paths']['/v1/social/history/{item}/visits/{visit}/photos/{photo}']['get']
            self.assertFalse(photo['x-wegoh-executable'])
        finally:
            auth.native_origin = previous


if __name__ == '__main__': unittest.main(verbosity=2)
