import copy
import json
import unittest
from unittest.mock import patch

import psycopg

from native_functional_policy import FunctionalError
from private_records import VisitCipher
from test_friend_vehicle_controls import FriendRemoteTests
from vehicle_control_support import command_problem, public_support, report_body, support_actions


def temperature():
    return dict(id='hvac.temperature', revision=1, status='known', available=True,
                areas=[dict(id='ROW_1_RIGHT', min=15, max=30, step=.5)], zones=[])


class ControlSupportContractTests(unittest.TestCase):
    def test_closed_finite_and_bounded_reports(self):
        valid = dict(functionalRevision=1, receiverRevision=1, actions=[temperature()])
        self.assertEqual(report_body(json.dumps(valid).encode()), valid)
        bad = []
        for change in ({'id': 'new.action'}, {'revision': True}, {'status': 'invented'}, {'available': 1},
                       {'currentValue': 22}, {'available': False}, {'status': 'unknown'}, {'areas': 'ROW_1_RIGHT'},
                       {'zones': None}, {'zones': [['ROW_1_RIGHT']]}, {'zones': [['ROW_1_RIGHT', 'ROW_1_LEFT']]},
                       {'areas': [dict(id='ROW_1_LEFT', min=15, max=30, step=.5)]},
                       {'areas': [dict(id=s, min=15, max=30, step=.5) for s in ('ROW_1_LEFT', 'ROW_1_RIGHT')],
                        'zones': [['ROW_1_LEFT', 'ROW_1_RIGHT']]}):
            bad.append(dict(valid, actions=[dict(temperature(), **change)]))
        for change in ({'id': 'ALL'}, {'min': True}, {'min': -1}, {'max': 51}, {'step': 0},
                       {'step': float('nan')}, {'max': float('inf')}, {'current': 22}):
            item = temperature(); item['areas'] = [dict(item['areas'][0], **change)]
            bad.append(dict(valid, actions=[item]))
        no_zones = temperature(); del no_zones['zones']
        bad.append(dict(valid, actions=[no_zones]))
        duplicate_area = temperature(); duplicate_area['areas'] *= 2
        bad += [dict(valid, actions=[duplicate_area]), dict(valid, actions=[temperature()] * 2),
                dict(valid, actions=[temperature()] * 12), dict(valid, deviceId='d' * 32),
                dict(valid, functionalRevision=True), dict(valid, receiverRevision=0)]
        for value in bad:
            with self.subTest(value=value), self.assertRaises(FunctionalError):
                report_body(json.dumps(value).encode())
        with self.assertRaises(FunctionalError):
            report_body(b'{"functionalRevision":1,"functionalRevision":2}')
        with self.assertRaises(FunctionalError) as caught:
            report_body(b' ' * 12289)
        self.assertEqual(caught.exception.status, 413)

    def test_switches_integer_ranges_and_missing_support(self):
        actions = [dict(id='light.cabin', revision=1, status='known', available=True, areas=[], zones=[]),
                   dict(id='hvac.power', revision=1, status='known', available=True,
                        areas=[dict(id='ROW_1_RIGHT', min=None, max=None, step=None)], zones=[]),
                   dict(id='hvac.fan', revision=1, status='known', available=True,
                        areas=[dict(id='ROW_1_RIGHT', min=1, max=8, step=1)], zones=[]),
                   dict(id='seat.heat', revision=1, status='unknown', available=False, areas=[], zones=[])]
        self.assertEqual(len(support_actions(actions)), 4)
        item = copy.deepcopy(actions[2]); item['areas'][0]['step'] = .5
        with self.assertRaises(FunctionalError):
            support_actions([item])
        action = dict(id='hvac.temperature', revision=1)
        self.assertEqual(public_support(None, action), dict(status='unknown', available=False, areas=[], zones=[], observedAt=None, expiresAt=None))
        snapshot = dict(actions=[temperature()], observedAt='2026-11-13T00:00:00+00:00', expiresAt='2026-11-13T00:01:30+00:00')
        self.assertIsNone(command_problem(None, action, dict(seat='ROW_2_LEFT', value=22)))
        self.assertEqual(command_problem(snapshot, action, dict(seat='ROW_2_LEFT', value=22)), 'VEHICLE_CONTROL_AREA_UNSUPPORTED')
        self.assertEqual(command_problem(snapshot, action, dict(seat='ROW_1_RIGHT', value=22.25)), 'VEHICLE_CONTROL_VALUE_UNSUPPORTED')
        self.assertIsNone(command_problem(snapshot, action, dict(seat='ROW_1_RIGHT', value=22.5)))
        snapshot['actions'] = [dict(temperature(), available=False, areas=[])]
        self.assertEqual(command_problem(snapshot, action, dict(seat='ROW_1_RIGHT', value=22.5)), 'VEHICLE_CONTROL_UNSUPPORTED')

    def test_zones_group_reported_seats_in_seat_order(self):
        cabin = ['ROW_2_RIGHT', 'ROW_3_RIGHT', 'ROW_2_CENTER', 'ROW_1_RIGHT', 'ROW_2_LEFT', 'ROW_1_CENTER']
        seat = lambda seat_id: dict(id=seat_id, min=None, max=None, step=None)
        power = dict(id='hvac.power', revision=1, status='known', available=True,
                     areas=[seat(s) for s in cabin + ['ROW_3_LEFT']], zones=[['ROW_2_RIGHT', 'ROW_2_LEFT'], ['ROW_1_RIGHT', 'ROW_1_CENTER']])
        self.assertEqual(support_actions([power])[0]['zones'], [['ROW_1_CENTER', 'ROW_1_RIGHT'], ['ROW_2_LEFT', 'ROW_2_RIGHT']])
        for zones in ([['ROW_1_CENTER', 'ROW_1_RIGHT'], ['ROW_1_RIGHT', 'ROW_2_LEFT']], [['ROW_1_RIGHT', 'ROW_1_RIGHT']],
                      [['ROW_1_RIGHT', 'ROW_3_CENTER']], [['ROW_1_RIGHT', 'ALL']], [['ROW_1_RIGHT', 1]], 'ROW_1_RIGHT',
                      [['ROW_1_RIGHT', 'ROW_1_CENTER']] * 5, [['ROW_1_LEFT', 'ROW_1_RIGHT']]):
            with self.subTest(zones=zones), self.assertRaises(FunctionalError):
                support_actions([dict(power, zones=zones)])
        # The driver seat is never remotely controlled, so a report naming it (seat, zone or window) is rejected.
        with self.assertRaises(FunctionalError):
            support_actions([dict(power, areas=power['areas'] + [seat('ROW_1_LEFT')], zones=[['ROW_1_LEFT', 'ROW_1_RIGHT']])])
        window = dict(id='window.position', revision=1, status='known', available=True,
                      areas=[dict(id=w, min=0, max=100, step=1) for w in ('ROW_1_RIGHT', 'ROW_2_LEFT')], zones=[])
        self.assertEqual(support_actions([window])[0]['zones'], [])
        for bad in (dict(window, zones=[['ROW_1_RIGHT', 'ROW_2_LEFT']]),
                    dict(window, areas=[dict(id='ROW_1_LEFT', min=0, max=100, step=1)])):
            with self.subTest(window=bad), self.assertRaises(FunctionalError):
                support_actions([bad])

    def test_largest_report_with_zones_fits_body_limit(self):
        from device_command_registry import DRIVER_AREA, SEATS, WINDOWS
        from vehicle_control_support import MAX_BYTES, REGISTRY
        actions = []
        for described in REGISTRY.describe():
            kind = REGISTRY.lookup(described['id'], described['revision']).argument_kind
            if kind == 'switch':
                areas, zones = [], []
            elif kind == 'window-position':
                areas, zones = [dict(id=w, min=0, max=100, step=1) for w in WINDOWS if w != DRIVER_AREA], []
            else:
                low, high, step = {'hvac-celsius': (12.5, 32.5, .5), 'hvac-fan': (0, 100, 1), 'seat-level': (0, 10, 1)}.get(kind, (None, None, None))
                seats = [s for s in SEATS if s != DRIVER_AREA]
                areas = [dict(id=s, min=low, max=high, step=step) for s in seats]
                zones = [seats[0:2], seats[2:4], seats[4:6], seats[6:8]]
            actions.append(dict(id=described['id'], revision=described['revision'], status='known', available=True, areas=areas, zones=zones))
        raw = json.dumps(dict(functionalRevision=2147483647, receiverRevision=2147483647, actions=actions), separators=(',', ':')).encode()
        self.assertLessEqual(len(raw), MAX_BYTES)
        self.assertEqual(len(report_body(raw)['actions']), len(actions))


class ControlSupportHttpTests(FriendRemoteTests):
    def setup_support(self):
        self.setup_remote(); self.start_trip(); self.enable()
        code, receiver = self.native('/v1/device/command-receiver')
        self.assertEqual(code, 200, receiver)
        self.receiver = receiver

    def report(self, actions=None, **changes):
        data = dict(receiverRevision=self.receiver['revision'], actions=[temperature()] if actions is None else actions)
        data.update(changes)
        return self.native('/v1/device/control-support', data, 'PUT')

    def shown(self):
        status, _, value = self.web(self.trip_remotes, who='bob', session=self.b)
        self.assertEqual(status, 200, value)
        return value['remotes'][0]['actions'][0]['support']

    def saved(self):
        with psycopg.connect(self.dsn) as conn:
            row = conn.execute('SELECT protected FROM native_functional_authorizations WHERE grant_id=%s', (self.token['grantId'],)).fetchone()
        return VisitCipher().restore('native-functional', self.token['grantId'], row[0])

    def test_report_is_encrypted_without_authority_revision_or_events_and_gates_only_fresh_known(self):
        self.setup_support()
        self.assertEqual(self.shown()['status'], 'unknown')
        self.assertEqual(self.send('before-support-0001', arguments=dict(seat='ROW_2_LEFT', value=22))[0], 201)
        base = self.factory.state()
        with psycopg.connect(self.dsn) as conn:
            versions = conn.execute('SELECT * FROM team_resource_versions ORDER BY account_id,resource').fetchall()
        code, accepted = self.report()
        self.assertEqual(code, 200, accepted)
        self.assertEqual(accepted['status'], 'accepted')
        self.assertEqual(self.factory.state(), base)
        self.assertEqual(self.native('/v1/device/command-receiver')[1], self.receiver)
        with psycopg.connect(self.dsn) as conn:
            self.assertEqual(conn.execute('SELECT * FROM team_resource_versions ORDER BY account_id,resource').fetchall(), versions)
        stored = self.saved()['receiverSupport']
        self.assertEqual(stored['deviceId'], self.did)
        self.assertEqual(stored['grantId'], self.token['grantId'])
        shown = self.shown()
        self.assertEqual(shown['status'], 'known'); self.assertTrue(shown['available'])
        self.assertEqual(shown['areas'], temperature()['areas']); self.assertEqual(shown['zones'], [])
        code, _, denied = self.send('unsupported-area-01', arguments=dict(seat='ROW_2_LEFT', value=22))
        self.assertEqual(code, 422, denied); self.assertEqual(denied['detail'], 'VEHICLE_CONTROL_AREA_UNSUPPORTED')
        self.assertEqual(self.send('unsupported-step-01', arguments=dict(seat='ROW_1_RIGHT', value=22.25))[0], 422)
        self.assertEqual(self.send('supported-value-01')[0], 201)
        self.assertEqual(self.send('before-support-0001', arguments=dict(seat='ROW_2_LEFT', value=22))[0], 201)
        self.assertEqual(self.report([dict(temperature(), status='unknown', available=False, areas=[], zones=[])])[0], 200)
        self.assertEqual(self.send('unknown-compat-0001', arguments=dict(seat='ROW_2_LEFT', value=22))[0], 201)

    def test_stored_report_in_an_older_format_reads_as_no_report(self):
        # Reports saved before zones existed must not break every read of the grant's consent.
        from native_functional_policy import stored_functional_payload
        self.setup_support(); self.assertEqual(self.report()[0], 200)
        payload = self.saved()
        for action in payload['receiverSupport']['actions']:
            del action['zones']
        with psycopg.connect(self.dsn) as conn:
            conn.execute('UPDATE native_functional_authorizations SET protected=%s WHERE grant_id=%s',
                (VisitCipher().protect('native-functional', self.token['grantId'], payload), self.token['grantId']))
            row = conn.execute('SELECT grant_id,protected,revision FROM native_functional_authorizations WHERE grant_id=%s',
                (self.token['grantId'],)).fetchone()
        restored = stored_functional_payload(dict(grant_id=row[0], protected=row[1], revision=row[2]))
        self.assertNotIn('receiverSupport', restored)
        self.assertEqual(self.native('/v1/device/command-receiver')[0], 200)
        self.assertEqual(self.shown()['status'], 'unknown')
        self.assertEqual(self.send('old-format-compat-1', arguments=dict(seat='ROW_2_LEFT', value=22))[0], 201)
        self.assertEqual(self.report()[0], 200)
        self.assertEqual(self.shown()['status'], 'known')

    def test_receiver_off_and_reenable_drop_snapshot_and_stale_receiver_is_rejected(self):
        self.setup_support(); self.assertEqual(self.report()[0], 200)
        code, off = self.tls.native('/v1/device/command-receiver', dict(grantId=self.receiver['grantId'], revision=self.receiver['revision'], enabled=False), 'PUT', token=self.token['accessToken'])
        self.assertEqual(code, 200, off); self.assertNotIn('receiverSupport', self.saved())
        self.assertEqual(self.report()[0], 403)
        code, on = self.tls.native('/v1/device/command-receiver', dict(grantId=off['grantId'], revision=off['revision'], enabled=True), 'PUT', token=self.token['accessToken'])
        self.assertEqual(code, 200, on)
        self.assertEqual(self.shown()['status'], 'unknown')
        self.assertEqual(self.report()[0], 409)
        self.receiver = on; self.assertEqual(self.report()[0], 200)

    def test_ttl_and_credential_epoch_make_observations_unknown(self):
        self.setup_support(); self.assertEqual(self.report()[0], 200)
        authorization = self.h.module.TEAM_AUTH.native_authorization
        current = authorization.now()
        with patch.object(authorization, 'clock', return_value=current + 91):
            self.assertEqual(self.shown()['status'], 'unknown')
            self.assertEqual(self.send('expired-compatible-1', arguments=dict(seat='ROW_2_LEFT', value=22))[0], 201)
        self.assertEqual(self.shown()['status'], 'known')
        with psycopg.connect(self.dsn) as conn:
            conn.execute('UPDATE native_v2_grants SET credential_epoch=credential_epoch+1 WHERE grant_id=%s', (self.token['grantId'],))
        self.assertEqual(self.shown()['status'], 'unknown')

    def test_report_rejects_browser_wrong_revision_and_functional_change_drops_metadata(self):
        self.setup_support()
        data = dict(functionalRevision=self.functional_revision, receiverRevision=self.receiver['revision'], actions=[temperature()])
        self.assertEqual(self.web('/v1/device/control-support', data, 'PUT', session=self.a)[0], 404)
        self.functional_revision -= 1
        self.assertEqual(self.report()[0], 409)
        self.functional_revision += 1
        self.assertEqual(self.report()[0], 200)
        self.functional_revision = self.factory.approve(self.a, self.token, ['device-commands:receive', 'room-music:read'])
        self.assertNotIn('receiverSupport', self.saved())
        self.assertEqual(self.shown()['status'], 'unknown')

    def test_native_report_requires_vehicle_category_and_same_certificate(self):
        self.setup_remote()
        status, self.receiver = self.native('/v1/device/command-receiver')
        self.assertEqual(status, 200)
        code, value = self.report()
        self.assertEqual(code, 403, value)
        self.assertEqual(value['error'], 'VEHICLE_OWNER_REQUIRED')
        data = dict(functionalRevision=self.functional_revision, receiverRevision=self.receiver['revision'], actions=[temperature()])
        self.assertEqual(self.tls.native('/v1/device/control-support', data, 'PUT', token=self.token['accessToken'], client='b')[0], 403)


def load_tests(loader, tests, pattern):
    return unittest.TestSuite(loader.loadTestsFromNames([name], kind) for kind in
        (ControlSupportContractTests, ControlSupportHttpTests) for name in vars(kind) if name.startswith('test_'))
