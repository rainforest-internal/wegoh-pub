"""Actual private PG owner isolation; no live account/device/history mutation."""
import datetime
import unittest
import test_native_access_retention as fixtures
from native_access_management import list_owned,lookup_owned_locked,ManagementError

class NativeAccessManagementTests(unittest.TestCase):
    setUpClass=fixtures.NativeAccessRetentionTests.__dict__['setUpClass']
    connect=fixtures.NativeAccessRetentionTests.__dict__['connect']
    shutdown=fixtures.NativeAccessRetentionTests.__dict__['shutdown']
    setUp=fixtures.NativeAccessRetentionTests.setUp
    protect=fixtures.NativeAccessRetentionTests.protect
    restore=fixtures.NativeAccessRetentionTests.restore
    seed=fixtures.NativeAccessRetentionTests.seed

    @staticmethod
    def named(key):return 'vehicle:'+key

    def test_01_owner_projection_has_exact_shape_no_other_account_or_authority(self):
        a=self.seed();b=self.seed('b')
        with self.connect() as conn:
            values=list_owned(conn,a['owner'],vehicle_name=self.named,now=self.now)
            self.assertEqual(len(values),1)
            self.assertEqual(set(values[0]),{'id','name','createdAt','lastUsedAt','expiresAt','authorizationVersion'})
            self.assertEqual((values[0]['id'],values[0]['name'],values[0]['authorizationVersion']),(a['device'],'vehicle:'+a['key'],1))
            self.assertIsNone(values[0]['lastUsedAt'])
            self.assertEqual(values[0]['expiresAt'].tzinfo,datetime.timezone.utc)
            self.assertNotIn(b['device'],str(values));self.assertNotIn(a['receipt']['accessToken'],str(values))
            self.assertEqual(list_owned(conn,'team-'+'f'*40,vehicle_name=self.named,now=self.now),[])
            conn.execute('UPDATE native_v2_installations SET active_grant_id=NULL WHERE installation_key_id=%s',(a['key'],))
            self.assertEqual(list_owned(conn,a['owner'],vehicle_name=self.named,now=self.now),[])
            self.assertEqual(len(list_owned(conn,b['owner'],vehicle_name=self.named,now=self.now)),1)
            self.assertEqual(conn.execute('SELECT data FROM synthetic_history WHERE id=1').fetchone()['data'],b'preserved-original')

    def test_02_locked_owner_lookup_cannot_select_other_owner_or_installation_and_never_mutates(self):
        a=self.seed();b=self.seed('b')
        with self.connect() as conn:
            # The production core owns this exact advisory lock ordering.
            conn.execute('SELECT pg_advisory_xact_lock(%s)',(int.from_bytes(bytes.fromhex(a['key'])[:8],'big',signed=True),))
            original=conn.execute('SELECT * FROM native_v2_grants WHERE grant_id=%s',(a['grant'],)).fetchone()
            row=lookup_owned_locked(conn,a['owner'],a['device'])
            self.assertEqual(row['grant_id'],a['grant']);self.assertEqual(row,original)
            self.assertIsNone(lookup_owned_locked(conn,b['owner'],a['device']))
            self.assertIsNone(lookup_owned_locked(conn,a['owner'],b['device']))
            self.assertIsNone(lookup_owned_locked(conn,a['owner'],'invalid'))
            self.assertEqual(conn.execute('SELECT * FROM native_v2_grants WHERE grant_id=%s',(a['grant'],)).fetchone(),original)
        with self.connect(autocommit=True) as conn:
            with self.assertRaises(ManagementError):lookup_owned_locked(conn,a['owner'],a['device'])
        with self.connect() as conn:
            for bad in (True,'other',None):
                with self.assertRaises(ManagementError):list_owned(conn,bad,vehicle_name=self.named,now=self.now)

if __name__=='__main__':unittest.main()
