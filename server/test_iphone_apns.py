import json
import logging
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import httpcore
import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from iphone_apns import ALERTS, APNsProvider


class APNsProviderTests(unittest.TestCase):
    def setUp(self):
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        file = Path(self.folder.name) / 'fixture.p8'
        file.write_bytes(self.key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                                 serialization.NoEncryption()))
        self.env = {'WEGOH_APNS_TEAM_ID': 'TEAM123456', 'WEGOH_APNS_KEY_ID': 'KEY1234567',
                    'WEGOH_APNS_KEY_PATH': str(file)}
        self.token = 'ab' * 32
        self.event = {'event_id': 'aaaa1111' + '1' * 24, 'kind': 'trip_invitation',
                      'trip_id': '1' * 32, 'recipient_id': 'team-' + '2' * 40, 'expires_at': 1900000000}

    def provider(self):
        with patch.dict(os.environ, self.env, clear=True), patch('iphone_apns.httpcore.ConnectionPool') as pool:
            provider = APNsProvider.from_environment()
            self.assertFalse(pool.call_args.kwargs['http1'])
            self.assertTrue(pool.call_args.kwargs['http2'])
        self.addCleanup(provider.close)
        return provider

    def test_configuration_absent_partial_and_wrong_key(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(APNsProvider.from_environment())
        with patch.dict(os.environ, {'WEGOH_APNS_TEAM_ID': 'TEAM123456'}, clear=True):
            with self.assertRaisesRegex(ValueError, 'configuration'):
                APNsProvider.from_environment()
        file = Path(self.env['WEGOH_APNS_KEY_PATH'])
        file.write_bytes(ec.generate_private_key(ec.SECP384R1()).private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
        with patch.dict(os.environ, self.env, clear=True):
            with self.assertRaisesRegex(ValueError, 'P-256'):
                APNsProvider.from_environment()

    def test_header_codec_debug_output_stays_disabled(self):
        for name in ('hpack.hpack', 'hpack.table'):
            logger = logging.getLogger(name)
            self.addCleanup(logger.setLevel, logger.level)
            logger.setLevel(logging.DEBUG)
        self.provider()
        self.assertFalse(logging.getLogger('hpack.hpack').isEnabledFor(logging.DEBUG))
        self.assertFalse(logging.getLogger('hpack.table').isEnabledFor(logging.DEBUG))

    def test_fixed_hosts_alert_and_routing_payload(self):
        provider = self.provider()
        provider.pool.request.return_value = httpcore.Response(200)
        for env, host in [('sandbox', 'api.sandbox.push.apple.com'), ('production', 'api.push.apple.com')]:
            with self.subTest(env):
                self.assertEqual(provider.send(self.token, env, **self.event), (200, '', None, None))
                args, kwargs = provider.pool.request.call_args
                self.assertEqual(args, ('POST', f'https://{host}/3/device/{self.token}'))
                headers = kwargs['headers']
                self.assertEqual(headers['apns-expiration'], str(self.event['expires_at']))
                self.assertEqual(headers['apns-priority'], '10')
                self.assertEqual(headers['apns-push-type'], 'alert')
                self.assertEqual(headers['apns-topic'], 'io.wegoh.iphone')
                self.assertEqual(headers['apns-id'], 'aaaa1111-1111-1111-1111-111111111111')
                self.assertEqual(headers['apns-collapse-id'], self.event['event_id'])
                self.assertEqual(json.loads(kwargs['content']), {
                    'aps': {'sound': 'default', 'alert': {'title': 'WegoH', 'body': '여행 초대가 왔어요.'}},
                    'wegoh': {'eventId': self.event['event_id'], 'kind': 'trip_invitation',
                              'accountId': self.event['recipient_id'], 'tripId': self.event['trip_id']}})
                self.assertEqual(set(kwargs['extensions']['timeout']), {'pool', 'connect', 'write', 'read'})

    def test_cached_es256_provider_token_and_fixed_event_bodies(self):
        provider = self.provider()
        provider.pool.request.return_value = httpcore.Response(200)
        start = int(time.time()) - 3050
        authorizations = []
        for age in (0, 2900, 3001):
            with patch('iphone_apns.time.time', return_value=start + age):
                for kind in ALERTS:
                    event = dict(self.event, kind=kind, trip_id=None)
                    provider.send(self.token, 'sandbox', **event)
                    message = json.loads(provider.pool.request.call_args.kwargs['content'])
                    self.assertNotIn('tripId', message['wegoh'])
                    self.assertEqual(message['aps']['alert']['body'], ALERTS[kind])
                auth = provider.pool.request.call_args.kwargs['headers']['authorization']
                self.assertTrue(auth.startswith('bearer '))
                authorizations.append(auth[7:])
        self.assertEqual(authorizations[0], authorizations[1])
        self.assertNotEqual(authorizations[1], authorizations[2])
        self.assertEqual(jwt.get_unverified_header(authorizations[2])['kid'], self.env['WEGOH_APNS_KEY_ID'])
        self.assertEqual(jwt.decode(authorizations[2], self.key.public_key(), algorithms=['ES256']),
                         {'iss': self.env['WEGOH_APNS_TEAM_ID'], 'iat': start + 3001})

    def test_response_error_timestamp_and_retry_hint(self):
        provider = self.provider()
        for status, data, headers, expected in [
            (410, {'reason': 'Unregistered', 'timestamp': 1600000100123}, {}, ('Unregistered', 1600000100123, None)),
            (410, {'reason': 'Unregistered', 'timestamp': True}, {}, ('Unregistered', None, None)),
            (403, {'reason': 'InvalidProviderToken', 'timestamp': 1}, {}, ('InvalidProviderToken', None, None)),
            (429, {'reason': 'TooManyRequests'}, {'Retry-After': '40'}, ('TooManyRequests', None, 40)),
            (503, ['unexpected'], {'Retry-After': '-3'}, ('', None, None)),
        ]:
            with self.subTest(status=status, data=data):
                response = httpcore.Response(status, content=json.dumps(data).encode(), headers=headers)
                response.read()
                provider.pool.request.return_value = response
                self.assertEqual(provider.send(self.token, 'production', **self.event), (status, *expected))

    def test_invalid_input_and_network_failure_exclude_credentials_from_error(self):
        provider = self.provider()
        for token, env, event in [('AB' * 32, 'sandbox', self.event), (self.token, 'other', self.event),
                                  (self.token, 'sandbox', dict(self.event, kind='unknown')),
                                  (self.token, 'sandbox', dict(self.event, recipient_id='not-an-id'))]:
            with self.assertRaises(ValueError):
                provider.send(token, env, **event)
        provider.pool.request.assert_not_called()
        provider.pool.request.side_effect = httpcore.ReadTimeout('fixture transport exception')
        with self.assertRaisesRegex(OSError, '^APNs transport unavailable$'):
            provider.send(self.token, 'sandbox', **self.event)


if __name__ == '__main__':
    unittest.main()
