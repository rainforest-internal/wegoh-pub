from fastapi import APIRouter, HTTPException, Request, Response
import psycopg

from native_access import native_resource
from native_functional_identity import request_actor, transaction_actor, business_json
from private_records import VisitCipher
from team_friends import blocked
from team_history import TeamHistory, identifier, text
from team_missions import safety_status
from team_rooms import TeamRooms
from team_trip_context import CLOSED_STATES, trip_state, linked_room, resolve_trip_context
from team_trips import TeamTrips


def unavailable(status=404, detail='Trip result unavailable'):
    raise HTTPException(status, detail)


class TeamTripResults:
    def __init__(self, auth, rooms=None, history=None):
        self.auth, self.dsn, self.enabled = auth, auth.dsn, auth.enabled
        self.rooms = rooms or getattr(auth, 'room_service', None) or TeamRooms(auth)
        self.history = history or getattr(auth, 'history_service', None) or TeamHistory(auth, self.rooms)
        self.trips = getattr(auth, 'trip_service', None) or TeamTrips(auth)

    @staticmethod
    def protect(trip, value):
        return VisitCipher().protect('team-trip-result', trip, value)

    @staticmethod
    def restore(trip, raw):
        return VisitCipher().restore('team-trip-result', trip, raw)

    def finish_trip(self, conn, context):
        if context['state'] != 'completed':
            unavailable(409, 'TRIP_STATE_CONFLICT')
        trip, room = context['tripId'], context['roomId']
        if conn.execute('SELECT 1 FROM team_trip_results WHERE trip_id=%s', (trip,)).fetchone():
            return
        members = []
        for account, raw, joined in conn.execute('SELECT account_id,protected,joined_at FROM team_room_members '
                'WHERE room_id=%s AND left_at IS NULL ORDER BY account_id', (room,)):
            if context['members'].get(account, {}).get('state') != 'accepted':
                continue
            member = self.rooms.member_payload(account, room, raw)
            members.append(dict(accountId=account, role=member['role'], joinedAt=joined.isoformat()))
        courses = []
        from team_trip_route_segments import TeamTripRouteSegments
        frozen = TeamTripRouteSegments(self.trips).load(conn, trip)
        if frozen is not None:
            courses = [dict(id=course['packId'], version=course['version'], addedBy=course['addedById']) for course in frozen['courses']]
        for pack, link in (self.trips.course_links(conn, trip).items() if frozen is None else []):
            row = conn.execute('SELECT version FROM pack_versions WHERE pack_id=%s ORDER BY version DESC LIMIT 1',
                (pack,)).fetchone()
            if row:
                courses.append(dict(id=pack, version=row[0], addedBy=link['addedBy']))
        payload = conn.execute('SELECT protected FROM team_rooms WHERE room_id=%s', (room,)).fetchone()[0]
        room_value = self.rooms.restore('owner:' + context['ownerId'], room, payload)
        if room_value['courseId'] and not any(course['id'] == room_value['courseId'] for course in courses):
            courses.append(dict(id=room_value['courseId'], version=room_value['courseVersion'], addedBy=context['ownerId']))
        places = {row[0] for row in conn.execute('SELECT proposal_id FROM team_trip_place_proposals '
            'WHERE trip_id=%s ORDER BY proposal_id', (trip,))}
        reader = getattr(getattr(self.auth, 'trip_places_service', None), 'result_reader', None)
        if reader:
            result = reader(conn, trip, context['ownerId'])
            if isinstance(result, dict):
                result = result.get('places', [])
            places.update(item['id'] for item in result)
        value = dict(startedAt=context['startedAt'].isoformat(), endedAt=context['endedAt'].isoformat(),
            members=members, cars=self.trips.cars(conn, trip), riders=self.trips.riders(conn, trip),
            courses=courses, course=dict(courseId=room_value['courseId'], courseVersion=room_value['courseVersion']),
            missions=[row[0] for row in conn.execute('SELECT mission_id FROM team_missions WHERE room_id=%s '
                'ORDER BY mission_id LIMIT 50', (room,))],
            places=sorted(places))
        conn.execute('INSERT INTO team_trip_results(trip_id,protected) VALUES(%s,%s) ON CONFLICT(trip_id) DO NOTHING',
            (trip, self.protect(trip, value)))

    def access(self, conn, trip, account):
        identifier(trip)
        state = trip_state(conn, trip)
        room, owner = linked_room(conn, trip)
        member = conn.execute('SELECT joined_at,left_at FROM team_room_members WHERE room_id=%s AND account_id=%s',
            (room, account)).fetchone()
        if not member or not self.rooms.person(account):
            unavailable()
        joined, left = member
        if state['sourceKind'] == 'legacy_room':
            if any(peer != account and blocked(conn, account, peer) for peer, in conn.execute(
                    'SELECT account_id FROM team_room_members WHERE room_id=%s', (room,))):
                unavailable()
        if left is not None:
            context = dict(tripId=trip, roomId=room, ownerId=owner, **state)
        else:
            context = resolve_trip_context(self.auth, conn, trip, account, states=CLOSED_STATES)
        return context, joined, left

    def current_results(self, conn, context, account, value, key, service, method):
        reader = getattr(getattr(self.auth, service, None), method, None)
        if reader is None:
            return [dict(id=item, state='unavailable') for item in value[key]]
        if key == 'missions':
            result = reader(conn, context['tripId'], context['roomId'], account)
        else:
            result = reader(conn, context['tripId'], account)
        if isinstance(result, dict):
            result = result.get(key, [])
        allowed = set(value[key])
        current = {item['id']: {key: field for key, field in item.items() if key not in ('roomId', 'expiresAt')}
            for item in result if item.get('id') in allowed}
        return [current.get(item, dict(id=item, state='unavailable')) for item in value[key]]

    def archive_detail(self, conn, trip, account):
        context, joined, left = self.access(conn, trip, account)
        own = self.history.saved_room_history(conn, context['roomId'], account)
        start, ended = self.history.trip_period(context, joined, left)
        result = dict(tripId=trip, state='left' if left is not None else context['state'], readOnly=True,
            ownPeriod=dict(startedAt=start, endedAt=ended), history=own,
            sourceKind=context['sourceKind'], startTimeEstimated=context['sourceKind'] == 'legacy_room',
            summary=None)
        if left is not None or context['state'] != 'completed':
            return result
        row = conn.execute('SELECT protected,revision FROM team_trip_results WHERE trip_id=%s', (trip,)).fetchone()
        if not row:
            if context['sourceKind'] != 'legacy_room':
                return dict(result, summaryState='unavailable')
            self.finish_trip(conn, context)
            row = conn.execute('SELECT protected,revision FROM team_trip_results WHERE trip_id=%s', (trip,)).fetchone()
        value = self.restore(trip, row[0])
        current = {}
        for peer, raw, joined_at in conn.execute('SELECT account_id,protected,joined_at FROM team_room_members '
                'WHERE room_id=%s AND left_at IS NULL', (context['roomId'],)):
            if (context['members'].get(peer, {}).get('state') == 'accepted'
                    and self.rooms.person(peer) and (peer == account or not blocked(conn, account, peer))):
                current[peer] = dict(self.rooms.member_payload(peer, context['roomId'], raw), joinedAt=joined_at.isoformat())
        visible = {item['accountId'] for item in value['members'] if item['accountId'] in current
            and current[item['accountId']]['joinedAt'] == item['joinedAt']
            and (item['accountId'] == account or current[item['accountId']]['consents']['status'])}
        members = [dict(accountId=item['accountId'], role=item['role'], name=self.rooms.person(item['accountId'])['name'])
            for item in value['members'] if item['accountId'] in visible]
        cars = [dict(id=car, **data, riders=sorted(peer for peer, assigned in value['riders'].items()
                if assigned == car and peer in visible))
            for car, data in value['cars'].items() if data['driverId'] in visible]
        courses = []
        links = self.trips.course_links(conn, trip)
        for course in value['courses']:
            main_course = value['course']['courseId'] == course['id']
            if course['addedBy'] not in visible or not main_course and course['id'] not in links:
                continue
            approved = self.history.course(conn, dict(courseId=course['id'], courseVersion=course['version']))
            if approved:
                courses.append(dict(approved, addedBy=course['addedBy']))
        name, _ = self.rooms.review_name(conn, context['roomId'], context['ownerId'], context['title'], account)
        result.update(revision=row[1], summaryState='available', summary=dict(title=name,
            startedAt=value['startedAt'], endedAt=value['endedAt'], members=members, cars=cars, courses=courses,
            missions=self.current_results(conn, context, account, value, 'missions', 'mission_service', 'trip_result_reader'),
            places=self.current_results(conn, context, account, value, 'places', 'trip_places_service', 'result_reader'),
            safety=safety_status()))
        return result

    def save_history(self, conn, trip, account, title):
        title = text(title, 100)
        context, joined, left = self.access(conn, trip, account)
        return self.history.save_trip_history(conn, context, account, title, joined, left)

    def list_archives(self, conn, account, cursor=None):
        if cursor is not None:
            identifier(cursor)
        self.rooms.graph_lock(conn)
        rows = conn.execute('SELECT t.trip_id FROM team_trips t JOIN team_rooms r USING(trip_id) '
            'JOIN team_room_members m USING(room_id) WHERE m.account_id=%s AND t.deleted_at IS NULL '
            "AND (t.state IN ('completed','cancelled') OR m.left_at IS NOT NULL) "
            'AND (%s::text IS NULL OR t.trip_id<%s) ORDER BY t.trip_id DESC LIMIT 51',
            (account, cursor, cursor)).fetchall()
        result = []
        for trip, in rows[:50]:
            try:
                context, joined, left = self.access(conn, trip, account)
            except HTTPException as error:
                if error.status_code == 404:
                    continue
                raise
            start, ended = self.history.trip_period(context, joined, left)
            result.append(dict(tripId=trip, state='left' if left is not None else context['state'],
                ownPeriod=dict(startedAt=start, endedAt=ended),
                sourceKind=context['sourceKind'], history=self.history.saved_room_history(conn, context['roomId'], account)))
        return dict(archives=result, nextCursor=rows[49][0] if len(rows) > 50 else None)

    def trip_router(self):
        router = APIRouter()
        if not self.enabled:
            return router

        def actor(request, mutate=False):
            if native_resource(request):
                unavailable()
            return request_actor(self.auth, request, mutate=mutate)['id']

        @router.get('/v1/social/trip-archives')
        def listing(request: Request, response: Response):
            actor(request)
            if set(request.query_params) - {'cursor'} or len(request.query_params.getlist('cursor')) > 1:
                unavailable(400, 'Invalid pagination fields')
            with psycopg.connect(self.dsn) as conn:
                account = transaction_actor(self.auth, request, conn)['id']
                result = self.list_archives(conn, account, request.query_params.get('cursor'))
            response.headers['Cache-Control'] = 'private, no-store'
            return result

        @router.get('/v1/social/trips/{trip}/archive')
        @router.get('/v1/social/trips/{trip}/results')
        def read(trip: str, request: Request, response: Response):
            actor(request)
            if request.query_params:
                unavailable(400, 'Invalid result fields')
            with psycopg.connect(self.dsn) as conn:
                account = transaction_actor(self.auth, request, conn)['id']
                result = self.archive_detail(conn, trip, account)
            response.headers['Cache-Control'] = 'private, no-store'
            return result

        @router.post('/v1/social/trips/{trip}/history', status_code=201)
        async def save(trip: str, request: Request, response: Response):
            account = actor(request, True)
            if request.query_params:
                unavailable(400, 'Invalid record fields')
            raw = bytearray()
            async for chunk in request.stream():
                raw.extend(chunk)
                if len(raw) > 2048:
                    unavailable(413, 'Record request too large')
            data = business_json(request, raw, maximum=2048)
            if not isinstance(data, dict) or set(data) != {'title'}:
                unavailable(400, 'Invalid record fields')
            self.auth.rate('history-write:' + account, limit=30)
            with psycopg.connect(self.dsn) as conn:
                account = transaction_actor(self.auth, request, conn, mutate=True)['id']
                result, created = self.save_history(conn, trip, account, data['title'])
            response.status_code = 201 if created else 200
            response.headers['Cache-Control'] = 'private, no-store'
            return result

        from iphone_trip_history import register_iphone_trip_history_routes
        register_iphone_trip_history_routes(router, self)
        return router
