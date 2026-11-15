from fastapi import HTTPException

from private_records import PrivateRecordError
from team_trip_context import resolve_trip_context
from team_trips import failure


FIELDS = {'score', 'accelerations', 'brakings', 'measurable', 'final'}
PURPOSE = 'driving-score:report'
MAX_COUNT = 2147483647


def driving_score(value, *, final=None):
    if not isinstance(value, dict) or set(value) != FIELDS:
        failure(400, 'DRIVING_SCORE_INVALID')
    if (type(value['measurable']) is not bool or type(value['final']) is not bool
            or final is not None and value['final'] != final
            or any(type(value[key]) is not int or not 0 <= value[key] <= MAX_COUNT
                   for key in ('accelerations', 'brakings'))):
        failure(400, 'DRIVING_SCORE_INVALID')
    if value['measurable']:
        if (type(value['score']) is not int or not 0 <= value['score'] <= 100
                or value['score'] != max(0, 100 - 5 * (value['accelerations'] + value['brakings']))):
            failure(400, 'DRIVING_SCORE_INVALID')
    elif value['score'] is not None:
        failure(400, 'DRIVING_SCORE_INVALID')
    return dict(value)


class TeamTripDrivingScores:
    def __init__(self, trips):
        self.trips = trips

    def domain(self, car, pack, version):
        return 'driving-score:' + car + ':' + pack + ':' + str(version)

    def restore(self, trip, car, pack, version, raw):
        value = self.trips.restore(self.domain(car, pack, version), trip, raw)
        try:
            return driving_score(value)
        except HTTPException:
            raise PrivateRecordError('Trip driving score integrity failed') from None

    def write(self, conn, trip, car, pack, account, value, *, final=False, notify=True):
        from team_trip_plan import TeamTripPlan
        value = driving_score(value, final=final)
        plan = TeamTripPlan(self.trips)
        state = resolve_trip_context(self.trips.auth, conn, trip, account, states=None)['state']
        plan.context(conn, trip, car, account, driver=True, mutable=False)
        from team_trip_route_segments import TeamTripRouteSegments, route_contract_version
        segmented = route_contract_version(conn, trip) == 2
        if state != 'active' and not (segmented and final and state == 'completed'):
            failure(409, 'TRIP_STATE_CONFLICT')
        TeamTripRouteSegments(self.trips).check_shared(conn, trip, account, score=True, pack=pack, final=final)
        courses = self.trips.courses(conn, trip, account, False)
        course = next((item for item in courses if item['packId'] == pack), None)
        if course is None:
            failure(404, 'Course unavailable')
        version = course['version']
        plan.route_state(conn, trip, car)
        if not final and conn.execute('SELECT 1 FROM team_trip_car_course_completions '
                'WHERE trip_id=%s AND car_id=%s AND pack_id=%s', (trip, car, pack)).fetchone():
            failure(409, 'DRIVING_SCORE_CONFLICT')
        row = conn.execute('SELECT protected FROM team_trip_car_driving_scores '
            'WHERE trip_id=%s AND car_id=%s AND pack_id=%s AND version=%s FOR UPDATE',
            (trip, car, pack, version)).fetchone()
        if row:
            previous = self.restore(trip, car, pack, version, row[0])
            if previous == value:
                return dict(status='unchanged')
            if (previous['final'] or any(value[key] < previous[key] for key in ('accelerations', 'brakings'))):
                failure(409, 'DRIVING_SCORE_CONFLICT')
        conn.execute('INSERT INTO team_trip_car_driving_scores(trip_id,car_id,pack_id,version,protected) '
            'VALUES(%s,%s,%s,%s,%s) ON CONFLICT(trip_id,car_id,pack_id,version) '
            'DO UPDATE SET protected=EXCLUDED.protected',
            (trip, car, pack, version, self.trips.protect(self.domain(car, pack, version), trip, value)))
        if notify:
            self.trips.notify(conn, trip, bump=False, invalidate=False, sections=('route',))
        return dict(status='updated')

    def for_course(self, conn, trip, account, pack, version):
        cars = self.trips.cars(conn, trip)
        car = next((identifier for identifier, item in cars.items() if item['driverId'] == account),
                   self.trips.riders(conn, trip).get(account))
        if car is None:
            return []
        from team_friends import blocked
        driver = cars[car]['driverId']
        if driver != account and (blocked(conn, driver, account) or not self.trips.person(driver)):
            return []
        row = conn.execute('SELECT protected FROM team_trip_car_driving_scores '
            'WHERE trip_id=%s AND car_id=%s AND pack_id=%s AND version=%s',
            (trip, car, pack, version)).fetchone()
        return [dict(carId=car, **self.restore(trip, car, pack, version, row[0]))] if row else []
