"""Eight owned HTTP/PostgreSQL contracts. All people and coordinates are synthetic."""
import copy
from datetime import datetime,timedelta,timezone
from unittest.mock import patch
import unittest
import psycopg
import test_team_auth as fixture
from rest_stop_data import DATASET
from team_recommendations import DEFAULTS


class RecommendationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture=fixture.TeamTests
        cls.fixture.setUpClass()
        __import__('api_application')

    @classmethod
    def tearDownClass(cls):cls.fixture.tearDownClass()

    def setUp(self):
        self.api=self.fixture(methodName='test_01_jwt_verification_and_exact_hosts')
        self.api.setUp()
        self.a=self.api.login()
        self.base='/v1/recommendations'

    def call(self,path,data=None,method='GET',session=None,who='alice',**options):
        return self.api.call(self.base+path,data,method,session=session or self.a,who=who,**options)

    def settings(self,**options):
        status,_,value=self.call('/settings',**options)
        self.assertEqual(status,200,value)
        return value

    def save(self,history=False,feedback=False,prefs=None,**options):
        current=self.settings(**options)
        status,_,value=self.call('/settings',dict(revision=current['revision'],preferences=prefs or copy.deepcopy(DEFAULTS),
            permissions=dict(useHistory=history,useFeedback=feedback)),'PUT',**options)
        self.assertEqual(status,200,value)
        return value

    def query(self,prefs=None,revision=None,item=None,**options):
        item=item or DATASET['items'][0]
        point=dict(id='synthetic-selected',provider='map',name='Synthetic selected place',address='',latitude=item['latitude'],longitude=item['longitude'])
        request=dict(settingsRevision=self.settings(**options)['revision']if revision is None else revision,
            anchor=dict(kind='selected-place',place=point),preferences=copy.deepcopy(prefs or DEFAULTS),dismissed=[])
        status,_,value=self.call('/query',request,'POST',**options)
        self.assertEqual(status,200,value)
        return value,request

    def course(self,places=1,offset=0):
        point=DATASET['items'][0]
        pack=self.api.pack()
        pack['stops'][0].update(latitude=point['latitude']+offset,longitude=point['longitude'])
        for index in range(1,places):pack['stops'].append(dict(pack['stops'][0],id='place-'+str(index),name='Synthetic place '+str(index)))
        self.assertEqual(self.api.publish(pack,self.a)[0],201)
        self.assertEqual(self.api.approve(pack,self.a)[0],200)
        return pack

    def history(self,course,session=None,who='alice'):
        body=dict(title='Synthetic private recommendation record',startedAt='2026-01-02T01:00:00Z',endedAt=None,courseId=course['id'],courseVersion=course['version'])
        status,_,value=self.api.call('/v1/social/history',body,'POST',session=session or self.a,who=who)
        self.assertEqual(status,201,value)
        return value

    def test_01_default_off_real_source_and_no_anchor_persistence(self):
        current=self.settings()
        self.assertEqual(current['revision'],0)
        self.assertFalse(current['configured'])
        self.assertEqual(current['permissions'],dict(useHistory=False,useFeedback=False))
        result,_=self.query()
        self.assertEqual(result['algorithm'],'explicit-rules-v1');self.assertFalse(result['aiUsed'])
        self.assertEqual(result['source']['rowCount'],215)
        self.assertEqual(result['source']['dataAsOf'],['2026-09-17'])
        self.assertFalse(result['historyUsed']);self.assertEqual(result['historyConsidered'],0)
        self.assertFalse(result['feedbackUsed']);self.assertEqual(result['restStops'][0]['straightLineMeters'],0)
        self.assertNotIn('latitude',result['anchor'])
        for field in ('price','travelSeconds','currentOpen','chargerAvailable','coordinateVerifiedAt'):
            self.assertIsNone(result['restStops'][0][field])
        with psycopg.connect(self.api.dsn)as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM team_recommendations').fetchone()[0],0)
            self.assertEqual(conn.execute('SELECT count(*) FROM team_histories').fetchone()[0],0)

    def test_02_actual_approved_courses_and_explainable_priority(self):
        near=self.course(1);many=self.course(3,offset=.01)
        result,_=self.query()
        self.assertEqual(result['courses'][0]['id'],near['id'])
        self.assertEqual(result['courses'][0]['straightLineMeters'],0)
        prefs=dict(DEFAULTS,coursePriority='manyStops')
        result,_=self.query(prefs)
        self.assertEqual(result['courses'][0]['id'],many['id']);self.assertIn('morePlaces',result['courses'][0]['reasons'])
        with psycopg.connect(self.api.dsn)as conn:
            from test_course_moderation_fixture import restrict_course
            checksum = conn.execute('SELECT checksum FROM pack_versions WHERE pack_id=%s', (many['id'],)).fetchone()[0]
            restrict_course(conn, checksum)
        result,_=self.query(prefs)
        self.assertEqual([x['id']for x in result['courses']],[near['id']])

    def test_03_owner_isolation_revision_and_mutation_auth(self):
        bob=self.api.login('bob')
        self.save(feedback=True)
        self.assertEqual(self.settings(session=bob,who='bob')['revision'],0)
        stale=dict(revision=0,preferences=copy.deepcopy(DEFAULTS),permissions=dict(useHistory=False,useFeedback=False))
        self.assertEqual(self.call('/settings',stale,'PUT')[0],409)
        self.assertEqual(self.call('/settings',stale,'PUT',csrf=False)[0],403)
        self.assertEqual(self.call('/settings',stale,'PUT',origin='https://wrong.invalid')[0],403)
        self.assertEqual(self.api.call(self.base+'/settings')[0],401)
        self.assertEqual(self.api.native(self.base+'/query',{},'POST')[0],401)

    def test_04_history_is_separate_opt_in_and_owner_only(self):
        pack=self.course();record=self.history(pack)
        bob=self.api.login('bob');self.history(pack,bob,'bob')
        service=self.api.module.TEAM_RECOMMENDATIONS
        with patch.object(service.history,'restore',side_effect=AssertionError('History used without opt-in')):
            result,_=self.query()
        self.assertIsNone(result['courses'][0]['visitedBefore'])
        prefs=dict(DEFAULTS,hideVisited=True)
        _,request=self.query()
        request['preferences']=prefs
        self.assertEqual(self.call('/query',request,'POST')[0],409)
        self.save(history=True,prefs=prefs)
        result,_=self.query(prefs)
        self.assertEqual(result['courses'],[]);self.assertEqual(result['historyConsidered'],1)
        self.assertTrue(result['historyUsed'])
        self.save(history=False)
        self.assertEqual(self.api.call('/v1/social/history/'+record['id'],session=self.a)[0],200)

    def test_05_feedback_requires_consent_and_changes_actual_order(self):
        result,_=self.query()
        self.assertGreaterEqual(len(result['restStops']),2)
        target=result['restStops'][-1]
        feedback=dict(revision=0,kind='rest',id=target['id'],version=None,response='like')
        self.assertEqual(self.call('/feedback',feedback,'POST')[0],403)
        current=self.save(feedback=True)
        feedback['revision']=current['revision']
        code,_,saved=self.call('/feedback',feedback,'POST');self.assertEqual(code,200,saved)
        result,_=self.query();self.assertEqual(result['restStops'][0]['id'],target['id'])
        self.assertIn('likedByYou',result['restStops'][0]['reasons'])
        feedback.update(revision=saved['revision'],response='notInterested')
        self.assertEqual(self.call('/feedback',feedback,'POST')[0],200)
        result,_=self.query();self.assertNotIn(target['id'],[x['id']for x in result['restStops']])
        self.assertEqual(self.settings()['feedbackCount'],1)

    def test_06_withdrawal_erases_recommendation_state_not_original_history(self):
        pack=self.course();record=self.history(pack)
        saved=self.save(history=True,feedback=True)
        feedback=dict(revision=saved['revision'],kind='course',id=pack['id'],version=1,response='like')
        self.assertEqual(self.call('/feedback',feedback,'POST')[0],200)
        before=self.settings()
        with psycopg.connect(self.api.dsn)as conn:
            raw=bytes(conn.execute('SELECT protected FROM team_recommendations').fetchone()[0])
            self.assertNotIn(pack['id'].encode(),raw);self.assertNotIn(b'useHistory',raw)
        status,_,current=self.call('/settings',method='DELETE');self.assertEqual(status,200,current)
        self.assertFalse(current['configured']);self.assertEqual(current['feedbackCount'],0)
        self.assertEqual(current['permissions'],dict(useHistory=False,useFeedback=False))
        self.assertGreater(current['revision'],before['revision'])
        self.assertEqual(self.call('/feedback',feedback,'POST')[0],409)
        self.assertEqual(self.api.call('/v1/social/history/'+record['id'],session=self.a)[0],200)
        with psycopg.connect(self.api.dsn)as conn:
            raw=bytearray(conn.execute('SELECT protected FROM team_recommendations').fetchone()[0]);raw[-1]^=1
            conn.execute('UPDATE team_recommendations SET protected=%s',(bytes(raw),))
        self.assertEqual(self.call('/settings')[0],503)

    def test_07_exact_fields_bounds_and_one_time_gps_consent(self):
        _,request=self.query()
        for field,value in [('maxDistanceKm',10**400),('coursePriority',{}),('facilities',['toilet','toilet'])]:
            invalid=copy.deepcopy(request);invalid['preferences'][field]=value
            self.assertEqual(self.call('/query',invalid,'POST')[0],400)
        invalid=copy.deepcopy(request);invalid['extra']=True
        self.assertEqual(self.call('/query',invalid,'POST')[0],400)
        invalid=copy.deepcopy(request);invalid['extra']='x'*17000
        self.assertEqual(self.call('/query',invalid,'POST')[0],413)
        now=datetime.now(timezone.utc)
        request['anchor']=dict(kind='browser-location',consent=True,position=dict(latitude=0,longitude=0,accuracyMeters=20,capturedAt=now.isoformat()))
        self.assertEqual(self.call('/query',request,'POST')[0],200)
        invalid=copy.deepcopy(request);invalid['anchor']['consent']=False
        self.assertEqual(self.call('/query',invalid,'POST')[0],400)
        invalid=copy.deepcopy(request);invalid['anchor']['position']['capturedAt']=(now-timedelta(minutes=6)).isoformat()
        self.assertEqual(self.call('/query',invalid,'POST')[0],400)
        invalid=copy.deepcopy(request);invalid['anchor']['position']['accuracyMeters']=10**400
        self.assertEqual(self.call('/query',invalid,'POST')[0],400)

    def test_08_current_typed_operations_and_browser_only_events(self):
        status,_,schema=self.api.call('/openapi.json');self.assertEqual(status,200,schema)
        expected={('/settings','get'),('/settings','put'),('/settings','delete'),('/query','post'),('/feedback','post')}
        for path,method in expected:
            op=schema['paths'][self.base+path][method]
            native=(path,method) in {('/settings','get'),('/query','post'),('/feedback','post')}
            self.assertEqual(op['x-wegoh-native-access'],native);self.assertEqual(op['tags'],['16 내 취향 추천'])
            self.assertEqual({'NativeMTLS':[],'DeviceBearer':[]} in op['security'],native)
            self.assertNotIn('DeviceBearer',op['security'][0])
            self.assertIn('200',op['responses'])
        query=schema['paths'][self.base+'/query']['post']['requestBody']['content']['application/json']['schema']
        self.assertEqual(len(query['oneOf']),2)
        query=query['oneOf'][0]
        self.assertEqual(len(query['oneOf']),2)
        for branch in query['oneOf']:
            self.assertFalse(branch['additionalProperties']);self.assertEqual(len(branch['properties']['anchor']['oneOf']),2)
        self.assertNotIn('learningRevision',query['oneOf'][0]['properties'])
        self.assertIn('learningRevision',query['oneOf'][1]['required'])
        import native_events
        self.assertIn('recommendations',native_events.visible_resources(self.api.module.TEAM_AUTH,dict(id=self.a['user']['id'],role='admin')))
        self.assertNotIn('recommendations',native_events.BASE_DEVICE_RESOURCES)


if __name__=='__main__':unittest.main(verbosity=2)
