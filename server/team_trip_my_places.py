import secrets

from private_records import PrivateRecordError
from team_trip_context import trip_state
from team_trip_plan import CAR_PLACE_LIMIT, TeamTripPlan, named_place
from team_trips import IDENT, failure


def route_contract_version(conn, trip):
    from team_trip_route_segments import route_contract_version as current_version
    return current_version(conn, trip)


def my_place_fields(data):
    if (not isinstance(data, dict) or set(data) != {'revision', 'pickup', 'drop', 'dropAtPickup'}
            or type(data['revision']) is not int or not 1 <= data['revision'] <= 2147483647
            or type(data['dropAtPickup']) is not bool
            or data['dropAtPickup'] and (data['pickup'] is None or data['drop'] is not None)):
        failure(400, 'TRIP_PLACE_SELECTION_INVALID')
    value = dict(data)
    for kind in ('pickup', 'drop'):
        choice = data[kind]
        if choice is None:
            continue
        if not isinstance(choice, dict):
            failure(400, 'TRIP_PLACE_SELECTION_INVALID')
        if set(choice) == {'placeId'}:
            if not isinstance(choice['placeId'], str) or not IDENT.fullmatch(choice['placeId']):
                failure(400, 'TRIP_PLACE_SELECTION_INVALID')
            value[kind] = dict(choice)
        else:
            value[kind] = named_place(choice, 'TRIP_PLACE_SELECTION_INVALID')
    return value


class TeamTripMyPlaces:
    def __init__(self, trips):
        self.trips = trips
        self.plan = TeamTripPlan(trips)

    def target(self, kind, choice, places, current, account):
        if choice is None:
            return None
        if 'placeId' in choice:
            place = places.get(choice['placeId'])
            if place is None or place['kind'] != kind:
                failure(404, 'Car place unavailable')
            return dict(place)
        candidates = list(places.values())
        selected = places.get(current.get(kind))
        if selected is not None:
            candidates.insert(0, selected)
        for place in candidates:
            if place['kind'] == kind and all(place[key] == choice[key] for key in ('name', 'lat', 'lng')):
                return dict(place)
        return dict(choice, id=None, kind=kind, addedBy=account)

    @staticmethod
    def same_selection(current, kind, target):
        if target is None:
            return current.get(kind) is None
        return target['id'] is not None and current.get(kind) == target['id']

    @staticmethod
    def response(state, route_revision, pickup, drop, status):
        same_place = pickup is not None and drop is not None and all(
            pickup[key] == drop[key] for key in ('lat', 'lng'))
        return dict(revision=state['revision'], routeRevision=route_revision,
            pickupPlaceId=pickup['id'] if pickup else None, dropPlaceId=drop['id'] if drop else None,
            dropAtPickup=same_place, status=status)

    def save(self, conn, trip, car, account, data):
        state = trip_state(conn, trip)
        (owner, _, _), _ = self.plan.context(conn, trip, car, account, rider=True)
        if route_contract_version(conn, trip) == 2 and state['state'] != 'planned':
            failure(409, 'TRIP_ROUTE_PLAN_LOCKED')
        value = my_place_fields(data)
        driver, route = self.plan.route_state(conn, trip, car)
        route_revision = route.get('routeRevision', 0)
        places = {place['id']: place for place in self.plan.places(conn, trip, car, account, owner)
                  if place['kind'] in ('pickup', 'drop')}
        current = dict(conn.execute('SELECT kind,place_id FROM team_trip_car_place_selections '
            'WHERE trip_id=%s AND car_id=%s AND account_id=%s FOR UPDATE', (trip, car, account)))
        pickup = self.target('pickup', value['pickup'], places, current, account)
        drop_choice = {key: pickup[key] for key in ('name', 'lat', 'lng')} if value['dropAtPickup'] else value['drop']
        drop = self.target('drop', drop_choice, places, current, account)
        desired = {'pickup': pickup, 'drop': drop}
        if all(self.same_selection(current, kind, target) for kind, target in desired.items()):
            return self.response(state, route_revision, pickup, drop, 'unchanged')
        if value['revision'] != state['revision']:
            failure(409, 'TRIP_PLACE_SELECTION_CHANGED')
        if route_revision >= 2147483647:
            failure(409, 'Route revision limit reached')
        for kind, target in desired.items():
            if target is not None and target['id'] is None:
                count = conn.execute('SELECT count(*) FROM team_trip_car_places WHERE trip_id=%s AND car_id=%s AND kind=%s',
                    (trip, car, kind)).fetchone()[0]
                if count >= CAR_PLACE_LIMIT:
                    failure(409, 'Car place limit reached')
        for kind, target in desired.items():
            if target is not None and target['id'] is None:
                target['id'] = secrets.token_hex(16)
                payload = {key: target[key] for key in ('name', 'lat', 'lng')}
                conn.execute('INSERT INTO team_trip_car_places(trip_id,car_id,place_id,kind,added_by,protected) '
                    'VALUES(%s,%s,%s,%s,%s,%s)', (trip, car, target['id'], kind, account,
                    self.trips.protect('car-place:' + car + ':' + target['id'], trip, payload)))
            if target is None:
                conn.execute('DELETE FROM team_trip_car_place_selections WHERE trip_id=%s AND car_id=%s AND account_id=%s AND kind=%s',
                    (trip, car, account, kind))
            elif current.get(kind) != target['id']:
                conn.execute('INSERT INTO team_trip_car_place_selections(trip_id,car_id,place_id,account_id,kind) '
                    'VALUES(%s,%s,%s,%s,%s) ON CONFLICT(trip_id,car_id,account_id,kind) '
                    'DO UPDATE SET place_id=EXCLUDED.place_id', (trip, car, target['id'], account, kind))
        previous = places.get(current.get('pickup'))
        if previous is not None and pickup is not None and previous['id'] != pickup['id']:
            self.plan.replace_pickup(conn, trip, car, driver, (previous['id'], previous['addedBy']),
                (pickup['id'], pickup['addedBy']))
        driver, updated_route = self.plan.route_state(conn, trip, car)
        updated_revision = updated_route.get('routeRevision', 0)
        if updated_revision == route_revision:
            updated_route['routeRevision'] = route_revision + 1
            self.plan.save_route_state(conn, trip, car, driver, updated_route)
            updated_revision += 1
        if updated_revision != route_revision + 1:
            raise PrivateRecordError('Trip route revision integrity failed')
        self.trips.notify(conn, trip, sections=('route', 'detail'))
        return self.response(trip_state(conn, trip), updated_revision, pickup, drop, 'updated')
