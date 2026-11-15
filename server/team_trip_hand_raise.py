"""Ephemeral hand-raise stop candidates for an active trip; no location storage and no coordinates in logs."""
from collections import deque
import json
import logging
import math
import re
import time
from datetime import datetime, timezone
from threading import BoundedSemaphore, Lock
from urllib.parse import urlencode

from place_search import kakao_transport, load_key, text
from rest_stop_data import DATASET
from team_discovery import FACILITIES
from route_preview import route_transport

LOG = logging.getLogger(__name__)

HAND_RAISE_KINDS = ('restroom', 'rest', 'drowsy', 'hungry', 'smoking', 'nursing', 'cafe', 'ev_charge', 'fuel')
STALE_SECONDS = 180
SAME_ROAD_METERS = 300
LEAD_GAP_METERS = 2000
ROUTE_END_MARGIN_METERS = 300
SEARCH_STEP_METERS = 6000
SEARCH_RADIUS_METERS = 4000
HEADING_STEPS_METERS = (2000, 5000, 10000)
HEADING_RADIUS_METERS = 2000
HEADING_SPREAD_DEGREES = 60
OFFICIAL_ROUTE_METERS = 3000
GROUP_METERS = 300
OFFICIAL_MATCH_METERS = 1000
MAX_SEARCH_CALLS = 16
MAX_DIRECTION_CALLS = 3
DETOUR_CANDIDATES = 2
MAX_CANDIDATES = 10
TIMEOUT_SECONDS = 6
CALL_TIMEOUT_SECONDS = 3
MAX_CONCURRENT = 4
MAX_DETOUR_SECONDS = 300
RATE_PER_MINUTE = 10
TRIP_RATE_PER_MINUTE = 30
GLOBAL_RATE_PER_MINUTE = 120
PROJECTION_BLOCK = 32
MAX_ROUTE_BYTES = 2 * 1024 * 1024
MAX_SEARCH_BYTES = 256 * 1024
MAX_PATH_POINTS = 4000
OFFICIAL_KINDS = frozenset(('restroom', 'rest', 'smoking', 'nursing', 'drowsy', 'ev_charge', 'fuel'))
QUERIES = dict(
    restroom=(('keyword', '휴게소'),), rest=(('keyword', '휴게소'),), smoking=(('keyword', '휴게소'),),
    nursing=(('keyword', '휴게소'),), drowsy=(('keyword', '졸음쉼터'),),
    cafe=(('category', 'CE7'),), ev_charge=(('keyword', '휴게소'),), fuel=(('keyword', '휴게소'),),
    hungry=(('category', 'FD6'), ('category', 'CE7'), ('keyword', '휴게소')))
LABELS = dict(ahead='모든 차 앞쪽', off_route='경로 벗어남')
HIGHWAY = re.compile(r'고속도로|도시고속|고속화')
HIGHWAY_QUERIES = (('keyword', '휴게소'),)
STEM = re.compile(r'([가-힣]+?)(휴게소|졸음쉼터|만남의광장)')
DIRECTION = re.compile(r'([가-힣]+?)\s*방향')
_SLOTS = BoundedSemaphore(MAX_CONCURRENT)


class CandidateError(ValueError):
    def __init__(self, code='CANDIDATES_UNAVAILABLE', status=503):
        self.code, self.status = code, status
        super().__init__(code)


def point_value(value, *, heading=False):
    keys = {'lat', 'lng'} | ({'heading'} if heading else set())
    if not isinstance(value, dict) or not {'lat', 'lng'} <= set(value) <= keys:
        raise ValueError()
    result = {}
    for key, low, high in (('lat', 32, 39), ('lng', 124, 132), ('heading', 0, 360)):
        if key not in value or key == 'heading' and value[key] is None:
            continue
        number = value[key]
        if type(number) not in (int, float) or not math.isfinite(number) or not low <= number <= high:
            raise ValueError()
        result[key] = float(number)
    if 'heading' in result:
        result['heading'] %= 360
    return result


def facilities_input(data):
    required = data.get('requiredFacilities', [])
    if (not isinstance(required, list) or len(required) > len(FACILITIES)
            or any(not isinstance(key, str) or key not in FACILITIES for key in required)
            or len(set(required)) != len(required)):
        raise CandidateError('DISCOVERY_FACILITY_INVALID', 400)
    return tuple(required)


def candidate_input(data):
    facilities_input(data)
    kind = data.get('kind')
    if not isinstance(kind, str) or kind not in HAND_RAISE_KINDS:
        raise CandidateError('Invalid hand-raise kind', 400)
    try:
        location = point_value(data.get('location'), heading=True)
    except ValueError:
        raise CandidateError('Invalid location', 400) from None
    destination = data.get('destination')
    if destination is not None:
        try:
            destination = point_value(destination)
        except ValueError:
            raise CandidateError('Invalid destination', 400) from None
    elif 'heading' not in location:
        raise CandidateError('Choose a destination or heading', 400)
    return kind, location, destination


def meters(a, b):
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 6371000 * 2 * math.asin(min(1, math.sqrt(h)))


def bearing(a, b):
    la1, la2 = math.radians(a[0]), math.radians(b[0])
    d = math.radians(b[1] - a[1])
    return (math.degrees(math.atan2(math.sin(d) * math.cos(la2),
        math.cos(la1) * math.sin(la2) - math.sin(la1) * math.cos(la2) * math.cos(d))) + 360) % 360


def offset(point, heading, distance):
    la, lo, th, delta = math.radians(point[0]), math.radians(point[1]), math.radians(heading), distance / 6371000
    lat = math.asin(math.sin(la) * math.cos(delta) + math.cos(la) * math.sin(delta) * math.cos(th))
    lng = lo + math.atan2(math.sin(th) * math.sin(delta) * math.cos(la), math.cos(delta) - math.sin(la) * math.sin(lat))
    return math.degrees(lat), math.degrees(lng)


class Line:
    def __init__(self, path, roads=None):
        self.path, self.ref = path, path[0]
        self.roads = roads or [''] * len(path)
        self.kx, self.ky = 111320 * math.cos(math.radians(self.ref[0])), 110540
        self.xy = [self.local(point) for point in path]
        self.cum = [0.0]
        for a, b in zip(self.xy, self.xy[1:]):
            self.cum.append(self.cum[-1] + math.hypot(b[0] - a[0], b[1] - a[1]))
        self.length = self.cum[-1]
        self.blocks = []
        for begin in range(0, len(self.xy) - 1, PROJECTION_BLOCK):
            chunk = self.xy[begin:begin + PROJECTION_BLOCK + 1]
            self.blocks.append((begin, begin + len(chunk) - 1, min(x for x, _ in chunk), max(x for x, _ in chunk),
                min(y for _, y in chunk), max(y for _, y in chunk)))
        self.west, self.east = min(q[1] for q in path), max(q[1] for q in path)
        self.south, self.north = min(q[0] for q in path), max(q[0] for q in path)

    def near(self, point, margin):
        lat, lng = point
        dlat, dlng = margin / 110540, margin / max(self.kx, 1)
        return self.south - dlat <= lat <= self.north + dlat and self.west - dlng <= lng <= self.east + dlng

    def local(self, point):
        return (point[1] - self.ref[1]) * self.kx, (point[0] - self.ref[0]) * self.ky

    def project(self, point):
        px, py = self.local(point)
        best = None
        order = sorted((math.hypot(max(x0 - px, 0, px - x1), max(y0 - py, 0, py - y1)), begin, end)
            for begin, end, x0, x1, y0, y1 in self.blocks)
        for bound, begin, end in order:
            if best is not None and bound >= best[0]:
                break
            for index in range(begin, end):
                best = self.segment(px, py, index, best)
        return best

    def segment(self, px, py, index, best):
        (ax, ay), (bx, by) = self.xy[index], self.xy[index + 1]
        dx, dy = bx - ax, by - ay
        span = dx * dx + dy * dy or 1e-9
        t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / span))
        fx, fy = ax + t * dx, ay + t * dy
        distance = math.hypot(px - fx, py - fy)
        if best is None or distance < best[0]:
            side = -1 if dx * (py - ay) - dy * (px - ax) > 0 else 1
            best = (distance, self.cum[index] + t * math.sqrt(span), side, index)
        return best

    def highway(self, index):
        return bool(HIGHWAY.search(self.roads[index]))

    def index_at(self, along):
        for index in range(len(self.cum) - 1):
            if self.cum[index + 1] >= along:
                return index
        return len(self.cum) - 2

    def at(self, along):
        along = max(0.0, min(self.length, along))
        for index in range(len(self.cum) - 1):
            if self.cum[index + 1] >= along:
                span = self.cum[index + 1] - self.cum[index] or 1e-9
                t = (along - self.cum[index]) / span
                a, b = self.path[index], self.path[index + 1]
                return a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1])
        return self.path[-1]


class KakaoHandRaiseProvider:
    def __init__(self, key, *, search_transport=kakao_transport, directions_transport=route_transport):
        self._key, self._search, self._route = key, search_transport, directions_transport

    def _raw(self, transport, url, timeout, maximum):
        raw = transport(url, {'Authorization': 'KakaoAK ' + self._key}, timeout, maximum)
        if len(raw) > maximum or self._key.encode() in raw:
            raise ValueError()
        return json.loads(raw)

    def directions(self, origin, destination, *, angle=None, waypoint=None, timeout):
        try:
            xy = lambda point: f'{point[1]},{point[0]}'
            params = dict(origin=xy(origin) + (f',angle={int(angle) % 360}' if angle is not None else ''),
                destination=xy(destination), priority='RECOMMEND', summary='false')
            if waypoint is not None:
                params['waypoints'] = xy(waypoint)
            route = self._raw(self._route, 'https://apis-navi.kakaomobility.com/v1/directions?' + urlencode(params),
                timeout, MAX_ROUTE_BYTES)['routes'][0]
            if type(route['result_code']) is not int:
                raise ValueError()
            if route['result_code'] != 0:
                raise CandidateError('CANDIDATES_ROUTE_NOT_FOUND', 422)
            summary = route['summary']
            for key in ('distance', 'duration'):
                if type(summary[key]) not in (int, float) or not math.isfinite(summary[key]) or summary[key] < 0:
                    raise ValueError()
            path, names = [], []
            for section in route['sections']:
                for road in section['roads']:
                    name = text(road.get('name', ''), 80)
                    vertices = road['vertexes']
                    if not isinstance(vertices, list) or len(vertices) % 2:
                        raise ValueError()
                    for index in range(0, len(vertices), 2):
                        lng, lat = vertices[index], vertices[index + 1]
                        if (type(lat) not in (int, float) or type(lng) not in (int, float)
                                or not 32 <= lat <= 39 or not 124 <= lng <= 132):
                            raise ValueError()
                        if not path or path[-1] != (lat, lng):
                            path.append((lat, lng))
                            names.append(name)
            if len(path) < 2:
                raise ValueError()
            if len(path) > MAX_PATH_POINTS:
                picks = [index * (len(path) - 1) // (MAX_PATH_POINTS - 1) for index in range(MAX_PATH_POINTS)]
                path, names = [path[index] for index in picks], [names[index] for index in picks]
            return dict(distance=summary['distance'], duration=summary['duration'], path=path, roads=names)
        except (CandidateError, TimeoutError):
            raise
        except Exception:
            raise CandidateError('CANDIDATES_PROVIDER_UNAVAILABLE', 502) from None

    def places(self, mode, value, point, radius, *, timeout):
        try:
            params = dict(x=point[1], y=point[0], radius=int(radius), sort='distance', size=15)
            if mode == 'keyword':
                params['query'] = value
            else:
                params['category_group_code'] = value
            documents = self._raw(self._search, 'https://dapi.kakao.com/v2/local/search/' + mode + '.json?'
                + urlencode(params), timeout, MAX_SEARCH_BYTES)['documents']
            if not isinstance(documents, list) or len(documents) > 30:
                raise ValueError()
            result = []
            for doc in documents:
                identifier = text(doc['id'], 100)
                if not re.fullmatch(r'[0-9]+', identifier):
                    raise ValueError()
                lat, lng = float(doc['y']), float(doc['x'])
                if not math.isfinite(lat) or not math.isfinite(lng) or abs(lat) > 90 or abs(lng) > 180:
                    raise ValueError()
                name = text(doc['place_name'], 80)
                if not name:
                    raise ValueError()
                result.append(dict(id='kakao-' + identifier, name=name, lat=lat, lng=lng))
            return result
        except (CandidateError, TimeoutError):
            raise
        except Exception:
            raise CandidateError('CANDIDATES_PROVIDER_UNAVAILABLE', 502) from None


class Budget:
    def __init__(self, clock, timeout):
        self.clock, self.deadline = clock, clock() + timeout
        self.searches = self.routes = 0
        self.partial = False

    def timeout(self):
        remaining = self.deadline - self.clock()
        if remaining <= 0:
            raise TimeoutError()
        return min(remaining, CALL_TIMEOUT_SECONDS)

    def expired(self):
        return self.deadline - self.clock() <= 0

    def route(self, provider, *args, **kwargs):
        if self.routes >= MAX_DIRECTION_CALLS:
            raise CandidateError('CANDIDATES_CALL_LIMIT', 503)
        self.routes += 1
        return provider.directions(*args, timeout=self.timeout(), **kwargs)

    def search(self, provider, kind, points, radius, queries=None):
        found = {}
        for index, point in enumerate(points):
            for mode, value in (queries[index] if queries else QUERIES[kind]):
                if self.searches >= MAX_SEARCH_CALLS:
                    self.partial = True
                    return list(found.values())
                try:
                    timeout = self.timeout()
                    self.searches += 1
                    for doc in provider.places(mode, value, point, radius, timeout=timeout):
                        found.setdefault(doc['id'], doc)
                except (TimeoutError, CandidateError):
                    self.partial = True
                    return list(found.values())
        return list(found.values())


def compact(name):
    return re.sub(r'\s+', '', name)


def stem_of(name):
    match = STEM.search(name)
    if not match:
        return None, None
    rest = DIRECTION.search(name[match.end():])
    return match.group(1) + match.group(2), rest.group(1) if rest else None


def group_places(docs):
    groups, loose = [], []
    for doc in sorted(docs, key=lambda item: (len(compact(item['name'])), item['id'])):
        stem, direction = stem_of(doc['name'])
        if stem is None:
            groups.append(dict(stem=None, direction=None, twoWay='양방향' in doc['name'], members=[doc]))
        elif direction and direction != '양':
            for group in groups:
                if (group['stem'] == stem and group['direction'] == direction
                        and any(meters(p(doc), p(member)) <= GROUP_METERS for member in group['members'])):
                    group['members'].append(doc)
                    break
            else:
                groups.append(dict(stem=stem, direction=direction, twoWay=False, members=[doc]))
        else:
            loose.append((doc, stem, direction == '양' or '양방향' in doc['name']))
    for doc, stem, two_way in loose:
        near = [(min(meters(p(doc), p(member)) for member in group['members']), index)
            for index, group in enumerate(groups) if group['stem'] == stem]
        near = [item for item in near if item[0] <= GROUP_METERS]
        if near:
            group = groups[min(near)[1]]
        else:
            group = dict(stem=stem, direction=None, twoWay=False, members=[])
            groups.append(group)
        group['members'].append(doc)
        group['twoWay'] = group['twoWay'] or two_way
    return same_place(groups)


def same_place(groups):
    merged = []
    for group in sorted(groups, key=lambda item: (item['stem'] is None, len(item['stem'] or ''))):
        group = dict(group, aliases={group['stem']} if group['stem'] else set())
        if group['stem']:
            kind, base = suffix(group['stem'])
            for other in merged:
                if (other['stem'] and suffix(other['stem'])[0] == kind
                        and (suffix(other['stem'])[1] in base or base in suffix(other['stem'])[1])
                        and (not other['direction'] or not group['direction'] or other['direction'] == group['direction'])
                        and min(meters(p(a), p(b)) for a in other['members'] for b in group['members']) <= GROUP_METERS):
                    other['members'] += group['members']
                    other['aliases'] |= group['aliases']
                    other['twoWay'] = other['twoWay'] or group['twoWay']
                    other['direction'] = other['direction'] or group['direction']
                    break
            else:
                merged.append(group)
        else:
            merged.append(group)
    return merged


def suffix(stem):
    for word in ('휴게소', '졸음쉼터', '만남의광장'):
        if stem.endswith(word):
            return word, compact(stem[:-len(word)])
    return None, compact(stem)


def p(item):
    return item['lat'], item['lng']


def official_parts(name):
    match = re.fullmatch(r'\s*([^()]+?)\s*(?:\(([^()]*)\))?\s*', name)
    if not match:
        return compact(name), None
    return compact(match.group(1)), (match.group(2) or '').strip() or None


def official_items(near):
    result = []
    for item in DATASET['items']:
        if type(item.get('latitude')) not in (int, float) or type(item.get('longitude')) not in (int, float):
            continue
        place = (float(item['latitude']), float(item['longitude']))
        if near(place):
            result.append(dict(item, lat=place[0], lng=place[1]))
    return result


def merge_official(groups, officials, kind, standalone=None):
    places, used = [], set()
    for group in groups:
        rep = group['members'][0]
        stem = group['stem']
        match = None
        bases = {suffix(alias)[1] for alias in group.get('aliases', ()) if suffix(alias)[0] == '휴게소'}
        if bases:
            options = []
            for item in officials:
                name, hint = official_parts(item['name'])
                if name not in bases or item['id'] in used:
                    continue
                if hint and group['direction'] and hint not in group['direction'] and group['direction'] not in hint:
                    continue
                distance = min(meters(p(item), p(member)) for member in group['members'])
                if distance <= OFFICIAL_MATCH_METERS:
                    options.append((distance, item['id'], item))
            if options:
                match = min(options)[2]
                used.add(match['id'])
        if stem:
            name = stem + ('(' + group['direction'] + '방향)' if group['direction'] and not group['twoWay'] else '')
        else:
            name = rep['name']
        location = p(match) if match else p(rep)
        places.append(dict(name=name, lat=location[0], lng=location[1], source='official' if match else 'kakao',
            facilities=dict(match['facilities']) if match else None, restStop=bool(stem or match),
            routeName=(match.get('routeName') or None) if match else None,
            direction=(match.get('reportedDirection') or None) if match else None,
            twoWay=group['twoWay'] or bool(match and match.get('direction') == 'both') or '양방향' in name))
    if kind in OFFICIAL_KINDS or standalone:
        for item in officials:
            if item['id'] in used or kind not in OFFICIAL_KINDS and not standalone(item):
                continue
            base, hint = official_parts(item['name'])
            places.append(dict(name=base + '휴게소' + ('(' + hint + '방향)' if hint else ''), lat=item['lat'],
                lng=item['lng'], source='official', facilities=dict(item['facilities']), restStop=True,
                routeName=item.get('routeName') or None, direction=item.get('reportedDirection') or None,
                twoWay=item.get('direction') == 'both'))
    required = {'nursing': 'nursing', 'ev_charge': 'evCharger', 'fuel': 'gasStation'}.get(kind)
    if required:
        places = [place for place in places if place['facilities'] and place['facilities'].get(required) is True]
    return places


def filter_facilities(places, required):
    return [place for place in places if all(place['facilities'] and place['facilities'].get(key) is True for key in required)]


def facility_rank(kind, place):
    if kind != 'restroom':
        return 0
    return 0 if place['facilities'] and place['facilities'].get('toilet') is True else 1


def dto(place, verdict, label, from_requester, from_lead):
    return dict(name=place['name'], lat=round(place['lat'], 6), lng=round(place['lng'], 6), verdict=verdict,
        label=label, fromRequesterMeters=from_requester, fromLeadMeters=from_lead, detourSeconds=None,
        detourMeters=None, facilities=place['facilities'], source=place['source'],
        routeName=place.get('routeName'), direction=place.get('direction'))


def car_view(car, state, along):
    return dict(carId=car['carId'], state=state, alongMeters=along)


def heading_candidates(provider, budget, kind, requester, required_facilities=()):
    origin, heading = p(requester), requester['heading']
    steps = [(distance, offset(origin, heading, distance)) for distance in HEADING_STEPS_METERS]
    docs = budget.search(provider, kind, [point for _, point in steps], HEADING_RADIUS_METERS)
    officials = official_items(lambda place: any(meters(place, point) <= HEADING_RADIUS_METERS for _, point in steps))
    result = []
    for place in filter_facilities(merge_official(group_places(docs), officials, kind), required_facilities):
        distance = meters(origin, p(place))
        turn = abs((bearing(origin, p(place)) - heading + 180) % 360 - 180)
        if distance < 1 or turn > HEADING_SPREAD_DEGREES:
            continue
        result.append((facility_rank(kind, place), distance, place))
    result.sort(key=lambda item: (item[0], item[1], item[2]['name']))
    return [dto(place, 'heading', '진행 방향', round(distance), None)
        for _, distance, place in result[:MAX_CANDIDATES]]


def route_candidates(provider, budget, kind, requester, others, destination, required_facilities=()):
    located = [requester] + [car for car in others if car.get('lat') is not None]
    target = (destination['lat'], destination['lng'])
    rear = max(located, key=lambda car: (meters(p(car), target), car is requester))
    angle = lambda car: car.get('heading') if car is requester else None
    try:
        base = budget.route(provider, p(rear), target, angle=angle(rear))
    except CandidateError:
        # 다른 차 위치에서 길을 못 찾으면(국외 좌표·도로 밖 등) 그 차 때문에 검색 전체를 실패시키지 않고
        # 요청한 차 기준으로 다시 찾는다. 그 차는 아래 투영에서 other_road로 표시된다.
        if rear is requester:
            raise
        rear = requester
        base = budget.route(provider, p(rear), target, angle=angle(rear))
    line = Line(base['path'], base.get('roads'))
    spots = {id(car): line.project(p(car)) for car in located}
    if spots[id(requester)][0] > SAME_ROAD_METERS and rear is not requester:
        rear = requester
        base = budget.route(provider, p(rear), target, angle=angle(rear))
        line = Line(base['path'], base.get('roads'))
        spots = {id(car): line.project(p(car)) for car in located}
    same = [car for car in located if spots[id(car)][0] <= SAME_ROAD_METERS] or [requester]
    mine = spots[id(requester)][1]
    leader = max(same, key=lambda car: (spots[id(car)][1], car is requester))
    lead = spots[id(leader)][1]
    cars = []
    for car in [requester] + others:
        if id(car) not in spots:
            cars.append(car_view(car, 'unknown', None))
        elif spots[id(car)][0] <= SAME_ROAD_METERS:
            cars.append(car_view(car, 'same_road', round(spots[id(car)][1] - mine)))
        else:
            cars.append(car_view(car, 'other_road', None))
    start, end = lead + LEAD_GAP_METERS, line.length - ROUTE_END_MARGIN_METERS
    centers, queries, along = [], [], start + SEARCH_STEP_METERS / 2
    while start < end and along - SEARCH_STEP_METERS / 2 < end:
        centers.append(line.at(along))
        highway = line.highway(line.index_at(min(along, line.length)))
        queries.append(HIGHWAY_QUERIES if kind == 'hungry' and highway else QUERIES[kind])
        along += SEARCH_STEP_METERS
    docs = budget.search(provider, kind, centers, SEARCH_RADIUS_METERS, queries) if centers else []
    docs = [doc for doc in docs if line.near(p(doc), SEARCH_RADIUS_METERS)]
    officials = [item for item in official_items(lambda place: line.near(place, OFFICIAL_ROUTE_METERS))
        if line.project(p(item))[0] <= OFFICIAL_ROUTE_METERS]
    ranked = []
    standalone = lambda item: line.highway(line.project(p(item))[3])
    for place in filter_facilities(merge_official(group_places(docs), officials, kind, standalone if kind == 'hungry' else None), required_facilities):
        if budget.expired():
            budget.partial = True
            break
        distance, position, side, index = line.project(p(place))
        if position < start or position > end or side < 0 and not place['twoWay']:
            continue
        if distance > SAME_ROAD_METERS:
            verdict = 'off_route'
        elif line.highway(index) and not place['restStop']:
            verdict = 'off_route'
        else:
            verdict = 'ahead'
        ranked.append(((verdict != 'ahead', facility_rank(kind, place), place['source'] != 'official', position, place['name']),
            dto(place, verdict, LABELS[verdict], round(position - mine), round(position - lead))))
    ranked.sort(key=lambda item: item[0])
    candidates = [item[1] for item in ranked[:MAX_CANDIDATES]]
    for candidate in [item for item in candidates if item['verdict'] == 'ahead'][:DETOUR_CANDIDATES]:
        try:
            via = budget.route(provider, p(rear), target, angle=angle(rear), waypoint=(candidate['lat'], candidate['lng']))
        except (TimeoutError, CandidateError):
            budget.partial = True
            continue
        candidate.update(detourSeconds=round(via['duration'] - base['duration']),
            detourMeters=round(via['distance'] - base['distance']))
        if candidate['detourSeconds'] > MAX_DETOUR_SECONDS:
            candidate.update(verdict='off_route', label='들르면 +%d분' % round(candidate['detourSeconds'] / 60))
    candidates.sort(key=lambda item: item['verdict'] != 'ahead')
    return candidates, cars


def find_candidates(provider, kind, requester, others, destination, *, clock=time.monotonic, timeout=TIMEOUT_SECONDS, required_facilities=()):
    budget = Budget(clock, timeout)
    try:
        if destination is None:
            candidates = heading_candidates(provider, budget, kind, requester, required_facilities)
            cars = [car_view(requester, 'same_road', 0)] + [car_view(car, 'unknown', None) for car in others]
            basis = 'heading'
        else:
            candidates, cars = route_candidates(provider, budget, kind, requester, others, destination, required_facilities)
            basis = 'route'
    except TimeoutError:
        raise CandidateError('CANDIDATES_TIMEOUT', 504) from None
    return dict(basis=basis, partial=budget.partial, candidates=candidates, cars=cars), budget


def fresh_location(value, now):
    if not value:
        return None
    try:
        captured = datetime.fromisoformat(value['capturedAt'].replace('Z', '+00:00'))
        if captured.utcoffset() is None:
            return None
        age = (now - captured.astimezone(timezone.utc)).total_seconds()
    except (KeyError, TypeError, ValueError, AttributeError):
        return None
    if not -30 <= age <= STALE_SECONDS:
        return None
    return dict(lat=value['latitude'], lng=value['longitude'], capturedAt=captured, accuracyMeters=value.get('accuracyMeters'))


def latest_vehicle_location(auth, conn, room, account):
    vehicle = getattr(auth, 'vehicle_service', None)
    if vehicle is None or not getattr(vehicle, 'enabled', False):
        return None
    now = conn.execute('SELECT clock_timestamp()').fetchone()[0]
    best = None
    for (device,) in conn.execute("SELECT g.device_id FROM native_v2_grants g JOIN native_v2_installations i "
            "USING(installation_key_id) JOIN native_device_refs r ON r.device_id=g.device_id AND r.kind='native' "
            "WHERE g.account_id=%s AND g.state='TOKEN_ISSUED' AND i.active_grant_id=g.grant_id "
            "AND i.revoked_at IS NULL AND g.expires_at>%s ORDER BY g.device_id LIMIT 100",
            (account, auth.functional_access.base.now())).fetchall():
        value = fresh_location(vehicle.latest(conn, room, account, device, 'location', trip_context=True), now)
        if value and (best is None or value['capturedAt'] > best['capturedAt']):
            best = value
    return best


def latest_location(auth, conn, room, account):
    from team_trip_locations import latest_member_location
    member = latest_member_location(auth, conn, room, account)
    vehicle = latest_vehicle_location(auth, conn, room, account)
    return max((point for point in (member, vehicle) if point), key=lambda point: point['capturedAt'], default=None)


def trip_cars(auth, conn, trips, context, account, device=None, purposes=frozenset()):
    from team_friends import blocked
    accepted = {peer for peer, member in context['members'].items() if member['state'] == 'accepted'}
    cars, riders = trips.cars(conn, context['tripId']), trips.riders(conn, context['tripId'])
    mine = next((car for car, value in cars.items() if value['driverId'] == account), None) or riders.get(account)
    others = []
    for car, value in cars.items():
        driver = value['driverId']
        if car == mine or driver not in accepted or blocked(conn, driver, account):
            continue
        entry = dict(carId=car)
        people = [driver] + [peer for peer, assigned in sorted(riders.items())
            if assigned == car and peer in accepted and not blocked(conn, peer, account)]
        best = None
        for peer in people:
            if not context['members'][peer].get('locationConsent'):
                continue
            location = latest_location(auth, conn, context['roomId'], peer)
            if location and (best is None or location['capturedAt'] > best['capturedAt']):
                best = location
        if best:
            entry.update(lat=best['lat'], lng=best['lng'])
        others.append(entry)
    return mine, others


class HandRaiseCandidates:
    def __init__(self, provider=None, *, clock=time.monotonic, timeout=TIMEOUT_SECONDS, limit=RATE_PER_MINUTE,
            trip_limit=TRIP_RATE_PER_MINUTE, global_limit=GLOBAL_RATE_PER_MINUTE):
        self.provider, self.clock, self.timeout = provider, clock, timeout
        self.limits = dict(account=limit, trip=trip_limit, all=global_limit)
        self._attempts = dict(account={}, trip={}, all={})
        self._lock = Lock()

    @classmethod
    def from_environment(cls):
        key = load_key()
        return cls(KakaoHandRaiseProvider(key) if key else None)

    def admit(self, account, trip):
        try:
            if self.provider is None:
                raise CandidateError()
            now = self.clock()
            scopes = (('account', account), ('trip', trip), ('all', 'all'))
            with self._lock:
                windows = []
                for scope, key in scopes:
                    attempts = self._attempts[scope]
                    for stale in [k for k, hits in attempts.items() if not hits or hits[-1] <= now - 60]:
                        del attempts[stale]
                    hits = attempts.setdefault(key, deque())
                    while hits and hits[0] <= now - 60:
                        hits.popleft()
                    if len(hits) >= self.limits[scope]:
                        raise CandidateError('CANDIDATES_RATE_LIMITED', 429)
                    windows.append(hits)
                for hits in windows:
                    hits.append(now)
        except CandidateError as error:
            LOG.info('trip.signal.candidates: failed reason=%s', error.code)
            raise

    def find(self, kind, requester, others, destination, *, required_facilities=()):
        if not _SLOTS.acquire(blocking=False):
            LOG.info('trip.signal.candidates: failed reason=CANDIDATES_BUSY')
            raise CandidateError('CANDIDATES_BUSY', 503)
        try:
            result, budget = find_candidates(self.provider, kind, requester, others, destination,
                clock=self.clock, timeout=self.timeout, required_facilities=required_facilities)
        except CandidateError as error:
            LOG.info('trip.signal.candidates: failed reason=%s', error.code)
            raise
        except Exception:
            LOG.info('trip.signal.candidates: failed reason=CANDIDATES_PROVIDER_UNAVAILABLE')
            raise CandidateError('CANDIDATES_PROVIDER_UNAVAILABLE', 502) from None
        finally:
            _SLOTS.release()
        LOG.info('trip.signal.candidates: loaded basis=%s kind=%s count=%d search_calls=%d direction_calls=%d partial=%s',
            result['basis'], kind, len(result['candidates']), budget.searches, budget.routes, str(result['partial']).lower())
        return result
