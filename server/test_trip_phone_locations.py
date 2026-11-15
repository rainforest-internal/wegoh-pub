from datetime import datetime, timedelta, timezone

import psycopg
import test_trip_merge_api as fixtures
from team_trips import TeamTrips


class TripPhoneLocationTests(fixtures.TripApiFixture):
    def create(self, owner):
        status, _, result = self.h.trip(data=dict(title='위치 공유', description='', memberIds=[]),
            method='POST', session=owner)
        self.assertEqual(status, 201, result)
        return result['id']

    def join(self, trip, session, *, share):
        token = self.api(trip, '/link', self.a, method='POST')[2]['token']
        status, _, result = self.h.social('/trip-links/join', session,
            dict(token=token, locationConsent=share), 'POST')
        self.assertEqual(status, 200, result)

    def locations(self, trip, viewer):
        status, headers, result = self.api(trip, '/locations', viewer)
        self.assertEqual(status, 200, result)
        self.assertIn('no-store', headers['cache-control'])
        self.assertEqual(result['tripId'], trip)
        return result

    def send(self, trip, session, sample, expected=200, **kwargs):
        status, _, result = self.api(trip, '/locations/me', session, sample, 'POST', **kwargs)
        self.assertEqual(status, expected, result)
        if expected == 200:
            self.assertEqual(result, {'status': 'accepted'})

    def test_location_visibility_during_trip(self):
        trip = self.create(self.a)
        self.join(trip, self.b, share=True)
        self.h.transition_trip(trip, self.a, 'start')
        self.assertEqual(self.api(trip, '/locations', self.e)[0], 404)
        self.assertEqual(self.locations(trip, self.a)['locations'], [])
        self.assertIsNone(self.locations(trip, self.a)['shareId'])
        share_id = self.locations(trip, self.b)['shareId']
        now = datetime.now(timezone.utc)
        sample = dict(shareId=share_id, latitude=37.5264, longitude=127.0784, accuracyMeters=12,
                      capturedAt=now.isoformat())
        self.send(trip, self.b, sample, expected=403, csrf=False)
        self.send(trip, self.b, sample)
        self.send(trip, self.b, sample)
        self.send(trip, self.b, dict(sample, latitude=37, capturedAt=(now-timedelta(seconds=1)).isoformat()), 409)
        self.send(trip, self.b, dict(sample, accountId=self.a['user']['id']), 400)
        self.send(trip, self.b, dict(sample, latitude=True), 400)
        self.send(trip, self.b, dict(sample, capturedAt=(now-timedelta(minutes=5)).isoformat()), 400)
        self.send(trip, self.a, sample, 403)

        row, = self.locations(trip, self.a)['locations']
        self.assertEqual((row['accountId'], row['name'], row['source'], row['latitude'], row['longitude'],
                          row['accuracyMeters']), (self.b['user']['id'], 'bob', 'phone', 37.5264, 127.0784, 12))
        self.assertNotIn('shareId', row)
        self.assertEqual(self.h.rights(trip, self.a, self.b, edit=True)[0], 200)
        for payload in (self.workspace(trip, self.a), self.api(trip, '', self.a)[2]):
            self.assertNotIn(share_id, str(payload))
            self.assertNotIn(str(row['latitude']), str(payload))
        self.assertEqual(self.locations(trip, self.b)['locations'], [row])
        self.join(trip, self.e, share=False)
        self.assertEqual(self.locations(trip, self.e)['locations'], [row])
        other = self.create(self.b)
        with fixtures.trip_fixture.concurrent_active_trips():
            self.h.transition_trip(other, self.b, 'start')
        self.assertEqual(self.locations(other, self.b)['locations'], [])

        status, _, result = self.h.social('/blocks', self.e, dict(targetId=self.b['user']['id']), 'POST')
        self.assertEqual(status, 201, result)
        self.assertEqual(self.locations(trip, self.e)['locations'], [])
        self.assertEqual(self.locations(trip, self.a)['locations'], [row])
        self.h.transition_trip(trip, self.a, 'finish')
        self.assertEqual(self.api(trip, '/locations', self.a)[0], 409)
        self.send(trip, self.b, sample, 409)

    def test_car_location_comes_from_its_shared_occupants(self):
        trip = self.create(self.a)
        self.join(trip, self.b, share=False)
        self.join(trip, self.e, share=True)
        self.h.vehicle(self.b)
        car_path = self.h.new_car(trip, self.b)
        car = car_path.split('/')[-1]
        self.assertEqual(self.h.ride(car_path, self.a)[0], 200)
        self.h.transition_trip(trip, self.a, 'start')
        status, _, reply = self.api(trip, '/location-sharing', self.a, dict(locationConsent=True), 'PATCH')
        self.assertEqual(status, 200, reply)
        self.assertEqual(self.locations(trip, self.e)['cars'], [])
        now = datetime.now(timezone.utc)
        rider = dict(shareId=self.locations(trip, self.a)['shareId'], latitude=37.51, longitude=127.02,
                     accuracyMeters=7, capturedAt=(now-timedelta(seconds=2)).isoformat())
        self.send(trip, self.a, rider)
        walker = dict(shareId=self.locations(trip, self.e)['shareId'], latitude=37.6, longitude=127.1,
                      accuracyMeters=3, capturedAt=now.isoformat())
        self.send(trip, self.e, walker)

        result = self.locations(trip, self.e)
        seen = {row['accountId']: row for row in result['locations']}
        self.assertEqual(set(seen), {self.a['user']['id'], self.e['user']['id']})
        alice = seen[self.a['user']['id']]
        expected = dict(carId=car, source='phone', latitude=37.51, longitude=127.02, accuracyMeters=7,
                        capturedAt=alice['capturedAt'])
        self.assertEqual(result['cars'], [expected])
        self.assertEqual(self.locations(trip, self.b)['cars'], [expected])
        for payload in (self.api(trip, '', self.e)[2], self.workspace(trip, self.e)):
            self.assertNotIn('37.51', str(payload))

        status, _, reply = self.h.social('/blocks', self.e, dict(targetId=self.b['user']['id']), 'POST')
        self.assertEqual(status, 201, reply)
        blocked = self.locations(trip, self.e)
        self.assertEqual(blocked['cars'], [])
        self.assertIn(alice, blocked['locations'])
        self.assertEqual(self.locations(trip, self.a)['cars'], [expected])

        status, _, reply = self.api(trip, '/location-sharing', self.a, dict(locationConsent=False), 'PATCH')
        self.assertEqual(status, 200, reply)
        self.assertEqual(self.locations(trip, self.b)['cars'], [])

    def test_old_and_retried_fixes_cannot_revive_after_withdrawal_or_rejoin(self):
        trip = self.create(self.a)
        self.join(trip, self.b, share=True)
        self.h.transition_trip(trip, self.a, 'start')
        first = self.locations(trip, self.b)['shareId']
        now = datetime.now(timezone.utc)
        sample = dict(shareId=first, latitude=37.5264, longitude=127.0784, accuracyMeters=4,
                      capturedAt=now.isoformat())
        self.send(trip, self.b, sample)
        for enabled in (False, True):
            status, _, result = self.api(trip, '/location-sharing', self.b,
                dict(locationConsent=enabled), 'PATCH')
            self.assertEqual(status, 200, result)
            self.assertEqual(self.locations(trip, self.a)['locations'], [])
            self.assertEqual(self.locations(trip, self.b)['locations'], [])
            self.send(trip, self.b, sample, 409 if enabled else 403)
        second = self.locations(trip, self.b)['shareId']
        self.assertTrue(second)
        self.assertNotEqual(first, second)
        current_sample = dict(sample, shareId=second, capturedAt=datetime.now(timezone.utc).isoformat())
        self.send(trip, self.b, current_sample)
        status, _, result = self.api(trip, '/members/'+self.b['user']['id'], self.b, method='DELETE')
        self.assertEqual(status, 200, result)
        self.assertEqual(self.api(trip, '/locations', self.b)[0], 404)
        self.assertEqual(self.locations(trip, self.a)['locations'], [])
        self.join(trip, self.b, share=True)
        self.assertNotEqual(second, self.locations(trip, self.b)['shareId'])
        self.send(trip, self.b, current_sample, 409)
        self.assertEqual(self.locations(trip, self.b)['locations'], [])

    def test_expired_fix_is_hidden_and_trip_finish_erases_latest_fix(self):
        trip = self.create(self.a)
        self.join(trip, self.b, share=True)
        self.h.transition_trip(trip, self.a, 'start')
        account = self.b['user']['id']
        now = datetime.now(timezone.utc)
        sample = dict(shareId=self.locations(trip, self.b)['shareId'], capturedAt=now.isoformat(),
                      latitude=37.58881, longitude=127.04449, accuracyMeters=8)
        self.send(trip, self.b, sample)
        query = 'SELECT protected FROM team_trip_members WHERE trip_id=%s AND account_id=%s'
        with psycopg.connect(self.dsn) as conn:
            raw, = conn.execute(query, (trip, account)).fetchone()
            self.assertNotIn(b'37.58881', raw)
            member = TeamTrips.restore('member:'+account, trip, raw)
            saved = member['phoneLocation']
            self.assertEqual(saved['shareId'], sample['shareId'])
            self.assertEqual(saved['latitude'], sample['latitude'])
            saved['capturedAt'] = (now-timedelta(seconds=61)).isoformat()
            conn.execute('UPDATE team_trip_members SET protected=%s WHERE trip_id=%s AND account_id=%s',
                (TeamTrips.protect('member:'+account, trip, member), trip, account))
        self.assertEqual(self.locations(trip, self.a)['locations'], [])
        self.send(trip, self.b, dict(sample, capturedAt=datetime.now(timezone.utc).isoformat()))
        self.h.transition_trip(trip, self.a, 'finish')
        with psycopg.connect(self.dsn) as conn:
            raw, = conn.execute(query, (trip, account)).fetchone()
            self.assertNotIn('phoneLocation', TeamTrips.restore('member:'+account, trip, raw))

    def test_native_location_belongs_to_current_car_and_share_period(self):
        trip = self.create(self.a)
        self.join(trip, self.b, share=False)
        self.h.transition_trip(trip, self.a, 'start')
        self.assertEqual(self.api(trip, '/location-sharing', self.a,
            dict(locationConsent=True), 'PATCH')[0], 200)
        _, _, car = self.h.pair(self.a)
        certificate = self.h._native_fingerprint
        path = '/v1/native/trips/' + trip + '/locations'

        def native(suffix='', data=None, method='GET', expected=200, *, credential=car, fingerprint=certificate):
            status, headers, result = self.h.native(path + suffix, data, method,
                token=credential['accessToken'], certificate=fingerprint)
            self.assertEqual(status, expected, result)
            if expected == 200:
                self.assertIn('no-store', headers['cache-control'])
            return result

        current = native()
        revision = self.h.native('/v1/device/functional-permissions', token=car['accessToken'],
            certificate=certificate)[2]['revision']
        sample = dict(shareId=current['shareId'], capturedAt=datetime.now(timezone.utc).isoformat(),
            latitude=37.52, longitude=127.07, accuracyMeters=5, functionalRevision=revision)
        self.assertEqual(self.h.call(path, session=self.a)[0], 404)
        native('/me', dict(sample, functionalRevision=revision+1), 'POST', 409)
        native('/me', dict(sample, deviceId='f'*32), 'POST', 400)
        native('/me', sample, 'POST')
        row, = self.locations(trip, self.b)['locations']
        self.assertEqual((row['accountId'], row['source'], row['latitude']), (self.a['user']['id'], 'vehicle', 37.52))
        _, _, viewer_car = self.h.pair(self.b, 'bob')
        viewer_certificate = self.h._native_fingerprint
        self.assertEqual(native(credential=viewer_car, fingerprint=viewer_certificate)['locations'], [row])
        native('/me', sample, 'POST', 403, credential=viewer_car, fingerprint=viewer_certificate)
        native(expected=401, fingerprint=viewer_certificate)
        for enabled in (False, True):
            self.assertEqual(self.api(trip, '/location-sharing', self.a,
                dict(locationConsent=enabled), 'PATCH')[0], 200)
            self.assertEqual(self.locations(trip, self.b)['locations'], [])
            native('/me', sample, 'POST', 409 if enabled else 403)
        sample.update(shareId=native()['shareId'], capturedAt=datetime.now(timezone.utc).isoformat())
        native('/me', sample, 'POST')
        self.assertEqual(self.h.call('/v1/devices/'+car['deviceId'], method='DELETE', session=self.a)[0], 200)
        self.assertEqual(self.locations(trip, self.b)['locations'], [])
        native(expected=401)
        _, _, other_car = self.h.pair(self.a)
        other_certificate = self.h._native_fingerprint
        sample.update(capturedAt=datetime.now(timezone.utc).isoformat())
        native('/me', sample, 'POST', credential=other_car, fingerprint=other_certificate)
        self.h.transition_trip(trip, self.a, 'finish')
        native(expected=409, credential=other_car, fingerprint=other_certificate)
        with psycopg.connect(self.dsn) as conn:
            raw, = conn.execute('SELECT protected FROM team_trip_members WHERE trip_id=%s AND account_id=%s',
                (trip, self.a['user']['id'])).fetchone()
            self.assertNotIn('vehicleLocation', TeamTrips.restore('member:'+self.a['user']['id'], trip, raw))
