"""Owned temporary PostgreSQL/HTTP contracts; all people/course/location are synthetic.

Uses existing auth/room fixture methods without inheriting their test cases.
Native requests below simulate the already reviewed trusted-edge metadata boundary;
physical vehicle/Cloudflare certificate deployment is not claimed by these tests.
"""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import importlib.util
import datetime
import hashlib
import http.client
import json
import threading
import secrets
import sys
import unittest
import psycopg
from fastapi import HTTPException
from psycopg import sql
from psycopg.conninfo import make_conninfo
import test_team_auth as fixture
import test_team_rooms as room_fixture


class MissionsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixture.TeamTests.setUpClass()
        module = fixture.TeamTests.module
        app = module.app
        before = len(app.router.routes)
        app.include_router(module.TEAM_MISSIONS.trip_router())
        routes = app.router.routes[before:]
        del app.router.routes[before:]
        app.router.routes[0:0] = routes

    @classmethod
    def tearDownClass(cls):
        fixture.TeamTests.tearDownClass()

    def setUp(self):
        self.h = room_fixture.RoomTests(methodName='test_18_room_owner_member_roles_and_explicit_close')
        self.h.setUp()
        self.dsn = self.h.dsn

    def prepare(self, start=False):
        a, b, e = self.h.sessions()
        pack = self.h.pack()
        pack['stops'].append(dict(pack['stops'][0], id='second', name='Second synthetic stop', latitude=37.51, longitude=127.01))
        self.assertEqual(self.h.publish(pack, a)[0], 201)
        self.assertEqual(self.h.approve(pack, a)[0], 200)
        room = self.h.new_room(a, courseId=pack['id'], courseVersion=pack['version'], preference='country-roads')
        self.assertEqual(self.h.join(b, room['code'])[0], 200)
        path = '/rooms/' + room['id'] + '/missions'
        code, _, mission = self.h.room(path, dict(preference='country-roads'), 'POST', session=a)
        self.assertEqual(code, 201, mission)
        if start:
            for who, session in [('alice', a), ('bob', b)]:
                self.assertEqual(self.h.room(path + '/' + mission['id'] + '/participation',
                    dict(consent=True, participationRevision=0), 'PUT', who, session)[0], 200)
            mission = self.one(path, a)
            code, _, mission = self.h.room(path + '/' + mission['id'] + '/start',
                dict(revision=mission['revision']), 'POST', session=a)
            self.assertEqual(code, 200, mission)
        return a, b, e, room, path, mission

    def one(self, path, session, who='alice'):
        code, _, value = self.h.room(path, session=session, who=who)
        self.assertEqual(code, 200, value)
        return value['missions'][0]

    def report(self, path, mission, session, who='alice', event=None, checkpoint=None):
        current = self.one(path, session, who)
        body = dict(eventId=event or secrets.token_hex(16),
                    checkpoint=checkpoint or current['participation']['nextCheckpoint'],
                    participationRevision=current['participation']['revision'])
        result = self.h.room(path + '/' + mission['id'] + '/progress', body, 'POST', who, session)
        return result, body

    def device_purposes(self, session, token, purposes):
        path = "/v1/devices/" + token["deviceId"] + "/functional-permissions"
        status, _, current = self.h.call(path, session=session)
        self.assertEqual(status, 200, current)
        body = {key: value for key, value in current.items() if key not in ("deviceId", "expiresAt")}
        body["approvedPurposes"] = self.h.web_purposes(current, purposes)
        status, _, saved = self.h.call(path, body, "PUT", session=session)
        self.assertEqual(status, 200, saved)
        return saved["revision"]

    def grant_device(self, path, mission, session, allow=True):
        # pair is the fixture's proof-checked public-v1 connection/claim/exchange helper.
        _, _, token = self.h.pair(session)
        device = token["deviceId"]
        self.device_purposes(session, token, ["rooms:read", "missions:read", "missions:progress"])
        grant_path = "/v1/social" + path + "/" + mission["id"] + "/devices/" + device
        if allow:
            self.assertEqual(self.h.call(grant_path, dict(revision=0, consent=True, expiresInHours=1, participationRevision=1),
                                        "PUT", session=session)[0], 200)
        return token, grant_path

    def held_body_logout(self, path, data, session):
        # Test-owned ASGI receive barrier: proof that the handler is consuming
        # this body, then revoke the actual personal session before its tail.
        original = self.h.server.config.loaded_app
        received, release = threading.Event(), threading.Event()
        async def tracked(scope, receive, send):
            async def observed():
                message = await receive()
                if scope.get('path') == path and message.get('type') == 'http.request' and message.get('more_body') and message.get('body'):
                    received.set()
                return message
            await original(scope, observed, send)
        self.h.server.config.loaded_app = tracked
        raw = json.dumps(data).encode();middle = len(raw) // 2
        def send():
            def chunks():
                yield raw[:middle]
                if not release.wait(5):
                    raise RuntimeError('Owned body release not received')
                yield raw[middle:]
            connection = http.client.HTTPConnection('127.0.0.1', self.h.port, timeout=6)
            headers = {'Host':'web.wegoh.invalid','Content-Type':'application/json','Origin':fixture.WEB,
                       'Cookie':session['cookie'],'X-WegoH-CSRF':session['csrfToken'],
                       'Cf-Access-Jwt-Assertion':self.h.assertion(),'Transfer-Encoding':'chunked'}
            try:
                connection.request('POST', path, body=chunks(), headers=headers, encode_chunked=True)
                response = connection.getresponse();response.read();return response.status
            finally:
                connection.close()
        try:
            with ThreadPoolExecutor(max_workers=1) as pool:
                pending = pool.submit(send)
                try:
                    self.assertTrue(received.wait(4), 'Actual handler body receive not observed')
                    self.assertEqual(self.h.call('/v1/auth/session', method='DELETE', session=session)[0], 200)
                finally:
                    release.set()
                self.assertEqual(pending.result(timeout=8), 401)
        finally:
            release.set();self.h.server.config.loaded_app = original

    def test_01_exact_fields_owner_csrf_and_no_implicit_participation(self):
        a, b, e, room, path, mission = self.prepare()
        self.assertTrue(a['capabilities']['roomMissions'])
        self.assertFalse(mission['participation']['consent'])
        self.assertEqual([item['label'] for item in mission['checkpoints']], ['Synthetic stop', 'Second synthetic stop'])
        self.assertEqual(self.h.room(path, dict(preference='short-time'), 'POST', session=a)[0], 409)
        self.assertEqual(self.h.room(path, dict(preference='country-roads'), 'POST', 'bob', b)[0], 403)
        self.assertEqual(self.h.room(path, session=e, who='eve')[0], 404)
        self.assertEqual(self.h.room(path, dict(preference='country-roads'), 'POST', session=a, csrf=False)[0], 403)
        self.assertEqual(self.h.room(path + '/' + mission['id'] + '/participation',
            dict(consent=False, participationRevision=0), 'PUT', session=a)[0], 400)
        self.assertEqual(self.h.room(path, dict(preference='country-roads', score=99), 'POST', session=a)[0], 400)
        self.assertEqual(self.h.room(path, method='POST', session=a, raw=b'x' * 4097)[0], 413)
        self.assertIsNone(mission['safety']['value'])
        self.assertEqual(mission['safety']['verifiedMeasurementKinds'], [])
        self.assertFalse(mission['physicalArrivalVerified'])
        self.assertFalse(mission['routePreference']['appliedToNavigation'])
        source=self.h.state/'content'/mission['course']['checksum']
        original=source.read_bytes()
        try:
            source.write_bytes(original+b' ')
            self.assertEqual(self.h.room(path,session=a)[0],503)
        finally:
            source.write_bytes(original)
        self.held_body_logout('/v1/social' + path, dict(preference='country-roads'), a)
        with psycopg.connect(self.dsn) as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM team_missions').fetchone()[0], 1)

    def test_02_start_requires_two_explicit_participants_and_current_revision(self):
        a, b, e, room, path, mission = self.prepare()
        start = path + '/' + mission['id'] + '/start'
        self.assertEqual(self.h.room(start, dict(revision=mission['revision']), 'POST', session=a)[0], 409)
        join_path = path + '/' + mission['id'] + '/participation'
        self.assertEqual(self.h.room(join_path, dict(consent=True, participationRevision=0), 'PUT', session=a)[0], 200)
        self.assertEqual(self.h.room(join_path, method='DELETE', session=a)[0], 200)
        self.assertEqual(self.h.room(join_path, dict(consent=True, participationRevision=0), 'PUT', session=a)[0], 409)
        self.assertEqual(self.h.room(join_path, dict(consent=True, participationRevision=2), 'PUT', session=a)[0], 200)
        self.h.room(path + '/' + mission['id'] + '/participation', dict(consent=True, participationRevision=0), 'PUT', 'bob', b)
        self.assertEqual(self.h.room(start, dict(revision=mission['revision']), 'POST', session=a)[0], 409)
        current = self.one(path, a)
        self.assertEqual(self.h.room(start, dict(revision=current['revision']), 'POST', 'bob', b)[0], 403)
        self.assertEqual(self.h.room(start, dict(revision=current['revision']), 'POST', session=a)[2]['state'], 'active')
        self.assertEqual(self.h.room(path + '/' + mission['id'] + '/participation',
            dict(consent=True, participationRevision=0), 'PUT', session=a)[0], 409)

    def test_03_order_idempotency_and_cooperative_completion(self):
        a, b, e, room, path, mission = self.prepare(start=True)
        self.assertEqual(self.report(path, mission, a, checkpoint=2)[0][0], 409)
        first, body = self.report(path, mission, a)
        self.assertEqual(first[0], 200)
        self.assertEqual(self.h.room(path + '/' + mission['id'] + '/progress', body, 'POST', session=a)[0], 200)
        self.assertEqual(self.h.room(path + '/' + mission['id'] + '/progress', dict(body, checkpoint=2), 'POST', session=a)[0], 409)
        self.assertEqual(self.report(path, mission, a)[0][0], 200)
        self.assertEqual(self.one(path, a)['state'], 'active')
        self.assertEqual(self.report(path, mission, b, 'bob')[0][0], 200)
        final, last = self.report(path, mission, b, 'bob')
        self.assertEqual(final[0], 200)
        self.assertEqual(final[2]['state'], 'completed')
        self.assertIsNotNone(final[2]['completedAt'])
        self.assertEqual(self.h.room(path + '/' + mission['id'] + '/progress', last, 'POST', 'bob', b)[2]['state'], 'completed')
        self.assertEqual(self.h.room(path + '/' + mission['id'], method='DELETE', session=a)[0], 409)
        self.h.room(path + '/' + mission['id'] + '/participation', method='DELETE', who='bob', session=b)
        hidden = self.one(path, a)
        self.assertEqual(hidden['state'], 'result-withdrawn')
        self.assertEqual(hidden['participants'], [])
        self.assertIsNone(hidden['completedAt'])

    def test_04_concurrent_confirmations_change_each_participant_only_once(self):
        a, b, e, room, path, mission = self.prepare(start=True)
        revision = self.one(path, a)['participation']['revision']
        def confirm(event):
            return self.h.room(path + '/' + mission['id'] + '/progress',
                dict(eventId=event, checkpoint=1, participationRevision=revision), 'POST', session=a)[0]
        with ThreadPoolExecutor(max_workers=2) as pool:
            statuses = list(pool.map(confirm, ['1' * 32, '2' * 32]))
        self.assertEqual(sorted(statuses), [200, 409])
        self.assertEqual(self.one(path, a)['participation']['nextCheckpoint'], 2)
        with psycopg.connect(self.dsn) as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM team_mission_events').fetchone()[0], 1)

    def test_05_withdraw_leave_block_rejoin_and_expiry_never_revive_roster(self):
        a, b, e, room, path, mission = self.prepare(start=True)
        self.assertEqual(self.h.room(path + '/' + mission['id'] + '/participation', method='DELETE', who='bob', session=b)[0], 200)
        self.assertEqual(self.one(path, a)['state'], 'interrupted')
        self.assertEqual(self.h.room(path + '/' + mission['id'] + '/participation', dict(consent=True, participationRevision=0), 'PUT', 'bob', b)[0], 409)
        self.h.room('/rooms/' + room['id'] + '/leave', method='POST', who='bob', session=b)
        self.assertEqual(self.one(path, a)['state'], 'interrupted')
        self.assertEqual(self.h.join(b, room['code'])[0], 200)
        self.assertEqual(self.one(path, a)['state'], 'interrupted')
        self.assertEqual(self.report(path, mission, b, 'bob', checkpoint=1)[0][0], 403)
        self.assertEqual(self.h.room('/blocks', dict(targetId=b['user']['id']), 'POST', session=a)[0], 201)
        self.assertEqual(self.h.room(path, session=b, who='bob')[0], 404)
        with psycopg.connect(self.dsn) as conn:
            conn.execute("UPDATE team_rooms SET expires_at=now()-interval '1second' WHERE room_id=%s", (room['id'],))
        self.assertEqual(self.h.room(path, session=a)[0], 404)
        with psycopg.connect(self.dsn) as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM team_missions').fetchone()[0], 1)
            self.assertEqual(conn.execute('SELECT count(*) FROM team_mission_members').fetchone()[0], 2)

    def test_06_native_requires_separate_mission_grant_and_current_device_token(self):
        a, b, e, room, path, mission = self.prepare(start=True)
        token, grant = self.grant_device(path, mission, a, allow=False)
        native = "/v1/native/rooms/" + room["id"] + "/missions"
        status, _, permission = self.h.native("/v1/device/functional-permissions", token=token["accessToken"])
        self.assertEqual(status, 200, permission)
        revision = permission["revision"]
        data = dict(eventId="3" * 32, checkpoint=1, participationRevision=self.one(path, a)["participation"]["revision"],
                    functionalRevision=revision)
        self.assertEqual(self.h.native(native, token=token["accessToken"])[2]["missions"], [])
        self.assertEqual(self.h.native(native + "/" + mission["id"] + "/progress", data, "POST", token["accessToken"])[0], 403)
        self.assertEqual(self.h.call(grant, dict(revision=0, consent=True, expiresInHours=1, participationRevision=1), "PUT", session=a)[0], 200)
        self.assertEqual(len(self.h.native(native, token=token["accessToken"])[2]["missions"]), 1)
        self.assertEqual(self.h.native(native + "/" + mission["id"] + "/progress", data, "POST", token["accessToken"])[0], 200)
        # Keep the original stale-authority assertion at the actual public request's
        # locked revalidation boundary. Only this disposable transaction's token
        # hash is changed; rejection rolls it back and cannot advance progress.
        from unittest.mock import patch
        import team_missions
        original = team_missions.transaction_actor
        current_revision = self.one(path, a)["participation"]["revision"]
        def stale_after_outer_auth(auth, request, conn, **kwargs):
            conn.execute("UPDATE native_v2_credentials SET access_hash=%s WHERE grant_id=%s", ("0" * 64, token["grantId"]))
            return original(auth, request, conn, **kwargs)
        late = dict(eventId="4" * 32, checkpoint=2, participationRevision=current_revision, functionalRevision=revision)
        with patch.object(team_missions, "transaction_actor", side_effect=stale_after_outer_auth):
            self.assertEqual(self.h.native(native + "/" + mission["id"] + "/progress", late, "POST", token["accessToken"])[0], 401)
        self.assertEqual(self.one(path, a)["participation"]["nextCheckpoint"], 2)
        with psycopg.connect(self.dsn) as conn:
            with self.assertRaises(HTTPException) as denied:
                self.h.module.TEAM_MISSIONS.progress(conn, room["id"], mission["id"], a["user"]["id"],
                    {key: value for key, value in late.items() if key != "functionalRevision"},
                    dict(id=token["deviceId"], grantId="0" * 32))
            self.assertEqual(denied.exception.status_code, 401)
        # Existing read-only routes stay read-only; cert changes remain denied.
        self.assertEqual(self.h.native("/v1/native/rooms", {}, "POST", token["accessToken"])[0], 404)
        wrong_certificate = self.h.native(native, token=token["accessToken"], certificate="cd" * 32)
        self.assertEqual(wrong_certificate[0], 403, wrong_certificate[2])
        self.assertEqual(wrong_certificate[2]["detail"], "CERTIFICATE_BINDING_MISMATCH")
        device = token["deviceId"]
        permission_path = "/v1/devices/" + device + "/functional-permissions"
        devices_path = grant.rsplit('/', 1)[0]
        enabled = self.h.call(devices_path, session=a)[2]['devices'][0]
        self.assertTrue(enabled['progressEnabled'] and enabled['active'])
        self.assertEqual(self.h.call(permission_path + "/missions:progress", method="DELETE", session=a)[0], 200)
        disabled = self.h.call(devices_path, session=a)[2]['devices'][0]
        self.assertTrue(disabled['roomsRead'])
        self.assertFalse(disabled['progressEnabled'])
        self.assertFalse(disabled['active'])
        self.assertEqual(self.h.native(native, token=token["accessToken"])[2]["missions"], [])
        self.device_purposes(a, token, ["rooms:read", "missions:read", "missions:progress"])
        self.assertEqual(self.h.native(native, token=token["accessToken"])[2]["missions"], [])
        self.assertEqual(self.h.call(grant, dict(revision=0, consent=False, expiresInHours=1, participationRevision=0), "PUT", session=a)[0], 200)
        self.assertEqual(self.h.call(grant, dict(revision=1, consent=True, expiresInHours=1, participationRevision=1), "PUT", session=a)[0], 409)
        self.assertEqual(self.h.room(path + "/" + mission["id"] + "/participation", method="DELETE", session=a)[0], 200)
        self.assertEqual(self.h.call(grant, dict(revision=0, consent=False, expiresInHours=1, participationRevision=0), "PUT", session=a)[0], 200)
        self.assertEqual(self.h.native(native, token=token["accessToken"])[2]["missions"], [])
        self.assertEqual(self.h.call("/v1/devices/" + device, method="DELETE", session=a)[0], 200)
        self.assertEqual(self.h.native(native, token=token["accessToken"])[0], 401)

    def test_07_current_approval_account_and_ciphertext_fail_closed(self):
        from api_doc_catalog import validate_tag_registry, OPERATIONS, TAG_DESCRIPTIONS
        validate_tag_registry(OPERATIONS, TAG_DESCRIPTIONS)
        with self.assertRaisesRegex(RuntimeError, 'tag description missing'):
            validate_tag_registry({('post', '/test-only'): {'tag': 'unregistered-test-tag'}}, TAG_DESCRIPTIONS)
        a, b, e, room, path, mission = self.prepare(start=True)
        with psycopg.connect(self.dsn) as conn:
            from test_course_moderation_fixture import restrict_course
            restrict_course(conn, mission['course']['checksum'])
        unavailable=self.one(path, a)
        self.assertEqual(unavailable['state'], 'course-unavailable')
        self.assertEqual(unavailable['checkpoints'], [])
        self.assertEqual(self.report(path, mission, a, checkpoint=1)[0][0], 409)
        self.assertEqual(self.h.room(path + '/' + mission['id'] + '/participation', method='DELETE', who='bob', session=b)[0], 200)
        self.h.write_members([row for row in self.h.members_rows if row['email'] != 'alice@example.invalid'])
        self.assertEqual(self.h.room(path, session=a)[0], 403)
        self.h.write_members(self.h.members_rows)
        with psycopg.connect(self.dsn) as conn:
            raw = bytes(conn.execute('SELECT protected FROM team_missions').fetchone()[0])
            self.assertNotIn(b'country-roads', raw)
            conn.execute('UPDATE team_missions SET protected=%s', (bytes([raw[0] ^ 1]) + raw[1:],))
        self.assertEqual(self.h.room(path, session=a)[0], 503)

    def test_08_populated_mission_tables_use_actual_dynamic_encrypted_backup_restore(self):
        a, b, e, room, path, mission = self.prepare(start=True)
        self.grant_device(path, mission, a)
        self.assertEqual(self.report(path, mission, a)[0][0], 200)
        source = Path(__file__).parent / 'ops/live/backup.py'
        spec = importlib.util.spec_from_file_location('mission_backup_contract', source)
        backup = importlib.util.module_from_spec(spec);sys.modules[spec.name] = backup;spec.loader.exec_module(backup)
        work = self.h.state / ('mission-backup-' + secrets.token_hex(8));work.mkdir(mode=0o700)
        base = work / 'snapshots';base.mkdir(mode=0o700)
        tool = Path(self.h.tools['pg_ctl']).parent
        layout = backup.Layout(self.dsn, self.h.state / 'content', base, str(tool / 'pg_dump'), str(tool / 'pg_restore'))
        name = 'mission_restore_' + secrets.token_hex(6)
        with psycopg.connect(self.dsn, autocommit=True) as conn:
            conn.execute(sql.SQL('CREATE DATABASE {} TEMPLATE template0').format(sql.Identifier(name)))
        try:
            snapshot = backup.snapshot(layout)
            target = make_conninfo(self.dsn, dbname=name)
            restored = work / 'restore';restored.mkdir(mode=0o700)
            try:
                result = backup.verify_into(layout, snapshot, target, restored)
            except RuntimeError:
                expected = backup.authenticated_manifest(snapshot)['tables']
                with psycopg.connect(target) as conn:
                    actual = backup.fingerprint(conn)
                digest = lambda item: hashlib.sha256(json.dumps(item,sort_keys=True,separators=(',',':')).encode()).hexdigest()
                differences = []
                for table in sorted(set(expected) | set(actual)):
                    for field in sorted(set(expected.get(table,{})) | set(actual.get(table,{}))):
                        before, after = expected.get(table,{}).get(field), actual.get(table,{}).get(field)
                        if before != after:
                            item = dict(table=table,field=field,sourceSha256=digest(before),restoredSha256=digest(after))
                            if field in ('columns','constraints','indexes'):
                                left,right = {row[0]:row for row in (before or [])},{row[0]:row for row in (after or [])}
                                item['entries'] = [dict(name=name,sourceSha256=digest(left.get(name)),restoredSha256=digest(right.get(name)))
                                                   for name in sorted(set(left)|set(right)) if left.get(name)!=right.get(name)]
                            if table == 'team_missions' and field == 'constraints':
                                key = 'team_missions_state_check'
                                left = {row[0]: row for row in (before or [])}
                                right = {row[0]: row for row in (after or [])}
                                item['fixedStateCheckDefinition'] = dict(
                                    source=left.get(key, [None])[-1], restored=right.get(key, [None])[-1])
                            differences.append(item)
                stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
                destination = Path(__file__).resolve().parents[1] / 'docs/evidence/missions-unit' / ('backup-difference-' + stamp + '.json')
                destination.write_text(json.dumps(dict(observedAt=datetime.datetime.now(datetime.timezone.utc).isoformat(),differences=differences,
                    scope='Schema names/field digests only. No row, account, consent, key, or token contents.'),indent=2)+'\n')
                raise
            self.assertTrue(result['verified'])
            with psycopg.connect(target) as conn:
                counts = {table: conn.execute(sql.SQL('SELECT count(*) FROM {}').format(sql.Identifier(table))).fetchone()[0]
                          for table in ('team_missions', 'team_mission_members', 'team_mission_events', 'team_mission_device_grants')}
                self.assertEqual(counts, dict(team_missions=1, team_mission_members=2, team_mission_events=1, team_mission_device_grants=1))
                account, raw = conn.execute('SELECT account_id,protected FROM team_mission_members WHERE account_id=%s', (a['user']['id'],)).fetchone()
                restored_member = self.h.module.TEAM_MISSIONS.restore('member', account, mission['id'], raw)
                self.assertEqual(restored_member['completed'], 1)
            self.assertEqual(self.one(path, a)['participation']['nextCheckpoint'], 2)
        finally:
            with psycopg.connect(self.dsn, autocommit=True) as conn:
                conn.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(name)))

    def promote(self, room, *, state='active'):
        from team_trips import TeamTrips
        trip = secrets.token_hex(16)
        service = TeamTrips(self.h.module.TEAM_AUTH)
        with psycopg.connect(self.dsn) as conn:
            owner = conn.execute('SELECT owner_id FROM team_rooms WHERE room_id=%s', (room,)).fetchone()[0]
            conn.execute('INSERT INTO team_trips(trip_id,owner_id,protected,state,started_at,source_kind) '
                "VALUES(%s,%s,%s,%s,CASE WHEN %s='active' THEN now() END,'legacy_room')",
                (trip, owner, service.protect('owner:'+owner, trip, dict(title='Synthetic mission trip', description='')), state, state))
            conn.execute('UPDATE team_rooms SET trip_id=%s,code_hash=NULL,expires_at=NULL WHERE room_id=%s', (trip, room))
            for account, in conn.execute('SELECT account_id FROM team_room_members WHERE room_id=%s AND left_at IS NULL', (room,)).fetchall():
                payload = dict(state='accepted', via='link', permissions=dict(invite=False, edit=False))
                conn.execute('INSERT INTO team_trip_members(trip_id,account_id,protected) VALUES(%s,%s,%s)',
                    (trip, account, service.protect('member:'+account, trip, payload)))
        self.h.module.TEAM_AUTH.mission_service = self.h.module.TEAM_MISSIONS
        return trip, service

    def test_new_trip_mission_uses_an_approved_linked_course(self):
        owner, _, _ = self.h.sessions()
        code, _, trip = self.h.room('/trips', dict(title='Synthetic mission trip',
            description='', memberIds=[]), 'POST', session=owner)
        self.assertEqual(code, 201, trip)
        trip_path = '/trips/' + trip['id']
        mission_path = trip_path + '/missions'
        code, _, listing = self.h.room(mission_path, session=owner)
        self.assertEqual(code, 200, listing)
        self.assertFalse(listing['courseAvailable'])
        self.assertEqual(self.h.room(mission_path, dict(preference='balanced'),
            'POST', session=owner)[0], 409)

        pack = self.h.pack()
        self.assertEqual(self.h.publish(pack, owner)[0], 201)
        self.assertEqual(self.h.approve(pack, owner)[0], 200)
        self.assertEqual(self.h.room(trip_path + '/courses', dict(packId=pack['id']),
            'POST', session=owner)[0], 201)
        code, _, listing = self.h.room(mission_path, session=owner)
        self.assertEqual(code, 200, listing)
        self.assertTrue(listing['courseAvailable'])
        code, _, mission = self.h.room(mission_path, dict(preference='balanced'),
            'POST', session=owner)
        self.assertEqual(code, 201, mission)
        self.assertEqual((mission['course']['id'], mission['course']['version']),
            (pack['id'], pack['version']))
        self.assertEqual(mission['checkpoints'], [dict(ordinal=1, label=pack['stops'][0]['name'])])
        self.assertFalse(mission['participation']['consent'])

    def test_native_reads_current_trip_missions_without_a_legacy_room_lookup(self):
        owner, _, _, room, path, mission = self.prepare(start=True)
        token, _ = self.grant_device(path, mission, owner)
        trip, _ = self.promote(room['id'])
        native = '/v1/native/trips/' + trip + '/missions'
        status, _, value = self.h.native(native, token=token['accessToken'])
        self.assertEqual(status, 200, value)
        shown = value['missions'][0]
        self.assertEqual(shown['id'], mission['id'])
        self.assertEqual(shown['tripId'], trip)
        self.assertEqual(shown['contractVersion'], 1)
        self.assertNotIn('roomId', shown)
        self.assertNotIn('expiresAt', shown)
        self.assertEqual(self.h.native('/v1/native/rooms/'+room['id']+'/missions', token=token['accessToken'])[0], 409)
        self.assertEqual(self.h.native('/v1/native/trips/'+('0'*32)+'/missions', token=token['accessToken'])[0], 404)
        self.device_purposes(owner, token, ['rooms:read'])
        status, _, current = self.h.native(native, token=token['accessToken'])
        self.assertEqual(status, 200, current)
        self.assertEqual(current['missions'], [])

    def test_trip_twenty_person_roster_and_corrupt_twenty_first(self):
        from account_handles import create_account
        from private_records import VisitCipher, PrivateRecordError
        a, b, _, room, _, mission = self.prepare()
        trip, trips = self.promote(room['id'])
        service = self.h.module.TEAM_MISSIONS
        accounts = [a['user']['id'], b['user']['id']]
        with psycopg.connect(self.dsn) as conn:
            for _ in range(18):
                account = 'team-'+secrets.token_hex(20)
                create_account(conn, account, VisitCipher().protect('team-account:'+account, 'identity', dict(email='alice@example.invalid', displayName='Synthetic participant')))
                trips.save_member(conn, trip, account, 'accepted')
                accounts.append(account)
        for account in accounts:
            with psycopg.connect(self.dsn) as conn:
                service.participate(conn, room['id'], mission['id'], account, True, 0, trip_context=True)
        with psycopg.connect(self.dsn) as conn:
            current = service.snapshot(conn, room['id'], mission['id'], accounts[0], trip_context=True)
            started = service.start(conn, room['id'], mission['id'], accounts[0], current['revision'], trip_context=True)
            self.assertEqual(len(started['participants']), 20)
            self.assertEqual(started['tripId'], trip)
            self.assertNotIn('roomId', started)
            self.assertNotIn('expiresAt', started)
            self.assertEqual(started['safety']['state'], 'unavailable')
            _, row, value = service.row(conn, room['id'], mission['id'], accounts[0], trip_context=True)
            self.assertEqual(len(value['roster']), 20)
            value['roster']['team-'+secrets.token_hex(20)] = secrets.token_hex(16)
            service.save_record(conn, mission['id'], row[0], value, 'active')
            with self.assertRaises(PrivateRecordError):
                service.row(conn, room['id'], mission['id'], accounts[0], trip_context=True)

    def test_trip_planned_enrollment_finish_closes_progress_and_preserves_results(self):
        a, b, _, room, _, mission = self.prepare()
        trip, trips = self.promote(room['id'], state='planned')
        service = self.h.module.TEAM_MISSIONS
        owner = a['user']['id']
        with psycopg.connect(self.dsn) as conn:
            for account in (owner, b['user']['id']):
                service.participate(conn, room['id'], mission['id'], account, True, 0, trip_context=True)
            current = service.snapshot(conn, room['id'], mission['id'], owner, trip_context=True)
            with self.assertRaises(HTTPException) as error:
                service.start(conn, room['id'], mission['id'], owner, current['revision'], trip_context=True)
            self.assertEqual(error.exception.status_code, 409)
            trips.transition(conn, trip, owner, 'start', 1)
            started = service.start(conn, room['id'], mission['id'], owner, current['revision'], trip_context=True)
            body = dict(eventId=secrets.token_hex(16), checkpoint=1, participationRevision=started['participation']['revision'])
            service.progress(conn, room['id'], mission['id'], owner, body, trip_context=True)
            enrolling = service.create(conn, room['id'], owner, 'country-roads', trip_context=True)
            trips.transition(conn, trip, owner, 'finish', 2)
            service.withdraw_trip_context(conn, trip, room['id'])
            result = service.trip_result_reader(conn, trip, room['id'], owner)
            states = {item['id']: item['state'] for item in result['missions']}
            self.assertEqual(states[mission['id']], 'interrupted')
            self.assertEqual(states[enrolling['id']], 'cancelled')
            self.assertEqual(conn.execute('SELECT count(*) FROM team_mission_events WHERE mission_id=%s', (mission['id'],)).fetchone()[0], 1)
        with psycopg.connect(self.dsn) as conn:
            with self.assertRaises(HTTPException) as error:
                service.progress(conn, room['id'], mission['id'], owner, body, trip_context=True)
            self.assertEqual(error.exception.status_code, 409)
            withdrawn = service.participate(conn, room['id'], mission['id'], owner, False, trip_context=True)
            self.assertFalse(withdrawn['consent'])

    def test_trip_block_hook_is_permanent_and_departure_does_not_revive_grants(self):
        a, b, _, room, path, mission = self.prepare(start=True)
        trip, trips = self.promote(room['id'])
        service = self.h.module.TEAM_MISSIONS
        owner, member = a['user']['id'], b['user']['id']
        with psycopg.connect(self.dsn) as conn:
            service.on_trip_block(conn, trip, room['id'], owner, member)
            current = service.snapshot(conn, room['id'], mission['id'], owner, trip_context=True)
            self.assertEqual(current['state'], 'interrupted')
            self.assertEqual(service.trip_result_reader(conn, trip, room['id'], owner)['missions'][0]['state'], 'interrupted')
            trips.remove_member(conn, trip, member)
        with psycopg.connect(self.dsn) as conn:
            trips.save_member(conn, trip, member, 'accepted')
        with psycopg.connect(self.dsn) as conn:
            self.assertFalse(service.participants(conn, room['id'], mission['id'])[member]['eligible'])
            self.assertEqual(service.snapshot(conn, room['id'], mission['id'], owner, trip_context=True)['state'], 'interrupted')
        self.assertEqual(self.h.room(path, session=a)[0], 409)
        self.assertEqual(self.h.room(path, who='eve', session=self.h.login('eve'))[0], 404)

    def test_trip_router_isolates_mission_ids_and_has_no_room_identity(self):
        a, b, e, room, path, mission = self.prepare()
        trip, _ = self.promote(room['id'])
        url = '/v1/social/trips/'+trip+'/missions'
        code, _, current = self.h.call(url, session=a)
        self.assertEqual(code, 200, current)
        self.assertEqual(current['missions'][0]['tripId'], trip)
        self.assertNotIn('roomId', current['missions'][0])
        self.assertEqual(self.h.call(url, session=e, who='eve')[0], 404)
        other = self.h.new_room(a, courseId=mission['course']['id'], courseVersion=mission['course']['version'], preference='country-roads')
        other_trip, _ = self.promote(other['id'])
        code, _, result = self.h.call('/v1/social/trips/'+other_trip+'/missions/'+mission['id']+'/participation',
            dict(consent=True, participationRevision=0), 'PUT', session=a)
        self.assertEqual(code, 404, result)


    def test_trip_completed_reader_rechecks_consent_and_course_without_live_access(self):
        a, b, _, room, path, mission = self.prepare(start=True)
        for session, who in ((a, 'alice'), (b, 'bob')):
            self.assertEqual(self.report(path, mission, session, who)[0][0], 200)
            self.assertEqual(self.report(path, mission, session, who)[0][0], 200)
        trip, trips = self.promote(room['id'])
        service = self.h.module.TEAM_MISSIONS
        with psycopg.connect(self.dsn) as conn:
            trips.transition(conn, trip, a['user']['id'], 'finish', 1)
            result = service.trip_result_reader(conn, trip, room['id'], a['user']['id'])['missions'][0]
            self.assertEqual(result['state'], 'completed')
            self.assertEqual(len(result['participants']), 2)
            self.assertEqual(result['safety']['state'], 'unavailable')
            self.assertFalse(result['physicalArrivalVerified'])
            service.participate(conn, room['id'], mission['id'], b['user']['id'], False, trip_context=True)
            withdrawn = service.trip_result_reader(conn, trip, room['id'], a['user']['id'])['missions'][0]
            self.assertEqual(withdrawn['state'], 'result-withdrawn')
            self.assertEqual(withdrawn['participants'], [])
            self.assertIsNone(withdrawn['completedAt'])
            from test_course_moderation_fixture import restrict_course
            restrict_course(conn, mission['course']['checksum'], state='quarantined')
            self.assertEqual(service.trip_result_reader(conn, trip, room['id'], a['user']['id'])['missions'][0]['state'], 'course-unavailable')


    def test_trip_device_grant_keeps_finite_deadline_and_closes_at_finish(self):
        from datetime import datetime, timezone, timedelta
        a, _, _, room, path, mission = self.prepare(start=True)
        token, _ = self.grant_device(path, mission, a)
        trip, trips = self.promote(room['id'])
        service = self.h.module.TEAM_MISSIONS
        with psycopg.connect(self.dsn) as conn:
            before = conn.execute('SELECT expires_at FROM team_mission_device_grants WHERE mission_id=%s', (mission['id'],)).fetchone()[0]
            data = dict(revision=1, consent=True, expiresInHours=24, participationRevision=1)
            grant = service.grant(conn, room['id'], mission['id'], a['user']['id'], token['deviceId'], data, trip_context=True)
            self.assertLessEqual(grant['expiresAt'], datetime.now(timezone.utc)+timedelta(hours=24))
            self.assertGreater(before, datetime.now(timezone.utc))
            trips.transition(conn, trip, a['user']['id'], 'finish', 1)
            self.assertEqual(conn.execute('SELECT count(*) FROM team_mission_device_grants WHERE mission_id=%s', (mission['id'],)).fetchone()[0], 0)
            revoked = service.grant(conn, room['id'], mission['id'], a['user']['id'], token['deviceId'], dict(data, consent=False, revision=0), trip_context=True)
            self.assertFalse(revoked['consent'])
            with self.assertRaises(HTTPException) as error:
                service.grant(conn, room['id'], 'f'*32, a['user']['id'], token['deviceId'], dict(data, consent=False), trip_context=True)
            self.assertEqual(error.exception.status_code, 404)


if __name__ == '__main__':
    unittest.main(verbosity=2)
