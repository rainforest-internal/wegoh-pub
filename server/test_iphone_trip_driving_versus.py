import unittest

import psycopg
import test_iphone_trips as fixture


class IPhoneDrivingVersusTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixture.IPhoneTripTests.setUpClass.__func__(cls)

    def setUp(self):
        self.h = fixture.IPhoneTripTests()
        self.h.setUp()
        self.addCleanup(self.h.phone.doCleanups)
        h = self.h
        h.befriend(h.bob)
        self.trip = h.create()
        h.join(self.trip, h.bob)
        h.vehicle()
        self.car = h.checked(h.call('/' + self.trip + '/cars', dict(name='현재 차', seats=2), 'POST'), 201)['id']
        self.path = '/' + self.trip + '/driving-versus'

    def test_current_driver_and_rider_only_and_existing_read_scope_required(self):
        h = self.h
        value = h.checked(h.call(self.path))
        self.assertEqual((value['state'], value['reason'], value['winnerCarIds']),
            ('unavailable', 'contract-unavailable', []))
        self.assertEqual(h.call(self.path, session=h.bob)[0], 404)
        h.checked(h.call('/' + self.trip + '/cars/' + self.car + '/ride', {}, 'PUT', session=h.bob))
        response = h.call(self.path, session=h.bob)
        h.checked(response)
        self.assertEqual(h.phone.header(response[1], 'cache-control'), 'private, no-store')
        h.checked(h.call('/' + self.trip + '/ride', {}, 'DELETE', session=h.bob))
        self.assertEqual(h.call(self.path, session=h.bob)[0], 404)
        self.assertEqual(h.call(self.path, session=h.eve)[0], 404)
        with psycopg.connect(h.phone.api.dsn) as conn:
            conn.execute("UPDATE iphone_sessions SET scopes=ARRAY['account:read'] WHERE account_id=%s", (h.a,))
        self.assertEqual(h.call(self.path)[0], 403)

    def test_no_mission_consent_or_web_endpoint_and_query_is_closed(self):
        h = self.h
        self.assertEqual(h.call(self.path + '?carId=' + self.car)[0], 400)
        web = h.phone.api.login()
        self.assertEqual(h.phone.api.call('/v1/social/trips/' + self.trip + '/driving-versus', session=web)[0], 404)
        self.assertEqual(h.call(self.path, {}, 'POST')[0], 405)


if __name__ == '__main__':
    unittest.main()
