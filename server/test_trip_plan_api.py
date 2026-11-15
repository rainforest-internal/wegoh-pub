import json
import unittest
from unittest.mock import patch

import psycopg
from test_trip_merge_api import TripApiFixture


class TripPlanTests(TripApiFixture):
    def setup_car(self, *, owner_driver=True, seats=2, provision_vehicle=True):
        trip = self.h.new_trip(self.a)
        self.h.join(trip, self.a, self.b)
        self.h.join(trip, self.a, self.e)
        driver, rider = (self.a, self.b) if owner_driver else (self.b, self.e)
        if provision_vehicle:
            self.h.vehicle(driver)
        car = self.h.new_car(trip, driver, seats=seats).split('/')[-1]
        self.assertEqual(self.api(trip, '/cars/'+car+'/ride', rider, method='PUT')[0],200)
        return trip, car, driver, rider

    def place(self, trip, car, session, kind='pickup', lat=37.5, lng=127):
        value = self.api(trip, '/cars/'+car+'/places', session, dict(kind=kind,name='만날 장소',lat=lat,lng=lng), 'POST')
        self.assertEqual(value[0],201,value[2])
        return value[2]['id']

    def detail(self, trip, session):
        value = self.api(trip, '', session)
        self.assertEqual(value[0],200,value[2])
        return value[2]

    def select(self, trip, car, place, session, method='PUT'):
        return self.api(trip, '/cars/'+car+'/places/'+place+'/select', session, method=method)

    def test_dates_permissions_validation_and_lifecycle_projection(self):
        result = self.h.trip(data=dict(title='날짜 여행',description='',memberIds=[],startDate='2026-11-08',endDate='2026-12-08'), method='POST',session=self.a)
        self.assertEqual(result[0],201,result[2]);trip=result[2]['id']
        self.h.join(trip,self.a,self.b)
        dates=dict(startDate='2028-02-29',endDate='2028-03-30')
        self.assertEqual(self.api(trip,'',self.b,dates,'PATCH')[0],403)
        self.assertEqual(self.h.rights(trip,self.a,self.b,edit=True)[0],200)
        self.assertEqual(self.api(trip,'',self.b,dates,'PATCH')[0],200)
        detail=self.detail(trip,self.a)
        self.assertEqual({key:detail[key] for key in dates},dates)
        self.assertEqual(detail['title'],'날짜 여행')
        summary=self.h.trip(session=self.a)[2]['trips'][0]
        self.assertEqual({key:summary[key] for key in dates},dates)
        self.assertEqual(summary['state'],'planned')
        for body in ({},dict(title='제목만'),dict(startDate=None),dict(startDate='2026-02-29',endDate=None),
                dict(startDate='2026-01-01',endDate='2026-02-01'),dict(startDate=None,endDate=None,extra=True)):
            self.assertEqual(self.api(trip,'',self.a,body,'PATCH')[0],400)
        self.assertEqual(self.api(trip,'',self.a,dates,'PATCH',csrf=False)[0],403)
        self.assertEqual(self.api(trip,'',self.a,dict(startDate=None,endDate=None),'PATCH')[0],200)
        self.transition(trip,'start')
        self.assertEqual(self.detail(trip,self.a)['state'],'active')
        self.assertEqual(self.detail(trip,self.a)['revision'],self.workspace(trip,self.a)['revision'])

    def test_list_includes_past_trips_until_archived_and_hides_closed_pending_invites(self):
        self.h.befriend(self.a, self.b)
        planned = self.h.new_trip(self.a, members=(self.b,))
        active = self.h.new_trip(self.a)
        completed = self.h.new_trip(self.a, members=(self.b,))
        cancelled = self.h.new_trip(self.a, members=(self.b,))
        self.assertEqual(self.h.respond(completed, self.b)[0], 200)
        dates = dict(startDate='2026-11-08', endDate='2026-11-09')
        self.assertEqual(self.api(completed, '', self.a, dates, 'PATCH')[0], 200)
        self.transition(completed, 'start')
        self.transition(completed, 'finish')
        self.transition(active, 'start')
        self.transition(cancelled, 'cancel')
        listing = self.h.trip(session=self.a)[2]
        self.assertEqual({item['id']: item['state'] for item in listing['trips']},
            {planned: 'planned', active: 'active', completed: 'completed', cancelled: 'cancelled'})
        closed = next(item for item in listing['trips'] if item['id'] == completed)
        self.assertEqual({key: closed[key] for key in dates}, dates)
        guest = self.h.trip(session=self.b)[2]
        self.assertEqual([(item['id'], item['state']) for item in guest['trips']], [(completed, 'completed')])
        self.assertEqual([item['tripId'] for item in guest['invitations']], [planned])
        self.assertEqual(self.h.trip(session=self.e)[2], dict(trips=[], invitations=[]))
        self.assertEqual(self.api(completed, '', self.a, method='DELETE')[0], 200)
        self.assertEqual(self.api(cancelled, '', self.a, method='DELETE')[0], 200)
        self.assertEqual({item['id'] for item in self.h.trip(session=self.a)[2]['trips']}, {planned, active})
        self.assertEqual(self.h.trip(session=self.b)[2]['trips'], [])

    def test_place_visibility_selection_replacement_cleanup_and_notifications(self):
        trip,car,driver,rider=self.setup_car(owner_driver=False)
        service=self.h.module.TEAM_TRIPS
        before=self.h.revision(driver)
        place=self.place(trip,car,rider)
        self.assertGreater(self.h.revision(driver),before)
        with psycopg.connect(self.dsn) as conn:
            self.assertGreater(conn.execute("SELECT revision FROM team_resource_versions WHERE account_id=%s AND resource='rooms'",
                ('trip-account:'+driver['user']['id'],)).fetchone()[0],0)
            raw=conn.execute('SELECT protected FROM team_trip_car_places WHERE trip_id=%s AND car_id=%s',(trip,car)).fetchone()[0]
            self.assertNotIn('만날 장소'.encode(),bytes(raw))
        for session in (self.a,driver,rider):
            item=self.detail(trip,session)['cars'][0]['places'][0]
            self.assertEqual(set(item),{'id','kind','name','lat','lng','addedBy','createdAt','selectedBy'})
        self.assertEqual(self.select(trip,car,place,driver)[0],403)
        self.assertEqual(self.select(trip,car,place,rider)[0],200)
        second=self.place(trip,car,driver)
        self.assertEqual(self.select(trip,car,second,rider)[0],200)
        places={item['id']:item for item in self.detail(trip,driver)['cars'][0]['places']}
        self.assertEqual(places[place]['selectedBy'],[])
        self.assertEqual(places[second]['selectedBy'],[rider['user']['id']])
        self.assertEqual(self.select(trip,car,place,rider,'DELETE')[0],200)
        self.assertEqual(self.api(trip,'/cars/'+car+'/places/'+second,self.a,method='DELETE')[0],403)
        self.assertEqual(self.api(trip,'/ride',rider,method='DELETE')[0],200)
        self.assertEqual(self.detail(trip,rider)['cars'][0]['places'],[dict(name='만날 장소',selectedBy=0)]*2)
        self.assertEqual(self.api(trip,'/cars/'+car+'/places/'+place,rider,method='DELETE')[0],200)
        self.assertEqual(self.api(trip,'/cars/'+car,driver,method='DELETE')[0],200)
        with psycopg.connect(self.dsn) as conn:
            for table in ('team_trip_car_places','team_trip_car_place_selections'):
                self.assertEqual(conn.execute('SELECT count(*) FROM '+table+' WHERE trip_id=%s',(trip,)).fetchone()[0],0)

    def test_member_readiness_follows_acceptance_car_vehicle_and_places(self):
        self.h.befriend(self.a,self.b)
        trip=self.h.new_trip(self.a,members=(self.b,))
        self.h.join(trip,self.a,self.e)
        a,b,e=(session['user']['id'] for session in (self.a,self.b,self.e))
        def readiness(session=self.a):
            return {member['id']:member['readiness'] for member in self.detail(trip,session)['members']}
        self.assertEqual(readiness(),{a:'needsCar',b:'invited',e:'needsCar'})
        device=self.h.vehicle(self.a)
        car=self.h.new_car(trip,self.a).split('/')[-1]
        self.assertEqual(self.h.respond(trip,self.b)[0],200)
        self.assertEqual(readiness(),{a:'ready',b:'needsCar',e:'needsCar'})
        self.assertEqual(self.api(trip,'/cars/'+car+'/ride',self.b,method='PUT')[0],200)
        self.assertEqual(readiness(self.e),{a:'ready',b:'needsPlaces',e:'needsCar'})
        pickup=self.place(trip,car,self.a)
        drop=self.place(trip,car,self.b,'drop')
        def detail_version():
            with psycopg.connect(self.dsn) as conn:
                row=conn.execute("SELECT revision FROM team_resource_versions WHERE account_id=%s AND resource='rooms'",
                    ('event-trip:'+trip+':detail',)).fetchone()
            return row[0] if row else 0
        before=detail_version()
        self.assertEqual(self.select(trip,car,pickup,self.b)[0],200)
        self.assertGreater(detail_version(),before)
        self.assertEqual(readiness()[b],'needsPlaces')
        self.assertEqual(self.select(trip,car,drop,self.b)[0],200)
        self.assertEqual(readiness(self.e)[b],'ready')
        before=detail_version()
        self.assertEqual(self.api(trip,'/cars/'+car+'/places/'+drop,self.a,method='DELETE')[0],200)
        self.assertGreater(detail_version(),before)
        self.assertEqual(readiness()[b],'needsPlaces')
        with psycopg.connect(self.dsn) as conn:
            conn.execute('UPDATE native_v2_installations SET revoked_at=1 WHERE installation_key_id='
                '(SELECT installation_key_id FROM native_v2_grants WHERE device_id=%s)',(device['deviceId'],))
        self.assertEqual(readiness(self.b),{a:'needsVehicle',b:'needsPlaces',e:'needsCar'})

    def test_place_limits_permissions_and_scoped_ids(self):
        trip,car,driver,rider=self.setup_car()
        base='/cars/'+car+'/places'
        self.assertEqual(self.api(trip,base,self.e,dict(kind='pickup',name='x',lat=0,lng=0),'POST')[0],403)
        place=self.place(trip,car,driver)
        for update in (dict(kind='bad'),dict(lat=True),dict(lng=181),dict(name='x'*41),dict(extra=1)):
            data=dict(kind='pickup',name='x',lat=0,lng=0);data.update(update)
            self.assertEqual(self.api(trip,base,rider,data,'POST')[0],400)
        self.assertEqual(self.api(trip,base+'/'+place,rider,method='DELETE')[0],403)
        other=self.h.new_trip(self.a)
        self.assertEqual(self.api(other,base+'/'+place,driver,method='DELETE')[0],404)
        for _ in range(9):self.place(trip,car,rider)
        self.assertEqual(self.api(trip,base,rider,dict(kind='pickup',name='x',lat=0,lng=0),'POST')[2],dict(detail='Car place limit reached'))
        self.place(trip,car,rider,'drop')
        self.assertEqual(self.api(trip,base,rider,method='POST',raw=b'{"kind":"drop","kind":"pickup"}')[0],400)
        self.assertEqual(self.api(trip,base,rider,method='POST',raw=b' '*4097)[0],413)
        self.assertEqual(self.api(trip,base,rider,dict(kind='drop',name='x',lat=0,lng=0),'POST',csrf=False)[0],403)

    def test_places_reject_huge_integer_coordinates_without_mutation(self):
        trip, car, driver, rider = self.setup_car()
        path = '/cars/'+car+'/places'
        for key in ('lat', 'lng'):
            for value in (10**400, -(10**400)):
                with self.subTest(key=key, positive=value > 0):
                    data = dict(kind='pickup', name='픽업', lat=0, lng=0)
                    data[key] = value
                    status, _, body = self.api(trip, path, rider, data, 'POST')
                    self.assertEqual(status, 400, body)
                    self.assertEqual(body, dict(detail='Invalid car place'))
        self.assertEqual(self.detail(trip, driver)['cars'][0]['places'], [])

    def test_pickup_replacement_respects_saved_route_slots_and_progress(self):
        self.h.vehicle(self.a)
        for case in ('planned', 'shared', 'omitted', 'already included', 'passed', 'ended', 'unreported'):
            with self.subTest(case=case):
                trip, car, driver, rider = self.setup_car(provision_vehicle=False)
                base = '/cars/'+car
                old_id = self.place(trip, car, rider)
                new_id = self.place(trip, car, rider, lat=37.6)
                drop_id = self.place(trip, car, rider, 'drop', lat=37.7)
                old_pickup = dict(type='pickup', ref=old_id)
                new_pickup = dict(type='pickup', ref=new_id)
                drop = dict(type='drop', ref=drop_id)
                self.assertEqual(self.select(trip, car, old_id, rider)[0], 200)
                if case == 'shared':
                    self.assertEqual(self.api(trip, base+'/ride', self.e, method='PUT')[0], 200)
                    self.assertEqual(self.select(trip, car, old_id, self.e)[0], 200)
                items = [] if case == 'omitted' else [old_pickup]
                if case == 'already included':
                    items.append(new_pickup)
                items.append(drop)
                self.assertEqual(self.api(trip, base+'/route-order', driver, dict(items=items), 'PUT')[0], 200)
                if case in ('passed', 'ended', 'unreported'):
                    # The same driver ran the previous case's trip; one active trip per person.
                    self.transition(trip, 'start', endActiveTrip=True)
                if case in ('passed', 'ended'):
                    progress = dict(next=drop if case == 'passed' else None, routeRevision=1)
                    self.assertEqual(self.api(trip, base+'/route-progress', driver, progress, 'PUT')[0], 200)

                before = self.detail(trip, driver)['cars'][0]
                self.assertEqual(self.select(trip, car, new_id, rider)[0], 200)
                after = self.detail(trip, driver)['cars'][0]
                self.assertEqual(after['routeOrder'], [new_pickup, drop] if case == 'planned' else items)
                self.assertEqual(after['routeRevision'], before['routeRevision'] + (case == 'planned'))
                self.assertEqual(after.get('routeNext'), before.get('routeNext'))
                self.assertEqual('routeNext' in after, 'routeNext' in before)
                places = {place['id']: place for place in after['places']}
                self.assertEqual(places[new_id]['selectedBy'], [rider['user']['id']])

    def test_route_course_requirements_merge_and_omission_preserves_places(self):
        trip,car,driver,rider=self.setup_car()
        pack=self.h.published_course(driver)
        with psycopg.connect(self.dsn) as conn:
            conn.execute('DELETE FROM pack_reviews WHERE checksum IN (SELECT checksum FROM pack_versions WHERE pack_id=%s)',(pack['id'],))
        self.assertEqual(self.h.attach(trip,pack,driver)[0],201)
        pickup=self.place(trip,car,rider)
        stop=pack['stops'][0]
        drop=self.place(trip,car,rider,'drop',stop['latitude'],stop['longitude'])
        self.select(trip,car,pickup,rider)
        items=[dict(type='course',courseId=pack['id'],ref=entry['id']) for entry in pack['stops']]
        items[0]['dropRef']=drop
        path='/cars/'+car+'/route-order'
        self.assertEqual(self.api(trip,path,rider,dict(items=items),'PUT')[0],403)
        self.assertEqual(self.api(trip,path,driver,dict(items=[]),'PUT')[2],dict(detail='All course places are required'))
        self.assertEqual(self.api(trip,path,driver,dict(items=items),'PUT')[0],200)
        detail=self.detail(trip,rider)
        self.assertEqual(detail['cars'][0]['routeOrder'],items)
        self.h.approve(pack,driver)
        self.assertEqual(self.detail(trip,rider)['cars'][0]['routeOrder'],items)
        self.assertEqual(detail['cars'][0]['places'][0]['selectedBy'],[rider['user']['id']])
        self.assertEqual([entry['id'] for entry in detail['courses'][0]['stops']],
                         [entry['id'] for entry in pack['stops']])
        other=dict(items=[dict(item) for item in items],routeRevision=self.detail(trip,driver)['cars'][0]['routeRevision']);other['items'][0].pop('dropRef');other['items'].append(dict(type='drop',ref=drop))
        self.assertEqual(self.api(trip,path,driver,other,'PUT')[0],400)
        self.assertEqual(self.api(trip,'/cars/'+car+'/places/'+drop,rider,method='DELETE')[0],200)
        self.assertNotIn('dropRef',self.detail(trip,driver)['cars'][0]['routeOrder'][0])
        self.assertEqual(self.h.detach(trip,pack,driver)[0],200)
        self.assertIsNone(self.detail(trip,driver)['cars'][0]['routeOrder'])

    def test_ride_invite_privacy_capacity_atomic_move_and_kick(self):
        trip,car,driver,rider=self.setup_car(seats=1)
        base='/cars/'+car
        self.assertEqual(self.api(trip,base+'/ride-invites',rider,dict(accountId=self.e['user']['id']),'POST')[0],403)
        self.assertEqual(self.api(trip,base+'/ride-invites',driver,dict(accountId=self.e['user']['id']),'POST')[2],dict(detail='Car is full'))
        self.assertEqual(self.api(trip,'/ride',rider,method='DELETE')[0],200)
        invite=self.api(trip,base+'/ride-invites',driver,dict(accountId=rider['user']['id']),'POST')
        self.assertEqual(invite[0],201,invite[2]);identifier=invite[2]['id']
        self.assertEqual(self.detail(trip,self.e)['rideInvites'],[])
        self.assertEqual(self.detail(trip,rider)['rideInvites'][0]['id'],identifier)
        response=base+'/ride-invites/'+identifier+'/respond'
        self.assertEqual(self.api(trip,response,self.e,dict(accept=True),'POST')[0],404)
        self.assertEqual(self.api(trip,base+'/ride',self.e,method='PUT')[0],200)
        self.assertEqual(self.api(trip,response,rider,dict(accept=True),'POST')[2],dict(detail='Car is full'))
        self.assertEqual(len(self.detail(trip,rider)['rideInvites']),1)
        self.assertEqual(self.api(trip,base+'/riders/'+self.e['user']['id'],rider,method='DELETE')[0],403)
        self.assertEqual(self.api(trip,base+'/riders/'+self.e['user']['id'],driver,method='DELETE')[0],200)
        self.assertEqual(self.api(trip,response,rider,dict(accept=True),'POST')[0],200)
        self.assertEqual(self.detail(trip,rider)['rideInvites'],[])
        place=self.place(trip,car,rider);self.select(trip,car,place,rider)
        self.assertEqual(self.api(trip,base+'/riders/'+rider['user']['id'],driver,method='DELETE')[0],200)
        self.assertIn(rider['user']['id'],[p['id'] for p in self.detail(trip,driver)['unassigned']])
        with psycopg.connect(self.dsn) as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM team_trip_car_place_selections WHERE trip_id=%s',(trip,)).fetchone()[0],0)

    def test_completion_active_driver_idempotency_and_course_cleanup(self):
        trip,car,driver,rider=self.setup_car()
        pack=self.h.published_course(driver);self.h.attach(trip,pack,driver)
        path='/cars/'+car+'/courses/'+pack['id']+'/complete'
        self.assertEqual(self.api(trip,path,driver,method='POST')[0],409)
        self.transition(trip,'start')
        self.assertEqual(self.api(trip,path,rider,method='POST')[0],403)
        self.assertEqual(self.api(trip,path,driver,method='POST')[0],200)
        revision=self.detail(trip,driver)['revision'];event=self.h.revision(driver)
        self.assertEqual(self.api(trip,path,driver,method='POST')[0],200)
        self.assertEqual(self.detail(trip,driver)['revision'],revision)
        self.assertEqual(self.h.revision(driver),event)
        self.assertEqual(self.detail(trip,rider)['courses'][0]['completedCarIds'],[car])
        self.assertEqual(self.h.detach(trip,pack,driver)[0],200)
        with psycopg.connect(self.dsn) as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM team_trip_car_course_completions WHERE trip_id=%s',(trip,)).fetchone()[0],0)
        self.transition(trip,'finish')
        self.assertEqual(self.api(trip,'/cars/'+car+'/places',driver,dict(kind='pickup',name='x',lat=0,lng=0),'POST')[0],409)

    def test_invite_accept_moves_from_other_car_and_member_cleanup(self):
        trip,car,driver,rider=self.setup_car()
        self.h.vehicle(self.e)
        other=self.h.new_car(trip,self.e).split('/')[-1]
        place=self.place(trip,car,rider);self.select(trip,car,place,rider)
        base='/cars/'+other+'/ride-invites'
        self.assertEqual(self.api(trip,base,self.e,dict(accountId=driver['user']['id']),'POST')[2],dict(detail='Already driving'))
        invite=self.api(trip,base,self.e,dict(accountId=rider['user']['id']),'POST')[2]['id']
        self.assertEqual(self.api(trip,base+'/'+invite,self.a,method='DELETE')[0],403)
        self.assertEqual(self.api(trip,base+'/'+invite+'/respond',rider,dict(accept=True),'POST')[0],200)
        with psycopg.connect(self.dsn) as conn:
            self.assertEqual(conn.execute('SELECT car_id FROM team_trip_riders WHERE trip_id=%s AND account_id=%s',
                (trip,rider['user']['id'])).fetchone()[0],other)
            self.assertEqual(conn.execute('SELECT count(*) FROM team_trip_car_place_selections WHERE trip_id=%s',(trip,)).fetchone()[0],0)
        back=self.api(trip,'/cars/'+car+'/ride-invites',driver,dict(accountId=rider['user']['id']),'POST')[2]['id']
        self.assertEqual(self.api(trip,'/cars/'+car+'/ride-invites/'+back,driver,method='DELETE')[0],200)
        self.assertEqual(self.detail(trip,rider)['rideInvites'],[])
        self.api(trip,'/cars/'+car+'/ride-invites',driver,dict(accountId=rider['user']['id']),'POST')
        self.assertEqual(self.api(trip,'/members/'+rider['user']['id'],rider,method='DELETE')[0],200)
        with psycopg.connect(self.dsn) as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM team_trip_ride_invites WHERE trip_id=%s',(trip,)).fetchone()[0],0)
            self.assertEqual(conn.execute('SELECT count(*) FROM team_trip_riders WHERE trip_id=%s',(trip,)).fetchone()[0],0)

    def test_block_hides_place_authors_selections_and_invites(self):
        trip,car,driver,rider=self.setup_car(owner_driver=False)
        place=self.place(trip,car,rider);self.select(trip,car,place,rider)
        self.api(trip,'/cars/'+car+'/ride-invites',driver,dict(accountId=rider['user']['id']),'POST')
        self.assertEqual(self.h.social('/blocks',driver,dict(targetId=rider['user']['id']),'POST')[0],201)
        detail=self.detail(trip,driver)
        self.assertEqual(detail['cars'][0]['places'],[])
        self.assertEqual(detail['rideInvites'],[])
        self.assertNotIn(rider['user']['id'],json.dumps(detail))
        self.assertEqual(self.api(trip,'/cars/'+car+'/places/'+place,driver,method='DELETE')[0],404)
        self.assertEqual(self.h.social('/blocks',self.a,dict(targetId=driver['user']['id']),'POST')[0],201)
        with psycopg.connect(self.dsn) as conn:
            for table in ('team_trip_car_places','team_trip_car_place_selections','team_trip_ride_invites'):
                self.assertEqual(conn.execute('SELECT count(*) FROM '+table+' WHERE trip_id=%s',(trip,)).fetchone()[0],0)


if __name__ == '__main__':
    unittest.main()
