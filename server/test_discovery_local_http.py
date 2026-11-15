"""Actual owned PrivatePG Browser seam; road metrics remain explicit fixtures."""
from datetime import datetime, timezone
from unittest.mock import patch
import unittest
import psycopg
import test_team_auth as fixture
import test_discovery_local as caller_fixture
query=caller_fixture.query

class DiscoveryLocalHttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixture.TeamTests.setUpClass()
        __import__('api_application')
    @classmethod
    def tearDownClass(cls):fixture.TeamTests.tearDownClass()
    def setUp(self):
        self.h=fixture.TeamTests('test_01_jwt_verification_and_exact_hosts');self.h.setUp()
        self.owner=self.h.login()
        factory=caller_fixture.LocalDiscoveryTests('test_all_candidates_before_limit_distance_duration_and_unreachable');factory.setUp()
        self.local,self.provider=factory.service,factory.provider
    def expect(self,result,status):
        self.assertEqual(result[0],status,result[2]);return result[2]
    def test_withdrawn_account_and_expired_session_before_dispatch_do_not_call_provider(self):
        auth=self.h.module.TEAM_AUTH;path='/v1/discovery/places/query'
        with patch.object(auth,'local_discovery',self.local):
            original=auth.rate
            def withdraw(*args,**kwargs):
                original(*args,**kwargs)
                self.h.write_members([row for row in self.h.members_rows if row['email']!='alice@example.invalid'])
            try:
                with patch.object(auth,'rate',side_effect=withdraw):
                    self.expect(self.h.call(path,query(),'POST',session=self.owner),403)
                self.assertEqual(self.provider.calls,[])
            finally:self.h.write_members(self.h.members_rows)
            def expires(*args,**kwargs):
                original(*args,**kwargs)
                with psycopg.connect(self.h.module.DSN) as conn:
                    conn.execute("UPDATE studio_sessions SET expires_at=now()-interval '1 second' WHERE creator_id=%s",(self.owner['user']['id'],))
            with patch.object(auth,'rate',side_effect=expires):
                self.expect(self.h.call(path,query(),'POST',session=self.owner),401)
            self.assertEqual(self.provider.calls,[])
    def test_browser_location_opt_in_and_provider_failures_are_not_successful_records(self):
        auth=self.h.module.TEAM_AUTH;path='/v1/discovery/places/query'
        with patch.object(auth,'local_discovery',self.local):
            location=dict(kind='browser-location',consent=False,position=dict(latitude=37.5,longitude=127,accuracyMeters=10,capturedAt=datetime.now(timezone.utc).isoformat()))
            self.expect(self.h.call(path,query(anchor=location),'POST',session=self.owner),400)
            self.assertEqual(self.provider.calls,[])
            for code,status in [('ROAD_PROVIDER_UNAVAILABLE',503),('ROAD_PROVIDER_TIMEOUT',504),('ROAD_PROVIDER_RESPONSE_INVALID',502)]:
                self.provider.error=code
                result=self.expect(self.h.call(path,query(),'POST',session=self.owner),status)
                self.assertNotIn('items',result)
            self.assertEqual(len(self.provider.calls),3)
            with psycopg.connect(self.h.module.DSN) as conn:
                self.assertEqual(conn.execute('SELECT count(*) FROM team_room_signals').fetchone()[0],0)

    def test_browser_auth_only_closed_road_projection_no_records_and_expiry_before_return(self):
        auth=self.h.module.TEAM_AUTH;path='/v1/discovery/places/query'
        with patch.object(auth,'local_discovery',self.local):
            self.expect(self.h.call(path,query(),'POST'),401)
            self.expect(self.h.call(path,query(),'POST',session=self.owner,csrf=False),403)
            self.expect(self.h.call(path,query(),'POST',session=self.owner,origin='https://wrong.invalid'),403)
            self.expect(self.h.native(path,query(),'POST'),404)
            self.assertEqual(self.provider.calls,[])
            tables=('visited_places','team_histories','team_history_trace_batches','team_room_signals')
            with psycopg.connect(self.h.module.DSN) as conn:before={t:conn.execute('SELECT count(*) FROM '+t).fetchone()[0] for t in tables}
            result=self.h.call(path,query(),'POST',session=self.owner)
            value=self.expect(result,200);self.assertIn('no-store',result[1]['cache-control']);self.assertEqual(len(value['items']),2)
            # Optional author-owned public/synthetic DTO capture for Browser QA.
            import os
            output=os.environ.get('WEGOH_TEST_DISCOVERY_DTO_OUTPUT')
            if output:
                from pathlib import Path
                import json
                Path(output).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
            self.assertEqual(len(self.provider.calls),1)
            bob=self.h.login('bob')
            self.expect(self.h.call(path,query(),'POST',session=bob,who='bob'),200)
            self.expect(self.h.call(path,query(functionalRevision=1),'POST',session=self.owner),400)
            self.assertEqual(len(self.provider.calls),2)
            with psycopg.connect(self.h.module.DSN) as conn:after={t:conn.execute('SELECT count(*) FROM '+t).fetchone()[0] for t in tables}
            self.assertEqual(before,after)
            original=self.local.query
            def expires(*args,**kwargs):
                answer=original(*args,**kwargs)
                with psycopg.connect(self.h.module.DSN) as conn:
                    conn.execute("UPDATE studio_sessions SET expires_at=now()-interval '1 second' WHERE creator_id=%s",(self.owner['user']['id'],))
                return answer
            with patch.object(self.local,'query',side_effect=expires):
                self.expect(self.h.call(path,query(),'POST',session=self.owner),401)
        # Absence is explicit preparation; legacy straight-line query still works.
        self.owner=self.h.login()
        with patch.object(auth,'local_discovery',None):
            self.assertEqual(self.expect(self.h.call(path,query(),'POST',session=self.owner),503),dict(code='PREPARATION'))
            old=dict(anchor=query()['anchor'],radiusMeters=1,limit=1)
            value=self.expect(self.h.call('/v1/discovery/rest-stops/query',old,'POST',session=self.owner),200)
            self.assertEqual(value['basis'],'great-circle-straight-line')

if __name__=='__main__':unittest.main()
