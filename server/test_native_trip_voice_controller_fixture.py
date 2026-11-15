"""Owned trip-controller TLS edge; no operating profile, credential or microphone."""
import asyncio
import hashlib
import json
import os
import re
import socket
import ssl
import threading
import time

import uvicorn
from uvicorn.protocols.http.h11_impl import H11Protocol
from uvicorn.protocols.websockets.websockets_sansio_impl import WebSocketsSansIOProtocol
from websockets.sync.client import connect

from test_native_social_tls_fixture import NativeSocialTlsFixture, strict_object


class NativeTripVoiceControllerFixture(NativeSocialTlsFixture):
    def __enter__(self):
        self.previous_voice = os.environ.get('WEGOH_VOICE_ENABLED')
        os.environ['WEGOH_VOICE_ENABLED'] = '1'
        self.case = None
        self.voice_peer = None
        super().__enter__()
        class Edge:
            def connection_made(inner, transport):
                super().connection_made(transport)
                tls = transport.get_extra_info('ssl_object')
                der = tls.getpeercert(binary_form=True)
                fingerprint = hashlib.sha256(der).hexdigest().encode() if der else None
                application = inner.app

                async def verified(scope, receive, send):
                    scope = dict(scope)
                    headers = [(k, v) for k, v in scope['headers']
                               if k.lower() not in {b'host', b'cf-cert-sha256', b'cf-cert-presented',
                                                    b'cf-cert-verified', b'cf-cert-revoked'}]
                    headers.append((b'host', b'api.wegoh.invalid'))
                    if fingerprint:
                        headers.extend([(b'cf-cert-sha256', fingerprint), (b'cf-cert-presented', b'true'),
                                        (b'cf-cert-verified', b'true'), (b'cf-cert-revoked', b'false')])
                    scope['headers'] = headers
                    await application(scope, receive, send)

                inner.app = verified

        class HTTP(Edge, H11Protocol):
            pass

        class WSS(Edge, WebSocketsSansIOProtocol):
            pass

        self.edge_port = self._free_port()
        config = uvicorn.Config(self.application, host='127.0.0.1', port=self.edge_port, interface='asgi3',
                                http=HTTP, ws=WSS, proxy_headers=False, access_log=False, log_level='critical',
                                ssl_certfile=str(self.h.state / 'social-server.pem'),
                                ssl_keyfile=str(self.h.state / 'social-server.key'),
                                ssl_ca_certs=str(self.h.state / 'social-ca.pem'), ssl_cert_reqs=ssl.CERT_OPTIONAL)
        config.load()
        config.ssl.minimum_version = config.ssl.maximum_version = ssl.TLSVersion.TLSv1_3
        self.edge = uvicorn.Server(config)
        self.edge_thread = threading.Thread(target=self.edge.run, daemon=True)
        self.edge_thread.start()
        deadline = time.monotonic() + 5
        while not self.edge.started and time.monotonic() < deadline:
            time.sleep(.02)
        if not self.edge.started:
            raise RuntimeError('Owned trip voice TLS edge did not start')
        return self

    @staticmethod
    def _free_port():
        with socket.socket() as probe:
            probe.bind(('127.0.0.1', 0))
            return probe.getsockname()[1]

    def seed_social(self):
        def call(path, body=None, method='GET', session=None, who='alice', expected=200):
            status, _, value = self.h.call(path, body, method, session=session or self.owner, who=who)
            if status != expected:
                raise AssertionError('Owned trip fixture seed rejected: ' + path + ' status=' + str(status))
            return value
        created = call('/v1/social/trips', dict(title='Synthetic held controller trip', description='',
                                               memberIds=[], locationConsent=False), 'POST', expected=201)
        self.trip_id = created['id']
        self.trip_path = '/v1/social/trips/' + self.trip_id
        link = call(self.trip_path + '/link', {}, 'POST', expected=201)
        call('/v1/social/trip-links/join', dict(token=link['token'], locationConsent=False), 'POST', self.peer, 'bob')
        detail = call(self.trip_path)
        call(self.trip_path + '/start', dict(revision=detail['revision']), 'POST')
        self.set_participation(False)
        snapshot = call(self.trip_path + '/voice-participation', session=self.peer, who='bob')
        call(self.trip_path + '/voice-participation', dict(participating=True,
             memberJoinedAt=snapshot['memberJoinedAt'], revision=snapshot['revision']), 'PATCH', self.peer, 'bob')

    def set_participation(self, value):
        path = self.trip_path + '/voice-participation'
        status, _, snapshot = self.h.call(path, session=self.owner)
        if status != 200:
            raise AssertionError('Owned voice participation read rejected')
        status, _, _ = self.h.call(path, dict(participating=value, memberJoinedAt=snapshot['memberJoinedAt'],
                                             revision=snapshot['revision']), 'PATCH', session=self.owner)
        if status != 200:
            raise AssertionError('Owned voice participation change rejected')

    def begin_case(self, name, *, hold_patch=False, hold_ready=False):
        self.set_participation(False)
        case = dict(name=name, patches=0, patch_bodies=0, requests=0, pcm=0, ready=threading.Event(),
                    patch=threading.Event(), release_patch=threading.Event(), release_ready=threading.Event())
        if not hold_patch:
            case['release_patch'].set()
        if not hold_ready:
            case['release_ready'].set()
        self.case = case
        return case

    async def application(self, scope, receive, send):
        path, kind = scope.get('path', ''), scope['type']
        if kind == 'http' and scope['method'] == 'POST' and (path == '/v1/connections' or
                re.fullmatch(r'/v1/connections/[a-f0-9]{32}/claim', path) or path == '/v1/connections/recover'):
            raw = b''
            while True:
                event = await receive()
                raw += event.get('body', b'')
                if len(raw) > 16384:
                    raise ValueError('Owned enrollment body too large')
                if not event.get('more_body'):
                    break
            body = strict_object(raw)
            if path == '/v1/connections':
                status, value = self.service.begin(body)
                self.approve_pending(value['userCode'])
            elif path.endswith('/claim'):
                status, value = self.service.claim(path.split('/')[3], body)
            else:
                status, value = self.service.recover(body)
            self.observations.append(dict(stage='owned-controller-enrollment',
                                          operation='begin' if path == '/v1/connections' else 'claim', status=status))
            await send(dict(type='http.response.start', status=status,
                            headers=[(b'content-type', b'application/json')]))
            await send(dict(type='http.response.body', body=json.dumps(value).encode()))
            return
        case = self.case
        voice = kind == 'websocket' and path == self.trip_path + '/voice'
        patch = bool(case and kind == 'http' and scope['method'] == 'PATCH' and
                     path == '/v1/native/trips/' + self.trip_id + '/voice-participation')
        patch_body_seen = False

        async def observed_send(event):
            nonlocal patch_body_seen
            if kind == 'http' and event['type'] == 'http.response.start':
                operation = {'/v1/device-sessions/exchange': 'exchange', '/v1/account': 'account',
                             '/v1/device/functional-permissions': 'functional'}.get(path, 'native-api')
                self.observations.append(dict(stage='owned-controller-http', operation=operation,
                                              status=event['status']))
                if patch:
                    case['patches'] += 1
            if patch and event['type'] == 'http.response.body':
                case['patch_bodies'] += 1
                if not patch_body_seen:
                    patch_body_seen = True
                    case['patch'].set()
                    if not await asyncio.to_thread(case['release_patch'].wait, 8):
                        raise TimeoutError('Owned participation response hold')
            if voice and event['type'] == 'websocket.send' and event.get('text'):
                value = json.loads(event['text'])
                if value.get('type') == 'ready':
                    case['ready'].set()
                    if not await asyncio.to_thread(case['release_ready'].wait, 8):
                        raise TimeoutError('Owned voice ready hold')
            await send(event)

        async def observed_receive():
            event = await receive()
            if voice and event['type'] == 'websocket.receive':
                if event.get('bytes') is not None:
                    case['pcm'] += 1
                    raise AssertionError('Controller request probe must never capture PCM')
                value = json.loads(event.get('text', '{}'))
                if value.get('type') == 'floor-request':
                    case['requests'] += 1
                    # Observe the real session request without granting any microphone lease.
                    event = dict(type='websocket.receive', text='{"type":"ping"}')
            return event

        await self.h.module.app(scope, observed_receive, observed_send)

    def start_other_floor(self):
        raw = socket.create_connection(('127.0.0.1', self.h.port), timeout=3)
        self.voice_peer = connect('ws://web.wegoh.invalid' + self.trip_path + '/voice', sock=raw,
                                  origin='https://web.wegoh.invalid', open_timeout=3, close_timeout=1,
                                  additional_headers={'Cf-Access-Jwt-Assertion': self.h.assertion('bob'),
                                                      'Cookie': self.peer['cookie']})
        if json.loads(self.voice_peer.recv(timeout=3))['type'] != 'ready':
            raise AssertionError('Owned peer not ready')
        self.voice_peer.send('{"type":"floor-request"}')
        if json.loads(self.voice_peer.recv(timeout=3))['type'] != 'floor-granted':
            raise AssertionError('Owned peer not granted')

    def end_other_floor(self):
        self.voice_peer.send('{"type":"floor-release"}')
        if json.loads(self.voice_peer.recv(timeout=3))['type'] != 'floor-ended':
            raise AssertionError('Owned peer floor not ended')
        self.voice_peer.close()
        self.voice_peer = None

    def __exit__(self, *args):
        if self.case:
            self.case['release_patch'].set()
            self.case['release_ready'].set()
        if self.voice_peer:
            self.voice_peer.close()
        if hasattr(self, 'edge'):
            self.edge.should_exit = True
            self.edge_thread.join(5)
            if self.edge_thread.is_alive():
                raise RuntimeError('Owned voice edge did not stop')
        try:
            return super().__exit__(*args)
        finally:
            if self.previous_voice is None:
                os.environ.pop('WEGOH_VOICE_ENABLED', None)
            else:
                os.environ['WEGOH_VOICE_ENABLED'] = self.previous_voice
