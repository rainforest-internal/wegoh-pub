import math

from fastapi import HTTPException

from private_records import PrivateRecordError
from team_friends import blocked
from team_trip_context import resolve_trip_context, trip_state
from team_trips import failure
from course_publication import COURSE_AVAILABLE


ROUTE_POLICY = dict(earlyArrival='wait-with-navigation', completion='all-cars-drop',
    emptyPickup='direct-to-join', betweenCourses='shared-only')
PHASES = ('pickup', 'waiting', 'shared', 'drop', 'done')
# A car's live progress uses only fixes its members shared within this window.
PROGRESS_FRESH_SECONDS = 60
PROGRESS_CLOCK_SKEW_SECONDS = 10
# Other cars see a coarser remaining distance than the car's own members.
PUBLIC_DISTANCE_STEP_METERS = 100


def route_contract_version(conn, trip):
    return 2 if conn.execute('SELECT 1 FROM team_trip_route_plans WHERE trip_id=%s', (trip,)).fetchone() else 1


def item_key(item):
    return item['type'], item.get('courseId'), item['ref']


def ground_meters(first, last):
    """Great-circle distance between two {lat,lng} points."""
    lat1, lat2 = math.radians(first['lat']), math.radians(last['lat'])
    half = (math.sin((lat2-lat1)/2)**2
            + math.cos(lat1)*math.cos(lat2)*math.sin(math.radians(last['lng']-first['lng'])/2)**2)
    return 2*6371008.8*math.asin(min(1.0, math.sqrt(half)))


def leg_progress(point, start, end):
    """Straight-line distance left to `end` and the projected share of the start->end leg already covered."""
    from team_trip_routes import route_position
    remaining = ground_meters(point, end)
    fraction = None
    if start is not None:
        length = route_position(end, [start, end])
        along = route_position(point, [start, end])
        if length and along is not None:
            fraction = max(0.0, min(1.0, along/length))
    return remaining, fraction


class TeamTripRouteSegments:
    def __init__(self, trips):
        self.trips = trips

    def load(self, conn, trip):
        row = conn.execute('SELECT protected FROM team_trip_route_plans WHERE trip_id=%s FOR UPDATE', (trip,)).fetchone()
        if not row:
            return None
        value = self.trips.restore('route-plan-v2', trip, row[0])
        from team_trip_plan import TeamTripPlan
        try:
            if (not isinstance(value, dict) or set(value) != {'courses', 'cars', 'released'}
                    or not isinstance(value['courses'], list) or not value['courses']
                    or not isinstance(value['cars'], dict) or type(value['released']) is not bool):
                raise ValueError()
            for car, state in value['cars'].items():
                if (not isinstance(state, dict) or set(state) != {'driverId', 'items', 'completed', 'joined', 'revision'}
                        or type(state['joined']) is not bool or type(state['revision']) is not int
                        or not 0 <= state['revision'] <= 2147483647):
                    raise ValueError()
                TeamTripPlan.order_fields(state['items'])
                TeamTripPlan.order_fields(state['completed'])
                if any(item not in state['items'] for item in state['completed']):
                    raise ValueError()
            for course in value['courses']:
                if not isinstance(course, dict) or not course.get('stops') or type(course.get('version')) is not int:
                    raise ValueError()
        except (HTTPException, KeyError, TypeError, ValueError):
            raise PrivateRecordError('Trip segmented route integrity failed') from None
        return value

    def save(self, conn, trip, value):
        conn.execute('INSERT INTO team_trip_route_plans(trip_id,protected) VALUES(%s,%s) '
            'ON CONFLICT(trip_id) DO UPDATE SET protected=excluded.protected',
            (trip, self.trips.protect('route-plan-v2', trip, value)))

    @staticmethod
    def next_item(state):
        return next((item for item in state['items'] if item not in state['completed']), None)

    @classmethod
    def phase(cls, value, car):
        state = value['cars'][car]
        if not value['released']:
            return 'waiting' if state['joined'] else 'pickup'
        item = cls.next_item(state)
        route_item = next((row for row in state['items'] if row not in state['completed'] and row['type'] != 'signal'), None)
        return 'done' if item is None else 'drop' if route_item is None or route_item['type'] == 'drop' else 'shared'

    @staticmethod
    def single_join_item(value):
        first = value['courses'][0]
        if len(first['stops']) == 1:
            return dict(type='course', courseId=first['packId'], ref=first['stops'][0]['id'])
        return None

    @classmethod
    def held_single_join_item(cls, value, car):
        item = cls.single_join_item(value)
        state = value['cars'][car]
        return item if item is not None and state['joined'] and item not in state['completed'] else None

    def complete_join_course(self, conn, trip, car, account, pack, progress):
        from team_trip_plan import TeamTripPlan
        plan = TeamTripPlan(self.trips)
        value = self.load(conn, trip)
        state = value['cars'][car]
        item = self.held_single_join_item(value, car)
        if (progress is None or item is None or item['courseId'] != pack
                or not value['released'] or self.phase(value, car) != 'shared' or self.next_item(state) != item):
            failure(409, 'TRIP_ROUTE_PROGRESS_CHANGED')
        current = plan.route_state(conn, trip, car)[1].get('routeRevision', 0)
        if (progress['routeRevision'] != current or progress['progressRevision'] != state['revision']
                or state['revision'] == 2147483647):
            failure(409, 'TRIP_ROUTE_PROGRESS_CHANGED')
        if self.project(conn, trip, car, account) is None:
            failure(409, 'TRIP_ROUTE_COURSE_UNAVAILABLE')
        state['completed'].append(item)
        state['revision'] += 1
        self.save(conn, trip, value)
        self.advance(conn, trip, value)
        self.trips.notify(conn, trip, bump=False, invalidate=False, sections=('route',))
        return value

    def prepare(self, conn, trip, owner):
        from team_trip_plan import TeamTripPlan
        plan = TeamTripPlan(self.trips)
        cars = self.trips.cars(conn, trip)
        courses = self.trips.courses(conn, trip, owner, False)
        if not cars or not courses or any(not course['stops'] for course in courses):
            failure(409, 'TRIP_ROUTE_PLAN_REQUIRED')
        if len(courses) != len(self.trips.course_links(conn, trip)):
            failure(409, 'TRIP_ROUTE_COURSE_UNAVAILABLE')
        shared = [dict(type='course', courseId=course['packId'], ref=stop['id'])
            for course in courses for stop in course['stops']]
        states = {}
        for car in sorted(cars):
            driver = cars[car]['driverId']
            if [course['packId'] for course in self.trips.courses(conn, trip, driver, False)] != [course['packId'] for course in courses]:
                failure(409, 'TRIP_ROUTE_COURSE_UNAVAILABLE')
            places = plan.places(conn, trip, car, driver, owner)
            available = {(item['kind'], item['id']): item for item in places if item['kind'] in ('pickup', 'drop')}
            old = plan.route_order(conn, trip, car, driver, owner)
            old = old if old is not None else plan.default_order(conn, trip, car, driver, owner)
            pickups = [dict(type='pickup', ref=item['ref']) for item in old if item['type'] == 'pickup']
            drops = [dict(type='drop', ref=item.get('dropRef', item['ref'])) for item in old if item['type'] == 'drop' or 'dropRef' in item]
            for kind, items in (('pickup', pickups), ('drop', drops)):
                for (place_kind, place), value in available.items():
                    if place_kind == kind and value['selectedBy'] and dict(type=kind, ref=place) not in items:
                        items.append(dict(type=kind, ref=place))
            items = pickups + shared + drops
            if len(items) > 50:
                failure(409, 'Trip route limit reached')
            plan.save_order(conn, trip, car, items, force=True)
            states[car] = dict(driverId=driver, items=items, completed=[], joined=False, revision=0)
            driver, saved = plan.route_state(conn, trip, car)
            saved['routeNext'] = items[0]
            plan.save_route_state(conn, trip, car, driver, saved)
        self.save(conn, trip, dict(courses=courses, cars=states, released=False))
        from team_trip_driving_versus import TeamTripDrivingVersus
        TeamTripDrivingVersus(self.trips).initialize(conn, trip)

    def frozen_courses(self, conn, trip, account, can_edit):
        value = self.load(conn, trip)
        if value is None:
            return None
        result = []
        for saved in value['courses']:
            adder = saved['addedById']
            if not self.trips.person(adder) or adder != account and blocked(conn, adder, account):
                continue
            row = conn.execute('SELECT 1 FROM pack_versions p '
                f'WHERE p.pack_id=%s AND p.version=%s AND {COURSE_AVAILABLE}',
                (saved['packId'], saved['version'])).fetchone()
            if not row:
                continue
            course = dict(saved, mine=adder == account, canRemove=adder == account or can_edit)
            course['completedCarIds'] = [car for (car,) in conn.execute('SELECT x.car_id FROM team_trip_car_course_completions x '
                'JOIN team_trip_cars c USING(trip_id,car_id) WHERE x.trip_id=%s AND x.pack_id=%s ORDER BY x.car_id',
                (trip, saved['packId'])) if car in value['cars'] and (account == value['cars'][car]['driverId'] or not blocked(conn, account, value['cars'][car]['driverId']))]
            result.append(course)
        return result

    def car_fix(self, conn, trip, car, account, value):
        """Freshest location a member of `car` currently shares with `account` in an active trip."""
        from team_trip_hand_raise import latest_location
        try:
            context = resolve_trip_context(self.trips.auth, conn, trip, account, states=('active',))
        except HTTPException as error:
            if error.status_code not in (403, 404, 409):
                raise
            return None
        riders = self.trips.riders(conn, trip)
        people = [value['cars'][car]['driverId']] + sorted(peer for peer, assigned in riders.items() if assigned == car)
        now = conn.execute('SELECT clock_timestamp()').fetchone()[0]
        best = None
        for peer in people:
            member = context['members'].get(peer, {})
            if (member.get('state') != 'accepted' or member.get('locationConsent') is not True
                    or peer != account and blocked(conn, account, peer)):
                continue
            fix = latest_location(self.trips.auth, conn, context['roomId'], peer)
            if (fix and -PROGRESS_CLOCK_SKEW_SECONDS <= (now-fix['capturedAt']).total_seconds() <= PROGRESS_FRESH_SECONDS
                    and (best is None or fix['capturedAt'] > best['capturedAt'])):
                best = fix
        return best

    @staticmethod
    def course_points(value):
        return {('course', course['packId'], stop['id']): stop for course in value['courses'] for stop in course['stops']
                if stop.get('lat') is not None and stop.get('lng') is not None}

    def plan_progress(self, conn, trip, car, account, value, places):
        """Own-car progress toward routePlan.next for the car's driver and riders."""
        state = value['cars'][car]
        target = self.next_item(state)
        if (target is None or self.phase(value, car) == 'waiting'
                or target == self.held_single_join_item(value, car)):
            return None
        points = self.course_points(value)
        points.update({(place['kind'], None, place['id']): place for place in places
                       if place.get('id') and place.get('lat') is not None and place.get('lng') is not None})
        end = points.get(item_key(target))
        if end is None:
            return None
        fix = self.car_fix(conn, trip, car, account, value)
        if fix is None:
            return None
        index = state['items'].index(target)
        remaining, fraction = leg_progress(fix, points.get(item_key(state['items'][index-1])) if index else None, end)
        return dict(remainingMeters=round(remaining), legFraction=None if fraction is None else round(fraction, 3))

    def status_progress(self, conn, trip, car, account, value):
        """Public progress toward the join point or the next shared course stop; private places stay hidden."""
        phase = self.phase(value, car)
        state = value['cars'][car]
        first = value['courses'][0]
        start = None
        if phase == 'pickup':
            target = dict(type='course', courseId=first['packId'], ref=first['stops'][0]['id'])
        elif phase == 'shared':
            shared = [item for item in state['items'] if item['type'] == 'course']
            held = self.held_single_join_item(value, car)
            target = next((item for item in shared if item not in state['completed'] and item != held), None)
            if target is None:
                return None
            index = shared.index(target)
            start = shared[index-1] if index else None
        else:
            return None
        points = self.course_points(value)
        end = points.get(item_key(target))
        if end is None:
            return None
        fix = self.car_fix(conn, trip, car, account, value)
        if fix is None:
            return None
        remaining, fraction = leg_progress(fix, points.get(item_key(start)) if start else None, end)
        step = PUBLIC_DISTANCE_STEP_METERS
        return dict(target=dict(target), remainingMeters=int(round(remaining/step))*step,
                    legFraction=None if fraction is None else round(fraction, 2))

    @staticmethod
    def segment_for(items, index):
        item = items[index]
        if item['type'] == 'signal':
            item = next((row for row in items[index + 1:] if row['type'] != 'signal'), {'type': 'drop'})
        return 'pickup' if item['type'] == 'pickup' else 'drop' if item['type'] == 'drop' else 'shared'

    def project(self, conn, trip, car, account):
        value = self.load(conn, trip)
        if value is None or car not in value['cars']:
            return None
        owner = self.trips.load(conn, trip)[0]
        state = value['cars'][car]
        if account != state['driverId'] and self.trips.riders(conn, trip).get(account) != car:
            return None
        visible = self.frozen_courses(conn, trip, account, False)
        if len(visible) != len(value['courses']):
            return None
        from team_trip_plan import TeamTripPlan
        visible_places = TeamTripPlan(self.trips).places(conn, trip, car, account, owner)
        places = {(item.get('kind'), item.get('id')) for item in visible_places}
        if any(item['type'] != 'course' and (item['type'], item['ref']) not in places for item in state['items']):
            return None
        first = value['courses'][0]
        stop = first['stops'][0]
        visible_cars = {identifier for identifier, member in value['cars'].items()
            if account == member['driverId'] or not blocked(conn, account, member['driverId'])}
        return dict(contractVersion=2, phase=self.phase(value, car),
            segments=[dict(segment=segment, items=[dict(item) for index, item in enumerate(state['items'])
                if self.segment_for(state['items'], index) == segment])
                for segment in ('pickup', 'shared', 'drop')],
            joinPoint=dict(courseId=first['packId'], ref=stop['id'], **{key: stop[key] for key in ('name', 'lat', 'lng')}),
            joinEtaSeconds=None, progressRevision=state['revision'], next=self.next_item(state),
            joinBarrier=dict(arrivedCarIds=[identifier for identifier, member in value['cars'].items() if member['joined'] and identifier in visible_cars],
                totalCarCount=len(value['cars']), released=value['released']),
            progress=self.plan_progress(conn, trip, car, account, value, visible_places))

    def status(self, conn, trip, car, account):
        value = self.load(conn, trip)
        if value is None or car not in value['cars']:
            return None
        driver = value['cars'][car]['driverId']
        if driver != account and blocked(conn, account, driver):
            return None
        return dict(phase=self.phase(value, car), joinEtaSeconds=None,
                    progress=self.status_progress(conn, trip, car, account, value))

    def check_shared(self, conn, trip, account, *, score=False, pack=None, final=False):
        value = self.load(conn, trip)
        if value is None:
            return
        cars = self.trips.cars(conn, trip)
        car = next((identifier for identifier, state in cars.items() if state['driverId'] == account), self.trips.riders(conn, trip).get(account))
        if car not in value['cars']:
            failure(409, 'TRIP_SIGNAL_CAR_REQUIRED' if not score else 'DRIVING_SCORE_PHASE_CONFLICT')
        phase = self.phase(value, car)
        if score:
            next_item = next((item for item in value['cars'][car]['items']
                if item['type'] == 'course' and item not in value['cars'][car]['completed']), None)
            items = [item for item in value['cars'][car]['items'] if item.get('courseId') == pack]
            completed = items and all(item in value['cars'][car]['completed'] for item in items)
            if final and completed and value['released']:
                return
            if phase != 'shared' or not next_item or next_item.get('courseId') != pack:
                failure(409, 'DRIVING_SCORE_PHASE_CONFLICT')
        elif phase == 'done':
            failure(409, 'TRIP_SIGNAL_ROUTE_FINISHED')

    def arrive(self, conn, trip, car, account, data):
        from team_trip_plan import TeamTripPlan
        plan = TeamTripPlan(self.trips)
        trip_status = resolve_trip_context(self.trips.auth, conn, trip, account, states=None)
        plan.context(conn, trip, car, account, driver=True, mutable=False)
        value = self.load(conn, trip)
        if value is None or car not in value['cars']:
            failure(409, 'TRIP_ROUTE_CONTRACT_REQUIRED')
        if (not isinstance(data, dict) or not {'routeRevision', 'progressRevision', 'item'} <= data.keys()
                or data.keys() - {'routeRevision', 'progressRevision', 'item', 'singleJoinCompletion'}
                or 'singleJoinCompletion' in data and data['singleJoinCompletion'] != 'explicit-v1'):
            failure(400, 'TRIP_ROUTE_PROGRESS_INVALID')
        if any(type(data[key]) is not int or not 0 <= data[key] <= 2147483647 for key in ('routeRevision', 'progressRevision')):
            failure(400, 'TRIP_ROUTE_PROGRESS_INVALID')
        plan.order_fields([data['item']])
        state = value['cars'][car]
        if self.project(conn, trip, car, account) is None:
            failure(409, 'TRIP_ROUTE_COURSE_UNAVAILABLE')
        if 'singleJoinCompletion' in data and data['item'] != self.single_join_item(value):
            failure(400, 'TRIP_ROUTE_PROGRESS_INVALID')
        if data['item'] in state['completed'] or data['item'] == self.held_single_join_item(value, car):
            return dict(status='unchanged', routePlan=self.project(conn, trip, car, account))
        if trip_status['state'] != 'active':
            failure(409, 'TRIP_STATE_CONFLICT')
        current = plan.route_state(conn, trip, car)[1].get('routeRevision', 0)
        if current != data['routeRevision'] or state['revision'] != data['progressRevision'] or self.next_item(state) != data['item'] or self.phase(value, car) == 'waiting' and data['item']['type'] != 'signal':
            failure(409, 'TRIP_ROUTE_PROGRESS_CHANGED')
        if state['revision'] == 2147483647:
            failure(409, 'TRIP_ROUTE_PROGRESS_CHANGED')
        if data.get('singleJoinCompletion') != 'explicit-v1':
            state['completed'].append(dict(data['item']))
        state['revision'] += 1
        first = value['courses'][0]
        join = dict(type='course', courseId=first['packId'], ref=first['stops'][0]['id'])
        if data['item'] == join:
            state['joined'] = True
        if not value['released'] and value['cars'] and all(member['joined'] for member in value['cars'].values()):
            value['released'] = True
        self.save(conn, trip, value)
        self.advance(conn, trip, value)
        self.trips.notify(conn, trip, bump=False, invalidate=False, sections=('route',))
        return dict(status='updated', routePlan=self.project(conn, trip, car, account))

    def advance(self, conn, trip, value):
        from team_trip_plan import TeamTripPlan
        plan = TeamTripPlan(self.trips)
        for car in sorted(value['cars']):
            state = value['cars'][car]
            driver, saved = plan.route_state(conn, trip, car)
            guided = saved.get('routeNext')
            # Keep the driver's current guidance while it still points ahead;
            # otherwise the car heads to the next place awaiting arrival.
            if guided is None or guided in state['completed'] or guided not in state['items']:
                target = self.next_item(state)
                if 'routeNext' not in saved or guided != target:
                    saved['routeNext'] = target
                    plan.save_route_state(conn, trip, car, driver, saved)
            if value['released']:
                for course in value['courses']:
                    items = [item for item in state['items'] if item.get('courseId') == course['packId']]
                    if items and all(item in state['completed'] for item in items):
                        conn.execute('INSERT INTO team_trip_car_course_completions(trip_id,car_id,pack_id) VALUES(%s,%s,%s) ON CONFLICT DO NOTHING',
                            (trip, car, course['packId']))
        if value['cars'] and all(self.phase(value, car) == 'done' for car in value['cars']):
            self.trips.close_active_trip(conn, trip)
        from team_trip_driving_versus import TeamTripDrivingVersus
        TeamTripDrivingVersus(self.trips).refresh(conn, trip)

    def withdraw_car(self, conn, trip, car, *, defer_reconcile=False):
        value = self.load(conn, trip)
        if value is None or car not in value['cars']:
            return
        del value['cars'][car]
        if value['cars'] and all(state['joined'] for state in value['cars'].values()):
            value['released'] = True
        self.save(conn, trip, value)
        if not defer_reconcile:
            self.advance(conn, trip, value)

    def reconcile(self, conn, trip):
        value = self.load(conn, trip)
        if value is not None:
            self.advance(conn, trip, value)

    def add_signal(self, conn, trip, car, signal):
        value = self.load(conn, trip)
        if value is None:
            return
        if car not in value['cars'] or self.phase(value, car) == 'done':
            failure(409, 'TRIP_SIGNAL_ROUTE_FINISHED')
        state = value['cars'][car]
        item = dict(type='signal', ref=signal)
        if item not in state['items']:
            if state['revision'] == 2147483647:
                failure(409, 'TRIP_ROUTE_PROGRESS_CHANGED')
            target = self.next_item(state)
            at = state['items'].index(target) if target is not None else len(state['items'])
            state['items'].insert(at, item)
            state['revision'] += 1
            self.save(conn, trip, value)

    def lock_active(self, conn, trip, error='TRIP_ROUTE_PLAN_LOCKED'):
        if route_contract_version(conn, trip) == 2 and trip_state(conn, trip)['state'] == 'active':
            failure(409, error)
