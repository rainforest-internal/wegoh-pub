from fractions import Fraction

from fastapi import Request, Response
import psycopg
from psycopg.rows import dict_row

from native_functional_identity import resolve_current_device
from native_functional_policy import FunctionalError, stored_functional_payload
from native_principal import is_native_principal
from private_records import PrivateRecordError
from team_friends import blocked
from team_trip_context import resolve_trip_context
from team_trips import failure


KIND = 'safe-driving-versus'
DISCLOSURE_VERSION = 4
PURPOSE = 'driving-score:report'
DEVICE_PROOF = {'grantId', 'deviceId'}
LEGACY_PROOF = DEVICE_PROOF | {'functionalRevision', 'functionalDisclosureVersion', 'functionalDisclosureSha256'}


def valid_proof(report, fields):
    if set(report) not in (fields | DEVICE_PROOF, fields | LEGACY_PROOF):
        return False
    if any(not isinstance(report[key], str) or not report[key] for key in DEVICE_PROOF):
        return False
    return 'functionalRevision' not in report or (report['functionalDisclosureVersion'] in (4, 5)
        and type(report['functionalRevision']) is int and report['functionalRevision'] >= 1
        and isinstance(report['functionalDisclosureSha256'], str))


def average(scores):
    return Fraction(sum(scores), len(scores)) if scores else None


class TeamTripDrivingVersus:
    def __init__(self, trips):
        self.trips = trips

    def load(self, conn, trip):
        row = conn.execute('SELECT protected FROM team_trip_driving_versus WHERE trip_id=%s FOR UPDATE', (trip,)).fetchone()
        if not row:
            return None
        value = self.trips.restore('driving-versus', trip, row[0])
        try:
            if (not isinstance(value, dict) or set(value) - {'tripReports'} != {'cars', 'courses', 'reports', 'withdrawn', 'result', 'finalCarIds'}
                    or not isinstance(value['cars'], dict) or not isinstance(value['courses'], list)
                    or not isinstance(value['reports'], dict) or not isinstance(value['withdrawn'], list)
                    or not set(value['withdrawn']) <= set(value['cars'])
                    or not isinstance(value['finalCarIds'], list) or not set(value['finalCarIds']) <= set(value['cars'])):
                raise ValueError()
            for car, data in value['cars'].items():
                if not isinstance(data, dict) or set(data) != {'driverId', 'name'}:
                    raise ValueError()
            for course in value['courses']:
                if (not isinstance(course, dict) or set(course) != {'packId', 'version'}
                        or type(course['version']) is not int or course['version'] < 1):
                    raise ValueError()
            for car, courses in value['reports'].items():
                if car not in value['cars'] or not isinstance(courses, dict):
                    raise ValueError()
                for pack, report in courses.items():
                    if (not isinstance(report, dict) or not valid_proof(report, {'score', 'measurable'})
                            or type(report['measurable']) is not bool
                            or (report['measurable'] and (type(report['score']) is not int or not 0 <= report['score'] <= 100))
                            or (not report['measurable'] and report['score'] is not None)
                            or pack not in {item['packId'] for item in value['courses']}):
                        raise ValueError()
            from team_trip_driving_scores import driving_score, FIELDS
            from fastapi import HTTPException
            totals = value.get('tripReports', {})
            if not isinstance(totals, dict) or not set(totals) <= set(value['cars']):
                raise ValueError()
            for report in totals.values():
                if not isinstance(report, dict) or not valid_proof(report, FIELDS):
                    raise ValueError()
                try:
                    driving_score({key: report[key] for key in FIELDS})
                except HTTPException:
                    raise ValueError() from None
            if value['result'] is not None:
                result = value['result']
                if (not isinstance(result, dict) or set(result) != {'state', 'reason', 'winnerCarIds', 'tied'}
                        or result['state'] not in ('final', 'unavailable') or type(result['tied']) is not bool
                        or not isinstance(result['winnerCarIds'], list)
                        or not set(result['winnerCarIds']) <= set(value['cars'])):
                    raise ValueError()
        except (KeyError, TypeError, ValueError):
            raise PrivateRecordError('Trip driving versus integrity failed') from None
        return value

    def save(self, conn, trip, value):
        conn.execute('INSERT INTO team_trip_driving_versus(trip_id,protected) VALUES(%s,%s) '
            'ON CONFLICT(trip_id) DO UPDATE SET protected=excluded.protected',
            (trip, self.trips.protect('driving-versus', trip, value)))

    def initialize(self, conn, trip):
        from team_trip_route_segments import TeamTripRouteSegments
        route = TeamTripRouteSegments(self.trips).load(conn, trip)
        if route is None or self.load(conn, trip) is not None:
            return
        cars = self.trips.cars(conn, trip)
        self.save(conn, trip, dict(cars={car: dict(driverId=cars[car]['driverId'], name=cars[car]['name'])
            for car in route['cars']}, courses=[dict(packId=item['packId'], version=item['version'])
            for item in route['courses']], reports={}, withdrawn=[], result=None, finalCarIds=[]))

    def permission(self, conn, driver, device, *, grant=None):
        try:
            current = resolve_current_device(self.trips.auth, conn, driver, device)
            if grant is not None and current.grant_id != grant:
                return None
            proof = dict(grantId=current.grant_id, deviceId=device)
            with conn.cursor(row_factory=dict_row) as cursor:
                row = cursor.execute('SELECT * FROM native_functional_authorizations WHERE grant_id=%s FOR SHARE',
                    (current.grant_id,)).fetchone()
            if row:
                metadata = stored_functional_payload(row)
                if metadata['functionalDisclosureVersion'] in (4, 5):
                    proof.update(functionalRevision=current.functional_revision,
                        functionalDisclosureVersion=metadata['functionalDisclosureVersion'],
                        functionalDisclosureSha256=metadata['functionalDisclosureSha256'])
            return proof
        except FunctionalError as error:
            if error.status in (401, 403, 404):
                return None
            raise

    def record_report(self, conn, trip, car, pack, account, score, principal):
        if not score['final'] or not is_native_principal(principal) or principal['id'] != account:
            return
        value = self.load(conn, trip)
        if (value is None or car not in value['cars'] or car in value['withdrawn']
                or value['cars'][car]['driverId'] != account):
            return
        proof = self.permission(conn, account, principal['deviceId'], grant=principal['grantId'])
        if proof is None:
            return
        if pack not in {item['packId'] for item in value['courses']}:
            return
        report = dict(proof, score=score['score'], measurable=score['measurable'])
        previous = value['reports'].get(car, {}).get(pack)
        if previous == report:
            return
        if previous and any(previous[key] != report[key] for key in ('score', 'measurable')):
            failure(409, 'DRIVING_SCORE_CONFLICT')
        value['reports'].setdefault(car, {})[pack] = report
        self.save(conn, trip, value)
        self.refresh(conn, trip)
        self.trips.notify(conn, trip, bump=False, invalidate=False, sections=('route',))

    def proof_current(self, conn, car, report, cache=None):
        key = (car['driverId'], report['deviceId'], report['grantId'])
        if cache is None:
            cache = {}
        if key not in cache:
            cache[key] = self.permission(conn, key[0], key[1], grant=key[2]) is not None
        return cache[key]

    def sharing_current(self, conn, driver):
        for (device,) in conn.execute("SELECT DISTINCT device_id FROM native_v2_grants WHERE account_id=%s "
                "AND state='TOKEN_ISSUED' ORDER BY device_id", (driver,)):
            if self.permission(conn, driver, device) is not None:
                return True
        return False

    @staticmethod
    def result(state, reason=None, winners=()):
        return dict(state=state, reason=reason, winnerCarIds=list(winners), tied=len(winners) > 1)

    def refresh(self, conn, trip):
        from team_trip_route_segments import TeamTripRouteSegments
        value = self.load(conn, trip)
        if value is None:
            return None
        route = TeamTripRouteSegments(self.trips).load(conn, trip)
        present = self.trips.cars(conn, trip)
        if route is None:
            raise PrivateRecordError('Trip driving versus route unavailable')
        members = self.trips.members(conn, trip)
        withdrawn = sorted(set(value['withdrawn']) | {car for car, data in value['cars'].items()
            if car not in present or car not in route['cars'] or members.get(data['driverId'], {}).get('state') != 'accepted'})
        changed = withdrawn != value['withdrawn']
        value['withdrawn'] = withdrawn
        if value['result'] is None:
            proof_cache = {}
            for car in withdrawn:
                value['reports'].pop(car, None)
            active = {car: data for car, data in value['cars'].items() if car not in withdrawn}
            context = resolve_trip_context(self.trips.auth, conn, trip, self.trips.load(conn, trip)[0], states=None)
            finished = route['released'] and all(TeamTripRouteSegments.phase(route, car) in ('drop', 'done') for car in active)
            if len(active) < 2:
                value['result'] = self.result('unavailable', 'insufficient-cars')
            elif context['state'] in ('completed', 'cancelled') and not finished:
                value['result'] = self.result('unavailable', 'shared-incomplete')
            elif finished:
                ready = all(course['packId'] in value['reports'].get(car, {}) and
                    self.proof_current(conn, data, value['reports'][car][course['packId']], proof_cache)
                    for car, data in active.items() for course in value['courses'])
                if ready:
                    averages = {car: average([value['reports'][car][course['packId']]['score']
                        for course in value['courses'] if value['reports'][car][course['packId']]['measurable']]) for car in active}
                    eligible = {car: score for car, score in averages.items() if score is not None}
                    if len(eligible) < 2:
                        value['result'] = self.result('unavailable', 'insufficient-measurements')
                    else:
                        best = max(eligible.values())
                        value['result'] = self.result('final', winners=sorted(car for car, score in eligible.items() if score == best))
            if value['result'] is not None:
                value['finalCarIds'] = sorted(active)
                changed = True
        if changed:
            self.save(conn, trip, value)
        return value

    def view(self, conn, trip, account):
        context = resolve_trip_context(self.trips.auth, conn, trip, account, states=None)
        current_cars = self.trips.cars(conn, trip)
        car = next((identifier for identifier, data in current_cars.items() if data['driverId'] == account),
            self.trips.riders(conn, trip).get(account))
        if car is None:
            failure(404, 'Driving versus unavailable')
        driver = current_cars[car]['driverId']
        if driver != account and blocked(conn, account, driver):
            failure(404, 'Driving versus unavailable')
        value = self.refresh(conn, trip)
        empty = dict(kind=KIND, automatic=True, cars=[], **self.result('unavailable', 'contract-unavailable'))
        if value is None:
            return empty
        if car not in value['cars'] or car in value['withdrawn']:
            failure(404, 'Driving versus unavailable')
        available = {(course['packId'], course['version']) for course in self.trips.courses(conn, trip, account, False)}
        courses_hidden = any((course['packId'], course['version']) not in available for course in value['courses'])
        visible, restricted, proof_cache = [], courses_hidden, {}
        reasons = {'course-unavailable'} if courses_hidden else set()
        for identifier, data in value['cars'].items():
            driver = data['driverId']
            contributes = identifier not in value['withdrawn'] if value['result'] is None else identifier in value['finalCarIds']
            if (not self.trips.person(driver) or driver != account and blocked(conn, account, driver)
                    or context['members'].get(driver, {}).get('state') != 'accepted'):
                restricted |= contributes
                if contributes:
                    reasons.add('participant-unavailable')
                continue
            reports = value['reports'].get(identifier, {})
            withdrawn = identifier in value['withdrawn']
            restricted |= withdrawn and identifier in value['finalCarIds'] and value['result'] is not None and value['result']['state'] == 'final'
            if withdrawn and identifier in value['finalCarIds'] and value['result'] is not None and value['result']['state'] == 'final':
                reasons.add('participant-unavailable')
            sharing_available = withdrawn or self.sharing_current(conn, driver)
            if not sharing_available:
                reasons.add('vehicle-connection-required')
            courses, scores, sharing = [], [], courses_hidden
            for course in value['courses']:
                if (course['packId'], course['version']) not in available:
                    continue
                report = reports.get(course['packId'])
                if withdrawn:
                    state, score = 'pending', None
                elif not sharing_available or report is not None and not self.proof_current(conn, data, report, proof_cache):
                    state, score, sharing = 'sharing-unavailable', None, True
                    reasons.add('vehicle-connection-required' if not sharing_available else 'report-device-changed')
                elif report is None:
                    state, score = 'pending', None
                else:
                    state, score = ('final', report['score']) if report['measurable'] else ('unavailable', None)
                    if report['measurable']:
                        scores.append(score)
                courses.append(dict(course, state=state, score=score))
            ready = all(item['state'] in ('final', 'unavailable') for item in courses)
            state = 'withdrawn' if withdrawn else 'sharing-unavailable' if sharing else 'ready' if ready and scores else 'unavailable' if ready else 'pending'
            restricted |= sharing
            mean = average(scores)
            visible.append(dict(carId=identifier, name=data['name'], participating=True, state=state,
                averageScore=round(float(mean), 2) if mean is not None and not sharing else None,
                measuredCourseCount=len(scores), courses=courses))
        result = value['result'] or self.result('pending', 'final-reports-pending')
        if restricted:
            result = self.result('unavailable', next(iter(reasons)) if len(reasons) == 1 else 'vehicle-authority-unavailable')
        return dict(kind=KIND, automatic=True, cars=visible, **result)


def install(router, trips, actor, transaction):
    @router.get('/v1/native/trips/{id}/driving-versus')
    @router.get('/v1/iphone/trips/{id}/driving-versus', include_in_schema=False)
    def read(id: str, request: Request, response: Response):
        who = actor(request, response, native=True)
        if request.query_params:
            failure(400, 'Invalid driving versus fields')
        with psycopg.connect(trips.dsn) as conn:
            transaction(request, conn, who)
            return TeamTripDrivingVersus(trips).view(conn, id, who)
