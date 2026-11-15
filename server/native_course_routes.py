import re

from fastapi import APIRouter, HTTPException, Request, Response
from starlette.concurrency import run_in_threadpool
from psycopg.rows import tuple_row

from native_access_codec import CodecError, decode_json
from native_authorization import NativeAuthorizationError
from native_principal import is_native_principal
from route_preview import POINT_SCHEMA, RoutePreviewError, route_input
from team_course_discovery import CourseDiscovery
from team_rooms import TeamRooms


REQUEST_SCHEMA = dict(type='object', additionalProperties=False, required=['checksum', 'points'], properties={
    'checksum': dict(type='string', pattern='^[a-f0-9]{64}$'),
    'points': dict(type='array', minItems=1, maxItems=3, items=POINT_SCHEMA)})


def checked_points(value, detail):
    if (not isinstance(value, dict) or set(value) != {'checksum', 'points'}
            or not isinstance(value['checksum'], str) or not re.fullmatch('[a-f0-9]{64}', value['checksum'])):
        raise HTTPException(400, 'ROUTE_INPUT_INVALID')
    try:
        _, points = route_input(dict(points=value['points']))
    except RoutePreviewError as error:
        raise HTTPException(error.status, error.code) from None
    stored = [dict(lat=stop['latitude'], lng=stop['longitude']) for stop in detail['pack']['stops']]
    if value['checksum'] != detail['checksum'] or points != stored:
        raise HTTPException(409, 'COURSE_ROUTE_CHANGED')
    return points


def create_router(auth, previews):
    router = APIRouter()
    discovery = CourseDiscovery(auth, None)

    def current(request, pack_id, version, value):
        initial = getattr(request.state, 'device_identity', None)
        if not is_native_principal(initial):
            raise HTTPException(404, 'Not found')
        service = auth.native_authorization
        with service.db() as conn:
            TeamRooms.graph_lock(conn)
            row = conn.execute('SELECT installation_key_id FROM native_v2_grants WHERE grant_id=%s',
                               (initial['grantId'],)).fetchone()
            if row is None:
                raise HTTPException(401, 'INVALID_CREDENTIAL')
            service.lock(conn, row['installation_key_id'])
            try:
                principal = service.authenticate(request, connection=conn)
            except NativeAuthorizationError as error:
                raise HTTPException(error.status, error.code) from None
            if any(principal[key] != initial[key] for key in ('id', 'grantId', 'credentialEpoch', 'slotRevision')):
                raise HTTPException(401, 'INVALID_CREDENTIAL')
            conn.row_factory = tuple_row
            conn.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))', (pack_id,))
            detail = discovery.detail(conn, principal['id'], pack_id, version)
            return principal['id'], checked_points(value, detail)

    @router.post('/v1/native/courses/{pack_id}/versions/{version}/route-preview', openapi_extra={
        'requestBody': {'required': True, 'content': {'application/json': {'schema': REQUEST_SCHEMA}}}})
    async def preview(pack_id: str, version: int, request: Request, response: Response):
        from iphone_sessions import body
        response.headers['Cache-Control'] = 'private, no-store'
        if request.query_params or not is_native_principal(getattr(request.state, 'device_identity', None)):
            raise HTTPException(404, 'Not found')
        try:
            value = decode_json(bytes(await body(request, 'application/json', maximum_bytes=4096)), maximum_bytes=4096)
        except CodecError:
            raise HTTPException(400, 'ROUTE_INPUT_INVALID') from None
        account, points = await run_in_threadpool(current, request, pack_id, version, value)
        try:
            result = await run_in_threadpool(previews.preview, account, dict(points=points))
        except RoutePreviewError as error:
            headers = {'Cache-Control': 'private, no-store'}
            if error.status == 429:
                headers['Retry-After'] = '60'
            raise HTTPException(error.status, error.code, headers=headers) from None
        if await run_in_threadpool(current, request, pack_id, version, value) != (account, points):
            raise HTTPException(401, 'INVALID_CREDENTIAL')
        return result

    return router
