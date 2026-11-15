"""iPhone session, real QR approval routes and synthetic vehicle credential exchange."""
import unittest
import secrets
from concurrent.futures import ThreadPoolExecutor
import threading
from unittest.mock import patch

import test_iphone_session as fixture


class IphoneVehicleIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.addClassCleanup(fixture.IphoneSessionTests.doClassCleanups)
        fixture.IphoneSessionTests.setUpClass()

    def setUp(self):
        self.phone = fixture.IphoneSessionTests()
        self.phone.setUp()

    def pending(self):
        from test_enrollment import make_csr
        from enrollment_crypto import challenge, digest, public_bytes, validate_csr
        from native_access_codec import derive_revoke_capability, revoke_commitment
        _, csr = make_csr()
        service = self.phone.api.module.TEAM_NATIVE_AUTHORIZATION
        operation, verifier = secrets.token_hex(16), secrets.token_urlsafe(32)
        key_id = digest(public_bytes(validate_csr(csr).public_key()))
        return service.begin(dict(authorizationVersion=1, operationId=operation,
            name='Single vehicle test', csrPem=csr, codeChallenge=challenge(verifier),
            requestedScopes=['account:read', 'device:self:manage'],
            revokeCommitment=revoke_commitment(derive_revoke_capability(verifier, key_id, operation))))[1]

    def approval(self, pending, token):
        path = '/v1/iphone/connections/' + pending['userCode']
        status, _, detail = self.phone.iphone(path, token=token)
        self.assertEqual(status, 200, detail)
        return path, dict(authorizationVersion=1, consentVersion=1,
            approvedScopes=detail['requiredScopes'], keepSignedIn=False,
            disclosureVersion=detail['disclosureSnapshot']['disclosureVersion'],
            disclosureSha256=detail['disclosureSnapshot']['disclosureSha256'])

    def test_second_vehicle_requires_revoking_first_and_web_cannot_bypass(self):
        phone = self.phone
        token = phone.login()['accessToken']
        web = phone.api.login()
        _, _, credential = phone.api.pair(web)
        pending = self.pending()
        path, payload = self.approval(pending, token)
        phone.assert_error(phone.iphone(path, payload, 'POST', token=token),
                           409, 'VEHICLE_CONNECTION_LIMIT')
        status, _, error = phone.api.call(path.replace('/v1/iphone/', '/v1/'), payload, 'POST', session=web)
        self.assertEqual((status, error['error']), (409, 'OPERATION_CONFLICT'))
        self.assertEqual(phone.iphone('/v1/iphone/vehicles/' + credential['deviceId'], method='DELETE', token=token)[0], 200)
        self.assertEqual(phone.iphone(path, payload, 'POST', token=token)[0], 200)

    def test_concurrent_approvals_reserve_only_one_vehicle(self):
        token = self.phone.login()['accessToken']
        requests = [self.approval(self.pending(), token) for _ in range(2)]
        barrier = threading.Barrier(2)
        def submit(request):
            barrier.wait(timeout=5)
            path, payload = request
            return self.phone.iphone(path, payload, 'POST', token=token)
        with ThreadPoolExecutor(max_workers=2) as workers:
            futures = [workers.submit(submit, request) for request in requests]
            results = [future.result(timeout=10) for future in futures]
        self.assertEqual(sorted(item[0] for item in results), [200, 409])
        self.assertEqual(next(item[2]['detail'] for item in results if item[0] == 409), 'VEHICLE_CONNECTION_LIMIT')

    def test_expired_unexchanged_approval_does_not_keep_slot_reserved(self):
        token = self.phone.login()['accessToken']
        first = self.pending()
        path, payload = self.approval(first, token)
        self.assertEqual(self.phone.iphone(path, payload, 'POST', token=token)[0], 200)
        service = self.phone.api.module.TEAM_NATIVE_AUTHORIZATION
        future = service.now() + 301
        with patch.object(service, 'clock', return_value=future):
            path, payload = self.approval(self.pending(), token)
            self.assertEqual(self.phone.iphone(path, payload, 'POST', token=token)[0], 200)

    def test_same_installation_can_reauthenticate_and_old_approval_cannot_bypass_exchange_limit(self):
        import psycopg
        from psycopg.rows import dict_row
        from types import SimpleNamespace
        from native_authorization import VehicleConnectionLimit
        phone = self.phone
        token = phone.login()['accessToken']
        _, _, credential = phone.api.pair(phone.api.login())
        service = phone.api.module.TEAM_NATIVE_AUTHORIZATION
        with psycopg.connect(phone.api.dsn, row_factory=dict_row) as conn:
            current = conn.execute('SELECT * FROM native_v2_grants WHERE device_id=%s', (credential['deviceId'],)).fetchone()
            service._require_vehicle_slot(conn, current['account_id'], current['installation_key_id'], service.now())
        pending = self.pending()
        path, payload = self.approval(pending, token)
        with patch.object(service, '_require_vehicle_slot'):
            self.assertEqual(phone.iphone(path, payload, 'POST', token=token)[0], 200)
        with psycopg.connect(phone.api.dsn, row_factory=dict_row) as conn:
            grant = conn.execute('SELECT * FROM native_v2_grants WHERE connection_id=%s', (pending['connectionId'],)).fetchone()
            with self.assertRaises(VehicleConnectionLimit):
                service._issue(conn, 'SESSION_EXCHANGE', SimpleNamespace(for_transport=lambda: {}), grant, {}, first=True)
        listing = phone.iphone('/v1/iphone/vehicles', token=token)[2]['devices']
        self.assertEqual([item['id'] for item in listing], [credential['deviceId']])

    def test_iphone_qr_approval_and_owner_device_revoke(self):
        phone, vehicles = self.phone, '/v1/iphone/vehicles'
        alice = phone.login()['accessToken']
        bob = phone.login(who='bob')['accessToken']
        web = phone.api.login()
        phone.assert_error(phone.iphone(vehicles), 401, 'IPHONE_SESSION_REQUIRED')
        self.assertEqual(phone.api.call(vehicles, session=web, bearer=alice)[0], 404)
        phone.assert_error(phone.iphone('/v1/iphone/connections/bad', token=alice),
                           400, 'INVALID_COMPARISON_CODE')
        self.assertEqual(phone.iphone(vehicles, token=alice)[2], {'devices': []})

        call = phone.api.call

        def approve_in_iphone(path, data=None, method='GET', **kwargs):
            if path.startswith('/v1/connections/'):
                status, headers, value = call('/v1/iphone' + path.removeprefix('/v1'), data, method,
                                              who=None, host=fixture.IPHONE, bearer=alice, origin=None)
                self.assertIn('no-store', phone.header(headers, 'cache-control'))
                return status, headers, value
            return call(path, data, method, **kwargs)

        with patch.object(phone.api, 'call', side_effect=approve_in_iphone):
            pending, _, credential = phone.api.pair(web)

        code = '/v1/iphone/connections/' + pending['userCode']
        status, _, decision = phone.iphone(code, token=alice)
        self.assertEqual((status, decision['state']), (200, 'APPROVED'))
        phone.assert_error(phone.iphone(code, token=bob), 404, 'OPERATION_NOT_FOUND')
        phone.assert_error(phone.iphone(code, {'authorizationVersion': 1}, 'DELETE', token=alice),
                           409, 'OPERATION_CONFLICT')

        device = credential['deviceId']
        token = credential['accessToken']
        self.assertEqual(phone.api.native(vehicles, token=token)[0], 404)
        status, _, listing = phone.iphone(vehicles, token=alice)
        self.assertEqual(status, 200, listing)
        self.assertEqual([item['id'] for item in listing['devices']], [device])
        self.assertEqual(phone.iphone(vehicles, token=bob)[2], {'devices': []})
        path = vehicles + '/' + device
        phone.assert_error(phone.iphone(path, method='DELETE', token=bob), 404, 'DEVICE_UNAVAILABLE')
        self.assertEqual(phone.api.native('/v1/account', token=token)[0], 200)
        status, _, revoked = phone.iphone(path, method='DELETE', token=alice)
        self.assertEqual((status, revoked), (200, {'status': 'revoked'}))
        self.assertEqual(phone.api.native('/v1/account', token=token)[0], 401)
        self.assertEqual(phone.iphone(vehicles, token=alice)[2], {'devices': []})
        phone.assert_error(phone.iphone(path, method='DELETE', token=alice), 404, 'DEVICE_UNAVAILABLE')
