from copy import deepcopy

from api_doc_shared import entry, response, READ, BROWSER, IDENT, arr, b, n, s, nullable
from api_doc_trips import strict
from team_discovery import FACILITIES as FACILITY_KEYS
from team_trip_hand_raise import (HAND_RAISE_KINDS, STALE_SECONDS, SAME_ROAD_METERS, LEAD_GAP_METERS,
    SEARCH_STEP_METERS, SEARCH_RADIUS_METERS, HEADING_STEPS_METERS, HEADING_RADIUS_METERS, OFFICIAL_ROUTE_METERS,
    GROUP_METERS, MAX_SEARCH_CALLS, MAX_DIRECTION_CALLS, DETOUR_CANDIDATES, MAX_CANDIDATES, TIMEOUT_SECONDS,
    RATE_PER_MINUTE, MAX_DETOUR_SECONDS, TRIP_RATE_PER_MINUTE, GLOBAL_RATE_PER_MINUTE)

T = '/v1/social/trips/{id}/signals/candidates'
N = '/v1/native/trips/{id}/signals/candidates'
LAT = dict(type='number', minimum=32, maximum=39, description='대한민국 범위 위도. 저장하지 않습니다.')
LNG = dict(type='number', minimum=124, maximum=132, description='대한민국 범위 경도. 저장하지 않습니다.')
LOCATION = strict({'lat': LAT, 'lng': LNG,
    'heading': nullable(dict(type='number', minimum=0, maximum=360, description='진행 방향(북=0, 시계 방향). 선택.'))},
    '손든 사람의 현재 위치. 응답 후 버리며 로그에도 남기지 않습니다.')
LOCATION['required'] = ['lat', 'lng']
DESTINATION = strict({'lat': LAT, 'lng': LNG}, '여행 목적지. 없으면 null이며 이때 heading이 필요합니다.')
BODY_SCHEMA = strict({'kind': s('손들기 종류.', enum=list(HAND_RAISE_KINDS)), 'location': LOCATION,
    'destination': nullable(DESTINATION),
    'requiredFacilities': dict(arr(s('필수 시설 키.', enum=list(FACILITY_KEYS)), '모든 시설이 확인된 후보만 반환. 생략하면 빈 목록.'), maxItems=len(FACILITY_KEYS), uniqueItems=True)}, '후보 조회 전용. 신호를 만들지 않습니다.')
BODY_SCHEMA['required'] = ['kind', 'location']
FACILITIES = nullable(strict({key: b(label + ' 여부.') for key, label in (
    ('toilet', '화장실'), ('nursing', '수유실'), ('restaurant', '식당'), ('gasStation', '주유소'),
    ('evCharger', '전기차 충전'), ('lpg', 'LPG 충전'), ('restSpace', '휴게 공간'))}, '공식 휴게소 데이터와 짝지은 경우의 시설.'))
CANDIDATE = strict({'name': s('휴게소·졸음쉼터·매장 묶음 이름.'), 'lat': n('후보 위도.'), 'lng': n('후보 경도.'),
    'verdict': s('ahead=경로 선 ' + str(SAME_ROAD_METERS) + 'm 안, 진행 방향 오른쪽 또는 양방향. off_route=경로 선에서 '
        + str(SAME_ROAD_METERS) + 'm 초과, 고속도로 구간의 휴게소 밖 매장, 우회 ' + str(MAX_DETOUR_SECONDS) + '초 초과(표시만). heading=목적지 없이 진행 방향 앞쪽.', enum=['ahead', 'off_route', 'heading']),
    'label': s('표시 문구. 모든 차 앞쪽 / 경로 벗어남 / 들르면 +N분 / 앞쪽 · Nkm.'),
    'fromRequesterMeters': n('경로상(heading이면 직선) 손든 차에서의 거리.'),
    'fromLeadMeters': nullable(n('경로상 가장 앞선 차에서의 거리. heading이면 null.')),
    'detourSeconds': nullable(n('상위 ' + str(DETOUR_CANDIDATES) + '곳만: 가장 뒤 차→후보→목적지와 기준 경로의 시간 차.')),
    'detourMeters': nullable(n('상위 ' + str(DETOUR_CANDIDATES) + '곳만: 거리 차.')),
    'routeName': nullable(s('공식 원자료의 노선명. 확인할 수 없으면 null.', maxLength=100)),
    'direction': nullable(s('공식 원자료의 방향 원문. 실제 진입 가능성 보장이 아니며 없으면 null.', maxLength=80)),
    'candidateReceipt': nullable(s('ahead 후보 선택의 서버 인증 영수증. 계정·여행·revision·종류·장소를 바인딩하며300초 유효. 신호 생성 JSON 본문으로만 전달합니다.', maxLength=2048, pattern='^[A-Za-z0-9_-]+$')),
    'facilities': FACILITIES, 'source': s('official=공식 휴게소 데이터와 짝지음, kakao=카카오 검색만.', enum=['official', 'kakao'])},
    '진행 방향 왼쪽(양방향 제외)은 거리와 상관없이, 후보 구간 밖 장소도 제외합니다. 이름만 다른 같은 휴게소(300m 안)는 한 곳입니다.')
CAR = strict({'carId': nullable(IDENT), 'state': s('same_road=기준 경로 ' + str(SAME_ROAD_METERS) + 'm 안, other_road=다른 길로 가는 중(판정 제외), '
        'unknown=최근 ' + str(STALE_SECONDS) + '초 안 보고 위치 없음.', enum=['same_road', 'other_road', 'unknown']),
    'alongMeters': nullable(n('손든 차 기준 경로상 앞(+)/뒤(-) 거리. same_road가 아니면 null.'))},
    '첫 항목은 손든 차(차가 없으면 carId null). 좌표는 반환하지 않습니다.')
RESULT = strict({'basis': s('route=목적지까지 경로 기준, heading=진행 방향 기준.', enum=['route', 'heading']),
    'partial': b('호출 상한·시간 초과·일부 공급자 오류로 일부 구간만 찾았거나 우회 계산을 생략함.'),
    'candidates': arr(CANDIDATE, '최대 ' + str(MAX_CANDIDATES) + '곳. ahead 먼저, 가까운 순.'),
    'cars': arr(CAR, '보이는 차.')}, '조회 전용 후보 목록.')
RULES = ('요청자가 제공한 위치와, 이 여행의 일행에게 공유를 켠 다른 차 운전자·동승자의 최신 휴대전화 또는 차량 위치를 차 단위로 씁니다. 차단된 상대와 최근 관측이 없는 차의 좌표는 경로 계산에 쓰지 않습니다. '
    + str(STALE_SECONDS) + '초가 지난 위치는 unknown입니다. destination이 있으면 목적지에서 가장 먼(직선) 차에서 카카오 길찾기 1회로 기준 경로를 만들고, '
    '요청자가 그 경로에서 벗어나면 요청자에서 1회 다시 만듭니다. 경로 ' + str(SAME_ROAD_METERS) + 'm 안 차만 같은 길이며, 가장 앞선 차 + '
    + str(LEAD_GAP_METERS) + 'm 이후 구간을 ' + str(SEARCH_STEP_METERS) + 'm 간격·반경 ' + str(SEARCH_RADIUS_METERS)
    + 'm로 검색합니다. restroom·rest·smoking·nursing=휴게소+공식 휴게소, drowsy=졸음쉼터+공식 휴게소, hungry=FD6·CE7+휴게소(고속도로 구간은 휴게소+공식 휴게소만). '
    '고속도로 구간에서는 휴게소/졸음쉼터/만남의광장 묶음과 공식 휴게소만 ahead이고, 우회가 ' + str(MAX_DETOUR_SECONDS) + '초를 넘는 후보는 off_route(들르면 +N분)입니다. '
    '공식 휴게소는 경로 ' + str(OFFICIAL_ROUTE_METERS) + 'm 안만. 휴게소/졸음쉼터/만남의광장 이름과 ' + str(GROUP_METERS)
    + 'm로 매장을 묶고 공식 데이터와 이름·좌표로 짝지어 시설을 붙입니다. nursing은 수유실 확인된 곳만, restroom은 화장실 확인된 곳 우선. cafe는 CE7 카테고리, ev_charge·fuel은 공식 휴게소에서 해당 evCharger·gasStation 시설이 확인된 곳만 반환합니다. requiredFacilities가 있으면 공식 데이터 결합 뒤 모든 키가 true인 곳만 남기고 시설 미확인 장소는 제외합니다. '
    'destination이 없으면 heading 앞 ' + '/'.join(str(x // 1000) for x in HEADING_STEPS_METERS) + 'km 지점 반경 '
    + str(HEADING_RADIUS_METERS) + 'm만 찾습니다. 검색 ≤' + str(MAX_SEARCH_CALLS) + '회, 길찾기 ≤' + str(MAX_DIRECTION_CALLS)
    + '회, 전체 ' + str(TIMEOUT_SECONDS) + '초. 초과하면 그때까지 결과와 partial=true.')
ERRORS = ('400 DISCOVERY_FACILITY_INVALID / Invalid hand-raise kind / Invalid location / Invalid destination / Choose a destination or heading / Invalid trip fields. '
    '403 웹 CSRF 또는 차량 기능 권한 부족. 404 비멤버. 409 TRIP_STATE_CONFLICT(active 아님), v2 픽업·합류 대기·공유·드랍에서 허용, v2 여행에서 내가 운전·동승하는 참여 차가 없으면 TRIP_SIGNAL_CAR_REQUIRED, 해당 차 경로 done이면 TRIP_SIGNAL_ROUTE_FINISHED. '
    '422 CANDIDATES_ROUTE_NOT_FOUND. 429 CANDIDATES_RATE_LIMITED(분당 계정 ' + str(RATE_PER_MINUTE) + '·여행 ' + str(TRIP_RATE_PER_MINUTE) + '·전체 ' + str(GLOBAL_RATE_PER_MINUTE) + '회, Retry-After 60). '
    '502 CANDIDATES_PROVIDER_UNAVAILABLE. 503 CANDIDATES_UNAVAILABLE(키 없음)·CANDIDATES_BUSY. 504 CANDIDATES_TIMEOUT(기준 경로 전 시간 초과).')
BODY = {('post', T): BODY_SCHEMA}
NO_BODY = set()
OPS = {('post', T): entry('여행', '손들기 후보 찾기', BROWSER,
    '손들기 화면에서 종류를 고르면 호출하고, 고른 후보로 POST /signals(destination)를 보냅니다.',
    'accepted 멤버, active 여행. 이번 검색에 보낸 좌표를 사용하며 지속적인 상태·위치 공유 동의는 요구하지 않습니다. 신호·위치·후보를 저장하지 않습니다. ' + RULES,
    ERRORS + ' 웹은 CSRF. 차량은 이 경로 대신 native 경로를 씁니다. private, no-store.',
    {'200': response(RESULT, '조회 결과.')}, ['400', '401', '403', '404', '409', '413', '422', '429', '502', '503', '504'],
    example=dict(kind='restroom', location=dict(lat=37.2719, lng=126.8948, heading=205),
        destination=dict(lat=36.7697, lng=126.9318)))}
OPS[('post', T)]['errorDescriptions'] = {
    '422': '카카오 길찾기가 현재 위치에서 목적지까지 경로를 찾지 못했습니다(CANDIDATES_ROUTE_NOT_FOUND). 목적지를 확인하거나 목적지 없이 진행 방향으로 찾습니다.',
    '502': '카카오 공급자 응답이 없거나 형식이 다르거나 키를 반사했습니다(CANDIDATES_PROVIDER_UNAVAILABLE). 후보 없음으로 확정하지 말고 잠시 뒤 다시 찾습니다.',
    '504': '기준 경로를 받기 전에 전체 시간 상한을 넘었습니다(CANDIDATES_TIMEOUT). 검색 중 시간 초과는 200 partial=true로 반환합니다.'}
NATIVE = {('post', N)}
OPS[('post', N)] = deepcopy(OPS[('post', T)])
OPS[('post', N)]['prerequisites'] = '현재 Native mTLS·Bearer와 rooms:read. 웹과 같은 업무 권한.'
OPS[('post', N)]['retry'] = ERRORS + ' JSON에 현재 functionalRevision 필수. 트랜잭션 안에서 grant·목적을 재검사합니다.'
BODY[('post', N)] = deepcopy(BODY_SCHEMA)
