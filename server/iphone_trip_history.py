"""Account-bound completed-trip records and editable shared-course drafts."""
import copy
import hashlib
import json
import secrets

import psycopg
from fastapi import HTTPException, Request, Response
from starlette.concurrency import run_in_threadpool

from iphone_course_copy import _allowed_source
from iphone_sessions import body as iphone_body
from native_access_codec import CodecError, decode_json
from remix_sources import identity, source_fingerprint


def unavailable(status=404, detail='Trip result unavailable'):
    raise HTTPException(status, detail)


def shared_options(results, conn, trip, account):
    results.rooms.graph_lock(conn)
    context, _, left = results.access(conn, trip, account)
    if left is not None or context['state'] != 'completed':
        unavailable(409, 'TRIP_STATE_CONFLICT')
    archive = results.archive_detail(conn, trip, account)
    summary = archive.get('summary')
    if summary is None:
        unavailable(409, 'TRIP_RESULT_UNAVAILABLE')
    remix = results.auth.history_remix_service
    sources, places = [], []
    for course in summary['courses']:
        source = remix.source_course(conn, course['id'], course['version'])
        if not source or not source['available'] or not source['authorAvailable']:
            continue
        from team_friends import blocked
        if account != source['creatorId'] and blocked(conn, account, source['creatorId']):
            continue
        number, permission = remix.reuse_permission(conn, source)
        allowed = account == source['creatorId'] or permission['consent'] and permission['rightsConfirmed']
        raw = remix.raw_course(source['checksum'])
        if hashlib.sha256(raw).hexdigest() != source['checksum']:
            unavailable(503, 'Source course integrity unavailable')
        try:
            pack = json.loads(raw)
        except (ValueError, UnicodeError):
            unavailable(503, 'Source course integrity unavailable')
        if not isinstance(pack, dict) or not isinstance(pack.get('stops'), list) or not 1 <= len(pack['stops']) <= 3:
            unavailable(503, 'Source course integrity unavailable')
        source = dict(courseId=course['id'], version=course['version'], checksum=source['checksum'],
                      reuseRevision=None if account == source['creatorId'] else number)
        sources.append(source)
        for index, stop in enumerate(pack['stops']):
            key = source_fingerprint(dict(source=source, index=index))[:32]
            places.append(dict(id=key, courseId=course['id'], version=course['version'],
                name=stop['name'], latitude=stop['latitude'], longitude=stop['longitude'],
                canReuse=bool(allowed), stop=stop, source=source))
    fingerprint = source_fingerprint(dict(tripId=trip, revision=archive['revision'], sources=sources,
        choices=[dict(id=place['id'], canReuse=place['canReuse']) for place in places]))
    return dict(title=summary['title'], selectionFingerprint=fingerprint,
                places=[{key: value for key, value in place.items() if key not in ('stop', 'source')} for place in places]), places


def make_trip_draft(results, conn, trip, actor, data):
    options, places = shared_options(results, conn, trip, actor['id'])
    selection = data['selectionIds']
    if (not isinstance(selection, list) or not 1 <= len(selection) <= 3
            or any(not isinstance(value, str) for value in selection) or len(set(selection)) != len(selection)):
        unavailable(400, 'Choose one to three shared course places')
    if data['selectionFingerprint'] != options['selectionFingerprint']:
        unavailable(409, 'Shared course selection changed')
    selected = [place for place in places if place['id'] in selection]
    if [place['id'] for place in selected] != selection:
        unavailable(409, 'Shared course selection or order changed')
    if any(not place['canReuse'] for place in selected):
        unavailable(403, 'Source course re-use permission required')
    remix = results.auth.history_remix_service
    if conn.execute('SELECT count(*) FROM team_remix_drafts WHERE account_id=%s', (actor['id'],)).fetchone()[0] >= 500:
        unavailable(409, 'Re-creation draft limit reached')
    sources = []
    for place in selected:
        source = place['source']
        if source not in sources:
            _allowed_source(remix, conn, actor['id'], source['courseId'], source['version'])
            sources.append(source)
    draft_id = secrets.token_hex(16)
    stops = [dict(copy.deepcopy(place['stop']), id='shared-' + place['id']) for place in selected]
    pack = dict(schemaVersion=1, **identity(draft_id, actor), title=options['title'],
                description='여행에서 공유한 장소로 만든 경로', stops=stops)
    source = dict(kind='trip', tripId=trip, courses=[{key: item[key] for key in ('courseId', 'version', 'checksum')} for item in sources])
    saved = dict(draft=pack, source=source, tripCopy=True, selectionIds=selection,
                 selectionFingerprint=options['selectionFingerprint'], sourcePermissions=sources)
    conn.execute('INSERT INTO team_remix_drafts(draft_id,account_id,draft_pack_id,protected) VALUES(%s,%s,%s,%s)',
        (draft_id, actor['id'], pack['id'], remix.protect('draft', actor['id'], draft_id, saved)))
    return dict(pack=pack, tags=[], hasCover=False, remixDraftId=draft_id)


def validate_trip_draft(remix, conn, owner, saved):
    if saved.get('tripCopy') is not True or saved.get('source', {}).get('kind') != 'trip':
        unavailable()
    results = remix.auth.trip_results_service
    options, places = shared_options(results, conn, saved['source']['tripId'], owner)
    if options['selectionFingerprint'] != saved['selectionFingerprint']:
        unavailable(409, 'Shared course selection changed; create a current draft')
    chosen = [place for place in places if place['id'] in saved['selectionIds']]
    if [place['id'] for place in chosen] != saved['selectionIds'] or any(not place['canReuse'] for place in chosen):
        unavailable(403, 'Re-creation rights withdrawn or changed')
    for source in saved['sourcePermissions']:
        current, number = _allowed_source(remix, conn, owner, source['courseId'], source['version'])
        if current['checksum'] != source['checksum'] or number != source['reuseRevision']:
            unavailable(409, 'Source course or re-use permission changed')


def register_iphone_trip_history_routes(router, results):
    auth = results.auth

    def actor(request, *, conn=None, write=False, course=False):
        if request.url.query:
            unavailable(400, 'IPHONE_INVALID_REQUEST')
        if conn is not None:
            results.rooms.graph_lock(conn)
        sessions = auth.iphone_sessions
        who = sessions.authenticate(request, 'trips:manage' if write else 'trips:read',
                                    connection=conn, lock=write and conn is not None)
        if course:
            sessions.authenticate(request, 'courses:write', connection=conn, lock=conn is not None)
            if who['role'] not in ('creator', 'admin'):
                unavailable(403, 'Action not permitted')
        return who

    def private(response):
        response.headers['Cache-Control'] = 'private, no-store'

    async def fields(request, required):
        try:
            value = decode_json(await iphone_body(request, 'application/json'), maximum_bytes=2048)
        except CodecError:
            unavailable(400, 'IPHONE_INVALID_REQUEST')
        if not isinstance(value, dict) or set(value) != set(required):
            unavailable(400, 'IPHONE_INVALID_REQUEST')
        return value

    @router.get('/v1/iphone/trips/{trip}/results', include_in_schema=False)
    def results_read(trip: str, request: Request, response: Response):
        actor(request)
        with psycopg.connect(results.dsn) as conn:
            who = actor(request, conn=conn)
            value = results.archive_detail(conn, trip, who['id'])
        private(response)
        return value

    @router.get('/v1/iphone/trips/{trip}/history', include_in_schema=False)
    def history_read(trip: str, request: Request, response: Response):
        actor(request)
        with psycopg.connect(results.dsn) as conn:
            who = actor(request, conn=conn)
            context, _, _ = results.access(conn, trip, who['id'])
            saved = results.history.saved_room_history(conn, context['roomId'], who['id'])
            if saved is None:
                unavailable(404, 'TRIP_HISTORY_NOT_SAVED')
            value = results.history.detail(conn, saved['id'], who['id'])
        private(response)
        return value

    @router.post('/v1/iphone/trips/{trip}/history', include_in_schema=False, status_code=201)
    async def history_save(trip: str, request: Request, response: Response):
        actor(request, write=True)
        data = await fields(request, ('title',))
        def write():
            with psycopg.connect(results.dsn) as conn:
                who = actor(request, conn=conn, write=True)
                auth.rate('history-write:' + who['id'], limit=30)
                return results.save_history(conn, trip, who['id'], data['title'])
        value, created = await run_in_threadpool(write)
        response.status_code = 201 if created else 200
        private(response)
        return value

    @router.get('/v1/iphone/trips/{trip}/course-draft-options', include_in_schema=False)
    def draft_options(trip: str, request: Request, response: Response):
        actor(request)
        with psycopg.connect(results.dsn) as conn:
            who = actor(request, conn=conn)
            value = shared_options(results, conn, trip, who['id'])[0]
        private(response)
        return value

    @router.post('/v1/iphone/trips/{trip}/course-drafts', include_in_schema=False, status_code=201)
    async def draft_create(trip: str, request: Request, response: Response):
        actor(request, write=True, course=True)
        data = await fields(request, ('selectionIds', 'selectionFingerprint'))
        def write():
            with psycopg.connect(results.dsn) as conn:
                who = actor(request, conn=conn, write=True, course=True)
                auth.rate('trip-course-draft:' + who['id'], limit=20)
                return make_trip_draft(results, conn, trip, who, data)
        value = await run_in_threadpool(write)
        private(response)
        return value
