import unittest
from concurrent.futures import ThreadPoolExecutor

import psycopg
from fastapi import HTTPException
from native_functional_policy import authorize, FunctionalError
from team_trip_driving_scores import driving_score
import test_native_functional_trips as fixture


def score(a=1, b=1, *, final=False, measurable=True):
    return dict(score=max(0, 100-5*(a+b)) if measurable else None,
                accelerations=a, brakings=b, measurable=measurable, final=final)


class DrivingScorePolicyTests(unittest.TestCase):
    def test_closed_value_formula_integer_counts_and_measurement(self):
        self.assertEqual(driving_score(score()), score())
        self.assertEqual(driving_score(score(30, 0, final=True), final=True)['score'], 0)
        self.assertIsNone(driving_score(score(measurable=False))['score'])
        invalid = [None, {}, dict(score(), speedKmh=80), dict(score(), samples=[]),
                   dict(score(), capturedAt='2026-11-13'), dict(score(), score=91),
                   dict(score(), score=True), dict(score(), accelerations=True),
                   dict(score(), brakings=-1), dict(score(), accelerations=1.0),
                   dict(score(), measurable=1), dict(score(), final=0),
                   dict(score(), measurable=False), dict(score(), score=None),
                   dict(score(), accelerations=2147483648)]
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(HTTPException) as error:
                driving_score(value)
            self.assertEqual((error.exception.status_code, error.exception.detail), (400, 'DRIVING_SCORE_INVALID'))
        with self.assertRaises(HTTPException):
            driving_score(score(final=True), final=False)

    def test_trip_interaction_authorizes_scores_without_separate_score_consent(self):
        path='/v1/native/trips/'+'a'*32+'/cars/'+'b'*32+'/courses/course/driving-score'
        self.assertTrue(authorize('PUT', path, frozenset(('rooms:interact','driving-score:report'))))
        self.assertTrue(authorize('PUT', path, frozenset(('rooms:interact',))))
        with self.assertRaises(FunctionalError) as error:
            authorize('PUT', path, frozenset(('driving-score:report',)))
        self.assertEqual(error.exception.code,'FUNCTIONAL_PURPOSE_REQUIRED')
        from native_functional_defaults import INITIAL_PURPOSES, ACCOUNT_PURPOSES
        self.assertNotIn('driving-score:report', INITIAL_PURPOSES)
        self.assertNotIn('driving-score:report', ACCOUNT_PURPOSES)


class DrivingScoreHttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixture.NativeTripTests.setUpClass()
        cls.addClassCleanup(fixture.NativeTripTests.tearDownClass)

    def setUp(self):
        self.h=fixture.NativeTripTests();self.h.setUp();self.addCleanup(self.h.factory.h.doCleanups)
        h=self.h
        h.browser(h.guest,h.path+'/respond',dict(accept=True),'POST')
        h.browser(h.guest,'/v1/devices/'+h.device['deviceId']+'/vehicle-profile',dict(plateNumber='123가4567',name='',expectedRevision=0),'PUT')
        self.revision=h.approve(['rooms:read','rooms:interact','driving-score:report'])
        self.base='/v1/native/trips/'+h.trip
        self.car=h.native(self.base+'/cars',dict(name='사용자A의 차',seats=2,functionalRevision=self.revision),'POST',201)['id']
        self.pack=h.h.pack();self.pack['author']='사용자A'
        published=h.h.publish(self.pack,h.guest,'bob');self.assertEqual(published[0],201,published[2])
        h.h.approve(self.pack,h.owner)
        h.browser(h.guest,h.path+'/courses',dict(packId=self.pack['id']),'POST',201)
        current=h.browser(h.owner,h.path+'/workspace')['revision']
        h.browser(h.owner,h.path+'/start',dict(revision=current),'POST')
        self.path=self.base+'/cars/'+self.car+'/courses/'+self.pack['id']

    def write(self, value=None, expected=200, suffix='/driving-score', method='PUT', revision=None):
        return self.h.native(self.path+suffix, dict(drivingScore=score() if value is None else value,
            functionalRevision=self.revision if revision is None else revision), method, expected)

    def visible(self, session):
        return self.h.browser(session,self.h.path)['courses'][0]['drivingScores']

    def test_score_refresh_keeps_current_hand_raise_context_and_only_route_version_changes(self):
        h=self.h
        owner_device=h.factory.connect(h.owner)
        h.browser(h.owner,'/v1/devices/'+owner_device['deviceId']+'/vehicle-profile',
            dict(plateNumber='234나5678',name='',expectedRevision=0),'PUT')
        h.browser(h.owner,h.path+'/cars',dict(name='사용자B의 차',seats=1),'POST',201)
        destination=dict(name='서산휴게소',latitude=37.5,longitude=127.0)
        created=h.browser(h.owner,h.path+'/signals',dict(kind='rest',destination=destination),'POST',201)
        signal=created['id']
        before=h.browser(h.guest,h.path+'/signals')['signals'][0]
        self.assertTrue(before['canRespond'])
        revision=h.browser(h.guest,h.path)['revision']
        def versions():
            with psycopg.connect(h.h.dsn) as conn:
                return dict(conn.execute("SELECT account_id,revision FROM team_resource_versions WHERE account_id=ANY(%s)",
                    (['event-trip:'+h.trip+':route','event-trip:'+h.trip+':signals'],)))
        resources=versions()
        self.write()
        self.assertEqual(h.browser(h.guest,h.path)['revision'],revision)
        after=h.browser(h.guest,h.path+'/signals')['signals'][0]
        self.assertTrue(after['canRespond'])
        self.assertEqual(after['resolution'],'pending')
        updated=versions()
        self.assertGreater(updated['event-trip:'+h.trip+':route'],resources['event-trip:'+h.trip+':route'])
        self.assertEqual(updated['event-trip:'+h.trip+':signals'],resources['event-trip:'+h.trip+':signals'])
        h.browser(h.guest,h.path+'/signals/'+signal+'/vote',dict(choice='agree'),'POST')

    def test_current_driver_strict_body_same_car_filter_and_encrypted_storage(self):
        self.assertEqual(self.write()['status'],'updated')
        self.assertEqual(self.visible(self.h.owner),[])
        expected=dict(carId=self.car,**score())
        self.assertEqual(self.visible(self.h.guest),[expected])
        self.h.browser(self.h.owner,self.h.path+'/cars/'+self.car+'/ride',method='PUT')
        self.assertEqual(self.visible(self.h.owner),[expected])
        self.h.browser(self.h.owner,self.h.path+'/ride',method='DELETE')
        self.assertEqual(self.visible(self.h.owner),[])
        with psycopg.connect(self.h.h.dsn) as conn:
            raw=conn.execute('SELECT protected FROM team_trip_car_driving_scores WHERE trip_id=%s',(self.h.trip,)).fetchone()[0]
            self.assertNotIn(b'accelerations',bytes(raw))
        for extra in ('speed','samples','timestamps','location'):
            self.write(dict(score(),**{extra:[]}),400)
        owner_device=self.h.factory.connect(self.h.owner)
        owner_revision=self.h.factory.approve(self.h.owner,owner_device,['rooms:read','rooms:interact','driving-score:report'])
        self.h.native(self.path+'/driving-score',dict(drivingScore=score(),functionalRevision=owner_revision),'PUT',403,device=owner_device)
        self.h.browser(self.h.guest,self.h.path+'/cars/'+self.car+'/courses/'+self.pack['id']+'/complete',
            dict(drivingScore=score(final=True)),'POST',403)

    def test_revision_revocation_wrong_car_and_membership_are_rechecked(self):
        self.write(revision=self.revision+1,expected=409)
        self.h.native(self.path.replace(self.car,'e'*32)+'/driving-score',
            dict(drivingScore=score(),functionalRevision=self.revision),'PUT',404)
        rev=self.h.approve(['rooms:read','rooms:interact'])
        self.write(revision=rev)
        self.h.native(self.path+'/complete',dict(functionalRevision=rev),'POST')
        self.h.native(self.path+'/complete',dict(drivingScore=score(final=True),functionalRevision=rev),'POST')

    def test_legacy_completion_rejects_late_interim_but_allows_final_score_once(self):
        self.h.native(self.path+'/complete',dict(functionalRevision=self.revision),'POST')
        before=self.h.browser(self.h.guest,self.h.path)
        self.assertEqual(before['courses'][0]['completedCarIds'],[self.car])
        self.assertEqual(before['courses'][0]['drivingScores'],[])
        self.write(expected=409)
        unchanged=self.h.browser(self.h.guest,self.h.path)
        self.assertEqual(unchanged['revision'],before['revision'])
        self.assertEqual(unchanged['courses'][0]['drivingScores'],[])
        self.h.native(self.path+'/complete',dict(functionalRevision=self.revision),'POST')
        self.write(score(final=True),suffix='/complete',method='POST')
        self.write(score(final=True),suffix='/complete',method='POST')
        self.assertTrue(self.visible(self.h.guest)[0]['final'])
        self.write(expected=409)

    def test_final_completion_is_atomic_idempotent_and_cannot_regress(self):
        self.write()
        self.write(score(2,1,final=True),suffix='/complete',method='POST')
        self.assertTrue(self.visible(self.h.guest)[0]['final'])
        self.write(score(3,1),409)
        self.write(score(2,1,final=True),suffix='/complete',method='POST')
        self.write(score(3,1,final=True),409,suffix='/complete',method='POST')
        with psycopg.connect(self.h.h.dsn) as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM team_trip_car_driving_scores WHERE trip_id=%s',(self.h.trip,)).fetchone()[0],1)
        self.assertEqual(self.visible(self.h.guest)[0]['score'],85)

    def test_concurrent_final_and_progress_never_restore_unfinalized_score(self):
        def report(final):
            return self.h.factory.native(self.h.device,self.path+('/complete' if final else '/driving-score'),
                dict(drivingScore=score(final=final),functionalRevision=self.revision),'POST' if final else 'PUT')
        with ThreadPoolExecutor(max_workers=2) as pool:
            result=list(pool.map(report,(True,False)))
        self.assertEqual(result[0][0],200,result[0][2])
        self.assertIn(result[1][0],(200,409),result[1][2])
        self.assertTrue(self.visible(self.h.guest)[0]['final'])

    def test_unknown_score_does_not_complete_or_mutate_and_course_cleanup_cascades(self):
        self.write(dict(score(final=True),samples=[]),400,suffix='/complete',method='POST')
        self.assertEqual(self.visible(self.h.guest),[])
        self.assertEqual(self.h.browser(self.h.guest,self.h.path)['courses'][0]['completedCarIds'],[])
        self.write(score(measurable=False))
        self.assertIsNone(self.visible(self.h.guest)[0]['score'])
        self.h.browser(self.h.guest,self.h.path+'/courses/'+self.pack['id'],method='DELETE')
        with psycopg.connect(self.h.h.dsn) as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM team_trip_car_driving_scores WHERE trip_id=%s',(self.h.trip,)).fetchone()[0],0)
