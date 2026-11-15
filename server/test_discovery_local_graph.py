"""Explicit test-owned engine + real Browser PrivatePG HTTP, no operating service.

The runner supplies exact pinned existing graph/catalog paths. No download or
implicit external provider is used. Test location is selected synthetic/public map.
"""
import os,unittest
from unittest.mock import patch
import psycopg
import test_team_auth as fixture

class LocalGraphHttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path=os.environ.get('WEGOH_TEST_DISCOVERY_LOCAL_CONFIG')
        if not path:raise unittest.SkipTest('Pinned owned road graph/catalog fixture required; set WEGOH_TEST_DISCOVERY_LOCAL_CONFIG to run this integration test')
        previous=os.environ.get('WEGOH_DISCOVERY_LOCAL_CONFIG')
        os.environ['WEGOH_DISCOVERY_LOCAL_CONFIG']=path
        try:fixture.TeamTests.setUpClass();__import__('api_application')
        finally:
            if previous is None:os.environ.pop('WEGOH_DISCOVERY_LOCAL_CONFIG',None)
            else:os.environ['WEGOH_DISCOVERY_LOCAL_CONFIG']=previous
    @classmethod
    def tearDownClass(cls):fixture.TeamTests.tearDownClass()
    def test_actual_selected_region_all_candidates_distance_duration_and_explicit_room_proposal(self):
        h=fixture.TeamTests('test_01_jwt_verification_and_exact_hosts');h.setUp();owner=h.login()
        local=h.module.TEAM_AUTH.local_discovery
        self.assertIsNotNone(local)
        body=dict(anchor=dict(kind='selected-place',place=dict(id='synthetic-public-anchor',provider='map',name='Synthetic public map anchor',address='',latitude=37.5618896,longitude=126.97622)),bounds=dict(west=126.975,south=37.565,east=126.98,north=37.57),category='restaurant',limit=3)
        def expect(result,status):self.assertEqual(result[0],status,result[2]);return result[2]
        original_matrix=local.provider.matrix
        def observed_matrix(*args,**kwargs):
            from road_provider import RoadProviderError
            try:return original_matrix(*args,**kwargs)
            except RoadProviderError as error:
                print('OWN_GRAPH_PROVIDER_CODE',error.code,flush=True)
                raise
        with patch.object(local.provider,'matrix',side_effect=observed_matrix) as matrix:
            expect(h.call('/v1/discovery/places/query',body,'POST',session=owner,csrf=False),403)
            expect(h.call('/v1/discovery/places/query',dict(body,accountId='invented'),'POST',session=owner),400)
            self.assertEqual(matrix.call_count,0)
            tables=('visited_places','team_histories','team_history_trace_batches','team_room_signals')
            with psycopg.connect(h.module.DSN)as conn:before={t:conn.execute('SELECT count(*) FROM '+t).fetchone()[0]for t in tables}
            response=expect(h.call('/v1/discovery/places/query',body,'POST',session=owner),200)
            self.assertEqual(response['counts']['eligible'],187)
            self.assertEqual(len(matrix.call_args.args[1]),187)
            self.assertEqual(response['counts']['returned'],3)
            self.assertTrue(all(row['road']['reachable'] for row in response['items']))
            self.assertEqual(sorted(row['road']['distanceMeters']for row in response['items']),[row['road']['distanceMeters']for row in response['items']])
            self.assertEqual(response['source']['sourceSha256'],'93a7722f88e761f0ea162f81d227765ef3371b403e9bde812e885bde7852f946')
            self.assertEqual(response['source']['dataAsOf'],dict(value='2026-10-29T21:21:26Z',precision='datetime'))
            duration=expect(h.call('/v1/discovery/places/query',dict(body,order='duration'),'POST',session=owner),200)
            self.assertEqual(sorted(row['road']['estimatedDurationSeconds']for row in duration['items']),[row['road']['estimatedDurationSeconds']for row in duration['items']])
            self.assertFalse(duration['graph']['liveTraffic']);self.assertIsNone(duration['unknown']['currentPrice'])
            with psycopg.connect(h.module.DSN)as conn:after={t:conn.execute('SELECT count(*) FROM '+t).fetchone()[0]for t in tables}
            self.assertEqual(before,after)
        # Search/select did not create a room proposal. Only the following explicit
        # Browser room consent and separate signal operation can publish it.
        room=expect(h.call('/v1/social/rooms',dict(name='Synthetic road selection',courseId=None,courseVersion=None,expiresInHours=1),'POST',session=owner),201)['id']
        flags={key:key in ('status','location')for key in ('status','location','visits','music','voice','control')}
        expect(h.call('/v1/social/rooms/'+room+'/consents',dict(consents=flags),'PATCH',session=owner),200)
        place=response['items'][0]['place']
        signal=expect(h.call('/v1/social/rooms/'+room+'/signals',dict(kind='rest',destination={k:place[k]for k in ('name','latitude','longitude')}),'POST',session=owner),201)
        detail=expect(h.call('/v1/social/rooms/'+room,session=owner),200)
        saved=next(row for row in detail['signals']if row['id']==signal['id'])
        self.assertEqual(saved['destination']['latitude'],place['latitude']);self.assertEqual(saved['destination']['longitude'],place['longitude'])
        self.assertTrue(saved['destination']['name']) # Current UGC projection may be a placeholder.
        vote_path='/v1/social/rooms/'+room+'/signals/'+signal['id']+'/vote'
        for choice in ('agree','pass'):
            expect(h.call(vote_path,dict(choice=choice),'POST',session=owner),200)
            current=expect(h.call('/v1/social/rooms/'+room,session=owner),200)
            visible=next(row for row in current['signals']if row['id']==signal['id'])
            self.assertEqual(visible['myVote'],choice)
            self.assertEqual(visible['votes'][choice],1)
        # Discovery opt-in did not grant continuing room location rights.
        flags['location']=False
        expect(h.call('/v1/social/rooms/'+room+'/consents',dict(consents=flags),'PATCH',session=owner),200)
        withdrawn=expect(h.call('/v1/social/rooms/'+room,session=owner),200)
        hidden=next(row for row in withdrawn['signals']if row['id']==signal['id'])
        self.assertIsNone(hidden['destination'])
        expect(h.call(vote_path,dict(choice='agree'),'POST',session=owner),409)
        output=os.environ.get('WEGOH_TEST_DISCOVERY_DTO_OUTPUT')
        if output:
            import json
            from pathlib import Path
            Path(output).write_text(json.dumps(response,ensure_ascii=False,indent=2)+'\n')

if __name__=='__main__':unittest.main()
