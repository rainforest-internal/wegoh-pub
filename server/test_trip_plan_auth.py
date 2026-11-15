import hashlib
import json
from pathlib import Path
import subprocess
import unittest

from ops.live import auth_compatibility as policy

ROOT=Path(__file__).resolve().parents[1]
BASE='1dd3157fa87f227a63fd3a3ad200458770465f41'
PLAN='b833b336f97748450fe2d969f1b1bef191c33663'


def baseline(name, revision=BASE):
    return subprocess.check_output(['git','show',revision+':'+name],cwd=ROOT)


class TripPlanAuthTests(unittest.TestCase):
    def test_profile_uses_measured_files_preserves_previous_records_and_purposes(self):
        previous=json.loads(baseline('server/ops/live/auth-transitions.json'))
        current=json.loads((ROOT/'server/ops/live/auth-transitions.json').read_text())
        for section in previous:
            if isinstance(previous[section],list):
                self.assertEqual(current[section][:len(previous[section])],previous[section])
        before=json.loads(baseline('server/native_access_wire.json'))
        after=json.loads(baseline('server/native_access_wire.json',PLAN))
        for field in ('purposeRegistry','disclosureVersion','disclosureSha256'):
            self.assertEqual(after['functional'][field],before['functional'][field])
        old_profile=previous['wireProfiles'][-1]
        new_profile=next(row for row in current['wireProfiles'] if row['id']=='functional-v2-trip-plan-v1')
        old_writer=next(row for row in previous['dataWriteProfiles'] if row['id']==old_profile['dataProfileId'])
        new_writer=next(row for row in current['dataWriteProfiles'] if row['id']==new_profile['dataProfileId'])
        old_files={**old_profile['implementationFiles'],**old_writer['files']}
        new_files={**new_profile['implementationFiles'],**new_writer['files']}
        for name,digest in old_files.items():
            self.assertEqual(hashlib.sha256(baseline(name)).hexdigest(),digest)
        for name,digest in new_files.items():
            self.assertEqual(hashlib.sha256(baseline(name,PLAN)).hexdigest(),digest)
        result=policy.plan_auth_transition(before,after,current_files=old_files,candidate_files=new_files)
        self.assertTrue(result['compatible'],result)
        self.assertEqual(result['transitionId'],'trip-room-merge-to-trip-plan')
        self.assertFalse(result['baseReauthorizationRequired'])
        for name in ('server/team_trip_plan.py','server/team_trip_routes.py'):
            files=dict(new_files);files[name]='0'*64
            denied=policy.plan_auth_transition(before,after,current_files=old_files,candidate_files=files)
            self.assertFalse(denied['compatible'])
        engine=json.loads((ROOT/'server/ops/live/engine-manifest.json').read_text())
        for name,digest in engine['files'].items():
            self.assertEqual(hashlib.sha256((ROOT/'server/ops/live'/name).read_bytes()).hexdigest(),digest)


if __name__ == '__main__':
    unittest.main()
