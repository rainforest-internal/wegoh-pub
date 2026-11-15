"""R7 current native authority and owner-only approved original HTTP contracts."""
import hashlib
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import psycopg
import test_team_auth as fixture
from native_authorization import protect, restore


class NativeCourseOriginalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixture.TeamTests.setUpClass()

    @classmethod
    def tearDownClass(cls):
        fixture.TeamTests.tearDownClass()

    def setUp(self):
        self.api=fixture.TeamTests('test_01_jwt_verification_and_exact_hosts')
        self.api.setUp()
        self.session=self.api.login()
        self.pack=self.api.pack()
        status,_,published=self.api.publish(self.pack,self.session)
        self.assertEqual(status,201,published)
        self.checksum=published['checksum']
        self.assertEqual(self.api.approve(self.pack,self.session)[0],200)
        _,_,self.credential=self.api.pair(self.session)
        self.certificate=self.api._native_fingerprint
        self.path=f"/v1/studio/packs/{self.pack['id']}/versions/1"

    def native(self,path=None,method='GET'):
        return self.api.native(path or self.path,method=method,
            token=self.credential['accessToken'],certificate=self.certificate)

    def remove_scope(self,conn):
        row=conn.execute('SELECT protected_consent FROM native_v2_grants WHERE grant_id=%s',
                         (self.credential['grantId'],)).fetchone()
        raw=row['protected_consent'] if isinstance(row,dict) else row[0]
        consent=restore('consent',self.credential['grantId'],raw)
        consent['scopes'].remove('courses:read')
        conn.execute('UPDATE native_v2_grants SET protected_consent=%s WHERE grant_id=%s',
                     (protect('consent',self.credential['grantId'],consent),self.credential['grantId']))

    def test_owned_approved_original_has_only_pack_fields_and_bound_checksum(self):
        status,headers,body=self.native()
        self.assertEqual(status,200,body)
        self.assertEqual(set(body),{'schemaVersion','id','version','title','author','description','stops'})
        self.assertEqual(body,self.api.call(self.path,session=self.session)[2])
        raw=(self.api.state/'content'/self.checksum).read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(),self.checksum)
        self.assertEqual(json.loads(raw),body)
        self.assertEqual(headers['etag'],'"'+self.checksum+'"')
        self.assertEqual(headers['cache-control'],'private, no-store, no-transform')
        self.assertEqual(self.native('/v1/studio/packs')[2]['packs'][0]['state'],'approved')
        with psycopg.connect(self.api.dsn) as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM team_devices').fetchone()[0],0)

    def test_other_owner_is_denied_even_for_native_admin(self):
        bob=self.api.login('bob');other=self.api.pack()
        self.assertEqual(self.api.publish(other,bob,'bob')[0],201)
        self.assertEqual(self.api.approve(other,self.session)[0],200)
        path=f"/v1/studio/packs/{other['id']}/versions/1"
        self.assertEqual(self.native(path)[0],404)
        self.assertEqual(self.api.call(path,session=bob,who='bob')[0],200)

    def test_unreviewed_is_available_and_actual_rejection_or_report_is_closed_to_native(self):
        with psycopg.connect(self.api.dsn) as conn:
            conn.execute('DELETE FROM pack_reviews WHERE checksum=%s',(self.checksum,))
        self.assertEqual(self.native()[0],200)
        self.assertEqual(self.api.call(self.path,session=self.session)[0],200)
        with psycopg.connect(self.api.dsn) as conn:
            from test_course_moderation_fixture import restrict_course
            restrict_course(conn, self.checksum)
        self.assertEqual(self.native()[0],404)
        self.assertEqual(self.api.approve(self.pack,self.session)[0],200)
        self.assertEqual(self.native()[0],200)
        report=f"/v1/packs/{self.pack['id']}/versions/1/reports"
        self.assertEqual(self.api.call(report,{'reason':'rights'},'POST',session=self.session)[0],202)
        self.assertEqual(self.native()[0],404)
        self.assertEqual(self.api.call(self.path,session=self.session)[0],200)

    def test_revoked_grant_and_locked_account_are_denied(self):
        self.api.write_members([row for row in self.api.members_rows if row['email']!='alice@example.invalid'])
        self.assertEqual(self.native()[0],403)
        self.api.write_members(self.api.members_rows)
        self.assertEqual(self.native()[0],200)
        self.assertEqual(self.native('/v1/device',method='DELETE')[0],200)
        self.assertEqual(self.native()[0],401)

    def test_missing_scope_and_stale_epoch_are_denied(self):
        with psycopg.connect(self.api.dsn) as conn:self.remove_scope(conn)
        self.assertEqual(self.native()[0],403)
        with psycopg.connect(self.api.dsn) as conn:
            conn.execute('UPDATE native_v2_grants SET credential_epoch=credential_epoch+1 WHERE grant_id=%s',
                         (self.credential['grantId'],))
        self.assertEqual(self.native()[0],401)

    def test_authority_changes_after_middleware_are_rechecked_under_lock(self):
        service=self.api.module.TEAM_NATIVE_AUTHORIZATION
        original=service.lock
        for change,expected in [('scope',403),('epoch',401),('revoked',403),('account',403)]:
            def changed(conn,key):
                original(conn,key)
                if change=='scope':self.remove_scope(conn)
                elif change=='epoch':
                    conn.execute('UPDATE native_v2_grants SET credential_epoch=credential_epoch+1 WHERE grant_id=%s',
                                 (self.credential['grantId'],))
                elif change=='revoked':
                    conn.execute("UPDATE native_v2_grants SET state='REVOKED',revoked_at=%s WHERE grant_id=%s",
                                 (service.now(),self.credential['grantId']))
                else:self.api.write_members([row for row in self.api.members_rows if row['email']!='alice@example.invalid'])
            with self.subTest(change=change),patch.object(service,'lock',side_effect=changed) as lock:
                try:
                    self.assertEqual(self.native()[0],expected)
                    lock.assert_called_once()
                finally:self.api.write_members(self.api.members_rows)
            self.assertEqual(self.native()[0],200)

    def test_unregistered_methods_and_path_variants_are_404(self):
        for path in [self.path+'/',self.path+'/reuse-permission',self.path.replace('/versions/1','/versions/01'),
                     self.path.replace('/versions/1','/versions/0'),self.path.replace('/versions/1','/versions/2147483648'),
                     '/v1/studio/packs/A/versions/1','/v1/studio/packs/'+'a'*81+'/versions/1']:
            with self.subTest(path=path):self.assertEqual(self.native(path)[0],404)
        for method in ['POST','PUT','PATCH','DELETE','HEAD']:
            with self.subTest(method=method):self.assertEqual(self.native(method=method)[0],404)
        self.assertEqual(self.native(self.path+'?all=1')[0],400)

    def test_openapi_and_wire_describe_native_owner_and_immediate_publication_boundary(self):
        from team_api_docs import build_schema
        schema=build_schema(self.api.module.app,self.api.module.TEAM_AUTH)
        operation=schema['paths']['/v1/studio/packs/{pack_id}/versions/{version}']['get']
        self.assertIn({'NativeMTLS':[],'DeviceBearer':[]},operation['security'])
        self.assertEqual(operation['x-wegoh-required-scopes'],['account:read','courses:read','device:self:manage'])
        self.assertIn(fixture.NATIVE,[value['url'] for value in operation['servers']])
        self.assertIn('사전 승인 없이',operation['description'])
        self.assertIn('404',operation['responses'])
        self.assertEqual(operation['responses']['200']['content']['application/json']['schema'],
                         {'$ref':'#/components/schemas/DrivePack'})
        wire=json.loads(Path(__file__).with_name('native_access_wire.json').read_text())['courseOriginalRead']
        self.assertNotIn('allowedReviewStates', wire)
        self.assertEqual(wire['publicationPolicy'], 'immediate-with-post-publication-restrictions')
        self.assertTrue(wire['ownerOnly'])


if __name__=='__main__':unittest.main()
