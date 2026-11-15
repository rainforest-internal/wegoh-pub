"""Eight actual HTTP/GCM/backup contracts on an owned synthetic PostgreSQL.
No production state, provider URL fetch, physical GPS or vehicle SDK is used.
"""
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import secrets
import sys
import unittest

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo

import test_team_auth as fixture
from test_history_remix_browser_fixture import prepare_records


class HistoryRemixTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixture.TeamTests.setUpClass()
        __import__('api_application')

    @classmethod
    def tearDownClass(cls):
        fixture.TeamTests.tearDownClass()

    def setUp(self):
        self.api = fixture.TeamTests(methodName='test_01_jwt_verification_and_exact_hosts')
        self.api.setUp()
        self.fixture = prepare_records(self.api)
        self.a, self.b = self.fixture['alice'], self.fixture['bob']
        self.meta = self.fixture['metadata']

    def call(self, path, data=None, method='GET', *, session=None, who='alice', **kwargs):
        return self.api.call(path, data, method, session=self.a if session is None else session, who=who, **kwargs)

    def history_path(self, item=None):
        return '/v1/social/history/' + (item or self.meta['courseHistoryId'])

    def permissions(self, item=None, *, bob=False):
        status, _, value = self.call(self.history_path(item) + '/remix-permissions',
            session=self.b if bob else self.a, who='bob' if bob else 'alice')
        self.assertEqual(status, 200, value)
        return value

    def reuse(self, enabled=True):
        path = '/v1/studio/packs/' + self.meta['courseId'] + '/versions/1/reuse-permission'
        current = self.call(path)[2]
        result = self.call(path, dict(revision=current['revision'], checksum=current['checksum'],
                                    consent=enabled, rightsConfirmed=enabled), 'PUT')
        self.assertEqual(result[0], 200, result[2])
        return result

    def grant(self, kind, enabled=True):
        state = self.permissions()
        old = next((v['revision'] for v in state['grants'] if v['accountId'] == self.b['user']['id'] and v['kind'] == kind), 0)
        path = next(v for v in state['paths'] if v['kind'] == kind)
        data = dict(revision=old, historyRevision=state['revision'], permissionRevision=state['permissionRevision'],
                    kind=kind, sourceFingerprint=path['fingerprint'], consent=enabled, rightsConfirmed=enabled)
        result = self.call(self.history_path() + '/remix-permissions/' + self.b['user']['id'], data, 'PUT')
        self.assertEqual(result[0], 200, result[2])
        return result

    def draft(self, kind='course', *, bob=False, item=None, **changes):
        state = self.permissions(item, bob=bob)
        source = next(v for v in state['paths'] if v['kind'] == kind)
        data = dict(revision=state['revision'], permissionRevision=state['permissionRevision'], kind=kind,
                    sourceFingerprint=source['fingerprint'], visitIds=[v['id'] for v in source.get('visits', [])], rightsConfirmed=True)
        data.update(changes)
        return self.call(self.history_path(item) + '/remix', data, 'POST',
                         session=self.b if bob else self.a, who='bob' if bob else 'alice')

    def publish(self, draft, *, bob=False, receipt=True, **changes):
        data = dict(pack=copy.deepcopy(draft['draft']), rightsConfirmed=True)
        if receipt:
            data['remixDraftId'] = draft['remixDraftId']
        data.update(changes)
        return self.call('/v1/packs', data, 'POST', session=self.b if bob else self.a, who='bob' if bob else 'alice')

    def test_01_explicit_defaults_session_csrf_role_strict_body_native_closed(self):
        state = self.permissions()
        self.assertTrue(all(v['allowed'] for v in state['paths']))
        self.assertFalse(next(v for v in state['paths'] if v['kind'] == 'course')['source']['reuseConsent'])
        self.assertTrue(self.a['capabilities']['historyRemix'])
        self.assertTrue(self.call(self.history_path())[2]['capabilities']['historyRemix'])
        self.assertTrue(all(not v['allowed'] for v in self.permissions(bob=True)['paths']))
        self.assertEqual(self.draft(bob=True)[0], 403)
        self.assertEqual(self.api.native(self.history_path() + '/remix-permissions')[0], 404)
        self.assertEqual(self.call(self.history_path() + '/remix', {}, 'POST', csrf=False)[0], 400)
        state = self.permissions()
        data = dict(revision=state['revision'], permissionRevision=state['permissionRevision'], kind='course',
                    sourceFingerprint=state['paths'][0]['fingerprint'], visitIds=[], rightsConfirmed=True)
        self.assertEqual(self.call(self.history_path() + '/remix', data, 'POST', csrf=False)[0], 403)
        self.assertEqual(self.call(self.history_path() + '/remix', dict(data, actorId=self.b['user']['id']), 'POST')[0], 400)
        self.assertEqual(self.call(self.history_path() + '/remix', method='POST', raw=b'x' * 8193)[0], 413)
        withdrawal = dict(revision=0, historyRevision=state['revision'], permissionRevision=state['permissionRevision'],
            kind='visits', sourceFingerprint=None, consent=False, rightsConfirmed=False)
        self.assertEqual(self.call(self.history_path() + '/remix-permissions/team-' + 'f' * 40, withdrawal, 'PUT')[0], 404)
        self.assertEqual(self.call('/v1/auth/session', method='DELETE')[0], 200)
        self.assertEqual(self.call(self.history_path() + '/remix', data, 'POST')[0], 401)

    def test_02_source_free_visits_are_explicit_original_order_and_metadata_only(self):
        item = self.meta['visitsHistoryId']
        state = self.permissions(item)
        self.assertFalse(next(v for v in state['paths'] if v['kind'] == 'course')['allowed'])
        visits = next(v for v in state['paths'] if v['kind'] == 'visits')['visits']
        for selection, expected in (([], 400), ([v['id'] for v in reversed(visits)], 409), ([visits[0]['id']] * 2, 400), (['f' * 32], 409)):
            self.assertEqual(self.draft('visits', item=item, visitIds=selection)[0], expected)
        self.assertEqual(self.draft('visits', item=item, rightsConfirmed=False)[0], 400)
        status, _, draft = self.draft('visits', item=item)
        self.assertEqual(status, 201, draft)
        actual = self.call(self.history_path(item))[2]['visits']
        self.assertEqual([[s[k] for k in ('name','latitude','longitude')] for s in draft['draft']['stops']],
                         [[v['place'][k] for k in ('name','latitude','longitude')] for v in actual])
        self.assertEqual(draft['source']['visitIds'], [v['id'] for v in actual])
        for stop in draft['draft']['stops']:
            self.assertEqual(set(stop), {'id','name','latitude','longitude','radiusMeters','action'})
            self.assertEqual(stop['action'], dict(type='chime', message='장소에 도착했습니다'))
            self.assertNotIn(stop['action']['message'], [v['review'] for v in actual])
        self.assertEqual(draft['draft']['version'], 1)
        self.assertNotEqual(draft['draft']['id'], self.meta['courseId'])

    def test_03_friend_course_and_visit_grants_are_distinct_from_read_and_source(self):
        self.reuse(True)
        self.assertEqual(self.draft(bob=True)[0], 403)
        self.grant('course')
        self.assertEqual(self.draft(bob=True)[0], 201)
        self.assertEqual(self.draft('visits', bob=True)[0], 403)
        self.grant('visits')
        self.assertEqual(self.draft('visits', bob=True)[0], 201)
        self.grant('course', False)
        self.assertEqual(self.draft(bob=True)[0], 403)
        self.assertEqual(self.draft('visits', bob=True)[0], 201)
        own = self.call(self.history_path())[2]
        self.assertTrue(own['access']['photos'])  # Owner's private access is unchanged.
        shared = self.call(self.history_path(), session=self.b, who='bob')[2]
        self.assertFalse(shared['access']['photos']); self.assertFalse(shared['access']['trace'])

    def test_04_source_withdraw_invalidates_history_and_old_receipt_publication(self):
        self.reuse(True); self.grant('course')
        status, _, draft = self.draft(bob=True); self.assertEqual(status, 201, draft)
        with self.api.websocket(self.b, who='bob') as socket:
            self.assertEqual(json.loads(socket.recv(timeout=3))['type'], 'snapshot')
            self.reuse(False)
            event = json.loads(socket.recv(timeout=3))
            self.assertEqual(event['type'], 'invalidate'); self.assertIn('history', event['resources'])
            self.assertNotIn(self.meta['courseHistoryId'], json.dumps(event))
            self.assertNotIn('latitude', json.dumps(event))
        self.assertIn(self.publish(draft, bob=True)[0], (403, 409))
        self.assertEqual(self.publish(draft, bob=True, receipt=False)[0], 403)
        self.assertIn(self.call('/v1/social/remix-drafts/' + draft['remixDraftId'], session=self.b, who='bob')[0], (403, 409))
        self.reuse(True)
        self.assertIn(self.publish(draft, bob=True)[0], (403, 409))  # Re-enabling never restores an old fingerprint.

    def test_05_current_read_review_friend_and_history_change_revoke_receipts(self):
        for boundary in ('read', 'review', 'friend', 'record'):
            with self.subTest(boundary=boundary):
                if boundary != 'read': self.setUp()
                self.reuse(True); self.grant('visits')
                status, _, draft = self.draft('visits', bob=True); self.assertEqual(status, 201, draft)
                path = self.history_path()
                if boundary == 'read':
                    self.assertEqual(self.call(path + '/shares/' + self.b['user']['id'], method='DELETE')[0], 200)
                elif boundary == 'review':
                    record = self.call(path)[2]
                    self.assertEqual(self.call(path + '/review-request', dict(revision=record['revision'], consent=False), 'PATCH')[0], 200)
                elif boundary == 'friend':
                    self.assertEqual(self.call('/v1/social/blocks', dict(targetId=self.b['user']['id']), 'POST')[0], 201)
                else:
                    record = self.call(path)[2]
                    update = {key: record[key] for key in ('revision','title','startedAt','endedAt','courseId','courseVersion')}
                    update['title'] = '변경된 합성 기록'
                    self.assertEqual(self.call(path, update, 'PUT')[0], 200)
                self.assertIn(self.publish(draft, bob=True)[0], (403, 404, 409))

    def test_06_publish_and_reedit_retain_current_server_bound_receipt(self):
        status, _, draft = self.draft(); self.assertEqual(status, 201, draft)
        status, _, published = self.publish(draft)
        self.assertEqual(status, 201, published); self.assertEqual(published['state'], 'approved')
        self.assertNotIn('historyId', published['source'])
        self.assertEqual(self.publish(draft)[0], 200)
        self.assertEqual(self.publish(draft, receipt=False)[0], 403)
        changed = copy.deepcopy(draft['draft']); changed['id'] = 'not-the-reserved-course'
        self.assertEqual(self.publish(draft, pack=changed)[0], 409)
        path = '/v1/studio/packs/' + draft['draft']['id'] + '/versions/1/remix-source'
        status, _, restored = self.call(path)
        self.assertEqual(status, 200, restored); self.assertEqual(restored['remixDraftId'], draft['remixDraftId'])
        self.assertEqual(self.call(path, session=self.b, who='bob')[0], 404)
        self.assertEqual(self.call('/v1/studio/packs/' + self.meta['courseId'] + '/versions/1/remix-source')[0], 404)
        edited = copy.deepcopy(draft['draft']); edited['version'] = 2; edited['title'] = '편집한 새 버전'
        self.assertEqual(self.publish(draft, pack=edited)[0], 201)

    def test_07_current_typed_seven_operations_strict_bodies_and_native_closed(self):
        status, _, schema = self.call('/developer/openapi.json')
        self.assertEqual(status, 200, schema)
        from api_doc_history_remix import OPS, BODY
        self.assertEqual(len(OPS), 7)
        for (method, path), authored in OPS.items():
            operation = schema['paths'][path][method]
            self.assertFalse(operation['x-wegoh-native-access'])
            self.assertTrue(operation['summary']); self.assertIn('17 기록 재창작', operation['tags'])
            if (method, path) in BODY:
                actual = operation['requestBody']['content']['application/json']['schema']
                self.assertFalse(actual['additionalProperties'])
        self.assertIn('historyRemix', schema['components']['schemas']['Capabilities']['properties'])
        self.assertIn('remixDraftId', schema['paths']['/v1/packs']['post']['requestBody']['content']['application/json']['schema']['properties'])
        export = os.environ.get('WEGOH_HISTORY_REMIX_SCHEMA_EXPORT')
        if export:
            target = Path(export); folder = fixture.ROOT / 'docs/evidence/history-remix-unit'
            if target.parent.resolve() != folder or target.exists() or target.is_symlink():
                raise RuntimeError('Explicit fresh public synthetic schema evidence path required')
            target.write_text(json.dumps(schema, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

    def test_08_three_encrypted_populated_tables_preserve_actual_backup_restore(self):
        self.reuse(True); self.grant('course')
        status, _, draft = self.draft(bob=True); self.assertEqual(status, 201, draft)
        tables = ('team_course_reuse_permissions','team_history_remix_permissions','team_remix_drafts')
        with psycopg.connect(self.api.dsn) as conn:
            before = {name: conn.execute(sql.SQL('SELECT count(*) FROM {}').format(sql.Identifier(name))).fetchone()[0] for name in tables}
            self.assertTrue(all(before.values()))
            for name in tables:
                protected = bytes(conn.execute(sql.SQL('SELECT protected FROM {} LIMIT 1').format(sql.Identifier(name))).fetchone()[0])
                self.assertNotIn(draft['remixDraftId'].encode(), protected)
                self.assertNotIn(b'rightsConfirmed', protected)
            conn.execute((fixture.ROOT / 'server/schema.sql').read_text())
            self.assertEqual(before, {name: conn.execute(sql.SQL('SELECT count(*) FROM {}').format(sql.Identifier(name))).fetchone()[0] for name in tables})
        source = fixture.ROOT / 'server/ops/live/backup.py'
        spec = importlib.util.spec_from_file_location('remix_backup_contract', source)
        backup = importlib.util.module_from_spec(spec); sys.modules[spec.name] = backup; spec.loader.exec_module(backup)
        work = self.api.state / ('remix-backup-' + secrets.token_hex(8)); work.mkdir(mode=0o700)
        base = work / 'snapshots'; base.mkdir(mode=0o700)
        tool = Path(self.api.tools['pg_ctl']).parent
        layout = backup.Layout(self.api.dsn, self.api.state / 'content', base, str(tool / 'pg_dump'), str(tool / 'pg_restore'))
        name = 'remix_restore_' + secrets.token_hex(6)
        with psycopg.connect(self.api.dsn, autocommit=True) as conn:
            conn.execute(sql.SQL('CREATE DATABASE {} TEMPLATE template0').format(sql.Identifier(name)))
        try:
            snapshot = backup.snapshot(layout)
            target = make_conninfo(self.api.dsn, dbname=name)
            restored = work / 'restore'; restored.mkdir(mode=0o700)
            result = backup.verify_into(layout, snapshot, target, restored)
            self.assertTrue(result['verified'])
            with psycopg.connect(target) as conn:
                self.assertEqual(before, {table: conn.execute(sql.SQL('SELECT count(*) FROM {}').format(sql.Identifier(table))).fetchone()[0] for table in tables})
        finally:
            with psycopg.connect(self.api.dsn, autocommit=True) as conn:
                conn.execute('SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname=%s', (name,))
                conn.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(name)))


if __name__ == '__main__':
    unittest.main(verbosity=2)
