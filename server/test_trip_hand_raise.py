"""Deterministic hand-raise candidate rules on the verified Seoul→Asan scenario; fake Kakao transports only."""
import json
import logging
import unittest
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlsplit

import team_trip_hand_raise as hand
from team_trip_hand_raise import CandidateError, HandRaiseCandidates, KakaoHandRaiseProvider, candidate_input

KEY = 'synthetic-kakao-key-0001'
DESTINATION = dict(lat=36.7696847, lng=126.9318116)
REQUESTER = (37.271913, 126.89483)
LEAD = (37.247489, 126.88281)
REAR = (37.306134, 126.89654)
FOOD = (
    ('화성휴게소 목포방향 푸드코트', 37.14255, 126.87935, 'FD6'),
    ('국도변 손칼국수', 37.1601, 126.8589, 'FD6'),
    ('투썸플레이스 화성휴게소 목포방향점', 37.14262, 126.87925, 'CE7'),
)
PATH = (
    (37.306134, 126.89654), (37.298846, 126.900572), (37.295594, 126.901668), (37.291272, 126.901956),
    (37.285861, 126.900558), (37.280082, 126.898251), (37.271913, 126.89483), (37.266757, 126.891703),
    (37.260104, 126.886615), (37.254973, 126.8843), (37.247489, 126.88281), (37.240062, 126.881545),
    (37.234754, 126.879606), (37.22415, 126.87414), (37.215491, 126.871249), (37.211144, 126.869928),
    (37.20024, 126.870823), (37.190017, 126.872248), (37.183393, 126.873045), (37.174124, 126.873397),
    (37.164129, 126.874175), (37.156961, 126.876545), (37.148096, 126.879591), (37.144226, 126.880132),
    (37.140405, 126.880009), (37.130781, 126.880038), (37.123952, 126.882052), (37.114667, 126.885541),
    (37.10707, 126.888274), (37.098947, 126.88882), (37.094088, 126.887631), (37.087389, 126.886312),
    (37.082715, 126.886594), (37.07611, 126.887556), (37.071692, 126.88824), (37.063557, 126.889415),
    (37.059196, 126.889479), (37.054998, 126.888629), (37.053335, 126.888058), (37.049216, 126.886128),
    (37.047333, 126.885166), (37.044898, 126.883931), (37.04104, 126.881965), (37.034775, 126.878797),
    (37.030756, 126.876923), (37.026249, 126.874854), (37.021607, 126.872798), (37.019473, 126.872021),
    (37.016843, 126.871284), (37.014297, 126.870771), (37.00492, 126.869236), (37.002277, 126.868971),
    (36.998222, 126.868942), (36.995386, 126.869163), (36.978261, 126.870697), (36.973126, 126.870863),
    (36.972483, 126.870468), (36.971561, 126.869224), (36.970915, 126.868638), (36.970202, 126.868525),
    (36.969547, 126.868827), (36.969023, 126.869542), (36.967617, 126.872393), (36.965843, 126.875339),
    (36.964498, 126.877055), (36.963258, 126.878353), (36.96206, 126.87937), (36.96052, 126.880459),
    (36.958092, 126.881943), (36.956705, 126.883008), (36.955544, 126.88408), (36.954073, 126.88573),
    (36.9521, 126.888644), (36.951038, 126.890782), (36.949073, 126.895514), (36.946606, 126.901556),
    (36.943468, 126.909146), (36.942857, 126.910412), (36.941952, 126.911918), (36.940401, 126.913781),
    (36.93923, 126.914808), (36.938155, 126.91553), (36.936819, 126.916201), (36.935076, 126.916742),
    (36.933104, 126.916949), (36.930957, 126.916699), (36.928102, 126.915897), (36.924289, 126.914762),
    (36.921009, 126.913764), (36.917982, 126.912876), (36.916527, 126.912436), (36.91219, 126.911151),
    (36.908512, 126.910059), (36.907275, 126.909762), (36.905823, 126.909704), (36.904042, 126.910022),
    (36.898718, 126.911197), (36.895194, 126.912144), (36.893337, 126.913001), (36.890632, 126.914801),
    (36.88764, 126.917726), (36.886272, 126.918946), (36.88475, 126.919966), (36.882694, 126.920825),
    (36.881228, 126.921171), (36.878446, 126.921457), (36.875754, 126.921708), (36.873701, 126.921894),
    (36.872781, 126.921794), (36.872202, 126.921578), (36.872027, 126.921177), (36.872185, 126.92067),
    (36.872625, 126.920451), (36.873086, 126.920635), (36.873453, 126.921347), (36.874114, 126.92375),
    (36.874765, 126.924941), (36.876223, 126.926737), (36.877982, 126.928934), (36.878591, 126.929475),
    (36.878814, 126.930212), (36.878638, 126.93174), (36.877901, 126.933971), (36.87568, 126.937547),
    (36.873002, 126.941364), (36.870628, 126.943976), (36.868714, 126.945606), (36.863706, 126.950913),
    (36.860017, 126.955639), (36.854406, 126.95917), (36.853348, 126.959711), (36.844289, 126.964588),
    (36.840718, 126.966374), (36.839655, 126.966388), (36.836812, 126.965978), (36.834848, 126.965937),
    (36.833347, 126.966428), (36.832062, 126.966894), (36.829898, 126.967719), (36.826251, 126.969102),
    (36.823985, 126.969715), (36.817767, 126.970684), (36.81524, 126.971334), (36.813186, 126.97348),
    (36.811308, 126.976172), (36.810617, 126.976574), (36.810083, 126.976244), (36.809758, 126.975151),
    (36.808971, 126.966453), (36.808791, 126.965481), (36.808111, 126.962935), (36.805224, 126.956339),
    (36.801262, 126.945478), (36.80012, 126.943668), (36.798967, 126.942697), (36.79605, 126.941057),
    (36.791733, 126.938909), (36.786633, 126.938049), (36.782955, 126.937842), (36.781305, 126.937775),
    (36.780102, 126.937209), (36.779062, 126.936899), (36.777688, 126.935394), (36.776759, 126.934276),
    (36.774806, 126.932533), (36.772981, 126.930956), (36.771354, 126.9295), (36.769596, 126.927363),
    (36.768389, 126.928422), (36.769201, 126.930572), (36.769052, 126.931056),
)
DOCS = (
    ('자안졸음쉼터', 37.213837, 126.873391),
    ('남양졸음쉼터 송산방향', 37.188314, 126.838457),
    ('남양졸음쉼터 봉담방향', 37.187864, 126.838339),
    ('남양졸음쉼터 전기차충전소', 37.184463, 126.837546),
    ('화성휴게소 서울방향', 37.14357, 126.881221),
    ('얌샘김밥 화성휴게소점', 37.14357, 126.881223),
    ('할리스 화성휴게소시흥방향점', 37.143537, 126.881244),
    ('화성휴게소 서울방향 주차장', 37.143508, 126.880757),
    ('못난이꽈배기 화성휴게소서울방향점', 37.143495, 126.88111),
    ('로보시타 카페 화성휴게소점', 37.143292, 126.879188),
    ('화성휴게소 피크닉존', 37.14304, 126.881258),
    ('화성로컬푸드직매장 휴게소점', 37.142786, 126.881277),
    ('화성휴게소주유소 목포방향', 37.142642, 126.879305),
    ('린데수소충전소 화성휴게소 목포방향', 37.142593, 126.879819),
    ('화성휴게소충전소 목포방향', 37.142259, 126.879463),
    ('발안휴게소푸드존', 37.134601, 126.895892),
    ('발안휴게소', 37.134598, 126.895924),
    ('이마트24 R발안휴게소점', 37.134578, 126.89592),
    ('휴게소 화성향남점', 37.117965, 126.914899),
    ('CU E평택호휴게소점', 36.924564, 126.9178),
    ('파스쿠찌 평택호휴게소점', 36.92456, 126.917809),
    ('평택호휴게소', 36.924553, 126.917816),
    ('블랙야크 평택호휴게소점', 36.924553, 126.917816),
    ('공차 평택호휴게소 양방향점', 36.924553, 126.917816),
    ('수누리감자탕 평택호휴게소점', 36.924553, 126.917816),
    ('평택시로컬푸드직매장 평택호휴게소점', 36.924553, 126.917816),
    ('무궁화반점 평택호휴게소점', 36.924553, 126.917816),
    ('노브랜드버거 평택호휴게소점', 36.924553, 126.917816),
    ('잠바주스 평택호휴게소점', 36.924553, 126.917816),
    ('33떡볶이 평택호휴게소 평택방향점', 36.924553, 126.917816),
    ('153포인츠부대찌개 평택호휴게소점', 36.924553, 126.917816),
    ('청담강정 평택호휴게소점', 36.924553, 126.917816),
    ('참바다휴 평택호휴게소', 36.924553, 126.917816),
    ('KH에너지 평택호휴게소충전소 익산방향', 36.924591, 126.917373),
    ('세븐일레븐 아산인주휴게소점', 36.875673, 126.89446),
    ('한솔휴게소', 36.864625, 126.94822),
    ('서해안만남의광장', 36.859625, 126.954476),
    ('GS25 아산염치휴게소점', 36.843091, 126.965733),
    ('염치휴게소', 36.838932, 126.966606),
    ('양평해장국 염치휴게소점', 36.8389, 126.96665),
    ('세븐일레븐 아산염치휴게소점', 36.838828, 126.966659),
    ('이순신휴게소', 36.830028, 126.967244),
    ('동춘당꽈배기 이순신휴게소점', 36.830028, 126.967244),
    ('이순신휴게소주유소', 36.829579, 126.967403),
)


HIGHWAY_END = 112
DETOURS = {(37.143612, 126.87908): (82, 35), (36.924553, 126.917816): (400, 4200)}


def road_name(index):
    return '서해안고속도로' if index < HIGHWAY_END else '아산로'


def beside(index, meters):
    travel = hand.bearing(PATH[index], PATH[index + 1])
    return hand.offset(PATH[index], travel + 90, meters)


FOOD = FOOD + (
    ('다미향웰빙한식뷔페',) + tuple(round(v, 6) for v in beside(104, 120)) + ('FD6',),
    ('아산로 한우국밥',) + tuple(round(v, 6) for v in beside(130, 80)) + ('FD6',),
)


class FakeKakao:
    def __init__(self, *, fail_search=False, slow=None, leak=False):
        self.calls, self.fail_search, self.slow, self.leak = [], fail_search, slow, leak

    def search(self, url, headers, timeout, maximum):
        assert headers == {'Authorization': 'KakaoAK ' + KEY} and 0 < timeout <= hand.CALL_TIMEOUT_SECONDS
        target = urlsplit(url)
        query = parse_qs(target.query)
        term = query.get('query', query.get('category_group_code'))[0]
        self.calls.append(('search', target.path.rsplit('/', 1)[-1], term, (float(query['y'][0]), float(query['x'][0]))))
        if self.slow:
            self.slow()
        if self.fail_search:
            raise TimeoutError()
        center, radius = (float(query['y'][0]), float(query['x'][0])), float(query['radius'][0])
        if term in ('FD6', 'CE7'):
            pool = [(name, lat, lng) for name, lat, lng, code in FOOD if code == term]
        else:
            pool = [doc for doc in DOCS if term in doc[0] or term == '휴게소' and ('졸음쉼터' in doc[0] or '만남의광장' in doc[0])]
        pool = sorted((doc for doc in pool if hand.meters(center, doc[1:]) <= radius), key=lambda doc: hand.meters(center, doc[1:]))
        documents = [dict(id=str(1000 + (DOCS + tuple(item[:3] for item in FOOD)).index(doc)), place_name=doc[0],
            x=str(doc[2]), y=str(doc[1])) for doc in pool[:15]]
        raw = json.dumps(dict(documents=documents), ensure_ascii=False)
        return (raw + (KEY if self.leak else '')).encode()

    def directions(self, url, headers, timeout, maximum):
        assert headers == {'Authorization': 'KakaoAK ' + KEY}
        query = parse_qs(urlsplit(url).query)
        origin = query['origin'][0].split(',')
        waypoint = query.get('waypoints', [None])[0]
        self.calls.append(('directions', ','.join(origin[2:]) or None, waypoint))
        start = (float(origin[1]), float(origin[0]))
        if not (32 <= start[0] <= 39 and 124 <= start[1] <= 132):
            raise OSError('origin outside the Korean road network')
        if hand.meters(start, PATH[0]) < 50:
            path, names = PATH, [road_name(index) for index in range(len(PATH))]
        else:
            index = min(range(len(PATH)), key=lambda i: hand.meters(PATH[i], start))
            if hand.meters(PATH[index], start) < 400:
                path = (start,) + PATH[index + 1:]
                names = [road_name(index)] + [road_name(i) for i in range(index + 1, len(PATH))]
            else:
                path, names = (start, (37.30, 126.70), (36.80, 126.70), PATH[-1]), ['서부로'] * 4
        extra = (0, 0)
        if waypoint:
            lng, lat = map(float, waypoint.split(','))
            extra = DETOURS.get(min(DETOURS, key=lambda key: hand.meters((lat, lng), key)), (240, 1800))
            if min(hand.meters((lat, lng), key) for key in DETOURS) > 500:
                extra = (240, 1800)
        roads = []
        for (lat, lng), name in zip(path, names):
            if not roads or roads[-1]['name'] != name:
                roads.append(dict(name=name, vertexes=list(roads[-1]['vertexes'][-2:]) if roads else []))
            roads[-1]['vertexes'] += [lng, lat]
        return json.dumps(dict(routes=[dict(result_code=0, summary=dict(distance=69772 + extra[1], duration=3385 + extra[0]),
            sections=[dict(roads=roads)])]), ensure_ascii=False).encode()

    def provider(self):
        return KakaoHandRaiseProvider(KEY, search_transport=self.search, directions_transport=self.directions)


def cars(*extra):
    return [dict(carId='b' * 32, lat=LEAD[0], lng=LEAD[1]),
        dict(carId='c' * 32, lat=REAR[0], lng=REAR[1]), *extra]


def requester(heading=205):
    return dict(carId='a' * 32, lat=REQUESTER[0], lng=REQUESTER[1], heading=heading)


def run(fake, kind='restroom', others=None, destination=DESTINATION, **kwargs):
    result, budget = hand.find_candidates(fake.provider(), kind, requester(), cars() if others is None else others,
        destination, **kwargs)
    return result, budget


class HandRaiseRuleTests(unittest.TestCase):
    def test_facility_filters_are_and_after_official_merge_and_reject_invalid_inputs(self):
        for required in (None, ['unsupported'], ['toilet', 'toilet'], [True]):
            with self.subTest(required=required), self.assertRaises(CandidateError) as error:
                candidate_input(dict(kind='cafe', location=dict(lat=37.27, lng=126.89, heading=205), requiredFacilities=required))
            self.assertEqual((error.exception.status, error.exception.code), (400, 'DISCOVERY_FACILITY_INVALID'))
        places = [dict(name='서산휴게소', facilities=dict(toilet=True, nursing=True)),
                  dict(name='홍성휴게소', facilities=dict(toilet=True, nursing=False)),
                  dict(name='카페', facilities=None)]
        self.assertEqual([p['name'] for p in hand.filter_facilities(places, ('toilet', 'nursing'))], ['서산휴게소'])
        self.assertEqual(hand.filter_facilities(places, ()), places)
        fake = FakeKakao()
        run(fake, kind='cafe')
        self.assertTrue(any(call[0] == 'search' and call[1] == 'category.json' and call[2] == 'CE7' for call in fake.calls), fake.calls)
        required, _ = run(FakeKakao(), required_facilities=('toilet', 'nursing'))
        self.assertTrue(all(row['facilities'] and row['facilities'].get('toilet') is True and
            row['facilities'].get('nursing') is True for row in required['candidates']))
        for kind, facility in (('ev_charge', 'evCharger'), ('fuel', 'gasStation')):
            result, _ = run(FakeKakao(), kind=kind)
            self.assertTrue(all(row['facilities'] and row['facilities'].get(facility) is True for row in result['candidates']))

    def test_reference_route_verdicts_for_restroom(self):
        fake = FakeKakao()
        result, budget = run(fake)
        names = [item['name'] for item in result['candidates']]
        self.assertEqual((result['basis'], result['partial']), ('route', False))
        first = result['candidates'][0]
        self.assertEqual((first['name'], first['verdict'], first['source']), ('화성휴게소(목포방향)', 'ahead', 'official'))
        self.assertEqual((first['detourSeconds'], first['detourMeters']), (82, 35))
        self.assertTrue(first['facilities']['toilet'])
        self.assertEqual(first['label'], '모든 차 앞쪽')
        self.assertTrue(13000 < first['fromRequesterMeters'] < 16000 and 10000 < first['fromLeadMeters'] < 13000)
        self.assertFalse(any('매송' in name for name in names))
        self.assertFalse(any('서울방향' in name or '시흥' in name or '익산' in name or '염치' in name or '자안' in name for name in names))
        ahead = [item['name'] for item in result['candidates'] if item['verdict'] == 'ahead']
        self.assertEqual(ahead, ['화성휴게소(목포방향)', '한솔휴게소', '서해안만남의광장', '이순신휴게소'])
        pyeongtaek = next(item for item in result['candidates'] if item['name'] == '평택호휴게소')
        self.assertEqual((pyeongtaek['verdict'], pyeongtaek['label'], pyeongtaek['detourSeconds'], pyeongtaek['source']),
            ('off_route', '들르면 +7분', 400, 'kakao'))
        self.assertEqual(result['candidates'].index(pyeongtaek), len(ahead))
        self.assertEqual({item['name'] for item in result['candidates'] if item['detourSeconds'] is not None},
            {'화성휴게소(목포방향)', '평택호휴게소'})
        off = [item for item in result['candidates'] if item['verdict'] == 'off_route']
        self.assertTrue(off and all(item['label'] == '경로 벗어남' for item in off if item['detourSeconds'] is None))
        self.assertIn('남양졸음쉼터(송산방향)', [item['name'] for item in off])
        self.assertFalse(any('발안' in name or '향남' in name for name in names))
        for store in ('로보시타', '얌샘김밥', '공차', '이마트24', '이순신휴게소주유소', 'CU'):
            self.assertFalse(any(store in name for name in names), store)
        self.assertEqual(result['cars'][0], dict(carId='a' * 32, state='same_road', alongMeters=0))
        self.assertEqual(result['cars'][1]['state'], 'same_road')
        self.assertTrue(2500 < result['cars'][1]['alongMeters'] < 3500)
        self.assertEqual(result['cars'][2]['state'], 'same_road')
        self.assertTrue(-4500 < result['cars'][2]['alongMeters'] < -3500)
        self.assertEqual((budget.routes, budget.searches), (3, 11))
        self.assertEqual(fake.calls[0], ('directions', None, None))
        self.assertTrue(all(call[2] == '휴게소' for call in fake.calls if call[0] == 'search'))
        self.assertLessEqual(len(result['candidates']), hand.MAX_CANDIDATES)
        self.assertEqual(set(first), {'name', 'lat', 'lng', 'verdict', 'label', 'fromRequesterMeters', 'fromLeadMeters',
            'detourSeconds', 'detourMeters', 'facilities', 'source', 'routeName', 'direction'})
        self.assertEqual((first['routeName'], first['direction']), ('서해안선', '하행'))
        self.assertIsNone(pyeongtaek['routeName'])
        self.assertIsNone(pyeongtaek['direction'])

    def test_store_grouping_two_way_and_official_matching(self):
        docs = [dict(id='kakao-%d' % index, name=name, lat=lat, lng=lng) for index, (name, lat, lng) in enumerate(DOCS)]
        groups = hand.group_places(docs)
        pyeongtaek = [group for group in groups if group['stem'] == '평택호휴게소']
        self.assertEqual(sorted(len(group['members']) for group in pyeongtaek), [1, 14])
        self.assertTrue(next(group for group in pyeongtaek if len(group['members']) == 14)['twoWay'])
        hwaseong = {group['direction']: sorted(member['name'] for member in group['members'])
            for group in groups if group['stem'] == '화성휴게소'}
        self.assertEqual(set(hwaseong), {'서울', '시흥', '목포'})
        self.assertIn('로보시타 카페 화성휴게소점', hwaseong['목포'])
        self.assertIn('얌샘김밥 화성휴게소점', hwaseong['서울'])
        self.assertEqual(len(hwaseong['목포']), 4)
        officials = hand.official_items(lambda place: hand.meters(place, (37.1436, 126.88)) < 1000)
        places = hand.merge_official(groups, officials, 'restroom')
        matched = {place['name']: place['source'] for place in places if place['name'].startswith('화성휴게소')}
        self.assertEqual(matched, {'화성휴게소(서울방향)': 'official', '화성휴게소(시흥방향)': 'kakao', '화성휴게소(목포방향)': 'official'})

    def test_other_road_car_and_unknown_location_are_excluded(self):
        parallel = dict(carId='d' * 32, lat=37.2475, lng=126.86)
        unknown = dict(carId='e' * 32)
        result, _ = run(FakeKakao(), others=cars(parallel, unknown))
        states = {car['carId'][0]: (car['state'], car['alongMeters']) for car in result['cars']}
        self.assertEqual(states['d'], ('other_road', None))
        self.assertEqual(states['e'], ('unknown', None))
        self.assertEqual(result['candidates'][0]['name'], '화성휴게소(목포방향)')
        self.assertTrue(10000 < result['candidates'][0]['fromLeadMeters'] < 13000)

    def test_rear_on_other_road_reroutes_from_requester_within_direction_limit(self):
        fake = FakeKakao()
        far = dict(carId='d' * 32, lat=37.33, lng=126.80)
        result, budget = run(fake, others=cars(far))
        self.assertEqual(fake.calls[0][:2], ('directions', None))
        self.assertEqual(fake.calls[1], ('directions', 'angle=205', None))
        states = {car['carId'][0]: car['state'] for car in result['cars']}
        self.assertEqual((states['a'], states['b'], states['d']), ('same_road', 'same_road', 'other_road'))
        self.assertEqual(budget.routes, hand.MAX_DIRECTION_CALLS)
        self.assertTrue(result['partial'])
        ahead = [item for item in result['candidates'] if item['verdict'] == 'ahead']
        self.assertEqual(ahead[0]['detourSeconds'], 82)
        self.assertIsNone(ahead[1]['detourSeconds'])

    def test_unroutable_rear_car_falls_back_to_requester(self):
        fake = FakeKakao()
        abroad = dict(carId='d' * 32, lat=37.4220, lng=-122.0841)
        result, _ = run(fake, others=cars(abroad))
        self.assertEqual(fake.calls[0][:2], ('directions', None))
        self.assertEqual(fake.calls[1], ('directions', 'angle=205', None))
        states = {car['carId'][0]: car['state'] for car in result['cars']}
        self.assertEqual((states['a'], states['b'], states['d']), ('same_road', 'same_road', 'other_road'))
        self.assertEqual(result['candidates'][0]['verdict'], 'ahead')

    def test_unroutable_requester_still_fails(self):
        fake = FakeKakao()
        with self.assertRaises(CandidateError) as error:
            hand.find_candidates(fake.provider(), 'restroom', dict(requester(), lat=37.4220, lng=-122.0841), cars(),
                DESTINATION)
        self.assertEqual((error.exception.code, error.exception.status), ('CANDIDATES_PROVIDER_UNAVAILABLE', 502))

    def test_cars_without_shared_location_never_shape_the_route(self):
        fake = FakeKakao()
        result, _ = run(fake, others=[dict(carId='b' * 32), dict(carId='c' * 32)])
        self.assertEqual(fake.calls[0], ('directions', 'angle=205', None))
        self.assertEqual(result['cars'][1:], [dict(carId='b' * 32, state='unknown', alongMeters=None),
            dict(carId='c' * 32, state='unknown', alongMeters=None)])
        first = result['candidates'][0]
        self.assertEqual((first['name'], first['fromLeadMeters']), ('화성휴게소(목포방향)', first['fromRequesterMeters']))

    def test_direction_is_checked_before_distance(self):
        names = [item['name'] for item in run(FakeKakao())[0]['candidates']]
        self.assertNotIn('발안휴게소', names)
        self.assertNotIn('휴게소 화성향남점', names)
        self.assertIn('남양졸음쉼터(송산방향)', names)

    def test_same_place_with_different_names_is_one_candidate(self):
        docs = [dict(id='kakao-1', name='신창휴게소', lat=36.86, lng=126.95),
            dict(id='kakao-2', name='아산신창휴게소', lat=36.8601, lng=126.9501),
            dict(id='kakao-3', name='GS25 아산신창휴게소점', lat=36.8602, lng=126.9502),
            dict(id='kakao-4', name='신창휴게소', lat=36.90, lng=126.95)]
        groups = hand.group_places(docs)
        self.assertEqual(sorted(len(group['members']) for group in groups), [1, 3])
        merged = next(group for group in groups if len(group['members']) == 3)
        self.assertEqual((merged['stem'], merged['aliases']), ('신창휴게소', {'신창휴게소', '아산신창휴게소'}))
        official = dict(id='rest-x', name='아산신창', lat=36.8603, lng=126.9503, direction='both',
            facilities=dict(toilet=True, nursing=True))
        places = hand.merge_official(groups, [official], 'restroom')
        self.assertEqual([(place['name'], place['source']) for place in places],
            [('신창휴게소', 'official'), ('신창휴게소', 'kakao')])

    def test_projection_index_matches_full_scan_and_stays_fast(self):
        import random, time
        rng = random.Random(7)
        path, point = [], (37.5, 126.9)
        for _ in range(hand.MAX_PATH_POINTS):
            point = hand.offset(point, 160 + rng.uniform(-40, 40), 120)
            path.append(point)
        line = hand.Line(path)
        def full(target):
            best = None
            px, py = line.local(target)
            for index in range(len(path) - 1):
                best = line.segment(px, py, index, best)
            return best
        targets = [hand.offset(path[rng.randrange(len(path))], rng.uniform(0, 360), rng.uniform(0, 5000)) for _ in range(200)]
        for target in targets[:40]:
            self.assertAlmostEqual(line.project(target)[0], full(target)[0], places=6)
        began = time.perf_counter()
        for target in targets:
            line.project(target)
        self.assertLess(time.perf_counter() - began, 1.0)
        self.assertFalse(line.near((33.0, 126.0), 4000))

    def test_unknown_only_cars_use_requester_as_rear_with_angle(self):
        fake = FakeKakao()
        result, _ = run(fake, others=[dict(carId='e' * 32)])
        self.assertEqual(fake.calls[0], ('directions', 'angle=205', None))
        self.assertEqual(result['cars'][1]['state'], 'unknown')
        self.assertEqual(result['candidates'][0]['name'], '화성휴게소(목포방향)')
        self.assertTrue(result['candidates'][0]['fromLeadMeters'] > 14000)

    def test_kind_queries_nursing_drowsy_and_hungry_call_limit(self):
        nursing, _ = run(FakeKakao(), 'nursing')
        self.assertTrue(nursing['candidates'])
        self.assertTrue(all(item['facilities'] and item['facilities']['nursing'] for item in nursing['candidates']))
        fake = FakeKakao()
        drowsy, _ = run(fake, 'drowsy')
        self.assertTrue(all(call[2] == '졸음쉼터' for call in fake.calls if call[0] == 'search'))
        self.assertIn('화성휴게소(목포방향)', [item['name'] for item in drowsy['candidates']])
        self.assertIn('남양졸음쉼터(송산방향)', [item['name'] for item in drowsy['candidates']])
        fake = FakeKakao()
        hungry, budget = run(fake, 'hungry')
        searches = [call for call in fake.calls if call[0] == 'search']
        self.assertEqual(len(searches), hand.MAX_SEARCH_CALLS)
        self.assertTrue(hungry['partial'])
        line = hand.Line(PATH)
        for call in searches:
            highway = line.project(call[3])[3] < HIGHWAY_END - 1
            self.assertEqual(call[1] == 'category.json', not highway and call[2] in ('FD6', 'CE7'))
            if highway:
                self.assertEqual(call[2], '휴게소')
        self.assertEqual([call[2] for call in searches if call[1] == 'category.json'][:2], ['FD6', 'CE7'])
        names = [item['name'] for item in hungry['candidates']]
        self.assertEqual(names[0], '화성휴게소(목포방향)')
        self.assertFalse(any('푸드코트' in name or '투썸' in name or '손칼국수' in name for name in names))
        ahead = [item['name'] for item in hungry['candidates'] if item['verdict'] == 'ahead']
        self.assertIn('아산로 한우국밥', ahead)
        self.assertNotIn('다미향웰빙한식뷔페', ahead)
        from unittest.mock import patch
        with patch.object(hand, 'MAX_CANDIDATES', 30):
            everything, _ = run(FakeKakao(), 'hungry')
        buffet = next(item for item in everything['candidates'] if item['name'] == '다미향웰빙한식뷔페')
        self.assertEqual((buffet['verdict'], buffet['label']), ('off_route', '경로 벗어남'))
        self.assertLess(line.project((buffet['lat'], buffet['lng']))[0], hand.SAME_ROAD_METERS)

    def test_heading_mode_without_destination(self):
        fake = FakeKakao()
        result, budget = run(fake, destination=None)
        self.assertEqual(result['basis'], 'heading')
        self.assertEqual(budget.routes, 0)
        self.assertEqual(len([call for call in fake.calls if call[0] == 'search']), 3)
        labels = {item['name']: item['label'] for item in result['candidates']}
        self.assertEqual(labels['매송휴게소(목포방향)'], '진행 방향')
        self.assertEqual(labels['자안졸음쉼터'], '진행 방향')
        self.assertEqual(labels['남양졸음쉼터(송산방향)'], '진행 방향')
        self.assertTrue(all(item['verdict'] == 'heading' and item['fromLeadMeters'] is None
            and item['detourSeconds'] is None for item in result['candidates']))
        self.assertEqual([car['state'] for car in result['cars']], ['same_road', 'unknown', 'unknown'])
        behind, _ = hand.find_candidates(fake.provider(), 'restroom', requester(25), cars(), None)
        self.assertFalse(any('매송' in item['name'] for item in behind['candidates']))

    def test_search_timeout_returns_partial_and_route_timeout_fails(self):
        now = [0.0]
        clock = lambda: now[0]
        def tick():
            now[0] += 2.5
        fake = FakeKakao(slow=tick)
        result, budget = run(fake, clock=clock, timeout=hand.TIMEOUT_SECONDS)
        self.assertTrue(result['partial'])
        self.assertLess(budget.searches, 10)
        failing = FakeKakao(fail_search=True)
        result, _ = run(failing)
        self.assertTrue(result['partial'])
        self.assertEqual([item['name'] for item in result['candidates'] if item['verdict'] == 'ahead'], ['화성휴게소(목포방향)'])
        with self.assertRaises(CandidateError) as error:
            run(FakeKakao(), clock=lambda: 0.0, timeout=0)
        self.assertEqual((error.exception.code, error.exception.status), ('CANDIDATES_TIMEOUT', 504))

    def test_key_reflection_and_bad_route_are_provider_errors(self):
        result, _ = run(FakeKakao(leak=True))
        self.assertTrue(result['partial'])
        self.assertEqual([item['source'] for item in result['candidates']], ['official'] * len(result['candidates']))
        provider = KakaoHandRaiseProvider(KEY, directions_transport=lambda *args: b'{"routes":[{"result_code":104}]}')
        with self.assertRaises(CandidateError) as error:
            provider.directions(REQUESTER, (36.7, 126.9), timeout=1)
        self.assertEqual((error.exception.code, error.exception.status), ('CANDIDATES_ROUTE_NOT_FOUND', 422))
        provider = KakaoHandRaiseProvider(KEY, directions_transport=lambda *args: KEY.encode())
        with self.assertRaises(CandidateError) as error:
            provider.directions(REQUESTER, (36.7, 126.9), timeout=1)
        self.assertEqual(error.exception.code, 'CANDIDATES_PROVIDER_UNAVAILABLE')
        self.assertNotIn(KEY, str(error.exception))

    def test_input_validation(self):
        location = dict(lat=37.27, lng=126.89, heading=205)
        self.assertEqual(candidate_input(dict(kind='hungry', location=location, destination=DESTINATION))[0], 'hungry')
        self.assertEqual(candidate_input(dict(kind='rest', location=dict(location, heading=360), destination=None))[1]['heading'], 0)
        for data, code in (
                (dict(kind='arrived', location=location, destination=None), 'Invalid hand-raise kind'),
                (dict(kind='join', location=location, destination=None), 'Invalid hand-raise kind'),
                (dict(kind=['rest'], location=location, destination=None), 'Invalid hand-raise kind'),
                (dict(kind='rest', location=dict(location, lat=True), destination=None), 'Invalid location'),
                (dict(kind='rest', location=dict(location, heading=361), destination=None), 'Invalid location'),
                (dict(kind='rest', location=dict(location, speed=3), destination=None), 'Invalid location'),
                (dict(kind='rest', location=dict(lat=10, lng=126.9), destination=None), 'Invalid location'),
                (dict(kind='rest', location=location, destination=dict(lat=36.7, lng=126.9, name='x')), 'Invalid destination'),
                (dict(kind='rest', location=dict(lat=37.27, lng=126.89), destination=None), 'Choose a destination or heading'),
                (dict(kind='rest', location=dict(lat=37.27, lng=126.89, heading=None)), 'Choose a destination or heading')):
            with self.subTest(data=data), self.assertRaises(CandidateError) as error:
                candidate_input(data)
            self.assertEqual((error.exception.status, error.exception.code), (400, code))

    def test_stale_reports_are_unknown(self):
        now = datetime(2026, 11, 8, 12, tzinfo=timezone.utc)
        value = lambda age: dict(latitude=37.2, longitude=126.9, capturedAt=(now - timedelta(seconds=age)).isoformat())
        self.assertEqual(hand.fresh_location(value(hand.STALE_SECONDS), now)['lat'], 37.2)
        self.assertIsNone(hand.fresh_location(value(hand.STALE_SECONDS + 1), now))
        self.assertIsNone(hand.fresh_location(value(-31), now))
        self.assertIsNone(hand.fresh_location(dict(value(0), capturedAt='2026-11-08T12:00:00'), now))
        self.assertIsNone(hand.fresh_location(None, now))

    def test_service_rate_limit_unavailable_and_logs_without_coordinates(self):
        with self.assertRaises(CandidateError) as error:
            HandRaiseCandidates(None).admit('team-' + 'a' * 40, 'f' * 32)
        self.assertEqual((error.exception.code, error.exception.status), ('CANDIDATES_UNAVAILABLE', 503))
        self.assertEqual((hand.TRIP_RATE_PER_MINUTE, hand.GLOBAL_RATE_PER_MINUTE), (30, 120))
        service = HandRaiseCandidates(FakeKakao().provider(), limit=2, trip_limit=3, global_limit=4)
        for _ in range(2):
            service.admit('team-' + 'a' * 40, 'f' * 32)
        with self.assertRaises(CandidateError) as error:
            service.admit('team-' + 'a' * 40, 'f' * 32)
        self.assertEqual(error.exception.status, 429)
        service.admit('team-' + 'b' * 40, 'f' * 32)
        with self.assertRaises(CandidateError):
            service.admit('team-' + 'c' * 40, 'f' * 32)
        service.admit('team-' + 'c' * 40, 'e' * 32)
        with self.assertRaises(CandidateError) as error:
            service.admit('team-' + 'd' * 40, 'd' * 32)
        self.assertEqual(error.exception.code, 'CANDIDATES_RATE_LIMITED')
        with self.assertLogs('team_trip_hand_raise', logging.INFO) as logs:
            result = service.find('restroom', requester(), cars(), DESTINATION)
        self.assertEqual(result['candidates'][0]['name'], '화성휴게소(목포방향)')
        text = '\n'.join(logs.output)
        self.assertIn('trip.signal.candidates: loaded basis=route kind=restroom', text)
        for value in ('37.', '126.', '36.', KEY):
            self.assertNotIn(value, text)


class HandRaiseContractTests(unittest.TestCase):
    def test_native_route_wire_docs_and_web_route(self):
        from unittest.mock import patch
        from fastapi import FastAPI
        from api_doc_catalog import OPERATIONS
        from api_doc_trip_hand_raise import NATIVE, N, T
        from api_doc_trip_merge import FEATURE_OPS
        from native_functional_policy import WIRE, FunctionalError, authorize
        from team_api_docs import build_schema
        from team_trip_routes import TeamTripRoutes
        from team_trips import TeamTrips
        from test_trip_merge_native_contracts import fixture
        rules = [row for row in WIRE['nativeRoutes'] if row['path'].endswith('/signals/candidates')]
        self.assertEqual(rules, [dict(method='POST', path=N, all=['rooms:read'], any=[])])
        self.assertTrue(authorize('POST', N.format(id='a' * 32), frozenset({'rooms:read'})))
        with self.assertRaises(FunctionalError):
            authorize('POST', N.format(id='a' * 32), frozenset({'rooms:interact'}))
        with self.assertRaises(FunctionalError):
            authorize('POST', T.format(id='a' * 32), frozenset({'rooms:read', 'rooms:interact'}))
        auth, _ = fixture()
        auth.trip_service = TeamTrips(auth)
        auth.hand_raise_service = HandRaiseCandidates(None)
        app = FastAPI()
        routers = (auth.trip_service.router(), TeamTripRoutes(auth).router())
        for router in routers:
            app.include_router(router)
        mounted = {(method.lower(), route.path) for router in routers for route in router.routes for method in route.methods}
        self.assertTrue({('post', T), ('post', N)} <= mounted)
        all_ops = dict(OPERATIONS)
        for group in FEATURE_OPS.values():
            all_ops.update(group)
        for method, path in all_ops:
            if (method, path) not in mounted:
                app.add_api_route(path, lambda: {}, methods=[method.upper()])
        with patch.dict(OPERATIONS):
            schema = build_schema(app, auth)
        models = schema['components']['schemas']
        self.assertEqual(NATIVE, {('post', N)})
        op = schema['paths'][N]['post']
        self.assertEqual(op['security'], [{'NativeMTLS': [], 'DeviceBearer': []}])
        self.assertEqual(op['x-wegoh-native-functional-purposes'], dict(all=['rooms:read'], any=[]))
        body = models[op['requestBody']['content']['application/json']['schema']['$ref'].split('/')[-1]]
        self.assertEqual(body['required'].count('functionalRevision'), 1)
        self.assertEqual(set(body['properties']), {'kind', 'location', 'destination', 'requiredFacilities', 'functionalRevision'})
        web = schema['paths'][T]['post']
        web_body = web['requestBody']['content']['application/json']['schema']
        web_body = models[web_body['$ref'].split('/')[-1]] if '$ref' in web_body else web_body
        self.assertEqual(web_body['properties']['kind']['enum'], list(hand.HAND_RAISE_KINDS))
        self.assertNotIn('functionalRevision', web_body['properties'])


if __name__ == '__main__':
    unittest.main()
