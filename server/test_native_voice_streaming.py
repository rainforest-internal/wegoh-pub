"""Sustained native trip PCM with real PostgreSQL and trusted-edge credentials."""
import json
import socket
import struct
import threading
import time
import unittest
from contextlib import contextmanager

import psycopg
from websockets.sync.client import connect
from websockets.exceptions import ConnectionClosed, InvalidStatus

from test_native_functional_voice import NativeVoiceTests


class NativeTripVoiceStreamingTests(NativeVoiceTests):
    def setUp(self):
        super().setUp()
        self.owner, self.other = self.h.login(), self.h.login('bob')
        with self.capture_credentials():
            self.first = self.factory.connect(self.owner)
            self.second = self.factory.connect(self.other, 'bob')
        created = self.expect(self.h.call('/v1/social/trips',
            dict(title='Synthetic native streaming trip', description='', memberIds=[], locationConsent=False),
            'POST', session=self.owner), 201, 'streaming trip')
        self.trip = created['id']
        self.base = '/v1/social/trips/' + self.trip
        link = self.expect(self.h.call(self.base + '/link', {}, 'POST', session=self.owner), 201, 'trip link')
        self.expect(self.h.call('/v1/social/trip-links/join',
            dict(token=link['token'], locationConsent=False), 'POST', session=self.other, who='bob'), 200, 'second account joins')
        for session, who in ((self.owner, 'alice'), (self.other, 'bob')):
            flags = {key: key == 'voice' for key in ('status', 'location', 'visits', 'music', 'voice', 'control')}
            self.expect(self.h.call(self.base + '/sharing', dict(consents=flags), 'PATCH', session=session, who=who),
                200, 'trip voice consent')
        detail = self.expect(self.h.call(self.base, session=self.owner), 200, 'trip revision')
        self.expect(self.h.call(self.base + '/start', dict(revision=detail['revision']), 'POST', session=self.owner),
            200, 'active trip')
        self.snapshots = []
        for session, credential, who in ((self.owner, self.first, 'alice'), (self.other, self.second, 'bob')):
            self.factory.approve(session, credential, ['room-voice:receive', 'room-voice:transmit'], who=who)
            path = '/v1/native/trips/' + self.trip + '/voice-permissions'
            snapshot = self.expect(self.factory.native(credential, path), 200, 'native trip permissions')
            self.assertEqual(snapshot['permissions'], dict(receiveVoice=True, transmitVoice=True))
            self.snapshots.append(snapshot)

    @contextmanager
    def capture_credentials(self):
        import test_enrollment
        from cryptography import x509
        from cryptography.x509.oid import NameOID
        import secrets

        original_issuer, original_csr = test_enrollment.SyntheticIssuer, test_enrollment.make_csr
        self.issuers, self.keys = [], []
        issuers, keys = self.issuers, self.keys

        class Issuer(original_issuer):
            def __init__(self):
                super().__init__()
                self.name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'Synthetic streaming CA ' + secrets.token_hex(8))])
                issuers.append(self)

            def response(self, csr):
                value = super().response(csr)
                self.certificate = value['certificate']
                return value

        def csr():
            key, value = original_csr()
            keys.append(key)
            return key, value

        test_enrollment.SyntheticIssuer, test_enrollment.make_csr = Issuer, csr
        try:
            yield
        finally:
            test_enrollment.SyntheticIssuer, test_enrollment.make_csr = original_issuer, original_csr

    def tls_edge(self):
        import datetime
        import ipaddress
        import secrets
        import ssl
        import uvicorn
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.x509.oid import NameOID, ExtendedKeyUsageOID
        from test_native_mtls import EdgeHTTP, EdgeWSS
        import test_team_auth as auth_fixture

        now = datetime.datetime.now(datetime.timezone.utc)
        directory = auth_fixture.TeamTests.state / ('native-stream-tls-' + secrets.token_hex(8))
        directory.mkdir(mode=0o700)

        def write(name, raw):
            path = directory / name
            with path.open('xb') as stream:
                stream.write(raw)
            path.chmod(0o600)
            return str(path)

        roots, client_files = [], []
        for index, (issuer, key, credential) in enumerate(zip(self.issuers, self.keys, (self.first, self.second))):
            ca = (x509.CertificateBuilder().subject_name(issuer.name).issuer_name(issuer.name)
                .public_key(issuer.key.public_key()).serial_number(x509.random_serial_number())
                .not_valid_before(now - datetime.timedelta(minutes=1)).not_valid_after(now + datetime.timedelta(hours=1))
                .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True).sign(issuer.key, hashes.SHA256()))
            roots.append(ca.public_bytes(serialization.Encoding.PEM))
            client_files.append((write('client' + str(index) + '.pem', issuer.certificate.encode()),
                write('client' + str(index) + '.key', key.private_bytes(serialization.Encoding.PEM,
                    serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))))
            self.assertEqual(x509.load_pem_x509_certificate(issuer.certificate.encode()).fingerprint(hashes.SHA256()).hex(),
                self.factory.certificates[credential['grantId']])
        ca_file = write('ca.pem', b''.join(roots))
        server_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'api.wegoh.invalid')])
        server_cert = (x509.CertificateBuilder().subject_name(subject).issuer_name(self.issuers[0].name)
            .public_key(server_key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(minutes=1)).not_valid_after(now + datetime.timedelta(hours=1))
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
            .add_extension(x509.SubjectAlternativeName([x509.DNSName('api.wegoh.invalid'),
                x509.IPAddress(ipaddress.ip_address('127.0.0.1'))]), critical=False).sign(self.issuers[0].key, hashes.SHA256()))
        server_pem = write('server.pem', server_cert.public_bytes(serialization.Encoding.PEM))
        private = write('server.key', server_key.private_bytes(serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
        self.tls_contexts = []
        for cert, key in client_files:
            context = ssl.create_default_context(cafile=ca_file)
            context.minimum_version = ssl.TLSVersion.TLSv1_3
            context.load_cert_chain(cert, key)
            self.tls_contexts.append(context)
        self.tls_port = auth_fixture.free_port()
        config = uvicorn.Config(self.h.module.app, host='127.0.0.1', port=self.tls_port,
            http=EdgeHTTP, ws=EdgeWSS, proxy_headers=False, access_log=False, log_level='critical',
            ssl_certfile=server_pem, ssl_keyfile=private, ssl_ca_certs=ca_file, ssl_cert_reqs=ssl.CERT_REQUIRED)
        config.load()
        config.ssl.minimum_version = ssl.TLSVersion.TLSv1_3
        config.synthetic_revoked = set()
        server = uvicorn.Server(config)
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()

        def stop():
            server.should_exit = True
            thread.join(5)
            self.assertFalse(thread.is_alive())

        self.addCleanup(stop)
        deadline = time.monotonic() + 5
        while not server.started and time.monotonic() < deadline:
            time.sleep(.02)
        self.assertTrue(server.started)

    def native_stream(self, credential, snapshot):
        use_tls = hasattr(self, 'tls_port')
        raw = socket.create_connection(('127.0.0.1', self.tls_port if use_tls else self.h.port), timeout=3)
        headers = {'Authorization': 'Bearer ' + credential['accessToken'],
            'cf-cert-sha256': self.factory.certificates[credential['grantId']],
            'cf-cert-presented': 'true', 'cf-cert-verified': 'true', 'cf-cert-revoked': 'false',
            'X-WegoH-Functional-Revision': str(snapshot['functionalRevision']),
            'X-WegoH-Room-Voice-Revision': str(snapshot['revision'])}
        try:
            if use_tls:
                from test_native_mtls import OwnedTLSConnection
                headers = {key: value for key, value in headers.items() if not key.startswith('cf-cert-')}
                index = 0 if credential is self.first else 1
                return connect('wss://api.wegoh.invalid' + self.base + '/voice', sock=raw,
                    ssl=self.tls_contexts[index], server_hostname='api.wegoh.invalid',
                    additional_headers=headers, origin=None, open_timeout=3, close_timeout=1,
                    create_connection=OwnedTLSConnection, proxy=None)
            return connect('ws://api.wegoh.invalid' + self.base + '/voice', sock=raw,
                additional_headers=headers, origin=None, open_timeout=3, close_timeout=1)
        except BaseException:
            raw.close()
            raise

    @staticmethod
    def frame(sequence):
        return struct.pack('<I', sequence) + bytes([sequence % 251]) * 640

    def exchange(self, sender, receiver, count=120):
        errors = []
        started = time.monotonic()

        def transmit():
            try:
                next_frame = started
                for sequence in range(count):
                    delay = next_frame - time.monotonic()
                    if delay > 0:
                        time.sleep(delay)
                    sender.send(self.frame(sequence))
                    next_frame += .02
                    sent_at = time.monotonic()
                    if next_frame <= sent_at:
                        next_frame = sent_at + .02
            except Exception as error:
                errors.append(error)

        thread = threading.Thread(target=transmit, daemon=True)
        thread.start()
        received = 0
        try:
            for sequence in range(count):
                self.assertEqual(receiver.recv(timeout=2), self.frame(sequence))
                received += 1
        finally:
            thread.join(3)
            print('QA_NATIVE_STREAM frames', received, 'of', count, 'elapsedMs', round((time.monotonic() - started) * 1000), flush=True)
        self.assertFalse(thread.is_alive())
        self.assertEqual(errors, [])

    def sustained_trip_exchange(self, count=120):
        with self.native_stream(self.first, self.snapshots[0]) as first, self.native_stream(self.second, self.snapshots[1]) as second:
            if hasattr(self, 'tls_port'):
                self.assertEqual(first.socket.version(), 'TLSv1.3')
                self.assertEqual(second.socket.version(), 'TLSv1.3')
            self.control(first, 'ready')
            self.control(second, 'ready')
            databases = [peer.socket.state.voice_database for peer in self.h.module.TEAM_VOICE.peers]
            first.send(json.dumps(dict(type='floor-request')))
            self.control(first, 'floor-granted')
            self.control(second, 'floor-started')
            self.exchange(first, second, count)
            first.send(json.dumps(dict(type='floor-release')))
            self.control(first, 'floor-ended')
            self.control(second, 'floor-ended')
            second.send(json.dumps(dict(type='floor-request')))
            self.control(second, 'floor-granted')
            self.control(first, 'floor-started')
            self.exchange(second, first, count)
            self.factory.approve(self.owner, self.first, ['room-voice:transmit'])
            with self.assertRaises(ConnectionClosed):
                first.recv(timeout=2)
            second.send(json.dumps(dict(type='floor-release')))
            self.control(second, 'floor-ended')
        with self.assertRaises(InvalidStatus):
            self.native_stream(self.first, self.snapshots[0])
        deadline = time.monotonic() + 2
        while self.h.module.TEAM_VOICE.peers and time.monotonic() < deadline:
            time.sleep(.02)
        self.assertFalse(self.h.module.TEAM_VOICE.peers)
        self.assertEqual(len(databases), 2)
        self.assertTrue(all(database.closed and database.connection is None for database in databases))

    def test_two_account_trip_native_pcm_at_fifty_frames_per_second(self):
        self.sustained_trip_exchange()

    def test_actual_mtls_two_account_trip_native_pcm_at_fifty_frames_per_second(self):
        self.tls_edge()
        self.sustained_trip_exchange(count=300)

    def test_missing_functional_default_retries_trip_voice_with_exclusive_graph_lock(self):
        with psycopg.connect(self.h.dsn) as conn:
            deleted = conn.execute('DELETE FROM native_functional_authorizations WHERE grant_id=%s',
                                   (self.first['grantId'],)).rowcount
        self.assertEqual(deleted, 1)
        snapshot = dict(self.snapshots[0], functionalRevision=1)
        with self.native_stream(self.first, snapshot) as first:
            self.control(first, 'ready')
            with psycopg.connect(self.h.dsn) as conn:
                self.assertEqual(conn.execute(
                    'SELECT state,revision FROM native_functional_authorizations WHERE grant_id=%s',
                    (self.first['grantId'],)).fetchone(), ('ACTIVE', 1))

    def test_reused_native_connection_rechecks_active_account_and_isolates_other_peer(self):
        with self.native_stream(self.first, self.snapshots[0]) as first, self.native_stream(self.second, self.snapshots[1]) as second:
            self.control(first, 'ready')
            self.control(second, 'ready')
            with psycopg.connect(self.h.dsn) as conn:
                conn.execute("UPDATE team_accounts SET account_status='suspended' WHERE account_id=%s",
                    (self.other['user']['id'],))
            second.send(json.dumps(dict(type='ping')))
            with self.assertRaises(ConnectionClosed):
                second.recv(timeout=2)
            first.send(json.dumps(dict(type='ping')))
            self.control(first, 'pong')
            status, _, _ = self.factory.native(self.second, '/v1/native/trips/' + self.trip + '/voice-permissions')
            self.assertEqual(status, 403)
            with self.assertRaises(InvalidStatus) as denied:
                self.native_stream(self.second, self.snapshots[1])
            self.assertEqual(denied.exception.response.status_code, 403)


def load_tests(loader, tests, pattern):
    return unittest.TestSuite(NativeTripVoiceStreamingTests(name) for name in vars(NativeTripVoiceStreamingTests)
        if name.startswith('test_'))


if __name__ == '__main__':
    unittest.main(verbosity=2)
