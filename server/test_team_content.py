"""Eight focused actual-PG/HTTP content contracts; no real identity or content."""
from datetime import datetime,timezone,timedelta
import json,secrets,unittest
import psycopg
from fastapi import HTTPException
import test_team_auth as fixture


class ContentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixture.TeamTests.setUpClass()
        from team_api_docs import install_api_docs
        install_api_docs(fixture.TeamTests.module.app,fixture.TeamTests.module.TEAM_AUTH,
                         fixture.ROOT/'server/web')
    @classmethod
    def tearDownClass(cls):fixture.TeamTests.tearDownClass()
    def setUp(self):
        self.api=fixture.TeamTests(methodName='test_01_jwt_verification_and_exact_hosts');self.api.setUp()
        self.engine=self.api.module.TEAM_CONTENT
        self.a=self.api.login();self.b=self.api.login('bob')
    def call(self,path,data=None,method='GET',who='bob',session=None,**kw):
        return self.api.call(path,data,method,who=who,session=session or(self.a if who=='alice'else self.b),**kw)
    def create(self):
        data=dict(title='Synthetic private title',startedAt='2026-01-02T01:00:00Z',endedAt=None,courseId=None,courseVersion=None)
        status,_,value=self.call('/v1/social/history',data,'POST');self.assertEqual(status,201);return value['id']
    def detail(self,item):
        status,_,value=self.call('/v1/social/history/'+item);self.assertEqual(status,200);return value
    def visit(self,item):
        data=dict(revision=self.detail(item)['revision'],place=dict(name='Synthetic selected place',latitude=37.654321,longitude=127.123456),visitedAt='2026-01-02T02:00:00Z',review='Synthetic review text',rating=4)
        status,_,value=self.call('/v1/social/history/'+item+'/visits',data,'POST');self.assertEqual(status,201);return value['id']
    def request(self,item,consent=True):
        return self.call('/v1/social/history/'+item+'/review-request',dict(revision=self.detail(item)['revision'],consent=consent),'PATCH')
    def inspect(self,kind,key):
        return self.call('/v1/moderation/content/'+kind+'/'+key,who='alice')
    def approve(self,kind,key):
        status,_,item=self.inspect(kind,key);self.assertEqual(status,200,item)
        body=dict(checksum=item['review']['checksum'],decision='approved',reviewer='Synthetic reviewer',reviewNote='Actual test operator decision; not a semantic approval of real user content')
        status,_,value=self.call('/v1/moderation/content/'+kind+'/'+key,body,'POST','alice');self.assertEqual(status,200,value);return value
    def friend(self):
        self.assertEqual(self.call('/v1/social/friends/requests',dict(targetId=self.a['user']['id']),'POST')[0],201)
        self.assertEqual(self.call('/v1/social/friends/requests/'+self.b['user']['id']+'/respond',dict(accept=True),'POST','alice')[0],200)
    def share(self,item):
        return self.call('/v1/social/history/'+item+'/shares/'+self.a['user']['id'],dict(permissionRevision=self.detail(item)['permissionRevision'],visits=True,trace=False,photos=False),'PUT')
    def queue(self):return self.call('/v1/moderation/content',who='alice')

    def test_01_projection_unknown_fields_and_key_kind_fail_closed(self):
        valid=dict(title='Synthetic',places=[],reviews=[],traceLabels=[])
        for kind,value in [('unknown',{}),('history',dict(valid,latitude=37.0)),('history',dict(valid,photos=[])),('room',dict(name='Synthetic',coordinates=[1,2])),('photo',dict(checksum='a'*64,width=True,height=1,contentType='image/jpeg'))]:
            with self.assertRaises(HTTPException)as denied:self.engine.digest(kind,value)
            self.assertEqual(denied.exception.status_code,400)
        self.assertEqual(self.inspect('unknown','a'*32)[0],404)
        self.assertEqual(self.inspect('photo','a'*32)[0],404)

    def test_02_no_private_original_or_coordinates_enter_admin_queue(self):
        item=self.create();self.visit(item)
        self.assertEqual(self.queue()[2]['items'],[]);self.assertEqual(self.inspect('history',item)[0],404)
        self.assertEqual(self.request(item)[0],200)
        status,_,entry=self.inspect('history',item);self.assertEqual(status,200)
        projection=entry['projection'];self.assertEqual(set(projection),{'title','places','reviews','traceLabels'})
        self.assertEqual(projection['places'],['Synthetic selected place']);self.assertEqual(projection['reviews'],['Synthetic review text'])
        raw=json.dumps(projection);self.assertNotIn('latitude',raw);self.assertNotIn('37.654321',raw);self.assertNotIn('photos',raw)
        status,headers,queue=self.queue();self.assertEqual(status,200);self.assertIn('no-store',headers.get('cache-control',''))
        self.assertEqual(len(queue['items']),1);self.assertNotIn('projection',queue['items'][0]);self.assertIn('detailUrl',queue['items'][0])

    def test_03_exact_changed_checksum_requires_new_human_decision(self):
        item=self.create();self.visit(item);self.assertEqual(self.request(item)[0],200)
        old=self.inspect('history',item)[2]['review']['checksum'];detail=self.detail(item)
        body={k:detail[k]for k in('title','startedAt','endedAt','courseId','courseVersion','revision')};body['title']='Changed synthetic title'
        self.assertEqual(self.call('/v1/social/history/'+item,body,'PUT')[0],200)
        decision=dict(checksum=old,decision='approved',reviewer='Synthetic reviewer',reviewNote='Old snapshot must not approve changed text')
        self.assertEqual(self.call('/v1/moderation/content/history/'+item,decision,'POST','alice')[0],409)
        self.assertNotEqual(self.inspect('history',item)[2]['review']['checksum'],old)
        self.assertEqual(self.approve('history',item)['state'],'approved')
        with psycopg.connect(self.api.dsn)as conn:
            raw=bytes(conn.execute('SELECT protected FROM team_content_reviews WHERE kind=%s AND content_key=%s',('history',item)).fetchone()[0]);self.assertNotIn(b'Changed synthetic title',raw)

    def test_04_friend_grant_intersects_review_and_report_requarantines(self):
        self.friend();item=self.create();self.visit(item);self.assertEqual(self.share(item)[0],200)
        self.assertEqual(self.call('/v1/social/history/'+item,who='alice')[0],404)
        self.assertEqual(self.request(item)[0],200);self.approve('history',item)
        self.assertEqual(self.call('/v1/social/history/'+item,who='alice')[0],200)
        status,_,reported=self.call('/v1/social/history/'+item+'/reports',dict(reason='privacy'),'POST','alice')
        self.assertEqual(status,202);self.assertEqual(reported['state'],'quarantined')
        self.assertEqual(self.call('/v1/social/history/'+item,who='alice')[0],404)
        self.assertEqual(self.inspect('history',item)[2]['review']['state'],'quarantined')
        with psycopg.connect(self.api.dsn)as conn:
            rows=conn.execute('SELECT protected FROM team_content_review_events WHERE kind=%s AND content_key=%s',('history',item)).fetchall()
            self.assertGreaterEqual(len(rows),3);self.assertTrue(all(b'"privacy"'not in bytes(row[0])for row in rows))

    def test_05_withdraw_hides_operator_and_does_not_delete_original(self):
        self.friend();item=self.create();self.visit(item);self.share(item);self.request(item);self.approve('history',item)
        before=self.detail(item);self.assertEqual(self.request(item,False)[0],200)
        self.assertEqual(self.inspect('history',item)[0],404);self.assertEqual(self.queue()[2]['items'],[])
        self.assertEqual(self.call('/v1/social/history/'+item,who='alice')[0],404)
        after=self.detail(item);self.assertEqual(after['title'],before['title']);self.assertEqual(after['visits'],before['visits'])
        self.assertEqual(self.request(item)[0],200);self.assertEqual(self.inspect('history',item)[2]['review']['state'],'quarantined')

    def test_06_room_and_selected_place_use_separate_expiring_projections(self):
        status,_,room=self.call('/v1/social/rooms',dict(name='Unreviewed room name',courseId=None,courseVersion=None,expiresInHours=1),'POST','alice');self.assertEqual(status,201);room_id=room['id']
        invite=self.call('/v1/social/invites/'+room['code']);self.assertEqual(invite[0],200);self.assertNotEqual(invite[2]['name'],'Unreviewed room name')
        choices=dict(status=True,location=True,visits=False,music=False,voice=False,control=False)
        self.assertEqual(self.call('/v1/social/rooms/join',dict(code=room['code'],consents=choices),'POST')[0],200)
        self.assertEqual(self.call('/v1/social/rooms/'+room_id+'/review-request',dict(consent=True),'PATCH','alice')[0],200);self.approve('room',room_id)
        self.assertEqual(self.call('/v1/social/rooms/'+room_id)[2]['name'],'Unreviewed room name')
        self.assertEqual(self.call('/v1/social/rooms/'+room_id+'/reports',dict(reason=[]),'POST')[0],400)
        self.assertEqual(self.call('/v1/social/rooms/'+room_id+'/reports',dict(reason='harmful'),'POST')[0],202)
        self.assertNotEqual(self.call('/v1/social/rooms/'+room_id)[2]['name'],'Unreviewed room name');self.approve('room',room_id)
        self.assertEqual(self.call('/v1/social/rooms/'+room_id+'/consents',dict(consents=choices),'PATCH')[0],200)
        status,_,signal=self.call('/v1/social/rooms/'+room_id+'/signals',dict(kind='rest',destination=dict(name='Unreviewed place name',latitude=37.5,longitude=127.0)),'POST');self.assertEqual(status,201);signal_id=signal['id'];key=room_id+':'+signal_id
        detail=self.call('/v1/social/rooms/'+room_id,who='alice')[2];shown=next(x for x in detail['signals']if x['id']==signal_id);self.assertNotEqual(shown['destination']['name'],'Unreviewed place name')
        route='/v1/social/rooms/'+room_id+'/signals/'+signal_id+'/review-request'
        self.assertEqual(self.call(route,dict(consent=True),'PATCH','alice')[0],404) # room owner cannot submit Bob's place for him
        self.assertEqual(self.call(route,dict(consent=True),'PATCH')[0],200);self.approve('room-place',key)
        self.assertEqual(self.inspect('room-place',key)[2]['projection'],dict(name='Unreviewed place name'))
        detail=self.call('/v1/social/rooms/'+room_id,who='alice')[2];self.assertEqual(next(x for x in detail['signals']if x['id']==signal_id)['destination']['name'],'Unreviewed place name')
        self.assertEqual(self.call('/v1/social/rooms/'+room_id+'/signals/'+signal_id+'/reports',dict(reason='privacy'),'POST','alice')[0],202)
        detail=self.call('/v1/social/rooms/'+room_id,who='alice')[2];self.assertNotEqual(next(x for x in detail['signals']if x['id']==signal_id)['destination']['name'],'Unreviewed place name');self.approve('room-place',key)
        self.assertEqual(self.call(route,dict(consent=False),'PATCH')[0],200);self.assertEqual(self.inspect('room-place',key)[0],404)
        with psycopg.connect(self.api.dsn)as conn:conn.execute("UPDATE team_rooms SET expires_at=now()-interval'1 second'WHERE room_id=%s",(room_id,))
        self.assertEqual(self.inspect('room',room_id)[0],404)
        with psycopg.connect(self.api.dsn)as conn:self.assertEqual(conn.execute('SELECT count(*)FROM team_rooms WHERE room_id=%s',(room_id,)).fetchone()[0],1)

    def test_07_role_origin_and_native_do_not_gain_moderation(self):
        item=self.create();self.request(item);body=dict(checksum=self.inspect('history',item)[2]['review']['checksum'],decision='approved',reviewer='Synthetic',reviewNote='Synthetic test review')
        self.assertEqual(self.call('/v1/moderation/content')[0],403)
        self.assertEqual(self.call('/v1/moderation/content/history/'+item,body,'POST')[0],403)
        self.assertEqual(self.call('/v1/moderation/content/history/'+item,body,'POST','alice',csrf=False)[0],403)
        self.assertEqual(self.call('/v1/moderation/content/history/'+item,body,'POST','alice',origin='https://wrong.invalid')[0],403)
        self.assertEqual(self.api.native('/v1/moderation/content')[0],404)
        schema=self.call('/openapi.json',who='alice')[2]
        self.assertIn('/v1/moderation/content/{kind}/{key}',schema['paths'])
        self.assertFalse(schema['paths']['/v1/moderation/content/{kind}/{key}/media']['get']['x-wegoh-executable'])

    def test_08_new_raw_string_is_not_automatically_disclosed(self):
        self.friend();item=self.create();visit=self.visit(item);self.share(item);self.request(item);self.approve('history',item)
        history=self.api.module.TEAM_HISTORY;owner=self.b['user']['id']
        with psycopg.connect(self.api.dsn)as conn:
            conn.execute("INSERT INTO team_resource_versions(account_id,resource,revision)VALUES(%s,'courses',7)ON CONFLICT(account_id,resource)DO UPDATE SET revision=7",(owner,))
            conn.execute((fixture.ROOT/'server/schema.sql').read_text())
            self.assertEqual(conn.execute("SELECT revision FROM team_resource_versions WHERE account_id=%s AND resource='courses'",(owner,)).fetchone()[0],7)
            conn.execute("INSERT INTO team_resource_versions(account_id,resource,revision)VALUES(%s,'content',1)ON CONFLICT(account_id,resource)DO UPDATE SET revision=team_resource_versions.revision+1",(owner,))
            raw=conn.execute('SELECT protected FROM team_history_visits WHERE history_id=%s AND visit_id=%s',(item,visit)).fetchone()[0]
            value=history.restore('visit',owner,item+':'+visit,raw);value['futureCaption']='Never implicitly shared'
            protected=history.protect('visit',owner,item+':'+visit,value);conn.execute('UPDATE team_history_visits SET protected=%s WHERE history_id=%s AND visit_id=%s',(protected,item,visit))
        status,_,received=self.call('/v1/social/history/'+item,who='alice');self.assertEqual(status,200)
        self.assertNotIn('futureCaption',json.dumps(received));self.assertNotIn('Never implicitly shared',json.dumps(received))


    def test_09_linked_reviews_have_no_room_deadline_and_expired_approval_stays_private(self):
        from trip_room_migration import TripRoomMigration
        owner=self.a['user']['id']
        status,_,room=self.call('/v1/social/rooms',dict(name='Trip review',courseId=None,courseVersion=None,expiresInHours=1),'POST','alice')
        self.assertEqual(status,201);rid=room['id']
        self.assertEqual(self.call('/v1/social/rooms/'+rid+'/review-request',dict(consent=True),'PATCH','alice')[0],200)
        self.approve('room',rid)
        with psycopg.connect(self.api.dsn)as conn:
            original=conn.execute('SELECT protected FROM team_rooms WHERE room_id=%s',(rid,)).fetchone()[0]
            conn.execute("UPDATE team_content_reviews SET expires_at=now()-interval '1 second' WHERE kind='room' AND content_key=%s",(rid,))
            TripRoomMigration(self.api.module.TEAM_AUTH).migrate_room(conn,rid)
            trip=conn.execute('SELECT trip_id FROM team_rooms WHERE room_id=%s',(rid,)).fetchone()[0]
            projection=dict(name='Trip review')
            self.assertEqual(self.engine.review(conn,'room',rid,owner,projection)['state'],'private')
            requested=self.engine.request(conn,'room',rid,owner,projection,True)
            self.assertEqual(requested['state'],'quarantined')
            self.assertIsNone(self.engine.row(conn,'room',rid)[5])
        self.approve('room',rid)
        with psycopg.connect(self.api.dsn)as conn:
            self.assertEqual(self.engine.shared(conn,'room',rid,owner,projection),projection)
            revision=conn.execute('SELECT revision FROM team_trips WHERE trip_id=%s',(trip,)).fetchone()[0]
            self.api.module.TEAM_TRIPS.transition(conn,trip,owner,'finish',revision)
            self.assertIsNone(self.engine.shared(conn,'room',rid,owner,projection))
            self.engine.withdraw_trip_context(conn,trip,rid)
            self.assertEqual(conn.execute('SELECT protected FROM team_rooms WHERE room_id=%s',(rid,)).fetchone()[0],original)
            with self.assertRaises(HTTPException)as denied:self.engine.request(conn,'room',rid,owner,projection,True)
            self.assertEqual(denied.exception.status_code,409)
            self.assertFalse(self.engine.request(conn,'room',rid,owner,projection,False)['requested'])

if __name__=='__main__':unittest.main(verbosity=2)
