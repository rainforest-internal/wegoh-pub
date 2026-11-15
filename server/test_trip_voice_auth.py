import hashlib
import json
from pathlib import Path
import subprocess
import unittest

from ops.live import auth_compatibility as policy

ROOT = Path(__file__).resolve().parents[1]
BEFORE_VOICE = 'dbbab583acc037875119065147525b349abfdd0e'
VOICE = 'b515c863dd91f067724a791da7828b2813d03f02'
SAVED_PLAYLISTS = '38201f43'


def release_file(revision, name):
    if revision is None:
        return (ROOT / name).read_bytes()
    return subprocess.check_output(['git', 'show', revision + ':' + name], cwd=ROOT)


class TripVoiceAuthTests(unittest.TestCase):
    def assert_transition(self, start, end, profile_id, transition_id, implementation):
        ledger = 'server/ops/live/auth-transitions.json'
        wire = 'server/native_access_wire.json'
        previous = json.loads(release_file(start, ledger))
        current = json.loads(release_file(end, ledger))
        for key, values in previous.items():
            if isinstance(values, list):
                self.assertEqual(current[key][:len(values)], values)
        before = json.loads(release_file(start, wire))
        after = json.loads(release_file(end, wire))
        for key in ('purposeRegistry', 'disclosureVersion', 'disclosureSha256'):
            self.assertEqual(before['functional'][key], after['functional'][key])
        old, new = previous['wireProfiles'][-1], current['wireProfiles'][-1]
        self.assertEqual(new['id'], profile_id)
        writers = {row['id']: row for row in current['dataWriteProfiles']}
        source = {**old['implementationFiles'], **writers[old['dataProfileId']]['files']}
        candidate = {**new['implementationFiles'], **writers[new['dataProfileId']]['files']}
        for revision, files in ((start, source), (end, candidate)):
            for name, digest in files.items():
                self.assertEqual(hashlib.sha256(release_file(revision, name)).hexdigest(), digest, name)
        self.assertIn(implementation, new['implementationFiles'])
        result = policy.plan_auth_transition(before, after, current_files=source, candidate_files=candidate)
        self.assertTrue(result['compatible'], result)
        self.assertTrue(result['authorizationPreserved'])
        self.assertTrue(result['functional']['existingStoredConsentPreserved'])
        self.assertFalse(result['functional']['defaultPolicyChanged'])
        self.assertFalse(result['baseReauthorizationRequired'])
        self.assertEqual(result['transitionId'], transition_id)
        tampered = dict(candidate, **{implementation: '0' * 64})
        self.assertFalse(policy.plan_auth_transition(before, after, current_files=source, candidate_files=tampered)['compatible'])

    def test_release_preserves_identity_and_binds_voice_revocation_implementation(self):
        self.assert_transition(BEFORE_VOICE, VOICE, 'functional-v2-trip-voice-participation-v1',
            'car-group-hand-raise-to-trip-voice-participation', 'server/team_voice.py')

    def test_saved_playlists_extend_trip_permissions_with_two_exact_routes(self):
        self.assert_transition(VOICE, SAVED_PLAYLISTS, 'functional-v2-trip-saved-playlists-v1',
            'trip-voice-participation-to-trip-saved-playlists', 'server/team_trip_saved_playlists.py')
        wire = 'server/native_access_wire.json'
        before = json.loads(release_file(VOICE, wire))['functional']['nativeRoutes']
        after = json.loads(release_file(SAVED_PLAYLISTS, wire))['functional']['nativeRoutes']
        path = '/v1/social/trips/{trip}/music/saved-playlists'
        self.assertEqual([row for row in after if row['path'] != path], before)
        self.assertCountEqual([row for row in after if row['path'] == path], [
            dict(method='GET', path=path, all=['rooms:read'], any=[]),
            dict(method='POST', path=path, all=['rooms:read', 'rooms:interact'], any=[]),
        ])

    def test_native_wire_consumers_and_release_engine_are_exact(self):
        source = (ROOT / 'server/native_access_wire.json').read_bytes()
        for name in ('server/web/native-access-wire.json', 'android/app/src/main/assets/native_access_wire.json'):
            self.assertEqual((ROOT / name).read_bytes(), source)
        vector = json.loads((ROOT / 'android/app/src/androidTest/assets/native_access_vectors.json').read_text())
        self.assertEqual(vector['wireSha256'], hashlib.sha256(source).hexdigest())
        engine = json.loads((ROOT / 'server/ops/live/engine-manifest.json').read_text())
        for name, digest in engine['files'].items():
            self.assertEqual(hashlib.sha256((ROOT / 'server/ops/live' / name).read_bytes()).hexdigest(), digest, name)

    def test_participation_contract_changes_only_one_setting(self):
        from api_doc_trip_merge import BODY, OPS, T, NATIVE_VOICE_PARTICIPATION
        browser = BODY[('patch', T + '/voice-participation')]
        native = BODY[('patch', NATIVE_VOICE_PARTICIPATION)]
        self.assertEqual(set(browser['required']), {'participating', 'memberJoinedAt', 'revision'})
        self.assertEqual(set(native['required']), set(browser['required']) | {'functionalRevision'})
        for path in (T + '/voice-participation', NATIVE_VOICE_PARTICIPATION):
            for method in ('get', 'patch'):
                schema = OPS[(method, path)]['responses']['200']['content']['application/json']['schema']
                self.assertEqual(set(schema['required']), {'tripId', 'participating', 'memberJoinedAt', 'revision'})


if __name__ == '__main__':
    unittest.main()
