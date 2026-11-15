import unittest

import psycopg
import test_team_trips as fixtures


class TripLocationConsentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixtures.TripTests.setUpClass()
        cls.addClassCleanup(fixtures.TripTests.tearDownClass)

    def setUp(self):
        self.h = fixtures.TripTests(methodName='test_v6_creation_privacy_permissions_and_invitation_lifecycle')
        self.h.setUp()
        self.addCleanup(self.h.doCleanups)
        self.owner, self.invited, self.visitor = self.h.sessions()
        self.h.befriend(self.owner, self.invited)

    def create(self, **choice):
        data = dict(title='위치 공유 테스트', description='', memberIds=[self.invited['user']['id']], **choice)
        status, _, result = self.h.trip(data=data, method='POST', session=self.owner)
        self.assertEqual(status, 201, result)
        return result['id']

    def respond(self, trip, **choice):
        return self.h.trip('/'+trip+'/respond', dict(accept=True, **choice), 'POST', session=self.invited)

    def sharing(self, trip, session):
        status, _, workspace = self.h.trip('/'+trip+'/workspace', session=session)
        self.assertEqual(status, 200, workspace)
        return workspace['mySharing']

    def share(self, trip, session, enabled):
        status, _, result = self.h.trip('/'+trip+'/location-sharing', dict(locationConsent=enabled),
                                        'PATCH', session=session)
        self.assertEqual(status, 200, result)
        self.assertIs(result['locationConsent'], enabled)
        return result

    def token(self, trip):
        return self.h.trip('/'+trip+'/link', method='POST', session=self.owner)[2]['token']

    def join(self, session, token, **choice):
        return self.h.social('/trip-links/join', session, dict(token=token, **choice), 'POST')

    def test_create_accept_and_link_join_have_independent_optional_choices(self):
        for choice in ({}, {'locationConsent': False}, {'locationConsent': True}):
            with self.subTest(choice=choice):
                trip = self.create(**choice)
                self.assertIs(self.sharing(trip, self.owner)['location'], bool(choice.get('locationConsent')))
                self.assertEqual(self.respond(trip, **choice)[2], {'status': 'accepted'})
                self.assertIs(self.sharing(trip, self.invited)['location'], bool(choice.get('locationConsent')))
                result = self.join(self.visitor, self.token(trip), **choice)
                self.assertEqual((result[0],result[2]), (200, {'tripId': trip}))
                self.assertIs(self.sharing(trip, self.visitor)['location'], bool(choice.get('locationConsent')))

    def test_retries_keep_choice_and_withdrawal_preserves_seat_and_role(self):
        trip = self.create(locationConsent=False)
        self.assertEqual(self.respond(trip, locationConsent=True)[0], 200)
        initial = self.share(trip, self.invited, True)
        self.assertRegex(initial['locationShareId'], '^[a-f0-9]{32}$')
        self.assertEqual(self.respond(trip, locationConsent=False)[0], 200)
        self.assertTrue(self.sharing(trip, self.invited)['location'])
        self.assertEqual(self.h.rights(trip, self.owner, self.invited, edit=True)[0], 200)
        self.h.vehicle(self.owner)
        car = self.h.new_car(trip, self.owner)
        self.assertEqual(self.h.ride(car, self.invited)[0], 200)
        disabled = self.share(trip, self.invited, False)
        self.assertIsNone(disabled['locationShareId'])
        self.assertEqual(self.share(trip, self.invited, False), disabled)
        self.assertEqual(self.respond(trip, locationConsent=True)[0], 200)
        token = self.token(trip)
        self.assertEqual(self.join(self.invited, token, locationConsent=True)[0], 200)
        self.assertFalse(self.sharing(trip, self.invited)['location'])
        detail = self.h.trip('/'+trip, session=self.invited)[2]
        self.assertTrue(detail['myPermissions']['edit'])
        self.assertIn(self.invited['user']['id'], [peer['id'] for peer in detail['cars'][0]['passengers']])
        fresh = self.share(trip, self.invited, True)
        self.assertNotEqual(fresh['locationShareId'], initial['locationShareId'])
        self.assertEqual(self.share(trip, self.invited, True), fresh)
        self.assertTrue(self.sharing(trip, self.invited)['location'])
        self.assertFalse(self.sharing(trip, self.owner)['location'])

    def test_non_boolean_cannot_grant_consent_or_consume_an_invitation(self):
        trip = self.create()
        token = self.token(trip)
        for invalid in ('true', 1, None):
            with self.subTest(invalid=invalid):
                self.assertEqual(self.respond(trip, locationConsent=invalid)[0], 400)
                self.assertEqual(self.join(self.visitor, token, locationConsent=invalid)[0], 400)
        self.assertEqual(self.h.trip(session=self.invited)[2]['invitations'][0]['tripId'], trip)
        self.assertEqual(self.h.trip('/'+trip, session=self.visitor)[0], 404)
        self.assertEqual(self.h.respond(trip, self.invited, False)[0], 200)
        self.assertEqual(self.h.trip(session=self.invited)[2]['invitations'], [])

    def test_legacy_local_choice_does_not_silently_expand_to_trip_wide_location(self):
        trip = self.create(locationConsent=True)
        account = self.owner['user']['id']
        service = self.h.module.TEAM_TRIPS
        with psycopg.connect(self.h.dsn) as conn:
            member = service.members(conn, trip)[account]
            prior_format = {key: member[key] for key in ('state', 'via', 'permissions')}
            conn.execute('UPDATE team_trip_members SET protected=%s WHERE trip_id=%s AND account_id=%s',
                         (service.protect('member:'+account, trip, prior_format), trip, account))
        self.assertFalse(self.sharing(trip, self.owner)['location'])
        self.assertTrue(self.h.trip('/'+trip, session=self.owner)[2]['isOwner'])
        choices = dict(self.sharing(trip, self.owner), location=True)
        self.assertEqual(self.h.trip('/'+trip+'/sharing', dict(consents=choices), 'PATCH', session=self.owner)[0], 200)
        self.assertFalse(self.sharing(trip, self.owner)['location'])
        confirmed = self.share(trip, self.owner, True)
        self.assertIsNotNone(confirmed['locationShareId'])
        choices['location'] = False
        self.assertEqual(self.h.trip('/'+trip+'/sharing', dict(consents=choices), 'PATCH', session=self.owner)[0], 200)
        self.assertFalse(self.sharing(trip, self.owner)['location'])
