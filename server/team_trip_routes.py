import psycopg
from fastapi import APIRouter, HTTPException, Request, Response
from starlette.concurrency import run_in_threadpool

from native_access import native_resource
from native_functional_identity import business_json, request_actor, transaction_actor
from team_friends import blocked
from team_rooms import TeamRooms
from team_trip_context import resolve_trip_context, trip_state
from team_trip_hand_raise import CandidateError, HandRaiseCandidates, candidate_input, facilities_input, trip_cars, latest_location, STALE_SECONDS
from team_trip_signal_contexts import fail
from team_trips import TeamTrips, location_choice


from datetime import datetime, timedelta, timezone
import math


def optional(read):
    try:
        return read()
    except HTTPException as error:
        if error.status_code not in (403, 404, 409):
            raise
        return None


def route_position(point, route):
    """Distance along the nearest segment of a shared course, in metres."""
    best, traversed = None, 0.0
    for first, last in zip(route, route[1:]):
        scale = math.cos(math.radians(point['lat']))
        ax, ay = (first['lng']-point['lng'])*111320*scale, (first['lat']-point['lat'])*111320
        bx, by = (last['lng']-point['lng'])*111320*scale, (last['lat']-point['lat'])*111320
        dx, dy = bx-ax, by-ay
        length = math.hypot(dx, dy)
        if not length:
            continue
        fraction = max(0.0, min(1.0, -(ax*dx+ay*dy)/(length*length)))
        distance = math.hypot(ax+fraction*dx, ay+fraction*dy)
        candidate = (distance, traversed+fraction*length)
        if best is None or candidate[0] < best[0]:
            best = candidate
        traversed += length
    return best[1] if best is not None else None


def car_shares_location(conn, context, actor, car):
    peers = [car['driverId']] + [peer['id'] for peer in car.get('passengers', [])]
    return any(context['members'].get(peer, {}).get('locationConsent') and not blocked(conn, actor['id'], peer)
               for peer in peers if peer != actor['id'])


def companion_rows(auth, conn, trips, context, actor, purposes, detail):
    others = [car for car in detail['cars'] if not car['isMine'] and not car['iRide']]
    if context['state'] != 'active':
        return [dict(carId=car['id'], label='위치 공유 꺼짐') for car in others]
    _, reported = trip_cars(auth, conn, trips, context, actor['id'], actor['deviceId'], purposes)
    positions = {row['carId']: row for row in reported}
    mine = latest_location(auth, conn, context['roomId'], actor['id'])
    mine_car = next((car for car in detail['cars'] if car['isMine'] or car['iRide']), {})
    course_stops = {(course['packId'], stop['id']): stop for course in detail.get('courses', []) for stop in course.get('stops', [])}
    places = {place['id']: place for place in mine_car.get('places') or []}
    route = [(course_stops.get((item.get('courseId'), item['ref'])) if item['type'] == 'course' else places.get(item['ref']))
             for item in mine_car.get('routeOrder') or []]
    if not route:
        route = [stop for course in detail.get('courses', []) for stop in course.get('stops', [])]
    route = [stop for stop in route if stop and stop.get('lat') is not None and stop.get('lng') is not None]
    origin = route_position(mine, route) if mine else None
    result = []
    for car in others:
        target = positions.get(car['id'], {})
        along = route_position(target, route) if 'lat' in target else None
        if along is None or origin is None:
            label = ('최근 공유 위치 없음' if car_shares_location(conn, context, actor, car) else '위치 공유 꺼짐') if 'lat' not in target else '내 차 위치 확인 중'
            result.append(dict(carId=car['id'], label=label))
        else:
            delta = along-origin
            result.append(dict(carId=car['id'], distanceMeters=round(abs(delta)), direction='ahead' if delta >= 0 else 'behind'))
    return result


def music_projection(auth, conn, context, actor, purposes):
    service = getattr(auth, 'room_music_service', None)
    if service is None or 'room-music:read' not in purposes or context['state'] not in ('planned', 'active'):
        return None
    permission = service.room_permission(conn, actor['id'], actor['deviceId'], actor['grantId'], context['roomId'], 'receiveMusic', trip_context=True)
    snapshot = service.snapshot(conn, context['roomId'], actor['id'], native=actor, trip_context=True)
    access = service.rooms.access(conn, context['roomId'], actor['id'], None, trip_context=True)
    playlist = service.shared_playlist(conn, context['roomId'], actor['id'], access, trip_context=True)
    selected = snapshot.get('selection')
    tracks = [entry for entry in playlist.get('entries', playlist.get('tracks', [])) if entry.get('track')]
    if not selected and not tracks:
        return dict(name=None,currentTitle=None,trackCount=0,djName=None,displayExpiresAt=permission['expiresAt'])
    owner = service.rooms.person(selected['ownerId']) if selected else None
    current = next((track for track in selected['tracks'] if track['id'] == selected['currentTrackId']), None) if selected else None
    added = next((entry.get('addedBy') for entry in tracks if current and entry['track']['id'] == current['id']), None)
    return dict(name=selected['name'] if selected else None, currentTitle=current['title'] if current else None,
                trackCount=len(selected['tracks']) if selected else len(tracks), djName=(added or owner or {}).get('name'),
                displayExpiresAt=permission['expiresAt'])


def result_projection(auth, conn, context, actor, purposes, detail):
    timeline, count = [], None
    mine = next((car for car in detail['cars'] if car['isMine'] or car['iRide']), None)
    if mine:
        courses = {course['packId']: course for course in detail.get('courses', [])}
        for pack, at in conn.execute('SELECT pack_id,created_at FROM team_trip_car_course_completions '
                'WHERE trip_id=%s AND car_id=%s ORDER BY created_at,pack_id', (context['tripId'], mine['id'])):
            if pack in courses:
                timeline.append(dict(id='course:'+pack, name=courses[pack]['title'], kind='경로 완료', at=at.isoformat()))
    history = getattr(auth, 'history_service', None)
    if history and 'history:read' in purposes:
        saved = history.saved_room_history(conn, context['roomId'], actor['id'])
        record = optional(lambda: history.detail(conn, saved['id'], actor['id'])) if saved else None
        if record:
            count = len(record['visits'])
            timeline.extend(dict(id='visit:'+visit['id'], name=visit['place']['name'], kind='방문 기록',
                                 at=str(visit['visitedAt'])) for visit in record['visits'])
    metrics, metrics_expiry = None, None
    return dict(timeline=sorted(timeline, key=lambda row: row['at']), visitCount=count, metrics=metrics, metricsExpiresAt=metrics_expiry)


def display(auth, conn, trips, trip, actor, purposes, detail):
    context = resolve_trip_context(auth, conn, trip, actor['id'], states=None)
    now = datetime.now(timezone.utc)
    music = optional(lambda: music_projection(auth, conn, context, actor, purposes))
    companions = optional(lambda: companion_rows(auth, conn, trips, context, actor, purposes, detail)) or []
    deadline = now+timedelta(seconds=10)
    if music:
        deadline = min(deadline, datetime.fromtimestamp(music.pop('displayExpiresAt'), timezone.utc))
    if any('distanceMeters' in row for row in companions):
        from team_vehicle import timestamp
        vehicle = auth.vehicle_service
        for peer, member in context['members'].items():
            if member['state'] != 'accepted' or not member.get('locationConsent') or (peer != actor['id'] and blocked(conn, actor['id'], peer)):
                continue
            grants = optional(lambda: vehicle.room_grants(conn, context['roomId'], peer, trip_context=True))
            if grants:
                for grant in grants[1]['devices'].values():
                    expiry = grant.get('expiresAt')
                    if expiry and timestamp(expiry)>now:
                        deadline = min(deadline, timestamp(expiry))
            location = latest_location(auth, conn, context['roomId'], peer)
            if location:
                deadline = min(deadline, location['capturedAt']+timedelta(seconds=STALE_SECONDS))
    result = result_projection(auth, conn, context, actor, purposes, detail)
    metrics_expiry = result.pop('metricsExpiresAt', None)
    if metrics_expiry is not None:
        deadline = min(deadline, metrics_expiry)
    return dict(serverNow=now.isoformat(), validUntil=max(now, deadline).isoformat(),
                endedAt=context['endedAt'].isoformat() if context.get('endedAt') else None,
                music=music, companions=companions,
                **result)


def route_projection(trips, conn, trip, account, *, include_members=False, modern=False):
    from team_trip_plan import TeamTripPlan
    owner, _, members = trips.access(conn, trip, account)
    plan = TeamTripPlan(trips)
    riders = trips.riders(conn, trip)
    from team_trip_route_segments import TeamTripRouteSegments, route_contract_version
    segments = TeamTripRouteSegments(trips)
    cars = []
    for car, value in trips.cars(conn, trip).items():
        driver = value['driverId']
        if driver != account and blocked(conn, driver, account):
            continue
        item = dict(id=car, isMine=driver == account, iRide=riders.get(account) == car,
            places=plan.places(conn, trip, car, account, owner), routeOrder=plan.route_order(conn, trip, car, account, owner))
        if modern:
            item['ordinal'] = value['ordinal']
            item['routePlan'] = segments.project(conn, trip, car, account)
            item['routeStatus'] = segments.status(conn, trip, car, account)
        if include_members:
            item.update(driverId=driver, passengers=[dict(id=peer) for peer, assigned in riders.items() if assigned == car])
        if (account in (owner, driver) or riders.get(account) == car) and (route_contract_version(conn, trip) == 1 or driver == account or riders.get(account) == car):
            state = plan.route_state(conn, trip, car)[1]
            item['routeRevision'] = state.get('routeRevision', 0)
            item.update(plan.project_next(conn, trip, car, account, state))
        cars.append(item)
    result = dict(id=trip, revision=trip_state(conn, trip)['revision'], cars=cars,
        courses=trips.courses(conn, trip, account, trips.rights(account, owner, members)['edit']))
    if modern:
        result['routeContractVersion'] = route_contract_version(conn, trip)
    return result



class TeamTripRoutes:
    def __init__(self, auth):
        self.auth, self.dsn = auth, auth.dsn
        self.trips = getattr(auth, 'trip_service', None) or TeamTrips(auth)
        self.signals = auth.trip_signal_contexts
        self.places = auth.trip_places_service
        if getattr(auth, 'hand_raise_service', None) is None:
            auth.hand_raise_service = HandRaiseCandidates.from_environment()

    def workspace(self, conn, trip, account, *, native=False, purposes=frozenset()):
        context = resolve_trip_context(self.auth, conn, trip, account, states=None)
        members = self.signals.members(conn, trip, context['roomId'])
        visible = {peer: self.trips.person(peer) for peer in members if peer == account or not blocked(conn, peer, account)}
        visible = {peer: person for peer, person in visible.items() if person}
        rights = self.trips.rights(account, context['ownerId'], context['members'])
        people = [dict(person, isMe=peer == account, isOwner=peer == context['ownerId']) for peer, person in visible.items()]
        people.sort(key=lambda item: (not item['isOwner'], item['id']))
        riders = self.trips.riders(conn, trip)
        cars = [dict(id=car, **value, passengers=[peer for peer, assigned in riders.items() if assigned == car and peer in visible])
            for car, value in self.trips.cars(conn, trip).items() if value['driverId'] in visible]
        sharing = dict(members[account]['consents'], location=context['members'][account].get('locationConsent', False)
                       and context['state'] in ('planned', 'active'))
        live, active = context['state'] in ('planned', 'active'), context['state'] == 'active'
        installed = getattr(self.auth, 'trip_feature_routes', {})
        features = {}
        for name, ready, state, consent in (
                ('signals', True, active, 'status'), ('places', True, live, 'location'),
                ('music', installed.get('music', False), live, 'music'),
                ('voice', installed.get('voice', False), active, 'voice'),
                ('missions', installed.get('missions', False), live, None),
                ('drivingData', installed.get('drivingData', False), active, None),
                ('reports', installed.get('reports', False), active, None),
                ('results', installed.get('results', False), context['state'] == 'completed', None)):
            features[name] = dict(available=bool(ready and state), consentRequired=bool(name != 'signals' and consent and not sharing[consent]))
        if native:
            for name, purpose in (('music', 'room-music:read'), ('voice', 'room-voice:receive'),
                    ('missions', 'missions:read'), ('drivingData', 'rooms:interact'),
                    ('reports', 'rooms:read'), ('results', None)):
                if purpose is None or purpose not in purposes:
                    features[name] = dict(available=False, consentRequired=True)
        return dict(tripId=trip, revision=context['revision'], state=context['state'], startedAt=context['startedAt'],
            endedAt=context['endedAt'], title=context['title'], description=context['description'],
            myPermissions=dict(rights, owner=account == context['ownerId']), members=people, cars=cars,
            roles=[dict(accountId=peer, role=members[peer]['role']) for peer in visible],
            mySharing={key: sharing[key] for key in ('status', 'location')} if native else sharing, features=features)

    def router(self):
        router = APIRouter()
        if not self.auth.enabled:
            return router

        def iphone(request):
            return request.url.path.startswith('/v1/iphone/')

        def iphone_actor(request, *, connection=None, mutate=False, scopes=None):
            if request.url.query:
                fail(400, 'IPHONE_INVALID_REQUEST')
            scopes = scopes or ('trips:manage' if mutate else 'trips:read',)
            identity = None
            for scope in scopes:
                identity = self.auth.iphone_sessions.authenticate(request, scope,
                    connection=connection, lock=mutate and connection is not None)
            return identity

        def actor(request, response, *, mutate=False, native=False, scopes=None):
            response.headers['Cache-Control'] = 'private, no-store'
            if native_resource(request) and not native:
                fail(403, '차량에서 사용할 수 없는 경로입니다.')
            identity = (iphone_actor(request, mutate=mutate, scopes=scopes) if iphone(request)
                else request_actor(self.auth, request, mutate=mutate))
            if mutate:
                self.auth.rate('trip-workspace-mutate:' + identity['id'], limit=60)
            return identity['id']

        def transaction(request, conn, account, *, mutate=False, scopes=None):
            TeamRooms.graph_lock(conn)
            identity = (iphone_actor(request, connection=conn, mutate=mutate, scopes=scopes) if iphone(request)
                else transaction_actor(self.auth, request, conn, mutate=mutate))
            if identity['id'] != account:
                fail(401, 'AUTHENTICATION_CHANGED')
            return identity

        async def body(request, required=(), optional=(), *, empty=False):
            raw = bytearray()
            if iphone(request):
                from iphone_sessions import body as iphone_body
                raw.extend(await iphone_body(request, 'application/json', maximum_bytes=4096))
            else:
                async for chunk in request.stream():
                    raw.extend(chunk)
                    if len(raw) > 4096:
                        fail(413, 'Request too large')
            if not raw and empty and not native_resource(request) and not iphone(request):
                return {}
            value = business_json(request, raw, maximum=4096)
            if not set(required) <= set(value) or set(value) - set(required) - set(optional):
                fail(400, 'Invalid trip fields')
            return value

        def page(request):
            params = request.query_params
            if set(params) - {'limit', 'cursor'} or any(len(params.getlist(key)) != 1 for key in params):
                fail(400, 'Invalid page query')
            raw = params.get('limit', '50')
            if not raw.isascii() or not raw.isdigit() or len(raw) > 3:
                fail(400, 'Invalid page size')
            return int(raw), params.get('cursor')

        @router.get('/v1/social/trips/{id}/workspace')
        def workspace(id: str, request: Request, response: Response):
            who = actor(request, response, native=True)
            with psycopg.connect(self.dsn) as conn:
                transaction(request, conn, who)
                snapshot = getattr(request.state, 'functional_snapshot', {})
                return self.workspace(conn, id, who, native=native_resource(request),
                    purposes=snapshot.get('approvedPurposes', frozenset()))

        async def transition(id, action, request, response):
            who = actor(request, response, mutate=True, native=action in ('start', 'finish') and request.url.path.startswith('/v1/native/'))
            data = await body(request, ('revision',), ('routeContractVersion', 'endActiveTrip') if action == 'start' else ())
            if 'routeContractVersion' in data and (type(data['routeContractVersion']) is not int or data['routeContractVersion'] != 2):
                fail(400, 'TRIP_ROUTE_CONTRACT_INVALID')
            if type(data.get('endActiveTrip', False)) is not bool:
                fail(400, 'Invalid trip transition')
            with psycopg.connect(self.dsn) as conn:
                transaction(request, conn, who, mutate=True)
                return self.trips.transition(conn, id, who, action, data['revision'], data.get('routeContractVersion'),
                    end_active_trip=data.get('endActiveTrip', False))

        @router.post('/v1/iphone/trips/{id}/start', include_in_schema=False)
        @router.post('/v1/social/trips/{id}/start')
        @router.post('/v1/native/trips/{id}/start')
        async def start(id: str, request: Request, response: Response):
            return await transition(id, 'start', request, response)

        @router.post('/v1/social/trips/{id}/finish')
        @router.post('/v1/iphone/trips/{id}/finish', include_in_schema=False)
        @router.post('/v1/native/trips/{id}/finish')
        async def finish(id: str, request: Request, response: Response):
            return await transition(id, 'finish', request, response)

        @router.post('/v1/iphone/trips/{id}/cancel', include_in_schema=False)
        @router.post('/v1/social/trips/{id}/cancel')
        async def cancel(id: str, request: Request, response: Response):
            return await transition(id, 'cancel', request, response)

        @router.put('/v1/iphone/trips/{id}/members/{accountId}/role', include_in_schema=False)
        @router.put('/v1/social/trips/{id}/members/{accountId}/role')
        async def role(id: str, accountId: str, request: Request, response: Response):
            who = actor(request, response, mutate=True)
            data = await body(request, ('role', 'revision'))
            with psycopg.connect(self.dsn) as conn:
                transaction(request, conn, who, mutate=True)
                return self.trips.set_role(conn, id, who, accountId, data['role'], data['revision'])

        def client_actor(request, response, *, mutate=False):
            vehicle = request.url.path.startswith('/v1/native/')
            if vehicle != native_resource(request):
                fail(403, 'Wrong trip settings client')
            return actor(request, response, mutate=mutate, native=vehicle)

        @router.get('/v1/iphone/trips/{id}/location-sharing', include_in_schema=False)
        @router.get('/v1/social/trips/{id}/location-sharing')
        @router.get('/v1/native/trips/{id}/location-sharing')
        def location_sharing(id: str, request: Request, response: Response):
            who = client_actor(request, response)
            with psycopg.connect(self.dsn) as conn:
                transaction(request, conn, who)
                return self.trips.location_sharing(conn, id, who)

        @router.patch('/v1/iphone/trips/{id}/location-sharing', include_in_schema=False)
        @router.patch('/v1/social/trips/{id}/location-sharing')
        @router.patch('/v1/native/trips/{id}/location-sharing')
        async def update_location_sharing(id: str, request: Request, response: Response):
            who = client_actor(request, response, mutate=True)
            data = await body(request, ('locationConsent',))
            enabled = location_choice(data)
            with psycopg.connect(self.dsn) as conn:
                transaction(request, conn, who, mutate=True)
                return self.trips.location_sharing(conn, id, who, enabled=enabled)

        @router.patch('/v1/social/trips/{id}/sharing')
        async def sharing(id: str, request: Request, response: Response):
            who = actor(request, response, mutate=True)
            data = await body(request, ('consents',))
            with psycopg.connect(self.dsn) as conn:
                transaction(request, conn, who, mutate=True)
                return self.trips.set_sharing(conn, id, who, data['consents'])

        @router.get('/v1/iphone/trips/{id}/voice-participation', include_in_schema=False)
        @router.get('/v1/social/trips/{id}/voice-participation')
        @router.get('/v1/native/trips/{id}/voice-participation')
        def voice_participation(id: str, request: Request, response: Response):
            who = client_actor(request, response)
            with psycopg.connect(self.dsn) as conn:
                transaction(request, conn, who)
                return self.trips.voice_participation(conn, id, who)

        @router.patch('/v1/iphone/trips/{id}/voice-participation', include_in_schema=False)
        @router.patch('/v1/social/trips/{id}/voice-participation')
        @router.patch('/v1/native/trips/{id}/voice-participation')
        async def update_voice_participation(id: str, request: Request, response: Response):
            who = client_actor(request, response, mutate=True)
            data = await body(request, ('participating', 'memberJoinedAt', 'revision'))
            with psycopg.connect(self.dsn) as conn:
                transaction(request, conn, who, mutate=True)
                return self.trips.voice_participation(conn, id, who, data)

        @router.get('/v1/iphone/trips/{id}/signals', include_in_schema=False)
        @router.get('/v1/social/trips/{id}/signals')
        def signals(id: str, request: Request, response: Response):
            who = actor(request, response, native=True)
            limit, cursor = page(request)
            with psycopg.connect(self.dsn) as conn:
                transaction(request, conn, who)
                return self.signals.list(conn, id, who, limit, cursor)

        @router.post('/v1/iphone/trips/{id}/signals', status_code=201, include_in_schema=False)
        @router.post('/v1/social/trips/{id}/signals', status_code=201)
        async def signal(id: str, request: Request, response: Response):
            who = actor(request, response, mutate=True, native=True)
            data = await body(request, ('kind',), ('destination', 'candidateReceipt'))
            self.auth.rate('trip-signal:' + who, limit=20)
            with psycopg.connect(self.dsn) as conn:
                transaction(request, conn, who, mutate=True)
                return self.signals.create(conn, id, who, data['kind'], data.get('destination'),
                    candidate_receipt=data.get('candidateReceipt'))

        @router.post('/v1/iphone/trips/{id}/signals/candidates', include_in_schema=False)
        @router.post('/v1/social/trips/{id}/signals/candidates')
        @router.post('/v1/native/trips/{id}/signals/candidates')
        async def signal_candidates(id: str, request: Request, response: Response):
            who = actor(request, response, mutate=True, native=request.url.path.startswith('/v1/native/'),
                scopes=('trips:read', 'maps:read'))
            data = await body(request, ('kind', 'location'), ('destination', 'requiredFacilities'))
            service = self.auth.hand_raise_service
            try:
                kind, location, destination = candidate_input(data)
                required = facilities_input(data)
            except CandidateError as error:
                fail(error.status, error.code)
            native = request.url.path.startswith('/v1/native/')
            device = self.auth.device(request)['deviceId'] if native else None
            from team_trip_route_segments import TeamTripRouteSegments
            segments = TeamTripRouteSegments(self.trips)
            with psycopg.connect(self.dsn) as conn:
                transaction(request, conn, who, mutate=True, scopes=('trips:read', 'maps:read'))
                resolve_trip_context(self.auth, conn, id, who, states=('active',))
                segments.check_shared(conn, id, who)
            try:
                service.admit(who, id)
            except CandidateError as error:
                raise HTTPException(error.status, error.code, headers=dict({'Cache-Control': 'private, no-store'},
                    **({'Retry-After': '60'} if error.status == 429 else {}))) from None
            with psycopg.connect(self.dsn) as conn:
                transaction(request, conn, who, mutate=True, scopes=('trips:read', 'maps:read'))
                context = resolve_trip_context(self.auth, conn, id, who, states=('active',))
                segments.check_shared(conn, id, who)
                snapshot = getattr(request.state, 'functional_snapshot', {})
                mine, others = trip_cars(self.auth, conn, self.trips, context, who, device,
                    snapshot.get('approvedPurposes', frozenset()) if native else frozenset())
            try:
                result = await run_in_threadpool(service.find, kind, dict(location, carId=mine), others, destination, required_facilities=required)
            except CandidateError as error:
                raise HTTPException(error.status, error.code, headers=dict({'Cache-Control': 'private, no-store'},
                    **({'Retry-After': '60'} if error.status == 429 else {}))) from None

            with psycopg.connect(self.dsn) as conn:
                transaction(request, conn, who, mutate=True, scopes=('trips:read', 'maps:read'))
                context = resolve_trip_context(self.auth, conn, id, who, states=('active',))
                segments.check_shared(conn, id, who)
                from trip_candidate_receipts import issue
                now = conn.execute('SELECT extract(epoch FROM clock_timestamp())').fetchone()[0]
                for candidate in result['candidates']:
                    candidate['candidateReceipt'] = (issue(id, who, context['revision'], kind, candidate, float(now))
                        if candidate['verdict'] == 'ahead' else None)
            return result

        @router.post('/v1/iphone/trips/{id}/signals/{signal}/vote', include_in_schema=False)
        @router.post('/v1/social/trips/{id}/signals/{signal}/vote')
        async def vote(id: str, signal: str, request: Request, response: Response):
            who = actor(request, response, mutate=True, native=True)
            data = await body(request, ('choice',))
            if not isinstance(data['choice'], str) or data['choice'] not in ('agree', 'pass'):
                fail(400, 'Invalid vote')
            self.auth.rate('trip-vote:' + who, limit=30)
            with psycopg.connect(self.dsn) as conn:
                transaction(request, conn, who, mutate=True)
                source = 'iphone' if iphone(request) else 'native' if native_resource(request) else 'web'
                return self.signals.vote(conn, id, who, signal, data['choice'], source=source)

        @router.post('/v1/iphone/trips/{id}/signals/{signal}/finish', include_in_schema=False)
        @router.post('/v1/social/trips/{id}/signals/{signal}/finish')
        async def finish_signal(id: str, signal: str, request: Request, response: Response):
            who = actor(request, response, mutate=True, native=True)
            data = await body(request, ('result',))
            with psycopg.connect(self.dsn) as conn:
                transaction(request, conn, who, mutate=True)
                return self.signals.finish(conn, id, who, signal, data['result'])

        @router.delete('/v1/iphone/trips/{id}/signals/{signal}/vote', include_in_schema=False)
        @router.delete('/v1/social/trips/{id}/signals/{signal}/vote')
        async def withdraw_vote(id: str, signal: str, request: Request, response: Response):
            who = actor(request, response, mutate=True, native=True)
            await body(request, empty=True)
            with psycopg.connect(self.dsn) as conn:
                transaction(request, conn, who, mutate=True)
                return self.signals.vote(conn, id, who, signal)

        @router.get('/v1/social/trips/{id}/places')
        def places(id: str, request: Request, response: Response):
            who = actor(request, response, native=True)
            limit, cursor = page(request)
            with psycopg.connect(self.dsn) as conn:
                transaction(request, conn, who)
                return self.places.list(conn, id, who, limit, cursor)

        @router.post('/v1/social/trips/{id}/places', status_code=201)
        async def create_place(id: str, request: Request, response: Response):
            who = actor(request, response, mutate=True)
            data = await body(request, ('category',), ('place', 'sourceSignalId'))
            if ('place' in data) == ('sourceSignalId' in data):
                fail(400, 'Choose a place or a source signal')
            with psycopg.connect(self.dsn) as conn:
                transaction(request, conn, who, mutate=True)
                return self.places.create(conn, id, who, data['category'], data.get('place'), data.get('sourceSignalId'))

        @router.patch('/v1/social/trips/{id}/places/{proposal}')
        async def update_place(id: str, proposal: str, request: Request, response: Response):
            who = actor(request, response, mutate=True)
            data = await body(request, ('revision',), ('place', 'recommended', 'state'))
            with psycopg.connect(self.dsn) as conn:
                transaction(request, conn, who, mutate=True)
                return self.places.update(conn, id, who, proposal, data)

        @router.delete('/v1/social/trips/{id}/places/{proposal}')
        async def delete_place(id: str, proposal: str, request: Request, response: Response):
            who = actor(request, response, mutate=True)
            data = await body(request, ('revision',))
            with psycopg.connect(self.dsn) as conn:
                transaction(request, conn, who, mutate=True)
                return self.places.update(conn, id, who, proposal, dict(data, state='withdrawn'))

        @router.patch('/v1/social/trips/{id}/signals/{signal}/review-request')
        async def review_place(id: str, signal: str, request: Request, response: Response):
            who = actor(request, response, mutate=True)
            data = await body(request, ('consent',))
            if type(data['consent']) is not bool:
                fail(400, 'Explicit review consent required')
            content = self.signals.rooms.content
            if not content:
                fail()
            with psycopg.connect(self.dsn) as conn:
                transaction(request, conn, who, mutate=True)
                context = resolve_trip_context(self.auth, conn, id, who)
                owner, value, *_ = self.signals.visible(conn, context, signal, who)
                if owner != who or not value.get('destination'):
                    fail()
                result = content.request(conn, 'room-place', context['roomId'] + ':' + signal, who,
                    dict(name=value['destination']['name']), data['consent'])
                return {key: result[key] for key in ('state', 'requested', 'checksum')}

        @router.post('/v1/social/trips/{id}/signals/{signal}/reports', status_code=202)
        async def report_place(id: str, signal: str, request: Request, response: Response):
            who = actor(request, response, mutate=True)
            data = await body(request, ('reason',))
            content = self.signals.rooms.content
            if not content:
                fail()
            self.auth.rate('content-report:' + who, limit=20)
            with psycopg.connect(self.dsn) as conn:
                transaction(request, conn, who, mutate=True)
                context = resolve_trip_context(self.auth, conn, id, who)
                owner, value, *_ = self.signals.visible(conn, context, signal, who)
                if not value.get('destination'):
                    fail()
                projection = dict(name=value['destination']['name'])
                key = context['roomId'] + ':' + signal
                if owner != who and not content.allowed(conn, 'room-place', key, owner, projection):
                    fail()
                return content.report(conn, 'room-place', key, owner, projection, who, data['reason'])

        from team_trip_plan import TeamTripPlan
        plan = TeamTripPlan(self.trips)

        @router.get('/v1/native/trips/{id}')
        def native_detail(id: str, request: Request, response: Response):
            who = actor(request, response, native=True)
            presentation = request.headers.getlist('X-WegoH-Trip-Route-Contract')
            if presentation and presentation != ['2']:
                fail(400, 'TRIP_ROUTE_PRESENTATION_INVALID')
            with psycopg.connect(self.dsn) as conn:
                identity = transaction(request, conn, who)
                section = request.query_params.get('section')
                if section:
                    if section not in ('route', 'location') or list(request.query_params.multi_items()) != [('section', section)]:
                        fail(400, 'Invalid trip section')
                    route = route_projection(self.trips, conn, id, who, include_members=section == 'location', modern=bool(presentation))
                    if section == 'route':
                        return route
                    context = resolve_trip_context(self.auth, conn, id, who, states=None)
                    now = conn.execute('SELECT clock_timestamp()').fetchone()[0]
                    return dict(id=id, revision=context['revision'], locationConsent=context['members'][who].get('locationConsent', False)
                        and context['state'] in ('planned', 'active'), display=dict(serverNow=now.isoformat(),
                        validUntil=(now + timedelta(seconds=15)).isoformat(), timeline=[], visitCount=None, metrics=None,
                        music=None, endedAt=None, companions=companion_rows(self.auth, conn, self.trips, context, identity,
                            set(request.state.functional_snapshot['approvedPurposes']), route)))
                result = self.trips.detail(conn, id, who, native=True)
                result['display'] = display(self.auth, conn, self.trips, id, identity,
                    set(request.state.functional_snapshot['approvedPurposes']), result)
                return result

        @router.get('/v1/iphone/trips/{id}/cars/{carId}/places', include_in_schema=False)
        @router.get('/v1/social/trips/{id}/cars/{carId}/places')
        @router.get('/v1/native/trips/{id}/cars/{carId}/places')
        def car_places(id: str, carId: str, request: Request, response: Response):
            who = actor(request, response, native=request.url.path.startswith('/v1/native/'))
            with psycopg.connect(self.dsn) as conn:
                transaction(request, conn, who)
                (owner, _, _), _ = plan.context(conn, id, carId, who, mutable=False)
                return dict(places=plan.places(conn, id, carId, who, owner))

        @router.post('/v1/iphone/trips/{id}/cars/{carId}/places', status_code=201, include_in_schema=False)
        @router.post('/v1/social/trips/{id}/cars/{carId}/places', status_code=201)
        @router.post('/v1/native/trips/{id}/cars/{carId}/places', status_code=201)
        async def add_car_place(id: str, carId: str, request: Request, response: Response):
            who = actor(request, response, mutate=True, native=request.url.path.startswith('/v1/native/'))
            data = await body(request, ('kind', 'name', 'lat', 'lng'))
            with psycopg.connect(self.dsn) as conn:
                transaction(request, conn, who, mutate=True)
                return plan.create_place(conn, id, carId, who, data)

        @router.delete('/v1/iphone/trips/{id}/cars/{carId}/places/{placeId}', include_in_schema=False)
        @router.delete('/v1/social/trips/{id}/cars/{carId}/places/{placeId}')
        @router.delete('/v1/native/trips/{id}/cars/{carId}/places/{placeId}')
        async def delete_car_place(id: str, carId: str, placeId: str, request: Request, response: Response):
            who = actor(request, response, mutate=True, native=request.url.path.startswith('/v1/native/'))
            await body(request, empty=True)
            with psycopg.connect(self.dsn) as conn:
                transaction(request, conn, who, mutate=True)
                return plan.delete_place(conn, id, carId, placeId, who)

        async def select_place(id, carId, placeId, request, response, selected):
            who = actor(request, response, mutate=True)
            await body(request, empty=True)
            with psycopg.connect(self.dsn) as conn:
                transaction(request, conn, who, mutate=True)
                return plan.select(conn, id, carId, placeId, who, selected)

        @router.put('/v1/social/trips/{id}/cars/{carId}/places/{placeId}/select')
        @router.put('/v1/iphone/trips/{id}/cars/{carId}/places/{placeId}/select', include_in_schema=False)
        async def select_car_place(id: str, carId: str, placeId: str, request: Request, response: Response):
            return await select_place(id, carId, placeId, request, response, True)

        @router.delete('/v1/social/trips/{id}/cars/{carId}/places/{placeId}/select')
        @router.delete('/v1/iphone/trips/{id}/cars/{carId}/places/{placeId}/select', include_in_schema=False)
        async def unselect_car_place(id: str, carId: str, placeId: str, request: Request, response: Response):
            return await select_place(id, carId, placeId, request, response, False)

        @router.put('/v1/iphone/trips/{id}/cars/{carId}/my-places', include_in_schema=False)
        async def my_places(id: str, carId: str, request: Request, response: Response):
            from team_trip_my_places import TeamTripMyPlaces
            who = actor(request, response, mutate=True)
            data = await body(request, ('revision', 'pickup', 'drop', 'dropAtPickup'))
            with psycopg.connect(self.dsn) as conn:
                transaction(request, conn, who, mutate=True)
                return TeamTripMyPlaces(self.trips).save(conn, id, carId, who, data)

        @router.put('/v1/social/trips/{id}/cars/{carId}/route-order')
        @router.put('/v1/native/trips/{id}/cars/{carId}/route-order')
        async def route_order(id: str, carId: str, request: Request, response: Response):
            who = actor(request, response, mutate=True, native=request.url.path.startswith('/v1/native/'))
            data = await body(request, ('items',), ('routeRevision', 'routeContractVersion'))
            if 'routeContractVersion' in data and (type(data['routeContractVersion']) is not int or data['routeContractVersion'] != 2):
                fail(400, 'TRIP_ROUTE_CONTRACT_INVALID')
            if 'routeRevision' in data and type(data['routeRevision']) is not int:
                fail(400, 'Invalid route revision')
            with psycopg.connect(self.dsn) as conn:
                transaction(request, conn, who, mutate=True)
                return plan.set_order(conn, id, carId, who, data['items'], data.get('routeRevision'), data.get('routeContractVersion'))

        @router.post('/v1/social/trips/{id}/cars/{carId}/route-arrivals')
        @router.post('/v1/native/trips/{id}/cars/{carId}/route-arrivals')
        async def route_arrival(id: str, carId: str, request: Request, response: Response):
            from team_trip_route_segments import TeamTripRouteSegments
            who = actor(request, response, mutate=True, native=request.url.path.startswith('/v1/native/'))
            data = await body(request, ('routeRevision', 'progressRevision', 'item'), ('singleJoinCompletion',))
            with psycopg.connect(self.dsn) as conn:
                transaction(request, conn, who, mutate=True)
                return TeamTripRouteSegments(self.trips).arrive(conn, id, carId, who, data)

        @router.put('/v1/social/trips/{id}/cars/{carId}/route-progress')
        @router.put('/v1/native/trips/{id}/cars/{carId}/route-progress')
        async def route_progress(id: str, carId: str, request: Request, response: Response):
            who = actor(request, response, mutate=True, native=request.url.path.startswith('/v1/native/'))
            data = await body(request, ('next', 'routeRevision'))
            with psycopg.connect(self.dsn) as conn:
                transaction(request, conn, who, mutate=True)
                return plan.progress(conn, id, carId, who, data['next'], data['routeRevision'])

        @router.post('/v1/social/trips/{id}/cars/{carId}/ride-invites', status_code=201)
        @router.post('/v1/native/trips/{id}/cars/{carId}/ride-invites', status_code=201)
        async def ride_invite(id: str, carId: str, request: Request, response: Response):
            who = actor(request, response, mutate=True, native=request.url.path.startswith('/v1/native/'))
            data = await body(request, ('accountId',))
            with psycopg.connect(self.dsn) as conn:
                transaction(request, conn, who, mutate=True)
                return plan.invite(conn, id, carId, who, data['accountId'])

        @router.post('/v1/iphone/trips/{id}/cars/{carId}/ride-invites/{inviteId}/respond', include_in_schema=False)
        @router.post('/v1/social/trips/{id}/cars/{carId}/ride-invites/{inviteId}/respond')
        async def respond_ride_invite(id: str, carId: str, inviteId: str, request: Request, response: Response):
            who = actor(request, response, mutate=True)
            data = await body(request, ('accept',))
            with psycopg.connect(self.dsn) as conn:
                transaction(request, conn, who, mutate=True)
                return plan.respond(conn, id, carId, inviteId, who, data['accept'])

        @router.delete('/v1/social/trips/{id}/cars/{carId}/ride-invites/{inviteId}')
        @router.delete('/v1/native/trips/{id}/cars/{carId}/ride-invites/{inviteId}')
        async def cancel_ride_invite(id: str, carId: str, inviteId: str, request: Request, response: Response):
            who = actor(request, response, mutate=True, native=request.url.path.startswith('/v1/native/'))
            await body(request, empty=True)
            with psycopg.connect(self.dsn) as conn:
                transaction(request, conn, who, mutate=True)
                return plan.cancel_invite(conn, id, carId, inviteId, who)

        @router.delete('/v1/social/trips/{id}/cars/{carId}/riders/{accountId}')
        @router.delete('/v1/native/trips/{id}/cars/{carId}/riders/{accountId}')
        async def remove_rider(id: str, carId: str, accountId: str, request: Request, response: Response):
            who = actor(request, response, mutate=True, native=request.url.path.startswith('/v1/native/'))
            await body(request, empty=True)
            with psycopg.connect(self.dsn) as conn:
                transaction(request, conn, who, mutate=True)
                return plan.remove_rider(conn, id, carId, who, accountId)

        @router.put('/v1/native/trips/{id}/cars/{carId}/courses/{packId}/driving-score')
        async def report_driving_score(id: str, carId: str, packId: str, request: Request, response: Response):
            from team_trip_driving_scores import TeamTripDrivingScores
            if not native_resource(request):
                fail(403, 'Native driver device required')
            who = actor(request, response, mutate=True, native=True)
            data = await body(request, ('drivingScore',))
            with psycopg.connect(self.dsn) as conn:
                transaction(request, conn, who, mutate=True)
                result = TeamTripDrivingScores(self.trips).write(conn, id, carId, packId, who, data['drivingScore'])
                from team_trip_driving_versus import TeamTripDrivingVersus
                TeamTripDrivingVersus(self.trips).record_report(conn, id, carId, packId, who,
                    data['drivingScore'], request.state.device_identity)
                return result

        @router.post('/v1/social/trips/{id}/cars/{carId}/courses/{packId}/complete')
        @router.post('/v1/native/trips/{id}/cars/{carId}/courses/{packId}/complete')
        async def complete_car_course(id: str, carId: str, packId: str, request: Request, response: Response):
            who = actor(request, response, mutate=True, native=request.url.path.startswith('/v1/native/'))
            data = await body(request, optional=('drivingScore', 'routeRevision', 'progressRevision'), empty=True)
            progress_keys = {'routeRevision', 'progressRevision'} & data.keys()
            if progress_keys and (progress_keys != {'routeRevision', 'progressRevision'}
                    or any(type(data[key]) is not int or not 0 <= data[key] <= 2147483647 for key in progress_keys)):
                fail(400, 'TRIP_ROUTE_PROGRESS_INVALID')
            progress = {key: data[key] for key in progress_keys} if progress_keys else None
            with psycopg.connect(self.dsn) as conn:
                transaction(request, conn, who, mutate=True)
                if 'drivingScore' in data:
                    from team_trip_driving_scores import driving_score
                    if not native_resource(request):
                        fail(403, 'Native driver device required')
                    driving_score(data['drivingScore'], final=True)
                result = plan.complete(conn, id, carId, packId, who, data.get('drivingScore'), progress)
                if 'drivingScore' in data:
                    from team_trip_driving_versus import TeamTripDrivingVersus
                    TeamTripDrivingVersus(self.trips).record_report(conn, id, carId, packId, who,
                        data['drivingScore'], request.state.device_identity)
                return result

        @router.get('/v1/iphone/trips/{id}/friends', include_in_schema=False)
        @router.get('/v1/native/trips/{id}/friends')
        def invite_friends(id: str, request: Request, response: Response):
            from account_handles import account_person
            from team_friends import pair_ids, read_pair, has_vehicle
            who = actor(request, response, native=True)
            with psycopg.connect(self.dsn) as conn:
                transaction(request, conn, who)
                owner, _, members = self.trips.access(conn, id, who, permission='invite')
                friends = []
                for peer, in conn.execute('SELECT CASE WHEN account_a=%s THEN account_b ELSE account_a END '
                        'FROM team_friend_pairs WHERE account_a=%s OR account_b=%s ORDER BY 1', (who, who, who)):
                    value, _ = read_pair(conn, *pair_ids(who, peer))
                    entry = account_person(conn, peer)
                    if (entry and value['state'] == 'accepted' and not value['blockedBy']
                            and (peer == owner or not blocked(conn, owner, peer))):
                        friends.append(dict(id=peer, name=entry['name'], hasVehicle=has_vehicle(conn, peer),
                            tripState=members.get(peer, {}).get('state', 'none')))
                return dict(friends=friends)

        from team_trip_driving_versus import install as install_driving_versus
        install_driving_versus(router, self.trips, actor, transaction)
        from team_trip_total_score import install as install_total_score
        install_total_score(router, self.trips, actor, transaction, body)
        return router
