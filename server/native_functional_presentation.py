import hashlib
import json

from native_functional_policy import FunctionalError, WIRE, validate_snapshot


HEADER = 'X-WegoH-Functional-Presentation'
LEGACY_VERSION = 2
LEGACY_SHA256 = 'ec92f07e28aa015408006bd5430f9d9b440870238fabc9393c176c263d4e6657'


def presentation_version(request):
    values = request.headers.getlist(HEADER)
    if not values or values == ['2']:
        return LEGACY_VERSION
    if values in (['3'], ['4'], ['5']):
        return int(values[0])
    raise FunctionalError(400, 'INVALID_FUNCTIONAL_PRESENTATION')


def present_snapshot(snapshot, version, *, approved_disclosure_version=None):
    current = validate_snapshot(snapshot)
    if type(version) is not int or version not in (LEGACY_VERSION, 3, 4, 5) or WIRE['disclosureVersion'] != 5:
        raise FunctionalError(400, 'INVALID_FUNCTIONAL_PRESENTATION')
    if version == 5:
        return dict(current, approvedDisclosureVersion=approved_disclosure_version)
    profile = next(item for item in WIRE['previousDisclosures'] if item['version'] == version)
    known = profile['purposeIds']
    registry = profile.get('purposeRegistry', [row for row in WIRE['purposeRegistry'] if row['id'] in known])
    actual = hashlib.sha256(json.dumps(dict(version=version, purposes=registry), sort_keys=True,
        ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()
    if (actual != profile['sha256'] or known != [row['id'] for row in registry]
            or version == 2 and (profile['sha256'] != LEGACY_SHA256 or len(known) != 19 or 'driving-score:report' in known)
            or version == 3 and (len(known) != 20 or 'purposeRegistry' not in profile)
            or not set(known) <= {row['id'] for row in WIRE['purposeRegistry']}):
        raise FunctionalError(503, 'FUNCTIONAL_STATE_INVALID')
    result = dict(current, functionalDisclosureVersion=version, functionalDisclosureSha256=profile['sha256'],
        approvedPurposes=[purpose for purpose in current['approvedPurposes'] if purpose in known])

    if version == 4:
        result['approvedDisclosureVersion'] = approved_disclosure_version if approved_disclosure_version in (1, 2, 3, 4) else None
    return result
