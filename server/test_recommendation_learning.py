"""Owned synthetic HTTP/model regressions for separately consented personal learning."""
import copy
import json
import math
import unittest
import importlib.util
from pathlib import Path
import secrets
import sys

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
import test_team_recommendations as base


class PersonalLearningTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): base.RecommendationTests.setUpClass()
    @classmethod
    def tearDownClass(cls): base.RecommendationTests.tearDownClass()

    def setUp(self):
        self.h = base.RecommendationTests(methodName='test_01_default_off_real_source_and_no_anchor_persistence')
        self.h.setUp(); self.api = self.h.api; self.a = self.h.a

    def learning(self, **options):
        status, _, value = self.h.call('/learning', **options)
        self.assertEqual(status, 200, value)
        return value

    def enable(self, **options):
        self.h.save(feedback=True, **options)
        state, settings = self.learning(**options), self.h.settings(**options)
        status, _, value = self.h.call('/learning', dict(revision=state['learningRevision'],
            recommendationRevision=settings['revision'], consent=True), 'PUT', **options)
        self.assertEqual(status, 200, value)
        return value

    def label(self, course, response, *, learned=True, **options):
        body = dict(revision=self.h.settings(**options)['revision'], kind='course', id=course['id'],
                    version=course['version'], response=response)
        if learned: body['learningRevision'] = self.learning(**options)['learningRevision']
        status, _, value = self.h.call('/feedback', body, 'POST', **options)
        self.assertEqual(status, 200, value)
        return value

    def query(self, *, learned=False, hide=(), **options):
        point = base.DATASET['items'][0]
        body = dict(settingsRevision=self.h.settings(**options)['revision'], preferences=copy.deepcopy(base.DEFAULTS),
            anchor=dict(kind='selected-place', place=dict(id='synthetic-selected',provider='map',name='Synthetic place',
                address='',latitude=point['latitude'],longitude=point['longitude'])), dismissed=['course:'+c['id'] for c in hide])
        if learned: body['learningRevision'] = self.learning(**options)['learningRevision']
        status, _, value = self.h.call('/query', body, 'POST', **options)
        self.assertEqual(status, 200, value)
        return value

    def course(self, places, *, offset=0, step=.08):
        point = base.DATASET['items'][0]
        pack = self.api.pack(); stop = pack['stops'][0]
        pack['stops'] = [dict(stop,id='place-'+str(i), latitude=point['latitude']+offset,
                             longitude=point['longitude']+step*i) for i in range(places)]
        self.assertEqual(self.api.publish(pack,self.a)[0],201)
        self.assertEqual(self.api.approve(pack,self.a)[0],200)
        return pack

    def train(self, **options):
        self.enable(**options)
        courses = [self.course(3,step=.07),self.course(3,step=.11),self.course(1),self.course(1,offset=.002)]
        for course, label in zip(courses,('like','like','notInterested','notInterested')):
            self.label(course,label,**options)
        return courses

    def test_01_default_off_old_feedback_never_becomes_training(self):
        self.assertFalse(self.learning()['enabled'])
        course = self.course(1); self.h.save(feedback=True)
        self.label(course,'like',learned=False)
        self.assertEqual(self.learning()['eligibleSamples'],0)
        self.enable(); self.assertEqual(self.learning()['eligibleSamples'],0)
        self.label(course,'like',learned=False)
        self.assertEqual(self.learning()['eligibleSamples'],0)
        self.assertFalse(self.query()['aiUsed'])
        self.assertEqual(self.query()['algorithm'],'explicit-rules-v1')

    def test_02_separate_consent_current_revision_auth_and_owner_only(self):
        state = self.learning(); settings = self.h.settings()
        body = dict(revision=state['learningRevision'],recommendationRevision=settings['revision'],consent=True)
        self.assertEqual(self.h.call('/learning',body,'PUT')[0],403)
        self.h.save(feedback=True); body['recommendationRevision']=self.h.settings()['revision']
        self.assertEqual(self.h.call('/learning',body,'PUT',csrf=False)[0],403)
        self.assertEqual(self.h.call('/learning',dict(body,consent=1),'PUT')[0],400)
        self.enable()
        bob = self.api.login('bob')
        self.assertFalse(self.learning(session=bob,who='bob')['enabled'])
        self.assertEqual(self.api.native('/v1/recommendations/learning')[0],404)

    def test_03_fitted_weights_change_unseen_order_and_opposite_labels_reverse_it(self):
        training = self.train()
        farther_many, nearest_one = self.course(3,offset=.004), self.course(1)
        self.assertNotIn(farther_many['id'],[c['id'] for c in training])
        self.assertNotIn(nearest_one['id'],[c['id'] for c in training])
        baseline = self.query(hide=training)
        self.assertEqual(baseline['courses'][0]['id'],nearest_one['id'])
        learned = self.query(learned=True,hide=training)
        self.assertTrue(learned['aiUsed']); self.assertEqual(learned['algorithm'],'personal-logistic-v1')
        self.assertEqual(learned['courses'][0]['id'],farther_many['id'])
        bob = self.api.login('bob'); options = dict(session=bob,who='bob')
        self.enable(**options)
        for course, label in zip(training,('notInterested','notInterested','like','like')):
            self.label(course,label,**options)
        opposite = self.query(learned=True,hide=training,**options)
        self.assertTrue(opposite['aiUsed']); self.assertEqual(opposite['courses'][0]['id'],nearest_one['id'])
        self.assertEqual(self.learning()['eligibleSamples'],4)
        self.assertEqual(self.learning(**options)['eligibleSamples'],4)
        empty=self.query(learned=True,hide=training+[farther_many,nearest_one])
        self.assertEqual(empty['courses'],[]);self.assertEqual(empty['learning']['status'],'trained');self.assertFalse(empty['aiUsed'])

    def test_04_withdraw_tombstone_rejects_old_consent_and_preserves_history(self):
        courses = self.train(); record = self.h.history(courses[0])
        old = self.learning()
        self.assertEqual(self.h.call('/learning',method='DELETE')[0],200)
        current = self.learning(); self.assertFalse(current['enabled']); self.assertEqual(current['eligibleSamples'],0)
        body = dict(revision=old['learningRevision'],recommendationRevision=self.h.settings()['revision'],consent=True)
        self.assertEqual(self.h.call('/learning',body,'PUT')[0],409)
        self.assertEqual(self.api.call('/v1/social/history/'+record['id'],session=self.a)[0],200)
        self.assertFalse(self.query()['aiUsed'])
        self.enable(); self.assertEqual(self.learning()['eligibleSamples'],0)

    def test_05_approval_withdraw_removes_sample_influence_and_no_old_version_relabel(self):
        training = self.train()
        with psycopg.connect(self.api.dsn) as conn:
            from test_course_moderation_fixture import restrict_course
            for (checksum,) in conn.execute('SELECT checksum FROM pack_versions WHERE pack_id=ANY(%s)',
                    ([c['id'] for c in training[:2]],)).fetchall():
                restrict_course(conn, checksum)
        status = self.learning(); self.assertEqual(status['eligibleSamples'],2)
        self.assertEqual(status['status'],'collecting-feedback')
        self.assertFalse(self.query(learned=True)['aiUsed'])
        changed = copy.deepcopy(training[0]); changed['version']=2; changed['title']='New explicit version'
        self.assertEqual(self.api.publish(changed,self.a)[0],201); self.assertEqual(self.api.approve(changed,self.a)[0],200)
        self.assertEqual(self.learning()['eligibleSamples'],2)
        self.label(changed,'like'); self.assertEqual(self.learning()['eligibleSamples'],3)

    def test_06_feedback_off_and_full_settings_withdraw_clear_live_model(self):
        self.train(); self.h.save(feedback=False)
        self.assertFalse(self.learning()['enabled']); self.assertEqual(self.learning()['eligibleSamples'],0)
        self.enable(); self.assertEqual(self.learning()['eligibleSamples'],0)
        self.assertEqual(self.h.call('/settings',method='DELETE')[0],200)
        self.assertFalse(self.learning()['enabled'])

    def test_07_owner_bound_encryption_and_no_anchor_private_history_features(self):
        self.train(); self.query(learned=True)
        from private_records import VisitCipher
        with psycopg.connect(self.api.dsn) as conn:
            raw = bytes(conn.execute('SELECT protected FROM team_recommendation_learning WHERE account_id=%s',
                                    (self.a['user']['id'],)).fetchone()[0])
        self.assertNotIn(b'features',raw); self.assertNotIn(b'label',raw)
        stored = VisitCipher().restore('team-recommendation-learning',self.a['user']['id'],raw)
        for sample in stored['samples'].values():
            self.assertEqual(set(sample),{'courseId','version','checksum','features','label','epoch'})
            self.assertEqual(len(sample['features']),3)
        self.assertNotIn('latitude',json.dumps(stored)); self.assertNotIn('history',json.dumps(stored))
        # Restore the populated encrypted purpose table with the unchanged live
        # backup comparator, rather than treating CREATE as preservation proof.
        source=base.fixture.ROOT/'server/ops/live/backup.py'
        spec=importlib.util.spec_from_file_location('learning_backup_contract',source)
        backup=importlib.util.module_from_spec(spec);sys.modules[spec.name]=backup;spec.loader.exec_module(backup)
        work=self.api.state/('learning-backup-'+secrets.token_hex(8));work.mkdir(mode=0o700)
        snapshots=work/'snapshots';snapshots.mkdir(mode=0o700)
        tool=Path(self.api.tools['pg_ctl']).parent
        layout=backup.Layout(self.api.dsn,self.api.state/'content',snapshots,str(tool/'pg_dump'),str(tool/'pg_restore'))
        name='learning_restore_'+secrets.token_hex(6)
        with psycopg.connect(self.api.dsn,autocommit=True) as conn:
            conn.execute(sql.SQL('CREATE DATABASE {} TEMPLATE template0').format(sql.Identifier(name)))
        try:
            snapshot=backup.snapshot(layout);target=make_conninfo(self.api.dsn,dbname=name)
            restored=work/'restore';restored.mkdir(mode=0o700)
            self.assertTrue(backup.verify_into(layout,snapshot,target,restored)['verified'])
            with psycopg.connect(target) as conn:
                recovered=bytes(conn.execute('SELECT protected FROM team_recommendation_learning WHERE account_id=%s',
                    (self.a['user']['id'],)).fetchone()[0])
                self.assertEqual(recovered,raw)
        finally:
            with psycopg.connect(self.api.dsn,autocommit=True) as conn:
                conn.execute('SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname=%s',(name,))
                conn.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(name)))

    def test_08_actual_loss_decreases_and_finite_difference_is_consistent(self):
        status,_,schema=self.api.call('/openapi.json');self.assertEqual(status,200,schema)
        for method in ('get','put','delete'):
            operation=schema['paths']['/v1/recommendations/learning'][method]
            self.assertFalse(operation['x-wegoh-native-access'])
            self.assertIn('16 내 취향 추천',operation['tags']);self.assertIn('200',operation['responses'])
        query=schema['paths']['/v1/recommendations/query']['post']['requestBody']['content']['application/json']['schema']
        self.assertEqual(len(query['oneOf']),2)
        query=query['oneOf'][0]
        self.assertEqual(len(query['oneOf']),2)
        self.assertFalse(query['oneOf'][0]['additionalProperties']);self.assertFalse(query['oneOf'][1]['additionalProperties'])
        feedback=schema['paths']['/v1/recommendations/feedback']['post']['requestBody']['content']['application/json']['schema']
        self.assertEqual(len(feedback['oneOf']),2)
        feedback=feedback['oneOf'][0]
        self.assertEqual(feedback['oneOf'][0]['properties']['kind']['enum'],['course','rest'])
        self.assertEqual(feedback['oneOf'][1]['properties']['kind']['const'],'course')
        self.enable();state=self.learning();revision=self.h.settings()['revision']
        rest=base.DATASET['items'][0]
        invalid=dict(revision=revision,kind='rest',id=rest['id'],version=None,response='like',learningRevision=state['learningRevision'])
        self.assertEqual(self.h.call('/feedback',invalid,'POST')[0],400)
        self.assertEqual(self.h.settings()['revision'],revision)
        self.assertEqual(self.learning()['eligibleSamples'],0)
        from recommendation_model import fit,score
        samples = [([1.,1.,.2],1),([1.,1.,.3],1),([1.,0.,0.],0),([1.,0.,0.],0)]
        model = fit(samples); self.assertEqual(model['status'],'trained')
        def objective(weights):
            value = 0.25*sum(w*w for w in weights)
            for x,y in samples:
                z=sum(a*b for a,b in zip(weights,x))
                value += (max(z,0)-y*z+math.log1p(math.exp(-abs(z))))/len(samples)
            return value
        self.assertLess(objective(model['weights']),objective([0.,0.,0.]))
        eps=1e-5
        for i in range(3):
            high=list(model['weights']); low=list(high); high[i]+=eps; low[i]-=eps
            self.assertLess(abs((objective(high)-objective(low))/(2*eps)),.05)
        self.assertGreater(score(model,[1.,1.,.25]),score(model,[1.,0.,0.]))
