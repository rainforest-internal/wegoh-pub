"""Real candidate receipts cannot be moved across trips, accounts or places."""
import copy
import time
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from fastapi import HTTPException
from test_iphone_trip_management import IPhoneTripManagementTests
from trip_candidate_receipts import issue, verify

CANDIDATE = dict(name='공식 후보', lat=37.5, lng=127.0, verdict='ahead', label='모든 차 앞쪽',
    fromRequesterMeters=1800, fromLeadMeters=1200, detourSeconds=180, detourMeters=200,
    facilities=None, source='official', routeName='실제 노선', direction='실제 방향')
DETAILS = {key: CANDIDATE[key] for key in ('routeName', 'direction', 'fromLeadMeters', 'detourSeconds')}


class CandidateReceiptTests(IPhoneTripManagementTests):
    def setup_trip(self):
        self.befriend(self.bob)
        trip = self.create()
        self.join(trip, self.bob)
        self.vehicle()
        self.second_vehicle()
        for session in (self.alice, self.bob):
            self.checked(self.call('/' + trip + '/cars', dict(name='실제 차', seats=2), 'POST', session=session), 201)
        self.checked(self.call('/' + trip + '/start', dict(revision=self.detail(trip)['revision']), 'POST'))
        return trip

    def query(self, trip):
        service = SimpleNamespace(admit=lambda *_: None, find=lambda *_args, **_kwargs: dict(
            basis='route', partial=False, candidates=[copy.deepcopy(CANDIDATE)], cars=[]))
        with patch.object(self.phone.api.module.TEAM_AUTH, 'hand_raise_service', service):
            result = self.checked(self.call('/' + trip + '/signals/candidates', dict(
                kind='cafe', location=dict(lat=37.5, lng=127.0, heading=180)), 'POST'))
        return result['candidates'][0]['candidateReceipt']

    def test_http_receipt_preserves_only_authenticated_estimates(self):
        trip = self.setup_trip()
        receipt = self.query(trip)
        self.assertLessEqual(len(receipt), 2048)
        place = dict(name=CANDIDATE['name'], latitude=CANDIDATE['lat'], longitude=CANDIDATE['lng'])
        data = dict(kind='cafe', destination=place, candidateReceipt=receipt)
        self.assertEqual(self.call('/' + trip + '/signals', dict(data, fromLeadMeters=1), 'POST')[0], 400)
        self.assertEqual(self.call('/' + trip + '/signals', dict(data,
            destination=dict(place, latitude=37.6)), 'POST')[0], 409)
        self.assertEqual(self.call('/' + trip + '/signals', data, 'POST', session=self.bob)[0], 409)
        self.checked(self.call('/' + trip + '/signals', data, 'POST'), 201)
        signal = self.checked(self.call('/' + trip + '/signals', session=self.bob))['signals'][0]
        self.assertEqual(signal['candidateDetails'], DETAILS)
        self.assertNotIn('candidateReceipt', signal)

    def test_trip_revision_change_and_legacy_input(self):
        trip = self.setup_trip()
        receipt = self.query(trip)
        self.checked(self.call('/' + trip, dict(title='변경된 여행', description=''), 'PATCH'))
        place = dict(name=CANDIDATE['name'], latitude=CANDIDATE['lat'], longitude=CANDIDATE['lng'])
        self.assertEqual(self.call('/' + trip + '/signals', dict(kind='cafe', destination=place,
            candidateReceipt=receipt), 'POST')[0], 409)
        self.checked(self.call('/' + trip + '/signals', dict(kind='cafe', destination=place), 'POST'), 201)
        self.assertIsNone(self.checked(self.call('/' + trip + '/signals'))['signals'][0]['candidateDetails'])

    def test_receipt_rejects_tampering_expiry_and_other_contexts(self):
        now = time.time()
        destination = dict(name=CANDIDATE['name'], latitude=CANDIDATE['lat'], longitude=CANDIDATE['lng'])
        receipt = issue('a' * 32, self.a, 7, 'cafe', CANDIDATE, now)
        self.assertEqual(verify(receipt, 'a' * 32, self.a, 7, 'cafe', destination, now), DETAILS)
        for token, trip, account, revision, kind, clock in (
            (receipt[:-8] + 'A' * 8, 'a' * 32, self.a, 7, 'cafe', now),
            (receipt, 'b' * 32, self.a, 7, 'cafe', now),
            (receipt, 'a' * 32, self.b, 7, 'cafe', now),
            (receipt, 'a' * 32, self.a, 8, 'cafe', now),
            (receipt, 'a' * 32, self.a, 7, 'rest', now),
            (receipt, 'a' * 32, self.a, 7, 'cafe', now + 301)):
            with self.subTest(trip=trip, revision=revision, kind=kind, clock=clock), self.assertRaises(HTTPException) as error:
                verify(token, trip, account, revision, kind, destination, clock)
            self.assertEqual((error.exception.status_code, error.exception.detail), (409, 'TRIP_SIGNAL_CANDIDATE_CHANGED'))


def load_tests(loader, tests, pattern):
    return unittest.TestSuite(CandidateReceiptTests(name) for name in CandidateReceiptTests.__dict__ if name.startswith('test_'))
