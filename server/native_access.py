from native_principal import is_native_principal
"""Explicit, revocable per-device social read purposes.

Existing paired devices retain only their original course/music access. Missing
new purpose fields always mean false; no permission is inferred from role,
friendship, pairing, or knowledge of a resource ID.
"""
import json
import re
from urllib.parse import urlsplit

import psycopg
from fastapi import APIRouter, HTTPException, Request, Response
from private_records import VisitCipher
from native_access_codec import decode_json, CodecError
from team_data import changed

PURPOSES = ('friends', 'rooms', 'history')
DEVICE_ID = re.compile(r'[a-f0-9]{32}')


def empty_permissions():
    return {purpose: False for purpose in PURPOSES}


def read_actor(auth, request, purpose):
    if purpose not in PURPOSES:
        raise ValueError('Unknown device purpose')
    if not getattr(request.state, 'device_identity', None):
        return auth.browser(request)
    access = getattr(auth, 'native_access', None)
    if access is None or request.method != 'GET':
        raise HTTPException(404, 'Not found')
    return access.authorize(request, purpose)


def native_resource(request):
    return bool(getattr(request.state, 'device_identity', None))


class NativeAccess:
    def __init__(self, auth):
        self.auth, self.dsn = auth, auth.dsn

    @staticmethod
    def restore(owner, device, raw):
        value = VisitCipher().restore('team-device:' + owner, device, raw)
        stored = value.get('nativeReadPermissions')
        revision = value.get('nativePermissionRevision', 1)
        if stored is None:
            stored = empty_permissions()
        if (not isinstance(value.get('name'), str) or type(revision) is not int
                or revision < 1 or not isinstance(stored, dict)
                or set(stored) != set(PURPOSES)
                or any(type(item) is not bool for item in stored.values())):
            raise RuntimeError('Device permission record invalid')
        return value, dict(stored), revision

    def load(self, conn, owner, device, *, lock=False):
        if not DEVICE_ID.fullmatch(device):
            raise HTTPException(404, 'Device unavailable')
        row = conn.execute('SELECT protected,expires_at FROM team_devices '
            'WHERE device_id=%s AND account_id=%s AND revoked_at IS NULL '
            'AND expires_at>now()' + (' FOR UPDATE' if lock else ''),
            (device, owner)).fetchone()
        if not row:
            raise HTTPException(404, 'Device unavailable')
        value, permissions, revision = self.restore(owner, device, row[0])
        return value, permissions, revision, row[1]

    def save(self, conn, owner, device, value, permissions, revision):
        value.update(nativeReadPermissions=permissions,
                     nativePermissionRevision=revision + 1)
        protected = VisitCipher().protect('team-device:' + owner, device, value)
        conn.execute('UPDATE team_devices SET protected=%s '
                     'WHERE device_id=%s AND account_id=%s', (protected, device, owner))
        changed(conn, owner, 'devices')

    def current(self, account):
        with psycopg.connect(self.dsn) as conn:
            value, permissions, revision, expiry = self.load(
                conn, account['id'], account['deviceId'])
        return dict(deviceId=account['deviceId'], name=value['name'],
                    permissions=permissions, revision=revision, expiresAt=expiry)

    def authorize(self, request, purpose):
        if (not self.auth.native_origin
                or request.url.hostname != urlsplit(self.auth.native_origin).hostname
                or request.method != 'GET'):
            raise HTTPException(404, 'Not found')
        # Re-check active token, current allowlist and device purpose for each GET.
        actor = self.auth.device(request)
        if not self.current(actor)['permissions'][purpose]:
            raise HTTPException(404, 'Resource unavailable')
        return actor

    def router(self):
        router = APIRouter()
        if not self.auth.enabled:
            return router

        def snapshot(owner, device):
            authorization=getattr(self.auth,'native_authorization',None)
            if authorization and authorization.enabled:
                result=authorization.owned_permissions(owner,device)
                if result is not None:return result
            with psycopg.connect(self.dsn) as conn:
                value, permissions, revision, expiry = self.load(conn, owner, device)
            return dict(deviceId=device, name=value['name'], permissions=permissions,
                        revision=revision, expiresAt=expiry)

        @router.get('/v1/devices/{device}/permissions')
        def browser_permissions(device: str, request: Request, response: Response):
            actor = self.auth.browser(request)
            response.headers['Cache-Control'] = 'private, no-store'
            return snapshot(actor['id'], device)

        @router.put('/v1/devices/{device}/permissions')
        async def update(device: str, request: Request, response: Response):
            actor = self.auth.browser(request, mutate=True)
            self.auth.rate('device-purpose-write:' + actor['id'], limit=30)
            raw = bytearray()
            async for chunk in request.stream():
                raw.extend(chunk)
                if len(raw) > 4096:
                    raise HTTPException(413, 'Request too large')
            try:
                body = decode_json(bytes(raw),maximum_bytes=4096)
            except (CodecError, ValueError, UnicodeError):
                raise HTTPException(400, 'Invalid JSON') from None
            authorization=getattr(self.auth,'native_authorization',None)
            if authorization and authorization.enabled and authorization.owned_permissions(actor['id'],device) is not None:
                response.headers['Cache-Control']='private, no-store'
                return authorization.reduce_owned_scopes(actor['id'],device,body)
            if (not isinstance(body, dict) or set(body) != {'revision', 'permissions'}
                    or type(body['revision']) is not int or body['revision'] < 1
                    or not isinstance(body['permissions'], dict)
                    or set(body['permissions']) != set(PURPOSES)
                    or any(type(item) is not bool for item in body['permissions'].values())):
                raise HTTPException(400, 'Invalid device purposes')
            with psycopg.connect(self.dsn) as conn:
                value, _, revision, _ = self.load(conn, actor['id'], device, lock=True)
                if revision != body['revision']:
                    raise HTTPException(409, 'Device permissions changed')
                self.save(conn, actor['id'], device, value, body['permissions'], revision)
            response.headers['Cache-Control'] = 'private, no-store'
            return snapshot(actor['id'], device)

        @router.delete('/v1/devices/{device}/permissions/{purpose}')
        def revoke(device: str, purpose: str, request: Request, response: Response):
            actor = self.auth.browser(request, mutate=True)
            if purpose not in PURPOSES:
                raise HTTPException(404, 'Purpose unavailable')
            # Explicit revocation does not require an old revision to remain current.
            with psycopg.connect(self.dsn) as conn:
                value, permissions, revision, _ = self.load(conn, actor['id'], device, lock=True)
                if permissions[purpose]:
                    permissions[purpose] = False
                    self.save(conn, actor['id'], device, value, permissions, revision)
            response.headers['Cache-Control'] = 'private, no-store'
            return snapshot(actor['id'], device)

        from client_reports import register_client_reports
        register_client_reports(router, self.auth)

        @router.get('/v1/device/permissions')
        def device_permissions(request: Request, response: Response):
            if not getattr(request.state, 'device_identity', None):
                raise HTTPException(404, 'Not found')
            response.headers['Cache-Control'] = 'private, no-store'
            actor = self.auth.device(request)
            if is_native_principal(actor):
                return {key: actor[key] for key in ('authorizationVersion', 'deviceId', 'scopes', 'keepSignedIn', 'consentVersion', 'grantExpiresAt')}
            return self.current(actor)

        @router.get('/v1/native/rooms')
        def device_rooms(request: Request, response: Response):
            actor = self.authorize(request, 'rooms')
            service = getattr(self.auth, 'room_service', None)
            if service is None or not service.enabled:
                raise HTTPException(404, 'Resource unavailable')
            with psycopg.connect(self.dsn) as conn:
                rooms = service.list_rooms(conn, actor['id'])
            response.headers['Cache-Control'] = 'private, no-store'
            return dict(rooms=rooms, nativeReadOnly=True)

        return router
