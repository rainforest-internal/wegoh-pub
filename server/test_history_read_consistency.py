"""One new reader/writer regression plus two existing affected history contracts. No live state."""
import time,threading,unittest
from concurrent.futures import ThreadPoolExecutor
import psycopg
import test_team_auth as fixture
import test_team_history as history

class StableReadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):fixture.TeamTests.setUpClass()
    @classmethod
    def tearDownClass(cls):fixture.TeamTests.tearDownClass()
    def setUp(self):
        self.h=history.HistoryTests(methodName='test_01_owner_admin_and_personal_crud_capabilities');self.h.setUp();self.api=self.h.api
    def test_01_parent_shared_lock_keeps_reviewed_detail_consistent(self):
        h=self.h;a,b,_=h.users();h.make_friend(a,b);item=h.create(a);code,_,visit=h.visit(item,a);self.assertEqual(code,201);h.share(item,a,b);h.approve_text(item,a)
        before=h.detail(item,a);v=before['visits'][0];payload=dict(revision=before['revision'],place=v['place'],visitedAt=v['visitedAt'],review='Changed after actual reader',rating=5)
        service=self.api.module.TEAM_HISTORY;original=service.projection;observed=threading.Event();release=threading.Event()
        def held_projection(conn,identifier,owner):
            result=original(conn,identifier,owner)
            if identifier==item and not observed.is_set():
                observed.set()
                if not release.wait(4):raise RuntimeError('Synthetic reader barrier expired')
            return result
        try:
            service.projection=held_projection
            with ThreadPoolExecutor(max_workers=2)as pool:
                reader=pool.submit(h.call,'/history/'+item,who='bob',session=b)
                self.assertTrue(observed.wait(3))
                writer=pool.submit(h.call,'/history/'+item+'/visits/'+visit['id'],payload,'PUT',session=a)
                deadline=time.monotonic()+3;blocked=False
                while time.monotonic()<deadline:
                    with psycopg.connect(self.api.dsn)as conn:
                        blocked=bool(conn.execute("SELECT 1 FROM pg_stat_activity WHERE wait_event_type='Lock'AND cardinality(pg_blocking_pids(pid))>0 AND query LIKE %s",('%FROM team_histories%FOR UPDATE%',)).fetchone())
                    if blocked:break
                    time.sleep(.02)
                self.assertTrue(blocked,'Actual writer must wait for the detail parent share lock');self.assertFalse(writer.done())
                release.set();read=reader.result(timeout=4);self.assertEqual(read[0],200,read[2]);self.assertEqual(read[2]['visits'][0]['review'],v['review']);self.assertEqual(writer.result(timeout=4)[0],200)
        finally:release.set();service.projection=original
        self.assertEqual(h.call('/history/'+item,who='bob',session=b)[0],404)
        self.assertEqual(h.detail(item,a)['visits'][0]['review'],'Changed after actual reader')

    def test_02_existing_visit_grant_and_delete_contract(self):self.h.test_03_individual_grant_purpose_scope_and_delete()
    def test_03_existing_trace_consent_and_provenance_contract(self):self.h.test_04_trace_collection_revocation_idempotence_and_report_provenance()

if __name__=='__main__':unittest.main(verbosity=2)
