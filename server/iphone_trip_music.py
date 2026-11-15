import psycopg
from fastapi import APIRouter, HTTPException, Request, Response
from iphone_sessions import body
from native_functional_identity import business_json
from team_rooms import TeamRooms, failure
from team_trip_context import resolve_trip_context
from team_trip_saved_playlists import add_saved_playlist, list_saved_playlists, move_saved_playlist


def router(service):
    routes = APIRouter()
    auth = service.auth

    def actor(request, response, *, connection=None, mutate=False):
        response.headers['Cache-Control'] = 'private, no-store'
        if request.query_params:
            failure(400, 'IPHONE_INVALID_REQUEST')
        return auth.iphone_sessions.authenticate(request, 'trips:manage' if mutate else 'trips:read',
            connection=connection, lock=mutate and connection is not None)

    def current(request, response, conn, expected, *, mutate=False):
        TeamRooms.graph_lock(conn)
        who = actor(request, response, connection=conn, mutate=mutate)
        if who['id'] != expected['id']:
            failure(401, 'AUTHENTICATION_CHANGED')
        return who

    def collection(conn, trip, who):
        context = resolve_trip_context(auth, conn, trip, who['id'])
        access = service.rooms.access(conn, context['roomId'], who['id'], trip_context=True)
        value = list_saved_playlists(service, conn, trip, context['roomId'], who, False)
        return dict(value, musicSharing=access['consents']['music'])

    async def payload(request, fields):
        raw = await body(request, 'application/json', maximum_bytes=4096)
        value = business_json(request, raw, maximum=4096)
        if set(value) != set(fields):
            failure(400, 'Invalid music fields')
        return value

    @routes.get('/v1/iphone/trips/{trip}/music', include_in_schema=False)
    def read(trip: str, request: Request, response: Response):
        expected = actor(request, response)
        with psycopg.connect(service.dsn) as conn:
            who = current(request, response, conn, expected)
            return collection(conn, trip, who)

    @routes.patch('/v1/iphone/trips/{trip}/music/sharing', include_in_schema=False)
    async def sharing(trip: str, request: Request, response: Response):
        expected = actor(request, response, mutate=True)
        data = await payload(request, ('enabled',))
        if type(data['enabled']) is not bool:
            failure(400, 'Choose music sharing explicitly')
        with psycopg.connect(service.dsn) as conn:
            who = current(request, response, conn, expected, mutate=True)
            context = resolve_trip_context(auth, conn, trip, who['id'])
            access = service.rooms.access(conn, context['roomId'], who['id'], trip_context=True)
            choices = dict(access['consents'], music=data['enabled'])
            auth.trip_service.set_sharing(conn, trip, who['id'], choices)
            return collection(conn, trip, who)

    @routes.post('/v1/iphone/trips/{trip}/music/playlist', status_code=201, include_in_schema=False)
    async def add(trip: str, request: Request, response: Response):
        expected = actor(request, response, mutate=True)
        data = await payload(request, ('title', 'url', 'rightsConfirmed', 'reviewConsent'))
        if data['rightsConfirmed'] is not True or type(data['reviewConsent']) is not bool:
            failure(400, 'Choose link rights and review explicitly')
        with psycopg.connect(service.dsn) as conn:
            who = current(request, response, conn, expected, mutate=True)
            context = resolve_trip_context(auth, conn, trip, who['id'])
            room = context['roomId']
            value = service.add_track(conn, room, who['id'], dict(title=data['title'], artist='음악',
                url=data['url'], rightsConfirmed=data['rightsConfirmed']), trip_context=True)
            item = value['playlist']['tracks'][-1]
            if item['addedBy']['id'] != who['id']:
                raise HTTPException(503, 'Music result unavailable')
            if data['reviewConsent']:
                service.review_track(conn, room, who['id'], item['id'], dict(consent=True), trip_context=True)
            return collection(conn, trip, who)

    @routes.patch('/v1/iphone/trips/{trip}/music/playlist/{item}/position', include_in_schema=False)
    async def move(trip: str, item: str, request: Request, response: Response):
        expected = actor(request, response, mutate=True)
        data = await payload(request, ('afterId',))
        with psycopg.connect(service.dsn) as conn:
            who = current(request, response, conn, expected, mutate=True)
            context = resolve_trip_context(auth, conn, trip, who['id'])
            move_saved_playlist(service, conn, trip, context['roomId'], who, False, item, data)
            return collection(conn, trip, who)

    @routes.post('/v1/iphone/trips/{trip}/music/saved-playlists', include_in_schema=False)
    async def add_saved(trip: str, request: Request, response: Response):
        expected = actor(request, response, mutate=True)
        data = await payload(request, ('playlistId', 'playlistRevision', 'trackId', 'rightsConfirmed', 'reviewConsent'))
        with psycopg.connect(service.dsn) as conn:
            who = current(request, response, conn, expected, mutate=True)
            if 'account:read' not in who['scopes']:
                failure(403, 'SCOPE_DENIED')
            context = resolve_trip_context(auth, conn, trip, who['id'])
            add_saved_playlist(service, conn, trip, context['roomId'], who, False, data)
            return collection(conn, trip, who)

    return routes
