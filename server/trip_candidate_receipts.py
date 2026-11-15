"""Short-lived authenticated candidate metadata; no new key or database store."""
import base64
import binascii
import math
import re

from fastapi import HTTPException
from private_records import PrivateRecordError, VisitCipher

SECONDS = 300
MAXIMUM = 2048
DETAIL_KEYS = {'routeName', 'direction', 'fromLeadMeters', 'detourSeconds'}


def details(value):
    if not isinstance(value, dict) or set(value) != DETAIL_KEYS:
        raise ValueError('Invalid candidate details')
    for key, maximum in (('routeName', 100), ('direction', 80)):
        text = value[key]
        if text is not None and (not isinstance(text, str) or not 1 <= len(text) <= maximum
                or any(ord(char) < 32 for char in text)):
            raise ValueError('Invalid candidate label')
    for key, minimum in (('fromLeadMeters', 0), ('detourSeconds', -2147483647)):
        number = value[key]
        if number is not None and (type(number) is not int or not minimum <= number <= 2147483647):
            raise ValueError('Invalid candidate metric')
    return dict(value)


def issue(trip, account, revision, kind, candidate, now):
    value = dict(tripRevision=revision, kind=kind, expiresAt=int(now) + SECONDS,
        destination=dict(name=candidate['name'], latitude=candidate['lat'], longitude=candidate['lng']),
        details=details({key: candidate.get(key) for key in DETAIL_KEYS}))
    raw = VisitCipher().protect('trip-candidate:' + account, trip, value)
    token = base64.urlsafe_b64encode(raw).rstrip(b'=').decode('ascii')
    if len(token) > MAXIMUM:
        raise ValueError('Candidate receipt limit exceeded')
    return token


def verify(token, trip, account, revision, kind, destination, now):
    try:
        if (not isinstance(token, str) or not 1 <= len(token) <= MAXIMUM
                or not re.fullmatch(r'[A-Za-z0-9_-]+', token)):
            raise ValueError('Invalid candidate receipt')
        raw = base64.b64decode(token + '=' * (-len(token) % 4), altchars=b'-_', validate=True)
        value = VisitCipher().restore('trip-candidate:' + account, trip, raw)
        if (not isinstance(value, dict) or set(value) != {'tripRevision', 'kind', 'expiresAt', 'destination', 'details'}
                or value['tripRevision'] != revision or value['kind'] != kind
                or type(value['expiresAt']) is not int or not math.isfinite(now)
                or not now <= value['expiresAt'] <= now + SECONDS
                or value['destination'] != destination):
            raise ValueError('Candidate selection changed')
        return details(value['details'])
    except (ValueError, TypeError, binascii.Error, PrivateRecordError):
        raise HTTPException(409, 'TRIP_SIGNAL_CANDIDATE_CHANGED') from None
