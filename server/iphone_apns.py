"""Token-authenticated iPhone notification provider."""
import json
import logging
import os
import re
import time
from pathlib import Path
from threading import Lock
from uuid import UUID

import httpcore
import jwt
from cryptography.exceptions import UnsupportedAlgorithm
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec


HOSTS = {'sandbox': 'api.sandbox.push.apple.com', 'production': 'api.push.apple.com'}
ALERTS = {
    'friend_request': '친구 요청이 왔어요.',
    'friend_accepted': '친구가 되었어요.',
    'trip_invitation': '여행 초대가 왔어요.',
    'hand_raise': '손들기 요청이 왔어요.',
    'hand_raise_reaction': '손들기 응답이 왔어요.',
}


class APNsProvider:
    def __init__(self, team_id, key_id, key):
        self.team_id = team_id
        self.key_id = key_id
        self.key = key
        for name in ('hpack.hpack', 'hpack.table'):
            logger = logging.getLogger(name)
            logger.setLevel(max(logging.INFO, logger.level))
        self.pool = httpcore.ConnectionPool(http1=False, http2=True, max_connections=4, max_keepalive_connections=4)
        self._lock = Lock()
        self._token = None
        self._issued = 0

    @classmethod
    def from_environment(cls):
        team = os.environ.get('WEGOH_APNS_TEAM_ID', '')
        key_id = os.environ.get('WEGOH_APNS_KEY_ID', '')
        path = os.environ.get('WEGOH_APNS_KEY_PATH', '')
        if not any((team, key_id, path)):
            return None
        if (not re.fullmatch('[A-Z0-9]{10}', team) or not re.fullmatch('[A-Z0-9]{10}', key_id)
                or not path):
            raise ValueError('Invalid APNs provider configuration')
        try:
            key = serialization.load_pem_private_key(Path(path).read_bytes(), password=None)
        except (OSError, TypeError, ValueError, UnsupportedAlgorithm):
            raise ValueError('Invalid APNs signing key') from None
        if not isinstance(key, ec.EllipticCurvePrivateKey) or not isinstance(key.curve, ec.SECP256R1):
            raise ValueError('APNs requires a P-256 signing key')
        return cls(team, key_id, key)

    def close(self):
        self.pool.close()

    def _authorization(self):
        with self._lock:
            now = int(time.time())
            if self._token is None or not 0 <= now - self._issued < 50 * 60:
                self._token = jwt.encode({'iss': self.team_id, 'iat': now}, self.key, algorithm='ES256',
                                         headers={'kid': self.key_id})
                self._issued = now
            return 'bearer ' + self._token

    def send(self, token, environment, *, event_id, kind, trip_id, recipient_id, expires_at):
        if not re.fullmatch(r'(?:[0-9a-f]{2}){32,256}', token) or environment not in HOSTS:
            raise ValueError('Invalid APNs destination')
        if not re.fullmatch(r'[0-9a-f]{32}', event_id):
            raise ValueError('Invalid push event ID')
        if not re.fullmatch(r'team-[0-9a-f]{40}', recipient_id) or kind not in ALERTS:
            raise ValueError('Invalid push event')
        route = {'eventId': event_id, 'kind': kind, 'accountId': recipient_id}
        if trip_id is not None:
            if not re.fullmatch(r'[0-9a-f]{32}', trip_id):
                raise ValueError('Invalid push trip ID')
            route['tripId'] = trip_id
        payload = {'aps': {'alert': {'title': 'WegoH', 'body': ALERTS[kind]}, 'sound': 'default'}, 'wegoh': route}
        headers = {
            'authorization': self._authorization(), 'apns-topic': 'io.wegoh.iphone', 'apns-push-type': 'alert',
            'apns-priority': '10', 'apns-expiration': str(int(expires_at)), 'apns-id': str(UUID(hex=event_id)),
            'apns-collapse-id': event_id, 'content-type': 'application/json',
        }
        try:
            response = self.pool.request('POST', f'https://{HOSTS[environment]}/3/device/{token}', headers=headers,
                                         content=json.dumps(payload, ensure_ascii=False, separators=(',', ':')).encode(),
                                         extensions={'timeout': {'connect': 3., 'read': 5., 'write': 3., 'pool': 1.}})
        except (httpcore.NetworkError, httpcore.TimeoutException, httpcore.ProtocolError):
            raise OSError('APNs transport unavailable') from None
        if response.status == 200:
            return 200, '', None, None
        try:
            data = json.loads(response.content)
        except (ValueError, UnicodeError):
            data = None
        data = data if isinstance(data, dict) else {}
        reason = data.get('reason')
        if not isinstance(reason, str) or not re.fullmatch(r'[A-Za-z]{1,64}', reason):
            reason = ''
        timestamp = data.get('timestamp')
        if type(timestamp) is not int or timestamp < 0 or response.status != 410:
            timestamp = None
        retry = next((v for k, v in response.headers if k.lower() == b'retry-after'), b'')
        retry_after = int(retry) if re.fullmatch(rb'[0-9]{1,9}', retry) else None
        return response.status, reason, timestamp, retry_after
