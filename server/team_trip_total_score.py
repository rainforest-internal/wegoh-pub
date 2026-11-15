from fastapi import Request, Response
import psycopg

from native_principal import is_native_principal
from team_friends import blocked
from team_trip_context import resolve_trip_context
from team_trip_driving_scores import driving_score, FIELDS
from team_trip_driving_versus import TeamTripDrivingVersus, KIND
from team_trip_plan import TeamTripPlan
from team_trip_route_segments import TeamTripRouteSegments
from team_trips import failure


class TeamTripTotalScore:
    def __init__(self, trips):
        self.trips = trips
        self.store = TeamTripDrivingVersus(trips)

    def write(self, conn, trip, car, account, value, principal):
        score = driving_score(value)
        context = resolve_trip_context(self.trips.auth, conn, trip, account, states=None)
        TeamTripPlan(self.trips).context(conn, trip, car, account, driver=True, mutable=False)
        if not is_native_principal(principal) or principal['id'] != account:
            failure(403, 'Native driver device required')
        proof = self.store.permission(conn, account, principal['deviceId'], grant=principal['grantId'])
        if proof is None:
            failure(403, 'DRIVING_SCORE_DEVICE_REQUIRED')
        route = TeamTripRouteSegments(self.trips).load(conn, trip)
        data = self.store.load(conn, trip)
        if route is None or data is None or car not in route['cars'] or car not in data['cars']:
            failure(409, 'TRIP_ROUTE_CONTRACT_REQUIRED')
        if data['cars'][car]['driverId'] != account or car in data['withdrawn']:
            failure(404, 'Driving score unavailable')
        done = TeamTripRouteSegments.phase(route, car) == 'done'
        if context['state'] not in ('active', 'completed') or context['state'] == 'completed' and not score['final']:
            failure(409, 'TRIP_STATE_CONFLICT')
        if score['final'] and not (done or context['state'] == 'completed'):
            failure(409, 'DRIVING_SCORE_PHASE_CONFLICT')
        reports = data.setdefault('tripReports', {})
        previous = reports.get(car)
        report = dict(score, **proof)
        if previous and all(previous.get(key) == report.get(key) for key in FIELDS | {'grantId', 'deviceId'}):
            return dict(status='unchanged')
        if previous and (previous['final'] or any(score[key] < previous[key] for key in ('accelerations', 'brakings'))
                         or previous['measurable'] and not score['measurable']):
            failure(409, 'DRIVING_SCORE_CONFLICT')
        reports[car] = report
        self.store.save(conn, trip, data)
        self.trips.notify(conn, trip, bump=False, invalidate=False, sections=('route',))
        return dict(status='updated')

    def view(self, conn, trip, account):
        context = resolve_trip_context(self.trips.auth, conn, trip, account, states=None)
        current = self.trips.cars(conn, trip)
        own = next((key for key, car in current.items() if car['driverId'] == account), self.trips.riders(conn, trip).get(account))
        if own not in current or current[own]['driverId'] != account and blocked(conn, account, current[own]['driverId']):
            failure(404, 'Driving score unavailable')
        data = self.store.load(conn, trip)
        if data is None or own not in data['cars'] or own in data['withdrawn']:
            failure(404, 'Driving score unavailable')
        reports = data.get('tripReports', {})
        cars, restricted, proof_cache, reasons = [], False, {}, set()
        for key, car in data['cars'].items():
            driver = car['driverId']
            if not self.trips.person(driver) or driver != account and blocked(conn, account, driver) or context['members'].get(driver, {}).get('state') != 'accepted':
                restricted = True
                reasons.add('participant-unavailable')
                continue
            withdrawn = key not in current or key in data['withdrawn']
            report = reports.get(key)
            connected = self.store.sharing_current(conn, driver)
            current_report = report is None or self.store.proof_current(conn, car, report, proof_cache)
            sharing = connected and current_report
            if not sharing:
                reasons.add('vehicle-connection-required' if not connected else 'report-device-changed')
            restricted |= not sharing
            score = report['score'] if report and sharing and not withdrawn else None
            state = 'withdrawn' if withdrawn else 'sharing-unavailable' if not sharing else 'ready' if score is not None else 'unavailable' if report and report['final'] else 'pending'
            cars.append(dict(carId=key, name=car['name'], participating=True, state=state, totalScore=score,
                final=bool(report and report['final'] and sharing and not withdrawn), averageScore=None, measuredCourseCount=0, courses=[]))
        active = [car for car in cars if car['state'] != 'withdrawn']
        result = self.store.result('pending', 'trip-reports-pending')
        if restricted:
            result = self.store.result('unavailable', next(iter(reasons)) if len(reasons) == 1 else 'vehicle-authority-unavailable')
        elif context['state'] == 'cancelled':
            result = self.store.result('unavailable', 'trip-cancelled')
        elif active and all(car['final'] for car in active):
            measured = [car for car in active if car['totalScore'] is not None]
            if len(measured) < 2:
                result = self.store.result('unavailable', 'insufficient-measurements')
            else:
                best = max(car['totalScore'] for car in measured)
                result = self.store.result('final', winners=sorted(car['carId'] for car in measured if car['totalScore'] == best))
        return dict(kind=KIND, automatic=True, scope='trip', cars=cars, **result)


def install(router, trips, actor, transaction, body):
    @router.get('/v1/native/trips/{id}/driving-score')
    @router.get('/v1/iphone/trips/{id}/driving-score', include_in_schema=False)
    def read(id: str, request: Request, response: Response):
        who = actor(request, response, native=True)
        if request.query_params:
            failure(400, 'Invalid driving score fields')
        with psycopg.connect(trips.dsn) as conn:
            transaction(request, conn, who)
            return TeamTripTotalScore(trips).view(conn, id, who)

    @router.put('/v1/native/trips/{id}/cars/{carId}/driving-score')
    async def write(id: str, carId: str, request: Request, response: Response):
        who = actor(request, response, mutate=True, native=True)
        data = await body(request, ('drivingScore',))
        with psycopg.connect(trips.dsn) as conn:
            transaction(request, conn, who, mutate=True)
            return TeamTripTotalScore(trips).write(conn, id, carId, who, data['drivingScore'], request.state.device_identity)
