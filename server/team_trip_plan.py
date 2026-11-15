import hashlib
import json
import math
import re
import secrets
from datetime import date

from fastapi import HTTPException
from private_records import PrivateRecordError
from studio import validate_pack
from team_device_commands import iso
from team_friends import ACCOUNT, blocked
from team_trip_context import resolve_trip_context, trip_state
from team_trips import IDENT, PACK, failure, trip_text


WAYPOINT_ID = re.compile(r'trip-waypoint-[a-f0-9]{32}')
WAYPOINT_LIMIT = 3
ROUTE_LIMIT = 50
CAR_PLACE_LIMIT = 10


def trip_dates(data, current=None):
    value = dict(current or dict(startDate=None, endDate=None))
    for key in ('startDate', 'endDate'):
        if key not in data:
            continue
        raw = data[key]
        if raw is not None:
            try:
                if type(raw) is not str or len(raw) != 10 or date.fromisoformat(raw).isoformat() != raw:
                    raise ValueError()
            except (TypeError, ValueError):
                failure(400, 'Invalid trip dates')
        value[key] = raw
    if value['startDate'] is not None and value['endDate'] is not None:
        if not 0 <= (date.fromisoformat(value['endDate']) - date.fromisoformat(value['startDate'])).days <= 30:
            failure(400, 'Invalid trip dates')
    return value


def place_fields(data):
    if (not isinstance(data, dict) or set(data) != {'kind', 'name', 'lat', 'lng'}
            or type(data['kind']) is not str or data['kind'] not in ('pickup', 'drop')):
        failure(400, 'Invalid car place')
    return dict(kind=data['kind'], **named_place({key: data[key] for key in ('name', 'lat', 'lng')}, 'Invalid car place'))


def named_place(data, error):
    if not isinstance(data, dict) or set(data) != {'name', 'lat', 'lng'}:
        failure(400, error)
    name = trip_text(data['name'], 'place name', 1, 40)
    for key, maximum in (('lat', 90), ('lng', 180)):
        if type(data[key]) not in (int, float) or not -maximum <= data[key] <= maximum or not math.isfinite(data[key]):
            failure(400, error)
    return dict(name=name, lat=data['lat'], lng=data['lng'])


class TeamTripPlan:
    def __init__(self, trips):
        self.trips = trips

    def route_state(self, conn, trip, car):
        row = conn.execute('SELECT driver_id,protected FROM team_trip_cars WHERE trip_id=%s AND car_id=%s FOR UPDATE',
            (trip, car)).fetchone()
        if not row:
            failure(404, 'Car unavailable')
        return row[0], self.trips.car_payload(trip, car, row[0], row[1])

    def save_route_state(self, conn, trip, car, driver, value):
        conn.execute('UPDATE team_trip_cars SET protected=%s WHERE trip_id=%s AND car_id=%s',
            (self.trips.protect('car:' + car + ':driver:' + driver, trip, value), trip, car))

    def signal_senders(self, conn, trip, identifiers):
        return dict(conn.execute('SELECT c.signal_id,s.account_id FROM team_trip_signal_contexts c '
            'JOIN team_room_signals s USING(signal_id) WHERE c.trip_id=%s AND c.signal_id=ANY(%s)',
            (trip, list(identifiers)))) if identifiers else {}

    def project_next(self, conn, trip, car, account, value):
        if 'routeNext' not in value:
            return {}
        target = value['routeNext']
        if target is not None and target['type'] == 'signal':
            sender = self.signal_senders(conn, trip, [target['ref']]).get(target['ref'])
            if sender is None or sender != account and blocked(conn, sender, account):
                return {}
        return dict(routeNext=target)

    def context(self, conn, trip, car, account, *, driver=False, rider=False, mutable=True):
        context = self.trips.access(conn, trip, account, mutable=mutable)
        value = self.trips.car(conn, trip, car, account)
        if driver and value['driverId'] != account:
            failure(403, 'Only the driver may manage the car')
        if rider and self.trips.riders(conn, trip).get(account) != car:
            failure(403, 'Only a passenger may select a place')
        return context, value

    def places(self, conn, trip, car, account, owner):
        full = account in (owner, self.trips.cars(conn, trip)[car]['driverId']) or self.trips.riders(conn, trip).get(account) == car
        from team_trip_route_segments import route_contract_version
        if route_contract_version(conn, trip) == 2 and account != self.trips.cars(conn, trip)[car]['driverId'] and self.trips.riders(conn, trip).get(account) != car:
            return []
        selected = {}
        for place, peer in conn.execute('SELECT place_id,account_id FROM team_trip_car_place_selections '
                'WHERE trip_id=%s AND car_id=%s ORDER BY account_id', (trip, car)):
            if peer == account or not blocked(conn, peer, account):
                selected.setdefault(place, []).append(peer)
        result = []
        for place, kind, adder, raw, created in conn.execute('SELECT place_id,kind,added_by,protected,created_at '
                'FROM team_trip_car_places WHERE trip_id=%s AND car_id=%s ORDER BY created_at,place_id', (trip, car)):
            if adder != account and blocked(conn, adder, account):
                continue
            value = self.trips.restore('car-place:' + car + ':' + place, trip, raw)
            try:
                if (not isinstance(value, dict) or set(value) != {'name', 'lat', 'lng'}
                        or place_fields(dict(value, kind=kind)) != dict(value, kind=kind)):
                    raise PrivateRecordError('Trip car place integrity failed')
            except HTTPException:
                raise PrivateRecordError('Trip car place integrity failed') from None
            peers = selected.get(place, [])
            result.append(dict(id=place, kind=kind, **value, addedBy=adder, createdAt=iso(created), selectedBy=peers)
                if full else dict(name=value['name'], selectedBy=len(peers)))
        signals = self.route_state(conn, trip, car)[1].get('routeSignals', {})
        senders = self.signal_senders(conn, trip, signals)
        for signal, value in signals.items():
            sender = senders.get(signal)
            if sender is None or sender != account and blocked(conn, sender, account):
                continue
            result.append(dict(id=signal, kind='signal', **value) if full else
                dict(kind='signal', name=value['name'], selectedBy=0))
        return result

    def create_place(self, conn, trip, car, account, data):
        value = place_fields(data)
        _, vehicle = self.context(conn, trip, car, account)
        from team_trip_route_segments import TeamTripRouteSegments
        TeamTripRouteSegments(self.trips).lock_active(conn, trip)
        if account != vehicle['driverId'] and self.trips.riders(conn, trip).get(account) != car:
            failure(403, 'Only the driver or a passenger may add a place')
        count = conn.execute('SELECT count(*) FROM team_trip_car_places WHERE trip_id=%s AND car_id=%s AND kind=%s',
            (trip, car, value['kind'])).fetchone()[0]
        if count >= CAR_PLACE_LIMIT:
            failure(409, 'Car place limit reached')
        identifier = secrets.token_hex(16)
        payload = {key: value[key] for key in ('name', 'lat', 'lng')}
        conn.execute('INSERT INTO team_trip_car_places(trip_id,car_id,place_id,kind,added_by,protected) VALUES(%s,%s,%s,%s,%s,%s)',
            (trip, car, identifier, value['kind'], account, self.trips.protect('car-place:' + car + ':' + identifier, trip, payload)))
        self.trips.notify(conn, trip, sections=('route',))
        return dict(id=identifier)

    def place(self, conn, trip, car, place, account):
        if not isinstance(place, str) or not IDENT.fullmatch(place):
            failure(404, 'Car place unavailable')
        row = conn.execute('SELECT kind,added_by FROM team_trip_car_places WHERE trip_id=%s AND car_id=%s AND place_id=%s',
            (trip, car, place)).fetchone()
        if not row or row[1] != account and blocked(conn, row[1], account):
            failure(404, 'Car place unavailable')
        return row

    def delete_place(self, conn, trip, car, place, account):
        _, vehicle = self.context(conn, trip, car, account)
        from team_trip_route_segments import TeamTripRouteSegments
        TeamTripRouteSegments(self.trips).lock_active(conn, trip)
        _, adder = self.place(conn, trip, car, place, account)
        if account not in (vehicle['driverId'], adder):
            failure(403, 'Only the driver or author may delete the place')
        conn.execute('DELETE FROM team_trip_car_places WHERE trip_id=%s AND car_id=%s AND place_id=%s', (trip, car, place))
        items = self.stored_order(conn, trip, car)
        if items is not None:
            items = [dict(item) for item in items if not (item['type'] in ('pickup', 'drop') and item['ref'] == place)]
            for item in items:
                if item.get('dropRef') == place:
                    item.pop('dropRef')
            self.save_order(conn, trip, car, items)
        self.trips.notify(conn, trip, sections=('route', 'detail'))
        return dict(status='deleted')

    def select(self, conn, trip, car, place, account, selected):
        _, vehicle = self.context(conn, trip, car, account, rider=True)
        from team_trip_route_segments import TeamTripRouteSegments
        TeamTripRouteSegments(self.trips).lock_active(conn, trip)
        kind, adder = self.place(conn, trip, car, place, account)
        if selected:
            previous = None
            if kind == 'pickup':
                previous = conn.execute('SELECT s.place_id,p.added_by FROM team_trip_car_place_selections s '
                    'JOIN team_trip_car_places p USING(trip_id,car_id,place_id,kind) '
                    'WHERE s.trip_id=%s AND s.car_id=%s AND s.account_id=%s AND s.kind=%s',
                    (trip, car, account, kind)).fetchone()
            conn.execute('INSERT INTO team_trip_car_place_selections(trip_id,car_id,place_id,account_id,kind) VALUES(%s,%s,%s,%s,%s) '
                'ON CONFLICT(trip_id,car_id,account_id,kind) DO UPDATE SET place_id=excluded.place_id', (trip, car, place, account, kind))
            if previous is not None and previous[0] != place:
                self.replace_pickup(conn, trip, car, vehicle['driverId'], previous, (place, adder))
        else:
            conn.execute('DELETE FROM team_trip_car_place_selections WHERE trip_id=%s AND car_id=%s AND place_id=%s AND account_id=%s',
                (trip, car, place, account))
        self.trips.notify(conn, trip, sections=('route', 'detail'))
        return dict(status='selected' if selected else 'unselected')

    def replace_pickup(self, conn, trip, car, driver, previous, replacement):
        old_place, old_author = previous
        new_place, new_author = replacement
        items = self.stored_order(conn, trip, car)
        old_item = dict(type='pickup', ref=old_place)
        new_item = dict(type='pickup', ref=new_place)
        if items is None or old_item not in items or new_item in items:
            return
        if any(author != driver and blocked(conn, author, driver) for author in (old_author, new_author)):
            return
        if conn.execute('SELECT 1 FROM team_trip_car_place_selections '
                'WHERE trip_id=%s AND car_id=%s AND place_id=%s AND kind=%s LIMIT 1',
                (trip, car, old_place, 'pickup')).fetchone() is not None:
            return
        _, state = self.route_state(conn, trip, car)
        index = items.index(old_item)
        if 'routeNext' in state:
            next_item = state['routeNext']
            if next_item not in items or index < items.index(next_item):
                return
        elif trip_state(conn, trip)['state'] != 'planned':
            # An active car has not reported which saved stops are still ahead.
            return
        items[index] = new_item
        self.save_order(conn, trip, car, items, next_replacement=(old_item, new_item))

    def read_stops(self, conn, identifier, version):
        row = conn.execute('SELECT checksum FROM pack_versions WHERE pack_id=%s AND version=%s',
            (identifier, version)).fetchone()
        try:
            checksum = row[0]
            if not isinstance(checksum, str) or len(checksum) != 64 or any(c not in '0123456789abcdef' for c in checksum):
                raise ValueError()
            path = self.trips.content / checksum
            if path.is_symlink() or not path.is_file() or path.stat().st_size > 262144:
                raise ValueError()
            with path.open('rb') as source:
                raw = source.read(262145)
            if len(raw) > 262144 or hashlib.sha256(raw).hexdigest() != checksum:
                raise ValueError()
            pack = validate_pack(json.loads(raw))
            if pack['id'] != identifier or pack['version'] != version:
                raise ValueError()
        except (OSError, ValueError, TypeError, KeyError):
            failure(503, 'Pack integrity check failed')
        return [dict(id=stop['id'], name=stop['name'], lat=stop['latitude'], lng=stop['longitude']) for stop in pack['stops']]

    def course_stops(self, conn, trip, account):
        return {(course['packId'], stop['id']): stop
            for course in self.trips.courses(conn, trip, account, False) for stop in course['stops']}

    def course_waypoints(self, conn, trip, pack):
        row = conn.execute('SELECT waypoints FROM team_trip_courses WHERE trip_id=%s AND pack_id=%s', (trip, pack)).fetchone()
        if not row or row[0] is None:
            return []
        points = self.trips.restore('course-waypoints:' + pack, trip, row[0])
        try:
            if not isinstance(points, list) or len(points) > WAYPOINT_LIMIT:
                raise PrivateRecordError('Trip waypoint integrity failed')
            ids = set()
            for point in points:
                if not isinstance(point, dict):
                    raise PrivateRecordError('Trip waypoint integrity failed')
                identifier = point.get('id')
                place = {key: value for key, value in point.items() if key != 'id'}
                if (not isinstance(identifier, str) or not WAYPOINT_ID.fullmatch(identifier) or identifier in ids
                        or named_place(place, 'Invalid trip waypoint') != place):
                    raise PrivateRecordError('Trip waypoint integrity failed')
                ids.add(identifier)
        except HTTPException:
            raise PrivateRecordError('Trip waypoint integrity failed') from None
        return points

    def edit_waypoints(self, conn, trip, account, pack, *, place=None, remove=None):
        if not isinstance(pack, str) or not PACK.fullmatch(pack):
            failure(404, 'Course unavailable')
        self.trips.access(conn, trip, account, permission='edit', mutable=True)
        if trip_state(conn, trip)['state'] != 'planned':
            failure(409, 'TRIP_STATE_CONFLICT')
        course = next((item for item in self.trips.courses(conn, trip, account, True)
                       if item['packId'] == pack and item['stops']), None)
        if course is None:
            failure(404, 'Course unavailable')
        points = self.course_waypoints(conn, trip, pack)
        if remove is None:
            value = named_place(place, 'Invalid trip waypoint')
            for point in points:
                if value == {key: point[key] for key in value}:
                    return point, False
            if len(points) >= WAYPOINT_LIMIT:
                failure(409, 'Trip waypoint limit reached')
            identifier = 'trip-waypoint-' + secrets.token_hex(16)
            added = dict(id=identifier, **value)
            points.append(added)
        else:
            updated = [point for point in points if point['id'] != remove]
            if len(updated) == len(points):
                failure(404, 'Trip waypoint unavailable')
            points = updated
            identifier, added = remove, None
        conn.execute('UPDATE team_trip_courses SET waypoints=%s WHERE trip_id=%s AND pack_id=%s',
            (self.trips.protect('course-waypoints:' + pack, trip, points), trip, pack))
        adding = added is not None
        if adding:
            self.check_waypoint_capacity(conn, trip)
        self.waypoints_changed(conn, trip, pack, identifier, adding)
        self.trips.notify(conn, trip, sections=('route',))
        return added, True

    def check_waypoint_capacity(self, conn, trip):
        rows = conn.execute('SELECT pack_id,waypoints IS NOT NULL FROM team_trip_courses WHERE trip_id=%s', (trip,)).fetchall()
        additions = sum(len(self.course_waypoints(conn, trip, pack)) for pack, present in rows if present)
        # Published courses may grow to three stops; reserve both pickup and drop slots even before a car exists.
        if additions and len(rows) * 3 + additions > ROUTE_LIMIT - 2 * CAR_PLACE_LIMIT:
            failure(409, 'Trip route limit reached')

    def waypoints_changed(self, conn, trip, pack, identifier, adding):
        target = dict(type='course', courseId=pack, ref=identifier)
        for car, vehicle in self.trips.cars(conn, trip).items():
            order = self.stored_order(conn, trip, car)
            if adding:
                course = [ref for pack_id, ref in self.course_stops(conn, trip, vehicle['driverId']) if pack_id == pack]
                if identifier not in course:
                    continue
                if order is None:
                    self.bump_route_revision(conn, trip, car)
                    continue
                index = next((i for i, item in enumerate(order)
                              if item.get('courseId') == pack and item['ref'] == course[-1]), None)
                if index is None:
                    self.bump_route_revision(conn, trip, car)
                    continue
                if len(order) >= ROUTE_LIMIT:
                    failure(409, 'Trip route limit reached')
                self.save_order(conn, trip, car, order[:index] + [target] + order[index:])
            elif order is None:
                self.bump_route_revision(conn, trip, car)
            else:
                self.save_order(conn, trip, car,
                    [item for item in order if (item.get('courseId'), item['ref']) != (pack, identifier)])

    def bump_route_revision(self, conn, trip, car):
        driver, value = self.route_state(conn, trip, car)
        value['routeRevision'] = value.get('routeRevision', 0) + 1
        if value['routeRevision'] > 2147483647:
            failure(409, 'Route revision limit reached')
        self.save_route_state(conn, trip, car, driver, value)

    @staticmethod
    def order_fields(items):
        if not isinstance(items, list) or len(items) > ROUTE_LIMIT:
            failure(400, 'Invalid route order')
        seen, drops = set(), set()
        for item in items:
            if not isinstance(item, dict) or type(item.get('type')) is not str:
                failure(400, 'Invalid route order')
            kind = item['type']
            fields = {'type', 'ref', 'courseId'} if kind == 'course' else {'type', 'ref'}
            if kind not in ('course', 'pickup', 'drop', 'signal') or set(item) - fields - ({'dropRef'} if kind == 'course' else set()) or not fields <= set(item):
                failure(400, 'Invalid route order')
            ref = item['ref']
            if not isinstance(ref, str) or not (PACK if kind == 'course' else IDENT).fullmatch(ref):
                failure(400, 'Invalid route order')
            if kind == 'course' and (not isinstance(item['courseId'], str) or not PACK.fullmatch(item['courseId'])):
                failure(400, 'Invalid route order')
            key = (kind, item.get('courseId'), ref)
            if key in seen:
                failure(400, 'Invalid route order')
            seen.add(key)
            drop = item.get('dropRef') if kind == 'course' else ref if kind == 'drop' else None
            if 'dropRef' in item and (not isinstance(drop, str) or not IDENT.fullmatch(drop)):
                failure(400, 'Invalid route order')
            if drop is not None:
                if drop in drops:
                    failure(400, 'Invalid route order')
                drops.add(drop)
        return items

    def stored_order(self, conn, trip, car):
        raw = conn.execute('SELECT route_order FROM team_trip_cars WHERE trip_id=%s AND car_id=%s', (trip, car)).fetchone()[0]
        if raw is None:
            return None
        items = self.trips.restore('route-order:' + car, trip, raw)
        try:
            return self.order_fields(items)
        except HTTPException:
            raise PrivateRecordError('Trip route order integrity failed') from None

    def route_order(self, conn, trip, car, account, owner):
        items = self.stored_order(conn, trip, car)
        if items is None:
            return None
        vehicle = self.trips.cars(conn, trip)[car]
        from team_trip_route_segments import route_contract_version
        if route_contract_version(conn, trip) == 2 and account != vehicle['driverId'] and self.trips.riders(conn, trip).get(account) != car:
            return None
        if account not in (owner, vehicle['driverId']) and self.trips.riders(conn, trip).get(account) != car:
            return None
        stops = self.course_stops(conn, trip, account)
        places = {(item['kind'], item['id']): item for item in self.places(conn, trip, car, account, owner)}
        if {(item['courseId'], item['ref']) for item in items if item['type'] == 'course'} != set(stops):
            return None
        result = []
        for item in items:
            if item['type'] != 'course' and (item['type'], item['ref']) not in places:
                continue
            item = dict(item)
            if ('drop', item.get('dropRef')) not in places:
                item.pop('dropRef', None)
            elif item['type'] == 'course':
                stop, drop = stops[item['courseId'], item['ref']], places['drop', item['dropRef']]
                if (stop['lat'], stop['lng']) != (drop['lat'], drop['lng']):
                    return None
            result.append(item)
        return result

    def save_order(self, conn, trip, car, items, *, force=False, next_replacement=None):
        self.order_fields(items)
        if not force and self.stored_order(conn, trip, car) == items:
            return
        conn.execute('UPDATE team_trip_cars SET route_order=%s WHERE trip_id=%s AND car_id=%s',
            (self.trips.protect('route-order:' + car, trip, items), trip, car))
        driver, value = self.route_state(conn, trip, car)
        value['routeRevision'] = value.get('routeRevision', 0) + 1
        if value['routeRevision'] > 2147483647:
            failure(409, 'Route revision limit reached')
        if value.get('routeNext') is not None and value['routeNext'] not in items:
            if next_replacement is not None and value['routeNext'] == next_replacement[0]:
                value['routeNext'] = next_replacement[1]
            else:
                value.pop('routeNext')
        self.save_route_state(conn, trip, car, driver, value)

    def default_order(self, conn, trip, car, account, owner):
        stops = self.course_stops(conn, trip, account)
        items = [dict(type='course', courseId=course, ref=stop) for course, stop in stops]
        places = self.places(conn, trip, car, account, owner)
        for kind in ('pickup', 'drop'):
            for place in places:
                if place.get('kind') != kind:
                    continue
                if kind == 'pickup':
                    at = next((i for i, item in enumerate(items) if item['type'] == 'course'), len(items))
                    items.insert(at, dict(type='pickup', ref=place['id']))
                else:
                    host = next((item for item in items if item['type'] == 'course' and 'dropRef' not in item and
                        (stops[item['courseId'], item['ref']]['lat'], stops[item['courseId'], item['ref']]['lng']) ==
                        (place['lat'], place['lng'])), None)
                    if host is not None:
                        host['dropRef'] = place['id']
                    else:
                        items.append(dict(type='drop', ref=place['id']))
        return items

    def course_priority_changed(self, conn, trip):
        for car in self.trips.cars(conn, trip):
            if self.stored_order(conn, trip, car) is not None:
                continue
            self.bump_route_revision(conn, trip, car)

    def courses_changed(self, conn, trip):
        owner = self.trips.load(conn, trip)[0]
        for car in self.trips.cars(conn, trip):
            driver, value = self.route_state(conn, trip, car)
            old = self.stored_order(conn, trip, car)
            if not value.get('routeSignals'):
                conn.execute('UPDATE team_trip_cars SET route_order=NULL WHERE trip_id=%s AND car_id=%s', (trip, car))
                if old is not None or 'routeNext' in value or value.get('routeRevision', 0) > 0:
                    value['routeRevision'] = value.get('routeRevision', 0) + 1
                    if value['routeRevision'] > 2147483647:
                        failure(409, 'Route revision limit reached')
                    value.pop('routeNext', None)
                    self.save_route_state(conn, trip, car, driver, value)
                continue
            default = self.default_order(conn, trip, car, driver, owner)
            available = {(item['type'], item.get('courseId'), item['ref']): item for item in default}
            stops = self.course_stops(conn, trip, driver)
            places = {(place['kind'], place['id']): place for place in self.places(conn, trip, car, driver, owner)}
            items = []
            for item in old or []:
                if item['type'] == 'signal' and item['ref'] in value['routeSignals']:
                    items.append(dict(item))
                elif (item['type'], item.get('courseId'), item['ref']) in available:
                    selected = dict(item)
                    if selected.get('dropRef') is not None:
                        place = places.get(('drop', selected['dropRef']))
                        stop = stops.get((selected.get('courseId'), selected['ref']))
                        if place is None or stop is None or (place['lat'], place['lng']) != (stop['lat'], stop['lng']):
                            selected.pop('dropRef')
                    items.append(selected)
            used = {(item['type'], item.get('courseId'), item['ref']) for item in items}
            old_places = {item['ref'] for item in old or [] if item['type'] in ('pickup', 'drop')}
            old_places.update(item['dropRef'] for item in old or [] if 'dropRef' in item)
            used_drops = {item['ref'] for item in items if item['type'] == 'drop'} | {
                item['dropRef'] for item in items if 'dropRef' in item}
            for key, item in available.items():
                if key not in used and (item['type'] == 'course' or item['ref'] in old_places):
                    selected = dict(item)
                    if selected.get('dropRef') in used_drops:
                        selected.pop('dropRef')
                    if 'dropRef' in selected:
                        used_drops.add(selected['dropRef'])
                    if selected['type'] == 'drop':
                        used_drops.add(selected['ref'])
                    items.append(selected)
            for place_id in old_places - used_drops:
                place = places.get(('drop', place_id))
                if place is None:
                    continue
                host = next((item for item in items if item['type'] == 'course' and 'dropRef' not in item and
                    (stops[item['courseId'], item['ref']]['lat'], stops[item['courseId'], item['ref']]['lng']) ==
                    (place['lat'], place['lng'])), None)
                if host is None:
                    items.append(dict(type='drop', ref=place_id))
                else:
                    host['dropRef'] = place_id
            if old is None:
                items = [dict(type='signal', ref=signal) for signal in value['routeSignals']] + default
            self.save_order(conn, trip, car, items, force=True)

    def progress(self, conn, trip, car, account, next_item, revision):
        (owner, _, _), _ = self.context(conn, trip, car, account, driver=True)
        if trip_state(conn, trip)['state'] != 'active':
            failure(409, 'TRIP_STATE_CONFLICT')
        driver, value = self.route_state(conn, trip, car)
        if type(revision) is not int or not 0 <= revision <= 2147483647:
            failure(400, 'Invalid route revision')
        if revision != value.get('routeRevision', 0):
            failure(409, 'Route revision conflict')
        items = self.route_order(conn, trip, car, account, owner)
        items = items if items is not None else self.default_order(conn, trip, car, account, owner)
        if next_item is not None:
            self.order_fields([next_item])
            if next_item not in items:
                failure(400, 'Next place is not in the car route')
        # The reported place is where the driver is being guided now. Confirmed
        # arrivals stay with route-arrivals; guidance only cannot point back to a
        # confirmed place or end the route before every arrival is confirmed.
        from team_trip_route_segments import TeamTripRouteSegments
        arrivals = TeamTripRouteSegments(self.trips).load(conn, trip)
        state = arrivals['cars'].get(car) if arrivals is not None else None
        if state is not None and (next_item in state['completed'] if next_item is not None
                else TeamTripRouteSegments.next_item(state) is not None):
            failure(409, 'TRIP_ROUTE_PROGRESS_CHANGED')
        if 'routeNext' not in value or value['routeNext'] != next_item:
            value['routeNext'] = dict(next_item) if next_item is not None else None
            self.save_route_state(conn, trip, car, driver, value)
            self.trips.notify(conn, trip, bump=False, invalidate=False, sections=('route',))
        return dict(status='updated')

    def apply_agreed_signal(self, conn, context, signal, destination, car_ids):
        from team_trip_signal_contexts import place_value
        if not isinstance(signal, str) or not IDENT.fullmatch(signal):
            failure(400, 'Invalid route signal')
        place = place_value(destination)
        place = dict(name=place['name'], lat=place['latitude'], lng=place['longitude'])
        trip = context['tripId']
        cars = self.trips.cars(conn, trip)
        for car in dict.fromkeys(car_ids):
            if car not in cars:
                failure(409, 'Trip car changed')
            driver, value = self.route_state(conn, trip, car)
            from team_trip_route_segments import TeamTripRouteSegments
            TeamTripRouteSegments(self.trips).check_shared(conn, trip, driver)
            signals = value.get('routeSignals', {})
            if signal in signals:
                if signals[signal] != place:
                    raise PrivateRecordError('Trip route signal integrity failed')
                continue
            items = self.stored_order(conn, trip, car)
            if items is None:
                items = self.default_order(conn, trip, car, driver, context['ownerId'])
            added = dict(type='signal', ref=signal)
            arrivals = TeamTripRouteSegments(self.trips).load(conn, trip)
            if arrivals is not None and car in arrivals['cars']:
                # Guidance may run ahead; the agreed place joins before the next unconfirmed arrival.
                target = TeamTripRouteSegments.next_item(arrivals['cars'][car])
                at = items.index(target) if target in items else len(items)
            elif 'routeNext' in value:
                at = items.index(value['routeNext']) if value['routeNext'] in items else len(items)
            else:
                completed = {row[0] for row in conn.execute('SELECT pack_id FROM team_trip_car_course_completions '
                    'WHERE trip_id=%s AND car_id=%s', (trip, car))}
                at = next((i for i, item in enumerate(items) if item['type'] == 'course' and
                    item['courseId'] not in completed), len(items)) if completed else 0
            items.insert(at, added)
            if len(signals) >= 50:
                failure(409, 'Route signal limit reached')
            self.save_order(conn, trip, car, items)
            value = self.route_state(conn, trip, car)[1]
            value['routeSignals'] = dict(signals, **{signal: place})
            value['routeNext'] = added
            self.save_route_state(conn, trip, car, driver, value)
            TeamTripRouteSegments(self.trips).add_signal(conn, trip, car, signal)

    def set_order(self, conn, trip, car, account, items, revision=None, route_contract_version=None):
        self.order_fields(items)
        (owner, _, _), _ = self.context(conn, trip, car, account, driver=True)
        from team_trip_route_segments import TeamTripRouteSegments
        TeamTripRouteSegments(self.trips).lock_active(conn, trip)
        if route_contract_version is not None and (type(route_contract_version) is not int or route_contract_version != 2):
            failure(400, 'TRIP_ROUTE_CONTRACT_INVALID')
        current = self.route_state(conn, trip, car)[1].get('routeRevision', 0)
        if revision is None:
            if current != 0:
                failure(409, 'Route revision conflict')
        elif type(revision) is not int or not 0 <= revision <= 2147483647:
            failure(400, 'Invalid route revision')
        elif revision != current:
            failure(409, 'Route revision conflict')
        stops = self.course_stops(conn, trip, account)
        if route_contract_version == 2:
            expected_shared = [dict(type='course', courseId=course, ref=stop) for course, stop in stops]
            shared = [item for item in items if item['type'] == 'course']
            kinds = [('pickup' if item['type'] == 'pickup' else 'drop' if item['type'] == 'drop' else 'shared') for item in items]
            if (shared != expected_shared or any('dropRef' in item for item in items)
                    or kinds != sorted(kinds, key=('pickup', 'shared', 'drop').index)):
                failure(400, 'TRIP_ROUTE_SEGMENT_ORDER_INVALID')
        places = {(item['kind'], item['id']): item for item in self.places(conn, trip, car, account, owner)}
        if {(item['courseId'], item['ref']) for item in items if item['type'] == 'course'} != set(stops):
            failure(400, 'All course places are required')
        for item in items:
            if item['type'] != 'course':
                place = places.get((item['type'], item['ref']))
                if place is None:
                    failure(400, 'Invalid route order')
                if route_contract_version != 2 and item['type'] == 'drop' and any(not WAYPOINT_ID.fullmatch(stop['id']) and (stop['lat'], stop['lng']) ==
                        (place['lat'], place['lng']) for stop in stops.values()):
                    failure(400, 'Attach the drop to its course place')
            elif 'dropRef' in item:
                place = places.get(('drop', item['dropRef']))
                stop = stops[item['courseId'], item['ref']]
                if not place or place['kind'] != 'drop' or (place['lat'], place['lng']) != (stop['lat'], stop['lng']):
                    failure(400, 'Invalid route order')
        self.save_order(conn, trip, car, items)
        self.trips.notify(conn, trip, sections=('route',))
        return dict(status='updated')

    def invites(self, conn, trip, account):
        result = []
        for identifier, car, peer, created, driver in conn.execute('SELECT i.invite_id,i.car_id,i.account_id,i.created_at,c.driver_id '
                'FROM team_trip_ride_invites i JOIN team_trip_cars c USING(trip_id,car_id) '
                'WHERE i.trip_id=%s ORDER BY i.created_at,i.invite_id', (trip,)):
            if account in (driver, peer) and not blocked(conn, driver, peer):
                result.append(dict(id=identifier, carId=car, accountId=peer, createdAt=iso(created)))
        return result

    def invite(self, conn, trip, car, account, target):
        (_, _, members), vehicle = self.context(conn, trip, car, account, driver=True)
        if (not isinstance(target, str) or not ACCOUNT.fullmatch(target) or members.get(target, {}).get('state') != 'accepted'
                or not self.trips.person(target) or blocked(conn, account, target)):
            failure(404, 'Account unavailable')
        if any(value['driverId'] == target for value in self.trips.cars(conn, trip).values()):
            failure(409, 'Already driving')
        if sum(value == car for value in self.trips.riders(conn, trip).values()) >= vehicle['seats']:
            failure(409, 'Car is full')
        row = conn.execute('INSERT INTO team_trip_ride_invites(trip_id,car_id,invite_id,account_id) VALUES(%s,%s,%s,%s) '
            'ON CONFLICT(trip_id,car_id,account_id) DO UPDATE SET account_id=excluded.account_id RETURNING invite_id',
            (trip, car, secrets.token_hex(16), target)).fetchone()
        self.trips.notify(conn, trip)
        return dict(id=row[0])

    def respond(self, conn, trip, car, identifier, account, accept):
        if type(accept) is not bool:
            failure(400, 'Choose a response')
        self.context(conn, trip, car, account)
        row = conn.execute('SELECT account_id FROM team_trip_ride_invites WHERE trip_id=%s AND car_id=%s AND invite_id=%s',
            (trip, car, identifier)).fetchone()
        if not row or row[0] != account:
            failure(404, 'Ride invite unavailable')
        if accept:
            self.trips.assign_ride(conn, trip, car, account)
        conn.execute('DELETE FROM team_trip_ride_invites WHERE trip_id=%s AND car_id=%s AND invite_id=%s', (trip, car, identifier))
        self.trips.notify(conn, trip)
        return dict(status='accepted' if accept else 'declined')

    def cancel_invite(self, conn, trip, car, identifier, account):
        self.context(conn, trip, car, account, driver=True)
        row = conn.execute('DELETE FROM team_trip_ride_invites WHERE trip_id=%s AND car_id=%s AND invite_id=%s RETURNING invite_id',
            (trip, car, identifier)).fetchone()
        if not row:
            failure(404, 'Ride invite unavailable')
        self.trips.notify(conn, trip)
        return dict(status='cancelled')

    def remove_rider(self, conn, trip, car, account, target):
        self.context(conn, trip, car, account, driver=True)
        if self.trips.riders(conn, trip).get(target) != car or blocked(conn, account, target):
            failure(404, 'Passenger unavailable')
        self.trips.leave_car(conn, trip, target)
        self.trips.notify(conn, trip)
        return dict(status='removed')

    def complete(self, conn, trip, car, pack, account, driving_score=None, progress=None):
        state = resolve_trip_context(self.trips.auth, conn, trip, account, states=None)['state']
        self.context(conn, trip, car, account, driver=True, mutable=False)
        from team_trip_route_segments import TeamTripRouteSegments
        segments = TeamTripRouteSegments(self.trips)
        segmented = segments.load(conn, trip)
        if segmented is not None:
            items = [item for item in segmented['cars'].get(car, {}).get('items', []) if item.get('courseId') == pack]
            if not items or not segmented['released']:
                failure(409, 'TRIP_ROUTE_PROGRESS_CHANGED')
            if any(item not in segmented['cars'][car]['completed'] for item in items):
                if state != 'active':
                    failure(409, 'TRIP_STATE_CONFLICT')
                segmented = segments.complete_join_course(conn, trip, car, account, pack, progress)
        if state != 'active' and (segmented is None or state != 'completed'):
            failure(409, 'TRIP_STATE_CONFLICT')
        if pack not in {course['packId'] for course in self.trips.courses(conn, trip, account, False)}:
            failure(404, 'Course unavailable')
        score_changed = False
        if driving_score is not None:
            from team_trip_driving_scores import TeamTripDrivingScores
            score_changed = TeamTripDrivingScores(self.trips).write(conn, trip, car, pack, account, driving_score, final=True, notify=False)['status'] == 'updated'
        row = conn.execute('INSERT INTO team_trip_car_course_completions(trip_id,car_id,pack_id) VALUES(%s,%s,%s) '
            'ON CONFLICT DO NOTHING RETURNING car_id', (trip, car, pack)).fetchone()
        if row or score_changed:
            self.trips.notify(conn, trip)
        return dict(status='completed')
