"""Direct course publication and member additions over isolated real HTTP/DB."""
import unittest

import psycopg
import test_team_trips as trip_fixture


class DirectCourseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        trip_fixture.TripTests.setUpClass()

    @classmethod
    def tearDownClass(cls):
        trip_fixture.TripTests.tearDownClass()

    def setUp(self):
        self.http = trip_fixture.TripTests(methodName='test_v6_courses_permissions_review_visibility_and_member_cleanup')
        self.http.setUp()
        self.owner, self.member, self.other = self.http.sessions()

    def test_saved_course_is_immediately_public_and_member_can_add_it(self):
        api = self.http
        trip = api.new_trip(self.owner)
        api.join(trip, self.owner, self.member)
        pack = api.pack()
        status, _, saved = api.publish(pack, self.member, 'bob')
        self.assertEqual(status, 201)
        self.assertEqual(saved['state'], 'approved')
        detail = api.trip('/'+trip, session=self.member)[2]
        self.assertFalse(detail['isOwner'])
        self.assertFalse(detail['myPermissions']['edit'])
        self.assertEqual(api.attach(trip, pack, self.member)[0], 201)
        self.assertEqual(api.attach(trip, pack, self.member)[0], 200)
        shown = api.trip('/'+trip, session=self.owner)[2]['courses'][0]
        self.assertEqual(shown['title'], pack['title'])
        self.assertTrue(shown['reviewed'])
        self.assertEqual(len(shown['stops']), 1)
        self.assertEqual(api.call(f"/v1/packs/{pack['id']}/versions/1", session=self.other, who='eve')[0], 200)
        library = api.call('/v1/studio/course-library', session=self.other, who='eve')[2]
        self.assertIn(pack['id'], [item['id'] for item in library['public']])
        with psycopg.connect(api.dsn) as conn:
            events = conn.execute('SELECT state,reviewer FROM pack_review_events WHERE checksum=%s', (saved['checksum'],)).fetchall()
        self.assertEqual(events, [('approved', 'creator-publication')])

    def test_addition_still_requires_accepted_membership_and_open_trip(self):
        api = self.http
        pack = api.pack()
        self.assertEqual(api.publish(pack, self.member, 'bob')[0], 201)
        trip = api.new_trip(self.owner)
        self.assertEqual(api.attach(trip, pack, self.member)[0], 404)
        api.befriend(self.owner, self.member)
        self.assertEqual(api.invite(trip, self.owner, self.member)[0], 201)
        self.assertEqual(api.attach(trip, pack, self.member)[0], 404)
        self.assertEqual(api.respond(trip, self.member)[0], 200)
        self.assertEqual(api.attach(trip, pack, self.member)[0], 201)
        api.close_trip(trip, self.owner)
        self.assertEqual(api.attach(trip, pack, self.member)[0], 409)

    def test_reported_course_is_not_republished_by_retry(self):
        api = self.http
        pack = api.pack()
        self.assertEqual(api.publish(pack, self.member, 'bob')[0], 201)
        self.assertEqual(api.call(f"/v1/packs/{pack['id']}/versions/1/reports", dict(reason='privacy'), 'POST', session=self.owner)[0], 202)
        self.assertEqual(api.publish(pack, self.member, 'bob')[2]['state'], 'quarantined')
        self.assertEqual(api.call(f"/v1/packs/{pack['id']}/versions/1", session=self.other, who='eve')[0], 404)

    def legacy_course(self, state=None):
        api = self.http
        pack = api.pack()
        status, _, saved = api.publish(pack, self.member, 'bob')
        self.assertEqual(status, 201)
        checksum = saved['checksum']
        with psycopg.connect(api.dsn) as conn:
            conn.execute('DELETE FROM pack_reviews WHERE checksum=%s', (checksum,))
            conn.execute('DELETE FROM pack_review_events WHERE checksum=%s', (checksum,))
            if state is not None:
                conn.execute('INSERT INTO pack_reviews(checksum,state,reviewer,review_note) VALUES(%s,%s,%s,%s)',
                    (checksum, state, 'legacy-import', 'Legacy state without a report or moderation event'))
        return pack, checksum

    def test_legacy_missing_or_unreviewed_courses_are_available_without_changing_stored_rows(self):
        api = self.http
        from course_publication import available
        for state in (None, 'quarantined', 'rejected'):
            with self.subTest(state=state):
                pack, checksum = self.legacy_course(state)
                public = f"/v1/packs/{pack['id']}/versions/1"
                self.assertEqual(api.call(public, session=self.other, who='eve')[0], 200)
                library = api.call('/v1/studio/course-library', session=self.other, who='eve')[2]
                self.assertIn(pack['id'], [item['id'] for item in library['public']])
                self.assertEqual(api.call(f"/v1/studio/course-stars/{pack['id']}/versions/1",
                    method='PUT', session=self.other, who='eve')[0], 200)
                owned = api.call('/v1/studio/packs', session=self.member, who='bob')[2]['packs']
                self.assertEqual(next(item for item in owned if item['id'] == pack['id'])['state'], 'approved')
                trip = api.new_trip(self.owner)
                api.join(trip, self.owner, self.member)
                self.assertEqual(api.attach(trip, pack, self.member)[0], 201)
                shown = api.trip('/' + trip, session=self.owner)[2]['courses'][0]
                self.assertEqual(shown['title'], pack['title'])
                self.assertEqual(shown['stops'][0]['id'], pack['stops'][0]['id'])
                self.assertTrue(shown['reviewed'])
                with psycopg.connect(api.dsn) as conn:
                    self.assertTrue(available(conn, checksum))
                    row = conn.execute('SELECT state FROM pack_reviews WHERE checksum=%s', (checksum,)).fetchone()
                    self.assertEqual(row, (state,) if state else None)
                    self.assertEqual(conn.execute('SELECT count(*) FROM pack_review_events WHERE checksum=%s', (checksum,)).fetchone()[0], 0)

    def test_v2_start_and_arrivals_accept_a_legacy_course_without_review(self):
        api = self.http
        pack, _ = self.legacy_course('quarantined')
        trip = api.new_trip(self.owner)
        api.join(trip, self.owner, self.member)
        api.vehicle(self.owner)
        car_path = api.new_car(trip, self.owner)
        car = car_path.rsplit('/', 1)[1]
        self.assertEqual(api.attach(trip, pack, self.member)[0], 201)
        detail = api.trip('/' + trip, session=self.owner)[2]
        start = api.trip('/' + trip + '/start', dict(revision=detail['revision'], routeContractVersion=2),
                         'POST', session=self.owner)
        self.assertEqual(start[0], 200, start[2])
        detail = api.trip('/' + trip, session=self.owner)[2]
        shown = next(item for item in detail['cars'] if item['id'] == car)
        plan = shown['routePlan']
        self.assertEqual(plan['contractVersion'], 2)
        result = api.trip('/' + car_path + '/route-arrivals',
            dict(routeRevision=shown['routeRevision'], progressRevision=plan['progressRevision'], item=plan['next']),
            'POST', session=self.owner)
        self.assertEqual(result[0], 200, result[2])

    def test_actual_reports_and_operator_rejections_remain_post_publication_restrictions(self):
        api = self.http
        from course_publication import available
        pack, checksum = self.legacy_course()
        public = f"/v1/packs/{pack['id']}/versions/1"
        self.assertEqual(api.call(public + '/reports', dict(reason='privacy'), 'POST', session=self.owner)[0], 202)
        self.assertEqual(api.call(public, session=self.other, who='eve')[0], 404)
        with psycopg.connect(api.dsn) as conn:
            self.assertFalse(available(conn, checksum))
        self.assertEqual(api.approve(pack, self.owner)[0], 200)
        self.assertEqual(api.call(public, session=self.other, who='eve')[0], 200)
        with psycopg.connect(api.dsn) as conn:
            conn.execute('DELETE FROM content_reports WHERE checksum=%s', (checksum,))
            conn.execute("UPDATE pack_reviews SET state='rejected',reviewer='operator',review_note='Explicit moderation' WHERE checksum=%s", (checksum,))
            conn.execute("INSERT INTO pack_review_events(checksum,state,reviewer,review_note) VALUES(%s,'rejected','operator','Explicit moderation')", (checksum,))
            self.assertFalse(available(conn, checksum))
        self.assertEqual(api.call(public, session=self.other, who='eve')[0], 404)
