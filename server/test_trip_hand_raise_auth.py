import hashlib
import json
from pathlib import Path
import subprocess
import unittest

from ops.live import auth_compatibility as policy

ROOT = Path(__file__).resolve().parents[1]
PLAN = 'b833b336f97748450fe2d969f1b1bef191c33663'
HAND_RAISE = '5c8e2a19'


def baseline(name, revision=PLAN):
    return subprocess.check_output(['git', 'show', revision + ':' + name], cwd=ROOT)


class TripHandRaiseAuthTests(unittest.TestCase):
    def test_profile_uses_measured_files_preserves_previous_records_and_purposes(self):
        previous = json.loads(baseline('server/ops/live/auth-transitions.json'))
        current = json.loads((ROOT / 'server/ops/live/auth-transitions.json').read_text())
        for section in previous:
            if isinstance(previous[section], list):
                self.assertEqual(current[section][:len(previous[section])], previous[section])
        before = json.loads(baseline('server/native_access_wire.json'))
        after = json.loads(baseline('server/native_access_wire.json', HAND_RAISE))
        current_wire = json.loads((ROOT / 'server/native_access_wire.json').read_text())
        self.assertIn(dict(method='POST', path='/v1/native/trips/{id}/signals/candidates', all=['rooms:read'], any=[]),
            current_wire['functional']['nativeRoutes'])
        for field in ('purposeRegistry', 'disclosureVersion', 'disclosureSha256'):
            self.assertEqual(after['functional'][field], before['functional'][field])
        added = [row for row in after['functional']['nativeRoutes'] if row not in before['functional']['nativeRoutes']]
        self.assertEqual(added, [dict(method='POST', path='/v1/native/trips/{id}/signals/candidates', all=['rooms:read'], any=[])])
        self.assertEqual(len(after['functional']['nativeRoutes']), len(before['functional']['nativeRoutes']) + 1)
        old_profile, new_profile = previous['wireProfiles'][-1], next(row for row in current['wireProfiles'] if row['id'] == 'functional-v2-hand-raise-v1')
        self.assertEqual((old_profile['id'], new_profile['id']), ('functional-v2-trip-plan-v1', 'functional-v2-hand-raise-v1'))
        writers = {row['id']: row for row in current['dataWriteProfiles']}
        old_files = {**old_profile['implementationFiles'], **writers[old_profile['dataProfileId']]['files']}
        new_files = {**new_profile['implementationFiles'], **writers[new_profile['dataProfileId']]['files']}
        self.assertEqual(set(new_files) - set(old_files), {'server/team_trip_hand_raise.py'})
        for name, digest in old_files.items():
            self.assertEqual(hashlib.sha256(baseline(name)).hexdigest(), digest)
        for name, digest in new_files.items():
            self.assertEqual(hashlib.sha256(baseline(name, HAND_RAISE)).hexdigest(), digest)
        result = policy.plan_auth_transition(before, after, current_files=old_files, candidate_files=new_files)
        self.assertTrue(result['compatible'], result)
        self.assertEqual(result['transitionId'], 'trip-plan-to-hand-raise')
        self.assertFalse(result['baseReauthorizationRequired'])
        self.assertTrue(result['functional']['existingStoredConsentPreserved'])
        self.assertEqual(result['rollback']['compatibilityFloor'], 'functional-v2/trip-plan-v1')
        for name in ('server/team_trip_hand_raise.py', 'server/team_trip_routes.py'):
            files = dict(new_files)
            files[name] = '0' * 64
            denied = policy.plan_auth_transition(before, after, current_files=old_files, candidate_files=files)
            self.assertFalse(denied['compatible'])
        engine = json.loads((ROOT / 'server/ops/live/engine-manifest.json').read_text())
        for name, digest in engine['files'].items():
            self.assertEqual(hashlib.sha256((ROOT / 'server/ops/live' / name).read_bytes()).hexdigest(), digest)


if __name__ == '__main__':
    unittest.main()
