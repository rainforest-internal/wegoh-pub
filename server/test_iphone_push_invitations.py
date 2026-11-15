import unittest
from unittest.mock import patch

import psycopg
from fastapi import HTTPException

from iphone_push_invitations import invitation_visible
import test_team_trips as trip_fixture


class TripInvitationPushTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = trip_fixture.TripTests
        cls.fixture.setUpClass()
        cls.addClassCleanup(cls.fixture.tearDownClass)

    def setUp(self):
        self.h = self.fixture(methodName='test_v6_creation_privacy_permissions_and_invitation_lifecycle')
        self.h.setUp()
        self.addCleanup(self.h.doCleanups)
        self.a, self.b, self.e = self.h.sessions()
        self.h.befriend(self.a, self.b)
        self.queued = []

        def capture(conn, *, kind, actor, recipients, resource_id, trip_id=None):
            if kind == 'trip_invitation':
                self.assertEqual(len(recipients), 1)
                self.queued.append(dict(kind=kind, actor_id=actor, recipient_id=recipients[0],
                                        resource_id=resource_id, trip_id=trip_id))

        self.enterContext(patch('iphone_push.enqueue_push', side_effect=capture))

    def visible(self, event):
        with psycopg.connect(self.h.dsn) as conn:
            return invitation_visible(conn, event, self.h.module.TEAM_AUTH, None)

    def test_create_retry_decline_reinvite_and_accepted(self):
        trip = self.h.new_trip(self.a, members=[self.b])
        self.assertEqual(len(self.queued), 1)
        first = self.queued[0]
        self.assertEqual(first['trip_id'], trip)
        self.assertEqual(first['actor_id'], self.a['user']['id'])
        self.assertEqual(first['recipient_id'], self.b['user']['id'])
        self.assertTrue(self.visible(first))
        self.assertEqual(self.h.invite(trip, self.a, self.b)[0], 200)
        self.assertEqual(len(self.queued), 1)
        self.assertEqual(self.h.respond(trip, self.b, accept=False)[0], 200)
        self.assertFalse(self.visible(first))
        self.assertEqual(self.h.invite(trip, self.a, self.b)[0], 201)
        self.assertEqual(len(self.queued), 2)
        second = self.queued[1]
        self.assertNotEqual(first['resource_id'], second['resource_id'])
        self.assertFalse(self.visible(first))
        self.assertTrue(self.visible(second))
        self.assertEqual(self.h.respond(trip, self.b)[0], 200)
        self.assertFalse(self.visible(second))

    def test_delegate_invite_permissions_and_friends_rechecked(self):
        self.h.befriend(self.b, self.e, who='eve')
        trip = self.h.new_trip(self.a, members=[self.b])
        self.assertEqual(self.h.respond(trip, self.b)[0], 200)
        self.assertEqual(self.h.rights(trip, self.a, self.b, invite=True)[0], 200)
        self.assertEqual(self.h.invite(trip, self.b, self.e)[0], 201)
        event = self.queued[-1]
        self.assertTrue(self.visible(event))
        self.assertEqual(self.h.rights(trip, self.a, self.b, invite=False)[0], 200)
        self.assertFalse(self.visible(event))
        self.assertEqual(self.h.rights(trip, self.a, self.b, invite=True)[0], 200)
        self.assertEqual(self.h.friend('/friends/' + self.e['user']['id'], method='DELETE', session=self.b, who='bob')[0], 200)
        self.assertFalse(self.visible(event))

    def test_closed_trip_and_enqueue_failure(self):
        trip = self.h.new_trip(self.a)
        with patch('iphone_push.enqueue_push', side_effect=HTTPException(503, 'Synthetic outbox failure')):
            self.assertEqual(self.h.invite(trip, self.a, self.b)[0], 503)
        self.assertEqual(self.h.trip(session=self.b)[2]['invitations'], [])
        self.assertEqual(self.h.invite(trip, self.a, self.b)[0], 201)
        event = self.queued[-1]
        self.assertTrue(self.visible(event))
        self.h.close_trip(trip, self.a)
        self.assertFalse(self.visible(event))
