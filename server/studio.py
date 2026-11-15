"""Local creator sessions and immutable public Drive Packs. No vehicle location endpoint."""
from course_publication import COURSE_AVAILABLE, COURSE_STATE, available, presentation_state
import base64
import asyncio
import functools
import hashlib
import hmac
import json
import math
import os
import re
import secrets
import tempfile
import threading
import unicodedata
from pathlib import Path

import psycopg
from private_records import VisitCipher
from place_search import PlaceSearch, PlaceSearchError
from place_map_config import public_map_config
from route_preview import RoutePreview, RoutePreviewError, ROUTE_REQUEST_SCHEMA
from starlette.concurrency import run_in_threadpool
from native_principal import is_native_principal
from team_data import changed
from team_rooms import TeamRooms
from fastapi import APIRouter, HTTPException, Request, Response

LIMIT = 262144
COVER_UPLOAD_LIMIT = 120 * 1024
COVER_STORED_LIMIT = 512 * 1024
IDENTIFIER = re.compile(r"[a-z0-9][a-z0-9_-]{0,79}\Z")


def normalize_course_tag(value):
    if isinstance(value, str):
        tag = unicodedata.normalize('NFC', value.strip().removeprefix('#'))
        if (1 <= len(tag) <= 24 and unicodedata.category(tag[0])[0] in 'LN'
                and all(unicodedata.category(c)[0] in 'LMN' or c in '_-' for c in tag)):
            return tag
    raise ValueError('태그는 글자나 숫자로 시작하며 글자, 숫자, 밑줄, 하이픈을 쓸 수 있습니다 (최대 24자).')


def normalize_course_tags(values):
    if not isinstance(values, list) or len(values) > 8:
        raise ValueError('코스 태그는 최대 8개까지 추가할 수 있습니다.')
    tags = {}
    for value in values:
        tag = normalize_course_tag(value)
        tags.setdefault(tag.casefold(), tag)
    return list(tags.values())


def validate_pack(pack):
    def text(obj, key, limit):
        value = obj.get(key)
        if not isinstance(value, str) or not value.strip() or len(value.encode('utf-16-le')) // 2 > limit:
            raise ValueError(f"{key}: 비어 있거나 너무 긴 문자열입니다")
        return value

    if not isinstance(pack, dict) or set(pack) != {"schemaVersion", "id", "version", "title", "author", "description", "stops"}:
        raise ValueError("Invalid pack fields")
    if type(pack['schemaVersion']) is not int or pack['schemaVersion'] != 1:
        raise ValueError("Unsupported schemaVersion")
    if not IDENTIFIER.fullmatch(text(pack, 'id', 80)):
        raise ValueError("Invalid pack ID")
    if type(pack['version']) is not int or not 1 <= pack['version'] <= 2147483647:
        raise ValueError("version must be a positive integer")
    for field, maximum in [('title', 100), ('author', 80), ('description', 500)]:
        text(pack, field, maximum)
    stops = pack['stops']
    if not isinstance(stops, list) or not 1 <= len(stops) <= 3:
        raise ValueError("A pack needs 1–3 stops")
    ids = set()
    for stop in stops:
        if not isinstance(stop, dict) or set(stop) - {'id', 'name', 'latitude', 'longitude', 'radiusMeters', 'action', 'poiId', 'address', 'place'}:
            raise ValueError("Invalid stop fields")
        stop_id = text(stop, 'id', 80)
        if not IDENTIFIER.fullmatch(stop_id) or stop_id in ids:
            raise ValueError("Stop IDs must be valid and unique")
        ids.add(stop_id)
        text(stop, 'name', 80)
        for field, low, high in [('latitude', -90, 90), ('longitude', -180, 180), ('radiusMeters', 25, 500)]:
            value = stop.get(field)
            if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
                raise ValueError(f"Invalid {field}")
        action = stop.get('action')
        if not isinstance(action, dict) or set(action) != {'type', 'message'} or action['type'] != 'chime':
            raise ValueError("Only arrival chimes are supported")
        text(action, 'message', 240)
        for field, maximum in [('poiId', 100), ('address', 200)]:
            if field in stop and (not isinstance(stop[field], str) or len(stop[field]) > maximum):
                raise ValueError(f"Invalid {field}")
        if 'place' in stop:
            place = stop['place']
            if not isinstance(place, dict) or set(place) != {'id','provider','name','address'}:
                raise ValueError('Invalid place object')
            for field, maximum in [('id',240),('provider',40),('name',80)]: text(place,field,maximum)
            if not isinstance(place['address'], str) or len(place['address']) > 200:
                raise ValueError('Invalid place address')
    return pack


async def read_json(request):
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw) > LIMIT:
            raise HTTPException(413, "Pack exceeds 256 KiB")
    try:
        return json.loads(raw.decode('utf-8'))
    except (ValueError, UnicodeError):
        raise HTTPException(400, "Invalid JSON")


def create_router(dsn, content: Path, team_auth=None, place_search=None, route_preview=None):
    router = APIRouter()
    cover_worker_slot = threading.BoundedSemaphore(1)

    shared = bool(team_auth and team_auth.enabled)
    if shared and getattr(team_auth, 'trip_service', None):
        from team_trip_signal_contexts import TeamTripSignalContexts
        from team_trip_places import TeamTripPlaces
        from team_trip_routes import TeamTripRoutes
        team_auth.trip_signal_contexts = TeamTripSignalContexts(team_auth)
        team_auth.trip_places_service = TeamTripPlaces(team_auth)
        try:
            from team_trip_results import TeamTripResults
        except ModuleNotFoundError as error:
            if error.name != 'team_trip_results':
                raise
        else:
            if getattr(team_auth, 'trip_results_service', None) is None:
                team_auth.trip_results_service = TeamTripResults(team_auth)
        team_auth.trip_feature_routes = {}
        for attribute, feature in (
                ('vehicle_service', 'reports'), ('device_command_service', 'commands'),
                ('room_music_service', 'music'), ('room_music_access', 'musicPermissions'),
                ('room_voice_access', 'voicePermissions'), ('voice_service', 'voice'),
                ('mission_service', 'missions'),
                ('history_service', 'history'), ('trip_results_service', 'results')):
            service = getattr(team_auth, attribute, None)
            factory = getattr(service, 'trip_router', None)
            if factory is not None:
                routes = factory()
                router.include_router(routes)
                team_auth.trip_feature_routes[feature] = bool(routes.routes)
        router.include_router(TeamTripRoutes(team_auth).router())
    search = place_search if place_search is not None else PlaceSearch.from_environment()

    routes = route_preview if route_preview is not None else RoutePreview.from_environment()

    def origin(request):
        if shared:
            return team_auth.check_origin(request)
        if request.headers.get('origin') != str(request.base_url).rstrip('/'):
            raise HTTPException(403, "Open the studio on its own local URL")

    def creator(request, check_origin=True):
        if shared:
            device = getattr(request.state, 'device_identity', None)
            if device and not check_origin:
                return device['id']
            identity = team_auth.browser(request, mutate=check_origin)
            if request.method == 'POST' and request.url.path == '/v1/packs' and identity['role'] not in ('creator','admin'):
                raise HTTPException(403, 'Action not permitted')
            return identity['id']
        if check_origin: origin(request)
        token = request.cookies.get('wegoh_studio', '')
        if not token or len(token) > 200:
            raise HTTPException(401, "Start a creator session first")
        with psycopg.connect(dsn) as conn:
            row = conn.execute('SELECT creator_id FROM studio_sessions WHERE token_hash=%s AND expires_at>now()',
                               (hashlib.sha256(token.encode()).hexdigest(),)).fetchone()
        if not row:
            raise HTTPException(401, "Creator session expired")
        return row[0]

    def search_for_account(request, response, authenticate):
        account = authenticate()
        value = {key: request.query_params.getlist(key) for key in request.query_params}
        response.headers['Cache-Control'] = 'private, no-store'
        try:
            places = search.search(account, value)
        except PlaceSearchError as error:
            headers = {'Cache-Control': 'private, no-store'}
            if error.status == 429:
                headers['Retry-After'] = '60'
            raise HTTPException(error.status, error.code, headers=headers) from None
        if authenticate() != account:
            raise HTTPException(401, 'Authentication changed')
        return dict(places=places)

    async def preview_for_account(request, response, authenticate):
        account = await run_in_threadpool(authenticate)
        response.headers['Cache-Control'] = 'private, no-store'
        value = await read_json(request)
        try:
            result = await run_in_threadpool(routes.preview, account, value)
        except RoutePreviewError as error:
            headers = {'Cache-Control': 'private, no-store'}
            if error.status == 429:
                headers['Retry-After'] = '60'
            raise HTTPException(error.status, error.code, headers=headers) from None
        if await run_in_threadpool(authenticate) != account:
            raise HTTPException(401, 'Authentication changed')
        return result

    @router.get('/v1/places/search', openapi_extra={
        'x-wegoh-native-access': False,
        'parameters': [
            {'name': 'q', 'in': 'query', 'required': True, 'description': 'trim 후 2~60자 이름 또는 주소. 제어문자·중복 파라미터는 거절합니다.',
             'schema': {'type': 'string', 'minLength': 2, 'maxLength': 60}},
            {'name': 'x', 'in': 'query', 'required': False, 'description': '지도 중심 경도. y와 함께 전달하거나 함께 생략합니다.',
             'schema': {'type': 'number', 'minimum': -180, 'maximum': 180}},
            {'name': 'y', 'in': 'query', 'required': False, 'description': '지도 중심 위도. x와 함께 전달하거나 함께 생략합니다.',
             'schema': {'type': 'number', 'minimum': -90, 'maximum': 90}}
        ]})
    def search_places(request: Request, response: Response):
        if getattr(request.state, 'device_identity', None) is not None:
            raise HTTPException(404, 'Not found')
        return search_for_account(request, response, lambda: creator(request, check_origin=False))

    @router.post('/v1/routes/preview', openapi_extra={'x-wegoh-native-access': False,
        'requestBody': {'required': True, 'content': {'application/json': {'schema': ROUTE_REQUEST_SCHEMA}}}})
    async def preview_route(request: Request, response: Response):
        if getattr(request.state, 'device_identity', None) is not None:
            raise HTTPException(404, 'Not found')
        return await preview_for_account(request, response, lambda: creator(request))

    if shared:
        @router.get('/v1/iphone/places/search', include_in_schema=False)
        def iphone_search_places(request: Request, response: Response):
            return search_for_account(request, response, lambda: team_auth.iphone(request, 'maps:read')['id'])

        @router.post('/v1/iphone/routes/preview', include_in_schema=False)
        async def iphone_preview_route(request: Request, response: Response):
            return await preview_for_account(request, response, lambda: team_auth.iphone(request, 'maps:read')['id'])

    def local_workspace(request):
        if shared or os.environ.get('WEGOH_LOCAL_STUDIO') != '1': raise HTTPException(404)
        if not request.client or request.client.host not in ('127.0.0.1','::1'):
            raise HTTPException(403,'Local workspace only')
        origin(request)

    def moderator(request):
        if shared and request.url.hostname not in ('localhost','127.0.0.1'):
            return team_auth.browser(request, mutate=request.method not in ('GET','HEAD'), roles=('admin',))
        # A creator cookie never grants moderation. The operator key stays out of web/APK.
        key = os.environ.get('WEGOH_API_KEY', '')
        supplied = request.headers.get('authorization', '')
        if (len(key) < 32 or not request.client or request.client.host not in ('127.0.0.1','::1')
                or not hmac.compare_digest(supplied.encode(), ('Bearer '+key).encode())):
            raise HTTPException(401, 'Local operator authentication required')
        if request.headers.get('origin'): origin(request)

    def read_pack(checksum):
        if not re.fullmatch(r'[0-9a-f]{64}', checksum):
            raise HTTPException(503, 'Pack integrity check failed')
        raw = (content / checksum).read_bytes()
        if hashlib.sha256(raw).hexdigest() != checksum:
            raise HTTPException(503, 'Pack integrity check failed')
        return raw

    @functools.lru_cache(maxsize=4096)
    def stored_card_stops(checksum):
        # A checksum names immutable bytes, so its stops never change. Failed
        # reads raise and are not cached.
        return tuple((stop['id'], stop['name'], stop['latitude'], stop['longitude'])
                     for stop in json.loads(read_pack(checksum))['stops'])

    def card_stops(checksum):
        """Course card map stops, so list screens need no detail read per card."""
        return [dict(id=stop, name=name, lat=lat, lng=lng) for stop, name, lat, lng in stored_card_stops(checksum)]

    def stop_names(checksum):
        return tuple(name for _, name, _, _ in stored_card_stops(checksum))

    def version_row(conn, pack_id, version):
        if not IDENTIFIER.fullmatch(pack_id) or not 1 <= version <= 2147483647:
            raise HTTPException(404, 'Pack not found')
        row = conn.execute('SELECT checksum FROM pack_versions WHERE pack_id=%s AND version=%s',
                           (pack_id,version)).fetchone()
        if not row: raise HTTPException(404, 'Pack not found')
        return row[0]

    def cover_bytes(conn, pack_id, version):
        row = conn.execute('SELECT image FROM pack_course_covers WHERE pack_id=%s AND version=%s',
                           (pack_id, version)).fetchone()
        return bytes(row[0]) if row else None

    def cover_response(conn, pack_id, version):
        image = cover_bytes(conn, pack_id, version)
        if image is None:
            raise HTTPException(404, 'Course cover unavailable')
        return Response(image, media_type='image/jpeg', headers={
            'Cache-Control': 'private, no-store, no-transform', 'X-Content-Type-Options': 'nosniff'})

    @router.get('/v1/moderation/packs')
    def review_queue(request: Request, response: Response):
        moderator(request)
        response.headers['Cache-Control']='private, no-store'
        with psycopg.connect(dsn) as conn:
            rows = conn.execute("SELECT p.pack_id,p.version,p.checksum,coalesce(r.state,'quarantined'),p.title,p.tags "
                                'FROM pack_versions p LEFT JOIN pack_reviews r USING(checksum) '
                                'ORDER BY p.created_at,p.pack_id,p.version LIMIT 1000').fetchall()
        return {'packs':[dict(zip(('id','version','checksum','state','title','tags'),row)) for row in rows]}

    @router.get('/v1/moderation/packs/{pack_id}/versions/{version}')
    def inspect_pack(pack_id: str, version: int, request: Request):
        moderator(request)
        with psycopg.connect(dsn) as conn: checksum=version_row(conn,pack_id,version)
        return Response(read_pack(checksum),media_type='application/json',headers={'Cache-Control':'no-store, no-transform','ETag':'"'+checksum+'"'})

    @router.get('/v1/moderation/packs/{pack_id}/versions/{version}/cover', openapi_extra={'x-wegoh-native-access': False})
    def inspect_cover(pack_id: str, version: int, request: Request):
        moderator(request)
        with psycopg.connect(dsn) as conn:
            version_row(conn, pack_id, version)
            return cover_response(conn, pack_id, version)

    @router.post('/v1/moderation/packs/{pack_id}/versions/{version}')
    async def review_pack(pack_id: str, version: int, request: Request):
        moderator(request)
        body=await read_json(request)
        if (not isinstance(body,dict) or set(body)!={'checksum','decision','reviewer','reviewNote'}
                or body['decision'] not in ('approved','rejected')
                or not isinstance(body['reviewer'],str) or not 1<=len(body['reviewer'].strip())<=80
                or not isinstance(body['reviewNote'],str) or not 1<=len(body['reviewNote'].strip())<=1000):
            raise HTTPException(400,'Explicit full-content review required')
        if shared and request.url.hostname not in ('localhost','127.0.0.1'):
            body['reviewer'] = request.state.team_identity['displayName']
        # This records an operator's semantic review; no keyword or checkbox auto-approval.
        with psycopg.connect(dsn) as conn:
            conn.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',(pack_id,))
            checksum=version_row(conn,pack_id,version)
            if body['checksum']!=checksum: raise HTTPException(409,'Review checksum differs from submitted bytes')
            read_pack(checksum)
            conn.execute('INSERT INTO pack_reviews(checksum,state,reviewer,review_note) VALUES(%s,%s,%s,%s) '
                         'ON CONFLICT(checksum) DO UPDATE SET state=excluded.state,reviewer=excluded.reviewer,review_note=excluded.review_note,reviewed_at=now()',
                         (checksum,body['decision'],body['reviewer'].strip(),body['reviewNote'].strip()))
            conn.execute('INSERT INTO pack_review_events(checksum,state,reviewer,review_note) VALUES(%s,%s,%s,%s)',
                         (checksum,body['decision'],body['reviewer'].strip(),body['reviewNote'].strip()))
            if shared: changed(conn, '*', 'courses')
        return {'checksum':checksum,'state':body['decision']}

    @router.get('/v1/moderation/reports')
    def reports(request: Request, response: Response):
        moderator(request)
        response.headers['Cache-Control']='private, no-store'
        with psycopg.connect(dsn) as conn:
            rows=conn.execute('SELECT report_id,pack_id,version,checksum,reason,created_at FROM content_reports ORDER BY created_at DESC LIMIT 1000').fetchall()
        return {'reports':[dict(zip(('id','packId','version','checksum','reason','createdAt'),row)) for row in rows]}

    def record_report_in(conn,owner,pack_id,version,reason,expected_checksum=None):
        conn.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',(pack_id,))
        checksum=version_row(conn,pack_id,version)
        if expected_checksum is not None and expected_checksum!=checksum:
            raise HTTPException(409,'Report checksum differs from submitted bytes')
        read_pack(checksum)
        row=conn.execute('INSERT INTO content_reports(report_id,pack_id,version,checksum,creator_id,reason) '
                         'VALUES(%s,%s,%s,%s,%s,%s) ON CONFLICT(checksum,creator_id,reason) DO UPDATE SET reason=excluded.reason RETURNING report_id',
                         (secrets.token_hex(16),pack_id,version,checksum,owner,reason)).fetchone()
        conn.execute("INSERT INTO pack_reviews(checksum,state,reviewer,review_note) VALUES(%s,'quarantined','report-channel','Awaiting full-content review after report') "
                     "ON CONFLICT(checksum) DO UPDATE SET state='quarantined',reviewer=excluded.reviewer,review_note=excluded.review_note,reviewed_at=now()",(checksum,))
        conn.execute("INSERT INTO pack_review_events(checksum,state,reviewer,review_note) VALUES(%s,'quarantined','report-channel','Awaiting full-content review after report')",(checksum,))
        if shared: changed(conn, '*', 'courses')
        return {'reportId':row[0],'state':'quarantined'}

    def record_report(owner,pack_id,version,reason,expected_checksum=None):
        with psycopg.connect(dsn) as conn:
            return record_report_in(conn,owner,pack_id,version,reason,expected_checksum)

    if shared:
        team_auth.course_pack_reader = read_pack
        team_auth.course_card_stops = card_stops
        team_auth.course_stop_names = stop_names
        team_auth.course_reporter = record_report_in
        from native_course_routes import create_router as native_course_routes
        router.include_router(native_course_routes(team_auth, routes))

    @router.post('/v1/packs/{pack_id}/versions/{version}/reports',status_code=202)
    async def report_pack(pack_id: str, version: int, request: Request):
        owner=creator(request)
        body=await read_json(request)
        if not isinstance(body,dict) or set(body)!={'reason'} or body['reason'] not in ('harmful','privacy','rights','other'):
            raise HTTPException(400,'Choose a report reason')
        return record_report(owner,pack_id,version,body['reason'])

    @router.post('/v1/local/packs/{pack_id}/versions/{version}/reports',status_code=202)
    async def local_report_pack(pack_id: str, version: int, request: Request):
        # Emulator-local explicit action, not anonymous external-service identity.
        # No operator key, creator session, GPS or visit history enters the APK.
        local_workspace(request)
        if request.headers.get('x-wegoh-local-report')!='1':
            raise HTTPException(403,'Explicit local reporting required')
        body=await read_json(request)
        if (not isinstance(body,dict) or set(body)!={'reason','checksum'}
                or body['reason'] not in ('harmful','privacy','rights','other')
                or not isinstance(body['checksum'],str) or not re.fullmatch('[0-9a-f]{64}',body['checksum'])):
            raise HTTPException(400,'Choose a report reason and exact downloaded checksum')
        return record_report('local-vehicle',pack_id,version,body['reason'],body['checksum'])

    @router.post('/v1/local/visits')
    async def share_visits(request: Request):
        local_workspace(request)
        if request.headers.get('x-wegoh-local-visit') != '1':
            raise HTTPException(403,'Explicit local sharing required')
        body = await read_json(request)
        if not isinstance(body, dict) or body.get('consent') is not True or not isinstance(body.get('visits'), list) or len(body['visits'])>100:
            raise HTTPException(400,'Choose and confirm visit sharing')
        records=[]
        for visit in body['visits']:
            if not isinstance(visit,dict) or set(visit)!={'id','place','visitedAt'}:
                raise HTTPException(400,'Invalid visit')
            place=visit['place']
            if not isinstance(visit['id'],str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,80}',visit['id']):
                raise HTTPException(400,'Invalid visit ID')
            if type(visit['visitedAt']) is not int or not 0<visit['visitedAt']<=253402300799999:
                raise HTTPException(400,'Invalid visit time')
            if not isinstance(place,dict) or set(place)!={'id','provider','name','address','latitude','longitude'}:
                raise HTTPException(400,'Invalid place')
            for field,maximum in [('id',240),('provider',40),('name',80),('address',200)]:
                if not isinstance(place[field],str) or len(place[field])>maximum or (field!='address' and not place[field].strip()):
                    raise HTTPException(400,'Invalid place text')
            for field,low,high in [('latitude',-90,90),('longitude',-180,180)]:
                if type(place[field]) not in (int,float) or not math.isfinite(place[field]) or not low<=place[field]<=high:
                    raise HTTPException(400,'Invalid place location')
            records.append((visit['id'],json.dumps(place,ensure_ascii=False),visit['visitedAt']))
        cipher=VisitCipher()
        with psycopg.connect(dsn) as conn:
            conn.execute("SELECT pg_advisory_xact_lock(hashtextextended('private-visits',0))")
            count=conn.execute("SELECT count(*) FROM visited_places WHERE creator_id='local-creator'").fetchone()[0]
            fresh=sum(not conn.execute('SELECT 1 FROM visited_places WHERE visit_id=%s',(record[0],)).fetchone() for record in records)
            if count+fresh>1000:raise HTTPException(409,'Private workspace is full; manage visits before sharing')
            for visit_id,place,visited_at in records:
                encrypted=cipher.protect('local-creator',visit_id,dict(place=json.loads(place),visitedAt=visited_at))
                conn.execute("INSERT INTO visited_places (visit_id,creator_id,place,visited_at,protected) VALUES (%s,'local-creator',NULL,1,%s) ON CONFLICT (visit_id) DO NOTHING",(visit_id,encrypted))
        return {'accepted':len(records)}

    @router.get('/v1/places/visited')
    def visited(request: Request, response: Response):
        owner=creator(request,False)
        response.headers['Cache-Control']='private, no-store'
        with psycopg.connect(dsn) as conn:
            rows=conn.execute('SELECT visit_id,protected FROM visited_places WHERE creator_id=%s',(owner,)).fetchall()
        cipher=VisitCipher();places={}
        for visit_id,protected in rows:
            record=cipher.restore(owner,visit_id,protected)
            place=dict(record['place'],visitedAt=record['visitedAt'])
            if place['id'] not in places or places[place['id']]['visitedAt']<place['visitedAt']:places[place['id']]=place
        return {'places':sorted(places.values(),key=lambda item:item['visitedAt'],reverse=True)[:100]}

    @router.delete('/v1/places/visited')
    def clear_visited(request: Request):
        owner=creator(request)
        with psycopg.connect(dsn) as conn:
            conn.execute('DELETE FROM visited_places WHERE creator_id=%s',(owner,))
        return {'status':'cleared'}

    @router.get('/v1/auth/session')
    def auth_session(request: Request, response: Response):
        response.headers['Cache-Control']='private, no-store'
        if shared:
            return team_auth.status(request)
        try:
            owner=creator(request,False)
        except HTTPException as error:
            if error.status_code!=401:raise
            owner=None
        return dict(mode='local-workspace',authenticated=bool(owner),
            user=dict(id=owner,displayName='WegoH 로컬 창작자',role='creator') if owner else None,
            csrfToken=None,nativeApiEnabled=False,placeMap=public_map_config())

    @router.post('/v1/auth/session')
    @router.post('/v1/studio/session')
    def start_session(request: Request, response: Response):
        # Shared login lives in TeamAuth; the old local route must fail closed.
        if shared:raise HTTPException(404, 'Local workspace unavailable')
        # Opt-in, localhost-only single creator workspace, not production user login.
        if os.environ.get('WEGOH_LOCAL_STUDIO') != '1':
            raise HTTPException(404)
        if not request.client or request.client.host not in ('127.0.0.1', '::1'):
            raise HTTPException(403, "Local workspace only")
        origin(request)
        token = secrets.token_urlsafe(32)
        with psycopg.connect(dsn) as conn:
            conn.execute('DELETE FROM studio_sessions WHERE expires_at<=now()')
            conn.execute("INSERT INTO studio_sessions VALUES (%s,'local-creator',now()+interval '4 hours')",
                         (hashlib.sha256(token.encode()).hexdigest(),))
        response.set_cookie('wegoh_studio', token, max_age=14400, httponly=True,
                            samesite='strict', secure=request.url.scheme == 'https', path='/')
        response.headers['Cache-Control'] = 'no-store'
        if request.url.path == '/v1/auth/session':
            return dict(mode='local-workspace',authenticated=True,user=dict(id='local-creator',displayName='WegoH 로컬 창작자',role='creator'),csrfToken=None,nativeApiEnabled=False,placeMap=public_map_config())
        return {'creator': 'WegoH 로컬 창작자', 'mode': 'local-workspace'}

    @router.delete('/v1/auth/session')
    @router.delete('/v1/studio/session')
    def logout(request: Request, response: Response):
        if shared:raise HTTPException(404, 'Local workspace unavailable')
        origin(request)
        token = request.cookies.get('wegoh_studio', '')
        with psycopg.connect(dsn) as conn:
            conn.execute('DELETE FROM studio_sessions WHERE token_hash=%s', (hashlib.sha256(token.encode()).hexdigest(),))
        response.delete_cookie('wegoh_studio', path='/')
        if request.url.path == '/v1/auth/session':
            return dict(mode='local-workspace',authenticated=False,user=None,csrfToken=None,nativeApiEnabled=False,placeMap=public_map_config())
        return {'status': 'signed-out'}

    if shared:
        def iphone_course_owner(request, scope):
            actor = team_auth.iphone(request, scope)
            if request.url.query:
                raise HTTPException(400, 'IPHONE_INVALID_REQUEST')
            team_auth.rate('iphone-courses:' + actor['id'], limit=60)
            return actor

        @router.post('/v1/iphone/courses/public/{pack_id}/versions/{version}/copy', status_code=201, include_in_schema=False)
        async def copy_public_course(pack_id: str, version: int, request: Request):
            from iphone_course_copy import make_public_copy
            from iphone_sessions import json_fields
            await run_in_threadpool(iphone_course_owner, request, 'courses:write')
            await json_fields(request)

            def write():
                with psycopg.connect(dsn) as conn:
                    TeamRooms.graph_lock(conn)
                    actor = team_auth.iphone_sessions.authenticate(request, 'courses:write', connection=conn, lock=True)
                    if actor['role'] not in ('creator', 'admin'):
                        raise HTTPException(403, 'Action not permitted')
                    return make_public_copy(team_auth.history_remix_service, conn, actor, pack_id, version)

            return await run_in_threadpool(write)

        @router.get('/v1/iphone/courses', include_in_schema=False)
        def iphone_courses(request: Request, response: Response):
            actor = iphone_course_owner(request, 'courses:read')
            response.headers['Cache-Control'] = 'private, no-store'
            with psycopg.connect(dsn) as conn:
                rows = conn.execute(f'SELECT p.pack_id,p.version,p.title,p.author,p.description,p.stop_count,p.checksum,{COURSE_STATE} '
                    "FROM (SELECT DISTINCT ON (pack_id) * FROM pack_versions WHERE creator_id=%s "
                    "ORDER BY pack_id,version DESC) p LEFT JOIN pack_reviews r USING(checksum) "
                    "ORDER BY p.created_at DESC,p.pack_id LIMIT 1000", (actor['id'],)).fetchall()
            return {'packs': [dict(zip(('id','version','title','author','description','stopCount','checksum','state'), row),
                                   stopNames=list(stop_names(row[6])), stops=card_stops(row[6])) for row in rows]}

        @router.get('/v1/iphone/courses/{pack_id}/versions/{version}', include_in_schema=False)
        def iphone_course(pack_id: str, version: int, request: Request):
            actor = iphone_course_owner(request, 'courses:read')
            if not IDENTIFIER.fullmatch(pack_id) or not 1 <= version <= 2147483647:
                raise HTTPException(404, 'Course unavailable')
            with psycopg.connect(dsn) as conn:
                row = conn.execute('SELECT checksum,tags,EXISTS(SELECT 1 FROM pack_course_covers c WHERE c.pack_id=p.pack_id AND c.version=p.version) FROM pack_versions p WHERE pack_id=%s AND version=%s AND creator_id=%s',
                                   (pack_id, version, actor['id'])).fetchone()
                source = conn.execute('SELECT draft_id FROM team_remix_drafts WHERE draft_pack_id=%s AND account_id=%s',
                                      (pack_id, actor['id'])).fetchone()
            if not row:
                raise HTTPException(404, 'Course unavailable')
            result = {'pack': json.loads(read_pack(row[0])), 'remixDraftId': source[0] if source else None,
                      'tags': row[1], 'hasCover': row[2]}
            return Response(json.dumps(result, ensure_ascii=False), media_type='application/json',
                            headers={'Cache-Control': 'private, no-store, no-transform'})


    @router.post('/v1/packs', status_code=201)
    @router.post('/v1/iphone/courses', status_code=201, include_in_schema=False)
    async def publish(request: Request, response: Response):
        iphone = request.url.path == '/v1/iphone/courses'
        if iphone:
            if not shared: raise HTTPException(404, 'IPHONE_ROUTE_NOT_FOUND')
            actor = await run_in_threadpool(iphone_course_owner, request, 'courses:write')
            if actor['role'] not in ('creator', 'admin'): raise HTTPException(403, 'Action not permitted')
            owner = actor['id']
            if request.headers.get('content-type', '').split(';', 1)[0].strip() != 'application/json':
                raise HTTPException(400, 'IPHONE_INVALID_REQUEST')
            response.headers['Cache-Control'] = 'private, no-store'
        else:
            owner = creator(request)
        try:
            async with asyncio.timeout(5):
                body = await read_json(request)
        except TimeoutError:
            raise HTTPException(408, 'Request timeout') from None
        if (not isinstance(body, dict) or body.get('rightsConfirmed') is not True or 'pack' not in body
                or set(body) - {'rightsConfirmed', 'pack', 'remixDraftId', 'tags', 'coverImage', 'copyCoverFromVersion'}):
            raise HTTPException(400, "Confirm your rights and public publication")
        try:
            pack = validate_pack(body['pack'])
            tags = normalize_course_tags(body.get('tags', []))
            pack['author'] = (actor['displayName'] if iphone else request.state.team_identity['displayName']) if shared else 'WegoH 로컬 창작자'
            raw = json.dumps(pack, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
            if len(raw) > LIMIT:
                raise HTTPException(413, "Pack exceeds 256 KiB")
        except (ValueError, KeyError, TypeError) as error:
            raise HTTPException(400, str(error))
        image = None
        source_version = body.get('copyCoverFromVersion')
        if 'copyCoverFromVersion' in body and (type(source_version) is not int
                or not 1 <= source_version < pack['version'] or 'coverImage' in body):
            raise HTTPException(400, 'Invalid course cover version')
        if 'coverImage' in body:
            encoded = body['coverImage']
            if not isinstance(encoded, str) or len(encoded) > 4 * ((COVER_UPLOAD_LIMIT + 2) // 3):
                raise HTTPException(400, 'Invalid course cover')
            try:
                image = base64.b64decode(encoded, validate=True)
            except ValueError:
                raise HTTPException(400, 'Invalid course cover') from None
            if not image or len(image) > COVER_UPLOAD_LIMIT or not image.startswith(b'\xff\xd8\xff'):
                raise HTTPException(400, 'Invalid course cover')
            from team_photos import bounded_worker
            if not cover_worker_slot.acquire(blocking=False):
                raise HTTPException(429, 'Course image processor is busy', headers={'Retry-After': '1'})
            try:
                metadata, image = await run_in_threadpool(bounded_worker, image, 'image/jpeg')
            finally:
                cover_worker_slot.release()
            if max(metadata['width'], metadata['height']) > 960 or len(image) > COVER_STORED_LIMIT:
                raise HTTPException(400, 'Invalid course cover dimensions')
        checksum = hashlib.sha256(raw).hexdigest()
        draft_id = body.get('remixDraftId')
        if 'remixDraftId' in body and (not isinstance(draft_id,str) or not re.fullmatch(r'[a-f0-9]{32}',draft_id)):
            raise HTTPException(400, 'Invalid re-creation draft receipt')
        remix = getattr(team_auth, 'history_remix_service', None) if shared else None
        provenance = None
        # A DB advisory lock serializes all versions of the same pack across processes.
        with psycopg.connect(dsn) as conn:
            if shared:
                if iphone:
                    TeamRooms.graph_lock(conn)
                current=(team_auth.iphone_sessions.authenticate(request, 'courses:write', connection=conn, lock=True)
                         if iphone else team_auth.browser(request,mutate=True,roles=('creator','admin'),connection=conn))
                if current['role'] not in ('creator', 'admin'): raise HTTPException(403, 'Action not permitted')
                if current['id']!=owner:raise HTTPException(401,'Creator account changed')
            if remix:
                provenance=remix.authorize_publication(conn,owner,pack,draft_id)
            elif draft_id is not None:
                raise HTTPException(404,'Re-creation unavailable')
            conn.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))', (pack['id'],))
            existing = conn.execute('SELECT version,creator_id,checksum,tags FROM pack_versions WHERE pack_id=%s ORDER BY version DESC',
                                    (pack['id'],)).fetchall()
            if existing and existing[0][1] != owner:
                raise HTTPException(409, 'Pack ID belongs to another creator')
            if source_version is not None:
                if not any(version == source_version and creator_id == owner for version, creator_id, _, _ in existing):
                    raise HTTPException(404, 'Course cover unavailable')
                image = cover_bytes(conn, pack['id'], source_version)
                if image is None:
                    raise HTTPException(404, 'Course cover unavailable')
            elif (image is None and pack['version'] == 1 and provenance
                  and provenance['kind'] == 'course' and 'historyId' not in provenance):
                image = cover_bytes(conn, provenance['courseId'], provenance['version'])
            same = next((row for row in existing if row[0] == pack['version']), None)
            if same:
                if (same[2] != checksum or same[3] != tags
                        or image != cover_bytes(conn, pack['id'], pack['version'])):
                    raise HTTPException(409, 'Published versions are immutable; increase version')
                response.status_code = 200
                return {'id': pack['id'], 'version': pack['version'], 'checksum': checksum,
                        'state':presentation_state(conn, checksum), **({'pack': pack} if iphone else {}), **({'source':remix.public_source(provenance)} if provenance else {})}
            if pack['version'] != (existing[0][0] + 1 if existing else 1):
                raise HTTPException(409, 'Publish the next consecutive version')
            temporary = None
            try:
                with tempfile.NamedTemporaryFile(dir=content, delete=False, prefix='.pack-') as stream:
                    temporary = Path(stream.name)
                    stream.write(raw); stream.flush(); os.fsync(stream.fileno())
                try:
                    os.link(temporary, content / checksum)
                except FileExistsError:
                    pass
            finally:
                if temporary is not None:
                    temporary.unlink(missing_ok=True)
            conn.execute('INSERT INTO pack_versions (pack_id,version,creator_id,checksum,title,author,description,stop_count,tags) '
                         'VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                         (pack['id'], pack['version'], owner, checksum, pack['title'], pack['author'], pack['description'], len(pack['stops']), tags))
            if image is not None:
                conn.execute('INSERT INTO pack_course_covers (pack_id,version,image) VALUES (%s,%s,%s)',
                             (pack['id'], pack['version'], image))
            conn.execute("INSERT INTO pack_reviews(checksum,state,reviewer,review_note) "
                         "VALUES(%s,'approved','creator-publication','Published directly by the creator')", (checksum,))
            conn.execute("INSERT INTO pack_review_events(checksum,state,reviewer,review_note) "
                         "VALUES(%s,'approved','creator-publication','Published directly by the creator')", (checksum,))
            if remix:remix.published(conn,owner,draft_id)
            if shared: changed(conn, '*', 'courses')
        return {'id': pack['id'], 'version': pack['version'], 'checksum': checksum,'state':'approved', **({'pack': pack} if iphone else {}), **({'source':remix.public_source(provenance)} if provenance else {})}

    @router.get('/v1/studio/packs/{pack_id}/versions/{version}')
    def own_pack(pack_id: str, version: int, request: Request):
        owner=creator(request,False)
        identity=getattr(request.state,'device_identity',None)
        if is_native_principal(identity):
            from native_authorization import NativeAuthorizationError
            service=team_auth.native_authorization
            with service.db() as conn:
                initial=conn.execute('SELECT installation_key_id FROM native_v2_grants WHERE grant_id=%s',
                                     (identity['grantId'],)).fetchone()
                if not initial:raise HTTPException(401,'INVALID_CREDENTIAL')
                service.lock(conn,initial['installation_key_id'])
                try:current=service.authenticate(request,connection=conn)
                except NativeAuthorizationError as error:raise HTTPException(error.status,error.code) from None
                if (current['id']!=owner or current['grantId']!=identity['grantId']
                        or current['credentialEpoch']!=identity['credentialEpoch']):
                    raise HTTPException(401,'INVALID_CREDENTIAL')
                conn.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',(pack_id,))
                row=conn.execute('SELECT p.checksum FROM pack_versions p LEFT JOIN pack_reviews r USING(checksum) '
                                 f"WHERE p.pack_id=%s AND p.version=%s AND p.creator_id=%s AND {COURSE_AVAILABLE}",
                                 (pack_id,version,owner)).fetchone()
                if not row:raise HTTPException(404,'Course unavailable')
                return Response(read_pack(row['checksum']),media_type='application/json',
                                headers={'Cache-Control':'private, no-store, no-transform','ETag':'"'+row['checksum']+'"'})
        with psycopg.connect(dsn) as conn:
            row=conn.execute('SELECT checksum FROM pack_versions WHERE pack_id=%s AND version=%s AND creator_id=%s',
                             (pack_id,version,owner)).fetchone()
        if not row:raise HTTPException(404,'Course unavailable')
        return Response(read_pack(row[0]),media_type='application/json',headers={'Cache-Control':'private, no-store, no-transform'})

    @router.get('/v1/studio/packs')
    def creator_catalogue(request: Request, response: Response):
        owner=creator(request,False)
        response.headers['Cache-Control']='private, no-store'
        browser = getattr(request.state, 'device_identity', None) is None
        with psycopg.connect(dsn) as conn:
            rows=conn.execute(f'SELECT p.pack_id,p.version,p.title,p.author,p.description,p.stop_count,p.checksum,{COURSE_STATE},p.tags '
                              'FROM pack_versions p LEFT JOIN pack_reviews r USING(checksum) WHERE p.creator_id=%s '
                              'ORDER BY p.created_at DESC,p.pack_id,p.version DESC LIMIT 1000',(owner,)).fetchall()
        fields = ('id','version','title','author','description','stopCount','checksum','state')
        if browser:
            fields += ('tags',)
        return {'packs':[dict(zip(fields,row)) for row in rows]}

    @router.get('/v1/studio/packs/{pack_id}/versions/{version}/cover', openapi_extra={'x-wegoh-native-access': False})
    def own_cover(pack_id: str, version: int, request: Request):
        if getattr(request.state, 'device_identity', None) is not None:
            raise HTTPException(404, 'Course cover unavailable')
        owner = creator(request, False)
        with psycopg.connect(dsn) as conn:
            version_row(conn, pack_id, version)
            row = conn.execute('SELECT creator_id FROM pack_versions WHERE pack_id=%s AND version=%s',
                               (pack_id, version)).fetchone()
            if not row or row[0] != owner:
                raise HTTPException(404, 'Course cover unavailable')
            return cover_response(conn, pack_id, version)

    @router.get('/v1/packs')
    def catalogue(response: Response):
        response.headers['Cache-Control']='no-store'
        with psycopg.connect(dsn) as conn:
            rows = conn.execute('SELECT DISTINCT ON (p.pack_id) p.pack_id,p.version,p.title,p.author,p.description,p.stop_count,p.checksum '
                                f"FROM pack_versions p LEFT JOIN pack_reviews r USING(checksum) WHERE {COURSE_AVAILABLE} "
                                'ORDER BY p.pack_id,p.version DESC LIMIT 100').fetchall()
        return {'packs': [dict(zip(('id','version','title','author','description','stopCount','checksum'), row)) for row in rows]}

    @router.get('/v1/packs/{pack_id}/versions/{version}')
    def download_pack(pack_id: str, version: int):
        if not IDENTIFIER.fullmatch(pack_id) or not 1 <= version <= 2147483647:
            raise HTTPException(404, 'Pack not found')
        with psycopg.connect(dsn) as conn:
            row = conn.execute(f"SELECT p.checksum FROM pack_versions p LEFT JOIN pack_reviews r USING(checksum) WHERE p.pack_id=%s AND p.version=%s AND {COURSE_AVAILABLE}", (pack_id, version)).fetchone()
        if not row:
            raise HTTPException(404, 'Pack not found')
        raw = read_pack(row[0])
        return Response(raw, media_type='application/json', headers={'ETag': '"'+row[0]+'"',
                        'Cache-Control': 'no-cache, no-transform', 'X-Content-Type-Options': 'nosniff'})

    @router.get('/v1/packs/{pack_id}/versions/{version}/cover', openapi_extra={'x-wegoh-native-access': False})
    def download_cover(pack_id: str, version: int):
        with psycopg.connect(dsn) as conn:
            checksum = version_row(conn, pack_id, version)
            if not available(conn, checksum):
                raise HTTPException(404, 'Course cover unavailable')
            return cover_response(conn, pack_id, version)
    return router
