import unittest
from unittest.mock import patch

import psycopg
import test_native_functional_trips as fixture


class TripPlanNativeHttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixture.NativeTripTests.setUpClass()
        cls.addClassCleanup(fixture.NativeTripTests.tearDownClass)

    def setUp(self):
        self.h=fixture.NativeTripTests()
        self.h.setUp()
        self.addCleanup(self.h.doCleanups)
        self.h.browser(self.h.guest,self.h.path+'/respond',dict(accept=True),'POST')
        self.path='/v1/native/trips/'+self.h.trip

    def test_date_write_requires_edit_and_current_native_revision(self):
        h=self.h
        revision=h.approve(['rooms:interact'])
        body=dict(startDate='2026-11-08',endDate=None,functionalRevision=revision)
        h.native(self.path,body,'PATCH',expected=403)
        h.browser(h.owner,h.path+'/members/'+h.guest['user']['id']+'/permissions',dict(invite=True,edit=True),'PUT')
        h.native(self.path,dict(startDate=None,endDate=None),'PATCH',expected=400)
        h.native(self.path,dict(body,functionalRevision=revision+1),'PATCH',expected=409)
        h.native(self.path,body,'PATCH')
        h.native(self.path)
        revision=h.approve(['rooms:read','rooms:interact'])
        detail=h.native(self.path)
        self.assertEqual(detail['startDate'],'2026-11-08')
        self.assertEqual(detail['link'],dict(active=False,expiresAt=None))
        revoke='/v1/devices/'+h.device['deviceId']+'/functional-permissions/rooms:interact'
        unchanged=h.browser(h.guest,revoke,method='DELETE')
        self.assertEqual(unchanged['revision'],revision)
        h.native(self.path,dict(body,functionalRevision=revision),'PATCH')

    def test_native_friends_lifecycle_and_web_only_routes(self):
        h=self.h
        revision=h.approve(['rooms:read','rooms:interact'])
        h.native(self.path+'/friends',expected=403)
        h.browser(h.owner,h.path+'/members/'+h.guest['user']['id']+'/permissions',dict(invite=True,edit=True),'PUT')
        friends=h.native(self.path+'/friends')['friends']
        self.assertEqual(friends,[dict(id=h.owner['user']['id'],name=h.owner['user']['displayName'],hasVehicle=False,tripState='accepted')])
        detail=h.native(self.path)
        h.native(self.path+'/start',dict(revision=detail['revision'],functionalRevision=revision),'POST',expected=403)
        owner_device=h.factory.connect(h.owner)
        owner_revision=h.factory.approve(h.owner,owner_device,['rooms:interact'])
        h.native(self.path+'/start',dict(revision=detail['revision'],functionalRevision=owner_revision),'POST',device=owner_device)
        h.native(self.path+'/finish',dict(revision=detail['revision'],functionalRevision=owner_revision),'POST',expected=409,device=owner_device)
        for method,suffix,body in [('PUT','/cars/'+'a'*32+'/places/'+'b'*32+'/select',{}),
                ('POST','/cars/'+'a'*32+'/ride-invites/'+'c'*32+'/respond',dict(accept=True))]:
            result=h.factory.native(h.device,self.path+suffix,dict(body,functionalRevision=revision),method)
            self.assertIn(result[0],(403,404))

    def test_native_places_reject_huge_integer_coordinates_without_mutation(self):
        h = self.h
        h.browser(h.guest, '/v1/devices/'+h.device['deviceId']+'/vehicle-profile',
            dict(plateNumber='123가4567', name='', expectedRevision=0), 'PUT')
        revision = h.approve(['rooms:read', 'rooms:interact'])
        car = h.native(self.path+'/cars', dict(name='내 차', seats=2, functionalRevision=revision),
            'POST', expected=201)['id']
        path = self.path+'/cars/'+car+'/places'
        for key in ('lat', 'lng'):
            for value in (10**400, -(10**400)):
                with self.subTest(key=key, positive=value > 0):
                    data = dict(kind='pickup', name='픽업', lat=0, lng=0, functionalRevision=revision)
                    data[key] = value
                    self.assertEqual(h.native(path, data, 'POST', expected=400), dict(detail='Invalid car place'))
        self.assertEqual(h.native(path)['places'], [])

    def test_native_driver_order_completion_and_recheck_after_actor(self):
        h=self.h
        h.browser(h.guest,'/v1/devices/'+h.device['deviceId']+'/vehicle-profile',dict(plateNumber='123가4567',name='',expectedRevision=0),'PUT')
        revision=h.approve(['rooms:read','rooms:interact'])
        car=h.native(self.path+'/cars',dict(name='내 차',seats=2,functionalRevision=revision),'POST',expected=201)['id']
        base=self.path+'/cars/'+car
        place=h.native(base+'/places',dict(kind='pickup',name='픽업',lat=37.5,lng=127,functionalRevision=revision),'POST',expected=201)['id']
        h.native(base+'/route-order',dict(items=[dict(type='pickup',ref=place)],functionalRevision=revision),'PUT')
        self.assertEqual(h.native(base+'/places')['places'][0]['id'],place)
        from native_functional_identity import transaction_actor
        fired=False
        def recheck(auth,request,conn,**kwargs):
            nonlocal fired
            if request.url.path==base+'/route-order' and not fired:
                fired=True
                with psycopg.connect(h.h.dsn) as other:
                    other.execute('UPDATE native_functional_authorizations SET revision=revision+1 WHERE grant_id=%s',(h.device['grantId'],))
            return transaction_actor(auth,request,conn,**kwargs)
        with patch('team_trip_routes.transaction_actor',side_effect=recheck):
            h.native(base+'/route-order',dict(items=[],functionalRevision=revision),'PUT',expected=409)
        self.assertTrue(fired)
        self.assertEqual(h.native(self.path)['cars'][0]['routeOrder'],[dict(type='pickup',ref=place)])

    def test_native_route_progress_checks_revisions_route_membership_and_driver(self):
        h = self.h
        h.browser(h.guest, '/v1/devices/'+h.device['deviceId']+'/vehicle-profile',
            dict(plateNumber='123가4567', name='', expectedRevision=0), 'PUT')
        revision = h.approve(['rooms:read', 'rooms:interact'])
        car = h.native(self.path+'/cars', dict(name='진행 확인 차', seats=2, functionalRevision=revision),
            'POST', expected=201)['id']
        base = self.path+'/cars/'+car
        place = h.native(base+'/places', dict(kind='pickup', name='다음 픽업', lat=37.5, lng=127,
            functionalRevision=revision), 'POST', expected=201)['id']
        current = h.browser(h.owner, h.path)
        h.browser(h.owner, h.path+'/start', dict(revision=current['revision']), 'POST')
        next_item = dict(type='pickup', ref=place)
        body = dict(next=next_item, routeRevision=0, functionalRevision=revision)
        self.assertEqual(h.native(base+'/route-progress', body, 'PUT'), dict(status='updated'))
        detail = h.native(self.path)
        self.assertEqual(detail['cars'][0]['routeNext'], next_item)
        self.assertEqual(detail['cars'][0]['routeRevision'], 0)
        h.native(base+'/route-progress', dict(body, next=dict(type='pickup', ref='f'*32)), 'PUT', expected=400)
        h.native(base+'/route-order', dict(items=[next_item], routeRevision=0, functionalRevision=revision), 'PUT')
        h.native(base+'/route-progress', body, 'PUT', expected=409)
        other = h.factory.connect(h.owner)
        other_revision = h.factory.approve(h.owner, other, ['rooms:read', 'rooms:interact'])
        h.native(base+'/route-progress', dict(next=next_item, routeRevision=1, functionalRevision=other_revision),
            'PUT', expected=403, device=other)
        h.native(base+'/route-progress', dict(next=None, routeRevision=1, functionalRevision=revision+1), 'PUT', expected=409)

    def test_mobile_pickup_replacement_updates_the_saved_native_route(self):
        h = self.h
        h.browser(h.guest, '/v1/devices/'+h.device['deviceId']+'/vehicle-profile',
            dict(plateNumber='123가4567', name='', expectedRevision=0), 'PUT')
        revision = h.approve(['rooms:read', 'rooms:interact'])
        car = h.native(self.path+'/cars', dict(name='픽업 차', seats=2, functionalRevision=revision),
            'POST', expected=201)['id']
        base = self.path+'/cars/'+car
        mobile_car = h.path+'/cars/'+car
        h.browser(h.owner, mobile_car+'/ride', method='PUT')

        def place(kind, name, latitude):
            return h.browser(h.owner, mobile_car+'/places',
                dict(kind=kind, name=name, lat=latitude, lng=127), 'POST', 201)['id']

        def select(place_id):
            return h.browser(h.owner, mobile_car+'/places/'+place_id+'/select', method='PUT')

        old_id = place('pickup', '기존 픽업', 37.5)
        drop_id = place('drop', '하차 장소', 37.6)
        self.assertEqual(select(old_id), dict(status='selected'))
        old_pickup = dict(type='pickup', ref=old_id)
        drop = dict(type='drop', ref=drop_id)
        order = [old_pickup, drop]
        h.native(base+'/route-order', dict(items=order, routeRevision=0, functionalRevision=revision), 'PUT')
        current = h.browser(h.owner, h.path)
        h.browser(h.owner, h.path+'/start', dict(revision=current['revision']), 'POST')
        progress = dict(next=old_pickup, routeRevision=1, functionalRevision=revision)
        h.native(base+'/route-progress', progress, 'PUT')

        new_id = place('pickup', '새 픽업', 37.7)
        self.assertEqual(select(new_id), dict(status='selected'))
        new_pickup = dict(type='pickup', ref=new_id)
        route = h.native(self.path+'?section=route')['cars'][0]
        self.assertEqual(route['routeOrder'], [new_pickup, drop])
        self.assertEqual(route['routeNext'], new_pickup)
        self.assertEqual(route['routeRevision'], 2)
        selections = {item['id']: item['selectedBy'] for item in route['places']}
        self.assertEqual(selections[old_id], [])
        self.assertEqual(selections[new_id], [h.owner['user']['id']])
        h.native(base+'/route-progress', progress, 'PUT', expected=409)
        h.native(base+'/route-order', dict(items=order, routeRevision=1, functionalRevision=revision),
            'PUT', expected=409)
        select(new_id)
        self.assertEqual(h.native(self.path+'?section=route')['cars'][0]['routeRevision'], 2)


if __name__ == '__main__':
    unittest.main()
