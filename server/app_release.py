"""Read-only catalog produced from a verified signed release APK; absent by default."""
import json
import os
from pathlib import Path
import re

from fastapi import APIRouter, HTTPException

PACKAGE = 'io.wegoh.app'
MAX_CATALOG_BYTES = 8192
router = APIRouter()


def validate_release(value):
    if not isinstance(value, dict) or set(value) != {'schemaVersion', 'packageName', 'versionCode', 'versionName', 'apkSha256', 'signingCertificatesSha256'}:
        raise ValueError('Invalid release fields')
    if type(value['schemaVersion']) is not int or value['schemaVersion'] != 1 or value['packageName'] != PACKAGE:
        raise ValueError('Invalid release identity')
    if type(value['versionCode']) is not int or not 0 < value['versionCode'] <= 2147483647:
        raise ValueError('Invalid version code')
    if not isinstance(value['versionName'], str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.+_-]{0,63}', value['versionName']):
        raise ValueError('Invalid version name')
    hashes = [value['apkSha256']]
    certificates = value['signingCertificatesSha256']
    if not isinstance(certificates, list) or not 1 <= len(certificates) <= 8 or not all(isinstance(v,str) for v in certificates) or len(set(certificates)) != len(certificates):
        raise ValueError('Invalid signing certificates')
    hashes += certificates
    if not all(isinstance(v, str) and re.fullmatch('[0-9a-f]{64}', v) for v in hashes):
        raise ValueError('Invalid release fingerprint')
    return value


def load_release(path):
    with Path(path).open('rb') as stream:
        data = stream.read(MAX_CATALOG_BYTES + 1)
    if len(data) > MAX_CATALOG_BYTES:
        raise ValueError('Release catalog too large')
    return validate_release(json.loads(data))


@router.get('/v1/app-release')
def app_release():
    path = os.environ.get('WEGOH_APP_RELEASE_FILE')
    if not path:
        raise HTTPException(404, 'App release unavailable')
    try:
        return load_release(path)
    except (OSError, ValueError, TypeError):
        raise HTTPException(503, 'App release unavailable') from None
