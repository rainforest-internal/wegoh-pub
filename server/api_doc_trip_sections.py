from copy import deepcopy
from api_doc_trips import DETAIL, CAR, strict, IDENT, LOCATION_CONSENT
from api_doc_trip_plan import DISPLAY
from api_doc_shared import arr


def apply_sections(operation, *, native):
    sections = ['route', 'location'] if native else ['route']
    operation.setdefault('parameters', []).append(dict(name='section', **{'in': 'query'}, required=False,
        schema=dict(type='string', enum=sections), description='생략하면 전체 상세. 지정하면 해당 영역만 반환하며 workspace·음악·기록 전체를 읽지 않습니다. 중복 키와 다른 값은 거절합니다.'))
    if native:
        operation['parameters'].append(dict(name='X-WegoH-Trip-Route-Contract', **{'in': 'header'}, required=False,
            schema=dict(type='string', enum=['2']), description='2를 명시한 route 영역 응답에만 routeContractVersion·routePlan 추가. 생략한 구형 차량은 기존 정확한 키 집합. 중복·다른 값 거절.'))
    car = strict({key: deepcopy(CAR['properties'][key]) for key in
        ('id', 'isMine', 'iRide', 'places', 'routeOrder', 'routeRevision', 'routeNext')}, '차별 경로만 반환. 멤버·리모컨·차량 프로필은 제외.')
    car['required'] = ['id', 'isMine', 'iRide', 'places', 'routeOrder']
    route = strict(dict(id=IDENT, revision=DETAIL['properties']['revision'], cars=arr(car, '현재 보이는 차별 경로.'),
        courses=DETAIL['properties']['courses']), 'section=route. 기존 여행 접근·차단·차별 경로 가시성을 유지합니다.')
    content = operation['responses']['200']['content']['application/json']
    choices = [content['schema'], route]
    if native:
        modern = deepcopy(route)
        modern['properties']['routeContractVersion'] = DETAIL['properties']['routeContractVersion']
        modern['required'].append('routeContractVersion')
        modern_car = modern['properties']['cars']['items']
        modern_car['properties']['ordinal'] = deepcopy(CAR['properties']['ordinal'])
        modern_car['required'].append('ordinal')
        modern_car['properties']['routePlan'] = deepcopy(CAR['properties']['routePlan'])
        modern_car['required'].append('routePlan')
        modern_car['properties']['routeStatus'] = deepcopy(CAR['properties']['routeStatus'])
        modern_car['required'].append('routeStatus')
        choices.append(modern)
        choices.append(strict(dict(id=IDENT, revision=DETAIL['properties']['revision'], locationConsent=LOCATION_CONSENT,
            display=DISPLAY), 'section=location. display에는 현재 동행 차량 위치 요약만 있으며 music/metrics는 null, timeline은 빈 배열입니다.'))
    content['schema'] = dict(oneOf=choices)
